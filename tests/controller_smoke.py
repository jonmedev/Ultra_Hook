"""Opt-in upstream acquisition and MCP smoke; never claims desktop UI validation."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import setup_agentcontroller as setup
from install import stop_process


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    destination = args.destination.absolute()
    if destination.exists():
        raise RuntimeError('Integration test requires a fresh destination.')
    plan = setup.acquire(destination, dry_run=True)
    assert plan['status'] == 'plan' and not destination.exists()
    first = setup.acquire(destination)
    second = setup.acquire(destination)
    assert first['command'] == second['command']
    assert first['provenance'] == second['provenance']
    if not first['command']:
        assert first['status'] == 'pending' and first.get('next')
        print(json.dumps({'downloadVerified': True, 'repeatAcquisition': True,
                          'manualPlatformSetupPending': True, 'uiValidation': 'not-run'}))
        return 0
    requests = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'ultra-hook-controller-smoke', 'version': '1'}}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}}
    ]
    env = setup.public_build_environment(destination, sys.executable)
    process = subprocess.Popen([first['command']], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, cwd=destination, env=env, text=True,
                               encoding='utf-8', start_new_session=os.name != 'nt',
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        output, _ = process.communicate(''.join(json.dumps(row) + '\n' for row in requests), timeout=35)
        assert process.returncode == 0 and len(output) < 4 * 1024 * 1024
        replies = [json.loads(line) for line in output.splitlines() if line.strip()]
        initialized = next(row for row in replies if row.get('id') == 1)
        catalog = next(row for row in replies if row.get('id') == 2)
        assert 'error' not in initialized and 'error' not in catalog
        names = {tool['name'] for tool in catalog['result']['tools']}
        assert {'snapshot', 'type_text', 'click', 'assert_visible', 'assert_value', 'screenshot_window'} <= names
        assert len(names) == 52
        print(json.dumps({'downloadVerified': True, 'repeatAcquisition': True,
                          'mcpInitialized': True, 'toolCount': len(names), 'uiValidation': 'not-run'}))
        return 0
    finally:
        stop_process(process)


if __name__ == '__main__':
    raise SystemExit(main())
