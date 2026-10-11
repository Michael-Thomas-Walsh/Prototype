"""Transparent non-AI clustering of candidate intersection records."""
from collections import defaultdict

def groups(issues):
    # Common MEP element + fabric category + level: transparent, conservative grouping.
    clusters=defaultdict(list)
    for item in issues:
        key=(item.get('mepId',''),item.get('pair',''),item.get('level',''))
        clusters[key].append(item)
    result=[]
    for index,(key,items) in enumerate(sorted(clusters.items(),key=lambda kv:(-len(kv[1]),str(kv[0]))),1):
        result.append({'id':'GROUP-%04d'%index,'mepId':key[0], 'disciplinePair':key[1], 'level':key[2],
            'issueIds':[x['id'] for x in items], 'candidateCount':len(items),
            'uniqueFabricElements':len({x.get('fabricId') for x in items}),
            'classification':'Requires review', 'recommendation':'Review grouped candidate contacts; do not assume a penetration or confirmed clash.',
            'evidence':'AABB_BROAD_PHASE', 'groupingRule':'same MEP element + discipline pair + level'})
    return {'totalRawCandidates':len(issues),'groups':result,'limitations':'Groups are derived from broad-phase AABB candidates, not verified mesh intersections.'}
