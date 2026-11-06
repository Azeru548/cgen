# ARCHITECTURE — cgen

Source of truth for how cgen fits together. `README.md` is the pipeline
contract, `PRODUCT.md` the product scope, `DESIGN.md` the visual system.
`DESIGN.md` (Precision Bench) wins over any older design notes.

## Pipeline

```text
prompt → Groq JSON-only spec → Pydantic validation → CadQuery → STEP/STL
```

- `backend/app/ai/groq_client.py`: Groq (`openai/gpt-oss-120b`, temp 0,
  `json_object`). Never emits code. Part specs (`3d_part` v3.2) or assembly
  plans (`3d_assembly` v4.0, registry types only).
- `backend/app/cad/schema.py` (v3.2): `box/cylinder/cone/sphere/torus/
  polygon_prism + union/cut/intersect + part{build,features≤4}`.
  Caps: depth ≤ 4, nodes ≤ 15. `extra=forbid`.
- `backend/app/cad/assembly.py` (v4.0) + `cad/registry.py`: `Component{id
  slug, type, params, transform{pos±10000, rot±360}, visible,
  instances≤12, relationships≤8, generated?}`, `MAX_COMPONENTS=24`.
  Deterministic factories + `mounting_points_local()` for relationships.
- `backend/app/cad/cadquery_engine.py`: origin-centered mm geometry, fixed
  feature order (hole→pattern→grid→shell→chamfer→fillet), through-hole
  auto-extend, export validation (`ISO-10303` / STL ascii+binary checks).
- `backend/app/services/generation.py + assembly.py`: orchestration + diff
  guards. Modify: numeric retune + feature-add OK; redesign / feature-remove
  / unrequested rename / no-op → 422. Rebuild (`POST /rebuild`): strict
  numeric-only, no LLM.
- `backend/app/services/file_store.py + byteship.py + names.py`:
  `LocalArtifactStore` (in-mem, 200 entries, 1h TTL, ephemeral disk) or
  `ByteshipArtifactStore` (when `BYTESHIP_API_KEY` set, via same-origin
  `/artifacts/` proxy). Opaque tokens, sanitized stems.

## Routes (`backend/app/main.py`)

`GET /health`, `GET /test/cad`, `POST /generate`, `POST /modify`,
`POST /rebuild`, `POST /remint`, `GET /components`, `POST /assembly/add|update|remove`,
`GET /download/{token}`, `GET /artifacts/{req}/{file}`.
Auth optional (`REQUIRE_AUTH=false` default; Firebase JWT when on; the
frontend attaches the ID token, and CORS allows `Authorization`).
Errors: 400 prompt, 401 auth, 404 expired token, 422 spec/guard,
500 CAD/config, 502 Groq/storage. No secrets/paths/tracebacks to client.

File revival: `POST /remint` re-exports a stored spec as-is (no AI, no
diff guard) and the frontend appends it as a `remint` revision, so expired
links are revived with one click while history stays append-only.

## Frontend (`frontend/`)

Next.js 16 + React 19 + R3F + Firebase. Routes: `/` landing,
`/signin`, `/onboarding`, `/workspace` (home shelf ↔ bench).

- State: `Project→Workspace→Revision` (`types/revisions.ts`,
  pure reducers `lib/revisions.ts`). Append-only; `clearViewer` hides only;
  re-view branches. Firestore mirror (`hooks/useProjectSync.ts`,
  `lib/projectStore.ts`); guests in-memory. Revisions store the full
  `GenerateResponse` (spec + URLs) — specs survive, file links expire.
- Viewer: `components/cad/CadViewport.tsx + StlModel.tsx`. Per-object STL
  fetch→parse→recenter; `TransformControls` translate/rotate; selection color;
  reframe on first-load / 1.5× change / reset only. Bridge:
  `lib/assembly.ts:sceneObjects()`.
- Coordinates: CAD is Z-up and three.js is Y-up, so the whole scene renders
  inside a `rotation={[-π/2,0,0]}` wrapper. Stored transforms therefore stay in
  CAD axes (Z is height, as in the inspector and the exported STEP) and mesh
  rotations use Euler order `ZYX`, which is the backend's X→Y→Z composition.
  The well shows a live DRO (pos/rot/size) and an origin axis cross; front /
  top / right / iso views and a perspective↔orthographic switch drive
  `FrameCamera`.
- Animated parts: `assembly.animation` (schema 4.1, optional) holds per-component
  keyframes. `MotionPose` samples them on the render loop, so playback costs no
  React renders; the clock is only mirrored into state ~10 Hz for the scrub bar.
  Animation never reaches the engine — exports use the stored transforms.
- Measure: two clicks on the model give a distance chip plus CAD-axis deltas;
  `MeasureOverlay` is drawn in world space, so no scene-graph changes.
- Inspector: `AssemblyTree + ObjectInspector`. Placement, name, visibility,
  group, lock, remove, duplicate, seat/centre/align, and motion commit locally
  and keep existing mesh URLs. Drag snap (free / 1 / 5 / 10 mm) quantises the
  moved part and applies the same delta to grouped companions. `Bom` lists
  parts by registry type, counting one part per instance.
  Parameter Apply and library add hit `/assembly/update` / `/assembly/add`
  with prior `component_files` so unchanged solids are not re-exported;
  the viewer overlay still runs for the whole request, however short, so
  every non-instant change reads as work in progress (the instant local
  commits above — placement, name, visibility, group, lock, remove — never
  set it). Any solid
  change (parameter, add, remove) also re-exports the combined STEP/STL, so
  downloads never lag behind geometry; pose-only edits keep the combined
  file until remint. `ParametricPanel + useParametricSession`
  (650ms debounced `/rebuild` preview), `SpecPanel`, `RevisionHistory`,
  `Downloads` (STEP authoritative; links ~1h TTL, re-run on 404).
- API: `lib/api.ts` (`generatePart/modifyPart/rebuildPart`,
  assembly ops, `resolveFileUrl`, `humanizeApiError` incl. 404-expired). When
  a user is signed in, `AuthProvider` registers a token provider and each
  POST carries `Authorization: Bearer <Firebase ID token>`; guests send none.

## Export model

Single part: one STEP + one STL. Assembly: combined STEP/STL plus
per-component files; objects stay logically separate (compound, not a
boolean union) — scene representation is richer than export by design.
No constraint solver, collision engine, threads, or mating (out of scope).

## Known limitations

- Render Free: ephemeral disk + single-process store. Deploys/restarts and
  the 1h TTL kill old download links; specs in revisions persist — re-run
  (`Generate`/`Rebuild`) to mint fresh links. Byteship (if configured)
  extends delivery, not permanence.
- Assembly placement is explicit transforms + lightweight relationships,
  not a solver. Fit conflicts fail with 422, never silent bad geometry.
- Incremental assembly edits reuse per-object STL URLs. A geometry change
  (parameter, add, remove) refreshes the combined STEP/STL; a pose, name,
  lock or group edit reuses it, so the combined download can show the older
  placement until a remint. Per-object STLs are always current.
