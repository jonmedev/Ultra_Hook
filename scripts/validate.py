"""Validate distributable manifests, skills, references and executable syntax offline."""
import ast
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def validate(root=ROOT):
    plugin = root / 'plugins/ultra-hook'
    portable = json.loads((plugin / 'plugin.json').read_text())
    compatible = json.loads((plugin / '.codex-plugin/plugin.json').read_text())
    assert portable['name'] == compatible['name'] == 'ultra-hook'
    assert portable['version'] == compatible['version']
    assert re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-z0-9.]+)?', portable['version'])
    marketplace = json.loads((root / '.agents/plugins/marketplace.json').read_text())
    assert marketplace['name'] == 'ultra-hook'
    assert marketplace['plugins'][0]['source']['path'] == './plugins/ultra-hook'
    hooks = json.loads((plugin / 'hooks/hooks.json').read_text())['hooks']
    handlers = [h for groups in hooks.values() for group in groups for h in group['hooks']]
    assert len(handlers) == 5
    for handler in handlers:
        match = re.fullmatch(r'node "\$\{PLUGIN_ROOT\}/(hooks/[a-z-]+\.(?:js|cjs))"', handler['command'])
        assert match and (plugin / match[1]).is_file(), 'Invalid portable hook command'
        assert handler['timeout'] <= 5
    skills = sorted((plugin / 'skills').glob('*/SKILL.md'))
    assert len(skills) == 2
    for skill in skills:
        text = skill.read_text(encoding='utf-8')
        assert text.startswith('---\n') and '\n---\n' in text[4:]
        header = text.split('---', 2)[1]
        name = re.search(r'^name:\s*([a-z0-9-]+)\s*$', header, re.M)
        assert name and name[1] == skill.parent.name
        assert re.search(r'^description:\s*\S.+$', header, re.M)
    markdown = [root / 'README.md', *root.glob('docs/*.md'), *(plugin / 'skills').rglob('*.md')]
    for file in markdown:
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)', file.read_text(encoding='utf-8')):
            if target.startswith(('https://', 'http://', '#')):
                continue
            target = target.split('#')[0]
            assert not Path(target).is_absolute()
            resolved = (file.parent / target).resolve()
            assert resolved.is_relative_to(root.resolve()) and resolved.is_file(), file.relative_to(root).as_posix()
    for file in [*root.glob('scripts/*.py'), *root.glob('tests/*.py')]:
        ast.parse(file.read_text(encoding='utf-8'), filename=file.name)
    for file in [*plugin.glob('hooks/*.cjs'), *plugin.glob('hooks/*.js')]:
        checked = subprocess.run(['node', '--check', str(file)], capture_output=True, text=True)
        assert checked.returncode == 0, file.name
    return {'valid': True, 'version': portable['version'], 'skills': len(skills), 'hooks': len(handlers)}


if __name__ == '__main__':
    try:
        print(json.dumps(validate()))
    except (AssertionError, OSError, ValueError, KeyError) as error:
        print('Validation failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
