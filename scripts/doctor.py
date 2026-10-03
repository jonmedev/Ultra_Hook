#!/usr/bin/env python3
"""Read-only Ultra Hook metadata checks for Codex and Claude Code; never run a model or grant hook trust."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
from collections import Counter
import install
import claude_code
from install import CLI, InstallError, PLUGIN, REPO, SERVER, codex_home, load_config, plugin_catalog, marketplaces, stop_process, check_package, guard_path, private_bytes, emit_result, OutputParser

EXPECTED_SKILLS = {'ultra-hook:ultra-hook', 'ultra-hook:agentcontroller'}


def metadata_rows(document, key):
    if not isinstance(document, dict) or not isinstance(document.get('data', []), list):
        raise InstallError('Invalid runtime metadata shape; raw output withheld.')
    rows, errors = [], bool(document.get('errors') or document.get('warnings'))
    for entry in document.get('data', []):
        if not isinstance(entry, dict) or not isinstance(entry.get(key, []), list):
            raise InstallError('Invalid runtime metadata entries; raw output withheld.')
        errors |= bool(entry.get('errors') or entry.get('warnings'))
        for item in entry.get(key, []):
            if not isinstance(item, dict):
                raise InstallError('Invalid runtime metadata row; raw output withheld.')
            rows.append(item)
    return rows, errors


def hook_definitions_match(hooks, plugin_root):
    if plugin_root is None:
        return False
    source = plugin_root / 'hooks/hooks.json'
    try:
        manifest_bytes = private_bytes(source, limit=1024 * 1024)
        if manifest_bytes != private_bytes(REPO / 'plugins/ultra-hook/hooks/hooks.json', limit=1024 * 1024):
            return False
        manifest = json.loads(manifest_bytes)
        expected = []
        for event, groups in manifest['hooks'].items():
            runtime_event = event[0].lower() + event[1:]
            for group in groups:
                for handler in group['hooks']:
                    expected.append((runtime_event, handler['type'], handler['command'].replace('${PLUGIN_ROOT}', str(plugin_root)),
                                     group.get('matcher'), handler.get('timeout')))
        actual = []
        for hook in hooks:
            if (hook.get('source') != 'plugin' or hook.get('sourcePath') != str(source)
                    or hook.get('async') is True or hook.get('isManaged') is True):
                return False
            actual.append((hook.get('eventName'), hook.get('handlerType'), hook.get('command'),
                           hook.get('matcher'), hook.get('timeoutSec')))
        return len(expected) == 5 and Counter(actual) == Counter(expected)
    except (InstallError, OSError, ValueError, TypeError, KeyError):
        return False


def summarize_runtime(hooks_document, skills_document, mcp_document=None, *, plugin_root=None):
    hook_rows, hook_errors = metadata_rows(hooks_document, 'hooks')
    skill_rows, skill_errors = metadata_rows(skills_document, 'skills')
    hooks = [hook for hook in hook_rows if hook.get('pluginId') == PLUGIN]
    skills = [skill for skill in skill_rows if str(skill.get('name', '')).startswith('ultra-hook:')]
    trusted = [hook for hook in hooks if hook.get('enabled') and hook.get('trustStatus') == 'trusted']
    server = next((entry for entry in (mcp_document or {}).get('data', []) if isinstance(entry, dict) and entry.get('name') == SERVER), None)
    definitions_match = hook_definitions_match(hooks, plugin_root)
    skills_ready = (not skill_errors and len(skills) == 2 and {skill.get('name') for skill in skills} == EXPECTED_SKILLS
                    and all(skill.get('enabled', True) is True for skill in skills))
    ready = len(hooks) == 5 and len(trusted) == 5 and definitions_match and not hook_errors
    result = {'hookCount': len(hooks), 'trustedHookCount': len(trusted), 'skillCount': len(skills),
              'skillNames': sorted(skill.get('name', '') for skill in skills),
              'hookDefinitionsMatch': definitions_match, 'metadataErrors': hook_errors or skill_errors,
              'skillsReady': skills_ready, 'hooksReady': ready,
              'trustPending': not ready,
              'agentcontrollerRuntime': {'registered': server is not None,
                                         'toolCount': len(server.get('tools') or {}) if server else 0,
                                         'toolsError': bool(server and server.get('toolsError'))}}
    return result


def runtime_arguments(cli, cwd, *, check_agentcontroller=False):
    # Empty table overrides merge instead of clearing existing servers. Discover
    # effective names with the native CLI and verify individual disable flags.
    discovered = cli.run(['mcp', 'list', '--json'], json_output=True, timeout=15, cwd=cwd)
    if not isinstance(discovered, list) or len(discovered) > 256:
        raise InstallError('Cannot safely enumerate effective MCP registrations.')
    names = set()
    already_disabled = set()
    for item in discovered:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) or len(item['name']) > 256:
            raise InstallError('Invalid effective MCP registration metadata.')
        names.add(item['name'])
        if item.get('enabled') is False:
            already_disabled.add(item['name'])
    if len(names) != len(discovered):
        raise InstallError('Duplicate effective MCP registration names; inspection refused.')
    overrides = []
    allowed = None
    if check_agentcontroller:
        registration = load_config(cli.home).get('mcp_servers', {}).get(SERVER)
        if registration:
            # Never put credentials/env/headers from config on a process command
            # line. Only a simple local stdio registration can be inspected here.
            if (set(registration) - {'command', 'args', 'enabled', 'startup_timeout_sec', 'tool_timeout_sec'}
                    or not isinstance(registration.get('command'), str)
                    or registration.get('args') or registration.get('enabled') is False
                    or not Path(registration['command']).is_file()):
                raise InstallError('AgentController runtime check requires a reviewed simple local command without extra config.')
            allowed = registration
    flags = []
    configured = set(load_config(cli.home).get('mcp_servers', {}))
    for name in sorted(names):
        # Plugin/virtual servers may be listed as disabled without a base
        # transport. Adding even an enabled=false table synthesizes an invalid
        # transport. Leave them untouched, but verify they remain disabled below.
        if name in already_disabled:
            continue
        enabled = name == SERVER and allowed is not None
        entry = 'enabled=' + str(enabled).lower()
        if not enabled and name not in configured:
            # An enabled plugin-provided server has no profile table to merge into,
            # and a bare enabled=false is rejected as an invalid transport. This
            # placeholder is never started: the entry stays disabled.
            entry += ',command="ultra-hook-doctor-disabled"'
        flags.append(json.dumps(name, ensure_ascii=False) + '={' + entry + '}')
    # Native dotted-key overrides split dots even inside quotes. A TOML inline
    # table retains arbitrary server names and merges only the enabled fields.
    overrides = ['-c', 'mcp_servers={' + ','.join(flags) + '}'] if flags else []
    verified = cli.run(['mcp', 'list', '--json'] + overrides, json_output=True, timeout=15, cwd=cwd)
    if not isinstance(verified, list) or len(verified) != len(discovered):
        raise InstallError('MCP registrations changed during metadata planning.')
    seen = set()
    for item in verified:
        name = item.get('name') if isinstance(item, dict) else None
        if name not in names or name in seen:
            raise InstallError('MCP registrations changed during metadata planning.')
        seen.add(name)
        if name == SERVER and allowed:
            transport = item.get('transport') or {}
            if (item.get('enabled') is not True or transport.get('command') != allowed['command']
                    or transport.get('args') or transport.get('env') or transport.get('env_vars')
                    or transport.get('cwd') or transport.get('url')):
                raise InstallError('Effective AgentController differs from the reviewed simple registration.')
        elif item.get('enabled') is not False:
            raise InstallError('Native config did not disable all unexpected MCP servers; inspection refused.')
    return ['app-server', '--stdio'] + overrides


def runtime_metadata(cli, cwd, timeout=35, *, check_agentcontroller=False):
    package_version = check_package(REPO)
    plugin_root = cli.home / 'plugins/cache/ultra-hook/ultra-hook' / package_version
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    process = subprocess.Popen(cli.prefix + runtime_arguments(cli, cwd, check_agentcontroller=check_agentcontroller), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                               encoding='utf-8', errors='replace', shell=False, env=cli.env,
                               cwd=cwd, creationflags=creationflags, start_new_session=sys.platform != 'win32')
    inbox = queue.Queue(maxsize=64)
    fault = threading.Event()
    deadline = time.monotonic() + timeout
    def reader():
        budget = 8 * 1024 * 1024
        try:
            while True:
                line = process.stdout.readline(1024 * 1024 + 1)
                if not line:
                    inbox.put_nowait(None)
                    return
                budget -= len(line.encode('utf-8'))
                if budget < 0 or len(line) > 1024 * 1024:
                    raise ValueError('frame limit')
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError('frame shape')
                inbox.put_nowait(message)
        except (ValueError, queue.Full, OSError):
            fault.set()
    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()
    counter = 0
    def request(method, params):
        nonlocal counter
        counter += 1
        identity = counter
        process.stdin.write(json.dumps({'id': identity, 'method': method, 'params': params}) + '\n')
        process.stdin.flush()
        while True:
            if fault.is_set():
                raise InstallError('Runtime metadata output was invalid or exceeded limits; raw output withheld.')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InstallError('Runtime metadata inspection timed out; trust remains pending.')
            try:
                message = inbox.get(timeout=min(remaining, 0.1))
            except queue.Empty as exc:
                continue
            if message is None:
                raise InstallError('App server ended before metadata inspection completed.')
            if message.get('id') == identity and 'method' not in message:
                if 'error' in message:
                    raise InstallError('Installed app-server does not support this metadata request; trust remains pending.')
                result = message.get('result', {})
                if not isinstance(result, dict):
                    raise InstallError('Invalid runtime metadata result; raw output withheld.')
                return result
            if 'id' in message and 'method' in message:
                # Deny unexpected server requests; no prompts or delegated operations.
                process.stdin.write(json.dumps({'id': message['id'], 'error':
                    {'code': -32601, 'message': 'Metadata-only doctor does not handle interactive requests.'}}) + '\n')
                process.stdin.flush()
    try:
        request('initialize', {'clientInfo': {'name': 'ultra-hook-doctor', 'version': package_version},
                              'capabilities': {'experimentalApi': True}, 'requestAttestation': False})
        process.stdin.write(json.dumps({'method': 'initialized'}) + '\n')
        process.stdin.flush()
        hooks = request('hooks/list', {'cwds': [str(Path(cwd).resolve())]})
        skills = request('skills/list', {'cwds': [str(Path(cwd).resolve())], 'forceReload': True})
        mcp = None
        if check_agentcontroller and SERVER in load_config(cli.home).get('mcp_servers', {}):
            mcp = request('mcpServerStatus/list', {'serverName': SERVER})
        return summarize_runtime(hooks, skills, mcp, plugin_root=plugin_root)
    finally:
        stop_process(process)
        process.stdin.close()
        reader_thread.join(timeout=1)
        if not reader_thread.is_alive():
            process.stdout.close()


def inspect(cli, cwd=REPO, *, check_agentcontroller=False):
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
        result['runtime'] = runtime_metadata(cli, cwd, check_agentcontroller=check_agentcontroller)
    except (InstallError, OSError, ValueError, TypeError, KeyError):
        result['runtime'] = {'hooksReady': False, 'trustPending': True,
                             'trustedHookCount': 0, 'skillCount': 0, 'diagnostic': 'Runtime metadata unavailable or invalid; inspection remains pending.'}
    result['uiTransportDiscovered'] = bool(result['runtime'].get('agentcontrollerRuntime', {}).get('toolCount'))
    result['uiValidation'] = 'not-run; target assertions required'
    result['agentcontrollerCheckRequested'] = check_agentcontroller
    result['ready'] = result['enabled'] and result['runtime'].get('hooksReady', False) and result['runtime'].get('skillsReady', False)
    return result


def main():
    parser = OutputParser(description=__doc__)
    parser.add_argument('--codex-home')
    parser.add_argument('--codex-command')
    parser.add_argument('--cwd', type=Path, default=REPO)
    parser.add_argument('--json', action='store_true', help='Emit safe JSON only, for automation (default: readable summary).')
    parser.add_argument('--check-agentcontroller', action='store_true', help='Explicitly start only a reviewed local AgentController stdio registration for metadata.')
    install.add_runtime_arguments(parser)
    args = parser.parse_args()
    result = None
    try:
        if install.codex_selected(args):
            result = inspect(CLI(codex_home(args.codex_home), args.codex_command), args.cwd, check_agentcontroller=args.check_agentcontroller)
    except InstallError as exc:
        result = {'status': 'error', 'message': str(exc)}
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        result = {'status': 'error', 'message': 'Inspection failed; private diagnostics withheld.'}
    claude = claude_code.run_step('doctor', args.claude_code, lambda home, cli: claude_code.inspect(REPO, cli),
                                  home=args.claude_home, command=args.claude_command)
    code = install.finish('doctor', result, claude, json_output=args.json)
    ready = all(part.get('ready') for part in (result, claude) if part is not None and part.get('status') != 'skipped')
    return code or (0 if ready else 2)


if __name__ == '__main__':
    sys.exit(main())
