import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.decision_ledger import register, Ledger, DecisionCreate, SourceUpdate
from backend.knowledge_graph import register as graph_register, GraphSnapshot
from backend.circulation import register as circulation_register,SpatialModel,Scenario,analyse,topologic_graph
from backend.demo_network import MODEL

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setenv('FUSION_REVIEWERS_JSON',json.dumps({'test-token':{'name':'Test approver','role':'approver'},'review-token':{'name':'Test reviewer','role':'reviewer'}}))
    monkeypatch.delenv('FUSION_NEO4J_URI',raising=False)
    app=FastAPI();register(app,tmp_path,lambda:[{'id':'ISS-1','mepId':'P-1','fabricId':'W-1','type':'AABB candidate'}]);graph_register(app,tmp_path);circulation_register(app,tmp_path)
    return TestClient(app,headers={'X-Fusion-Token':'test-token'})

def proposal(client):
    client.post('/api/ledger/sources',json={'project':'Test','source_key':'model','revision':'R1'})
    r=client.post('/api/ledger/decisions',json={'title':'Penetration design','project':'Test','context':'Pipe intersects the wall','decision':'Provide approved sleeve','rationale':'Maintain wall integrity','options':['Reroute pipe','Provide sleeve'],'acceptance_criteria':['Detail reviewed'],'references':[{'kind':'model','id':'M1','source_key':'model','source_version':'R1','provenance':'human-confirmed'}]})
    assert r.status_code==201,r.text
    return r.json()['id']

def event(client,did,version,status,kind='review',token=None,**extra):
    headers={'X-Fusion-Token':token} if token else {}
    return client.post('/api/ledger/decisions/'+did+'/events',headers=headers,json={'expected_version':version,'event_type':kind,'status':status,'actor':'Forged client name','note':'Reviewed against the evidence',**extra})

def test_review_approval_stale_revalidation(client):
    did=proposal(client)
    assert event(client,did,0,'Approved','approval').status_code==422
    assert event(client,did,0,'Under review').status_code==201
    d=event(client,did,1,'Approved','approval').json()
    assert d['history'][-1]['actor']=='Test approver'
    assert d['evidence_validity']=='current'
    r=client.post('/api/ledger/sources',json={'project':'Test','source_key':'model','revision':'R2','expected_revision':'R1'})
    assert r.status_code==200
    d=client.get('/api/ledger/decisions/'+did).json()
    assert d['status']=='Approved' and d['evidence_validity']=='stale'
    assert event(client,did,2,'Under review').status_code==201
    assert event(client,did,3,'Approved','approval').status_code==422
    refs=d['references'];refs[0]['source_version']='R2'
    assert event(client,did,3,'Under review','evidence',references=refs).status_code==201
    assert event(client,did,4,'Approved','approval').status_code==201

def test_concurrent_review_conflict(client):
    did=proposal(client)
    assert event(client,did,0,'Under review').status_code==201
    assert event(client,did,0,'Rejected').status_code==409

def test_reviewer_cannot_approve(client):
    did=proposal(client);event(client,did,0,'Under review')
    assert event(client,did,1,'Approved','approval',token='review-token').status_code==403

def test_forged_identity_and_missing_token(client):
    did=proposal(client)
    assert event(client,did,0,'Under review',token='bad-token').status_code==401

def test_sources_compare_and_swap(client):
    proposal(client)
    assert client.post('/api/ledger/sources',json={'project':'Test','source_key':'model','revision':'R2'}).status_code==409

def test_supersession_is_terminal(client):
    did=proposal(client);replacement=proposal(client)
    event(client,did,0,'Under review');event(client,did,1,'Approved','approval')
    assert event(client,did,2,'Superseded','supersession',superseded_by=replacement).status_code==201
    assert event(client,did,3,'Under review').status_code==409

def test_issue_context_fingerprint(client):
    r=client.post('/api/ledger/context/ISS-1');assert r.status_code==200
    d=r.json();assert d['element_ids']==['P-1','W-1'] and d['references'][0]['source_version']
    assert 'AABB candidate' in d['context']

def test_legacy_migration_preserves_history(tmp_path):
    import sqlite3
    path=tmp_path/'decision_ledger.sqlite3'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE decisions(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,creator TEXT NOT NULL,payload TEXT NOT NULL)')
        c.execute('INSERT INTO decisions VALUES(?,?,?,?)',('OLD','2020','User',json.dumps({'title':'Legacy','project':'Test','status':'Approved','references':[{'kind':'model','id':'old'}]})))
    ledger=Ledger(tmp_path)
    with ledger.db() as c:d=ledger.get(c,'OLD')
    assert d['status']=='Approved' and d['evidence_validity']=='incomplete'

def test_graph_snapshot_immutability_and_isolation(client):
    p={'project':'Test','revision':'R1','nodes':[{'id':'A','kind':'Element','label':'A'},{'id':'B','kind':'Drawing','label':'B'}],'edges':[{'id':'AB','source':'A','target':'B','kind':'APPEARS_IN','provenance':'human-confirmed','reason':'Verified view reference','source_key':'model','source_version':'R1'}]}
    assert client.post('/api/knowledge/import',json=p).status_code==200
    assert client.get('/api/knowledge/neighbourhood',params={'project':'Test','revision':'R1','node_id':'A'}).json()['edges'][0]['reason']=='Verified view reference'
    p['nodes'][0]['label']='Changed'
    assert client.post('/api/knowledge/import',json=p).status_code==409
    assert client.get('/api/knowledge/neighbourhood',params={'project':'Other','revision':'R1','node_id':'A'}).status_code==404

def test_graph_rejects_dangling_edge(client):
    assert client.post('/api/knowledge/import',json={'project':'T','revision':'R','nodes':[],'edges':[{'id':'x','source':'a','target':'b','kind':'x','provenance':'inferred','reason':'Invalid edge','source_key':'m','source_version':'r'}]}).status_code==422

def test_decision_graph_links_evidence(client):
    did=proposal(client)
    r=client.post('/api/knowledge/decisions',params={'project':'Test'});assert r.status_code==200,r.text
    data=client.get('/api/knowledge/neighbourhood',params={'project':'Test','revision':r.json()['revision'],'node_id':did}).json()
    assert any(e['kind']=='SUPPORTED_BY' for e in data['edges'])

def test_accessible_journey_lost_general_reroutes():
    model=SpatialModel.model_validate(MODEL)
    d=analyse(model,Scenario(project=model.project,revision=model.revision,blocked_portals=['D-001']))
    general,accessible=d['journeys']
    assert general['changed'] and not general['lost']
    assert accessible['lost']
    assert general['after'][0]['distance_m']==38

def test_parallel_doors_and_one_way():
    data=json.loads(json.dumps(MODEL));data['portals'].append(dict(data['portals'][0],id='D-PARALLEL'))
    model=SpatialModel.model_validate(data)
    d=analyse(model,Scenario(project=model.project,revision=model.revision,blocked_portals=['D-001']))
    assert not d['journeys'][1]['lost']
    data={'project':'T','revision':'1','provenance':'synthetic','distance_basis':'synthetic','spaces':[{'id':'A','name':'A','xyz':[0,0,0],'exit':True},{'id':'B','name':'B','xyz':[1,0,0]}],'portals':[{'id':'p','source':'A','target':'B','distance_m':1,'bidirectional':False}],'journeys':[{'id':'j','origin':'B','destination':'A'}]}
    d=analyse(SpatialModel.model_validate(data),Scenario(project='T',revision='1'))
    assert not d['journeys'][0]['after']

def test_unknown_portal_rejected():
    from fastapi import HTTPException
    with pytest.raises(HTTPException):analyse(SpatialModel.model_validate(MODEL),Scenario(project='T',revision='1',blocked_portals=['TYPO']))

def test_topologic_kernel():
    result=topologic_graph(SpatialModel.model_validate(MODEL))
    assert result['vertices']==5 and result['edges']==5 and not result['skipped_portals']

def test_spatial_context_reproduces_saved_run(client):
    assert client.post('/api/circulation/import',json=MODEL).status_code==200
    scenario={'project':MODEL['project'],'revision':MODEL['revision'],'blocked_portals':['D-001']}
    r=client.post('/api/circulation/decision-context',json=scenario);assert r.status_code==200,r.text
    ref=next(x for x in r.json()['references'] if x['kind']=='analysis')
    assert client.get('/api/circulation/runs/'+ref['id']).json()['summary']['lost_journeys']==1
    assert client.post('/api/circulation/graph',json=scenario).status_code==200

def test_width_unknown_excluded():
    data=json.loads(json.dumps(MODEL));data['portals'][0]['width_m']=None
    d=analyse(SpatialModel.model_validate(data),Scenario(project='T',revision='1',minimum_width_m=1))
    assert any(p['id']=='D-001' for p in d['excluded_portals'])

def test_spatial_immutable(client):
    client.post('/api/circulation/import',json=MODEL)
    p=json.loads(json.dumps(MODEL));p['spaces'][0]['occupants']=99
    assert client.post('/api/circulation/import',json=p).status_code==409

def test_fulltext_search_includes_outcomes(client):
    did=proposal(client)
    assert event(client,did,0,None,'outcome',note='Observation: sleeve inspection revealed delamination').status_code==201
    result=client.get('/api/ledger/decisions',params={'q':'delamination','project':'Test'}).json()
    assert result['total']==1 and result['decisions'][0]['id']==did

def test_weighted_maturity_uses_rule_weights(tmp_path):
    # Execute the actual assessment function independently of unavailable v15 modules.
    import ast,sqlite3
    from pathlib import Path
    tree=ast.parse((Path(__file__).parents[1]/'backend'/'app.py').read_text())
    functions=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('_rule_failed','assess_qa_rule_set')]
    for node in functions:node.decorator_list=[]
    saved=sqlite3.connect(':memory:');saved.row_factory=sqlite3.Row
    saved.execute('CREATE TABLE qa_rule_sets(id TEXT,name TEXT,stage TEXT,rules TEXT)')
    rules=[{'name':'Critical','source':'All','category':'All','parameter':'critical','operator':'equals','value':'yes','weight':3},{'name':'Minor','source':'All','category':'All','parameter':'minor','operator':'equals','value':'yes','weight':1}]
    saved.execute('INSERT INTO qa_rule_sets VALUES(?,?,?,?)',('rules','Rules','4',json.dumps(rules)));saved.commit()
    props=sqlite3.connect(':memory:');props.row_factory=sqlite3.Row
    props.execute('CREATE TABLE objects(id TEXT,name TEXT,source TEXT,category TEXT,level TEXT,properties TEXT)')
    props.execute('INSERT INTO objects VALUES(?,?,?,?,?,?)',('A','A','Arch','Wall','1',json.dumps({'critical':'no','minor':'yes'})));props.commit()
    env={'_qa_rule_db':lambda:saved,'qa_conn':lambda:props,'json':json,'read':lambda name:{'assignments':{}} if name=='programme.json' else {'workPackages':[],'deliverables':[]}}
    exec(compile(ast.fix_missing_locations(ast.Module(body=functions,type_ignores=[])),'assessment','exec'),env)
    assert env['assess_qa_rule_set']('rules')['maturityPct']==25.0
