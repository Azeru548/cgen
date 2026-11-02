# cgen frontend

Next.js 16 + TypeScript + Three.js (`three`, `@react-three/fiber`,
`@react-three/drei`). Vanilla CSS only — no Tailwind, no component library.

Project → Workspace → Revision model: describe a part → `POST /generate`
(or revise via `POST /modify`) on the cgen backend → every success appends a
revision → STL preview in the browser → spec panel → STEP/STL downloads.
History is append-only: new workspaces start fresh, clearing the viewer keeps
all revisions, and re-viewing an old revision branches the next edit off it.

- STEP is the authoritative CAD artifact (opened in Autodesk for verification).
- STL is the lightweight visualization artifact, parsed with Three.js
  `STLLoader` into a `BufferGeometry`. No CAD kernel in the browser.
- The API returns relative `download_url`s; the client resolves them against
  `NEXT_PUBLIC_API_BASE_URL`. No Groq credentials exist anywhere here.

```powershell
npm install
npm test        # vitest (api client, spec helpers, downloads)
npm run lint    # eslint
npm run build   # production build
npm run dev     # local dev server
```

Deploy to any Next.js host with root directory `frontend` and set
`NEXT_PUBLIC_API_BASE_URL` to your backend origin at build time (unset, it
defaults to `http://localhost:8000`). Then add the frontend origin to the
backend's `CORS_ORIGINS` env var. See the root [`SECURITY.md`](../SECURITY.md)
before exposing the API.
