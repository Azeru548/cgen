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
