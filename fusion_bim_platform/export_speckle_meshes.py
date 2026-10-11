"""Export real transformed Speckle bundle mesh geometry as selectable GLB chunks.
Run from platform root using the Python environment containing specklepy[bundle], numpy, trimesh.
No credentials, IFC data or geometry need to be sent to a third-party service.
"""
import json, re, math, collections
from pathlib import Path
import numpy as np
import trimesh
from specklepy.api import operations
from specklepy.api.credentials import get_default_account

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'; STATIC=ROOT/'frontend'/'public'/'data'; OUT=STATIC/'meshes'
PROJECT='0f3cb45af1'; MODEL='ee03c40d73'; VERSION='cb0188d0ef'
UNIT={'m':1.,'mm':.001,'cm':.01,'ft':.3048,'in':.0254}
CHUNK_LIMIT=250
ALLOWED={'Architecture','Structural','Plumbing','HVAC','Electrical','Facades','Site'}

def vertices(mesh):
    v=getattr(mesh,'vertices',None)
    if v is None:v=getattr(mesh,'positions',None)
    v=np.asarray(v,dtype=np.float64).reshape((-1,3))
    if not np.isfinite(v).all():raise ValueError('Nonfinite vertices')
    return v

def faces(mesh,n):
    f=getattr(mesh,'faces',None)
    if f is None:f=getattr(mesh,'triangles',None)
    f=np.asarray(f)
    if f.ndim==2 and f.shape[1] in (3,4):
        tri=f if f.shape[1]==3 else np.concatenate([f[:,[0,1,2]],f[:,[0,2,3]]])
    elif f.ndim==1:
        stream=f.astype(np.int64).tolist()
        def parse(counts):
            result=[];j=0
            while j<len(stream):
                c=stream[j];j+=1;cnt=({3:3,4:4} if counts else {0:3,1:4}).get(c)
                if cnt is None or j+cnt>len(stream):return None
                q=stream[j:j+cnt];j+=cnt
                result.append(q[:3]);
                if cnt==4:result.append([q[0],q[2],q[3]])
            return np.asarray(result,dtype=np.int64).reshape((-1,3))
        tri=parse(True)
        if tri is None:tri=parse(False)
        if tri is None:raise ValueError('Unknown face stream')
    else:raise ValueError('Unsupported faces')
    tri=np.asarray(tri,dtype=np.int64)
    if len(tri) and (tri.min()<0 or tri.max()>=n):raise ValueError('Out of range indices')
    return tri

def position(v,t,s):
    if t is not None:
        m=np.asarray(t,dtype=float).reshape((4,4))
        if not np.allclose(m[3],[0,0,0,1],atol=1e-7):raise ValueError('Unexpected transform')
        v=v@m[:3,:3].T+m[:3,3]
    v=v*s
    # Align with existing Three.js dashboard: Revit Z becomes viewer Y.
    return np.column_stack((v[:,0],v[:,2],-v[:,1]))

def export(version_id=None):
    version_id=version_id or VERSION
    account=get_default_account()
    if account is None:raise RuntimeError('No Speckle default account. Sign in using Speckle Manager.')
    OUT.mkdir(parents=True,exist_ok=True)
    # Never leave a stale READY manifest while a new export is running.
    elements=json.loads((DATA/'elements.json').read_text())
    by_id=collections.defaultdict(list)
    for e in elements:by_id[e['baseId']].append(e)
    manifest={'status':'EXPORTING','source':'Speckle bundle','projectId':PROJECT,'modelId':MODEL,'versionId':version_id,'chunks':[],'errors':[]}
    (STATIC/'mesh_manifest.json').write_text(json.dumps(manifest,indent=2))
    scene=trimesh.Scene();included=set();discipline=None;count=0;num=0
    def flush():
        nonlocal scene,count,num
        if not count:return
        name=f'{discipline.lower()}_{num:03d}.glb';path=OUT/name
        path.write_bytes(scene.export(file_type='glb'))
        manifest['chunks'].append({'url':'/data/meshes/'+name,'discipline':discipline,'elementCount':count,'bytes':path.stat().st_size})
        (STATIC/'mesh_manifest.json').write_text(json.dumps(manifest,indent=2))
        print('Exported',name,count,'objects',round(path.stat().st_size/1048576,1),'MiB',flush=True)
        scene=trimesh.Scene();count=0;num+=1
    with operations.receive3(account,PROJECT,MODEL,version_id,include_geometry=True) as model:
        scale=UNIT.get(str(model.units).lower())
        if scale is None:raise ValueError('Unknown units: '+str(model.units))
        groups=collections.defaultdict(list)
        for obj in model.objects:
            matches=by_id.get(obj.application_id,[])
            for e in matches:
                if e['discipline'] in ALLOWED and e['category'] not in ('Spaces','Rooms','Analytical Surfaces','Electrical Circuits','Sheets','Grids','Levels'):
                    groups[e['discipline']].append((obj,e))
        for discipline in sorted(groups):
            num=0
            for obj,e in groups[discipline]:
                part=0
                for geo in obj.geometries or []:
                    if 'mesh' not in str(geo.type).lower():continue
                    try:
                        raw=geo.decode_mesh();v=vertices(raw);f=faces(raw,len(v))
                        if not len(f):continue
                        v=position(v,getattr(geo,'transform',None),scale)
                        shape=trimesh.Trimesh(vertices=v,faces=f,process=False)
                        if shape.is_empty:continue
                        # Name is stable even across GLB chunk boundaries and is used for issue selection.
                        node=e['id'] if part==0 else f'{e["id"]}__part{part}'
                        scene.add_geometry(shape,node_name=node,geom_name=f'geom_{count}_{part}')
                        part+=1
                    except Exception as exc:
                        if len(manifest['errors'])<50:manifest['errors'].append({'element':e['id'],'error':str(exc)[:150]})
                if part:
                    included.add(e['id']);count+=1
                    if count>=CHUNK_LIMIT:flush()
            flush()
    if not manifest['chunks']:
        raise RuntimeError('Mesh export produced zero GLB chunks; inspect manifest errors')
    manifest['status']='READY';manifest['exportedElements']=len(included)
    (STATIC/'mesh_manifest.json').write_text(json.dumps(manifest,indent=2))
    (DATA/'mesh_manifest.json').write_text(json.dumps(manifest,indent=2))
    print('Complete:',len(included),'meshed objects,',len(manifest['chunks']),'GLB chunks')
    print('Warnings:',len(manifest['errors']),'examples logged')

if __name__=='__main__':export()
