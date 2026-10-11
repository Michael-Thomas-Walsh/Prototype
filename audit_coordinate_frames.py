"""Audit local-coordinate artifacts in Speckle-derived bounding boxes.
Usage: python audit_coordinate_frames.py
Does NOT treat bounding-box overlaps as confirmed clashes.
"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

SOURCE = Path('output/geometry_bounds.csv')
REPORT = Path('output/coordinate_audit.json')
SAMPLE = Path('output/repeated_local_bounds.csv')

with SOURCE.open(encoding='utf-8-sig', newline='') as f:
    rows = list(csv.DictReader(f))

coord_fields = ('min_x', 'min_y', 'min_z', 'max_x', 'max_y', 'max_z')
groups = defaultdict(list)
for r in rows:
    name = r.get('category', '').split(' / ')[0].strip() or 'Unknown'
    try:
        # Round to tolerate tiny float parsing differences; in reported model, units are feet.
        key = tuple(round(float(r[k]), 5) for k in coord_fields)
    except (ValueError, KeyError, TypeError):
        continue
    groups[name].append((key,r))

result = {'input_file': str(SOURCE), 'coordinate_unit': 'ft',
          'warning': 'Diagnostic only. Coordinate frame not validated; no spatial clashes can be confirmed.',
          'sources': {}}
examples = []
for name, items in sorted(groups.items()):
    counts = Counter(k for k, _ in items)
    repeated = sum(n for n in counts.values() if n > 1)
    origin = 0
    for key, r in items:
        cx,cy,cz = ((key[i]+key[i+3])/2 for i in range(3))
        if max(abs(cx),abs(cy),abs(cz)) < 1.0:
            origin += 1
    result['sources'][name] = {
       'count': len(items), 'unique_boxes': len(counts),
       'objects_in_repeated_box_groups': repeated,
       'percent_in_repeated_box_groups': round(100*repeated/len(items),1),
       'boxes_centered_within_1ft_of_origin': origin,
       'top_repetition_count': max(counts.values(), default=0)
    }
    topkeys = dict(counts.most_common(10))
    for key, r in items:
        if topkeys.get(key,0) > 1:
            examples.append({
              'source': name, 'application_id':r.get('application_id',''),
              'name': r.get('name',''), 'category':r.get('category',''),
              'identical_box_group_size':topkeys[key],
              **{k:v for k,v in zip(coord_fields,key)}
            })

REPORT.parent.mkdir(parents=True,exist_ok=True)
REPORT.write_text(json.dumps(result,indent=2), encoding='utf-8')
fields = ['source','application_id','name','category','identical_box_group_size',*coord_fields]
with SAMPLE.open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=fields); w.writeheader();w.writerows(examples)
print('Coordinate-frame audit (NOT clash detection):')
for name,s in result['sources'].items():
    print(f"{name}: {s['count']:,} objects; {s['unique_boxes']:,} distinct boxes; "
          f"{s['percent_in_repeated_box_groups']}% in repeated groups; "
          f"max repeat {s['top_repetition_count']}")
print(f'\nSaved {REPORT} and {SAMPLE}')
print('NEXT: extract per-object world transforms before running clash detection.')
