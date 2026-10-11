"""Deterministic graph traversal and Critical Path Method.
All demonstration edges and dependencies must be identified as synthetic.
"""
from collections import defaultdict, deque

def neighbourhood(graph, root, depth=2):
    nodes={n['id']:n for n in graph['nodes']}
    if root not in nodes: raise ValueError('Unknown node')
    depth=max(0,min(int(depth),5)); seen={root:0}; queue=deque([root]); edges=[]; unique=set()
    while queue:
        node=queue.popleft()
        if seen[node]>=depth: continue
        for edge in graph['edges']:
            if node not in (edge['source'],edge['target']): continue
            peer=edge['target'] if edge['source']==node else edge['source']
            if peer not in nodes:continue
            key=(edge['source'],edge.get('relation'),edge['target'])
            if key not in unique: edges.append(edge);unique.add(key)
            if peer not in seen:seen[peer]=seen[node]+1;queue.append(peer)
    return {'root':root,'nodes':[nodes[n] for n in seen], 'edges':edges, 'evidence':'SYNTHETIC_GRAPH_DEMO'}

def cpm(activities):
    """Finish-to-start, no lag CPM; project start week zero.
    Output both input planned start and network-driven dates; no automatic real-world delay inference.
    """
    byid={a['id']:a for a in activities}
    if len(byid)!=len(activities):raise ValueError('Duplicate activity IDs')
    successors=defaultdict(list); indegree={k:0 for k in byid}
    for a in activities:
        if int(a['duration'])<1:raise ValueError('Activity duration must be >= 1')
        for p in a.get('predecessors',[]):
            if p not in byid:raise ValueError('Unknown predecessor %s for %s'%(p,a['id']))
            successors[p].append(a['id']);indegree[a['id']]+=1
    q=deque(k for k,v in indegree.items() if v==0); order=[]
    while q:
        k=q.popleft();order.append(k)
        for s in successors[k]:
            indegree[s]-=1
            if indegree[s]==0:q.append(s)
    if len(order)!=len(byid):raise ValueError('Activity dependencies contain a cycle')
    es={};ef={}
    for k in order:
        es[k]=max((ef[p] for p in byid[k].get('predecessors',[])),default=0)
        ef[k]=es[k]+int(byid[k]['duration'])
    finish=max(ef.values(),default=0);ls={};lf={}
    for k in reversed(order):
        lf[k]=min((ls[s] for s in successors[k]),default=finish)
        ls[k]=lf[k]-int(byid[k]['duration'])
    rows=[{'id':k,'name':byid[k]['name'],'duration':int(byid[k]['duration']), 'plannedStart':byid[k].get('start'), 'earlyStart':es[k],'earlyFinish':ef[k],'lateStart':ls[k],'lateFinish':lf[k],'float':ls[k]-es[k], 'critical':ls[k]==es[k], 'predecessors':byid[k].get('predecessors',[])} for k in order]
    return {'projectFinishWeek':finish,'criticalCount':sum(r['critical'] for r in rows),'activities':rows,'assumptions':'Synthetic finish-to-start dependencies, zero lag, no calendars, resources, constraints or approved baseline'}
