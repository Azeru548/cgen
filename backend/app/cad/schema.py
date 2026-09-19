"""Versioned CAD specification schema (Milestone 6, extended in 3.1).

Contract boundary: Groq produces JSON -> this schema validates it ->
CadQuery builds geometry. Anything outside this schema is rejected.

Schema version: 3.1 (additive over 3.0; all v3.0 specifications remain valid)

Build operations in v3.0 (geometry construction):
  primitives : box, cylinder, cone, sphere, torus, polygon_prism
  composition: union (base + tool), cut (base - tool), intersect (base ∩ tool)

Feature node in v3.0 (deterministic engineering features on a solid):
  part {build, features[]} where features are applied in engine-fixed order:
    hole (drill along +Z through the part's bbox, centered on the bbox),
    fillet (all convex bbox-boundary edges, normalized |X| or |Y| edges),
    chamfer (same edge set as fillet, conical bevel),
    shell (hollow: wall thickness, top face removed)

v3.1 adds ONE feature variant (MAX_FEATURES stays 4):
    hole_pattern (N identical holes on a deterministic bolt circle in the
    XY plane — hole i sits at angle 2π·i/count on circle_diameter,
    centered on the part; the LLM never positions individual holes)

Engineering features are STRUCTURAL, not spatial: they carry no offsets and
no rotation. All placement remains deterministic and origin-centered — the
LLM never computes positions (that extension is deliberately out of M6; it
requires a placement-aware schema redesign, see M7).

All numeric dimensions are millimeters. Nested trees are capped in depth and
node count so pathological requests cannot reach the CAD engine.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SPEC_VERSION = "3.1"

# Hard cap per dimension so the AI cannot request absurd geometry.
MAX_DIMENSION_MM = 10_000.0

MAX_NAME_LENGTH = 100

# A primitive alone has depth 1; each composition level (union/cut/intersect)
# adds 1; a part node adds 1 on top of its build subtree.
# A full binary tree of depth 4 holds at most 15 nodes.
MAX_NESTING_DEPTH = 4
MAX_OPERATION_NODES = 15

# Engineering features per part node (bounded composition, not unbounded trees).
MAX_FEATURES = 4

Dim = Annotated[float, Field(gt=0, le=MAX_DIMENSION_MM)]

# Shorthand wall/edge sizes are still real geometry dimensions: keep the same
# bounds so a shell/fillet/chamfer can never request absurd geometry.
Size = Annotated[float, Field(gt=0, le=MAX_DIMENSION_MM)]


# --- Build operations: primitives -------------------------------------------


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


class TorusOperation(BaseModel):
    """Ring torus: major_radius to the tube center, minor_radius the tube.

    Axis +Z, centered on the origin. Only ring tori (minor < major) are
    valid: a self-intersecting spindle torus is geometrically degenerate
    for CAD export.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["torus"] = "torus"
    major_radius: Dim
    minor_radius: Dim

    @model_validator(mode="after")
    def minor_radius_must_be_smaller(self) -> "TorusOperation":
        if self.minor_radius >= self.major_radius:
            raise ValueError(
                "torus minor_radius must be smaller than major_radius"
            )
        return self


class PolygonPrismOperation(BaseModel):
    """Regular n-gon prism: circumradius is the vertex radius (center -> corner).

    Axis +Z, centered on the origin. Hex bolts, prismatic stock, etc.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["polygon_prism"] = "polygon_prism"
    sides: int = Field(ge=3, le=12)
    circumradius: Dim
    height: Dim


# --- Build operations: composition -------------------------------------------


class UnionOperation(BaseModel):
    """Boolean union: result = base + tool."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["union"] = "union"
    base: "BuildOperation"
    tool: "BuildOperation"


class CutOperation(BaseModel):
    """Boolean subtraction: result = base - tool."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["cut"] = "cut"
    base: "BuildOperation"
    tool: "BuildOperation"


class IntersectOperation(BaseModel):
    """Boolean intersection: result = base ∩ tool (the shared volume).

    base and tool must overlap; a disjoint pair yields an empty solid and is
    rejected at build time (mapped to HTTP 422).
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["intersect"] = "intersect"
    base: "BuildOperation"
    tool: "BuildOperation"


# --- Engineering features (structural, applied by the engine in fixed order) --


class HoleFeature(BaseModel):
    """Drilled hole along the Z axis.

    The engine centers the hole on the solid's bounding box and, for through
    holes, extends the cutter beyond the full Z extent (same deterministic
    rule as the legacy `cut`+`through` cylinder). The LLM never computes
    offsets. `depth` is only meaningful for blind holes; shallow wide blind
    holes are valid and give counterbore-style recesses when concentric
    with a larger through hole.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["hole"] = "hole"
    diameter: Dim
    through: bool = False
    depth: Size | None = None

    @model_validator(mode="after")
    def blind_depth_required(self) -> "HoleFeature":
        if not self.through and self.depth is None:
            raise ValueError(
                "hole needs depth (blind) or through=true (through hole)"
            )
        if self.through and self.depth is not None:
            raise ValueError("through hole must not specify depth")
        return self


class HolePatternFeature(BaseModel):
    """N identical holes on a deterministic bolt circle in the XY plane.

    ONE feature regardless of count: hole i (0-based) sits at angle
    2π·i/count on a circle of `circle_diameter`, centered on the solid's
    bounding-box center. Diameter/depth/through conventions match
    HoleFeature. The LLM never positions individual holes; arbitrary
    per-hole placement is deliberately out of scope.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["hole_pattern"] = "hole_pattern"
    diameter: Dim
    count: int = Field(ge=2, le=12)
    circle_diameter: Dim
    through: bool = False
    depth: Size | None = None

    @model_validator(mode="after")
    def blind_depth_required(self) -> "HolePatternFeature":
        if not self.through and self.depth is None:
            raise ValueError(
                "hole_pattern needs depth (blind) or through=true (through holes)"
            )
        if self.through and self.depth is not None:
            raise ValueError("through hole_pattern must not specify depth")
        return self


class FilletFeature(BaseModel):
    """Round all convex bbox-boundary edges (|X| and |Y| edge directions)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["fillet"] = "fillet"
    radius: Size


class ChamferFeature(BaseModel):
    """45° bevel on the same deterministic edge set as fillet."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["chamfer"] = "chamfer"
    size: Size


class ShellFeature(BaseModel):
    """Hollow the solid: wall thickness, top face open.

    Deterministic OCCT behavior; one thickness for all walls. The engine
    applies shell before edge features (fillet/chamfer) regardless of list
    order — that order is robust where the reverse produces invalid solids.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["shell"] = "shell"
    thickness: Size


Feature = Annotated[
    Union[HoleFeature, HolePatternFeature, FilletFeature, ChamferFeature, ShellFeature],
    Field(discriminator="type"),
]


# --- Feature node -------------------------------------------------------------


class PartOperation(BaseModel):
    """A built solid plus deterministic engineering features.

    `build` constructs the solid (any non-part operation). `features` are
    applied in engine-fixed order (hole(s) -> shell -> chamfer -> fillet)
    regardless of list order, keeping geometry deterministic.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["part"] = "part"
    build: "BuildOperation"
    features: list[Feature] = Field(default_factory=list, max_length=MAX_FEATURES)


# --- Discriminated unions ------------------------------------------------------


Operation = Annotated[
    Union[
        BoxOperation,
        CylinderOperation,
        ConeOperation,
        SphereOperation,
        TorusOperation,
        PolygonPrismOperation,
        UnionOperation,
        CutOperation,
        IntersectOperation,
        PartOperation,
    ],
    Field(discriminator="type"),
]

# Anything that can appear inside a composition or as a part build target.
# `part` is deliberately excluded: features attach to exactly one solid, and
# nesting feature nodes inside boolean trees would be ambiguous.
BuildOperation = Annotated[
    Union[
        BoxOperation,
        CylinderOperation,
        ConeOperation,
        SphereOperation,
        TorusOperation,
        PolygonPrismOperation,
        UnionOperation,
        CutOperation,
        IntersectOperation,
    ],
    Field(discriminator="type"),
]


class CADSpec(BaseModel):
    """Top-level validated CAD specification, schema v3.1."""

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


for _model in (
    UnionOperation,
    CutOperation,
    IntersectOperation,
    PartOperation,
    CADSpec,
):
    _model.model_rebuild()


def operation_depth(op: BaseModel) -> int:
    """Nesting depth of an operation tree; a lone primitive has depth 1.

    Compositions (union/cut/intersect) and the part node each add 1;
    a part node's depth continues through its build subtree.
    """
    if isinstance(op, (UnionOperation, CutOperation, IntersectOperation)):
        return 1 + max(operation_depth(op.base), operation_depth(op.tool))
    if isinstance(op, PartOperation):
        return 1 + operation_depth(op.build)
    return 1


def operation_node_count(op: BaseModel) -> int:
    """Total number of operation nodes in the tree (features not counted)."""
    if isinstance(op, (UnionOperation, CutOperation, IntersectOperation)):
        return 1 + operation_node_count(op.base) + operation_node_count(op.tool)
    if isinstance(op, PartOperation):
        return 1 + operation_node_count(op.build)
    return 1


def feature_summary(op: BaseModel) -> list[str]:
    """Engine application order for a part node's features (display/logging).

    Mirrors cadquery_engine._apply_features: holes and hole patterns ->
    shell -> chamfer -> fillet. Keep in sync with the engine.
    """
    if not isinstance(op, PartOperation):
        return []
    by_order = {"hole": 0, "hole_pattern": 0, "shell": 1, "chamfer": 2, "fillet": 3}
    return sorted(
        (f.type for f in op.features),
        key=lambda t: by_order.get(t, 99),
    )
