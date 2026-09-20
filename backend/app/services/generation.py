"""Generation orchestration (M4): prompt -> spec -> CAD -> validated files.

Single place where the M4 pipeline lives:

  prompt validation (4xxInvalidPromptError)
    -> Groq structured spec (errors propagate for HTTP mapping in main.py)
    -> deterministic CadQuery export (box reuses the Milestone 1 exporter)
    -> export validation (STEP magic, STL structure)
    -> sanitized filenames + token registration in the FileStore

Emits structured log events (generation_started, ai_spec_generated,
cad_generation_started, cad_generation_completed, file_export_completed,
generation_failed). Never logs secrets, full prompts (truncated to
MAX_PROMPT_LOG_CHARS), or raw CAD objects.

AI output stays DATA: validated Pydantic models flow into the engine;
nothing is ever exec()'d or eval()'d.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import json

from ..ai import groq_client
from ..cad import cadquery_engine
from ..cad.schema import BoxOperation, CADSpec
from .file_store import FileStore
from .names import default_name_for, sanitize_name

logger = logging.getLogger("cgen.generation")

MAX_PROMPT_LENGTH = 2000
MAX_PROMPT_LOG_CHARS = 120


class InvalidPromptError(ValueError):
    """User request rejected before any AI/CAD work (maps to HTTP 400)."""


@dataclass
class GeneratedFile:
    format: str
    filename: str
    bytes: int
    download_url: str


@dataclass
class GenerationResult:
    request_id: str
    specification: dict
    units: str
    files: dict[str, GeneratedFile] = field(default_factory=dict)
    generation_time_ms: int = 0


def _rename_to_stem(path: Path, stem: str, ext: str) -> Path:
    """Rename an exported temp file to the sanitized public filename.

    Same-directory rename only; `stem` is pre-sanitized so the target is
    always a plain `<stem>.<ext>` filename in the same temp dir.
    """
    target = path.parent / f"{stem}.{ext}"
    if path.name == target.name:
        return path
    try:
        # Same-directory temp space: a stale same-name file can only come
        # from a previous export into this directory, so replacing it is safe.
        target.unlink(missing_ok=True)
        return path.rename(target)
    except Exception as e:
        raise RuntimeError(f"Could not finalize {ext.upper()} file: {e}") from e


def run_generation(
    prompt: object,
    *,
    request_id: str,
    file_store: FileStore,
) -> GenerationResult:
    """Execute one generation and return the frontend-friendly result.

    Raises InvalidPromptError (400), GroqConfigError (500),
    AIGenerationError (502), SpecValidationError (422), ValueError (422),
    RuntimeError (500). Every failure is logged with the request_id first.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise InvalidPromptError("prompt must not be empty.")
    if len(prompt) > MAX_PROMPT_LENGTH:
        raise InvalidPromptError(
            f"prompt is too long (max {MAX_PROMPT_LENGTH} characters)."
        )

    logger.info(
        "generation_started request_id=%s prompt_len=%d prompt_prefix=%r",
        request_id,
        len(prompt),
        prompt.strip()[:MAX_PROMPT_LOG_CHARS],
    )
    started = time.monotonic()

    try:
        ai_started = time.monotonic()
        spec = groq_client.parse_prompt_to_spec(prompt.strip())
        ai_ms = int((time.monotonic() - ai_started) * 1000)
        stem = sanitize_name(spec.name, fallback=spec.operation.type)
        if stem == "rectangular_block" and spec.operation.type != "box":
            # The model occasionally echoes the example name; fall back to a
            # name derived from the actual operation instead.
            stem = default_name_for(spec.operation.type)
        logger.info(
            "ai_spec_generated request_id=%s stem=%s operation=%s ai_ms=%d",
            request_id,
            stem,
            spec.operation.type,
            ai_ms,
        )

        logger.info(
            "cad_generation_started request_id=%s operation=%s",
            request_id,
            spec.operation.type,
        )
        cad_started = time.monotonic()
        op = spec.operation
        if isinstance(op, BoxOperation):
            exported = cadquery_engine.export_box(
                width=op.width, depth=op.depth, height=op.height
            )
        else:
            exported = cadquery_engine.export_operation(op, name=stem)
        cad_ms = int((time.monotonic() - cad_started) * 1000)

        step_final = _rename_to_stem(Path(exported["step_path"]), stem, "step")
        stl_final = _rename_to_stem(Path(exported["stl_path"]), stem, "stl")

        checks = cadquery_engine.validate_exported_files(step_final, stl_final)
        logger.info(
            "file_export_completed request_id=%s step_bytes=%d stl_bytes=%d checks=%s",
            request_id,
            step_final.stat().st_size,
            stl_final.stat().st_size,
            ",".join(sorted(checks)),
        )

        token = file_store.put(
            step_path=str(step_final), stl_path=str(stl_final), stem=stem
        )
        files = {
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
        total_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "cad_generation_completed request_id=%s cad_ms=%d total_ms=%d",
            request_id,
            cad_ms,
            total_ms,
        )
        return GenerationResult(
            request_id=request_id,
            specification=spec.model_dump(),
            units=spec.units,
            files=files,
            generation_time_ms=total_ms,
        )
    except Exception as e:
        # Sanitized detail only: every message raised in this pipeline is
        # constructed without keys, paths, or tracebacks.
        logger.warning("generation_failed request_id=%s error=%s", request_id, e)
        raise


# ---------------------------------------------------------------------------
# Modification pipeline (M7)
# ---------------------------------------------------------------------------

MAX_INSTRUCTION_LENGTH = 2000


class InvalidModificationError(ValueError):
    """Modification request rejected before any AI/CAD work (maps to HTTP 400)."""


class ModificationRejectedError(ValueError):
    """Diff guard rejected the modification as unrelated to the instruction."""


def _structure_signature(op: object) -> object:
    """Numeric-agnostic skeleton of an operation tree.

    Same node types in the same shape (plus polygon side count, which is
    topological) produce equal signatures. Numeric dimensions, booleans
    (e.g. cylinder `through`), and blind-hole depths are tunable parameters
    and are deliberately excluded. Part features are excluded here — they
    are checked separately by _feature_type_counts so that adding a new
    feature is allowed while removing/replacing one is not.
    """
    node_type = getattr(op, "type", None)
    if node_type in ("union", "cut", "intersect"):
        return (
            node_type,
            _structure_signature(op.base),
            _structure_signature(op.tool),
        )
    if node_type == "part":
        return (node_type, _structure_signature(op.build))
    if node_type == "polygon_prism":
        return (node_type, op.sides)
    return (node_type,)


def _skeletons_compatible(old_op: object, new_op: object) -> bool:
    """True when the new tree keeps the old skeleton.

    Identical skeletons are compatible. The single exception is promotion
    of a bare solid to a part node with the SAME build geometry (e.g.
    box -> part(box + hole)), which is how a first feature gets added to
    a featureless solid. Every other shape change — top-level type swap,
    build-tree rebuild, primitive swap — is a redesign, not a modification.
    """
    old_sig = _structure_signature(old_op)
    new_sig = _structure_signature(new_op)
    if old_sig == new_sig:
        return True
    if getattr(old_op, "type", None) != "part" and getattr(new_op, "type", None) == "part":
        return _structure_signature(old_op) == _structure_signature(new_op.build)
    return False


def _feature_type_counts(op: object) -> dict[str, int]:
    """Multiset of feature types on an operation (empty for non-part ops)."""
    from collections import Counter

    feats = getattr(op, "features", None)
    if not feats:
        return dict(Counter())
    return dict(Counter(f.type for f in feats))


def _diff_specs(old: CADSpec, new: CADSpec) -> dict[str, bool]:
    """Structural comparison of two CADSpecs.

    Returns a dict of changed field categories:
    - "constants": document_type or units changed (always rejected)
    - "name": part name changed
    - "operation_structure": operation skeleton changed, i.e. a redesign
      such as box -> cylinder, part -> union, or a build-tree rebuild
      (always rejected, except bare-solid -> part promotion with the
      same build geometry)
    - "operation_dimensions": numeric values changed within same structure
    - "features": feature multiset changed (added/removed/replaced)
    """
    changes: dict[str, bool] = {
        "constants": False,
        "name": False,
        "operation_structure": False,
        "operation_dimensions": False,
        "features": False,
    }

    if old.document_type != new.document_type or old.units != new.units:
        changes["constants"] = True

    if old.name != new.name:
        changes["name"] = True

    if not _skeletons_compatible(old.operation, new.operation):
        changes["operation_structure"] = True

    old_json = json.dumps(old.model_dump(), sort_keys=True)
    new_json = json.dumps(new.model_dump(), sort_keys=True)
    if old_json != new_json and not changes["operation_structure"]:
        changes["operation_dimensions"] = True

    if _feature_type_counts(old.operation) != _feature_type_counts(new.operation):
        changes["features"] = True

    return changes


def validate_modification(old: CADSpec, new: CADSpec, instruction: str) -> None:
    """Diff guard: reject modifications that change unrelated fields.

    Allowed: numeric parameter retunes within the same operation skeleton
    (dimensions, diameters, counts, depths, thicknesses) and ADDING new
    features to a part. Rejected: constants drift, unexpected renames,
    operation-skeleton redesigns (e.g. part -> union, box -> cylinder,
    swapping a build primitive for an unrelated one such as a sphere),
    and REMOVING or REPLACING existing features (e.g. dropping a hole).

    Raises ModificationRejectedError if the modification is suspicious.
    Deterministic, no LLM involved.
    """
    changes = _diff_specs(old, new)

    if changes["constants"]:
        raise ModificationRejectedError(
            "Modification changed document_type or units, which must remain constant."
        )

    instruction_lower = instruction.lower().strip()
    name_change_requested = any(
        kw in instruction_lower
        for kw in ["rename", "name it", "call it", "new name"]
    )
    if changes["name"] and not name_change_requested:
        raise ModificationRejectedError(
            "Modification changed the part name without an explicit rename request."
        )

    if changes["operation_structure"]:
        raise ModificationRejectedError(
            "Modification changes the operation structure (redesign). "
            "Only dimension/feature parameter changes within the same "
            "shape are allowed; generate a new part for a different design."
        )

    old_counts = _feature_type_counts(old.operation)
    new_counts = _feature_type_counts(new.operation)
    for ftype, needed in old_counts.items():
        if new_counts.get(ftype, 0) < needed:
            raise ModificationRejectedError(
                f"Modification removes or replaces the existing '{ftype}' "
                f"feature. Existing features must be kept; only their "
                f"parameters may change."
            )

    something_changed = any(changes.values())
    if not something_changed:
        raise ModificationRejectedError(
            "No changes detected in the specification."
        )


def run_modification(
    current_spec: dict,
    instruction: str,
    *,
    request_id: str,
    file_store: FileStore,
) -> GenerationResult:
    """Modify an existing spec, regenerate CAD, and return the result.

    Raises InvalidModificationError (400), GroqConfigError (500),
    AIGenerationError (502), SpecValidationError (422),
    ModificationRejectedError (422), ValueError (422), RuntimeError (500).
    """
    if not isinstance(instruction, str) or not instruction.strip():
        raise InvalidModificationError("instruction must not be empty.")
    if len(instruction) > MAX_INSTRUCTION_LENGTH:
        raise InvalidModificationError(
            f"instruction is too long (max {MAX_INSTRUCTION_LENGTH} characters)."
        )

    old_spec = CADSpec.model_validate(current_spec)

    logger.info(
        "modification_started request_id=%s instruction_len=%d",
        request_id,
        len(instruction),
    )
    started = time.monotonic()

    try:
        ai_started = time.monotonic()
        new_spec = groq_client.modify_spec(
            json.dumps(current_spec, separators=(",", ":")),
            instruction.strip(),
        )
        ai_ms = int((time.monotonic() - ai_started) * 1000)

        validate_modification(old_spec, new_spec, instruction)
        logger.info(
            "ai_modification_completed request_id=%s ai_ms=%d",
            request_id,
            ai_ms,
        )

        stem = sanitize_name(new_spec.name, fallback=new_spec.operation.type)
        if stem == "rectangular_block" and new_spec.operation.type != "box":
            stem = default_name_for(new_spec.operation.type)

        logger.info(
            "cad_generation_started request_id=%s operation=%s",
            request_id,
            new_spec.operation.type,
        )
        cad_started = time.monotonic()
        op = new_spec.operation
        if isinstance(op, BoxOperation):
            exported = cadquery_engine.export_box(
                width=op.width, depth=op.depth, height=op.height
            )
        else:
            exported = cadquery_engine.export_operation(op, name=stem)
        cad_ms = int((time.monotonic() - cad_started) * 1000)

        step_final = _rename_to_stem(Path(exported["step_path"]), stem, "step")
        stl_final = _rename_to_stem(Path(exported["stl_path"]), stem, "stl")

        checks = cadquery_engine.validate_exported_files(step_final, stl_final)
        logger.info(
            "file_export_completed request_id=%s step_bytes=%d stl_bytes=%d checks=%s",
            request_id,
            step_final.stat().st_size,
            stl_final.stat().st_size,
            ",".join(sorted(checks)),
        )

        token = file_store.put(
            step_path=str(step_final), stl_path=str(stl_final), stem=stem
        )
        files = {
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
        total_ms = int((time.monotonic() - started) * 1000)
        logger.info(
            "modification_completed request_id=%s cad_ms=%d total_ms=%d",
            request_id,
            cad_ms,
            total_ms,
        )
        return GenerationResult(
            request_id=request_id,
            specification=new_spec.model_dump(),
            units=new_spec.units,
            files=files,
            generation_time_ms=total_ms,
        )
    except Exception as e:
        logger.warning("modification_failed request_id=%s error=%s", request_id, e)
        raise
