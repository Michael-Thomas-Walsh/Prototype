"""First-pass category-aware review of the Speckle element inventory.
Run from the project directory using the virtual environment Python.
Writes output/review_issues.csv and output/review_summary.json.
These are review flags, NOT confirmed design defects.
"""
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'output' / 'elements.json'
DEST = ROOT / 'output'
DEST.mkdir(exist_ok=True)
model = json.loads(SOURCE.read_text(encoding='utf-8'))
elements = model['elements']
issues = []

SYSTEM = 'Parameters.Instance Parameters.Mechanical.System Name'
SHEET = 'Parameters.Instance Parameters.Identity Data.Sheet Number'


def flag(obj, rule, severity, message):
    issues.append({
        'issue_id': f'REV-{len(issues)+1:05d}',
        'rule': rule,
        'severity': severity,
        'element_id': obj.get('application_id', ''),
        'name': obj.get('name', ''),
        'category': obj.get('category', ''),
        'level': obj.get('level', ''),
        'message': message,
        'status': 'Needs review',
    })

sheets = {}
for obj in elements:
    category = obj.get('category', '')
    props = obj.get('properties') or {}
    parts = category.split(' / ')
    # Collection categories: source / optional level / category / optional type
    family = parts[-2] if len(parts) >= 3 else ''
    if family == 'Sheets':
        number = str(props.get(SHEET, '') or '').strip()
        if not number:
            flag(obj, 'SHEET_NUMBER_EMPTY', 'Medium', 'Sheet has no sheet number')
        elif number in sheets:
            flag(obj, 'SHEET_NUMBER_COLLISION', 'Info',
                 f'Sheet number {number} also occurs in this federation; verify whether cross-model numbering is intentional')
        else:
            sheets[number] = obj['application_id']
    if family in {'Pipes', 'Ducts'}:
        if not str(props.get(SYSTEM, '') or '').strip():
            flag(obj, 'MEP_SYSTEM_UNASSIGNED', 'Medium',
                 f'{family[:-1]} has no exported mechanical system name; verify in Revit')
        if not obj.get('level'):
            flag(obj, 'MEP_LEVEL_UNASSIGNED', 'Low',
                 f'{family[:-1]} has no resolved level in this export; verify level assignment')

fields = ['issue_id','rule','severity','element_id','name','category','level','message','status']
with (DEST/'review_issues.csv').open('w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(issues)
summary = {'model_id': model['model_id'], 'version_id': model['version_id'],
           'total_elements': len(elements), 'issue_count': len(issues),
           'by_rule': dict(Counter(x['rule'] for x in issues)),
           'note': 'Flags are potential metadata review items, not confirmed defects.'}
(DEST/'review_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
print(json.dumps(summary, indent=2))
