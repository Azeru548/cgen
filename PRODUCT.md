# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Next.js 16 (App Router) + React 19 + TypeScript + vanilla CSS; FastAPI + CadQuery backend; STEP/STL export.

## Users

Broader creators and makers who want real CAD parts without deep CAD-software expertise. They open the app to describe a shape, tweak dimensions, and download manufacturable files — not to learn a professional MCAD tool.

## Product Purpose

cgen turns natural-language part descriptions into validated 3D CAD models (STEP + STL). Success is: a creator describes a part, previews it, adjusts parameters, and downloads files they can use — without AI remaining in the loop for local parametric edits.

## Positioning

Language-to-solid generation with a deterministic CadQuery engine, an append-only project/workspace/revision model, and a no-AI `/rebuild` path for dial-based numeric retunes. Neighboring chat-CAD tools stop at generation; cgen keeps a full revision history and local parametric control.

## Operating Context

Single-page web workstation: prompt bar, WebGL viewport, inspector (spec, revisions, downloads), boot/engine status. Work happens in Project → Workspace → Revision sessions. Backend download tokens are short-lived; specs remain authoritative.

## Capabilities and Constraints

- Generate and modify parts from natural language (LLM + schema validation)
- Local parametric rebuild (box/cylinder dims, hole/fillet numbers) with no AI
- Append-only revisions; clear-viewer without data loss; multi-workspace project
- STEP (authoritative) + STL (preview mesh) downloads
- Ephemeral file links (≈1h TTL); WebGL required for preview
- Schema v3.2 operation/feature model; conservative client-side parameter ranges

## Brand Commitments

- Name: cgen — AI CAD generator
- Logo asset: `frontend/public/logo-removebg.png`
- Voice: plain, technical-but-approachable, honest about readiness (engine pill, boot checks)
- Signature loader: walking-machine SVG (keep as personality unless redesign replaces it deliberately)

## Evidence on Hand

Working full-stack app in repo (frontend + backend + tests). No external marketing site, testimonials, or customer proof. No approved visual DESIGN.md.

## Product Principles

1. Specs and revisions are append-only truth; UI never destroys history.
2. Local numeric edits never call the AI; rebuild is deterministic and guarded.
3. Preview stays usable while updates land — no blanking the model on every tick.
4. Errors name the problem and the recovery path in plain language.
5. Downloads (especially STEP) remain authoritative even when preview fails.

## Accessibility & Inclusion

Keyboard-operable controls, visible focus, `prefers-reduced-motion` respected for nonessential motion, aria labels on viewport/toolbars, readable contrast on dark surfaces (to be re-verified after redesign).
