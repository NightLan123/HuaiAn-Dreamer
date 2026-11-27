"""Export the public source manifest, never discover runtime data recursively.

The HTTP download handler consumes build()'s existing source/index/manifest/sha256
shape. Extend SOURCE_MANIFEST.json deliberately when adding public source files.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def files(root=ROOT):
    root = Path(root).resolve()
    manifest = json.loads((root / 'SOURCE_MANIFEST.json').read_text('utf-8'))
    result = []
    for item in manifest['files']:
        relative = Path(item['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid source manifest path')
        path = root / relative
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Missing or unsafe public source file: ' + item['path'])
        if path.suffix in {'.py', '.js', '.html', '.css', '.svg', '.json', '.md', '.txt', '.cmd', '.bat', '.sh'} or path.name in {'.gitignore', '.gitattributes'}:
            result.append(path)
    return sorted(result)

def build(root=ROOT):
    root = Path(root)
    lines = ['# HuaiAn Dreamer — public source', '', 'Current source files; runtime data is excluded.', '']
    rows = []
    for path in files(root):
        raw = path.read_bytes(); name = path.relative_to(root).as_posix()
        sha = hashlib.sha256(raw).hexdigest()
        lines.extend(['## BEGIN FILE: ' + name, 'SHA256: ' + sha, '````text'])
        start = len(lines) + 1; code = raw.decode('utf-8-sig').splitlines()
        lines.extend(code); end = len(lines); lines.extend(['````', '## END FILE: ' + name, ''])
        rows.append({'path': name, 'sha256': sha, 'source_start_line': start, 'source_end_line': end, 'lines': len(code)})
    source = '\n'.join(lines) + '\n'; sha = hashlib.sha256(source.encode('utf-8')).hexdigest()
    index = ['# Public source index', '', 'SHA256: ' + sha, '', '| File | Start | End |', '| --- | ---: | ---: |']
    index.extend('| {path} | {source_start_line} | {source_end_line} |'.format(**row) for row in rows)
    return {'source': source, 'index': '\n'.join(index) + '\n', 'manifest': rows, 'sha256': sha}

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, default=ROOT / 'exports')
    args = parser.parse_args(); result = build(); args.output.mkdir(parents=True, exist_ok=True)
    for key, name in [('source', 'HuaiAn_Dreamer_Source.md'), ('index', 'HuaiAn_Dreamer_Code_Index.md')]:
        (args.output / name).write_text(result[key], encoding='utf-8')
    print('Exported', len(result['manifest']), 'public source files.')

if __name__ == '__main__':
    main()
