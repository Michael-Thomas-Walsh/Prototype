"""Circulation scenarios: explicit spaces/portals, weighted routes and access profiles.
Geometry adjacency is not assumed to be traversable. Declared portal data is required.
"""
import json, sqlite3
from contextlib import closing
from pathlib import Path
import networkx as nx
from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator, ConfigDict
from typing import Literal

class Space(BaseModel):
    id: str=Field(min_length=1)
    name: str
    xyz: tuple[float,float,float]
    exit: bool=False
    occupants: int=Field(default=0,ge=0)
class Portal(BaseModel):
    id: str=Field(min_length=1)
    source: str
    target: str
    distance_m: float=Field(gt=0,allow_inf_nan=False)
    width_m: float|None=Field(default=None,gt=0,allow_inf_nan=False)
    accessible: bool|None=None
    bidirectional: bool=True
    available: bool=True
    element_id: str|None=None
class Journey(BaseModel):
    id: str
    origin: str
    destination: str
    profile: Literal['general','accessible']='general'
class SpatialModel(BaseModel):
    model_config=ConfigDict(extra='forbid')
    project: str=Field(min_length=1)
    revision: str=Field(min_length=1)
    provenance: Literal['extracted','human-confirmed','synthetic']
    distance_basis: Literal['measured-route','estimated','synthetic']
    spaces: list[Space]=Field(min_length=1,max_length=20000)
    portals: list[Portal]=Field(max_length=100000)
    journeys: list[Journey]=Field(default_factory=list,max_length=2000)
    @model_validator(mode='after')
    def check(self):
        import math
        ids={s.id for s in self.spaces}
        if len(ids)!=len(self.spaces):raise ValueError('Duplicate space IDs')
        if any(not all(math.isfinite(x) for x in s.xyz) for s in self.spaces):raise ValueError('Nonfinite coordinates')
        if len({p.id for p in self.portals})!=len(self.portals):raise ValueError('Duplicate portal IDs')
        if any(p.source not in ids or p.target not in ids or p.source==p.target for p in self.portals):raise ValueError('Invalid portal endpoint')
        if len({j.id for j in self.journeys})!=len(self.journeys):raise ValueError('Duplicate journey IDs')
        if any(j.origin not in ids or j.destination not in ids for j in self.journeys):raise ValueError('Unknown journey endpoint')
        return self
class Scenario(BaseModel):
    project: str
    revision: str
    blocked_portals: list[str]=Field(default_factory=list,max_length=5000)
    profile: Literal['general','accessible']='general'
    minimum_width_m: float=Field(default=0,ge=0,allow_inf_nan=False)
    max_route_m: float|None=Field(default=None,gt=0,allow_inf_nan=False)
    alternatives: int=Field(default=3,ge=1,le=5)

def build_graph(model,blocked,profile,width):
    # Portal nodes preserve distinct parallel doors. Directed arcs preserve one-way access.
    g=nx.DiGraph();g.add_nodes_from(('space:'+s.id,{'kind':'space','id':s.id}) for s in model.spaces)
    excluded=[]
    for p in model.portals:
        reason=None
        if p.id in blocked:reason='blocked in scenario'
        elif not p.available:reason='unavailable in baseline'
        elif profile=='accessible' and p.accessible is not True:reason='accessibility unknown or unavailable'
        elif width>0 and (p.width_m is None or p.width_m<width):reason='width unknown or below selected threshold'
        if reason:excluded.append({'id':p.id,'reason':reason});continue
        a,b,k='space:'+p.source,'space:'+p.target,'portal:'+p.id
        g.add_node(k,kind='portal',id=p.id)
        g.add_edge(a,k,weight=p.distance_m/2);g.add_edge(k,b,weight=p.distance_m/2)
        if p.bidirectional:g.add_edge(b,k,weight=p.distance_m/2);g.add_edge(k,a,weight=p.distance_m/2)
    return g,excluded

def routes(g,a,b,count):
    from itertools import islice
    try:
        paths=list(islice(nx.shortest_simple_paths(g,'space:'+a,'space:'+b,weight='weight'),count))
        return [{'spaces':[g.nodes[n]['id'] for n in p if g.nodes[n]['kind']=='space'],'portals':[g.nodes[n]['id'] for n in p if g.nodes[n]['kind']=='portal'],'distance_m':round(nx.path_weight(g,p,'weight'),3)} for p in paths]
    except (nx.NetworkXNoPath,nx.NodeNotFound):return []

def analyse(model,scenario):
    unknown=set(scenario.blocked_portals)-{p.id for p in model.portals}
    if unknown:raise HTTPException(422,'Unknown blocked portals: '+', '.join(sorted(unknown)))
    before,_=build_graph(model,set(),scenario.profile,scenario.minimum_width_m)
    after,excluded=build_graph(model,set(scenario.blocked_portals),scenario.profile,scenario.minimum_width_m)
    journeys=[]
    for j in model.journeys:
        # Accessibility journey remains accessible even when the global profile is general.
        profile='accessible' if 'accessible' in (j.profile,scenario.profile) else 'general'
        g0,_=build_graph(model,set(),profile,scenario.minimum_width_m)
        g1,_=build_graph(model,set(scenario.blocked_portals),profile,scenario.minimum_width_m)
        r0=routes(g0,j.origin,j.destination,1);r1=routes(g1,j.origin,j.destination,scenario.alternatives)
        journeys.append({'id':j.id,'origin':j.origin,'destination':j.destination,'profile':profile,'before':r0,'after':r1,
                         'changed':r0!=(r1[:1]),'lost':bool(r0 and not r1),
                         'delta_m':round(r1[0]['distance_m']-r0[0]['distance_m'],3) if r0 and r1 else None})
    exits=[s for s in model.spaces if s.exit];coverage=[]
    # Reverse searches per exit provide nearest-exit distance for every space.
    distances={e.id:nx.single_source_dijkstra_path_length(after.reverse(copy=False),'space:'+e.id,weight='weight') for e in exits}
    base_dist={e.id:nx.single_source_dijkstra_path_length(before.reverse(copy=False),'space:'+e.id,weight='weight') for e in exits}
    for s in model.spaces:
        reachable=[{'exit':e.id,'distance_m':round(distances[e.id]['space:'+s.id],3)} for e in exits if 'space:'+s.id in distances[e.id]]
        reachable.sort(key=lambda x:x['distance_m']);was=any('space:'+s.id in v for v in base_dist.values())
        coverage.append({'space':s.id,'name':s.name,'occupants':s.occupants,'reachable_exits':reachable,'newly_disconnected':was and not reachable,
                         'threshold_exceeded':bool(reachable and scenario.max_route_m is not None and reachable[0]['distance_m']>scenario.max_route_m)})
    # Cut portals are structural bottlenecks in the undirected adjacency projection;
    # they do not assert evacuation capacity or independent compliant escape routes.
    cuts=[after.nodes[n]['id'] for n in nx.articulation_points(after.to_undirected()) if after.nodes[n]['kind']=='portal']
    loads={p.id:0 for p in model.portals}
    for j in journeys:
        if j['after']:
            for pid in j['after'][0]['portals']:loads[pid]+=1
    return {'project':model.project,'revision':model.revision,'provenance':model.provenance,'distance_basis':model.distance_basis,
            'scenario':scenario.model_dump(),'journeys':journeys,'spaces':coverage,'excluded_portals':excluded,
            'bottleneck_portals':cuts,'journey_usage':[{'portal':p,'journeys':n} for p,n in sorted(loads.items(),key=lambda x:-x[1]) if n],
            'summary':{'changed_journeys':sum(j['changed'] for j in journeys),'lost_journeys':sum(j['lost'] for j in journeys),'newly_disconnected_spaces':sum(bool(s['newly_disconnected']) for s in coverage),'unreachable_spaces':sum(not s['reachable_exits'] for s in coverage),'occupants_without_route':sum(s['occupants'] for s in coverage if not s['reachable_exits'])},
            'limitations':['Route screening against declared portal data, not escape-route compliance or evacuation simulation.','Alternative paths may share portals; their count is not a count of independent escape routes.','No occupancy flow, smoke, door swing, fire compartment or construction-phase verification.','Threshold is a user scenario input, not a regulatory limit.']}

def topologic_graph(model):
    from topologicpy.Vertex import Vertex
    from topologicpy.Edge import Edge
    from topologicpy.Graph import Graph
    # Kernel topology verifies declared spatial connections, while NetworkX retains
    # direction, profiles and portal identities used by the circulation calculations.
    vertices={s.id:Vertex.ByCoordinates(*s.xyz) for s in model.spaces}
    edges=[];pairs=set();skipped=[]
    for p in model.portals:
        pair=tuple(sorted([p.source,p.target]))
        if pair in pairs:continue
        pairs.add(pair)
        edge=Edge.ByVertices([vertices[p.source],vertices[p.target]])
        if edge is None:skipped.append(p.id)
        else:edges.append(edge)
    graph=Graph.ByVerticesEdges(list(vertices.values()),edges)
    if graph is None:raise ValueError('Topologic could not build the spatial graph')
    return {'engine':'TopologicPy','vertices':len(Graph.Vertices(graph) or []),'edges':len(Graph.Edges(graph) or []),'skipped_portals':skipped,
            'purpose':'Kernel graph of declared space adjacency; parallel doors are retained separately in the circulation network.'}

def register(app,root):
    path=Path(root)/'circulation.sqlite3'
    with closing(sqlite3.connect(path)) as c:
        c.execute('CREATE TABLE IF NOT EXISTS spatial_models(project TEXT,revision TEXT,payload TEXT,PRIMARY KEY(project,revision))');c.commit()
    def get(project,revision):
        with closing(sqlite3.connect(path)) as c:r=c.execute('SELECT payload FROM spatial_models WHERE project=? AND revision=?',(project,revision)).fetchone()
        if not r:raise HTTPException(404,'Spatial revision not imported')
        return SpatialModel.model_validate_json(r[0])
    @app.post('/api/circulation/import')
    def import_spatial(p:SpatialModel):
        raw=json.dumps(p.model_dump(),sort_keys=True)
        with closing(sqlite3.connect(path)) as c:
            c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT payload FROM spatial_models WHERE project=? AND revision=?',(p.project,p.revision)).fetchone()
            if old and old[0]!=raw:raise HTTPException(409,'Spatial revision is immutable; use a new revision')
            c.execute('INSERT OR IGNORE INTO spatial_models VALUES(?,?,?)',(p.project,p.revision,raw));c.commit()
        return {'project':p.project,'revision':p.revision,'spaces':len(p.spaces),'portals':len(p.portals)}
    @app.get('/api/circulation/models')
    def models():
        with closing(sqlite3.connect(path)) as c:return [{'project':r[0],'revision':r[1]} for r in c.execute('SELECT project,revision FROM spatial_models ORDER BY rowid DESC')]
    @app.get('/api/circulation/model')
    def model(project:str,revision:str):return get(project,revision).model_dump()
    @app.post('/api/circulation/analyse')
    def analysis(p:Scenario):return analyse(get(p.project,p.revision),p)
    @app.post('/api/circulation/topology')
    def topology(p:Scenario):
        try:return topologic_graph(get(p.project,p.revision))
        except ImportError as exc:raise HTTPException(503,'Install requirements-v17.txt including topologic-core to enable TopologicPy') from exc
        except HTTPException:raise
        except Exception as exc:raise HTTPException(422,'Topology conversion failed: '+str(exc)) from exc
    @app.get('/api/circulation/example')
    def example():
        from .demo_network import MODEL
        return MODEL
    @app.post('/api/circulation/decision-context')
    def decision_context(p:Scenario):
        from .decision_ledger import SourceUpdate,digest
        model=get(p.project,p.revision);result=analyse(model,p);ledger=app.state.decision_ledger
        # Preserve analysis evidence independently of the mutable source registry.
        run_id='RUN-'+digest(result)[:24]
        with closing(sqlite3.connect(path)) as c:
            c.execute('CREATE TABLE IF NOT EXISTS spatial_runs(id TEXT PRIMARY KEY,payload TEXT)')
            c.execute('INSERT OR IGNORE INTO spatial_runs VALUES(?,?)',(run_id,json.dumps(result)));c.commit()
        refs=[]
        for key,revision,kind,id in [('circulation-model',model.revision,'model',model.revision),(run_id,digest(result),'analysis',run_id)]:
            with ledger.db() as c:old=c.execute('SELECT revision FROM ledger_sources WHERE project=? AND source_key=?',(p.project,key)).fetchone()
            if key=='circulation-model' and old and old['revision']!=revision:
                raise HTTPException(409,'This spatial revision is not the registered current model. Reconcile the source explicitly before recording the scenario.')
            if not old:ledger.update_source(SourceUpdate(project=p.project,source_key=key,revision=revision), 'Circulation analysis')
            refs.append({'kind':kind,'id':id,'source_key':key,'source_version':revision,'provenance':'synthetic' if model.provenance=='synthetic' else 'calculated' if kind=='analysis' else model.provenance,'description':'Circulation source or reproducible scenario result'})
        return {'title':'Review circulation change: '+(', '.join(p.blocked_portals) or 'baseline'), 'project':p.project,'context':json.dumps(result['summary'],indent=2),'priority':'high' if result['summary']['lost_journeys'] or result['summary']['newly_disconnected_spaces'] else 'medium','why_it_matters':f"{result['summary']['changed_journeys']} journeys change; {result['summary']['lost_journeys']} lose their route under the declared scenario. Review the design assumptions and affected users before accepting the change.",'references':refs,'element_ids':[x.element_id or x.id for x in model.portals if x.id in p.blocked_portals],'assumptions':['Blocked portals represent an unavailable passage, not merely removal of a door leaf.','Route weights use '+model.distance_basis+' distances.'],'options':['Retain baseline passages','Adopt proposed portal closures','Provide an alternative accessible passage'],'acceptance_criteria':['Review affected journeys and reachable exits with the responsible designer'],'reusable_conditions':['Revalidate portal geometry, accessibility, occupancy and applicable requirements on each project.']}
    @app.get('/api/circulation/runs/{run_id}')
    def run(run_id:str):
        with closing(sqlite3.connect(path)) as c:
            exists=c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='spatial_runs'").fetchone()
            r=c.execute('SELECT payload FROM spatial_runs WHERE id=?',(run_id,)).fetchone() if exists else None
        if not r:raise HTTPException(404,'Analysis run not found')
        return json.loads(r[0])
    @app.post('/api/circulation/graph')
    def graph(p:Scenario):
        from .knowledge_graph import GraphSnapshot
        model=get(p.project,p.revision)
        nodes=[{'id':s.id,'kind':'Space','label':s.name,'properties':s.model_dump()} for s in model.spaces]
        nodes += [{'id':'portal:'+x.id,'kind':'Portal','label':x.id,'properties':x.model_dump()} for x in model.portals]
        edges=[]
        for x in model.portals:
            for endpoint in [x.source,x.target]:
                edges.append({'id':x.id+':'+endpoint,'source':endpoint,'target':'portal:'+x.id,'kind':'BOUNDS_PORTAL','provenance':model.provenance,'reason':'Space is an endpoint of this declared portal','source_key':'circulation-model','source_version':model.revision})
        return app.state.knowledge_graph.put(GraphSnapshot(project=p.project,revision='spatial:'+p.revision,nodes=nodes,edges=edges))
