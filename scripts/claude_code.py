#!/usr/bin/env python3
"""Install Ultra Hook into Claude Code through its official plugin CLI; no model calls."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from install import (InstallError, MARKETPLACE, MAX_RECEIPT_BYTES, PLUGIN, REPO, SERVER, OutputParser, check_package,
                     ensure_directory, guard_path, private_bytes, run_bounded, same_path, write_private)

SCOPE = 'user'


def claude_home(value=None):
    home = guard_path(Path(os.path.abspath(Path(value or os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude').expanduser())))
    if home == Path(home.anchor):
        raise InstallError('Claude Code profile cannot be a filesystem root.')
    return home


def command_prefix(value=None):
    """Return the launch command, or None when Claude Code is not installed."""
    path = value or shutil.which('claude')
    if not path:
        return None
    path = Path(path).resolve()
    if path.suffix.lower() in ('.cmd', '.ps1'):
        # The npm shim only forwards to the packaged native executable.
        native = path.parent / 'node_modules/@anthropic-ai/claude-code/bin/claude.exe'
        if not native.is_file():
            raise InstallError('Cannot safely launch this Claude Code shim. Provide --claude-command pointing to the claude executable.')
        return [str(native)]
    if not path.is_file():
        raise InstallError('Claude Code executable does not exist.')
    return [str(path)]


class ClaudeCLI:
    def __init__(self, home, executable=None, *, explicit_home=False):
        prefix = command_prefix(executable)
        if prefix is None:
            raise InstallError('Claude Code CLI is required for this step. Install it separately, then rerun.')
        self.home = home
        self.prefix = prefix
        self.env = os.environ.copy()
        # Setting the variable moves Claude Code's user state file, so export it
        # only for a profile the caller chose; the default stays implicit.
        if explicit_home:
            self.env['CLAUDE_CONFIG_DIR'] = str(home)

    def run(self, args, *, json_output=False, timeout=90, check=True):
        try:
            result = run_bounded(self.prefix + list(args), timeout=timeout, env=self.env, cwd=REPO)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise InstallError('Claude Code CLI failed or timed out; raw output withheld.') from exc
        if not check:
            return result.returncode
        if result.returncode:
            raise InstallError(f'Claude Code CLI command {args[0]} failed (exit {result.returncode}); raw output withheld.')
        if json_output:
            try:
                return json.loads(result.stdout)
            except ValueError as exc:
                raise InstallError('Claude Code CLI returned invalid JSON; raw output withheld.') from exc
        return result.stdout


def check_claude_package(repo):
    version = check_package(repo)
    manifest = json.loads((repo / '.claude-plugin/plugin.json').read_text(encoding='utf-8-sig'))
    market = json.loads((repo / '.claude-plugin/marketplace.json').read_text(encoding='utf-8-sig'))
    if (manifest.get('name') != MARKETPLACE or manifest.get('version') != version
            or market.get('name') != MARKETPLACE):
        raise InstallError('Package must contain matching Claude Code manifests for this version.')
    return version


def catalog(cli, args, key):
    document = cli.run(args + ['--json'], json_output=True)
    if not isinstance(document, list) or any(not isinstance(entry, dict) or not isinstance(entry.get(key), str)
                                             for entry in document):
        raise InstallError('Invalid Claude Code plugin catalog; raw data withheld.')
    return document


def marketplace(cli):
    return next((entry for entry in catalog(cli, ['plugin', 'marketplace', 'list'], 'name')
                 if entry['name'] == MARKETPLACE), None)


def plugin(cli):
    entries = [entry for entry in catalog(cli, ['plugin', 'list'], 'id') if entry['id'] == PLUGIN]
    if any(entry.get('scope') != SCOPE for entry in entries):
        raise InstallError('Ultra Hook is installed in a Claude Code project scope; manage that installation with claude plugin.')
    return entries[0] if entries else None


def controller_registered(cli):
    # The native lookup can start a registered server for its health check, so it
    # runs only when the caller explicitly supplies a controller to register.
    return cli.run(['mcp', 'get', SERVER], check=False, timeout=60) == 0


def load_receipt(home):
    data = private_bytes(home / '.ultra-hook/receipt.json', limit=MAX_RECEIPT_BYTES)
    receipt = json.loads(data) if data is not None else {}
    if not isinstance(receipt, dict) or (receipt and receipt.get('plugin') != PLUGIN):
        raise InstallError('Invalid Claude Code installation receipt; private data withheld.')
    return receipt, data


def plan_actions(repo, cli, version, controller_command):
    market = marketplace(cli)
    if market and (market.get('source') != 'directory' or not same_path(market.get('path', ''), repo)):
        raise InstallError('A different ultra-hook marketplace is registered in Claude Code; it will not be replaced. '
                           'Update that installation with claude plugin update, or remove it first.')
    installed = plugin(cli) if market else None
    actions = []
    if not market:
        actions.append(['plugin', 'marketplace', 'add', str(repo)])
    if not installed:
        actions.append(['plugin', 'install', PLUGIN, '--scope', SCOPE])
    else:
        if installed.get('version') != version:
            actions.append(['plugin', 'marketplace', 'update', MARKETPLACE])
            actions.append(['plugin', 'update', PLUGIN, '--scope', SCOPE])
        if not installed.get('enabled'):
            actions.append(['plugin', 'enable', PLUGIN, '--scope', SCOPE])
    registered = None
    if controller_command:
        command = Path(controller_command).expanduser().resolve()
        if not command.is_file():
            raise InstallError('AgentController command must be an existing executable/launcher file.')
        registered = controller_registered(cli)
        if not registered:
            actions.append(['mcp', 'add', '--scope', SCOPE, SERVER, '--', str(command)])
    return actions, bool(market), bool(installed), registered


INVERSE = {('plugin', 'marketplace', 'add'): ['plugin', 'marketplace', 'remove', MARKETPLACE],
           ('plugin', 'install'): ['plugin', 'uninstall', PLUGIN, '--scope', SCOPE],
           ('mcp', 'add'): ['mcp', 'remove', SERVER, '--scope', SCOPE]}


def inverse(action):
    return next((command for tokens, command in INVERSE.items() if tuple(action[:len(tokens)]) == tokens), None)


def install(repo, home, cli, *, dry_run=False, controller_command=None):
    repo = Path(repo).resolve()
    version = check_claude_package(repo)
    actions, had_market, had_plugin, registered = plan_actions(repo, cli, version, controller_command)
    plan = {'plugin': PLUGIN, 'version': version, 'claudeHome': str(home),
            'commands': [cli.prefix + action for action in actions],
            'agentcontroller': {'checked': registered is not None, 'registered': bool(registered),
                                'willRegister': any(action[:2] == ['mcp', 'add'] for action in actions)}}
    if dry_run:
        return {'status': 'plan', **plan}
    state = home / '.ultra-hook'
    old_receipt, receipt_bytes = load_receipt(home)
    if old_receipt.get('uninstalled'):
        old_receipt = {}
    if old_receipt and (not old_receipt.get('repo') or not same_path(old_receipt['repo'], repo)):
        raise InstallError('Existing Claude Code receipt belongs to a different source; refusing to reuse it.')
    completed = []
    try:
        for action in actions:
            # A CLI may commit before reporting failure; record the attempt first.
            completed.append(action)
            cli.run(action)
        effective = plugin(cli)
        if not effective or not effective.get('enabled') or effective.get('version') != version:
            raise InstallError('Ultra Hook was not verified installed/enabled in Claude Code at the requested version.')
    except InstallError as exc:
        errors = []
        for action in reversed(completed):
            command = inverse(action)
            if command:
                try:
                    cli.run(command)
                except InstallError:
                    errors.append('registration rollback incomplete')
        raise InstallError('Claude Code installation failed; rollback attempted. Reason: ' + str(exc) +
                           ('. ' + '; '.join(errors) if errors else '')) from exc
    created_mcp = plan['agentcontroller']['willRegister']
    receipt = {'plugin': PLUGIN, 'version': version, 'repo': str(repo),
               'createdMarketplace': bool(old_receipt.get('createdMarketplace')) or not had_market,
               'createdPlugin': bool(old_receipt.get('createdPlugin')) or not had_plugin,
               'createdMcp': bool(old_receipt.get('createdMcp')) or created_mcp,
               'mcpCommand': str(Path(controller_command).expanduser().resolve()) if created_mcp else old_receipt.get('mcpCommand')}
    ensure_directory(state)
    write_private(state / 'receipt.json', json.dumps(receipt, indent=2).encode('utf-8'), expected=receipt_bytes)
    return {'status': 'installed', **plan}


def uninstall(home, cli, *, dry_run=False):
    receipt, receipt_bytes = load_receipt(home)
    if not receipt:
        raise InstallError('No Ultra Hook receipt for Claude Code; no registration will be removed.')
    market = marketplace(cli)
    if market and (not receipt.get('repo') or market.get('source') != 'directory'
                   or not same_path(market.get('path', ''), receipt['repo'])):
        raise InstallError('The Claude Code marketplace source changed since installation; it will not be removed.')
    actions = []
    if receipt.get('createdPlugin') and market and plugin(cli):
        actions.append(INVERSE[('plugin', 'install')])
    if receipt.get('createdMcp'):
        actions.append(INVERSE[('mcp', 'add')])
    if receipt.get('createdMarketplace') and market:
        actions.append(INVERSE[('plugin', 'marketplace', 'add')])
    if dry_run:
        return {'status': 'plan', 'claudeHome': str(home), 'commands': [cli.prefix + action for action in actions]}
    for action in actions:
        cli.run(action)
    receipt.update({'uninstalled': True, 'createdPlugin': False, 'createdMarketplace': False, 'createdMcp': False})
    write_private(home / '.ultra-hook/receipt.json', json.dumps(receipt, indent=2).encode('utf-8'), expected=receipt_bytes)
    return {'status': 'uninstalled', 'claudeHome': str(home),
            'message': 'Source files, AgentController binaries and unrelated plugins were preserved.'}


def inspect(repo, cli):
    version = check_claude_package(Path(repo).resolve())
    market = marketplace(cli)
    installed = plugin(cli) if market else None
    result = {'plugin': PLUGIN, 'marketplaceRegistered': bool(market), 'installed': bool(installed),
              'enabled': bool(installed and installed.get('enabled')),
              'version': installed.get('version') if installed else None, 'packageVersion': version}
    result['ready'] = result['enabled'] and result['version'] == version
    return result


LABELS = {('plugin', 'marketplace', 'add'): 'Register the local Ultra Hook marketplace in Claude Code.',
          ('plugin', 'marketplace', 'update'): 'Refresh the Ultra Hook marketplace in Claude Code.',
          ('plugin', 'marketplace', 'remove'): 'Remove the owned Ultra Hook marketplace from Claude Code.',
          ('plugin', 'install'): 'Install Ultra Hook in Claude Code.',
          ('plugin', 'update'): 'Update Ultra Hook in Claude Code.',
          ('plugin', 'enable'): 'Enable Ultra Hook in Claude Code.',
          ('plugin', 'uninstall'): 'Remove the owned Ultra Hook plugin from Claude Code.',
          ('mcp', 'add'): 'Register the AgentController launcher in Claude Code.',
          ('mcp', 'remove'): 'Remove the owned AgentController registration from Claude Code.'}


def describe(command):
    for tokens, label in LABELS.items():
        if any(tuple(command[index:index + len(tokens)]) == tokens for index in range(len(command))):
            return label
    return 'Apply an owned Claude Code registration change.'


def human_result(operation, result):
    status = result.get('status')
    if status == 'skipped':
        return 'Claude Code: skipped; ' + result['message']
    if status == 'error':
        return 'Claude Code error: ' + result['message']
    if status == 'plan':
        lines = ['Claude Code ' + ('installation' if operation == 'install' else 'removal') + ' plan',
                 'Profile: ' + result['claudeHome']]
        lines.extend(f'{index}. {describe(command)}' for index, command in enumerate(result['commands'], 1))
        if not result['commands']:
            lines.append('No registration changes are needed.')
        return '\n'.join(lines)
    if status == 'uninstalled':
        return 'Claude Code cleanup completed.\n' + result['message']
    if operation == 'doctor':
        state = 'ready' if result.get('ready') else 'needs attention'
        detail = ('enabled' if result.get('enabled') else 'disabled' if result.get('installed') else 'not installed')
        return (f'Claude Code: {state}\nPlugin: {detail}'
                + (' (version ' + str(result['version']) + ')' if result.get('version') else ''))
    lines = ['Ultra Hook ' + str(result['version']) + ' is installed and enabled in Claude Code.',
             'Profile: ' + result['claudeHome']]
    if not result['commands']:
        lines.append('Already installed; no registration changes were needed.')
    controller = result['agentcontroller']
    if controller['willRegister']:
        lines.append('AgentController is registered in Claude Code. Registration alone does not validate UI behavior.')
    elif controller['registered']:
        lines.append('An existing AgentController registration in Claude Code was retained.')
    else:
        lines.append('AgentController was not registered in Claude Code; UI validation requires it.')
    lines.append('Next: start a new Claude Code session and send /ultra-hook:ultra-hook followed by your task.')
    return '\n'.join(lines)


def run_step(operation, mode, step, *, home=None, command=None):
    """Run one Claude Code step for a combined launcher; mode is auto, yes or no."""
    if mode == 'no':
        return None
    try:
        if command_prefix(command) is None:
            if mode == 'yes':
                raise InstallError('Claude Code CLI is required. Install it separately, then rerun.')
            return {'status': 'skipped', 'message': 'its CLI was not found.'}
        profile = claude_home(home)
        return step(profile, ClaudeCLI(profile, command, explicit_home=home is not None))
    except InstallError as exc:
        return {'status': 'error', 'message': str(exc)}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return {'status': 'error', 'message': 'Claude Code ' + operation + ' failed; private diagnostics withheld.'}


def main():
    parser = OutputParser(description=__doc__)
    parser.add_argument('--claude-home', help='Explicit Claude Code profile directory (use synthetic directories for tests).')
    parser.add_argument('--claude-command', help='Existing Claude Code executable path.')
    parser.add_argument('--agentcontroller-command', help='Existing AgentController stdio launcher; never overwrites a registration.')
    parser.add_argument('--dry-run', action='store_true', help='Read-only plan; no installation.')
    parser.add_argument('--uninstall', action='store_true', help='Remove only registrations owned by the receipt.')
    parser.add_argument('--check', action='store_true', help='Report whether the plugin is installed and enabled.')
    parser.add_argument('--json', action='store_true', help='Emit safe JSON only.')
    args = parser.parse_args()
    operation = 'uninstall' if args.uninstall else 'doctor' if args.check else 'install'
    steps = {'install': lambda home, cli: install(REPO, home, cli, dry_run=args.dry_run,
                                                   controller_command=args.agentcontroller_command),
             'uninstall': lambda home, cli: uninstall(home, cli, dry_run=args.dry_run),
             'doctor': lambda home, cli: inspect(REPO, cli)}
    result = run_step(operation, 'yes', steps[operation], home=args.claude_home, command=args.claude_command)
    failed = result.get('status') == 'error'
    print(json.dumps(result, indent=2) if args.json else human_result(operation, result),
          file=sys.stderr if failed else sys.stdout)
    return 1 if failed else 2 if operation == 'doctor' and not result.get('ready') else 0


if __name__ == '__main__':
    sys.exit(main())
