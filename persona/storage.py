from __future__ import annotations
import sqlite3, threading, json, copy, re, math
from pathlib import Path
from .common import uid, now, dumps, SCHEMA

BASE_STATE = {'traits': {'curiosity': .65, 'restraint': .65, 'assertiveness': .50},
              'values': {'honesty': .85, 'respect': .8, 'autonomy': .7},
              'short': {'valence': 0., 'arousal': .25, 'stress': .15, 'engagement': .65},
              'self_summary': '我刚开始积累自己的经历，尚未形成经过验证的稳定倾向。',
              'turn_count': 0, 'updated_at': 0.}

class Store:
    TABLES = ('meta', 'sessions', 'messages', 'memories', 'events', 'relations')
    def __init__(self, directory, create=True):
        from .data_guard import inspect_database,DataGuardError
        path=Path(directory)/'subject.sqlite3'
        if path.exists():inspect_database(path)
        elif not create:raise DataGuardError('原主体数据库缺失，已停止，未创建空库：'+str(path))
        self.directory = Path(directory); self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.directory / 'subject.sqlite3', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA busy_timeout=5000')
        with self.db:
            self.db.executescript('''
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, title TEXT, scope TEXT, person TEXT, created_at REAL);
            CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, created_at REAL, turn_id TEXT);
            CREATE TABLE IF NOT EXISTS memories (id TEXT PRIMARY KEY, content TEXT, kind TEXT, scope TEXT, person TEXT,
                confidence REAL, importance REAL, status TEXT, source_turn TEXT, evidence TEXT, created_at REAL, updated_at REAL, revision INTEGER, interpretation TEXT);
            CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, kind TEXT, payload TEXT, created_at REAL);
            CREATE TABLE IF NOT EXISTS relations (id TEXT PRIMARY KEY, name TEXT, data TEXT, updated_at REAL);
            CREATE TABLE IF NOT EXISTS inbox (id TEXT PRIMARY KEY, payload TEXT, status TEXT, result TEXT, created_at REAL);
            CREATE INDEX IF NOT EXISTS message_session ON messages(session_id, created_at);
            CREATE INDEX IF NOT EXISTS memory_scope ON memories(scope, status);
            ''')
            if not self.meta('identity'):
                self.setmeta('identity', {'id':uid(), 'created_at':now(), 'schema':SCHEMA})
                self.setmeta('state', copy.deepcopy(BASE_STATE))
            elif self.meta('identity')['schema'] != SCHEMA:
                raise RuntimeError('主体数据版本不兼容；请保留数据并使用匹配的程序版本')
            self.db.execute("UPDATE inbox SET status='interrupted',result=? WHERE status='processing'", (dumps({'message':'上次处理被中断；为避免重复发送，不自动重试。'}),))

    def meta(self, key):
        with self.lock:
            r = self.db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
            return json.loads(r[0]) if r else None
    def setmeta(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key,dumps(value)))
    def rows(self, sql, args=()):
        with self.lock: return [dict(x) for x in self.db.execute(sql,args).fetchall()]
    def event(self, kind, payload):
        self.db.execute('INSERT INTO events VALUES (?,?,?,?)',(uid(),kind,dumps(payload),now()))
    def session(self, person='web:owner', scope='private:web:owner', title='新的对话'):
        i = uid()
        with self.lock,self.db:
            self.db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)',(i,title[:60],scope,person,now()))
        return i
    def get_session(self, sid):
        r = self.rows('SELECT * FROM sessions WHERE id=?',(sid,))
        if not r: raise ValueError('对话不存在')
        return r[0]
    def sessions(self): return self.rows('SELECT * FROM sessions ORDER BY created_at DESC')
    def history(self, sid, limit=40, offset=0):
        return list(reversed(self.rows('SELECT * FROM messages WHERE session_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', (sid,limit,offset))))
    def memories(self, scope=None, all_status=False):
        where=[];args=[]
        if scope is not None: where.append("(scope=? OR scope='self')");args.append(scope)
        if not all_status: where.append("status='active'")
        return self.rows('SELECT * FROM memories'+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY updated_at DESC', args)
    def relation(self, person):
        r = self.rows('SELECT * FROM relations WHERE id=?',(person,))
        return json.loads(r[0]['data']) if r else {'trust':.5, 'familiarity':0., 'affection':.5, 'interactions':0}
    def recent_events(self, limit=50, offset=0):
        r=self.rows('SELECT * FROM events ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?', (limit,offset))
        for x in r:x['payload']=json.loads(x['payload'])
        return r
    def snapshot(self):
        with self.lock:
            return {'format':'persona-dialogue', 'schema':SCHEMA, 'exported_at':now(),
                    'qq_inbox':self.rows('SELECT * FROM inbox'),'tables':{t:self.rows('SELECT * FROM '+t) for t in self.TABLES}}
    def restore(self, snap):
        if snap.get('format')!='persona-dialogue' or snap.get('schema')!=SCHEMA: raise ValueError('不兼容的主体快照')
        ts=snap.get('tables',{})
        if set(ts)!=set(self.TABLES): raise ValueError('快照缺少数据表')
        inbox=snap.get('qq_inbox',[])
        if not isinstance(inbox,list) or len(inbox)>50000:raise ValueError('QQ 收件备份无效或超过上限')
        seen=set()
        for row in inbox:
            if not isinstance(row,dict) or set(row)!=set(('id','payload','status','result','created_at')) or not all(isinstance(row[f],str) for f in ('id','payload','status','result')) or row['id'] in seen:raise ValueError('QQ 收件备份格式无效')
            if not isinstance(json.loads(row['payload']),dict) or not isinstance(json.loads(row['result']),dict) or type(row['created_at']) not in (int,float) or not math.isfinite(row['created_at']):raise ValueError('QQ 收件备份内容无效')
            seen.add(row['id'])
        # Validate every table in an isolated in-memory DB before touching live data.
        probe=sqlite3.connect(':memory:')
        try:
            for t in self.TABLES:
                schema=self.db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(t,)).fetchone()[0]
                probe.execute(schema)
                cols=[x[1] for x in self.db.execute('PRAGMA table_info('+t+')')]
                if not isinstance(ts[t],list): raise ValueError('快照表格式错误')
                for row in ts[t]:
                    if set(row)!=set(cols): raise ValueError('快照列不兼容')
                    probe.execute('INSERT INTO '+t+' VALUES ('+','.join('?'*len(cols))+')', [row[c] for c in cols])
            meta={x['key']:json.loads(x['value']) for x in ts['meta']}
            from .affect_runtime import validate_metadata as validate_affect_v2
            validate_affect_v2(meta)
            from .pmm_trainer import validate_metadata as validate_pmm28
            validate_pmm28(meta)
            from .evidence import validate as validate_evidence
            validate_evidence(meta.get('learning_evidence'))
            from .learning import validate_policy,validate_state as validate_learning,validate_observed
            if meta.get('learning_policy') is not None:validate_policy(meta['learning_policy'])
            validate_learning(meta.get('learning_center'));validate_observed(meta.get('learning_observed_sources'))
            from .social_graph import validate as validate_graph
            validate_graph(meta.get('social_graph'))
            if not meta.get('identity',{}).get('id') or not isinstance(meta.get('state'),dict): raise ValueError('主体信息缺失')
            identity=meta['identity'];state=meta['state']
            from .affect import validate as validate_affect
            validate_affect(meta.get('pmm_affect'),identity['id'])
            from .pragmatics import validate as validate_pragmatics
            validate_pragmatics(meta.get('pmm_pragmatics'))
            if identity.get('schema')!=SCHEMA or not re.fullmatch(r'[0-9a-f]{32}',str(identity.get('id',''))):raise ValueError('快照主体标识无效')
            if set(state)!=set(BASE_STATE) or not isinstance(state['turn_count'],int) or state['turn_count']<0:raise ValueError('快照状态格式错误')
            if not isinstance(state['self_summary'],str):raise ValueError('快照自我描述格式错误')
            for field in ('short','traits','values'):
                if not isinstance(state[field],dict) or set(state[field])!=set(BASE_STATE[field]):raise ValueError('快照状态维度不兼容')
                for key,value in state[field].items():
                    low=-1 if key=='valence' else 0
                    if not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=1:raise ValueError('快照状态数值无效')
            for row in ts['relations']:
                relation=json.loads(row['data'])
                for key in ('trust','affection','familiarity'):
                    value=relation.get(key)
                    if not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=1:raise ValueError('快照关系数值无效')
                if not isinstance(relation.get('interactions'),int) or relation['interactions']<0:raise ValueError('快照关系计数无效')
            from .memory_lifecycle import validate_memory_state
            validate_memory_state({'pending':meta.get('memory_pending') or [],'traces':meta.get('memory_traces') or {},'open_events':meta.get('memory_open_events') or {}})
            from .cognition import AppraisalHead,validate_feedback_state
            AppraisalHead(meta.get('cognitive_head'));validate_feedback_state(meta.get('cognitive_feedback') or [])
            old=self.meta('identity')['id']
            if meta['identity']['id']!=old and self.meta('state')['turn_count']>0:
                raise ValueError('这个程序已有另一位主体的经历。请使用新的数据目录恢复，避免覆盖身份。')
            for m in ts['messages']:
                if not probe.execute('SELECT 1 FROM sessions WHERE id=?',(m['session_id'],)).fetchone(): raise ValueError('快照会话引用不完整')
        finally: probe.close()
        with self.lock,self.db:
            for t in reversed(self.TABLES):self.db.execute('DELETE FROM '+t)
            for t in self.TABLES:
                cols=[x[1] for x in self.db.execute('PRAGMA table_info('+t+')')]
                for row in ts[t]:self.db.execute('INSERT INTO '+t+' VALUES ('+','.join('?'*len(cols))+')',[row[c] for c in cols])
            self.db.execute('DELETE FROM inbox')
            for row in inbox:self.db.execute('INSERT INTO inbox VALUES (?,?,?,?,?)',(row['id'],row['payload'],'interrupted' if row['status']=='processing' else row['status'],row['result'],row['created_at']))
            self.setmeta('consolidation_generation',uid())
            self.event('restore',{'identity':meta['identity']['id']})
    def edit_memory(self, mid, action, content='', reason='用户在管理界面修订'):
        with self.lock,self.db:
            old=self.rows('SELECT * FROM memories WHERE id=?',(mid,))
            if not old: raise ValueError('记忆不存在')
            if action not in ('UPDATE','DELETE','KEEP'): raise ValueError('无效记忆操作')
            if action=='UPDATE' and not content.strip(): raise ValueError('修订内容不能为空')
            self.db.execute('UPDATE memories SET content=?,status=?,updated_at=?,revision=revision+1 WHERE id=?',
                (content[:6000] if action=='UPDATE' else old[0]['content'], 'deleted' if action=='DELETE' else 'active',now(),mid))
            self.event('memory_manual',{'before':old[0],'op':action,'reason':reason})
    def add_inbox(self, key, event):
        with self.lock,self.db:
            cur=self.db.execute('INSERT OR IGNORE INTO inbox VALUES (?,?,?,?,?)',(key,dumps(event),'pending','{}',now()))
            return cur.rowcount==1
    def inbox_update(self,key,status,result):
        with self.lock,self.db:self.db.execute('UPDATE inbox SET status=?,result=? WHERE id=?',(status,dumps(result),key))
    def close(self):
        with self.lock:self.db.close()
