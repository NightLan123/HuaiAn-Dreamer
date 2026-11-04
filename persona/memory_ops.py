from .common import uid, now, clamp
MEMORY_OPS=('ADD','UPDATE','DELETE','NOOP','KEEP','REINTERPRET','MERGE','DECAY')

class MemoryOperations:
    def add_memory(self,content,kind,session,turn_id,evidence,confidence,importance):
        mid=uid();t=now()
        self.store.db.execute('INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (mid,content[:6000],kind,session['scope'],session['person'],confidence,importance,'active',turn_id,evidence[:2000],t,t,1,''))
        traces=self.store.meta('memory_traces') or {}
        traces[mid]={'storage_strength':.25+.5*importance,'last_access':t,'accesses':0,'sources':[{'record_id':turn_id+':u','quote':evidence[:2000]}] if evidence else [],'source_type':'direct_interaction' if session.get('direct_interaction',True) else 'observed_group'}
        self.store.setmeta('memory_traces',traces)
        return mid
    def apply_memory(self,op,text,session,turn_id,visible_ids):
        if not isinstance(op,dict):return {'status':'rejected','reason':'操作不是对象'}
        action=op.get('op');mid=str(op.get('id',''));content=str(op.get('content','')).strip()
        result={'op':action,'id':mid,'status':'rejected'}
        if action not in MEMORY_OPS:return {**result,'reason':'未知操作'}
        if action in ('NOOP','KEEP'):return {**result,'status':'kept'}
        quote=str(op.get('evidence_quote','')).strip()
        if not quote or quote not in text:return {**result,'reason':'当前输入中找不到逐字证据'}
        targets=list(dict.fromkeys(str(x) for x in op.get('ids',[]))) if action=='MERGE' else [mid]
        if action!='ADD':
            if not targets or any(i not in visible_ids for i in targets):return {**result,'reason':'目标不在本轮可访问记忆中'}
            if action=='MERGE' and len(targets)<2:return {**result,'reason':'合并至少需要两条不同记忆'}
            for i in targets:
                old=self.store.rows('SELECT * FROM memories WHERE id=? AND scope=? AND status=\'active\'',(i,session['scope']))
                if not old:return {**result,'reason':'记忆范围不允许修改或已失效'}
        if action in ('ADD','UPDATE','MERGE','REINTERPRET') and not content:return {**result,'reason':'内容为空'}
        try:
            conf=clamp(op.get('confidence',.5));imp=clamp(op.get('importance',.5))
        except (ValueError,TypeError):return {**result,'reason':'数值无效'}
        kind=op.get('kind','hypothesis')
        if kind not in ('fact','preference','hypothesis','relation','self_observation'):kind='hypothesis'
        conf=min(conf,.6 if kind in ('hypothesis','self_observation') else .9)
        if action=='ADD':
            duplicates=self.store.rows("SELECT id FROM memories WHERE content=? AND scope=? AND status='active'",(content[:6000],session['scope']))
            if duplicates:return {**result,'status':'kept','id':duplicates[0]['id'],'reason':'内容已存在'}
            mid=self.add_memory(content,kind,session,turn_id,quote,conf,imp)
        elif action in ('UPDATE','MERGE'):
            # Versioning: retain original content, create a successor with its own evidence.
            for i in targets:self.store.db.execute("UPDATE memories SET status='superseded',updated_at=? WHERE id=?",(now(),i))
            mid=self.add_memory(content,kind,session,turn_id,quote,conf,imp)
        elif action=='DELETE':self.store.db.execute("UPDATE memories SET status='deleted',updated_at=?,revision=revision+1 WHERE id=?",(now(),mid))
        elif action=='REINTERPRET':self.store.db.execute('UPDATE memories SET interpretation=?,updated_at=?,revision=revision+1 WHERE id=?',(content[:2000],now(),mid))
        elif action=='DECAY':self.store.db.execute('UPDATE memories SET importance=importance*0.8,updated_at=?,revision=revision+1 WHERE id=?',(now(),mid))
        if action in ('ADD','UPDATE','MERGE'):
            traces=self.store.meta('memory_traces') or {}
            if mid in traces:
                for source in traces[mid].get('sources',[]):source['source_text']=text
                self.store.setmeta('memory_traces',traces)
        return {**result,'id':mid,'status':'applied','evidence':quote,'targets':targets if action!='ADD' else []}
