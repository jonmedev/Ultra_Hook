import importlib.util
import contextlib
import hashlib
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
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_release', ROOT / 'scripts/build_release.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
validation_spec = importlib.util.spec_from_file_location('release_validation', ROOT / 'scripts/validate.py')
validator = importlib.util.module_from_spec(validation_spec)
validation_spec.loader.exec_module(validator)


def copy_release(root):
    for name in builder.RELEASE_FILES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())


class ReleaseTests(unittest.TestCase):
    def test_archive_is_deterministic_and_contains_only_distributable_inputs(self):
        with tempfile.TemporaryDirectory(prefix='ultra-package-') as temporary:
            destination = Path(temporary)
            first = builder.build(ROOT, destination)
            second = builder.build(ROOT, destination)
            self.assertEqual(first['sha256'], second['sha256'])
            with zipfile.ZipFile(destination / first['archive']) as archive:
                names = archive.namelist()
                prefix = 'ultra-hook-' + first['version'] + '/'
                self.assertEqual({name.removeprefix(prefix) for name in names}, builder.RELEASE_FILES)
                self.assertEqual(archive.comment, b'')
                for info in archive.infolist():
                    self.assertEqual(info.extra, b'')
                    self.assertEqual(info.comment, b'')
                    self.assertEqual(info.date_time, (2026, 1, 1, 0, 0, 0))
                    self.assertEqual(info.external_attr >> 16, 0o100644)
                self.assertTrue(any(n.endswith('/scripts/install.py') for n in names))
                self.assertTrue(any(n.endswith('/hooks/hooks.json') for n in names))
                self.assertTrue(any(n.endswith('/LICENSE') for n in names))
                for name in names:
                    parts = Path(name).parts
                    self.assertNotIn('.git', parts)
                    self.assertNotIn('..', parts)
                    self.assertNotIn('__pycache__', parts)
                    self.assertFalse(Path(name).is_absolute())
                    self.assertFalse(name.endswith(('.exe', '.jsonl', '.log', '.pyc')))

    def test_unexpected_files_are_rejected_even_in_allowed_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            copy_release(root)
            for name in ('unexpected.md', 'scripts/unreviewed.py', 'docs/extra.json'):
                with self.subTest(name=name):
                    extra = root / name
                    extra.write_text('Public but unapproved input', encoding='utf-8')
                    with self.assertRaisesRegex(builder.ReleaseError, 'unexpected-release-file'):
                        builder.release_files(root)
                    extra.unlink()
            (root / 'empty-extra').mkdir()
            with self.assertRaisesRegex(builder.ReleaseError, 'unexpected-release-directory'):
                builder.release_files(root)

    def test_snapshot_audit_does_not_execute_scanner_from_input_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'source'
            copy_release(root)
            marker = root / 'executed-marker'
            (root / 'scripts/audit_release.py').write_text(
                "from pathlib import Path\nPath(__file__).parents[1].joinpath('executed-marker').touch()\n",
                encoding='utf-8')
            token = 'sk' + '-' + 'S' * 32
            (root / 'README.md').write_text(token, encoding='utf-8')
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr), self.assertRaisesRegex(builder.ReleaseError, 'content-audit'):
                builder.build(root, base / 'output')
            self.assertFalse(marker.exists())
            self.assertNotIn(token, stderr.getvalue())
            self.assertIn('secret-provider-token', stderr.getvalue())

    def test_changes_during_snapshot_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            copy_release(root)
            original = builder.audit.read_regular
            def mutate_after_read(path, base, *args):
                data = original(path, base, *args)
                if path.name == 'README.md':
                    path.write_bytes(data + b'\nConcurrent mutation\n')
                return data
            with mock.patch.object(builder.audit, 'read_regular', side_effect=mutate_after_read):
                with self.assertRaisesRegex(builder.ReleaseError, 'inputs-changed'):
                    builder.capture_snapshot(root)

    def test_changes_after_audit_cannot_enter_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'source'
            copy_release(root)
            old_readme = (root / 'README.md').read_bytes()
            original = builder.publish_snapshot
            token = 'sk' + '-' + 'T' * 32
            def mutate_after_audit(snapshot, version, output):
                (root / 'README.md').write_text(token, encoding='utf-8')
                return original(snapshot, version, output)
            with mock.patch.object(builder, 'publish_snapshot', side_effect=mutate_after_audit):
                result = builder.build(root, base / 'output')
            with zipfile.ZipFile(base / 'output' / result['archive']) as archive:
                data = archive.read('ultra-hook-' + result['version'] + '/README.md')
            self.assertEqual(data, old_readme)
            self.assertNotIn(token.encode(), data)

    def test_hardlinked_source_and_output_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'source'
            copy_release(root)
            outside = base / 'outside.txt'
            outside.write_bytes(b'Synthetic external file')
            target = root / 'README.md'
            target.unlink()
            try:
                os.link(outside, target)
            except OSError:
                self.skipTest('Hardlinks unavailable')
            with self.assertRaisesRegex(builder.audit.InputError, 'hardlinked'):
                builder.build(root, base / 'output')
            target.unlink()
            target.write_bytes((ROOT / 'README.md').read_bytes())
            output = base / 'output'
            output.mkdir()
            version = json.loads((root / 'plugins/ultra-hook/plugin.json').read_bytes())['version']
            os.link(outside, output / ('ultra-hook-' + version + '.zip'))
            with self.assertRaisesRegex(builder.audit.InputError, 'hardlinked'):
                builder.build(root, output)
            self.assertEqual(outside.read_bytes(), b'Synthetic external file')

    def test_failed_archive_write_preserves_previous_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            result = builder.build(ROOT, output)
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            with mock.patch.object(builder.zipfile.ZipFile, 'writestr', side_effect=OSError('synthetic write failure')):
                with self.assertRaises(OSError):
                    builder.build(ROOT, output)
            self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, before)
            self.assertEqual(hashlib.sha256((output / result['archive']).read_bytes()).hexdigest(), result['sha256'])

    def test_checksum_replace_failure_rolls_back_previous_zip(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'source'
            copy_release(root)
            output = base / 'output'
            builder.build(root, output)
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            (root / 'README.md').write_text('A different public revision', encoding='utf-8')
            original_replace = builder.os.replace
            def fail_checksum(source, destination):
                if Path(destination).suffix == '.sha256':
                    raise OSError('synthetic checksum failure')
                return original_replace(source, destination)
            with mock.patch.object(builder.os, 'replace', side_effect=fail_checksum):
                with self.assertRaisesRegex(builder.ReleaseError, 'publication-failed'):
                    builder.build(root, output)
            self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, before)

    def test_concurrent_builder_lock_and_in_tree_output_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'source'
            copy_release(root)
            with self.assertRaisesRegex(builder.ReleaseError, 'output-inside-release-inputs'):
                builder.build(root, root / 'artifacts')
            self.assertFalse((root / 'artifacts').exists())
            output = base / 'output'
            output.mkdir()
            version = json.loads((root / 'plugins/ultra-hook/plugin.json').read_bytes())['version']
            lock = output / ('.ultra-hook-' + version + '.lock')
            lock.write_bytes(b'')
            with self.assertRaises(FileExistsError):
                builder.build(root, output)
            self.assertEqual(list(output.iterdir()), [lock])

    def test_parent_relative_output_path_remains_supported(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'source'
            copy_release(root)
            result = builder.build(root, root / '..' / 'output')
            self.assertTrue((base / 'output' / result['archive']).is_file())

    def test_validation_checks_are_active_under_python_optimization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            copy_release(root)
            manifest = root / 'plugins/ultra-hook/.codex-plugin/plugin.json'
            value = json.loads(manifest.read_bytes())
            value['version'] = '999.0.0'
            manifest.write_text(json.dumps(value), encoding='utf-8')
            for option in ([], ['-O']):
                result = subprocess.run([sys.executable, '-B', *option, str(ROOT / 'scripts/validate.py'),
                                         '--root', str(root)], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 1)
                self.assertNotIn(str(root), result.stderr)
                self.assertIn('Validation failed', result.stderr)

    def test_unsafe_markdown_target_and_node_environment_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'
            copy_release(root)
            (root / 'README.md').write_text('[outside](../../outside.md)', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'outside-release'):
                validator.validate(root)
            (root / 'README.md').write_bytes((ROOT / 'README.md').read_bytes())
            with mock.patch.dict(os.environ, {'NODE_OPTIONS': '--require=missing-synthetic-preload'}):
                self.assertTrue(validator.validate(root)['valid'])

    def test_cli_redacts_unexpected_exceptions(self):
        marker = 'synthetic-private-exception-value'
        stderr = io.StringIO()
        with mock.patch.object(builder, 'build', side_effect=OSError(marker)), contextlib.redirect_stderr(stderr):
            self.assertEqual(builder.main(['--output', 'unused-synthetic-output']), 1)
        self.assertNotIn(marker, stderr.getvalue())
        stderr = io.StringIO()
        with mock.patch.object(validator, 'validate', side_effect=SyntaxError(marker)), contextlib.redirect_stderr(stderr):
            self.assertEqual(validator.main([]), 1)
        self.assertNotIn(marker, stderr.getvalue())


if __name__ == '__main__':
    unittest.main()
