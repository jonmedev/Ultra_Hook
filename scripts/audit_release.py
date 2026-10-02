#!/usr/bin/env python3
"""Fail closed on private data and local artifacts before publication (stdlib only)."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys

MAX_BYTES = 2 * 1024 * 1024
BINARY_SUFFIXES = {'.exe', '.dll', '.pdb', '.so', '.dylib', '.pyc', '.zip', '.7z',
                   '.tar', '.gz', '.sqlite', '.db', '.dmp', '.png', '.jpg', '.jpeg',
                   '.gif', '.mp4', '.pdf', '.docx', '.xlsx', '.pptx'}
LOCAL_PARTS = {'.codex', '.claude', '.commandcode', '.agentcontroller', '.cas',
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
    'private-email': re.compile(r'(?i)\b[A-Z0-9.!#$%&*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b'),
    'session-uuid': re.compile(r'(?i)\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b'),
}
PUBLIC_NOREPLY = re.compile(r'(?:[0-9]+\+)?[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?@users\.noreply\.github\.com')


class Auditor:
    def __init__(self, private_terms=(), allowed_emails=(), max_bytes=MAX_BYTES,
                 allow_github_noreply_identities=False):
        self.private_terms = tuple(term for term in private_terms if term)
        self.allowed_emails = {email.casefold() for email in allowed_emails}
        self.max_bytes = max_bytes
        self.allow_github_noreply_identities = allow_github_noreply_identities
        self.findings = []
        self.checked = 0

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
        attrs = getattr(path.lstat(), 'st_file_attributes', 0)
        return path.is_symlink() or bool(attrs & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0))

    def working_tree(self, root):
        if self.linked(root):
            self.add('.', 'symlink-or-reparse-point')
            return
        def visit(directory):
            try:
                entries = list(directory.iterdir())
            except OSError:
                self.add(directory.relative_to(root).as_posix(), 'scan-read-error')
                return
            for entry in sorted(entries):
                name = entry.relative_to(root).as_posix()
                if entry.name == '.git' and entry.parent == root:
                    continue
                try:
                    self.path_checks(name)
                    if self.linked(entry):
                        self.add(name, 'symlink-or-reparse-point')
                    elif entry.is_dir():
                        visit(entry)
                    elif entry.is_file():
                        if entry.stat().st_size > self.max_bytes:
                            self.add(name, 'scan-size-limit')
                        else:
                            self.data_checks(entry.read_bytes(), name)
                    else:
                        self.add(name, 'nonregular-file')
                except OSError:
                    self.add(name, 'scan-read-error')
        visit(root)

    @staticmethod
    def git(root, args, input_data=None):
        completed = subprocess.run(['git', '-C', str(root), *args], input=input_data,
                                   capture_output=True, shell=False, timeout=60)
        if completed.returncode:
            raise ValueError('git-scan-failed')
        return completed.stdout

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
        commits = self.git(root, ['rev-list', '--all']).splitlines()
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
