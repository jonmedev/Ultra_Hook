#!/usr/bin/env python3
"""Ultra Hook helper to build Kasempiternal's AgentController from pinned source; does not register MCP or launch UI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from install import InstallError, guard_path, ensure_directory, write_private, private_bytes, run_bounded

SOURCE = 'https://github.com/Kasempiternal/agentcontroller.git'
COMMIT = 'bc6db97122d6adf07342d3efc87e7ac7c96b4889'
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


def plan(destination, runtime='win-x64', dotnet_command=None):
    if runtime not in ('win-x64', 'win-arm64'):
        raise ValueError('Unsupported AgentController runtime.')
    destination = guard_path(Path(os.path.abspath(Path(destination).expanduser())))
    source = destination / 'source'
    project = source / 'Windows/AgentController.Windows/AgentController.Windows.csproj'
    output = destination / 'bin'
    return {'source': SOURCE, 'commit': COMMIT, 'license': 'Apache-2.0 (retained from pinned source)',
            'destination': str(destination),
            'commands': [['git', 'clone', '--no-checkout', SOURCE, str(source)],
                         ['git', '-C', str(source), 'checkout', '--detach', COMMIT],
                         [dotnet_executable(dotnet_command) or 'dotnet', 'publish', str(project), '--configuration', 'Release', '--runtime', runtime,
                          '--self-contained', 'true', '--output', str(output), '-p:PublishSingleFile=true',
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
    guard_path(build_lock, regular=True)
    build_lock.unlink()
    return {'status': 'built', **result,
            'next': 'Pass commandAfterBuild to install.py --agentcontroller-command. Review platform permissions locally.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog='Official upstream downloads: https://github.com/Kasempiternal/agentcontroller/releases')
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--runtime', choices=('win-x64', 'win-arm64'), default='win-x64')
    parser.add_argument('--build-windows', action='store_true', help='Explicitly fetch pinned source and build with .NET 9.')
    parser.add_argument('--dotnet-command', help='Existing .NET executable; otherwise PATH and Windows ProgramFiles are checked.')
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.destination, args.runtime, enabled=args.build_windows, dotnet_command=args.dotnet_command), indent=2))
        return 0
    except InstallError as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}), file=sys.stderr)
        return 1
    except (ValueError, OSError, TypeError, subprocess.TimeoutExpired):
        print(json.dumps({'status': 'error', 'message': 'Source setup failed; private diagnostics withheld. Files retained for local review.'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
