"""External experience evidence feeds the existing trait profile and slow gate.

No alternate personality state. Generated replies locate actual experiences but
cannot supply a target label. Engineering eligibility is not psychometric validity.
"""
from __future__ import annotations
import copy
from .common import now
from .registry import LONG_IDS, digest, update_trait_evidence
from . import traits as tr, learning as learn

INSTRUCTION='''\n[SELF_EXPERIENCE_V27] 可选 self_experience_updates 只从 user_record 中明确评价 AI 既往行为的外部反馈提取，不使用 self_record、用户自述的性格或本轮情绪。没有明确反馈时返回 []。
每项含 target_entity="agent_self", evidence_kind="external_feedback", experience_turn_id（prior_interactions 中真实回合ID）, feature_id（稳定人格或 BEQ/ERQ/PANAS 长期字段）, estimate, confidence, timeframe（人格 sustained；长期习惯按注册表）, evidence:[{record_id,quote}]。引用逐字原文；这是待审查假设，不能自称正式测量或直接修改人格。单个事件和多次评价只算一个独立经历。可选 context_label 为简短情境类别，context_quote 必须逐字来自 prior_interactions 对应 original_input；没有依据则不填写。'''

class Formation:
    def __init__(self,engine):self.e=engine;self.st=engine.store
    def interactions(self,scope,person,limit=20,before=None):
        return self.st.rows("SELECT m.turn_id,MIN(m.created_at) AS timestamp,GROUP_CONCAT(m.content, char(10)) AS actual_reply,(SELECT GROUP_CONCAT(mu.content, char(10)) FROM messages mu WHERE mu.turn_id=m.turn_id AND mu.role='user') AS original_input FROM messages m JOIN sessions s ON m.session_id=s.id WHERE EXISTS (SELECT 1 FROM events ev WHERE ev.kind IN ('turn','expression_partial') AND json_extract(ev.payload,'$.turn_id')=m.turn_id AND json_extract(ev.payload,'$.scope')=? AND json_extract(ev.payload,'$.person')=?) AND m.role='assistant' AND m.content<>'' AND m.created_at<? GROUP BY m.turn_id ORDER BY timestamp DESC LIMIT ?",(scope,person,before if before is not None else now(),max(1,min(50,limit))))
    def collect(self,profile,rows,records,session,manual=False):
        p=tr.ensure_traits(profile);gate=learn.permission(self.e,'self',session['scope'],session['person'],manual=manual,observed_only=not session.get('direct_interaction',True))
        report={'accepted':0,'rejected':[],'promoted':0,'source_keys':[]}
        if not gate['allowed']:report['blocked']=gate['reasons'];return p,report
        byid={r['id']:r for r in records};valid_records=[]
        if not isinstance(rows,list):return p,{**report,'rejected':['invalid_list']}
        for row in rows[:100]:
            try:
                if not isinstance(row,dict) or row.get('target_entity')!='agent_self' or row.get('evidence_kind') not in ('external_feedback','owner_evaluation'):raise ValueError('不是对 AI 自身行为的独立外部评价')
                k=row.get('feature_id')
                if k not in (*LONG_IDS,*tr.DISPOSITIONS):raise ValueError('即时状态不能写入长期人格')
                required=tr.DISPOSITIONS[k]['required_timeframe'] if k in tr.DISPOSITIONS else 'sustained'
                if row.get('timeframe')!=required:raise ValueError('缺少相应长期时间框架')
                ev=row.get('evidence',[])
                if not isinstance(ev,list) or len(ev)!=1:raise ValueError('每条评价必须明确一个原始反馈来源')
                raw=byid.get(ev[0].get('record_id'));q=ev[0].get('quote')
                if not raw or raw.get('source') not in ('human','observed','imported') or not isinstance(q,str) or not q.strip() or q not in raw['text']:raise ValueError('原文无效或来自生成回复')
                if raw.get('scope')!=session['scope'] or (raw.get('person') or raw.get('speaker')) not in (session['person'],'owner'):raise ValueError('反馈人物或范围不匹配')
                target=row.get('experience_turn_id')
                turns=self.st.rows("SELECT m.created_at,json_extract(ev.payload,'$.scope') AS scope,json_extract(ev.payload,'$.person') AS person FROM messages m JOIN events ev ON ev.kind IN ('turn','expression_partial') AND json_extract(ev.payload,'$.turn_id')=m.turn_id WHERE m.turn_id=? AND m.role='assistant' AND m.content<>'' LIMIT 1",(target,))
                if not turns or turns[0]['scope']!=session['scope'] or turns[0]['person']!=session['person']:raise ValueError('被评价经历未实际发送或不属于当前人物/范围')
                if (tr.event_time(raw) or 0)<turns[0]['created_at']:raise ValueError('反馈不能早于被评价的经历')
                if target==raw.get('event_id') and raw.get('source')!='human':raise ValueError('当前输入不能评价尚未发出的回复')
                # Same experience receives one independent vote, even from many
                # raters/quotes/feedback messages. Never manufacture chronology.
                record={**copy.deepcopy(raw),'subject_entity':'agent_self','evidence_kind':row['evidence_kind'],
                    'experience_turn_id':target,'experience_event_key':digest([session['scope'],p['id'],target]),
                    'experience_timestamp':turns[0]['created_at']}
                label=row.get('context_label');cq=row.get('context_quote')
                if label or cq:
                    inputs=self.st.rows("SELECT content FROM messages WHERE turn_id=? AND role='user'",(target,))
                    if not isinstance(label,str) or not label.strip() or len(label)>100 or not isinstance(cq,str) or not cq.strip() or not any(cq in i['content'] for i in inputs):raise ValueError('情境标签须引用被评价经历的实际用户输入')
                    record.update(experience_context_key=digest([session['scope'],label.strip()]),experience_context={'label':label.strip(),'quote':cq,'source':'owner_annotation' if row['evidence_kind']=='owner_evaluation' else 'model_inference'})
                existing={r['id']:r for r in p['psychology']['evidence_records']}.get(record['id'])
                if existing and existing.get('experience_turn_id')!=target:raise ValueError('同一反馈原文不能重定向到另一经历')
                candidate={k2:copy.deepcopy(row[k2]) for k2 in ('feature_id','estimate','confidence','evidence','timeframe') if k2 in row}
                if k in tr.DISPOSITIONS:
                    p,stats=tr.observe_dispositions(p,[candidate],[record],'human' if row['evidence_kind']=='owner_evaluation' else 'observed')
                    if stats['accepted'] and not existing:p['psychology']['evidence_records'].append(record)
                else:p['psychology'],stats=update_trait_evidence(p['psychology'],[candidate],[record],'human' if row['evidence_kind']=='owner_evaluation' else 'observed')
                if stats['rejected']:raise ValueError('特征数值或逐字证据无效')
                if stats['accepted']:report['accepted']+=stats['accepted'];valid_records.append(record)
            except (ValueError,TypeError,KeyError) as exc:report['rejected'].append(str(exc))
        if valid_records:
            p['revision']+=1;p['updated_at']=now()
            if self.e.config.get()['pmm28']['mode']!='active' and (manual or gate['mode']=='automatic'):p,promotion=tr.review(p,True,strength=gate['strength']);report['promotion']=promotion;report['promoted']=promotion['promoted']
            rs=self.e.evidence.register(valid_records,'self-experience')
            report['source_keys']=[r['origin_record_key'] for r in rs]
            self.e.evidence.complete('self_experience',valid_records,'experience:'+digest(report['source_keys']),
                {'trait_version':profile['trait_profile']['version'],'revision':profile['revision']},
                {'trait_version':p['trait_profile']['version'],'revision':p['revision'],'changes':p['trait_profile']['promotion_history'][len(profile['trait_profile']['promotion_history']):]},
                'external-experience',{'experience_turn_ids':sorted({r['experience_turn_id'] for r in valid_records})})
        return p,report
    def annotate(self,body):
        with self.e.lock,self.st.lock,self.st.db:
            p=self.e.profile()
            if body.get('expected_version')!=p['trait_profile']['version']:raise ValueError('人格版本已变化，请刷新')
            turn=body.get('experience_turn_id');rows=self.st.rows("SELECT m.created_at,json_extract(ev.payload,'$.scope') AS scope,json_extract(ev.payload,'$.person') AS person FROM messages m JOIN events ev ON ev.kind IN ('turn','expression_partial') AND json_extract(ev.payload,'$.turn_id')=m.turn_id WHERE m.turn_id=? AND m.role='assistant' AND m.content<>'' LIMIT 1",(turn,))
            if not rows:raise ValueError('只能评价确实发送过的经历')
            s=rows[0];note=body.get('note','').strip()
            if not note or len(note)>6000:raise ValueError('请填写具体行为依据，最多6000字')
            rid='owner-evaluation:'+digest([turn,note]);record={'id':rid,'speaker':'owner','person':'owner','scope':s['scope'],'text':note,'context':'','event_id':turn,'timestamp':now(),'source':'human'}
            row={**body,'target_entity':'agent_self','evidence_kind':'owner_evaluation','evidence':[{'record_id':rid,'quote':note}]}
            new,report=self.collect(p,[row],[record],s,manual=True)
            if report.get('blocked'):raise ValueError('自身学习未获授权：'+','.join(report['blocked']))
            if report['rejected']:raise ValueError(report['rejected'][0])
            pending=self.queue_promotions(p,new,report,self.st.meta('pmm_training_records') or [])
            self.st.setmeta('pmm_profile',new);self.st.setmeta('pmm_training_records',pending);self.st.event('self_experience_evaluated',report)
            return report
    def queue_promotions(self,before,after,report,pending):
        """Approved stable labels use the existing PMM training queue and heads."""
        from .registry import CONTRACT,extend_vector
        from .pmm import vector
        if not report.get('promoted'):return pending
        count=len(pending)
        for change in after['trait_profile']['promotion_history'][-report['promoted']:]:
            k=change['feature_id']
            if k not in CONTRACT['feature_order']:continue
            labels=[None]*len(CONTRACT['feature_order']);labels[CONTRACT['feature_order'].index(k)]=change['after']['estimate']
            for r in tr.promotion_records(after,change):
                group=r.get('experience_event_key') or r.get('event_id') or r['id']
                pending=self.e.queue_sample(pending,'promotion:'+change['id']+':'+r['id'],extend_vector(vector(r['text'],{},before),before['psychology']),
                    psychology_target=labels,source='trait_promotion',group_id=group,
                    training_context={'schema':'typed-supervision/1','target_entity':'trait_promotion','event_id':group,'scope':r.get('scope',''),'at':r.get('experience_timestamp') or tr.event_time(r) or 0.,'source_record_id':r['id']})
        report['training_samples_added']=len(pending)-count
        report['training_destination']='现有 PMM 待训练队列；BEQ/ERQ/PANAS 使用长期条件通道，无独立神经头'
        return pending
    def withdraw(self,body):
        with self.e.lock,self.st.lock,self.st.db:
            p=self.e.profile();t=p['trait_profile']
            if body.get('expected_version')!=t['version']:raise ValueError('人格版本已变化，请刷新')
            reason=str(body.get('reason','')).strip();rid=body.get('record_id')
            r=next((r for r in p['psychology']['evidence_records'] if r['id']==rid and r.get('subject_entity')=='agent_self'),None)
            if not r or not reason:raise ValueError('请指定经历证据并填写撤回理由')
            if r.get('withdrawn'):return {'ok':True,'duplicate':True}
            r['withdrawn']=True;r['withdrawal_reason']=reason[:1000];changes=[]
            self.e.evidence.mark_source_withdrawn(rid,reason)
            for k in (*LONG_IDS,*tr.DISPOSITIONS):
                f=t['dispositions'][k] if k in tr.DISPOSITIONS else p['psychology']['features'][k]
                ids=f.get('evidence_ids',[]) or [e['record_id'] for e in f.get('evidence',[])]
                if rid not in ids or f.get('source_type') not in ('promoted_evidence','experience_derived'):continue
                before=copy.deepcopy(f)
                # Do not silently recover an older estimate still based on the
                # invalid source; remove the affected derived prior for review.
                f.update(estimate=None,source_type='unknown',updated_at=now())
                if k in tr.DISPOSITIONS:f.update(uncertainty=None,evidence=[])
                else:f.update(posterior_uncertainty=None,evidence_ids=[],evidence_count=0,conflict=True)
                changes.append({'id':digest([rid,k,'withdraw']),'feature_id':k,'method':'source_withdrawal/1','before':before,'after':copy.deepcopy(f),'source_evidence':[{'record_id':rid,'quote':r['text']}],'at':now()})
            t['version']+=1;p['revision']+=1;p['updated_at']=now()
            for c in changes:c['trait_version']=t['version']
            t['promotion_history'].extend(changes);self.st.setmeta('pmm_profile',p)
            pending=self.st.meta('pmm_training_records') or []
            from .registry import CONTRACT
            affected=[CONTRACT['feature_order'].index(c['feature_id']) for c in changes if c['feature_id'] in CONTRACT['feature_order']]
            def invalid(sample):
                labels=sample.get('labels',{});target=labels.get('psychology_target') or []
                return labels.get('training_context',{}).get('source_record_id')==rid or labels.get('source')=='trait_promotion' and any(i<len(target) and target[i] is not None for i in affected)
            self.st.setmeta('pmm_training_records',[sample for sample in pending if not invalid(sample)])
            self.e.evidence.complete('source_withdrawal',[r],'withdraw:'+rid,{'trait_version':t['version']-1},{'trait_version':t['version'],'changes':changes},'owner-review')
            return {'ok':True,'invalidated':len(changes),'trait_version':t['version'],'neural_unlearning':'未重置既有权重；当前先验停用，待训练标签已移除'}
