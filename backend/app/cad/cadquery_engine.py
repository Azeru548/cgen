"""Deterministic CadQuery engine (Milestone 3, extended in Milestone 6).

The engine receives already-validated Pydantic data (cad/schema.py) and
builds geometry from it. It NEVER receives or executes raw AI output:
no exec(), no eval().

Geometry conventions (all units millimeters, origin at world 0,0,0):
  box           : width (X) x depth (Y) x height (Z), centered on the origin.
  cylinder      : circular cross-section of `radius` in the XY plane, axis
                  along Z, spanning z in [-height/2, +height/2] (centered).
  cone          : frustum along Z, `bottom_radius` at z=-height/2,
                  `top_radius` at z=+height/2 (equal radii = straight cylinder).
  sphere        : `radius` about the origin.
  torus         : ring torus, axis +Z, centered on the origin.
  polygon_prism : regular n-gon prism, axis +Z, centered on the origin.
  union         : result = base + tool (boolean fuse).
  cut           : result = base - tool (boolean subtraction).
  intersect     : result = base ∩ tool (empty result is rejected).
  part          : build solid, then apply engineering features (below).

Engineering features (Milestone 6) are STRUCTURAL, not spatial: they carry
no offsets or rotation. The engine applies them in a fixed order regardless
of the order they appear in the spec (the order is the one OCCT handles
robustly — see _apply_features):

   1. holes    — drilled along +Z, centered on the solid's bounding box;
                 through holes extend through the bbox (same deterministic
                 rule as the legacy through-cylinder cut); concentric holes
                 are applied largest-first (counterbore pattern); blind
                 holes drill from the top (+Z) face down `depth`.
                  hole_pattern cuts N identical holes on a deterministic bolt
                  circle (hole i at angle 2π·i/count on circle_diameter,
                  XY-centered); fit/overlap is validated before cutting.
                  hole_grid cuts rows×cols identical holes on a deterministic
                  centered rectangular array (position (i,j) at
                  x=(i-(cols-1)/2)*spacing_x, y=(j-(rows-1)/2)*spacing_y);
                  rows=1 or cols=1 gives a straight line; extents/spacing/
                  center-overlap are validated before cutting.
  2. shell    — hollow the solid with a uniform wall, top (+Z) face open.
  3. chamfer  — all convex bbox-boundary edges parallel to X or Y, 45° bevel.
  4. fillet   — same deterministic edge set as chamfer, rounded.

Through holes: when a cylinder with through=True is the `tool` of a `cut`,
the engine ignores the tool's nominal height and instead rebuilds it to span
the base's full Z extent plus a margin, centered on the base bounding-box
center. The LLM never computes offsets; placement is deterministic.
"""

from __future__ import annotations

import math
import re
import tempfile
from pathlib import Path

from .schema import (
    BoxOperation,
    ChamferFeature,
    ConeOperation,
    CutOperation,
    CylinderOperation,
    FilletFeature,
    HoleFeature,
    HoleGridFeature,
    HolePatternFeature,
    IntersectOperation,
    PartOperation,
    PolygonPrismOperation,
    ShellFeature,
    SphereOperation,
    TorusOperation,
    UnionOperation,
)

# Extra length added on EACH side of the base when auto-extending a
# through-hole tool: large enough to guarantee overlap for a clean boolean,
# relative term keeps it sane for very large parts.
THROUGH_MARGIN_MM = 2.0
THROUGH_MARGIN_RATIO = 0.001

# Extra cutter length past a blind hole's floor so the flat tool tip cuts
# cleanly (deterministic, not AI-supplied).
HOLE_OVERSHOOT_MM = 0.5


def get_cadquery_version() -> str | None:
    try:
        import cadquery as cq

        return cq.__version__
    except Exception:
        return None


def _require_cq():
    try:
        import cadquery as cq
    except Exception as e:
        raise RuntimeError(f"CadQuery is not available: {e}") from e
    return cq


def make_box(width: float = 100.0, depth: float = 60.0, height: float = 30.0):
    """Create a simple box solid. Raises RuntimeError if CadQuery unavailable."""
    try:
        import cadquery as cq
    except Exception as e:
        raise RuntimeError(f"CadQuery is not available: {e}") from e
    if min(width, depth, height) <= 0:
        raise ValueError("Box dimensions must be positive")
    return cq.Workplane("XY").box(width, depth, height)


def make_cylinder(radius: float, height: float):
    """Z-axis cylinder of `radius`, spanning z in [-height/2, +height/2]."""
    cq = _require_cq()
    if min(radius, height) <= 0:
        raise ValueError("Cylinder dimensions must be positive")
    solid = cq.Solid.makeCylinder(radius, height)
    return solid.translate(cq.Vector(0, 0, -height / 2))


def make_cone(bottom_radius: float, top_radius: float, height: float):
    """Z-axis frustum: bottom_radius at z=-height/2, top_radius at +height/2."""
    cq = _require_cq()
    if min(bottom_radius, top_radius, height) <= 0:
        raise ValueError("Cone dimensions must be positive")
    solid = cq.Solid.makeCone(bottom_radius, top_radius, height)
    return solid.translate(cq.Vector(0, 0, -height / 2))


def make_sphere(radius: float):
    """Sphere of `radius` centered on the origin.

    NOTE: CadQuery's makeSphere defaults to angleDegrees1=0 (equator), which
    yields a hemisphere. A full sphere needs the latitude sweep -90..+90.
    """
    cq = _require_cq()
    if radius <= 0:
        raise ValueError("Sphere radius must be positive")
    return cq.Solid.makeSphere(
        radius, angleDegrees1=-90, angleDegrees2=90, angleDegrees3=360
    )


def make_torus(major_radius: float, minor_radius: float):
    """Full ring torus, axis +Z, centered on the origin.

    major_radius reaches the tube center; minor_radius is the tube radius.
    CadQuery's makeTorus(radius1, radius2) with default angles is a full
    torus (no planar cut surfaces).
    """
    cq = _require_cq()
    if min(major_radius, minor_radius) <= 0:
        raise ValueError("Torus radii must be positive")
    if minor_radius >= major_radius:
        raise ValueError(
            "Torus minor_radius must be smaller than major_radius (ring torus)"
        )
    return cq.Solid.makeTorus(major_radius, minor_radius)


def make_polygon_prism(sides: int, circumradius: float, height: float):
    """Regular n-gon prism: circumradius = center-to-vertex, axis +Z, centered.

    Workplane.polygon() inscribes the n-gon in a circle of the given DIAMETER,
    so the circumradius is passed as diameter/2. The profile starts at z=0,
    so the solid is translated down by height/2 to match the centered
    convention used by every other primitive. First vertex sits on the +X
    axis (deterministic phase).
    """
    cq = _require_cq()
    if sides < 3:
        raise ValueError("Polygon prism needs at least 3 sides")
    if min(circumradius, height) <= 0:
        raise ValueError("Polygon prism dimensions must be positive")
    solid = cq.Workplane("XY").polygon(sides, 2 * circumradius).extrude(height).val()
    return solid.translate(cq.Vector(0, 0, -height / 2))


def as_shape(obj):
    """Return a CadQuery Shape suitable for OCC boolean ops.

    `cut`/`fuse`/`intersect` read `.wrapped` on a Shape. A Workplane is a
    builder (the Milestone 1 `make_box` return type) and has no `.wrapped`;
    unwrap it with `.val()` the same way `make_polygon_prism` does.
    """
    cq = _require_cq()
    if isinstance(obj, cq.Workplane):
        val = obj.val()
        if val is None:
            raise ValueError("Workplane has no solid to operate on")
        return val
    return obj


def union(base, tool):
    """Boolean union: result = base + tool. Inputs are CadQuery shapes."""
    try:
        return as_shape(base).fuse(as_shape(tool))
    except Exception as e:
        raise RuntimeError(f"Boolean union failed: {e}") from e


def intersect(base, tool):
    """Boolean intersection: result = base ∩ tool.

    A disjoint base/tool pair produces an empty solid; that is a realistic
    outcome of an AI-described request, so it is rejected with ValueError
    (mapped to HTTP 422) instead of silently exporting nothing.
    """
    try:
        result = as_shape(base).intersect(as_shape(tool))
    except Exception as e:
        raise RuntimeError(f"Boolean intersection failed: {e}") from e
    try:
        volume = result.Volume()
    except Exception:
        volume = 0.0
    if volume <= 0:
        raise ValueError(
            "intersect produced an empty solid — base and tool do not "
            "overlap. Rephrase the request."
        )
    return result


def cut(base, tool):
    """Boolean subtraction: result = base - tool. Inputs are CadQuery shapes."""
    try:
        return as_shape(base).cut(as_shape(tool))
    except Exception as e:
        raise RuntimeError(f"Boolean cut failed: {e}") from e


def through_tool_height(zmin: float, zmax: float) -> float:
    """Pure helper (no CadQuery needed): height a through-hole tool needs to
    span the base Z extent [zmin, zmax] plus the deterministic margin."""
    span = zmax - zmin
    if span <= 0:
        raise ValueError("Base Z extent must be positive for a through hole")
    return span + 2 * max(THROUGH_MARGIN_MM, span * THROUGH_MARGIN_RATIO)


def _build_through_tool(cq, base, radius: float):
    """Rebuild a through-hole cylinder to span the base bounding box."""
    bbox = base.BoundingBox()
    height = through_tool_height(bbox.zmin, bbox.zmax)
    tool = cq.Solid.makeCylinder(radius, height)
    cx = (bbox.xmin + bbox.xmax) / 2
    cy = (bbox.ymin + bbox.ymax) / 2
    cz = (bbox.zmin + bbox.zmax) / 2
    return tool.translate(cq.Vector(cx, cy, cz - height / 2))


# --- Engineering features (Milestone 6) ---------------------------------------


def _through_tool_at(cq, solid, radius: float):
    """Through-hole cutter spanning the solid's full Z extent plus margin,
    centered on the solid's bounding-box center in X and Y."""
    return _build_through_tool(cq, solid, radius)


def _blind_tool_at(cq, solid, radius: float, depth: float):
    """Blind-hole cutter: drills from the top (+Z) face down `depth`, with a
    small deterministic overshoot so the flat tip cuts cleanly. Centered on
    the solid's bounding-box center in X and Y."""
    bbox = solid.BoundingBox()
    height = depth + HOLE_OVERSHOOT_MM
    tool = cq.Solid.makeCylinder(radius, height)
    cz = bbox.zmax - depth  # top of the cutter, above the hole floor
    return tool.translate(
        cq.Vector((bbox.xmin + bbox.xmax) / 2, (bbox.ymin + bbox.ymax) / 2, cz)
    )


def _cut_hole(solid, feature: HoleFeature):
    """Cut one hole along +Z, centered on the solid's bounding box.

    Through holes reuse the through-tool rule (full bbox extent + margin).
    Blind holes drill from the top (+Z) face down `depth`, with a small
    deterministic overshoot so the flat tip cuts cleanly.
    """
    cq = _require_cq()
    radius = feature.diameter / 2
    if feature.through:
        tool = _through_tool_at(cq, solid, radius)
        return cut(solid, tool)
    assert feature.depth is not None  # guaranteed by the schema
    tool = _blind_tool_at(cq, solid, radius, feature.depth)
    return cut(solid, tool)


# Tolerance for bolt-circle fit/overlap checks (mm). Rejections use
# ValueError so they surface as 422 through the existing error mapping.
_PATTERN_FIT_TOL_MM = 1e-6


def _validate_hole_pattern(solid, feature: HolePatternFeature, other_hole_radii: list) -> None:
    """Reject bolt circles that cannot work, before cutting anything.

    Deterministic checks against the solid's bounding box (all pattern holes
    are interior by construction when these pass):
      - the bolt circle plus one hole radius fits inside the XY half-extents;
      - adjacent holes do not overlap (chord between centers >= one diameter);
      - no hole overlaps another centered hole (e.g. the central through hole).
    """
    bbox = solid.BoundingBox()
    hx = (bbox.xmax - bbox.xmin) / 2
    hy = (bbox.ymax - bbox.ymin) / 2
    bolt_radius = feature.circle_diameter / 2
    hole_radius = feature.diameter / 2
    if bolt_radius + hole_radius > min(hx, hy) + _PATTERN_FIT_TOL_MM:
        raise ValueError(
            "hole_pattern does not fit: the bolt circle plus one hole radius "
            "extends past the part face"
        )
    chord = 2 * bolt_radius * math.sin(math.pi / feature.count)
    if chord < 2 * hole_radius - _PATTERN_FIT_TOL_MM:
        raise ValueError(
            "hole_pattern holes overlap each other: reduce the diameter, "
            "enlarge the bolt circle, or use fewer holes"
        )
    for center_radius in other_hole_radii:
        if bolt_radius < center_radius + hole_radius - _PATTERN_FIT_TOL_MM:
            raise ValueError(
                "hole_pattern overlaps the central hole: enlarge the bolt "
                "circle or use smaller holes"
            )


def _apply_hole_pattern(solid, feature: HolePatternFeature, other_hole_radii: list):
    """Cut N identical holes on the bolt circle (hole i at 2π·i/count).

    The cutter is built once from the pre-cut solid (interior holes never
    change the bbox, so every instance is identical) and translated in XY
    only. Through/blind behavior matches _cut_hole exactly.
    """
    cq = _require_cq()
    assert feature.depth is not None or feature.through  # guaranteed by schema
    _validate_hole_pattern(solid, feature, other_hole_radii)
    hole_radius = feature.diameter / 2
    bolt_radius = feature.circle_diameter / 2
    if feature.through:
        tool = _through_tool_at(cq, solid, hole_radius)
    else:
        assert feature.depth is not None
        tool = _blind_tool_at(cq, solid, hole_radius, feature.depth)
    for i in range(feature.count):
        angle = 2 * math.pi * i / feature.count
        dx = bolt_radius * math.cos(angle)
        dy = bolt_radius * math.sin(angle)
        solid = cut(solid, tool.translate(cq.Vector(dx, dy, 0)))
    return solid


def _grid_positions(feature: HoleGridFeature) -> list[tuple[float, float]]:
    """Deterministic (x, y) centers for a hole_grid, XY-centered on origin.

    A null spacing (single-hole axis, enforced by the schema) behaves as 0:
    with one hole on that axis every center sits at 0 regardless.
    """
    sx = feature.spacing_x or 0.0
    sy = feature.spacing_y or 0.0
    return [
        (
            (i - (feature.cols - 1) / 2) * sx,
            (j - (feature.rows - 1) / 2) * sy,
        )
        for j in range(feature.rows)
        for i in range(feature.cols)
    ]


def _validate_hole_grid(solid, feature: HoleGridFeature, other_hole_radii: list) -> None:
    """Reject hole grids that cannot work, before cutting anything.

    Deterministic checks against the solid's bounding box:
      - the outermost hole edges fit inside the XY half-extents;
      - adjacent holes do not overlap (each multi-hole axis spacing >=
        one diameter; single-hole axes need no spacing);
      - no grid hole overlaps another centered hole.
    Rejections use ValueError so they surface as 422.
    """
    bbox = solid.BoundingBox()
    hx = (bbox.xmax - bbox.xmin) / 2
    hy = (bbox.ymax - bbox.ymin) / 2
    hole_radius = feature.diameter / 2
    sx = feature.spacing_x or 0.0
    sy = feature.spacing_y or 0.0
    extent_x = ((feature.cols - 1) / 2) * sx + hole_radius
    extent_y = ((feature.rows - 1) / 2) * sy + hole_radius
    if extent_x > hx + _PATTERN_FIT_TOL_MM or extent_y > hy + _PATTERN_FIT_TOL_MM:
        raise ValueError(
            "hole_grid does not fit: the outermost holes extend past the part face"
        )
    if feature.cols > 1 and sx < 2 * hole_radius - _PATTERN_FIT_TOL_MM:
        raise ValueError(
            "hole_grid holes overlap each other: increase spacing_x, "
            "use smaller holes, or use fewer columns"
        )
    if feature.rows > 1 and sy < 2 * hole_radius - _PATTERN_FIT_TOL_MM:
        raise ValueError(
            "hole_grid holes overlap each other: increase spacing_y, "
            "use smaller holes, or use fewer rows"
        )
    for x, y in _grid_positions(feature):
        dist = math.hypot(x, y)
        for center_radius in other_hole_radii:
            if dist < center_radius + hole_radius - _PATTERN_FIT_TOL_MM:
                raise ValueError(
                    "hole_grid overlaps the central hole: increase the spacings "
                    "or use smaller holes"
                )


def _apply_hole_grid(solid, feature: HoleGridFeature, other_hole_radii: list):
    """Cut rows×cols identical holes on the deterministic centered grid.

    Same cutter-reuse discipline as _apply_hole_pattern: the tool is built
    once from the pre-cut solid and translated in XY only. Through/blind
    behavior matches _cut_hole exactly.
    """
    cq = _require_cq()
    assert feature.depth is not None or feature.through  # guaranteed by schema
    _validate_hole_grid(solid, feature, other_hole_radii)
    hole_radius = feature.diameter / 2
    if feature.through:
        tool = _through_tool_at(cq, solid, hole_radius)
    else:
        assert feature.depth is not None
        tool = _blind_tool_at(cq, solid, hole_radius, feature.depth)
    for dx, dy in _grid_positions(feature):
        solid = cut(solid, tool.translate(cq.Vector(dx, dy, 0)))
    return solid


def _is_axis_aligned_to_xy(edge, tol: float = 1e-6) -> bool:
    """True when a straight edge runs parallel to the X or Y axis."""
    vertices = edge.Vertices()
    if len(vertices) < 2:
        return False
    p0, p1 = vertices[0], vertices[1]
    dx = abs(p1.X - p0.X)
    dy = abs(p1.Y - p0.Y)
    dz = abs(p1.Z - p0.Z)
    x_aligned = dx > tol and dy < tol and dz < tol
    y_aligned = dy > tol and dx < tol and dz < tol
    return x_aligned or y_aligned


def _on_bbox_boundary_xy(edge, bbox, tol: float = 1e-6) -> bool:
    """True when a straight X/Y edge lies on an outer bounding-box side.

    Only the edge's CONSTANT plan coordinate must be extreme (y ∈
    {ymin, ymax} for an X-parallel edge, x ∈ {xmin, xmax} for a Y-parallel
    one); endpoints may sit anywhere along that side. A boolean fuse splits
    full-side rims at reentrant vertices, so requiring corner endpoints
    rejects every segment of fused footprints (e.g. L-brackets) even though
    the outer rims are valid fillet targets. Concave notch rims stay
    excluded (their constant coordinate is interior), and on a plain box
    the selected set is identical to the old corner-endpoint rule.
    """
    vertices = edge.Vertices()
    if len(vertices) < 2:
        return False
    p0, p1 = vertices[0], vertices[1]
    dx = abs(p1.X - p0.X)
    dy = abs(p1.Y - p0.Y)
    if dx >= dy:
        # X-parallel (the caller pre-filters axis alignment): the side is
        # defined by the constant Y.
        return abs(p0.Y - bbox.ymin) <= tol or abs(p0.Y - bbox.ymax) <= tol
    # Y-parallel: the side is defined by the constant X.
    return abs(p0.X - bbox.xmin) <= tol or abs(p0.X - bbox.xmax) <= tol


def _select_feature_edges(solid, cq):
    """Deterministic edge set for fillet/chamfer: straight edges parallel to
    X or Y that lie on the bounding-box boundary in the XY plane.

    This rounds/prisms the vertical corner edges and the top/bottom rim of
    prismatic solids (boxes, L-shapes) while never touching curved edges
    (circles, seams) — so cylinders, spheres, tori and drilled hole rims are
    always left intact.
    """
    bbox = solid.BoundingBox()
    selected = []
    for edge in solid.Edges():
        if _is_axis_aligned_to_xy(edge) and _on_bbox_boundary_xy(edge, bbox):
            selected.append(edge)
    return selected


def _apply_fillet(solid, radius: float):
    cq = _require_cq()
    edges = _select_feature_edges(solid, cq)
    if not edges:
        raise ValueError("fillet found no applicable straight boundary edges")
    try:
        return solid.fillet(radius, edges)
    except Exception as e:
        raise RuntimeError(
            "fillet failed — try a smaller radius or simpler geometry"
        ) from e


def _apply_chamfer(solid, size: float):
    cq = _require_cq()
    edges = _select_feature_edges(solid, cq)
    if not edges:
        raise ValueError("chamfer found no applicable straight boundary edges")
    try:
        # CadQuery 2.8: chamfer(length, length2, edgeList) — length2 is a
        # required positional in this release; None gives a symmetric
        # 45° chamfer of `size`.
        return solid.chamfer(size, None, edges)
    except Exception as e:
        raise RuntimeError(
            "chamfer failed — try a smaller size or simpler geometry"
        ) from e


def _apply_shell(solid, thickness: float):
    """Hollow the solid: uniform wall, top (+Z) face removed.

    OCCT silently returns the input unchanged when the thickness is too
    large for the solid (e.g. thicker than the smallest dimension), so the
    result is volume-checked: a real shell always removes material.
    """
    cq = _require_cq()
    try:
        wp = cq.Workplane("XY").newObject([solid])
        result = wp.faces(">Z").shell(-thickness)
        volume = result.val().Volume()
        if volume >= solid.Volume() * (1 - 1e-6):
            raise RuntimeError("no material removed")
        if not result.val().isValid():
            raise RuntimeError("resulting solid is invalid")
        return result.val()
    except Exception as e:
        raise RuntimeError(
            "shell failed — thickness may exceed the smallest wall spacing"
        ) from e


def _apply_features(solid, features: list):
    """Apply features in engine-fixed order: holes and hole patterns ->
    shell -> chamfer -> fillet.

    The order is NOT the spec's list order — it is the order OCCT handles
    robustly (verified empirically in M6):
      - holes first, while the solid is still full (through tools span the
        true bbox); concentric holes apply largest-first (counterbore);
        hole patterns apply after single holes so the pattern's
        center-overlap check sees the finished central holes;
      - shell before edge features (filleting or chamfering first makes the
        subsequent inner offset fail or produce invalid solids whenever the
        radius/size reaches the wall thickness);
      - chamfer before fillet (fillet leaves tangent edges that break the
        subsequent chamfer on the same solid).
    Feature list order in the spec is irrelevant; results are deterministic.
    """
    holes = [f for f in features if isinstance(f, HoleFeature)]
    for feature in sorted(holes, key=lambda h: h.diameter, reverse=True):
        solid = _cut_hole(solid, feature)
    center_radii = [h.diameter / 2 for h in holes]
    for feature in features:
        if isinstance(feature, HolePatternFeature):
            solid = _apply_hole_pattern(solid, feature, center_radii)
    for feature in features:
        if isinstance(feature, HoleGridFeature):
            solid = _apply_hole_grid(solid, feature, center_radii)
    for feature in features:
        if isinstance(feature, ShellFeature):
            solid = _apply_shell(solid, feature.thickness)
    for feature in features:
        if isinstance(feature, ChamferFeature):
            solid = _apply_chamfer(solid, feature.size)
    for feature in features:
        if isinstance(feature, FilletFeature):
            solid = _apply_fillet(solid, feature.radius)
    return solid


def build_operation(op):
    """Build a CadQuery shape from a validated operation node (recursive)."""
    cq = _require_cq()
    if isinstance(op, BoxOperation):
        dims = (op.width, op.depth, op.height)
        if min(dims) <= 0:
            raise ValueError("Box dimensions must be positive")
        w, d, h = dims
        return cq.Solid.makeBox(w, d, h, pnt=cq.Vector(-w / 2, -d / 2, -h / 2))
    if isinstance(op, CylinderOperation):
        return make_cylinder(op.radius, op.height)
    if isinstance(op, ConeOperation):
        return make_cone(op.bottom_radius, op.top_radius, op.height)
    if isinstance(op, SphereOperation):
        return make_sphere(op.radius)
    if isinstance(op, TorusOperation):
        return make_torus(op.major_radius, op.minor_radius)
    if isinstance(op, PolygonPrismOperation):
        return make_polygon_prism(op.sides, op.circumradius, op.height)
    if isinstance(op, UnionOperation):
        return union(build_operation(op.base), build_operation(op.tool))
    if isinstance(op, CutOperation):
        base = build_operation(op.base)
        tool_op = op.tool
        if isinstance(tool_op, CylinderOperation) and tool_op.through:
            if tool_op.radius <= 0:
                raise ValueError("Through-hole radius must be positive")
            tool = _build_through_tool(cq, base, tool_op.radius)
        else:
            tool = build_operation(tool_op)
        return cut(base, tool)
    if isinstance(op, IntersectOperation):
        return intersect(build_operation(op.base), build_operation(op.tool))
    if isinstance(op, PartOperation):
        solid = build_operation(op.build)
        return _apply_features(solid, op.features)
    raise ValueError(f"Unsupported operation: {type(op).__name__}")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").lower()
    return (slug or "part")[:50]


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _head_contains(path: Path, marker: bytes, limit: int) -> bool:
    try:
        with path.open("rb") as f:
            return marker in f.read(limit)
    except OSError:
        return False


def _stl_structure_ok(path: Path) -> bool:
    """Plausibility check for our exporter's STL output (no full parser).

    ASCII STL starts with "solid" and ends with an "endsolid" trailer;
    binary STL has an 84-byte header followed by 50-byte facet records.
    Only head/tail bytes are read, never the whole file.
    """
    try:
        size = path.stat().st_size
        if size <= 0:
            return False
        with path.open("rb") as f:
            head = f.read(128)
        if head.startswith(b"solid"):
            try:
                with path.open("rb") as f:
                    f.seek(max(0, size - 128))
                    tail = f.read(128)
                return b"endsolid" in tail
            except OSError:
                return False
        return size >= 84 and (size - 84) % 50 == 0
    except OSError:
        return False


def validate_exported_files(step_path: str | Path, stl_path: str | Path) -> dict:
    """Verify exported STEP/STL files are sane; raise RuntimeError otherwise.

    Checks: both exist, both non-empty, STEP carries the ISO-10303 magic,
    STL has a plausible ASCII/binary structure. The error message names only
    the failed checks — never filesystem paths.
    """
    step = Path(step_path)
    stl = Path(stl_path)
    checks = {
        "step_exists": step.is_file(),
        "step_non_empty": _file_size(step) > 0,
        "step_magic_ok": _head_contains(step, b"ISO-10303", 64),
        "stl_exists": stl.is_file(),
        "stl_non_empty": _file_size(stl) > 0,
        "stl_structure_ok": _stl_structure_ok(stl),
    }
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise RuntimeError(f"Export validation failed: {', '.join(failed)}")
    return checks


def _export_solid(solid, stem: str, out_dir: str | Path | None = None) -> dict:
    cq = _require_cq()
    target = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="cgen_"))
    target.mkdir(parents=True, exist_ok=True)

    step_path = target / f"{stem}.step"
    stl_path = target / f"{stem}.stl"

    try:
        cq.exporters.export(solid, str(step_path))
    except Exception as e:
        raise RuntimeError(f"STEP export failed: {e}") from e
    try:
        cq.exporters.export(solid, str(stl_path))
    except Exception as e:
        raise RuntimeError(f"STL export failed: {e}") from e

    return {
        "step_path": str(step_path),
        "stl_path": str(stl_path),
        "step_bytes": step_path.stat().st_size,
        "stl_bytes": stl_path.stat().st_size,
        "cadquery_version": get_cadquery_version(),
    }


def export_operation(operation, name: str = "part", out_dir: str | Path | None = None) -> dict:
    """Build any validated operation and export STEP + STL. Returns metadata."""
    solid = build_operation(operation)
    op_type = getattr(operation, "type", "part")
    result = _export_solid(solid, f"{_slugify(name)}_{op_type}", out_dir)
    result.update({"operation": op_type, "units": "mm"})
    return result


def export_box(
    width: float = 100.0,
    depth: float = 60.0,
    height: float = 30.0,
    out_dir: str | Path | None = None,
) -> dict:
    """Create box, export STEP + STL to out_dir, return file metadata."""
    solid = make_box(width, depth, height)

    target = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="cgen_"))
    target.mkdir(parents=True, exist_ok=True)

    step_path = target / f"box_{width}x{depth}x{height}.step"
    stl_path = target / f"box_{width}x{depth}x{height}.stl"

    try:
        import cadquery as cq

        cq.exporters.export(solid, str(step_path))
    except Exception as e:
        raise RuntimeError(f"STEP export failed: {e}") from e

    try:
        import cadquery as cq

        cq.exporters.export(solid, str(stl_path))
    except Exception as e:
        raise RuntimeError(f"STL export failed: {e}") from e

    return {
        "width": width,
        "depth": depth,
        "height": height,
        "units": "mm",
        "step_path": str(step_path),
        "stl_path": str(stl_path),
        "step_bytes": step_path.stat().st_size,
        "stl_bytes": stl_path.stat().st_size,
        "cadquery_version": get_cadquery_version(),
    }


def apply_transform(solid, position: tuple[float, float, float], rotation: tuple[float, float, float]):
    """Rotate XYZ Euler degrees about the origin, then translate (mm)."""
    cq = _require_cq()
    solid = as_shape(solid)
    rx, ry, rz = rotation
    origin = cq.Vector(0, 0, 0)
    if rx:
        solid = solid.rotate(origin, cq.Vector(1, 0, 0), rx)
    if ry:
        solid = solid.rotate(origin, cq.Vector(0, 1, 0), ry)
    if rz:
        solid = solid.rotate(origin, cq.Vector(0, 0, 1), rz)
    x, y, z = position
    if x or y or z:
        solid = solid.translate(cq.Vector(x, y, z))
    return solid


def export_solids(solids: list, stem: str, out_dir: str | Path | None = None) -> dict:
    """Export one or more solids as a STEP/STL compound (identity preserved)."""
    if not solids:
        raise ValueError("Nothing to export — the assembly has no solids.")
    cq = _require_cq()
    shapes = [as_shape(s) for s in solids]
    if len(shapes) == 1:
        compound = shapes[0]
    else:
        compound = cq.Compound.makeCompound(shapes)
    result = _export_solid(compound, stem, out_dir)
    result.update({"operation": "assembly", "units": "mm"})
    return result
