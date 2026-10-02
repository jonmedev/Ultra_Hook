#!/usr/bin/env python3
"""Install Ultra Hook through the official Codex plugin CLI; no model calls."""
from __future__ import annotations
import argparse
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import stat
import sys
import tempfile
import threading
import time
import tomllib

PLUGIN = 'ultra-hook@ultra-hook'
MARKETPLACE = 'ultra-hook'
CAS = 'cas@claude-agent-system'
SERVER = 'agentcontroller'
REPO = Path(__file__).resolve().parents[1]
MAX_CONFIG_BYTES = 8 * 1024 * 1024
MAX_RECEIPT_BYTES = 256 * 1024
_UNSET = object()


class InstallError(RuntimeError):
    pass


def codex_home(value=None):
    home = Path(os.path.abspath(Path(value or os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser()))
    guard_path(home)
    if home == Path(home.anchor):
        raise InstallError('Codex profile cannot be a filesystem root.')
    return home


def guard_path(path, *, regular=False):
    """Reject existing links/reparse points and multiply-linked private files.

    Rechecked at operation boundaries; this is not a sandbox against a concurrent
    attacker with the same filesystem permissions.
    """
    path = Path(os.path.abspath(path))
    for candidate in reversed((path, *path.parents)):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise InstallError('Linked/reparse filesystem paths are not supported for installer data.')
        if candidate == path and stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise InstallError('Hardlinked private files are not supported for installer data.')
        if candidate == path and regular and not stat.S_ISREG(info.st_mode):
            raise InstallError('Expected a regular installer data file.')
    return path


def private_bytes(path, *, limit=MAX_CONFIG_BYTES):
    path = guard_path(path, regular=True)
    try:
        with path.open('rb') as handle:
            info = os.fstat(handle.fileno())
            if info.st_nlink != 1 or info.st_size > limit:
                raise InstallError('Private installer data exceeds limits or is hardlinked.')
            data = handle.read(limit + 1)
    except FileNotFoundError:
        return None
    if len(data) > limit:
        raise InstallError('Private installer data exceeds its size limit.')
    guard_path(path, regular=True)
    return data


def ensure_directory(path):
    guard_path(path)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    guard_path(path)
    if not path.is_dir():
        raise InstallError('Installer directory is not a directory.')


def stop_process(process):
    """Stop the owned child and, where supported, its process tree."""
    if process.poll() is not None:
        return
    if os.name == 'nt':
        killer = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/taskkill.exe'
        if killer.is_file():
            try:
                subprocess.run([str(killer), '/PID', str(process.pid), '/T', '/F'], shell=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
    else:
        try:
            import signal
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=5)


def run_bounded(command, *, timeout=90, env=None, cwd=None, max_output=4 * 1024 * 1024):
    """Collect limited stdout/stderr without unbounded communicate buffers."""
    process = subprocess.Popen(command, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=env, cwd=cwd, start_new_session=os.name != 'nt',
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    buffers = [bytearray(), bytearray()]
    total = 0
    overflow = threading.Event()
    mutex = threading.Lock()
    def read(stream, buffer):
        nonlocal total
        try:
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                with mutex:
                    total += len(chunk)
                    if total > max_output:
                        overflow.set()
                        break
                    buffer.extend(chunk)
        except (OSError, ValueError):
            overflow.set()
    threads = [threading.Thread(target=read, args=(stream, buffer), daemon=True)
               for stream, buffer in zip((process.stdout, process.stderr), buffers)]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    try:
        while process.poll() is None or any(thread.is_alive() for thread in threads):
            if overflow.is_set():
                raise InstallError('Child process output exceeded its limit; raw output withheld.')
            if time.monotonic() >= deadline:
                raise InstallError('Child process timed out; raw output withheld.')
            overflow.wait(0.02)
        if overflow.is_set():
            raise InstallError('Child process output exceeded its limit; raw output withheld.')
        return subprocess.CompletedProcess(command, process.returncode,
                    buffers[0].decode('utf-8', errors='replace'), buffers[1].decode('utf-8', errors='replace'))
    finally:
        stop_process(process)
        for stream, thread in zip((process.stdout, process.stderr), threads):
            if not thread.is_alive():
                stream.close()


def load_config(home):
    path = home / 'config.toml'
    data = private_bytes(path)
    config = tomllib.loads(data.decode('utf-8-sig')) if data is not None else {}
    for key in ('plugins', 'mcp_servers', 'plugin_marketplaces', 'marketplaces'):
        if key in config and (not isinstance(config[key], dict)
                              or any(not isinstance(value, dict) for value in config[key].values())):
            raise InstallError('Unsupported configuration structure; private data withheld.')
    return config


def write_private(path, data, *, expected=_UNSET):
    path = guard_path(path, regular=True)
    ensure_directory(path.parent)
    descriptor, name = tempfile.mkstemp(prefix='.ultra-hook-', suffix='.tmp', dir=path.parent)
    temp = Path(name)
    identity = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        guard_path(path, regular=True)
        if expected is not _UNSET and private_bytes(path) != expected:
            raise InstallError('Installer data changed concurrently; refusing to overwrite it.')
        now = temp.lstat()
        if (now.st_dev, now.st_ino) != (identity.st_dev, identity.st_ino) or now.st_nlink != 1:
            raise InstallError('Temporary installer data was replaced; refusing to write.')
        os.replace(temp, path)
    finally:
        try:
            now = temp.lstat()
            if (now.st_dev, now.st_ino) == (identity.st_dev, identity.st_ino):
                temp.unlink()
        except FileNotFoundError:
            pass


def command_prefix(value=None):
    path = value or shutil.which('codex')
    if not path:
        raise InstallError('Codex CLI is required. Install it separately, then rerun.')
    path = Path(path).resolve()
    if path.suffix.lower() in ('.cmd', '.ps1'):
        entry = path.parent / 'node_modules/@openai/codex/bin/codex.js'
        node = shutil.which('node')
        if not entry.is_file() or not node:
            raise InstallError('Cannot safely launch this Codex shim. Provide --codex-command pointing to codex.exe.')
        return [node, str(entry)]
    if not path.is_file():
        raise InstallError('Codex executable does not exist.')
    return [str(path)]


class CLI:
    def __init__(self, home, executable=None):
        self.home = home
        self.prefix = command_prefix(executable)
        self.env = os.environ.copy()
        self.env['CODEX_HOME'] = str(home)
        self.env['DO_NOT_TRACK'] = '1'

    def run(self, args, *, json_output=False, timeout=90, cwd=REPO):
        try:
            result = run_bounded(self.prefix + list(args), timeout=timeout, env=self.env, cwd=cwd)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InstallError('Codex CLI failed or timed out; raw output withheld.') from exc
        if result.returncode:
            raise InstallError(f'Codex CLI command {args[0]} failed (exit {result.returncode}); raw output withheld.')
        if json_output:
            try:
                return json.loads(result.stdout)
            except ValueError as exc:
                raise InstallError('Codex CLI returned invalid JSON; raw output withheld.') from exc
        return result.stdout


def prerequisites(cli):
    if sys.version_info < (3, 11):
        raise InstallError('Python 3.11 or newer is required.')
    node = shutil.which('node')
    if not node:
        raise InstallError('Node.js 18 or newer is required for plugin hooks.')
    result = run_bounded([node, '--version'], timeout=15, max_output=4096)
    match = re.match(r'v(\d+)\.', result.stdout.strip())
    if result.returncode or not match or int(match[1]) < 18:
        raise InstallError('Node.js 18 or newer is required.')
    for args in (['plugin', 'marketplace', 'add', '--help'], ['plugin', 'add', '--help'],
                 ['plugin', 'list', '--help'], ['plugin', 'marketplace', 'list', '--help']):
        if '--json' not in cli.run(args, timeout=15):
            raise InstallError('This Codex CLI lacks the required plugin JSON commands.')
    return {'python': '.'.join(map(str, sys.version_info[:3])), 'node': result.stdout.strip(),
            'codex': cli.run(['--version'], timeout=15).strip()}


def check_package(repo):
    marketplace = json.loads((repo / '.agents/plugins/marketplace.json').read_text(encoding='utf-8-sig'))
    plugin = json.loads((repo / 'plugins/ultra-hook/.codex-plugin/plugin.json').read_text(encoding='utf-8-sig'))
    portable = json.loads((repo / 'plugins/ultra-hook/plugin.json').read_text(encoding='utf-8-sig'))
    version = portable.get('version')
    semver = r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?'
    if (marketplace.get('name') != MARKETPLACE or plugin.get('name') != MARKETPLACE
            or portable.get('name') != MARKETPLACE or not isinstance(version, str)
            or not re.fullmatch(semver, version) or plugin.get('version') != version):
        raise InstallError('Package must contain matching ultra-hook manifests with a valid semantic version.')
    return version


def plugin_catalog(cli):
    document = cli.run(['plugin', 'list', '--marketplace', MARKETPLACE, '--json'], json_output=True)
    if (not isinstance(document, dict) or not isinstance(document.get('installed', []), list)
            or any(not isinstance(entry, dict) or not isinstance(entry.get('pluginId'), str)
                   for entry in document.get('installed', []))):
        raise InstallError('Invalid native plugin catalog; raw data withheld.')
    return {entry.get('pluginId'): entry for entry in document.get('installed', [])}


def marketplaces(cli):
    document = cli.run(['plugin', 'marketplace', 'list', '--json'], json_output=True)
    if (not isinstance(document, dict) or not isinstance(document.get('marketplaces', []), list)
            or any(not isinstance(entry, dict) or not isinstance(entry.get('name'), str)
                   for entry in document.get('marketplaces', []))):
        raise InstallError('Invalid native marketplace catalog; raw data withheld.')
    return {entry.get('name'): entry for entry in document.get('marketplaces', [])}


def same_path(first, second):
    return os.path.normcase(str(Path(first).resolve())) == os.path.normcase(str(Path(second).resolve()))


def controller_registration(config, command=None):
    current = config.get('mcp_servers', {}).get(SERVER)
    if command:
        command = Path(command).expanduser().resolve()
        if not command.is_file():
            raise InstallError('AgentController command must be an existing executable/launcher file.')
    if current is not None:
        if command and (not current.get('command') or not same_path(current['command'], command)
                        or current.get('args') or current.get('url')):
            raise InstallError('A different AgentController server is registered. It will not be overwritten.')
        return {'registered': True, 'add': False, 'command': str(command) if command else None}
    return {'registered': False, 'add': command is not None, 'command': str(command) if command else None}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode('utf-8')).hexdigest()


def protected(config, *, replace_cas=False, add_mcp=False):
    # Compare all parsed user preferences except the exact keys this installer owns.
    copied = copy.deepcopy(config)
    copied.get('plugins', {}).pop(PLUGIN, None)
    if replace_cas:
        copied.get('plugins', {}).pop(CAS, None)
    if add_mcp:
        copied.get('mcp_servers', {}).pop(SERVER, None)
    for key in ('plugins', 'mcp_servers'):
        if copied.get(key) == {}:
            copied.pop(key, None)
    # Official marketplace registration uses this dedicated registry table.
    for key in ('plugin_marketplaces', 'marketplaces'):
        if isinstance(copied.get(key), dict):
            copied[key].pop(MARKETPLACE, None)
            if not copied[key]:
                copied.pop(key)
    return copied


def set_plugin_enabled(home, identity, enabled):
    """Change one documented plugin table, preserving every other byte."""
    path = home / 'config.toml'
    original_bytes = private_bytes(path)
    if original_bytes is None:
        raise InstallError('Config disappeared; refusing to edit it.')
    original = original_bytes.decode('utf-8-sig')
    config = tomllib.loads(original)
    if identity not in config.get('plugins', {}):
        raise InstallError('Expected plugin registration is absent; refusing config surgery.')
    header = re.compile(r'^\[plugins\."' + re.escape(identity) + r'"\]\s*$', re.MULTILINE)
    found = header.search(original)
    if not found:
        raise InstallError('Plugin table uses unsupported TOML spelling; change its enabled setting through Codex UI.')
    end = re.search(r'^\[', original[found.end():], re.MULTILINE)
    stop = found.end() + end.start() if end else len(original)
    section = original[found.end():stop]
    setting = re.compile(r'^(\s*enabled\s*=\s*)(true|false)(\s*(?:#.*)?)$', re.MULTILINE)
    if not setting.search(section):
        raise InstallError('Plugin enabled setting is missing; change it through Codex UI.')
    section = setting.sub(lambda match: match[1] + str(enabled).lower() + match[3], section, count=1)
    updated = original[:found.end()] + section + original[stop:]
    expected = dict(config)
    expected['plugins'] = {key: dict(value) for key, value in config['plugins'].items()}
    expected['plugins'][identity]['enabled'] = enabled
    if tomllib.loads(updated) != expected:
        raise InstallError('Config edit changed unrelated values; refusing to write.')
    write_private(path, updated.encode('utf-8'), expected=original_bytes)


@contextmanager
def installation_lock(home):
    guard_path(home)
    state = home / '.ultra-hook'
    ensure_directory(state)
    lock = state / 'install.lock'
    guard_path(lock, regular=True)
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise InstallError('An installer lock exists. Verify the previous process has ended before removing that lock.') from exc
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        identity = os.fstat(handle.fileno())
        handle.write(str(os.getpid()))
    try:
        yield state
    finally:
        guard_path(lock, regular=True)
        try:
            current = lock.lstat()
            if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                lock.unlink()
        except FileNotFoundError:
            pass


def install(repo, home, cli, *, dry_run=False, agentcontroller_command=None, replace_cas=False, runtime_check=None):
    home = guard_path(home)
    guard_path(home / '.ultra-hook')
    repo = Path(repo).resolve()
    version = check_package(repo)
    requirements = prerequisites(cli)
    initial_bytes = private_bytes(home / 'config.toml')
    initial = load_config(home)
    if private_bytes(home / 'config.toml') != initial_bytes:
        raise InstallError('Config changed during planning; rerun.')
    controller = controller_registration(initial, agentcontroller_command)
    known_markets = marketplaces(cli)
    market = known_markets.get(MARKETPLACE)
    if market and not same_path(market.get('root', ''), repo):
        raise InstallError('A different ultra-hook marketplace is registered; it will not be replaced.')
    installed = plugin_catalog(cli).get(PLUGIN) if market else None
    if installed and installed.get('version') != version:
        raise InstallError('A different Ultra Hook version is installed. Uninstall the owned installation and review the new version before installing it.')
    cas_enabled = initial.get('plugins', {}).get(CAS, {}).get('enabled', False)
    actions = []
    if not market:
        actions.append(['plugin', 'marketplace', 'add', str(repo), '--json'])
    if not installed or not installed.get('enabled'):
        actions.append(['plugin', 'add', PLUGIN, '--json'])
    if controller['add']:
        actions.append(['mcp', 'add', SERVER, '--', controller['command']])
    plan = {'plugin': PLUGIN, 'version': version, 'codexHome': str(home), 'prerequisites': requirements,
            'commands': [cli.prefix + action for action in actions], 'casDetected': bool(cas_enabled),
            'replaceCasRequested': replace_cas, 'hookTrust': 'review current definitions in Codex /hooks',
            'agentcontroller': {'registered': controller['registered'], 'willRegister': controller['add']}}
    if dry_run:
        return {'status': 'plan', **plan}
    from doctor import runtime_metadata
    runtime_check = runtime_check or runtime_metadata
    with installation_lock(home) as state:
        config_file = home / 'config.toml'
        baseline = private_bytes(config_file)
        if baseline != initial_bytes:
            raise InstallError('Config changed since planning; rerun without overwriting it.')
        locked_market = marketplaces(cli).get(MARKETPLACE)
        locked_installed = plugin_catalog(cli).get(PLUGIN) if locked_market else None
        if locked_market != market or locked_installed != installed:
            raise InstallError('Plugin registrations changed since planning; rerun.')
        transaction = state / 'backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        ensure_directory(transaction)
        if baseline is not None:
            write_private(transaction / 'config.toml', baseline)
        previous_receipt = state / 'receipt.json'
        receipt_bytes = private_bytes(previous_receipt, limit=MAX_RECEIPT_BYTES)
        old_receipt = json.loads(receipt_bytes) if receipt_bytes is not None else {}
        if not isinstance(old_receipt, dict):
            raise InstallError('Invalid installation receipt; private data withheld.')
        if old_receipt and (old_receipt.get('plugin') != PLUGIN or not old_receipt.get('repo')
                            or not same_path(old_receipt['repo'], repo)):
            raise InstallError('Existing installation receipt belongs to a different source; refusing to reuse it.')
        owned = {'plugin': bool(old_receipt.get('createdPlugin')) or not bool(installed),
                 'marketplace': bool(old_receipt.get('createdMarketplace')) or not bool(market),
                 'mcp': bool(old_receipt.get('createdMcp')) or controller['add']}
        completed = []
        expected_bytes = baseline
        try:
            for action in actions:
                if private_bytes(config_file) != expected_bytes:
                    raise InstallError('Config changed concurrently before a CLI mutation; refusing to continue.')
                # A CLI may commit before returning failure/timeout. Record the
                # attempt first; rollback verifies current ownership separately.
                completed.append(action)
                cli.run(action, json_output=action[-1] == '--json')
                expected_bytes = private_bytes(config_file)
            effective = plugin_catalog(cli).get(PLUGIN)
            if not effective or not effective.get('enabled') or effective.get('version') != version:
                raise InstallError('Ultra Hook was not verified installed/enabled at the requested version.')
            if protected(load_config(home), add_mcp=controller['add']) != protected(initial, add_mcp=controller['add']):
                raise InstallError('The CLI changed an unrelated preference; rolling back this transaction.')
            try:
                metadata = (runtime_check(cli, repo, check_agentcontroller=True)
                            if agentcontroller_command and runtime_check is runtime_metadata else runtime_check(cli, repo))
            except (InstallError, OSError):
                metadata = {'trustedHookCount': 0, 'skillCount': 0, 'hooksReady': False,
                            'trustPending': True, 'diagnostic': 'Runtime metadata unavailable; inspect Codex /hooks before migration.'}
            migration_pending = bool(replace_cas and cas_enabled)
            cas_disabled = bool(old_receipt.get('disabledCas'))
            if (replace_cas and cas_enabled and metadata.get('hookCount') == 5
                    and metadata.get('trustedHookCount') == 5 and metadata.get('skillCount') == 2 and metadata.get('skillsReady')
                    and metadata.get('hooksReady')):
                set_plugin_enabled(home, CAS, False)
                expected_bytes = private_bytes(config_file)
                migration_pending = False
                cas_disabled = True
            if protected(load_config(home), replace_cas=cas_disabled, add_mcp=controller['add']) != protected(initial, replace_cas=cas_disabled, add_mcp=controller['add']):
                raise InstallError('An unrelated setting changed; rolling back.')
            receipt = {'plugin': PLUGIN, 'version': version, 'repo': str(repo), 'backup': str(transaction),
                       'createdPlugin': owned['plugin'], 'createdMarketplace': owned['marketplace'],
                       'createdMcp': owned['mcp'], 'mcpCommand': controller['command'] or old_receipt.get('mcpCommand'),
                       'mcpFingerprint': (fingerprint(load_config(home).get('mcp_servers', {}).get(SERVER))
                                          if controller['add'] else old_receipt.get('mcpFingerprint')),
                       'disabledCas': cas_disabled, 'migrationPending': migration_pending,
                       'runtime': metadata}
            write_private(previous_receipt, json.dumps(receipt, indent=2).encode('utf-8'), expected=receipt_bytes)
            return {'status': 'installed', **plan, 'runtime': metadata, 'migrationPending': migration_pending,
                    'backup': str(transaction)}
        except Exception as exc:
            # Roll back only registrations newly introduced by this transaction.
            errors = []
            for action in reversed(completed):
                inverse = None
                try:
                    guard_path(home)
                    private_bytes(config_file)
                    if action[:2] == ['mcp', 'add']:
                        current_server = load_config(home).get('mcp_servers', {}).get(SERVER)
                        if current_server and (current_server.get('command') == controller['command']
                                and not current_server.get('args') and not current_server.get('url')
                                and not (set(current_server) - {'command', 'args', 'enabled'})):
                            inverse = ['mcp', 'remove', SERVER]
                        elif current_server:
                            errors.append('MCP registration changed; retained for review')
                    elif action[0] == 'plugin':
                        current_market = marketplaces(cli).get(MARKETPLACE)
                        source_matches = current_market and same_path(current_market.get('root', ''), repo)
                        if action[:2] == ['plugin', 'add'] and not installed:
                            current_plugin = plugin_catalog(cli).get(PLUGIN) if current_market else None
                            if source_matches and current_plugin and current_plugin.get('version') == version:
                                inverse = ['plugin', 'remove', PLUGIN, '--json']
                            elif current_plugin:
                                errors.append('plugin ownership changed; retained for review')
                        elif action[:3] == ['plugin', 'marketplace', 'add'] and not market:
                            if source_matches:
                                inverse = ['plugin', 'marketplace', 'remove', MARKETPLACE, '--json']
                            elif current_market:
                                errors.append('marketplace source changed; retained for review')
                except (InstallError, OSError, ValueError, TypeError):
                    errors.append('rollback ownership could not be verified; retained for review')
                if inverse:
                    try:
                        cli.run(inverse, json_output=inverse[-1] == '--json')
                        expected_bytes = private_bytes(config_file)
                    except InstallError:
                        errors.append('registration rollback incomplete')
            current_bytes = private_bytes(config_file)
            unchanged_outside_transaction = (protected(load_config(home), replace_cas=locals().get('cas_disabled', False), add_mcp=controller['add'])
                                             == protected(initial, replace_cas=locals().get('cas_disabled', False), add_mcp=controller['add']))
            if not errors and current_bytes == expected_bytes and unchanged_outside_transaction:
                if baseline is not None:
                    write_private(config_file, baseline, expected=current_bytes)
                elif config_file.exists():
                    config_file.unlink()
            else:
                errors.append('unrelated config changed; backup retained without overwriting it')
            raise InstallError('Installation failed; rollback attempted. Backup: ' + str(transaction) +
                               ('. ' + '; '.join(errors) if errors else '')) from exc


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--dry-run', action='store_true', help='Read-only plan; no installation.')
    result.add_argument('--codex-home', help='Explicit Codex profile directory (use synthetic directories for tests).')
    result.add_argument('--codex-command', help='Existing Codex executable path.')
    result.add_argument('--agentcontroller-command', help='Existing AgentController stdio launcher; never overwritten.')
    result.add_argument('--replace-cas', action='store_true', help='Disable CAS only after 5 trusted new hooks and 2 skills are verified.')
    return result


def main():
    args = parser().parse_args()
    try:
        home = codex_home(args.codex_home)
        result = install(REPO, home, CLI(home, args.codex_command), dry_run=args.dry_run,
                         agentcontroller_command=args.agentcontroller_command, replace_cas=args.replace_cas)
        print(json.dumps(result, indent=2))
        return 0
    except InstallError as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}), file=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print(json.dumps({'status': 'error', 'message': 'Installation failed; private diagnostics withheld.'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
