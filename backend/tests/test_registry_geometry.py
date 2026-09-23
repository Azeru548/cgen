"""M9 component factories: real CadQuery solids (skipped without CadQuery).

Reproduces the enclosure USB-cut Workplane/Shape mismatch and checks that
boolean-using library parts actually produce valid non-empty geometry.
"""

from __future__ import annotations

import math

import pytest

from app.cad import cadquery_engine, registry
from app.cad.assembly import AssemblySpec, ComponentInstance
from app.cad.schema import BoxOperation, CutOperation, CylinderOperation
from app.services.assembly import export_assembly_document
from app.services.file_store import FileStore


def need_cq():
    return pytest.importorskip("cadquery")


def assert_valid_solid(solid, *, min_volume: float = 1e-3):
    cq = need_cq()
    assert not isinstance(solid, cq.Workplane), (
        "factory returned a Workplane; booleans and compound export need a Shape"
    )
    assert hasattr(solid, "wrapped")
    volume = solid.Volume()
    assert volume > min_volume, f"solid volume {volume} is empty"
    assert solid.isValid()
    return volume


def enclosure_params(**overrides):
    params = registry.validate_parameters(
        "enclosure",
        {
            "width": 90,
            "depth": 70,
            "height": 40,
            "wall_thickness": 2.5,
            "board": "none",
            "usb_cutout": False,
            **overrides,
        },
    )
    return params


def test_cut_solid_minus_workplane_tool_produces_geometry():
    """Exact failure mode: Solid.cut(Workplane) -> no attribute 'wrapped'."""
    need_cq()
    base = cadquery_engine.build_operation(
        BoxOperation(width=40, depth=20, height=20)
    )
    tool = cadquery_engine.make_box(10, 10, 10)  # Workplane (M1 helper)
    result = cadquery_engine.cut(base, tool)
    vol = assert_valid_solid(result)
    assert vol < base.Volume()


def test_union_solid_plus_workplane_tool_produces_geometry():
    need_cq()
    base = cadquery_engine.make_cylinder(8, 20)
    tool = cadquery_engine.make_box(30, 6, 6)
    result = cadquery_engine.union(base, tool)
    vol = assert_valid_solid(result)
    assert vol > base.Volume()


def test_existing_single_part_boolean_cut_still_produces_geometry():
    need_cq()
    op = CutOperation(
        base=CylinderOperation(radius=15, height=120),
        tool=CylinderOperation(radius=7.5, height=120, through=True),
    )
    solid = cadquery_engine.build_operation(op)
    vol = assert_valid_solid(solid)
    outer = math.pi * 15**2 * 120
    inner = math.pi * 7.5**2 * 120
    assert vol == pytest.approx(outer - inner, rel=1e-3)


def test_washer_boolean_cut_produces_geometry():
    need_cq()
    solid = registry.build_component(
        "washer",
        registry.validate_parameters("washer", {}),
    )
    vol = assert_valid_solid(solid)
    outer = math.pi * (7.0 / 2) ** 2 * 0.5
    inner = math.pi * (3.2 / 2) ** 2 * 0.5
    assert vol == pytest.approx(outer - inner, rel=1e-2)


def test_enclosure_without_usb_opening():
    need_cq()
    solid = registry.build_enclosure(enclosure_params())
    assert_valid_solid(solid, min_volume=100)


def test_enclosure_with_usb_opening():
    need_cq()
    closed = registry.build_enclosure(enclosure_params(usb_cutout=False, board="none"))
    opened = registry.build_enclosure(enclosure_params(usb_cutout=True, board="none"))
    closed_vol = assert_valid_solid(closed, min_volume=100)
    opened_vol = assert_valid_solid(opened, min_volume=100)
    assert opened_vol < closed_vol


def test_enclosure_with_mounting_holes():
    need_cq()
    plain = registry.build_enclosure(enclosure_params(board="none", usb_cutout=False))
    holed = registry.build_enclosure(
        enclosure_params(board="arduino_uno", usb_cutout=False)
    )
    plain_vol = assert_valid_solid(plain, min_volume=100)
    holed_vol = assert_valid_solid(holed, min_volume=100)
    assert holed_vol < plain_vol


def test_enclosure_with_usb_opening_and_mounting_holes():
    need_cq()
    solid = registry.build_enclosure(
        enclosure_params(board="arduino_uno", usb_cutout=True)
    )
    assert_valid_solid(solid, min_volume=100)


def test_arduino_uno_board_with_mounting_holes():
    need_cq()
    solid = registry.build_component("arduino_uno", {})
    vol = assert_valid_solid(solid)
    full = 68.6 * 53.4 * 1.6
    assert vol < full


def test_m3_screw_union_produces_geometry():
    need_cq()
    solid = registry.build_component(
        "m3_screw", registry.validate_parameters("m3_screw", {"length": 12})
    )
    assert_valid_solid(solid, min_volume=10)


def test_arduino_enclosure_benchmark_assembly_exports():
    """Canonical M9 prompt geometry: enclosure + Arduino + four M3 screws."""
    need_cq()
    spec = AssemblySpec(
        name="arduino_enclosure",
        components=[
            ComponentInstance(
                id="enclosure_1",
                component_type="enclosure",
                name="Enclosure",
                parameters={
                    "width": 90,
                    "depth": 70,
                    "height": 40,
                    "wall_thickness": 2.5,
                    "board": "arduino_uno",
                    "usb_cutout": True,
                },
            ),
            ComponentInstance(
                id="arduino_1",
                component_type="arduino_uno",
                name="Arduino Uno",
                parameters={},
                transform={"position": [0, 0, 8], "rotation": [0, 0, 0]},
                relationships=[{"type": "centered_on", "target_id": "enclosure_1"}],
            ),
            ComponentInstance(
                id="screws_1",
                component_type="m3_screw",
                name="M3 screws",
                parameters={"length": 12},
                relationships=[{"type": "mounted_on", "target_id": "arduino_1"}],
            ),
        ],
    )
    result = export_assembly_document(
        spec, request_id="bench", file_store=FileStore()
    )
    assert result.files["step"].bytes > 0
    assert result.files["stl"].bytes > 0
    screws = next(c for c in result.specification["components"] if c["id"] == "screws_1")
    assert len(screws["instances"]) == 4
    for cid in ("enclosure_1", "arduino_1", "screws_1"):
        files = result.component_files[cid]
        assert files["step"].bytes > 0
        assert files["stl"].bytes > 0


def test_registry_box_is_a_solid_not_a_workplane():
    need_cq()
    cq = need_cq()
    solid = registry._box(10, 8, 6)
    assert not isinstance(solid, cq.Workplane)
    assert solid.Volume() == pytest.approx(10 * 8 * 6, rel=1e-6)
