# Fusion BIM Intelligence — runnable prototype v0.1

A local 4D BIM coordination dashboard built around your actual Snowdon Towers Speckle export.

## What's implemented

- **Interactive 3D in your OWN application** (Three.js through React Three Fiber). The rendered model is a **world-coordinate bounding-box proxy** per element, **not actual Revit mesh surfaces**. Click an object to inspect it, zoom target, and view programme mapping.
- **Discipline visibility** for Architecture, Structural, Plumbing, HVAC, Electrical, Facades and Site.
- **Programme**: 103 *fictional* activities generated from actual categories and levels; select a Gantt bar to highlight associated elements in the viewer. Edit start week, duration and progress in the inspector. Move the week slider; enable "4D: show elements scheduled by week" to view construction sequence (schematic scheduling, not verified installed/complete status).
- **Coordination**: 375 *unconfirmed* structural AABB candidate pairs (not actual confirmed clashes). Select an issue to highlight and inspect both participants in your viewer. Review status and comments are editable and stored via API/SQLite, with local browser fallback.
- **Intelligence**: first metrics. Not yet real critical path or risk prediction.

**Important:** Your V4 run reported 35 surface intersection candidates, but you have not yet uploaded `clash_v4_results.csv`. The UI displays **35 as an aggregate only**, not per-issue evidence. Do not confuse the 375 broad-phase rows with 35 V4-confirmed surface candidates.

## Install & run on Windows

Extract this archive to `D:\Fusion_Prototype\fusion_bim_platform`. You can keep your existing Python scripts and `output` directory untouched.

Open **two** PowerShell terminals:

### Terminal 1: API

```powershell
cd D:\Fusion_Prototype\fusion_bim_platform
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\.venv\Scripts\python.exe -m uvicorn backend.app:app --reload --port 8000
```

If your `.venv` is instead inside this folder, change the Python path to `.\.venv\Scripts\python.exe`.

### Terminal 2: Web app

```powershell
cd D:\Fusion_Prototype\fusion_bim_platform\frontend
npm install
npm run dev
```

Open **http://localhost:5173**.

You'll need Node.js 20.19+ or 22.12+ recommended for recent Vite releases. If `npm install` fails, provide the terminal error.

The frontend can still read static demo data when the API is unavailable, but only browser-local fallback is then available for edits.

## Project layout

- `frontend/src/Viewer.tsx`: on-page interactive 3D model.
- `frontend/src/App.tsx`: dashboard, activity selection, Gantt, coordination and 4D.
- `backend/app.py`: FastAPI read/write API and SQLite persistence.
- `data/elements.json`: your actual Speckle element IDs and world-space bounding boxes.
- `data/issues.json`: the 375 structural AABB review candidates.
- `data/programme.json`: fictional activity timeline and element mapping.
- `build_data.py`: rebuild the data files from the latest exports.

## Regenerate data after Speckle changes

Place the updated `geometry_bounds_world.csv` and `fusion_v4/structural_review_queue.csv` in the parent folder, then from the platform root:

```powershell
python build_data.py D:\Fusion_Prototype
Copy-Item .\data\*.json .\frontend\public\data\ -Force
```

The versioned Speckle model currently represented here is `0f3cb45af1 / ee03c40d73 / cb0188d0ef`.

## Limitations and next technical steps

1. **Real geometry**: Implement a Speckle bundle mesh-to-GLB exporter with a per-element GLB node/instance ID table and materials. Replace the AABB proxies with the actual mesh geometry in Viewer.tsx. Because the source CSV contains bounding boxes only, actual mesh surfaces cannot be reconstructed from these CSVs.
2. **V4 evidence**: Import the actual per-pair `clash_v4_results.csv` to label 35 surface-intersection candidates correctly. Keep 340 no-crossing pairs as "not proven clash-free".
3. **Precise coordination**: Implement robust volumetric mesh/solid intersection tests, false-positive rules for penetrations, and review ownership.
4. **Programme**: Add dependency editor, critical path calculation, long-lead items, risk scoring, baselines, revisions, and per-activity assignee.
5. **Scale**: Stream spatial tiles/GLB and fetch properties on demand instead of loading all elements for 30 buildings.
6. **Validation**: Verify coordinate transforms against Revit; non-mesh objects and unknown Speckle relation ID 30 remain unresolved.

No external secrets or personal credentials are bundled. All schedule dates and activity assignments are illustrative and are not sourced from an approved project programme.

## v0.2 — Real Speckle meshes and synthetic TIDP impact view

The dashboard now has a **Coordination → Potential delivery impact** section linking each issue to the fictional work packages, programme activities and drawing deliverables. The `data/delivery_plan.json` register includes 103 illustrative work packages and 206 illustrative drawing deliverables. These are NOT actual issued drawings, an approved TIDP, or verified programme consequences; links are inferred through the original model-to-activity mappings.

The **Actual meshes** checkbox in the viewer activates only once the source Speckle geometry is converted into GLB chunks. Since the provided CSVs contain only bounding boxes, these real meshes must be exported from the authenticated Speckle bundle on your Windows PC. Proxy mode remains available.

From `D:\Fusion_Prototype\fusion_bim_platform` (with the existing parent virtual environment):

```powershell
..\.venv\Scripts\python.exe -m pip install "specklepy[bundle]" numpy trimesh
..\.venv\Scripts\python.exe export_speckle_meshes.py
```

This downloads the pinned model version `cb0188d0ef` using your existing Speckle account and writes actual triangle meshes to `frontend/public/data/meshes/*.glb`, plus `frontend/public/data/mesh_manifest.json`. Files are split into chunks of 250 elements, and geometry node names retain their element IDs for picking and review highlighting. **This export can take a while and require considerable disk space and RAM.** Review the output warnings, validate sample geometry placement against Revit, then restart/refresh your Vite dashboard and enable **Actual meshes**. Large federated models may load slowly; streamed model/LOD handling is planned for a later version.

When installing v0.2 over a working copy, **back up your `prototype.sqlite3` first** so your review statuses and activity edits aren't lost. Extract the archive to `D:\Fusion_Prototype` to update `fusion_bim_platform`. Do not delete the existing `.venv` or your parent `output` folder.

Validation: Python source syntax checked; full GLB conversion and browser build have **not** been executed here against your authenticated Speckle account. Viewer performance and precise picking depend on the exported GLB nodes preserving the element IDs. All V4 surface evidence remains separate unless the corresponding per-issue V4 results CSV is supplied.


## v0.3 — One-click model sync

Start the FastAPI backend and Vite frontend as before. Use the **Sync from Speckle** button in the 3D viewer toolbar. This invokes a single local Python exporter job, streams progress messages, and makes the GLB chunks available through `/api/model-assets`. It requires Speckle login on the backend machine and installed `specklepy[bundle]`, `numpy`, `trimesh`. The exporter can take several minutes, and the backend must remain running. The sync cannot be started twice simultaneously.

New API routes: `POST /api/mesh-sync`, `GET /api/mesh-sync`, `GET /api/mesh-manifest`. These are intended for localhost prototype use; add authentication and access controls before deployment to a network.

## v0.4: Version-aware Speckle sync and impact warnings

The **Check latest Speckle version** button compares the live latest Speckle model version against the dashboard's baseline `data/metadata.json:speckleVersion`.

- If the version is unchanged, reports **Up to date** without re-exporting the meshes.
- If a new version exists, receives both versions' metadata and compares element identities and properties, flags new/deleted/modified elements, and uses existing illustrative model-to-activity/TIDP mappings to identify potentially impacted work packages and drawings. It exports latest meshes while retaining the old baseline reference so that the dashboard does not silently relabel unvalidated analyses.
- A change in Speckle version is a review trigger, *not* proof of a clash or construction delay. Mesh-only differences are not assessed by the metadata diff, and affected drawing associations are fictional. **After a change, rebaseline the element/issue/4D datasets before relying on 3D selections and review calculations.**
- **Demo: Tokamak revision** generates an unmistakably fictional STEP-related equipment-change alert, with fictional package and TIDP identifiers, without changing Speckle or the actual project data.
- The checking backend requires the same authenticated Speckle Python environment as the GLB exporter.

Restart both your FastAPI backend and Vite frontend after installing this update. Project files are packaged under the `fusion_bim_platform/` folder.
