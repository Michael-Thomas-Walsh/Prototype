"""Versioned decision memory. Compatible with v16 SQLite records; no destructive migration."""
import hashlib, json, os, re, sqlite3, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from fastapi import HTTPException, Header
from pydantic import BaseModel, Field, ConfigDict

STATUSES = ('Proposed','Under review','Approved','Rejected','Superseded')
TRANSITIONS = {'Proposed':{'Under review','Rejected'}, 'Under review':{'Approved','Rejected'},
               'Approved':{'Under review','Superseded'}, 'Rejected':{'Under review'}, 'Superseded':set()}
def stamp(): return datetime.now(timezone.utc).isoformat()
def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()

class Evidence(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    kind: str = Field(min_length=1,max_length=60)
    id: str = Field(min_length=1,max_length=300)
    source_key: str = Field(min_length=1,max_length=300)
    source_version: str = Field(min_length=1,max_length=300)
    provenance: Literal['extracted','calculated','human-confirmed','inferred','synthetic']
    description: str = Field(default='',max_length=3000)

class DecisionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    title: str = Field(min_length=4,max_length=240)
    project: str = Field(default='Snowdon Towers (prototype)',min_length=1,max_length=150)
    building_type: str = ''
    discipline: str = ''
    issue_type: str = ''
    priority: Literal['critical','high','medium','low'] = 'medium'
    why_it_matters: str = Field(default='',max_length=5000)
    design_stage: str = ''
    context: str = Field(min_length=5,max_length=12000)
    options: list[str] = Field(default_factory=list,max_length=30)
    decision: str = Field(min_length=5,max_length=12000)
    rationale: str = Field(min_length=5,max_length=12000)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    acceptance_criteria: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    reusable_conditions: list[str] = Field(default_factory=list)
    references: list[Evidence] = Field(default_factory=list,max_length=100)
    issue_id: str | None = None
    element_ids: list[str] = Field(default_factory=list)
    owner: str = ''
    status: Literal['Proposed'] = 'Proposed'

class EventCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    expected_version: int = Field(ge=0)
    event_type: Literal['review','approval','evidence','implementation','outcome','lesson','supersession'] = 'review'
    actor: str = Field(default='Local reviewer',min_length=1,max_length=150)
    note: str = Field(min_length=5,max_length=12000)
    status: str | None = None
    references: list[Evidence] = Field(default_factory=list,max_length=100)
    superseded_by: str | None = None

class SourceUpdate(BaseModel):
    project: str = Field(min_length=1)
    source_key: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    expected_revision: str | None = None

class Ledger:
    def __init__(self, root):
        self.path=Path(root)/'decision_ledger.sqlite3'
        with self.db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,creator TEXT NOT NULL,payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS decision_events(event_id TEXT PRIMARY KEY,decision_id TEXT NOT NULL,created_at TEXT NOT NULL,actor TEXT NOT NULL,event_type TEXT NOT NULL,payload TEXT NOT NULL,FOREIGN KEY(decision_id) REFERENCES decisions(id));
            CREATE INDEX IF NOT EXISTS idx_ledger_events ON decision_events(decision_id,created_at);
            CREATE TABLE IF NOT EXISTS ledger_sources(project TEXT,source_key TEXT,revision TEXT,updated_at TEXT,PRIMARY KEY(project,source_key));
            CREATE TABLE IF NOT EXISTS ledger_source_history(id INTEGER PRIMARY KEY,project TEXT,source_key TEXT,previous_revision TEXT,revision TEXT,actor TEXT,created_at TEXT);
            ''')
            c.execute('CREATE VIRTUAL TABLE IF NOT EXISTS ledger_search USING fts5(id UNINDEXED, body)')
            c.execute("CREATE INDEX IF NOT EXISTS idx_decision_project ON decisions(json_extract(payload,'$.project'))")
            for row in c.execute('SELECT id,payload FROM decisions WHERE id NOT IN (SELECT id FROM ledger_search)').fetchall():
                history=' '.join(e[0] for e in c.execute('SELECT payload FROM decision_events WHERE decision_id=?',(row['id'],)))
                c.execute('INSERT INTO ledger_search(id,body) VALUES(?,?)',(row['id'],row['payload']+' '+history))
    @contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=15); c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON'); c.execute('PRAGMA journal_mode=WAL')
        try:
            with c: yield c
        finally: c.close()
    def get(self,c,did):
        row=c.execute('SELECT * FROM decisions WHERE id=?',(did,)).fetchone()
        if not row: raise HTTPException(404,'Decision not found')
        d=json.loads(row['payload']);d.update(id=did,created_at=row['created_at'],creator=row['creator'])
        events=c.execute('SELECT rowid,* FROM decision_events WHERE decision_id=? ORDER BY rowid',(did,)).fetchall()
        history=[]
        for e in events:
            p=json.loads(e['payload'])
            if p.get('status'): d['status']=p['status']
            if e['event_type']=='evidence':d['references']=p.get('references',[])
            history.append(dict(id=e['event_id'],created_at=e['created_at'],actor=e['actor'],event_type=e['event_type'],**p))
        refs=d.get('references',[]);problems=[]
        if not refs: problems.append('No versioned evidence attached')
        for ref in refs:
            if not ref.get('source_key') or not ref.get('source_version'):
                problems.append('Legacy reference requires source and revision');continue
            current=c.execute('SELECT revision FROM ledger_sources WHERE project=? AND source_key=?',(d['project'],ref['source_key'])).fetchone()
            if not current:problems.append('Unregistered source: '+ref['source_key'])
            elif current['revision']!=ref['source_version']:problems.append('Changed source: '+ref['source_key'])
        d.update(history=history,version=len(events),events_count=len(events),evidence_problems=problems,
                 evidence_validity='stale' if any(p.startswith('Changed') for p in problems) else 'incomplete' if problems else 'current',
                 demonstration=any(r.get('provenance')=='synthetic' for r in refs),
                 evidence_hash=digest(refs),approval_identity='Verified only when event authenticated=true')
        return d
    def list(self,q='',project='',status='',limit=200,offset=0):
        conditions=[];args=[]
        terms=re.findall(r'[\w-]+',q)
        join=' JOIN ledger_search ON ledger_search.id=d.id' if terms else ''
        if terms:
            conditions.append('ledger_search MATCH ?');args.append(' AND '.join('"'+t+'"*' for t in terms))
        if project:conditions.append("json_extract(d.payload,'$.project')=?");args.append(project)
        if status:
            conditions.append("COALESCE((SELECT json_extract(e.payload,'$.status') FROM decision_events e WHERE e.decision_id=d.id AND json_extract(e.payload,'$.status') IS NOT NULL ORDER BY e.rowid DESC LIMIT 1),json_extract(d.payload,'$.status'))=?");args.append(status)
        where=' WHERE '+' AND '.join(conditions) if conditions else ''
        base=' FROM decisions d'+join+where
        with self.db() as c:
            total=c.execute('SELECT COUNT(*)'+base,args).fetchone()[0]
            rows=c.execute('SELECT d.id'+base+" ORDER BY CASE json_extract(d.payload,'$.priority') WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,d.created_at DESC LIMIT ? OFFSET ?",args+[limit,offset]).fetchall()
            items=[self.get(c,r['id']) for r in rows]
        return {'decisions':items,'total':total,'offset':offset,'limit':limit}
    def create(self,payload,actor):
        did='DEC-'+uuid.uuid4().hex[:12].upper()
        with self.db() as c:
            raw=json.dumps(payload.model_dump(),ensure_ascii=False)
            c.execute('INSERT INTO decisions VALUES(?,?,?,?)',(did,stamp(),actor,raw))
            c.execute('INSERT INTO ledger_search(id,body) VALUES(?,?)',(did,raw))
        return {'id':did,'status':'Proposed'}
    def event(self,did,event,identity):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE');d=self.get(c,did)
            if d['version']!=event.expected_version:raise HTTPException(409,'Decision changed. Reload before reviewing.')
            if d['status']=='Superseded':raise HTTPException(409,'Superseded records are historical; create a new proposal.')
            if event.status and event.status!=d['status'] and event.status not in TRANSITIONS.get(d['status'],set()):raise HTTPException(422,'Invalid decision transition')
            if event.status=='Approved':
                if d['status']!='Under review':raise HTTPException(422,'Submit for review before approval')
                if event.event_type!='approval' or identity['role']!='approver':raise HTTPException(403,'An authorised approver and explicit approval event are required')
                if d['evidence_validity']!='current':raise HTTPException(422,'Resolve evidence problems before approval')
                if not any(r.get('kind')=='model' for r in d.get('references',[])):raise HTTPException(422,'Attach versioned model evidence before approval')
                if not any(str(x).strip() for x in d.get('options',[])) or not any(str(x).strip() for x in d.get('acceptance_criteria',[])):raise HTTPException(422,'Document alternatives and acceptance criteria before approval')
            if event.event_type=='approval' and event.status!='Approved':raise HTTPException(422,'Approval must set Approved status')
            if event.event_type=='evidence':
                if not event.references:raise HTTPException(422,'Replacement evidence cannot be empty')
                if event.status!='Under review':raise HTTPException(422,'Changed evidence must return to Under review')
            if event.status=='Superseded':
                if event.event_type!='supersession' or not event.superseded_by or event.superseded_by==did:raise HTTPException(422,'Specify replacement decision')
                replacement=self.get(c,event.superseded_by)
                if replacement['project']!=d['project']:raise HTTPException(422,'Replacement must belong to the same project')
            if event.event_type=='implementation' and d['status']!='Approved':raise HTTPException(422,'Implementation verification requires an approved decision')
            p=event.model_dump(exclude={'actor','event_type'});p.update(authenticated=identity['authenticated'],role=identity['role'],evidence_hash=d['evidence_hash'])
            c.execute('INSERT INTO decision_events VALUES(?,?,?,?,?,?)',(str(uuid.uuid4()),did,stamp(),identity['actor'],event.event_type,json.dumps(p)))
            c.execute("UPDATE ledger_search SET body=body || ' ' || ? WHERE id=?",(json.dumps(p),did))
            return self.get(c,did)
    def update_source(self,p,actor):
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT revision FROM ledger_sources WHERE project=? AND source_key=?',(p.project,p.source_key)).fetchone()
            old=row['revision'] if row else None
            if old!=p.expected_revision:raise HTTPException(409,'Source revision changed. Refresh the source registry.')
            c.execute('INSERT INTO ledger_sources VALUES(?,?,?,?) ON CONFLICT(project,source_key) DO UPDATE SET revision=excluded.revision,updated_at=excluded.updated_at',(p.project,p.source_key,p.revision,stamp()))
            c.execute('INSERT INTO ledger_source_history(project,source_key,previous_revision,revision,actor,created_at) VALUES(?,?,?,?,?,?)',(p.project,p.source_key,old,p.revision,actor,stamp()))
        return {'source_key':p.source_key,'revision':p.revision,'previous_revision':old}

def register(app,root,issue_provider=None):
    ledger=Ledger(root);app.state.decision_ledger=ledger
    def identity(token,actor='Local reviewer'):
        accounts=json.loads(os.environ.get('FUSION_REVIEWERS_JSON','{}'))
        if accounts:
            record=accounts.get(token or '')
            if not record:raise HTTPException(401,'Valid reviewer token required')
            return {'actor':record['name'],'role':record.get('role','reviewer'),'authenticated':True}
        return {'actor':actor,'role':'approver' if os.environ.get('FUSION_LOCAL_REVIEW')=='1' else 'reviewer','authenticated':False}
    @app.get('/api/ledger/decisions')
    def listed(q:str='',project:str='',status:str='',limit:int=200,offset:int=0):return ledger.list(q,project,status,max(1,min(limit,500)),max(0,offset))
    @app.post('/api/ledger/decisions',status_code=201)
    def create(p:DecisionCreate,actor:str='Local reviewer',x_fusion_token:str|None=Header(default=None)):
        who=identity(x_fusion_token,actor);return ledger.create(p,who['actor'])
    @app.get('/api/ledger/decisions/{did}')
    def get(did:str):
        with ledger.db() as c:return ledger.get(c,did)
    @app.post('/api/ledger/decisions/{did}/events',status_code=201)
    def event(did:str,p:EventCreate,x_fusion_token:str|None=Header(default=None)):return ledger.event(did,p,identity(x_fusion_token,p.actor))
    @app.get('/api/ledger/precedents')
    def precedents(q:str,project:str='',limit:int=8):
        ds=ledger.list(q,project,limit=500)['decisions']
        ds.sort(key=lambda d:(d['evidence_validity']=='current',d['status']=='Approved',any(e['event_type']=='outcome' for e in d['history'])),reverse=True)
        return {'results':ds[:max(1,min(limit,25))],'warning':'Contextual precedents. Check applicability, outcomes and access rights before reuse.'}
    @app.get('/api/ledger/sources')
    def sources(project:str):
        with ledger.db() as c:return [dict(r) for r in c.execute('SELECT * FROM ledger_sources WHERE project=?',(project,))]
    @app.post('/api/ledger/sources')
    def source(p:SourceUpdate,x_fusion_token:str|None=Header(default=None)):return ledger.update_source(p,identity(x_fusion_token)['actor'])
    @app.post('/api/ledger/context/{issue_id}')
    def context(issue_id:str,project:str='Snowdon Towers (prototype)',x_fusion_token:str|None=Header(default=None)):
        who=identity(x_fusion_token)
        issue=next((i for i in (issue_provider() if issue_provider else []) if i['id']==issue_id),None)
        if issue is None:raise HTTPException(404,'Issue not found')
        snapshot={k:v for k,v in issue.items() if k not in ('status','comment')};version=digest(snapshot);key='issue:'+issue_id
        with ledger.db() as c:row=c.execute('SELECT revision FROM ledger_sources WHERE project=? AND source_key=?',(project,key)).fetchone()
        ledger.update_source(SourceUpdate(project=project,source_key=key,revision=version,expected_revision=row['revision'] if row else None),who['actor'])
        refs=[{'kind':'coordination finding','id':issue_id,'source_key':key,'source_version':version,'provenance':'calculated','description':'Immutable finding fingerprint; source model revision must be attached separately.'}]
        refs.extend(reconcile(project,who['actor'])['references'])
        return {'title':'Review '+issue_id,'project':project,'issue_id':issue_id,'element_ids':[issue[k] for k in ('mepId','fabricId') if issue.get(k)],'context':json.dumps(snapshot,ensure_ascii=False,indent=2),'references':refs}

    def reconcile(project,actor):
        references=[]
        files=[('mesh-manifest',Path(root)/'frontend'/'public'/'data'/'mesh_manifest.json')]
        for key,path in files:
            if not path.exists():continue
            data=json.loads(path.read_text(encoding='utf-8'));revision=digest(data)
            with ledger.db() as c:row=c.execute('SELECT revision FROM ledger_sources WHERE project=? AND source_key=?',(project,key)).fetchone()
            if not row or row['revision']!=revision:
                ledger.update_source(SourceUpdate(project=project,source_key=key,revision=revision,expected_revision=row['revision'] if row else None),actor)
            references.append({'kind':'model','id':key,'source_key':key,'source_version':revision,'provenance':'extracted','description':'Fingerprint of local mesh manifest. Native source revisions remain as supplied by the exporter; fingerprint does not prove complete federation coverage.'})
        return {'references':references,'available':bool(references)}
    @app.post('/api/ledger/reconcile')
    def reconcile_api(project:str,x_fusion_token:str|None=Header(default=None)):
        who=identity(x_fusion_token);return reconcile(project,who['actor'])

    app.state.reconcile_sources = reconcile
