"""Milestone 3 tests: CADSpec schema validation (no Groq calls, no CadQuery)."""

import pytest
from pydantic import ValidationError

from app.cad import schema
from app.cad.schema import (
    CADSpec,
    MAX_DIMENSION_MM,
    feature_summary,
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
        CADSpec.model_validate(valid_payload(operation={"type": "extrude", "height": 10}))
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


# --- Milestone 6 primitives: torus, polygon_prism ---------------------------


def test_valid_torus():
    spec = CADSpec.model_validate(
        valid_payload(
            name="o_ring",
            operation={"type": "torus", "major_radius": 30, "minor_radius": 8},
        )
    )
    assert spec.operation.type == "torus"
    assert spec.operation.major_radius == 30
    assert spec.operation.minor_radius == 8


def test_valid_torus_inside_composition():
    spec = CADSpec.model_validate(
        valid_payload(
            name="ring_union",
            operation={
                "type": "union",
                "base": {"type": "torus", "major_radius": 30, "minor_radius": 8},
                "tool": box_op(),
            },
        )
    )
    assert spec.operation.base.type == "torus"


def test_torus_minor_ge_major_rejected():
    for minor in (30, 31):
        with pytest.raises(ValidationError):
            CADSpec.model_validate(
                valid_payload(
                    operation={"type": "torus", "major_radius": 30, "minor_radius": minor}
                )
            )


def test_torus_bounds_enforced():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(
                operation={"type": "torus", "major_radius": 0, "minor_radius": 5}
            )
        )
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(
                operation={
                    "type": "torus",
                    "major_radius": MAX_DIMENSION_MM + 1,
                    "minor_radius": 5,
                }
            )
        )


def test_valid_polygon_prism():
    spec = CADSpec.model_validate(
        valid_payload(
            name="hex_boss",
            operation={"type": "polygon_prism", "sides": 6, "circumradius": 10, "height": 8},
        )
    )
    assert spec.operation.type == "polygon_prism"
    assert spec.operation.sides == 6
    assert spec.operation.circumradius == 10


def test_polygon_prism_sides_bounds():
    for bad_sides in (2, 13):
        with pytest.raises(ValidationError):
            CADSpec.model_validate(
                valid_payload(
                    operation={
                        "type": "polygon_prism",
                        "sides": bad_sides,
                        "circumradius": 10,
                        "height": 8,
                    }
                )
            )


def test_polygon_prism_sides_must_be_integer_like():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(
                operation={
                    "type": "polygon_prism",
                    "sides": 6.5,
                    "circumradius": 10,
                    "height": 8,
                }
            )
        )


def test_polygon_prism_dimension_bounds():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(
                operation={
                    "type": "polygon_prism",
                    "sides": 6,
                    "circumradius": 0,
                    "height": 8,
                }
            )
        )


# --- Milestone 6 composition: intersect --------------------------------------


def test_valid_intersect():
    spec = CADSpec.model_validate(
        valid_payload(
            name="lens",
            operation={
                "type": "intersect",
                "base": box_op(),
                "tool": {"type": "sphere", "radius": 60},
            },
        )
    )
    assert spec.operation.type == "intersect"
    assert spec.operation.base.type == "box"
    assert spec.operation.tool.type == "sphere"


def test_intersect_nested_in_booleans():
    spec = CADSpec.model_validate(
        valid_payload(
            name="composed",
            operation={
                "type": "cut",
                "base": {
                    "type": "intersect",
                    "base": box_op(),
                    "tool": {"type": "sphere", "radius": 60},
                },
                "tool": {"type": "cylinder", "radius": 5, "height": 40, "through": True},
            },
        )
    )
    assert spec.operation.base.type == "intersect"
    assert operation_depth(spec.operation) == 3


def test_intersect_missing_tool_rejected():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(operation={"type": "intersect", "base": box_op()})
        )


# --- Milestone 6 feature node: part ------------------------------------------


def plate_payload(features):
    return valid_payload(
        name="plate",
        operation={
            "type": "part",
            "build": {"type": "box", "width": 100, "depth": 60, "height": 10},
            "features": features,
        },
    )


def test_valid_part_with_features():
    spec = CADSpec.model_validate(
        plate_payload(
            [
                {"type": "hole", "diameter": 8, "through": True},
                {"type": "fillet", "radius": 3},
                {"type": "chamfer", "size": 2},
                {"type": "shell", "thickness": 2},
            ]
        )
    )
    assert spec.operation.type == "part"
    assert spec.operation.build.type == "box"
    assert len(spec.operation.features) == 4


def test_part_without_features_is_valid():
    spec = CADSpec.model_validate(plate_payload([]))
    assert spec.operation.features == []


def test_part_features_order_is_normalized_for_display():
    # Engine applies holes -> shell -> chamfer -> fillet regardless of list order.
    spec = CADSpec.model_validate(
        plate_payload(
            [
                {"type": "chamfer", "size": 2},
                {"type": "hole", "diameter": 8, "through": True},
                {"type": "fillet", "radius": 3},
            ]
        )
    )
    assert feature_summary(spec.operation) == ["hole", "chamfer", "fillet"]


def test_part_allows_multiple_holes_up_to_cap():
    features = [
        {"type": "hole", "diameter": 6, "through": True},
        {"type": "hole", "diameter": 3, "depth": 8},
        {"type": "fillet", "radius": 2},
        {"type": "chamfer", "size": 2},
    ]
    spec = CADSpec.model_validate(plate_payload(features))
    assert len(spec.operation.features) == 4


def test_part_feature_cap_enforced():
    features = [
        {"type": "hole", "diameter": 6, "through": True},
        {"type": "hole", "diameter": 3, "depth": 8},
        {"type": "fillet", "radius": 2},
        {"type": "chamfer", "size": 2},
    ]
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            plate_payload(features + [{"type": "shell", "thickness": 1}])
        )


def test_part_counts_toward_depth_and_nodes():
    spec = CADSpec.model_validate(plate_payload([]))
    assert operation_depth(spec.operation) == 2
    assert operation_node_count(spec.operation) == 2
    # part wrapping the reference cut tree: depth 3, nodes 4
    spec2 = CADSpec.model_validate(
        valid_payload(
            name="shaft_part",
            operation={
                "type": "part",
                "build": {
                    "type": "cut",
                    "base": {"type": "cylinder", "radius": 15, "height": 120},
                    "tool": {"type": "cylinder", "radius": 7.5, "height": 120, "through": True},
                },
                "features": [{"type": "fillet", "radius": 1}],
            },
        )
    )
    assert operation_depth(spec2.operation) == 3
    assert operation_node_count(spec2.operation) == 4


def test_part_nesting_rejected_everywhere():
    inner = {
        "type": "part",
        "build": box_op(),
        "features": [],
    }
    # part inside part
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(
                name="nested_part",
                operation={"type": "part", "build": inner, "features": []},
            )
        )
    # part inside a boolean
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(
                name="boolean_part",
                operation={"type": "union", "base": box_op(), "tool": inner},
            )
        )


def test_part_extra_and_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            valid_payload(
                name="bad_part",
                operation={
                    "type": "part",
                    "build": box_op(),
                    "features": [],
                    "position": {"x": 1},
                },
            )
        )
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            plate_payload([{"type": "hole", "diameter": 8, "through": True, "offset": 5}])
        )
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            plate_payload([{"type": "engrave", "text": "hi"}])
        )


# --- Milestone 6 feature validation ------------------------------------------


def test_blind_hole_requires_depth():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            plate_payload([{"type": "hole", "diameter": 8}])
        )


def test_through_hole_rejects_depth():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            plate_payload([{"type": "hole", "diameter": 8, "through": True, "depth": 20}])
        )


def test_shallow_wide_blind_hole_is_valid_counterbore():
    # Shallow wide blind holes are legitimate counterbore recesses; combined
    # with a concentric through hole they form a counterbored hole.
    spec = CADSpec.model_validate(
        plate_payload(
            [
                {"type": "hole", "diameter": 16, "through": True},
                {"type": "hole", "diameter": 8, "depth": 4},
            ]
        )
    )
    assert len(spec.operation.features) == 2


def test_blind_hole_depth_recorded():
    spec = CADSpec.model_validate(
        plate_payload([{"type": "hole", "diameter": 8, "depth": 20}])
    )
    assert spec.operation.features[0].depth == 20


def test_feature_sizes_bounded():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            plate_payload([{"type": "fillet", "radius": 0}])
        )
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            plate_payload([{"type": "fillet", "radius": MAX_DIMENSION_MM + 1}])
        )
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            plate_payload([{"type": "chamfer", "size": 0}])
        )
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            plate_payload([{"type": "shell", "thickness": -1}])
        )


def test_shell_position_in_list_is_irrelevant():
    # Application order is owned by the engine (holes -> shell -> chamfer ->
    # fillet); the schema accepts shell anywhere in the feature list.
    for features in (
        [{"type": "shell", "thickness": 2}, {"type": "fillet", "radius": 3}],
        [{"type": "fillet", "radius": 3}, {"type": "shell", "thickness": 2}],
    ):
        spec = CADSpec.model_validate(plate_payload(features))
        assert feature_summary(spec.operation) == ["shell", "fillet"]


# --- Schema v3.1: hole_pattern ------------------------------------------------


def pattern_payload(count=4, **overrides):
    feature = {
        "type": "hole_pattern",
        "diameter": 8,
        "count": count,
        "circle_diameter": 60,
        "through": True,
    }
    feature.update(overrides)
    return plate_payload([feature])


def test_valid_hole_pattern_four_holes():
    spec = CADSpec.model_validate(pattern_payload(4))
    assert spec.operation.features[0].type == "hole_pattern"
    assert spec.operation.features[0].count == 4


def test_valid_hole_pattern_eight_holes():
    spec = CADSpec.model_validate(pattern_payload(8))
    assert spec.operation.features[0].count == 8


def test_hole_pattern_count_bounds_rejected():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(pattern_payload(1))
    with pytest.raises(ValidationError):
        CADSpec.model_validate(pattern_payload(13))


def test_hole_pattern_through_depth_rules():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(pattern_payload(4, depth=12))
    with pytest.raises(ValidationError):
        CADSpec.model_validate(
            pattern_payload(4, through=False, depth=None)
        )
    # Blind pattern with depth is valid.
    spec = CADSpec.model_validate(pattern_payload(4, through=False, depth=6))
    assert spec.operation.features[0].depth == 6


def test_hole_pattern_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        CADSpec.model_validate(pattern_payload(4, position=[10, 0]))


def test_flange_central_hole_plus_pattern_within_cap():
    spec = CADSpec.model_validate(
        valid_payload(
            name="flange",
            operation={
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
        )
    )
    assert len(spec.operation.features) == 2
    assert feature_summary(spec.operation) == ["hole", "hole_pattern"]
