"""Milestone 2 tests: CADSpec schema validation (no Groq calls, no CadQuery)."""

import pytest
from pydantic import ValidationError

from app.cad.schema import CADSpec, MAX_DIMENSION_MM


def valid_payload(**overrides):
    payload = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "rectangular_block",
        "operation": {"type": "box", "width": 100, "depth": 60, "height": 30},
    }
    payload.update(overrides)
    return payload


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


def test_invalid_operation_rejected():
    op = {"type": "cylinder", "width": 100, "depth": 60, "height": 30}
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
