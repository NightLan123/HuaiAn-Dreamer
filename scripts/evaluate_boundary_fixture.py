"""Inspect numeric boundary cold priors; this is not a human-labelled benchmark."""
from __future__ import annotations
import argparse,copy,json,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT)]
from test_v221 import BoundaryTests

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'docs'/'BOUNDARY_FIXTURE_V221.json')
    args=parser.parse_args();case=BoundaryTests();case.setUp();rows=[]
    try:
        seed=case.seed()
        for label,relation in [('stranger',{}),('familiar',{'familiarity':.5,'interactions':15}),('close',{'familiarity':.95,'trust':.9,'affection':.9,'interactions':100})]:
            for stress in (.1,.9):
                for strength in (.1,.8):
                    boundary=copy.deepcopy(seed);boundary['stable_sensitivity']=strength
                    estimate=case.estimate(boundary,relation,stress)
                    selected=case.r.engine.boundaries.policy({'action':'reply','gate':'weighted_policy','scores':{},'knowledge':{}},[estimate],{'semantic':{'disengagement':0}},[])
                    rows.append({'relation':label,'stress':stress,'seed_strength':strength,'activation':estimate['activation'],
                                 'canonical_action':selected['action'],'social_action':selected.get('boundary',{}).get('action','answer')})
        mention=case.estimate(seed,request=0)['activation'];metrics=case.r.engine.boundaries.status()['metrics']
    finally:case.tearDown()
    result={'version':'2.2.1','kind':'controlled_numeric_fixture','human_labelled_samples':0,'calibrated':False,
            'semantic_cues':'explicit synthetic inputs; no real language-understanding accuracy measured',
            'keyword_api_numeric_precision_comparison':None,'real_qq_latency':None,
            'interpretation':'验证输入条件确实进入独立数值头，不证明初始权重符合人的心理，也不证明 API 或语义识别精度。',
            'mention_without_request_activation':mention,'cold_prior_metrics':metrics,'scenarios':rows}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'scenarios':len(rows),'output':str(args.output),'calibrated':False},ensure_ascii=False))

if __name__=='__main__':main()
