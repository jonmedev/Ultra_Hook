#!/usr/bin/env python3
"""Check publication inputs for known private-data patterns and local artifacts."""
from __future__ import annotations

import argparse
from itertools import islice
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import threading
import time

MAX_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 10000
MAX_DEPTH = 64
MAX_GIT_BYTES = 16 * 1024 * 1024
GIT_SCAN_SECONDS = 120
BINARY_SUFFIXES = {'.exe', '.dll', '.pdb', '.so', '.dylib', '.pyc', '.zip', '.7z',
                   '.tar', '.gz', '.sqlite', '.db', '.dmp', '.png', '.jpg', '.jpeg',
                   '.gif', '.mp4', '.pdf', '.docx', '.xlsx', '.pptx'}
LOCAL_PARTS = {'.git', '.codex', '.claude', '.commandcode', '.agentcontroller', '.cas',
               '__pycache__', 'node_modules', '.pytest_cache', '.venv', 'venv',
               'hooks-logs', 'logs', 'cache', 'caches', 'publish', 'dist', 'bin', 'obj'}
LOCAL_NAMES = {'installation.json', 'models_cache.json', 'credentials.json',
               'auth.json', 'mcp-token', 'mcp-port', '.cas-text-specialist'}
PATTERNS = {
    'secret-aws-key': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'secret-provider-token': re.compile(r'\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,})\b'),
    'secret-private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----'),
    'secret-jwt': re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b'),
    'secret-assignment': re.compile(r'''(?im)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|secret[_-]?key)\s*["']?\s*[:=]\s*["']?([A-Za-z0-9+/=_-]{16,})(?=["'\s,;]|$)'''),
    'secret-bearer': re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/-]{24,}'),
    'credential-url': re.compile(r'(?i)\bhttps?://[^\s/:@]+:[^\s/@]{8,}@'),
    'absolute-user-path': re.compile(r'''(?i)(?:[A-Z]:[\\/]+(?:Users|Documents and Settings)[\\/]+[^\s<>$%"'\\/]+|/(?:Users|home)/[^\s<>$%"'/]+)'''),
    'private-email': re.compile(r'(?i)\b[A-Z0-9.!#$%&*+/=?^_`{|}~-]+(?:\[bot\])?@[A-Z0-9.-]+\.[A-Z]{2,}\b'),
    'session-uuid': re.compile(r'(?i)\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b'),
}
PUBLIC_NOREPLY = re.compile(r'(?:[0-9]+\+)?[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?(?:\[bot\])?@users\.noreply\.github\.com')


class InputError(ValueError):
    """An input failure identified by a safe classification, never raw OS text."""


def linked_stat(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024))


def fingerprint(info, *, descriptor_comparison=False):
    mode = info.st_mode
    if descriptor_comparison and os.name == 'nt':
        # Windows pathname stat synthesizes execute bits for .cmd/.bat/.com/.exe
        # names; descriptor fstat has no filename and omits them (Python 3.11).
        # Normalize only that cross-API difference. Same-API snapshots below
        # still compare every mode bit, and all identity/link/time fields remain.
        mode &= ~0o111
    return (info.st_dev, info.st_ino, mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def checked_path(path, root):
    """Reject links and special files without resolving away their identities."""
    path, root = Path(path).absolute(), Path(root).absolute()
    if not path.is_relative_to(root) or '..' in path.parts:
        raise InputError('path-outside-root')
    components = [root]
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        components.append(current)
    for component in components:
        info = component.lstat()
        if linked_stat(info):
            raise InputError('symlink-or-reparse-point')
        if component != path and not stat.S_ISDIR(info.st_mode):
            raise InputError('nonregular-file')
    info = path.lstat()
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise InputError('hardlinked-file')
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise InputError('nonregular-file')
    return info


def read_regular(path, root, max_bytes=MAX_BYTES):
    """Read a bounded stable regular file; callers audit the returned immutable bytes.

    Descriptor checks and no-follow where available narrow pathname races. This is
    not an OS sandbox against a hostile process controlling parent directories.
    """
    before = checked_path(path, root)
    if not stat.S_ISREG(before.st_mode):
        raise InputError('nonregular-file')
    if before.st_size > max_bytes:
        raise InputError('scan-size-limit')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if fingerprint(opened, descriptor_comparison=True) != fingerprint(before, descriptor_comparison=True):
            raise InputError('input-changed-during-read')
        data = bytearray()
        while len(data) <= max_bytes:
            block = os.read(descriptor, min(65536, max_bytes + 1 - len(data)))
            if not block:
                break
            data.extend(block)
        if len(data) > max_bytes:
            raise InputError('scan-size-limit')
        if fingerprint(os.fstat(descriptor)) != fingerprint(opened):
            raise InputError('input-changed-during-read')
    finally:
        os.close(descriptor)
    if fingerprint(checked_path(path, root)) != fingerprint(before):
        raise InputError('input-changed-during-read')
    return bytes(data)


def bounded_command(command, *, input_data=None, env=None, timeout=60, max_bytes=MAX_GIT_BYTES):
    """Bound stdout while the child runs; discard stderr that can contain secrets."""
    if input_data is not None and len(input_data) > max_bytes:
        raise InputError('git-input-size-limit')
    process = subprocess.Popen(command, stdin=subprocess.PIPE if input_data is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, shell=False, env=env,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    data = bytearray()
    limit_hit = threading.Event()
    read_failed = threading.Event()

    def read_output():
        try:
            while True:
                chunk = os.read(process.stdout.fileno(), min(65536, max_bytes + 1))
                if not chunk:
                    break
                if len(data) + len(chunk) > max_bytes:
                    limit_hit.set()
                    process.kill()
                    break
                data.extend(chunk)
        except OSError:
            read_failed.set()
        finally:
            process.stdout.close()

    def write_input():
        try:
            process.stdin.write(input_data)
        except OSError:
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    writer = None
    if input_data is not None:
        writer = threading.Thread(target=write_input, daemon=True)
        writer.start()
    try:
        status = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        raise InputError('git-scan-timeout') from None
    finally:
        reader.join(timeout=2)
        if writer is not None:
            writer.join(timeout=2)
    if limit_hit.is_set():
        raise InputError('git-output-size-limit')
    if status or read_failed.is_set() or reader.is_alive() or (writer is not None and writer.is_alive()):
        raise InputError('git-scan-failed')
    return bytes(data)


class Auditor:
    def __init__(self, private_terms=(), allowed_emails=(), max_bytes=MAX_BYTES,
                 allow_github_noreply_identities=False):
        self.private_terms = tuple(term for term in private_terms if term)
        self.allowed_emails = {email.casefold() for email in allowed_emails}
        self.max_bytes = max_bytes
        self.allow_github_noreply_identities = allow_github_noreply_identities
        self.findings = []
        self.checked = 0
        self.git_deadline = None

    def display_path(self, name):
        name = str(name).replace('\\', '/')
        for term in self.private_terms:
            name = re.sub(re.escape(term), '<redacted>', name, flags=re.IGNORECASE)
        for pattern in PATTERNS.values():
            name = pattern.sub('<redacted>', name)
        # Control characters in filenames must never shape console/log output.
        return ''.join(char if char.isprintable() else '?' for char in name)

    def add(self, name, kind, line=0, count=1, origin='working-tree'):
        self.findings.append({'path': self.display_path(name), 'line': line,
                              'kind': kind, 'count': count, 'origin': origin})

    def path_checks(self, name, origin='working-tree'):
        parts = PurePosixPath(str(name).replace('\\', '/')).parts
        lower = [part.casefold() for part in parts]
        filename = lower[-1] if lower else ''
        if any(part in LOCAL_PARTS for part in lower) or filename in LOCAL_NAMES:
            self.add(name, 'local-artifact', origin=origin)
        if re.search(r'(?:cas-cost-review|k-stack-review)-\d|(?:session|verification|handoff|transcript|smoke-result)[-_].*\.(?:jsonl?|log|md)$', filename):
            self.add(name, 'local-session-artifact', origin=origin)
        if filename.endswith(('.log', '.jsonl')):
            self.add(name, 'log-or-transcript', origin=origin)
        if filename.startswith('.env') and filename not in {'.env.example', '.env.sample', '.env.template', '.env.schema'}:
            self.add(name, 'credential-file', origin=origin)
        if filename in {'id_rsa', 'id_ed25519', 'id_ecdsa', '.netrc', '.npmrc', '.pypirc', '.pgpass'} or filename.endswith(('.pem', '.key', '.p12', '.pfx', '.keystore')):
            self.add(name, 'credential-file', origin=origin)
        if PurePosixPath(filename).suffix in BINARY_SUFFIXES:
            self.add(name, 'binary-artifact', origin=origin)
        self.text_checks(str(name), name, origin, filenames=True)

    def text_checks(self, text, name, origin, filenames=False):
        for kind, pattern in PATTERNS.items():
            by_line = {}
            for match in pattern.finditer(text):
                if kind == 'private-email' and match.group().casefold() in self.allowed_emails:
                    continue
                line = 0 if filenames else text.count('\n', 0, match.start()) + 1
                by_line[line] = by_line.get(line, 0) + 1
            for line, count in by_line.items():
                self.add(name, kind, line, count, origin)
        for term in self.private_terms:
            by_line = {}
            for match in re.finditer(re.escape(term), text, re.IGNORECASE):
                line = 0 if filenames else text.count('\n', 0, match.start()) + 1
                by_line[line] = by_line.get(line, 0) + 1
            for line, count in by_line.items():
                self.add(name, 'local-private-term', line, count, origin)

    def data_checks(self, data, name, origin='working-tree'):
        self.checked += 1
        if len(data) > self.max_bytes:
            self.add(name, 'scan-size-limit', origin=origin)
            return
        try:
            text = data.decode('utf-8-sig')
        except UnicodeDecodeError:
            self.add(name, 'non-utf8-artifact', origin=origin)
            return
        if '\x00' in text:
            self.add(name, 'binary-content', origin=origin)
            return
        self.text_checks(text, name, origin)

    @staticmethod
    def linked(path):
        return linked_stat(path.lstat())

    def working_tree(self, root):
        if self.linked(root):
            self.add('.', 'symlink-or-reparse-point')
            return
        entries_seen = 0
        def visit(directory, depth=0):
            nonlocal entries_seen
            if depth > MAX_DEPTH:
                self.add('.', 'scan-depth-limit')
                return
            try:
                entries = list(islice(directory.iterdir(), MAX_ENTRIES + 1))
                if len(entries) > MAX_ENTRIES:
                    raise InputError('scan-entry-limit')
            except OSError:
                self.add(directory.relative_to(root).as_posix(), 'scan-read-error')
                return
            for entry in sorted(entries):
                entries_seen += 1
                if entries_seen > MAX_ENTRIES:
                    raise InputError('scan-entry-limit')
                name = entry.relative_to(root).as_posix()
                if entry.name == '.git' and entry.parent == root:
                    continue
                try:
                    self.path_checks(name)
                    info = checked_path(entry, root)
                    if stat.S_ISDIR(info.st_mode):
                        visit(entry, depth + 1)
                    elif stat.S_ISREG(info.st_mode):
                        self.data_checks(read_regular(entry, root, self.max_bytes), name)
                    else:
                        self.add(name, 'nonregular-file')
                except InputError as error:
                    self.add(name, str(error))
                except OSError:
                    self.add(name, 'scan-read-error')
        visit(root)

    def git(self, root, args, input_data=None):
        if self.git_deadline is None:
            self.git_deadline = time.monotonic() + GIT_SCAN_SECONDS
        remaining = self.git_deadline - time.monotonic()
        if remaining <= 0:
            raise InputError('git-scan-timeout')
        # A caller's alternate index/worktree/config must not redirect this scan.
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith('GIT_')}
        env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                    'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_REPLACE_OBJECTS': '1',
                    'GIT_NO_LAZY_FETCH': '1', 'GIT_OPTIONAL_LOCKS': '0'})
        return bounded_command(['git', '-c', 'core.fsmonitor=false', '-c', 'core.hooksPath=' + os.devnull,
                                '-C', str(root), *args], input_data=input_data, env=env,
                               timeout=min(60, remaining))

    def git_blob(self, root, oid, name, origin, mode=None):
        self.path_checks(name, origin)
        if mode == '120000':
            self.add(name, 'symlink-or-reparse-point', origin=origin)
        size = int(self.git(root, ['cat-file', '-s', oid]).strip())
        if size > self.max_bytes:
            self.add(name, 'scan-size-limit', origin=origin)
            return
        self.data_checks(self.git(root, ['cat-file', 'blob', oid]), name, origin)

    def staged(self, root):
        self.require_git_root(root)
        entries = self.git(root, ['ls-files', '--stage', '-z']).split(b'\x00')
        if len(entries) > MAX_ENTRIES + 1:
            raise InputError('index-scan-size-limit')
        for entry in entries:
            if not entry:
                continue
            metadata, raw_name = entry.split(b'\t', 1)
            mode, raw_oid, stage = metadata.decode('ascii').split()
            name = raw_name.decode('utf-8', errors='replace')
            if stage != '0':
                self.add(name, 'unresolved-index-entry', origin='git-index')
            if mode == '160000':
                self.add(name, 'submodule-unscanned', origin='git-index')
                continue
            self.git_blob(root, raw_oid, name, 'git-index', mode)

    def history(self, root):
        self.require_git_root(root)
        if self.git(root, ['rev-parse', '--is-shallow-repository']).strip() == b'true':
            self.add('<git-history>', 'shallow-history-unscanned', origin='git-history')
            return
        refs = self.git(root, ['for-each-ref', '--count=10001', '--format=%(refname)']).splitlines()
        if len(refs) > MAX_ENTRIES:
            raise InputError('history-scan-size-limit')
        for ref in refs:
            self.data_checks(ref, '<git-ref>', 'git-refs')
        commits = self.git(root, ['rev-list', '--max-count=1001', '--all']).splitlines()
        if len(commits) > 1000:
            raise ValueError('history-scan-size-limit')
        seen_entries = set()
        for commit in commits:
            tree = self.git(root, ['ls-tree', '-rz', '--full-tree', commit.decode('ascii')])
            for entry in tree.split(b'\x00'):
                if not entry:
                    continue
                metadata, raw_name = entry.split(b'\t', 1)
                mode, kind, oid = metadata.decode('ascii').split()
                identity = (mode, oid, raw_name)
                if identity in seen_entries:
                    continue
                seen_entries.add(identity)
                if len(seen_entries) > MAX_ENTRIES:
                    raise InputError('history-scan-size-limit')
                name = raw_name.decode('utf-8', errors='replace')
                origin = 'git-history:' + commit.decode('ascii')[:12]
                self.path_checks(name, origin)
                if mode == '120000':
                    self.add(name, 'symlink-or-reparse-point', origin=origin)
                if mode == '160000':
                    self.add(name, 'submodule-unscanned', origin=origin)
        objects = self.git(root, ['rev-list', '--objects', '--all']).splitlines()
        mapping = {}
        for line in objects:
            oid, _, name = line.partition(b' ')
            mapping[oid.decode('ascii')] = name.decode('utf-8', errors='replace') or '<git-object>'
            if len(mapping) > MAX_ENTRIES:
                raise InputError('history-scan-size-limit')
        if len(mapping) > 10000:
            raise ValueError('history-scan-size-limit')
        if not mapping:
            return
        metadata = self.git(root, ['cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)'],
                            ('\n'.join(mapping) + '\n').encode('ascii'))
        for line in metadata.decode('ascii').splitlines():
            oid, kind, size = line.split()
            if kind not in {'blob', 'commit', 'tag'}:
                continue
            name = mapping[oid]
            origin = 'git-history:' + oid[:12]
            if kind == 'blob':
                self.path_checks(name, origin)
            if int(size) > self.max_bytes:
                self.add(name, 'scan-size-limit', origin=origin)
                continue
            data = self.git(root, ['cat-file', kind, oid])
            if kind in {'commit', 'tag'}:
                # Identity is publication data too; report only findings, never header values.
                name = '<git-' + kind + '>'
            if kind in {'commit', 'tag'} and self.allow_github_noreply_identities:
                data = self.public_commit_identities(data, kind)
            self.data_checks(data, name, origin)

    def require_git_root(self, root):
        actual = self.git(root, ['rev-parse', '--show-toplevel']).decode('utf-8').strip()
        if Path(actual).resolve() != Path(root).resolve():
            raise ValueError('git-root-mismatch; refusing to inspect a parent repository')

    @staticmethod
    def public_commit_identities(data, kind='commit'):
        # Exempt only canonical addresses in actual commit/tag identity headers.
        # Messages, filenames, file content and other emails still fail.
        header, separator, message = data.partition(b'\n\n')
        lines = []
        for line in header.split(b'\n'):
            prefix = rb'(?:author|committer)' if kind == 'commit' else rb'tagger'
            match = re.fullmatch(prefix + rb' .* <([^<>]+)> [0-9]+ [+-][0-9]{4}', line)
            if match:
                try:
                    email = match.group(1).decode('ascii')
                except UnicodeDecodeError:
                    email = ''
                if PUBLIC_NOREPLY.fullmatch(email):
                    start, end = match.span(1)
                    line = line[:start] + b'PUBLIC_NOREPLY_IDENTITY' + line[end:]
            lines.append(line)
        return b'\n'.join(lines) + separator + message


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--git-staged', action='store_true', help='Scan the full index, not only changed files.')
    parser.add_argument('--git-history', action='store_true', help='Scan all reachable blobs, commits and tags.')
    parser.add_argument('--deny-term', action='append', default=[], help='Additional private term; never printed.')
    parser.add_argument('--allow-email', action='append', default=[], help='Exact approved public email, including public commit identity.')
    parser.add_argument('--allow-github-noreply-identities', action='store_true',
                        help='Allow canonical public GitHub noreply addresses only in commit author/committer and tagger headers.')
    args = parser.parse_args(argv)
    private = args.deny_term + os.environ.get('ULTRA_HOOK_PRIVATE_TERMS', '').splitlines()
    auditor = Auditor(private, args.allow_email,
                      allow_github_noreply_identities=args.allow_github_noreply_identities)
    root = args.root.absolute()
    try:
        if not root.is_dir():
            raise ValueError('scan-root-unavailable')
        auditor.working_tree(root)
        if args.git_staged:
            auditor.staged(root)
        if args.git_history:
            auditor.history(root)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        auditor.add('.', 'scan-incomplete', origin='scanner')
    print(json.dumps({'passed': not auditor.findings, 'filesChecked': auditor.checked,
                      'findingCount': len(auditor.findings), 'findings': auditor.findings}, ensure_ascii=True))
    return 1 if auditor.findings else 0


if __name__ == '__main__':
    sys.exit(main())
