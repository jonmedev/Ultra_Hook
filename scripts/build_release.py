"""Build a deterministic archive from an audited, explicit source snapshot."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
from itertools import islice
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('_ultra_release_audit', Path(__file__).with_name('audit_release.py'))
audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(audit)

# Additions are a deliberate release-policy change, not a consequence of a suffix.
RELEASE_FILES = frozenset('''
.agents/plugins/marketplace.json
.claude-plugin/marketplace.json
.claude-plugin/plugin.json
.gitattributes
.github/dependabot.yml
.github/workflows/ci.yml
.github/workflows/release.yml
.gitignore
AGENTS.md
LICENSE
Install.cmd
install.sh
NOTICE
README.md
SECURITY.md
docs/MIGRATION.md
docs/GETTING_STARTED.md
docs/ADVANCED_INSTALL.md
docs/KSTACK_COMPARISON.md
docs/RELEASING.md
docs/RELEASE_TEMPLATE.md
plugins/ultra-hook/.codex-plugin/plugin.json
plugins/ultra-hook/hooks/claude-hooks.json
plugins/ultra-hook/hooks/hook-io.cjs
plugins/ultra-hook/hooks/hooks.json
plugins/ultra-hook/hooks/model-routing.cjs
plugins/ultra-hook/hooks/prompt-routing.cjs
plugins/ultra-hook/hooks/protect-secrets.js
plugins/ultra-hook/hooks/safety-command-parser.cjs
plugins/ultra-hook/hooks/sensitive-command-approval.cjs
plugins/ultra-hook/hooks/session-start.cjs
plugins/ultra-hook/hooks/team-spawn.cjs
plugins/ultra-hook/hooks/tests/claude-runtime.test.cjs
plugins/ultra-hook/hooks/tests/safety-windows.test.cjs
plugins/ultra-hook/hooks/tests/security-boundaries.test.cjs
plugins/ultra-hook/hooks/tests/team-routing.test.cjs
plugins/ultra-hook/plugin.json
plugins/ultra-hook/skills/agentcontroller/SKILL.md
plugins/ultra-hook/skills/agentcontroller/references/windows.md
plugins/ultra-hook/skills/ultra-hook/SKILL.md
plugins/ultra-hook/skills/ultra-hook/references/engineering.md
plugins/ultra-hook/skills/ultra-hook/references/research.md
plugins/ultra-hook/skills/ultra-hook/references/teams-and-models.md
scripts/audit_release.py
scripts/build_release.py
scripts/doctor.py
scripts/install.py
scripts/setup_agentcontroller.py
scripts/uninstall.py
scripts/validate.py
tests/test_audit_release.py
tests/test_build_release.py
tests/test_install.py
tests/test_install_security.py
tests/test_controller_setup.py
tests/controller_smoke.py
'''.split())
RELEASE_DIRS = frozenset(str(parent) for name in RELEASE_FILES
                         for parent in PurePosixPath(name).parents if str(parent) != '.')
MAX_TOTAL_BYTES = 32 * 1024 * 1024


class ReleaseError(ValueError):
    """Only fixed classifications belong in public release diagnostics."""


def release_files(root):
    root = Path(root).absolute()
    if not stat.S_ISDIR(audit.checked_path(root, root).st_mode):
        raise ReleaseError('release-root-not-directory')
    found = set()

    def visit(directory):
        entries = list(islice(directory.iterdir(), len(RELEASE_FILES) + len(RELEASE_DIRS) + 2))
        if len(entries) > len(RELEASE_FILES) + len(RELEASE_DIRS) + 1:
            raise ReleaseError('release-entry-limit')
        for entry in sorted(entries):
            name = entry.relative_to(root).as_posix()
            if name == '.git':
                continue
            info = audit.checked_path(entry, root)
            if stat.S_ISDIR(info.st_mode):
                if name not in RELEASE_DIRS:
                    raise ReleaseError('unexpected-release-directory')
                visit(entry)
            elif name not in RELEASE_FILES:
                raise ReleaseError('unexpected-release-file')
            else:
                found.add(name)
    visit(root)
    if found != RELEASE_FILES:
        raise ReleaseError('missing-release-file')
    return [root / name for name in sorted(found)]


def capture_snapshot(root):
    """Read once, check stability, then audit exactly the bytes used by the ZIP."""
    root = Path(root).absolute()
    paths = release_files(root)
    before = {p: audit.fingerprint(audit.checked_path(p, root)) for p in paths}
    snapshot = {}
    total = 0
    for path in paths:
        data = audit.read_regular(path, root)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise ReleaseError('release-size-limit')
        snapshot[path.relative_to(root).as_posix()] = data
    if paths != release_files(root):
        raise ReleaseError('release-inputs-changed')
    for path in paths:
        if before[path] != audit.fingerprint(audit.checked_path(path, root)):
            raise ReleaseError('release-inputs-changed')
    scanner = audit.Auditor()
    for name, data in snapshot.items():
        scanner.path_checks(name, 'release-snapshot')
        scanner.data_checks(data, name, 'release-snapshot')
    if scanner.findings:
        sys.stderr.write(json.dumps({'findings': scanner.findings}, ensure_ascii=True) + '\n')
        raise ReleaseError('release-content-audit-failed')
    return snapshot


def output_directory(output, root):
    output = Path(output).absolute()
    for component in reversed((output, *output.parents)):
        if component.exists() or component.is_symlink():
            info = component.lstat()
            if audit.linked_stat(info) or not stat.S_ISDIR(info.st_mode):
                raise ReleaseError('unsafe-output-directory')
    # Normalize ordinary parent-relative CLI paths only after checking their links.
    output = Path(os.path.abspath(output))
    if output.resolve().is_relative_to(Path(root).resolve()):
        raise ReleaseError('output-inside-release-inputs')
    output.mkdir(parents=True, exist_ok=True)
    return output


def directory_identity(path):
    info = path.lstat()
    if audit.linked_stat(info) or not stat.S_ISDIR(info.st_mode):
        raise ReleaseError('output-directory-changed')
    return info.st_dev, info.st_ino


def temporary_file(directory):
    descriptor, name = tempfile.mkstemp(prefix='.ultra-release-', suffix='.tmp', dir=directory)
    return os.fdopen(descriptor, 'w+b'), Path(name)


def write_synced(handle, data):
    handle.write(data)
    handle.flush()
    os.fsync(handle.fileno())


def publish_snapshot(snapshot, version, output):
    name = 'ultra-hook-' + version
    destination = output / (name + '.zip')
    checksum = output / (name + '.sha256')
    lock = output / ('.' + name + '.lock')
    identity = directory_identity(output)
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    lock_identity = os.fstat(descriptor)
    os.close(descriptor)
    temporaries = []
    try:
        previous = {}
        for target in (destination, checksum):
            if target.exists() or target.is_symlink():
                previous[target] = (audit.read_regular(target, output, MAX_TOTAL_BYTES),
                                    audit.fingerprint(audit.checked_path(target, output)))
            else:
                previous[target] = (None, None)
        handle, archive_temp = temporary_file(output)
        temporaries.append(archive_temp)
        with handle:
            with zipfile.ZipFile(handle, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                archive.comment = b''
                for relative, data in sorted(snapshot.items()):
                    info = zipfile.ZipInfo(name + '/' + relative, date_time=(2026, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.create_system = 3
                    info.external_attr = 0o100644 << 16
                    info.extra = info.comment = b''
                    archive.writestr(info, data)
            handle.flush()
            os.fsync(handle.fileno())
            handle.seek(0)
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        handle, checksum_temp = temporary_file(output)
        temporaries.append(checksum_temp)
        with handle:
            write_synced(handle, (digest + '  ' + destination.name + '\n').encode('ascii'))
        rollback = None
        if previous[destination][0] is not None:
            handle, rollback = temporary_file(output)
            temporaries.append(rollback)
            with handle:
                write_synced(handle, previous[destination][0])
        if directory_identity(output) != identity:
            raise ReleaseError('output-directory-changed')
        for target, (_, old_info) in previous.items():
            present = target.exists() or target.is_symlink()
            if present != (old_info is not None) or (present and
                    audit.fingerprint(audit.checked_path(target, output)) != old_info):
                raise ReleaseError('output-artifact-changed')
        os.replace(archive_temp, destination)
        try:
            if directory_identity(output) != identity:
                raise ReleaseError('output-directory-changed')
            os.replace(checksum_temp, checksum)
        except (OSError, ValueError):
            if directory_identity(output) != identity:
                raise ReleaseError('release-rollback-unavailable') from None
            if rollback is not None:
                os.replace(rollback, destination)
            else:
                destination.unlink()
            raise ReleaseError('release-publication-failed') from None
        return {'archive': destination.name, 'sha256': digest, 'files': len(snapshot), 'version': version}
    finally:
        if directory_identity(output) == identity:
            for temporary in temporaries:
                temporary.unlink(missing_ok=True)
            if lock.exists() and (lock.lstat().st_dev, lock.lstat().st_ino) == (lock_identity.st_dev, lock_identity.st_ino):
                lock.unlink()


def build(root, output):
    snapshot = capture_snapshot(root)
    try:
        version = json.loads(snapshot['plugins/ultra-hook/plugin.json'])['version']
        compatible = json.loads(snapshot['plugins/ultra-hook/.codex-plugin/plugin.json'])['version']
    except (ValueError, KeyError, TypeError):
        raise ReleaseError('invalid-package-manifest') from None
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-z0-9.]+)?', version) or version != compatible:
        raise ReleaseError('invalid-package-version')
    return publish_snapshot(snapshot, version, output_directory(output, root))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(ROOT, args.output)))
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print('Release build failed; no unverified artifact should be published.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
