"""Versioned PMM collaboration; never generates or sends a second message.

General LLM is external. Ports return drafts; only the coordinator's commit
adapter may publish new state, inside Engine's existing transaction discipline.
"""
from __future__ import annotations
import copy, json, time
from .registry import digest
from .pmm_contracts import (TurnContext, ComponentResult, ReasonerAssessment,
    TraitInference, EmotionSnapshot, RelationshipSnapshot, ExpressiveDriveSnapshot,
    PMMDecision, result, construct_blocks, BLOCK_CONTRACT)
from . import affect as af, traits as tr, relationships as dy
from .api_pmm import APIPMM
from .registry_pmm import RegistryPMM
from .psychology import ACTIONS

def appraisal_use(node):
    """Describe the adopted A result independently of the last model attempt."""
    payload = node.get('payload') if isinstance(node.get('payload'),dict) else {}
    packet = payload.get('appraisal_packet') if isinstance(payload.get('appraisal_packet'),dict) else {}
    mask = packet.get('mask')
    known = sum(v is True for v in mask.values()) if isinstance(mask, dict) else None
    failed = payload.get('reappraisal_failure') or payload.get('error') or {}
    if not isinstance(failed,dict): failed = {}
    if node.get('status') == 'failed':
        source, attempt = 'local_fallback', 'failed_before_request' if payload.get('request_count')==0 else 'failed'
    elif node.get('executed') is False or node.get('status') == 'disabled':
        source, attempt = 'local_only', 'skipped'
    elif payload.get('reappraisal_failure'):
        source = ('retained_previous_valid_evidence' if known else 'no_grounded_appraisal') if known is not None else 'unrecorded'
        attempt = 'failed'
    elif node.get('status') == 'ok':
        source = ('current_evidence' if known else 'no_grounded_appraisal') if known is not None else 'unrecorded'
        attempt = 'succeeded'
    else:
        source, attempt = 'unrecorded', 'unrecorded'
    return {'source': source, 'last_attempt': attempt, 'known_dimensions': known,'request_count':payload.get('request_count'),
            'dimension_count': len(mask) if isinstance(mask, dict) else None,
            'failure_code': failed.get('failure_code') or failed.get('error_type'),
            'failure_category': failed.get('failure_category'),
            'contract_issues': copy.deepcopy(failed.get('contract_issues', []))}

def evaluation_history(run,trace=None):
    trace=trace or (run.get('cognitive_snapshot') or {}).get('pmm28') or {}
    nodes=trace.get('components') or {}
    reasoner=nodes.get('reasoner')
    evaluation=run.get('reasoner_evaluation')
    if evaluation is None and trace.get('mode')=='full' and isinstance(reasoner,dict):
        evaluation=appraisal_use(reasoner)
    negotiation=run.get('negotiation_result')
    if negotiation is None and isinstance(nodes.get('negotiation'),dict):
        node=nodes['negotiation']
        negotiation={k:node[k] for k in ('executed','status','reason','elapsed_ms','attempts','policy','trigger_reason',
                     'failure_code','failure_category','contract_path','contract_reason','contract_issues') if k in node}
    return {'reasoner_evaluation':evaluation,'negotiation_result':negotiation}

class ExistingMemoryEvidence:
    version = 'existing-scoped-memory/2.8'
    def retrieve(self, ctx, *, memories):
        # This is the result of Engine.retrieve, including its permission filtering.
        # Assert scope again; do not perform a global second lookup.
        rows = copy.deepcopy(memories)
        for r in rows:
            if r.get('scope') not in (ctx.scope, 'self'):
                raise ValueError('Memory scope mismatch')
        return result(ComponentResult, ctx, self.version,
                      {'records': rows, 'source_digest': digest(rows), 'count': len(rows)},
                      execution='same_turn_scoped_retrieval', observed=True)

class InternalAPIReasoner:
    version = 'api-reasoner-adapter/2.8'
    def __init__(self, engine): self.engine = engine
    def analyze(self, ctx, *, cached, profile, understanding, activity, relation, memories):
        config = self.engine.config.get(); start = time.monotonic()
        connection = config['pmm']['api']
        model = {k: connection.get(k) for k in ('model', 'provider', 'base_url')}
        try:
            if cached is not None:
                decoded = copy.deepcopy(cached)
                execution = 'same_turn_legacy_prepare_cache'; calls = 0
            else:
                c = copy.deepcopy(config)
                c['pmm']['api']['timeout'] = min(c['pmm']['api']['timeout'], c['pmm28']['reasoner_timeout'])
                c['pmm']['api']['json_repair'] = False  # bounded one-call shadow budget
                port = APIPMM(c, self.engine.pmm_provider_factory)
                from .api_pmm import BudgetedProvider
                port.provider=BudgetedProvider(port.provider,c['pmm28']['reasoner_timeout'])
                decoded, _ = port.prepare(ctx.text, understanding, profile, activity, relation, memories)
                execution = 'independent_api_request'; calls = len(getattr(port.provider, 'calls', []))
            quote = decoded.get('appraisal_evidence')
            if not isinstance(quote, str) or not quote.strip() or quote not in ctx.text:
                raise ValueError('No grounded current-event appraisal')
            payload = {'appraisal': decoded.get('legacy_state_prediction', decoded['state']),
                       'action_probabilities': decoded['action_probabilities'],
                       'layered_affect': decoded.get('layered_affect'),
                       'evidence_quote': quote, 'hypothesis': decoded.get('language_condition', ''),
                       'uncertainty': {'calibrated': False, 'estimate': None},
                       'cache_key': digest([ctx.json(), model, understanding, memories]),
                       'provider': model, 'additional_requests': calls}
            return result(ReasonerAssessment, ctx, self.version, payload,
                          execution=execution, kind='model_inference_not_fact',
                          elapsed_ms=round((time.monotonic()-start)*1000, 3))
        except Exception as exc:
            # Exception messages can contain URLs/keys; store only class and safe code.
            return result(ReasonerAssessment, ctx, self.version,
                          {'error_type': type(exc).__name__, 'reason': 'internal_api_unavailable_or_invalid'},
                          status='failed', executed=True, execution='attempted_request_or_validation')

class LegacyNumericBridge:
    version = 'registry-370-shadow-bridge/2.8'
    def __init__(self, engine): self.engine = engine
    def predict(self, ctx, *, vector, blocks, **inputs):
        model = RegistryPMM(self.engine.model.export(), ctx.subject_id)
        decoded = model.decode(vector, [])
        return result(TraitInference, ctx, self.version,
                      {'action_probabilities': decoded['action_probabilities'], 'state_prediction': decoded['state'],
                       'latent': decoded['latent'], 'blocks': blocks, 'checkpoint_sha256': digest(model.export()),
                       'calibration': 'uncalibrated', 'formal_eligible': False}, status='uncalibrated',
                      execution='actual_numpy_forward', kind='prediction_not_observation')

class ExistingAffect:
    version = 'existing-affect-adapter/2.8'
    def advance(self, ctx, *, base, profile, understanding, event, relation, memories, reasoner):
        proposal = reasoner['payload'].get('layered_affect') if reasoner['status'] == 'ok' else None
        state, trace = af.evaluate(copy.deepcopy(base), tr.snapshot(profile), understanding,
                                   event, relation, memories, proposal, at=ctx.timestamp)
        return result(EmotionSnapshot, ctx, self.version, {'state': state, 'trace': trace},
                      execution='existing_affect_evaluate', kind='draft_not_commit')

class ExistingRelationship:
    version = 'existing-dyad-adapter/2.8'
    def evaluate(self, ctx, *, profile, understanding, relation):
        d = relation['dyad']
        if d['other_id'] != ctx.person_id or d['context_id'] != ctx.scope:
            raise ValueError('Relationship identity/scope mismatch')
        appraisal = dy.cognition(tr.snapshot(profile), understanding, relation)
        return result(RelationshipSnapshot, ctx, self.version,
                      {'self_id': ctx.subject_id, 'other_id': ctx.person_id, 'scope': ctx.scope,
                       'dyad': copy.deepcopy(d), 'appraisal': appraisal,
                       'model_of_other': 'separate_existing_interlocutor_profile'},
                      execution='existing_relationship_cognition', kind='inference_not_fact')

class ExpressiveDriveAdapter:
    version = 'expressive-drive/2.8.3'
    def __init__(self, engine): self.engine = engine
    def evaluate(self, ctx, *, profile, understanding, event, affect, relationship, reasoner, neural, session_id=None, environment=None):
        from . import expression_drive as ed
        base = self.engine.store.meta(ed.KEY)
        if base is None:
            base = ed.migrate(self.engine.store)
        expected_rev = base['revision']
        packet = reasoner['payload'].get('appraisal_packet') if reasoner.get('status') == 'ok' else None
        # If Cognition.assess already evaluated a prospective draft for the exact same source_event_ids,
        # revise that draft in-place with full PMM understanding & reasoner_packet rather than double-jumping.
        src_ids = [str(x).strip() for x in (event.get('source_event_ids') or []) if str(x).strip()]
        skey = ed.stream_key(profile['id'], event.get('scope', ctx.scope), event.get('person', ctx.person_id))
        stream_row = (base.get('streams') or {}).get(skey) or {}
        eval_map = stream_row.get('evaluated_source_ids') or {}
        prospective_already_ran = bool(src_ids) and all(sid in eval_map for sid in src_ids) and (
            not (environment or {}).get('is_duplicate_turn_replay')
        )
        draft_state, res = ed.evaluate_event(
            base, profile, {**event, 'session_id': session_id or event.get('session_id', ctx.scope)},
            ctx.timestamp, understanding=understanding, affect_view=affect['payload'],
            relation=relationship['payload']['dyad'], reasoner_packet=packet,
            neural_payload=neural.get('payload'), environment=environment,
            revise_draft=prospective_already_ran
        )
        snap = result(ExpressiveDriveSnapshot, ctx, self.version, res,
                      execution='personality_emotion_appraisal_drive_dynamics', kind='transaction_draft')
        return draft_state, expected_rev, snap

class CoordinatedDecision:
    version = 'calibration-first-arbitration/2.8'
    def decide(self, ctx, *, reasoner, neural, mode, expressive_drive=None):
        api = reasoner['payload'].get('action_probabilities', {})
        net = neural['payload'].get('action_probabilities', {})
        a = max(api, key=api.get) if api else None
        n = max(net, key=net.get) if net else None
        terms={k:0. for k in ACTIONS};reason='legacy_official_shadow_only' if mode=='shadow' else 'uncalibrated_legacy_fallback'
        eligible=neural['payload'].get('formal_eligible') is True
        coverage=sum(sum(v['mask']) for v in neural['payload'].get('blocks',{}).values())
        if mode=='active' and eligible:
            if not coverage:reason='unknown_trait_context_legacy_fallback'
            elif reasoner['status']!='ok':reason='missing_reasoner_legacy_fallback'
            elif a!=n:
                # Neither model has authority to declare the other's inference a
                # fact. Ask for missing context through the existing policy gates.
                reason='grounded_api_neural_disagreement_request_clarification';terms['clarify']=.08
            elif max(net.values(),default=0)<.5:reason='low_predictive_separation_legacy_fallback'
            else:
                reason='validated_neural_condition_with_grounded_api_agreement'
                terms={k:.2*(net.get(k,0)-1/len(ACTIONS)) for k in ACTIONS}
        ed_summary = None
        if isinstance(expressive_drive, dict) and isinstance(expressive_drive.get('payload'), dict):
            edp = expressive_drive['payload']
            ed_summary = {
                'activation': edp.get('activation'),
                'urgency': edp.get('urgency'),
                'persistence': edp.get('persistence'),
                'expressive_intent': edp.get('expressive_intent'),
                'policy_score_terms': copy.deepcopy(edp.get('policy_score_terms', {})),
                'active_motive_id': edp.get('active_motive_id'),
                'status': edp.get('status'),
            }
        return result(PMMDecision, ctx, self.version,
                      {'api_preference': a, 'neural_preference': n, 'disagreement': bool(a and n and a != n),
                       'arbitration': reason,'known_constructs':coverage,
                       'score_terms': terms, 'formal_contribution': any(abs(v)>0 for v in terms.values()),
                       'api_evidence':reasoner['payload'].get('evidence_quote'),
                       'neural_release_gate':neural['payload'].get('release_gate'),
                       'expressive_drive_summary': ed_summary,
                       'uncertainty':{'api':'uncalibrated_hypothesis','neural':neural['payload'].get('calibration')},
                       'rule': 'check_source_then_calibration_then_conflict; never_average_predictions'})

class PMMCoordinator:
    version = 'pmm-coordinator/2.8'
    def __init__(self, engine):
        self.engine = engine
        self.memory = ExistingMemoryEvidence(); self.reasoner = InternalAPIReasoner(engine)
        from .trait_dynamics import NeuralDynamicsPort
        self.neural = NeuralDynamicsPort(engine); self.affect = ExistingAffect()
        self.relationship = ExistingRelationship()
        self.expressive_drive = ExpressiveDriveAdapter(engine)
        self.decision = CoordinatedDecision()
        from .trait_estimator import LongTermEstimator
        from .pmm_trainer import Learning
        self.estimator=LongTermEstimator();self.learning=Learning(engine)

    def run_full(self, *, turn_id,event,at,profile,understanding,relation,memories,affect_base,decoded,environment=None):
        """Single official 2.8.1+ path. No Legacy forward is run for comparison."""
        from . import affect_runtime as ar
        from .affect_response import appraisal_packet,label_readout
        started=time.monotonic();ctx=TurnContext(subject_id=profile['id'],scope=event['scope'],event_id=event['id'],timestamp=at,
            prior_revision=profile['revision'],turn_id=turn_id,person_id=event['person'],text=event['text'],evidence_refs=tuple(event.get('source_event_ids',[])))
        timings={};components={}
        def call(name,fn):
            start=time.monotonic();value=fn();timings[name]=round((time.monotonic()-start)*1000,3);return value
        memory=call('memory',lambda:self.memory.retrieve(ctx,memories=memories));components['memory']=memory
        failed=decoded.get('pmm28_api_failure');packet=appraisal_packet(decoded.get('appraisal_checks',{}) if not failed else {},event,ctx.evidence_refs or [ctx.event_id],decoded.get('appraisal_evidence') if not failed else None)
        if decoded.get('reappraisal_checks') is not None:
            packet['reappraisal_candidate']={'event_facts_sha256':digest(packet['event_facts']),'checks':decoded['reappraisal_checks']}
        reasoner=result(ReasonerAssessment,ctx,'event-reasoner-A/2.8.1',{'appraisal':copy.deepcopy(decoded['state']),
            'action_probabilities':decoded['action_probabilities'],'evidence_quote':decoded.get('appraisal_evidence'),'appraisal_packet':packet,
            'facts':decoded.get('facts',[]),'uncertainties':decoded.get('uncertainties',[]),'error':failed,
            'request_count':decoded.get('reasoner_request_count'),
            'evaluation_evidence':copy.deepcopy(decoded.get('evaluation_evidence')),
            'reappraisal_failure':copy.deepcopy(decoded.get('reappraisal_failure')),
            'optional_field_warnings':copy.deepcopy(decoded.get('optional_field_warnings',[]))},
            status='failed' if failed else 'ok',execution='same_turn_A_request',kind='appraisal_hypothesis_not_fact')
        components['reasoner']=reasoner
        if decoded.get('a_skipped_reason'):
            reasoner.update(status='disabled',executed=False,reason=decoded['a_skipped_reason'],execution='local_only_no_A_request')
        elif failed and decoded.get('reasoner_request_count')==0:
            reasoner.update(executed=False,execution='failed_before_request')
        usage = appraisal_use(reasoner)
        reasoner['payload'].update(evaluation_status=usage['source'], evaluation_use=usage)
        def emotion():
            model=ar.model_for(self.engine.store);base=self.engine.store.meta(ar.KEY)
            state,res=ar.draft(base,model,profile,event,at,packet,relation,
                {'relevance':packet['checks'].get('affect.appraisal.goal_relevance') or 0.,'urgency':packet['checks'].get('affect.appraisal.urgency') or 0.})
            view,trace=ar.legacy_view(affect_base,res,profile)
            return model,state,res,view,trace
        model,emotion_draft,emotion_result,view,layer=call('affect',emotion)
        affect=result(EmotionSnapshot,ctx,'affect-state/2.8.1',{'state':view,'trace':layer,'dynamics_v2':emotion_result},
            execution='real_time_OU_then_single_event_jump',kind='transaction_draft');components['affect']=affect
        relationship=call('relationship',lambda:self.relationship.evaluate(ctx,profile=profile,understanding=understanding,relation=relation));components['relationship']=relationship
        neural=call('neural',lambda:self.neural.predict(ctx,blocks=construct_blocks(profile),reasoner=reasoner,affect=affect,relationship=relationship,memory=memory,understanding=understanding,session_id=event.get('session_id')));components['neural']=neural
        # E-F reads this turn's h after P-A/B. This is a head readout only: no
        # repeated OU sampling, regulation choice or event jump.
        labels=call('labels',lambda:label_readout(model,emotion_result['fast_state_latent'],emotion_result['appraisal'],neural['payload']['latent']))
        emotion_result.update(labels);emotion_result['label_h_t']=neural['payload']['latent']
        row=emotion_draft['streams'][ar.stream_key(profile['id'],event)];row['events'][event['id']]['result']=copy.deepcopy(emotion_result)
        view['emotion']['categorical_activations']=copy.deepcopy(labels['emotion_labels']);layer['emotion_state']=copy.deepcopy(view['emotion'])
        view['trajectory'][-1]['emotion']=copy.deepcopy(view['emotion'])
        layer['dynamics_v2']=copy.deepcopy(emotion_result)
        affect['payload'].update(state=view,trace=layer,dynamics_v2=emotion_result)
        drive_draft,expected_drive_rev,exp_drive=call('expressive_drive',lambda:self.expressive_drive.evaluate(
            ctx,profile=profile,understanding=understanding,event=event,affect=affect,relationship=relationship,
            reasoner=reasoner,neural=neural,session_id=event.get('session_id'),environment=environment))
        components['expressive_drive']=exp_drive
        decision=call('decision',lambda:self.decision.decide(ctx,reasoner=reasoner,neural=neural,mode='active',expressive_drive=exp_drive))
        if decision['payload']['arbitration'].endswith('legacy_fallback'):decision['payload']['arbitration']='no_neural_probability_bonus:'+decision['payload']['arbitration'].removesuffix('_legacy_fallback')
        components['decision']=decision
        for name,node in components.items():
            node['elapsed_ms']=timings.get(name,decoded.get('reasoner_elapsed_ms',0.));node['applied_to']={'memory':['A','neural','B','expression'],'reasoner':['appraisal','expressive_drive','decision'],
                'affect':['neural','expressive_drive','B','expression'],'relationship':['neural','expressive_drive','B','decision'],'neural':['expressive_drive','decision'] if node.get('payload',{}).get('formal_eligible') else ['expressive_drive','candidate_diagnostics','labels'],
                'expressive_drive':['decision','B','policy','expression'],
                'decision':['policy']}[name]
        if usage['source'] in ('local_only', 'local_fallback'):
            reasoner['applied_to'] = []
        from .pmm_contracts import TraitUpdateProposal
        longterm=self.estimator.estimate(ctx) if self.engine.config.get()['pmm28']['long_term_mode']!='disabled' else result(TraitUpdateProposal,ctx,self.estimator.version,{'reason':'disabled'},status='disabled',executed=False)
        longterm['payload']['stable_trait_version_read']=profile['trait_profile']['version']
        longterm['payload']['purpose']='independent_measurement_estimator_not_experience_scheduler'
        learning=getattr(getattr(self.engine,'learning',None),'experiences',None)
        if learning:
            state=learning.state();job=state.get('job') or {}
            longterm['payload']['experience_learning']={'scheduler':'after_committed_memory_threshold',
                'last_job_id':job.get('id'),'status':job.get('status','waiting'),
                'consumed_events':len(state['consumed']),'trait_version':profile['trait_profile']['version']}
        return {**ctx.json(),'version':'pmm-coordinator/2.8.1','mode':'full','session_id':event.get('session_id'),
            'components':components,'long_term':longterm,'elapsed_ms':round((time.monotonic()-started)*1000,3),'external_sends':0,'formal_state_writes':0,
            'execution_order':['memory','reasoner','affect','relationship','neural','labels','expressive_drive','decision'],
            'dependencies':[['memory','reasoner'],['reasoner','affect'],['affect','neural'],['relationship','neural'],['memory','neural'],['affect','expressive_drive'],['neural','expressive_drive'],['relationship','expressive_drive'],['reasoner','expressive_drive'],['expressive_drive','decision'],['neural','decision']],
            '_emotion_draft':emotion_draft,'_expected_emotion_revision':self.engine.store.meta(ar.KEY)['revision'],
            '_drive_draft':drive_draft,'_expected_drive_revision':expected_drive_rev}

    def run(self, *, turn_id, event, at, profile, understanding, relation, memories,
            affect_base, activity, vector, legacy_decoded, mode, environment=None):
        ctx = TurnContext(subject_id=profile['id'], scope=event['scope'], event_id=event['id'],
                          turn_id=turn_id, person_id=event['person'], text=event['text'], timestamp=at,
                          prior_revision=profile['revision'], evidence_refs=tuple(event.get('source_event_ids', [])))
        started = time.monotonic(); blocks = construct_blocks(profile)
        memory = self.memory.retrieve(ctx, memories=memories)
        from .psychology import context_profile
        if legacy_decoded.get('pmm28_api_failure'):
            reasoner=result(ReasonerAssessment,ctx,self.reasoner.version,legacy_decoded['pmm28_api_failure'],status='failed',
                            executed=True,execution='legacy_prepare_attempt_failed_no_second_retry')
        else:
            reasoner = self.reasoner.analyze(ctx, cached=legacy_decoded if legacy_decoded.get('mode') == 'api' else None,
                profile=context_profile(profile,ctx.scope), understanding=understanding, activity=activity, relation=relation, memories=memory['payload']['records'])
        affect = self.affect.advance(ctx, base=affect_base, profile=profile, understanding=understanding,
            event=event, relation=relation, memories=memory['payload']['records'], reasoner=reasoner)
        relationship = self.relationship.evaluate(ctx, profile=profile, understanding=understanding, relation=relation)
        neural = self.neural.predict(ctx, vector=vector, blocks=blocks, reasoner=reasoner, affect=affect,
            relationship=relationship, memory=memory, understanding=understanding)
        _, _, exp_drive = self.expressive_drive.evaluate(
            ctx, profile=profile, understanding=understanding, event=event,
            affect=affect, relationship=relationship, reasoner=reasoner, neural=neural,
            session_id=event.get('session_id'), environment=environment
        )
        decision = self.decision.decide(ctx, reasoner=reasoner, neural=neural, mode=mode, expressive_drive=exp_drive)
        if self.engine.config.get()['pmm28']['long_term_mode']=='disabled':
            from .pmm_contracts import TraitUpdateProposal
            long_term=result(TraitUpdateProposal,ctx,self.estimator.version,{'reason':'long_term_estimation_disabled'},status='disabled',executed=False)
        else:long_term=self.estimator.estimate(ctx)
        stored=self.engine.store.meta('pmm28_estimator') or {}
        long_term['payload']['stored_estimator_revision']=stored.get('revision',0)
        long_term['payload']['committed_proposal_id']=(stored.get('posterior') or {}).get('proposal_id')
        long_term['payload']['stable_trait_version_read']=profile['trait_profile']['version']
        return {**ctx.json(), 'version': self.version, 'mode': mode, 'construct_contract': BLOCK_CONTRACT,
                'components': {'memory': memory, 'reasoner': reasoner, 'affect': affect, 'relationship': relationship,
                               'neural': neural, 'expressive_drive': exp_drive, 'decision': decision},
                'long_term': long_term,
                'elapsed_ms': round((time.monotonic()-started)*1000, 3), 'external_sends': 0, 'formal_state_writes': 0}

    def status(self):
        from .pmm_trainer import empty_catalog, validate_catalog, published_gate
        cfg = self.engine.config.get()['pmm28']
        catalog=self.engine.store.meta('pmm28_models') or empty_catalog(self.engine.profile()['id'])
        validate_catalog(catalog,self.engine.profile()['id'])
        samples=self.engine.store.meta('pmm28_samples') or {'revision':0,'rows':{}}
        ready,reason=published_gate(self.engine,catalog)
        return {'version': self.version, 'config': cfg, 'construct_contract': BLOCK_CONTRACT,
                'calibration': 'held_out_behavior_validated' if ready else 'uncalibrated', 'release_gate':reason,'long_term_commit_ready': False,
                'models':{'revision':catalog['revision'],'published':catalog['published'],
                          'versions':[{'sha256':key,'steps':v['steps'],'revision':v['revision'],
                                       'frozen':key in catalog['frozen'],'revoked':key in catalog['revoked'],
                                       'engineering_only':(v.get('training') or {}).get('engineering_only',True),
                                       'report':catalog['reports'].get(key)} for key,v in catalog['versions'].items()]},
                'samples':{'revision':samples['revision'],'count':len(samples['rows']),'recent':[{k:r.get(k) for k in ('key','subject_id','scope','event_id','task','timestamp','withdrawn','engineering_fixture')} for r in list(samples['rows'].values())[-50:]]},
                'legacy_checkpoint_sha256': digest(self.engine.model.export())}

    def longitudinal_action(self,body):
        from .pmm_longitudinal import action
        return action(self,body)

    def record_commit(self,trace,*,partial=False,receipts=()):
        """Attach the existing ACK/transaction receipt; never emit another send."""
        if not trace:return
        st=self.engine.store;profile=self.engine.profile();affect=st.meta('pmm_affect') or {}
        from . import expression_drive as ed
        drive_meta=st.meta(ed.KEY) or {}
        trace['commit_receipt']={'kind':'qq_acknowledged_prefix' if partial else 'qq_acknowledged' if receipts else 'local_transaction',
            'acknowledged_messages':[r.get('message_id') for r in receipts if r.get('message_id') is not None],
            'profile_revision':profile['revision'],'trait_version':profile['trait_profile']['version'],
            'affect_revision':affect.get('emotion',{}).get('state_revision'),
            'expressive_drive_revision':drive_meta.get('revision'),
            'stable_trait_updates':0,'partial':partial}
        trace['formal_state_writes']=int(trace.get('mode')=='full' and 'affect' in trace.get('components',{}) or trace.get('mode')=='active' and trace.get('components',{}).get('reasoner',{}).get('status')=='ok')
        trace['formal_state_write_meaning']='emotion_mood_and_expressive_drive_draft_committed_via_original_transaction; not_a_stable_trait_write'

    def review_samples(self,body):
        """Owner-reviewed external annotations join the existing source index."""
        from .pmm_trainer import audit_dataset, sample_key
        st=self.engine.store;owner=self.engine.profile()['id']
        if body.get('subject_id')!=owner:raise ValueError('当前主体已变化')
        with self.engine.lock,st.lock,st.db:
            state=st.meta('pmm28_samples') or {'schema':'pmm-dataset/2.8','subject_id':owner,'revision':0,'rows':{}}
            if body.get('expected_revision')!=state['revision']:raise ValueError('数据集版本已变化')
            if body.get('op')=='withdraw':
                key=body.get('key');row=state['rows'].get(key)
                if not row or not str(body.get('reason','')).strip():raise ValueError('撤回需样本及理由')
                if row.get('withdrawn'):return {'duplicate':True,'revision':state['revision']}
                # Withdraw all aliases of this event, rather than allowing another
                # task label to keep the same invalid source alive.
                for sample in state['rows'].values():
                    if sample['event_id']==row['event_id'] and sample['scope']==row['scope']:
                        sample.update(withdrawn=True,withdrawal_reason=str(body['reason'])[:1000])
                for ref in row['evidence_refs']:
                    source=self.engine.evidence.state()['sources'][ref]
                    self.engine.evidence.mark_source_withdrawn(source['record_id'],body['reason'])
                from .traits import invalidate_pmm28_evidence
                records=[self.engine.evidence.state()['sources'][ref]['record_id'] for ref in row['evidence_refs']]
                profile,changes=invalidate_pmm28_evidence(self.engine.profile(),records,body['reason']);st.setmeta('pmm_profile',profile)
                report={'withdrawn':key,'invalidated_traits':len(changes)}
            else:
                incoming=body.get('samples')
                if not isinstance(incoming,list) or not 1<=len(incoming)<=1000:raise ValueError('每批应为 1–1000 条审核标签')
                normalized=[]
                for item in incoming:
                    row=copy.deepcopy(item);record=row.pop('record',None);quote=row.pop('quote',None)
                    if record is not None:
                        if record.get('source') not in ('human','observed','imported') or record.get('scope')!=row.get('scope') or record.get('measurement_subject_id')!=row.get('subject_id') or record.get('timestamp')!=row.get('timestamp'):
                            raise ValueError('原文主体、时间或作用范围与标签不一致')
                        registered=self.engine.evidence.register([record],'pmm28-reviewed-measurement')[0]
                        row.update(event_id=registered['origin_event_id'],evidence_refs=[registered['origin_record_key']],quotes={registered['origin_record_key']:quote})
                    normalized.append(row)
                audited,report=audit_dataset(normalized,owner,self.learning.source_resolver)
                added=0
                for row in audited:
                    key=sample_key(row);old=state['rows'].get(key)
                    if old and digest(old)!=digest(row):raise ValueError('同一事件标签已存在；需撤回并明确修订来源，不能覆盖')
                    if not old:state['rows'][key]=row;added+=1
                report['added']=added
            state['revision']+=1;st.setmeta('pmm28_samples',state)
            st.event('pmm28_dataset_review',{'subject_id':owner,'revision':state['revision'],'report':report})
            return {'revision':state['revision'],'report':report}

    def model_action(self,body):
        """Only this scheduler publishes candidates; no old weights are replaced."""
        from .pmm_trainer import empty_catalog,validate_catalog,publication_eligibility
        from .trait_dynamics import initial_checkpoint
        st=self.engine.store;owner=self.engine.profile()['id'];op=body.get('op')
        if body.get('subject_id')!=owner:raise ValueError('当前主体已变化')
        with self.engine.lock:
            catalog=st.meta('pmm28_models') or empty_catalog(owner);validate_catalog(catalog,owner)
            if op=='train' and body.get('job_id') in catalog['jobs']:
                return {'duplicate':True,'job':catalog['jobs'][body['job_id']],'revision':catalog['revision']}
            if body.get('expected_revision')!=catalog['revision']:raise ValueError('模型目录版本已变化')
            before=catalog['revision'];key=body.get('version')
            if op=='bind_scale':
                from .pmm_longitudinal import calibration_live
                from .trait_dynamics import bind_measurement_scale
                entry=(st.meta('pmm28_estimator') or {}).get('protocols',{}).get(body.get('protocol_id'))
                protocol=calibration_live(self,entry,'protocol')
                parent=catalog['versions'].get(key) if key else initial_checkpoint(owner)
                if parent is None or key in catalog['revoked']:raise ValueError('标定父版本不存在或已撤销')
                candidate=bind_measurement_scale(parent,protocol);key=candidate['sha256']
                catalog['versions'].setdefault(parent['sha256'],parent);catalog['versions'][key]=candidate
                outcome={'candidate':key,'calibrated_facets':candidate['scale']['construct_ids'],'published_unchanged':catalog['published']}
            elif op=='train':
                if not isinstance(body.get('job_id'),str) or not body['job_id']:raise ValueError('训练必须有幂等任务 ID')
                parent=catalog['versions'].get(key) if key else initial_checkpoint(owner)
                if parent is None or key in catalog['revoked']:raise ValueError('训练父版本不存在或已撤销')
                samples=st.meta('pmm28_samples') or {'rows':{}}
                keys=body.get('sample_keys') if body.get('sample_keys') is not None else [k for k,r in samples['rows'].items() if not r.get('withdrawn')]
                if any(k not in samples['rows'] for k in keys):raise ValueError('训练样本已变化')
                rows=[samples['rows'][k] for k in keys]
                candidate,report,audited=self.learning.train(checkpoint=parent,rows=rows,plan=body['split_plan'],
                    target=body.get('target','core'),epochs=body.get('epochs',20),learning_rate=body.get('learning_rate',.01),
                    structural_candidates=tuple(body.get('structural_candidates',[0.,.0001])))
                # Re-check source liveness after expensive work, before storing.
                for row in audited:self.learning.source_resolver(row)
                key=candidate['sha256'];catalog['versions'].setdefault(parent['sha256'],parent)
                catalog['versions'][key]=candidate;catalog['reports'][key]=report;catalog['datasets'][key]=audited
                catalog['jobs'][body['job_id']]={'version':key,'dataset_sha256':report['dataset']['dataset_sha256']}
                outcome={'candidate':key,'report':report,'published_unchanged':catalog['published']}
            else:
                if key not in catalog['versions']:raise ValueError('模型版本不存在')
                if op=='freeze':
                    if key not in catalog['frozen']:catalog['frozen'].append(key)
                elif op in ('publish','rollback'):
                    if key not in catalog['frozen'] or key in catalog['revoked']:raise ValueError('发布须为已冻结且未撤销的候选')
                    if op=='rollback' and not any(a.get('version')==key and a['op']=='publish' for a in catalog['audit']):raise ValueError('只能回滚到曾发布版本')
                    ready,reason=publication_eligibility(catalog['versions'][key],catalog['reports'].get(key),catalog['datasets'].get(key,[]),owner,self.learning.source_resolver)
                    if not ready:raise ValueError('模型未通过发布门禁：'+reason)
                    catalog['published']=key
                    from .pmm_trainer import published_gate
                    ready,reason=published_gate(self.engine,catalog)
                    if not ready:raise ValueError('模型父版本验证失败：'+reason)
                elif op=='revoke':
                    if key not in catalog['revoked']:catalog['revoked'].append(key)
                    if catalog['published']==key:catalog['published']=None
                else:raise ValueError('未知模型操作')
                outcome={'version':key,'op':op,'published':catalog['published']}
            from .common import now
            catalog['revision']+=1;catalog['audit'].append({'op':op,'version':key,'at':now(),'previous_revision':before,'revision':catalog['revision']})
            validate_catalog(catalog,owner)
            with st.lock,st.db:
                current=st.meta('pmm28_models') or empty_catalog(owner)
                if current['revision']!=before:raise ValueError('模型目录 CAS 冲突，候选未提交')
                st.setmeta('pmm28_models',catalog);st.event('pmm28_model_revision',catalog['audit'][-1])
            return {**outcome,'revision':catalog['revision']}

    def traces(self, limit=20, scope=None):
        limit = max(1, min(100, int(limit)))
        rows = self.engine.store.rows("SELECT payload FROM events WHERE kind IN ('turn','expression_partial') ORDER BY rowid DESC LIMIT ?", (limit*4,))
        out = []
        for row in rows:
            trace = json.loads(row['payload']).get('pmm28')
            if trace and (scope is None or trace.get('scope') == scope):
                reasoner=(trace.get('components') or {}).get('reasoner') or {}
                if trace.get('mode')=='full' and isinstance(reasoner.get('payload'),dict):
                    use=appraisal_use(reasoner)
                    reasoner['payload'].update(evaluation_use=use,evaluation_status=use['source'])
                    if use['source'] in ('local_only','local_fallback'):reasoner['applied_to']=[]
                out.append(trace)
            if len(out) >= limit: break
        return out
