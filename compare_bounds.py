
import csv
from collections import Counter, defaultdict
from pathlib import Path

folder = Path("output")

def load(filename):
    with (folder / filename).open(
        encoding="utf-8-sig", newline=""
    ) as f:
        return list(csv.DictReader(f))

old = load("geometry_bounds.csv")
new = load("geometry_bounds_world.csv")

def stats(rows):
    groups = defaultdict(list)

    for row in rows:
        category = row["category"].split(" / ")[0]

        box = tuple(
            round(float(row[k]), 4)
            for k in (
                "min_x", "min_y", "min_z",
                "max_x", "max_y", "max_z"
            )
        )
        groups[category].append(box)

    result = {}
    for category, boxes in groups.items():
        counts = Counter(boxes)
        repeated = sum(
            count for count in counts.values()
            if count > 1
        )

        result[category] = {
            "objects": len(boxes),
            "unique_boxes": len(counts),
            "repeated_pct": round(
                100 * repeated / len(boxes), 1
            ),
            "max_repeat": max(counts.values())
        }

    return result

before = stats(old)
after = stats(new)

print("\nCOORDINATE COMPARISON")
print("-" * 75)

for source in sorted(set(before) | set(after)):
    a = before.get(source, {})
    b = after.get(source, {})

    print(f"\n{source}")
    print(
        f"  Before: {a.get('repeated_pct', 0)}% "
        f"repeated, max {a.get('max_repeat', 0)}"
    )
    print(
        f"  After:  {b.get('repeated_pct', 0)}% "
        f"repeated, max {b.get('max_repeat', 0)}"
    )
