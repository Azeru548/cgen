"""Deterministic CadQuery engine (Milestone 3).

The engine receives already-validated Pydantic data (cad/schema.py) and
builds geometry from it. It NEVER receives or executes raw AI output:
no exec(), no eval().

Geometry conventions (all units millimeters, origin at world 0,0,0):
  box      : width (X) x depth (Y) x height (Z), centered on the origin.
  cylinder : circular cross-section of `radius` in the XY plane, axis along Z,
             spanning z in [-height/2, +height/2] (centered on the origin).
  cone     : frustum along Z, `bottom_radius` at z=-height/2,
             `top_radius` at z=+height/2 (equal radii = straight cylinder).
  sphere   : `radius` about the origin.
  union    : result = base + tool (boolean fuse).
  cut      : result = base - tool (boolean subtraction).

Through holes: when a cylinder with through=True is the `tool` of a `cut`,
the engine ignores the tool's nominal height and instead rebuilds it to span
the base's full Z extent plus a margin, centered on the base bounding-box
center. The LLM never computes offsets; placement is deterministic.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from .schema import (
    BoxOperation,
    ConeOperation,
    CutOperation,
    CylinderOperation,
    SphereOperation,
    UnionOperation,
)

# Extra length added on EACH side of the base when auto-extending a
# through-hole tool: large enough to guarantee overlap for a clean boolean,
# relative term keeps it sane for very large parts.
THROUGH_MARGIN_MM = 2.0
THROUGH_MARGIN_RATIO = 0.001


def get_cadquery_version() -> str | None:
    try:
        import cadquery as cq

        return cq.__version__
    except Exception:
        return None


def _require_cq():
    try:
        import cadquery as cq
    except Exception as e:
        raise RuntimeError(f"CadQuery is not available: {e}") from e
    return cq


def make_box(width: float = 100.0, depth: float = 60.0, height: float = 30.0):
    """Create a simple box solid. Raises RuntimeError if CadQuery unavailable."""
    try:
        import cadquery as cq
    except Exception as e:
        raise RuntimeError(f"CadQuery is not available: {e}") from e
    if min(width, depth, height) <= 0:
        raise ValueError("Box dimensions must be positive")
    return cq.Workplane("XY").box(width, depth, height)


def make_cylinder(radius: float, height: float):
    """Z-axis cylinder of `radius`, spanning z in [-height/2, +height/2]."""
    cq = _require_cq()
    if min(radius, height) <= 0:
        raise ValueError("Cylinder dimensions must be positive")
    solid = cq.Solid.makeCylinder(radius, height)
    return solid.translate(cq.Vector(0, 0, -height / 2))


def make_cone(bottom_radius: float, top_radius: float, height: float):
    """Z-axis frustum: bottom_radius at z=-height/2, top_radius at +height/2."""
    cq = _require_cq()
    if min(bottom_radius, top_radius, height) <= 0:
        raise ValueError("Cone dimensions must be positive")
    solid = cq.Solid.makeCone(bottom_radius, top_radius, height)
    return solid.translate(cq.Vector(0, 0, -height / 2))


def make_sphere(radius: float):
    """Sphere of `radius` centered on the origin.

    NOTE: CadQuery's makeSphere defaults to angleDegrees1=0 (equator), which
    yields a hemisphere. A full sphere needs the latitude sweep -90..+90.
    """
    cq = _require_cq()
    if radius <= 0:
        raise ValueError("Sphere radius must be positive")
    return cq.Solid.makeSphere(
        radius, angleDegrees1=-90, angleDegrees2=90, angleDegrees3=360
    )


def union(base, tool):
    """Boolean union: result = base + tool. Inputs are CadQuery shapes."""
    try:
        return base.fuse(tool)
    except Exception as e:
        raise RuntimeError(f"Boolean union failed: {e}") from e


def cut(base, tool):
    """Boolean subtraction: result = base - tool. Inputs are CadQuery shapes."""
    try:
        return base.cut(tool)
    except Exception as e:
        raise RuntimeError(f"Boolean cut failed: {e}") from e


def through_tool_height(zmin: float, zmax: float) -> float:
    """Pure helper (no CadQuery needed): height a through-hole tool needs to
    span the base Z extent [zmin, zmax] plus the deterministic margin."""
    span = zmax - zmin
    if span <= 0:
        raise ValueError("Base Z extent must be positive for a through hole")
    return span + 2 * max(THROUGH_MARGIN_MM, span * THROUGH_MARGIN_RATIO)


def _build_through_tool(cq, base, radius: float):
    """Rebuild a through-hole cylinder to span the base bounding box."""
    bbox = base.BoundingBox()
    height = through_tool_height(bbox.zmin, bbox.zmax)
    tool = cq.Solid.makeCylinder(radius, height)
    cx = (bbox.xmin + bbox.xmax) / 2
    cy = (bbox.ymin + bbox.ymax) / 2
    cz = (bbox.zmin + bbox.zmax) / 2
    return tool.translate(cq.Vector(cx, cy, cz - height / 2))


def build_operation(op):
    """Build a CadQuery shape from a validated operation node (recursive)."""
    cq = _require_cq()
    if isinstance(op, BoxOperation):
        dims = (op.width, op.depth, op.height)
        if min(dims) <= 0:
            raise ValueError("Box dimensions must be positive")
        w, d, h = dims
        return cq.Solid.makeBox(w, d, h, pnt=cq.Vector(-w / 2, -d / 2, -h / 2))
    if isinstance(op, CylinderOperation):
        return make_cylinder(op.radius, op.height)
    if isinstance(op, ConeOperation):
        return make_cone(op.bottom_radius, op.top_radius, op.height)
    if isinstance(op, SphereOperation):
        return make_sphere(op.radius)
    if isinstance(op, UnionOperation):
        return union(build_operation(op.base), build_operation(op.tool))
    if isinstance(op, CutOperation):
        base = build_operation(op.base)
        tool_op = op.tool
        if isinstance(tool_op, CylinderOperation) and tool_op.through:
            if tool_op.radius <= 0:
                raise ValueError("Through-hole radius must be positive")
            tool = _build_through_tool(cq, base, tool_op.radius)
        else:
            tool = build_operation(tool_op)
        return cut(base, tool)
    raise ValueError(f"Unsupported operation: {type(op).__name__}")


def _slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name.strip()).strip("_").lower()
    return (slug or "part")[:50]


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _head_contains(path: Path, marker: bytes, limit: int) -> bool:
    try:
        with path.open("rb") as f:
            return marker in f.read(limit)
    except OSError:
        return False


def _stl_structure_ok(path: Path) -> bool:
    """Plausibility check for our exporter's STL output (no full parser).

    ASCII STL starts with "solid" and ends with an "endsolid" trailer;
    binary STL has an 84-byte header followed by 50-byte facet records.
    Only head/tail bytes are read, never the whole file.
    """
    try:
        size = path.stat().st_size
        if size <= 0:
            return False
        with path.open("rb") as f:
            head = f.read(128)
        if head.startswith(b"solid"):
            try:
                with path.open("rb") as f:
                    f.seek(max(0, size - 128))
                    tail = f.read(128)
                return b"endsolid" in tail
            except OSError:
                return False
        return size >= 84 and (size - 84) % 50 == 0
    except OSError:
        return False


def validate_exported_files(step_path: str | Path, stl_path: str | Path) -> dict:
    """Verify exported STEP/STL files are sane; raise RuntimeError otherwise.

    Checks: both exist, both non-empty, STEP carries the ISO-10303 magic,
    STL has a plausible ASCII/binary structure. The error message names only
    the failed checks — never filesystem paths.
    """
    step = Path(step_path)
    stl = Path(stl_path)
    checks = {
        "step_exists": step.is_file(),
        "step_non_empty": _file_size(step) > 0,
        "step_magic_ok": _head_contains(step, b"ISO-10303", 64),
        "stl_exists": stl.is_file(),
        "stl_non_empty": _file_size(stl) > 0,
        "stl_structure_ok": _stl_structure_ok(stl),
    }
    failed = sorted(name for name, ok in checks.items() if not ok)
    if failed:
        raise RuntimeError(f"Export validation failed: {', '.join(failed)}")
    return checks


def _export_solid(solid, stem: str, out_dir: str | Path | None) -> dict:
    cq = _require_cq()
    target = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="cgen_"))
    target.mkdir(parents=True, exist_ok=True)

    step_path = target / f"{stem}.step"
    stl_path = target / f"{stem}.stl"

    try:
        cq.exporters.export(solid, str(step_path))
    except Exception as e:
        raise RuntimeError(f"STEP export failed: {e}") from e
    try:
        cq.exporters.export(solid, str(stl_path))
    except Exception as e:
        raise RuntimeError(f"STL export failed: {e}") from e

    return {
        "step_path": str(step_path),
        "stl_path": str(stl_path),
        "step_bytes": step_path.stat().st_size,
        "stl_bytes": stl_path.stat().st_size,
        "cadquery_version": get_cadquery_version(),
    }


def export_operation(operation, name: str = "part", out_dir: str | Path | None = None) -> dict:
    """Build any validated operation and export STEP + STL. Returns metadata."""
    solid = build_operation(operation)
    op_type = getattr(operation, "type", "part")
    result = _export_solid(solid, f"{_slugify(name)}_{op_type}", out_dir)
    result.update({"operation": op_type, "units": "mm"})
    return result


def export_box(
    width: float = 100.0,
    depth: float = 60.0,
    height: float = 30.0,
    out_dir: str | Path | None = None,
) -> dict:
    """Create box, export STEP + STL to out_dir, return file metadata."""
    solid = make_box(width, depth, height)

    target = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="cgen_"))
    target.mkdir(parents=True, exist_ok=True)

    step_path = target / f"box_{width}x{depth}x{height}.step"
    stl_path = target / f"box_{width}x{depth}x{height}.stl"

    try:
        import cadquery as cq

        cq.exporters.export(solid, str(step_path))
    except Exception as e:
        raise RuntimeError(f"STEP export failed: {e}") from e

    try:
        import cadquery as cq

        cq.exporters.export(solid, str(stl_path))
    except Exception as e:
        raise RuntimeError(f"STL export failed: {e}") from e

    return {
        "width": width,
        "depth": depth,
        "height": height,
        "units": "mm",
        "step_path": str(step_path),
        "stl_path": str(stl_path),
        "step_bytes": step_path.stat().st_size,
        "stl_bytes": stl_path.stat().st_size,
        "cadquery_version": get_cadquery_version(),
    }
