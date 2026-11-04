"""Export reviewable source with a deterministic index; never export runtime data."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ROOT_FILES={'run.py','run_pmm_service.py','launcher.py','requirements.txt','requirements-learning.txt','README.md','RELEASE.json','Start_HuaiAn.cmd','Check_Environment.cmd','start_windows.bat','start_pmm_windows.bat','start_mac_linux.sh','start_pmm_mac_linux.sh'}
TREES={'persona':{'.py','.json'},'web':{'.html','.js','.css','.svg'},'tests':{'.py','.js'},'scripts':{'.py'},'examples':{'.py','.json'},'docs':{'.md','.json'}}

def files(root=ROOT):
    root=Path(root).resolve();out=[]
    candidates=[root/name for name in ROOT_FILES]
    for name in TREES:
        directory=root/name
        if directory.is_dir() and not directory.is_symlink():candidates.extend(directory.rglob('*'))
    for p in candidates:
        rel=p.relative_to(root)
        if not p.is_file() or p.is_symlink() or any(part.startswith('.') or part in ('__pycache__','node_modules') for part in rel.parts):continue
        if not p.resolve().is_relative_to(root):continue
        if str(rel) in ROOT_FILES or len(rel.parts)>1 and rel.parts[0] in TREES and p.suffix in TREES[rel.parts[0]]:out.append(p)
    return sorted(out,key=lambda p:p.relative_to(root).as_posix())

def build(root=ROOT):
    root=Path(root);release=json.loads((root/'RELEASE.json').read_text('utf-8')) if (root/'RELEASE.json').exists() else {}
    version=release.get('version','unknown')
    lines=[f'# 槐安梦客 / HuaiAn Dreamer — 完整源码 {version}', '', '这份文件包含实际源码，不是摘要。每个文件按 BEGIN FILE / END FILE 分隔。',
           '不包含运行数据、对话、API 密钥、配置、虚拟环境或日志。阅读指定模块时请使用代码索引的行号。','']
    rows=[]
    for p in files(root):
        path=p.relative_to(root).as_posix();raw=p.read_bytes();sha=hashlib.sha256(raw).hexdigest();code=raw.decode('utf-8').splitlines()
        lines.extend([f'## BEGIN FILE: {path}',f'SHA256: {sha}','````text']);start=len(lines)+1
        lines.extend(code);end=len(lines);lines.extend(['````',f'## END FILE: {path}',''])
        rows.append({'path':path,'sha256':sha,'source_start_line':start,'source_end_line':end,'lines':len(code)})
    source='\n'.join(lines)+'\n';combined=hashlib.sha256(source.encode()).hexdigest()
    index=[f'# 槐安梦客 {version} — 代码索引','','对应源码文件：HuaiAn_Dreamer_Source.md',f'完整源码文本 SHA256：`{combined}`','',
           '请在后续对话中附上或选择这两份文件。让对话先读本索引，再读源码中对应行区间，并核对版本和 SHA256。仅凭版本说明不能证明检查过代码；没有文件访问能力的对话仍需重新附上文件。','',
           '优先入口：2.8.1 当前规格 docs/V281_SPEC.md；验收 docs/V281_ACCEPTANCE.md；公式与实验 docs/V281_MATH_EXPERIMENTS.md；双模型 docs/V281_DUAL_API.md；迁移 docs/V281_MIGRATION.md。正式回合 persona/engine.py、pmm_coordinator.py；情绪计算 affect_dynamics_v2.py、affect_response.py、affect_regulation.py；状态 affect_runtime.py；训练 affect_training.py、affect_learning.py；A/B 分别见 pmm_event_reasoner.py、pmm_negotiator.py、pmm_connections.py。先前人格公式 P-A—P-E、纵向提案保留在 trait_dynamics.py、pmm_trainer.py、trait_estimator.py、pmm_longitudinal.py。原始 2.7 / 2.8 完整归档位于 ZIP 内 legacy/。Windows 启动 Start_HuaiAn.cmd。','',
           '导出当前安装目录的源码：双击打开程序 → 后台诊断记录 → 下载完整源码、代码索引。开发者也可运行 `python scripts/export_sources.py`。导出按白名单选择源文件，运行数据不会混入。','',
           '| 文件 | 源码文本起始行 | 结束行 | SHA256 |','|---|---:|---:|---|']
    index.extend(f"| {r['path']} | {r['source_start_line']} | {r['source_end_line']} | {r['sha256']} |" for r in rows)
    return {'source':source,'index':'\n'.join(index)+'\n','manifest':rows,'sha256':combined}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'exports');args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    result=build()
    for key,name in [('source','HuaiAn_Dreamer_Source.md'),('index','HuaiAn_Dreamer_Code_Index.md')]:
        (args.output/name).write_text(result[key],encoding='utf-8',newline='\n')
    print(json.dumps({'files':len(result['manifest']),'source_sha256':result['sha256'],'output':str(args.output)},ensure_ascii=False))
if __name__=='__main__':main()
