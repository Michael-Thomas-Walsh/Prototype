"""Diagnose AABB quality before running any BIM clash screening.

Reads output/geometry_bounds.csv (no Speckle API calls required).
Outputs output/bounds_diagnostics.json and output/suspicious_boxes.csv.
Does not call any overlaps 'clashes'.
"""
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
INPUT = ROOT / 'output' / 'geometry_bounds.csv'
OUTPUT = ROOT / 'output'
FT_TO_M = 0.3048
MAX_EXAMPLES = 100


def percentile(sorted_values, p):
    if not sorted_values:
        return None
    return sorted_values[round((len(sorted_values)-1)*p)]


def summarise(vals):
    s = sorted(vals)
    return {'min': round(s[0],3), 'median': round(percentile(s,.5),3),
            'p95': round(percentile(s,.95),3), 'p99': round(percentile(s,.99),3),
            'max': round(s[-1],3)} if s else {}


def main():
    if not INPUT.exists():
        raise SystemExit(f'Missing file: {INPUT}')
    by_source = defaultdict(list)
    rejected = []
    all_rows = []
    with INPUT.open(newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            try:
                lo = [float(row['min_'+a]) for a in 'xyz']
                hi = [float(row['max_'+a]) for a in 'xyz']
                if not all(map(math.isfinite,lo+hi)) or any(b<a for a,b in zip(lo,hi)):
                    raise ValueError('invalid bounds')
            except (ValueError, TypeError, KeyError) as ex:
                rejected.append({'application_id':row.get('application_id',''), 'reason':str(ex)})
                continue
            dims_ft = [b-a for a,b in zip(lo,hi)]
            longest_m = max(dims_ft)*FT_TO_M
            volume_m3 = math.prod(dims_ft)*FT_TO_M**3
            source = row.get('category','').split(' / ')[0]
            info = {'application_id':row.get('application_id',''), 'name':row.get('name',''),
                    'category':row.get('category',''), 'level':row.get('level',''),
                    'source':source, 'length_x_m':round(dims_ft[0]*FT_TO_M,3),
                    'length_y_m':round(dims_ft[1]*FT_TO_M,3),
                    'length_z_m':round(dims_ft[2]*FT_TO_M,3),
                    'longest_dimension_m':round(longest_m,3),
                    'box_volume_m3':round(volume_m3,3),
                    'centre_x_m':round((lo[0]+hi[0])/2*FT_TO_M,3),
                    'centre_y_m':round((lo[1]+hi[1])/2*FT_TO_M,3),
                    'centre_z_m':round((lo[2]+hi[2])/2*FT_TO_M,3),
                    'min_x_ft':lo[0], 'max_x_ft':hi[0],
                    'min_y_ft':lo[1], 'max_y_ft':hi[1],
                    'min_z_ft':lo[2], 'max_z_ft':hi[2]}
            by_source[source].append(info)
            all_rows.append(info)
    groups = {}
    for source, entries in sorted(by_source.items()):
        groups[source] = {'count':len(entries),
                          'longest_dimension_m':summarise([e['longest_dimension_m'] for e in entries]),
                          'box_volume_m3':summarise([e['box_volume_m3'] for e in entries]),
                          'over_50m':sum(e['longest_dimension_m']>50 for e in entries),
                          'over_100m':sum(e['longest_dimension_m']>100 for e in entries),
                          'over_500m':sum(e['longest_dimension_m']>500 for e in entries)}
    suspects = sorted(all_rows,key=lambda e:e['box_volume_m3'],reverse=True)[:MAX_EXAMPLES]
    fields = ['application_id','name','source','category','level','length_x_m','length_y_m',
              'length_z_m','longest_dimension_m','box_volume_m3','centre_x_m',
              'centre_y_m','centre_z_m']
    OUTPUT.mkdir(exist_ok=True)
    with (OUTPUT/'suspicious_boxes.csv').open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        w.writerows([{k:v for k,v in e.items() if k in fields} for e in suspects])
    report = {'status':'DIAGNOSTIC_ONLY_NOT_CLASHES','units_input':'ft',
              'total_bounds':len(all_rows), 'invalid_bounds':len(rejected),
              'by_source':groups, 'top_10_largest_boxes':[
                  {k:e[k] for k in ['application_id','name','source','category','longest_dimension_m','box_volume_m3']}
                  for e in suspects[:10]],
              'notes':['AABBs may be inflated for rotated/curved elements or compound geometry.',
                       'Validate coordinate frames and instance transforms before exact clash checks.',
                       'Large dimensions alone are not proof of an invalid bounding box.']}
    (OUTPUT/'bounds_diagnostics.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Loaded',len(all_rows),'boxes; invalid:',len(rejected))
    for source, g in groups.items():
        print(f'{source}: n={g["count"]:,} longest(m) median={g["longest_dimension_m"].get("median")} p99={g["longest_dimension_m"].get("p99")} max={g["longest_dimension_m"].get("max")} >100m={g["over_100m"]}')
    print('Largest boxes:')
    for e in suspects[:10]:
        print(f'  {e["source"]}: {e["name"][:45]} | longest={e["longest_dimension_m"]}m volume={e["box_volume_m3"]}m3')
    print('Saved output/bounds_diagnostics.json and output/suspicious_boxes.csv')

if __name__=='__main__':
    main()
