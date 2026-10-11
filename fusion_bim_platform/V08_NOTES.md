# V0.8 — GLB coordination focus

- Resolve element identity by walking up the GLB scene-node hierarchy; trimesh often puts the Revit ID on the parent node rather than mesh primitives.
- In actual-mesh mode, do not render the orange AABB highlight substitute.
- In isolation, the two selected meshes stay opaque; other meshes are hidden.
- Report missing selected meshes after all chunks load instead of silently showing boxes.
- Move isolate/exit/close controls to the right-hand side.

Preserve the existing SQLite database and mesh assets when applying this update.
If a missing-ID warning appears, the export may have omitted that object or the scene hierarchy may use an unexpected naming scheme; investigate instead of substituting an AABB.
