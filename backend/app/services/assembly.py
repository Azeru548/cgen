"""Deterministic assembly operations (Milestone 9). No LLM in this module.

Add / remove / update / export an assembly. Geometry comes from the
component registry; files go through the existing FileStore.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from ..cad import assembly as assembly_schema
from ..cad import cadquery_engine
from ..cad import registry
from ..cad.assembly import (
    AssemblySpec,
    ComponentInstance,
    Transform,
    allocate_component_id,
    as_assembly,
    instance_poses,
    resolve_relationships,
    validate_registry,
)
from ..cad.schema import CADSpec
from .file_store import FileStore
from .generation import GeneratedFile, GenerationResult, _rename_to_stem
from .names import sanitize_name

logger = logging.getLogger("cgen.assembly")

ParamValue = float | int | bool | str


def parse_document(payload: object) -> CADSpec | AssemblySpec:
    """Validate a stored specification as 3d_part or 3d_assembly."""
    if not isinstance(payload, dict):
        raise ValueError("specification must be a JSON object.")
    doc_type = payload.get("document_type")
    if doc_type == "3d_assembly":
        return validate_registry(AssemblySpec.model_validate(payload))
    return CADSpec.model_validate(payload)


def _files_from_export(
    exported: dict, stem: str, file_store: FileStore
) -> dict[str, GeneratedFile]:
    step_final = _rename_to_stem(Path(exported["step_path"]), stem, "step")
    stl_final = _rename_to_stem(Path(exported["stl_path"]), stem, "stl")
    cadquery_engine.validate_exported_files(step_final, stl_final)
    token = file_store.put(
        step_path=str(step_final), stl_path=str(stl_final), stem=stem
    )
    return {
        "step": GeneratedFile(
            format="step",
            filename=step_final.name,
            bytes=step_final.stat().st_size,
            download_url=f"/download/{token}?format=step",
        ),
        "stl": GeneratedFile(
            format="stl",
            filename=stl_final.name,
            bytes=stl_final.stat().st_size,
            download_url=f"/download/{token}?format=stl",
        ),
    }


def _build_local_solid(component: ComponentInstance):
    return registry.build_component(
        component.component_type,
        component.parameters,
        generated_spec=component.generated,
    )


def export_assembly_document(
    assembly: AssemblySpec,
    *,
    request_id: str,
    file_store: FileStore,
) -> GenerationResult:
    """Build every component, export per-object + compound files."""
    started = time.monotonic()
    validated = resolve_relationships(validate_registry(assembly))
    stem = sanitize_name(validated.name, fallback="assembly")

    logger.info(
        "assembly_export_started request_id=%s components=%d",
        request_id,
        len(validated.components),
    )

    world_solids = []
    component_files: dict[str, dict[str, GeneratedFile]] = {}
    cad_started = time.monotonic()

    for component in validated.components:
        local = _build_local_solid(component)
        local_export = cadquery_engine._export_solid(
            local, f"{stem}_{component.id}", out_dir=None
        )
        component_files[component.id] = _files_from_export(
            local_export, f"{stem}_{component.id}", file_store
        )
        for pose in instance_poses(component):
            if not component.visible:
                continue
            world_solids.append(
                cadquery_engine.apply_transform(
                    local, pose.position, pose.rotation
                )
            )

    if not world_solids:
        raise ValueError(
            "Nothing to export — every component is hidden. Show at least one object."
        )

    combined = cadquery_engine.export_solids(world_solids, stem)
    files = _files_from_export(combined, stem, file_store)
    cad_ms = int((time.monotonic() - cad_started) * 1000)
    total_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "assembly_export_completed request_id=%s cad_ms=%d total_ms=%d",
        request_id,
        cad_ms,
        total_ms,
    )
    return GenerationResult(
        request_id=request_id,
        specification=validated.model_dump(),
        units=validated.units,
        files=files,
        generation_time_ms=total_ms,
        component_files=component_files,
    )


def default_grid_instances(count: int, pitch: float = 16.0) -> list[Transform]:
    """Centered rectangular instance poses for a repeated component."""
    if count < 1:
        raise ValueError("count must be at least 1")
    if count == 1:
        return []
    if count > assembly_schema.MAX_INSTANCES:
        raise ValueError(
            f"count {count} exceeds max {assembly_schema.MAX_INSTANCES} instances"
        )
    cols = math_ceil_sqrt(count)
    rows = (count + cols - 1) // cols
    poses: list[Transform] = []
    n = 0
    for r in range(rows):
        for c in range(cols):
            if n >= count:
                break
            x = (c - (cols - 1) / 2) * pitch
            y = (r - (rows - 1) / 2) * pitch
            poses.append(Transform(position=(x, y, 0.0)))
            n += 1
    return poses


def math_ceil_sqrt(n: int) -> int:
    v = 1
    while v * v < n:
        v += 1
    return v


def manual_placement_transform(
    existing_components: int, component_type: str, parameters: dict[str, ParamValue]
) -> Transform:
    """Deterministic, non-overlapping default pose for a manual library add.

    The M9 library inserted at the origin, so every manually added part landed
    on top of the previous one. This places a new part in the first free slot
    of a simple deterministic lattice, so repeated adds of the same type march
    outward instead of stacking. Takes the current component count rather than
    an AssemblySpec because an empty assembly is not a valid document.
    """
    slot = existing_components
    spacing = _placement_spacing(component_type, parameters)
    columns = 4
    col = slot % columns
    row = slot // columns
    x = (col - (columns - 1) / 2) * spacing
    y = (row - 0.5) * spacing
    return Transform(position=(x, y, 0.0))


def _placement_spacing(component_type: str, parameters: dict[str, ParamValue]) -> float:
    """Slot pitch wide enough for this part's footprint, with clearance."""
    extent = 40.0
    try:
        definition = registry.get(component_type)
        params = registry.validate_parameters(component_type, parameters)
    except ValueError:
        return extent + 10.0
    keys = {p.key for p in definition.parameters}
    if {"width", "depth"} <= keys:
        try:
            width = registry._f(params, "width")
            depth = registry._f(params, "depth")
            extent = max(width, depth)
        except ValueError:
            extent = 40.0
    elif {"diameter"} <= keys:
        try:
            extent = registry._f(params, "diameter")
        except ValueError:
            extent = 40.0
    if component_type in registry.BOARDS:
        profile = registry.BOARDS[component_type]
        extent = max(profile.width, profile.depth)
    return extent + 10.0


def add_component(
    current: CADSpec | AssemblySpec | None,
    component_type: str,
    *,
    parameters: dict[str, ParamValue] | None,
    transform: Transform | None,
    count: int,
    name: str | None,
    request_id: str,
    file_store: FileStore,
) -> GenerationResult:
    definition = registry.get(component_type)
    if not definition.insertable:
        raise ValueError(
            f"component '{component_type}' cannot be inserted from the library"
        )
    params = registry.validate_parameters(component_type, parameters)
    if current is None:
        existing: set[str] = set()
        assembly_name = definition.display_name.lower().replace(" ", "_")
        prior: list[ComponentInstance] = []
    else:
        current_assembly = as_assembly(current)
        existing = {c.id for c in current_assembly.components}
        assembly_name = current_assembly.name
        prior = list(current_assembly.components)

    new_id = allocate_component_id(existing, component_type)
    display = name.strip() if isinstance(name, str) and name.strip() else definition.display_name
    instances = default_grid_instances(count) if count > 1 else []
    pose = (
        transform
        if transform is not None
        else manual_placement_transform(len(prior), component_type, params)
    )
    added = ComponentInstance(
        id=new_id,
        component_type=component_type,
        name=display,
        parameters=params,
        transform=pose,
        instances=instances,
    )
    next_spec = AssemblySpec(
        name=assembly_name,
        components=prior + [added],
    )
    return export_assembly_document(
        next_spec, request_id=request_id, file_store=file_store
    )


def remove_component(
    current: CADSpec | AssemblySpec,
    component_id: str,
    *,
    request_id: str,
    file_store: FileStore,
) -> GenerationResult:
    assembly = as_assembly(current)
    remaining = [c for c in assembly.components if c.id != component_id]
    if len(remaining) == len(assembly.components):
        raise ValueError(f"No component with id '{component_id}' in this assembly.")
    if not remaining:
        raise ValueError("Cannot remove the last object. Clear the viewer instead.")
    next_spec = assembly.model_copy(update={"components": remaining})
    return export_assembly_document(
        next_spec, request_id=request_id, file_store=file_store
    )


def update_component(
    current: CADSpec | AssemblySpec,
    component_id: str,
    *,
    parameters: dict[str, ParamValue] | None,
    transform: Transform | None,
    visible: bool | None,
    name: str | None,
    instances: list[Transform] | None,
    request_id: str,
    file_store: FileStore,
) -> GenerationResult:
    assembly = as_assembly(current)
    found = False
    updated: list[ComponentInstance] = []
    for component in assembly.components:
        if component.id != component_id:
            updated.append(component)
            continue
        found = True
        params = component.parameters
        if parameters is not None:
            params = registry.validate_parameters(component.component_type, parameters)
        new_name = component.name
        if isinstance(name, str) and name.strip():
            new_name = name.strip()
        updated.append(
            component.model_copy(
                update={
                    "parameters": params,
                    "transform": transform if transform is not None else component.transform,
                    "visible": component.visible if visible is None else visible,
                    "name": new_name,
                    "instances": instances if instances is not None else component.instances,
                }
            )
        )
    if not found:
        raise ValueError(f"No component with id '{component_id}' in this assembly.")
    next_spec = assembly.model_copy(update={"components": updated})
    return export_assembly_document(
        next_spec, request_id=request_id, file_store=file_store
    )


def rebuild_assembly(
    base: CADSpec | AssemblySpec,
    updated: CADSpec | AssemblySpec,
    *,
    request_id: str,
    file_store: FileStore,
) -> GenerationResult:
    """Numeric/transform retune of an existing assembly. No add/remove/type swap."""
    old_a = as_assembly(base)
    new_a = validate_registry(as_assembly(updated))
    old_ids = [c.id for c in old_a.components]
    new_ids = [c.id for c in new_a.components]
    from .generation import ModificationRejectedError, validate_rebuild

    if old_ids != new_ids:
        raise ModificationRejectedError(
            "Assembly rebuild cannot add, remove, or reorder components. "
            "Use the component library or a new generation for that."
        )
    for old_c, new_c in zip(old_a.components, new_a.components, strict=True):
        if old_c.component_type != new_c.component_type:
            raise ModificationRejectedError(
                f"Assembly rebuild cannot change component '{old_c.id}' "
                f"from {old_c.component_type} to {new_c.component_type}."
            )
        if (old_c.generated is None) != (new_c.generated is None):
            raise ModificationRejectedError(
                f"Assembly rebuild cannot attach or detach generated geometry "
                f"on '{old_c.id}'."
            )
        if old_c.generated is not None and new_c.generated is not None:
            validate_rebuild(old_c.generated, new_c.generated)
    if old_a.model_dump() == new_a.model_dump():
        raise ModificationRejectedError("No changes detected in the assembly.")
    return export_assembly_document(
        new_a, request_id=request_id, file_store=file_store
    )
