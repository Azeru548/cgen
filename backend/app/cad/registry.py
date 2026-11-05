"""Deterministic component registry (Milestone 9).

The registry is the authoritative vocabulary of reusable components.
The LLM may only name types that exist here. Geometry is produced by
factories in this module — never by generated code.

A factory either:
  * maps onto an existing CADSpec operation (primitives), or
  * builds a CadQuery solid with local transforms (fasteners, boards).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Literal

from .schema import (
    BoxOperation,
    ConeOperation,
    CylinderOperation,
    HoleFeature,
    PartOperation,
    PolygonPrismOperation,
    ShellFeature,
    SphereOperation,
    TorusOperation,
)

ParamKind = Literal["length", "count", "choice", "flag"]
ParamValue = float | int | bool | str
Category = Literal[
    "geometry", "fasteners", "mechanical", "electronics", "robotics", "templates"
]


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    kind: ParamKind
    default: ParamValue
    minimum: float | None = None
    maximum: float | None = None
    options: tuple[str, ...] | None = None
    unit: str | None = "mm"
    description: str = ""


@dataclass(frozen=True)
class BoardProfile:
    """Published PCB envelope used by electronics parts and the enclosure."""

    key: str
    width: float
    depth: float
    height: float
    hole_diameter: float
    holes_xy: tuple[tuple[float, float], ...]
    usb_offset_x: float
    usb_width: float
    usb_height: float
    usb_z: float


@dataclass(frozen=True)
class ComponentDef:
    type: str
    category: Category
    display_name: str
    description: str
    parameters: tuple[ParamSpec, ...]
    insertable: bool = True
    parameterized: bool = True
    builder: Callable[[dict[str, ParamValue]], object] | None = field(
        default=None, compare=False, hash=False
    )


# --- Board envelopes (local origin at PCB centre, USB toward -X) ------------

# Arduino Uno Rev3: 68.6 x 53.4 mm, four M3-clearance holes.
# Hole coordinates converted from the published bottom-left origin.
_ARDUINO = BoardProfile(
    key="arduino_uno",
    width=68.6,
    depth=53.4,
    height=1.6,
    hole_diameter=3.2,
    holes_xy=(
        (13.97 - 34.3, 2.54 - 26.7),
        (15.24 - 34.3, 50.8 - 26.7),
        (66.04 - 34.3, 35.56 - 26.7),
        (66.04 - 34.3, 7.62 - 26.7),
    ),
    usb_offset_x=-34.3,
    usb_width=12.0,
    usb_height=11.0,
    usb_z=6.5,
)

_RASPI = BoardProfile(
    key="raspberry_pi",
    width=85.0,
    depth=56.0,
    height=1.6,
    hole_diameter=2.75,
    holes_xy=(
        (3.5 - 42.5, 3.5 - 28.0),
        (61.5 - 42.5, 3.5 - 28.0),
        (3.5 - 42.5, 52.5 - 28.0),
        (61.5 - 42.5, 52.5 - 28.0),
    ),
    usb_offset_x=42.5,
    usb_width=15.0,
    usb_height=16.0,
    usb_z=8.0,
)

_ESP32 = BoardProfile(
    key="esp32",
    width=55.0,
    depth=28.0,
    height=1.6,
    hole_diameter=3.0,
    holes_xy=(
        (2.5 - 27.5, 2.5 - 14.0),
        (52.5 - 27.5, 2.5 - 14.0),
        (2.5 - 27.5, 25.5 - 14.0),
        (52.5 - 27.5, 25.5 - 14.0),
    ),
    usb_offset_x=-27.5,
    usb_width=8.0,
    usb_height=3.2,
    usb_z=2.5,
)

_PICO = BoardProfile(
    key="raspberry_pi_pico",
    width=51.0,
    depth=21.0,
    height=1.6,
    hole_diameter=2.1,
    holes_xy=(
        (2.0 - 25.5, 2.0 - 10.5),
        (49.0 - 25.5, 2.0 - 10.5),
        (2.0 - 25.5, 19.0 - 10.5),
        (49.0 - 25.5, 19.0 - 10.5),
    ),
    usb_offset_x=-25.5,
    usb_width=8.0,
    usb_height=3.2,
    usb_z=2.0,
)

_NANO = BoardProfile(
    key="arduino_nano",
    width=45.0,
    depth=18.0,
    height=1.6,
    hole_diameter=2.2,
    holes_xy=(
        (2.0 - 22.5, 2.0 - 9.0),
        (43.0 - 22.5, 2.0 - 9.0),
        (2.0 - 22.5, 16.0 - 9.0),
        (43.0 - 22.5, 16.0 - 9.0),
    ),
    usb_offset_x=-22.5,
    usb_width=8.0,
    usb_height=3.5,
    usb_z=2.0,
)

BOARDS: dict[str, BoardProfile] = {
    _ARDUINO.key: _ARDUINO,
    _RASPI.key: _RASPI,
    _ESP32.key: _ESP32,
}


def _f(params: dict[str, ParamValue], key: str) -> float:
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"parameter '{key}' must be a number")
    return float(value)


def _i(params: dict[str, ParamValue], key: str) -> int:
    value = params[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"parameter '{key}' must be an integer")
    return int(value)


def _b(params: dict[str, ParamValue], key: str) -> bool:
    value = params[key]
    if not isinstance(value, bool):
        raise ValueError(f"parameter '{key}' must be true or false")
    return value


def _s(params: dict[str, ParamValue], key: str) -> str:
    value = params[key]
    if not isinstance(value, str):
        raise ValueError(f"parameter '{key}' must be a string")
    return value


def _require_cq():
    from .cadquery_engine import _require_cq as _cq

    return _cq()


def _cut(base, tool):
    from .cadquery_engine import cut

    return cut(base, tool)


def _union(base, tool):
    from .cadquery_engine import union

    return union(base, tool)


def _box(w: float, d: float, h: float):
    """Origin-centered box Solid — same convention as build_operation(Box).

    Do not use cadquery_engine.make_box here: that Milestone 1 helper
    returns a Workplane, which boolean cut/fuse cannot consume.
    """
    cq = _require_cq()
    if min(w, d, h) <= 0:
        raise ValueError("Box dimensions must be positive")
    return cq.Solid.makeBox(w, d, h, pnt=cq.Vector(-w / 2, -d / 2, -h / 2))


def _cyl(r: float, h: float):
    from .cadquery_engine import make_cylinder

    return make_cylinder(r, h)


def _translate(solid, x: float, y: float, z: float):
    cq = _require_cq()
    if x == 0 and y == 0 and z == 0:
        return solid
    return solid.translate(cq.Vector(x, y, z))


def _hex_prism(across_flats: float, height: float):
    from .cadquery_engine import make_polygon_prism

    circum = across_flats / math.sqrt(3)
    return make_polygon_prism(6, circum, height)


def _cone(bottom_radius: float, top_radius: float, height: float):
    """Z-axis frustum, centered (matches make_cylinder's convention)."""
    from .cadquery_engine import make_cone

    return make_cone(bottom_radius, top_radius, height)


def _sphere(radius: float):
    """Full sphere. cq.Solid.makeSphere alone is a hemisphere, so go through
    the engine helper that sweeps latitude -90..+90."""
    from .cadquery_engine import make_sphere

    return make_sphere(radius)


def _rotate_x(solid, degrees: float):
    cq = _require_cq()
    return solid.rotate(cq.Vector(0, 0, 0), cq.Vector(1, 0, 0), degrees)


def _chamfered_rod(radius: float, length: float, chamfer: float):
    """Centered Z rod with 45° end chamfers (clamped to what the rod allows)."""
    c = max(0.0, min(chamfer, radius * 0.45, length * 0.45))
    if c < 0.05:
        return _cyl(radius, length)
    core = _cyl(radius, length - 2 * c)
    top = _translate(_cone(radius, radius - c, c), 0, 0, length / 2 - c / 2)
    bottom = _translate(_cone(radius - c, radius, c), 0, 0, -length / 2 + c / 2)
    return _union(_union(core, top), bottom)


# --- Profile toolkit -------------------------------------------------------
#
# Real parts are defined by a cross-section, not by stacking boxes. These
# helpers extrude a closed polygon (sampled arcs are fine at 0.05 mm) and
# repeat cutters around an axis, which is what gear teeth, GT2 grooves,
# T-slot extrusions, knurls and bolt circles all need.


def _rotate_z(solid, degrees: float):
    cq = _require_cq()
    return solid.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), degrees)


def _arc_points(
    cx: float, cy: float, radius: float, start_deg: float, end_deg: float, steps: int
) -> list[tuple[float, float]]:
    """Sampled circular arc as (x, y) points, inclusive of both ends."""
    if steps < 1:
        raise ValueError("arc needs at least one step")
    return [
        (
            cx + radius * math.cos(math.radians(start_deg + (end_deg - start_deg) * i / steps)),
            cy + radius * math.sin(math.radians(start_deg + (end_deg - start_deg) * i / steps)),
        )
        for i in range(steps + 1)
    ]


def _dedupe(points: list[tuple[float, float]], tol: float = 1e-6):
    """Drop repeated profile points; a zero-length line kills the OCC edge."""
    out: list[tuple[float, float]] = []
    for point in points:
        if not out or math.dist(point, out[-1]) > tol:
            out.append(point)
    if len(out) > 2 and math.dist(out[0], out[-1]) <= tol:
        out.pop()
    if len(out) < 3:
        raise ValueError("profile collapsed to fewer than three points")
    return out


def _profile_solid(points: list[tuple[float, float]], height: float):
    """Extrude a closed XY profile along Z, centred like every other part."""
    cq = _require_cq()
    if height <= 0:
        raise ValueError("profile height must be positive")
    pts = _dedupe(points)
    # OCC needs the outer wire wound counter-clockwise; a reversed profile
    # extrudes a solid that reports itself invalid.
    area = 0.0
    for i, (x0, y0) in enumerate(pts):
        x1, y1 = pts[(i + 1) % len(pts)]
        area += x0 * y1 - x1 * y0
    if area < 0:
        pts.reverse()
    wp = cq.Workplane("XY").moveTo(*pts[0])
    for x, y in pts[1:]:
        wp = wp.lineTo(x, y)
    solid = wp.close().extrude(height).val()
    return solid.translate(cq.Vector(0, 0, -height / 2))


def _bolt_holes(
    solid,
    count: int,
    bolt_circle: float,
    hole_diameter: float,
    height: float,
    z: float = 0.0,
    start_deg: float = 0.0,
):
    """Cut `count` through holes evenly spaced on a bolt circle."""
    for i in range(count):
        angle = math.radians(start_deg + 360.0 * i / count)
        cutter = _cyl(hole_diameter / 2, height)
        cutter = _translate(
            cutter, bolt_circle / 2 * math.cos(angle), bolt_circle / 2 * math.sin(angle), z
        )
        solid = _cut(solid, cutter)
    return solid


def _chamfered_hex(across_flats: float, height: float):
    """Hex body with the standard 30° chamfer on both faces."""
    circum = across_flats / math.sqrt(3)
    chamfer = max(0.1, min(height * 0.2, (circum - across_flats / 2) * math.sqrt(3)))
    core = _hex_prism(across_flats, max(height - 2 * chamfer, 0.2))
    top = _translate(_cone(circum, across_flats / 2, chamfer), 0, 0, height / 2 - chamfer / 2)
    bottom = _translate(_cone(across_flats / 2, circum, chamfer), 0, 0, -height / 2 + chamfer / 2)
    return _union(_union(core, top), bottom)


def _helix_sweep(radius: float, wire_radius: float, pitch: float, height: float):
    """Round-wire helix swept along a true helical path (spring, not a stack)."""
    cq = _require_cq()
    path = cq.Wire.makeHelix(pitch=pitch, height=height, radius=radius)
    profile = cq.Workplane("XZ").center(radius, 0).circle(wire_radius)
    solid = profile.sweep(path, isFrenet=True).val()
    return solid.translate(cq.Vector(0, 0, -height / 2))


def _intersect(base, tool):
    from .cadquery_engine import intersect

    return intersect(base, tool)


def _rounded_rect(
    width: float, depth: float, radius: float, steps: int = 5
) -> list[tuple[float, float]]:
    """Closed rounded-rectangle profile centred on the origin."""
    r = max(0.0, min(radius, width / 2 - 1e-3, depth / 2 - 1e-3))
    if r < 1e-3:
        return [
            (-width / 2, -depth / 2),
            (width / 2, -depth / 2),
            (width / 2, depth / 2),
            (-width / 2, depth / 2),
        ]
    points: list[tuple[float, float]] = []
    corners = (
        (width / 2 - r, -depth / 2 + r, -90.0),
        (width / 2 - r, depth / 2 - r, 0.0),
        (-width / 2 + r, depth / 2 - r, 90.0),
        (-width / 2 + r, -depth / 2 + r, 180.0),
    )
    for cx, cy, start in corners:
        points.extend(_arc_points(cx, cy, r, start, start + 90.0, steps))
    return points


def _ring(outer_radius: float, inner_radius: float, height: float):
    """Annulus solid centred on the origin (disc minus bore)."""
    if inner_radius >= outer_radius:
        raise ValueError("ring inner radius must be smaller than the outer radius")
    return _cut(_cyl(outer_radius, height), _cyl(inner_radius, height + 4))


def _revolve_profile(points: list[tuple[float, float]], angle: float = 360.0):
    """Revolve a closed (radius, z) section around the Z axis.

    Bodies of revolution (collars, flanges, knobs) are defined by their axial
    section, so chamfers and fillets are exact arcs instead of boolean bevels.
    """
    cq = _require_cq()
    pts = _dedupe(points)
    if min(r for r, _ in pts) < 0:
        raise ValueError("revolved profile has a negative radius")
    wp = cq.Workplane("XZ").moveTo(*pts[0])
    for point in pts[1:]:
        wp = wp.lineTo(*point)
    return wp.close().revolve(angle, (0, 0, 0), (0, 1, 0)).val()


def _involute_gear_points(module: float, teeth: int, pressure_angle: float = 20.0):
    """Closed spur-gear outline with true involute flanks.

    Flanks are sampled from the involute of the base circle between the root
    and addendum radii, joined by root and tip arcs. This is the real tooth
    form (not a trapezoid approximation), just polyline-sampled.
    """
    if teeth < 6:
        raise ValueError("spur_gear needs at least 6 teeth")
    if module <= 0:
        raise ValueError("spur_gear module must be positive")
    alpha = math.radians(pressure_angle)
    pitch_r = module * teeth / 2
    base_r = pitch_r * math.cos(alpha)
    addendum_r = pitch_r + module
    root_r = max(pitch_r - 1.25 * module, module * 0.5)
    inv_alpha = math.tan(alpha) - alpha
    half_angle = math.pi / (2 * teeth) - inv_alpha
    if half_angle <= 0:
        raise ValueError("spur_gear tooth geometry is degenerate at this pressure angle")
    t_tip = math.sqrt(max((addendum_r / base_r) ** 2 - 1.0, 1e-9))

    def flank(t: float) -> tuple[float, float]:
        x = base_r * (math.cos(t) + t * math.sin(t))
        y = base_r * (math.sin(t) - t * math.cos(t))
        return math.atan2(y, x), base_r * math.sqrt(1.0 + t * t)

    steps = 8
    points: list[tuple[float, float]] = []
    step_angle = 2 * math.pi / teeth
    for k in range(teeth):
        centre = k * step_angle
        start_t = 0.0 if root_r < base_r else math.sqrt((root_r / base_r) ** 2 - 1.0)
        ts = [start_t + (t_tip - start_t) * i / steps for i in range(steps + 1)]
        if root_r < base_r:
            points.append((centre - half_angle, root_r))
        for t in ts:
            angle, radius = flank(t)
            points.append((centre - half_angle - angle, radius))
        low = centre - half_angle - flank(t_tip)[0]
        high = centre + half_angle + flank(t_tip)[0]
        for i in range(1, 4):
            points.append((low + (high - low) * i / 4, addendum_r))
        for t in reversed(ts):
            angle, radius = flank(t)
            points.append((centre + half_angle + angle, radius))
        if root_r < base_r:
            points.append((centre + half_angle, root_r))
        gap_end = centre + step_angle - half_angle
        for i in range(1, 4):
            points.append((centre + half_angle + (gap_end - centre - half_angle) * i / 4, root_r))
    return [
        (radius * math.cos(angle), radius * math.sin(angle)) for angle, radius in points
    ]


# --- Primitive builders (map onto existing operations, then CadQuery) ------


def _build_from_operation(op):
    from .cadquery_engine import build_operation

    return build_operation(op)


def build_box(params: dict[str, ParamValue]):
    return _build_from_operation(
        BoxOperation(
            width=_f(params, "width"),
            depth=_f(params, "depth"),
            height=_f(params, "height"),
        )
    )


def build_cylinder(params: dict[str, ParamValue]):
    return _build_from_operation(
        CylinderOperation(radius=_f(params, "radius"), height=_f(params, "height"))
    )


def build_sphere(params: dict[str, ParamValue]):
    return _build_from_operation(SphereOperation(radius=_f(params, "radius")))


def build_cone(params: dict[str, ParamValue]):
    return _build_from_operation(
        ConeOperation(
            bottom_radius=_f(params, "bottom_radius"),
            top_radius=_f(params, "top_radius"),
            height=_f(params, "height"),
        )
    )


def build_torus(params: dict[str, ParamValue]):
    return _build_from_operation(
        TorusOperation(
            major_radius=_f(params, "major_radius"),
            minor_radius=_f(params, "minor_radius"),
        )
    )


def build_prism(params: dict[str, ParamValue]):
    return _build_from_operation(
        PolygonPrismOperation(
            sides=_i(params, "sides"),
            circumradius=_f(params, "circumradius"),
            height=_f(params, "height"),
        )
    )


# --- Fasteners (local origin at the tip, axis +Z) --------------------------
#
# Metric fasteners follow the published envelope: socket-head cap screws get a
# cylindrical head with a hex recess (a hex prism head is a bolt, not a cap
# screw), and hex nuts get the 30° face chamfer that makes them look machined.


def _screw_head(solid, diameter: float, head_af: float, head_h: float, kind: str, length: float):
    """Add the requested head form on top of a shank that ends at z=length.

    `countersunk` is a 90° flat head, `button` a shallow dome, `socket` the
    cylindrical cap-screw head, and `hex` the legacy hex-prism bolt head. All
    four get a hex drive recess on the top face.
    """
    if kind == "hex":
        head = _hex_prism(head_af, head_h)
        head = _translate(head, 0, 0, length + head_h / 2)
        recess = _hex_prism(head_af * 0.45, head_h * 1.1)
        return _cut(_union(solid, head), _translate(recess, 0, 0, length + head_h * 0.75))
    if kind == "countersunk":
        cone_h = max(0.4, (head_af * 1.1 - diameter) / 2)
        head = _cone(diameter / 2, head_af * 1.1 / 2, cone_h)
        head = _translate(head, 0, 0, length + cone_h / 2)
        recess = _hex_prism(head_af * 0.4, cone_h * 1.1)
        return _cut(
            _union(solid, head), _translate(recess, 0, 0, length + cone_h)
        )
    if kind == "button":
        dome_r = head_af / 2
        dome = _require_cq().Solid.makeSphere(dome_r, angleDegrees1=-90, angleDegrees2=90)
        dome = _translate(dome, 0, 0, length + head_h - dome_r)
        # Clip the sphere exactly at the head base so the dome never bulges
        # into the shank.
        keep = _box(head_af + 1, head_af + 1, head_h)
        dome = _intersect(dome, _translate(keep, 0, 0, length + head_h / 2))
        head = _translate(_cyl(dome_r, head_h * 0.4), 0, 0, length + head_h * 0.2)
        merged = _union(_union(solid, head), dome)
        recess = _hex_prism(head_af * 0.4, head_h * 0.9)
        return _cut(merged, _translate(recess, 0, 0, length + head_h * 0.55))
    head = _cyl(head_af / 2, head_h)
    head = _translate(head, 0, 0, length + head_h / 2)
    recess = _hex_prism(head_af * 0.45, head_h * 1.2)
    return _cut(
        _union(solid, head), _translate(recess, 0, 0, length + head_h * 0.7)
    )


def _metric_screw(diameter: float, head_af: float, head_h: float):
    """Metric screw: chamfered shank plus a head form chosen per instance."""

    def builder(params: dict[str, ParamValue]):
        length = _f(params, "length")
        kind = _s(params, "head") if "head" in params else "socket"
        shank = _chamfered_rod(diameter / 2, length, min(0.4, length * 0.1))
        shank = _translate(shank, 0, 0, length / 2)
        return _screw_head(shank, diameter, head_af, head_h, kind, length)

    return builder


def _metric_nut(hole: float, af: float, height: float):
    """Hex nut with the standard 30° chamfer on both faces."""

    def builder(params: dict[str, ParamValue]):
        body = _chamfered_hex(af, height)
        cutter = _cyl(hole / 2, height + 4)
        return _cut(body, cutter)

    return builder


def build_washer(params: dict[str, ParamValue]):
    inner = _f(params, "inner_diameter")
    outer = _f(params, "outer_diameter")
    thickness = _f(params, "thickness")
    kind = _s(params, "kind") if "kind" in params else "flat"
    if inner >= outer:
        raise ValueError("washer inner_diameter must be smaller than outer_diameter")
    body = _cut(_cyl(outer / 2, thickness), _cyl(inner / 2, thickness + 4))
    if kind == "split":
        # Spring washer: one radial slit through the annulus.
        gap = _box(outer * 0.12, outer * 2.2, thickness + 4)
        body = _cut(body, _translate(gap, outer / 2, 0, 0))
    return body


def build_set_screw(params: dict[str, ParamValue]):
    """Grub screw: headless chamfered body, hex drive at both ends, cup point."""
    diameter = _f(params, "diameter")
    length = _f(params, "length")
    body = _chamfered_rod(diameter / 2, length, min(0.3, diameter * 0.15))
    drive = _hex_prism(diameter * 0.45, length * 0.45)
    for sign in (-1.0, 1.0):
        body = _cut(body, _translate(drive, 0, 0, sign * (length / 2 - length * 0.2)))
    cup = _require_cq().Solid.makeSphere(diameter * 0.3)
    return _cut(body, _translate(cup, 0, 0, -length / 2))


def build_threaded_rod(params: dict[str, ParamValue]):
    """All-thread rod envelope (threads are not modelled)."""
    diameter = _f(params, "diameter")
    length = _f(params, "length")
    return _chamfered_rod(diameter / 2, length, min(0.6, diameter * 0.2))


def build_t_nut(params: dict[str, ParamValue]):
    """T-slot hammer nut: rounded block, raised boss, through hole."""
    width = _f(params, "width")
    length = _f(params, "length")
    thickness = _f(params, "thickness")
    boss = _f(params, "boss_diameter")
    boss_h = _f(params, "boss_height")
    hole = _f(params, "hole_diameter")
    if hole >= min(boss, width) * 0.9:
        raise ValueError("t_nut hole_diameter is too large for the body")
    body = _profile_solid(_rounded_rect(width, length, min(width, length) * 0.18), thickness)
    boss_solid = _cyl(boss / 2, boss_h)
    body = _union(body, _translate(boss_solid, 0, 0, thickness / 2 + boss_h / 2))
    return _cut(body, _cyl(hole / 2, thickness + boss_h + 4))


def build_nyloc_nut(params: dict[str, ParamValue]):
    """Nyloc nut: chamfered hex body with the nylon collar on top."""
    hole = _f(params, "hole_diameter")
    af = _f(params, "across_flats")
    height = _f(params, "height")
    collar = _f(params, "collar_height")
    if hole >= af * 0.85:
        raise ValueError("nyloc hole_diameter must be smaller than across_flats")
    body = _chamfered_hex(af, height)
    body = _union(body, _translate(_cyl(af / 2 * 0.93, collar), 0, 0, height / 2 + collar / 2))
    return _cut(body, _cyl(hole / 2, height + collar + 4))


def build_standoff(params: dict[str, ParamValue]):
    length = _f(params, "length")
    outer = _f(params, "outer_diameter")
    hole = _f(params, "hole_diameter")
    if hole >= outer:
        raise ValueError("standoff hole_diameter must be smaller than outer_diameter")
    body = _cyl(outer / 2, length)
    cutter = _cyl(hole / 2, length + 4)
    return _cut(body, cutter)


# --- Mechanical ------------------------------------------------------------


def build_heat_insert(params: dict[str, ParamValue]):
    """Heat-set threaded insert for printed plastic: tapered body + top flange."""
    length = _f(params, "length")
    outer = _f(params, "outer_diameter")
    hole = _f(params, "hole_diameter")
    if hole >= outer * 0.85:
        raise ValueError("heat insert hole_diameter must be clearly smaller than outer_diameter")
    flange_h = min(0.6, length * 0.15)
    body = _cone(outer / 2 * 0.9, outer / 2, length - flange_h)
    body = _translate(body, 0, 0, -flange_h / 2)
    flange = _cyl(outer / 2 * 1.18, flange_h)
    flange = _translate(flange, 0, 0, length / 2 - flange_h / 2)
    solid = _union(body, flange)
    cutter = _cyl(hole / 2, length + 4)
    return _cut(solid, cutter)


def build_hex_standoff(params: dict[str, ParamValue]):
    """Hex standoff with a through hole (threads not modelled)."""
    length = _f(params, "length")
    af = _f(params, "across_flats")
    hole = _f(params, "hole_diameter")
    if hole >= af * 0.85:
        raise ValueError("standoff hole_diameter must be smaller than across_flats")
    body = _hex_prism(af, length)
    cutter = _cyl(hole / 2, length + 4)
    return _cut(body, cutter)


def build_bracket(params: dict[str, ParamValue]):
    """L-bracket with two mounting holes in each leg."""
    width = _f(params, "width")
    depth = _f(params, "depth")
    height = _f(params, "height")
    thickness = _f(params, "thickness")
    hole = _f(params, "hole_diameter")
    if thickness >= min(width, depth, height):
        raise ValueError("bracket thickness must be smaller than width, depth and height")
    if hole * 2.5 >= min(width, height):
        raise ValueError(
            "bracket hole_diameter is too large for this width and height"
        )
    base = _box(width, depth, thickness)
    base = _translate(base, 0, 0, thickness / 2)
    wall = _box(width, thickness, height)
    wall = _translate(wall, 0, -depth / 2 + thickness / 2, height / 2)
    solid = _union(base, wall)

    hole_x = (-width / 4, width / 4)
    for x in hole_x:
        # Base: vertical through hole.
        cutter = _cyl(hole / 2, thickness + 4)
        cutter = _translate(cutter, x, 0, thickness / 2)
        solid = _cut(solid, cutter)
        # Wall: horizontal through hole (along Y).
        cutter = _cyl(hole / 2, depth + 4)
        cutter = _rotate_x(cutter, 90.0)
        cutter = _translate(cutter, x, -depth / 2 + thickness / 2, height / 2)
        solid = _cut(solid, cutter)
    return solid


def build_spacer(params: dict[str, ParamValue]):
    return _build_from_operation(
        PartOperation(
            build=CylinderOperation(
                radius=_f(params, "outer_diameter") / 2,
                height=_f(params, "length"),
            ),
            features=[
                HoleFeature(diameter=_f(params, "hole_diameter"), through=True),
            ],
        )
    )


def build_shaft(params: dict[str, ParamValue]):
    """Plain shaft with 45° end chamfers (the lead-in real shafts have)."""
    return _chamfered_rod(
        _f(params, "diameter") / 2,
        _f(params, "length"),
        _f(params, "chamfer"),
    )


def build_bearing(params: dict[str, ParamValue]):
    od = _f(params, "outer_diameter")
    id_ = _f(params, "inner_diameter")
    width = _f(params, "width")
    if id_ >= od:
        raise ValueError("bearing inner_diameter must be smaller than outer_diameter")
    return _build_from_operation(
        PartOperation(
            build=CylinderOperation(radius=od / 2, height=width),
            features=[HoleFeature(diameter=id_, through=True)],
        )
    )


def build_hinge(params: dict[str, ParamValue]):
    """Butt hinge: segmented barrel with pin, two leaves and screw holes."""
    length = _f(params, "length")
    knuckle = _f(params, "knuckle_diameter")
    leaf = _f(params, "leaf_width")
    thickness = _f(params, "thickness")
    hole = _f(params, "hole_diameter")
    if hole >= min(leaf, length / 2) * 0.9:
        raise ValueError("hinge hole_diameter is too large for the leaf")

    pin = _cyl(knuckle / 2 * 0.55, length + 2)
    barrel = _cyl(knuckle / 2, length)
    # Two shallow ring grooves divide the barrel into knuckles without
    # splitting the solid (a real hinge's knuckles are separate parts, which a
    # single watertight export cannot represent).
    groove_w = max(0.6, length * 0.035)
    for z in (-length / 6, length / 6):
        ring = _cut(_cyl(knuckle / 2 + 1, groove_w), _cyl(knuckle / 2 - 0.6, groove_w))
        barrel = _cut(barrel, _translate(ring, 0, 0, z))

    # Leaves overlap the barrel by 0.5 mm so the fuse is a real union rather
    # than a tangent contact.
    overlap = 0.5
    left = _box(leaf, length, thickness)
    left = _translate(left, -leaf / 2 - knuckle / 2 + overlap, 0, 0)
    right = _box(leaf, length, thickness)
    right = _translate(right, leaf / 2 + knuckle / 2 - overlap, 0, 0)
    solid = _union(_union(_union(barrel, pin), left), right)

    for side in (-1.0, 1.0):
        x = side * (knuckle / 2 + leaf / 2)
        for y in (-length / 4, length / 4):
            cutter = _cyl(hole / 2, thickness + 4)
            cutter = _translate(cutter, x, y, 0)
            solid = _cut(solid, cutter)
    return solid


def build_spur_gear(params: dict[str, ParamValue]):
    """Spur gear: involute teeth, bore and a chamfer on both bore edges."""
    module = _f(params, "module")
    teeth = _i(params, "teeth")
    thickness = _f(params, "thickness")
    bore = _f(params, "bore_diameter")
    pitch_r = module * teeth / 2
    root_r = pitch_r - 1.25 * module
    if bore / 2 + 0.6 >= root_r:
        raise ValueError("spur_gear bore_diameter leaves no material under the teeth")
    body = _profile_solid(_involute_gear_points(module, teeth), thickness)
    bore_cutter = _cyl(bore / 2, thickness + 4)
    body = _cut(body, bore_cutter)
    bevel = 0.35
    for sign in (-1.0, 1.0):
        chamfer = _cone(bore / 2 + bevel, bore / 2, bevel)
        body = _cut(
            body, _translate(chamfer, 0, 0, sign * (thickness / 2 - bevel / 2))
        )
    return body


def build_gt2_pulley(params: dict[str, ParamValue]):
    """GT2 timing pulley: trapezoid grooves, two flanges, hub and set screw."""
    teeth = _i(params, "teeth")
    belt_width = _f(params, "belt_width")
    bore = _f(params, "bore_diameter")
    set_screw = _b(params, "set_screw")
    pitch_d = 2.0 * teeth / math.pi
    rim = (pitch_d - 0.25) / 2
    groove_depth = 0.75
    groove_floor = rim - groove_depth
    if groove_floor <= bore / 2 + 0.6:
        raise ValueError(
            "gt2_pulley bore_diameter leaves no material under the grooves"
        )
    body = _cyl(rim, belt_width)
    # GT2 belt tooth: wider at the root than at the crest, so the mating
    # groove is wider at its floor.
    wide, narrow = 1.15, 0.9
    groove = _profile_solid(
        [
            (groove_floor, -wide / 2),
            (rim + 1.0, -narrow / 2),
            (rim + 1.0, narrow / 2),
            (groove_floor, wide / 2),
        ],
        belt_width,
    )
    for i in range(teeth):
        body = _cut(body, _rotate_z(groove, 360.0 * i / teeth))
    flange_r = rim + 0.8
    for sign in (-1.0, 1.0):
        flange = _cyl(flange_r, 0.6)
        body = _union(body, _translate(flange, 0, 0, sign * (belt_width / 2 + 0.3)))
    hub_d = min(rim * 2 * 0.88, bore + 6.0)
    hub_h = 4.0
    hub_z = belt_width / 2 + 0.6 + hub_h / 2
    body = _union(body, _translate(_cyl(hub_d / 2, hub_h), 0, 0, hub_z))
    body = _cut(body, _cyl(bore / 2, belt_width + hub_h + 8))
    if set_screw:
        hole = _cyl(1.6, hub_d / 2 - bore / 2 + 1.0)
        hole = _rotate_x(hole, 90.0)
        body = _cut(
            body, _translate(hole, 0, 0, hub_z)
        )
    return body


def build_v_slot_extrusion(params: dict[str, ParamValue]):
    """T-slot extrusion: square bar with four real T-slots and a centre bore.

    Slot proportions follow the published 2020 section: 6.2 mm opening, 2 mm
    opening depth, 11.5 mm channel and a 3.5 mm channel depth.
    """
    size = _f(params, "size")
    length = _f(params, "length")
    bore = _f(params, "bore_diameter")
    if bore >= size * 0.45:
        raise ValueError("v_slot bore_diameter is too large for the profile")
    half = size / 2
    opening = size * 0.31
    opening_d = size * 0.10
    channel = size * 0.575
    channel_d = size * 0.175
    body = _box(size, size, length)
    # One slot profile with chamfered inner corners: square channel corners
    # would meet at the 45° diagonals and cut the corner webs clean through.
    inner = half - opening_d - channel_d
    chamfer = channel_d * 0.55
    slot_profile = [
        (-opening / 2, half),
        (opening / 2, half),
        (opening / 2, half - opening_d),
        (channel / 2, half - opening_d),
        (channel / 2, inner + chamfer),
        (channel / 2 - chamfer, inner),
        (-channel / 2 + chamfer, inner),
        (-channel / 2, inner + chamfer),
        (-channel / 2, half - opening_d),
        (-opening / 2, half - opening_d),
    ]
    slot = _profile_solid(slot_profile, length + 2)
    for i in range(4):
        body = _cut(body, _rotate_z(slot, 90.0 * i))
    corner = size * 0.06
    for i in range(4):
        trim = _box(corner * 2, corner * 2, length + 2)
        trim = _rotate_z(trim, 45.0)
        trim = _translate(trim, half, half, 0)
        body = _cut(body, _rotate_z(trim, 90.0 * i))
    if bore > 0:
        body = _cut(body, _cyl(bore / 2, length + 4))
    return body


def build_shaft_coupling(params: dict[str, ParamValue]):
    """Rigid shaft coupling: two bores, clamp slit and cross screws."""
    length = _f(params, "length")
    outer = _f(params, "outer_diameter")
    bore_a = _f(params, "bore_a")
    bore_b = _f(params, "bore_b")
    if max(bore_a, bore_b) >= outer * 0.8:
        raise ValueError("coupling bores are too large for the outer diameter")
    body = _chamfered_rod(outer / 2, length, min(0.8, outer * 0.06))
    for bore, sign in ((bore_a, -1.0), (bore_b, 1.0)):
        depth = length * 0.62
        cutter = _cyl(bore / 2, depth + 2)
        body = _cut(body, _translate(cutter, 0, 0, sign * (length / 2 - depth / 2)))
    slit = _box(1.0, outer, length + 2)
    body = _cut(body, _translate(slit, 0, outer / 3.6, 0))
    for sign in (-1.0, 1.0):
        hole = _cyl(1.7, outer + 2)
        hole = _rotate_y(hole, 90.0)
        body = _cut(body, _translate(hole, 0, outer * 0.34, sign * length * 0.22))
    return body


def build_shaft_collar(params: dict[str, ParamValue]):
    """Shaft collar: revolved section with chamfered rims and a set-screw hole."""
    shaft = _f(params, "shaft_diameter")
    outer = _f(params, "outer_diameter")
    width = _f(params, "width")
    set_screw = _b(params, "set_screw")
    if shaft >= outer * 0.85:
        raise ValueError("collar shaft_diameter is too large for the outer diameter")
    inner = shaft / 2
    rim = outer / 2
    bevel = min(0.5, width * 0.2, (rim - inner) * 0.4)
    body = _revolve_profile(
        [
            (inner, -width / 2),
            (rim, -width / 2),
            (rim, width / 2 - bevel),
            (rim - bevel, width / 2),
            (inner, width / 2),
        ]
    )
    if set_screw:
        # Radial M3 grub-screw hole from the outer surface into the bore.
        hole = _cyl(1.5, rim - inner + 0.6)
        hole = _rotate_x(hole, 90.0)
        body = _cut(body, _translate(hole, 0, (rim + inner) / 2, 0))
    return body


def build_flange(params: dict[str, ParamValue]):
    """Bolt-on flange: revolved disc + hub section, then bolt circle and bore."""
    outer = _f(params, "outer_diameter")
    bore = _f(params, "bore_diameter")
    thickness = _f(params, "thickness")
    bolt_count = _i(params, "bolt_count")
    bolt_circle = _f(params, "bolt_circle")
    bolt = _f(params, "bolt_diameter")
    hub_h = _f(params, "hub_height")
    if bore >= outer * 0.85:
        raise ValueError("flange bore_diameter is too large for the outer diameter")
    if bolt_circle >= outer - bolt * 0.5:
        raise ValueError("flange bolt_circle does not fit inside the outer diameter")
    if bolt_circle <= bore + bolt:
        raise ValueError("flange bolt_circle collides with the bore")
    inner = bore / 2
    rim = outer / 2
    bevel = min(0.8, thickness * 0.25)
    section = [
        (inner, -thickness / 2),
        (rim, -thickness / 2),
        (rim, thickness / 2 - bevel),
        (rim - bevel, thickness / 2),
    ]
    if hub_h > 0:
        hub_r = max(inner + 3.0, rim * 0.55)
        section.extend(
            [
                (hub_r, thickness / 2),
                (hub_r, thickness / 2 + hub_h - bevel),
                (hub_r - bevel, thickness / 2 + hub_h),
                (inner, thickness / 2 + hub_h),
            ]
        )
    else:
        section.append((inner, thickness / 2))
    body = _revolve_profile(section)
    body = _bolt_holes(body, bolt_count, bolt_circle, bolt, thickness + hub_h + 4)
    return body


def build_compression_spring(params: dict[str, ParamValue]):
    """Compression spring: round wire swept along a helical pitch."""
    wire = _f(params, "wire_diameter")
    coil = _f(params, "coil_diameter")
    coils = _i(params, "coils")
    free_length = _f(params, "free_length")
    if wire >= coil * 0.45:
        raise ValueError("spring wire_diameter is too thick for the coil_diameter")
    pitch = (free_length - wire) / coils
    if pitch <= wire * 1.05:
        raise ValueError("spring free_length is too short for that wire and coil count")
    return _helix_sweep(coil / 2 - wire / 2, wire / 2, pitch, pitch * coils)


def build_dowel_pin(params: dict[str, ParamValue]):
    """Dowel pin: parallel pin with the small end chamfers dowels carry."""
    diameter = _f(params, "diameter")
    length = _f(params, "length")
    return _chamfered_rod(diameter / 2, length, min(0.4, diameter * 0.12))


# --- Robotics (expanded) ---------------------------------------------------


def _spline_bore(outer_radius: float, teeth: int, height: float):
    """Toothed (splined) bore profile, cut through a servo horn boss."""
    points: list[tuple[float, float]] = []
    for i in range(teeth * 2):
        angle = math.radians(360.0 * i / (teeth * 2))
        radius = outer_radius if i % 2 == 0 else outer_radius * 0.86
        points.append((radius * math.cos(angle), radius * math.sin(angle)))
    return _profile_solid(points, height)


def build_servo_horn(params: dict[str, ParamValue]):
    """Servo horn: splined boss plus a rounded arm with a row of link holes."""
    arm = _f(params, "arm_length")
    boss_d = _f(params, "boss_diameter")
    thickness = _f(params, "thickness")
    hole = _f(params, "hole_diameter")
    holes = _i(params, "holes")
    spline = _i(params, "spline_teeth")
    if hole >= arm * 0.5:
        raise ValueError("servo_horn hole_diameter is too large for the arm")
    boss = _cyl(boss_d / 2, thickness)
    spline_cut = _spline_bore(boss_d * 0.24, spline, thickness + 4)
    boss = _cut(boss, spline_cut)
    arm_width = boss_d * 0.72
    profile = _rounded_rect(arm, arm_width, arm_width / 2)
    arm_solid = _translate(_profile_solid(profile, thickness), arm / 2, 0, 0)
    body = _union(boss, arm_solid)
    for i in range(holes):
        x = arm / 2 - arm_width / 2 + arm_width * (i + 1) / (holes + 1)
        body = _cut(body, _translate(_cyl(hole / 2, thickness + 4), x, 0, 0))
    return body


def build_linear_rail(params: dict[str, ParamValue]):
    """MGN-style linear rail with a carriage block and mounting holes."""
    length = _f(params, "length")
    rail_w = _f(params, "rail_width")
    blocks = _i(params, "blocks")
    block_len = _f(params, "block_length")
    rail_h = rail_w * 0.62
    if blocks * block_len > length * 1.05:
        raise ValueError("linear_rail blocks are longer than the rail")
    body = _box(rail_w, rail_h, length)
    raceway_r = rail_w * 0.09
    for sign in (-1.0, 1.0):
        for x in (-rail_w * 0.32, rail_w * 0.32):
            groove = _cyl(raceway_r, length + 2)
            body = _cut(body, _translate(groove, x, sign * rail_h / 2, 0))
    pitch = 25.0
    holes = max(1, int(length // pitch))
    for i in range(holes):
        z = -length / 2 + pitch / 2 + i * pitch
        body = _cut(body, _translate(_cyl(rail_w * 0.14, rail_h + 2), 0, 0, z))
    block_w = rail_w * 1.9
    block_h = rail_h * 1.6
    spacing = length / (blocks + 1)
    for i in range(blocks):
        z = -length / 2 + spacing * (i + 1)
        block = _box(block_w, block_h, block_len)
        block = _translate(block, 0, rail_h / 2 + block_h / 2 - rail_h * 0.15, z)
        body = _union(body, block)
        for sx in (-1.0, 1.0):
            for sz in (-1.0, 1.0):
                hole = _cyl(rail_w * 0.12, block_h + 2)
                body = _cut(
                    body,
                    _translate(
                        hole,
                        sx * block_w * 0.3,
                        rail_h / 2 + block_h - rail_h * 0.15,
                        z + sz * block_len * 0.28,
                    ),
                )
    return body


def build_wheel_hub(params: dict[str, ParamValue]):
    """Wheel hub: motor-shaft bore, raised boss and a bolt circle."""
    hub_d = _f(params, "hub_diameter")
    thickness = _f(params, "thickness")
    shaft = _f(params, "shaft_diameter")
    bolt_count = _i(params, "bolt_count")
    bolt_circle = _f(params, "bolt_circle")
    bolt = _f(params, "bolt_diameter")
    if shaft >= hub_d * 0.8:
        raise ValueError("wheel_hub shaft_diameter is too large for the hub")
    if bolt_circle >= hub_d - bolt:
        raise ValueError("wheel_hub bolt_circle does not fit inside the hub")
    if bolt_circle <= shaft + bolt:
        raise ValueError("wheel_hub bolt_circle collides with the shaft bore")
    inner = shaft / 2
    rim = hub_d / 2
    bevel = min(0.6, thickness * 0.2)
    body = _revolve_profile(
        [
            (inner, -thickness / 2),
            (rim, -thickness / 2),
            (rim, thickness / 2 - bevel),
            (rim - bevel, thickness / 2),
            (inner, thickness / 2),
        ]
    )
    boss = _cyl(hub_d * 0.3, thickness * 0.5)
    body = _union(body, _translate(boss, 0, 0, thickness / 2 + thickness * 0.25))
    body = _bolt_holes(body, bolt_count, bolt_circle, bolt, thickness + 4)
    return body


def build_ball_caster(params: dict[str, ParamValue]):
    """Ball caster: mounting plate, cup shell, captive ball and three posts."""
    ball_d = _f(params, "ball_diameter")
    plate = _f(params, "plate_width")
    height = _f(params, "total_height")
    hole = _f(params, "hole_diameter")
    if height <= ball_d * 0.8:
        raise ValueError("ball_caster total_height is too short for that ball")
    ball_r = ball_d / 2
    shell = 1.2
    center_z = -height / 2 + ball_r
    # The cup caps the TOP hemisphere; the ball protrudes below the housing.
    cup = _cut(_sphere(ball_r + shell), _sphere(ball_r + 0.15))
    keep = _box(ball_d * 3, ball_d * 3, ball_r + shell + 1.0)
    cup = _intersect(cup, _translate(keep, 0, 0, (ball_r + shell + 1.0) / 2))
    cup = _translate(cup, 0, 0, center_z)
    housing_top = height / 2 - 1.0
    housing_h = housing_top - center_z
    body = _union(cup, _translate(_cyl(ball_r + shell, housing_h), 0, 0, center_z + housing_h / 2))
    top = _translate(_box(plate, plate, 2.0), 0, 0, housing_top)
    body = _union(body, top)
    for angle in (45.0, 165.0, 285.0):
        radians = math.radians(angle)
        rib = _box(2.0, ball_d * 0.9, housing_h * 0.8)
        body = _union(
            body,
            _rotate_z(
                _translate(rib, (ball_r + shell) * 0.35, 0, center_z + housing_h * 0.45),
                angle,
            ),
        )
    ball = _translate(_sphere(ball_r), 0, 0, center_z)
    for sx in (-1.0, 1.0):
        hole_cutter = _cyl(hole / 2, 6.0)
        body = _cut(body, _translate(hole_cutter, sx * plate * 0.28, 0, housing_top))
    return _union(body, ball)


def build_idler_pulley(params: dict[str, ParamValue]):
    """Smooth idler pulley: grooved rim, two flanges and a bearing seat."""
    outer = _f(params, "outer_diameter")
    bore = _f(params, "bore_diameter")
    width = _f(params, "width")
    groove = _f(params, "groove_depth")
    if bore >= outer * 0.7:
        raise ValueError("idler bore_diameter is too large for the outer diameter")
    inner = bore / 2
    rim = outer / 2
    if groove >= (rim - inner) * 0.6:
        raise ValueError("idler groove_depth is too deep for the wall")
    bevel = 0.4
    flange = 0.9
    body = _revolve_profile(
        [
            (inner, -width / 2),
            (rim, -width / 2),
            (rim, -width / 2 + flange - bevel),
            (rim - bevel, -width / 2 + flange),
            (rim - groove, 0.0),
            (rim - bevel, width / 2 - flange),
            (rim, width / 2 - flange + bevel),
            (rim, width / 2),
            (inner, width / 2),
        ]
    )
    return body


# --- Electronics -----------------------------------------------------------


def _build_board(profile: BoardProfile):
    def builder(params: dict[str, ParamValue]):
        pcb = _box(profile.width, profile.depth, profile.height)
        for hx, hy in profile.holes_xy:
            cutter = _cyl(profile.hole_diameter / 2, profile.height + 4)
            cutter = _translate(cutter, hx, hy, 0)
            pcb = _cut(pcb, cutter)
        return pcb

    return builder


def build_breadboard(params: dict[str, ParamValue]):
    width = _f(params, "width")
    depth = _f(params, "depth")
    height = _f(params, "height")
    return _box(width, depth, height)


# --- Hardware peripherals (M10.1) ------------------------------------------
#
# Envelopes follow common published sizes for the named part class. They are
# representative mechanical envelopes for layout and clearance work, not
# manufacturer-verified drawings.


def build_oled_module(params: dict[str, ParamValue]):
    """0.96\" I2C OLED: PCB envelope with the 4-pin header footprint."""
    width = _f(params, "width")
    depth = _f(params, "depth")
    pcb = _box(width, depth, 1.6)
    header = _box(21.0, 2.54, 2.54)
    header = _translate(header, 0, depth / 2 - 1.27, 2.07)
    return _union(pcb, header)


def build_lcd_module(params: dict[str, ParamValue]):
    """16x2 character LCD: board, display bezel, and 4 corner holes."""
    width = _f(params, "width")
    depth = _f(params, "depth")
    body = _box(width, depth, 1.6)
    glass = _box(width - 4.0, 14.0, 2.0)
    glass = _translate(glass, 0, depth / 2 - 9.0, 1.8)
    solid = _union(body, glass)
    inset_x = width / 2 - 2.54
    inset_y = depth / 2 - 2.54
    for hx in (-inset_x, inset_x):
        for hy in (-inset_y, inset_y):
            cutter = _cyl(1.1, 6.0)
            cutter = _translate(cutter, hx, hy, 0)
            solid = _cut(solid, cutter)
    return solid


def build_push_button(params: dict[str, ParamValue]):
    """Tactile switch: body, plunger, and 2 lead pins."""
    body = _box(6.0, 6.0, 3.5)
    plunger = _cyl(1.5, 2.0)
    plunger = _translate(plunger, 0, 0, 2.75)
    solid = _union(body, plunger)
    for px in (-1.27, 1.27):
        pin = _cyl(0.3, 6.0)
        pin = _translate(pin, px, 0, -1.5)
        solid = _union(solid, pin)
    return solid


def build_potentiometer(params: dict[str, ParamValue]):
    """Trimmer potentiometer: body block, adjustment screw, 3 pins."""
    body = _box(9.5, 4.5, 10.0)
    screw = _cyl(1.5, 2.5)
    screw = _translate(screw, 0, 0, 6.25)
    solid = _union(body, screw)
    for px in (-2.54, 0.0, 2.54):
        pin = _cyl(0.3, 2.0)
        pin = _translate(pin, px, 0, -5.0)
        solid = _union(solid, pin)
    return solid


def build_fan(params: dict[str, ParamValue]):
    """Axial fan: rounded frame, struts, hub and tilted blades."""
    size = _f(params, "size")
    thickness = _f(params, "thickness")
    hole = _f(params, "hole_diameter")
    blades = _i(params, "blades")
    hub_d = _f(params, "hub_diameter")
    if hub_d >= size * 0.7:
        raise ValueError("fan hub_diameter is too large for the frame")
    frame = _profile_solid(_rounded_rect(size, size, size * 0.09), thickness)
    frame = _cut(frame, _cyl((size - 6.0) / 2, thickness + 2))
    inset = size * 0.09
    for sx in (-1.0, 1.0):
        for sy in (-1.0, 1.0):
            frame = _cut(
                frame,
                _translate(_cyl(hole / 2, thickness + 2), sx * (size / 2 - inset), sy * (size / 2 - inset), 0),
            )
    hub = _cyl(hub_d / 2, thickness * 0.7)
    hub = _cut(hub, _cyl(hub_d * 0.16, thickness + 2))
    body = _union(frame, hub)
    strut_len = (size - 6.0 - hub_d) / 2 + 1.0
    for angle in (0.0, 120.0, 240.0):
        strut = _box(strut_len, hub_d * 0.3, thickness * 0.7)
        strut = _translate(strut, hub_d / 2 + strut_len / 2 - 1.0, 0, 0)
        body = _union(body, _rotate_z(strut, angle))
    blade_len = (size - 7.5 - hub_d) / 2
    for i in range(blades):
        blade = _box(blade_len, hub_d * 0.55, thickness * 0.45)
        blade = _rotate_y(blade, 22.0)
        blade = _translate(blade, hub_d / 2 + blade_len / 2 - 0.4, 0, 0)
        body = _union(body, _rotate_z(blade, 360.0 * i / blades))
    return body


def build_battery_holder(params: dict[str, ParamValue]):
    """Printed cell cradle: open half-pipe trough, end caps and strap slots."""
    cell_d = _f(params, "cell_diameter")
    cell_l = _f(params, "cell_length")
    wall = _f(params, "wall")
    cells = _i(params, "cells")
    if wall >= cell_d * 0.35:
        raise ValueError("battery_holder wall is too thick for the cell diameter")
    inner = cell_d / 2
    outer = inner + wall
    pitch = cell_d + wall * 2.6
    footprint = (cells - 1) * pitch + outer * 2 + wall
    body = _box(cell_l, footprint, wall)
    for c in range(cells):
        y = (c - (cells - 1) / 2) * pitch
        trough = _rotate_y(_cyl(outer, cell_l), 90.0)
        body = _union(body, _translate(trough, 0, y, 0))
    # Open the top: everything above the cell centreline goes away.
    body = _cut(body, _translate(_box(cell_l + 2, footprint + 2, cell_d * 2), 0, 0, cell_d))
    for c in range(cells):
        y = (c - (cells - 1) / 2) * pitch
        bore = _rotate_y(_cyl(inner - 0.15, cell_l + 2), 90.0)
        body = _cut(body, _translate(bore, 0, y, 0))
    for sign in (-1.0, 1.0):
        # Overlap the cap into the trough by 0.4 mm so the fuse is a real union.
        cap = _box(wall, footprint, outer)
        cap = _translate(cap, sign * (cell_l / 2 + wall / 2 - 0.4), 0, 0)
        body = _union(body, cap)
        cap_hole = _rotate_y(_cyl(inner * 0.35, wall + 2), 90.0)
        for c in range(cells):
            y = (c - (cells - 1) / 2) * pitch
            body = _cut(body, _translate(cap_hole, sign * (cell_l / 2 + wall / 2), y, 0))
    # Strap grooves: shallow 2 mm bands around the outside, never cut through
    # the wall (that would split the cradle into loose pieces).
    for x in (-cell_l * 0.28, cell_l * 0.28):
        for c in range(cells):
            y = (c - (cells - 1) / 2) * pitch
            band = _ring(outer + 1.0, outer - 1.4, 2.0)
            body = _cut(body, _translate(_rotate_y(band, 90.0), x, y, 0))
    return body


def build_pin_header(params: dict[str, ParamValue]):
    """2.54 mm pin header: insulated body with square posts or sockets."""
    pins = _i(params, "pins")
    rows = _i(params, "rows")
    pitch = _f(params, "pitch")
    pin_height = _f(params, "pin_height")
    gender = _s(params, "gender")
    block_h = 2.54
    body = _profile_solid(
        _rounded_rect(pins * pitch, rows * pitch, pitch * 0.18), block_h
    )
    post = 0.64
    for row in range(rows):
        y = (row - (rows - 1) / 2) * pitch
        for col in range(pins):
            x = (col - (pins - 1) / 2) * pitch
            if gender == "female":
                socket = _box(post * 1.35, post * 1.35, block_h + 2)
                body = _cut(body, _translate(socket, x, y, 0))
                rim = _box(post * 1.9, post * 1.9, 0.5)
                body = _cut(body, _translate(rim, x, y, block_h / 2 - 0.2))
            else:
                body = _union(body, _translate(_box(post, post, pin_height), x, y, 0))
    return body


def build_barrel_jack(params: dict[str, ParamValue]):
    """DC barrel jack: barrel, flange plate, centre pin and solder tabs."""
    barrel_d = _f(params, "outer_diameter")
    length = _f(params, "length")
    flange_w = _f(params, "flange_width")
    flange_h = _f(params, "flange_height")
    pin_d = _f(params, "pin_diameter")
    if pin_d >= barrel_d * 0.5:
        raise ValueError("barrel jack pin_diameter is too large for the barrel")
    barrel = _cyl(barrel_d / 2, length)
    barrel = _cut(barrel, _cyl(pin_d * 1.1, length + 2))
    front = _translate(_profile_solid(_rounded_rect(flange_w, flange_h, 1.0), 2.0), 0, 0, length / 2 + 1.0)
    body = _union(barrel, front)
    pin = _cyl(pin_d / 2, length + 3.0)
    body = _union(body, pin)
    for x in (-barrel_d * 0.45, 0.0, barrel_d * 0.45):
        tab = _box(2.4, 4.0, 1.0)
        body = _union(body, _translate(tab, x, 0, -length / 2 - 0.5))
    return body


def build_terminal_block(params: dict[str, ParamValue]):
    """Pitched terminal block: body plus one bore per way."""
    ways = _i(params, "ways")
    pitch = _f(params, "pitch")
    height = _f(params, "height")
    width = ways * pitch + (pitch - 3.0)
    body = _box(width, 8.0, height)
    for w in range(ways):
        x = (w - (ways - 1) / 2) * pitch
        for sy in (-2.0, 2.0):
            bore = _cyl(0.9, height + 4)
            bore = _translate(bore, x, sy, 0)
            body = _cut(body, bore)
    return body


# --- Robotics (M10.1) ------------------------------------------------------


def build_dc_motor(params: dict[str, ParamValue]):
    """DC gear motor: cylindrical can, gearbox face, and output shaft."""
    diameter = _f(params, "diameter")
    length = _f(params, "length")
    shaft_diameter = _f(params, "shaft_diameter")
    shaft_length = _f(params, "shaft_length")
    body = _cyl(diameter / 2, length)
    gearbox = _box(12.0, 12.0, 4.0)
    gearbox = _translate(gearbox, 0, 0, length / 2 + 2.0)
    solid = _union(body, gearbox)
    shaft = _cyl(shaft_diameter / 2, shaft_length)
    shaft = _translate(shaft, 0, 0, length / 2 + 4.0 + shaft_length / 2)
    return _union(solid, shaft)


def build_servo_motor(params: dict[str, ParamValue]):
    """Hobby servo: body, output boss, and two mounting ears with holes."""
    length = _f(params, "length")
    width = _f(params, "width")
    height = _f(params, "height")
    body = _box(width, length, height)
    boss = _cyl(3.0, 3.0)
    boss = _translate(boss, 0, 0, height / 2 + 1.5)
    solid = _union(body, boss)
    ear_y = length / 2 + 3.0
    for ey in (-ear_y, ear_y):
        ear = _box(width, 6.0, 2.0)
        ear = _translate(ear, 0, ey, height / 2 - 1.0)
        solid = _union(solid, ear)
    for ey in (-ear_y, ear_y):
        for ex in (-width / 2 + 2.0, width / 2 - 2.0):
            cutter = _cyl(1.1, 6.0)
            cutter = _translate(cutter, ex, ey, 0)
            solid = _cut(solid, cutter)
    return solid


def build_wheel(params: dict[str, ParamValue]):
    """Wheel: tyre, hub, and axle bore on the Z axis."""
    diameter = _f(params, "diameter")
    width = _f(params, "width")
    bore = _f(params, "bore_diameter")
    if bore >= diameter:
        raise ValueError("wheel bore_diameter must be smaller than diameter")
    tyre = _cyl(diameter / 2, width)
    bore_cut = _cyl(bore / 2, width + 4)
    return _cut(tyre, bore_cut)


def build_caster_wheel(params: dict[str, ParamValue]):
    """Caster: wheel plus a fork and a vertical swivel axis."""
    diameter = _f(params, "diameter")
    width = _f(params, "width")
    bore = _f(params, "bore_diameter")
    total_height = _f(params, "total_height")
    wheel = build_wheel(
        {
            "diameter": diameter,
            "width": width,
            "bore_diameter": bore,
        }
    )
    # Wheel axis along Z; drop the fork around it.
    wheel = _rotate_y(wheel, 90.0)
    wheel = _translate(wheel, 0, 0, wheel_radius_offset(diameter, total_height))
    for side in (-1.0, 1.0):
        fork = _box(1.5, width + 2.0, total_height - wheel_radius_offset(diameter, total_height) + 2.0)
        fork = _translate(fork, side * (diameter / 2 + 0.75), 0, 0)
        wheel = _union(wheel, fork)
    top = _box(diameter + 6.0, width + 4.0, 2.0)
    top = _translate(top, 0, 0, total_height / 2)
    return _union(wheel, top)


def wheel_radius_offset(diameter: float, total_height: float) -> float:
    """Z centre of the caster wheel so its bottom sits on the ground plane."""
    return diameter / 2.0 - (total_height / 2.0 - diameter / 2.0)


def _rotate_y(solid, degrees: float):
    cq = _require_cq()
    return solid.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 1, 0), degrees)


def build_motor_bracket(params: dict[str, ParamValue]):
    """Motor bracket: L plate with a shaft clearance hole and bolt slots."""
    width = _f(params, "width")
    depth = _f(params, "depth")
    thickness = _f(params, "thickness")
    shaft_diameter = _f(params, "shaft_diameter")
    if thickness >= min(width, depth):
        raise ValueError("motor bracket thickness must be smaller than width and depth")
    plate = _box(width, depth, thickness)
    hole = _cyl(shaft_diameter / 2 + 0.5, thickness + 4)
    hole = _translate(hole, 0, depth / 2 - depth / 4, 0)
    return _cut(plate, hole)


def build_chassis_plate(params: dict[str, ParamValue]):
    """Chassis plate with rounded-out corners via a bolt-hole pattern."""
    width = _f(params, "width")
    depth = _f(params, "depth")
    thickness = _f(params, "thickness")
    plate = _box(width, depth, thickness)
    for hx, hy in _chassis_holes(width, depth):
        cutter = _cyl(1.6, thickness + 4)
        cutter = _translate(cutter, hx, hy, 0)
        plate = _cut(plate, cutter)
    return plate


def _chassis_holes(width: float, depth: float) -> tuple[tuple[float, float], ...]:
    inset_x = width / 2 - 6.0
    inset_y = depth / 2 - 6.0
    return (
        (-inset_x, -inset_y),
        (inset_x, -inset_y),
        (-inset_x, inset_y),
        (inset_x, inset_y),
    )


def build_usb_connector(params: dict[str, ParamValue]):
    return _box(_f(params, "length"), _f(params, "width"), _f(params, "height"))


# --- Printed-part helpers --------------------------------------------------


def build_knob(params: dict[str, ParamValue]):
    """Control knob: revolved body, knurl flutes, shaft bore and pointer mark."""
    diameter = _f(params, "diameter")
    height = _f(params, "height")
    shaft = _f(params, "shaft_diameter")
    flutes = _i(params, "flutes")
    shaft_kind = _s(params, "shaft_kind")
    if shaft >= diameter * 0.7:
        raise ValueError("knob shaft_diameter is too large for the body")
    inner = shaft / 2
    rim = diameter / 2
    bevel = min(1.2, height * 0.16)
    body = _revolve_profile(
        [
            (inner, -height / 2),
            (rim - bevel, -height / 2),
            (rim, -height / 2 + bevel),
            (rim, height / 2 - bevel),
            (rim - bevel, height / 2),
            (inner, height / 2),
        ]
    )
    if flutes > 0:
        flute_r = diameter * 0.045
        for i in range(flutes):
            cutter = _cyl(flute_r, height * 0.72)
            cutter = _translate(cutter, rim - flute_r * 0.2, 0, 0)
            body = _cut(body, _rotate_z(cutter, 360.0 * i / flutes))
    if shaft_kind == "d":
        # D-shaft: shave one side of the bore with a straight chord.
        flat_depth = shaft * 0.18
        flat = _box(shaft * 1.5, shaft, height + 4)
        body = _cut(body, _translate(flat, 0, inner - flat_depth + shaft / 2, 0))
    pointer = _box(diameter * 0.09, diameter * 0.28, 0.6)
    body = _cut(body, _translate(pointer, 0, rim * 0.72, height / 2 - 0.2))
    return body


def build_cable_clip(params: dict[str, ParamValue]):
    """Cable clip: C-shaped cradle with a screw tab (printed snap-in)."""
    cable = _f(params, "cable_diameter")
    width = _f(params, "width")
    wall = _f(params, "wall")
    hole = _f(params, "hole_diameter")
    mouth = _f(params, "mouth_width")
    if wall >= cable * 0.5:
        raise ValueError("cable_clip wall is too thick for the cable")
    body = _ring(cable / 2 + wall, cable / 2, width)
    body = _cut(
        body, _translate(_box(mouth, cable, width + 2), 0, cable / 2 + wall, 0)
    )
    tab_len = cable * 0.9
    tab = _profile_solid(
        _rounded_rect(tab_len * 2, width, width * 0.45), 1.8
    )
    tab = _translate(tab, 0, -(cable / 2 + wall), 0)
    body = _union(body, tab)
    body = _cut(body, _translate(_cyl(hole / 2, 6.0), 0, -(cable / 2 + wall), 0))
    return body


def build_zip_tie_mount(params: dict[str, ParamValue]):
    """Adhesive/screw tie mount: base pad with a bridge loop for the tie."""
    length = _f(params, "length")
    width = _f(params, "width")
    hole = _f(params, "hole_diameter")
    slot = _f(params, "slot_width")
    if slot >= width * 0.7:
        raise ValueError("zip_tie_mount slot_width is too wide for the base")
    base = _profile_solid(_rounded_rect(length, width, width * 0.25), 1.6)
    bridge_h = 4.0
    bridge = _box(length * 0.55, width * 0.55, bridge_h)
    bridge = _translate(bridge, 0, 0, 0.8 + bridge_h / 2)
    body = _union(base, bridge)
    body = _cut(
        body,
        _translate(_box(slot, width * 0.55 + 2, bridge_h * 0.55), 0, 0, 0.8 + bridge_h * 0.45),
    )
    for sx in (-1.0, 1.0):
        body = _cut(body, _translate(_cyl(hole / 2, 6.0), sx * length * 0.32, 0, 0))
    return body


def build_gusset(params: dict[str, ParamValue]):
    """Corner gusset: triangular rib with a hole in each leg."""
    leg_a = _f(params, "leg_a")
    leg_b = _f(params, "leg_b")
    thickness = _f(params, "thickness")
    hole = _f(params, "hole_diameter")
    if hole * 3.0 >= min(leg_a, leg_b):
        raise ValueError("gusset hole_diameter is too large for the legs")
    profile = [(-leg_a / 2, -leg_b / 2), (leg_a / 2, -leg_b / 2), (-leg_a / 2, leg_b / 2)]
    body = _profile_solid(profile, thickness)
    for x in (-leg_a * 0.22, leg_a * 0.22):
        body = _cut(
            body,
            _translate(_cyl(hole / 2, thickness + 4), x, -leg_b * 0.28, 0),
        )
    for y in (-leg_b * 0.22, leg_b * 0.22):
        body = _cut(
            body,
            _translate(_cyl(hole / 2, thickness + 4), -leg_a * 0.28, y, 0),
        )
    return body


def build_vent_panel(params: dict[str, ParamValue]):
    """Vented panel: rounded plate with capsule slots and corner holes."""
    width = _f(params, "width")
    height = _f(params, "height")
    thickness = _f(params, "thickness")
    slots = _i(params, "slots")
    slot_width = _f(params, "slot_width")
    hole = _f(params, "hole_diameter")
    if slot_width >= height * 0.5:
        raise ValueError("vent slot_width is too wide for the panel")
    body = _profile_solid(_rounded_rect(width, height, 3.0), thickness)
    slot_len = width * 0.62
    cutter_profile = _rounded_rect(slot_len, slot_width, slot_width / 2)
    step = height / (slots + 1)
    for i in range(slots):
        y = -height / 2 + step * (i + 1)
        cutter = _profile_solid(cutter_profile, thickness + 2)
        body = _cut(body, _translate(cutter, 0, y, 0))
    if hole > 0:
        inset_x = width / 2 - hole * 1.6
        inset_y = height / 2 - hole * 1.6
        for sx in (-1.0, 1.0):
            for sy in (-1.0, 1.0):
                body = _cut(
                    body,
                    _translate(_cyl(hole / 2, thickness + 4), sx * inset_x, sy * inset_y, 0),
                )
    return body


def build_snap_fit_clip(params: dict[str, ParamValue]):
    """Cantilever snap clip: base, flexible arm and a chamfered hook."""
    arm_length = _f(params, "arm_length")
    width = _f(params, "width")
    thickness = _f(params, "thickness")
    hook = _f(params, "hook_height")
    if hook >= arm_length * 0.6:
        raise ValueError("snap_fit hook_height is too tall for the arm")
    base = _box(width, thickness * 3.0, 2.0)
    base = _translate(base, 0, -thickness, -arm_length / 2 + 1.0)
    arm = _box(width, thickness, arm_length)
    arm = _translate(arm, 0, 0, 0)
    body = _union(base, arm)
    lip = _box(width, thickness * 2.2, hook)
    lip = _translate(lip, 0, thickness * 0.6, arm_length / 2 - hook / 2)
    body = _union(body, lip)
    nose = _box(width + 2, thickness * 2.2, hook)
    nose = _rotate_x(nose, 30.0)
    body = _cut(body, _translate(nose, 0, thickness * 2.6, arm_length / 2 + hook * 0.2))
    return body


def build_pcb_mount_post(params: dict[str, ParamValue]):
    """Snap-in PCB post: flange, split post, barb and chamfered nose."""
    height = _f(params, "height")
    diameter = _f(params, "diameter")
    hole = _f(params, "hole_diameter")
    if hole >= diameter * 0.6:
        raise ValueError("pcb_mount_post hole_diameter is too large for the post")
    flange = _cyl(diameter * 0.75, 1.2)
    post = _cyl(diameter / 2 * 0.55, height)
    post = _translate(post, 0, 0, 0.6 + height / 2)
    body = _union(flange, post)
    barb = _cone(diameter * 0.55, diameter * 0.62, 0.9)
    body = _union(body, _translate(barb, 0, 0, 0.6 + height - 0.45))
    nose = _cone(diameter * 0.3, diameter * 0.34, 0.7)
    body = _union(body, _translate(nose, 0, 0, 0.6 + height + 0.35))
    for sign in (-1.0, 1.0):
        slit = _box(0.5, diameter, height * 0.8)
        body = _cut(body, _translate(slit, sign * diameter * 0.16, 0, 0.6 + height * 0.45))
    if hole > 0:
        body = _cut(body, _cyl(hole / 2, height + 6))
    return body


# --- Enclosure template ----------------------------------------------------


def _enclosure_inner(params: dict[str, ParamValue]) -> tuple[float, float, float, float]:
    width = _f(params, "width")
    depth = _f(params, "depth")
    height = _f(params, "height")
    wall = _f(params, "wall_thickness")
    if wall * 2 >= min(width, depth, height):
        raise ValueError(
            "enclosure wall thickness leaves no inner cavity — "
            "reduce the wall or enlarge the box"
        )
    return width, depth, height, wall


def _board_for_enclosure(params: dict[str, ParamValue]) -> BoardProfile | None:
    board = _s(params, "board")
    if board == "none":
        return None
    profile = BOARDS.get(board)
    if profile is None:
        raise ValueError(f"unknown enclosure board '{board}'")
    return profile


def _assert_board_fits(
    profile: BoardProfile, width: float, depth: float, wall: float
) -> None:
    inner_w = width - 2 * wall
    inner_d = depth - 2 * wall
    clearance = 2.0
    if profile.width + clearance > inner_w or profile.depth + clearance > inner_d:
        raise ValueError(
            f"{profile.key} ({profile.width:.1f}×{profile.depth:.1f} mm) does not "
            f"fit in the enclosure inner cavity ({inner_w:.1f}×{inner_d:.1f} mm). "
            "Enlarge the enclosure or reduce the wall thickness."
        )


def build_enclosure(params: dict[str, ParamValue]):
    width, depth, height, wall = _enclosure_inner(params)
    profile = _board_for_enclosure(params)
    if profile is not None:
        _assert_board_fits(profile, width, depth, wall)

    solid = _build_from_operation(
        PartOperation(
            build=BoxOperation(width=width, depth=depth, height=height),
            features=[ShellFeature(thickness=wall)],
        )
    )
    if profile is not None:
        for hx, hy in profile.holes_xy:
            cutter = _cyl(profile.hole_diameter / 2, height + 4)
            cutter = _translate(cutter, hx, hy, 0)
            solid = _cut(solid, cutter)
    if _b(params, "usb_cutout") and profile is not None:
        cutter = _box(wall * 4, profile.usb_width, profile.usb_height)
        z = -height / 2 + wall + profile.usb_z
        x = -width / 2
        cutter = _translate(cutter, x, 0, z)
        solid = _cut(solid, cutter)
    elif _b(params, "usb_cutout"):
        cutter = _box(wall * 4, 12.0, 8.0)
        cutter = _translate(cutter, -width / 2, 0, -height / 2 + wall + 8.0)
        solid = _cut(solid, cutter)
    return solid


def build_enclosure_lid(params: dict[str, ParamValue]):
    width = _f(params, "width")
    depth = _f(params, "depth")
    thickness = _f(params, "thickness")
    return _box(width, depth, thickness)


def build_generated_part(params: dict[str, ParamValue]):
    raise ValueError("generated_part is built from its nested CAD specification")


# --- Parameter tables ------------------------------------------------------

_BOX_PARAMS = (
    ParamSpec("width", "Width", "length", 100.0, 0.1, 10000.0),
    ParamSpec("depth", "Depth", "length", 60.0, 0.1, 10000.0),
    ParamSpec("height", "Height", "length", 30.0, 0.1, 10000.0),
)
_CYL_PARAMS = (
    ParamSpec("radius", "Radius", "length", 15.0, 0.1, 10000.0),
    ParamSpec("height", "Height", "length", 30.0, 0.1, 10000.0),
)
_HEAD_SPEC = ParamSpec(
    "head",
    "Head",
    "choice",
    "socket",
    options=("socket", "countersunk", "button", "hex"),
    unit=None,
    description="socket cap, 90° countersunk, button dome or hex bolt head",
)
_SCREW_LEN = (ParamSpec("length", "Length", "length", 12.0, 4.0, 80.0), _HEAD_SPEC)


def _defs() -> tuple[ComponentDef, ...]:
    return (
        ComponentDef(
            "box", "geometry", "Box",
            "Rectangular block, origin at the centre.",
            _BOX_PARAMS, builder=build_box,
        ),
        ComponentDef(
            "cylinder", "geometry", "Cylinder",
            "Z-axis cylinder, origin at the centre.",
            _CYL_PARAMS, builder=build_cylinder,
        ),
        ComponentDef(
            "sphere", "geometry", "Sphere",
            "Sphere centred on the origin.",
            (ParamSpec("radius", "Radius", "length", 25.0, 0.1, 10000.0),),
            builder=build_sphere,
        ),
        ComponentDef(
            "cone", "geometry", "Cone",
            "Z-axis frustum, origin at the centre.",
            (
                ParamSpec("bottom_radius", "Bottom radius", "length", 20.0, 0.1, 10000.0),
                ParamSpec("top_radius", "Top radius", "length", 10.0, 0.1, 10000.0),
                ParamSpec("height", "Height", "length", 40.0, 0.1, 10000.0),
            ),
            builder=build_cone,
        ),
        ComponentDef(
            "torus", "geometry", "Torus",
            "Ring torus, axis +Z.",
            (
                ParamSpec("major_radius", "Major radius", "length", 30.0, 0.2, 10000.0),
                ParamSpec("minor_radius", "Minor radius", "length", 8.0, 0.1, 5000.0),
            ),
            builder=build_torus,
        ),
        ComponentDef(
            "polygon_prism", "geometry", "Polygon prism",
            "Regular n-gon prism, axis +Z.",
            (
                ParamSpec("sides", "Sides", "count", 6, 3, 12, unit=None),
                ParamSpec("circumradius", "Circumradius", "length", 10.0, 0.1, 10000.0),
                ParamSpec("height", "Height", "length", 8.0, 0.1, 10000.0),
            ),
            builder=build_prism,
        ),
        ComponentDef(
            "m2_screw", "fasteners", "M2 Screw",
            "M2 cap screw. Length is the unthreaded-equivalent shank; no real thread.",
            _SCREW_LEN, builder=_metric_screw(2.0, 4.0, 2.0),
        ),
        ComponentDef(
            "m3_screw", "fasteners", "M3 Screw",
            "M3 cap screw. Length is the shank; no real thread.",
            _SCREW_LEN, builder=_metric_screw(3.0, 5.5, 3.0),
        ),
        ComponentDef(
            "m4_screw", "fasteners", "M4 Screw",
            "M4 cap screw. Length is the shank; no real thread.",
            (
                ParamSpec("length", "Length", "length", 16.0, 6.0, 100.0),
                _HEAD_SPEC,
            ),
            builder=_metric_screw(4.0, 7.0, 4.0),
        ),
        ComponentDef(
            "m5_screw", "fasteners", "M5 Screw",
            "M5 socket-head cap screw. Length is the shank; no real thread.",
            (
                ParamSpec("length", "Length", "length", 20.0, 8.0, 120.0),
                _HEAD_SPEC,
            ),
            builder=_metric_screw(5.0, 8.5, 5.0),
        ),
        ComponentDef(
            "m6_screw", "fasteners", "M6 Screw",
            "M6 cap screw for frame joints and 608-bearing axles. No real thread.",
            (
                ParamSpec("length", "Length", "length", 20.0, 10.0, 150.0),
                _HEAD_SPEC,
            ),
            builder=_metric_screw(6.0, 10.0, 6.0),
        ),
        ComponentDef(
            "m6_nut", "fasteners", "M6 Nut",
            "M6 hex nut with chamfered faces. Across-flats 10 mm.",
            (), parameterized=False, builder=_metric_nut(6.0, 10.0, 5.0),
        ),
        ComponentDef(
            "m3_nut", "fasteners", "M3 Nut",
            "M3 hex nut with chamfered faces. Across-flats 5.5 mm.",
            (), parameterized=False, builder=_metric_nut(3.0, 5.5, 2.4),
        ),
        ComponentDef(
            "m4_nut", "fasteners", "M4 Nut",
            "M4 hex nut with chamfered faces. Across-flats 7 mm.",
            (), parameterized=False, builder=_metric_nut(4.0, 7.0, 3.2),
        ),
        ComponentDef(
            "m5_nut", "fasteners", "M5 Nut",
            "M5 hex nut with chamfered faces. Across-flats 8 mm.",
            (), parameterized=False, builder=_metric_nut(5.0, 8.0, 4.0),
        ),
        ComponentDef(
            "washer", "fasteners", "Washer",
            "Plain or split-lock washer. Defaults match M3.",
            (
                ParamSpec("inner_diameter", "Inner Ø", "length", 3.2, 0.5, 50.0),
                ParamSpec("outer_diameter", "Outer Ø", "length", 7.0, 1.0, 80.0),
                ParamSpec("thickness", "Thickness", "length", 0.5, 0.1, 10.0),
                ParamSpec(
                    "kind", "Kind", "choice", "flat",
                    options=("flat", "split"), unit=None,
                    description="flat washer or spring washer with a radial slit",
                ),
            ),
            builder=build_washer,
        ),
        ComponentDef(
            "set_screw", "fasteners", "Set screw",
            "Headless grub screw with hex drive at both ends and a cup point.",
            (
                ParamSpec("diameter", "Diameter", "length", 3.0, 1.6, 8.0),
                ParamSpec("length", "Length", "length", 6.0, 2.0, 30.0),
            ),
            builder=build_set_screw,
        ),
        ComponentDef(
            "threaded_rod", "fasteners", "Threaded rod",
            "All-thread rod envelope for links and lead screws. Threads are not modelled.",
            (
                ParamSpec("diameter", "Diameter", "length", 3.0, 1.6, 16.0),
                ParamSpec("length", "Length", "length", 100.0, 10.0, 1000.0),
            ),
            builder=build_threaded_rod,
        ),
        ComponentDef(
            "t_nut", "fasteners", "T-nut",
            "Hammer nut for 2020 T-slot: rounded block, raised boss, through hole.",
            (
                ParamSpec("width", "Width", "length", 10.5, 4.0, 24.0),
                ParamSpec("length", "Length", "length", 10.0, 4.0, 40.0),
                ParamSpec("thickness", "Thickness", "length", 3.0, 1.0, 10.0),
                ParamSpec("boss_diameter", "Boss Ø", "length", 6.0, 2.0, 16.0),
                ParamSpec("boss_height", "Boss height", "length", 1.5, 0.0, 6.0),
                ParamSpec("hole_diameter", "Hole Ø", "length", 3.4, 1.0, 12.0),
            ),
            builder=build_t_nut,
        ),
        ComponentDef(
            "nyloc_nut", "fasteners", "Nyloc nut",
            "Chamfered hex nut with the nylon collar that resists vibration.",
            (
                ParamSpec("hole_diameter", "Hole Ø", "length", 3.0, 1.0, 12.0),
                ParamSpec("across_flats", "Across flats", "length", 5.5, 2.0, 30.0),
                ParamSpec("height", "Height", "length", 4.0, 1.5, 20.0),
                ParamSpec("collar_height", "Collar", "length", 1.0, 0.2, 4.0),
            ),
            builder=build_nyloc_nut,
        ),
        ComponentDef(
            "standoff", "fasteners", "Standoff",
            "Cylindrical standoff with a through hole. Defaults match M3.",
            (
                ParamSpec("length", "Length", "length", 10.0, 2.0, 80.0),
                ParamSpec("outer_diameter", "Outer Ø", "length", 6.0, 2.0, 40.0),
                ParamSpec("hole_diameter", "Hole Ø", "length", 3.2, 0.5, 20.0),
            ),
            builder=build_standoff,
        ),
        ComponentDef(
            "hex_standoff", "fasteners", "Hex standoff",
            "Hex standoff with a through hole. Defaults match M3.",
            (
                ParamSpec("length", "Length", "length", 10.0, 2.0, 80.0),
                ParamSpec("across_flats", "Across flats", "length", 5.5, 2.0, 40.0),
                ParamSpec("hole_diameter", "Hole Ø", "length", 3.2, 0.5, 20.0),
            ),
            builder=build_hex_standoff,
        ),
        ComponentDef(
            "heat_insert", "fasteners", "Heat-set insert",
            "Heat-set threaded insert for printed plastic: tapered body and flange. "
            "Threads are not modelled.",
            (
                ParamSpec("length", "Length", "length", 5.7, 2.0, 30.0),
                ParamSpec("outer_diameter", "Outer Ø", "length", 4.6, 2.0, 20.0),
                ParamSpec("hole_diameter", "Hole Ø", "length", 3.0, 1.0, 12.0),
            ),
            builder=build_heat_insert,
        ),
        ComponentDef(
            "bracket", "mechanical", "L-bracket",
            "L-bracket from two plates with two mounting holes per leg. "
            "Origin at the inner corner on the base.",
            (
                ParamSpec("width", "Width", "length", 40.0, 5.0, 400.0),
                ParamSpec("depth", "Depth", "length", 30.0, 5.0, 400.0),
                ParamSpec("height", "Height", "length", 30.0, 5.0, 400.0),
                ParamSpec("thickness", "Thickness", "length", 3.0, 0.5, 20.0),
                ParamSpec("hole_diameter", "Hole Ø", "length", 3.4, 1.0, 12.0),
            ),
            builder=build_bracket,
        ),
        ComponentDef(
            "spacer", "mechanical", "Spacer",
            "Cylindrical spacer with a centred through hole.",
            (
                ParamSpec("length", "Length", "length", 10.0, 1.0, 200.0),
                ParamSpec("outer_diameter", "Outer Ø", "length", 8.0, 2.0, 80.0),
                ParamSpec("hole_diameter", "Hole Ø", "length", 3.2, 0.5, 40.0),
            ),
            builder=build_spacer,
        ),
        ComponentDef(
            "shaft", "mechanical", "Shaft",
            "Plain cylindrical shaft with chamfered ends, axis +Z.",
            (
                ParamSpec("diameter", "Diameter", "length", 8.0, 0.5, 200.0),
                ParamSpec("length", "Length", "length", 60.0, 1.0, 1000.0),
                ParamSpec("chamfer", "End chamfer", "length", 0.5, 0.0, 10.0),
            ),
            builder=build_shaft,
        ),
        ComponentDef(
            "bearing", "mechanical", "Bearing",
            "Simplified ring bearing (no races or balls).",
            (
                ParamSpec("outer_diameter", "Outer Ø", "length", 22.0, 4.0, 200.0),
                ParamSpec("inner_diameter", "Inner Ø", "length", 8.0, 1.0, 180.0),
                ParamSpec("width", "Width", "length", 7.0, 1.0, 80.0),
            ),
            builder=build_bearing,
        ),
        ComponentDef(
            "hinge", "mechanical", "Hinge",
            "Butt hinge: knuckled barrel with pin, two leaves and screw holes. "
            "Knuckles are grooves, not separate parts.",
            (
                ParamSpec("length", "Length", "length", 40.0, 10.0, 200.0),
                ParamSpec("knuckle_diameter", "Knuckle Ø", "length", 6.0, 2.0, 30.0),
                ParamSpec("leaf_width", "Leaf width", "length", 16.0, 4.0, 80.0),
                ParamSpec("thickness", "Thickness", "length", 2.0, 0.5, 8.0),
                ParamSpec("hole_diameter", "Hole Ø", "length", 3.4, 1.0, 10.0),
            ),
            builder=build_hinge,
        ),
        ComponentDef(
            "spur_gear", "mechanical", "Spur gear",
            "Spur gear with involute flanks, 20° pressure angle and a chamfered bore.",
            (
                ParamSpec("module", "Module", "length", 1.0, 0.3, 6.0),
                ParamSpec("teeth", "Teeth", "count", 20, 6, 80, unit=None),
                ParamSpec("thickness", "Thickness", "length", 5.0, 1.0, 40.0),
                ParamSpec("bore_diameter", "Bore Ø", "length", 5.0, 1.0, 60.0),
            ),
            builder=build_spur_gear,
        ),
        ComponentDef(
            "gt2_pulley", "mechanical", "GT2 pulley",
            "GT2 timing pulley (2 mm pitch): trapezoid grooves, flanges, hub, set screw.",
            (
                ParamSpec("teeth", "Teeth", "count", 20, 8, 60, unit=None),
                ParamSpec("belt_width", "Belt width", "length", 6.0, 3.0, 20.0),
                ParamSpec("bore_diameter", "Bore Ø", "length", 5.0, 1.0, 20.0),
                ParamSpec("set_screw", "Set screw", "flag", True, unit=None),
            ),
            builder=build_gt2_pulley,
        ),
        ComponentDef(
            "v_slot_extrusion", "mechanical", "T-slot extrusion",
            "Aluminium T-slot extrusion (2020 section) with four slots and a centre bore.",
            (
                ParamSpec("size", "Profile size", "length", 20.0, 10.0, 60.0),
                ParamSpec("length", "Length", "length", 200.0, 10.0, 1200.0),
                ParamSpec("bore_diameter", "Centre bore Ø", "length", 4.2, 0.0, 20.0),
            ),
            builder=build_v_slot_extrusion,
        ),
        ComponentDef(
            "shaft_coupling", "mechanical", "Shaft coupling",
            "Rigid coupling: two bores, clamp slit and cross clamp screws.",
            (
                ParamSpec("length", "Length", "length", 25.0, 8.0, 80.0),
                ParamSpec("outer_diameter", "Outer Ø", "length", 16.0, 6.0, 60.0),
                ParamSpec("bore_a", "Bore A", "length", 5.0, 1.0, 40.0),
                ParamSpec("bore_b", "Bore B", "length", 5.0, 1.0, 40.0),
            ),
            builder=build_shaft_coupling,
        ),
        ComponentDef(
            "shaft_collar", "mechanical", "Shaft collar",
            "Clamp collar with chamfered rims and a radial set-screw hole.",
            (
                ParamSpec("shaft_diameter", "Shaft Ø", "length", 5.0, 1.0, 40.0),
                ParamSpec("outer_diameter", "Outer Ø", "length", 10.0, 3.0, 60.0),
                ParamSpec("width", "Width", "length", 8.0, 2.0, 40.0),
                ParamSpec("set_screw", "Set screw", "flag", True, unit=None),
            ),
            builder=build_shaft_collar,
        ),
        ComponentDef(
            "flange", "mechanical", "Flange",
            "Bolt-on flange: bevelled disc, optional hub and a bolt circle.",
            (
                ParamSpec("outer_diameter", "Outer Ø", "length", 40.0, 10.0, 300.0),
                ParamSpec("bore_diameter", "Bore Ø", "length", 16.0, 2.0, 250.0),
                ParamSpec("thickness", "Thickness", "length", 6.0, 1.5, 40.0),
                ParamSpec("bolt_count", "Bolts", "count", 4, 0, 12, unit=None),
                ParamSpec("bolt_circle", "Bolt circle Ø", "length", 30.0, 5.0, 280.0),
                ParamSpec("bolt_diameter", "Bolt Ø", "length", 4.2, 1.0, 20.0),
                ParamSpec("hub_height", "Hub height", "length", 4.0, 0.0, 40.0),
            ),
            builder=build_flange,
        ),
        ComponentDef(
            "compression_spring", "mechanical", "Compression spring",
            "Round-wire compression spring swept along a true helix.",
            (
                ParamSpec("wire_diameter", "Wire Ø", "length", 1.0, 0.2, 6.0),
                ParamSpec("coil_diameter", "Coil Ø", "length", 10.0, 2.0, 80.0),
                ParamSpec("coils", "Coils", "count", 8, 2, 50, unit=None),
                ParamSpec("free_length", "Free length", "length", 30.0, 3.0, 300.0),
            ),
            builder=build_compression_spring,
        ),
        ComponentDef(
            "dowel_pin", "mechanical", "Dowel pin",
            "Parallel dowel pin with the small end chamfers dowels carry.",
            (
                ParamSpec("diameter", "Diameter", "length", 3.0, 1.0, 20.0),
                ParamSpec("length", "Length", "length", 10.0, 2.0, 100.0),
            ),
            builder=build_dowel_pin,
        ),
        ComponentDef(
            "arduino_uno", "electronics", "Arduino Uno",
            "Arduino Uno Rev3 PCB envelope with four mounting holes. USB toward -X.",
            (), parameterized=False, builder=_build_board(_ARDUINO),
        ),
        ComponentDef(
            "raspberry_pi", "electronics", "Raspberry Pi",
            "Raspberry Pi 4 / 5 PCB envelope with four mounting holes.",
            (), parameterized=False, builder=_build_board(_RASPI),
        ),
        ComponentDef(
            "esp32", "electronics", "ESP32",
            "ESP32 DevKit envelope with four corner holes. USB toward -X.",
            (), parameterized=False, builder=_build_board(_ESP32),
        ),
        ComponentDef(
            "raspberry_pi_pico", "electronics", "Raspberry Pi Pico",
            "Pico PCB envelope with four mounting holes. USB toward -X.",
            (), parameterized=False, builder=_build_board(_PICO),
        ),
        ComponentDef(
            "arduino_nano", "electronics", "Arduino Nano",
            "Nano PCB envelope with four mounting holes. USB toward -X.",
            (), parameterized=False, builder=_build_board(_NANO),
        ),
        ComponentDef(
            "breadboard", "electronics", "Breadboard",
            "Half-size breadboard envelope (no clips).",
            (
                ParamSpec("width", "Width", "length", 82.5, 20.0, 200.0),
                ParamSpec("depth", "Depth", "length", 54.5, 20.0, 120.0),
                ParamSpec("height", "Height", "length", 9.5, 2.0, 20.0),
            ),
            builder=build_breadboard,
        ),
        ComponentDef(
            "usb_connector", "electronics", "USB connector",
            "USB-B style connector envelope for cutout planning.",
            (
                ParamSpec("length", "Length", "length", 16.0, 5.0, 40.0),
                ParamSpec("width", "Width", "length", 12.0, 5.0, 30.0),
                ParamSpec("height", "Height", "length", 11.0, 3.0, 20.0),
            ),
            builder=build_usb_connector,
        ),
        ComponentDef(
            "oled_096", "electronics", "OLED 0.96\"",
            "0.96\" I2C OLED module: PCB envelope with a 4-pin header footprint. "
            "Representative envelope, not a manufacturer drawing.",
            (
                ParamSpec("width", "Width", "length", 27.0, 10.0, 80.0),
                ParamSpec("depth", "Depth", "length", 27.0, 10.0, 80.0),
            ),
            builder=build_oled_module,
        ),
        ComponentDef(
            "lcd_16x2", "electronics", "LCD 16x2",
            "16x2 character LCD: board, display bezel, four corner mounting holes.",
            (
                ParamSpec("width", "Width", "length", 80.0, 30.0, 160.0),
                ParamSpec("depth", "Depth", "length", 36.0, 15.0, 100.0),
            ),
            builder=build_lcd_module,
        ),
        ComponentDef(
            "push_button", "electronics", "Push button",
            "12 mm tactile switch: body, plunger, and two leads.",
            (), parameterized=False, builder=build_push_button,
        ),
        ComponentDef(
            "potentiometer", "electronics", "Potentiometer",
            "Trimmer potentiometer: body, adjustment screw, three pins.",
            (), parameterized=False, builder=build_potentiometer,
        ),
        ComponentDef(
            "terminal_block", "electronics", "Terminal block",
            "Pitched terminal block with one bore per way.",
            (
                ParamSpec("ways", "Ways", "count", 2, 1, 12, unit=None),
                ParamSpec("pitch", "Pitch", "length", 5.0, 2.54, 20.0),
                ParamSpec("height", "Height", "length", 10.0, 4.0, 40.0),
            ),
            builder=build_terminal_block,
        ),
        ComponentDef(
            "fan", "electronics", "Fan",
            "Axial fan: rounded frame, corner mounting holes, struts and tilted blades.",
            (
                ParamSpec("size", "Frame size", "length", 40.0, 15.0, 120.0),
                ParamSpec("thickness", "Thickness", "length", 10.0, 3.0, 38.0),
                ParamSpec("hole_diameter", "Hole Ø", "length", 4.3, 1.0, 10.0),
                ParamSpec("blades", "Blades", "count", 7, 0, 15, unit=None),
                ParamSpec("hub_diameter", "Hub Ø", "length", 14.0, 4.0, 60.0),
            ),
            builder=build_fan,
        ),
        ComponentDef(
            "battery_holder", "electronics", "Battery holder",
            "Printed cell cradle: open trough, end caps, terminal holes and strap grooves.",
            (
                ParamSpec("cell_diameter", "Cell Ø", "length", 18.4, 8.0, 40.0),
                ParamSpec("cell_length", "Cell length", "length", 65.0, 10.0, 120.0),
                ParamSpec("wall", "Wall", "length", 1.8, 0.6, 6.0),
                ParamSpec("cells", "Cells", "count", 1, 1, 6, unit=None),
            ),
            builder=build_battery_holder,
        ),
        ComponentDef(
            "pin_header", "electronics", "Pin header",
            "2.54 mm pin header in male or female form.",
            (
                ParamSpec("pins", "Pins", "count", 8, 1, 40, unit=None),
                ParamSpec("rows", "Rows", "count", 1, 1, 2, unit=None),
                ParamSpec("pitch", "Pitch", "length", 2.54, 1.27, 5.08),
                ParamSpec("pin_height", "Pin height", "length", 6.0, 2.0, 20.0),
                ParamSpec(
                    "gender", "Gender", "choice", "male",
                    options=("male", "female"), unit=None,
                    description="male posts or female sockets",
                ),
            ),
            builder=build_pin_header,
        ),
        ComponentDef(
            "dc_barrel_jack", "electronics", "DC barrel jack",
            "Panel barrel jack: barrel, flange, centre pin and solder tabs.",
            (
                ParamSpec("outer_diameter", "Barrel Ø", "length", 8.0, 3.0, 20.0),
                ParamSpec("length", "Length", "length", 14.0, 4.0, 40.0),
                ParamSpec("flange_width", "Flange width", "length", 11.0, 4.0, 30.0),
                ParamSpec("flange_height", "Flange height", "length", 9.0, 4.0, 30.0),
                ParamSpec("pin_diameter", "Pin Ø", "length", 2.0, 0.5, 6.0),
            ),
            builder=build_barrel_jack,
        ),
        ComponentDef(
            "dc_gear_motor", "robotics", "DC gear motor",
            "Geared DC motor: can, gearbox face, output shaft.",
            (
                ParamSpec("diameter", "Body Ø", "length", 24.0, 6.0, 80.0),
                ParamSpec("length", "Body length", "length", 30.0, 8.0, 120.0),
                ParamSpec("shaft_diameter", "Shaft Ø", "length", 4.0, 1.0, 20.0),
                ParamSpec("shaft_length", "Shaft length", "length", 10.0, 2.0, 40.0),
            ),
            builder=build_dc_motor,
        ),
        ComponentDef(
            "servo_motor", "robotics", "Servo motor",
            "Hobby servo: body, output boss, two mounting ears with holes.",
            (
                ParamSpec("length", "Length", "length", 40.0, 15.0, 90.0),
                ParamSpec("width", "Width", "length", 20.0, 8.0, 50.0),
                ParamSpec("height", "Height", "length", 40.0, 10.0, 90.0),
            ),
            builder=build_servo_motor,
        ),
        ComponentDef(
            "robot_wheel", "robotics", "Robot wheel",
            "Wheel with a hub and axle bore on the Z axis.",
            (
                ParamSpec("diameter", "Diameter", "length", 65.0, 10.0, 250.0),
                ParamSpec("width", "Width", "length", 20.0, 3.0, 80.0),
                ParamSpec("bore_diameter", "Bore Ø", "length", 6.0, 1.0, 40.0),
            ),
            builder=build_wheel,
        ),
        ComponentDef(
            "caster_wheel", "robotics", "Caster wheel",
            "Swivel caster: wheel, fork, and top plate.",
            (
                ParamSpec("diameter", "Diameter", "length", 24.0, 8.0, 80.0),
                ParamSpec("width", "Width", "length", 12.0, 3.0, 40.0),
                ParamSpec("bore_diameter", "Bore Ø", "length", 4.0, 1.0, 20.0),
                ParamSpec("total_height", "Total height", "length", 38.0, 12.0, 120.0),
            ),
            builder=build_caster_wheel,
        ),
        ComponentDef(
            "motor_bracket", "robotics", "Motor bracket",
            "L-shaped motor plate with shaft clearance and bolt holes.",
            (
                ParamSpec("width", "Width", "length", 30.0, 5.0, 120.0),
                ParamSpec("depth", "Depth", "length", 30.0, 5.0, 120.0),
                ParamSpec("thickness", "Thickness", "length", 3.0, 0.5, 12.0),
                ParamSpec("shaft_diameter", "Shaft Ø", "length", 4.0, 1.0, 20.0),
            ),
            builder=build_motor_bracket,
        ),
        ComponentDef(
            "chassis_plate", "robotics", "Chassis plate",
            "Flat chassis plate with four corner mounting holes.",
            (
                ParamSpec("width", "Width", "length", 120.0, 20.0, 500.0),
                ParamSpec("depth", "Depth", "length", 90.0, 20.0, 500.0),
                ParamSpec("thickness", "Thickness", "length", 3.0, 0.5, 15.0),
            ),
            builder=build_chassis_plate,
        ),
        ComponentDef(
            "servo_horn", "robotics", "Servo horn",
            "Servo horn: splined boss and a rounded arm with link holes.",
            (
                ParamSpec("arm_length", "Arm length", "length", 20.0, 5.0, 80.0),
                ParamSpec("boss_diameter", "Boss Ø", "length", 7.0, 3.0, 20.0),
                ParamSpec("thickness", "Thickness", "length", 2.5, 0.8, 8.0),
                ParamSpec("hole_diameter", "Hole Ø", "length", 2.2, 0.8, 6.0),
                ParamSpec("holes", "Link holes", "count", 3, 1, 6, unit=None),
                ParamSpec("spline_teeth", "Spline teeth", "count", 21, 6, 40, unit=None),
            ),
            builder=build_servo_horn,
        ),
        ComponentDef(
            "linear_rail", "robotics", "Linear rail",
            "MGN-style linear rail with raceways and a carriage block.",
            (
                ParamSpec("length", "Length", "length", 200.0, 30.0, 1000.0),
                ParamSpec("rail_width", "Rail width", "length", 12.0, 5.0, 30.0),
                ParamSpec("blocks", "Carriages", "count", 1, 0, 4, unit=None),
                ParamSpec("block_length", "Block length", "length", 30.0, 8.0, 120.0),
            ),
            builder=build_linear_rail,
        ),
        ComponentDef(
            "wheel_hub", "robotics", "Wheel hub",
            "Motor-to-wheel hub: shaft bore, raised boss and bolt circle.",
            (
                ParamSpec("hub_diameter", "Hub Ø", "length", 24.0, 8.0, 120.0),
                ParamSpec("thickness", "Thickness", "length", 6.0, 2.0, 30.0),
                ParamSpec("shaft_diameter", "Shaft Ø", "length", 5.0, 1.0, 20.0),
                ParamSpec("bolt_count", "Bolts", "count", 6, 0, 12, unit=None),
                ParamSpec("bolt_circle", "Bolt circle Ø", "length", 16.0, 4.0, 100.0),
                ParamSpec("bolt_diameter", "Bolt Ø", "length", 3.4, 1.0, 12.0),
            ),
            builder=build_wheel_hub,
        ),
        ComponentDef(
            "ball_caster", "robotics", "Ball caster",
            "Ball caster: plate, housing, captive ball and reinforcing ribs.",
            (
                ParamSpec("ball_diameter", "Ball Ø", "length", 12.0, 4.0, 60.0),
                ParamSpec("plate_width", "Plate width", "length", 24.0, 8.0, 100.0),
                ParamSpec("total_height", "Total height", "length", 26.0, 8.0, 120.0),
                ParamSpec("hole_diameter", "Hole Ø", "length", 3.4, 1.0, 10.0),
            ),
            builder=build_ball_caster,
        ),
        ComponentDef(
            "idler_pulley", "robotics", "Idler pulley",
            "Smooth idler pulley: dished rim, two flanges and a bearing bore.",
            (
                ParamSpec("outer_diameter", "Outer Ø", "length", 14.0, 5.0, 80.0),
                ParamSpec("bore_diameter", "Bore Ø", "length", 5.0, 1.0, 30.0),
                ParamSpec("width", "Width", "length", 8.0, 2.0, 30.0),
                ParamSpec("groove_depth", "Groove depth", "length", 1.0, 0.0, 8.0),
            ),
            builder=build_idler_pulley,
        ),
        ComponentDef(
            "enclosure", "templates", "Enclosure",
            "Open-top rectangular enclosure. Optional board mounting holes and USB cutout.",
            (
                ParamSpec("width", "Width", "length", 90.0, 20.0, 400.0),
                ParamSpec("depth", "Depth", "length", 70.0, 20.0, 400.0),
                ParamSpec("height", "Height", "length", 40.0, 10.0, 200.0),
                ParamSpec("wall_thickness", "Wall", "length", 2.5, 0.8, 12.0),
                ParamSpec(
                    "board", "Board", "choice", "arduino_uno",
                    options=("none", "arduino_uno", "raspberry_pi", "esp32"),
                    unit=None,
                ),
                ParamSpec("usb_cutout", "USB cutout", "flag", True, unit=None),
            ),
            builder=build_enclosure,
        ),
        ComponentDef(
            "enclosure_lid", "templates", "Enclosure lid",
            "Flat lid matching an enclosure footprint.",
            (
                ParamSpec("width", "Width", "length", 90.0, 20.0, 400.0),
                ParamSpec("depth", "Depth", "length", 70.0, 20.0, 400.0),
                ParamSpec("thickness", "Thickness", "length", 2.5, 0.8, 12.0),
            ),
            builder=build_enclosure_lid,
        ),
        ComponentDef(
            "knob", "templates", "Knob",
            "Control knob: bevelled body, knurl flutes, D or round bore, pointer mark.",
            (
                ParamSpec("diameter", "Diameter", "length", 20.0, 6.0, 80.0),
                ParamSpec("height", "Height", "length", 12.0, 4.0, 50.0),
                ParamSpec("shaft_diameter", "Shaft Ø", "length", 6.0, 1.0, 20.0),
                ParamSpec("flutes", "Flutes", "count", 18, 0, 60, unit=None),
                ParamSpec(
                    "shaft_kind", "Shaft", "choice", "d",
                    options=("d", "round"), unit=None,
                    description="D-shaft flat or plain round bore",
                ),
            ),
            builder=build_knob,
        ),
        ComponentDef(
            "cable_clip", "templates", "Cable clip",
            "Snap-in C clip for routing cable, with a screw tab.",
            (
                ParamSpec("cable_diameter", "Cable Ø", "length", 6.0, 1.5, 30.0),
                ParamSpec("width", "Width", "length", 10.0, 3.0, 30.0),
                ParamSpec("wall", "Wall", "length", 1.6, 0.6, 6.0),
                ParamSpec("hole_diameter", "Screw Ø", "length", 3.4, 1.0, 10.0),
                ParamSpec("mouth_width", "Mouth", "length", 4.0, 1.0, 20.0),
            ),
            builder=build_cable_clip,
        ),
        ComponentDef(
            "zip_tie_mount", "templates", "Zip-tie mount",
            "Screw-down pad with a bridge loop for a cable tie.",
            (
                ParamSpec("length", "Length", "length", 20.0, 6.0, 60.0),
                ParamSpec("width", "Width", "length", 12.0, 4.0, 40.0),
                ParamSpec("hole_diameter", "Screw Ø", "length", 3.4, 1.0, 10.0),
                ParamSpec("slot_width", "Tie slot", "length", 3.0, 1.0, 10.0),
            ),
            builder=build_zip_tie_mount,
        ),
        ComponentDef(
            "gusset", "templates", "Gusset",
            "Triangular corner gusset with mounting holes in each leg.",
            (
                ParamSpec("leg_a", "Leg A", "length", 30.0, 8.0, 200.0),
                ParamSpec("leg_b", "Leg B", "length", 30.0, 8.0, 200.0),
                ParamSpec("thickness", "Thickness", "length", 3.0, 1.0, 20.0),
                ParamSpec("hole_diameter", "Hole Ø", "length", 3.4, 1.0, 10.0),
            ),
            builder=build_gusset,
        ),
        ComponentDef(
            "vent_panel", "templates", "Vent panel",
            "Vented panel: rounded plate with capsule slots and corner holes.",
            (
                ParamSpec("width", "Width", "length", 80.0, 10.0, 400.0),
                ParamSpec("height", "Height", "length", 60.0, 10.0, 300.0),
                ParamSpec("thickness", "Thickness", "length", 2.0, 0.6, 10.0),
                ParamSpec("slots", "Slots", "count", 6, 0, 30, unit=None),
                ParamSpec("slot_width", "Slot width", "length", 4.0, 1.0, 20.0),
                ParamSpec("hole_diameter", "Hole Ø", "length", 3.4, 0.0, 10.0),
            ),
            builder=build_vent_panel,
        ),
        ComponentDef(
            "snap_fit_clip", "templates", "Snap-fit clip",
            "Cantilever snap clip: base, flexible arm and a chamfered hook.",
            (
                ParamSpec("arm_length", "Arm length", "length", 20.0, 5.0, 80.0),
                ParamSpec("width", "Width", "length", 8.0, 2.0, 40.0),
                ParamSpec("thickness", "Thickness", "length", 1.6, 0.6, 8.0),
                ParamSpec("hook_height", "Hook height", "length", 3.0, 0.8, 15.0),
            ),
            builder=build_snap_fit_clip,
        ),
        ComponentDef(
            "pcb_mount_post", "templates", "PCB mount post",
            "Snap-in PCB post: flange, split post, barb and chamfered nose.",
            (
                ParamSpec("height", "Height", "length", 10.0, 3.0, 40.0),
                ParamSpec("diameter", "Diameter", "length", 6.0, 2.0, 20.0),
                ParamSpec("hole_diameter", "Hole Ø", "length", 3.0, 0.0, 10.0),
            ),
            builder=build_pcb_mount_post,
        ),
        ComponentDef(
            "generated_part", "geometry", "Generated part",
            "A CAD specification produced by the existing single-part pipeline.",
            (), insertable=False, parameterized=False, builder=None,
        ),
    )


_REGISTRY: dict[str, ComponentDef] = {d.type: d for d in _defs()}


def get(type_key: str) -> ComponentDef:
    definition = _REGISTRY.get(type_key)
    if definition is None:
        known = ", ".join(sorted(_REGISTRY))
        raise ValueError(
            f"Unknown component type '{type_key}'. "
            f"Available types: {known}."
        )
    return definition


def all_types() -> list[str]:
    return list(_REGISTRY.keys())


def insertable_catalog() -> list[ComponentDef]:
    return [d for d in _REGISTRY.values() if d.insertable]


def public_catalog() -> list[dict[str, object]]:
    """JSON-ready catalog for GET /components (no builders)."""
    out: list[dict[str, object]] = []
    for definition in _REGISTRY.values():
        params = [
            {
                "key": p.key,
                "label": p.label,
                "kind": p.kind,
                "default": p.default,
                "min": p.minimum,
                "max": p.maximum,
                "options": list(p.options) if p.options else None,
                "unit": p.unit,
                "description": p.description,
            }
            for p in definition.parameters
        ]
        out.append(
            {
                "type": definition.type,
                "category": definition.category,
                "display_name": definition.display_name,
                "description": definition.description,
                "insertable": definition.insertable,
                "parameterized": definition.parameterized,
                "has_mounting_points": bool(
                    mounting_points_local(definition.type, default_parameters(definition.type))
                ),
                "parameters": params,
            }
        )
    return out


def prompt_catalog() -> str:
    """Compact type list for the assembly-planning system prompt."""
    lines: list[str] = []
    for definition in _REGISTRY.values():
        if not definition.insertable and definition.type != "generated_part":
            continue
        params = ", ".join(
            f"{p.key}={p.default!r}" + (f"{p.unit}" if p.unit else "")
            for p in definition.parameters
        ) or "none"
        lines.append(
            f"- {definition.type} [{definition.category}]: {definition.display_name}. "
            f"params: {params}. {definition.description}"
        )
    return "\n".join(lines)


def default_parameters(type_key: str) -> dict[str, ParamValue]:
    return {p.key: p.default for p in get(type_key).parameters}


def validate_parameters(
    type_key: str, raw: dict[str, ParamValue] | None
) -> dict[str, ParamValue]:
    """Fill defaults, reject unknown keys, enforce ranges. No `any`."""
    definition = get(type_key)
    incoming = dict(raw or {})
    known = {p.key: p for p in definition.parameters}
    extra = sorted(set(incoming) - set(known))
    if extra:
        raise ValueError(
            f"component '{type_key}' has unknown parameter(s): {', '.join(extra)}"
        )
    out: dict[str, ParamValue] = {}
    for key, spec in known.items():
        if key in incoming:
            value = incoming[key]
        else:
            value = spec.default
        out[key] = _coerce_param(type_key, spec, value)
    return out


def _coerce_param(type_key: str, spec: ParamSpec, value: ParamValue) -> ParamValue:
    label = f"{type_key}.{spec.key}"
    if spec.kind == "flag":
        if not isinstance(value, bool):
            raise ValueError(f"{label} must be true or false")
        return value
    if spec.kind == "choice":
        if not isinstance(value, str):
            raise ValueError(f"{label} must be one of {spec.options}")
        if spec.options is not None and value not in spec.options:
            raise ValueError(
                f"{label} must be one of {list(spec.options)} (got {value!r})"
            )
        return value
    if spec.kind == "count":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{label} must be an integer")
        number = int(value)
        if spec.minimum is not None and number < spec.minimum:
            raise ValueError(f"{label} must be >= {spec.minimum}")
        if spec.maximum is not None and number > spec.maximum:
            raise ValueError(f"{label} must be <= {spec.maximum}")
        return number
    # length
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number (mm)")
    number_f = float(value)
    if not math.isfinite(number_f):
        raise ValueError(f"{label} must be finite")
    if spec.minimum is not None and number_f < spec.minimum:
        raise ValueError(f"{label} must be >= {spec.minimum} mm")
    if spec.maximum is not None and number_f > spec.maximum:
        raise ValueError(f"{label} must be <= {spec.maximum} mm")
    return number_f


def mounting_points_local(
    type_key: str, parameters: dict[str, ParamValue]
) -> list[tuple[float, float, float]]:
    """Local-frame mounting hole centres, or empty if the type has none."""
    if type_key in BOARDS:
        profile = BOARDS[type_key]
        z = profile.height / 2
        return [(x, y, z) for x, y in profile.holes_xy]
    if type_key == "enclosure":
        profile = _board_for_enclosure(parameters)
        if profile is None:
            return []
        height = _f(parameters, "height")
        wall = _f(parameters, "wall_thickness")
        z = -height / 2 + wall
        return [(x, y, z) for x, y in profile.holes_xy]
    if type_key == "lcd_16x2":
        width = _f(parameters, "width")
        depth = _f(parameters, "depth")
        inset_x = width / 2 - 2.54
        inset_y = depth / 2 - 2.54
        return [
            (x, y, 0.8)
            for x in (-inset_x, inset_x)
            for y in (-inset_y, inset_y)
        ]
    if type_key == "servo_motor":
        length = _f(parameters, "length")
        width = _f(parameters, "width")
        height = _f(parameters, "height")
        ear_y = length / 2 + 3.0
        return [
            (x, y, height / 2)
            for y in (-ear_y, ear_y)
            for x in (-width / 2 + 2.0, width / 2 - 2.0)
        ]
    if type_key == "chassis_plate":
        width = _f(parameters, "width")
        depth = _f(parameters, "depth")
        thickness = _f(parameters, "thickness")
        return [(x, y, thickness / 2) for x, y in _chassis_holes(width, depth)]
    if type_key == "bracket":
        # Base-leg holes only: mounted_on places one instance per point with an
        # identity rotation, so a mixed-plane list would seat wall screws wrong.
        width = _f(parameters, "width")
        thickness = _f(parameters, "thickness")
        return [(x, 0.0, thickness) for x in (-width / 4, width / 4)]
    return []


def build_component(
    type_key: str,
    parameters: dict[str, ParamValue],
    generated_spec=None,
):
    """Build a local-frame CadQuery solid for a validated component."""
    if type_key == "generated_part":
        if generated_spec is None:
            raise ValueError("generated_part needs a nested CAD specification")
        from .cadquery_engine import build_operation

        return build_operation(generated_spec.operation)
    definition = get(type_key)
    if definition.builder is None:
        raise ValueError(f"component '{type_key}' has no geometry factory")
    return definition.builder(parameters)
