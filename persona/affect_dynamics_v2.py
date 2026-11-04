"""E-A/B/C/E. Unbounded latent dynamics, seconds, exact block OU propagation.

Each fast axis is scalar; the first three couple only to the corresponding
slow axis. No latent clipping. Display links belong to the observation layer.
"""
from __future__ import annotations
import copy, math
from datetime import datetime, timezone
import numpy as np
from .affect import AXES

MOOD_AXES = AXES[:3]
LINK_EPS = 1e-9

def seconds(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if isinstance(value, datetime):
        if value.tzinfo is None: raise ValueError('事件时间必须带时区')
        value = value.timestamp()
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 253402300799:
        raise ValueError('事件时间须为有限 UTC 秒或带时区的 ISO 时间')
    return float(value)

def iso(value): return datetime.fromtimestamp(seconds(value), timezone.utc).isoformat()

def link(x, axes=AXES):
    x=np.asarray(x,dtype=float)
    if x.shape!=(len(axes),) or not np.isfinite(x).all():raise ValueError('潜在情绪维度/有限性错误')
    return {k:float(np.tanh(v) if k=='valence' else np.exp(-np.logaddexp(0.,-v))) for k,v in zip(axes,x)}

def inverse(values, axes=AXES):
    """Record precision loss at exact historical boundaries; unknown != zero."""
    out=[];mask=[];boundary=[]
    for k in axes:
        v=values.get(k);mask.append(int(v is not None))
        if v is None:out.append(0.);continue
        lo=-1. if k=='valence' else 0.
        if type(v) not in (int,float) or not math.isfinite(v) or not lo<=v<=1:raise ValueError('历史情绪边界无效')
        p=(v+1)/2 if k=='valence' else v
        clipped=min(1-LINK_EPS,max(LINK_EPS,p))
        if clipped!=p:boundary.append(k)
        latent=math.log(clipped)-math.log1p(-clipped)
        out.append(latent/2 if k=='valence' else latent)
    return out,mask,{'link':'tanh_valence_sigmoid_other','epsilon':LINK_EPS,'boundary_approximations':boundary,'original':copy.deepcopy(values)}

def ou_moments(x,mu,kappa,sigma,dt):
    x,mu,kappa,sigma=np.broadcast_arrays(*[np.asarray(v,dtype=float) for v in (x,mu,kappa,sigma)])
    if not all(np.isfinite(v).all() for v in (x,mu,kappa,sigma)) or (kappa<0).any() or (sigma<0).any() or not math.isfinite(dt) or dt<0:raise ValueError('OU 参数/时间无效')
    decay=np.exp(-kappa*dt)
    factor=np.full_like(kappa,dt,dtype=float)
    np.divide(-np.expm1(-2*kappa*dt),2*kappa,out=factor,where=kappa!=0)
    return mu+decay*(x-mu),sigma*sigma*factor

def _integral(power,rate,dt):
    """Integral of s**power exp(-rate*s), stable at zero and tiny intervals."""
    z=rate*dt
    if z<.5:
        term=1.;total=1/(power+1)
        for n in range(1,80):
            term*=-z/n;add=term/(power+n+1);total+=add
            if abs(add)<1e-17:break
        return dt**(power+1)*total
    value=-math.expm1(-z)/rate
    tail=math.exp(-z)
    for n in range(1,power+1):value=n/rate*value-(dt**n*tail/rate if tail else 0.)
    return value

def coupled_moments(e,m,mu_e,mu_m,ke,km,se,sm,c,dt):
    """Exact two-dimensional triangular OU. c couples fast deviation to mood.

    Independent driving Brownian motions still induce cross-covariance. Near
    equal rates use the analytic moment series instead of subtracting numbers.
    """
    if dt<0 or any(not math.isfinite(float(v)) for v in (e,m,mu_e,mu_m,ke,km,se,sm,c,dt)) or min(ke,km,se,sm)<0:raise ValueError('快慢 OU 参数无效')
    if not dt:return np.array([e,m]),np.zeros((2,2))
    fe,fm=math.exp(-ke*dt),math.exp(-km*dt);d=km-ke
    close=abs(d)<1e-4*max(ke,km,1/dt)
    cross=(dt*fm if d==0 else (fe-fm)/d)
    if close and abs(d*dt)<.01:cross=fm*dt*(1+d*dt/2+(d*dt)**2/6+(d*dt)**3/24)
    mean=np.array([mu_e+fe*(e-mu_e),mu_m+fm*(m-mu_m)+c*cross*(e-mu_e)])
    qe=se*se*_integral(0,2*ke,dt)
    if close:
        # exp(d*s)-1 series; omitted terms are O((d/effective_rate)^5).
        coeff=[d**n/math.factorial(n+1) for n in range(5)]
        em=sum(a*_integral(i+1,2*km,dt) for i,a in enumerate(coeff))
        mm=sum(a*b*_integral(i+j+2,2*km,dt) for i,a in enumerate(coeff) for j,b in enumerate(coeff))
    else:
        em=(_integral(0,2*ke,dt)-_integral(0,ke+km,dt))/d
        mm=(_integral(0,2*ke,dt)-2*_integral(0,ke+km,dt)+_integral(0,2*km,dt))/(d*d)
    cov=np.array([[qe,c*se*se*em],[c*se*se*em,sm*sm*_integral(0,2*km,dt)+c*c*se*se*mm]])
    return mean,(cov+cov.T)/2

def propagate(fast,mood,parameters,dt,rng,delta_turns=1):
    """Interval OU first; event jump is deliberately absent from this function."""
    fast=np.asarray(fast,float);mood=np.asarray(mood,float)
    if fast.shape!=(len(AXES),) or mood.shape!=(len(MOOD_AXES),):raise ValueError('快/慢状态维度错误')
    mu=np.asarray(parameters['mu']);k=np.asarray(parameters['kappa']);s=np.asarray(parameters['sigma'])
    if any(v.shape!=(8,) or not np.isfinite(v).all() for v in (mu,k,s)) or (k<=0).any() or (s<0).any():raise ValueError('动态参数无效')
    if type(delta_turns) is not int or delta_turns<0:raise ValueError('轮次增量无效')
    n=np.asarray(parameters.get('kappa_n',[0.]*8),float)
    if n.shape!=(8,) or (n<0).any() or not np.isfinite(n).all():raise ValueError('轮次参数无效')
    if n.any() and not parameters.get('turn_term_validated'):raise ValueError('轮次独立项缺少验证')
    mean,var=ou_moments(fast,mu[:5],k[:5],s[:5],dt);slow=np.zeros(3);noise=np.zeros(8);covariances=[]
    for i in range(3):
        pair,cov=coupled_moments(fast[i],mood[i],mu[i],mu[i+5],k[i],k[i+5],s[i],s[i+5],parameters['coupling'][i],dt)
        vals,vecs=np.linalg.eigh(cov)
        if vals.min()<-1e-10*max(1.,np.abs(cov).max()):raise ValueError('OU 协方差非正半定')
        draw=vecs@(np.sqrt(np.maximum(vals,0))*rng.standard_normal(2)) if dt else np.zeros(2)
        mean[i]=pair[0];slow[i]=pair[1];noise[i]=draw[0];noise[i+5]=draw[1];covariances.append(cov.tolist())
    if dt:noise[3:5]=np.sqrt(var[3:5])*rng.standard_normal(2)
    center=np.r_[mean,slow];decay=np.exp(-n*delta_turns)
    # E-C is a deterministic additional transition after real-time propagation;
    # no second clock-derived Brownian interval is manufactured from a turn.
    final=mu+decay*(center+noise-mu)
    return final[:5],final[5:],{'mean':center.tolist(),'natural_noise':noise.tolist(),'covariance_blocks':covariances,'uncoupled_variance':var[3:5].tolist(),'kappa_n':n.tolist(),'turn_term_order':'OU_then_independent_validated_turn_map'}
