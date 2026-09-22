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
Category = Literal["geometry", "fasteners", "mechanical", "electronics", "templates"]


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
    from .cadquery_engine import make_box

    return make_box(w, d, h)


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


def _metric_screw(diameter: float, head_af: float, head_h: float):
    def builder(params: dict[str, ParamValue]):
        length = _f(params, "length")
        shaft = _cyl(diameter / 2, length)
        shaft = _translate(shaft, 0, 0, length / 2)
        head = _hex_prism(head_af, head_h)
        head = _translate(head, 0, 0, length + head_h / 2)
        return _union(shaft, head)

    return builder


def _metric_nut(hole: float, af: float, height: float):
    def builder(params: dict[str, ParamValue]):
        body = _hex_prism(af, height)
        cutter = _cyl(hole / 2, height + 4)
        return _cut(body, cutter)

    return builder


def build_washer(params: dict[str, ParamValue]):
    inner = _f(params, "inner_diameter")
    outer = _f(params, "outer_diameter")
    thickness = _f(params, "thickness")
    if inner >= outer:
        raise ValueError("washer inner_diameter must be smaller than outer_diameter")
    body = _cyl(outer / 2, thickness)
    cutter = _cyl(inner / 2, thickness + 4)
    return _cut(body, cutter)


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


def build_bracket(params: dict[str, ParamValue]):
    width = _f(params, "width")
    depth = _f(params, "depth")
    height = _f(params, "height")
    thickness = _f(params, "thickness")
    if thickness >= min(width, depth, height):
        raise ValueError("bracket thickness must be smaller than width, depth and height")
    base = _box(width, depth, thickness)
    base = _translate(base, 0, 0, thickness / 2)
    wall = _box(width, thickness, height)
    wall = _translate(wall, 0, -depth / 2 + thickness / 2, height / 2)
    return _union(base, wall)


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
    return _build_from_operation(
        CylinderOperation(
            radius=_f(params, "diameter") / 2,
            height=_f(params, "length"),
        )
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
    length = _f(params, "length")
    knuckle = _f(params, "knuckle_diameter")
    leaf = _f(params, "leaf_width")
    thickness = _f(params, "thickness")
    pin = _cyl(knuckle / 2 * 0.55, length + 2)
    barrel = _cyl(knuckle / 2, length)
    left = _box(leaf, length, thickness)
    left = _translate(left, -leaf / 2 - knuckle / 2, 0, 0)
    right = _box(leaf, length, thickness)
    right = _translate(right, leaf / 2 + knuckle / 2, 0, 0)
    return _union(_union(_union(barrel, pin), left), right)


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


def build_usb_connector(params: dict[str, ParamValue]):
    return _box(_f(params, "length"), _f(params, "width"), _f(params, "height"))


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
_SCREW_LEN = (ParamSpec("length", "Length", "length", 12.0, 4.0, 80.0),)


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
            (ParamSpec("length", "Length", "length", 16.0, 6.0, 100.0),),
            builder=_metric_screw(4.0, 7.0, 4.0),
        ),
        ComponentDef(
            "m3_nut", "fasteners", "M3 Nut",
            "M3 hex nut. Across-flats 5.5 mm.",
            (), parameterized=False, builder=_metric_nut(3.0, 5.5, 2.4),
        ),
        ComponentDef(
            "m4_nut", "fasteners", "M4 Nut",
            "M4 hex nut. Across-flats 7 mm.",
            (), parameterized=False, builder=_metric_nut(4.0, 7.0, 3.2),
        ),
        ComponentDef(
            "washer", "fasteners", "Washer",
            "Plain washer. Defaults match M3.",
            (
                ParamSpec("inner_diameter", "Inner Ø", "length", 3.2, 0.5, 50.0),
                ParamSpec("outer_diameter", "Outer Ø", "length", 7.0, 1.0, 80.0),
                ParamSpec("thickness", "Thickness", "length", 0.5, 0.1, 10.0),
            ),
            builder=build_washer,
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
            "bracket", "mechanical", "L-bracket",
            "L-bracket from two plates. Origin at the inner corner on the base.",
            (
                ParamSpec("width", "Width", "length", 40.0, 5.0, 400.0),
                ParamSpec("depth", "Depth", "length", 30.0, 5.0, 400.0),
                ParamSpec("height", "Height", "length", 30.0, 5.0, 400.0),
                ParamSpec("thickness", "Thickness", "length", 3.0, 0.5, 20.0),
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
            "Plain cylindrical shaft, axis +Z.",
            (
                ParamSpec("diameter", "Diameter", "length", 8.0, 0.5, 200.0),
                ParamSpec("length", "Length", "length", 60.0, 1.0, 1000.0),
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
            "Simplified butt hinge: barrel, pin, two leaves. No real knuckle joint.",
            (
                ParamSpec("length", "Length", "length", 40.0, 10.0, 200.0),
                ParamSpec("knuckle_diameter", "Knuckle Ø", "length", 6.0, 2.0, 30.0),
                ParamSpec("leaf_width", "Leaf width", "length", 16.0, 4.0, 80.0),
                ParamSpec("thickness", "Thickness", "length", 2.0, 0.5, 8.0),
            ),
            builder=build_hinge,
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
                "has_mounting_points": definition.type in BOARDS
                or definition.type == "enclosure",
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
