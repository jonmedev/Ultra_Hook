"""Installer tests use temporary profiles/fake CLI only; no live profile writes."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import io
from contextlib import redirect_stdout, redirect_stderr
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
            'hooksReady': ready, 'trustPending': not ready, 'skillsReady': True}


def trusted_hooks(plugin_root=None):
    plugin_root = plugin_root or install.REPO / 'plugins/ultra-hook'
    source = plugin_root / 'hooks/hooks.json'
    definition = json.loads(source.read_text(encoding='utf-8'))
    return [{'pluginId':install.PLUGIN, 'enabled':True, 'trustStatus':'trusted',
             'eventName':event[0].lower()+event[1:], 'handlerType':handler['type'],
             'command':handler['command'].replace('${PLUGIN_ROOT}',str(plugin_root)),
             'matcher':group.get('matcher'), 'timeoutSec':handler['timeout'],
             'source':'plugin', 'sourcePath':str(source)}
            for event,groups in definition['hooks'].items() for group in groups for handler in group['hooks']]


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

    def new_source(self):
        target=self.root/'new extracted repo with spaces'
        install.shutil.copytree(self.repo,target)
        return target

    def test_uninstall_then_new_source_preserves_terminal_receipt_backup(self):
        self.execute(runtime_check=lambda *_:runtime())
        uninstall.uninstall(self.home,self.cli)
        prior=(self.home/'.ultra-hook/receipt.json').read_bytes()
        target=self.new_source()
        for manifest in ('plugin.json','.codex-plugin/plugin.json'):
            (target/'plugins/ultra-hook'/manifest).write_text(json.dumps({'name':'ultra-hook','version':'0.1.2'}))
        self.cli.version='0.1.2'
        result=install.install(target,self.home,self.cli,runtime_check=lambda *_:runtime())
        receipt=json.loads((self.home/'.ultra-hook/receipt.json').read_bytes())
        self.assertEqual(receipt['repo'],str(target.resolve()))
        self.assertEqual(receipt['version'],'0.1.2')
        self.assertTrue(receipt['createdPlugin'])
        self.assertFalse(receipt['disabledCas'])
        self.assertFalse(receipt['createdMcp'])
        self.assertEqual((Path(result['backup'])/'receipt.json').read_bytes(),prior)

    def test_ambiguous_terminal_receipt_cannot_switch_sources(self):
        self.execute(runtime_check=lambda *_:runtime())
        uninstall.uninstall(self.home,self.cli)
        path=self.home/'.ultra-hook/receipt.json'
        terminal=json.loads(path.read_bytes())
        target=self.new_source()
        variants=[]
        for key in ('createdPlugin','createdMarketplace','createdMcp','disabledCas'):
            missing=dict(terminal);missing.pop(key);variants.append(missing)
            enabled=dict(terminal);enabled[key]=True;variants.append(enabled)
            mistyped=dict(terminal);mistyped[key]=0;variants.append(mistyped)
        active=dict(terminal);active['uninstalled']=False;variants.append(active)
        mistyped=dict(terminal);mistyped['uninstalled']=1;variants.append(mistyped)
        wrong=dict(terminal);wrong['plugin']='unrelated@plugin';variants.append(wrong)
        variants.append({})
        for receipt in variants:
            with self.subTest(receipt=receipt):
                path.write_text(json.dumps(receipt))
                before=path.read_bytes()
                self.cli.calls=[]
                with self.assertRaises(install.InstallError):
                    install.install(target,self.home,self.cli,runtime_check=lambda *_:runtime())
                self.assertEqual(path.read_bytes(),before)
                self.assertFalse(any(call[:2]==['plugin','add'] or call[:3]==['plugin','marketplace','add']for call in self.cli.calls))

    def test_failed_new_install_retains_terminal_receipt_and_its_backup(self):
        self.execute(runtime_check=lambda *_:runtime())
        uninstall.uninstall(self.home,self.cli)
        path=self.home/'.ultra-hook/receipt.json';prior=path.read_bytes()
        self.cli.fail_add=True
        with self.assertRaises(install.InstallError):
            install.install(self.new_source(),self.home,self.cli,runtime_check=lambda *_:runtime())
        self.assertEqual(path.read_bytes(),prior)
        self.assertTrue(any(backup.read_bytes()==prior for backup in (self.home/'.ultra-hook/backups').glob('*/receipt.json')))
        self.assertTrue(any(call[:2]==['plugin','add'] for call in self.cli.calls))
        self.assertFalse(self.cli.installed)
        self.assertNotIn('ultra-hook',self.cli.markets)

    def test_terminal_receipt_same_source_is_also_backed_up(self):
        self.execute(runtime_check=lambda *_:runtime())
        uninstall.uninstall(self.home,self.cli)
        prior=(self.home/'.ultra-hook/receipt.json').read_bytes()
        result=self.execute(runtime_check=lambda *_:runtime())
        self.assertEqual((Path(result['backup'])/'receipt.json').read_bytes(),prior)

    def acquisition_fixture(self, *, pending=False, fail=False, bad_hash=False):
        calls=[]
        def provider(destination, *, dry_run=False):
            calls.append((destination,dry_run))
            command=destination/'bin/controller.exe'
            if dry_run:
                return {'status':'plan','command':None if pending else str(command),'provenance':{'source':'synthetic public source'}}
            if fail:
                raise ValueError('synthetic secret diagnostic')
            destination.mkdir(parents=True,exist_ok=True)
            if pending:
                (destination/'public download.dmg').write_bytes(b'public synthetic artifact')
                return {'status':'pending','command':None,'provenance':{'source':'synthetic public source'},
                        'next':'Install the downloaded application and review platform permissions.'}
            reused=command.exists()
            command.parent.mkdir(parents=True,exist_ok=True)
            if not reused:
                command.write_bytes(b'public synthetic controller')
            digest=install.hashlib.sha256(command.read_bytes()).hexdigest()
            return {'status':'reused' if reused else 'acquired','command':str(command),
                    'provenance':{'source':'synthetic public source','binarySha256':'0'*64 if bad_hash else digest}}
        return provider,calls

    def test_joint_dry_run_never_fetches_or_creates_acquisition_directory(self):
        provider,calls=self.acquisition_fixture()
        result=self.execute(dry_run=True,with_agentcontroller=True,acquisition_provider=provider)
        target=self.home/'tools/agentcontroller'
        self.assertEqual(calls,[(target,True)])
        self.assertFalse(target.exists())
        self.assertTrue(result['agentcontroller']['willRegister'])
        self.assertTrue(any(command[-2]=='--' for command in result['commands'] if 'mcp' in command))

    def test_joint_acquisition_registers_verified_launcher_and_reuses_on_repeat(self):
        provider,calls=self.acquisition_fixture()
        before=install.load_config(self.home)
        first=self.execute(with_agentcontroller=True,acquisition_provider=provider,runtime_check=lambda *_:runtime())
        self.assertEqual(first['agentcontroller']['acquisition']['status'],'acquired')
        receipt=json.loads((self.home/'.ultra-hook/receipt.json').read_bytes())
        self.assertTrue(receipt['createdMcp'])
        self.assertEqual(receipt['agentcontrollerAcquisition']['provenance']['binarySha256'],
                         install.hashlib.sha256(b'public synthetic controller').hexdigest())
        second=self.execute(with_agentcontroller=True,acquisition_provider=provider,runtime_check=lambda *_:runtime())
        self.assertEqual(second['agentcontroller']['acquisition']['status'],'reused')
        self.assertEqual(sum(call[:2]==['mcp','add']for call in self.cli.calls),1)
        self.assertEqual(install.protected(install.load_config(self.home),add_mcp=True),install.protected(before,add_mcp=True))
        self.assertEqual([dry for _,dry in calls],[True,False,True,False])

    def test_joint_external_registration_is_reused_without_acquisition_or_ownership(self):
        command=self.root/'existing controller.exe';command.write_bytes(b'external user launcher')
        (self.home/'config.toml').write_text(INITIAL+'\n[mcp_servers.agentcontroller]\ncommand='+json.dumps(str(command))+'\n')
        provider=mock.Mock(side_effect=AssertionError('external registration must not be downloaded again'))
        result=self.execute(with_agentcontroller=True,acquisition_provider=provider,runtime_check=lambda *_:runtime())
        self.assertEqual(result['agentcontroller']['acquisition']['provenance']['method'],'existing-registration')
        self.assertFalse(json.loads((self.home/'.ultra-hook/receipt.json').read_bytes())['createdMcp'])
        self.assertFalse(any(call[:2]==['mcp','add'] for call in self.cli.calls))

    def test_joint_registration_conflicts_and_invalid_options_fail_before_acquisition(self):
        provider=mock.Mock(side_effect=AssertionError('must not acquire'))
        for options in ({'with_agentcontroller':True,'agentcontroller_command':'existing.exe'},
                        {'agentcontroller_dir':self.root/'target'}):
            with self.assertRaises(install.InstallError):
                self.execute(acquisition_provider=provider,**options)
        (self.home/'config.toml').write_text(INITIAL+'\n[mcp_servers.agentcontroller]\nurl="https://synthetic.invalid/mcp"\n')
        with self.assertRaises(install.InstallError):
            self.execute(with_agentcontroller=True,acquisition_provider=provider)
        provider.assert_not_called()

    def test_joint_pending_installation_never_registers_or_claims_transport(self):
        provider,_=self.acquisition_fixture(pending=True)
        result=self.execute(with_agentcontroller=True,acquisition_provider=provider,runtime_check=lambda *_:runtime())
        self.assertEqual(result['status'],'installed')
        self.assertEqual(result['agentcontroller']['acquisition']['status'],'pending')
        self.assertFalse(result['agentcontroller']['registered'])
        self.assertFalse(result['agentcontroller']['willRegister'])
        self.assertNotIn('agentcontroller',install.load_config(self.home).get('mcp_servers',{}))
        self.assertIn('pending',install.human_result('install',result))

    def test_joint_acquisition_failure_keeps_config_and_no_cli_mutations(self):
        provider,_=self.acquisition_fixture(fail=True)
        before=(self.home/'config.toml').read_bytes()
        with self.assertRaises(install.InstallError) as raised:
            self.execute(with_agentcontroller=True,acquisition_provider=provider,runtime_check=lambda *_:runtime())
        self.assertNotIn('synthetic secret',str(raised.exception))
        self.assertEqual((self.home/'config.toml').read_bytes(),before)
        self.assertFalse(any(call[:2] in (['plugin','add'],['mcp','add']) or call[:3]==['plugin','marketplace','add'] for call in self.cli.calls))

    def test_joint_hash_mismatch_and_failed_cli_keep_artifact_without_registration(self):
        provider,_=self.acquisition_fixture(bad_hash=True)
        before=(self.home/'config.toml').read_bytes()
        with self.assertRaises(install.InstallError):
            self.execute(with_agentcontroller=True,acquisition_provider=provider,runtime_check=lambda *_:runtime())
        self.assertEqual((self.home/'config.toml').read_bytes(),before)
        self.assertTrue((self.home/'tools/agentcontroller/bin/controller.exe').exists())
        provider,_=self.acquisition_fixture()
        self.cli.fail_add=True
        with self.assertRaises(install.InstallError):
            self.execute(with_agentcontroller=True,acquisition_provider=provider,runtime_check=lambda *_:runtime())
        self.assertEqual((self.home/'config.toml').read_bytes(),before)
        self.assertTrue((self.home/'tools/agentcontroller/bin/controller.exe').exists())
        self.assertNotIn('agentcontroller',install.load_config(self.home).get('mcp_servers',{}))

    def test_joint_receipt_source_failure_happens_before_real_acquisition(self):
        self.execute(runtime_check=lambda *_:runtime())
        self.cli.markets.clear();self.cli.installed=False
        provider,calls=self.acquisition_fixture()
        with self.assertRaises(install.InstallError):
            install.install(self.new_source(),self.home,self.cli,with_agentcontroller=True,
                            acquisition_provider=provider,runtime_check=lambda *_:runtime())
        self.assertTrue(calls)
        self.assertTrue(all(dry_run for _,dry_run in calls))

    def test_joint_provider_safe_prerequisite_errors_remain_actionable(self):
        def provider(destination, *, dry_run=False):
            if dry_run:
                return {'status':'plan','command':str(destination/'controller.exe'),'provenance':{}}
            raise setup_agentcontroller.AcquisitionError('Install Git and the .NET 9 SDK before retrying.')
        with self.assertRaisesRegex(install.InstallError,'Install Git and the .NET 9 SDK'):
            self.execute(with_agentcontroller=True,acquisition_provider=provider,runtime_check=lambda *_:runtime())

    def test_joint_custom_directory_with_spaces_is_respected(self):
        provider,calls=self.acquisition_fixture()
        target=self.root/'custom controller files'
        result=self.execute(with_agentcontroller=True,agentcontroller_dir=target,acquisition_provider=provider,runtime_check=lambda *_:runtime())
        self.assertEqual(calls,[(target,True),(target,False)])
        self.assertTrue(Path(result['agentcontroller']['acquisition']['command']).is_relative_to(target))
        self.assertFalse((self.home/'tools/agentcontroller').exists())

    def test_joint_profile_receipt_does_not_duplicate_provider_runtime_inventory(self):
        provider,_=self.acquisition_fixture()
        def inventory_provider(destination, *, dry_run=False):
            result=provider(destination,dry_run=dry_run)
            result['provenance']['files']={'public file': '0'*64}
            return result
        result=self.execute(with_agentcontroller=True,acquisition_provider=inventory_provider,runtime_check=lambda *_:runtime())
        self.assertNotIn('files',result['agentcontroller']['acquisition']['provenance'])
        self.assertNotIn('files',json.loads((self.home/'.ultra-hook/receipt.json').read_bytes())['agentcontrollerAcquisition']['provenance'])

    def test_hook_trust_summary_excludes_unrelated_hooks(self):
        hooks = trusted_hooks()
        hooks.append({'pluginId':'unrelated@plugin','enabled':True,'trustStatus':'untrusted'})
        report = doctor.summarize_runtime({'data':[{'hooks':hooks}]}, {'data':[{'skills':
            [{'name':'ultra-hook:ultra-hook'},{'name':'ultra-hook:agentcontroller'},{'name':'cas:review'}]}]},
            plugin_root=install.REPO / 'plugins/ultra-hook')
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
            self.assertIn('timeout', kwargs)
            self.assertNotIn('SYNTHETIC_API_TOKEN', kwargs['env'])
            self.assertNotIn('NUGET_CREDENTIALPROVIDERS_PATH', kwargs['env'])
            self.assertTrue(kwargs['env']['USERPROFILE'].startswith(str(target)))
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
             mock.patch.dict(setup_agentcontroller.os.environ, {'SYNTHETIC_API_TOKEN':'fixture-secret','NUGET_CREDENTIALPROVIDERS_PATH':'fixture-provider'}), \
             mock.patch.object(setup_agentcontroller, 'run_bounded', side_effect=simulated):
            result = setup_agentcontroller.build(target, enabled=True, dotnet_command=dotnet)
        self.assertEqual(result['status'], 'built')
        self.assertEqual((target / 'NOTICE.AgentController').read_text(), 'synthetic upstream notice')
        self.assertEqual((target / 'LICENSE.AgentController').read_text(), 'synthetic Apache license')
        record = json.loads((target / 'source-provenance.json').read_text())
        self.assertEqual(record['binarySha256'], install.hashlib.sha256(b'synthetic build output').hexdigest())
        self.assertEqual(calls[-1][0], str(dotnet.resolve()))


def subprocess_if_available():
    return setup_agentcontroller.subprocess


class OutputTests(unittest.TestCase):
    def result(self, ready=False):
        return {'status':'installed','version':'0.1.2','codexHome':'synthetic profile with spaces',
                'commands':[],'runtime':{**runtime(ready),'hookDefinitionsMatch':True},
                'agentcontroller':{'registered':False,'willRegister':False},'migrationPending':False}

    def invoke(self, module, args, result=None, error=None):
        target = 'install' if module is install else 'inspect' if module is doctor else 'uninstall'
        stdout,stderr=io.StringIO(),io.StringIO()
        with mock.patch.object(sys,'argv',[module.__name__+'.py']+args), \
             mock.patch.object(module,'CLI',return_value=object()), \
             mock.patch.object(module,'codex_home',return_value=Path('synthetic profile')), \
             mock.patch.object(module,target,return_value=result,side_effect=error), \
             redirect_stdout(stdout),redirect_stderr(stderr):
            code=module.main()
        return code,stdout.getvalue(),stderr.getvalue()

    def test_install_pending_trust_and_cas_migration_have_safe_next_steps(self):
        result=self.result();result['migrationPending']=True
        code,text,errors=self.invoke(install,[],result)
        self.assertEqual(code,0)
        self.assertEqual(errors,'')
        self.assertIn('open /hooks and review',text)
        self.assertIn('CAS remains enabled',text)
        self.assertIn('--replace-cas',text)
        self.assertIn('UI validation requires',text)
        self.assertNotIn('"status"',text)

    def test_ready_and_idempotent_install_gives_usage_without_ui_pass(self):
        result=self.result(True)
        result['agentcontroller']['registered']=True
        code,text,_=self.invoke(install,[],result)
        self.assertEqual(code,0)
        self.assertIn('Already installed',text)
        self.assertIn('ask Codex to use the Ultra Hook skill',text)
        self.assertIn('does not validate UI behavior',text)

    def test_mismatched_definitions_never_tell_user_to_grant_trust(self):
        result=self.result();result['runtime']['hookDefinitionsMatch']=False
        text=install.human_result('install',result)
        self.assertIn('Compare the installed package before granting hook trust',text)
        self.assertNotIn('open /hooks',text)

    def test_dry_run_describes_exact_action_types_without_claiming_installation(self):
        result={'status':'plan','codexHome':'synthetic profile','commands':[
            ['codex with spaces','plugin','marketplace','add','repo with spaces','--json'],
            ['codex with spaces','plugin','add',install.PLUGIN,'--json'],
            ['codex with spaces','mcp','add','agentcontroller','--','launcher with spaces']]}
        code,text,_=self.invoke(install,['--dry-run'],result)
        self.assertEqual(code,0)
        self.assertIn('Plan only; no changes made.',text)
        self.assertIn('Register the local',text)
        self.assertIn('Register the supplied',text)
        self.assertIn('without --dry-run',text)
        self.assertNotIn('is installed and enabled',text)

    def test_json_success_keeps_existing_objects_for_all_three_commands(self):
        for module,result in ((install,self.result()),(doctor,{'ready':False,'safeMetadata':True}),
                              (uninstall,{'status':'uninstalled','backupsPreserved':True})):
            code,text,errors=self.invoke(module,['--json'],result)
            self.assertEqual(json.loads(text),result)
            self.assertEqual(errors,'')
            self.assertEqual(code,2 if module is doctor else 0)

    def test_json_errors_are_clean_and_private_exceptions_are_withheld(self):
        for module in (install,doctor,uninstall):
            for error in (install.InstallError('safe actionable issue'),ValueError('synthetic secret must not appear')):
                code,text,errors=self.invoke(module,['--json'],error=error)
                self.assertEqual(code,1)
                self.assertEqual(text,'')
                self.assertEqual(json.loads(errors)['status'],'error')
                self.assertNotIn('synthetic secret',errors)

    def test_doctor_distinguishes_catalog_discovery_from_ui_validation_and_exit_codes(self):
        result={'ready':True,'enabled':True,'installed':True,'uiTransportDiscovered':True,
                'agentcontrollerCheckRequested':True,'runtime':{**runtime(True),'hookDefinitionsMatch':True,
                'agentcontrollerRuntime':{'toolCount':52}}}
        code,text,_=self.invoke(doctor,[],result)
        self.assertEqual(code,0)
        self.assertIn('52 tools discovered',text)
        self.assertIn('UI behavior has not been tested',text)
        result['ready']=False;result['runtime']=runtime(False)
        code,_,_=self.invoke(doctor,[],result)
        self.assertEqual(code,2)

    def test_uninstall_human_plan_shows_owned_removal_and_preserves_cas_restore(self):
        result={'status':'plan','commands':[['codex','mcp','remove','agentcontroller']],
                'restoreCas':True,'backupsPreserved':True}
        code,text,_=self.invoke(uninstall,['--dry-run'],result)
        self.assertEqual(code,0)
        self.assertIn('owned AgentController',text)
        self.assertIn('Restore CAS',text)
        self.assertIn('no changes made',text)

    def test_invalid_options_keep_json_clean_and_argparse_exit_code(self):
        for module in (install,doctor,uninstall):
            stdout,stderr=io.StringIO(),io.StringIO()
            with mock.patch.object(sys,'argv',[module.__name__+'.py','--json','--unknown=synthetic-secret']), \
                 redirect_stdout(stdout),redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    module.main()
            self.assertEqual(raised.exception.code,2)
            self.assertEqual(stdout.getvalue(),'')
            self.assertEqual(json.loads(stderr.getvalue())['status'],'error')
            self.assertNotIn('synthetic-secret',stderr.getvalue())

    def test_doctor_next_steps_remind_user_to_keep_custom_profile_options(self):
        result={'ready':False,'enabled':True,'installed':True,'uiTransportDiscovered':False,
                'agentcontroller':{'registered':True},'runtime':{**runtime(),'hookDefinitionsMatch':True}}
        code,text,_=self.invoke(doctor,['--codex-home','synthetic profile with spaces','--cwd','synthetic workspace'],result)
        self.assertEqual(code,2)
        self.assertIn('Reuse any --codex-home, --codex-command and --cwd options',text)

    def test_joint_json_remains_clean_and_human_output_reports_pending_steps(self):
        result=self.result()
        result['agentcontroller']['acquisition']={'status':'pending','command':None,'provenance':{},'next':'Open the downloaded DMG and review required permissions.'}
        code,text,errors=self.invoke(install,['--with-agentcontroller','--json'],result)
        self.assertEqual(code,0)
        self.assertEqual(json.loads(text),result)
        self.assertEqual(errors,'')
        code,text,errors=self.invoke(install,['--with-agentcontroller'],result)
        self.assertIn('combined installation is not complete',text)
        self.assertIn('Open the downloaded DMG',text)
        self.assertIn('Preparing optional AgentController setup',errors)


if __name__ == '__main__':
    unittest.main()
