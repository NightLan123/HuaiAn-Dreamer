"""Train a reviewed candidate against existing evidence, without publishing it."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from persona.server import Runtime
from persona.pmm_coordinator import PMMCoordinator
from persona.common import uid

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-dir',type=Path,required=True);p.add_argument('--subject-id',required=True)
    p.add_argument('--split-plan',type=Path,required=True);p.add_argument('--parent-version')
    p.add_argument('--target',choices=['core','adapter'],default='core');p.add_argument('--epochs',type=int,default=20)
    p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    # Existing data only. A mistyped path must not create a fresh empty identity.
    if not (args.data_dir/'personas.json').is_file():p.error('Existing persona catalog is required')
    if args.output.exists() and any(args.output.iterdir()):p.error('Use an empty output directory')
    from persona.lock import InstanceLock
    with InstanceLock(args.data_dir):
        r=Runtime(args.data_dir,ROOT)
        try:
            st,_,engine,_=r.context(args.subject_id)
            cat=st.meta('pmm28_models') or {};plan=json.loads(args.split_plan.read_text('utf8'))
            result=PMMCoordinator(engine).model_action({'op':'train','subject_id':args.subject_id,'expected_revision':cat.get('revision',0),
                'job_id':'cli-'+uid(),'split_plan':plan.get('split_plan',plan),'target':args.target,'epochs':args.epochs,'version':args.parent_version})
            cat=st.meta('pmm28_models');key=result['candidate'];candidate=cat['versions'][key];report=cat['reports'][key];data=cat['datasets'][key]
            args.output.mkdir(parents=True,exist_ok=True)
            for name,value in [('candidate.json',candidate),('report.json',report),('dataset.json',data)]:
                path=args.output/name
                if path.exists():raise ValueError('Output file already exists; use a new directory')
                path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            print(json.dumps({'candidate':candidate['sha256'],'published':False,'output':str(args.output),'engineering_only':report['engineering_only']},ensure_ascii=False))
        finally:r.close()

if __name__=='__main__':main()
