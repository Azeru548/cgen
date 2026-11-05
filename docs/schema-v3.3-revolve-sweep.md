# Report — schema v3.3: revolve and sweep

Status: shipped on `main` in `d3938eb` (operations) plus the follow-up validity
guard. Backend **412 tests passing**, frontend **116 tests passing**,
`tsc --noEmit` clean.

## Why

The schema only allowed `box`, `cylinder`, `cone`, `sphere`, `torus`,
`polygon_prism` and booleans. Anything turned about an axis (pulleys, knobs,
bushings, flanges, cups, funnels) or routed along a path (pipes, handles,
hooks, wire) had to be faked by stacking primitives, which is exactly the
"crude shapes matched together" problem. Two operations close that gap without
touching the pipeline: the LLM still emits JSON, Pydantic still validates, the
same CadQuery engine still builds and exports.

## The two operations

### `revolve`

```json
{"type": "revolve", "profile": [[6, -8], [12, -8], [12, 8], [6, 8]], "angle": 360}
```

`profile` is the axial **half-section**: `[radius, height]` pairs in mm, where
radius is the distance from the Z axis (`0` = a point on the axis) and height is
the position along it. The polygon is closed automatically; points must go
around the section in order. `angle` is optional (default `360`) and may be
anything up to a full turn, for arc-shaped parts.

### `sweep`

```json
{"type": "sweep", "radius": 4, "path": [[0, 0, 0], [50, 0, 0], [50, 0, 50]], "closed": false}
```

A circular wire of `radius` swept along a 3D polyline of 2–24 `[x, y, z]`
points. Corners are rounded into elbows (round transition, Frenet frame), so a
90° bend is a smooth tube joint, not a mitre. `closed: true` joins the last
point back to the first for a loop (frame, ring handle).

Both are ordinary **build operations**, so they compose:

- inside `union` / `cut` / `intersect`;
- as the `build` of a `part` node, where holes, `shell`, `chamfer` and `fillet`
  are applied by the engine;
- as one node against the existing caps (depth 4, 15 operation nodes).

Both are then translated so their **bounding-box centre is the origin**, the
same "everything is centred" invariant every other primitive follows, so
boolean placement stays deterministic and the LLM still never positions parts.
Centring does not break concentricity: expanding a path by a wire radius grows
the bounding box equally on every side, so two sweeps along the same path share
a centre.

## Validation (all rejected before OCCT sees the geometry)

| Operation | Rejected |
|---|---|
| `revolve` | fewer than 3 points; collinear profile (zero enclosed area); any negative radius (section crossing the axis); all points on the axis; more than 32 points; `angle` ≤ 0 or > 360; unknown fields |
| `sweep` | fewer than 2 distinct points; identical consecutive points; zero radius; `closed` with fewer than 3 distinct points; more than 24 points; unknown fields |
| both | a built shape OCCT reports as invalid or empty → clear `ValueError` (HTTP 422) instead of a corrupt STL |

The last rule matters in practice: a wire whose radius is wider than the gap
between two path segments still returns *a* shape from OCCT, but it
self-intersects (`isValid()` is false). Previously that would have exported
broken geometry; now it fails with
`"sweep produced an invalid (self-intersecting) solid; check the profile/path
and reduce the section or wire size"`.

## Geometry conventions worth knowing

- **Revolve axis.** The section is built on CadQuery's `XZ` workplane (local x →
  world X = radius, local y → world Z = height) and revolved about the
  workplane's local y axis, which is world **+Z**. Verified: a rectangular
  section r = 10…20, z = 0…5 yields exactly π(20² − 10²)·5 = 4712.4 mm³.
  A 180° revolve is exactly half of the 360° volume.
- **Profile radii instead of fillets.** A rounded corner on a turned part is
  modelled as several profile points (`[[0,-25],[40,-25],[40,22],[37,25],[0,25]]`),
  not as a fillet feature — see limits.
- **Hollow pipes.** `sweep` is a solid wire. A hollow elbow is
  `cut { base: sweep r20, tool: sweep r16 }` on the same path: 4 mm wall,
  verified at 134.6 cm³ against 135.7 cm³ analytic for a 300 mm elbow.
- **Cups.** A `revolve` is a solid of revolution: give the full section
  including the inner wall, or build the solid and add a `shell` feature (both
  verified).

## What changed, by file

| File | Change |
|---|---|
| `backend/app/cad/schema.py` | `RevolveOperation`, `SweepOperation`, point caps, geometry validators, both added to `Operation`/`BuildOperation`, `SPEC_VERSION` → `3.3` |
| `backend/app/cad/cadquery_engine.py` | `make_revolve`, `make_sweep`, `_center_on_origin`, `_profile_points`, `_require_valid_solid`, dispatch in `build_operation`, docstring conventions |
| `backend/app/ai/groq_client.py` | allowed operation list, both operations documented with examples, routing rules, revolve/sweep-specific rules, modification prompt list |
| `frontend/types/api.ts` | `OperationType`, `RevolveOperation`, `SweepOperation`, `BuildOperation` |
| `frontend/lib/api.ts` | contract guard accepts both types |
| `frontend/lib/spec.ts` | labels, one-line summaries, dimension rows (revolve: section points/angle/outer ⌀/height; sweep: wire ⌀/path points/true path length/closed) |
| `frontend/app/page.tsx` | landing-page operation list + glyphs; library category counts corrected to what the registry actually holds (6/17/13/16/11/9) |
| `backend/app/main.py`, `README.md`, `PRODUCT.md`, `DESIGN.md` | version and operation-table updates to v3.3 |
| `backend/tests/test_schema.py` | 9 tests: valid revolve/sweep, partial angle, axis points, every rejection path, point caps, node counting |
| `backend/tests/test_engine.py` | 12 tests: exact volumes and centring, partial-angle proportionality, cone-from-section, tubes, bends, closed loops, 3D paths, hollow elbow, invalid sweep, part/union composition, STEP+STL export |
| `frontend/tests/spec.test.ts`, `frontend/tests/api.test.ts` | labels, summaries, dimension rows, and the contract guard (which previously asserted `revolve` was **rejected**) |

## Prompt cost

The system prompt (base instructions + the 72-type registry catalog) is now
**22,031 characters ≈ 5.5k tokens**, up ~900 characters from before. The new
text teaches both operations with one example each, plus the routing rules
(prefer `revolve` over stacked cylinders, `sweep` over cylinder unions) and two
correctness rules that came out of testing (no fillet/chamfer on profile
builds; keep the wire radius below the corner gap).

## Known limits (deliberate, stated in the UI text and prompt)

- **No fillet or chamfer on a `revolve`/`sweep` build.** The engine's fillet and
  chamfer target the outer straight boundary edges of a box-like solid; a
  revolved body has none, so the request fails with
  `"fillet found no applicable straight boundary edges"`. The prompt now tells
  the model to put the radius in the profile instead. `shell` and holes *do*
  work on both.
- **Paths are polylines, not arcs.** A bend is as smooth as the number of points
  given; there is no arc or spline primitive.
- **Constant wire radius.** No tapered or flattened sweeps.
- **Self-intersection is rejected, not repaired.**
- **No threads, no helical sweep** — a spring still needs a stack of tori or a
  library part.
- **Modification cannot swap operation types.** "Modify" keeps the tree shape;
  turning a box into a revolve is a new part.
- **Prompt output is a guess about intent.** A vague prompt ("make it nicer")
  can still route to primitives; the prompts below are written the way the
  router expects.

## Test prompts

Paste these into the prompt bar. "Expected" is the operation you should see in
the spec panel's tree; "check" is the visual/geometric result.

### Revolve

| # | Prompt | Expected | Check |
|---|---|---|---|
| 1 | `A pulley 40 mm outer diameter, 30 mm bore, 12 mm wide, with a 4 mm flange on each side` | `revolve` | round part, flanges at both rims, clean Ø30 bore |
| 2 | `A bushing 16 mm outer diameter, 10 mm bore, 20 mm long, with a 1 mm chamfer on both bore edges` | `revolve` | chamfer reads as a cone at the bore, not a fillet |
| 3 | `A control knob 30 mm diameter, 18 mm tall, 6 mm D-shaft bore, domed top` | `revolve` | dome is smooth, bore present, no stacked discs |
| 4 | `A funnel: 44 mm mouth, 8 mm spout, 30 mm tall, 2 mm wall` | `revolve` | hollow cone with a tube spout; wall visible in section |
| 5 | `A cup 70 mm tall, 80 mm outside diameter, 4 mm wall, closed bottom` | `revolve` (or `part` + `shell`) | open top, flat closed bottom, even 4 mm wall |
| 6 | `Half a shaft collar: 40 mm outer diameter, 10 mm bore, 12 mm long, only 180 degrees` | `revolve` with `angle: 180` | exactly half a ring — a C, not a full collar |
| 7 | `A flanged boss: 60 mm flange 8 mm thick, 30 mm boss 40 mm tall, 25 mm through bore, four 6 mm holes on a 48 mm bolt circle` | `part` over a `revolve` build | flange + boss as one body, four holes on the circle |

### Sweep

| # | Prompt | Expected | Check |
|---|---|---|---|
| 8 | `A drawer handle 120 mm long with two 25 mm standoff legs, 10 mm rod` | `sweep` | two elbows, rounded corners, equal legs |
| 9 | `A 90 degree pipe elbow, 40 mm outside diameter, 32 mm inside, 150 mm legs` | `cut` of two `sweep`s | hollow bore all the way through, even 4 mm wall |
| 10 | `A wire hook: 60 mm straight, then a 180 degree bend, then 30 mm back, 3 mm wire` | `sweep` with 6–8 path points | U-turn looks round, no kinks |
| 11 | `A picture-frame handle: 100 x 60 mm rectangular loop from 8 mm rod` | `sweep` with `closed: true` | closed loop, four rounded corners, no seam gap |
| 12 | `A 3D bent tube: up 80 mm, then 60 mm along X, then down 40 mm along Z, 6 mm rod` | `sweep` with 4 points | genuinely 3D path, elbows rounded |

### Composition and regressions

| # | Prompt | Expected | Check |
|---|---|---|---|
| 13 | `A tube bracket: 20 mm cube with a 6 mm rod passing through it and out both sides by 30 mm` | `union` of `box` + `sweep` | single solid, rod emerges centred from both faces |
| 14 | `An Arduino Uno enclosure 90 x 70 x 40 mm with a USB cutout and a lid` | `3d_assembly` | still the M9 benchmark: enclosure + board + lid + screws |
| 15 | `A GT2 pulley, 20 teeth, 6 mm belt, 5 mm bore` | library `gt2_pulley` | 20 grooves visible; this is a **library** part, not a revolve |
| 16 | `An M3 socket cap screw 12 mm long and an M3 nut` | library `m3_screw` + `m3_nut` | hex head/nut chamfers, no thread modelling |

### Things that should fail cleanly (readable error, not a broken model)

| # | Prompt | Expected behaviour |
|---|---|---|
| 17 | `A 10 mm rod bent through a 90 degree corner with an 8 mm gap` | rejected: wire wider than the corner gap → *"sweep produced an invalid (self-intersecting) solid…"* |
| 18 | `Fillet the outer rim of a revolved cup with a 3 mm radius` | the prompt now steers the model to profile points instead; if it still emits a `fillet` on a revolve, the engine answers *"fillet found no applicable straight boundary edges"* |
| 19 | `Make it nicer` | should be treated as a modification request, and the structural guard refuses to redesign the part |

### What to look at while testing

- **Spec panel**: the tree shows `Revolve · 8-point section · 360°` or
  `Sweep · ⌀10 × 4-point path`; the rows below give outer diameter and height
  (revolve) or wire diameter, path length and closed flag (sweep).
- **Geometry sanity**: revolve volumes are π(R² − r²)·h for annular sections;
  a straight sweep is πr²L; a 90° elbow keeps ~95 % of the straight-run volume.
- **Downloads**: STEP should stay well under a megabyte for these parts; the
  STL is tessellated at 0.01 mm, so a dense part can be a few hundred kB.

## Running the checks

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests/ -q      # 412 passed
cd frontend && npx tsc --noEmit && npx vitest run               # 116 passed
```
