"""Read the latest Speckle version, compare it to the dashboard baseline, export meshes.
Changes are potential coordination impacts, never automatically confirmed clashes.
"""
import json, re, sys
from pathlib import Path
from specklepy.api.client import SpeckleClient
from specklepy.api.credentials import get_default_account
from specklepy.api import operations
from export_speckle_meshes import export, PROJECT, MODEL, ROOT

DATA=ROOT/'data'
def stable_id(identifier):
    return re.sub(r'_t[0-9a-f]{8,}$','',str(identifier or ''))
def inventory(account, version):
    # A full metadata comparison including property changes; geometry-only changes
    # require additional mesh fingerprinting and are therefore not claimed here.
    result={}
    with operations.receive3(account,PROJECT,MODEL,version,include_geometry=False) as model:
        for obj in model.objects:
            category=' / '.join(obj.collection_path or [])
            properties=dict(obj.properties or {})
            signature=json.dumps([obj.name,category,obj.level.name if obj.level else None,properties],sort_keys=True,default=str)
            result[str(obj.application_id)] = signature
    return result

def impact_for(ids):
    programme=json.loads((DATA/'programme.json').read_text(encoding='utf8'))
    plan=json.loads((DATA/'delivery_plan.json').read_text(encoding='utf8'))
    changed=set(ids)
    activities=[a['id'] for a in programme['activities'] if any(stable_id(e) in changed for e in programme['assignments'].get(a['id'],[]))]
    act=set(activities)
    packages=[x for x in plan['workPackages'] if any(a in act for a in x.get('activityIds',[]))]
    pkg={x['id'] for x in packages}
    drawings=[x for x in plan['deliverables'] if x.get('workPackageId') in pkg or any(a in act for a in x.get('activityIds',[]))]
    return {'activityIds':activities[:100], 'workPackageIds':[x['id'] for x in packages][:100], 'drawingIds':[d['id'] for d in drawings][:100], 'activitiesCount':len(activities),'workPackagesCount':len(packages),'drawingsCount':len(drawings)}

def main():
    account=get_default_account()
    if account is None:raise RuntimeError('No Speckle account configured')
    client=SpeckleClient(host='app.speckle.systems'); client.authenticate_with_account(account)
    model=client.model.get_with_versions(MODEL,PROJECT,versions_limit=1)
    latest=model.versions.items[0].id
    meta=json.loads((DATA/'metadata.json').read_text(encoding='utf8'))
    baseline=meta['speckleVersion']
    event={'projectId':PROJECT,'modelId':MODEL,'baselineVersion':baseline,'latestVersion':latest,'synthetic':False}
    if latest==baseline:
        manifest_path=ROOT/'frontend'/'public'/'data'/'mesh_manifest.json'
        manifest={}
        if manifest_path.exists():
            try: manifest=json.loads(manifest_path.read_text(encoding='utf8'))
            except (OSError,ValueError): pass
        chunks=manifest.get('chunks',[])
        all_present=bool(chunks) and all(
            (ROOT/'frontend'/'public'/str(c.get('url','')).lstrip('/').removeprefix('data/')).is_file()
            for c in chunks
        )
        # Cache identity matters: a READY mesh cache from a different version is stale.
        ready=(manifest.get('status')=='READY' and
               manifest.get('versionId')==latest and all_present)
        if not ready:
            print('Speckle unchanged, but local mesh cache is missing/incomplete. Exporting meshes...',flush=True)
            export(version_id=latest)
        event.update(status='UNCHANGED',
                     message='Up to date — no new Speckle version. Meshes ready.' if ready else 'Up to date — Speckle unchanged; missing meshes exported.',
                     changedElements=0,meshExport='ALREADY_CACHED' if ready else 'DONE')
        print('SYNC_RESULT '+json.dumps(event),flush=True)
        return
    print(f'New Speckle version {latest}; comparing with dashboard baseline {baseline}',flush=True)
    old=inventory(account,baseline); new=inventory(account,latest)
    added=set(new)-set(old); removed=set(old)-set(new)
    updated={k for k in set(new)&set(old) if new[k]!=old[k]}
    changes=added|removed|updated
    affected=impact_for(changes)
    event.update(status='CHANGE_DETECTED',message='New Speckle version found. Review affected work packages and drawings.',added=len(added),removed=len(removed),metadataModified=len(updated),changedElements=len(changes),geometryOnlyChangesNotAssessed=True,affected=affected,sampleChangedIds=sorted(changes)[:40],requiresReview=True)
    print('SYNC_RESULT '+json.dumps(event),flush=True)
    # Persist the warning immediately, even if mesh export fails.
    (DATA/'latest_sync.json').write_text(json.dumps(event,indent=2),encoding='utf8')
    print('Exporting meshes from latest version; existing mapped dashboard remains on baseline until re-indexed.',flush=True)
    # Exporter uses actual latest version without changing the approved dashboard baseline.
    export(version_id=latest)
    event['meshExport']='DONE'
    event['message']='New version downloaded. Potential impacts need review; existing issue/4D mappings still reference the previous baseline.'
    (DATA/'latest_sync.json').write_text(json.dumps(event,indent=2),encoding='utf8')
    print('SYNC_RESULT '+json.dumps(event),flush=True)

if __name__=='__main__':main()
