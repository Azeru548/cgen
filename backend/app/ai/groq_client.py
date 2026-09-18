"""Groq language layer (Milestone 2).

Separation of responsibilities:
  Groq    = interprets natural language, returns strict JSON only.
  Pydantic (cad/schema.py) = validates the CAD specification.
  CadQuery (cad/cadquery_engine.py) = generates geometry.

This module NEVER executes AI output. No exec(), no eval().
Raw model output is parsed as JSON and validated via CADSpec;
anything else is rejected with a clean error.
"""

from __future__ import annotations

import json
import os

from pydantic import ValidationError

from ..cad.schema import CADSpec

# Overridable without code changes (e.g. Render env var) if Groq retires it.
GROQ_MODEL_DEFAULT = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """You translate natural-language CAD requests into a strict JSON CAD specification.

Rules you MUST follow:
- Return JSON ONLY. No markdown, no explanation, no comments, no code fences.
- NEVER return Python code, CadQuery code, or any executable code.
- ONLY use supported operations. Currently ONLY "box" is supported.
  Do NOT invent cylinders, holes, cones, spheres, or boolean operations.
- Convert ALL dimensions to millimeters (mm) in the output numbers:
  1 m = 1000 mm, 1 cm = 10 mm, 1 inch = 25.4 mm.
- If a dimension is missing, make no guess outside what the user said;
  use a sensible explicit value and keep the shape a box.

Return EXACTLY this shape (numbers are examples):
{"document_type": "3d_part", "units": "mm", "name": "rectangular_block",
 "operation": {"type": "box", "width": 100, "depth": 60, "height": 30}}
"""


class GroqConfigError(RuntimeError):
    """Server misconfiguration: missing key, missing SDK, or bad setup."""


class AIGenerationError(RuntimeError):
    """Groq call failed or returned unusable (non-JSON / empty) output."""


class SpecValidationError(ValueError):
    """Model returned JSON, but it is not a valid CADSpec."""


def _get_api_key() -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise GroqConfigError(
            "GROQ_API_KEY is not set. Configure it as an environment variable."
        )
    return key


def _get_client(api_key: str):
    """Lazily construct the official Groq client (import deferred so the
    module imports cleanly in environments without the SDK installed)."""
    try:
        from groq import Groq
    except Exception as e:
        raise GroqConfigError(
            "The 'groq' package is not installed. Add it to requirements.txt."
        ) from e
    return Groq(api_key=api_key)


def _extract_json(text: str) -> str:
    """Tolerate a model wrapping JSON in ```json fences; otherwise pass through."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        # Drop opening fence (``` or ```json) and trailing fence.
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    return cleaned


def parse_prompt_to_spec(prompt: str, *, client=None) -> CADSpec:
    """Translate a natural-language prompt into a validated CADSpec.

    `client` is injectable for tests (any object exposing
    client.chat.completions.create(...)). When omitted, the real Groq
    client is built from GROQ_API_KEY.
    """
    api_key = _get_api_key()
    client = client if client is not None else _get_client(api_key)
    model = os.environ.get("GROQ_MODEL", GROQ_MODEL_DEFAULT)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
    except (GroqConfigError, AIGenerationError):
        raise
    except Exception as e:
        raise AIGenerationError(f"Groq request failed: {e}") from e

    try:
        content = response.choices[0].message.content
    except Exception as e:
        raise AIGenerationError(f"Groq returned an unexpected response: {e}") from e

    if not content or not content.strip():
        raise AIGenerationError("Groq returned an empty response.")

    try:
        data = json.loads(_extract_json(content))
    except Exception as e:
        raise AIGenerationError(
            "Groq did not return valid JSON. Please rephrase the request."
        ) from e

    try:
        return CADSpec.model_validate(data)
    except ValidationError as e:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in e.errors()[:3]
        )
        raise SpecValidationError(
            f"AI specification failed validation: {details}"
        ) from e
