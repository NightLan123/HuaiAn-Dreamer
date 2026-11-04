"""Reproduce API-PMM and Learned-PMM local controlled conditions, no API keys."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_v27_stage3 import runtime_comparison

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'docs'/'V27_ABLATION.json');args=p.parse_args()
    result={'version':'2.7','dataset':'synthetic_held_conditions','external_model_calls':False,'psychological_validity_established':False,
        'runs':[runtime_comparison(m) for m in ('api','learned')]}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output':str(args.output),'full_runtime_conditions':16,'local_repeatable_ablations':36,'active_component_comparisons':6,'real_provider':False}))
if __name__=='__main__':main()
