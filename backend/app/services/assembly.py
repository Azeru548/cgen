"""Deterministic assembly operations (Milestone 9). No LLM in this module.

Add / remove / update / export an assembly. Geometry comes from the
component registry; files go through the existing FileStore.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from ..cad import assembly as assembly_schema
from ..cad import cadquery_engine
from ..cad import registry
from ..cad.assembly import (
    AssemblyGroup,
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
from .byteship import ArtifactStore, ArtifactUrls, LocalArtifactStore
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
    exported: dict,
    stem: str,
    file_store: FileStore,
    request_id: str,
    artifacts: ArtifactStore | None = None,
) -> dict[str, GeneratedFile]:
    step_final = _rename_to_stem(Path(exported["step_path"]), stem, "step")
    stl_final = _rename_to_stem(Path(exported["stl_path"]), stem, "stl")
    cadquery_engine.validate_exported_files(step_final, stl_final)
    store: ArtifactStore = artifacts or LocalArtifactStore(file_store)
    urls: ArtifactUrls = store.store_pair(
        step_path=step_final, stl_path=stl_final, stem=stem, request_id=request_id
    )
    return {
        "step": GeneratedFile(
            format="step",
            filename=step_final.name,
            bytes=step_final.stat().st_size,
            download_url=urls.step,
        ),
        "stl": GeneratedFile(
            format="stl",
            filename=stl_final.name,
            bytes=stl_final.stat().st_size,
            download_url=urls.stl,
        ),
    }


def _build_local_solid(component: ComponentInstance):
    return registry.build_component(
        component.component_type,
        component.parameters,
        generated_spec=component.generated,
    )


def geometry_signature(component: ComponentInstance) -> str:
    """Fingerprint of the solid itself — pose, name, lock, and groups do not count.

    Parameters are coerced through the registry so `10` and `10.0` (and filled
    defaults) match the document the exporter actually builds.
    """
    try:
        params = registry.validate_parameters(
            component.component_type, component.parameters
        )
    except ValueError:
        params = component.parameters
    generated = (
        component.generated.model_dump() if component.generated is not None else None
    )
    payload = {
        "type": component.component_type,
        "parameters": params,
        "generated": generated,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def parse_file_pair(raw: object) -> dict[str, GeneratedFile] | None:
    if not isinstance(raw, dict):
        return None
    step = raw.get("step")
    stl = raw.get("stl")
    if not isinstance(step, dict) or not isinstance(stl, dict):
        return None
    try:
        return {
            "step": GeneratedFile(
                format="step",
                filename=str(step["filename"]),
                bytes=int(step["bytes"]),
                download_url=str(step["download_url"]),
            ),
            "stl": GeneratedFile(
                format="stl",
                filename=str(stl["filename"]),
                bytes=int(stl["bytes"]),
                download_url=str(stl["download_url"]),
            ),
        }
    except (KeyError, TypeError, ValueError):
        return None


def parse_component_files(
    raw: object,
) -> dict[str, dict[str, GeneratedFile]]:
    if not isinstance(raw, dict):
        return {}
    parsed: dict[str, dict[str, GeneratedFile]] = {}
    for cid, pair in raw.items():
        if not isinstance(cid, str):
            continue
        files = parse_file_pair(pair)
        if files is not None:
            parsed[cid] = files
    return parsed


def reusable_ids(
    previous: list[ComponentInstance],
    current: list[ComponentInstance],
    available_files: dict[str, dict[str, GeneratedFile]],
) -> set[str]:
    """Component ids whose local solid (and therefore STL) can be kept."""
    prior = {component.id: component for component in previous}
    keep: set[str] = set()
    for component in current:
        old = prior.get(component.id)
        if old is None or component.id not in available_files:
            continue
        if geometry_signature(old) == geometry_signature(component):
            keep.add(component.id)
    return keep


def export_assembly_document(
    assembly: AssemblySpec,
    *,
    request_id: str,
    file_store: FileStore,
    artifacts: ArtifactStore | None = None,
    previous_components: list[ComponentInstance] | None = None,
    reuse_component_files: dict[str, dict[str, GeneratedFile]] | None = None,
    reuse_combined_files: dict[str, GeneratedFile] | None = None,
) -> GenerationResult:
    """Build changed components; reuse unchanged per-object files.

    Pose, visibility, name, lock, and grouping never invalidate a component
    STL — the viewer applies world transforms on the existing mesh — so those
    edits are free and also keep the combined files.

    The combined STEP/STL is rebuilt whenever at least one solid changed
    (parameter edit, add, remove). Reusing it there would hand the user a
    download with the old geometry, and STEP is the authoritative artifact.
    """
    started = time.monotonic()
    validated = resolve_relationships(validate_registry(assembly))
    stem = sanitize_name(validated.name, fallback="assembly")
    reuse_files = reuse_component_files or {}
    keep = reusable_ids(
        previous_components or [], validated.components, reuse_files
    )

    logger.info(
        "assembly_export_started request_id=%s components=%d reuse=%d",
        request_id,
        len(validated.components),
        len(keep),
    )

    component_files: dict[str, dict[str, GeneratedFile]] = {}
    cad_started = time.monotonic()
    rebuilt = 0
    # Locals already built for the components that changed, reused by the
    # combined pass below instead of building them twice.
    built_locals: dict[str, object] = {}

    for component in validated.components:
        if component.id in keep:
            component_files[component.id] = reuse_files[component.id]
            continue
        rebuilt += 1
        local = _build_local_solid(component)
        built_locals[component.id] = local
        local_export = cadquery_engine._export_solid(
            local, f"{stem}_{component.id}", out_dir=None
        )
        component_files[component.id] = _files_from_export(
            local_export,
            f"{stem}_{component.id}",
            file_store,
            request_id,
            artifacts,
        )

    # A changed solid invalidates the combined download; a pose-only edit does
    # not (the world transforms live in the spec, not in the component meshes).
    rebuild_combined = reuse_combined_files is None or rebuilt > 0
    if rebuild_combined:
        world_solids = []
        for component in validated.components:
            local = built_locals.get(component.id)
            if local is None:
                local = _build_local_solid(component)
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
        files = _files_from_export(combined, stem, file_store, request_id, artifacts)
    else:
        files = reuse_combined_files

    cad_ms = int((time.monotonic() - cad_started) * 1000)
    total_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "assembly_export_completed request_id=%s rebuilt=%d cad_ms=%d total_ms=%d",
        request_id,
        rebuilt,
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


def _reuse_context(
    current: CADSpec | AssemblySpec | None,
    component_files: object = None,
    files: object = None,
) -> tuple[
    list[ComponentInstance] | None,
    dict[str, dict[str, GeneratedFile]] | None,
    dict[str, GeneratedFile] | None,
]:
    """Previous solids + file URLs so an edit can skip rebuilding them."""
    if current is None:
        return None, None, None
    prior = list(as_assembly(current).components)
    reused = parse_component_files(component_files)
    if not reused and isinstance(current, CADSpec):
        pair = parse_file_pair(files)
        if pair is not None:
            reused = {prior[0].id: pair}
    combined = parse_file_pair(files)
    return prior, (reused or None), combined


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
    artifacts: ArtifactStore | None = None,
    component_files: object = None,
    files: object = None,
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
        groups: list[AssemblyGroup] = []
    else:
        current_assembly = as_assembly(current)
        existing = {c.id for c in current_assembly.components}
        assembly_name = current_assembly.name
        prior = list(current_assembly.components)
        groups = list(current_assembly.groups)

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
        schema_version=assembly_schema.ASSEMBLY_SCHEMA_VERSION,
        components=prior + [added],
        groups=groups,
    )
    previous, reuse_files, reuse_combined = _reuse_context(
        current, component_files, files
    )
    return _export(
        next_spec,
        request_id=request_id,
        file_store=file_store,
        artifacts=artifacts,
        previous_components=previous,
        reuse_component_files=reuse_files,
        reuse_combined_files=reuse_combined,
    )


def _export(
    spec: AssemblySpec,
    *,
    request_id: str,
    file_store: FileStore,
    artifacts: ArtifactStore | None,
    previous_components: list[ComponentInstance] | None = None,
    reuse_component_files: dict[str, dict[str, GeneratedFile]] | None = None,
    reuse_combined_files: dict[str, GeneratedFile] | None = None,
):
    """Call the exporter, passing `artifacts` only when one is configured.

    Keeping the default call shape identical means existing callers and stubs
    of `export_assembly_document` continue to work unchanged.
    """
    kwargs: dict = {
        "request_id": request_id,
        "file_store": file_store,
    }
    if artifacts is not None:
        kwargs["artifacts"] = artifacts
    # Only forward reuse when the client actually sent prior files. Extra
    # kwargs would TypeError test doubles that still use the original
    # export_assembly_document signature.
    if reuse_component_files:
        kwargs["previous_components"] = previous_components or []
        kwargs["reuse_component_files"] = reuse_component_files
    if reuse_combined_files is not None:
        kwargs["reuse_combined_files"] = reuse_combined_files
    return export_assembly_document(spec, **kwargs)


def remove_component(
    current: CADSpec | AssemblySpec,
    component_id: str,
    *,
    request_id: str,
    file_store: FileStore,
    artifacts: ArtifactStore | None = None,
    component_files: object = None,
    files: object = None,
) -> GenerationResult:
    assembly = as_assembly(current)
    remaining = [c for c in assembly.components if c.id != component_id]
    if len(remaining) == len(assembly.components):
        raise ValueError(f"No component with id '{component_id}' in this assembly.")
    if not remaining:
        raise ValueError("Cannot remove the last object. Clear the viewer instead.")
    remaining_ids = {c.id for c in remaining}
    next_spec = assembly.model_copy(
        update={
            "components": remaining,
            "groups": _prune_groups(assembly.groups, remaining_ids),
        }
    )
    previous, reuse_files, reuse_combined = _reuse_context(
        current, component_files, files
    )
    return _export(
        next_spec,
        request_id=request_id,
        file_store=file_store,
        artifacts=artifacts,
        previous_components=previous,
        reuse_component_files=reuse_files,
        reuse_combined_files=reuse_combined,
    )


def _prune_groups(
    groups: list[AssemblyGroup], remaining_ids: set[str]
) -> list[AssemblyGroup]:
    """Drop missing members; a group with fewer than two members disappears."""
    pruned: list[AssemblyGroup] = []
    for group in groups:
        members = [member for member in group.component_ids if member in remaining_ids]
        if len(members) < 2:
            continue
        pruned.append(group.model_copy(update={"component_ids": members}))
    return pruned


def update_component(
    current: CADSpec | AssemblySpec,
    component_id: str,
    *,
    parameters: dict[str, ParamValue] | None,
    transform: Transform | None,
    visible: bool | None,
    name: str | None,
    instances: list[Transform] | None,
    locked: bool | None = None,
    request_id: str,
    file_store: FileStore,
    artifacts: ArtifactStore | None = None,
    component_files: object = None,
    files: object = None,
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
                    "locked": component.locked if locked is None else locked,
                }
            )
        )
    if not found:
        raise ValueError(f"No component with id '{component_id}' in this assembly.")
    next_spec = assembly.model_copy(update={"components": updated})
    previous, reuse_files, reuse_combined = _reuse_context(
        current, component_files, files
    )
    return _export(
        next_spec,
        request_id=request_id,
        file_store=file_store,
        artifacts=artifacts,
        previous_components=previous,
        reuse_component_files=reuse_files,
        reuse_combined_files=reuse_combined,
    )


def rebuild_assembly(
    base: CADSpec | AssemblySpec,
    updated: CADSpec | AssemblySpec,
    *,
    request_id: str,
    file_store: FileStore,
    artifacts: ArtifactStore | None = None,
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
            # Identical nested parts are a no-op, not a rejection — grouping
            # and locking only touch assembly metadata.
            if old_c.generated.model_dump() != new_c.generated.model_dump():
                validate_rebuild(old_c.generated, new_c.generated)
    if old_a.model_dump() == new_a.model_dump():
        raise ModificationRejectedError("No changes detected in the assembly.")
    return _export(
        new_a, request_id=request_id, file_store=file_store, artifacts=artifacts
    )


def _shift_transform(pose: Transform, delta: tuple[float, float, float]) -> Transform:
    x, y, z = pose.position
    dx, dy, dz = delta
    return pose.model_copy(update={"position": (x + dx, y + dy, z + dz)})


def _rekey_assembly(
    incoming: AssemblySpec,
    taken_ids: set[str],
    taken_group_ids: set[str],
    offset: tuple[float, float, float],
) -> tuple[list[ComponentInstance], list[AssemblyGroup]]:
    """Copy an assembly beside an existing one: unique ids, no host links."""
    mapping: dict[str, str] = {}
    used = set(taken_ids)
    for component in incoming.components:
        new_id = allocate_component_id(used, component.component_type)
        mapping[component.id] = new_id
        used.add(new_id)
    added: list[ComponentInstance] = []
    for component in incoming.components:
        relationships = [
            rel.model_copy(update={"target_id": mapping[rel.target_id]})
            for rel in component.relationships
            if rel.target_id in mapping
        ]
        added.append(
            component.model_copy(
                update={
                    "id": mapping[component.id],
                    "transform": _shift_transform(component.transform, offset),
                    "instances": [
                        _shift_transform(pose, offset) for pose in component.instances
                    ],
                    "relationships": relationships,
                }
            )
        )
    groups: list[AssemblyGroup] = []
    used_groups = set(taken_group_ids)
    for group in incoming.groups:
        members = [mapping[member] for member in group.component_ids if member in mapping]
        if len(members) < 2:
            continue
        new_gid = allocate_component_id(used_groups, "group")
        used_groups.add(new_gid)
        groups.append(
            group.model_copy(update={"id": new_gid, "component_ids": members})
        )
    return added, groups


def attach_document(
    current: CADSpec | AssemblySpec,
    incoming: CADSpec | AssemblySpec,
    *,
    request_id: str,
    file_store: FileStore,
    artifacts: ArtifactStore | None = None,
) -> GenerationResult:
    """Place a newly generated document beside the current scene.

    The new objects keep their internal relationships and get a deterministic
    offset so they do not stack on the existing parts. Nothing is mated to
    the host — that is the unselected Generate path.
    """
    host = as_assembly(current)
    if len(host.components) >= assembly_schema.MAX_COMPONENTS:
        raise ValueError(
            f"Assembly already has {assembly_schema.MAX_COMPONENTS} components."
        )
    offset_pose = manual_placement_transform(
        len(host.components), "box", {"width": 40, "depth": 40, "height": 10}
    )
    taken = {c.id for c in host.components}
    taken_groups = {g.id for g in host.groups}
    if isinstance(incoming, CADSpec):
        new_id = allocate_component_id(taken, "generated_part")
        added = [
            ComponentInstance(
                id=new_id,
                component_type="generated_part",
                name=incoming.name,
                generated=incoming,
                transform=offset_pose,
            )
        ]
        extra_groups: list[AssemblyGroup] = []
    else:
        added, extra_groups = _rekey_assembly(
            incoming, taken, taken_groups, offset_pose.position
        )
    if len(host.components) + len(added) > assembly_schema.MAX_COMPONENTS:
        raise ValueError(
            f"Adding {len(added)} objects would exceed "
            f"{assembly_schema.MAX_COMPONENTS} components."
        )
    if len(host.groups) + len(extra_groups) > assembly_schema.MAX_GROUPS:
        extra_groups = extra_groups[: max(0, assembly_schema.MAX_GROUPS - len(host.groups))]
    next_spec = host.model_copy(
        update={
            "components": list(host.components) + added,
            "groups": list(host.groups) + extra_groups,
            "schema_version": assembly_schema.ASSEMBLY_SCHEMA_VERSION,
        }
    )
    return _export(
        next_spec, request_id=request_id, file_store=file_store, artifacts=artifacts
    )
