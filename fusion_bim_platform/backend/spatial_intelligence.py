"""Route *screening* for extracted Revit room/door connectivity, not a fire-code checker."""
from __future__ import annotations
import json
from pathlib import Path
import networkx as nx
ROOT=Path(__file__).resolve().parents[1]
SPATIAL=ROOT/'data'/'spatial_graph.json'
DEMO=ROOT/'data'/'spatial_demo.json'

def load_graph():
    path=SPATIAL if SPATIAL.exists() else DEMO
    data=json.loads(path.read_text(encoding='utf-8'))
    g=nx.Graph()
    for room in data.get('spaces',[]): g.add_node(room['id'],**room)
    for edge in data.get('connections',[]):
        if edge['a'] in g and edge['b'] in g:
            g.add_edge(edge['a'],edge['b'],**{k:v for k,v in edge.items() if k not in ('a','b')},weight=max(0.01,float(edge.get('distance_m') or 1)))
    return data,g,path==DEMO

def analyse(blocked=None,origin=None,destination=None):
    data,g,demo=load_graph(); blocked=set(blocked or [])
    h=g.copy()
    for a,b,props in list(h.edges(data=True)):
        if props.get('id') in blocked:h.remove_edge(a,b)
    exits=[n for n,v in h.nodes(data=True) if v.get('is_exit')]
    isolated=[n for n in h.nodes if h.degree(n)==0 and n not in exits]
    unavailable=[n for n in h.nodes if n not in exits and not any(nx.has_path(h,n,x) for x in exits)] if exits else []
    bridges=list(nx.bridges(h)); cuts=[{'a':a,'b':b,'connection_id':h[a][b].get('id')} for a,b in bridges]
    centrality=nx.betweenness_centrality(h,weight='weight',normalized=True) if h.nodes else {}
    findings=[]
    for n in unavailable:
        findings.append({'id':'UNREACHABLE-'+n,'severity':'High','title':'No route to a modelled exit','rule':'SPACE-CONNECTIVITY-01','spaces':[n],'evidence':'No connected path to any node explicitly labelled as an exit in this extracted graph.','status':'Review required'})
    for n in isolated:
        if n not in unavailable:findings.append({'id':'ISOLATED-'+n,'severity':'High','title':'Isolated space','rule':'SPACE-CONNECTIVITY-02','spaces':[n],'evidence':'No traversable connections were extracted.','status':'Review required'})
    if not exits:
        findings.append({'id':'EXIT-NOT-DEFINED','severity':'High','title':'Exit destinations not defined','rule':'SPACE-DATA-01','spaces':[],'evidence':'The source model did not identify any validated exit nodes; escape-route screening is unavailable until exits are reviewed and classified.','status':'Data required'})
    for cut in cuts:
        findings.append({'id':'BRIDGE-'+str(cut['connection_id']),'severity':'Review','title':'Single-connection vulnerability','rule':'SPACE-RESILIENCE-01','spaces':[cut['a'],cut['b']],'evidence':'Removing this connection separates the spatial graph. This is not a fire-code non-compliance finding.','status':'Review required'})
    result={'source':data.get('source',{}),'demo':demo,'spaces':list(g.nodes.values()),'connections':data.get('connections',[]),'metrics':{'spaces':g.number_of_nodes(),'connections':g.number_of_edges(),'exits':len(exits),'unreachable':len(unavailable),'bridge_connections':len(bridges)},'findings':findings,'centrality':centrality,'blocked':list(blocked),'caution':'Connectivity and routes are screening evidence only, not certified evacuation or Part B compliance.'}
    if origin and destination:
        if origin not in h or destination not in h:result['route']={'error':'Select valid spaces'}
        else:
            try:
                p=nx.shortest_path(h,origin,destination,weight='weight');dist=nx.path_weight(h,p,'weight')
                result['route']={'spaces':p,'distance_m':round(dist,2) if all(h[p[i]][p[i+1]].get('distance_m') is not None for i in range(len(p)-1)) else None,'hops':len(p)-1,'connections':[h[p[i]][p[i+1]].get('id') for i in range(len(p)-1)]}
            except nx.NetworkXNoPath:result['route']={'error':'No traversable route in the extracted network'}
    return result

def import_graph(payload):
    if not isinstance(payload,dict) or not isinstance(payload.get('spaces'),list) or not isinstance(payload.get('connections'),list):raise ValueError('Expected spaces and connections arrays')
    if len(payload['spaces'])>20000 or len(payload['connections'])>60000:raise ValueError('Spatial dataset exceeds import limits')
    ids=set()
    for s in payload['spaces']:
        if not isinstance(s.get('id'),str) or not s['id'] or s['id'] in ids:raise ValueError('Invalid/duplicate space ID')
        ids.add(s['id'])
    for e in payload['connections']:
        if e.get('a') not in ids or e.get('b') not in ids or e.get('a')==e.get('b'):raise ValueError('Connection references invalid spaces')
    SPATIAL.parent.mkdir(exist_ok=True)
    tmp=SPATIAL.with_suffix('.tmp');tmp.write_text(json.dumps(payload,indent=2),encoding='utf-8');tmp.replace(SPATIAL)
    return {'spaces':len(ids),'connections':len(payload['connections']),'source':payload.get('source',{}),'status':'Imported; review model identity and source revision before treating links as current'}
