"""Installer tests use temporary profiles/fake CLI only; no live profile writes."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import install
import doctor
import uninstall
import setup_agentcontroller


INITIAL = '''# user preferences stay intact
model = "chosen-user-model"
model_reasoning_effort = "max"
approval_policy = "on-request"
sandbox_mode = "workspace-write"
[plugins."cas@claude-agent-system"]
enabled = true # legacy stays active until new hooks are trusted
[plugins."other@somewhere"]
enabled = true
'''


class FakeCLI:
    def __init__(self, home):
        self.home = home
        self.prefix = ['codex executable with spaces']
        self.calls = []
        self.markets = {}
        self.installed = False
        self.fail_add = False
        self.version = '0.1.0'

    def run(self, args, **kwargs):
        self.calls.append(list(args))
        path = self.home / 'config.toml'
        if args[:3] == ['plugin', 'marketplace', 'list']:
            return {'marketplaces': list(self.markets.values())}
        if args[:3] == ['plugin', 'marketplace', 'add']:
            self.markets['ultra-hook'] = {'name': 'ultra-hook', 'root': args[3]}
            return {'added': True}
        if args[:3] == ['plugin', 'marketplace', 'remove']:
            self.markets.pop('ultra-hook', None)
            return {'removed': True}
        if args[:2] == ['plugin', 'list']:
            config = install.load_config(self.home)
            enabled = config.get('plugins', {}).get(install.PLUGIN, {}).get('enabled', False)
            return {'installed': [{'pluginId': install.PLUGIN, 'version': self.version, 'enabled': enabled}]
                                  if self.installed else []}
        if args[:2] == ['plugin', 'add']:
            if self.fail_add:
                raise install.InstallError('synthetic plugin failure')
            if install.PLUGIN not in install.load_config(self.home).get('plugins', {}):
                path.write_text(path.read_text() + '\n[plugins."ultra-hook@ultra-hook"]\nenabled = true\n')
            else:
                install.set_plugin_enabled(self.home, install.PLUGIN, True)
            self.installed = True
            return {'installed': True}
        if args[:2] == ['plugin', 'remove']:
            self.installed = False
            return {'removed': True}
        if args[:2] == ['mcp', 'add']:
            path.write_text(path.read_text() + '\n[mcp_servers.agentcontroller]\ncommand = ' + json.dumps(args[4]) + '\n')
            return ''
        if args[:2] == ['mcp', 'remove']:
            return ''
        raise AssertionError(args)


def runtime(ready=False):
    return {'hookCount': 5, 'trustedHookCount': 5 if ready else 0, 'skillCount': 2,
            'hooksReady': ready, 'trustPending': not ready}


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ultra hook tests ')
        self.root = Path(self.tmp.name)
        self.home = self.root / 'synthetic CODEX_HOME'
        self.home.mkdir()
        (self.home / 'config.toml').write_text(INITIAL, encoding='utf-8')
        (self.home / 'auth.json').write_text('synthetic credential never inspected', encoding='utf-8')
        (self.home / 'AGENTS.md').write_text('synthetic user policy', encoding='utf-8')
        self.repo = self.root / 'repo with spaces'
        (self.repo / '.agents/plugins').mkdir(parents=True)
        (self.repo / '.agents/plugins/marketplace.json').write_text(json.dumps({'name': 'ultra-hook'}))
        (self.repo / 'plugins/ultra-hook/.codex-plugin').mkdir(parents=True)
        (self.repo / 'plugins/ultra-hook/.codex-plugin/plugin.json').write_text(
            json.dumps({'name': 'ultra-hook', 'version': '0.1.0'}))
        (self.repo / 'plugins/ultra-hook/plugin.json').write_text(
            json.dumps({'name': 'ultra-hook', 'version': '0.1.0'}))
        self.cli = FakeCLI(self.home)
        self.pre = mock.patch.object(install, 'prerequisites', return_value={'python':'3.11','node':'v18.0','codex':'fake'})
        self.pre.start()

    def tearDown(self):
        self.pre.stop()
        self.tmp.cleanup()

    def execute(self, **kwargs):
        return install.install(self.repo, self.home, self.cli, **kwargs)

    def test_default_install_is_idempotent_and_preserves_user_settings_and_files(self):
        baseline = install.load_config(self.home)
        auth = (self.home / 'auth.json').read_bytes()
        policy = (self.home / 'AGENTS.md').read_bytes()
        first = self.execute(runtime_check=lambda *_: runtime())
        count = sum(call[:2] == ['plugin','add'] for call in self.cli.calls)
        second = self.execute(runtime_check=lambda *_: runtime())
        self.assertEqual(first['status'], 'installed')
        self.assertEqual(second['status'], 'installed')
        self.assertEqual(sum(call[:2] == ['plugin','add'] for call in self.cli.calls), count)
        self.assertEqual(install.protected(install.load_config(self.home)), install.protected(baseline))
        self.assertEqual((self.home / 'auth.json').read_bytes(), auth)
        self.assertEqual((self.home / 'AGENTS.md').read_bytes(), policy)
        self.assertTrue(install.load_config(self.home)['plugins'][install.CAS]['enabled'])
        self.assertTrue(json.loads((self.home / '.ultra-hook/receipt.json').read_text())['createdPlugin'])

    def test_plan_performs_no_writes_and_path_is_single_argument(self):
        before = (self.home / 'config.toml').read_bytes()
        planned = self.execute(dry_run=True)
        self.assertEqual(planned['commands'][0][-2], str(self.repo.resolve()))
        self.assertFalse((self.home / '.ultra-hook').exists())
        self.assertEqual((self.home / 'config.toml').read_bytes(), before)
        self.assertFalse(any(call[:2] == ['plugin','add'] for call in self.cli.calls))

    def test_future_manifest_version_installs_without_script_changes(self):
        for name in ('plugin.json', '.codex-plugin/plugin.json'):
            (self.repo / 'plugins/ultra-hook' / name).write_text(json.dumps({'name':'ultra-hook','version':'1.2.3-rc.1+build.4'}))
        self.cli.version = '1.2.3-rc.1+build.4'
        result = self.execute(runtime_check=lambda *_: runtime())
        self.assertEqual(result['version'], self.cli.version)

    def test_mismatched_or_invalid_versions_fail_before_cli_writes(self):
        path = self.repo / 'plugins/ultra-hook/plugin.json'
        for version in ('0.2.0', '01.2.3', '1.2.3-01', 'not-a-version'):
            path.write_text(json.dumps({'name':'ultra-hook','version':version}))
            with self.assertRaises(install.InstallError):
                self.execute()
        self.assertFalse(self.cli.calls)

    def test_different_installed_version_requires_explicit_uninstall(self):
        self.execute(runtime_check=lambda *_: runtime())
        self.cli.version = '0.0.9'
        with self.assertRaisesRegex(install.InstallError, 'Uninstall'):
            self.execute()

    def test_replace_cas_waits_for_five_trusted_runtime_hooks(self):
        pending = self.execute(replace_cas=True, runtime_check=lambda *_: runtime(False))
        self.assertTrue(pending['migrationPending'])
        self.assertTrue(install.load_config(self.home)['plugins'][install.CAS]['enabled'])
        ready = self.execute(replace_cas=True, runtime_check=lambda *_: runtime(True))
        self.assertFalse(ready['migrationPending'])
        self.assertFalse(install.load_config(self.home)['plugins'][install.CAS]['enabled'])
        self.assertEqual(install.load_config(self.home)['model_reasoning_effort'], 'max')

    def test_extra_untrusted_hook_keeps_cas_enabled(self):
        metadata = runtime(True)
        metadata['hookCount'] = 6
        metadata['hooksReady'] = False
        result = self.execute(replace_cas=True, runtime_check=lambda *_: metadata)
        self.assertTrue(result['migrationPending'])
        self.assertTrue(install.load_config(self.home)['plugins'][install.CAS]['enabled'])

    def test_rollback_does_not_overwrite_concurrent_user_config_change(self):
        def changed(*_):
            cfg = self.home / 'config.toml'
            cfg.write_text(cfg.read_text().replace('chosen-user-model', 'concurrently-chosen-model'))
            return runtime()
        with self.assertRaises(install.InstallError):
            self.execute(runtime_check=changed)
        self.assertEqual(install.load_config(self.home)['model'], 'concurrently-chosen-model')
        self.assertFalse(self.cli.installed)

    def test_uninstall_refuses_changed_marketplace_source(self):
        self.execute(runtime_check=lambda *_: runtime())
        self.cli.markets['ultra-hook']['root'] = str(self.root / 'other repository')
        with self.assertRaises(install.InstallError):
            uninstall.uninstall(self.home, self.cli)
        self.assertTrue(self.cli.installed)

    def test_failed_install_rolls_back_new_marketplace_and_keeps_original_config(self):
        before = (self.home / 'config.toml').read_bytes()
        self.cli.fail_add = True
        with self.assertRaises(install.InstallError):
            self.execute(runtime_check=lambda *_: runtime())
        self.assertNotIn('ultra-hook', self.cli.markets)
        self.assertEqual((self.home / 'config.toml').read_bytes(), before)
        self.assertTrue(list((self.home / '.ultra-hook/backups').glob('*/config.toml')))

    def test_different_agentcontroller_is_never_overwritten(self):
        executable = self.root / 'controller with spaces.exe'
        executable.write_bytes(b'synthetic executable')
        cfg = self.home / 'config.toml'
        cfg.write_text(INITIAL + '[mcp_servers.agentcontroller]\ncommand="other-existing-command"\n')
        before = cfg.read_bytes()
        with self.assertRaises(install.InstallError):
            self.execute(agentcontroller_command=executable, runtime_check=lambda *_: runtime())
        self.assertEqual(cfg.read_bytes(), before)
        self.assertEqual(self.cli.calls, [])

    def test_missing_controller_stays_explicitly_pending(self):
        result = self.execute(runtime_check=lambda *_: runtime())
        self.assertFalse(result['agentcontroller']['registered'])
        self.assertFalse(result['agentcontroller']['willRegister'])
        self.assertFalse(any(call[:2] == ['mcp','add'] for call in self.cli.calls))

    def test_uninstall_restores_cas_only_from_receipt_and_preserves_other_plugin(self):
        self.execute(replace_cas=True, runtime_check=lambda *_: runtime(True))
        result = uninstall.uninstall(self.home, self.cli)
        self.assertEqual(result['status'], 'uninstalled')
        config = install.load_config(self.home)
        self.assertTrue(config['plugins'][install.CAS]['enabled'])
        self.assertTrue(config['plugins']['other@somewhere']['enabled'])
        self.assertFalse(self.cli.installed)
        self.assertTrue((self.home / 'auth.json').exists())
        self.assertTrue(list((self.home / '.ultra-hook/backups').iterdir()))

    def test_unknown_receipt_refuses_uninstall(self):
        with self.assertRaises(install.InstallError):
            uninstall.uninstall(self.home, self.cli)
        self.assertFalse(self.cli.calls)

    def test_hook_trust_summary_excludes_unrelated_hooks(self):
        hooks = [{'pluginId': install.PLUGIN, 'enabled': True, 'trustStatus': 'trusted'} for _ in range(5)]
        hooks.append({'pluginId':'unrelated@plugin','enabled':True,'trustStatus':'untrusted'})
        report = doctor.summarize_runtime({'data':[{'hooks':hooks}]}, {'data':[{'skills':
            [{'name':'ultra-hook:ultra-hook'},{'name':'ultra-hook:agentcontroller'},{'name':'cas:review'}]}]})
        self.assertTrue(report['hooksReady'])
        self.assertEqual(report['trustedHookCount'], 5)
        self.assertEqual(report['skillCount'], 2)

    def test_agentcontroller_source_build_is_opt_in_and_pinned(self):
        target = self.root / 'Agent Controller output'
        with mock.patch.object(subprocess_if_available(), 'run', side_effect=AssertionError('must not build')):
            result = setup_agentcontroller.build(target)
        self.assertEqual(result['status'], 'plan')
        self.assertEqual(result['commit'], 'bc6db97122d6adf07342d3efc87e7ac7c96b4889')
        self.assertFalse(target.exists())

    def test_dotnet_explicit_path_and_windows_programfiles_fallback(self):
        executable = self.root / 'Program Files/dotnet/dotnet.exe'
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b'synthetic executable')
        self.assertEqual(setup_agentcontroller.dotnet_executable(executable), str(executable.resolve()))
        with mock.patch.object(setup_agentcontroller.shutil, 'which', return_value=None), \
             mock.patch.object(setup_agentcontroller, 'os', SimpleNamespace(name='nt',
                 environ={'ProgramFiles': str(self.root / 'Program Files')})):
            self.assertEqual(setup_agentcontroller.dotnet_executable(), str(executable))

    def test_doctor_transport_is_not_ui_validation(self):
        self.cli.markets['ultra-hook'] = {'name':'ultra-hook','root':str(self.repo)}
        self.cli.installed = True
        with mock.patch.object(doctor, 'runtime_metadata', return_value={**runtime(), 'agentcontrollerRuntime':{'toolCount':52}}):
            report = doctor.inspect(self.cli, self.repo)
        self.assertTrue(report['uiTransportDiscovered'])
        self.assertIn('not-run', report['uiValidation'])
        self.assertNotIn('uiValidationReady', report)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows source-build branch')
    def test_build_retains_license_notice_and_binary_provenance(self):
        target = self.root / 'isolated source build'
        dotnet = self.root / 'dotnet.exe'
        dotnet.write_bytes(b'fake sdk')
        calls = []
        def simulated(command, **kwargs):
            calls.append(command)
            self.assertFalse(kwargs['shell'])
            output = ''
            if '--list-sdks' in command:
                output = '9.0.300 [synthetic SDK]\n'
            elif 'clone' in command:
                source = target / 'source'
                source.mkdir()
                (source / 'LICENSE').write_text('synthetic Apache license')
                (source / 'NOTICE').write_text('synthetic upstream notice')
            elif 'rev-parse' in command:
                output = setup_agentcontroller.COMMIT + '\n'
            elif 'publish' in command:
                (target / 'bin').mkdir()
                (target / 'bin/agentcontroller-windows.exe').write_bytes(b'synthetic build output')
            return setup_agentcontroller.subprocess.CompletedProcess(command, 0, output, '')
        with mock.patch.object(setup_agentcontroller.shutil, 'which', return_value='git'), \
             mock.patch.object(setup_agentcontroller.subprocess, 'run', side_effect=simulated):
            result = setup_agentcontroller.build(target, enabled=True, dotnet_command=dotnet)
        self.assertEqual(result['status'], 'built')
        self.assertEqual((target / 'NOTICE.AgentController').read_text(), 'synthetic upstream notice')
        self.assertEqual((target / 'LICENSE.AgentController').read_text(), 'synthetic Apache license')
        record = json.loads((target / 'source-provenance.json').read_text())
        self.assertEqual(record['binarySha256'], install.hashlib.sha256(b'synthetic build output').hexdigest())
        self.assertEqual(calls[-1][0], str(dotnet.resolve()))


def subprocess_if_available():
    return setup_agentcontroller.subprocess


if __name__ == '__main__':
    unittest.main()
