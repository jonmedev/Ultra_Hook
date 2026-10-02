#!/usr/bin/env python3
"""Opt-in Windows AgentController source build; does not register MCP or launch UI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

SOURCE = 'https://github.com/Kasempiternal/agentcontroller.git'
COMMIT = 'bc6db97122d6adf07342d3efc87e7ac7c96b4889'


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
    destination = Path(destination).expanduser().resolve()
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
    sdk = subprocess.run([dotnet, '--list-sdks'], capture_output=True, text=True, shell=False, timeout=30)
    if sdk.returncode or not re.search(r'^9\.', sdk.stdout, re.MULTILINE):
        raise ValueError('The .NET 9 SDK is required.')
    destination = Path(result['destination'])
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Choose an empty destination. Existing source/build files are never overwritten or deleted.')
    destination.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env['DOTNET_CLI_HOME'] = str(destination / '.dotnet-cli')
    env['DOTNET_NOLOGO'] = '1'
    env['DOTNET_CLI_TELEMETRY_OPTOUT'] = '1'
    for command in result['commands']:
        process = subprocess.run(command, shell=False, capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=600, env=env)
        if process.returncode:
            raise ValueError('Source build step failed; files retained for local diagnosis. Raw output withheld.')
        if command[0] == 'git' and 'checkout' in command:
            check = subprocess.run(['git', '-C', str(destination / 'source'), 'rev-parse', 'HEAD'],
                                   shell=False, capture_output=True, text=True, timeout=30)
            if check.returncode or check.stdout.strip() != COMMIT:
                raise ValueError('Source revision does not match the pinned commit; refusing build.')
    license_path = destination / 'source/LICENSE'
    if not license_path.is_file():
        raise ValueError('Pinned upstream license is missing; build files retained, no MCP registration attempted.')
    shutil.copy2(license_path, destination / 'LICENSE.AgentController')
    notice_path = destination / 'source/NOTICE'
    if not notice_path.is_file():
        raise ValueError('Pinned upstream NOTICE is missing; no MCP registration attempted.')
    shutil.copy2(notice_path, destination / 'NOTICE.AgentController')
    executable = Path(result['commandAfterBuild'])
    if not executable.is_file():
        raise ValueError('Build produced no expected executable; no registration attempted.')
    provenance = {key: result[key] for key in ('source', 'commit', 'license')}
    provenance['binarySha256'] = hashlib.sha256(executable.read_bytes()).hexdigest()
    (destination / 'source-provenance.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    return {'status': 'built', **result,
            'next': 'Pass commandAfterBuild to install.py --agentcontroller-command. Review platform permissions locally.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--runtime', choices=('win-x64', 'win-arm64'), default='win-x64')
    parser.add_argument('--build-windows', action='store_true', help='Explicitly fetch pinned source and build with .NET 9.')
    parser.add_argument('--dotnet-command', help='Existing .NET executable; otherwise PATH and Windows ProgramFiles are checked.')
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.destination, args.runtime, enabled=args.build_windows, dotnet_command=args.dotnet_command), indent=2))
        return 0
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
