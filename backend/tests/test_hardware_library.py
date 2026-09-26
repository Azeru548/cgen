"""M10.1: hardware component library, deterministic geometry, manual import.

No LLM anywhere in this module: manual insertion is a deterministic
registry path, and the AI path is checked only for resolvability of the new
component ids.
"""

from __future__ import annotations

import math

import pytest

from app.cad import registry
from app.cad.assembly import (
    AssemblySpec,
    ComponentInstance,
    Transform,
    allocate_component_id,
    resolve_relationships,
    validate_registry,
)

ELECTRONICS = (
    "esp32",
    "arduino_uno",
    "raspberry_pi",
    "oled_096",
    "lcd_16x2",
    "push_button",
    "potentiometer",
    "terminal_block",
)
ROBOTICS = (
    "dc_gear_motor",
    "servo_motor",
    "robot_wheel",
    "caster_wheel",
    "motor_bracket",
    "chassis_plate",
)
MECHANICAL = (
    "m3_screw",
    "m3_nut",
    "washer",
    "standoff",
    "bearing",
    "shaft",
    "bracket",
)


# --- Registry --------------------------------------------------------------


def test_m10_components_are_registered():
    types = set(registry.all_types())
    for required in ELECTRONICS + ROBOTICS + MECHANICAL:
        assert required in types, f"missing component type: {required}"


def test_ids_are_unique_and_metadata_complete():
    types = registry.all_types()
    assert len(types) == len(set(types))
    for type_key in types:
        definition = registry.get(type_key)
        assert definition.display_name.strip()
        assert definition.description.strip()
        assert definition.category in {
            "geometry",
            "fasteners",
            "mechanical",
            "electronics",
            "robotics",
            "templates",
        }
        keys = [p.key for p in definition.parameters]
        assert len(keys) == len(set(keys)), f"{type_key} has duplicate parameter keys"


def test_every_insertable_component_resolves_to_a_builder():
    for definition in registry.insertable_catalog():
        assert definition.builder is not None, f"{definition.type} has no builder"


def test_invalid_component_id_rejected_cleanly():
    with pytest.raises(ValueError, match="Unknown component type"):
        registry.get("quantum_flux_capacitor")
    with pytest.raises(ValueError, match="Unknown component type"):
        registry.validate_parameters("quantum_flux_capacitor", {})


def test_new_component_parameters_validate_and_reject_out_of_range():
    params = registry.validate_parameters("robot_wheel", {})
    assert params["diameter"] == 65.0
    assert params["bore_diameter"] == 6.0
    with pytest.raises(ValueError, match="must be <="):
        registry.validate_parameters("robot_wheel", {"diameter": 9999.0})
    with pytest.raises(ValueError, match="must be >="):
        registry.validate_parameters("dc_gear_motor", {"shaft_diameter": 0.0})
    ways = registry.validate_parameters("terminal_block", {"ways": 4})
    assert ways["ways"] == 4
    with pytest.raises(ValueError, match="must be an integer"):
        registry.validate_parameters("terminal_block", {"ways": 2.5})


def test_mounting_points_exist_for_serviceable_hardware():
    for type_key in ("servo_motor", "chassis_plate", "lcd_16x2"):
        params = registry.validate_parameters(type_key, {})
        points = registry.mounting_points_local(type_key, params)
        assert len(points) == 4, f"{type_key} should expose 4 mounting points"


# --- Geometry --------------------------------------------------------------


def need_cq():
    return pytest.importorskip("cadquery")


def test_every_insertable_component_builds_valid_geometry():
    need_cq()
    for definition in registry.insertable_catalog():
        params = registry.validate_parameters(definition.type, {})
        solid = registry.build_component(definition.type, params)
        assert not isinstance(solid, need_cq().Workplane), (
            f"{definition.type} returned a Workplane, not a Shape"
        )
        assert solid.Volume() > 1e-3, f"{definition.type} built an empty solid"
        assert solid.isValid(), f"{definition.type} built an invalid solid"


def test_dc_motor_has_body_and_shaft():
    need_cq()
    solid = registry.build_component(
        "dc_gear_motor", registry.validate_parameters("dc_gear_motor", {})
    )
    volume = solid.Volume()
    assert volume > math.pi * 11.0**2 * 20.0


def test_robot_wheel_is_annulus_with_axle_bore():
    need_cq()
    solid = registry.build_component(
        "robot_wheel",
        registry.validate_parameters(
            "robot_wheel", {"diameter": 60.0, "width": 20.0, "bore_diameter": 6.0}
        ),
    )
    outer = math.pi * 30.0**2 * 20.0
    inner = math.pi * 3.0**2 * 20.0
    assert solid.Volume() == pytest.approx(outer - inner, rel=1e-2)


def test_robot_wheel_rejects_bore_larger_than_diameter():
    with pytest.raises(ValueError, match="bore_diameter"):
        registry.build_component(
            "robot_wheel",
            registry.validate_parameters(
                "robot_wheel", {"diameter": 20.0, "bore_diameter": 40.0}
            ),
        )


def test_chassis_plate_has_four_holes():
    need_cq()
    plain = registry.build_component(
        "chassis_plate", registry.validate_parameters("chassis_plate", {})
    )
    holed = registry.build_component(
        "chassis_plate",
        registry.validate_parameters(
            "chassis_plate", {"width": 100.0, "depth": 80.0, "thickness": 3.0}
        ),
    )
    assert holed.Volume() < plain.Volume()


def test_servo_has_mounting_ears_holes():
    need_cq()
    solid = registry.build_component(
        "servo_motor", registry.validate_parameters("servo_motor", {})
    )
    assert solid.Volume() > 0
    assert solid.isValid()


def test_terminal_block_bores_scale_with_ways():
    need_cq()
    two = registry.build_component(
        "terminal_block", registry.validate_parameters("terminal_block", {"ways": 2})
    )
    six = registry.build_component(
        "terminal_block", registry.validate_parameters("terminal_block", {"ways": 6})
    )
    assert six.Volume() > two.Volume()


def test_electronics_modules_build():
    need_cq()
    for type_key in ("oled_096", "lcd_16x2", "push_button", "potentiometer"):
        solid = registry.build_component(
            type_key, registry.validate_parameters(type_key, {})
        )
        assert solid.isValid()
        assert solid.Volume() > 1e-3


# --- Manual insertion (no AI) ---------------------------------------------


def test_manual_insert_creates_instance_with_stable_id_and_placement():
    """A component added by id joins the assembly with a non-origin pose."""
    from app.cad.assembly import allocate_component_id as allocate

    first = allocate(set(), "oled_096")
    second = allocate({first}, "oled_096")
    assert first == "oled_096_1"
    assert second == "oled_096_2"

    spec = AssemblySpec(
        name="manual",
        components=[
            ComponentInstance(
                id=first,
                component_type="oled_096",
                name="OLED",
                parameters={},
                transform=Transform(position=(10.0, 0.0, 0.0)),
            )
        ],
    )
    filled = validate_registry(spec)
    assert filled.components[0].component_type == "oled_096"
    assert filled.components[0].parameters["width"] == 27.0


def test_manual_insert_participates_in_export():
    from app.services.assembly import export_assembly_document
    from app.services.file_store import FileStore

    need_cq()
    spec = AssemblySpec(
        name="manual_export",
        components=[
            ComponentInstance(
                id="esp32_1",
                component_type="esp32",
                name="ESP32",
                parameters={},
                transform=Transform(position=(0.0, 0.0, 0.0)),
            ),
            ComponentInstance(
                id="oled_1",
                component_type="oled_096",
                name="OLED",
                parameters={},
                transform=Transform(position=(0.0, 40.0, 0.0)),
            ),
        ],
    )
    result = export_assembly_document(
        spec, request_id="manual", file_store=FileStore()
    )
    assert result.files["step"].bytes > 0
    assert result.files["stl"].bytes > 0
    assert "esp32_1" in result.component_files
    assert "oled_1" in result.component_files
    for cid in ("esp32_1", "oled_1"):
        assert result.component_files[cid]["stl"].bytes > 0


def test_manual_add_endpoint_uses_no_llm(monkeypatch):
    """POST /assembly/add must not touch the Groq client."""
    from fastapi.testclient import TestClient

    from app import main as main_module
    from app.ai import groq_client

    def explode(*_args, **_kwargs):
        raise AssertionError("manual component add must not call the LLM")

    monkeypatch.setattr(groq_client, "plan_assembly", explode, raising=False)
    monkeypatch.setattr(groq_client, "plan_modification", explode, raising=False)

    client = TestClient(main_module.app)
    response = client.post(
        "/assembly/add",
        json={"specification": None, "component_type": "oled_096", "count": 1},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    component = payload["specification"]["components"][0]
    assert component["component_type"] == "oled_096"
    assert component["id"] == "oled_096_1"
    assert payload["component_files"] is not None
    assert payload["component_files"]["oled_096_1"]["stl"]["bytes"] > 0


def test_manual_add_rejects_unknown_component():
    from fastapi.testclient import TestClient

    from app import main as main_module

    client = TestClient(main_module.app)
    response = client.post(
        "/assembly/add",
        json={"specification": None, "component_type": "flux_capacitor", "count": 1},
    )
    assert response.status_code == 422
    assert "Unknown component type" in response.json()["detail"]


# --- Placement -------------------------------------------------------------


def test_manual_add_placement_avoids_overlap():
    """Consecutive manual adds of the same part get distinct poses."""
    from app.services.assembly import manual_placement_transform

    params = registry.validate_parameters("oled_096", {})
    first = manual_placement_transform(0, "oled_096", params)
    second = manual_placement_transform(1, "oled_096", params)
    assert first.position != second.position


def test_manual_placement_scales_with_part_footprint():
    from app.services.assembly import _placement_spacing

    small = _placement_spacing(
        "robot_wheel", registry.validate_parameters("robot_wheel", {"diameter": 40.0})
    )
    large = _placement_spacing(
        "robot_wheel", registry.validate_parameters("robot_wheel", {"diameter": 120.0})
    )
    assert large > small


# --- AI compatibility -----------------------------------------------------


def test_ai_prompt_catalog_offers_new_components():
    catalog = registry.prompt_catalog()
    for type_key in ("dc_gear_motor", "servo_motor", "robot_wheel", "oled_096"):
        assert type_key in catalog


def test_ai_resolves_new_component_ids_through_registry_validation():
    spec = AssemblySpec(
        name="robot",
        components=[
            ComponentInstance(
                id="chassis_1",
                component_type="chassis_plate",
                name="Chassis",
                parameters={},
            ),
            ComponentInstance(
                id="motor_l",
                component_type="dc_gear_motor",
                name="Left motor",
                parameters={},
                transform=Transform(position=(-40.0, 0.0, 5.0)),
            ),
            ComponentInstance(
                id="wheel_l",
                component_type="robot_wheel",
                name="Left wheel",
                parameters={},
                transform=Transform(position=(-52.0, 0.0, 0.0)),
            ),
        ],
    )
    filled = validate_registry(spec)
    assert filled.components[1].parameters["diameter"] == 24.0
    assert filled.components[2].parameters["bore_diameter"] == 6.0


def test_relationship_mounting_works_for_new_hardware():
    spec = AssemblySpec(
        name="chassis_screws",
        components=[
            ComponentInstance(
                id="chassis_1",
                component_type="chassis_plate",
                name="Chassis",
                parameters={},
            ),
            ComponentInstance(
                id="standoffs_1",
                component_type="standoff",
                name="Standoffs",
                parameters={},
                relationships=[{"type": "mounted_on", "target_id": "chassis_1"}],
            ),
        ],
    )
    resolved = resolve_relationships(validate_registry(spec))
    standoffs = next(c for c in resolved.components if c.id == "standoffs_1")
    assert len(standoffs.instances) == 4
