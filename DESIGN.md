# DESIGN — cgen (Precision Bench)

<!-- impeccable:design-schema 1 -->

## Direction contract

- **Thesis:** cgen is a machinist's metrology kit — engraved scales, DRO wells, one signal-needle accent; refuses warm-ivory craft-kit chrome and generic dark SaaS CAD.
- **Own-world:** cool instrument-gray ground (#e8eaed), white chrome surfaces, engraved ink (#16181d), hairline etched rules, near-square radii (2–6px), one signal red (#cc2936) for primary action and live state only; Barlow Semi Condensed UI + JetBrains Mono DRO numerals; tick rails, graduation edges, dark measuring well (#0e1014) as the only atmosphere.
- **Story:** maker lands on engraved nameplates, opens a bench, describes a part, adds registry components, watches DRO readouts while dragging, caged→zeroed values on Apply, downloads packed files.
- **First viewport:** Home — chrome bar with tick rail; workspace nameplates in a calibration-bench grid, each with engraved serial (WS-###) and rev stamp; New workspace as instrument key. Workspace — chrome top bar + tick rail; library rail left; dark measuring well with reticle center; graduated inspector right; prompt thimble + red Generate bottom. Signature: dirty values raise a red cage tick; Apply settles with a scale-tick pulse; drag ticks XYZ like encoder counts.
- **Form:** assigned direction “Precision Bench”, seed `14f0f6df` (direction round, code-led wireframe lock).
- **Finish:** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.

## Color roles

| Token | Hex / value | Role |
|---|---|---|
| `--bg` | `#e8eaed` | Page canvas (instrument gray) |
| `--surface` | `#f7f8fa` | Cards, bars, inputs |
| `--panel` | `#eef0f3` | Inspector / library rail |
| `--ink` | `#16181d` | Primary text (engraved) |
| `--ink-secondary` | `#4a5058` | Secondary text |
| `--ink-faint` | `#555d6b` | Tertiary / meta (≥4.5:1 on ground) |
| `--border` | `#c9ced6` | Default hairline rules |
| `--border-strong` | `#a8b0bb` | Emphasised rules / tick marks |
| `--signal` | `#cc2936` | Sole accent: primary action + live/dirty state |
| `--danger` | `#a01820` | Errors |
| Viewport canvas | `#0e1014` | Dark measuring well (sole atmosphere) |

Strategy: **Single-accent restraint** — legacy coral/cobalt/mint/amber tokens alias to signal/ink so decoration never reintroduces a second hue. Signal is reserved for Generate, dirty/Apply cage ticks, focus, and active selection borders.

## Typography

| Role | Face | Notes |
|---|---|---|
| UI / display | **Barlow Semi Condensed** | Headings, buttons, body |
| Data / DRO | **JetBrains Mono** | mm values, serials, meta, tabular numerals |

Scale (approx): home title `clamp(1.7rem, 3.5vw, 2.4rem)` · body `0.95–1.02rem` · meta `0.62–0.7rem` mono uppercase · DRO numerals `1.05–1.2rem` tabular (monumental measures raise).

## Spacing & shape

- Scale: `--space-1` … `--space-6` (0.35 → 2.5rem).
- Radius: `2–6px` controls and panels (near-square); pill radius only for legacy aliases.
- Depth: soft inset+drop shadows (`--shadow-sm/md/lg`), never hard offset blocks.
- Ornament: tick rails (`--tick` / `--tick-v`), graduated inspector edge, reticle crosshair in the well.

## Motion

- Focal: **cage-tick settle** — dirty Apply raises a red inset cage tick; Apply pulses (`tick-settle`); drag pulses DRO wells (`dro-pulse` while `[data-moving]`).
- Supporting: nameplate entrance (`plate-in`), view fade-rise, palette open, button press.
- Timing: 150–350ms routine; `cubic-bezier(0.16, 1, 0.3, 1)`; full `prefers-reduced-motion` kill switch.

## Surfaces

1. **Home (`WorkspaceHome`)** — chrome top bar with tick rail; engraved workspace nameplates (WS-### serial, LAST OPEN, rev stamp) in a calibration-bench grid; create plate as dashed instrument key with red `+`.
2. **Workspace (`page.tsx`)** — fixed 100dvh shell: top bar (logo → home, Workspace, Clear viewer) + tick rail; **left library rail** with graduated edge; dark measuring well + reticle; graduated inspector right; prompt thimble + signal Generate bottom.

## Components

Nameplates, revision items (active = signal border, no side-stripe), model library rail palette, prompt bar, generate button (signal; muted when disabled), parametric DRO wells, assembly tree (selected = signal border), object placement fields (dark DRO), file rows, download buttons, viewport overlays — all inherit Precision Bench tokens above.

## Assembly interaction (M9)

- **Model library** lives in the **left rail**. Categories (Geometry / Fasteners / Mechanical / Electronics / Templates) open as compact overlays to the right of the rail — only one open, shell height fixed. **Add** inserts a registry component with no LLM call.
- **Inspector** is the sole vertical scroll region in the workspace; header sticks while content scrolls.
- **Assembly tree** lists named objects; selection is shared with the viewport (signal border). Eye toggle is a preview; **Apply placement** commits visibility, name, and transform as one revision.
- **Object inspector** shows name, XYZ mm / Euler degrees, and registry parameters. Dirty values raise a red cage tick; **Apply** settles the tick. Neither writes a revision until the explicit button.
- **Viewer** renders each component’s local STL at its transform. Repeated fasteners share one definition and N instance poses. Camera still frames on first load, reset, or a large size change only.
- **Single-part** documents (schema 3.2) still occupy the scene as one generated object so the tree stays available.

## Accessibility

- Focus: 2px signal outline, 2px offset; `caret-color: signal`.
- Contrast: ink on ground ≥4.5:1; white on signal for primary button; status colors paired with text labels.
- Browser surfaces: `::selection`, caret, scrollbars themed from the palette.
- Reduced motion: all transitions/animations disabled under `prefers-reduced-motion`.

## Not canonized

- Section-number kickers (01/02/04) — refused by craft floor; panels use plain `.panel-title` labels.
- Solid >1px red inset side-stripes on active/selected list rows — refused; selection uses border + soft signal fill; cage ticks reserved for dirty/Apply only.
- Warm-ivory Open Kit palette, multi-hue compartment roles, Bricolage Grotesque — superseded by this world.

## Verified

- `tsc --noEmit` clean · vitest **61** · eslint 0 errors on changed files · workspace is a fixed app shell (no page scroll; inspector-only scroll) · `impeccable detect` clean on changed targets.
