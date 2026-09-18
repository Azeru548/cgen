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
import logging
import os

from pydantic import ValidationError

from ..cad.schema import CADSpec

logger = logging.getLogger(__name__)

# Default model (2026-09): Groq deprecated llama-3.3-70b-versatile on
# 2026-06-17 and retired it on 2026-08-16 (console.groq.com/docs/deprecations).
# Calls with the retired ID fail with 400 `model_decommissioned`, which this
# service surfaces as HTTP 502. Replacement is Groq's recommended production
# model openai/gpt-oss-120b. Override per-environment via GROQ_MODEL.
GROQ_MODEL_DEFAULT = "openai/gpt-oss-120b"

# Upstream API messages are truncated to this length before being included
# in responses/logs, so a verbose provider payload can never leak excess data.
MAX_API_MESSAGE_CHARS = 300

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


def _coerce_text(value: object, limit: int = MAX_API_MESSAGE_CHARS) -> str:
    """Collapse whitespace and truncate provider-supplied text.

    Only used for short error-message strings. Headers, keys, and request
    bodies are never passed through here.
    """
    if not isinstance(value, str) or not value.strip():
        return ""
    return " ".join(value.split())[:limit]


def _extract_api_message(exc: BaseException) -> tuple[str, str]:
    """Pull (message, code) from a Groq SDK error body, e.g.
    {"error": {"message": "...", "code": "model_decommissioned"}}.
    Returns ("", "") when the body is absent or unstructured."""
    body = getattr(exc, "body", None)
    payload: object = None
    if isinstance(body, dict):
        err = body.get("error")
        payload = err if isinstance(err, dict) else body
    if not isinstance(payload, dict):
        return "", ""
    message = _coerce_text(payload.get("message"))
    code = _coerce_text(payload.get("code"), limit=80)
    return message, code


def _describe_request_error(exc: BaseException, model: str) -> str:
    """Map a Groq SDK/API failure to a safe, diagnosable message.

    Includes the upstream HTTP status, the API error code/message (truncated),
    and the model in use. NEVER includes headers, API keys, or request data.
    """
    status = getattr(exc, "status_code", None)
    api_msg, api_code = _extract_api_message(exc)
    suffix = f" Upstream: {api_msg}" if api_msg else ""
    code_hint = f" (code: {api_code})" if api_code else ""

    if status is None:
        # No HTTP response at all: DNS/TLS/connection/timeout on the way to Groq.
        local = _coerce_text(getattr(exc, "message", "") or str(exc), limit=120)
        detail = f"Could not reach the Groq API ({local or 'connection error'})."
        return f"{detail} Check Groq status and Render egress networking."

    if status == 401:
        return (
            f"Groq authentication failed (401{code_hint}). The GROQ_API_KEY "
            f"is invalid or unauthorized.{suffix}"
        )
    if status == 403:
        return (
            f"Groq permission denied (403{code_hint}). The key lacks access or "
            f"the model is blocked at the organization level.{suffix}"
        )
    if status == 404:
        return (
            f"Groq could not find the model '{model}' (404{code_hint}). "
            f"Set a supported model via the GROQ_MODEL env var "
            f"(e.g. {GROQ_MODEL_DEFAULT}).{suffix}"
        )
    if status == 429:
        return (
            f"Groq rate limit reached (429{code_hint}). "
            f"Wait and retry; consider upgrading the Groq plan.{suffix}"
        )
    if status == 400:
        model_retired = (
            api_code in ("model_decommissioned", "model_not_found")
            or "decommission" in api_msg.lower()
            or "deprecat" in api_msg.lower()
            or model in api_msg
        )
        if model_retired:
            return (
                f"Groq rejected the model '{model}' (400{code_hint}): it is "
                f"retired or unknown. Set a supported model via the GROQ_MODEL "
                f"env var (e.g. {GROQ_MODEL_DEFAULT}).{suffix}"
            )
        if "response_format" in api_msg.lower():
            return (
                f"Groq rejected the response_format for model '{model}' "
                f"(400{code_hint}). The model may not support JSON mode; try a "
                f"supported model via GROQ_MODEL.{suffix}"
            )
        return f"Groq rejected the request (400{code_hint}).{suffix}"
    if status in (500, 502, 503):
        return (
            f"Groq API server error ({status}{code_hint}). "
            f"Retry shortly; check https://status.groq.com.{suffix}"
        )
    return f"Groq API error ({status}{code_hint}).{suffix}" or "Groq request failed."


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
            # JSON Object Mode: per the Groq API reference this guarantees the
            # message is valid JSON on chat models incl. openai/gpt-oss-120b.
            # (Strict json_schema Structured Outputs would also work on gpt-oss,
            # but json_object + our Pydantic CADSpec boundary is sufficient and
            # stays portable if GROQ_MODEL is overridden.)
            response_format={"type": "json_object"},
        )
    except (GroqConfigError, AIGenerationError):
        raise
    except Exception as e:
        detail = _describe_request_error(e, model)
        # Server-side breadcrumb: Render access logs only show the 502 line,
        # so the actionable cause must also land in the application logs.
        # `detail` is pre-sanitized (no keys, headers, or request data).
        logger.warning("Groq request failed (model=%s): %s", model, detail)
        raise AIGenerationError(detail) from e

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
