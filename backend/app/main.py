"""Milestone 1 PoC: FastAPI + CadQuery on Render Free.
Milestone 2: + POST /generate (Groq prompt -> validated CADSpec -> box export).
Milestone 3: + multi-operation CAD (box/cylinder/cone/sphere/union/cut).
Milestone 4: + production-grade generation API (clean contract, file store,
  request IDs, timing, structured logging).
Milestone 6: + schema v3.0 (torus, polygon_prism, intersect, part features:
  hole/fillet/chamfer/shell) with unchanged API contracts.
  Schema v3.1 adds the hole_pattern feature (bolt-circle holes); contracts unchanged.
  Schema v3.2 adds the hole_grid feature (rectangular/linear hole arrays);
  contracts unchanged.
Milestone 7: + POST /modify (natural-language modification of existing specs
  with structural diff guard).

Endpoints (Milestone 1, unchanged):
  GET /health    -> liveness, reports whether CadQuery imports OK
  GET /test/cad  -> create 100x60x30mm box, export STEP+STL, return metadata
  GET /test/cad/download?format=step|stl -> generate box and return the file

Milestone 4:
  POST /generate      -> prompt -> Groq -> CADSpec -> CAD engine -> files
  GET /download/{token} -> download a generated STEP/STL pair by token

Milestone 7:
  POST /modify        -> spec + instruction -> Groq -> diff guard -> CAD -> files

Milestone 8.1:
  POST /rebuild       -> base + edited spec -> numeric guard -> CAD -> files
  (no AI on this path; topology changes rejected)

No auth, no DB. Ephemeral disk only.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .ai import groq_client
from .services.byteship import (
    CONTENT_TYPES,
    ArtifactNotFoundError,
    ArtifactStorageError,
    ByteshipArtifactStore,
    default_artifact_store,
)
from .services.file_store import FileStore
from .services.generation import (
    InvalidModificationError,
    InvalidPromptError,
    ModificationRejectedError,
    run_generation,
    run_modification,
    run_rebuild,
)

logger = logging.getLogger("cgen.api")

app = FastAPI(title="cgen PoC — FastAPI + CadQuery", version="0.9.0")


def _cors_origins() -> list[str]:
    """Allowed browser origins, comma-separated in CORS_ORIGINS.

    Default covers local Next.js dev. Production frontend origin(s) must be
    set via the CORS_ORIGINS env var (runtime setting — no rebuild needed).
    Wildcards are never used: the browser sends credentials nowhere here,
    but an explicit allowlist keeps the API surface intentional.
    """
    raw = os.environ.get("CORS_ORIGINS", "http://localhost:3000")
    return [o.strip() for o in raw.split(",") if o.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
    max_age=600,
)

# Re-exported for backwards compatibility (tests import it from here).
from .services.generation import MAX_PROMPT_LENGTH  # noqa: E402

# Token -> generated STEP/STL pairs for /download when no remote artifact
# store is configured. Ephemeral and single-process by design (see
# services/file_store.py).
file_store = FileStore()

# Artifact delivery backend (M10.2). Byteship when BYTESHIP_API_KEY is set,
# otherwise the local FileStore above, so the app never fails to start
# because an optional deployment dependency is absent.
artifact_store = default_artifact_store(file_store)


class GenerateRequest(BaseModel):
    prompt: str = Field(
        description="Natural-language description of the 3D part to generate. "
        "1-2000 characters; dimensions in any common unit (normalized to mm)."
    )


class ModifyRequest(BaseModel):
    specification: dict = Field(
        description="Current valid CAD specification (from a previous /generate or /modify response)."
    )
    instruction: str = Field(
        description="Natural-language modification instruction. 1-2000 characters."
    )


class FileMetadata(BaseModel):
    format: Literal["step", "stl"] = Field(description="CAD file format.")
    filename: str = Field(description="Sanitized public filename, e.g. shaft.step.")
    bytes: int = Field(description="File size in bytes.")
    download_url: str = Field(description="Relative URL to download this file.")


class GenerateResponse(BaseModel):
    status: Literal["completed"] = Field(description="Always 'completed' on success.")
    request_id: str = Field(description="Random ID for this request; see server logs.")
    specification: dict = Field(
        description="Validated CAD specification (schema v3.2 part or v4.0 assembly)."
    )
    units: str = Field(description="Length unit used throughout: mm.")
    generation_time_ms: int = Field(description="Total backend generation time.")
    files: dict[str, FileMetadata] = Field(
        description="Generated files keyed by 'step' and 'stl' (combined assembly export)."
    )
    component_files: dict[str, dict[str, FileMetadata]] | None = Field(
        default=None,
        description="Per-component STEP/STL for assemblies, keyed by component id.",
    )


def _to_file_meta(meta) -> FileMetadata:
    return FileMetadata(
        format=meta.format,
        filename=meta.filename,
        bytes=meta.bytes,
        download_url=meta.download_url,
    )


def _to_generate_response(result) -> GenerateResponse:
    component_files = None
    if result.component_files:
        component_files = {
            cid: {fmt: _to_file_meta(meta) for fmt, meta in files.items()}
            for cid, files in result.component_files.items()
        }
    return GenerateResponse(
        status="completed",
        request_id=result.request_id,
        specification=result.specification,
        units=result.units,
        generation_time_ms=result.generation_time_ms,
        files={key: _to_file_meta(meta) for key, meta in result.files.items()},
        component_files=component_files,
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
            body.prompt, request_id=request_id, file_store=file_store, artifacts=artifact_store
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

    return _to_generate_response(result)


@app.post(
    "/modify",
    response_model=GenerateResponse,
    responses={
        400: {"description": "Invalid request: empty instruction or invalid specification."},
        422: {"description": "Modification rejected by diff guard or CAD validation failed."},
        500: {"description": "Server misconfiguration or CAD generation failure."},
        502: {"description": "Groq API failure (auth, model, rate limit, network)."},
    },
)
def modify(body: ModifyRequest):
    """Modify an existing part based on a natural-language instruction.

    Pipeline: spec + instruction -> Groq modification -> diff guard ->
    deterministic CadQuery engine -> validated STEP/STL + download tokens.
    The diff guard rejects modifications that change unrelated fields.
    """
    request_id = uuid.uuid4().hex
    try:
        result = run_modification(
            body.specification,
            body.instruction,
            request_id=request_id,
            file_store=file_store,
            artifacts=artifact_store,
        )
    except InvalidModificationError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except groq_client.GroqConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except groq_client.AIGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except groq_client.SpecValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except groq_client.SpecModificationError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except ModificationRejectedError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return _to_generate_response(result)


class RebuildRequest(BaseModel):
    base_specification: dict = Field(
        description="Current valid CAD specification (the parametric base)."
    )
    specification: dict = Field(
        description="Edited CAD specification: numeric values only, same structure."
    )


@app.post(
    "/rebuild",
    response_model=GenerateResponse,
    responses={
        400: {"description": "Invalid request: malformed specifications."},
        422: {
            "description": "Rebuild rejected: structural/topology change or "
            "CAD validation failed."
        },
        500: {"description": "CAD generation failure."},
    },
)
def rebuild(body: RebuildRequest):
    """Rebuild CAD from a numerically edited spec. No AI on this path.

    Pipeline: base + edited spec -> structural guard (numeric-only) ->
    deterministic CadQuery engine -> validated STEP/STL + download tokens.
    Groq is never called; topology changes are rejected with 422.
    """
    request_id = uuid.uuid4().hex
    try:
        result = run_rebuild(
            body.base_specification,
            body.specification,
            request_id=request_id,
            file_store=file_store,
            artifacts=artifact_store,
        )
    except ModificationRejectedError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return _to_generate_response(result)


class AssemblyAddRequest(BaseModel):
    specification: dict | None = Field(
        default=None,
        description="Current 3d_part or 3d_assembly spec; omit for an empty workspace.",
    )
    component_type: str = Field(description="Registry component type, e.g. m3_screw.")
    parameters: dict | None = Field(
        default=None, description="Optional parameter overrides."
    )
    transform: dict | None = Field(
        default=None, description="Optional {position:[x,y,z], rotation:[rx,ry,rz]}."
    )
    count: int = Field(default=1, ge=1, le=12, description="Repeated instances.")
    name: str | None = Field(default=None, description="Optional display name.")


class AssemblyRemoveRequest(BaseModel):
    specification: dict
    component_id: str


class AssemblyUpdateRequest(BaseModel):
    specification: dict
    component_id: str
    parameters: dict | None = None
    transform: dict | None = None
    visible: bool | None = None
    name: str | None = None
    instances: list[dict] | None = None


def _parse_transform(raw: dict | None):
    from .cad.assembly import Transform

    if raw is None:
        return None
    return Transform.model_validate(raw)


def _parse_instances(raw: list[dict] | None):
    from .cad.assembly import Transform

    if raw is None:
        return None
    return [Transform.model_validate(item) for item in raw]


def _parse_current_spec(payload: dict | None):
    from .services.assembly import parse_document

    if payload is None:
        return None
    return parse_document(payload)


@app.get("/components")
def list_components():
    """Deterministic component catalog. No AI, no CAD."""
    from .cad import registry
    from .cad.assembly import ASSEMBLY_SCHEMA_VERSION

    return {
        "schema_version": ASSEMBLY_SCHEMA_VERSION,
        "components": registry.public_catalog(),
    }


@app.post(
    "/assembly/add",
    response_model=GenerateResponse,
    responses={
        400: {"description": "Invalid request."},
        422: {"description": "Unknown component, bad parameters, or CAD validation."},
        500: {"description": "CAD generation failure."},
    },
)
def assembly_add(body: AssemblyAddRequest):
    """Insert a registry component without calling the LLM."""
    from .services import assembly as assembly_svc

    request_id = uuid.uuid4().hex
    try:
        current = _parse_current_spec(body.specification)
        result = assembly_svc.add_component(
            current,
            body.component_type,
            parameters=body.parameters,
            transform=_parse_transform(body.transform),
            count=body.count,
            name=body.name,
            request_id=request_id,
            file_store=file_store,
            artifacts=artifact_store,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return _to_generate_response(result)


@app.post(
    "/assembly/remove",
    response_model=GenerateResponse,
    responses={
        400: {"description": "Invalid request."},
        422: {"description": "Unknown component or last-object removal."},
        500: {"description": "CAD generation failure."},
    },
)
def assembly_remove(body: AssemblyRemoveRequest):
    """Remove one object from an assembly. No AI."""
    from .services import assembly as assembly_svc

    request_id = uuid.uuid4().hex
    try:
        current = _parse_current_spec(body.specification)
        if current is None:
            raise ValueError("specification is required.")
        result = assembly_svc.remove_component(
            current,
            body.component_id,
            request_id=request_id,
            file_store=file_store,
            artifacts=artifact_store,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return _to_generate_response(result)


@app.post(
    "/assembly/update",
    response_model=GenerateResponse,
    responses={
        400: {"description": "Invalid request."},
        422: {"description": "Unknown component or invalid parameters."},
        500: {"description": "CAD generation failure."},
    },
)
def assembly_update(body: AssemblyUpdateRequest):
    """Update one component's parameters, pose, visibility, or name. No AI."""
    from .services import assembly as assembly_svc

    request_id = uuid.uuid4().hex
    try:
        current = _parse_current_spec(body.specification)
        if current is None:
            raise ValueError("specification is required.")
        result = assembly_svc.update_component(
            current,
            body.component_id,
            parameters=body.parameters,
            transform=_parse_transform(body.transform),
            visible=body.visible,
            name=body.name,
            instances=_parse_instances(body.instances),
            request_id=request_id,
            file_store=file_store,
            artifacts=artifact_store,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return _to_generate_response(result)


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


@app.get(
    "/artifacts/{request_id}/{filename}",
    responses={
        400: {"description": "Unsupported artifact format."},
        404: {"description": "No such artifact in storage."},
        502: {"description": "Artifact storage unreachable."},
    },
)
def get_artifact(request_id: str, filename: str):
    """Serve a stored STEP/STL artifact (M10.2).

    `download_url` points here so the browser fetches CAD bytes same-origin.
    The viewer needs the STL bytes to build the WebGL mesh, and the Byteship
    CDN sends no CORS headers, so a direct CDN URL cannot be fetched by the
    page. Byteship remains the system of record; the key never leaves here.
    """
    store = artifact_store
    if not isinstance(store, ByteshipArtifactStore):
        raise HTTPException(
            status_code=404,
            detail="Remote artifact storage is not configured.",
        )
    try:
        data = store.fetch(request_id, filename)
    except ArtifactNotFoundError as e:
        logger.warning(
            "artifact_fetch_failed request_id=%s reason=unknown_artifact", request_id
        )
        raise HTTPException(status_code=404, detail=str(e))
    except ArtifactStorageError as e:
        logger.error("artifact_fetch_failed request_id=%s", request_id)
        raise HTTPException(status_code=502, detail=str(e))
    extension = filename.rpartition(".")[2]
    media_type = CONTENT_TYPES.get(extension, "application/octet-stream")
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{_public_name(filename)}"'},
    )


def _public_name(filename: str) -> str:
    """Filename for the Content-Disposition header: no quotes, no slashes."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
    return cleaned[:120] or "artifact"
