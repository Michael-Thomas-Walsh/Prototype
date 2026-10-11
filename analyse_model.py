
import json
import csv
from pathlib import Path
from collections import Counter, defaultdict

OUTPUT = Path("output")

with open(OUTPUT / "elements.json", encoding="utf-8") as f:
    data = json.load(f)

elements = data["elements"]
print(f"Loaded {len(elements):,} elements")

# Build a unique element index
by_id = defaultdict(list)
categories = Counter()
levels = Counter()
disciplines = Counter()

for obj in elements:
    element_id = str(obj.get("application_id") or "").strip()
    category = str(obj.get("category") or "Unclassified")
    level = str(obj.get("level") or "")

    if element_id:
        by_id[element_id].append(obj)

    categories[category] += 1
    levels[level or "Unassigned"] += 1

    # Dataset labels only, not verified disciplines
    source = category.split(" / ")[0]
    disciplines[source] += 1

# Initial graph: verified host references only
nodes = []
edges = []
missing_ids = []
unresolved_hosts = []

for index, obj in enumerate(elements):
    element_id = str(obj.get("application_id") or "").strip()
    host_id = str(obj.get("host_id") or "").strip()

    node_id = f"element:{index}"

    nodes.append({
        "node_id": node_id,
        "application_id": element_id,
        "name": obj.get("name") or "",
        "category": obj.get("category") or "",
        "level": obj.get("level") or ""
    })

    if not element_id:
        missing_ids.append(index)

    if host_id:
        matches = by_id.get(host_id, [])

        if len(matches) == 1:
            host_index = next(
                i for i, item in enumerate(elements)
                if item is matches[0]
            )
            edges.append({
                "source": node_id,
                "target": f"element:{host_index}",
                "relationship": "HOSTED_BY"
            })
        else:
            unresolved_hosts.append({
                "element_index": index,
                "host_id": host_id,
                "matches": len(matches)
            })

def write_csv(filename, rows, fields):
    with open(OUTPUT / filename, "w",
              newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

write_csv(
    "graph_nodes.csv", nodes,
    ["node_id", "application_id", "name",
     "category", "level"]
)

write_csv(
    "graph_edges.csv", edges,
    ["source", "target", "relationship"]
)

duplicate_ids = {
    k: len(v) for k, v in by_id.items()
    if len(v) > 1
}

report = {
    "total_objects": len(elements),
    "unique_nonempty_ids": len(by_id),
    "objects_missing_ids": len(missing_ids),
    "duplicate_application_ids": duplicate_ids,
    "resolved_host_edges": len(edges),
    "unresolved_host_references": unresolved_hosts,
    "dataset_groups": dict(disciplines),
    "levels": dict(levels),
    "top_categories": categories.most_common(30)
}

with open(OUTPUT / "model_report.json", "w",
          encoding="utf-8") as f:
    json.dump(report, f, indent=2)

print("\n--- MODEL ANALYSIS ---")
print("Objects:", len(elements))
print("Unique IDs:", len(by_id))
print("Missing IDs:", len(missing_ids))
print("Duplicate IDs:", len(duplicate_ids))
print("Resolved host relationships:", len(edges))
print("Unresolved host references:", len(unresolved_hosts))

print("\nDataset groups:")
for name, count in disciplines.most_common():
    print(f"  {name}: {count}")

print("\nFiles created:")
print("  output/graph_nodes.csv")
print("  output/graph_edges.csv")
print("  output/model_report.json")
