# ARCHITECTURE — cgen

Source of truth for how cgen fits together. `README.md` is the pipeline
contract, `PRODUCT.md` the product scope, `DESIGN.md` the visual system.
`work.md` is a historical M9 build brief — its §16 still references the
superseded M8 ivory/coral system; `DESIGN.md` (Precision Bench) wins.

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
`POST /rebuild`, `GET /components`, `POST /assembly/add|update|remove`,
`GET /download/{token}`, `GET /artifacts/{req}/{file}`.
Auth optional (`REQUIRE_AUTH=false` default; Firebase JWT when on).
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
  fetch→parse→recenter; `TransformControls` translate; selection color;
  reframe on first-load / 1.5× change / reset only. Bridge:
  `lib/assembly.ts:sceneObjects()`.
- Inspector: `AssemblyTree + ObjectInspector` (draft → Apply →
  `/assembly/update`), `ParametricPanel + useParametricSession`
  (650ms debounced `/rebuild` preview), `SpecPanel`, `RevisionHistory`,
  `Downloads` (STEP authoritative; links ~1h TTL, re-run on 404).
- API: `lib/api.ts` (`generatePart/modifyPart/rebuildPart`,
  assembly ops, `resolveFileUrl`, `humanizeApiError` incl. 404-expired).

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
