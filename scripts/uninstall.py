#!/usr/bin/env python3
"""Remove only registrations owned by an Ultra Hook installation receipt, in Codex and Claude Code."""
import argparse
import json
from pathlib import Path
import sys
import install
import claude_code
from install import CLI, CAS, PLUGIN, MARKETPLACE, SERVER, InstallError, codex_home, load_config, same_path, set_plugin_enabled, installation_lock, write_private, marketplaces, fingerprint, guard_path, private_bytes, MAX_RECEIPT_BYTES, plugin_catalog, protected, emit_result, OutputParser


def uninstall(home, cli, dry_run=False):
    home = guard_path(home)
    receipt_file = home / '.ultra-hook/receipt.json'
    receipt_bytes = private_bytes(receipt_file, limit=MAX_RECEIPT_BYTES)
    if receipt_bytes is None:
        raise InstallError('No Ultra Hook receipt; no user registration will be removed.')
    receipt = json.loads(receipt_bytes)
    if not isinstance(receipt, dict) or receipt.get('plugin') != PLUGIN:
        raise InstallError('Unexpected receipt identity; refusing to uninstall.')
    config = load_config(home)
    config_bytes = private_bytes(home / 'config.toml')
    market = marketplaces(cli).get(MARKETPLACE)
    if market and (not receipt.get('repo') or not same_path(market.get('root', ''), receipt['repo'])):
        raise InstallError('The marketplace source changed since installation; it will not be removed.')
    actions = []
    installed = plugin_catalog(cli).get(PLUGIN) if market else None
    if installed and installed.get('version') != receipt.get('version'):
        raise InstallError('Installed plugin version changed since the receipt; refusing to remove it.')
    if receipt.get('createdPlugin'):
        actions.append(['plugin', 'remove', PLUGIN, '--json'])
    current = config.get('mcp_servers', {}).get(SERVER, {})
    if receipt.get('createdMcp') and current:
        recorded = receipt.get('mcpCommand')
        if (not recorded or not current.get('command') or not same_path(recorded, current['command'])
                or current.get('args') or current.get('url') or not receipt.get('mcpFingerprint')
                or fingerprint(current) != receipt['mcpFingerprint']):
            raise InstallError('AgentController registration changed since installation; it will not be removed.')
        actions.append(['mcp', 'remove', SERVER])
    if receipt.get('createdMarketplace'):
        actions.append(['plugin', 'marketplace', 'remove', MARKETPLACE, '--json'])
    if dry_run:
        return {'status': 'plan', 'commands': [cli.prefix + action for action in actions],
                'restoreCas': bool(receipt.get('disabledCas')), 'backupsPreserved': True}
    with installation_lock(home):
        if private_bytes(receipt_file, limit=MAX_RECEIPT_BYTES) != receipt_bytes or private_bytes(home / 'config.toml') != config_bytes:
            raise InstallError('Installation data changed since planning; rerun without overwriting it.')
        locked_market = marketplaces(cli).get(MARKETPLACE)
        locked_installed = plugin_catalog(cli).get(PLUGIN) if locked_market else None
        if locked_market != market or locked_installed != installed:
            raise InstallError('Registrations changed since planning; refusing removal.')
        if receipt.get('disabledCas') and config.get('plugins', {}).get(CAS, {}).get('enabled') is False:
            set_plugin_enabled(home, CAS, True)
        expected_bytes = private_bytes(home / 'config.toml')
        for action in actions:
            if private_bytes(home / 'config.toml') != expected_bytes:
                raise InstallError('Config changed concurrently during removal; remaining registrations retained.')
            cli.run(action, json_output=action[-1] == '--json')
            expected_bytes = private_bytes(home / 'config.toml')
            if protected(load_config(home), replace_cas=bool(receipt.get('disabledCas')), add_mcp=bool(receipt.get('createdMcp'))) != protected(config, replace_cas=bool(receipt.get('disabledCas')), add_mcp=bool(receipt.get('createdMcp'))):
                raise InstallError('An unrelated preference changed during removal; remaining registrations retained.')
        receipt['uninstalled'] = True
        receipt['createdPlugin'] = receipt['createdMarketplace'] = receipt['createdMcp'] = receipt['disabledCas'] = False
        write_private(receipt_file, json.dumps(receipt, indent=2).encode('utf-8'), expected=receipt_bytes)
    return {'status': 'uninstalled', 'backupsPreserved': True,
            'message': 'Source files, backups, AgentController binaries and unrelated plugins were preserved.'}


def main():
    parser = OutputParser(description=__doc__)
    parser.add_argument('--codex-home')
    parser.add_argument('--codex-command')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--json', action='store_true', help='Emit safe JSON only, for automation (default: readable summary).')
    install.add_runtime_arguments(parser)
    args = parser.parse_args()
    result = None
    try:
        if install.codex_selected(args):
            home = codex_home(args.codex_home)
            result = uninstall(home, CLI(home, args.codex_command), args.dry_run)
    except InstallError as exc:
        result = {'status': 'error', 'message': str(exc)}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result = {'status': 'error', 'message': 'Removal failed; private diagnostics withheld.'}

    def remove(home, cli):
        # A profile this installer never touched is not an error in auto mode.
        if args.claude_code == 'auto' and not claude_code.load_receipt(home)[0]:
            return {'status': 'skipped', 'message': 'no Ultra Hook receipt in its profile.'}
        return claude_code.uninstall(home, cli, dry_run=args.dry_run)
    claude = claude_code.run_step('uninstall', args.claude_code, remove, home=args.claude_home, command=args.claude_command)
    return install.finish('uninstall', result, claude, json_output=args.json)


if __name__ == '__main__':
    sys.exit(main())
