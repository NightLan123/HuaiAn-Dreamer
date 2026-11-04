"""Equations D/E. Research estimates on explicitly identified measurement scales.

The mathematical functions are pure. Candidate generation never writes a trait.
The D independence assumption concerns errors, not independence of constructs.
"""
from __future__ import annotations
import copy
import numpy as np
from .registry import digest
from .pmm_contracts import finite, BLOCK_IDS, TraitUpdateProposal, result

VERSION='longitudinal-estimator/2.8.1'

def vector(x,n,name):
    a=np.asarray(x,dtype=float)
    if a.shape!=(n,) or not np.isfinite(a).all():raise ValueError('Invalid vector: '+name)
    return a

def matrix(x,shape,name):
    a=np.asarray(x,dtype=float)
    if a.shape!=shape or not np.isfinite(a).all():raise ValueError('Invalid matrix: '+name)
    return a

def covariance(x,n,name):
    a=matrix(x,(n,n),name)
    if not np.allclose(a,a.T,rtol=1e-9,atol=1e-12):raise ValueError('Asymmetric covariance: '+name)
    a=(a+a.T)/2
    eigen=np.linalg.eigvalsh(a)
    if eigen.min(initial=0)<-1e-10*max(1.,np.abs(a).max(initial=0)):
        raise ValueError('Non-PSD covariance: '+name)
    # Tiny roundoff negatives only; never fix arbitrary invalid input.
    if eigen.min(initial=0)<0:
        values,basis=np.linalg.eigh(a);a=(basis*np.maximum(values,0))@basis.T
    return a

def solve_cov(s,b):
    condition=float(np.linalg.cond(s))
    if not np.isfinite(condition) or condition>1e12:raise ValueError('Ill-conditioned innovation covariance')
    try:
        np.linalg.cholesky(s)
        return np.linalg.solve(s,b),condition
    except np.linalg.LinAlgError:raise ValueError('Innovation covariance must be positive definite') from None

def predict(mu,P,zeta,Omega,*,F=None,G=None,b=None,Q=None,g_validated=False,cross_cov=None,independent_errors=True):
    """Equation D. Unvalidated G is identically disabled, never randomized."""
    mu=np.asarray(mu,dtype=float);n=len(mu)
    if not 1<=n<=25:raise ValueError('Estimator construct dimension must be 1..25')
    mu=vector(mu,n,'mu');P=covariance(P,n,'P');zeta=vector(zeta,n,'zeta');Omega=covariance(Omega,n,'Omega')
    F=np.eye(n) if F is None else matrix(F,(n,n),'F')
    G=np.zeros((n,n)) if G is None or not g_validated else matrix(G,(n,n),'G')
    b=np.zeros(n) if b is None else vector(b,n,'b');Q=np.zeros((n,n)) if Q is None else covariance(Q,n,'Q')
    prior=F@mu+G@zeta+b
    prior_P=F@P@F.T+G@Omega@G.T+Q
    if cross_cov is not None:
        cross=matrix(cross_cov,(n,n),'Cov(mu_error,zeta_error)')
        covariance(np.block([[P,cross],[cross.T,Omega]]),2*n,'joint error covariance')
        prior_P+=F@cross@G.T+G@cross.T@F.T
    elif not independent_errors:raise ValueError('Correlated errors require cross covariance')
    prior_P=covariance(prior_P,n,'P_prior')
    return {'mu':prior.tolist(),'P':prior_P.tolist(),'G_enabled':bool(g_validated and G.any()),
            'assumption':'explicit_cross_covariance' if cross_cov is not None else 'independent_prior_and_adjusted_state_errors',
            'transition':'validated' if g_validated else 'G_disabled','process_covariance':Q.tolist()}

def linear_gaussian(mu,P,y,H,R):
    """Equation E with mask selection, solve, and Joseph covariance form."""
    n=len(mu);mu=vector(mu,n,'mu');P=covariance(P,n,'P');k=len(y)
    H=matrix(H,(k,n),'H_o');R=covariance(R,k,'R')
    mask=np.asarray([v is not None for v in y],dtype=bool)
    if not mask.any():return {'mu':mu.tolist(),'P':P.tolist(),'updated':False,'reason':'no_observations','observed':[]}
    yy=np.asarray([float(v) for v in y if v is not None])
    if not np.isfinite(yy).all():raise ValueError('Nonfinite measurement')
    H=H[mask];R=R[np.ix_(mask,mask)]
    S=H@P@H.T+R
    solved,condition=solve_cov(S,H@P);K=solved.T
    post=mu+K@(yy-H@mu)
    residual=np.eye(n)-K@H
    post_P=residual@P@residual.T+K@R@K.T
    post_P=covariance(post_P,n,'Joseph posterior covariance')
    return {'mu':post.tolist(),'P':post_P.tolist(),'updated':True,'observed':np.flatnonzero(mask).tolist(),
            'gain':K.tolist(),'innovation':(yy-H@mu).tolist(),'condition_number':condition,
            'approximation':'linear_gaussian','jitter_added':0.}

def ordinal_logit(mu,P,category,H,thresholds,noise_scale=1.,points=64):
    """Ordinal observation: Gauss-Hermite tilted moments + Gaussian ADF.

    This is NOT a Kalman update on category numbers. It projects the non-Gaussian
    posterior to its first two moments; approximation is explicitly reported.
    """
    n=len(mu);mu=vector(mu,n,'mu');P=covariance(P,n,'P');h=vector(H,n,'ordinal loading')
    cuts=np.asarray(thresholds,dtype=float)
    if cuts.ndim!=1 or not len(cuts) or not np.isfinite(cuts).all() or np.any(np.diff(cuts)<=0):raise ValueError('Ordered finite thresholds required')
    if type(category) is not int or not 0<=category<=len(cuts):raise ValueError('Ordinal category outside protocol')
    finite(noise_scale,'ordinal noise',1e-5,1e3)
    if type(points) is not int or not 16<=points<=128:raise ValueError('Quadrature points invalid')
    v=float(h@P@h);mean=float(h@mu)
    if v<1e-14:return {'mu':mu.tolist(),'P':P.tolist(),'updated':False,'reason':'deterministic_prior'}
    nodes,weights=np.polynomial.hermite.hermgauss(points);z=mean+np.sqrt(2*v)*nodes
    def logistic(x):return np.exp(-np.logaddexp(0.,-x))
    lo=np.zeros_like(z) if category==0 else logistic((cuts[category-1]-z)/noise_scale)
    hi=np.ones_like(z) if category==len(cuts) else logistic((cuts[category]-z)/noise_scale)
    w=weights*np.maximum(hi-lo,0.)
    if not np.isfinite(w).all() or w.sum()<1e-15:raise ValueError('Ordinal observation has negligible model likelihood')
    w=w/w.sum();post_mean=float(w@z);post_var=float(w@((z-post_mean)**2));gain=P@h/v
    out=mu+gain*(post_mean-mean);outP=P+np.outer(gain,gain)*(post_var-v)
    return {'mu':out.tolist(),'P':covariance(outP,n,'ADF covariance').tolist(),'updated':True,
            'approximation':'ordinal_logit_gauss_hermite_moment_projection_ADF',
            'quadrature_points':points,'not_exact_joint_posterior':True}

def adjusted_state_summary(samples,*,subject_id,scope,construct_ids,protocol,min_span=86400.):
    """Independent observed states, not neural prediction minus current prior.

    The protocol's context reference must be fitted on separate data and in the
    same latent scale. Its uncertainty is included in Omega; otherwise not ready.
    """
    n=len(construct_ids);eligible=[];seen=set();rejected=[]
    if not protocol.get('validated') or not protocol.get('independent_context_calibration'):
        return {'ready':False,'reason':'measurement_context_protocol_not_validated'}
    if protocol.get('construct_ids')!=list(construct_ids):raise ValueError('Protocol construct identity mismatch')
    for row in samples:
        key=row.get('event_id')
        if row.get('subject_id')!=subject_id or row.get('scope')!=scope:raise ValueError('Longitudinal subject/scope mismatch')
        if key in seen:rejected.append({'event_id':key,'reason':'duplicate_event'});continue
        if not key or row.get('withdrawn') or not row.get('reviewed') or row.get('kind')!='independent_state_measurement':
            rejected.append({'event_id':key,'reason':'not_valid_independent_observation'});continue
        if row.get('protocol_id')!=protocol.get('id') or not row.get('evidence_refs'):
            rejected.append({'event_id':key,'reason':'protocol_or_evidence_missing'});continue
        finite(row.get('timestamp'),'observation time',0)
        observed=vector(row['latent_observed'],n,'latent observed');context=vector(row['context_expected'],n,'independent context reference')
        error=covariance(row['measurement_covariance'],n,'state measurement error')+covariance(row['context_covariance'],n,'context error')
        solve_cov(error,np.eye(n))
        eligible.append((row,observed-context,error));seen.add(key)
    if len(eligible)<2 or max((r[0]['timestamp'] for r in eligible),default=0)-min((r[0]['timestamp'] for r in eligible),default=0)<min_span:
        return {'ready':False,'reason':'insufficient_independent_time_separated_states','eligible':len(eligible),'rejected':rejected}
    precisions=[solve_cov(e,np.eye(n))[0] for _,_,e in eligible];precision=sum(precisions)
    Omega=solve_cov(precision,np.eye(n))[0]
    zeta=Omega@sum((w@z for w,(_,z,_) in zip(precisions,eligible)))
    # Include between-event heterogeneity in addition to measurement error.
    residual=np.stack([z-zeta for _,z,_ in eligible]);Omega+=residual.T@residual/(len(eligible)*(len(eligible)-1))
    return {'ready':True,'zeta':zeta.tolist(),'Omega':covariance(Omega,n,'Omega').tolist(),
            'event_ids':[r['event_id'] for r,_,_ in eligible],
            'evidence_refs':sorted({e for r,_,_ in eligible for e in r['evidence_refs']}),
            'observed_count':len(eligible),'rejected':rejected,
            'method':'independent_context_adjusted_precision_mean_plus_between_event_variation'}

class LongTermEstimator:
    version=VERSION
    def estimate(self,ctx,*,prior=None,samples=(),measurement=None,protocol=None,transition=None,construct_ids=None):
        ids=list(construct_ids or BLOCK_IDS['H']);n=len(ids)
        if any(k not in BLOCK_IDS['H'] for k in ids):
            return result(TraitUpdateProposal,ctx,VERSION,{'reason':'construct_specific_estimator_not_calibrated','construct_ids':ids},status='not_ready',executed=False)
        if prior is None or protocol is None:
            return result(TraitUpdateProposal,ctx,VERSION,{'reason':'no_identifiable_prior_or_measurement_scale'},status='not_ready',executed=False)
        if prior.get('construct_ids')!=ids or prior.get('scale_id')!=protocol.get('scale_id'):
            raise ValueError('Prior/measurement scale mismatch')
        summary=adjusted_state_summary(samples,subject_id=ctx.subject_id,scope=ctx.scope,construct_ids=ids,protocol=protocol)
        transition=transition or {}
        if transition.get('construct_ids') is not None and transition['construct_ids']!=ids:raise ValueError('Transition construct identity mismatch')
        if transition.get('scale_id') is not None and transition['scale_id']!=prior['scale_id']:raise ValueError('Transition measurement scale mismatch')
        transition_ok=transition.get('validated') is True and not transition.get('engineering_only') and bool(transition.get('validation_ref'))
        d=predict(prior['mu'],prior['P'],summary.get('zeta',[0.]*n),summary.get('Omega',np.zeros((n,n))),
                  F=transition.get('F') if transition_ok else None,G=transition.get('G'),b=transition.get('b') if transition_ok else None,Q=transition.get('Q') if transition_ok else None,
                  g_validated=transition_ok and summary['ready'],cross_cov=transition.get('cross_cov'),
                  independent_errors=transition.get('independent_errors',True))
        posterior={**d,'updated':False,'reason':'no_independent_measurement'}
        if measurement:
            if measurement.get('subject_id')!=ctx.subject_id or measurement.get('scope')!=ctx.scope or measurement.get('scale_id')!=prior['scale_id']:
                raise ValueError('Measurement subject, scope or scale mismatch')
            if not measurement.get('reviewed') or measurement.get('withdrawn') or not measurement.get('evidence_refs'):
                raise ValueError('Independent reviewed measurement required')
            fixture=measurement.get('source_kind')=='controlled_fixture' and measurement.get('engineering_fixture') is True
            if measurement.get('source_kind') not in ('independent_questionnaire','independent_observer') and not fixture:
                raise ValueError('Generated/promoted labels are not independent personality measurements')
            if measurement.get('event_id') in summary.get('event_ids',[]):raise ValueError('State evidence and independent calibration cannot reuse one event')
            if measurement.get('model')=='linear_gaussian':
                posterior=linear_gaussian(d['mu'],d['P'],measurement['y'],measurement['H'],measurement['R'])
            elif measurement.get('model')=='ordinal_logit':
                posterior=ordinal_logit(d['mu'],d['P'],measurement['category'],measurement['H'],measurement['thresholds'],measurement.get('noise_scale',1.))
            else:raise ValueError('Unsupported measurement likelihood; no blind Kalman conversion')
        payload={'construct_ids':ids,'scale_id':prior['scale_id'],'prior':copy.deepcopy(prior),'prediction':d,
                 'posterior':posterior,'state_summary':summary,'measurement':copy.deepcopy(measurement),
                 'transition_version':transition.get('id'),'G_validated':transition_ok,
                 'candidate_only':True,'committed':False,'psychological_validity':'not_established',
                 'engineering_only':bool(protocol.get('engineering_only') or transition.get('engineering_only') or prior.get('engineering_fixture') or any(r.get('engineering_fixture') for r in samples) or (measurement or {}).get('engineering_fixture'))}
        payload['proposal_id']=digest([ctx.subject_id,ctx.scope,ctx.prior_revision,payload])
        return result(TraitUpdateProposal,ctx,VERSION,payload,
                      status='ok' if posterior['updated'] or d['G_enabled'] else 'not_ready',executed=True,
                      kind='candidate_estimate_not_mechanism_validation')

def fit_measurement_scale(rows,construct_ids,plan,scale_id):
    """Independent linear scale/context calibration, not a questionnaire simulator.

    canonical and latent are independently scored paired measurements. Context
    expectations are fitted separately to observed state measurements. Both
    residual covariances remain visible; fixture calibrations cannot be released.
    """
    ids=list(construct_ids);n=len(ids)
    if not ids or len(set(ids))!=n or any(k not in BLOCK_IDS['H'] for k in ids):raise ValueError('HEXACO calibration IDs required')
    names=('train','validation','test');subjects=[set(plan[k]['subjects']) for k in names]
    if any(subjects[i]&subjects[j] for i in range(3) for j in range(i)) or plan['train']['end']>=plan['validation']['start'] or plan['validation']['end']>=plan['test']['start']:
        raise ValueError('Measurement calibration subject/time leakage')
    clean={};folds={k:[] for k in names}
    for r in rows:
        if r.get('source_kind') not in ('independent_questionnaire','independent_observer','controlled_fixture') or not r.get('reviewed') or r.get('withdrawn') or not r.get('evidence_refs'):
            raise ValueError('Independent reviewed scale measurements required')
        permissions=r.get('permissions',{})
        if not r.get('engineering_fixture') and (permissions.get('parameter_training') is not True or r.get('scope') not in permissions.get('scopes',[])):
            raise ValueError('No permission for measurement calibration in this scope')
        if r['source_kind']=='controlled_fixture' and not r.get('engineering_fixture'):raise ValueError('Fixture must stay marked')
        key=(r['subject_id'],r['event_id'])
        if key in clean:
            if digest(clean[key])!=digest(r):raise ValueError('Conflicting calibration event')
            continue
        for k in ('canonical','latent','state'):vector(r[k],n,k)
        if np.any(np.asarray(r['canonical'])<0) or np.any(np.asarray(r['canonical'])>1):raise ValueError('Canonical calibration scores must use 0..1 scoring protocol')
        context=np.asarray(r['context'],dtype=float)
        if context.ndim!=1 or not 1<=len(context)<=8 or not np.isfinite(context).all():raise ValueError('Explicit context encoding required')
        choices=[k for k in names if r['subject_id'] in plan[k]['subjects'] and plan[k]['start']<=r['timestamp']<=plan[k]['end']]
        if len(choices)!=1:raise ValueError('Measurement outside declared partition')
        clean[key]=r;folds[choices[0]].append(r)
    if any(len(v)<4 for v in folds.values()):raise ValueError('Insufficient scale calibration observations')
    train=folds['train'];x=np.array([r['canonical'] for r in train]);y=np.array([r['latent'] for r in train])
    if np.any(x.var(0)<1e-6):raise ValueError('Unidentifiable scale mapping')
    slope=((x-x.mean(0))*(y-y.mean(0))).sum(0)/((x-x.mean(0))**2).sum(0);intercept=y.mean(0)-slope*x.mean(0)
    if np.any(np.abs(slope)<1e-6):raise ValueError('Singular scale mapping')
    cx=np.array([[1.,*r['context']] for r in train]);sy=np.array([r['state'] for r in train])
    context_coef=np.linalg.solve(cx.T@cx+np.eye(cx.shape[1])*1e-6,cx.T@sy)
    error=y-(x*slope+intercept);context_error=sy-cx@context_coef
    measurement_R=error.T@error/max(1,len(train)-2);context_R=context_error.T@context_error/max(1,len(train)-cx.shape[1])
    metrics={}
    for k,rs in folds.items():
        xx=np.array([r['canonical'] for r in rs]);yy=np.array([r['latent'] for r in rs]);cc=np.array([[1.,*r['context']] for r in rs]);ss=np.array([r['state'] for r in rs])
        metrics[k]={'scale_mse':float(np.mean((yy-xx*slope-intercept)**2)),
                    'baseline_mse':float(np.mean((yy-y.mean(0))**2)),
                    'context_mse':float(np.mean((ss-cc@context_coef)**2)),
                    'context_baseline_mse':float(np.mean((ss-sy.mean(0))**2)),
                    'subjects':len({r['subject_id'] for r in rs})}
    engineering=any(r.get('engineering_fixture',False) for r in clean.values())
    valid=not engineering and all(metrics[k]['subjects']>=2 and metrics[k]['scale_mse']<metrics[k]['baseline_mse'] and metrics[k]['context_mse']<=metrics[k]['context_baseline_mse'] for k in ('validation','test'))
    out={'format':'measurement-calibration/2.8','scale_id':scale_id,'construct_ids':ids,'slope':slope.tolist(),'intercept':intercept.tolist(),
         'measurement_covariance':measurement_R.tolist(),'context_coefficients':context_coef.tolist(),'context_covariance':context_R.tolist(),
         'validated':valid,'independent_context_calibration':valid,'engineering_only':engineering,'metrics':metrics,
         'source_refs':sorted({e for r in clean.values() for e in r['evidence_refs']}),'dataset_sha256':digest(list(clean.values())),
         'split_plan':copy.deepcopy(plan),'scientific_validity':'not_established'}
    out['id']=digest(out);return out
