#!/usr/bin/env python3
"""Acquire Kasempiternal's AgentController from pinned sources or a verified DMG; never register MCP or launch UI."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import platform
import shlex
import shutil
import subprocess
import sys
import sysconfig
import time
import urllib.request
import urllib.parse
import zipfile
from install import InstallError, guard_path, ensure_directory, write_private, private_bytes, run_bounded

SOURCE = 'https://github.com/Kasempiternal/agentcontroller.git'
COMMIT = 'bc6db97122d6adf07342d3efc87e7ac7c96b4889'
SOURCE_ARCHIVE = 'https://codeload.github.com/Kasempiternal/agentcontroller/zip/' + COMMIT
SOURCE_SHA256 = 'be50d2e4ddf27a9a8bc9507e59aff8d5612c619696ba00b77e70596c7e1c5c30'
MAC_URL = 'https://github.com/Kasempiternal/agentcontroller/releases/download/v2.5.0/AgentController-2.5.0.dmg'
MAC_SHA256 = 'f76cc521fdff5a85afd8abba1875937f3a6af7689f8de5162abbe9751413f460'
RECEIPT = 'acquisition-provenance.json'
MAX_DOWNLOAD = 16 * 1024 * 1024
MAX_WINDOWS_DESTINATION = 100
MAC_NEXT = ('This official DMG requires Apple Silicon (arm64) and macOS 14 Sonoma or later; '
            'it does not support Intel Macs. Recording requires macOS 15 or later. '
            'Host compatibility has not been verified by this download-only helper. '
            'On a supported Mac, open AgentController-2.5.0.dmg from the acquisition directory in Finder. '
            'Copy AgentController.app to ~/Applications without replacing an existing app, '
            'launch it and grant Accessibility and Screen Recording in System Settings. '
            'The app installs ~/.agentcontroller/agentcontroller-mcp-bridge.sh at startup. '
            'Keep the app running, verify that bridge locally, then pass its absolute path '
            'to install.py --agentcontroller-command. App, bridge and UI validation remain pending.')
LINUX_NEXT = ('The Python stdio launcher is installed. Desktop capabilities are not validated: '
              'install the optional system AT-SPI, screenshot and input helpers described in '
              'https://github.com/Kasempiternal/agentcontroller/blob/' + COMMIT + '/Linux/README.md, '
              'then check permissions and a real UI. '
              'No system packages or global pip packages were installed.')


class AcquisitionError(ValueError):
    """Public messages contain fixed, safe setup instructions only."""


def check_windows_destination(destination):
    # NuGet appends long runtime/resource paths beneath the isolated package
    # cache. Keep a conservative margin below legacy Windows MAX_PATH limits.
    if len(str(destination).encode('utf-16-le')) // 2 > MAX_WINDOWS_DESTINATION:
        raise AcquisitionError('Windows AgentController source builds require an absolute destination of at most '
                               '100 characters (UTF-16 units). Choose a shorter --agentcontroller-dir '
                               '(or --destination for this helper), then retry. No download or build was started.')


def download_verified(url, expected):
    """Bounded HTTPS download from the fixed upstream endpoints; never execute it."""
    allowed = {'github.com', 'codeload.github.com', 'release-assets.githubusercontent.com',
               'objects.githubusercontent.com'}

    def check_url(value):
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme != 'https' or parsed.hostname not in allowed or parsed.username or parsed.password:
            raise AcquisitionError('AgentController download used an unexpected endpoint; nothing was installed.')

    class Redirects(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            check_url(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    check_url(url)
    start = time.monotonic()
    request = urllib.request.Request(url, headers={'User-Agent': 'Ultra-Hook-AgentController-Setup'})
    chunks, size = [], 0
    with urllib.request.build_opener(Redirects()).open(request, timeout=10) as response:
        check_url(response.geturl())
        while True:
            if time.monotonic() - start > 60:
                raise AcquisitionError('AgentController download exceeded its time limit; retry in a new empty directory.')
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_DOWNLOAD:
                raise AcquisitionError('AgentController download exceeded its size limit; nothing was installed.')
            chunks.append(chunk)
    data = b''.join(chunks)
    if hashlib.sha256(data).hexdigest() != expected:
        raise AcquisitionError('AgentController download checksum mismatch; nothing was installed.')
    return data


def file_digest(path):
    guard_path(path, regular=True)
    with path.open('rb') as handle:
        before = os.fstat(handle.fileno())
        if before.st_nlink != 1 or before.st_size > 256 * 1024 * 1024:
            raise AcquisitionError('AgentController output is linked or oversized; use a new empty directory.')
        hasher, size = hashlib.sha256(), 0
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            if size > 256 * 1024 * 1024:
                raise AcquisitionError('AgentController output exceeded its verification size limit.')
            hasher.update(chunk)
        digest = hasher.hexdigest()
        after = os.fstat(handle.fileno())
    guard_path(path, regular=True)
    current = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or (after.st_dev, after.st_ino) != (current.st_dev, current.st_ino):
        raise AcquisitionError('AgentController output changed during verification; retry after local review.')
    return digest


def runtime_files(directory):
    """Inventory only executable/runtime content, with no link traversal."""
    found = {}
    pending = [directory]
    visited = 0
    while pending:
        current = guard_path(pending.pop())
        with os.scandir(current) as entries:
            for entry in entries:
                visited += 1
                if visited > 512:
                    raise AcquisitionError('AgentController runtime contains too many files.')
                path = guard_path(Path(entry.path))
                if path.is_dir():
                    pending.append(path)
                else:
                    guard_path(path, regular=True)
                    found[path.relative_to(directory).as_posix()] = file_digest(path)
    return found


def platform_plan(destination):
    host = sys.platform
    if host == 'win32':
        check_windows_destination(destination)
        machine = platform.machine().lower() or sysconfig.get_platform().removeprefix('win-').lower()
        if machine not in ('amd64', 'x86_64', 'arm64', 'aarch64'):
            raise AcquisitionError('AgentController source setup supports Windows x64 and ARM64 only.')
        return {'platform': 'windows', 'source': SOURCE, 'commit': COMMIT,
                'runtime': 'win-arm64' if machine in ('arm64', 'aarch64') else 'win-x64',
                'command': str(destination / 'bin/agentcontroller-windows.exe')}
    if host.startswith('linux'):
        if sys.version_info < (3, 11):
            raise AcquisitionError('AgentController on Linux requires Python 3.11 or newer.')
        return {'platform': 'linux', 'source': SOURCE, 'commit': COMMIT,
                'archiveSha256': SOURCE_SHA256, 'command': str(destination / 'bin/agentcontroller-linux')}
    if host == 'darwin':
        return {'platform': 'macos', 'source': MAC_URL, 'version': '2.5.0',
                'requiredArchitecture': 'arm64', 'minimumMacOS': '14.0',
                'archiveSha256': MAC_SHA256, 'command': None}
    raise AcquisitionError('Automatic AgentController acquisition supports Windows, Linux and macOS only.')


def acquisition_inventory(destination, target):
    files = {}
    if target['platform'] == 'macos':
        files['AgentController-2.5.0.dmg'] = file_digest(destination / 'AgentController-2.5.0.dmg')
        if files['AgentController-2.5.0.dmg'] != MAC_SHA256:
            raise AcquisitionError('Downloaded AgentController DMG changed; use a new empty directory.')
    else:
        files.update({'bin/' + name: digest for name, digest in runtime_files(destination / 'bin').items()})
        if target['platform'] == 'linux':
            files.update({'source/' + name: digest for name, digest in runtime_files(destination / 'source').items()})
        for name in ('LICENSE.AgentController', 'NOTICE.AgentController'):
            files[name] = file_digest(destination / name)
    return files


def acquire(destination, *, dry_run=False):
    """Acquire owned files only. No MCP registration, UI launch, or profile edits."""
    try:
        return _acquire(destination, dry_run=dry_run)
    except AcquisitionError:
        raise
    except (ValueError, OSError, TypeError, KeyError, InstallError, zipfile.BadZipFile,
            subprocess.SubprocessError):
        raise AcquisitionError('AgentController acquisition failed. Files were retained for local review; '
                               'check prerequisites and use a new empty directory before retrying.') from None


def _acquire(destination, *, dry_run=False):
    destination = guard_path(Path(os.path.abspath(Path(destination).expanduser())))
    target = platform_plan(destination)
    command = target['command']
    provenance = {key: value for key, value in target.items() if key != 'command'}
    provenance.update({'schema': 1, 'owner': 'ultra-hook-agentcontroller', 'license': 'Apache-2.0'})
    next_step = MAC_NEXT if target['platform'] == 'macos' else LINUX_NEXT if target['platform'] == 'linux' else (
        'Register the acquired command with install.py; verify transport, permissions and a real UI separately.')
    receipt = destination / RECEIPT
    if receipt.exists():
        recorded = json.loads(private_bytes(receipt, limit=256 * 1024))
        if not isinstance(recorded, dict) or any(recorded.get(k) != v for k, v in provenance.items()):
            raise AcquisitionError('Existing AgentController provenance does not match this acquisition; use a new empty directory.')
        actual = acquisition_inventory(destination, target)
        if recorded.get('files') != actual or (command and recorded.get('binarySha256') != file_digest(Path(command))):
            raise AcquisitionError('Owned AgentController files changed; review them and use a new empty directory.')
        return {'status': 'pending' if command is None else 'reused', 'command': command,
                'provenance': recorded, 'next': next_step}
    if destination.exists() and any(destination.iterdir()):
        raise AcquisitionError('AgentController destination is not empty or has no matching ownership record; use a new empty directory.')
    if dry_run:
        return {'status': 'plan', 'command': command, 'provenance': provenance, 'next': next_step}
    if target['platform'] == 'windows':
        if not shutil.which('git') or not dotnet_executable():
            raise AcquisitionError('Install Git and the .NET 9 SDK, then retry AgentController acquisition. No SDK is installed automatically.')
        build(destination, target['runtime'], enabled=True)
    else:
        url, digest = (MAC_URL, MAC_SHA256) if target['platform'] == 'macos' else (SOURCE_ARCHIVE, SOURCE_SHA256)
        data = download_verified(url, digest)
        ensure_directory(destination)
        if any(destination.iterdir()):
            raise AcquisitionError('AgentController destination changed during acquisition; use a new empty directory.')
        lock = destination / '.ultra-hook-acquisition.lock'
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
        if target['platform'] == 'macos':
            write_private(destination / 'AgentController-2.5.0.dmg', data, expected=None)
        else:
            install_linux_source(destination, data)
    provenance['files'] = acquisition_inventory(destination, target)
    if command:
        provenance['binarySha256'] = file_digest(Path(command))
    write_private(receipt, json.dumps(provenance, indent=2).encode('utf-8'), expected=None)
    lock = destination / '.ultra-hook-acquisition.lock'
    if lock.exists():
        guard_path(lock, regular=True)
        lock.unlink()
    return {'status': 'acquired' if command else 'pending', 'command': command,
            'provenance': provenance, 'next': next_step}


def install_linux_source(destination, data):
    prefix = 'agentcontroller-' + COMMIT + '/'
    selected = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.infolist()) > 4096:
            raise AcquisitionError('AgentController source archive has too many entries.')
        for entry in archive.infolist():
            name = entry.filename
            if not name.startswith(prefix):
                raise AcquisitionError('AgentController archive has an unexpected root.')
            relative = name[len(prefix):]
            if relative in ('LICENSE', 'NOTICE'):
                output = relative + '.AgentController'
            elif relative.startswith('Linux/src/agentcontroller_linux/') and not entry.is_dir():
                suffix = relative[len('Linux/src/'):]
                if not re.fullmatch(r'[a-zA-Z0-9_/]+\.py', suffix) or '..' in suffix.split('/'):
                    raise AcquisitionError('AgentController archive has an unexpected runtime path.')
                output = 'source/' + suffix
            else:
                continue
            kind = (entry.external_attr >> 16) & 0o170000
            if kind not in (0, 0o100000) or entry.file_size > 1024 * 1024 or output in selected or len(selected) >= 128:
                raise AcquisitionError('AgentController source archive contains invalid runtime files.')
            selected[output] = archive.read(entry)
    required = {'LICENSE.AgentController', 'NOTICE.AgentController', 'source/agentcontroller_linux/__main__.py'}
    if not required.issubset(selected):
        raise AcquisitionError('AgentController source archive is incomplete.')
    for relative, content in selected.items():
        path = destination / relative
        ensure_directory(path.parent)
        write_private(path, content, expected=None)
    bin_dir = destination / 'bin'
    ensure_directory(bin_dir)
    runner = ("import sys\nfrom pathlib import Path\nsys.dont_write_bytecode = True\n"
              "sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'source'))\n"
              "from agentcontroller_linux.__main__ import main\nraise SystemExit(main())\n")
    write_private(bin_dir / 'run_agentcontroller.py', runner.encode('utf-8'), expected=None)
    # A no-argument executable lets Codex register it without global PYTHONPATH or pip.
    python = str(Path(sys.executable).resolve())
    launcher = '#!/bin/sh\nexec ' + shlex.quote(python) + ' -I ' + shlex.quote(str(bin_dir / 'run_agentcontroller.py')) + ' "$@"\n'
    path = bin_dir / 'agentcontroller-linux'
    write_private(path, launcher.encode('utf-8'), expected=None)
    os.chmod(path, 0o700)
BUILD_ENV_KEYS = {'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP',
                  'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMW6432', 'OS',
                  'PROCESSOR_ARCHITECTURE', 'PROCESSOR_ARCHITEW6432', 'NUMBER_OF_PROCESSORS',
                  'LANG', 'LC_ALL', 'LC_CTYPE'}


def public_build_environment(destination, dotnet):
    env = {key: value for key, value in os.environ.items() if key.upper() in BUILD_ENV_KEYS}
    isolated_home = destination / '.build-home'
    env.update({'HOME': str(isolated_home), 'USERPROFILE': str(isolated_home),
                'APPDATA': str(isolated_home / 'AppData/Roaming'),
                'LOCALAPPDATA': str(isolated_home / 'AppData/Local'),
                'DOTNET_ROOT': str(Path(dotnet).parent),
                'DOTNET_CLI_HOME': str(destination / '.dotnet-cli'),
                'DOTNET_NOLOGO': '1', 'DOTNET_CLI_TELEMETRY_OPTOUT': '1',
                'NUGET_PACKAGES': str(destination / '.nuget/packages'),
                'NUGET_HTTP_CACHE_PATH': str(destination / '.nuget/http-cache'),
                'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_SYSTEM': os.devnull,
                'GIT_CONFIG_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0'})
    if isolated_home.drive:
        env['HOMEDRIVE'] = isolated_home.drive
        env['HOMEPATH'] = str(isolated_home)[len(isolated_home.drive):]
    return env


def dotnet_executable(command=None):
    if command:
        path = Path(command).expanduser().resolve()
        if not path.is_file():
            raise ValueError('--dotnet-command must point to an existing .NET executable.')
        return str(path)
    found = shutil.which('dotnet')
    if found:
        return found
    if os.name == 'nt':
        for key in ('ProgramFiles', 'ProgramW6432'):
            base = os.environ.get(key)
            candidate = Path(base) / 'dotnet/dotnet.exe' if base else None
            if candidate and candidate.is_file():
                return str(candidate)
    return None


# Created by this build inside its own, initially empty destination. The pinned
# source, licenses and published executable stay; only regenerable caches go.
BUILD_CACHES = ('.build-home', '.dotnet-cli', '.nuget', 'NuGet', '.disabled-git-hooks',
                'source/Windows/AgentController.Windows/bin', 'source/Windows/AgentController.Windows/obj')


def remove_build_caches(destination):
    """Best effort: a cache still in use is retained and reported, never forced."""
    removed = True
    for name in BUILD_CACHES:
        path = destination / name
        try:
            guard_path(path)
            if path.is_dir():
                shutil.rmtree(path)
        except (OSError, InstallError):
            removed = False
    return removed


def plan(destination, runtime='win-x64', dotnet_command=None):
    if runtime not in ('win-x64', 'win-arm64'):
        raise ValueError('Unsupported AgentController runtime.')
    destination = guard_path(Path(os.path.abspath(Path(destination).expanduser())))
    check_windows_destination(destination)
    source = destination / 'source'
    project = source / 'Windows/AgentController.Windows/AgentController.Windows.csproj'
    output = destination / 'bin'
    return {'source': SOURCE, 'commit': COMMIT, 'license': 'Apache-2.0 (retained from pinned source)',
            'destination': str(destination),
            'commands': [['git', 'clone', '--no-checkout', SOURCE, str(source)],
                         ['git', '-C', str(source), 'checkout', '--detach', COMMIT],
                         [dotnet_executable(dotnet_command) or 'dotnet', 'publish', str(project), '--configuration', 'Release', '--runtime', runtime,
                          '--self-contained', 'true', '--output', str(output), '--disable-build-servers', '-p:PublishSingleFile=true',
                          '-p:IncludeNativeLibrariesForSelfExtract=true']],
            'commandAfterBuild': str(output / 'agentcontroller-windows.exe')}


def build(destination, runtime='win-x64', *, enabled=False, dotnet_command=None):
    result = plan(destination, runtime, dotnet_command)
    if not enabled:
        return {'status': 'plan', **result}
    if os.name != 'nt':
        raise ValueError('Automatic build is supported on Windows only. Use the upstream platform guide elsewhere.')
    dotnet = dotnet_executable(dotnet_command)
    if not shutil.which('git') or not dotnet:
        raise ValueError('Git and the .NET 9 SDK are required; no dependency installation is attempted.')
    destination = Path(result['destination'])
    env = public_build_environment(destination, dotnet)
    sdk = run_bounded([dotnet, '--list-sdks'], timeout=30, max_output=64 * 1024, env=env)
    if sdk.returncode or not re.search(r'^9\.', sdk.stdout, re.MULTILINE):
        raise ValueError('The .NET 9 SDK is required.')
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Choose an empty destination. Existing source/build files are never overwritten or deleted.')
    ensure_directory(destination)
    build_lock = destination / '.ultra-hook-build.lock'
    descriptor = os.open(build_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    # A failed build retains its lock/source for review; never silently retries
    # or overwrites existing outputs. Public source needs no credential helpers.
    ensure_directory(destination / '.disabled-git-hooks')
    for command in result['commands']:
        guard_path(destination)
        if command[0] == 'git':
            command = ['git', '-c', 'core.hooksPath=' + str(destination / '.disabled-git-hooks')] + command[1:]
        else:
            guard_path(destination / 'source/Windows/AgentController.Windows/AgentController.Windows.csproj', regular=True)
            guard_path(destination / 'bin')
        process = run_bounded(command, timeout=600, env=env, cwd=destination, max_output=8 * 1024 * 1024)
        if process.returncode:
            raise ValueError('Source build step failed; files retained for local diagnosis. Raw output withheld.')
        if command[0] == 'git' and 'checkout' in command:
            check = run_bounded(['git', '-C', str(destination / 'source'), 'rev-parse', 'HEAD'],
                                timeout=30, env=env, cwd=destination, max_output=4096)
            if check.returncode or check.stdout.strip() != COMMIT:
                raise ValueError('Source revision does not match the pinned commit; refusing build.')
    license_path = destination / 'source/LICENSE'
    guard_path(license_path, regular=True)
    if not license_path.is_file():
        raise ValueError('Pinned upstream license is missing; build files retained, no MCP registration attempted.')
    write_private(destination / 'LICENSE.AgentController', private_bytes(license_path, limit=1024 * 1024), expected=None)
    notice_path = destination / 'source/NOTICE'
    guard_path(notice_path, regular=True)
    if not notice_path.is_file():
        raise ValueError('Pinned upstream NOTICE is missing; no MCP registration attempted.')
    write_private(destination / 'NOTICE.AgentController', private_bytes(notice_path, limit=1024 * 1024), expected=None)
    executable = Path(result['commandAfterBuild'])
    guard_path(executable, regular=True)
    if not executable.is_file():
        raise ValueError('Build produced no expected executable; no registration attempted.')
    provenance = {key: result[key] for key in ('source', 'commit', 'license')}
    with executable.open('rb') as handle:
        provenance['binarySha256'] = hashlib.file_digest(handle, 'sha256').hexdigest()
    write_private(destination / 'source-provenance.json', json.dumps(provenance, indent=2).encode('utf-8'), expected=None)
    caches_removed = remove_build_caches(destination)
    guard_path(build_lock, regular=True)
    build_lock.unlink()
    return {'status': 'built', **result, 'buildCachesRemoved': caches_removed,
            'next': 'Pass commandAfterBuild to install.py --agentcontroller-command. Review platform permissions locally.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog='Official upstream downloads: https://github.com/Kasempiternal/agentcontroller/releases')
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--runtime', choices=('win-x64', 'win-arm64'), default='win-x64')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--build-windows', action='store_true', help='Explicitly fetch pinned source and build with .NET 9.')
    action.add_argument('--acquire', action='store_true', help='Acquire AgentController for this host; macOS downloads remain pending manual app setup.')
    parser.add_argument('--dry-run', action='store_true', help='With --acquire, show or verify the plan without downloads or writes.')
    parser.add_argument('--dotnet-command', help='Existing .NET executable; otherwise PATH and Windows ProgramFiles are checked.')
    args = parser.parse_args()
    try:
        if args.dry_run and not args.acquire:
            raise AcquisitionError('--dry-run requires --acquire; the legacy default already shows a build plan.')
        result = acquire(args.destination, dry_run=args.dry_run) if args.acquire else build(
            args.destination, args.runtime, enabled=args.build_windows, dotnet_command=args.dotnet_command)
        print(json.dumps(result, indent=2))
        return 0
    except AcquisitionError as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}), file=sys.stderr)
        return 1
    except InstallError as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}), file=sys.stderr)
        return 1
    except (ValueError, OSError, TypeError, subprocess.TimeoutExpired):
        print(json.dumps({'status': 'error', 'message': 'Source setup failed; private diagnostics withheld. Files retained for local review.'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
