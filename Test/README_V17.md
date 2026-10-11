# Fusion BIM Intelligence v0.17 — Engineering decisions and project memory

Fusion should help engineers understand what matters, make informed decisions, document why, and preserve the knowledge beyond the project.

## Install into your existing prototype

This is an updated **overlay**, not the complete earlier BIM application. Back up your project, then merge `fusion_bim_platform/` into `D:\Fusion_Prototype\fusion_bim_platform`. Preserve your existing data, GLBs, databases and earlier modules. If your local `backend/app.py` or `frontend/src/App.tsx` differs from the supplied v16 overlay, merge their changes rather than blindly overwriting them.

From the project folder, install `requirements-v17.txt` into your chosen Python 3.12 environment. Restart the existing backend and frontend. The existing database is migrated additively; legacy decisions remain intact and unversioned evidence is labelled incomplete.

## Standalone workbench included

You can also run and inspect the new decision, circulation and graph workspaces without the missing earlier BIM modules:

```powershell
cd D:\Fusion_Prototype\fusion_bim_platform
.\start_workbench.ps1
```

Requires Python 3.12 and Node.js 20+. Open `http://127.0.0.1:5173`. The launcher starts `backend.decision_app`, which deliberately excludes the earlier BIM viewer and QA modules. Stop an existing service on port 8000 or 5173 before starting it.

To allow explicitly **unverified local demonstration approvals**:

```powershell
.\start_workbench.ps1 -DemoApprovals
```

For named, role-controlled review events instead, set `FUSION_REVIEWERS_JSON` to a JSON object mapping random reviewer tokens to `{"name":"Reviewer name","role":"approver"}` or `{"name":"Reviewer name","role":"reviewer"}`. Enter the token under Reviewer access in the decision workspace. Tokens stay in frontend memory. These token checks protect ledger mutations and approval authority; they are **not** tenant authentication or read-access security. Bind this prototype to localhost. A shared deployment still requires an authenticated gateway, project authorisation, TLS, backups and protected audit storage.

## Neo4j graph database

The package includes a real Neo4j persistence adapter, scoped graph imports and bounded database-side traversal. SQLite snapshots allow local use without a database service; the UI clearly identifies the active engine. When Neo4j is configured and unavailable, graph operations fail explicitly rather than falling back silently.

With Docker Desktop running, in the same PowerShell session used to launch the backend:

```powershell
$env:FUSION_NEO4J_PASSWORD = 'replace-with-your-own-long-password'
docker compose -f compose.graph.yml up -d
$env:FUSION_NEO4J_URI = 'bolt://127.0.0.1:7687'
$env:FUSION_NEO4J_USER = 'neo4j'
.\start_workbench.ps1
```

Graph data persists in the Docker volume. Publish decision or spatial graphs after connecting. Existing SQLite snapshots are not automatically migrated; reimport/publish their original immutable revisions to populate Neo4j. Decision graphs are explicit snapshots; republish after changing decisions. Source and revision are mandatory on relationships. Evidence type, extraction/inference status and relationship reason stay visible.

## What changed

- Decision workspace is the default landing view, with review priority and “why it matters”.
- Create a decision directly from a selected coordination issue, retaining element IDs, the issue fingerprint and available local mesh-manifest evidence.
- Alternatives, assumptions, acceptance criteria, constraints, lessons and reuse conditions are first-class fields.
- Separate workflow status from evidence validity. Registered source changes flag stale evidence without erasing historic approval.
- Successful Speckle mesh synchronisation reconciles registered local mesh-manifest evidence. The evidence panel also supports explicit source reconciliation.
- Strict review transitions, optimistic concurrency, approval authority, required model evidence, replacement evidence and explicit supersession links.
- Implementation verification, observed outcomes and lessons are separate historical events.
- Indexed full-text decision/history search with pagination and no previous 4,000-record cutoff.
- Persistent graph snapshots and Neo4j graph database support, with decision/evidence/element/issue/event relationships.
- TopologicPy kernel graph construction and validation of declared space adjacency.
- Circulation analysis for multiple journeys, directionality, parallel doors, accessible profiles, unknown or insufficient width, portal closures, weighted route alternatives, reachable exits, user-selected distance thresholds, cut-portal bottlenecks and affected occupants.
- Reproducible circulation scenario records can create evidence-linked decisions and publish spatial relationships to the graph.
- Weighted QA maturity calculation now honours rule weights.
- Removed invented programme dependencies from the CPM endpoint; it now requires explicit dependency data.
- Issue and programme saves no longer silently fall back to browser storage. Failed saves remain visibly unsaved.
- New standalone workbench, setup instructions and focused regression tests.

## Demonstration

1. Open Circulation and choose **Load labelled demonstration**.
2. Block D-001 and select **Compare scenario**. The general journey reroutes; the accessible journey loses its route.
3. Select **Validate Topologic graph** to run the actual kernel conversion.
4. Select **Create decision from this scenario**, complete the decision and rationale, then save.
5. Submit for review and approve using an authorised token or explicit local demonstration mode.
6. In Source revisions, register `circulation-model` at `DEMO-SPATIAL-02`. The earlier approval remains recorded, but its evidence becomes stale. This is a labelled registry demonstration; it does not fabricate a revised BIM model.
7. In Knowledge graph, publish the decision graph and explore the displayed decision ID. Publish spatial graphs from Circulation and explore a space ID such as LAB.

## Data exchange

`examples/spatial_demo.json` is a complete, clearly synthetic import example. The backend's OpenAPI at `/docs` provides the validated request schemas for spatial models, graph snapshots and decision evidence. Source IDs must be namespaced consistently by source document and occurrence; this overlay does not repair arbitrary historical identity mappings.

Real circulation imports require declared spaces, portals, route distances, accessibility and journey endpoints. TopologicPy validates a kernel graph of those declarations; it does not infer complete navigable geometry from arbitrary Revit/Speckle meshes. Parallel doors remain distinct in the NetworkX routing representation. No fabricated connections are added.

## Verification and limits

- 20 focused backend tests passed, including actual TopologicPy kernel conversion, weighted QA scoring, stale-evidence/revalidation, concurrency, approval authority, legacy migration, source conflicts, search, spatial reachability and graph integrity.
- Live Neo4j 5.26 integration verified import, idempotent reimport, scoped neighbourhood traversal and persistence across driver reconnect.
- New React components passed strict TypeScript checks and the standalone Vite production build. Updated App.tsx passed syntax compilation.
- Automated browser visual testing was blocked by this execution environment's browser socket restrictions. No claim of a completed visual browser test is made.
- The full pre-existing BIM platform could not be run: the uploaded overlay omits the older viewer, sync, geometry, delivery and CPM modules and their data. Validate the merged application locally before replacing your working installation.
- Source fingerprints flag changes; they do not certify extraction completeness, model identity or sheet visibility.
- Circulation provides design-review screening. Route alternatives can share portals; their number does not establish independent compliant escape routes. It does not simulate smoke, evacuation flow, door swing, compartmentation or capacity, or certify regulatory compliance.
- No ACC, ANSYS, OpenMC or Primavera integration has been added. Programme dates and dependencies must be supplied explicitly.
- SQLite event storage is application-append-only, not tamper-proof. No blockchain or cryptographic audit-chain claim is made.

## Tests

```powershell
python -m pytest -q
cd workbench
npm ci
npx tsc --noEmit
npm run build
node check-syntax.cjs
```
