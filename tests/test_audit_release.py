"""Privacy checks use synthetic strings assembled at runtime, never real credentials."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('audit_release', Path(__file__).resolve().parents[1] / 'scripts/audit_release.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
    def test_child_stdout_is_bounded_while_running_and_timeout_is_redacted(self):
        command = [sys.executable, '-B', '-c', 'import os,time; os.write(1,b"x"*4096); time.sleep(10)']
        with self.assertRaisesRegex(audit.InputError, 'git-output-size-limit'):
            audit.bounded_command(command, max_bytes=32, timeout=3)
        with self.assertRaisesRegex(audit.InputError, 'git-scan-timeout'):
            audit.bounded_command([sys.executable, '-B', '-c', 'import time; time.sleep(10)'], timeout=0.1)
        self.assertEqual(audit.bounded_command([sys.executable, '-B', '-c',
                         'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())'],
                         input_data=b'synthetic round trip'), b'synthetic round trip')

    def test_total_git_scan_deadline_prevents_further_children(self):
        scanner = audit.Auditor()
        scanner.git_deadline = 0
        with mock.patch.object(audit, 'bounded_command') as runner:
            with self.assertRaisesRegex(audit.InputError, 'git-scan-timeout'):
                scanner.git(Path('.'), ['rev-parse', '--show-toplevel'])
            runner.assert_not_called()

    def test_hardlinked_working_file_is_rejected_without_reading_target(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'source'
            root.mkdir()
            outside = base / 'outside.txt'
            outside.write_text('ordinary synthetic data', encoding='utf-8')
            try:
                os.link(outside, root / 'linked.txt')
            except OSError:
                self.skipTest('Hardlinks unavailable on this filesystem')
            scanner = audit.Auditor()
            scanner.working_tree(root)
            self.assertEqual(scanner.checked, 0)
            self.assertIn('hardlinked-file', {item['kind'] for item in scanner.findings})

    def test_file_changed_between_stat_and_open_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'fixture.txt'
            source.write_bytes(b'initial')
            original_open = audit.os.open
            def change_before_open(path, flags):
                source.write_bytes(b'changed synthetic input')
                return original_open(path, flags)
            with mock.patch.object(audit.os, 'open', side_effect=change_before_open):
                with self.assertRaisesRegex(audit.InputError, 'input-changed'):
                    audit.read_regular(source, root)

    def test_read_limit_and_special_reparse_metadata_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'fixture.txt'
            source.write_bytes(b'12345')
            with self.assertRaisesRegex(audit.InputError, 'scan-size-limit'):
                audit.read_regular(source, root, 4)
            metadata = mock.Mock(st_mode=0o100644, st_file_attributes=1024)
            self.assertTrue(audit.linked_stat(metadata))

    def test_scanner_exception_details_are_not_printed(self):
        marker = 'synthetic-sensitive-exception'
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
                audit.Auditor, 'working_tree', side_effect=OSError(marker)):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = audit.main(['--root', directory])
            self.assertEqual(status, 1)
            self.assertNotIn(marker, output.getvalue())
            self.assertEqual(json.loads(output.getvalue())['findings'][0]['kind'], 'scan-incomplete')

    def test_bot_noreply_allowance_applies_only_to_identity_headers(self):
        email = '49699333+' + 'dependabot[bot]' + '@' + 'users.noreply.github.com'
        payload = ('author Dependency Bot <' + email + '> 1 +0000\n'
                   'committer Dependency Bot <' + email + '> 1 +0000\n\nPublic message').encode()
        scanner = audit.Auditor(allow_github_noreply_identities=True)
        scanner.data_checks(scanner.public_commit_identities(payload), '<git-commit>', 'git-history')
        self.assertFalse(scanner.findings)
        scanner.data_checks(scanner.public_commit_identities(payload + b'\n' + email.encode()),
                            '<git-commit>', 'git-history')
        self.assertIn('private-email', {item['kind'] for item in scanner.findings})
        self.assertNotIn(email, json.dumps(scanner.findings))

    def test_common_private_patterns_report_no_values(self):
        token = 'sk' + '-' + 'A' * 32
        email = 'private-fixture' + '@' + 'example.test'
        user_path = 'C:' + '/Users/' + 'fixture-user/private.txt'
        uuid = '-'.join(['12345678', '1234', '1234', '1234', '123456789012'])
        scanner = audit.Auditor()
        scanner.data_checks(('safe\n' + '\n'.join([token, email, user_path, uuid])).encode(), 'fixture.txt')
        self.assertEqual({item['kind'] for item in scanner.findings},
                         {'secret-provider-token', 'private-email', 'absolute-user-path', 'session-uuid'})
        report = json.dumps(scanner.findings)
        for value in [token, email, user_path, uuid]:
            self.assertNotIn(value, report)
        self.assertTrue(all(item['line'] >= 2 for item in scanner.findings))

    def test_filename_private_terms_are_redacted(self):
        private = 'synthetic' + '-owner'
        scanner = audit.Auditor([private])
        scanner.path_checks(private + '/README.md')
        self.assertNotIn(private, json.dumps(scanner.findings))
        self.assertEqual(scanner.findings[0]['kind'], 'local-private-term')

    def test_unquoted_assignments_bearer_and_url_credentials(self):
        scanner = audit.Auditor()
        assignment = 'api' + '_key=' + 'D' * 32
        bearer = 'Bear' + 'er ' + 'E' * 32
        url = 'https:' + '//fixture:' + 'F' * 16 + '@example.test/'
        scanner.data_checks('\n'.join([assignment, bearer, url]).encode(), 'fixture.txt')
        self.assertTrue({'secret-assignment', 'secret-bearer', 'credential-url'} <=
                        {item['kind'] for item in scanner.findings})
        for value in [assignment, bearer, url]:
            self.assertNotIn(value, json.dumps(scanner.findings))

    def test_public_noreply_exemption_is_commit_identity_only(self):
        email = '12345+' + 'public-fixture' + '@' + 'users.noreply.github.com'
        private = 'private-fixture' + '@' + 'example.test'
        commit = ('author Fixture <' + email + '> 1 +0000\n'
                  'committer Fixture <' + email + '> 1 +0000\n\nPublic message').encode()
        scanner = audit.Auditor(allow_github_noreply_identities=True)
        scanner.data_checks(scanner.public_commit_identities(commit), '<git-commit>', 'git-history')
        self.assertFalse(scanner.findings)
        for payload in [(commit + b'\n' + email.encode()),
                        commit.replace(email.encode(), private.encode())]:
            scanner = audit.Auditor(allow_github_noreply_identities=True)
            scanner.data_checks(scanner.public_commit_identities(payload), '<git-commit>', 'git-history')
            self.assertIn('private-email', {item['kind'] for item in scanner.findings})
        scanner = audit.Auditor(allow_github_noreply_identities=True)
        scanner.data_checks(commit, 'fixture.txt')
        self.assertIn('private-email', {item['kind'] for item in scanner.findings})

    def test_public_email_allowance_does_not_exempt_other_data(self):
        email = 'public-maintainer' + '@' + 'example.test'
        scanner = audit.Auditor(allowed_emails=[email])
        scanner.data_checks((email + '\n' + 'sk' + '-' + 'B' * 32).encode(), 'NOTICE')
        self.assertEqual([item['kind'] for item in scanner.findings], ['secret-provider-token'])

    def test_tree_rejects_local_artifacts_binary_and_large_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'README.md').write_text('Portable instructions', encoding='utf-8')
            (root / '.env').write_text('synthetic fixture', encoding='utf-8')
            (root / 'cache').mkdir()
            (root / 'fixture.exe').write_bytes(bytes([0, 255]))
            (root / 'large.txt').write_text('x' * 20, encoding='utf-8')
            scanner = audit.Auditor(max_bytes=16)
            scanner.working_tree(root)
            kinds = {item['kind'] for item in scanner.findings}
            self.assertTrue({'credential-file', 'local-artifact', 'binary-artifact', 'scan-size-limit'} <= kinds)

    def test_unreadable_encoding_fails_closed(self):
        scanner = audit.Auditor()
        scanner.data_checks(bytes([255, 254]), 'fixture.txt')
        self.assertEqual(scanner.findings[0]['kind'], 'non-utf8-artifact')

    def test_symlink_not_followed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / 'target.txt'
            target.write_text('ordinary text', encoding='utf-8')
            try:
                (root / 'link.txt').symlink_to(target)
            except OSError:
                self.skipTest('Creating symlinks is unavailable in this session')
            scanner = audit.Auditor()
            scanner.working_tree(root)
            self.assertIn('symlink-or-reparse-point', {item['kind'] for item in scanner.findings})
            self.assertEqual(scanner.checked, 1)

    @unittest.skipUnless(shutil.which('git'), 'Git unavailable')
    def test_archive_subdirectory_does_not_scan_parent_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = subprocess.run(['git', '-C', str(root), 'init', '--quiet'], capture_output=True, shell=False)
            self.assertEqual(result.returncode, 0)
            extracted = root / 'extracted-archive'
            extracted.mkdir()
            for operation in ('staged', 'history'):
                with self.assertRaisesRegex(ValueError, 'git-root-mismatch'):
                    getattr(audit.Auditor(), operation)(extracted)

    @unittest.skipUnless(shutil.which('git'), 'Git unavailable')
    def test_annotated_public_tag_is_allowed_but_tag_message_is_scanned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, shell=False)
                self.assertEqual(result.returncode, 0)
            git('init', '--quiet')
            git('config', 'user.name', 'Public Fixture')
            email = '12345+' + 'public-fixture' + '@' + 'users.noreply.github.com'
            git('config', 'user.email', email)
            (root / 'README.md').write_text('Public source', encoding='utf-8')
            git('add', 'README.md')
            git('commit', '--quiet', '-m', 'Public fixture')
            git('tag', '-a', 'v0.1.0', '-m', 'Public release')
            clean = audit.Auditor(allow_github_noreply_identities=True)
            clean.history(root)
            self.assertFalse(clean.findings)
            git('tag', '-a', 'v0.2.0', '-m', 'Address in message: ' + email)
            dirty = audit.Auditor(allow_github_noreply_identities=True)
            dirty.history(root)
            self.assertIn('private-email', {item['kind'] for item in dirty.findings})

    @unittest.skipUnless(shutil.which('git'), 'Git unavailable')
    def test_index_and_history_detect_deleted_private_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                completed = subprocess.run(['git', '-C', str(root), *args], capture_output=True, shell=False)
                self.assertEqual(completed.returncode, 0)
            git('init', '--quiet')
            git('config', 'user.name', 'Public Fixture')
            email = 'fixture' + '@' + 'example.test'
            git('config', 'user.email', email)
            token = 'sk' + '-' + 'C' * 32
            fixture = root / 'fixture.txt'
            fixture.write_text(token, encoding='utf-8')
            git('add', 'fixture.txt')
            staged = audit.Auditor(allowed_emails=[email])
            staged.staged(root)
            self.assertEqual(staged.findings[0]['kind'], 'secret-provider-token')
            git('commit', '--quiet', '-m', 'Synthetic fixture')
            fixture.write_text('Clean current contents', encoding='utf-8')
            git('add', 'fixture.txt')
            git('commit', '--quiet', '-m', 'Remove synthetic private fixture')
            clean = audit.Auditor(allowed_emails=[email])
            clean.working_tree(root)
            self.assertFalse(clean.findings)
            clean.history(root)
            self.assertIn('secret-provider-token', {item['kind'] for item in clean.findings})
            self.assertNotIn(token, json.dumps(clean.findings))

    @unittest.skipUnless(shutil.which('git'), 'Git unavailable')
    def test_history_checks_modes_and_all_paths_of_shared_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                completed = subprocess.run(['git', '-C', str(root), *args], capture_output=True, shell=False)
                self.assertEqual(completed.returncode, 0)
                return completed.stdout
            git('init', '--quiet')
            git('config', 'user.name', 'Public Fixture')
            email = 'fixture' + '@' + 'example.test'
            git('config', 'user.email', email)
            (root / 'README.md').write_text('Same benign content', encoding='utf-8')
            (root / '.env').write_text('Same benign content', encoding='utf-8')
            git('add', '.')
            oid = git('hash-object', 'README.md').decode().strip()
            git('update-index', '--add', '--cacheinfo', '120000', oid, 'historical-link')
            git('commit', '--quiet', '-m', 'Synthetic path and mode fixture')
            scanner = audit.Auditor(allowed_emails=[email])
            scanner.history(root)
            kinds = {item['kind'] for item in scanner.findings}
            self.assertTrue({'credential-file', 'symlink-or-reparse-point'} <= kinds)

    @unittest.skipUnless(shutil.which('git'), 'Git unavailable')
    def test_refs_replace_objects_and_inherited_index_cannot_hide_private_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args, env=None):
                result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                                        shell=False, env=env)
                self.assertEqual(result.returncode, 0)
                return result.stdout
            git('init', '--quiet')
            git('config', 'user.name', 'Public Fixture')
            email = 'fixture' + '@' + 'example.test'
            git('config', 'user.email', email)
            token = 'sk' + '-' + 'R' * 32
            path = root / 'fixture.txt'
            path.write_text(token, encoding='utf-8')
            git('add', 'fixture.txt')
            git('commit', '--quiet', '-m', 'Synthetic initial input')
            secret_oid = git('rev-parse', 'HEAD:fixture.txt').decode().strip()
            path.write_text('Public replacement', encoding='utf-8')
            clean_oid = git('hash-object', '-w', 'fixture.txt').decode().strip()
            git('replace', secret_oid, clean_oid)
            git('branch', 'branch-' + token)
            scanner = audit.Auditor(allowed_emails=[email])
            scanner.history(root)
            self.assertTrue(any(f['kind'] == 'secret-provider-token' and f['origin'] == 'git-refs'
                                for f in scanner.findings))
            self.assertTrue(any(f['kind'] == 'secret-provider-token' and f['origin'].startswith('git-history:')
                                for f in scanner.findings))
            self.assertNotIn(token, json.dumps(scanner.findings))
            decoy = root / '.git' / 'decoy-index'
            decoy_env = {**os.environ, 'GIT_INDEX_FILE': str(decoy)}
            git('read-tree', '--empty', env=decoy_env)
            with mock.patch.dict(os.environ, {'GIT_INDEX_FILE': str(decoy)}):
                scanner = audit.Auditor()
                scanner.staged(root)
            self.assertIn('secret-provider-token', {f['kind'] for f in scanner.findings})
            commit = git('rev-parse', 'HEAD').strip()
            (root / '.git' / 'shallow').write_bytes(commit + b'\n')
            scanner = audit.Auditor(allowed_emails=[email])
            scanner.history(root)
            self.assertEqual(scanner.findings[0]['kind'], 'shallow-history-unscanned')


if __name__ == '__main__':
    unittest.main()
