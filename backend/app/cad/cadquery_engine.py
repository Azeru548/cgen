"""Minimal CadQuery engine for Milestone 1 PoC.

Only does one thing reliably: create a box and export STEP/STL.
Keeps CadQuery import lazy so /health works even if CadQuery
is missing/broken in an environment.
"""

from __future__ import annotations

import tempfile
from pathlib import Path


def get_cadquery_version() -> str | None:
    try:
        import cadquery as cq

        return cq.__version__
    except Exception:
        return None


def make_box(width: float = 100.0, depth: float = 60.0, height: float = 30.0):
    """Create a simple box solid. Raises RuntimeError if CadQuery unavailable."""
    try:
        import cadquery as cq
    except Exception as e:
        raise RuntimeError(f"CadQuery is not available: {e}") from e
    if min(width, depth, height) <= 0:
        raise ValueError("Box dimensions must be positive")
    return cq.Workplane("XY").box(width, depth, height)


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
