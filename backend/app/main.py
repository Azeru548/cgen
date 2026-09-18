"""Milestone 1 PoC: FastAPI + CadQuery on Render Free.
Milestone 2: + POST /generate (Groq prompt -> validated CADSpec -> box export).

Endpoints (Milestone 1, unchanged):
  GET /health    -> liveness, reports whether CadQuery imports OK
  GET /test/cad  -> create 100x60x30mm box, export STEP+STL, return metadata
  GET /test/cad/download?format=step|stl -> generate box and return the file

Milestone 2:
  POST /generate -> natural-language prompt -> Groq -> CADSpec -> box export

No auth, no DB. Only proves: FastAPI -> CadQuery -> export -> download,
plus prompt -> Groq -> validated spec -> same box exporter.
"""

from __future__ import annotations

import secrets
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .ai import groq_client
from .cad import cadquery_engine
from .cad.schema import BoxOperation

app = FastAPI(title="cgen PoC — FastAPI + CadQuery", version="0.3.0")

# Prompt guardrails: empty prompts are user errors (400); very long prompts
# are rejected before spending an AI call on them.
MAX_PROMPT_LENGTH = 2000


class GenerateRequest(BaseModel):
    prompt: str


class GenerateResponse(BaseModel):
    status: str
    specification: dict
    units: str
    files: dict
    download: dict


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


@app.post("/generate", response_model=GenerateResponse)
def generate(body: GenerateRequest):
    """Milestone 3: prompt -> Groq -> CADSpec validation -> CAD engine.

    Box specs reuse the Milestone 1/2 box exporter (identical behavior and
    download links); every other operation goes through the general
    operation exporter with token-based downloads.
    """
    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt must not be empty.")
    if len(body.prompt) > MAX_PROMPT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"prompt is too long (max {MAX_PROMPT_LENGTH} characters).",
        )

    try:
        spec = groq_client.parse_prompt_to_spec(prompt)
    except groq_client.GroqConfigError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except groq_client.AIGenerationError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except groq_client.SpecValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    op = spec.operation
    if isinstance(op, BoxOperation):
        try:
            result = cadquery_engine.export_box(
                width=op.width, depth=op.depth, height=op.height
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
        dims = f"width={op.width}&depth={op.depth}&height={op.height}"
        download = {
            "step": f"/test/cad/download?format=step&{dims}",
            "stl": f"/test/cad/download?format=stl&{dims}",
        }
    else:
        try:
            result = cadquery_engine.export_operation(op, name=spec.name)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=500, detail=str(e))
        token = secrets.token_urlsafe(16)
        _GENERATED_FILES[token] = {
            "step": result["step_path"],
            "stl": result["stl_path"],
        }
        while len(_GENERATED_FILES) > MAX_STORED_GENERATIONS:
            _GENERATED_FILES.pop(next(iter(_GENERATED_FILES)))
        download = {
            "step": f"/download/{token}?format=step",
            "stl": f"/download/{token}?format=stl",
        }

    return {
        "status": "completed",
        "specification": spec.model_dump(),
        "units": spec.units,
        "files": {
            "step_bytes": result["step_bytes"],
            "stl_bytes": result["stl_bytes"],
        },
        "download": download,
    }


# Token -> {"step": path, "stl": path} for non-box /generate downloads.
# Ephemeral (Render Free disk) and single-process by design for this milestone;
# entries are reaped by count and die with the instance.
_GENERATED_FILES: dict[str, dict[str, str]] = {}
MAX_STORED_GENERATIONS = 200


@app.get("/download/{token}")
def download_generated(
    token: str,
    format: str = Query("step", pattern="^(step|stl)$"),
):
    """Download a STEP/STL file produced by a non-box /generate request."""
    entry = _GENERATED_FILES.get(token)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="Download link expired or unknown. Re-run /generate.",
        )
    path = Path(entry.get(format, ""))
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Generated file no longer available. Re-run /generate.",
        )
    media_type = "application/step" if format == "step" else "model/stl"
    return FileResponse(str(path), media_type=media_type, filename=f"{token}.{format}")
