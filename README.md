# cgen — AI CAD Generator (backend)

Natural-language prompt → Groq structured CAD spec → Pydantic validation →
deterministic CadQuery engine → validated STEP/STL + download tokens.

```text
User prompt
  → Groq structured CAD spec (JSON only, never executable code)
  → Pydantic validation (schema v2.0, allowlisted ops, tree limits)
  → CadQuery (deterministic geometry, no AI code execution)
  → STEP/STL (+ export validation, sanitized filenames, token downloads)
```

Live: `https://cgen-poc.onrender.com` · Docs: `GET /docs` (OpenAPI)

## Supported operations (schema v2.0)

```text
box       {width, depth, height}
cylinder  {radius, height, through?}
cone      {bottom_radius, top_radius, height}
sphere    {radius}
union     {base, tool}   result = base + tool
cut       {base, tool}   result = base - tool
```

All dimensions are millimeters (the model normalizes m/cm/inch → mm and
diameters → radii). Operation trees are capped (depth ≤ 4, nodes ≤ 15).
A `cut` whose tool is a cylinder with `"through": true` gets a deterministic
centered through-hole — the model never computes offsets.

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
│   ├── cad/schema.py         # CADSpec v2.0 (Pydantic, strict)
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
