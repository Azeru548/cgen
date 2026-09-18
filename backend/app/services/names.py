"""Machine-safe name handling (M4).

The AI proposes a `name` for each part, but AI output is DATA, never trusted
as a filesystem path. This module normalizes any raw name into a stem that is
safe for filenames and URLs:

  "Shaft With Hole!"  -> "shaft_with_hole"
  "../../etc/passwd"  -> "etc_passwd"
  ""                  -> fallback (derived from the operation type)

Rules: lowercase ASCII letters/digits/underscores only, max length cap,
never empty (falls back to e.g. "cylinder_part").
"""

from __future__ import annotations

import re

MAX_STEM_LENGTH = 60


def default_name_for(operation_type: str) -> str:
    """Deterministic fallback name when the AI name is unusable."""
    clean = re.sub(r"[^a-z0-9]+", "_", operation_type.strip().lower()).strip("_")
    return f"{clean or 'part'}_part"


def sanitize_name(raw: object, *, fallback: str = "part") -> str:
    """Normalize an AI-provided name into a filesystem/URL-safe stem."""
    if not isinstance(raw, str):
        return default_name_for(fallback)
    stem = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")
    stem = stem[:MAX_STEM_LENGTH].rstrip("_")
    if not stem:
        return default_name_for(fallback)
    return stem
