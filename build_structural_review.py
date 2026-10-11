"""Build a provisional MEP-to-structure review queue from Speckle AABB broad phase.
No intersections are confirmed; this is NOT mesh collision detection.
Run from prototype root: python build_structural_review.py
"""
import csv, json
from collections import Counter, defaultdict
from pathlib import Path

SOURCE = Path('output/clash_candidates_v3.csv')
BOUNDS = Path('output/geometry_bounds_world.csv')
DEST = Path('output')
DEST.mkdir(exist_ok=True)

def read(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def base_id(x):
    # _tXXXXXXXX... suffix added by Speckle to identify transformed instances.
    # Keep the full ID as primary identifier; base ID is reference-only.
    return x.rsplit('_t', 1)[0] if '_t' in x else x


def main():
    rows=read(SOURCE)
    bounds=read(BOUNDS)
    bound_ids={r['application_id'] for r in bounds}
    chosen=[r for r in rows if r.get('discipline_pair','').endswith('vs Structural')]
    grouped=Counter(r['fabric_category'] for r in chosen)
    summary={
      'scope':'MEP vs Structural, AABB screening only',
      'status':'UNCONFIRMED_AABB_REVIEW_CANDIDATES',
      'source_csv_rows':len(rows),
      'structural_candidate_pairs':len(chosen),
      'by_discipline':dict(Counter(r['discipline_pair'] for r in chosen)),
      'by_structural_category':dict(grouped),
      'unique_structural_elements':len(set(r['fabric_id'] for r in chosen)),
      'unique_mep_elements':len(set(r['mep_id'] for r in chosen)),
      'unmatched_bounds_ids':len({id for r in chosen for id in (r['mep_id'],r['fabric_id']) if id not in bound_ids}),
      'limitations':['No mesh intersection confirmation','World placement must be validated in Revit','AABB overlap volume is not collision penetration volume','Source 10000 rows are incomplete for non-structural comparisons']
    }
    ordered=sorted(chosen,key=lambda r:float(r['overlap_box_volume_m3']),reverse=True)
    out=[]
    for idx,r in enumerate(ordered,1):
        mep=r['mep_category']
        fabric=r['fabric_category']
        kind='Beam/framing coordination' if fabric=='Structural Framing' else ('Foundation coordination' if fabric=='Structural Foundations' else 'Column coordination')
        out.append({
          'review_id':f'STR-{idx:04d}',
          'status':'POTENTIAL_INTERSECTION_UNVERIFIED',
          'review_type':kind,
          'discipline_pair':r['discipline_pair'],
          'mep_category':mep,
          'mep_name':r['mep_name'],
          'mep_id':r['mep_id'],
          'mep_base_application_id':base_id(r['mep_id']),
          'mep_level':r['mep_level'],
          'structural_category':fabric,
          'structural_name':r['fabric_name'],
          'structural_id':r['fabric_id'],
          'structural_base_application_id':base_id(r['fabric_id']),
          'structural_level':r['fabric_level'],
          'aabb_overlap_m3':r['overlap_box_volume_m3'],
          'aabb_overlap_x_m':r['overlap_x_m'],
          'aabb_overlap_y_m':r['overlap_y_m'],
          'aabb_overlap_z_m':r['overlap_z_m'],
          'recommendation':'Verify element geometry and positions; check whether crossing/opening is intentional and approved.'
        })
    if out:
        with (DEST/'structural_review_queue.csv').open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(out[0]));w.writeheader();w.writerows(out)
    (DEST/'structural_review_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    print('Saved output/structural_review_queue.csv and output/structural_review_summary.json')
if __name__=='__main__':main()
