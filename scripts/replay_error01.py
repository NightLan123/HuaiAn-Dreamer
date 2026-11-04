"""Reproduce synthetic equivalents of ERROR-01; never read private user logs."""
from __future__ import annotations
import argparse,json,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT)]
from test_v221 import ErrorFlowTests
from persona.execution import public_trace

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'docs'/'ERROR_REPLAY_V221.json')
    args=parser.parse_args();rows=[]
    names=['test_failure_fixture_single_path_repairs_once_then_blocks',
           'test_candidate_mismatch_limited_regeneration_no_ghost_memory',
           'test_receipt_survives_commit_crash_and_restart_recovers_once',
           'test_crash_after_local_commit_is_idempotent',
           'test_background_failure_keeps_sent_fact_then_retry_only_learning']
    for name in names:
        case=ErrorFlowTests(name);case.setUp();started=time.monotonic()
        try:
            getattr(case,name)()
            rows.append({'case':name,'passed':True,'fixture_runtime_ms':round((time.monotonic()-started)*1000),
                         'injected_first_candidate_chars':25 if name=='test_candidate_mismatch_limited_regeneration_no_ghost_memory' else None,
                         'remote_send_invocations':len(case.sent),'committed_turns':case.r.store.meta('state')['turn_count'],
                         'stored_assistant_messages':len(case.r.store.rows("SELECT id FROM messages WHERE role='assistant'")),
                         'stored_memory_count':len(case.r.store.memories()),
                         'trace':public_trace(case.r.engine.journal.recent()[0])})
        finally:case.tearDown()
    result={'version':'2.2.1','kind':'synthetic_equivalent_fault_injection','live_qq':False,'live_model':False,
            'original_failed_http_body_available':False,
            'interpretation':'原日志只证明阶段、耗时和候选字符数。此处重建同类故障，不声称重放了缺失的原始响应或确认了旧故障的具体坏字段。',
            'original_timing_evidence':'FAILURE_EVIDENCE_REDACTED.json','cases':rows}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'passed':len(rows),'output':str(args.output),'live_qq':False},ensure_ascii=False))

if __name__=='__main__':main()
