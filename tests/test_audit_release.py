"""Privacy checks use synthetic strings assembled at runtime, never real credentials."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('audit_release', Path(__file__).resolve().parents[1] / 'scripts/audit_release.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
