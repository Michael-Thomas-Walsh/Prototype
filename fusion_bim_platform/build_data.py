"""Build prototype assets from the existing world-bounds and structural queue exports."""
import csv,json,re,sys
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parent
SOURCE=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT.parent
DEST=ROOT/'data';DEST.mkdir(exist_ok=True)
BOUNDS=SOURCE/'geometry_bounds_world.csv'
QUEUE=SOURCE/'fusion_v4'/'structural_review_queue.csv'
if not QUEUE.exists(): QUEUE=SOURCE/'structural_review_queue.csv'
if not BOUNDS.exists():raise SystemExit(f'Missing {BOUNDS}')
colmap={'Fusion BIM_revit':'Architecture','Snowdon Towers Sample Facades':'Facades','Snowdon Towers Sample Structural':'Structural','Snowdon Towers Sample Plumbing':'Plumbing','Snowdon Towers Sample HVAC':'HVAC','Snowdon Towers Sample Electrical':'Electrical','Snowdon Towers Sample Site':'Site'}
items=[]; groups=Counter()
with BOUNDS.open(encoding='utf-8-sig',newline='') as f:
 for r in csv.DictReader(f):
  source=r['category'].split(' / ')[0]; discipline=colmap.get(source,'Other');groups[discipline]+=1
  try:
   bb=[round(float(r[k]),4) for k in ('min_x','min_y','min_z','max_x','max_y','max_z')]
  except(ValueError,KeyError):continue
  if not all(abs(x)<1e6 for x in bb):continue
  cat=r['category'].split(' / ')
  items.append({'id':r['application_id'],'baseId':r['application_id'].split('_t')[0], 'name':r['name'],'discipline':discipline,'category':cat[-2] if len(cat)>=2 else cat[-1], 'categoryPath':r['category'],'level':r['level'] or 'Unassigned','bounds':bb})
(DEST/'elements.json').write_text(json.dumps(items,separators=(',',':')),encoding='utf-8')
issues=[]
if QUEUE.exists():
 with QUEUE.open(encoding='utf-8-sig',newline='') as f:
  for r in csv.DictReader(f):
   issues.append({'id':r['review_id'],'mepId':r['mep_id'],'fabricId':r['structural_id'],'mepName':r['mep_name'],'fabricName':r['structural_name'],'pair':r['discipline_pair'],'level':r['mep_level'] or r['structural_level'],'type':r['review_type'],'volume':float(r['aabb_overlap_m3']),'status':'New','evidence':'AABB candidate — mesh intersection unverified','recommendation':r['recommendation']})
(DEST/'issues.json').write_text(json.dumps(issues,separators=(',',':')),encoding='utf-8')
# A transparent, fictional baseline plan, linked to actual extracted objects by category, source and level.
# The dates are illustrative, not actual construction programme data.
activities=[];assignments={}; aidx=0
specs=[('Structural','Structural Foundations','Foundations',0,6),('Structural','Structural Framing','Structural frame',5,15),('Structural','Structural Columns','Structural columns',4,13),('Architecture','Walls','Walls and partitions',10,15),('Architecture','Floors','Floor construction',7,15),('Facades','Curtain','Facade installation',15,15),('HVAC','Ducts','HVAC ductwork',18,13),('HVAC','Mechanical Equipment','HVAC equipment',20,12),('Plumbing','Pipes','Pipework installation',17,16),('Plumbing','Pipe Fittings','Pipe fittings',18,14),('Electrical','Conduits','Electrical containment',20,13),('Electrical','Electrical Equipment','Electrical equipment',23,12)]
by_disc={d:[e for e in items if e['discipline']==d] for d in colmap.values()}
for disc,category,label,base,duration in specs:
 choices=[e for e in by_disc.get(disc,[]) if category.lower() in e['category'].lower() or category.lower() in e['name'].lower()]
 # Do not attach unrelated objects to an activity simply to populate it.
 levels=sorted(set(e['level'] for e in choices if e['level']!='Unassigned'))
 if not levels and choices:levels=['Unassigned']
 for offset,level in enumerate(levels):
  relevant=[e for e in choices if e['level']==level]
  if not relevant:continue
  aidx+=1;aid=f'ACT-{aidx:03d}'
  start=base+min(offset*2,10)
  activities.append({'id':aid,'name':f'{label} · {level}','discipline':disc,'level':level,'start':start,'duration':duration,'progress':0,'predecessors':[],'isSynthetic':True,'elementCount':len(relevant)})
  assignments[aid]=[e['id'] for e in relevant]
# generic commissioning activity remains explicitly unmapped
activities.append({'id':'ACT-COMM','name':'Testing and commissioning','discipline':'All','level':'All','start':38,'duration':8,'progress':0,'predecessors':[],'isSynthetic':True,'elementCount':0})
(DEST/'programme.json').write_text(json.dumps({'assumptions':'Synthetic 46-week construction baseline, rule-linked by source/category/level. NOT an approved programme. Activities may overlap.','activities':activities,'assignments':assignments},separators=(',',':')),encoding='utf-8')
(DEST/'metadata.json').write_text(json.dumps({'source':'Autodesk Snowdon Towers via Speckle','speckleProjectId':'0f3cb45af1','speckleModelId':'ee03c40d73','speckleVersion':'cb0188d0ef','representation':'transformed world-space axis-aligned bounding box proxies (not meshes)','geometryUnits':'metres','counts':dict(groups),'reviewEvidence':'375 AABB structural candidates; V4 reported 35 surface intersection candidates in aggregate but per-pair V4 CSV was not provided'}),encoding='utf-8')
print(f'Prepared {len(items):,} elements, {len(issues)} AABB issues, {len(activities)} synthetic activities; assets in {DEST}')
