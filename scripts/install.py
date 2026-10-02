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
CONTROLLER_DOWNLOADS = 'https://github.com/Kasempiternal/agentcontroller/releases'
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


def acquisition_result(document, *, destination=None, dry_run=False):
    """Validate the acquisition helper's public contract before registration."""
    if (not isinstance(document, dict) or 'command' not in document
            or document.get('status') not in ('plan', 'acquired', 'reused', 'pending')
            or not isinstance(document.get('provenance'), dict)):
        raise InstallError('AgentController acquisition returned invalid metadata; no registration was changed.')
    command = document.get('command')
    if command is not None:
        if not isinstance(command, str) or not Path(command).is_absolute():
            raise InstallError('AgentController acquisition must return an absolute local launcher path.')
        path = guard_path(command, regular=True)
        if destination is not None and not path.is_relative_to(destination):
            raise InstallError('AgentController acquisition returned a launcher outside its destination.')
        if not dry_run:
            if not path.is_file() or document['status'] not in ('acquired', 'reused'):
                raise InstallError('AgentController acquisition did not produce a verified launcher.')
            digest = document['provenance'].get('binarySha256')
            if not isinstance(digest, str) or not re.fullmatch('[0-9a-fA-F]{64}', digest):
                raise InstallError('AgentController launcher provenance has no valid SHA256 digest.')
            with path.open('rb') as handle:
                actual = hashlib.file_digest(handle, 'sha256').hexdigest()
            if actual != digest.lower():
                raise InstallError('AgentController launcher differs from its recorded SHA256; registration refused.')
    elif document['status'] not in ('plan', 'pending'):
        raise InstallError('AgentController acquisition produced no launcher; registration refused.')
    public_provenance_keys = {'schema', 'owner', 'platform', 'source', 'commit', 'runtime', 'version',
                              'license', 'method', 'archiveSha256', 'binarySha256'}
    public = {key: document[key] for key in ('status', 'command', 'next') if key in document}
    # The helper owns its full runtime inventory. Do not duplicate thousands of
    # per-file hashes into the profile receipt or novice-facing installer JSON.
    public['provenance'] = {key: value for key, value in document['provenance'].items() if key in public_provenance_keys}
    return public


def request_acquisition(provider, destination, *, dry_run):
    try:
        return acquisition_result(provider(destination, dry_run=dry_run), destination=destination, dry_run=dry_run)
    except InstallError:
        raise
    except (ValueError, OSError, RuntimeError, TypeError, KeyError) as exc:
        import setup_agentcontroller
        safe_error = getattr(setup_agentcontroller, 'AcquisitionError', ())
        if isinstance(exc, safe_error):
            raise InstallError(str(exc)) from exc
        raise InstallError('AgentController acquisition failed; private diagnostics withheld. Check its prerequisites and retained acquisition directory before retrying.') from exc


def existing_controller_acquisition(config):
    current = config.get('mcp_servers', {}).get(SERVER)
    if (not current or set(current) - {'command', 'args', 'enabled', 'startup_timeout_sec', 'tool_timeout_sec'}
            or not isinstance(current.get('command'), str) or current.get('args') or current.get('enabled') is False):
        raise InstallError('Existing AgentController needs review: --with-agentcontroller requires an enabled simple local launcher and never replaces another registration.')
    command = guard_path(Path(os.path.abspath(Path(current['command']).expanduser())), regular=True)
    if not command.is_file():
        raise InstallError('The registered AgentController launcher is missing; review it before acquisition.')
    with command.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    return {'status': 'reused', 'command': str(command),
            'provenance': {'method': 'existing-registration', 'binarySha256': digest}}


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


def install(repo, home, cli, *, dry_run=False, agentcontroller_command=None, replace_cas=False, runtime_check=None,
            with_agentcontroller=False, agentcontroller_dir=None, acquisition_provider=None):
    if with_agentcontroller and agentcontroller_command:
        raise InstallError('Choose --with-agentcontroller or --agentcontroller-command, not both.')
    if agentcontroller_dir is not None and not with_agentcontroller:
        raise InstallError('--agentcontroller-dir requires --with-agentcontroller.')
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
    acquisition = None
    acquire_required = False
    destination = None
    if with_agentcontroller:
        destination = guard_path(Path(os.path.abspath(Path(agentcontroller_dir).expanduser()))
                                 if agentcontroller_dir is not None else home / 'tools/agentcontroller')
        if SERVER in initial.get('mcp_servers', {}):
            acquisition = existing_controller_acquisition(initial)
            controller = controller_registration(initial, acquisition['command'])
            acquire_required = Path(acquisition['command']).is_relative_to(destination)
        else:
            acquire_required = True
    known_markets = marketplaces(cli)
    market = known_markets.get(MARKETPLACE)
    if market and not same_path(market.get('root', ''), repo):
        raise InstallError('A different ultra-hook marketplace is registered; it will not be replaced.')
    installed = plugin_catalog(cli).get(PLUGIN) if market else None
    if installed and installed.get('version') != version:
        raise InstallError('A different Ultra Hook version is installed. Uninstall the owned installation and review the new version before installing it.')
    if acquire_required:
        if acquisition_provider is None:
            from setup_agentcontroller import acquire
            acquisition_provider = acquire
        acquisition = request_acquisition(acquisition_provider, destination, dry_run=True)
        if controller['registered']:
            if not acquisition['command'] or not same_path(acquisition['command'], controller['command']):
                raise InstallError('Managed AgentController provenance does not match the existing registration; no replacement is allowed.')
        else:
            controller = {'registered': False, 'add': acquisition['command'] is not None, 'command': acquisition['command']}
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
    if acquisition is not None:
        plan['agentcontroller']['acquisition'] = acquisition
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
        terminal_receipt = (old_receipt.get('plugin') == PLUGIN and old_receipt.get('uninstalled') is True
                            and all(old_receipt.get(key) is False for key in
                                    ('createdPlugin', 'createdMarketplace', 'createdMcp', 'disabledCas')))
        if receipt_bytes is not None and not terminal_receipt and (
                old_receipt.get('plugin') != PLUGIN or not old_receipt.get('repo')
                or not same_path(old_receipt['repo'], repo)):
            raise InstallError('Existing installation receipt belongs to a different source; refusing to reuse it.')
        if terminal_receipt:
            write_private(transaction / 'receipt.json', receipt_bytes, expected=None)
            # A completed uninstall has no ownership to carry into a new
            # installation, even if its source directory happens to be the same.
            old_receipt = {}
        owned = {'plugin': bool(old_receipt.get('createdPlugin')) or not bool(installed),
                 'marketplace': bool(old_receipt.get('createdMarketplace')) or not bool(market),
                 'mcp': bool(old_receipt.get('createdMcp')) or controller['add']}
        completed = []
        expected_bytes = baseline
        try:
            if acquire_required:
                acquired = request_acquisition(acquisition_provider, destination, dry_run=False)
                if controller['registered'] and (not acquired['command'] or not same_path(acquired['command'], controller['command'])):
                    raise InstallError('Acquired AgentController differs from the existing registration; replacement refused.')
                acquisition = acquired
                plan['agentcontroller']['acquisition'] = acquired
                actions = [action for action in actions if action[:2] != ['mcp', 'add']]
                if not controller['registered']:
                    controller = {'registered': False, 'add': acquired['command'] is not None, 'command': acquired['command']}
                    owned['mcp'] = bool(old_receipt.get('createdMcp')) or controller['add']
                    if controller['add']:
                        actions.append(['mcp', 'add', SERVER, '--', controller['command']])
                plan['commands'] = [cli.prefix + action for action in actions]
                plan['agentcontroller']['willRegister'] = controller['add']
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
                            if (agentcontroller_command or with_agentcontroller and controller['command']) and runtime_check is runtime_metadata else runtime_check(cli, repo))
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
            if acquisition is not None:
                receipt['agentcontrollerAcquisition'] = acquisition
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
            acquisition_hint = (' AgentController acquisition files were retained; inspect them before retrying.'
                                if acquire_required else '')
            acquisition_reason = (' Reason: ' + str(exc) if acquire_required and isinstance(exc, InstallError) else '')
            raise InstallError('Installation failed; rollback attempted. Backup: ' + str(transaction) + acquisition_hint +
                               acquisition_reason +
                               ('. ' + '; '.join(errors) if errors else '')) from exc


def action_description(command):
    labels = {('plugin', 'marketplace', 'add'): 'Register the local Ultra Hook marketplace.',
              ('plugin', 'marketplace', 'remove'): 'Remove the owned Ultra Hook marketplace registration.',
              ('plugin', 'add'): 'Install or enable Ultra Hook.',
              ('plugin', 'remove'): 'Remove the owned Ultra Hook plugin registration.',
              ('mcp', 'add'): 'Register the supplied AgentController launcher.',
              ('mcp', 'remove'): 'Remove the owned AgentController MCP registration.'}
    for tokens, label in labels.items():
        if any(tuple(command[index:index + len(tokens)]) == tokens for index in range(len(command))):
            return label
    return 'Apply an owned registration change.'


def runtime_guidance(runtime):
    if runtime.get('hooksReady') and runtime.get('skillsReady'):
        return ['Hooks: 5/5 trusted; both skills are available.',
                'Next: ask Codex to use the Ultra Hook skill for your task.']
    if runtime.get('hookDefinitionsMatch') is False or runtime.get('metadataErrors'):
        return ['Runtime definitions could not be verified. Compare the installed package before granting hook trust.',
                'Next: run python -B scripts/doctor.py, reusing your profile and CLI options.']
    if runtime.get('hookDefinitionsMatch') and runtime.get('hookCount') == 5 and not runtime.get('hooksReady'):
        return ['Hook trust is pending. In Codex, open /hooks and review the five Ultra Hook definitions.',
                'Next: run python -B scripts/doctor.py after your review, reusing your profile and CLI options.']
    return ['Runtime verification is pending.', 'Next: run python -B scripts/doctor.py, reusing your profile and CLI options.']


def human_result(operation, result):
    """Render only the existing safe result fields; no new inspection/actions."""
    if result.get('status') == 'error':
        next_step = ('Check the Codex CLI/profile setup in README.md, then rerun doctor.' if operation == 'doctor'
                     else 'Review the reported issue; use --dry-run to inspect the plan before retrying.')
        return 'Error: ' + result['message'] + '\nNext: ' + next_step + '\nKeep the same profile and CLI options when retrying.'
    if result.get('status') == 'plan':
        lines = ['Ultra Hook ' + ('installation' if operation == 'install' else 'removal') + ' plan']
        if result.get('codexHome'):
            lines.append('Profile: ' + result['codexHome'])
        commands = result.get('commands', [])
        lines.extend(f'{index}. {action_description(command)}' for index, command in enumerate(commands, 1))
        if not commands:
            lines.append('No registration changes are needed.')
        if result.get('restoreCas'):
            lines.append('Restore CAS if this installation disabled it.')
        if result.get('replaceCasRequested') and result.get('casDetected'):
            lines.append('CAS migration requested; disabling CAS requires verified runtime definitions and trusted hooks.')
        acquisition = result.get('agentcontroller', {}).get('acquisition')
        if acquisition:
            lines.append('AgentController acquisition: ' + acquisition['status'] + '; this plan does not fetch or build anything.')
            if acquisition.get('next'):
                lines.append('AgentController next step: ' + acquisition['next'])
        lines.append('Plan only; no changes made.')
        lines.append(f'Next: rerun scripts/{operation}.py with the same options, without --dry-run.')
        return '\n'.join(lines)
    if operation == 'uninstall':
        return 'Ultra Hook cleanup completed.\n' + result['message']
    if operation == 'install':
        lines = ['Ultra Hook ' + str(result['version']) + ' is installed and enabled.',
                 'Profile: ' + result['codexHome']]
        if not result.get('commands'):
            lines.append('Already installed; no registration changes were needed.')
        lines.extend(runtime_guidance(result.get('runtime', {})))
        if result.get('migrationPending'):
            lines.append('CAS migration is pending; CAS remains enabled. Complete runtime verification and hook trust, then rerun with --replace-cas.')
        acquisition = result.get('agentcontroller', {}).get('acquisition')
        if acquisition:
            lines.append('AgentController acquisition: ' + acquisition['status'] + '.')
            if acquisition['status'] == 'pending':
                lines.append('AgentController setup is pending; the combined installation is not complete and no new MCP registration was added.')
            if acquisition.get('next'):
                lines.append('AgentController next step: ' + acquisition['next'])
        if not result.get('agentcontroller', {}).get('registered') and not result.get('agentcontroller', {}).get('willRegister'):
            lines.append('AgentController is not registered. Installation works without it; UI validation requires its setup in README.md.')
        else:
            lines.append('AgentController is registered. Registration alone does not validate UI behavior.')
        lines.append('AgentController by Kasempiternal (external dependency). Downloads: ' + CONTROLLER_DOWNLOADS)
        return '\n'.join(lines)
    runtime = result.get('runtime', {})
    lines = ['Ultra Hook: ' + ('ready' if result.get('ready') else 'needs attention'),
             'Plugin: ' + ('enabled' if result.get('enabled') else 'disabled' if result.get('installed') else 'not installed')
             + (' (version ' + str(result['version']) + ')' if result.get('version') else ''),
             f"Hooks: {runtime.get('trustedHookCount', 0)}/5 trusted; {runtime.get('hookCount', 0)} loaded.",
             f"Skills: {runtime.get('skillCount', 0)}/2 loaded" + ('; expected names verified.' if runtime.get('skillsReady') else '; verification pending.')]
    if not result.get('installed') or not result.get('enabled'):
        lines.append('Next: run python -B scripts/install.py to install or enable the plugin, reusing your profile and CLI options.')
    else:
        lines.extend(runtime_guidance(runtime))
    if result.get('uiTransportDiscovered'):
        count = runtime.get('agentcontrollerRuntime', {}).get('toolCount', 0)
        lines.append(f'AgentController: {count} tools discovered. UI behavior has not been tested.')
    elif result.get('agentcontrollerCheckRequested'):
        lines.append('AgentController transport was not discovered. Check its setup and registered launcher; UI behavior has not been tested.')
    elif result.get('agentcontroller', {}).get('registered'):
        lines.append('AgentController is registered; transport was not checked. To opt in: python -B scripts/doctor.py --check-agentcontroller, reusing your profile, CLI and --cwd options.')
    else:
        lines.append('AgentController is not registered. UI validation requires its setup in README.md.')
    lines.append('Reuse any --codex-home, --codex-command and --cwd options when rerunning doctor; do not switch profiles accidentally.')
    lines.append('AgentController by Kasempiternal (external dependency). Downloads: ' + CONTROLLER_DOWNLOADS)
    return '\n'.join(lines)


def emit_result(operation, result, *, json_output=False, stream=None):
    print(json.dumps(result, indent=2) if json_output else human_result(operation, result), file=stream or sys.stdout)


class OutputParser(argparse.ArgumentParser):
    def error(self, message):
        # Do not echo invalid arguments: a mistyped argument can contain private
        # text. Preserve argparse's exit code while keeping automation JSON clean.
        if '--json' in sys.argv[1:]:
            self.exit(2, json.dumps({'status':'error','message':'Invalid command-line options. Run with --help.'}) + '\n')
        super().error('Invalid command-line options. Run with --help.')


def parser():
    result = OutputParser(description=__doc__, epilog='AgentController is by Kasempiternal. Downloads: ' + CONTROLLER_DOWNLOADS)
    result.add_argument('--dry-run', action='store_true', help='Read-only plan; no installation.')
    result.add_argument('--json', action='store_true', help='Emit safe JSON only, for automation (default: readable summary).')
    result.add_argument('--codex-home', help='Explicit Codex profile directory (use synthetic directories for tests).')
    result.add_argument('--codex-command', help='Existing Codex executable path.')
    result.add_argument('--agentcontroller-command', help='Existing AgentController stdio launcher; never overwritten.')
    result.add_argument('--with-agentcontroller', action='store_true', help='Explicitly acquire and register AgentController, or reuse an existing reviewed local registration.')
    result.add_argument('--agentcontroller-dir', help='Acquisition directory; default CODEX_HOME/tools/agentcontroller. Requires --with-agentcontroller.')
    result.add_argument('--replace-cas', action='store_true', help='Disable CAS only after 5 trusted new hooks and 2 skills are verified.')
    return result


def main():
    args = parser().parse_args()
    try:
        if args.with_agentcontroller and not args.dry_run and not args.json:
            print('Preparing optional AgentController setup; source builds can take several minutes.', file=sys.stderr)
        home = codex_home(args.codex_home)
        result = install(REPO, home, CLI(home, args.codex_command), dry_run=args.dry_run,
                         agentcontroller_command=args.agentcontroller_command, replace_cas=args.replace_cas,
                         with_agentcontroller=args.with_agentcontroller, agentcontroller_dir=args.agentcontroller_dir)
        emit_result('install', result, json_output=args.json)
        return 0
    except InstallError as exc:
        emit_result('install', {'status': 'error', 'message': str(exc)}, json_output=args.json, stream=sys.stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        emit_result('install', {'status': 'error', 'message': 'Installation failed; private diagnostics withheld.'}, json_output=args.json, stream=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
