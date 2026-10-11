"""Saved weighted maturity snapshots and provenance-aware Revit view/sheet links."""
import json, sqlite3, hashlib
from datetime import datetime,timezone
from pathlib import Path
from collections import defaultdict
from fastapi import HTTPException
from pydantic import BaseModel,Field

def register_routes(app,root,qa_rule_db,qa_conn,rule_failed,read):
 def db():
  c=qa_rule_db()
  c.execute("""CREATE TABLE IF NOT EXISTS maturity_runs(id INTEGER PRIMARY KEY AUTOINCREMENT,rule_set_id TEXT NOT NULL,model_version TEXT NOT NULL,created_at TEXT NOT NULL,weighted_pass REAL NOT NULL,weighted_total REAL NOT NULL,score REAL,objects_checked INTEGER NOT NULL,failed_count INTEGER NOT NULL,details TEXT NOT NULL)""")
  c.execute("""CREATE TABLE IF NOT EXISTS sheet_links(model_key TEXT NOT NULL,element_id TEXT NOT NULL,view_id TEXT NOT NULL,sheet_id TEXT NOT NULL,sheet_number TEXT,sheet_name TEXT,view_name TEXT,document_title TEXT,source TEXT NOT NULL,PRIMARY KEY(model_key,element_id,view_id,sheet_id))""")
  c.execute("""CREATE TABLE IF NOT EXISTS sheet_imports(model_key TEXT PRIMARY KEY,created_at TEXT,document_title TEXT,records INTEGER,source_file TEXT)""")
  return c
 class ImportSheets(BaseModel):
  model_key:str=Field(min_length=1,max_length=128)
  document_title:str=''
  source_file:str='Revit API export'
  associations:list[dict]=Field(max_length=500000)
 @app.post('/api/revit/sheet-links/import')
 def import_sheets(payload:ImportSheets):
  dedup={}
  for x in payload.associations:
   element=str(x.get('element_id') or '')
   view=str(x.get('view_id') or '')
   sheet=str(x.get('sheet_id') or '')
   if not element or not view or not sheet:continue
   key=(payload.model_key,element,view,sheet)
   dedup[key]=(payload.model_key,element,view,sheet,str(x.get('sheet_number','')),str(x.get('sheet_name','')),str(x.get('view_name','')),payload.document_title,'REVIT_VIEW_COLLECTOR')
  stamp=datetime.now(timezone.utc).isoformat()
  with db() as c:
   c.execute('DELETE FROM sheet_links WHERE model_key=?',(payload.model_key,))
   c.executemany('INSERT INTO sheet_links VALUES(?,?,?,?,?,?,?,?,?)',list(dedup.values()))
   c.execute('INSERT INTO sheet_imports VALUES(?,?,?,?,?) ON CONFLICT(model_key) DO UPDATE SET created_at=excluded.created_at,document_title=excluded.document_title,records=excluded.records,source_file=excluded.source_file',(payload.model_key,stamp,payload.document_title,len(dedup),payload.source_file))
  return {'model_key':payload.model_key,'associations':len(dedup),'status':'IMPORTED','caution':'Revit view collector means candidate view membership, not guaranteed printed visibility. Linked models are not included.'}
 @app.get('/api/revit/sheet-links/status')
 def sheet_status():
  with db() as c:return [dict(r) for r in c.execute('SELECT * FROM sheet_imports ORDER BY created_at DESC')]
 @app.get('/api/revit/sheet-links/element/{element_id:path}')
 def element_sheet_links(element_id:str):
  clean=element_id.split('_t',1)[0]
  with db() as c:
   links=[dict(x) for x in c.execute('SELECT * FROM sheet_links WHERE element_id=? ORDER BY sheet_number LIMIT 250',(clean,))]
  return {'element_id':clean,'links':links,'confidence':'REVIT_VIEW_MEMBERSHIP_CANDIDATE','caution':'View collector may include occluded/cropped elements; verify actual printed drawing.'}
 @app.get('/api/qa/maturity/history/{rule_set_id}')
 def history(rule_set_id:str):
  with db() as c:
   return [dict(r) for r in c.execute('SELECT id,rule_set_id,model_version,created_at,score,objects_checked,failed_count FROM maturity_runs WHERE rule_set_id=? ORDER BY id DESC LIMIT 40',(rule_set_id,))]
 @app.post('/api/qa/maturity/snapshot/{rule_set_id}')
 def snapshot(rule_set_id:str,model_version:str=''):
  with db() as c:r=c.execute('SELECT * FROM qa_rule_sets WHERE id=?',(rule_set_id,)).fetchone()
  if not r:raise HTTPException(404,'Rule set not found')
  rules=json.loads(r['rules']);passed=total=0.;n=0;failed=set();source_scores=defaultdict(lambda:[0.,0.,0]);digest=hashlib.sha256()
  with qa_conn() as c:
   for obj in c.execute('SELECT id,source,category,properties FROM objects'):
    applicable=[x for x in rules if (x['source']=='All' or x['source']==obj['source']) and (x['category']=='All' or x['category']==obj['category'])]
    if not applicable:continue
    digest.update(obj['id'].encode('utf-8'));digest.update(obj['properties'].encode('utf-8'))
    n+=1;props=json.loads(obj['properties'])
    for rule in applicable:
     w=max(0.1,min(20,float(rule.get('weight',1))));total+=w;source_scores[obj['source']][1]+=w
     if rule_failed(rule,props):failed.add(obj['id'])
     else:passed+=w;source_scores[obj['source']][0]+=w
    source_scores[obj['source']][2]+=1
  ver=model_version.strip() or read('metadata.json').get('version_id','unlabelled-export')
  score=round(100*passed/total,2) if total else None
  details={'by_source':[{'source':k,'score':round(100*v[0]/v[1],2) if v[1] else None,'objects':int(v[2])} for k,v in source_scores.items()],'failed_ids_sample':list(sorted(failed))[:200],'rules_count':len(rules),'source':'LOCAL_EXPORTED_PROPERTIES','model_version_requested':ver,'data_fingerprint':digest.hexdigest()}
  with db() as c:
   previous=c.execute('SELECT id,score,model_version,details FROM maturity_runs WHERE rule_set_id=? ORDER BY id DESC LIMIT 1',(rule_set_id,)).fetchone()
   cur=c.execute('INSERT INTO maturity_runs(rule_set_id,model_version,created_at,weighted_pass,weighted_total,score,objects_checked,failed_count,details) VALUES(?,?,?,?,?,?,?,?,?)',(rule_set_id,ver,datetime.now(timezone.utc).isoformat(),passed,total,score,n,len(failed),json.dumps(details)))
  previous_fingerprint=json.loads(previous['details']).get('data_fingerprint') if previous else None
  same_data=previous_fingerprint==digest.hexdigest() if previous_fingerprint else None
  delta=round(score-previous['score'],2) if previous and previous['score'] is not None and score is not None and same_data is False else None
  return {'run_id':cur.lastrowid,'score':score,'previous_score':previous['score'] if previous else None,'delta_points':delta,'same_data_as_previous':same_data,'version':ver,'previous_version':previous['model_version'] if previous else None,'objects_checked':n,'distinct_failed':len(failed),'by_source':details['by_source'],'warning':'The current local QA database is assessed as-is. A new Speckle version label does NOT refresh its properties automatically. Genuine version comparisons require a fresh version-specific property extraction.'}
