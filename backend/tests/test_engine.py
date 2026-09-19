"""Milestone 3 tests: deterministic CadQuery engine.

Geometry tests need real CadQuery (cloud/Docker only) and are skipped
locally, following the Milestone 1 pattern. Pure-logic tests (through-hole
math) run everywhere. No Groq calls anywhere in this file.
"""

import math

import pytest

from app.cad import cadquery_engine
from app.cad.schema import BoxOperation, CADSpec

SHAFT_WITH_HOLE = {
    "document_type": "3d_part",
    "units": "mm",
    "name": "shaft_with_hole",
    "operation": {
        "type": "cut",
        "base": {"type": "cylinder", "radius": 15, "height": 120},
        "tool": {
            "type": "cylinder",
            "radius": 7.5,
            "height": 120,
            "through": True,
        },
    },
}


def need_cq():
    return pytest.importorskip("cadquery")


# --- Pure logic (runs everywhere) ------------------------------------------


def test_through_tool_height_math():
    # Span 120 -> 120 + 2 * max(2.0, 0.12) = 124.0
    assert cadquery_engine.through_tool_height(-60, 60) == pytest.approx(124.0)
    # Relative term dominates for very large parts.
    assert cadquery_engine.through_tool_height(0, 10000) == pytest.approx(10020.0)
    with pytest.raises(ValueError):
        cadquery_engine.through_tool_height(5, 5)


def test_build_rejects_unknown_operation():
    need_cq()
    with pytest.raises(ValueError, match="Unsupported operation"):
        cadquery_engine.build_operation(object())


# --- Primitives (need CadQuery) ---------------------------------------------


def test_make_box_volume():
    # Legacy make_box returns a Workplane (Milestone 1 behavior, unchanged);
    # the operation interpreter builds Solids used for volume/boolean checks.
    need_cq()
    solid = cadquery_engine.build_operation(
        BoxOperation(width=10, depth=20, height=30)
    )
    assert solid.Volume() == pytest.approx(6000.0, rel=1e-6)


def test_make_cylinder_volume_and_centering():
    need_cq()
    solid = cadquery_engine.make_cylinder(15, 120)
    assert solid.Volume() == pytest.approx(math.pi * 15**2 * 120, rel=1e-4)
    bbox = solid.BoundingBox()
    assert bbox.zmin == pytest.approx(-60.0)
    assert bbox.zmax == pytest.approx(60.0)


def test_make_cone_volume():
    need_cq()
    solid = cadquery_engine.make_cone(20, 10, 50)
    expected = (1 / 3) * math.pi * 50 * (20**2 + 20 * 10 + 10**2)
    assert solid.Volume() == pytest.approx(expected, rel=1e-4)


def test_make_sphere_volume():
    need_cq()
    solid = cadquery_engine.make_sphere(25)
    assert solid.Volume() == pytest.approx((4 / 3) * math.pi * 25**3, rel=1e-4)


def test_primitive_dims_must_be_positive():
    need_cq()
    with pytest.raises(ValueError):
        cadquery_engine.make_cylinder(0, 10)
    with pytest.raises(ValueError):
        cadquery_engine.make_cone(5, 5, -1)
    with pytest.raises(ValueError):
        cadquery_engine.make_sphere(0)


# --- Booleans (need CadQuery) ------------------------------------------------


def test_union_volume():
    need_cq()
    base = cadquery_engine.build_operation(
        BoxOperation(width=10, depth=10, height=10)
    )  # volume 1000, spans -5..+5
    # Sphere r=8 protrudes from the box, so the union strictly gains volume.
    tool = cadquery_engine.make_sphere(8)
    result = cadquery_engine.union(base, tool)
    assert 1000.0 < result.Volume() < 1000.0 + (4 / 3) * math.pi * 8**3


def test_cut_volume():
    need_cq()
    base = cadquery_engine.build_operation(
        BoxOperation(width=20, depth=20, height=20)
    )  # volume 8000
    tool = cadquery_engine.make_cylinder(5, 30)  # pokes through, removes pi*25*20
    result = cadquery_engine.cut(base, tool)
    assert result.Volume() == pytest.approx(8000 - math.pi * 25 * 20, rel=1e-3)


def test_shaft_with_hole_end_to_end():
    need_cq()
    spec = CADSpec.model_validate(SHAFT_WITH_HOLE)
    solid = cadquery_engine.build_operation(spec.operation)
    base_vol = math.pi * 15**2 * 120
    hole_vol = math.pi * 7.5**2 * 120
    assert solid.Volume() == pytest.approx(base_vol - hole_vol, rel=1e-3)
    assert solid.Volume() > 0


def test_export_operation_step_stl():
    need_cq()
    spec = CADSpec.model_validate(SHAFT_WITH_HOLE)
    result = cadquery_engine.export_operation(spec.operation, name=spec.name)
    assert result["operation"] == "cut"
    assert result["step_bytes"] > 0
    assert result["stl_bytes"] > 0
    with open(result["step_path"], "rb") as f:
        assert b"ISO-10303" in f.read(64)


def test_export_operation_cylinder():
    need_cq()
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "shaft",
            "operation": {"type": "cylinder", "radius": 15, "height": 120},
        }
    )
    result = cadquery_engine.export_operation(spec.operation, name=spec.name)
    assert result["operation"] == "cylinder"
    assert result["step_bytes"] > 0
    assert result["stl_bytes"] > 0


# --- Milestone 6 primitives: torus, polygon_prism ----------------------------


def test_make_torus_volume_and_span():
    need_cq()
    solid = cadquery_engine.make_torus(30, 8)
    expected = 2 * math.pi**2 * 30 * 8**2
    assert solid.Volume() == pytest.approx(expected, rel=1e-4)
    bbox = solid.BoundingBox()
    assert bbox.zmin == pytest.approx(-8.0, abs=1e-6)
    assert bbox.zmax == pytest.approx(8.0, abs=1e-6)
    assert bbox.xmax == pytest.approx(38.0, abs=1e-6)  # R + r


def test_make_torus_rejects_non_ring():
    need_cq()
    with pytest.raises(ValueError):
        cadquery_engine.make_torus(8, 8)
    with pytest.raises(ValueError):
        cadquery_engine.make_torus(8, 9)
    with pytest.raises(ValueError):
        cadquery_engine.make_torus(0, 1)


def test_build_torus_operation_volume():
    need_cq()
    spec = CADSpec.model_validate(
        valid_torus_spec(major=30, minor=8)
    )
    solid = cadquery_engine.build_operation(spec.operation)
    assert solid.Volume() == pytest.approx(2 * math.pi**2 * 30 * 8**2, rel=1e-4)


def test_make_polygon_prism_hex_volume_and_centering():
    need_cq()
    solid = cadquery_engine.make_polygon_prism(6, 10, 8)
    expected = 0.5 * 6 * 10**2 * math.sin(math.pi / 3) * 8
    assert solid.Volume() == pytest.approx(expected, rel=1e-4)
    bbox = solid.BoundingBox()
    assert bbox.zmin == pytest.approx(-4.0, abs=1e-6)
    assert bbox.zmax == pytest.approx(4.0, abs=1e-6)
    assert bbox.xmax == pytest.approx(10.0, abs=1e-6)  # circumradius


def test_make_polygon_prism_rejects_bad_sides_and_dims():
    need_cq()
    with pytest.raises(ValueError):
        cadquery_engine.make_polygon_prism(2, 10, 8)
    with pytest.raises(ValueError):
        cadquery_engine.make_polygon_prism(6, 0, 8)
    with pytest.raises(ValueError):
        cadquery_engine.make_polygon_prism(6, 10, -1)


def test_export_operation_torus():
    need_cq()
    spec = CADSpec.model_validate(valid_torus_spec(major=30, minor=8))
    result = cadquery_engine.export_operation(spec.operation, name=spec.name)
    assert result["operation"] == "torus"
    assert result["step_bytes"] > 0
    assert result["stl_bytes"] > 0
    with open(result["step_path"], "rb") as f:
        assert b"ISO-10303" in f.read(64)


def test_export_operation_polygon_prism():
    need_cq()
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "hex_boss",
            "operation": {
                "type": "polygon_prism",
                "sides": 6,
                "circumradius": 10,
                "height": 8,
            },
        }
    )
    result = cadquery_engine.export_operation(spec.operation, name=spec.name)
    assert result["operation"] == "polygon_prism"
    assert result["step_bytes"] > 0
    assert result["stl_bytes"] > 0


# --- Milestone 6 composition: intersect ---------------------------------------


def test_intersect_volume():
    need_cq()
    base = cadquery_engine.build_operation(
        BoxOperation(width=20, depth=20, height=20)
    )
    tool = cadquery_engine.make_cylinder(5, 30)  # pokes through both faces
    result = cadquery_engine.intersect(base, tool)
    assert result.Volume() == pytest.approx(math.pi * 25 * 20, rel=1e-4)


def test_intersect_disjoint_rejected():
    need_cq()
    ball = cadquery_engine.make_sphere(0.5)
    ring = cadquery_engine.make_torus(5, 1)  # hole radius 4 > ball radius: disjoint
    with pytest.raises(ValueError, match="do not overlap"):
        cadquery_engine.intersect(ball, ring)


def test_intersect_export_operation():
    need_cq()
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "rounded_plate",
            "operation": {
                "type": "intersect",
                "base": {"type": "box", "width": 50, "depth": 50, "height": 10},
                "tool": {"type": "sphere", "radius": 60},
            },
        }
    )
    result = cadquery_engine.export_operation(spec.operation, name=spec.name)
    assert result["operation"] == "intersect"
    assert result["step_bytes"] > 0
    assert result["stl_bytes"] > 0


# --- Milestone 6 part features --------------------------------------------------


def build_plate_part(features):
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "plate",
            "operation": {
                "type": "part",
                "build": {"type": "box", "width": 100, "depth": 60, "height": 10},
                "features": features,
            },
        }
    )
    return cadquery_engine.build_operation(spec.operation)


def test_part_through_hole_volume():
    need_cq()
    solid = build_plate_part([{"type": "hole", "diameter": 8, "through": True}])
    expected = 60000 - math.pi * 16 * 10
    assert solid.Volume() == pytest.approx(expected, rel=1e-4)


def test_part_blind_hole_volume():
    need_cq()
    solid = build_plate_part([{"type": "hole", "diameter": 8, "depth": 9}])
    expected = 60000 - math.pi * 16 * 9
    assert solid.Volume() == pytest.approx(expected, rel=1e-4)


def test_part_concentric_holes_counterbore_pattern():
    need_cq()
    # Largest-first: d16 through + concentric d8 recess 4 deep from the top.
    solid = build_plate_part(
        [
            {"type": "hole", "diameter": 8, "depth": 4},
            {"type": "hole", "diameter": 16, "through": True},
        ]
    )
    # The d16 through hole already spans the full height; the concentric
    # d8 recess (largest-first) removes nothing additional — exactly the
    # counterbore geometry requested. Floor: none. Rim: 6mm tall at r=8.
    expected = 60000 - math.pi * 64 * 10
    assert solid.Volume() == pytest.approx(expected, rel=1e-3)


def test_part_two_blind_holes_differing_depths():
    need_cq()
    # Two concentric blind holes: d8×9 first, then d12×4 (largest diameter
    # first would swallow it — instead check engine applies largest-first by
    # diameter: d12 cuts 4 deep from top, d8 cuts the remaining 5 below it).
    solid = build_plate_part(
        [
            {"type": "hole", "diameter": 8, "depth": 9},
            {"type": "hole", "diameter": 12, "depth": 4},
        ]
    )
    # d12 from z=+5 down to z=+1 (depth 4); d8 from top down 9 (to z=-4)
    # but the upper 4 mm of the d8 cylinder is already inside the d12 cut.
    expected = 60000 - math.pi * 36 * 4 - math.pi * 16 * 5
    assert solid.Volume() == pytest.approx(expected, rel=1e-3)


def test_part_feature_order_is_irrelevant():
    need_cq()
    a = build_plate_part(
        [
            {"type": "hole", "diameter": 8, "through": True},
            {"type": "chamfer", "size": 2},
        ]
    )
    b = build_plate_part(
        [
            {"type": "chamfer", "size": 2},
            {"type": "hole", "diameter": 8, "through": True},
        ]
    )
    assert a.Volume() == pytest.approx(b.Volume(), rel=1e-9)


def test_part_fillet_then_shell_volume():
    need_cq()
    # Engine order is shell first, then fillet (r=1 < wall t=2): valid combo.
    solid = build_plate_part(
        [
            {"type": "fillet", "radius": 1},
            {"type": "shell", "thickness": 2},
        ]
    )
    box = cadquery_engine.build_operation(BoxOperation(width=100, depth=60, height=10))
    shelled = cadquery_engine._apply_shell(box, 2)
    filleted = cadquery_engine._apply_fillet(shelled, 1)
    assert solid.Volume() == pytest.approx(filleted.Volume(), rel=1e-6)


def test_part_fillet_radius_ge_shell_thickness_rejected_cleanly():
    need_cq()
    # Engine order: shell t=2 succeeds, then fillet r=3 (> wall thickness)
    # fails on the hollowed solid with a clean, actionable error.
    with pytest.raises(RuntimeError, match="fillet failed"):
        build_plate_part(
            [
                {"type": "fillet", "radius": 3},
                {"type": "shell", "thickness": 2},
            ]
        )


def test_fillet_on_curved_solid_rejected_cleanly():
    need_cq()
    ring = cadquery_engine.make_torus(30, 8)
    with pytest.raises(ValueError, match="no applicable straight boundary edges"):
        cadquery_engine._apply_fillet(ring, 2)


def test_part_export_with_features():
    need_cq()
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "vent_plate",
            "operation": {
                "type": "part",
                "build": {"type": "box", "width": 80, "depth": 40, "height": 6},
                "features": [
                    {"type": "hole", "diameter": 6, "through": True},
                    {"type": "fillet", "radius": 2},
                ],
            },
        }
    )
    result = cadquery_engine.export_operation(spec.operation, name=spec.name)
    assert result["operation"] == "part"
    assert result["step_bytes"] > 0
    assert result["stl_bytes"] > 0
    with open(result["step_path"], "rb") as f:
        assert b"ISO-10303" in f.read(64)


def test_part_too_thick_shell_rejected_cleanly():
    need_cq()
    # OCCT silently no-ops a shell thicker than the solid; the engine must
    # detect that (no material removed) and fail loudly instead of exporting
    # a non-hollow part as success.
    from app.cad.schema import CADSpec as _S

    spec = _S.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "thin_plate",
            "operation": {
                "type": "part",
                "build": {"type": "box", "width": 40, "depth": 40, "height": 4},
                "features": [{"type": "shell", "thickness": 8}],
            },
        }
    )
    with pytest.raises(RuntimeError, match="shell failed"):
        cadquery_engine.build_operation(spec.operation)


# --- Milestone 6: hole_pattern ------------------------------------------------


def build_pattern_part(count=4, **overrides):
    features = [
        {
            "type": "hole_pattern",
            "diameter": 8,
            "count": count,
            "circle_diameter": 60,
            "through": True,
            "depth": None,
        }
    ]
    features[0].update(overrides)
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "pattern_plate",
            "operation": {
                "type": "part",
                "build": {"type": "box", "width": 100, "depth": 100, "height": 10},
                "features": features,
            },
        }
    )
    return cadquery_engine.build_operation(spec.operation)


def test_pattern_four_through_holes_volume():
    need_cq()
    solid = build_pattern_part(4)
    hole_vol = 4 * math.pi * 16 * 10
    expected = 100 * 100 * 10 - hole_vol
    assert solid.Volume() == pytest.approx(expected, rel=1e-4)


def test_pattern_eight_through_holes_volume():
    need_cq()
    solid = build_pattern_part(8)
    hole_vol = 8 * math.pi * 16 * 10
    expected = 100 * 100 * 10 - hole_vol
    assert solid.Volume() == pytest.approx(expected, rel=1e-4)


def test_pattern_blind_holes_volume():
    need_cq()
    solid = build_pattern_part(4, through=False, depth=6)
    hole_vol = 4 * math.pi * 16 * 6
    expected = 100 * 100 * 10 - hole_vol
    assert solid.Volume() == pytest.approx(expected, rel=1e-4)


def test_pattern_with_central_hole_volume():
    need_cq()
    from app.cad.schema import CADSpec as _S

    spec = _S.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "flange",
            "operation": {
                "type": "part",
                "build": {"type": "cylinder", "radius": 50, "height": 15},
                "features": [
                    {"type": "hole", "diameter": 40, "through": True},
                    {
                        "type": "hole_pattern",
                        "diameter": 8,
                        "count": 4,
                        "circle_diameter": 70,
                        "through": True,
                    },
                ],
            },
        }
    )
    solid = cadquery_engine.build_operation(spec.operation)
    central_hole = math.pi * 400 * 15
    bolt_holes = 4 * math.pi * 16 * 15
    expected = math.pi * 2500 * 15 - central_hole - bolt_holes
    assert solid.Volume() == pytest.approx(expected, rel=1e-4)


def test_pattern_export():
    need_cq()
    from app.cad.schema import CADSpec as _S

    spec = _S.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "flange",
            "operation": {
                "type": "part",
                "build": {"type": "cylinder", "radius": 50, "height": 15},
                "features": [
                    {"type": "hole", "diameter": 40, "through": True},
                    {
                        "type": "hole_pattern",
                        "diameter": 8,
                        "count": 4,
                        "circle_diameter": 70,
                        "through": True,
                    },
                ],
            },
        }
    )
    result = cadquery_engine.export_operation(spec.operation, name=spec.name)
    assert result["operation"] == "part"
    assert result["step_bytes"] > 0
    assert result["stl_bytes"] > 0


def valid_torus_spec(*, major: float, minor: float):
    return CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "o_ring",
            "operation": {
                "type": "torus",
                "major_radius": major,
                "minor_radius": minor,
            },
        }
    )
