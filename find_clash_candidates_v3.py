"""Fusion BIM prototype — WORLD-coordinate broad-phase clash candidates.

Reads output/geometry_bounds_world.csv (metres). DOES NOT claim confirmed clashes.
Requires representative Revit placements to have been independently checked.
Uses category-based physical object selection and an X-axis sweep.
Standard-library only. Produces prioritised candidate samples plus complete counts.
"""
import csv
import heapq
import json
import math
from collections import Counter
from pathlib import Path

DATA = Path('output')
INPUT = DATA / 'geometry_bounds_world.csv'
OUT_CSV = DATA / 'clash_candidates_v3.csv'
OUT_JSON = DATA / 'clash_summary_v3.json'
MIN_INTERSECTION_M = 0.01  # 10mm broad-phase overlap along EACH axis
TOP_N = 10000
# Source labels alone do not establish element type. We classify using category path.
MEP = {
    'Pipes': 'Plumbing', 'Pipe Fittings': 'Plumbing', 'Pipe Accessories': 'Plumbing',
    'Flex Pipes': 'Plumbing', 'Plumbing Fixtures': 'Plumbing',
    'Ducts': 'HVAC', 'Duct Fittings': 'HVAC', 'Duct Accessories': 'HVAC',
    'Flex Ducts': 'HVAC', 'Air Terminals': 'HVAC',
    'Conduits': 'Electrical', 'Conduit Fittings': 'Electrical',
    'Cable Trays': 'Electrical', 'Cable Tray Fittings': 'Electrical',
    'Electrical Fixtures': 'Electrical', 'Electrical Equipment': 'Electrical',
}
PHYSICAL = {
    'Walls': 'Architecture', 'Floors': 'Architecture',
    'Ceilings': 'Architecture', 'Roofs': 'Architecture',
    'Structural Framing': 'Structural', 'Structural Columns': 'Structural',
    'Structural Foundations': 'Structural',
}
EXCLUDED = {
    'Spaces', 'Rooms', 'Areas', 'Analytical Surfaces', 'Analytical Spaces',
    'Mass', 'Masses', 'Toposolids', 'Topography', 'Electrical Circuits',
}


def category_parts(raw):
    return [x.strip() for x in raw.split(' / ') if x.strip()]


def classify(row):
    parts = category_parts(row.get('category', ''))
    # source / optional level / REVIT CATEGORY / family type
    if any(part in EXCLUDED for part in parts):
        return None
    for part in parts[1:]:
        if part in MEP:
            return ('MEP', MEP[part], part)
        if part in PHYSICAL:
            return ('Fabric', PHYSICAL[part], part)
    return None


def load():
    if not INPUT.exists():
        raise SystemExit(f'Missing {INPUT}; run extract_geometry_world.py first.')
    boxes, discarded = [], Counter()
    with INPUT.open(newline='', encoding='utf-8-sig') as f:
        rows = csv.DictReader(f)
        needed = {'application_id','category','min_x','min_y','min_z','max_x','max_y','max_z'}
        if not needed.issubset(rows.fieldnames or []):
            raise SystemExit('World CSV is missing required columns: '+str(sorted(needed-set(rows.fieldnames or []))))
        for row in rows:
            cls = classify(row)
            if cls is None:
                discarded['nonphysical_or_out_of_scope'] += 1
                continue
            try:
                v = [float(row[k]) for k in ('min_x','min_y','min_z','max_x','max_y','max_z')]
            except (ValueError,TypeError):
                discarded['bad_numeric_bounds'] += 1
                continue
            if not all(map(math.isfinite, v)):
                discarded['nonfinite_bounds'] += 1
                continue
            size = [v[k+3]-v[k] for k in range(3)]
            if any(s <= 0 for s in size):
                discarded['degenerate_bounds'] += 1
                continue
            boxes.append({'id':row['application_id'], 'name':row.get('name',''),
                          'category':row['category'], 'level':row.get('level',''),
                          'group':cls[0], 'discipline':cls[1], 'revit_category':cls[2],
                          'v':v})
    return boxes, discarded


def analyze(boxes, discarded):
    boxes.sort(key=lambda a: a['v'][0])
    active = []
    top = []
    counts = Counter()
    candidate_count = 0
    x_pairs = 0
    serial = 0
    for i, a in enumerate(boxes):
        xmin = a['v'][0]
        active = [b for b in active if b['v'][3] > xmin + MIN_INTERSECTION_M]
        for b in active:
            if a['group'] == b['group']:
                continue
            x_pairs += 1
            # Verify intersection on all three axes with >=10mm depth
            depth = [min(a['v'][k+3], b['v'][k+3]) - max(a['v'][k], b['v'][k]) for k in range(3)]
            if min(depth) < MIN_INTERSECTION_M:
                continue
            mep = a if a['group']=='MEP' else b
            fabric = b if a['group']=='MEP' else a
            pair = mep['discipline']+' vs '+fabric['discipline']
            counts[pair] += 1
            candidate_count += 1
            # Candidate ordering is a triage heuristic, NOT severity or proof of clash.
            # Geometric overlap volume alone can be misleading for penetrations.
            vol = depth[0]*depth[1]*depth[2]
            serial += 1
            record = {
                'mep_id':mep['id'], 'mep_name':mep['name'],
                'mep_category':mep['revit_category'], 'mep_level':mep['level'],
                'fabric_id':fabric['id'], 'fabric_name':fabric['name'],
                'fabric_category':fabric['revit_category'], 'fabric_level':fabric['level'],
                'discipline_pair':pair, 'overlap_x_m':round(depth[0],4),
                'overlap_y_m':round(depth[1],4), 'overlap_z_m':round(depth[2],4),
                'overlap_box_volume_m3':round(vol,6),
                'status':'UNCONFIRMED_AABB_CANDIDATE',
            }
            if len(top)<TOP_N:
                heapq.heappush(top,(vol,serial,record))
            elif vol>top[0][0]:
                heapq.heapreplace(top,(vol,serial,record))
        active.append(a)
        if (i+1)%4000==0:
            print(f'Processed {i+1:,}/{len(boxes):,} selected objects; candidates so far: {candidate_count:,}')
    ordered = [it[2] for it in sorted(top, key=lambda x:-x[0])]
    DATA.mkdir(exist_ok=True)
    if ordered:
        with OUT_CSV.open('w', newline='', encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(ordered[0]))
            w.writeheader(); w.writerows(ordered)
    summary = {
        'status':'UNCONFIRMED_BROAD_PHASE_ONLY',
        'input_file':str(INPUT), 'coordinate_units':'m',
        'selected_physical_boxes':len(boxes), 'excluded':dict(discarded),
        'x_axis_pairs_checked':x_pairs, 'candidate_pairs_total':candidate_count,
        'candidate_pairs_by_disciplines':dict(counts),
        'candidate_rows_written':len(ordered),
        'csv_is_top_by_overlap_volume_not_complete':candidate_count>TOP_N,
        'minimum_overlap_per_axis_m':MIN_INTERSECTION_M,
        'caution':'World transforms and federation coordinates require Revit validation. AABB intersections are NOT confirmed collisions. Ranking by overlapping box volume is only a rough diagnostic.',
    }
    OUT_JSON.write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    print(f'Saved {OUT_CSV} and {OUT_JSON}')


if __name__=='__main__':
    print('CLASH ENGINE V3 — WORLD-COORDINATE BROAD PHASE')
    b,excluded=load()
    analyze(b,excluded)
