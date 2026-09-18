# AI CAD Generator — Milestone 1 PoC (FastAPI + CadQuery + Render)

**Goal of this milestone (only):** prove the deployed backend can reliably do
`Create box → Export STEP → Export STL → Return the files`.
No AI, no auth, no frontend yet — per spec §26–27, §32.

## What was built

```text
backend/
├── app/
│   ├── main.py              # FastAPI: /health, /test/cad, /test/cad/download
│   └── cad/
│       └── cadquery_engine.py  # make_box() + export_box() (STEP + STL)
├── tests/
│   └── test_box.py          # health, box export, invalid-dims tests
├── requirements.txt         # fastapi, uvicorn, cadquery==2.8.0, pytest, httpx
└── Dockerfile               # python:3.12-slim + GL system libs + pip wheels
render.yaml                  # Render Blueprint -> web service (Docker, Free)
```

Key design points (from spec):
- **Lazy CadQuery import** — `/health` answers even if CadQuery is broken,
  reporting `cadquery_available: true/false`. No import-time crash.
- **No `exec`/`eval`** — only allowlisted `box()` call (§19).
- **Ephemeral-disk aware** — files go to temp dir; client downloads
  immediately via `/test/cad/download?format=step|stl` (§22).
- **Human-readable errors** — 422 for bad dims, 500 with message for
  CAD/export failures, never raw tracebacks (§18).

## Local verification (done)

```powershell
cd backend
pip install fastapi uvicorn httpx pytest
python -m pytest tests/test_box.py::test_health tests/test_box.py::test_invalid_dimensions_rejected -v
# 2 passed
```

Full `pip install cadquery` was **not** completed locally (large OCP wheel,
slow link — exactly why spec §2 says heavy CAD runs in the cloud, not on the
dev machine). Without CadQuery, `/test/cad` correctly returns:
`500 {"detail":"CadQuery is not available: ..."}` — proving the error path.
The real geometry test runs on Render (below).

To run the API locally (without CAD):
```powershell
cd backend
uvicorn app.main:app --port 8000
# GET http://localhost:8000/health
```

## Deploy to Render Free (the actual proof test)

1. `git init`, commit, push to GitHub (repo root = this folder).
2. Render Dashboard → **New → Blueprint** → select the repo
   (uses `render.yaml`: Docker, `plan: free`, health check `/health`).
   - Alternative without blueprint: **New → Web Service → Docker**,
     Dockerfile path `./backend/Dockerfile`, context `./backend`.
3. Wait for build (~5–10 min first time: OCP wheel ~50 MB + pip resolve).
4. **Pass criteria** — in order:
   ```text
   GET https://<service>.onrender.com/health
   → {"status":"ok","cadquery_available":true,...}

   GET https://<service>.onrender.com/test/cad?width=100&depth=60&height=30
   → {"status":"completed",...,"validation":{all true},"files":{"step_bytes":>0,"stl_bytes":>0}}

   GET https://<service>.onrender.com/test/cad/download?format=step  → .step file
   GET https://<service>.onrender.com/test/cad/download?format=stl   → .stl file
   ```
5. Validate downloads: open STEP in FreeCAD/Onshape trial, STL in any viewer.
   STEP must start with `ISO-10303-21;` (the endpoint checks this itself).

**If build fails:** copy the Render build log — the two known risks are
(a) missing system GL lib (`import OCP` → `libGL.so` error → add to Dockerfile
`apt` list), (b) OCP wheel unavailable for the Python version (Dockerfile pins
3.12, which has wheels; do not bump to a bleeding-edge Python per CadQuery docs).

**If service runs but `cadquery_available: false`:** check logs for the
`cadquery_error` string; `GET /health` surfaces it.

## Next step after green (Groq integration — Milestone 3)

Do NOT build auth/payments/2D yet (§26). Next:
1. Add `POST /api/v1/generate` accepting `{prompt, output_type, units}`.
2. Add `backend/app/ai/`: Groq client → strict CAD JSON → Pydantic validation
   (versioned schema, allowlisted ops: box/cylinder/cone/sphere/extrude/cut/union/hole).
3. Extend `cadquery_engine.py` op-by-op (box first, then cylinder/cone/sphere,
   hole, boolean cut), each with schema + validation + test (§13, §28).
4. GLB export for Three.js preview (Milestone 4), then DXF via ezdxf (Milestone 6).

Costs remain $0: Render Free + Groq free tier + GitHub/Vercel free (§3, §25).
"# cgen" 
