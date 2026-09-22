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

from ..cad.assembly import AssemblySpec, validate_registry
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
- ONLY use these operation types: "box", "cylinder", "cone", "sphere", "torus",
  "polygon_prism", "union", "cut", "intersect", "part".
  Do NOT invent any other operation (no extrude, no sketch, no revolve,
  no loft, no sweep, no text).
- Convert ALL dimensions to millimeters (mm) in the output numbers:
  1 m = 1000 mm, 1 cm = 10 mm, 1 inch = 25.4 mm.
  Handle common engineering expressions: "M8 bolt hole" -> 8mm diameter hole;
  "30mm diameter" -> radius 15; "1 inch plate" -> 25.4mm thick.
- Cylinders, cones and spheres use RADIUS, not diameter: a 30mm diameter means radius 15.
  Torus and polygon_prism take "major_radius"/"minor_radius" and "circumradius"
  respectively (also radii, not diameters). Hole features take DIAMETER.
- Every dimension must be > 0 and <= 10000.
- Keep nesting shallow: at most 4 levels of composition/part, at most 15 operations total.
- If a dimension is missing, use a sensible explicit value; never omit required fields.
- "name": a short snake_case machine-safe name describing THIS object
  (lowercase letters, digits and underscores only, max 60 chars), e.g.
  "cylinder_shaft", "sphere", "cone", "shaft_with_hole", "o_ring",
  "hex_boss", "enclosure_box". NEVER reuse "rectangular_block" unless the
  object actually is a rectangular block.

Shapes (all dimensions in mm; every solid is centered on the origin — you never
specify positions, offsets, or rotations):
- box (extruded rectangle profile): {"type": "box", "width": 100, "depth": 60, "height": 30}
- cylinder (extruded circle profile, axis along Z):
  {"type": "cylinder", "radius": 15, "height": 120}
- cone (bottom radius at the base, top radius at the top):
  {"type": "cone", "bottom_radius": 20, "top_radius": 10, "height": 50}
- sphere: {"type": "sphere", "radius": 25}
- torus (ring: major_radius to the tube center, minor_radius the tube radius;
  minor MUST be smaller than major): {"type": "torus", "major_radius": 30, "minor_radius": 8}
- polygon_prism (extruded regular polygon: 3-12 sides, circumradius =
  center-to-corner): {"type": "polygon_prism", "sides": 6, "circumradius": 10, "height": 8}
- union (result = base + tool): {"type": "union", "base": {...}, "tool": {...}}
- cut (result = base - tool): {"type": "cut", "base": {...}, "tool": {...}}
- intersect (result = the SHARED volume of base and tool; they must overlap):
  {"type": "intersect", "base": {...}, "tool": {...}}

Holes, fillets, chamfers and hollow walls: use "part" with a "build" solid and
a "features" list. The engine applies features itself (holes -> shell ->
chamfer -> fillet) and centers holes on the part automatically — never compute
positions:
- hole (DIAMETER): through hole {"type": "hole", "diameter": 8, "through": true};
  blind hole {"type": "hole", "diameter": 8, "depth": 12} (depth measured from the
  top face; a through hole must NOT have depth). Use "hole" ONLY for ONE
  centered hole.
- hole_pattern (DIAMETERS, ONE feature no matter the count): two or more
  identical holes equally spaced around a circular bolt circle, e.g.
  {"type": "hole_pattern", "diameter": 8, "count": 4, "circle_diameter": 60,
   "through": true}; blind variant takes "depth" instead of "through".
  "count" is 2-12. "circle_diameter" is the bolt-circle diameter (center to
  opposite hole centers), NOT the part diameter. Use ONLY for genuinely
  circular layouts ("bolt circle", "equally spaced around the center",
  "flange bolt holes"): the whole circle must fit on the face, so NEVER use
  it for corner/rectangular/linear hole layouts on non-square faces.
- hole_grid (DIAMETERS, ONE feature no matter the count): two or more
  identical holes in a centered rectangular rows×cols array, e.g.
  {"type": "hole_grid", "diameter": 8, "rows": 2, "cols": 2,
   "spacing_x": 100, "spacing_y": 60, "through": true}; blind variant takes
  "depth" instead of "through". "rows"/"cols" are 1-12 with rows*cols <= 12;
  rows=1 or cols=1 gives a straight line of holes along one axis.
  "spacing_x"/"spacing_y" are CENTER-TO-CENTER distances between adjacent
  holes, NOT edge distances: holes 10mm from the edges of a 120×80 plate sit
  100mm apart in X and 60mm apart in Y, so spacing_x=100, spacing_y=60.
  Give a spacing ONLY for an axis with more than one hole and OMIT the
  other (no spacing_y for a 1×N horizontal row, no spacing_x for an N×1
  vertical column). A straight row of 4 holes with the first/last 15mm from
  the ends of a 120mm plate uses cols=4 and spacing_x=(120-15-15)/3=30.
  NEVER use a 1×1 grid for a single hole — that is just "hole".
  The array is always centered on the part — you NEVER give coordinates.
Routing — pick exactly ONE hole representation, never combine guesses:
  one centered hole -> "hole";
  "bolt circle" / "equally spaced around the center" / circular flange
  holes -> ONE "hole_pattern";
  "near each corner" / "in rows" / "at coordinates" / symmetric along one
  axis / any rectangular or straight-line layout -> ONE "hole_grid".
  At most 4 features total per part (e.g. central hole + hole_grid =
  2 features). NEVER emit several "hole" features (they would all drill the
  same centered hole), and NEVER compute positions.
- fillet: {"type": "fillet", "radius": 2}
- chamfer: {"type": "chamfer", "size": 2}
- shell (hollow with a wall, top face open):
  {"type": "shell", "thickness": 2}
- part example (plate with a through hole, rounded edges):
  {"type": "part",
   "build": {"type": "box", "width": 100, "depth": 60, "height": 10},
   "features": [{"type": "hole", "diameter": 8, "through": true},
                {"type": "fillet", "radius": 2}]}
Feature feasibility rules: fillet radius and chamfer size must stay well below
the smallest wall spacing (filleting before a shell fails); shell thickness
must be smaller than the smallest solid dimension; fillet/chamfer only apply
to straight box-like edges (never on cylinders, spheres, tori).

Legacy hole style (still valid): a "cut" whose tool is a cylinder with
"through": true is a deterministic centered through-hole, e.g.:
{"type": "cut", "base": {"type": "cylinder", "radius": 15, "height": 120},
 "tool": {"type": "cylinder", "radius": 7.5, "height": 120, "through": true}}
Prefer "part" with hole features for holes on box-like builds.

Return EXACTLY this top-level shape (operation varies as above):
{"document_type": "3d_part", "units": "mm", "name": "rectangular_block",
 "operation": {"type": "box", "width": 100, "depth": 60, "height": 30}}

ASSEMBLY MODE (document_type "3d_assembly"):
Use an assembly when the user wants MULTIPLE separately identifiable objects
in one workspace (enclosure + board + screws + lid, etc.). Do NOT boolean-union
them. If the request is a single solid, keep returning 3d_part as above.

Assembly JSON shape:
{"document_type": "3d_assembly", "units": "mm", "name": "arduino_enclosure",
 "schema_version": "4.0",
 "components": [
   {"id": "arduino_1", "component_type": "arduino_uno", "name": "Arduino Uno",
    "parameters": {}, "transform": {"position": [0, 0, 8], "rotation": [0, 0, 0]},
    "visible": true, "instances": [],
    "relationships": [{"type": "centered_on", "target_id": "enclosure_1"}]},
   {"id": "enclosure_1", "component_type": "enclosure", "name": "Enclosure",
    "parameters": {"width": 90, "depth": 70, "height": 40, "wall_thickness": 2.5,
                   "board": "arduino_uno", "usb_cutout": true},
    "transform": {"position": [0, 0, 0], "rotation": [0, 0, 0]},
    "visible": true, "instances": [], "relationships": []},
   {"id": "lid_1", "component_type": "enclosure_lid", "name": "Lid",
    "parameters": {"width": 90, "depth": 70, "thickness": 2.5},
    "transform": {"position": [0, 0, 21.25], "rotation": [0, 0, 0]},
    "visible": true, "instances": [], "relationships": []},
   {"id": "screws_1", "component_type": "m3_screw", "name": "M3 screws",
    "parameters": {"length": 12},
    "transform": {"position": [0, 0, 0], "rotation": [0, 0, 0]},
    "visible": true, "instances": [],
    "relationships": [{"type": "mounted_on", "target_id": "arduino_1"}]}
 ]}

Rules for assemblies:
- component_type MUST be one of the registry types listed below. NEVER invent types.
- id must be a lowercase slug: letter then letters/digits/underscores, unique in the list.
- Do NOT include a "generated" field unless component_type is "generated_part".
- Prefer library components (enclosure, arduino_uno, m3_screw) over generated_part.
- Use one m3_screw (or similar) with relationship mounted_on / repeated_from for
  repeated fasteners — do NOT emit four separate screw components.
- relationships.target_id must refer to another component in this list.
- Allowed relationship types: positioned_at, attached_to, aligned_with,
  repeated_from, mounted_on, centered_on.
- transforms: position in mm, rotation in XYZ Euler degrees.
- At most 24 components. At most 12 instances per component.
- If the board cannot physically fit, still return the assembly with a larger
  enclosure rather than omitting the board.

REGISTRY (authoritative; only these component_type values are legal):
"""


def _assembly_prompt_suffix() -> str:
    from ..cad import registry

    return registry.prompt_catalog()


def _system_prompt() -> str:
    return SYSTEM_PROMPT + _assembly_prompt_suffix()


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


def parse_prompt_to_spec(prompt: str, *, client=None) -> CADSpec | AssemblySpec:
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
                {"role": "system", "content": _system_prompt()},
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
        return _validate_document(data)
    except ValidationError as e:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in e.errors()[:3]
        )
        raise SpecValidationError(
            f"AI specification failed validation: {details}"
        ) from e
    except ValueError as e:
        raise SpecValidationError(f"AI specification failed validation: {e}") from e


def _validate_document(data: object) -> CADSpec | AssemblySpec:
    if not isinstance(data, dict):
        raise SpecValidationError("AI specification was not a JSON object.")
    if data.get("document_type") == "3d_assembly":
        return validate_registry(AssemblySpec.model_validate(data))
    return CADSpec.model_validate(data)


MODIFY_SYSTEM_PROMPT = """You modify an existing JSON CAD specification based on a natural-language instruction.

You receive:
1. The current valid CAD specification (JSON).
2. A modification instruction from the user.

You MUST return a modified CAD specification that follows the same schema.

Rules you MUST follow:
- Return JSON ONLY. No markdown, no explanation, no comments, no code fences.
- NEVER return Python code, CadQuery code, or any executable code.
- Preserve the document_type, units, and name fields unless the instruction explicitly asks to rename.
- Only change numeric fields that are directly relevant to the instruction. Do NOT modify unrelated fields.
- STRUCTURAL PRESERVATION (enforced by a deterministic validator — redesigns are rejected):
  - Keep the EXACT same operation tree: same top-level type, same nested
    composition shape, same build primitives. Only numeric values may change.
  - NEVER swap one primitive for another (no box -> cylinder, no hole -> sphere).
  - NEVER remove or replace an existing feature. A hole stays a hole; only its
    diameter/depth/through/count parameters may change.
  - You MAY add a NEW feature to a part (e.g. add a fillet), and you MAY wrap
    a bare solid in a "part" node to attach its first feature — the build
    geometry itself must stay identical.
  - A request that needs a different shape (e.g. "replace the hole with a
    sphere", "make it a cylinder instead of a box") is a NEW part, not a
    modification: return the current specification UNCHANGED so the validator
    reports no change.
- Keep all the same operation types: "box", "cylinder", "cone", "sphere", "torus", "polygon_prism", "union", "cut", "intersect", "part".
- Do NOT invent new operation types.
- Convert ALL dimensions to millimeters (mm) if not already.
- Every dimension must be > 0 and <= 10000.
- Keep nesting shallow: at most 4 levels, at most 15 operations total.
- Features: "hole", "hole_pattern", "hole_grid", "fillet", "chamfer", "shell" — same rules as generation.
- At most 4 features per part node.

Examples of valid modifications:
- "make it 50mm taller" → increase the height dimension by 50
- "add a 10mm through hole" → wrap the solid in a part node with a hole feature, or add to existing features
- "change the hole diameter to 12mm" → update the diameter on the existing hole
- "round the edges with 2mm fillet" → add fillet feature alongside existing features

Return EXACTLY the full modified specification as JSON:
{"document_type": "3d_part", "units": "mm", "name": "...", "operation": {...}}
"""


class SpecModificationError(RuntimeError):
    """Modification LLM call failed or returned unusable output."""


ASSEMBLY_MODIFY_PROMPT = """You modify an existing JSON assembly specification based on a natural-language instruction.

You receive:
1. The current valid 3d_assembly specification (JSON).
2. A modification instruction from the user.

Return a modified 3d_assembly that follows the same schema.

Rules:
- Return JSON ONLY. No markdown, no explanation, no code fences, no executable code.
- Preserve document_type "3d_assembly", units "mm", and schema_version "4.0".
- Preserve the name unless the instruction explicitly asks to rename.
- component_type MUST stay a registry type. NEVER invent types.
- You MAY change numeric parameters, transforms, visibility, and names.
- You MAY add library components the instruction asks for (enclosure, screws, lid, boards).
- You MAY remove a component the instruction asks to delete.
- For repeated fasteners, keep ONE component with relationship mounted_on / repeated_from
  rather than duplicating definitions.
- Do NOT boolean-union separate objects.
- generated_part nested specs: only numeric/feature parameter changes; do not redesign them.
- At most 24 components.

Return the full modified 3d_assembly JSON.
"""


def modify_spec(
    current_spec_json: str,
    instruction: str,
    *,
    client=None,
) -> CADSpec | AssemblySpec:
    """Modify an existing CAD spec based on a natural-language instruction.

    `current_spec_json` is the JSON-serialized current CADSpec.
    `instruction` is the user's modification request.
    `client` is injectable for tests.
    Returns the modified and validated CADSpec.
    Raises SpecModificationError on failure.
    """
    api_key = _get_api_key()
    client = client if client is not None else _get_client(api_key)
    model = os.environ.get("GROQ_MODEL", GROQ_MODEL_DEFAULT)

    user_content = (
        f"Current specification:\n{current_spec_json}\n\n"
        f"Modification instruction:\n{instruction}"
    )
    is_assembly = False
    try:
        parsed_current = json.loads(current_spec_json)
        is_assembly = (
            isinstance(parsed_current, dict)
            and parsed_current.get("document_type") == "3d_assembly"
        )
    except Exception:
        is_assembly = False
    system = ASSEMBLY_MODIFY_PROMPT if is_assembly else MODIFY_SYSTEM_PROMPT
    if is_assembly:
        system = system + "\nREGISTRY:\n" + _assembly_prompt_suffix()

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
    except (GroqConfigError, AIGenerationError):
        raise
    except Exception as e:
        detail = _describe_request_error(e, model)
        logger.warning("Groq modification request failed (model=%s): %s", model, detail)
        raise SpecModificationError(detail) from e

    try:
        content = response.choices[0].message.content
    except Exception as e:
        raise SpecModificationError(
            f"Groq returned an unexpected modification response: {e}"
        ) from e

    if not content or not content.strip():
        raise SpecModificationError("Groq returned an empty modification response.")

    try:
        data = json.loads(_extract_json(content))
    except Exception as e:
        raise SpecModificationError(
            "Groq did not return valid JSON for modification."
        ) from e

    try:
        return _validate_document(data)
    except ValidationError as e:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in e.errors()[:3]
        )
        raise SpecValidationError(
            f"Modified specification failed validation: {details}"
        ) from e
    except ValueError as e:
        raise SpecValidationError(
            f"Modified specification failed validation: {e}"
        ) from e
