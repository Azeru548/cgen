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

from ..ai import groq_client
from ..cad import cadquery_engine
from ..cad.schema import BoxOperation
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
