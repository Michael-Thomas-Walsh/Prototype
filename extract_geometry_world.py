"""Fusion BIM: Speckle bundle mesh bounds in world coordinates (diagnostic V2).

Usage: python extract_geometry_world.py (use project virtual environment)
Outputs: output/geometry_bounds_world.csv, output/geometry_world_report.json

Do not use for physical clash declarations until sample positions are verified.
Speckle ModelGeometry.transform contains the composed instance placement when present.
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
OUT = Path("output")
OUT.mkdir(exist_ok=True)

UNIT_TO_METRES = {"m": 1.0, "mm": 0.001, "cm": 0.01, "ft": 0.3048, "in": 0.0254}
FIELDS = ["application_id", "name", "category", "level", "min_x", "min_y", "min_z", "max_x", "max_y", "max_z", "mesh_parts", "vertices", "placed_parts", "unplaced_parts"]


def mesh_points(mesh):
    vs = getattr(mesh, "vertices", None)
    if vs is None:
        vs = getattr(mesh, "positions", None)
    if vs is None:
        raise ValueError("Decoded mesh has no vertices/positions")
    if hasattr(vs, "tolist"):
        vs = vs.tolist()
    if not len(vs):
        return []
    if isinstance(vs[0], (list, tuple)):
        return [(float(v[0]), float(v[1]), float(v[2])) for v in vs]
    if len(vs) % 3:
        raise ValueError("Invalid flat XYZ vertex stream")
    return [(float(vs[i]), float(vs[i+1]), float(vs[i+2])) for i in range(0, len(vs), 3)]


def point_transform(p, transform):
    """Use row-major 4x4 column-vector affine matrix, per Speckle bundle authoring.

    Fail closed when the flattened matrix cannot be interpreted consistently.
    """
    if transform is None:
        return p
    t = list(transform)
    if len(t) != 16 or not all(math.isfinite(float(v)) for v in t):
        raise ValueError("Transform must contain 16 finite values")
    t = [float(v) for v in t]
    if any(abs(t[k] - v) > 1e-7 for k, v in ((12, 0), (13, 0), (14, 0), (15, 1))):
        raise ValueError("Unexpected transform layout/non-affine last row; inspect SDK matrix convention")
    x, y, z = p
    return (t[0]*x + t[1]*y + t[2]*z + t[3],
            t[4]*x + t[5]*y + t[6]*z + t[7],
            t[8]*x + t[9]*y + t[10]*z + t[11])


def main():
    account = get_default_account()
    if account is None:
        raise RuntimeError("No default Speckle account is configured")
    client = SpeckleClient(host="app.speckle.systems")
    client.authenticate_with_account(account)
    model_info = client.model.get_with_versions(MODEL_ID, PROJECT_ID, versions_limit=1)
    version = model_info.versions.items[0]
    print("Receiving:", model_info.name, version.id)
    rows, problems, counts, transform_examples = [], [], Counter(), []
    with operations.receive3(account, PROJECT_ID, MODEL_ID, version.id, include_geometry=True) as model:
        scale = UNIT_TO_METRES.get(str(model.units).lower())
        if scale is None:
            raise ValueError(f"Unknown source model units: {model.units!r}")
        print("Objects:", len(model.objects), "units:", model.units)
        for n, obj in enumerate(model.objects, 1):
            mins = [math.inf] * 3
            maxs = [-math.inf] * 3
            pieces_ok = vertices = placed_parts = unplaced_parts = 0
            failed = False
            for geo in obj.geometries or []:
                typ = str(geo.type).lower()
                counts["geometry_total"] += 1
                if "mesh" not in typ:
                    counts["nonmesh_skipped"] += 1
                    continue
                try:
                    transform = getattr(geo, "transform", None)
                    pts = mesh_points(geo.decode_mesh())
                    if not pts:
                        continue
                    if transform is not None:
                        placed_parts += 1
                        counts["mesh_with_transform"] += 1
                        if len(transform_examples) < 8:
                            transform_examples.append({"application_id": obj.application_id, "matrix": list(transform)})
                    else:
                        unplaced_parts += 1
                        counts["mesh_without_transform"] += 1
                    for p in pts:
                        q = point_transform(p, transform)
                        if not all(math.isfinite(v) for v in q):
                            raise ValueError("Nonfinite transformed vertex")
                        for axis in range(3):
                            mins[axis] = min(mins[axis], q[axis] * scale)
                            maxs[axis] = max(maxs[axis], q[axis] * scale)
                    pieces_ok += 1
                    vertices += len(pts)
                except Exception as exc:
                    failed = True
                    counts["mesh_errors"] += 1
                    if len(problems) < 60:
                        problems.append({"application_id": obj.application_id, "geometry_type": str(geo.type), "error": str(exc)[:300]})
            if failed:
                counts["objects_with_failed_meshes_excluded"] += 1
                # Never publish incomplete bounds as reliable world AABBs.
                continue
            if pieces_ok and all(math.isfinite(v) for v in mins + maxs):
                path = getattr(obj, "collection_path", None) or []
                rows.append({
                    "application_id": obj.application_id, "name": obj.name or "",
                    "category": " / ".join(path) or "Unclassified",
                    "level": obj.level.name if obj.level else "",
                    **dict(zip(FIELDS[4:10], mins + maxs)),
                    "mesh_parts": pieces_ok, "vertices": vertices,
                    "placed_parts": placed_parts, "unplaced_parts": unplaced_parts,
                })
            if n % 2000 == 0:
                print(f"Processed {n:,}/{len(model.objects):,} objects | {len(rows):,} world bounds")
        summary = {
            "project_id": PROJECT_ID, "model_id": MODEL_ID,
            "version_id": version.id, "source_units": str(model.units), "output_units": "m",
            "total_objects": len(model.objects), "world_boxes": len(rows),
            "counts": dict(counts), "transform_examples": transform_examples,
            "unknown_relation_ids": sorted(model.unknown_relations),
            "sample_errors": problems,
            "status": "UNVALIDATED_WORLD_BOUNDS_NOT_CONFIRMED_CLASHES",
            "caution": "Bundle ModelGeometry.transform is treated as a composed row-major affine placement. Compare known element locations with Revit/Speckle before spatial testing. Meshless objects intentionally omitted. A missing transform is taken as identity.",
        }
    with (OUT / "geometry_bounds_world.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "geometry_world_report.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("transform_examples", "sample_errors")}, indent=2))
    print("Saved output/geometry_bounds_world.csv and output/geometry_world_report.json")


if __name__ == "__main__":
    main()
