import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_release', ROOT / 'scripts/build_release.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ReleaseTests(unittest.TestCase):
    def test_archive_is_deterministic_and_contains_only_distributable_inputs(self):
        with tempfile.TemporaryDirectory(prefix='ultra-package-') as temporary:
            destination = Path(temporary)
            first = builder.build(ROOT, destination)
            second = builder.build(ROOT, destination)
            self.assertEqual(first['sha256'], second['sha256'])
            with zipfile.ZipFile(destination / first['archive']) as archive:
                names = archive.namelist()
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


if __name__ == '__main__':
    unittest.main()
