"""Train a persisted emotion candidate; never publishes or changes personality."""
from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def main():
    p=argparse.ArgumentParser();p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--component',choices=['all','parameters','response','labels','regulation'],default='all');p.add_argument('--epochs',type=int,default=30);p.add_argument('--lr',type=float,default=.001);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if not (a.data_dir/'personas.json').is_file():p.error('需要已存在的主体数据目录')
    if a.output.exists() and any(a.output.iterdir()):p.error('输出目录须为空')
    from persona.lock import InstanceLock
    from persona.server import Runtime
    from persona.affect_learning import AffectLearning
    # Same data directory lock as the normal launcher.
    with InstanceLock(a.data_dir):
        app=Runtime(a.data_dir,ROOT)
        try:
            service=AffectLearning(app.engine);status=service.status();common={'subject_id':status['subject_id'],'expected_revision':status['revision']}
            imported=service.action({**common,'op':'import','dataset':json.loads(a.dataset.read_text('utf8'))})
            result=service.action({**common,'expected_revision':imported['revision'],'op':'train','dataset_id':imported['created'],'component':a.component,'epochs':a.epochs,'lr':a.lr})
            a.output.mkdir(parents=True,exist_ok=True);model=app.store.meta('pmm281_affect_models')['versions'][result['created']]
            (a.output/'candidate.json').write_text(json.dumps(model,ensure_ascii=False,indent=2));(a.output/'report.json').write_text(json.dumps(next(v['report'] for v in result['versions'] if v['version']==result['created']),ensure_ascii=False,indent=2));print(json.dumps({'candidate':result['created'],'published':False}))
        finally:app.close()

if __name__=='__main__':main()
