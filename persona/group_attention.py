"""Group observation is separate from direct relationship learning."""
from __future__ import annotations
import copy
from .common import now
from . import relationships as dy

class GroupAttention:
    def __init__(self,engine):self.e=engine;self.st=engine.store
    def reserve(self,p,records):
        c=self.e.config.get()['group_attention']
        if not c['enabled']:return False
        with self.st.lock,self.st.db:
            stats=self.st.meta('group_attention_budget') or {};v=stats.get(p['scope'],{'at':now(),'calls':0,'messages':0})
            if now()-v['at']>=60:v={'at':now(),'calls':0,'messages':0}
            v['messages']+=len(records)
            text='\n'.join(r['text'] for r in records).lower()
            candidate=self.e.config.get()['cognition']['mode']=='adaptive' or bool(p.get('thread')) or any(w.lower() in text for w in c['watched_terms']) or (v['messages']-1)%c['sample_every']==0
            allowed=candidate and v['calls']<c['per_minute']
            if allowed:v['calls']+=1
            stats[p['scope']]=v;self.st.setmeta('group_attention_budget',stats)
            return allowed
    def context(self,p):
        rows=(self.st.meta('group_observations') or {}).get(p['scope'],[])
        # Quoted threads do not borrow unrelated participants' observations.
        selected=[r for r in rows if r['thread']==p.get('thread','')][-10:];budget=self.e.config.get()['group_attention']['context_chars'];out=[]
        for r in reversed(selected):
            text=r['text'][:min(1000,budget)]
            if not text:break
            out.append({**r,'text':text,'knowledge':'observed_only','shared_experience':False});budget-=len(text)
        return list(reversed(out))
    def observe(self,p,b,records,decision):
        if decision['attention']=='SKIM':return
        with self.st.lock,self.st.db:
            observed=self.st.meta('group_observations') or {};rows=observed.get(p['scope'],[]);known={r['id'] for r in rows}
            for r in records:
                if r['id'] in known:continue
                rows.append({**copy.deepcopy(r),'scope':p['scope'],'person':p['person'],'thread':b['thread'],'at':now(),'knowledge':'observed_only','shared_experience':False})
            observed[p['scope']]=rows[-100:];self.st.setmeta('group_observations',observed)
            self.e.learning.observe_group(p,records)
            # Raw inbox records remain intact when this bounded working window rotates.
            if decision['action'] not in ('REPLY','CLARIFY'):self.e.memory_lifecycle.enqueue(records,p['scope'],p['person'],b['thread'],source='observed_group',appraisal=decision.get('estimates'),cognitive_id=decision.get('cognitive_id'))
            self.st.event('group_attention',{'scope':p['scope'],'person':p['person'],'thread':b['thread'],'attention':decision['attention'],'participation':decision['action'],'source_ids':[r['id'] for r in records],'relationship_changed':False})
    def status(self):
        observations=self.st.meta('group_observations') or {};dyads=self.st.meta('pmm_dyads') or {};people=[]
        for scope,rows in observations.items():
            for person in sorted({r['person'] for r in rows}):
                d=dyads.get(dy.key(person,scope),{});count=d.get('interactions',0)
                people.append({'scope':scope,'person':person,'observed_messages':sum(r['person']==person for r in rows),'direct_interactions':count,'relationship':'有直接互动记录' if count else '陌生人：只有旁观记录','mutual_common_ground':[]})
        return {'people':people,'budget':self.st.meta('group_attention_budget') or {}}
