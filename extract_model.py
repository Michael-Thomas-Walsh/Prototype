
import csv
import json
from collections import Counter
from pathlib import Path

from specklepy.api import operations
from specklepy.api.client import SpeckleClient
from specklepy.api.credentials import get_default_account

PROJECT_ID = "0f3cb45af1"
MODEL_ID = "ee03c40d73"

account = get_default_account()
if account is None:
    raise RuntimeError("No Speckle account configured")

client = SpeckleClient(host="app.speckle.systems")
client.authenticate_with_account(account)

model_info = client.model.get_with_versions(
    MODEL_ID, PROJECT_ID, versions_limit=1
)
version = model_info.versions.items[0]

print(f"Downloading: {model_info.name}")
print(f"Version: {version.id}")

output = Path("output")
output.mkdir(exist_ok=True)

with operations.receive3(
    account,
    PROJECT_ID,
    MODEL_ID,
    version.id,
    include_geometry=False,
) as model:

    print(f"Units: {model.units}")
    print(f"Objects received: {len(model.objects)}")

    rows = []
    category_counts = Counter()

    for obj in model.objects:
        category = (
            " / ".join(obj.collection_path)
            if obj.collection_path else "Unclassified"
        )

        level = obj.level.name if obj.level else ""

        row = {
            "application_id": obj.application_id,
            "name": obj.name or "",
            "category": category,
            "level": level,
            "host_id": (
                obj.host.application_id
                if obj.host else ""
            ),
            "properties": dict(obj.properties),
        }

        rows.append(row)
        category_counts[category] += 1

    with (output / "elements.json").open(
        "w", encoding="utf-8"
    ) as f:
        json.dump(
            {
                "project_id": PROJECT_ID,
                "model_id": MODEL_ID,
                "version_id": version.id,
                "units": model.units,
                "elements": rows,
            },
            f,
            indent=2,
            default=str,
        )

    with (output / "elements.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "application_id",
                "name",
                "category",
                "level",
                "host_id",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: row[key]
                for key in writer.fieldnames
            })

    print("\nTop categories:")
    for category, count in category_counts.most_common(20):
        print(f"{category}: {count}")

print("\nExport complete.")
print("Saved: output/elements.json")
print("Saved: output/elements.csv")
