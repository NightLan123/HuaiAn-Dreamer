"""Coordinator-owned longitudinal workflow on the SAME evidence/profile store."""
from __future__ import annotations
import copy
import numpy as np
from .common import now
from .registry import digest
from .pmm_contracts import TurnContext,BLOCK_IDS
from .trait_estimator import fit_measurement_scale,LongTermEstimator,covariance,vector
from .pmm_trainer import fit_transition

def empty(subject_id):
    return {'schema':'pmm-estimator-state/2.8','subject_id':subject_id,'revision':0,'protocols':{},'transitions':{},
            'proposals':{},'used_events':{},'posterior':None,'audit':[]}

def validate(state,subject_id):
    if state is None:return
    if not isinstance(state,dict) or state.get('schema')!='pmm-estimator-state/2.8' or state.get('subject_id')!=subject_id or type(state.get('revision')) is not int or state['revision']<0:
        raise ValueError('Longitudinal state identity/revision mismatch')
    for k in ('protocols','transitions','proposals','used_events'):
        if not isinstance(state.get(k),dict) or len(state[k])>10000:raise ValueError('Invalid longitudinal catalog')
    for key,r in state['proposals'].items():
        if r.get('subject_id')!=subject_id or r.get('payload',{}).get('proposal_id')!=key:raise ValueError('Proposal identity mismatch')
        payload=r['payload'];n=len(payload['construct_ids'])
        if any(k not in BLOCK_IDS['H'] for k in payload['construct_ids']):raise ValueError('Unsupported long-term construct')
        vector(payload['posterior']['mu'],n,'proposal mean');covariance(payload['posterior']['P'],n,'proposal covariance')
    if not isinstance(state.get('audit'),list):raise ValueError('Missing longitudinal audit')

def sources(co,row):
    """All annotation bindings reference real existing index entries."""
    bindings=row.get('evidence_bindings') or [row]
    refs=set()
    for binding in bindings:
        if binding.get('subject_id')!=row.get('subject_id'):raise ValueError('Longitudinal evidence subject mismatch')
        co.engine.evidence.validate_supervision_sources(binding);refs.update(binding['evidence_refs'])
    if set(row.get('evidence_refs',[]))!=refs:raise ValueError('Longitudinal evidence bindings incomplete')

def transition_rows(co,rows,protocol):
    """Derive training zeta from observations, never trust a supplied prediction."""
    from .trait_estimator import adjusted_state_summary
    prepared=[]
    for original in rows:
        row=copy.deepcopy(original);sources(co,row)
        bindings={b['event_id']:b for b in row.get('evidence_bindings',[])}
        for event_key,time_key in (('before_event_id','before_time'),('after_event_id','after_time')):
            binding=bindings.get(row[event_key])
            if not binding or binding.get('timestamp')!=row[time_key]:raise ValueError('Longitudinal endpoints do not match original measurement events')
        observed=copy.deepcopy(row.get('state_observations',[]))
        for observation in observed:
            sources(co,observation)
            if observation.get('source_kind') not in ('independent_questionnaire','independent_observer','controlled_fixture'):
                raise ValueError('Predictions cannot supply longitudinal state evidence')
            if not row['before_time']<observation['timestamp']<row['after_time']:
                raise ValueError('State observations must occur between independent trait measurements')
            if observation['event_id'] in (row['before_event_id'],row['after_event_id']):raise ValueError('Longitudinal evidence roles reuse one event')
            coef=np.asarray(protocol['context_coefficients']);x=np.asarray([1.,*observation['context']])
            if x.shape!=(coef.shape[0],):raise ValueError('Context shape mismatch')
            observation.update(context_expected=(x@coef).tolist(),context_covariance=protocol['context_covariance'],protocol_id=protocol['id'])
        diagnostic=protocol.get('engineering_only') or not protocol.get('validated')
        calculation_protocol={**protocol,'validated':True,'independent_context_calibration':True} if diagnostic else protocol
        summary=adjusted_state_summary(observed,subject_id=row['subject_id'],scope=row['scope'],construct_ids=protocol['construct_ids'],protocol=calculation_protocol)
        if not summary['ready']:raise ValueError('Insufficient independent observed states for G training')
        if not set(summary['evidence_refs']).issubset(set(row['evidence_refs'])):raise ValueError('Transition evidence does not include state measurements')
        row['zeta']=summary['zeta'];row['Omega']=summary['Omega'];row['scale_id']=protocol['scale_id']
        row['engineering_fixture']=bool(row.get('engineering_fixture') or diagnostic or any(r.get('engineering_fixture') for r in observed))
        prepared.append(row)
    return prepared

def calibration_live(co,entry,kind):
    if not isinstance(entry,dict) or not isinstance(entry.get('rows'),list) or not entry['rows'] or not isinstance(entry.get('model'),dict):raise ValueError('Calibration lacks original training/validation data')
    rows=entry['rows']
    for row in rows:sources(co,row)
    model=entry['model']
    if kind=='protocol':
        computed=fit_measurement_scale(rows,model['construct_ids'],model['split_plan'],model['scale_id'])
    else:
        state=co.engine.store.meta('pmm28_estimator') or empty(co.engine.profile()['id'])
        protocol=calibration_live(co,state['protocols'][entry['protocol_id']],'protocol')
        computed=fit_transition(transition_rows(co,rows,protocol),model['construct_ids'],model['split_plan'],ridge=model['ridge'])
    if computed!=model or not model.get('validated') or model.get('engineering_only'):raise ValueError('Longitudinal model not independently validated or evidence withdrawn')
    return model

def action(co,body):
    """Called only by PMMCoordinator; original state and events share one transaction."""
    e=co.engine;st=e.store;owner=e.profile()['id']
    if body.get('subject_id')!=owner:raise ValueError('当前主体已变化')
    with e.lock,st.lock,st.db:
        state=st.meta('pmm28_estimator') or empty(owner);validate(state,owner)
        op=body.get('op');proposal_id=body.get('proposal_id')
        if op=='commit' and state['proposals'].get(proposal_id,{}).get('committed'):
            return {'duplicate':True,'proposal_id':proposal_id,'revision':state['revision']}
        if body.get('expected_revision')!=state['revision']:raise ValueError('长期估计目录版本已变化')
        if op=='withdraw_evidence':
            source=e.evidence.state()['sources'].get(body.get('source_key'));reason=str(body.get('reason','')).strip()
            if not source or not reason:raise ValueError('撤回需原始来源和理由')
            e.evidence.mark_source_withdrawn(source['record_id'],reason)
            from .traits import invalidate_pmm28_evidence
            current=e.profile();after,changes=invalidate_pmm28_evidence(current,[source['record_id']],reason)
            st.setmeta('pmm_profile',after)
            for proposal in state['proposals'].values():
                if any(body['source_key'] in r['evidence_refs'] for r in proposal['source_rows']):proposal['source_withdrawn']=True
            st.event('pmm28_source_withdrawal',{'source_key':body['source_key'],'changes':changes,'reason':reason})
            outcome={'withdrawn':True,'invalidated_traits':len(changes),'neural_unlearning':'weights retained; release gate rechecks and blocks invalid evidence'}
        elif op in ('calibrate_scale','train_transition'):
            rows=body.get('rows',[])
            if not 1<=len(rows)<=10000:raise ValueError('标定需有界、独立数据')
            for row in rows:sources(co,row)
            if op=='calibrate_scale':
                model=fit_measurement_scale(rows,body['construct_ids'],body['split_plan'],body['scale_id']);group='protocols'
            else:
                pe=state['protocols'].get(body.get('protocol_id'))
                if not pe or pe['model']['construct_ids']!=body['construct_ids']:raise ValueError('G 训练需要同构念独立测量协议')
                model=fit_transition(transition_rows(co,rows,pe['model']),body['construct_ids'],body['split_plan'],ridge=body.get('ridge',.01));group='transitions'
            state[group][model['id']]={'model':model,'rows':copy.deepcopy(rows),'protocol_id':body.get('protocol_id')};outcome={'model':model}
        elif op=='estimate':
            config=e.config.get()['pmm28']
            if config['mode']=='legacy' or config['long_term_mode']=='disabled':raise ValueError('当前模式禁用新版长期估计')
            pe=state['protocols'].get(body.get('protocol_id'));te=state['transitions'].get(body.get('transition_id'))
            if not pe:raise ValueError('请先标定独立测量协议')
            # Candidate calculations with synthetic protocols remain possible,
            # clearly marked. Only calibration_live qualifies actual commits.
            protocol=copy.deepcopy(pe['model']);transition=copy.deepcopy(te['model']) if te else {}
            for row in pe['rows']:sources(co,row)
            if te:
                for row in te['rows']:sources(co,row)
            prior=copy.deepcopy(body['prior']);samples=copy.deepcopy(body.get('samples',[]));measurement=copy.deepcopy(body.get('measurement'))
            if prior.get('subject_id')!=owner or prior.get('scope')!=body.get('scope'):raise ValueError('Prior identity/scope mismatch')
            sources(co,prior)
            if prior.get('source_kind') not in ('independent_questionnaire','independent_observer','controlled_fixture') or not prior.get('reviewed'):raise ValueError('Independent baseline measurement required')
            for row in samples:
                sources(co,row)
                if row['subject_id']!=owner or row['scope']!=body['scope']:raise ValueError('State observation identity/scope mismatch')
                if row.get('source_kind') not in ('independent_questionnaire','independent_observer','controlled_fixture'):raise ValueError('State supervision must be independent measurement')
                if not prior['timestamp']<row['timestamp'] or measurement and row['timestamp']>=measurement['timestamp']:raise ValueError('State observations must follow baseline and precede post-measurement')
                # Caller cannot manufacture an arbitrary context correction.
                coeff=np.asarray(protocol['context_coefficients']);x=np.asarray([1.,*row['context']])
                if x.shape!=(coeff.shape[0],):raise ValueError('Context encoding mismatch')
                row['context_expected']=(x@coeff).tolist();row['context_covariance']=protocol['context_covariance']
                row['protocol_id']=protocol['id']
            if measurement:sources(co,measurement)
            current=e.profile();context=TurnContext(owner,body['scope'],body.get('event_id') or 'estimate:'+digest(body),now(),current['revision'],
                turn_id=body.get('event_id') or 'offline-estimation',person_id='owner-review',evidence_refs=tuple(prior['evidence_refs']))
            proposal=LongTermEstimator().estimate(context,prior=prior,samples=samples,measurement=measurement,protocol=protocol,transition=transition,construct_ids=protocol['construct_ids'])
            if 'proposal_id' not in proposal['payload']:return proposal
            proposal['protocol_id']=protocol['id'];proposal['transition_id']=transition.get('id')
            proposal['source_rows']=[prior,*samples]+([measurement] if measurement else [])
            proposal['profile_digest']=digest(current);proposal['engineering_only']=any(r.get('engineering_fixture',False) for r in proposal['source_rows']) or protocol.get('engineering_only',True)
            proposal_id=proposal['payload']['proposal_id'];state['proposals'].setdefault(proposal_id,proposal);outcome={'proposal':proposal}
        elif op=='commit':
            config=e.config.get()['pmm28'];proposal=state['proposals'].get(proposal_id)
            if config['mode']!='active' or config['long_term_mode']!='validated_commit':raise ValueError('仅 active + validated_commit 允许正式提交')
            if not proposal or proposal.get('engineering_only') or proposal.get('source_withdrawn'):raise ValueError('缺少正式合格提案；工程数据或撤回证据不能提交人格')
            protocol=calibration_live(co,state['protocols'][proposal['protocol_id']],'protocol')
            transition=calibration_live(co,state['transitions'][proposal['transition_id']],'transition')
            if not proposal['payload']['G_validated'] or not proposal['payload']['state_summary'].get('ready') or not proposal['payload']['posterior'].get('updated'):
                raise ValueError('缺少独立纵向状态、已验证 G 或独立后测校准')
            for row in proposal['source_rows']:sources(co,row)
            current=e.profile()
            if current['revision']!=proposal['prior_revision'] or digest(current)!=proposal['profile_digest']:raise ValueError('人格 CAS 已变化，必须重新估计')
            ids=proposal['payload']['state_summary']['event_ids']+[proposal['payload']['measurement']['event_id']]
            keys=[digest([owner,proposal['scope'],eid]) for eid in ids]
            if any(k in state['used_events'] for k in keys):raise ValueError('同一独立事件已贡献过稳定人格变化')
            from .traits import apply_pmm28_proposal
            refs=sorted({r for row in proposal['source_rows'] for r in row['evidence_refs']})
            raw=[e.evidence.state()['sources'][k] for k in refs]
            after=apply_pmm28_proposal(current,proposal,protocol,raw)
            st.setmeta('pmm_profile',after)
            proposal['committed']=True;proposal['committed_revision']=after['revision']
            state['posterior']={'proposal_id':proposal_id,'profile_revision':after['revision'],'posterior':proposal['payload']['posterior'],'scale_id':protocol['scale_id']}
            for k in keys:state['used_events'][k]=proposal_id
            st.event('pmm28_trait_revision',{'proposal_id':proposal_id,'source_keys':refs,'before':current,'after':after,'transition_id':transition['id'],'protocol_id':protocol['id']})
            outcome={'committed':True,'proposal_id':proposal_id,'trait_version':after['trait_profile']['version']}
        else:raise ValueError('未知长期估计操作')
        state['revision']+=1;state['audit'].append({'op':op,'at':now(),'revision':state['revision'],'proposal_id':proposal_id})
        validate(state,owner);st.setmeta('pmm28_estimator',state);st.event('pmm28_estimator_revision',state['audit'][-1])
        return {**outcome,'revision':state['revision']}
