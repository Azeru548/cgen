# cgen — AI CAD Generator (backend)

Natural-language prompt → Groq structured CAD spec → Pydantic validation →
deterministic CadQuery engine → validated STEP/STL + download tokens.

```text
User prompt
  → Groq structured CAD spec (JSON only, never executable code)
  → Pydantic validation (schema v3.1, allowlisted ops, tree limits)
  → CadQuery (deterministic geometry, no AI code execution)
  → STEP/STL (+ export validation, sanitized filenames, token downloads)
```

Live: `https://cgen-poc.onrender.com` · Docs: `GET /docs` (OpenAPI)

## Supported operations (schema v3.0)

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
```

`part` wraps a built solid with deterministic features (max 4, applied by the
engine in its own fixed order — holes → shell → chamfer → fillet — regardless
of list order):

```text
hole    {diameter, through} or {diameter, depth}   centered on the part
fillet  {radius}        all straight bbox-boundary edges (X/Y directions)
chamfer {size}          same edge set as fillet, 45° bevel
shell   {thickness}     hollow, top face open
```

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
| POST | `/generate` | Full pipeline. 400 bad prompt, 422 bad spec, 500 CAD/server failure, 502 Groq failure. |
| GET | `/download/{token}` | Token file download. 400 bad format, 404 unknown/expired token or lost file. |

Errors never expose keys, paths, or tracebacks; details are logged server-side
with the `request_id` (`generation_started`, `ai_spec_generated`,
`cad_generation_started`, `cad_generation_completed`, `file_export_completed`,
`generation_failed`, `download_requested`, `download_failed`).

## Project layout

```text
backend/
├── app/
│   ├── main.py               # routes + HTTP mapping + OpenAPI models
│   ├── ai/groq_client.py     # Groq: JSON-only spec, safe error mapping
│   ├── cad/schema.py         # CADSpec v3.1 (Pydantic, strict)
│   ├── cad/cadquery_engine.py# deterministic geometry + export validation
│   └── services/
│       ├── generation.py     # orchestration: timing, IDs, logging, renames
│       ├── file_store.py     # token store (TTL + count caps, ephemeral)
│       └── names.py          # AI-name sanitization
├── tests/                    # pytest suite (no real Groq calls)
├── requirements.txt
└── Dockerfile                # python:3.12-slim + GL libs (Render)
render.yaml                   # Render Blueprint (Docker, Free)
```

## Local development

```powershell
cd backend
pip install -r requirements.txt
python -m pytest tests/ -q
uvicorn app.main:app --port 8000
```

## Deploy

Push to GitHub; Render rebuilds from `render.yaml` (Docker). Set `GROQ_API_KEY`
in the Render Dashboard (service → Environment); optional `GROQ_MODEL` override
(default `openai/gpt-oss-120b`).

Costs remain $0: Render Free + Groq free tier + GitHub free.

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
│   ├── GeneratePanel.tsx    # prompt input (2000 max) + states
│   ├── SpecPanel.tsx        # name, units, operation, dims, op tree
│   └── Downloads.tsx        # STEP/STL anchors (backend URLs, resolved)
├── lib/
│   ├── api.ts            # API_BASE_URL, generatePart, guards, error mapping
│   └── spec.ts           # display labels derived from the validated spec
├── types/api.ts          # strict M4 response types (no `any`)
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
npm run build       # production build (typecheck + lint)
npm run dev         # local dev (uses NEXT_PUBLIC_API_BASE_URL)
```

Env: `NEXT_PUBLIC_API_BASE_URL` (see `.env.example`). Unset, the client falls
back to `http://localhost:3000` — set it explicitly to the backend origin.

Deploy (Vercel): import the repo, set **Root Directory = `frontend`**, set
`NEXT_PUBLIC_API_BASE_URL=https://cgen-poc.onrender.com`. Then add the Vercel
origin to the backend's `CORS_ORIGINS` env var on Render (comma-separated,
runtime setting — no rebuild needed), e.g.
`CORS_ORIGINS=http://localhost:3000,https://cgen.vercel.app`.
