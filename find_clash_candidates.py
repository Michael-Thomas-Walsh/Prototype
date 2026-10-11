"""Fusion BIM: fast, conservative AABB clash-candidate screening.

Input: output/geometry_bounds.csv from extract_geometry.py
Output: output/clash_candidates.csv and output/clash_summary.json

IMPORTANT: These are bounding-box intersections, NOT verified solid clashes.
Coordinates must share the same aligned model frame. Units assumed feet as
reported by the current Speckle model. Never use as an automated design signoff.
"""
import csv
import heapq
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'output'
INPUT = OUTPUT / 'geometry_bounds.csv'

# To reject mere edge-touch and numerical noise. AABB overlap in each axis.
MIN_OVERLAP_FT = 0.01  # 3.048 mm
# Preliminary pipeline intentionally targets services vs building/structure.
SERVICES = {'Snowdon Towers Sample Plumbing': 'Plumbing',
            'Snowdon Towers Sample HVAC': 'HVAC',
            'Snowdon Towers Sample Electrical': 'Electrical'}
TARGETS = {'Snowdon Towers Sample Structural': 'Structural',
           'Fusion BIM_revit': 'Architecture'}
# Physical building fabric only: avoid sheets, grids, analytical objects etc.
TARGET_TERMS = ('Walls', 'Floors', 'Structural Columns', 'Structural Framing',
                'Columns', 'Roofs', 'Ceilings', 'Foundations')
SERVICE_TERMS = ('Pipes', 'Pipe Fittings', 'Ducts', 'Duct Fittings',
                 'Cable Trays', 'Cable Tray Fittings', 'Conduits',
                 'Conduit Fittings', 'Mechanical Equipment',
                 'Electrical Equipment')
# Narrow broad-phase false positives: reject oversized element-wide bounds.
# Disable or raise if giant physical elements need checking.
MAX_BOX_VOLUME_FT3 = 1e8
MAX_RESULTS = 100000


def kind(row):
    parts = row['category'].split(' / ')
    source = parts[0].strip()
    if source in SERVICES and any(s in parts for s in SERVICE_TERMS):
        return 'service', SERVICES[source]
    if source in TARGETS and any(s in parts for s in TARGET_TERMS):
        return 'target', TARGETS[source]
    # Some structural items have level as part[1]; category match anywhere.
    return None, None


def load():
    entries = []
    excluded = Counter()
    with INPUT.open(newline='', encoding='utf-8-sig') as handle:
        for row in csv.DictReader(handle):
            role, discipline = kind(row)
            if role is None:
                excluded['nonphysical_or_out_of_scope'] += 1
                continue
            try:
                lo = tuple(float(row['min_'+c]) for c in 'xyz')
                hi = tuple(float(row['max_'+c]) for c in 'xyz')
                if not all(math.isfinite(a) for a in lo+hi):
                    raise ValueError('nonfinite')
                dims = [b-a for a,b in zip(lo,hi)]
                if any(d < MIN_OVERLAP_FT for d in dims):
                    excluded['thin_or_degenerate_box'] += 1
                    continue
                if math.prod(dims) > MAX_BOX_VOLUME_FT3:
                    excluded['oversized_box'] += 1
                    continue
            except (ValueError, TypeError, KeyError):
                excluded['invalid_box'] += 1
                continue
            entries.append({'id':row['application_id'], 'name':row['name'],
                            'category':row['category'], 'level':row['level'],
                            'role':role, 'discipline':discipline,
                            'min':lo, 'max':hi})
    return entries, excluded


def overlap(a,b):
    sizes = [min(a['max'][i],b['max'][i])-max(a['min'][i],b['min'][i]) for i in range(3)]
    return sizes if min(sizes) > MIN_OVERLAP_FT else None


def main():
    if not INPUT.exists():
        raise SystemExit(f'Missing {INPUT}. Run extract_geometry.py first.')
    boxes, excluded = load()
    # Sweep along X. Active set only holds boxes not yet ended in X.
    # No third-party spatial indexing dependency required.
    boxes.sort(key=lambda b:b['min'][0])
    active = {}
    endings = []
    result = []
    checked = 0
    counts = Counter()
    for n, box in enumerate(boxes):
        start_x=box['min'][0]
        while endings and endings[0][0] <= start_x+MIN_OVERLAP_FT:
            _, old_index = heapq.heappop(endings)
            active.pop(old_index, None)
        for other in active.values():
            if box['role'] == other['role']:
                continue
            checked += 1
            spans = overlap(box,other)
            if spans is None:
                continue
            service = box if box['role']=='service' else other
            target = other if box['role']=='service' else box
            counts[f"{service['discipline']} vs {target['discipline']}"] += 1
            if len(result) < MAX_RESULTS:
                result.append({
                    'service_id':service['id'], 'service_name':service['name'],
                    'service_discipline':service['discipline'],
                    'service_category':service['category'],
                    'target_id':target['id'], 'target_name':target['name'],
                    'target_discipline':target['discipline'],
                    'target_category':target['category'],
                    'service_level':service['level'], 'target_level':target['level'],
                    'overlap_x_ft':round(spans[0],4),
                    'overlap_y_ft':round(spans[1],4),
                    'overlap_z_ft':round(spans[2],4),
                    'overlap_box_ft3':round(math.prod(spans),5),
                    'review_status':'UNVERIFIED_AABB_OVERLAP'
                })
        active[n]=box
        heapq.heappush(endings,(box['max'][0],n))
    OUTPUT.mkdir(exist_ok=True)
    fields = ['service_id','service_name','service_discipline','service_category',
              'target_id','target_name','target_discipline','target_category',
              'service_level','target_level','overlap_x_ft','overlap_y_ft',
              'overlap_z_ft','overlap_box_ft3','review_status']
    with (OUTPUT/'clash_candidates.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        writer.writerows(result)
    report = {
        'status':'BROAD_PHASE_ONLY_NOT_CONFIRMED_CLASHES',
        'note':'Boxes need transform validation against Revit/Speckle; overlaps include penetrations and intentional contact.',
        'input_boxes':len(boxes), 'excluded':dict(excluded),
        'x_overlap_pairs_checked':checked,
        'candidate_pairs_total':sum(counts.values()),
        'candidate_rows_written':len(result),
        'truncated':sum(counts.values())>MAX_RESULTS,
        'candidate_pairs_by_disciplines':dict(counts),
        'minimum_overlap_ft_per_axis':MIN_OVERLAP_FT,
    }
    (OUTPUT/'clash_summary.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    print('Saved output/clash_candidates.csv and output/clash_summary.json')

if __name__=='__main__':
    main()
