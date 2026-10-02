"""Build an audited, deterministic source archive from explicit distributable inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'README.md', 'LICENSE', 'NOTICE', 'AGENTS.md', '.gitignore', '.gitattributes'}
DIRECTORIES = ('.agents/plugins', '.github/workflows', 'plugins/ultra-hook', 'scripts', 'tests', 'docs')
EXTENSIONS = {'.py', '.cjs', '.js', '.json', '.md', '.yml', '.yaml'}


def release_files(root):
    files = []
    for name in sorted(ROOT_FILES):
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or linked release input: ' + name)
        files.append(path)
    for directory in DIRECTORIES:
        base = root / directory
        if not base.is_dir() or base.is_symlink():
            raise ValueError('Missing or linked release directory: ' + directory)
        for path in sorted(base.rglob('*')):
            if path.is_symlink() or (getattr(path.lstat(), 'st_file_attributes', 0) & 1024):
                raise ValueError('Linked input refused: ' + path.relative_to(root).as_posix())
            if not path.is_file():
                continue
            if '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            if path.suffix not in EXTENSIONS:
                raise ValueError('Unexpected release input type: ' + path.relative_to(root).as_posix())
            files.append(path)
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def build(root, output):
    version = json.loads((root / 'plugins/ultra-hook/plugin.json').read_text())['version']
    if not __import__('re').fullmatch(r'\d+\.\d+\.\d+(?:-[a-z0-9.]+)?', version):
        raise ValueError('Invalid package version')
    output.mkdir(parents=True, exist_ok=True)
    name = 'ultra-hook-' + version
    destination = output / (name + '.zip')
    with tempfile.TemporaryDirectory(prefix='ultra-hook-release-') as temporary:
        staging = Path(temporary) / name
        staging.mkdir()
        files = release_files(root)
        for source in files:
            target = staging / source.relative_to(root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        checked = subprocess.run([sys.executable, '-B', str(root / 'scripts/audit_release.py'),
                                  '--root', str(staging)], capture_output=True, text=True)
        if checked.returncode:
            # The audit prints classifications/relative paths, never matched values.
            sys.stderr.write(checked.stdout)
            raise ValueError('Release content audit failed')
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for source in files:
                relative = source.relative_to(root)
                data = (staging / relative).read_bytes()
                info = zipfile.ZipInfo(name + '/' + relative.as_posix(), date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    (output / (name + '.sha256')).write_text(digest + '  ' + destination.name + '\n', encoding='ascii')
    return {'archive': destination.name, 'sha256': digest, 'files': len(files), 'version': version}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(build(ROOT, args.output.resolve())))
    except (ValueError, OSError, KeyError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
