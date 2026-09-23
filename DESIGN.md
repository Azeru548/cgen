# DESIGN — cgen (Open Kit)

<!-- impeccable:design-schema 1 -->

## Direction contract

- **Thesis:** cgen is an open making-kit — color-coded compartments and a landing shelf of project trays; refuses monochrome brutalist CAD chrome.
- **Own-world:** warm ivory canvas, white surfaces, coral/cobalt/mint/amber roles, 12–20px radii, Bricolage Grotesque + IBM Plex Mono for measurements only.
- **Story:** creator lands on the tray shelf, opens a workspace, describes a part or assembly, adds library components, previews the scene, inspects objects, and downloads — color marks the compartment.
- **First viewport:** tray cards + create action; workspace: fixed app shell — topbar, session pills, component library palette, rounded multi-object viewport + independently scrollable inspector, fixed prompt composer.
- **Form:** assigned direction “Open Kit”, seed `b5593edb` (degraded roll, no challengers).
- **Finish:** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, and DESIGN.md.

## Color roles

| Token | Hex / value | Role |
|---|---|---|
| `--bg` | `#f4f1ea` | Page canvas (warm ivory) |
| `--surface` | `#ffffff` | Cards, bars, inputs |
| `--panel` | `#fbfaf7` | Inspector panel |
| `--ink` | `#1b1e24` | Primary text |
| `--ink-secondary` | `#4c5361` | Secondary text |
| `--ink-faint` | `#7c8494` | Tertiary / meta |
| `--border` | `#e4ddd2` | Default borders |
| `--coral` | `#e85d2a` | Primary action (Generate, active tabs) |
| `--cobalt` | `#2f5fd9` | Focus, inspect labels, active revisions |
| `--mint` | `#0f9d7a` | Success / apply / validated |
| `--amber` | `#c9840a` | Downloads / output |
| `--danger` | `#d24545` | Errors |
| Viewport canvas | `#12141a` | 3D stage only (dark well) |

Strategy: **Full palette** — four compartment hues on a warm neutral ground; coral owns the primary action.

## Typography

| Role | Face | Notes |
|---|---|---|
| UI / display | **Bricolage Grotesque** | Headings, buttons, body |
| Data / labels | **IBM Plex Mono** | mm values, meta, kickers, schema chips only |

Scale (approx): home title `clamp(1.85rem, 4vw, 2.75rem)` · body `0.95–1.02rem` · meta `0.62–0.7rem` mono uppercase with tracking.

## Spacing & shape

- Scale: `--space-1` … `--space-6` (0.35 → 2.5rem).
- Radius: `10px` controls · `14px` panels · `20px` trays/viewport · pill for chips/tabs.
- Depth: soft dual-offset shadows (`--shadow-sm/md/lg`), never hard offset blocks.

## Motion

- Focal: **tray shelf entrance** — staggered `tray-in` (translateY + scale), hover lift.
- Supporting: view fade-rise, button press lift, tab/revision transitions, palette dropdown open.
- Timing: 150–350ms routine; `cubic-bezier(0.16, 1, 0.3, 1)`; full `prefers-reduced-motion` kill switch.

## Surfaces

1. **Home (`WorkspaceHome`)** — shelf of workspace trays: gradient + blur covers, white titles, create tray with coral `+`.
2. **Workspace (`page.tsx`)** — fixed 100dvh shell: topbar (logo → home), session pills, component library palette, rounded 3D viewport (multi-object, cobalt selection) + independently scrollable inspector, fixed prompt card with coral Generate.

## Components

Trays, session tabs, revision items, component library palette, prompt bar, generate button, parametric dials, assembly tree, object placement fields, file rows, download buttons, viewport overlays — all inherit Open Kit tokens above.

## Assembly interaction (M9)

- **Component library** is a horizontal palette above the workspace body. Categories (Geometry / Fasteners / Mechanical / Electronics / Templates) open as compact CAD-style dropdown overlays — only one open, shell height fixed. Coral pill **Add** inserts a registry component with no LLM call.
- **Inspector** is the sole vertical scroll region in the workspace; header sticks while content scrolls.
- **Assembly tree** lists named objects; selection is shared with the viewport (cobalt highlight). Eye toggle is a preview; **Apply placement** commits visibility, name, and transform as one revision.
- **Object inspector** shows name, XYZ mm / Euler degrees, and registry parameters. Parameter apply is mint; placement apply is cobalt. Neither writes a revision until the explicit button.
- **Viewer** renders each component’s local STL at its transform. Repeated fasteners share one definition and N instance poses. Camera still frames on first load, reset, or a large size change only.
- **Single-part** documents (schema 3.2) still occupy the scene as one generated object so the tree stays available.

## Accessibility

- Focus: 2px cobalt outline, 3px offset.
- Contrast: ink on ivory/white ≥4.5:1; white on coral for primary button large/bold text; status colors paired with text labels.
- Reduced motion: all transitions/animations disabled under `prefers-reduced-motion`.

## Verified

- `tsc --noEmit` clean · vitest **61** · backend pytest **232** · workspace is a fixed app shell (no page scroll; inspector-only scroll).
