"""Assembly / scene specification (Milestone 9, schema 4.0).

Additive over CADSpec 3.2: a workspace may still be a single `3d_part`.
An assembly is a named list of independently identifiable components.
Components stay logically separate — they are not boolean-unioned.

The LLM may propose an assembly plan (types, parameters, approximate
placement, relationships). Deterministic code validates the plan against
the component registry, resolves relationships, and builds geometry.
"""

from __future__ import annotations

import math
import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .schema import CADSpec, MAX_DIMENSION_MM, MAX_NAME_LENGTH

ASSEMBLY_SCHEMA_VERSION = "4.0"

MAX_COMPONENTS = 24
MAX_INSTANCES = 12
MAX_RELATIONSHIPS = 8
MAX_COMPONENT_ID_LENGTH = 40

COMPONENT_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

RelationshipType = Literal[
    "positioned_at",
    "attached_to",
    "aligned_with",
    "repeated_from",
    "mounted_on",
    "centered_on",
]

ParamValue = Union[float, int, bool, str]


class Transform(BaseModel):
    """World pose of a component. Rotation is XYZ Euler degrees."""

    model_config = ConfigDict(extra="forbid")

    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)

    @field_validator("position")
    @classmethod
    def position_in_range(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        for axis, coord in zip(("x", "y", "z"), value, strict=True):
            if not math.isfinite(coord):
                raise ValueError(f"transform position {axis} must be finite")
            if abs(coord) > MAX_DIMENSION_MM:
                raise ValueError(
                    f"transform position {axis} is out of range "
                    f"(|{coord}| > {MAX_DIMENSION_MM})"
                )
        return value

    @field_validator("rotation")
    @classmethod
    def rotation_in_range(cls, value: tuple[float, float, float]) -> tuple[float, float, float]:
        for axis, coord in zip(("x", "y", "z"), value, strict=True):
            if not math.isfinite(coord):
                raise ValueError(f"transform rotation {axis} must be finite")
            if abs(coord) > 360.0:
                raise ValueError(
                    f"transform rotation {axis} must be between -360 and 360 degrees"
                )
        return value


class Relationship(BaseModel):
    """Lightweight placement hint. Resolved deterministically; not a solver."""

    model_config = ConfigDict(extra="forbid")

    type: RelationshipType
    target_id: str = Field(min_length=1, max_length=MAX_COMPONENT_ID_LENGTH)

    @field_validator("target_id")
    @classmethod
    def target_id_shape(cls, value: str) -> str:
        cleaned = value.strip()
        if not COMPONENT_ID_RE.match(cleaned):
            raise ValueError(
                "relationship target_id must be a lowercase slug "
                "(letter, then letters/digits/underscores)"
            )
        return cleaned


class ComponentInstance(BaseModel):
    """One reusable component placed in an assembly.

    `instances` is the repetition list: one definition, N world poses.
    An empty list means a single instance at `transform`.
    `generated` is only valid when component_type is `generated_part`.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=MAX_COMPONENT_ID_LENGTH)
    component_type: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    parameters: dict[str, ParamValue] = Field(default_factory=dict)
    transform: Transform = Field(default_factory=Transform)
    visible: bool = True
    instances: list[Transform] = Field(default_factory=list, max_length=MAX_INSTANCES)
    relationships: list[Relationship] = Field(
        default_factory=list, max_length=MAX_RELATIONSHIPS
    )
    generated: CADSpec | None = None

    @field_validator("id")
    @classmethod
    def id_shape(cls, value: str) -> str:
        cleaned = value.strip()
        if not COMPONENT_ID_RE.match(cleaned):
            raise ValueError(
                "component id must be a lowercase slug "
                "(letter, then letters/digits/underscores, max 40)"
            )
        return cleaned

    @field_validator("component_type")
    @classmethod
    def type_shape(cls, value: str) -> str:
        cleaned = value.strip()
        if not COMPONENT_ID_RE.match(cleaned):
            raise ValueError(
                "component_type must be a known registry slug "
                "(lowercase letters, digits, underscores)"
            )
        return cleaned

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("component name must not be blank")
        return cleaned

    @model_validator(mode="after")
    def generated_only_for_generated_part(self) -> "ComponentInstance":
        if self.component_type == "generated_part":
            if self.generated is None:
                raise ValueError(
                    "generated_part components need a nested 3d_part specification"
                )
        elif self.generated is not None:
            raise ValueError(
                f"component '{self.id}' of type '{self.component_type}' "
                "must not carry a nested generated specification"
            )
        return self


class AssemblySpec(BaseModel):
    """Top-level validated assembly specification, schema 4.0."""

    model_config = ConfigDict(extra="forbid")

    document_type: Literal["3d_assembly"] = "3d_assembly"
    units: Literal["mm"] = "mm"
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    schema_version: Literal["4.0"] = "4.0"
    components: list[ComponentInstance] = Field(min_length=1, max_length=MAX_COMPONENTS)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned

    @model_validator(mode="after")
    def unique_ids_and_valid_relationships(self) -> "AssemblySpec":
        ids = [c.id for c in self.components]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(
                "duplicate component id(s): " + ", ".join(sorted(dupes))
            )
        known = set(ids)
        for component in self.components:
            for rel in component.relationships:
                if rel.target_id not in known:
                    raise ValueError(
                        f"component '{component.id}' relationship {rel.type} "
                        f"references missing component '{rel.target_id}'"
                    )
                if rel.target_id == component.id:
                    raise ValueError(
                        f"component '{component.id}' cannot reference itself"
                    )
            if len(component.instances) > MAX_INSTANCES:
                raise ValueError(
                    f"component '{component.id}' has too many instances "
                    f"({len(component.instances)} > {MAX_INSTANCES})"
                )
        return self


def instance_poses(component: ComponentInstance) -> list[Transform]:
    """World poses to draw: explicit instances, or the single transform."""
    if component.instances:
        return list(component.instances)
    return [component.transform]


def empty_assembly(name: str = "assembly") -> AssemblySpec:
    """Placeholder used only after the first component is added."""
    raise RuntimeError("empty assemblies are not valid; add a component first")


def allocate_component_id(existing: set[str], type_key: str) -> str:
    """Deterministic `{type}-{n}` id that does not collide with `existing`."""
    slug = type_key.strip().lower()
    if not COMPONENT_ID_RE.match(slug):
        slug = "part"
    n = 1
    while True:
        candidate = f"{slug}_{n}"
        if candidate not in existing:
            return candidate
        n += 1
        if n > 10_000:
            raise ValueError("could not allocate a unique component id")


DocumentSpec = Annotated[Union[CADSpec, AssemblySpec], Field(discriminator="document_type")]


def _rotate_point(
    point: tuple[float, float, float], rotation: tuple[float, float, float]
) -> tuple[float, float, float]:
    """XYZ Euler degrees, matching CadQuery `apply_transform`."""
    x, y, z = point
    rx, ry, rz = (math.radians(a) for a in rotation)
    # X
    if rx:
        cy, cz = math.cos(rx), math.sin(rx)
        y, z = y * cy - z * cz, y * cz + z * cy
    # Y
    if ry:
        cx, cz = math.cos(ry), math.sin(ry)
        x, z = x * cx + z * cz, -x * cz + z * cx
    # Z
    if rz:
        cx, cy = math.cos(rz), math.sin(rz)
        x, y = x * cx - y * cy, x * cy + y * cx
    return (x, y, z)


def transform_point(
    point: tuple[float, float, float], pose: Transform
) -> tuple[float, float, float]:
    rx, ry, rz = _rotate_point(point, pose.rotation)
    px, py, pz = pose.position
    return (rx + px, ry + py, rz + pz)


def validate_registry(assembly: AssemblySpec) -> AssemblySpec:
    """Reject unknown types and coerce parameters against the registry.

    Returns a copy with parameters filled/normalized. Relationship targets
    were already checked by AssemblySpec.
    """
    from . import registry

    normalized: list[ComponentInstance] = []
    for component in assembly.components:
        registry.get(component.component_type)
        params = registry.validate_parameters(
            component.component_type, component.parameters
        )
        normalized.append(component.model_copy(update={"parameters": params}))
    return assembly.model_copy(update={"components": normalized})


def resolve_relationships(assembly: AssemblySpec) -> AssemblySpec:
    """Apply lightweight placement relationships in document order.

    mounted_on / repeated_from → instance poses at the target's mounting
    points (one definition, N instances). centered_on copies XY from the
    target. attached_to / aligned_with copy XY and keep the source Z.
    positioned_at is a no-op (the explicit transform is the placement).
    """
    from . import registry

    by_id = {c.id: c for c in assembly.components}
    resolved: list[ComponentInstance] = []
    for component in assembly.components:
        current = component
        for rel in component.relationships:
            target = by_id[rel.target_id]
            if rel.type in ("mounted_on", "repeated_from"):
                local = registry.mounting_points_local(
                    target.component_type, target.parameters
                )
                if not local:
                    raise ValueError(
                        f"component '{component.id}' cannot {rel.type} "
                        f"'{target.id}': that component has no mounting points"
                    )
                poses = [
                    Transform(position=transform_point(p, target.transform))
                    for p in local
                ]
                if len(poses) > MAX_INSTANCES:
                    raise ValueError(
                        f"component '{component.id}' would produce "
                        f"{len(poses)} instances (max {MAX_INSTANCES})"
                    )
                current = current.model_copy(update={"instances": poses})
            elif rel.type == "centered_on":
                tx, ty, tz = target.transform.position
                _sx, _sy, sz = current.transform.position
                current = current.model_copy(
                    update={
                        "transform": Transform(
                            position=(tx, ty, sz),
                            rotation=current.transform.rotation,
                        )
                    }
                )
            elif rel.type in ("attached_to", "aligned_with"):
                tx, ty, _tz = target.transform.position
                _sx, _sy, sz = current.transform.position
                current = current.model_copy(
                    update={
                        "transform": Transform(
                            position=(tx, ty, sz),
                            rotation=current.transform.rotation,
                        )
                    }
                )
            elif rel.type == "positioned_at":
                current = current.model_copy(
                    update={"transform": target.transform.model_copy()}
                )
        resolved.append(current)
        by_id[current.id] = current
    return assembly.model_copy(update={"components": resolved})


def promote_part(spec: CADSpec, component_id: str = "generated_1") -> AssemblySpec:
    """Wrap a 3d_part CADSpec as a one-object assembly (additive promotion)."""
    return AssemblySpec(
        document_type="3d_assembly",
        units="mm",
        name=spec.name,
        schema_version="4.0",
        components=[
            ComponentInstance(
                id=component_id,
                component_type="generated_part",
                name=spec.name,
                parameters={},
                generated=spec,
            )
        ],
    )


def as_assembly(document: CADSpec | AssemblySpec) -> AssemblySpec:
    if isinstance(document, AssemblySpec):
        return document
    return promote_part(document)
