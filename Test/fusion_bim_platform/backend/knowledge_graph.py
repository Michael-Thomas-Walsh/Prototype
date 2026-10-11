"""Immutable project graph snapshots, with a persistent Neo4j projection.
SQLite holds import manifests. When Neo4j is configured, reads use Neo4j;
an unavailable graph database is reported, never silently replaced.
"""
import json, os, sqlite3, hashlib
from contextlib import closing
from pathlib import Path
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator, ConfigDict

class Node(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id: str=Field(min_length=1,max_length=300)
    kind: str=Field(min_length=1,max_length=80)
    label: str=Field(min_length=1,max_length=300)
    properties: dict=Field(default_factory=dict)
class Link(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id: str=Field(min_length=1,max_length=300)
    source: str
    target: str
    kind: str=Field(min_length=1,max_length=100)
    provenance: str=Field(pattern='^(extracted|calculated|human-confirmed|inferred|synthetic)$')
    reason: str=Field(min_length=5,max_length=3000)
    source_key: str=Field(min_length=1,max_length=300)
    source_version: str=Field(min_length=1,max_length=300)
class GraphSnapshot(BaseModel):
    model_config=ConfigDict(extra='forbid')
    project: str=Field(min_length=1,max_length=150)
    revision: str=Field(min_length=1,max_length=300)
    nodes: list[Node]=Field(max_length=100000)
    edges: list[Link]=Field(max_length=300000)
    @model_validator(mode='after')
    def validate_graph(self):
        ids={n.id for n in self.nodes}
        if len(ids)!=len(self.nodes):raise ValueError('Duplicate node IDs')
        if len({e.id for e in self.edges})!=len(self.edges):raise ValueError('Duplicate edge IDs')
        if any(e.source not in ids or e.target not in ids for e in self.edges):raise ValueError('Dangling relationship endpoint')
        return self

class GraphStore:
    def __init__(self,root):
        self.path=Path(root)/'knowledge_graph.sqlite3'
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('CREATE TABLE IF NOT EXISTS graph_snapshots(project TEXT,revision TEXT,hash TEXT,payload TEXT,PRIMARY KEY(project,revision))');c.commit()
        self.driver=None
        if os.environ.get('FUSION_NEO4J_URI'):
            from neo4j import GraphDatabase
            self.driver=GraphDatabase.driver(os.environ['FUSION_NEO4J_URI'],auth=(os.environ.get('FUSION_NEO4J_USER','neo4j'),os.environ['FUSION_NEO4J_PASSWORD']))
        self.database=os.environ.get('FUSION_NEO4J_DATABASE','neo4j')
    def status(self):
        if self.driver:
            try:self.driver.verify_connectivity();return {'engine':'Neo4j','connected':True}
            except Exception:return {'engine':'Neo4j','connected':False}
        return {'engine':'SQLite graph snapshots','connected':True,'note':'Set FUSION_NEO4J_URI to enable graph-database storage and querying.'}
    def put(self,p):
        raw=json.dumps(p.model_dump(),sort_keys=True);sha=hashlib.sha256(raw.encode()).hexdigest()
        with closing(sqlite3.connect(self.path)) as c:
            c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT hash FROM graph_snapshots WHERE project=? AND revision=?',(p.project,p.revision)).fetchone()
            if old and old[0]!=sha:raise HTTPException(409,'Graph revision is immutable. Use a new revision.')
            if self.driver:
                def write(tx):
                    # Scope every node to this immutable snapshot; no cross-project identity collisions.
                    key=json.dumps([p.project,p.revision])
                    existing=tx.run('MERGE (s:FusionSnapshot {key:$key}) ON CREATE SET s.project=$project,s.revision=$revision,s.hash=$hash RETURN s.hash AS hash',key=key,project=p.project,revision=p.revision,hash=sha).single()
                    if existing['hash']!=sha:raise HTTPException(409,'Neo4j revision is immutable; use a new revision')
                    tx.run('UNWIND $rows AS row MERGE (n:FusionNode {snapshot:$key,id:row.id}) SET n.kind=row.kind,n.label=row.label,n.properties=row.properties',key=key,rows=[dict(n.model_dump(),properties=json.dumps(n.properties)) for n in p.nodes]).consume()
                    tx.run('UNWIND $rows AS row MATCH (a:FusionNode {snapshot:$key,id:row.source}),(b:FusionNode {snapshot:$key,id:row.target}) MERGE (a)-[r:FUSION_LINK {id:row.id}]->(b) SET r += row',key=key,rows=[e.model_dump() for e in p.edges]).consume()
                try:
                    self.driver.execute_query('CREATE CONSTRAINT fusion_snapshot IF NOT EXISTS FOR (n:FusionSnapshot) REQUIRE n.key IS UNIQUE',database_=self.database)
                    self.driver.execute_query('CREATE CONSTRAINT fusion_node IF NOT EXISTS FOR (n:FusionNode) REQUIRE (n.snapshot,n.id) IS UNIQUE',database_=self.database)
                    with self.driver.session(database=self.database) as session:session.execute_write(write)
                except HTTPException:raise
                except Exception as exc:raise HTTPException(503,'Neo4j import failed; snapshot not published') from exc
            c.execute('INSERT OR IGNORE INTO graph_snapshots VALUES(?,?,?,?)',(p.project,p.revision,sha,raw));c.commit()
        return {'project':p.project,'revision':p.revision,'nodes':len(p.nodes),'edges':len(p.edges),'hash':sha,'storage':self.status()}
    def get(self,project,revision):
        with closing(sqlite3.connect(self.path)) as c:row=c.execute('SELECT payload FROM graph_snapshots WHERE project=? AND revision=?',(project,revision)).fetchone()
        if not row:raise HTTPException(404,'Graph snapshot not imported')
        if not self.driver:return json.loads(row[0])
        key=json.dumps([project,revision])
        try:
            nodes,_,_=self.driver.execute_query('MATCH (n:FusionNode {snapshot:$key}) RETURN n.id AS id,n.kind AS kind,n.label AS label,n.properties AS properties',key=key,database_=self.database)
            edges,_,_=self.driver.execute_query('MATCH (a:FusionNode {snapshot:$key})-[r:FUSION_LINK]->(b:FusionNode {snapshot:$key}) RETURN properties(r) AS edge',key=key,database_=self.database)
            return {'project':project,'revision':revision,'nodes':[dict(n,properties=json.loads(n['properties'])) for n in nodes],'edges':[dict(e['edge']) for e in edges]}
        except Exception as exc:raise HTTPException(503,'Neo4j query unavailable') from exc
    def neighbourhood(self,project,revision,node_id,depth=2):
        if self.driver:
            depth=max(0,min(int(depth),5));key=json.dumps([project,revision])
            # Traverse in the graph database, bounded and scoped to one revision.
            try:
                query=f"MATCH p=(r:FusionNode {{snapshot:$key,id:$id}})-[:FUSION_LINK*0..{depth}]-(n:FusionNode {{snapshot:$key}}) WHERE all(v IN nodes(p) WHERE v.snapshot=$key) RETURN DISTINCT n.id AS id,n.kind AS kind,n.label AS label,n.properties AS properties"
                rows,_,_=self.driver.execute_query(query,key=key,id=node_id,database_=self.database)
                if not rows:raise HTTPException(404,'Node not present in this revision')
                nodes=[dict(n,properties=json.loads(n['properties'])) for n in rows]
                ids=[n['id'] for n in nodes]
                links,_,_=self.driver.execute_query('MATCH (a:FusionNode {snapshot:$key})-[r:FUSION_LINK]->(b:FusionNode {snapshot:$key}) WHERE a.id IN $ids AND b.id IN $ids RETURN properties(r) AS edge',key=key,ids=ids,database_=self.database)
                return {'project':project,'revision':revision,'nodes':nodes,'edges':[dict(r['edge']) for r in links],'claim':'Related records with evidence. Graph proximity alone does not prove downstream impact.'}
            except HTTPException:raise
            except Exception as exc:raise HTTPException(503,'Neo4j traversal unavailable') from exc
        data=self.get(project,revision);ids={n['id'] for n in data['nodes']}
        if node_id not in ids:raise HTTPException(404,'Node not present in this revision')
        selected={node_id};frontier={node_id}
        for _ in range(depth):
            more=set()
            for e in data['edges']:
                if e['source'] in frontier:more.add(e['target'])
                if e['target'] in frontier:more.add(e['source'])
            frontier=more-selected;selected.update(more)
        return dict(data,nodes=[n for n in data['nodes'] if n['id'] in selected],edges=[e for e in data['edges'] if e['source'] in selected and e['target'] in selected],claim='Related records; each relationship includes its evidence. Adjacency alone does not prove impact.')

def register(app,root):
    from fastapi import Query
    store=GraphStore(root);app.state.knowledge_graph=store
    @app.get('/api/knowledge/status')
    def status():return store.status()
    @app.post('/api/knowledge/import')
    def import_graph(p:GraphSnapshot):return store.put(p)
    @app.get('/api/knowledge/snapshots')
    def snapshots():
        with closing(sqlite3.connect(store.path)) as c:return [{'project':r[0],'revision':r[1]} for r in c.execute('SELECT project,revision FROM graph_snapshots ORDER BY rowid DESC')]
    @app.get('/api/knowledge/neighbourhood')
    def neighbourhood(project:str,revision:str,node_id:str,depth:int=Query(2,ge=0,le=5)):return store.neighbourhood(project,revision,node_id,depth)
    @app.on_event('shutdown')
    def close_graph():
        if store.driver:store.driver.close()
    @app.post('/api/knowledge/decisions')
    def decision_graph(project:str):
        ledger=app.state.decision_ledger
        ds=ledger.list(project=project,limit=1000000)['decisions'];nodes={};edges=[]
        def node(id,kind,label,props=None):nodes[id]={'id':id,'kind':kind,'label':label,'properties':props or {}}
        def edge(a,b,kind,version,reason,provenance='human-confirmed'):
            edges.append({'id':'REL-'+hashlib.sha256(json.dumps([a,b,kind]).encode()).hexdigest()[:20],'source':a,'target':b,'kind':kind,'provenance':provenance,'reason':reason,'source_key':a,'source_version':str(version)})
        for d in ds:
            node(d['id'],'Decision',d['title'],{'status':d['status'],'validity':d['evidence_validity'],'rationale':d['rationale']})
            for eid in d.get('element_ids',[]):
                node('element:'+eid,'Element',eid);edge(d['id'],'element:'+eid,'CONCERNS',d['version'],'Element linked in decision context')
            if d.get('issue_id'):
                iid='issue:'+d['issue_id'];node(iid,'Issue',d['issue_id']);edge(d['id'],iid,'RESPONDS_TO',d['version'],'Decision originated from this review issue')
            for r in d.get('references',[]):
                rid='evidence:'+hashlib.sha256(json.dumps(r,sort_keys=True).encode()).hexdigest()[:24]
                node(rid,'Evidence',r.get('id',rid),r);edge(d['id'],rid,'SUPPORTED_BY',d['version'],r.get('description') or 'Evidence supplied with decision',r.get('provenance','inferred'))
            for e in d['history']:
                event_id='event:'+e['id'];node(event_id,'ReviewEvent',e['event_type'],e);edge(d['id'],event_id,'HAS_EVENT',d['version'],'Recorded review, implementation or outcome event')
        payload={'project':project,'nodes':list(nodes.values()),'edges':edges}
        revision='ledger-'+hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()[:16]
        return store.put(GraphSnapshot(revision=revision,**payload))
