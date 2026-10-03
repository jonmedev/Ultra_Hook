"""Validate an audited release snapshot without executing its Python or hook code."""
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile
from urllib.parse import unquote

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('_ultra_release_build', Path(__file__).with_name('build_release.py'))
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)


def require(condition, classification):
    if not condition:
        raise ValueError(classification)


def validate(root=ROOT):
    snapshot = builder.capture_snapshot(root)
    plugin = 'plugins/ultra-hook/'
    portable = json.loads(snapshot[plugin + 'plugin.json'])
    compatible = json.loads(snapshot[plugin + '.codex-plugin/plugin.json'])
    require(portable.get('name') == compatible.get('name') == 'ultra-hook', 'plugin-name-mismatch')
    version = portable.get('version')
    require(isinstance(version, str) and re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-z0-9.]+)?', version), 'invalid-version')
    require(version == compatible.get('version'), 'plugin-version-mismatch')
    marketplace = json.loads(snapshot['.agents/plugins/marketplace.json'])
    require(marketplace.get('name') == 'ultra-hook', 'marketplace-name-mismatch')
    entries = marketplace.get('plugins')
    require(isinstance(entries, list) and len(entries) == 1, 'unexpected-marketplace-entries')
    require(entries[0].get('name') == 'ultra-hook' and entries[0].get('source') ==
            {'source': 'local', 'path': './plugins/ultra-hook'}, 'unexpected-plugin-source')
    hooks = json.loads(snapshot[plugin + 'hooks/hooks.json'])['hooks']
    require(set(hooks) == {'SessionStart', 'UserPromptSubmit', 'PreToolUse'}, 'unexpected-hook-events')
    handlers = [handler for groups in hooks.values() for group in groups for handler in group['hooks']]
    require(len(handlers) == 5, 'unexpected-hook-count')
    for handler in handlers:
        require(handler.get('type') == 'command', 'unsupported-hook-handler')
        command = handler.get('command')
        match = re.fullmatch(r'node "\$\{PLUGIN_ROOT\}/(hooks/[a-z-]+\.(?:js|cjs))"', command or '')
        require(match is not None and plugin + match[1] in snapshot, 'invalid-portable-hook-command')
        timeout = handler.get('timeout')
        require(type(timeout) in (int, float) and 0 < timeout <= 5, 'invalid-hook-timeout')
    # Claude Code installs the repository root as the plugin, so the Codex
    # hooks/hooks.json under plugins/ultra-hook is never auto-loaded there.
    claude = json.loads(snapshot['.claude-plugin/plugin.json'])
    require(claude.get('name') == 'ultra-hook' and claude.get('version') == version, 'claude-manifest-mismatch')
    require(claude.get('skills') == './' + plugin + 'skills/' and
            claude.get('hooks') == './' + plugin + 'hooks/claude-hooks.json', 'unexpected-claude-components')
    claude_market = json.loads(snapshot['.claude-plugin/marketplace.json'])
    claude_entries = claude_market.get('plugins')
    require(claude_market.get('name') == 'ultra-hook' and isinstance(claude_entries, list) and len(claude_entries) == 1
            and claude_entries[0].get('name') == 'ultra-hook' and claude_entries[0].get('source') == './',
            'unexpected-claude-marketplace')
    require(not any(name.startswith('hooks/') for name in snapshot), 'claude-root-hooks-autoload')
    claude_hooks = json.loads(snapshot[plugin + 'hooks/claude-hooks.json'])['hooks']
    require(set(claude_hooks) == set(hooks), 'unexpected-claude-hook-events')

    def scripts(definition, pattern):
        found = []
        for event, groups in definition.items():
            for group in groups:
                for handler in group['hooks']:
                    match = re.fullmatch(pattern, handler.get('command') or '')
                    require(handler.get('type') == 'command' and match is not None, 'invalid-claude-hook-command')
                    timeout = handler.get('timeout')
                    require(type(timeout) in (int, float) and 0 < timeout <= 5, 'invalid-hook-timeout')
                    found.append((event, match[1]))
        return sorted(found)
    claude_scripts = scripts(claude_hooks, r'node "\$\{CLAUDE_PLUGIN_ROOT\}/' + re.escape(plugin) +
                             r'(hooks/[a-z-]+\.(?:js|cjs))" --runtime=claude')
    require(claude_scripts == scripts(hooks, r'node "\$\{PLUGIN_ROOT\}/(hooks/[a-z-]+\.(?:js|cjs))"'),
            'claude-hooks-differ-from-codex')
    skills =sorted(name for name in snapshot if name.startswith(plugin + 'skills/') and name.endswith('/SKILL.md'))
    require({PurePosixPath(name).parent.name for name in skills} == {'ultra-hook', 'agentcontroller'} and
            len(skills) == 2, 'unexpected-skills')
    for name in skills:
        text = snapshot[name].decode('utf-8')
        require(text.startswith('---\n') and '\n---\n' in text[4:], 'invalid-skill-frontmatter')
        header = text.split('---', 2)[1]
        match = re.search(r'^name:\s*([a-z0-9-]+)\s*$', header, re.M)
        require(match is not None and match[1] == PurePosixPath(name).parent.name, 'invalid-skill-name')
        require(re.search(r'^description:\s*\S.+$', header, re.M), 'missing-skill-description')
    for name, data in snapshot.items():
        if not name.endswith('.md'):
            continue
        for raw_target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', data.decode('utf-8')):
            if raw_target.startswith(('https://', 'http://', '#')):
                continue
            target = unquote(raw_target.split('#')[0])
            require(bool(target) and '\\' not in target and not re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', target)
                    and not target.startswith('/'), 'nonportable-markdown-reference')
            parts = list(PurePosixPath(name).parent.parts)
            for part in PurePosixPath(target).parts:
                if part == '..':
                    require(bool(parts), 'markdown-reference-outside-release')
                    parts.pop()
                elif part != '.':
                    parts.append(part)
            require('/'.join(parts) in snapshot, 'missing-markdown-reference')
    for name, data in snapshot.items():
        if name.endswith('.py'):
            ast.parse(data.decode('utf-8'), filename=PurePosixPath(name).name)
    # Compile syntax from the captured bytes, not a file swapped after validation.
    env = {key: value for key, value in os.environ.items() if key.upper() not in {'NODE_OPTIONS', 'NODE_PATH'}}
    with tempfile.TemporaryDirectory(prefix='ultra-validate-') as directory:
        for name, data in snapshot.items():
            if name.endswith(('.cjs', '.js')):
                # Hook sources stay printable ASCII, so an invisible control or
                # combining character cannot silently change a pattern.
                require(all(byte in (9, 10) or 32 <= byte <= 126 for byte in data), 'non-ascii-hook-source')
                file = Path(directory) / PurePosixPath(name).name
                file.write_bytes(data)
                checked = subprocess.run(['node', '--check', str(file)], capture_output=True,
                                         timeout=15, env=env, shell=False)
                require(checked.returncode == 0, 'invalid-javascript-syntax')
    return {'valid': True, 'version': version, 'skills': len(skills), 'hooks': len(handlers),
            'claudeHooks': len(claude_scripts)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(validate(args.root)))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError, SyntaxError, subprocess.TimeoutExpired):
        print('Validation failed; release inputs or validation tools are invalid or unavailable.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
