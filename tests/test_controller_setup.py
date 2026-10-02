"""Synthetic acquisition fixtures: no host configuration, downloads, or MCP startup."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import setup_agentcontroller as setup


def linux_archive(extra=None):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w') as archive:
        contents = {'LICENSE': b'synthetic license', 'NOTICE': b'synthetic notice',
                    'Linux/src/agentcontroller_linux/__init__.py': b'',
                    'Linux/src/agentcontroller_linux/__main__.py': b'def main(): return 0\n'}
        contents.update(extra or {})
        for name, data in contents.items():
            archive.writestr('agentcontroller-' + setup.COMMIT + '/' + name, data)
    return result.getvalue()


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.destination = self.root / 'Controller files with spaces'

    def acquire_linux(self):
        with mock.patch.object(setup.sys, 'platform', 'linux'), \
             mock.patch.object(setup, 'download_verified', return_value=linux_archive()):
            return setup.acquire(self.destination)

    def test_dry_run_all_platforms_creates_nothing_and_executes_nothing(self):
        for platform in ('win32', 'linux', 'darwin'):
            with self.subTest(platform=platform), mock.patch.object(setup.sys, 'platform', platform), \
                 mock.patch.object(setup.platform, 'machine', return_value='AMD64'), \
                 mock.patch.object(setup, 'download_verified', side_effect=AssertionError('download')), \
                 mock.patch.object(setup, 'build', side_effect=AssertionError('build')), \
                 mock.patch.object(setup, 'run_bounded', side_effect=AssertionError('execute')):
                result = setup.acquire(self.destination, dry_run=True)
            self.assertEqual(result['status'], 'plan')
            self.assertFalse(self.destination.exists())
            self.assertEqual(result['command'] is None, platform == 'darwin')

    def test_linux_acquisition_reuse_and_runtime_tamper_detection(self):
        result = self.acquire_linux()
        self.assertEqual(result['status'], 'acquired')
        self.assertEqual(result['provenance']['commit'], setup.COMMIT)
        self.assertEqual(result['provenance']['binarySha256'], setup.file_digest(Path(result['command'])))
        self.assertIn(' -I ', Path(result['command']).read_text())
        self.assertIn('No system packages', result['next'])
        with mock.patch.object(setup.sys, 'platform', 'linux'), \
             mock.patch.object(setup, 'download_verified', side_effect=AssertionError('must reuse')):
            self.assertEqual(setup.acquire(self.destination)['status'], 'reused')
            self.assertEqual(setup.acquire(self.destination, dry_run=True)['status'], 'reused')
            (self.destination / 'source/agentcontroller_linux/__main__.py').write_text('changed')
            with self.assertRaisesRegex(setup.AcquisitionError, 'files changed'):
                setup.acquire(self.destination)

    @unittest.skipIf(sys.platform == 'win32', 'POSIX launcher behavior')
    def test_linux_launcher_runs_without_global_pythonpath_or_bytecode_writes(self):
        result = self.acquire_linux()
        process = subprocess.run([result['command']], capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 0, process.stderr)
        with mock.patch.object(setup.sys, 'platform', 'linux'):
            self.assertEqual(setup.acquire(self.destination)['status'], 'reused')

    def test_linux_unexpected_runtime_file_rejected_on_reuse(self):
        self.acquire_linux()
        (self.destination / 'source/agentcontroller_linux/unexpected.py').write_text('synthetic')
        with mock.patch.object(setup.sys, 'platform', 'linux'):
            with self.assertRaisesRegex(setup.AcquisitionError, 'files changed'):
                setup.acquire(self.destination)

    def test_linux_archive_traversal_and_symlink_entries_rejected(self):
        data = linux_archive({'Linux/src/agentcontroller_linux/../../outside.py': b'bad'})
        with self.assertRaises(setup.AcquisitionError):
            setup.install_linux_source(self.destination, data)
        self.assertFalse(self.destination.exists())
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            entry = zipfile.ZipInfo('agentcontroller-' + setup.COMMIT + '/Linux/src/agentcontroller_linux/linked.py')
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            archive.writestr(entry, 'outside')
        with self.assertRaises(setup.AcquisitionError):
            setup.install_linux_source(self.destination, stream.getvalue())

    def test_windows_acquisition_preserves_build_api_and_reuses_without_execution(self):
        def build(destination, runtime, **kwargs):
            self.assertTrue(kwargs['enabled'])
            self.assertEqual(runtime, 'win-arm64')
            (destination / 'bin').mkdir(parents=True)
            (destination / 'bin/agentcontroller-windows.exe').write_bytes(b'synthetic executable')
            for name in ('LICENSE.AgentController', 'NOTICE.AgentController'):
                (destination / name).write_text('synthetic license')
        with mock.patch.object(setup.sys, 'platform', 'win32'), \
             mock.patch.object(setup.platform, 'machine', return_value='ARM64'), \
             mock.patch.object(setup.shutil, 'which', return_value='synthetic-git'), \
             mock.patch.object(setup, 'dotnet_executable', return_value='synthetic-dotnet'), \
             mock.patch.object(setup, 'build', side_effect=build) as called:
            first = setup.acquire(self.destination)
            second = setup.acquire(self.destination)
        self.assertEqual(first['status'], 'acquired')
        self.assertEqual(second['status'], 'reused')
        self.assertEqual(called.call_count, 1)
        self.assertEqual(first['provenance']['commit'], 'bc6db97122d6adf07342d3efc87e7ac7c96b4889')

    def test_missing_windows_prerequisites_are_actionable_and_no_writes(self):
        with mock.patch.object(setup.sys, 'platform', 'win32'), \
             mock.patch.object(setup.platform, 'machine', return_value='AMD64'), \
             mock.patch.object(setup.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(setup.AcquisitionError, 'Install Git and the .NET 9 SDK'):
                setup.acquire(self.destination)
        self.assertFalse(self.destination.exists())

    def test_windows_missing_architecture_environment_uses_interpreter_build(self):
        for compiled, runtime in [('win-amd64', 'win-x64'), ('win-arm64', 'win-arm64')]:
            with mock.patch.object(setup.sys, 'platform', 'win32'), \
                 mock.patch.object(setup.platform, 'machine', return_value=''), \
                 mock.patch.object(setup.sysconfig, 'get_platform', return_value=compiled):
                result = setup.acquire(self.destination, dry_run=True)
            self.assertEqual(result['provenance']['runtime'], runtime)

    def test_windows_long_destination_fails_before_download_build_or_writes(self):
        target = self.root / ('x' * 115)
        with mock.patch.object(setup.sys, 'platform', 'win32'), \
             mock.patch.object(setup, 'download_verified', side_effect=AssertionError('download')), \
             mock.patch.object(setup, 'build', side_effect=AssertionError('build')), \
             mock.patch.object(setup, 'run_bounded', side_effect=AssertionError('execute')):
            for dry_run in (False, True):
                with self.assertRaisesRegex(setup.AcquisitionError, 'shorter --agentcontroller-dir'):
                    setup.acquire(target, dry_run=dry_run)
        with self.assertRaisesRegex(setup.AcquisitionError, 'at most 100'):
            setup.plan(target)
        self.assertFalse(target.exists())

    def test_windows_destination_length_boundary_counts_utf16_units(self):
        setup.check_windows_destination('x' * 100)
        with self.assertRaises(setup.AcquisitionError):
            setup.check_windows_destination('x' * 101)
        with self.assertRaises(setup.AcquisitionError):
            setup.check_windows_destination('x' * 99 + '\U0001f4c1')

    def test_macos_only_downloads_verified_dmg_and_stays_pending_on_reuse(self):
        data = b'synthetic dmg'
        with mock.patch.object(setup.sys, 'platform', 'darwin'), \
             mock.patch.object(setup, 'MAC_SHA256', hashlib.sha256(data).hexdigest()), \
             mock.patch.object(setup, 'download_verified', return_value=data) as download, \
             mock.patch.object(setup, 'run_bounded', side_effect=AssertionError('no mount or server')):
            for _ in range(2):
                result = setup.acquire(self.destination)
                self.assertEqual(result['status'], 'pending')
                self.assertIsNone(result['command'])
                self.assertIn('Screen Recording', result['next'])
                self.assertIn('bridge', result['next'])
                self.assertEqual(result['provenance']['requiredArchitecture'], 'arm64')
                self.assertEqual(result['provenance']['minimumMacOS'], '14.0')
            self.assertEqual(download.call_count, 1)
            (self.destination / 'AgentController-2.5.0.dmg').write_bytes(b'changed')
            with self.assertRaises(setup.AcquisitionError):
                setup.acquire(self.destination)

    def test_mac_plan_reports_requirements_without_claiming_host_support(self):
        for machine, version in [('x86_64', '14.0'), ('arm64', '13.6'), ('arm64', '15.0')]:
            with self.subTest(machine=machine, version=version), \
                 mock.patch.object(setup.sys, 'platform', 'darwin'), \
                 mock.patch.object(setup.platform, 'machine', return_value=machine), \
                 mock.patch.object(setup.platform, 'mac_ver', return_value=(version, ('', '', ''), machine)):
                result = setup.acquire(self.destination, dry_run=True)
            self.assertIsNone(result['command'])
            self.assertIn('does not support Intel Macs', result['next'])
            self.assertIn('macOS 14 Sonoma or later', result['next'])
            self.assertIn('Host compatibility has not been verified', result['next'])
            self.assertFalse(self.destination.exists())

    def test_digest_ignores_stat_fstat_executable_mode_differences(self):
        executable = self.root / 'synthetic.exe'
        content = b'synthetic executable'
        executable.write_bytes(content)
        info = executable.stat()
        fingerprint = {key: getattr(info, key) for key in ('st_dev', 'st_ino', 'st_nlink', 'st_size', 'st_mtime_ns')}
        # Windows Python versions differ in executable permission bits reported
        # by path stat and handle fstat; these bits are not file identity.
        handle_info = SimpleNamespace(**fingerprint, st_mode=info.st_mode ^ 0o111)
        with mock.patch.object(setup.os, 'fstat', return_value=handle_info):
            self.assertEqual(setup.file_digest(executable), hashlib.sha256(content).hexdigest())

    def test_existing_unowned_directory_is_not_overwritten(self):
        self.destination.mkdir()
        existing = self.destination / 'keep.txt'
        existing.write_text('keep')
        with self.assertRaisesRegex(setup.AcquisitionError, 'not empty'):
            setup.acquire(self.destination)
        self.assertEqual(existing.read_text(), 'keep')

    def test_corrupt_or_foreign_receipt_does_not_execute(self):
        self.acquire_linux()
        record = self.destination / setup.RECEIPT
        data = json.loads(record.read_text())
        data['commit'] = 'untrusted'
        record.write_text(json.dumps(data))
        with mock.patch.object(setup.sys, 'platform', 'linux'), \
             mock.patch.object(setup, 'run_bounded', side_effect=AssertionError('no execution')):
            with self.assertRaisesRegex(setup.AcquisitionError, 'provenance'):
                setup.acquire(self.destination)

    def test_hardlinked_runtime_rejected(self):
        result = self.acquire_linux()
        try:
            (self.root / 'outside-link').hardlink_to(result['command'])
        except OSError:
            self.skipTest('host lacks hardlink support')
        with mock.patch.object(setup.sys, 'platform', 'linux'):
            with self.assertRaises(setup.AcquisitionError):
                setup.acquire(self.destination)

    def test_network_errors_are_redacted(self):
        with mock.patch.object(setup.sys, 'platform', 'linux'), \
             mock.patch.object(setup, 'download_verified', side_effect=OSError('synthetic private diagnostics')):
            with self.assertRaises(setup.AcquisitionError) as raised:
                setup.acquire(self.destination)
        self.assertNotIn('synthetic private', str(raised.exception))


class DownloadTests(unittest.TestCase):
    def response(self, data):
        response = io.BytesIO(data)
        response.geturl = lambda: setup.MAC_URL
        return response

    def test_checksum_and_byte_limit(self):
        for content, digest, limit in [(b'actual', '0' * 64, 100), (b'oversized', hashlib.sha256(b'oversized').hexdigest(), 4)]:
            with self.subTest(limit=limit), mock.patch.object(setup.urllib.request, 'build_opener') as opener, \
                 mock.patch.object(setup, 'MAX_DOWNLOAD', limit):
                opener.return_value.open.return_value = self.response(content)
                with self.assertRaises(setup.AcquisitionError):
                    setup.download_verified(setup.MAC_URL, digest)

    def test_unexpected_or_insecure_endpoint_rejected_before_network(self):
        credential_url = 'https://' + 'user' + '@' + 'github.com/file'
        for url in ('http://github.com/file', 'https://example.invalid/file', credential_url):
            with mock.patch.object(setup.urllib.request, 'build_opener', side_effect=AssertionError('network')):
                with self.assertRaises(setup.AcquisitionError):
                    setup.download_verified(url, '0' * 64)

    def test_redirect_checks_endpoint_before_following(self):
        with mock.patch.object(setup.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = self.response(b'valid')
            self.assertEqual(setup.download_verified(setup.MAC_URL, hashlib.sha256(b'valid').hexdigest()), b'valid')
        redirects = opener.call_args.args[0]
        with self.assertRaises(setup.AcquisitionError):
            redirects.redirect_request(None, None, 302, 'redirect', {}, 'http://github.com/insecure')


if __name__ == '__main__':
    unittest.main()
