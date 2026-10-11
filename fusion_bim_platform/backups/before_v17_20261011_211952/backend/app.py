"""Fusion BIM Intelligence prototype API.
Run: uvicorn backend.app:app --reload --port 8000 from project root.
"""
import json, sqlite3
from pathlib import Path
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data'; DB=ROOT/'prototype.sqlite3'
app=FastAPI(title='Fusion BIM Intelligence — prototype')
app.add_middleware(CORSMiddleware,allow_origins=['http://localhost:5173','http://127.0.0.1:5173'],allow_methods=['*'],allow_headers=['*'])
def conn():
 c=sqlite3.connect(DB);c.row_factory=sqlite3.Row
 c.execute('CREATE TABLE IF NOT EXISTS issue_state(id TEXT PRIMARY KEY, status TEXT NOT NULL, comment TEXT NOT NULL DEFAULT "")')
 c.execute('CREATE TABLE IF NOT EXISTS activity_state(id TEXT PRIMARY KEY, start INTEGER NOT NULL, duration INTEGER NOT NULL, progress INTEGER NOT NULL)')
 return c
def read(name):return json.loads((DATA/name).read_text(encoding='utf-8'))
class IssueUpdate(BaseModel):
 status:str
 comment:str=''
class ActivityUpdate(BaseModel):
 start:int=Field(ge=0,le=520)
 duration:int=Field(ge=1,le=104)
 progress:int=Field(ge=0,le=100)
@app.get('/api/health')
def health():return {'ok':True,'representation':'Mesh assets when available; AABB fallback is explicitly labelled'}
@app.get('/api/metadata')
def metadata():return read('metadata.json')
@app.get('/api/elements')
def elements():return read('elements.json')
@app.get('/api/issues')
def issues():
 result=read('issues.json')
 with conn() as db:
  statuses={r['id']:dict(r) for r in db.execute('SELECT * FROM issue_state')}
 for i in result:
  if i['id'] in statuses:i.update({k:statuses[i['id']][k] for k in ('status','comment')})
 return result
@app.put('/api/issues/{issue_id}')
def update_issue(issue_id:str,payload:IssueUpdate):
 if payload.status not in {'New','Under review','Accepted penetration','Action required','Resolved'}:raise HTTPException(400,'Unknown status')
 with conn() as db:
  db.execute('INSERT INTO issue_state(id,status,comment) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,comment=excluded.comment',(issue_id,payload.status,payload.comment))
 return {'id':issue_id,**payload.model_dump()}
@app.get('/api/programme')
def programme():
 result=read('programme.json')
 with conn() as db:
  overrides={r['id']:dict(r) for r in db.execute('SELECT * FROM activity_state')}
 for a in result['activities']:
  if a['id'] in overrides:a.update({k:overrides[a['id']][k] for k in ('start','duration','progress')})
 return result
@app.put('/api/activities/{activity_id}')
def update_activity(activity_id:str,payload:ActivityUpdate):
 with conn() as db:
  db.execute('INSERT INTO activity_state(id,start,duration,progress) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET start=excluded.start,duration=excluded.duration,progress=excluded.progress',(activity_id,payload.start,payload.duration,payload.progress))
 return {'id':activity_id,**payload.model_dump()}


# Mesh export is an explicitly user-triggered, single-job local operation.
# Never accept arbitrary executable paths or user-supplied command arguments.
import subprocess, sys, threading, time
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_mesh_lock = threading.Lock()
_mesh_job = {'state': 'idle', 'message': 'Ready to check Speckle for updates', 'log': [], 'started_at': None, 'finished_at': None}

def _job_snapshot():
 with _mesh_lock:
  return dict(_mesh_job, log=list(_mesh_job['log']))

def _run_mesh_export():
 cmd=[sys.executable, '-u', str(ROOT/'speckle_sync.py')]
 try:
  with subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1) as proc:
   for line in proc.stdout:
    line=line.rstrip()
    if not line:continue
    with _mesh_lock:
     if line.startswith('SYNC_RESULT '):
      try:_mesh_job['result']=json.loads(line[len('SYNC_RESULT '):])
      except ValueError:pass
     _mesh_job['log'].append(line[:500])
     _mesh_job['log']=_mesh_job['log'][-30:]
     _mesh_job['message']=line[:240]
   code=proc.wait()
  if code==0 and hasattr(app.state,'reconcile_sources'):
   try:
    with app.state.decision_ledger.db() as db:
     projects=[r[0] for r in db.execute("SELECT DISTINCT project FROM ledger_sources WHERE source_key='mesh-manifest'")]
    for project_name in projects:app.state.reconcile_sources(project_name,'Speckle synchronisation')
   except Exception as exc:
    with _mesh_lock:_mesh_job['log'].append('Evidence reconciliation requires attention: '+str(exc)[:200])
  with _mesh_lock:
   _mesh_job['state']=('unchanged' if (_mesh_job.get('result') or {}).get('status')=='UNCHANGED' else 'changed') if code==0 else 'failed'
   _mesh_job['finished_at']=time.time()
   _mesh_job['message']=(_mesh_job.get('result') or {}).get('message','Speckle sync completed') if code==0 else f'Speckle sync failed (exit code {code}). See log below.'
 except Exception as exc:
  with _mesh_lock:
   _mesh_job['state']='failed';_mesh_job['message']=str(exc);_mesh_job['finished_at']=time.time()

@app.post('/api/mesh-sync', status_code=202)
def start_mesh_sync():
 with _mesh_lock:
  if _mesh_job['state']=='running':raise HTTPException(409, 'Mesh export already running')
  _mesh_job.update(state='running', message='Connecting to Speckle…', log=[], result=None, started_at=time.time(), finished_at=None)
 threading.Thread(target=_run_mesh_export, daemon=True).start()
 return _job_snapshot()

@app.get('/api/mesh-sync')
def mesh_sync_status():return _job_snapshot()

@app.get('/api/mesh-manifest')
def mesh_manifest():
 file=ROOT/'frontend'/'public'/'data'/'mesh_manifest.json'
 if not file.exists():return {'status':'NOT_EXPORTED','chunks':[]}
 return json.loads(file.read_text(encoding='utf-8'))

# Expose model assets from the same backend origin, bypassing Vite's static file cache.
app.mount('/api/model-assets', StaticFiles(directory=str(ROOT/'frontend'/'public'/'data')), name='model-assets')

@app.post('/api/demo/tokamak-change')
def demo_tokamak_change():
    # Explicitly simulated, does not modify Speckle, Revit, or baseline models.
    return {'status':'DEMO_CHANGE','synthetic':True,'message':'SIMULATION ONLY: Tokamak equipment envelope revised. Check structural openings, access route, installation sequencing, work packages and TIDP drawings. No actual Speckle change has been detected by this simulation.','changedElements':1,'affected':{'activitiesCount':2,'workPackagesCount':2,'drawingsCount':3,'activityIds':['DEMO-TOK-01','DEMO-TOK-02'],'workPackageIds':['DEMO-WP-TOK-01','DEMO-WP-TOK-02'],'drawingIds':['DEMO-TIDP-TOK-001','DEMO-TIDP-STR-002','DEMO-TIDP-MEP-003']},'requiresReview':True}

# Model QA: query authentic exported Speckle/Revit parameters. Read-only.
from collections import Counter
from functools import lru_cache
QA_DB = ROOT / 'qa_properties.sqlite3'

def qa_conn():
 if not QA_DB.exists(): raise HTTPException(503,'QA properties database missing; install complete v0.9 package')
 c=sqlite3.connect(f'file:{QA_DB}?mode=ro',uri=True);c.row_factory=sqlite3.Row;return c

class QARule(BaseModel):
 source: str = 'All'
 category: str = 'All'
 parameter: str
 operator: str = 'missing_or_blank'
 value: str = ''
 limit: int = Field(default=250,ge=1,le=2000)

@app.get('/api/qa/catalog')
def qa_catalog(source:str='All',category:str='All'):
 with qa_conn() as db:
  where=[];args=[]
  if source!='All':where.append('source=?');args.append(source)
  if category!='All':where.append('category=?');args.append(category)
  condition=' WHERE '+' AND '.join(where) if where else ''
  rows=db.execute('SELECT category,source,properties FROM objects'+condition,args).fetchall()
  sources=[r[0] for r in db.execute('SELECT DISTINCT source FROM objects ORDER BY source')]
  categories=[r[0] for r in db.execute('SELECT DISTINCT category FROM objects'+(' WHERE source=?' if source!='All' else '')+' ORDER BY category',([source] if source!='All' else []))]
 fields=Counter();filled=Counter();blank=Counter()
 for r in rows:
  props=json.loads(r['properties'])
  for k,v in props.items():
   fields[k]+=1
   if v is None or (isinstance(v,str) and not v.strip()):blank[k]+=1
   else:filled[k]+=1
 return {'total':len(rows),'sources':sources,'categories':categories,'fields':[{'name':k,'present':n,'filled':filled[k],'blank':blank[k],'missing':len(rows)-n,'completeness_pct':round(100*filled[k]/len(rows),1) if rows else 0} for k,n in fields.most_common()]}

@app.post('/api/qa/check')
def qa_check(rule:QARule):
 operators={'missing_or_blank','missing','blank','equals','not_equals','contains','not_contains','greater_than','less_than'}
 if rule.operator not in operators:raise HTTPException(400,'Unsupported operator')
 with qa_conn() as db:
  where=[];args=[]
  if rule.source!='All':where.append('source=?');args.append(rule.source)
  if rule.category!='All':where.append('category=?');args.append(rule.category)
  rows=db.execute('SELECT id,source,category,level,name,properties FROM objects'+(' WHERE '+' AND '.join(where) if where else ''),args).fetchall()
 hits=[];sample=[];present=0;filled=0;failure_count=0
 for r in rows:
  props=json.loads(r['properties']);v=props.get(rule.parameter);has=rule.parameter in props
  isblank=v is None or (isinstance(v,str) and not v.strip())
  if has:present+=1
  if has and not isblank:filled+=1
  sv='' if v is None else str(v)
  op=rule.operator
  if op=='missing_or_blank':failed=not has or isblank
  elif op=='missing':failed=not has
  elif op=='blank':failed=has and isblank
  elif op=='equals':failed=sv.casefold()!=rule.value.casefold()
  elif op=='not_equals':failed=sv.casefold()==rule.value.casefold()
  elif op=='contains':failed=rule.value.casefold() not in sv.casefold()
  elif op=='not_contains':failed=rule.value.casefold() in sv.casefold()
  else:
   try:failed=(float(sv)<=float(rule.value) if op=='greater_than' else float(sv)>=float(rule.value))
   except (TypeError,ValueError):failed=True
  if failed:
   failure_count+=1
   if len(hits)<rule.limit:hits.append({'id':r['id'],'name':r['name'],'source':r['source'],'category':r['category'],'level':r['level'],'value':v,'present':has})
 return {'total':len(rows),'present':present,'filled':filled,'completeness_pct':round(100*filled/len(rows),1) if rows else 0,'failed':failure_count,'results':hits,'truncated':failure_count>len(hits),'provenance':'Actual Speckle-exported Revit properties; rule results are review candidates'}


# v0.10: reusable QA requirements and traceable maturity assessment.
from typing import List
from datetime import datetime, timezone

def _qa_rule_db():
 c=sqlite3.connect(ROOT/'prototype.sqlite3')
 c.row_factory=sqlite3.Row
 c.execute("CREATE TABLE IF NOT EXISTS qa_rule_sets(id TEXT PRIMARY KEY, name TEXT NOT NULL, stage TEXT NOT NULL, description TEXT NOT NULL, rules TEXT NOT NULL, updated_at TEXT NOT NULL)")
 return c

class SavedRule(BaseModel):
 name: str
 source: str = 'All'
 category: str = 'All'
 parameter: str
 operator: str = 'missing_or_blank'
 value: str = ''
 weight: float = Field(default=1.0,ge=0.1,le=20)

class SavedRuleSet(BaseModel):
 id: str = ''
 name: str
 stage: str = 'Stage 4'
 description: str = ''
 rules: List[SavedRule] = Field(min_length=1,max_length=40)

@app.get('/api/qa/rule-sets')
def qa_rule_sets():
 with _qa_rule_db() as db:
  return [dict(r)|{'rules':json.loads(r['rules'])} for r in db.execute('SELECT * FROM qa_rule_sets ORDER BY updated_at DESC')]

@app.post('/api/qa/rule-sets')
def save_qa_rule_set(payload:SavedRuleSet):
 import uuid
 rid=payload.id or uuid.uuid4().hex[:12]
 if not payload.name.strip():raise HTTPException(400,'Rule-set name required')
 operators={'missing_or_blank','missing','blank','equals','not_equals','contains','not_contains','greater_than','less_than'}
 if any(x.operator not in operators or not x.parameter.strip() for x in payload.rules):raise HTTPException(400,'Invalid QA rule')
 stamp=datetime.now(timezone.utc).isoformat()
 with _qa_rule_db() as db:
  db.execute('INSERT INTO qa_rule_sets(id,name,stage,description,rules,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,stage=excluded.stage,description=excluded.description,rules=excluded.rules,updated_at=excluded.updated_at',(rid,payload.name.strip(),payload.stage,payload.description,json.dumps([x.model_dump() for x in payload.rules]),stamp))
 return {'id':rid,'updated_at':stamp}

@app.delete('/api/qa/rule-sets/{rule_set_id}')
def delete_qa_rule_set(rule_set_id:str):
 with _qa_rule_db() as db:
  count=db.execute('DELETE FROM qa_rule_sets WHERE id=?',(rule_set_id,)).rowcount
 if not count:raise HTTPException(404,'Rule set not found')
 return {'deleted':True}

def _rule_failed(rule,props):
 name=rule['parameter'];op=rule['operator'];value=rule.get('value','')
 has=name in props;v=props.get(name);blank=v is None or isinstance(v,str) and not v.strip();txt='' if v is None else str(v)
 if op=='missing_or_blank':return not has or blank
 if op=='missing':return not has
 if op=='blank':return has and blank
 if op=='equals':return txt.casefold()!=value.casefold()
 if op=='not_equals':return txt.casefold()==value.casefold()
 if op=='contains':return value.casefold() not in txt.casefold()
 if op=='not_contains':return value.casefold() in txt.casefold()
 try:return float(txt)<=float(value) if op=='greater_than' else float(txt)>=float(value)
 except (ValueError,TypeError):return True

@app.post('/api/qa/assess/{rule_set_id}')
def assess_qa_rule_set(rule_set_id:str):
 with _qa_rule_db() as db: saved=db.execute('SELECT * FROM qa_rule_sets WHERE id=?',(rule_set_id,)).fetchone()
 if not saved:raise HTTPException(404,'Rule set not found')
 rules=json.loads(saved['rules'])
 checks=[{'name':r.get('name') or r['parameter'],'parameter':r['parameter'],'source':r['source'],'category':r['category'],'checked':0,'failed':0,'examples':[]} for r in rules]
 failed_ids=set();unique_checked=set();passed_checks=0;total_checks=0;weighted_passed=0.0;weighted_total=0.0
 with qa_conn() as db:
  for row in db.execute('SELECT id,name,source,category,level,properties FROM objects'):
   applicable=[i for i,r in enumerate(rules) if (r['source']=='All' or r['source']==row['source']) and (r['category']=='All' or r['category']==row['category'])]
   if not applicable:continue
   props=json.loads(row['properties']);unique_checked.add(row['id'])
   for i in applicable:
    rule=rules[i];check=checks[i];check['checked']+=1;total_checks+=1;weighted_total+=rule.get('weight',1.0)
    if _rule_failed(rule,props):
     check['failed']+=1;failed_ids.add(row['id'])
     if len(check['examples'])<25:check['examples'].append({'id':row['id'],'name':row['name'],'category':row['category'],'level':row['level'],'value':props.get(rule['parameter'])})
    else:passed_checks+=1;weighted_passed+=rule.get('weight',1.0)
 programme=read('programme.json');plan=read('delivery_plan.json')
 # Exported QA IDs are base Revit UniqueIds; viewer assignment IDs append _t<transform>.
 base_failed=set(failed_ids)
 linked=[]
 for act_id,ids in programme['assignments'].items():
  count=sum(1 for id in ids if id.split('_t',1)[0] in base_failed)
  if count:linked.append({'activityId':act_id,'failedElements':count})
 linked_by_id={a['activityId']:a['failedElements'] for a in linked}
 packages=[{'id':w['id'],'name':w['name'],'owner':w.get('owner'),'activityIds':w['activityIds'],'failedElements':sum(linked_by_id.get(a,0) for a in w['activityIds'])} for w in plan['workPackages'] if any(a in linked_by_id for a in w['activityIds'])]
 package_ids={x['id'] for x in packages}
 drawings=[{'id':d['id'],'title':d['title'],'workPackageId':d['workPackageId'],'status':d.get('status'),'targetWeek':d.get('targetWeek'),'reason':'Linked by fictional TIDP work package; appearance on sheet unverified'} for d in plan['deliverables'] if d['workPackageId'] in package_ids]
 return {'ruleSet':{'id':saved['id'],'name':saved['name'],'stage':saved['stage']},'objectsChecked':len(unique_checked),'checkInstances':total_checks,'passedChecks':passed_checks,'failedCheckInstances':total_checks-passed_checks,'distinctFailedElements':len(failed_ids),'maturityPct':round(100*weighted_passed/weighted_total,1) if weighted_total else None,'rules':checks,'impacts':{'activities':linked[:100],'activityCount':len(linked),'packages':packages[:100],'packageCount':len(packages),'drawings':drawings[:150],'drawingCount':len(drawings)},'cautions':['Rule-based assessment of exported Revit properties, not certified model maturity','Work packages, programme dates and TIDP deliverables are fictional','Drawing association is inferred through a fictional work package, not verified sheet visibility','Saved rules are stored locally in prototype.sqlite3','Geometry-only revisions and unrecognised Speckle relationships are outside this assessment']}

# v0.11: historical maturity and Revit sheet associations
from backend.delivery_intelligence import register_routes
register_routes(app,ROOT,_qa_rule_db,qa_conn,_rule_failed,read)

# V12: auditable deterministic graph + CPM analysis. Model sources remain unchanged.
from .graph_cpm import neighbourhood as graph_neighbourhood, cpm as calculate_cpm
from .coordination_intelligence import groups as coordination_groups
from fastapi import Query

@app.get('/api/graph')
def graph_all():
    return read('graph_demo.json')

@app.get('/api/graph/neighbourhood/{node_id}')
def graph_near(node_id:str, depth:int=Query(2,ge=0,le=5)):
    try:return graph_neighbourhood(read('graph_demo.json'),node_id,depth)
    except ValueError as exc:raise HTTPException(status_code=404,detail=str(exc))

@app.get('/api/coordination/groups')
def grouped_coordination():return coordination_groups(issues())

@app.get('/api/programme/cpm')
def programme_cpm():
    # The baseline carries no actual dependency edges. Only explicit demo dependencies
    # are added here, not written back into the user programme.
    p=programme();act=[dict(a) for a in p['activities']]
    if all(not a.get('predecessors') for a in act):
        raise HTTPException(422,'No explicit dependencies. Import an explicit demonstration or project programme before CPM analysis.')
    demo=bool(p.get('synthetic', False)); sample=[]
    try:result=calculate_cpm(act)
    except ValueError as exc:raise HTTPException(422,str(exc))
    result['syntheticDependencies']=demo
    result['demoDependencyActivityIds']=[a['id'] for a in sample] if demo else []
    return result

# v0.13: coordination evidence, reviewer audit, optional AI, BCF export and scenario CPM
from .coordination_actions import register as register_coordination_actions
register_coordination_actions(app,read,conn,issues,programme,calculate_cpm,coordination_groups,ROOT)


# Spatial intelligence (NetworkX): explicit extracted evidence or labelled synthetic demonstration
from .spatial_intelligence import analyse as spatial_analyse, import_graph as spatial_import
from fastapi import Body
@app.get('/api/spatial/analysis')
def spatial_analysis(origin:str='',destination:str='',blocked:str=''):
    return spatial_analyse([x for x in blocked.split(',') if x],origin or None,destination or None)
@app.post('/api/spatial/import')
def spatial_import_api(payload:dict=Body(...)):
    try:return spatial_import(payload)
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc))

# v0.16 - append-only design decision ledger
from .decision_ledger import register as register_decision_ledger
register_decision_ledger(app,ROOT,issues)

# v17: persistent knowledge graph and revision-scoped circulation analysis.
from .knowledge_graph import register as register_knowledge_graph
from .circulation import register as register_circulation
register_knowledge_graph(app,ROOT)
register_circulation(app,ROOT)
