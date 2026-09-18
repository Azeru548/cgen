"""Versioned CAD specification schema (Milestone 3).

Contract boundary: Groq produces JSON -> this schema validates it ->
CadQuery builds geometry. Anything outside this schema is rejected.

Schema version: 2.0
Supported operations in v2.0:
  primitives: box, cylinder, cone, sphere
  composition: union (base + tool), cut (base - tool)

All numeric dimensions are millimeters (the AI normalizes to mm before
emitting JSON). Nested trees are allowed but capped in depth and node count
so pathological requests cannot reach the CAD engine.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SPEC_VERSION = "2.0"

# Hard cap per dimension so the AI cannot request absurd geometry.
MAX_DIMENSION_MM = 10_000.0

MAX_NAME_LENGTH = 100

# A primitive alone has depth 1; each union/cut level adds 1.
# A full binary tree of depth 4 holds at most 15 nodes.
MAX_NESTING_DEPTH = 4
MAX_OPERATION_NODES = 15

Dim = Annotated[float, Field(gt=0, le=MAX_DIMENSION_MM)]


class BoxOperation(BaseModel):
    """Rectangular block, width (X) x depth (Y) x height (Z) in mm."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["box"] = "box"
    width: Dim
    depth: Dim
    height: Dim


class CylinderOperation(BaseModel):
    """Cylinder along the Z axis, in mm.

    `through` is only meaningful when this cylinder is the `tool` of a `cut`:
    the engine then extends it through the base automatically. Elsewhere it
    has no effect.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["cylinder"] = "cylinder"
    radius: Dim
    height: Dim
    through: bool = False


class ConeOperation(BaseModel):
    """Cone/frustum along the Z axis: bottom_radius at z=-h/2, top at +h/2."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["cone"] = "cone"
    bottom_radius: Dim
    top_radius: Dim
    height: Dim


class SphereOperation(BaseModel):
    """Sphere of the given radius, in mm."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["sphere"] = "sphere"
    radius: Dim


class UnionOperation(BaseModel):
    """Boolean union: result = base + tool."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["union"] = "union"
    base: "Operation"
    tool: "Operation"


class CutOperation(BaseModel):
    """Boolean subtraction: result = base - tool."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["cut"] = "cut"
    base: "Operation"
    tool: "Operation"


Operation = Annotated[
    Union[
        BoxOperation,
        CylinderOperation,
        ConeOperation,
        SphereOperation,
        UnionOperation,
        CutOperation,
    ],
    Field(discriminator="type"),
]


class CADSpec(BaseModel):
    """Top-level validated CAD specification, schema v2.0."""

    model_config = ConfigDict(extra="forbid")

    document_type: Literal["3d_part"] = "3d_part"
    units: Literal["mm"] = "mm"
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    operation: Operation

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @model_validator(mode="after")
    def operation_tree_must_be_bounded(self) -> "CADSpec":
        depth = operation_depth(self.operation)
        if depth > MAX_NESTING_DEPTH:
            raise ValueError(
                f"operation tree too deep ({depth} > {MAX_NESTING_DEPTH}). "
                "Simplify the request."
            )
        nodes = operation_node_count(self.operation)
        if nodes > MAX_OPERATION_NODES:
            raise ValueError(
                f"too many operations ({nodes} > {MAX_OPERATION_NODES}). "
                "Simplify the request."
            )
        return self


UnionOperation.model_rebuild()
CutOperation.model_rebuild()
CADSpec.model_rebuild()


def operation_depth(op: BaseModel) -> int:
    """Nesting depth of an operation tree; a lone primitive has depth 1."""
    if isinstance(op, (UnionOperation, CutOperation)):
        return 1 + max(operation_depth(op.base), operation_depth(op.tool))
    return 1


def operation_node_count(op: BaseModel) -> int:
    """Total number of operation nodes in the tree."""
    if isinstance(op, (UnionOperation, CutOperation)):
        return 1 + operation_node_count(op.base) + operation_node_count(op.tool)
    return 1
