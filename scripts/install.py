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
import sys
import tomllib

PLUGIN = 'ultra-hook@ultra-hook'
MARKETPLACE = 'ultra-hook'
CAS = 'cas@claude-agent-system'
SERVER = 'agentcontroller'
REPO = Path(__file__).resolve().parents[1]


class InstallError(RuntimeError):
    pass


def codex_home(value=None):
    return Path(value or os.environ.get('CODEX_HOME') or Path.home() / '.codex').expanduser().resolve()


def load_config(home):
    path = home / 'config.toml'
    return tomllib.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}


def write_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.ultra-hook-tmp')
    with temp.open('xb') as handle:
        handle.write(data)
    try:
        temp.chmod(0o600)
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


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

    def run(self, args, *, json_output=False, timeout=90):
        try:
            result = subprocess.run(self.prefix + list(args), shell=False, capture_output=True,
                                    text=True, encoding='utf-8', errors='replace',
                                    timeout=timeout, env=self.env, cwd=REPO)
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
    result = subprocess.run([node, '--version'], shell=False, capture_output=True, text=True, timeout=15)
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
    return {entry.get('pluginId'): entry for entry in document.get('installed', [])}


def marketplaces(cli):
    document = cli.run(['plugin', 'marketplace', 'list', '--json'], json_output=True)
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
    original = path.read_text(encoding='utf-8-sig')
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
    write_private(path, updated.encode('utf-8'))


@contextmanager
def installation_lock(home):
    state = home / '.ultra-hook'
    state.mkdir(parents=True, exist_ok=True)
    lock = state / 'install.lock'
    try:
        with lock.open('x', encoding='utf-8') as handle:
            handle.write(str(os.getpid()))
    except FileExistsError as exc:
        raise InstallError('An installer lock exists. Verify the previous process has ended before removing that lock.') from exc
    try:
        yield state
    finally:
        lock.unlink(missing_ok=True)


def install(repo, home, cli, *, dry_run=False, agentcontroller_command=None, replace_cas=False, runtime_check=None):
    repo = Path(repo).resolve()
    version = check_package(repo)
    requirements = prerequisites(cli)
    initial = load_config(home)
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
        baseline = config_file.read_bytes() if config_file.exists() else None
        transaction = state / 'backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        transaction.mkdir(parents=True)
        if baseline is not None:
            write_private(transaction / 'config.toml', baseline)
        previous_receipt = state / 'receipt.json'
        old_receipt = json.loads(previous_receipt.read_text()) if previous_receipt.exists() else {}
        owned = {'plugin': bool(old_receipt.get('createdPlugin')) or not bool(installed),
                 'marketplace': bool(old_receipt.get('createdMarketplace')) or not bool(market),
                 'mcp': bool(old_receipt.get('createdMcp')) or controller['add']}
        completed = []
        expected_bytes = baseline
        try:
            for action in actions:
                cli.run(action, json_output=action[-1] == '--json')
                completed.append(action)
                expected_bytes = config_file.read_bytes() if config_file.exists() else None
            effective = plugin_catalog(cli).get(PLUGIN)
            if not effective or not effective.get('enabled') or effective.get('version') != version:
                raise InstallError('Ultra Hook was not verified installed/enabled at the requested version.')
            if protected(load_config(home), add_mcp=controller['add']) != protected(initial, add_mcp=controller['add']):
                raise InstallError('The CLI changed an unrelated preference; rolling back this transaction.')
            try:
                metadata = runtime_check(cli, repo)
            except (InstallError, OSError):
                metadata = {'trustedHookCount': 0, 'skillCount': 0, 'hooksReady': False,
                            'trustPending': True, 'diagnostic': 'Runtime metadata unavailable; inspect Codex /hooks before migration.'}
            migration_pending = bool(replace_cas and cas_enabled)
            cas_disabled = bool(old_receipt.get('disabledCas'))
            if (replace_cas and cas_enabled and metadata.get('hookCount') == 5
                    and metadata.get('trustedHookCount') == 5 and metadata.get('skillCount') == 2
                    and metadata.get('hooksReady')):
                set_plugin_enabled(home, CAS, False)
                expected_bytes = config_file.read_bytes()
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
            write_private(previous_receipt, json.dumps(receipt, indent=2).encode('utf-8'))
            return {'status': 'installed', **plan, 'runtime': metadata, 'migrationPending': migration_pending,
                    'backup': str(transaction)}
        except Exception as exc:
            # Roll back only registrations newly introduced by this transaction.
            errors = []
            for action in reversed(completed):
                inverse = None
                if action[:2] == ['mcp', 'add']:
                    inverse = ['mcp', 'remove', SERVER]
                elif action[:2] == ['plugin', 'add'] and not installed:
                    inverse = ['plugin', 'remove', PLUGIN, '--json']
                elif action[:3] == ['plugin', 'marketplace', 'add'] and not market:
                    inverse = ['plugin', 'marketplace', 'remove', MARKETPLACE, '--json']
                if inverse:
                    try:
                        cli.run(inverse, json_output=inverse[-1] == '--json')
                        expected_bytes = config_file.read_bytes() if config_file.exists() else None
                    except InstallError:
                        errors.append('registration rollback incomplete')
            current_bytes = config_file.read_bytes() if config_file.exists() else None
            unchanged_outside_transaction = (protected(load_config(home), replace_cas=True, add_mcp=controller['add'])
                                             == protected(initial, replace_cas=True, add_mcp=controller['add']))
            if current_bytes == expected_bytes and unchanged_outside_transaction:
                if baseline is not None:
                    write_private(config_file, baseline)
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
    except (InstallError, OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
