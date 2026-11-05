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


def test_socket_head_screw_has_a_hex_recess():
    """A cap screw's head is cylindrical with a socket, not a hex prism.

    Old model: 5.5 mm hex-prism head (78.7 mm³) on an un-chamfered shank
    (84.8 mm³) = 163.5 mm³. New model: 5.5 mm cylindrical head with a hex
    socket, on a chamfered shank — measurably less material, and the socket
    is what makes the head read as a cap screw.
    """
    need_cq()
    params = registry.validate_parameters("m3_screw", {"length": 12})
    solid = registry.build_component("m3_screw", params)
    vol = assert_valid_solid(solid, min_volume=10)
    assert vol < 160.0


@pytest.mark.parametrize(
    "type_key",
    ("m3_nut", "m4_nut", "m5_nut", "heat_insert", "hex_standoff", "bracket", "shaft", "hinge"),
)
def test_refined_and_new_components_build_valid_solids(type_key):
    need_cq()
    params = registry.validate_parameters(type_key, {})
    solid = registry.build_component(type_key, params)
    assert_valid_solid(solid)


def test_bracket_rejects_holes_that_do_not_fit():
    need_cq()
    params = registry.validate_parameters("bracket", {"hole_diameter": 12.0})
    with pytest.raises(ValueError, match="too large"):
        registry.build_component("bracket", params)


EXPANDED_TYPES = (
    "m6_screw",
    "m6_nut",
    "set_screw",
    "threaded_rod",
    "t_nut",
    "nyloc_nut",
    "spur_gear",
    "gt2_pulley",
    "v_slot_extrusion",
    "shaft_coupling",
    "shaft_collar",
    "flange",
    "compression_spring",
    "dowel_pin",
    "servo_horn",
    "linear_rail",
    "wheel_hub",
    "ball_caster",
    "idler_pulley",
    "fan",
    "battery_holder",
    "pin_header",
    "dc_barrel_jack",
    "raspberry_pi_pico",
    "arduino_nano",
    "knob",
    "cable_clip",
    "zip_tie_mount",
    "gusset",
    "vent_panel",
    "snap_fit_clip",
    "pcb_mount_post",
)


@pytest.mark.parametrize("type_key", EXPANDED_TYPES)
def test_expanded_library_builds_valid_solids(type_key):
    need_cq()
    params = registry.validate_parameters(type_key, {})
    solid = registry.build_component(type_key, params)
    assert_valid_solid(solid)


def test_spur_gear_actually_cuts_involute_teeth():
    """A 20-tooth m1 gear must come out tooth-shaped, not a smooth disc."""
    need_cq()
    params = registry.validate_parameters("spur_gear", {})
    solid = registry.build_component("spur_gear", params)
    bbox = solid.BoundingBox()
    # Outside diameter = module * (teeth + 2) = 1 * 22.
    assert bbox.xlen == pytest.approx(22.0, abs=0.1)
    assert bbox.ylen == pytest.approx(22.0, abs=0.1)
    # Each tooth contributes flank and tip faces; a plain ring would not.
    assert len(solid.Faces()) > 20 * 8
    assert solid.Volume() < math.pi * 11.0**2 * 5.0 - math.pi * 2.5**2 * 5.0


def test_gt2_pulley_grooves_reduce_the_rim():
    need_cq()
    params = registry.validate_parameters("gt2_pulley", {})
    solid = registry.build_component("gt2_pulley", params)
    # 20T at 2 mm pitch: pitch diameter 12.73, rim 12.48, flanges 14.08.
    assert solid.BoundingBox().xlen == pytest.approx(14.08, abs=0.05)
    # 20 separate grooves interrupt the rim: a smooth pulley would have ~10
    # faces total, a grooved one keeps a face per flank and crown.
    assert len(solid.Faces()) > 70
    # Nothing may overlap the bore.
    assert solid.Volume() < math.pi * (14.08 / 2) ** 2 * 11.2


def test_v_slot_extrusion_keeps_its_corner_webs():
    """Square channel corners would sever the four corner lobes."""
    need_cq()
    params = registry.validate_parameters("v_slot_extrusion", {"length": 200.0})
    solid = registry.build_component("v_slot_extrusion", params)
    assert len(solid.Solids()) == 1, "the T-slots cut the extrusion into loose pieces"
    assert solid.Volume() < 20.0 * 20.0 * 200.0 * 0.55
    assert solid.Volume() > 20.0 * 20.0 * 200.0 * 0.35


def test_compression_spring_is_a_real_sweep():
    need_cq()
    params = registry.validate_parameters("compression_spring", {})
    solid = registry.build_component("compression_spring", params)
    wire_area = math.pi * (params["wire_diameter"] / 2) ** 2
    height = params["free_length"] - params["wire_diameter"]
    turns = params["coils"]
    pitch = height / turns
    helix_length = math.hypot(2 * math.pi * (params["coil_diameter"] - params["wire_diameter"]) / 2, pitch) * turns
    assert solid.Volume() == pytest.approx(wire_area * helix_length, rel=0.06)


def test_screw_head_choice_changes_the_head_shape():
    need_cq()
    countersunk = registry.build_component(
        "m3_screw", registry.validate_parameters("m3_screw", {"head": "countersunk"})
    )
    socket = registry.build_component(
        "m3_screw", registry.validate_parameters("m3_screw", {"head": "socket"})
    )
    assert countersunk.BoundingBox().xlen > socket.BoundingBox().xlen
    assert countersunk.BoundingBox().zlen < socket.BoundingBox().zlen
    with pytest.raises(ValueError, match="head"):
        registry.validate_parameters("m3_screw", {"head": "phillips"})


def test_fan_and_pin_header_match_their_published_envelopes():
    need_cq()
    fan = registry.build_component("fan", registry.validate_parameters("fan", {}))
    assert fan.BoundingBox().xlen == pytest.approx(40.0, abs=0.01)
    header = registry.build_component(
        "pin_header", registry.validate_parameters("pin_header", {})
    )
    assert header.BoundingBox().xlen == pytest.approx(8 * 2.54, abs=0.01)


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
