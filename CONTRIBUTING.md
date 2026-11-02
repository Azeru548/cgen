# Contributing to cgen

Thanks for helping. This project is a full-stack app with a deterministic CAD
engine, so the most useful contributions are bug reports with a reproducible
prompt/spec, focused fixes, and tests around geometry or state changes.

## Setup

**Backend** (Python 3.12; the Docker image uses 3.12):

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

`GROQ_API_KEY` is only needed for `/generate` and `/modify`. Tests stub the AI
and can run without a key. CadQuery downloads a large OCP wheel; a clean install
can take a few minutes.

**Frontend** (Node 20+):

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

Set `NEXT_PUBLIC_API_BASE_URL` to the backend origin (`http://localhost:8000`
by default). Never put a `GROQ_API_KEY` or any other server secret in
`NEXT_PUBLIC_*` — those values ship to the browser.

**Firebase (optional).** Accounts and project sync need a Firebase web app.
Copy its public web config into the `NEXT_PUBLIC_FIREBASE_*` variables. Publish
[`firestore.rules`](firestore.rules) and enable Email/Password sign-in. Without
this config the app runs as a guest; it does not crash.

## Checks

```bash
# backend
cd backend && python -m pytest tests/ -q

# frontend
cd frontend && npm run lint && npm test && npm run build
```

A PR should pass the same checks as CI (`.github/workflows/ci.yml`).

## Conventions

- **The LLM only returns data.** It never emits code. All geometry goes through
  the validated schema and the deterministic CadQuery engine.
- **Local edits never call the AI.** `/rebuild` and `/assembly/*` are guarded,
  deterministic paths; keep them that way.
- **Revisions are append-only.** UI state may hide things, but history is never
  rewritten.
- **Errors are user-facing.** Return controlled messages; log details
  server-side with the `request_id`. Do not leak keys, paths or tracebacks.
- **No `any` in frontend types.** Validate responses at the API boundary.
- Keep the Precision Bench visual system: read [`DESIGN.md`](DESIGN.md) before
  changing the interface.

## Reporting bugs

Open an issue with the prompt or specification, the expected result, and the
actual error/response. For security issues, follow [`SECURITY.md`](SECURITY.md)
instead of opening a public issue.

By contributing you agree that your contribution is licensed under the
[MIT License](LICENSE).
