"""Milestone 1 PoC: FastAPI + CadQuery on Render Free.
Milestone 2: + POST /generate (Groq prompt -> validated CADSpec -> box export).
Milestone 3: + multi-operation CAD (box/cylinder/cone/sphere/union/cut).
Milestone 4: + production-grade generation API (clean contract, file store,
  request IDs, timing, structured logging).

Endpoints (Milestone 1, unchanged):
  GET /health    -> liveness, reports whether CadQuery imports OK
  GET /test/cad  -> create 100x60x30mm box, export STEP+STL, return metadata
  GET /test/cad/download?format=step|stl -> generate box and return the file

Milestone 4:
  POST /generate      -> prompt -> Groq -> CADSpec -> CAD engine -> files
  GET /download/{token} -> download a generated STEP/STL pair by token

No auth, no DB. Ephemeral disk only.
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .ai import groq_client
from .services.file_store import FileStore
from .services.generation import InvalidPromptError, run_generation

logger = logging.getLogger("cgen.api")

app = FastAPI(title="cgen PoC — FastAPI + CadQuery", version="0.4.0")

# Re-exported for backwards compatibility (tests import it from here).
from .services.generation import MAX_PROMPT_LENGTH  # noqa: E402

# Token -> generated STEP/STL pairs for /generate downloads. Ephemeral and
# single-process by design; entries expire and are count-capped (see
# services/file_store.py). No database, no object storage in this milestone.
file_store = FileStore()


class GenerateRequest(BaseModel):
    prompt: str = Field(
        description="Natural-language description of the 3D part to generate. "
        "1-2000 characters; dimensions in any common unit (normalized to mm)."
    )


class FileMetadata(BaseModel):
    format: Literal["step", "stl"] = Field(description="CAD file format.")
    filename: str = Field(description="Sanitized public filename, e.g. shaft.step.")
    bytes: int = Field(description="File size in bytes.")
    download_url: str = Field(description="Relative URL to download this file.")


class GenerateResponse(BaseModel):
    status: Literal["completed"] = Field(description="Always 'completed' on success.")
    request_id: str = Field(description="Random ID for this request; see server logs.")
    specification: dict = Field(description="Validated CAD specification (schema v2.0).")
    units: str = Field(description="Length unit used throughout: mm.")
    generation_time_ms: int = Field(description="Total backend generation time.")
    files: dict[str, FileMetadata] = Field(
        description="Generated files keyed by 'step' and 'stl'."
    )


@app.get("/health")
def health():
    try:
        import cadquery as cq

        cq_version: str | None = cq.__version__
        cq_ok = True
    except Exception as e:  # pragma: no cover - environment dependent
        cq_version = None
        cq_ok = False
        cq_error = str(e)
    else:
        cq_error = None

    return {
        "status": "ok",
        "service": "cgen-poc",
        "cadquery_available": cq_ok,
        "cadquery_version": cq_version,
        "cadquery_error": cq_error,
    }


@app.get("/test/cad")
def test_cad(
    width: float = Query(100.0, gt=0, le=1000),
    depth: float = Query(60.0, gt=0, le=1000),
    height: float = Query(30.0, gt=0, le=1000),
):
    """Create box, export STEP + STL to temp dir, return file metadata.

    Files live on ephemeral disk (Render Free) — caller should download
    immediately via /test/cad/download. This endpoint proves generation
    works and that exports are non-empty.
    """
    from .cad.cadquery_engine import export_box

    try:
        result = export_box(width=width, depth=depth, height=height)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        # Distinguish CAD/export errors from generic 500s for the operator
        raise HTTPException(status_code=500, detail=str(e))

    step = Path(result["step_path"])
    stl = Path(result["stl_path"])

    # Validate: files exist, non-empty, magic bytes look right
    checks = {
        "step_exists": step.exists(),
        "stl_exists": stl.exists(),
        "step_non_empty": step.stat().st_size > 0 if step.exists() else False,
        "stl_non_empty": stl.stat().st_size > 0 if stl.exists() else False,
    }
    # STEP files are ASCII starting with "ISO-10303-21;"
    try:
        with step.open("rb") as f:
            head = f.read(64)
        checks["step_magic_ok"] = b"ISO-10303" in head
    except Exception:
        checks["step_magic_ok"] = False
    # Binary STL starts with 80-byte header; ASCII STL starts with "solid"
    try:
        with stl.open("rb") as f:
            head = f.read(6)
        checks["stl_magic_ok"] = head.startswith(b"solid") or len(head) == 6
    except Exception:
        checks["stl_magic_ok"] = False

    if not all(checks.values()):
        raise HTTPException(
            status_code=500,
            detail=f"CAD export validation failed: {checks}",
        )

    return {
        "status": "completed",
        "operation": "box",
        "units": "mm",
        "dimensions": {"width": width, "depth": depth, "height": height},
        "files": {
            "step_bytes": result["step_bytes"],
            "stl_bytes": result["stl_bytes"],
            "step_path": result["step_path"],
            "stl_path": result["stl_path"],
        },
        "validation": checks,
        "cadquery_version": result["cadquery_version"],
        "download": {
            "step": f"/test/cad/download?format=step&width={width}&depth={depth}&height={height}",
            "stl": f"/test/cad/download?format=stl&width={width}&depth={depth}&height={height}",
        },
    }


@app.get("/test/cad/download")
def test_cad_download(
    format: str = Query("step", pattern="^(step|stl)$"),
    width: float = Query(100.0, gt=0, le=1000),
    depth: float = Query(60.0, gt=0, le=1000),
    height: float = Query(30.0, gt=0, le=1000),
):
    """Generate box on the fly and stream the requested file back."""
    from .cad.cadquery_engine import make_box

    try:
        import cadquery as cq
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"CadQuery unavailable: {e}")

    try:
        solid = make_box(width=width, depth=depth, height=height)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    tmpdir = Path(tempfile.mkdtemp(prefix="cgen_dl_"))
    if format == "step":
        path = tmpdir / "box.step"
        media_type = "application/step"
    else:
        path = tmpdir / "box.stl"
        media_type = "model/stl"

    try:
        cq.exporters.export(solid, str(path))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{format.upper()} export failed: {e}")

    return FileResponse(str(path), media_type=media_type, filename=path.name)


@app.post(
    "/generate",
    response_model=GenerateResponse,
    responses={
        400: {"description": "Invalid request: empty or oversized prompt."},
        422: {"description": "AI specification failed CAD validation."},
        500: {"description": "Server misconfiguration or CAD generation failure."},
        502: {"description": "Groq API failure (auth, model, rate limit, network)."},
    },
)
def generate(body: GenerateRequest):
    """Generate a 3D part from a natural-language prompt.

    Pipeline: prompt -> Groq structured CAD spec -> Pydantic validation ->
    deterministic CadQuery engine -> validated STEP/STL + download tokens.
    Groq never produces executable code; only validated data reaches CAD.
    """
    request_id = uuid.uuid4().hex
    try:
        result = run_generation(
            body.prompt, request_id=request_id, file_store=file_store
        )
    except InvalidPromptError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except groq_client.GroqConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except groq_client.AIGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except groq_client.SpecValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return GenerateResponse(
        status="completed",
        request_id=result.request_id,
        specification=result.specification,
        units=result.units,
        generation_time_ms=result.generation_time_ms,
        files={
            key: FileMetadata(
                format=meta.format,
                filename=meta.filename,
                bytes=meta.bytes,
                download_url=meta.download_url,
            )
            for key, meta in result.files.items()
        },
    )


@app.get(
    "/download/{token}",
    responses={
        400: {"description": "Unsupported format (only 'step' or 'stl')."},
        404: {"description": "Unknown/expired token or missing file."},
    },
)
def download_generated(token: str, format: str = Query("step")):
    """Download a STEP/STL file produced by a /generate request.

    `token` is an opaque lookup key only — it is never interpreted as a
    filesystem path, so traversal and arbitrary-file access are impossible.
    """
    token_tag = (token[:8] + "...") if isinstance(token, str) and token else "?"
    if format not in ("step", "stl"):
        logger.warning("download_failed token=%s reason=bad_format", token_tag)
        raise HTTPException(
            status_code=400,
            detail="Unsupported format. Use 'step' or 'stl'.",
        )
    path = file_store.resolve(token, format)
    if path is None:
        logger.warning("download_failed token=%s reason=unknown_token", token_tag)
        raise HTTPException(
            status_code=404,
            detail="Download link expired or unknown. Re-run /generate.",
        )
    filename = file_store.filename_for(token, format) or f"part.{format}"
    logger.info("download_requested token=%s format=%s", token_tag, format)
    media_type = "application/step" if format == "step" else "model/stl"
    return FileResponse(str(path), media_type=media_type, filename=filename)
