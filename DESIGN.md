# DESIGN — cgen (Precision Bench)

<!-- impeccable:design-schema 1 -->

## Direction contract

- **Thesis:** cgen is a machinist's metrology kit — engraved scales, DRO wells, one signal-needle accent; refuses warm-ivory craft-kit chrome and blue-glow generic dark SaaS CAD.
- **Own-world (night shift):** bench-black ground (#0f1319) around a deepest-dark measuring well (#07090d), graphite chrome surfaces (#161c25 / #111722), etched light ink (#e8eaed), hairline rules (#2b3442 / #414c5e), near-square radii (2–6px), one signal red (#cc2936) for primary action and live state only; Barlow Semi Condensed UI + JetBrains Mono DRO numerals; tick rails, graduation edges. Dark-only: `color-scheme: dark`, no light theme.
- **Story:** maker lands on engraved nameplates, opens a bench, describes a part, adds registry components, watches DRO readouts while dragging, caged→zeroed values on Apply, downloads packed files.
- **First viewport:** Home — chrome bar with tick rail; workspace nameplates in a calibration-bench grid, each with engraved serial (WS-###) and rev stamp; New workspace as instrument key. Workspace — chrome top bar + tick rail; library rail left; dark measuring well with reticle center; graduated inspector right; prompt thimble + red Generate bottom. Signature: dirty values raise a red cage tick; Apply settles with a scale-tick pulse; drag ticks XYZ like encoder counts.
- **Form:** assigned direction “Precision Bench”, seed `14f0f6df` (direction round, code-led wireframe lock).
- **Finish:** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance.

## Color roles

| Token | Hex / value | Role |
|---|---|---|
| `--bg` | `#0f1319` | Page canvas (bench black) |
| `--bg-deep` | `#090c11` | Shell edges, deepest page ground |
| `--surface` | `#161c25` | Cards, bars, inputs |
| `--panel` | `#111722` | Inspector / library rail |
| `--input` | `#1c2330` | Field wells (`--input-hover` `#232c3b`) |
| `--surface-dark` | `#07090d` | Measuring well (deepest dark) |
| `--ink` | `#e8eaed` | Primary text (etched light) |
| `--ink-secondary` | `#a9b2be` | Secondary text |
| `--ink-faint` | `#8f99a6` | Tertiary / meta (≥4.5:1 on ground) |
| `--border` | `#2b3442` | Default hairline rules |
| `--border-strong` | `#414c5e` | Emphasised rules / tick marks |
| `--signal` | `#cc2936` | Sole accent: primary action + live/dirty state |
| `--signal-soft` | `#2b1418` | Signal fill behind active / dirty rows |
| `--danger` | `#e0606a` | Errors |
| Viewport canvas | `#0e1014` | three.js scene background |

Strategy: **Single-accent restraint** — legacy coral/cobalt/mint/amber tokens alias to signal/ink on dark, so decoration never reintroduces a second hue. Signal is reserved for Generate, dirty/Apply cage ticks, focus, and active selection borders.

## Typography

| Role | Face | Notes |
|---|---|---|
| UI / display | **Barlow Semi Condensed** | Headings, buttons, body |
| Data / DRO | **JetBrains Mono** | mm values, serials, meta, tabular numerals |

Scale (approx): home title `clamp(1.7rem, 3.5vw, 2.4rem)` · body `0.95–1.02rem` · meta `0.62–0.7rem` mono uppercase · DRO numerals `1.05–1.2rem` tabular (monumental measures raise).

## Spacing & shape

- Scale: `--space-1` … `--space-6` (0.35 → 2.5rem).
- Radius: `3–6px` controls and panels (near-square); `--radius-pill` is `2px` so no pill shapes survive.
- Depth: soft inset+drop shadows (`--shadow-sm/md/lg`), never hard offset blocks.
- Ornament: tick rails (`--tick` / `--tick-v`), graduated inspector edge, reticle crosshair in the well.

## Motion

- Focal: **cage-tick settle** — dirty Apply raises a red inset cage tick; Apply pulses (`tick-settle`); drag pulses DRO wells (`dro-pulse` while `[data-moving]`).
- Supporting: nameplate entrance (`plate-in`), view fade-rise, palette open, button press.
- Timing: 150–350ms routine; `cubic-bezier(0.16, 1, 0.3, 1)`; full `prefers-reduced-motion` kill switch.

## Surfaces

1. **Landing (`app/page.tsx`)** — entry door, Persuade mode. Top bar (logo → Sign in ghost, one signal CTA). Hero is left-weighted two-column: hook + one supporting sentence + single signal action + three-cell facts strip on the left; **spec readout** on the right — a real `3d_part` document rendered as an instrument card (prompt row, `document/schema/units` DRO rows, operation block, features, exports), labelled *"Example specification, not a customer file"*. Below: three equal columns (Describe / Assemble / Keep) divided by hairlines, never cards; closing CTA; mono footer. No card grid, no gradients.
2. **Auth (`app/signin/page.tsx`)** — single centred card on the well: logo, title, one sentence, the form (no nested box), and a skip link straight to the workspace. Redirects away when already signed in. Accounts optional.
3. **Onboarding (`app/onboarding/page.tsx`)** — two steps (01 Name it → 02 First part), step rail with signal marking the live step, name field, starter option list (selected = signal border + soft fill, no side-stripe), skip link. Creates the account's first project, then hands off to `/workspace`.
4. **Home (`WorkspaceHome`, at `/workspace`)** — chrome top bar with tick rail; engraved workspace nameplates (WS-### serial, LAST OPEN, rev stamp) in a calibration-bench grid; create plate as dashed instrument key with red `+`.
5. **Workspace (`app/workspace/page.tsx`)** — fixed 100dvh shell: top bar (logo → home, Workspace, Clear viewer) + tick rail; **left library rail** with graduated edge; dark measuring well + reticle; graduated inspector right; prompt thimble + signal Generate bottom. The sign-in form is **no longer** buried under the shelf — the top-bar chip links to `/signin`.

## Components

Nameplates, revision items (active = signal border, no side-stripe), model library rail palette, prompt bar, generate button (signal; muted when disabled), parametric DRO wells, assembly tree (selected = signal border), object placement fields (dark DRO), file rows, download buttons, viewport overlays — all inherit Precision Bench tokens above.

## Assembly interaction (M9)

- **Model library** lives in the **left rail**. Categories (Geometry / Fasteners / Mechanical / Electronics / Robotics / Templates) open as compact overlays to the right of the rail — only one open, shell height fixed. **Add** inserts a registry component with no LLM call.
- **Inspector** is the sole vertical scroll region in the workspace; header sticks while content scrolls.
- **Assembly tree** lists named objects; selection is shared with the viewport (signal border). A tick on each row adds to the selection (shift-click in the well does the same); **Group** / **Ungroup** / **Lock** act on ticked parts. Eye toggle is a preview; **Apply placement** commits visibility, name, and transform as one revision. Click empty space in the well to clear selection.
- **Move / Rotate** in the well toolbar drives a gizmo on the selected part (the part itself, not the camera). Grouped parts travel together.
- **Prompt bar** is **Generate** with nothing selected (a new independent object, even if the scene already has parts) and **Modify** when an object is selected.
- **Object inspector** shows name, XYZ mm / Euler degrees, and registry parameters. Dirty values raise a red cage tick; **Apply** settles the tick. Neither writes a revision until the explicit button.
- **Viewer** renders each component’s local STL at its transform. Repeated fasteners share one definition and N instance poses. Camera still frames on first load, reset, or a large size change only.
- **Well instruments**: a live DRO (pos / rot / size, signal while dragging), an origin axis cross, standard views (Front / Top / Right / Iso) with a Persp/Ortho switch centred at the top, a snap switch (Free / 1 / 5 / 10 mm) beside Move/Rotate, and **Measure** — two clicks, then a mono distance chip with CAD-axis deltas.
- **Placement quick actions**: Seat Z, Centre X, Centre Y, plus Align X/Y/Z when two or more parts are ticked (the active part is the datum). **Duplicate** copies the selected part beside itself, reusing its STL.
- **Design / Motion switch** in the topbar. Design is the ordinary workspace; Motion swaps the prompt for the timeline and keeps the same well in view. Leaving Motion stops playback.
- **Motion timeline** docks under the well: transport (back to start, Play/Pause, time readout), Length in seconds, a ruler you can scrub, one row per part on the left, one diamond per key on the right. Selecting a row selects the part; **+ Key** on any row records that part's current pose at the playhead and never goes away once a track exists; a diamond drags to retime and double-clicks to delete; **×** on a row clears its track. Dragging a part that already has a track keys the pose it was dropped at — the move/rotate gizmo stays available on animated parts instead of vanishing. The bar carries one sentence of instruction for the current row. Viewer-only metadata — the drawing and the exports never animate.
- **Bench framing**: the default camera looks down CAD −Z with CAD +Y up the screen, so flat parts (boards, plates, PCBs) arrive face-on and usable. Front / Top / Right remain true drawing views.
- **Never-clipping well controls**: the view bar wraps and docks top-right below 1240px; the bottom toolbar wraps upward into a second row instead of being cut off by the well edge.
- **Bill of materials**: parts grouped by registry type, quantities count instances, one hairline table below the downloads.
- **Single-part** documents (schema 3.3) still occupy the scene as one generated object so the tree stays available.

## Accessibility

- Focus: 2px signal outline, 2px offset; `caret-color: signal`.
- Contrast (measured): ink/bg 15.5:1, ink/surface 14.2:1, ink-secondary/bg 8.7:1, ink-faint/bg 6.5:1, danger/bg 5.4:1, white on signal 5.3:1; status colors paired with text labels.
- Browser surfaces: `::selection`, caret, scrollbars themed from the palette.
- Reduced motion: all transitions/animations disabled under `prefers-reduced-motion`.

## Not canonized

- Section-number kickers (01/02/04) — refused by craft floor; panels use plain `.panel-title` labels.
- Solid >1px red inset side-stripes on active/selected list rows — refused; selection uses border + soft signal fill; cage ticks reserved for dirty/Apply only.
- Warm-ivory Open Kit palette, multi-hue compartment roles, Bricolage Grotesque — superseded by this world.

## Verified

- `tsc --noEmit` clean · vitest **136** (11 files) · backend **428** · workspace is a fixed app shell (no page scroll; inspector-only scroll).
