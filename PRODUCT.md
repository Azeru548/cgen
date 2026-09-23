# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Next.js 16 (App Router) + React 19 + TypeScript + vanilla CSS; FastAPI + CadQuery backend; STEP/STL export.

## Users

Broader creators and makers who want real CAD parts without deep CAD-software expertise. They open the app to describe a shape, tweak dimensions, and download manufacturable files — not to learn a professional MCAD tool.

## Product Purpose

cgen turns natural-language descriptions into validated 3D CAD. M9 adds a reusable component library and an assembly workspace: a creator can describe a kit (enclosure + board + screws), add library parts without AI, inspect each object, and export STEP/STL — while local numeric and placement edits stay off the LLM.

## Positioning

Language-to-solid generation with a deterministic CadQuery engine, a versioned component registry, an append-only project/workspace/revision model, and no-AI paths for `/rebuild` and `/assembly/*`. The LLM interprets intent; the registry and engine produce geometry.

## Operating Context

Single-page web workstation: one top bar (logo, model library, Workspace, Clear viewer), prompt bar, multi-object WebGL scene, inspector (assembly tree, spec, revisions, downloads), boot checks. Work happens in Project → Workspace → Revision sessions. Backend download tokens are short-lived; specs remain authoritative.

## Capabilities and Constraints

- Generate and modify single parts (schema v3.2) or assemblies (schema v4.0) from natural language
- Deterministic component library (~25 types: geometry, fasteners, mechanical, electronics, enclosure template)
- Add / remove / update / hide objects without calling the LLM
- Multi-object scene: selection, per-object parameters, placement, visibility
- Local parametric rebuild for single parts; assembly update/rebuild for library components
- Append-only revisions; clear-viewer without data loss; multi-workspace project
- Combined STEP/STL export plus per-component files; objects stay logically separate (compound, not a boolean union)
- Ephemeral file links (≈1h TTL); WebGL required for preview
- No constraint solver, collision engine, real screw threads, or professional mating

## Brand Commitments

- Name: cgen — AI CAD generator
- Logo asset: `frontend/public/logo-removebg.png`
- Voice: plain, technical-but-approachable, honest about readiness (boot checks)
- Signature loader: walking-machine SVG (keep as personality unless redesign replaces it deliberately)

## Evidence on Hand

Working full-stack app in repo (frontend + backend + tests). No external marketing site, testimonials, or customer proof. No approved visual DESIGN.md.

## Product Principles

1. Specs and revisions are append-only truth; UI never destroys history.
2. Local numeric edits, placement, visibility, and library inserts never call the AI; rebuild/assembly apply is deterministic and guarded.
3. Preview stays usable while updates land — no blanking the model on every tick.
4. Errors name the problem and the recovery path in plain language.
5. Downloads (especially STEP) remain authoritative even when preview fails.

## Accessibility & Inclusion

Keyboard-operable controls, visible focus, `prefers-reduced-motion` respected for nonessential motion, aria labels on viewport/toolbars, readable contrast on dark surfaces (to be re-verified after redesign).
