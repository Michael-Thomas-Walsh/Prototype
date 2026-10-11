"""Fusion BIM prototype: inspect Speckle bundle geometry and export candidate AABBs.

Bounding boxes are a coarse spatial index only, NOT confirmed clashes.
Coordinates remain in the source model's coordinate space and units.
"""
import csv
import json
import math
from collections import Counter
from pathlib import Path

from specklepy.api import operations
from specklepy.api.client import SpeckleClient
from specklepy.api.credentials import get_default_account

PROJECT_ID = "0f3cb45af1"
MODEL_ID = "ee03c40d73"
OUTPUT = Path("output")
OUTPUT.mkdir(exist_ok=True)


def points_from_mesh(mesh):
    """Accept flat xyz vertex streams or Nx3 vertex arrays; fail clearly otherwise."""
    vertices = getattr(mesh, "vertices", None)
    if vertices is None:
        vertices = getattr(mesh, "positions", None)
    if vertices is None:
        raise ValueError(f"Decoded mesh {type(mesh).__name__} has no vertices/positions; attributes: {sorted(x for x in dir(mesh) if not x.startswith('_'))[:35]}")
    if hasattr(vertices, "tolist"):
        vertices = vertices.tolist()
    if len(vertices) == 0:
        return []
    if isinstance(vertices[0], (tuple, list)):
        return [(float(v[0]), float(v[1]), float(v[2])) for v in vertices]
    if len(vertices) % 3 != 0:
        raise ValueError("Vertex stream is not a multiple of 3")
    return [(float(vertices[i]), float(vertices[i + 1]), float(vertices[i + 2])) for i in range(0, len(vertices), 3)]


def category_of(obj):
    return " / ".join(obj.collection_path or []) or "Unclassified"


def main():
    account = get_default_account()
    if account is None:
        raise RuntimeError("No Speckle account found. Sign in to Speckle first.")
    client = SpeckleClient(host="app.speckle.systems")
    client.authenticate_with_account(account)
    model_info = client.model.get_with_versions(MODEL_ID, PROJECT_ID, versions_limit=1)
    if not model_info.versions.items:
        raise RuntimeError("No published versions found")
    version = model_info.versions.items[0]
    print(f"Receiving geometry: {model_info.name} version {version.id}")
    print("This may be a considerably larger download than the metadata-only extraction.")

    rows = []
    errors = []
    geometry_types = Counter()
    total_pieces = 0
    with operations.receive3(account, PROJECT_ID, MODEL_ID, version.id, include_geometry=True) as model:
        print(f"Objects: {len(model.objects):,} | units: {model.units}")
        print(f"Unrecognised relationship types: {sorted(model.unknown_relations)}")
        for n, obj in enumerate(model.objects, 1):
            pieces = obj.geometries
            if not pieces:
                continue
            mins = [math.inf, math.inf, math.inf]
            maxs = [-math.inf, -math.inf, -math.inf]
            vertex_count = 0
            decoded = 0
            for geo in pieces:
                total_pieces += 1
                geometry_types[str(geo.type)] += 1
                try:
                    mesh = geo.decode_mesh()
                    pts = points_from_mesh(mesh)
                    if not pts:
                        continue
                    for p in pts:
                        if not all(math.isfinite(v) for v in p):
                            continue
                        for axis in range(3):
                            mins[axis] = min(mins[axis], p[axis])
                            maxs[axis] = max(maxs[axis], p[axis])
                    decoded += 1
                    vertex_count += len(pts)
                except Exception as exc:
                    if len(errors) < 30:
                        errors.append({"application_id": obj.application_id, "geometry_type": str(geo.type), "error": str(exc)[:250]})
            if decoded and all(math.isfinite(x) for x in mins + maxs):
                rows.append({
                    "application_id": obj.application_id,
                    "name": obj.name or "",
                    "category": category_of(obj),
                    "level": obj.level.name if obj.level else "",
                    "min_x": mins[0], "min_y": mins[1], "min_z": mins[2],
                    "max_x": maxs[0], "max_y": maxs[1], "max_z": maxs[2],
                    "mesh_parts": decoded, "vertices": vertex_count,
                })
            if n % 2000 == 0:
                print(f"Processed {n:,}/{len(model.objects):,} | bounding boxes: {len(rows):,}")
        summary = {
            "project_id": PROJECT_ID, "model_id": MODEL_ID, "version_id": version.id,
            "units": model.units, "total_objects": len(model.objects),
            "bounding_boxes": len(rows), "geometry_pieces": total_pieces,
            "geometry_types": dict(geometry_types),
            "unknown_relation_ids": sorted(model.unknown_relations),
            "sample_errors": errors,
            "caution": "Axis-aligned candidate bounds only, not verified clashes. Confirm placement and coordinate transformations against Speckle/Revit before spatial analysis."
        }
    with (OUTPUT / "geometry_bounds.csv").open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["application_id", "name", "category", "level", "min_x", "min_y", "min_z", "max_x", "max_y", "max_z", "mesh_parts", "vertices"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (OUTPUT / "geometry_report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\nGeometry summary:")
    print(json.dumps(summary, indent=2))
    print("\nSaved output/geometry_bounds.csv and output/geometry_report.json")


if __name__ == "__main__":
    main()
