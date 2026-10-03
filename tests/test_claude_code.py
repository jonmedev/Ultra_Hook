"""Claude Code installer tests use temporary profiles and a fake CLI only; no live profile writes."""
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import install
import doctor
import uninstall
import claude_code

REPO = Path(__file__).resolve().parents[1]
VERSION = install.check_package(REPO)


class FakeClaude:
    def __init__(self, home):
        self.home = home
        self.prefix = ['claude executable with spaces']
        self.calls = []
        self.market = None
        self.plugin = None
        self.server = None
        self.fail = None
        self.installs_version = VERSION

    def run(self, args, *, json_output=False, timeout=90, check=True):
        self.calls.append(list(args))
        if self.fail and args[:len(self.fail)] == self.fail:
            raise install.InstallError('synthetic Claude Code failure')
        if args[:3] == ['plugin', 'marketplace', 'list']:
            return [self.market] if self.market else []
        if args[:3] == ['plugin', 'marketplace', 'add']:
            self.market = {'name': 'ultra-hook', 'source': 'directory', 'path': args[3]}
        elif args[:3] == ['plugin', 'marketplace', 'remove']:
            self.market = None
        elif args[:2] == ['plugin', 'list']:
            return [self.plugin] if self.plugin else []
        elif args[:2] in (['plugin', 'install'], ['plugin', 'update']):
            self.plugin = {'id': install.PLUGIN, 'version': self.installs_version, 'scope': 'user', 'enabled': True}
        elif args[:2] == ['plugin', 'enable']:
            self.plugin['enabled'] = True
        elif args[:2] == ['plugin', 'uninstall']:
            self.plugin = None
        elif args[:2] == ['mcp', 'get']:
            return 0 if self.server else 1
        elif args[:2] == ['mcp', 'add']:
            self.server = args[-1]
        elif args[:2] == ['mcp', 'remove']:
            self.server = None
        return ''

    def mutations(self):
        return [call for call in self.calls if call[:2] not in (['plugin', 'list'], ['mcp', 'get'])
                and call[:3] != ['plugin', 'marketplace', 'list']]


class ClaudeCodeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='ultra-claude-test-')
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name) / 'profile with spaces'
        self.home.mkdir()
        self.cli = FakeClaude(self.home)
        self.launcher = Path(self.directory.name) / 'launcher with spaces.exe'
        self.launcher.write_bytes(b'synthetic')

    def receipt(self):
        return json.loads((self.home / '.ultra-hook/receipt.json').read_text())

    def test_dry_run_plans_without_changes(self):
        result = claude_code.install(REPO, self.home, self.cli, dry_run=True, controller_command=str(self.launcher))
        self.assertEqual(result['status'], 'plan')
        self.assertEqual([command[1:3] for command in result['commands']],
                         [['plugin', 'marketplace'], ['plugin', 'install'], ['mcp', 'add']])
        self.assertEqual(self.cli.mutations(), [])
        self.assertFalse((self.home / '.ultra-hook').exists())

    def test_fresh_install_is_owned_idempotent_and_removable(self):
        result = claude_code.install(REPO, self.home, self.cli, controller_command=str(self.launcher))
        self.assertEqual(result['status'], 'installed')
        self.assertEqual(self.cli.market['path'], str(REPO))
        self.assertEqual(self.cli.server, str(self.launcher.resolve()))
        self.assertEqual({key: self.receipt()[key] for key in ('createdMarketplace', 'createdPlugin', 'createdMcp')},
                         {'createdMarketplace': True, 'createdPlugin': True, 'createdMcp': True})
        before = len(self.cli.mutations())
        again = claude_code.install(REPO, self.home, self.cli, controller_command=str(self.launcher))
        self.assertEqual(again['commands'], [])
        self.assertEqual(len(self.cli.mutations()), before)
        self.assertTrue(self.receipt()['createdMcp'])
        self.assertTrue(claude_code.inspect(REPO, self.cli)['ready'])
        removed = claude_code.uninstall(self.home, self.cli)
        self.assertEqual(removed['status'], 'uninstalled')
        self.assertEqual((self.cli.market, self.cli.plugin, self.cli.server), (None, None, None))
        self.assertTrue(self.receipt()['uninstalled'])

    def test_existing_registrations_are_retained_and_never_owned(self):
        self.cli.market = {'name': 'ultra-hook', 'source': 'directory', 'path': str(REPO)}
        self.cli.plugin = {'id': install.PLUGIN, 'version': VERSION, 'scope': 'user', 'enabled': True}
        self.cli.server = 'existing controller'
        result = claude_code.install(REPO, self.home, self.cli, controller_command=str(self.launcher))
        self.assertEqual(result['commands'], [])
        self.assertTrue(result['agentcontroller']['registered'])
        self.assertEqual(self.cli.server, 'existing controller')
        claude_code.uninstall(self.home, self.cli)
        self.assertEqual(self.cli.server, 'existing controller')
        self.assertIsNotNone(self.cli.plugin)
        self.assertIsNotNone(self.cli.market)

    def test_controller_lookup_runs_only_when_a_launcher_is_supplied(self):
        claude_code.install(REPO, self.home, self.cli)
        self.assertNotIn(['mcp', 'get', 'agentcontroller'], self.cli.calls)
        self.assertIsNone(self.cli.server)

    def test_older_or_disabled_installation_is_updated_through_native_commands(self):
        self.cli.market = {'name': 'ultra-hook', 'source': 'directory', 'path': str(REPO)}
        self.cli.plugin = {'id': install.PLUGIN, 'version': '0.0.1', 'scope': 'user', 'enabled': False}
        claude_code.install(REPO, self.home, self.cli)
        self.assertEqual(self.cli.mutations(), [['plugin', 'marketplace', 'update', 'ultra-hook'],
                                                ['plugin', 'update', install.PLUGIN, '--scope', 'user'],
                                                ['plugin', 'enable', install.PLUGIN, '--scope', 'user']])
        self.assertTrue(self.cli.plugin['enabled'])
        self.assertEqual(self.cli.plugin['version'], VERSION)
        self.assertFalse(self.receipt()['createdPlugin'])

    def test_foreign_marketplace_scope_and_receipt_are_refused(self):
        self.cli.market = {'name': 'ultra-hook', 'source': 'github', 'repo': 'someone/else'}
        with self.assertRaisesRegex(install.InstallError, 'different ultra-hook marketplace'):
            claude_code.install(REPO, self.home, self.cli)
        self.cli.market = {'name': 'ultra-hook', 'source': 'directory', 'path': str(REPO)}
        self.cli.plugin = {'id': install.PLUGIN, 'version': VERSION, 'scope': 'project', 'enabled': True}
        with self.assertRaisesRegex(install.InstallError, 'project scope'):
            claude_code.install(REPO, self.home, self.cli)
        self.cli.plugin = None
        (self.home / '.ultra-hook').mkdir()
        (self.home / '.ultra-hook/receipt.json').write_text(json.dumps({'plugin': install.PLUGIN, 'repo': str(self.home)}))
        with self.assertRaisesRegex(install.InstallError, 'different source'):
            claude_code.install(REPO, self.home, self.cli)
        self.assertEqual(self.cli.mutations(), [])

    def test_failure_rolls_back_only_new_registrations(self):
        self.cli.fail = ['mcp', 'add']
        with self.assertRaisesRegex(install.InstallError, 'rollback attempted'):
            claude_code.install(REPO, self.home, self.cli, controller_command=str(self.launcher))
        self.assertEqual((self.cli.market, self.cli.plugin), (None, None))
        self.assertFalse((self.home / '.ultra-hook/receipt.json').exists())

    def test_unverified_version_fails_and_missing_launcher_is_rejected(self):
        self.cli.installs_version = '9.9.9'
        with self.assertRaisesRegex(install.InstallError, 'not verified'):
            claude_code.install(REPO, self.home, self.cli)
        with self.assertRaisesRegex(install.InstallError, 'existing executable'):
            claude_code.install(REPO, self.home, self.cli, controller_command=str(self.home / 'absent'))

    def test_uninstall_without_receipt_or_with_moved_marketplace_removes_nothing(self):
        with self.assertRaisesRegex(install.InstallError, 'No Ultra Hook receipt'):
            claude_code.uninstall(self.home, self.cli)
        claude_code.install(REPO, self.home, self.cli)
        self.cli.market['path'] = str(self.home)
        with self.assertRaisesRegex(install.InstallError, 'source changed'):
            claude_code.uninstall(self.home, self.cli)
        self.assertIsNotNone(self.cli.plugin)

    def test_shim_resolution_and_missing_cli(self):
        with mock.patch.object(claude_code.shutil, 'which', return_value=None):
            self.assertIsNone(claude_code.command_prefix())
            self.assertEqual(claude_code.run_step('install', 'auto', None)['status'], 'skipped')
            self.assertEqual(claude_code.run_step('install', 'yes', None)['status'], 'error')
            self.assertIsNone(claude_code.run_step('install', 'no', None))
        shim = Path(self.directory.name) / 'claude.cmd'
        shim.write_text('synthetic')
        with self.assertRaisesRegex(install.InstallError, 'shim'):
            claude_code.command_prefix(str(shim))
        native = shim.parent / 'node_modules/@anthropic-ai/claude-code/bin/claude.exe'
        native.parent.mkdir(parents=True)
        native.write_bytes(b'synthetic')
        self.assertEqual(claude_code.command_prefix(str(shim)), [str(native.resolve())])

    def test_private_failures_are_withheld_from_step_results(self):
        def broken(home, cli):
            raise ValueError('synthetic secret must not appear')
        with mock.patch.object(claude_code, 'command_prefix', return_value=['claude']), \
             mock.patch.object(claude_code, 'claude_home', return_value=self.home):
            result = claude_code.run_step('install', 'auto', broken)
        self.assertEqual(result['status'], 'error')
        self.assertNotIn('synthetic secret', json.dumps(result))


class CombinedEntryPointTests(unittest.TestCase):
    """Both runtimes are reported together; neither step reaches a live profile."""

    def invoke(self, module, args, codex=None, claude=None, codex_found=True):
        target = 'install' if module is install else 'inspect' if module is doctor else 'uninstall'
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, 'argv', [module.__name__ + '.py'] + args), \
             mock.patch.object(module, 'CLI', return_value=object()), \
             mock.patch.object(module, 'codex_home', return_value=Path('synthetic profile')), \
             mock.patch.object(module, target, return_value=codex) as codex_step, \
             mock.patch.object(install.shutil, 'which', return_value='codex' if codex_found else None), \
             mock.patch.object(claude_code, 'run_step', return_value=claude) as claude_step, \
             redirect_stdout(stdout), redirect_stderr(stderr):
            code = module.main()
        return code, stdout.getvalue(), stderr.getvalue(), codex_step, claude_step

    CODEX = {'status': 'installed', 'version': VERSION, 'codexHome': 'synthetic profile', 'commands': [],
             'runtime': {}, 'agentcontroller': {'registered': False, 'willRegister': False}}
    CLAUDE = {'status': 'installed', 'version': VERSION, 'claudeHome': 'synthetic claude profile', 'commands': [],
              'agentcontroller': {'checked': False, 'registered': False, 'willRegister': False}}

    def test_both_runtimes_are_installed_and_reported(self):
        code, text, errors, codex_step, claude_step = self.invoke(install, [], self.CODEX, self.CLAUDE)
        self.assertEqual((code, errors), (0, ''))
        self.assertIn('installed and enabled.', text)
        self.assertIn('installed and enabled in Claude Code.', text)
        self.assertEqual(claude_step.call_args.args[:2], ('install', 'auto'))
        code, text, _, _, _ = self.invoke(install, ['--json'], self.CODEX, self.CLAUDE)
        self.assertEqual(json.loads(text), {**self.CODEX, 'claudeCode': self.CLAUDE})

    def test_claude_only_host_skips_codex_and_a_missing_host_fails(self):
        code, text, _, codex_step, _ = self.invoke(install, ['--json'], self.CODEX, self.CLAUDE, codex_found=False)
        self.assertEqual(code, 0)
        codex_step.assert_not_called()
        self.assertEqual(json.loads(text), {'status': 'installed', 'codex': {'status': 'skipped'}, 'claudeCode': self.CLAUDE})
        skipped = {'status': 'skipped', 'message': 'its CLI was not found.'}
        code, text, errors, _, _ = self.invoke(install, [], self.CODEX, skipped, codex_found=False)
        self.assertEqual((code, text), (1, ''))
        self.assertIn('Codex CLI or Claude Code CLI is required', errors)

    def test_claude_failure_fails_the_command_but_keeps_the_codex_report(self):
        failure = {'status': 'error', 'message': 'safe actionable issue'}
        code, text, errors, _, _ = self.invoke(install, [], self.CODEX, failure)
        self.assertEqual((code, text), (1, ''))
        self.assertIn('installed and enabled.', errors)
        self.assertIn('Claude Code error: safe actionable issue', errors)

    def test_explicit_runtime_selection(self):
        _, _, _, codex_step, claude_step = self.invoke(install, ['--codex', 'no'], self.CODEX, self.CLAUDE)
        codex_step.assert_not_called()
        _, _, _, codex_step, claude_step = self.invoke(install, ['--claude-code', 'no'], self.CODEX, None, codex_found=False)
        codex_step.assert_called_once()
        self.assertEqual(claude_step.call_args.args[1], 'no')

    def test_doctor_and_uninstall_report_both_runtimes(self):
        ready = {'ready': True, 'enabled': True, 'installed': True, 'runtime': {}}
        claude = {'plugin': install.PLUGIN, 'installed': True, 'enabled': True, 'version': VERSION, 'ready': False}
        code, text, _, _, _ = self.invoke(doctor, [], ready, claude)
        self.assertEqual(code, 2)
        self.assertIn('Claude Code: needs attention', text)
        code, _, _, _, _ = self.invoke(doctor, [], ready, {**claude, 'ready': True})
        self.assertEqual(code, 0)
        removed = {'status': 'uninstalled', 'claudeHome': 'synthetic', 'message': 'preserved.'}
        code, text, _, _, _ = self.invoke(uninstall, [], {'status': 'uninstalled', 'message': 'kept.'}, removed)
        self.assertEqual(code, 0)
        self.assertIn('Claude Code cleanup completed.', text)

    def test_controller_prepared_for_codex_is_offered_to_claude_code(self):
        with tempfile.TemporaryDirectory(prefix='ultra-claude-test-') as directory:
            launcher = Path(directory) / 'launcher.exe'
            launcher.write_bytes(b'synthetic')
            arguments = install.parser().parse_args(['--with-agentcontroller'])
            codex = {'agentcontroller': {'acquisition': {'status': 'reused', 'command': str(launcher)}}}
            self.assertEqual(install.controller_for_claude(arguments, codex), str(launcher))
            codex['agentcontroller']['acquisition']['command'] = str(Path(directory) / 'planned-only.exe')
            self.assertIsNone(install.controller_for_claude(arguments, codex))
            self.assertIsNone(install.controller_for_claude(install.parser().parse_args([]), codex))
            pending = {'agentcontroller': {'acquisition': {'status': 'pending', 'command': None}}}
            self.assertIsNone(install.controller_for_claude(arguments, pending))


if __name__ == '__main__':
    unittest.main()
