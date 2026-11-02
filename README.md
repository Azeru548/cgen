# cgen — AI CAD Generator

Natural-language prompt → Groq structured CAD spec or assembly plan →
Pydantic validation → deterministic component registry + CadQuery engine →
validated STEP/STL + download tokens.
Existing parts are revised in place via natural-language modification, and
the frontend keeps every successful generation/modification/assembly edit as
a revision in a Project → Workspace → Revision history.

```text
User prompt
  → Groq JSON only (3d_part v3.2 or 3d_assembly v4.0; never executable code)
  → Pydantic validation (allowlisted ops / registry component types)
  → CadQuery (deterministic geometry, no AI code execution)
  → STEP/STL (+ per-component files for assemblies)

Library insert / move / hide / param: NO LLM
  → POST /assembly/add|update|remove or POST /rebuild
```

Live demo: `https://cgen.pxxl.click` (frontend) · `https://cgen-poc.onrender.com`
(backend) · Docs: `GET /docs` (OpenAPI)

MIT licensed. Architecture in [`ARCHITECTURE.md`](ARCHITECTURE.md), contribution
guide in [`CONTRIBUTING.md`](CONTRIBUTING.md), security policy in
[`SECURITY.md`](SECURITY.md).

## Quick start

Two processes: the FastAPI + CadQuery backend and the Next.js frontend.

**Backend** (Python 3.12; CadQuery installs a large OCP wheel):

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export GROQ_API_KEY=gsk_...      # required only for /generate and /modify
uvicorn app.main:app --reload --port 8000
```

**Frontend** (Node 20+):

```bash
cd frontend
npm ci
cp .env.example .env.local       # points at http://localhost:8000
npm run dev
```

Open `http://localhost:3000`. Accounts are optional: the sign-in page also has
a guest path straight into the workspace.

**Accounts (optional).** Set the `NEXT_PUBLIC_FIREBASE_*` variables to your own
Firebase web app, publish [`firestore.rules`](firestore.rules), and enable
Email/Password sign-in plus your frontend origin under Authentication →
Authorized domains. Without your own config the app falls back to the public
demo project committed in `frontend/lib/firebase.ts`; override it for any real
deployment. `NEXT_PUBLIC_*` values are inlined at build time, so changing them
requires a rebuild.

**Production API auth (optional).** Set `REQUIRE_AUTH=true` and
`FIREBASE_PROJECT_ID` on the backend to reject anonymous calls. The frontend
attaches the signed-in user's Firebase ID token automatically. See
[`SECURITY.md`](SECURITY.md) before exposing the API publicly.

## Supported operations (schema v3.2)

```text
box           {width, depth, height}
cylinder      {radius, height, through?}
cone          {bottom_radius, top_radius, height}
sphere        {radius}
torus         {major_radius, minor_radius}          minor < major
polygon_prism {sides (3-12), circumradius, height}
union         {base, tool}   result = base + tool
cut           {base, tool}   result = base - tool
intersect     {base, tool}   result = base ∩ tool (must overlap)
part          {build, features[]}                  M6 engineering features

One feature is a bolt-circle pattern (v3.1, still ONE feature toward the
max-4 cap): `hole_pattern {diameter, count 2-12, circle_diameter,
through | depth}` — N identical holes at angles 2π·i/count, deterministic.
Rectangular/linear multi-hole layouts (v3.2, still ONE feature toward the
max-4 cap): `hole_grid {diameter, rows 1-12, cols 1-12 (rows*cols <= 12),
spacing_x?, spacing_y?, through | depth}` — rows×cols identical holes on a
deterministic centered array (spacing = center-to-center); rows=1 or cols=1
gives a straight line. Spacing is required exactly on multi-hole axes and
stays null on single-hole axes (a 1×N row needs spacing_x only). Corner/row/
coordinate layouts route here, genuinely circular layouts stay on
hole_pattern.
```

`part` wraps a built solid with deterministic features (max 4, applied by the
engine in its own fixed order — holes → shell → chamfer → fillet — regardless
of list order):

```text
hole    {diameter, through} or {diameter, depth}   centered on the part
fillet  {radius}        straight X/Y edges on outer bbox sides (fuse-split
                        rims included; notch rims and curves excluded)
chamfer {size}          same edge set as fillet, 45° bevel
shell   {thickness}     hollow, top face open
```

Fillet/chamfer edge selection is topological: X/Y-parallel edges whose
constant plan coordinate is extreme. On a plain box this is the top/bottom
rim set; on fused unions (L-brackets) it is the split outer rims. Radii
that OCCT cannot roll fail with a controlled error suggesting a smaller
radius — the empty-set rejection is preserved for truly edge-less solids
(spheres, tori).

All dimensions are millimeters (the model normalizes m/cm/inch → mm and
diameters → radii). Operation trees are capped (depth ≤ 4, nodes ≤ 15).
A `cut` whose tool is a cylinder with `"through": true` keeps its M3 behavior:
a deterministic centered through-hole — the model never computes offsets.
Engineering features are structural (no offsets, no rotation); placement-aware
geometry is a deliberate future milestone, not part of M6.

The backend generates **actual CAD files**, verified to open in Autodesk
(STEP with through-hole) and standard STL viewers.

## Example request

```json
POST /generate
{
  "prompt": "Create a 120mm long shaft with a 30mm diameter and a 15mm hole through the center."
}
```

## Example result

```json
{
  "status": "completed",
  "request_id": "9f2c...83",
  "specification": {
    "document_type": "3d_part",
    "units": "mm",
    "name": "shaft_with_hole",
    "operation": {
      "type": "cut",
      "base": { "type": "cylinder", "radius": 15, "height": 120, "through": false },
      "tool": { "type": "cylinder", "radius": 7.5, "height": 120, "through": true }
    }
  },
  "units": "mm",
  "generation_time_ms": 1842,
  "files": {
    "step": {
      "format": "step",
      "filename": "shaft_with_hole.step",
      "bytes": 9338,
      "download_url": "/download/TOKEN?format=step"
    },
    "stl": {
      "format": "stl",
      "filename": "shaft_with_hole.stl",
      "bytes": 50484,
      "download_url": "/download/TOKEN?format=stl"
    }
  }
}
```

Filenames are sanitized server-side (the AI-proposed `name` is never trusted
as a path). Download tokens are random opaque keys — they cannot address
arbitrary files. Files live on ephemeral disk (Render Free): download promptly.

## Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Cheap liveness (no AI, no CAD). |
| GET | `/test/cad` | Milestone 1 box probe + export self-checks. |
| GET | `/test/cad/download` | Milestone 1 box file download. |
| POST | `/generate` | Full pipeline. 400 bad prompt, 422 bad spec, 500 CAD/server failure, 502 Groq failure. May return `3d_part` or `3d_assembly`. |
| POST | `/modify` | Spec + instruction → revised spec → diff guard → files. Same response shape as `/generate`. 400 bad instruction, 422 guard/spec rejection, 500/502 as above. |
| POST | `/remint` | Stored spec → validation → fresh STEP/STL, no AI, no diff guard. Revives expired download links as a new revision. 422 bad spec, 500 CAD failure. |
| GET | `/components` | Deterministic component catalog (no AI, no CAD). |
| POST | `/assembly/add` | Insert a registry component. Promotes a `3d_part` to an assembly. No AI. |
| POST | `/assembly/update` | Parameters, transform, visibility, or name of one object. No AI. |
| POST | `/assembly/remove` | Remove one object (not the last). No AI. |
| GET | `/download/{token}` | Token file download. 400 bad format, 404 unknown/expired token or lost file. |

Errors never expose keys, paths, or tracebacks; details are logged server-side
with the `request_id` (`generation_started`, `ai_spec_generated`,
`cad_generation_started`, `cad_generation_completed`, `file_export_completed`,
`generation_failed`, `modification_started`, `ai_modification_completed`,
`modification_completed`, `modification_failed`, `download_requested`,
`download_failed`).

## Project layout

```text
backend/
├── app/
│   ├── main.py               # routes + HTTP mapping + OpenAPI models
│   ├── ai/groq_client.py     # Groq: JSON-only spec + modify prompt, safe error mapping
│   ├── cad/schema.py         # CADSpec v3.2 (Pydantic, strict)
│   ├── cad/cadquery_engine.py# deterministic geometry + export validation
│   └── services/
│       ├── generation.py     # generate + modify orchestration, diff guard
│       ├── file_store.py     # token store (TTL + count caps, ephemeral)
│       └── names.py          # AI-name sanitization
├── tests/                    # pytest suite (no real Groq calls)
├── requirements.txt
└── Dockerfile                # python:3.12-slim + GL libs (Render)
render.yaml                   # Render Blueprint (Docker, Free)
```

## Local development checks

```bash
(cd backend && python -m pytest tests/ -q)
(cd frontend && npm run lint && npm test && npm run build)
```

These are the same checks CI runs ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).

## Deploy

**Backend.** Build `backend/Dockerfile` on any Docker host. [`render.yaml`](render.yaml)
is a Render blueprint (Docker, free tier). Set `GROQ_API_KEY` in the host's
dashboard; optional `GROQ_MODEL` (default `openai/gpt-oss-120b`) and
`BYTESHIP_API_KEY` (artifact storage; server-side only). Set `CORS_ORIGINS` to
the deployed frontend origin (comma-separated, no rebuild needed).

**Frontend.** Deploy `frontend/` to any Next.js host. Set
`NEXT_PUBLIC_API_BASE_URL` to the backend origin **at build time**; unset, it
defaults to `http://localhost:8000`. Add the frontend origin to the backend's
`CORS_ORIGINS`.

Optional artifact storage: set `BYTESHIP_API_KEY` (server-side only) to deliver
generated STEP/STL files through Byteship. Without it the app falls back to the
in-process download store. Never expose the key to the browser.

## M10.2 — Artifact storage and delivery (Byteship)

Generated CAD bytes are now delivered through a small storage abstraction:

```
CAD generation → ArtifactStore → delivery URL
```

- **Byteship (production).** When `BYTESHIP_API_KEY` is set, each STEP/STL pair
  is uploaded to Byteship and `files.*.download_url` becomes the CDN delivery
  URL. Path-keyed upload: `PUT /v1/files/{path}` → `PUT {upload.url}` with the
  returned headers → `POST /v1/files/{path}/upload/complete`. Paths are
  `cgen/{request_id}/{filename}`; the user prompt is never used.
- **Local (default, no key).** The existing in-process `FileStore`, serving
  `/download/{token}?format=…`.

The artifact bytes are never regenerated for upload — CadQuery runs once, and no
CAD data is sent to an LLM. STEP uploads as `application/step`, STL as
`model/stl`. A storage failure returns CGEN's normal controlled error rather
than a success with a dead link. See `backend/app/services/byteship.py`.


## M7 — Modification, revisions, schema v3.2

**Modification (`POST /modify`).** The client sends the current spec plus a
natural-language instruction; Groq returns a revised spec that passes through
a deterministic structural diff guard *before* any CAD work: constants must
hold, renames need an explicit request, the operation skeleton must match
(no redesigns — e.g. part → union is rejected), and existing features may
gain new siblings but never lose members. Rejections are controlled 422s.
Numeric retunes (dimensions, diameters, counts, depths) and feature additions
pass through the unchanged deterministic engine.

**Project → Workspace → Revision (frontend-only, no backend changes).**
Every successful generate/modify appends a revision parented to the previous
active one — history is never overwritten. New Workspace starts empty without
affecting existing workspaces; Clear Viewer hides the display only; clicking
a history entry re-views it, and the next edit branches a new child off it.
Download links stay backend-ephemeral (TTL/caps), so old revisions always
keep their specs while file links may expire with a re-run prompt.

**Schema v3.2.** `hole_grid` covers rectangular/linear multi-hole layouts
(corners, rows, explicit coordinates) that a bolt circle cannot represent on
non-square faces; genuinely circular layouts stay on `hole_pattern`, single
centered holes on `hole`. Single-axis grids carry spacing on one axis only.

## M6 — Engineering feature expansion

Backend: torus, polygon prism, intersect, and the `part` node (holes,
fillets, chamfers, shells) — all validated by schema v3.0 and built by the
deterministic engine. The Groq system prompt handles engineering expressions
(M-size holes, diameter vs radius, inch plates) while staying JSON-only.
The engine applies features in the OCCT-robust order and guards failure
modes that OCCT handles silently (empty intersections, no-op shells,
fillet-on-hollowed-solid invalidity) with clean 422/500 errors.

Frontend: spec display for every new operation and feature, feature rows in
engine order, intersect (∩) trees. No component or styling changes.

## M5 — Frontend (Next.js + TypeScript + Three.js)

```text
frontend/
├── app/                  # workspace page + vanilla CSS
├── components/
│   ├── cad/CadViewport.tsx  # R3F canvas: orbit/zoom/pan, auto-framing, grid
│   ├── cad/StlModel.tsx     # STL fetch → parse → center → dispose
│   ├── BootScreen.tsx       # startup checks (schema, renderer, engine)
│   ├── Inspector.tsx        # spec + downloads + revision history sidebar
│   ├── RevisionHistory.tsx  # append-only revision list, time-travel select
│   ├── SpecPanel.tsx        # name, units, operation, dims, op tree
│   └── Downloads.tsx        # STEP/STL anchors (backend URLs, resolved)
├── lib/
│   ├── api.ts            # API_BASE_URL, generatePart/modifyPart, guards, errors
│   ├── revisions.ts      # pure Project → Workspace → Revision helpers
│   └── spec.ts           # display labels derived from the validated spec
├── types/
│   ├── api.ts            # strict response/spec types (no `any`)
│   └── revisions.ts      # Revision/Workspace/Project types
└── tests/                # vitest: api client, spec helpers, downloads
```

Flow: prompt → `POST /generate` → STL `download_url` → fetch → `STLLoader`
→ `BufferGeometry` → render. STEP is never parsed in the browser; it remains
the authoritative CAD download. No Tailwind, no component library, no
`GROQ_API_KEY` anywhere in frontend code.

```powershell
cd frontend
npm install
npm test            # vitest
npm run lint        # eslint
npm run build       # production build (typecheck)
npm run dev         # local dev (uses NEXT_PUBLIC_API_BASE_URL)
```

Env: `NEXT_PUBLIC_API_BASE_URL` (see `.env.example`). Unset, the client falls
back to `http://localhost:8000` — the backend's default dev port.

**Accounts (M11).** The public demo Firebase web config is committed in
`frontend/lib/firebase.ts`, so the hosted demo needs no build-time variables.
Forks should set their own `NEXT_PUBLIC_FIREBASE_*` values: those override the
demo config, and because `NEXT_PUBLIC_*` is inlined at build time, changing
them requires a **rebuild**, not just a restart.

The public demo runs the frontend at `https://cgen.pxxl.click` and the backend
as a Docker service on Render. Add your frontend origin to the backend's
`CORS_ORIGINS` env var (comma-separated runtime setting — no rebuild needed),
e.g. `CORS_ORIGINS=http://localhost:3000,https://your-frontend.example`.

Firebase Console setup that is **not** in the repo: enable the Email/Password
sign-in provider, and add the frontend origin under Authentication → Settings →
Authorized domains. Publish `firestore.rules` (per-user access).

## License

[MIT](LICENSE). Contributions are accepted under the same license; see
[`CONTRIBUTING.md`](CONTRIBUTING.md). For vulnerabilities, follow
[`SECURITY.md`](SECURITY.md) rather than opening a public issue.
