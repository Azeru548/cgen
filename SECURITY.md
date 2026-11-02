# Security policy

## Reporting a vulnerability

Please do **not** open a public issue for a security problem. Use GitHub's
private vulnerability reporting (Security → Report a vulnerability) so the
maintainers can assess and fix it before disclosure. Include the affected
endpoint or file, reproduction steps, and the impact you believe it has.

We will acknowledge a report as soon as possible and coordinate a fix and
disclosure timeline. There is no bounty program.

## Deployment notes

This repository is a working app, not a hardened multi-tenant service. Before
exposing your own deployment:

- **Authentication is optional by default.** `REQUIRE_AUTH` is unset, so
  `/generate`, `/modify`, `/rebuild`, `/remint` and `/assembly/*` accept
  anonymous callers. Set `REQUIRE_AUTH=true` and `FIREBASE_PROJECT_ID` to
  require a Firebase ID token. The frontend attaches the signed-in token
  automatically.
- **Generation spends the operator's Groq credits.** There is no built-in rate
  limiter. Put the API behind a proxy/WAF or add rate limiting before opening
  it to the public.
- **Firebase web config is public by design.** The API key in the frontend is
  an identifier, not a secret; access control lives in
  [`firestore.rules`](firestore.rules). Never add a service-account key or
  admin credential to the frontend or to this repository.
- **Download links are bearer tokens.** `/download/{token}` and
  `/artifacts/...` grant access to generated files. They expire (local store:
  1 hour) and are not authentication. Do not treat them as private storage.
- **Server secrets stay server-side.** `GROQ_API_KEY` and `BYTESHIP_API_KEY`
  belong in the backend environment only. If one is exposed, rotate it.
