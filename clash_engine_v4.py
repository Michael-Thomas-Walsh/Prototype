"""Fusion BIM V4 - mesh SURFACE intersection screening, not certified solid clashes.

Inputs: output/structural_review_queue.csv (or fusion_v4/structural_review_queue.csv).
Downloads Speckle bundle once, processes only involved geometry.
Requires: python -m pip install numpy "specklepy[bundle]"

Outputs: output/clash_v4_results.csv; output/clash_v4_summary.json

A detected triangle intersection is mesh-surface evidence, NOT automatically a
constructability defect. 'NO_SURFACE_CROSSING_FOUND' does NOT rule out nesting,
containment, thin-wall overlap, open/non-manifold mesh issues, or tolerance issues.
"""
from __future__ import annotations
import csv
import json
import math
from collections import Counter
from pathlib import Path
import numpy as np
from specklepy.api import operations
from specklepy.api.client import SpeckleClient
from specklepy.api.credentials import get_default_account

PROJECT = '0f3cb45af1'
MODEL = 'ee03c40d73'
VERSION = 'cb0188d0ef'  # pin to the reviewed version, don't silently switch
OUTPUT = Path('output'); OUTPUT.mkdir(exist_ok=True)
QUEUE_CHOICES = [OUTPUT/'structural_review_queue.csv', Path('fusion_v4/structural_review_queue.csv'), Path('structural_review_queue.csv')]
SCALE = {'m':1., 'mm':0.001, 'cm':0.01, 'ft':0.3048, 'in':0.0254}
MAX_TRIANGLES_PER_OBJECT = 15000
MAX_TRIANGLE_TESTS_PER_PAIR = 350000
TOLERANCE_M = 0.0001  # proximity tolerance used in SAT; NOT clearance requirement


def vertices_of(mesh):
    v = getattr(mesh,'vertices',None)
    if v is None: v = getattr(mesh,'positions',None)
    if v is None: raise ValueError('mesh has no vertices/positions')
    a = np.asarray(v,dtype=np.float64)
    if a.ndim == 1:
        if a.size % 3: raise ValueError('vertex buffer not divisible by 3')
        a = a.reshape((-1,3))
    if a.ndim != 2 or a.shape[1] != 3: raise ValueError('unsupported vertex shape')
    return a


def faces_of(mesh, nvertices):
    faces = getattr(mesh,'faces',None)
    if faces is None: faces = getattr(mesh,'triangles',None)
    if faces is None: raise ValueError('mesh has no faces/triangles field')
    a = np.asarray(faces)
    if a.ndim == 2 and a.shape[1] == 3:
        ans = a.astype(np.int64)
    elif a.ndim == 2 and a.shape[1] == 4:
        ans = np.vstack([a[:,[0,1,2]],a[:,[0,2,3]]]).astype(np.int64)
    elif a.ndim == 1:
        # Speckle's face encoding is commonly [3,i,j,k,4,i,j,k,l,...]
        # or legacy [0,i,j,k,1,i,j,k,l,...]. Parse explicitly; NEVER
        # assume a raw flat triangle index buffer without evidence.
        stream = a.astype(np.int64).tolist()
        def parse(mode):
            result=[]; i=0
            while i < len(stream):
                face_type=stream[i]; i+=1
                n = ({3:3,4:4} if mode=='counts' else {0:3,1:4}).get(face_type)
                if n is None or i+n > len(stream): return None
                f=stream[i:i+n]; i+=n
                if n == 3: result.append(f)
                else: result.extend(([f[0],f[1],f[2]], [f[0],f[2],f[3]]))
            return np.asarray(result,dtype=np.int64).reshape((-1,3))
        ans = parse('counts')
        if ans is None: ans = parse('legacy')
        if ans is None: raise ValueError('unrecognised flat face encoding; inspect decoded mesh schema')
    else:
        raise ValueError('unsupported face array layout')
    if ans.size and (ans.min()<0 or ans.max()>=nvertices):
        raise ValueError('mesh face indices out of range')
    return ans


def placed_vertices(vertices, transform, scale):
    if transform is None: return vertices*scale
    m=np.asarray(transform,dtype=np.float64)
    if m.size!=16: raise ValueError('invalid transform matrix length')
    m=m.reshape((4,4))
    if not np.allclose(m[3,:], [0,0,0,1],atol=1.e-7):
        raise ValueError('non-affine or unexpected matrix layout')
    return (vertices@m[:3,:3].T+m[:3,3])*scale


def extract_triangles(obj, scale):
    pieces=[]
    for geo in obj.geometries or []:
        if 'mesh' not in str(geo.type).lower(): continue
        mesh=geo.decode_mesh()
        vs=vertices_of(mesh)
        faces=faces_of(mesh,len(vs))
        if not len(faces): continue
        pts=placed_vertices(vs,geo.transform,scale)
        if not np.isfinite(pts).all(): raise ValueError('nonfinite mesh vertices')
        pieces.append(pts[faces])
    if not pieces: raise ValueError('no triangulated mesh geometry')
    result=np.concatenate(pieces)
    if len(result)>MAX_TRIANGLES_PER_OBJECT:
        raise ValueError(f'triangle limit exceeded: {len(result)} > {MAX_TRIANGLES_PER_OBJECT}')
    return result


def tri_crosses(a,b,eps):
    """Triangle-triangle separating-axis test (includes coplanar cases).

    SAT has conservative tolerance: touch/proximity may count as a hit.
    Surface intersection alone does not determine overlap volume.
    """
    e1=np.array([a[1]-a[0],a[2]-a[1],a[0]-a[2]])
    e2=np.array([b[1]-b[0],b[2]-b[1],b[0]-b[2]])
    n1=np.cross(e1[0],e1[1]); n2=np.cross(e2[0],e2[1])
    if np.linalg.norm(n1)<1e-12 or np.linalg.norm(n2)<1e-12: return False
    axes=[n1,n2]+[np.cross(x,y) for x in e1 for y in e2]
    # Coplanar faces need in-plane edge normals too.
    for e in e1: axes.append(np.cross(n1,e))
    for e in e2: axes.append(np.cross(n2,e))
    for axis in axes:
        norm=np.linalg.norm(axis)
        if norm<1e-12: continue
        u=a@(axis/norm); v=b@(axis/norm)
        if u.max()<v.min()-eps or v.max()<u.min()-eps: return False
    return True


def surface_intersection(a,b):
    amin=a.min(axis=1); amax=a.max(axis=1)
    bmin=b.min(axis=1); bmax=b.max(axis=1)
    # Sweep on triangle X bounds; reuse sorted ordering instead of Cartesian product
    ao=np.argsort(amin[:,0]); bo=np.argsort(bmin[:,0]); active=[]; cursor=0; checks=0
    for ai in ao:
        lo=amin[ai,0]; hi=amax[ai,0]
        while cursor<len(bo) and bmin[bo[cursor],0] <= hi+TOLERANCE_M:
            active.append(bo[cursor]); cursor+=1
        active=[j for j in active if bmax[j,0]>=lo-TOLERANCE_M]
        for j in active:
            if amin[ai,1]>bmax[j,1]+TOLERANCE_M or bmin[j,1]>amax[ai,1]+TOLERANCE_M: continue
            if amin[ai,2]>bmax[j,2]+TOLERANCE_M or bmin[j,2]>amax[ai,2]+TOLERANCE_M: continue
            checks+=1
            if checks>MAX_TRIANGLE_TESTS_PER_PAIR:
                return 'INCONCLUSIVE_TRIANGLE_TEST_LIMIT', checks
            if tri_crosses(a[ai],b[j],TOLERANCE_M):
                return 'SURFACE_INTERSECTION_CANDIDATE', checks
    return 'NO_SURFACE_CROSSING_FOUND',checks


def main():
    queue=next((p for p in QUEUE_CHOICES if p.exists()),None)
    if queue is None: raise FileNotFoundError('Place structural_review_queue.csv in output/, fusion_v4/, or project root')
    with queue.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    if not rows: raise ValueError('empty review queue')
    ids={v for row in rows for v in [row['mep_id'],row['structural_id']]}
    print(f'Loaded {len(rows)} pairs involving {len(ids)} unique instance IDs')
    account=get_default_account()
    if account is None: raise RuntimeError('No Speckle account configured')
    client=SpeckleClient(host='app.speckle.systems');client.authenticate_with_account(account)
    model=client.model.get_with_versions(MODEL,PROJECT,versions_limit=1)
    current=model.versions.items[0].id
    if current!=VERSION: print(f'INFO: current version {current}, processing pinned reviewed version {VERSION}')
    mesh_data={}; errors={}; seen=set()
    with operations.receive3(account,PROJECT,MODEL,VERSION,include_geometry=True) as received:
        scale=SCALE.get(str(received.units).lower())
        if scale is None: raise ValueError('Unknown model units')
        for obj in received.objects:
            oid=str(obj.application_id)
            if oid not in ids: continue
            seen.add(oid)
            try: mesh_data[oid]=extract_triangles(obj,scale)
            except Exception as exc: errors[oid]=str(exc)
        print(f'Matched {len(seen)}/{len(ids)} instance IDs; usable meshes: {len(mesh_data)}')
        print(f'Unrecognised Speckle relation IDs: {sorted(received.unknown_relations)}')
    out=[]; counts=Counter(); checked_total=0
    for index,row in enumerate(rows,1):
        a=row['mep_id']; b=row['structural_id']
        result=dict(row)
        result['mesh_test_status']='';result['triangle_pairs_checked']=0
        result['mep_triangles']=len(mesh_data[a]) if a in mesh_data else 0
        result['structural_triangles']=len(mesh_data[b]) if b in mesh_data else 0
        result['diagnostic']=''
        if a not in mesh_data or b not in mesh_data:
            result['mesh_test_status']='INCONCLUSIVE_MISSING_MESH'
            result['diagnostic']=' | '.join([f'{id}: {errors.get(id,"instance ID absent in bundle")}' for id in (a,b) if id not in mesh_data])
        else:
            try:
                status,n=surface_intersection(mesh_data[a],mesh_data[b]);result['mesh_test_status']=status
                result['triangle_pairs_checked']=n;checked_total+=n
            except Exception as exc:
                result['mesh_test_status']='INCONCLUSIVE_TEST_ERROR';result['diagnostic']=str(exc)
        counts[result['mesh_test_status']]+=1;out.append(result)
        if index%50==0:print(f'Checked {index}/{len(rows)}: {dict(counts)}',flush=True)
    fields=list(out[0].keys())
    with (OUTPUT/'clash_v4_results.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
    summary={'project_id':PROJECT,'model_id':MODEL,'version_id':VERSION,
             'method':'transformed triangle surface SAT intersection; not volumetric solid collision',
             'source_review_queue':str(queue),'input_pairs':len(rows),'matched_instance_ids':len(seen),
             'requested_instance_ids':len(ids),'mesh_loaded':len(mesh_data),
             'results':dict(counts),'triangle_tests':checked_total,
             'tolerance_m':TOLERANCE_M,'unknown_relation_id_30':'may mean semantic relationships incomplete',
             'limitations':['Mesh-surface intersection is not proof of physical interference or design defect',
                            'No surface crossing is not proof that closed solids do not overlap; containment is untested',
                            'Coincident contact may be reported as intersection',
                            'Geometry transforms and coordinates should be visually checked against Revit',
                            'Mesh topology and face encoding must be validated for the installed SDK']}
    (OUTPUT/'clash_v4_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    print('Saved output/clash_v4_results.csv and output/clash_v4_summary.json')

if __name__=='__main__':main()
