"""Adversarial installer fixtures; external temporary profiles only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import json
import unittest
from unittest import mock
from contextlib import contextmanager

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import install
import doctor
import uninstall
import setup_agentcontroller
import test_install as fixtures
runtime = fixtures.runtime


def directory_link(link, target):
    if os.name == 'nt':
        result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(target)],
                                shell=False, capture_output=True, timeout=10)
        if result.returncode:
            raise unittest.SkipTest('Cannot create synthetic junction')
    else:
        link.symlink_to(target, target_is_directory=True)


class SecurityTests(unittest.TestCase):
    setUp = fixtures.InstallerTests.setUp
    tearDown = fixtures.InstallerTests.tearDown
    execute = fixtures.InstallerTests.execute
    def test_linked_state_never_writes_external_backup(self):
        outside = self.root / 'outside private state'
        outside.mkdir()
        directory_link(self.home / '.ultra-hook', outside)
        try:
            with self.assertRaises(install.InstallError):
                self.execute(runtime_check=lambda *_: runtime())
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            (self.home / '.ultra-hook').rmdir() if os.name == 'nt' else (self.home / '.ultra-hook').unlink()

    def test_hardlinked_config_refused_before_cli_mutation(self):
        os.link(self.home / 'config.toml', self.root / 'outside-config.toml')
        with self.assertRaises(install.InstallError):
            self.execute(runtime_check=lambda *_: runtime())
        self.assertFalse(any(call[:2] == ['plugin','add'] for call in self.cli.calls))

    def test_snapshot_change_before_lock_refuses_all_mutations(self):
        real_lock = install.installation_lock
        @contextmanager
        def changed(home):
            config = home / 'config.toml'
            config.write_text(config.read_text().replace('chosen-user-model', 'new-user-model'))
            with real_lock(home) as state:
                yield state
        with mock.patch.object(install, 'installation_lock', changed):
            with self.assertRaises(install.InstallError):
                self.execute(runtime_check=lambda *_: runtime())
        self.assertFalse(any(call[:2] == ['plugin','add'] for call in self.cli.calls))
        self.assertEqual(install.load_config(self.home)['model'], 'new-user-model')

    def test_private_write_compare_rejects_changed_destination(self):
        target = self.home / 'config.toml'
        old = target.read_bytes()
        target.write_bytes(b'model="changed"\n')
        with self.assertRaises(install.InstallError):
            install.write_private(target, b'model="overwritten"\n', expected=old)
        self.assertEqual(target.read_bytes(), b'model="changed"\n')
        self.assertFalse(list(self.home.glob('.ultra-hook-*.tmp')))

    def test_backup_junction_and_hardlinked_receipt_are_rejected(self):
        state = self.home / '.ultra-hook';state.mkdir()
        outside = self.root / 'outside backups';outside.mkdir()
        directory_link(state / 'backups', outside)
        try:
            with self.assertRaises(install.InstallError):
                self.execute(runtime_check=lambda *_: runtime())
            self.assertEqual(list(outside.iterdir()), [])
        finally:
            (state / 'backups').rmdir() if os.name == 'nt' else (state / 'backups').unlink()
        self.execute(runtime_check=lambda *_: runtime())
        os.link(state / 'receipt.json', self.root / 'outside receipt.json')
        with self.assertRaises(install.InstallError):
            uninstall.uninstall(self.home,self.cli)
        self.assertTrue(self.cli.installed)

    def test_uninstall_refuses_upgraded_plugin_and_changed_snapshot(self):
        self.execute(runtime_check=lambda *_: runtime())
        self.cli.version = '9.9.9'
        with self.assertRaises(install.InstallError):
            uninstall.uninstall(self.home,self.cli)
        self.assertTrue(self.cli.installed)

    def test_foreign_cas_change_during_rollback_is_retained(self):
        def changed(*_):
            install.set_plugin_enabled(self.home, install.CAS, False)
            return runtime()
        with self.assertRaises(install.InstallError):
            self.execute(runtime_check=changed)
        self.assertFalse(install.load_config(self.home)['plugins'][install.CAS]['enabled'])

    def test_process_output_and_timeout_are_bounded(self):
        start=time.monotonic()
        with self.assertRaisesRegex(install.InstallError, 'output exceeded'):
            install.run_bounded([sys.executable,'-c','import sys,time;sys.stdout.write("x"*200000);sys.stdout.flush();time.sleep(10)'],max_output=4096,timeout=2)
        with self.assertRaisesRegex(install.InstallError, 'timed out'):
            install.run_bounded([sys.executable,'-c','import time;time.sleep(10)'],timeout=0.15)
        self.assertLess(time.monotonic()-start,4)

    def test_mcp_overrides_are_secret_free_verified_and_share_cwd(self):
        class Discovery:
            home=self.home
            calls=[]
            def run(inner,args,**kwargs):
                inner.calls.append((args,kwargs))
                return [{'name':'odd.name"quoted','enabled':len(inner.calls)==1,
                         'transport':{'env':{'SECRET':'synthetic-never-print'}}}]
        cli=Discovery()
        args=doctor.runtime_arguments(cli,self.repo)
        self.assertNotIn('synthetic-never-print',str(args))
        self.assertIn('enabled=false',args[-1])
        self.assertTrue(all(kwargs['cwd']==self.repo for _,kwargs in cli.calls))
        with mock.patch.object(cli,'run',return_value=[{'name':'managed','enabled':True}]):
            with self.assertRaises(install.InstallError):
                doctor.runtime_arguments(cli,self.repo)

    def test_explicit_mcp_extra_env_or_disabled_is_fail_closed(self):
        command=self.root/'fake executable.exe';command.write_bytes(b'fixture')
        for setting in ('enabled=false','env={SECRET="synthetic-never-print"}'):
            (self.home/'config.toml').write_text(fixtures.INITIAL+'\n[mcp_servers.agentcontroller]\ncommand='+json.dumps(str(command))+'\n'+setting+'\n')
            cli=mock.Mock(home=self.home)
            cli.run.return_value=[{'name':'agentcontroller','enabled':True}]
            with self.assertRaises(install.InstallError):
                doctor.runtime_arguments(cli,self.repo,check_agentcontroller=True)

    def test_duplicate_or_modified_trusted_hooks_never_ready(self):
        hooks=fixtures.trusted_hooks()
        skills={'data':[{'skills':[{'name':'ultra-hook:ultra-hook'},{'name':'ultra-hook:agentcontroller'}]}]}
        root=install.REPO/'plugins/ultra-hook'
        bad=[dict(hook)for hook in hooks];bad[0]['command']+=' --unreviewed'
        self.assertFalse(doctor.summarize_runtime({'data':[{'hooks':bad}]},skills,plugin_root=root)['hooksReady'])
        self.assertFalse(doctor.summarize_runtime({'data':[{'hooks':[hooks[0]]*5}]},skills,plugin_root=root)['hooksReady'])
        self.assertFalse(doctor.summarize_runtime({'data':[{'hooks':hooks,'warnings':['fixture']}]},skills,plugin_root=root)['hooksReady'])
        duplicate={'data':[{'skills':[{'name':'ultra-hook:ultra-hook'}]*2}]}
        self.assertFalse(doctor.summarize_runtime({'data':[{'hooks':hooks}]},duplicate,plugin_root=root)['skillsReady'])

    def test_builder_refuses_linked_destination_before_subprocess(self):
        outside=self.root/'outside build';outside.mkdir()
        link=self.root/'linked build';directory_link(link,outside)
        try:
            with mock.patch.object(setup_agentcontroller,'run_bounded',side_effect=AssertionError('must not run')):
                with self.assertRaises(install.InstallError):
                    setup_agentcontroller.build(link,enabled=True)
            self.assertEqual(list(outside.iterdir()),[])
        finally:
            link.rmdir() if os.name=='nt' else link.unlink()

    def test_cli_failure_after_mutation_is_rolled_back(self):
        original=self.cli.run
        def failing(args,**kwargs):
            result=original(args,**kwargs)
            if args[:2]==['plugin','add']:
                raise install.InstallError('synthetic CLI failed after writing')
            return result
        with mock.patch.object(self.cli,'run',side_effect=failing):
            with self.assertRaises(install.InstallError):
                self.execute(runtime_check=lambda *_:runtime())
        self.assertFalse(self.cli.installed)

    def test_appserver_frame_limit_and_total_timeout_are_bounded(self):
        script=self.root/'fake app server.py'
        cli=mock.Mock(home=self.home,prefix=[sys.executable,str(script)],env=os.environ.copy())
        for body in ('import sys,time;sys.stdout.write("x"*1100000);sys.stdout.flush();time.sleep(10)',
                     'import time;time.sleep(10)'):
            script.write_text(body)
            start=time.monotonic()
            with mock.patch.object(doctor,'runtime_arguments',return_value=[]):
                with self.assertRaises(install.InstallError):
                    doctor.runtime_metadata(cli,self.repo,timeout=0.3)
            self.assertLess(time.monotonic()-start,3)

    def test_already_disabled_synthetic_servers_do_not_get_transportless_overrides(self):
        class SyntheticCatalog:
            home=self.home
            calls=[]
            def run(inner,args,**kwargs):
                inner.calls.append(args)
                if len(inner.calls)>1 and '"bundled-disabled"' in args[-1]:
                    raise install.InstallError('synthetic native invalid transport')
                return [{'name':'local-server','enabled':len(inner.calls)==1},
                        {'name':'bundled-disabled','enabled':False}]
        cli=SyntheticCatalog()
        args=doctor.runtime_arguments(cli,self.repo)
        self.assertNotIn('bundled-disabled',args[-1])
        self.assertIn('"local-server"={enabled=false}',args[-1])
        self.assertEqual(len(cli.calls),2)


if __name__ == '__main__':
    unittest.main()
