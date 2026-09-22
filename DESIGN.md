# DESIGN — cgen (Open Kit)

<!-- impeccable:design-schema 1 -->

## Direction contract

- **Thesis:** cgen is an open making-kit — color-coded compartments and a landing shelf of project trays; refuses monochrome brutalist CAD chrome.
- **Own-world:** warm ivory canvas, white surfaces, coral/cobalt/mint/amber roles, 12–20px radii, Bricolage Grotesque + IBM Plex Mono for measurements only.
- **Story:** creator lands on the tray shelf, opens a workspace, describes a part, previews it, inspects and downloads — color marks the compartment.
- **First viewport:** tray cards + create action; workspace: topbar, session pills, rounded viewport + inspector, generate full-height on prompt.
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
- Supporting: view fade-rise, button press lift, tab/revision transitions, engine pulse.
- Timing: 150–350ms routine; `cubic-bezier(0.16, 1, 0.3, 1)`; full `prefers-reduced-motion` kill switch.

## Surfaces

1. **Home (`WorkspaceHome`)** — shelf of workspace trays: gradient + blur covers, white titles, create tray with coral `+`.
2. **Workspace (`page.tsx`)** — topbar (brand → home), session pills, rounded 3D viewport, prompt card with full-height coral Generate, inspector sections color-labeled (cobalt inspect, amber output, mint apply).

## Components

Trays, engine pill, session tabs, revision items, prompt bar, generate button, parametric dials, file rows, download buttons, viewport overlays — all inherit Open Kit tokens above.

## Accessibility

- Focus: 2px cobalt outline, 3px offset.
- Contrast: ink on ivory/white ≥4.5:1; white on coral for primary button large/bold text; status colors paired with text labels.
- Reduced motion: all transitions/animations disabled under `prefers-reduced-motion`.

## Verified

- `tsc --noEmit` clean · vitest **54/54** · eslint: no new issues in redesigned files · `detect.mjs` on changed targets: **[]**.
