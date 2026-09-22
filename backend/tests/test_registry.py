"""Milestone 9: component registry lookup and parameter validation (no CAD)."""

import pytest
from pydantic import ValidationError

from app.cad import registry
from app.cad.assembly import (
    AssemblySpec,
    ComponentInstance,
    Transform,
    allocate_component_id,
    resolve_relationships,
    validate_registry,
)


def test_catalog_has_required_types():
    types = set(registry.all_types())
    for required in (
        "box",
        "cylinder",
        "sphere",
        "m3_screw",
        "m3_nut",
        "washer",
        "standoff",
        "arduino_uno",
        "raspberry_pi",
        "esp32",
        "bracket",
        "enclosure",
        "enclosure_lid",
    ):
        assert required in types
    assert len(types) >= 20


def test_unknown_component_rejected():
    with pytest.raises(ValueError, match="Unknown component type"):
        registry.get("flux_capacitor")


def test_parameter_defaults_and_unknown_keys():
    params = registry.validate_parameters("m3_screw", {})
    assert params["length"] == 12.0
    with pytest.raises(ValueError, match="unknown parameter"):
        registry.validate_parameters("m3_screw", {"length": 12, "magic": 1})


def test_parameter_range_rejected():
    with pytest.raises(ValueError, match="must be >="):
        registry.validate_parameters("box", {"width": 0, "depth": 10, "height": 10})
    with pytest.raises(ValueError, match="must be one of"):
        registry.validate_parameters(
            "enclosure",
            {
                "width": 90,
                "depth": 70,
                "height": 40,
                "wall_thickness": 2.5,
                "board": "commodore_64",
                "usb_cutout": True,
            },
        )


def test_generated_part_not_insertable():
    assert registry.get("generated_part").insertable is False


def test_assembly_schema_rejects_unknown_relationship_target():
    with pytest.raises(ValidationError, match="missing component"):
        AssemblySpec.model_validate(
            {
                "document_type": "3d_assembly",
                "units": "mm",
                "name": "bad",
                "schema_version": "4.0",
                "components": [
                    {
                        "id": "box_1",
                        "component_type": "box",
                        "name": "Box",
                        "parameters": {"width": 10, "depth": 10, "height": 10},
                        "transform": {"position": [0, 0, 0], "rotation": [0, 0, 0]},
                        "visible": True,
                        "instances": [],
                        "relationships": [
                            {"type": "mounted_on", "target_id": "nope"}
                        ],
                    }
                ],
            }
        )


def test_assembly_schema_rejects_duplicate_ids():
    box = {
        "id": "box_1",
        "component_type": "box",
        "name": "Box",
        "parameters": {"width": 10, "depth": 10, "height": 10},
        "transform": {"position": [0, 0, 0], "rotation": [0, 0, 0]},
        "visible": True,
        "instances": [],
        "relationships": [],
    }
    other = dict(box)
    with pytest.raises(ValidationError, match="duplicate"):
        AssemblySpec.model_validate(
            {
                "document_type": "3d_assembly",
                "units": "mm",
                "name": "dup",
                "schema_version": "4.0",
                "components": [box, other],
            }
        )


def test_validate_registry_fills_defaults():
    spec = AssemblySpec(
        name="screws",
        components=[
            ComponentInstance(
                id="m3_screw_1",
                component_type="m3_screw",
                name="M3 Screw",
                parameters={},
            )
        ],
    )
    filled = validate_registry(spec)
    assert filled.components[0].parameters["length"] == 12.0


def test_validate_registry_rejects_unknown_type():
    spec = AssemblySpec(
        name="bad",
        components=[
            ComponentInstance(
                id="weird_1",
                component_type="box",
                name="Nope",
                parameters={"width": 10, "depth": 10, "height": 10},
            )
        ],
    )
    spec.components[0].component_type  # keep typed
    # Bypass ComponentInstance type regex by constructing via model_copy after
    # swapping type through a dump.
    dumped = spec.model_dump()
    dumped["components"][0]["component_type"] = "not_a_real_part"
    with pytest.raises(ValueError, match="Unknown component type"):
        validate_registry(AssemblySpec.model_validate(dumped))


def test_allocate_component_id_is_stable():
    assert allocate_component_id(set(), "m3_screw") == "m3_screw_1"
    assert allocate_component_id({"m3_screw_1"}, "m3_screw") == "m3_screw_2"


def test_mounted_on_creates_instances_from_arduino_holes():
    spec = AssemblySpec(
        name="board_screws",
        components=[
            ComponentInstance(
                id="arduino_1",
                component_type="arduino_uno",
                name="Arduino Uno",
                parameters={},
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
    resolved = resolve_relationships(validate_registry(spec))
    screws = next(c for c in resolved.components if c.id == "screws_1")
    assert len(screws.instances) == 4
    zs = {round(p.position[2], 4) for p in screws.instances}
    assert zs == {0.8}


def test_mounted_on_without_points_rejected():
    spec = AssemblySpec(
        name="bad_mount",
        components=[
            ComponentInstance(
                id="box_1",
                component_type="box",
                name="Box",
                parameters={"width": 20, "depth": 20, "height": 10},
            ),
            ComponentInstance(
                id="screws_1",
                component_type="m3_screw",
                name="M3",
                parameters={"length": 12},
                relationships=[{"type": "mounted_on", "target_id": "box_1"}],
            ),
        ],
    )
    with pytest.raises(ValueError, match="no mounting points"):
        resolve_relationships(validate_registry(spec))


def test_transform_validation_rejects_nan():
    with pytest.raises(ValidationError):
        Transform.model_validate({"position": [0, float("nan"), 0], "rotation": [0, 0, 0]})


def test_arduino_does_not_fit_tiny_enclosure():
    params = registry.validate_parameters(
        "enclosure",
        {
            "width": 30,
            "depth": 30,
            "height": 20,
            "wall_thickness": 2.5,
            "board": "arduino_uno",
            "usb_cutout": False,
        },
    )
    with pytest.raises(ValueError, match="does not fit"):
        registry._assert_board_fits(registry.BOARDS["arduino_uno"], 30, 30, 2.5)
    assert params["board"] == "arduino_uno"
