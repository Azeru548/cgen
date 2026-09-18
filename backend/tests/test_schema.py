"""Milestone 3 tests: CADSpec schema validation (no Groq calls, no CadQuery)."""

import pytest
from pydantic import ValidationError

from app.cad import schema
from app.cad.schema import (
    CADSpec,
    MAX_DIMENSION_MM,
    operation_depth,
    operation_node_count,
)


def valid_payload(**overrides):
    payload = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "rectangular_block",
        "operation": {"type": "box", "width": 100, "depth": 60, "height": 30},
    }
    payload.update(overrides)
    return payload


def box_op(**overrides):
    op = {"type": "box", "width": 100, "depth": 60, "height": 30}
    op.update(overrides)
    return op


# --- Milestone 2 box behavior (regression) ---------------------------------


def test_valid_spec():
    spec = CADSpec.model_validate(valid_payload())
    assert spec.operation.type == "box"
    assert (spec.operation.width, spec.operation.depth, spec.operation.height) == (
        100,
        60,
        30,
    )
    assert spec.units == "mm"


def test_zero_dimensions_rejected():
    for field in ("width", "depth", "height"):
        op = {"type": "box", "width": 100, "depth": 60, "height": 30, field: 0}
        with pytest.raises(ValidationError):
            CADSpec.model_validate(valid_payload(operation=op))


def test_negative_dimensions_rejected():
    op = {"type": "box", "width": -100, "depth": 60, "height": 30}
    with pytest.raises(ValidationError):
        CADSpec.model_validate(valid_payload(operation=op))


def test_dimensions_above_maximum_rejected():
    op = {
        "type": "box",
        "width": MAX_DIMENSION_MM + 1,
        "depth": 60,
        "height": 30,
    }
    with pytest.raises(ValidationError):
        CADSpec.model_validate(valid_payload(operation=op))


def test_wrong_document_type_and_units_rejected():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(valid_payload(document_type="2d_drawing"))
    with pytest.raises(ValidationError):
        CADSpec.model_validate(valid_payload(units="cm"))


def test_blank_and_oversized_names_rejected():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(valid_payload(name="   "))
    with pytest.raises(ValidationError):
        CADSpec.model_validate(valid_payload(name="x" * 101))


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(valid_payload(extra="nope"))


# --- Milestone 3 primitives -------------------------------------------------


def test_valid_cylinder():
    spec = CADSpec.model_validate(
        valid_payload(
            name="shaft",
            operation={"type": "cylinder", "radius": 15, "height": 120},
        )
    )
    assert spec.operation.type == "cylinder"
    assert spec.operation.radius == 15
    assert spec.operation.height == 120
    assert spec.operation.through is False


def test_valid_cone():
    spec = CADSpec.model_validate(
        valid_payload(
            name="funnel",
            operation={
                "type": "cone",
                "bottom_radius": 20,
                "top_radius": 10,
                "height": 50,
            },
        )
    )
    assert spec.operation.bottom_radius == 20
    assert spec.operation.top_radius == 10


def test_valid_sphere():
    spec = CADSpec.model_validate(
        valid_payload(name="ball", operation={"type": "sphere", "radius": 25})
    )
    assert spec.operation.radius == 25


def test_valid_union():
    spec = CADSpec.model_validate(
        valid_payload(
            name="block_on_plate",
            operation={
                "type": "union",
                "base": box_op(),
                "tool": {"type": "cylinder", "radius": 10, "height": 40},
            },
        )
    )
    assert spec.operation.type == "union"
    assert spec.operation.base.type == "box"
    assert spec.operation.tool.type == "cylinder"


def test_valid_cut_shaft_with_hole():
    """The reference nested example from the Milestone 3 spec."""
    spec = CADSpec.model_validate(
        {
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
    )
    assert spec.operation.type == "cut"
    assert spec.operation.tool.through is True


def test_invalid_operation_rejected():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(valid_payload(operation={"type": "torus", "radius": 10}))
    with pytest.raises(ValidationError):
        CADSpec.model_validate(valid_payload(operation={"type": "cylinder"}))


def test_invalid_primitive_dimensions_rejected():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(
                operation={"type": "cylinder", "radius": 0, "height": 120}
            )
        )
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(
                operation={"type": "cone", "bottom_radius": 20, "top_radius": -1, "height": 50}
            )
        )
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(
                operation={"type": "sphere", "radius": MAX_DIMENSION_MM + 1}
            )
        )


def test_unknown_fields_rejected_in_nested_operations():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(
                operation={"type": "sphere", "radius": 25, "color": "red"}
            )
        )
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(
                operation={
                    "type": "cut",
                    "base": box_op(),
                    "tool": {
                        "type": "cylinder",
                        "radius": 5,
                        "height": 40,
                        "depth": 40,  # not a cylinder field
                    },
                }
            )
        )


def test_malformed_nested_operation_rejected():
    # tool missing entirely
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(operation={"type": "cut", "base": box_op()})
        )
    # inner operation has the wrong fields for its type
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(
                operation={
                    "type": "union",
                    "base": box_op(),
                    "tool": {"type": "cylinder", "width": 10, "height": 10},
                }
            )
        )
    # inner operation is not an object at all
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(
                operation={"type": "union", "base": box_op(), "tool": "box"}
            )
        )


def nested_cut(depth: int):
    """A left-leaning cut chain of the given depth (depth 1 = single box)."""
    op = box_op()
    for _ in range(depth - 1):
        op = {
            "type": "cut",
            "base": op,
            "tool": {"type": "cylinder", "radius": 5, "height": 40, "through": True},
        }
    return op


def test_excessive_nesting_rejected():
    with pytest.raises(ValidationError, match="too deep"):
        CADSpec.model_validate(
            valid_payload(name="too_deep", operation=nested_cut(6))
        )
    # Depth exactly at the cap is accepted.
    spec = CADSpec.model_validate(
        valid_payload(name="at_cap", operation=nested_cut(schema.MAX_NESTING_DEPTH))
    )
    assert operation_depth(spec.operation) == schema.MAX_NESTING_DEPTH


def test_too_many_operations_rejected(monkeypatch):
    # Lift the depth cap so the node cap is what trips.
    monkeypatch.setattr(schema, "MAX_NESTING_DEPTH", 100)
    with pytest.raises(ValidationError, match="too many operations"):
        CADSpec.model_validate(valid_payload(name="wide", operation=nested_cut(14)))


def test_depth_and_node_helpers():
    assert operation_depth(CADSpec.model_validate(valid_payload()).operation) == 1
    assert operation_node_count(CADSpec.model_validate(valid_payload()).operation) == 1
    spec = CADSpec.model_validate(
        valid_payload(name="nested", operation=nested_cut(3))
    )
    assert operation_depth(spec.operation) == 3
    assert operation_node_count(spec.operation) == 5
