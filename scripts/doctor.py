#!/usr/bin/env python3
"""Read-only Ultra Hook metadata checks; never run a model or grant hook trust."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from install import CLI, InstallError, PLUGIN, REPO, SERVER, codex_home, load_config, plugin_catalog, marketplaces


def summarize_runtime(hooks_document, skills_document, mcp_document=None):
    hooks = [hook for entry in hooks_document.get('data', []) for hook in entry.get('hooks', [])
             if hook.get('pluginId') == PLUGIN]
    skills = [skill for entry in skills_document.get('data', []) for skill in entry.get('skills', [])
              if str(skill.get('name', '')).startswith('ultra-hook:')]
    trusted = [hook for hook in hooks if hook.get('enabled') and hook.get('trustStatus') == 'trusted']
    server = next((entry for entry in (mcp_document or {}).get('data', []) if entry.get('name') == SERVER), None)
    result = {'hookCount': len(hooks), 'trustedHookCount': len(trusted), 'skillCount': len(skills),
              'skillNames': sorted(skill.get('name', '') for skill in skills),
              'hooksReady': len(hooks) == 5 and len(trusted) == 5,
              'trustPending': len(hooks) != 5 or len(trusted) != 5,
              'agentcontrollerRuntime': {'registered': server is not None,
                                         'toolCount': len(server.get('tools') or {}) if server else 0,
                                         'toolsError': bool(server and server.get('toolsError'))}}
    return result


def runtime_metadata(cli, cwd, timeout=35):
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    process = subprocess.Popen(cli.prefix + ['app-server', '--stdio'], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                               encoding='utf-8', errors='replace', shell=False, env=cli.env,
                               cwd=cwd, creationflags=creationflags)
    inbox = queue.Queue()
    def reader():
        for line in process.stdout:
            try:
                inbox.put(json.loads(line))
            except ValueError:
                pass
        inbox.put(None)
    threading.Thread(target=reader, daemon=True).start()
    counter = 0
    def request(method, params):
        nonlocal counter
        counter += 1
        identity = counter
        process.stdin.write(json.dumps({'id': identity, 'method': method, 'params': params}) + '\n')
        process.stdin.flush()
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InstallError('Runtime metadata inspection timed out; trust remains pending.')
            try:
                message = inbox.get(timeout=remaining)
            except queue.Empty as exc:
                raise InstallError('Runtime metadata inspection timed out; trust remains pending.') from exc
            if message is None:
                raise InstallError('App server ended before metadata inspection completed.')
            if message.get('id') == identity and 'method' not in message:
                if 'error' in message:
                    raise InstallError('Installed app-server does not support this metadata request; trust remains pending.')
                return message.get('result', {})
            if 'id' in message and 'method' in message:
                # Deny unexpected server requests; no prompts or delegated operations.
                process.stdin.write(json.dumps({'id': message['id'], 'error':
                    {'code': -32601, 'message': 'Metadata-only doctor does not handle interactive requests.'}}) + '\n')
                process.stdin.flush()
    try:
        request('initialize', {'clientInfo': {'name': 'ultra-hook-doctor', 'version': '0.1.0'},
                              'capabilities': {'experimentalApi': True}, 'requestAttestation': False})
        process.stdin.write(json.dumps({'method': 'initialized'}) + '\n')
        process.stdin.flush()
        hooks = request('hooks/list', {'cwds': [str(Path(cwd).resolve())]})
        skills = request('skills/list', {'cwds': [str(Path(cwd).resolve())], 'forceReload': True})
        mcp = None
        if SERVER in load_config(cli.home).get('mcp_servers', {}):
            mcp = request('mcpServerStatus/list', {'serverName': SERVER})
        return summarize_runtime(hooks, skills, mcp)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for stream in (process.stdin, process.stdout):
            if stream:
                stream.close()


def inspect(cli, cwd=REPO):
    config = load_config(cli.home)
    market = marketplaces(cli).get('ultra-hook')
    installed = plugin_catalog(cli).get(PLUGIN) if market else None
    server = config.get('mcp_servers', {}).get(SERVER, {})
    result = {'plugin': PLUGIN, 'installed': bool(installed),
              'enabled': bool(installed and installed.get('enabled')),
              'version': installed.get('version') if installed else None,
              'marketplaceRegistered': bool(market),
              'agentcontroller': {'registered': bool(server),
                                  'commandExists': bool(server.get('command') and Path(server['command']).is_file())},
              'trustManagedAutomatically': False}
    try:
        result['runtime'] = runtime_metadata(cli, cwd)
    except (InstallError, OSError) as exc:
        result['runtime'] = {'hooksReady': False, 'trustPending': True,
                             'trustedHookCount': 0, 'skillCount': 0, 'diagnostic': str(exc)}
    result['uiTransportDiscovered'] = bool(result['runtime'].get('agentcontrollerRuntime', {}).get('toolCount'))
    result['uiValidation'] = 'not-run; target assertions required'
    result['ready'] = result['enabled'] and result['runtime'].get('hooksReady', False) and result['runtime'].get('skillCount') == 2
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home')
    parser.add_argument('--codex-command')
    parser.add_argument('--cwd', type=Path, default=REPO)
    parser.add_argument('--json', action='store_true', help='Emit safe JSON metadata (also the default).')
    args = parser.parse_args()
    try:
        result = inspect(CLI(codex_home(args.codex_home), args.codex_command), args.cwd)
        print(json.dumps(result, indent=2))
        return 0 if result['ready'] else 2
    except (InstallError, OSError, ValueError) as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
