"""Milestone 2 tests: POST /generate (Groq layer mocked, no network, no CadQuery).

The success path also mocks the CAD exporter, since CadQuery only exists
in the cloud/Docker environment — the wiring (spec -> export_box args) is
what is under test here.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai import groq_client
from app.cad.schema import CADSpec
from app.main import MAX_PROMPT_LENGTH, app

client = TestClient(app)

BOX_JSON = (
    '{"document_type": "3d_part", "units": "mm", "name": "rectangular_block", '
    '"operation": {"type": "box", "width": 100, "depth": 60, "height": 30}}'
)


def make_fake_client(content, captured=None):
    """Fake Groq client exposing chat.completions.create(...)."""

    def create(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        msg = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


class FakeApiError(Exception):
    """Duck-typed stand-in for groq SDK status errors.

    Mirrors the attributes the mapping code reads (status_code/body/message)
    plus sensitive attrs (headers/request) the mapping must NEVER echo.
    """

    def __init__(self, message, *, status_code=None, body=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.body = body
        self.headers = {"Authorization": "Bearer sk-test-secret-123"}
        self.request = SimpleNamespace(
            headers=self.headers, content='{"model": "secret-model"}'
        )


def make_failing_client(exc):
    def create(**kwargs):
        raise exc

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_auth_failure_is_actionable_502_without_leaks(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "sk-test-secret-123")
    exc = FakeApiError(
        "Error code: 401 - {'error': {'message': 'Invalid API Key'}}",
        status_code=401,
        body={"error": {"message": "Invalid API Key", "code": "invalid_api_key"}},
    )
    monkeypatch.setattr(groq_client, "_get_client", lambda key: make_failing_client(exc))
    r = client.post("/generate", json={"prompt": "Create a block."})
    assert r.status_code == 502, r.text
    detail = r.json()["detail"]
    assert "authentication failed" in detail
    assert "GROQ_API_KEY" in detail
    assert "sk-test-secret-123" not in r.text
    assert "Bearer" not in r.text
    assert "Traceback" not in r.text


def test_rate_limit_is_502(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    exc = FakeApiError(
        "Error code: 429 - {'error': {'message': 'Rate limit reached'}}",
        status_code=429,
        body={"error": {"message": "Rate limit reached", "code": "rate_limit_exceeded"}},
    )
    monkeypatch.setattr(groq_client, "_get_client", lambda key: make_failing_client(exc))
    r = client.post("/generate", json={"prompt": "Create a block."})
    assert r.status_code == 502, r.text
    assert "rate limit" in r.json()["detail"]


def test_retired_model_is_actionable_502(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    exc = FakeApiError(
        "Error code: 400 - {'error': {'message': 'The model "
        "`llama-3.3-70b-versatile` has been decommissioned', "
        "'code': 'model_decommissioned'}}",
        status_code=400,
        body={
            "error": {
                "message": "The model `llama-3.3-70b-versatile` has been decommissioned",
                "code": "model_decommissioned",
            }
        },
    )
    monkeypatch.setattr(groq_client, "_get_client", lambda key: make_failing_client(exc))
    # Force the retired model to reproduce the production failure exactly.
    monkeypatch.setattr(groq_client, "GROQ_MODEL_DEFAULT", "llama-3.3-70b-versatile")
    r = client.post("/generate", json={"prompt": "Create a block."})
    assert r.status_code == 502, r.text
    detail = r.json()["detail"]
    assert "retired" in detail
    assert "GROQ_MODEL" in detail


def test_connection_failure_is_502(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    exc = FakeApiError("Connection error.", status_code=None, body=None)
    monkeypatch.setattr(groq_client, "_get_client", lambda key: make_failing_client(exc))
    r = client.post("/generate", json={"prompt": "Create a block."})
    assert r.status_code == 502, r.text
    assert "Could not reach the Groq API" in r.json()["detail"]


def test_server_error_is_502(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    exc = FakeApiError("Error code: 503", status_code=503, body=None)
    monkeypatch.setattr(groq_client, "_get_client", lambda key: make_failing_client(exc))
    r = client.post("/generate", json={"prompt": "Create a block."})
    assert r.status_code == 502, r.text
    assert "server error" in r.json()["detail"]


def test_error_detail_is_logged_server_side(monkeypatch, caplog):
    import logging

    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    exc = FakeApiError("Error code: 401", status_code=401, body=None)
    monkeypatch.setattr(groq_client, "_get_client", lambda key: make_failing_client(exc))
    with caplog.at_level(logging.WARNING, logger="app.ai.groq_client"):
        client.post("/generate", json={"prompt": "Create a block."})
    assert any("Groq request failed" in rec.message for rec in caplog.records)


def test_empty_prompt_rejected_without_calling_groq(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Groq must not be called for an empty prompt")

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", fail_if_called)
    for bad in ("", "   "):
        r = client.post("/generate", json={"prompt": bad})
        assert r.status_code == 400, r.text


def test_oversized_prompt_rejected(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Groq must not be called for an oversized prompt")

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", fail_if_called)
    r = client.post("/generate", json={"prompt": "x" * (MAX_PROMPT_LENGTH + 1)})
    assert r.status_code == 400, r.text


def test_missing_api_key_is_server_error(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    r = client.post("/generate", json={"prompt": "Create a 100mm cube."})
    assert r.status_code == 500, r.text
    assert "GROQ_API_KEY" in r.json()["detail"]
    assert "Traceback" not in r.text


def test_invalid_groq_json_is_bad_gateway(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        groq_client, "_get_client", lambda key: make_fake_client("not json {{{")
    )
    r = client.post("/generate", json={"prompt": "Create a block."})
    assert r.status_code == 502, r.text


def test_invalid_spec_from_model_rejected(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    bad = (
        '{"document_type": "3d_part", "units": "mm", "name": "bad", '
        '"operation": {"type": "box", "width": -5, "depth": 60, "height": 30}}'
    )
    monkeypatch.setattr(groq_client, "_get_client", lambda key: make_fake_client(bad))
    r = client.post("/generate", json={"prompt": "Create a block."})
    assert r.status_code == 422, r.text


def test_groq_uses_json_mode_and_system_prompt(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    captured = {}
    monkeypatch.setattr(
        groq_client, "_get_client", lambda key: make_fake_client(BOX_JSON, captured)
    )
    spec = groq_client.parse_prompt_to_spec("Create a 100x60x30 block.")
    assert isinstance(spec, CADSpec)
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["temperature"] == 0
    system_text = captured["messages"][0]["content"]
    for required in (
        "JSON ONLY",
        "NEVER return Python",
        '"box"',
        '"cylinder"',
        '"cone"',
        '"sphere"',
        '"union"',
        '"cut"',
        '"through"',
        "RADIUS",
        "millimeters",
        "snake_case",
    ):
        assert required in system_text


def _write_valid_pair(tmp_path, stem="part"):
    """Write a minimal valid STEP/STL pair; return (step_path, stl_path)."""
    step = tmp_path / f"{stem}.step"
    stl = tmp_path / f"{stem}.stl"
    step.write_bytes(b"ISO-10303-21;\nFAKE STEP FOR TESTS\n")
    stl.write_bytes(b"solid test\nendsolid test\n")
    return str(step), str(stl)


def test_generate_success_path_mocked(monkeypatch, tmp_path):
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "rectangular_block",
            "operation": {"type": "box", "width": 100, "depth": 60, "height": 30},
        }
    )
    seen = {}
    step_path, stl_path = _write_valid_pair(tmp_path, stem="box_100x60x30")

    def fake_parse(prompt):
        seen["prompt"] = prompt
        return spec

    def fake_export(*, width, depth, height):
        seen["dims"] = (width, depth, height)
        return {
            "step_path": step_path,
            "stl_path": stl_path,
            "step_bytes": 1234,
            "stl_bytes": 5678,
        }

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", fake_parse)
    monkeypatch.setattr("app.services.generation.cadquery_engine.export_box", fake_export)

    r = client.post(
        "/generate",
        json={"prompt": "Create a rectangular block 100mm x 60mm x 30mm."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["specification"]["operation"] == {
        "type": "box",
        "width": 100.0,
        "depth": 60.0,
        "height": 30.0,
    }
    assert seen["dims"] == (100.0, 60.0, 30.0)
    # M4 contract: files carry metadata + download URLs; legacy keys are gone.
    assert set(body["files"]) == {"step", "stl"}
    assert "download" not in body
    step = body["files"]["step"]
    assert step["format"] == "step"
    assert step["filename"] == "rectangular_block.step"
    assert step["bytes"] > 0
    assert step["download_url"].startswith("/download/")
    assert "format=step" in step["download_url"]
    assert body["units"] == "mm"
    assert isinstance(body["request_id"], str) and body["request_id"]
    assert body["generation_time_ms"] >= 0


def test_generate_part_with_features_mocked(monkeypatch, tmp_path):
    """M6: a part node (build + features) flows through /generate end to end."""
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "vent_plate",
            "operation": {
                "type": "part",
                "build": {"type": "box", "width": 100, "depth": 60, "height": 10},
                "features": [
                    {"type": "hole", "diameter": 8, "through": True},
                    {"type": "fillet", "radius": 2},
                ],
            },
        }
    )
    seen = {}
    step_path, stl_path = _write_valid_pair(tmp_path, stem="vent_plate_part")

    def fake_export(operation, name="part", out_dir=None):
        seen["op"] = operation
        seen["name"] = name
        return {
            "operation": "part",
            "step_bytes": 321,
            "stl_bytes": 654,
            "step_path": step_path,
            "stl_path": stl_path,
        }

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    monkeypatch.setattr(
        "app.services.generation.cadquery_engine.export_operation", fake_export
    )

    r = client.post(
        "/generate",
        json={"prompt": "Create a 100x60x10mm plate with an 8mm through hole and 2mm rounded edges."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    op = body["specification"]["operation"]
    assert op["type"] == "part"
    assert op["build"]["type"] == "box"
    assert {f["type"] for f in op["features"]} == {"hole", "fillet"}
    assert seen["op"].build.width == 100
    assert seen["name"] == "vent_plate"
    assert body["files"]["step"]["filename"] == "vent_plate.step"


def test_generate_part_with_hole_pattern_mocked(monkeypatch, tmp_path):
    """M6.1: a hole_pattern feature flows through /generate end to end."""
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "flange",
            "operation": {
                "type": "part",
                "build": {"type": "cylinder", "radius": 50, "height": 15},
                "features": [
                    {"type": "hole", "diameter": 40, "through": True},
                    {
                        "type": "hole_pattern",
                        "diameter": 8,
                        "count": 4,
                        "circle_diameter": 70,
                        "through": True,
                    },
                ],
            },
        }
    )
    seen = {}
    step_path, stl_path = _write_valid_pair(tmp_path, stem="flange_part")

    def fake_export(operation, name="part", out_dir=None):
        seen["op"] = operation
        seen["name"] = name
        return {
            "operation": "part",
            "step_bytes": 456,
            "stl_bytes": 789,
            "step_path": step_path,
            "stl_path": stl_path,
        }

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    monkeypatch.setattr(
        "app.services.generation.cadquery_engine.export_operation", fake_export
    )

    r = client.post(
        "/generate",
        json={"prompt": "Create a 100mm diameter flange with a 40mm center hole and 4 M8 bolt holes on a 70mm circle."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    op = body["specification"]["operation"]
    assert op["type"] == "part"
    assert op["build"]["type"] == "cylinder"
    assert {f["type"] for f in op["features"]} == {"hole", "hole_pattern"}
    assert seen["op"].build.radius == 50
    assert seen["name"] == "flange"
    assert body["files"]["step"]["filename"] == "flange.step"


def test_generate_m6_new_operations_mocked(monkeypatch, tmp_path):
    """M6 primitives/composition wire through the generic export path."""
    cases = [
        (
            "o_ring",
            {"type": "torus", "major_radius": 30, "minor_radius": 8},
            "Create a ring with a 60mm outer diameter and 16mm tube diameter.",
        ),
        (
            "hex_boss",
            {"type": "polygon_prism", "sides": 6, "circumradius": 10, "height": 8},
            "Create a 20mm across-corners hexagonal boss 8mm tall.",
        ),
        (
            "lens",
            {
                "type": "intersect",
                "base": {"type": "box", "width": 50, "depth": 50, "height": 10},
                "tool": {"type": "sphere", "radius": 60},
            },
            "Intersect a 50mm cube with a large sphere to make a rounded plate.",
        ),
    ]
    for name, operation, prompt in cases:
        spec = CADSpec.model_validate(
            {
                "document_type": "3d_part",
                "units": "mm",
                "name": name,
                "operation": operation,
            }
        )
        step_path, stl_path = _write_valid_pair(tmp_path, stem=f"{name}_files")

        def fake_export(operation, name="part", out_dir=None, _p=(step_path, stl_path)):
            return {
                "operation": operation.type,
                "step_bytes": 10,
                "stl_bytes": 20,
                "step_path": _p[0],
                "stl_path": _p[1],
            }

        monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt, s=spec: s)
        monkeypatch.setattr(
            "app.services.generation.cadquery_engine.export_operation", fake_export
        )
        r = client.post("/generate", json={"prompt": prompt})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["specification"]["operation"] == operation


def test_generate_invalid_m6_spec_is_422(monkeypatch):
    """A spec the schema rejects (e.g. minor >= major torus) maps to 422."""
    from app.ai.groq_client import SpecValidationError
    from pydantic import ValidationError as PydanticValidationError

    def fake_parse(prompt):
        try:
            CADSpec.model_validate(
                {
                    "document_type": "3d_part",
                    "units": "mm",
                    "name": "bad_ring",
                    "operation": {"type": "torus", "major_radius": 8, "minor_radius": 8},
                }
            )
        except PydanticValidationError as e:
            raise SpecValidationError(
                f"AI specification failed validation: {e.errors()[0]['msg']}"
            ) from e

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", fake_parse)
    r = client.post("/generate", json={"prompt": "Create a degenerate ring."})
    assert r.status_code == 422, r.text
    assert "validation" in r.json()["detail"].lower()


def test_generate_cad_failure_is_server_error(monkeypatch):
    monkeypatch.setattr(
        groq_client,
        "parse_prompt_to_spec",
        lambda prompt: CADSpec.model_validate(
            {
                "document_type": "3d_part",
                "units": "mm",
                "name": "b",
                "operation": {"type": "box", "width": 10, "depth": 10, "height": 10},
            }
        ),
    )

    def fail_export(*, width, depth, height):
        raise RuntimeError("CadQuery is not available: No module named 'cadquery'")

    monkeypatch.setattr("app.services.generation.cadquery_engine.export_box", fail_export)
    r = client.post("/generate", json={"prompt": "Create a small block."})
    assert r.status_code == 500, r.text
    assert "Traceback" not in r.text


def test_milestone1_endpoints_still_alive(monkeypatch):
    # Groq must not be involved in Milestone 1 paths at all.
    def fail_if_called(*args, **kwargs):
        raise AssertionError("Milestone 1 must not call Groq")

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", fail_if_called)
    assert client.get("/health").status_code == 200


# --- Milestone 3: new operation types through /generate (all mocked) -------


def test_generate_cylinder_mocked(monkeypatch, tmp_path):
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "shaft",
            "operation": {"type": "cylinder", "radius": 15, "height": 120},
        }
    )
    seen = {}
    step_path, stl_path = _write_valid_pair(tmp_path, stem="shaft_cylinder")

    def fake_export(operation, name="part", out_dir=None):
        seen["op"] = operation
        seen["name"] = name
        return {
            "operation": "cylinder",
            "step_bytes": 111,
            "stl_bytes": 222,
            "step_path": step_path,
            "stl_path": stl_path,
        }

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    monkeypatch.setattr("app.services.generation.cadquery_engine.export_operation", fake_export)

    r = client.post(
        "/generate",
        json={"prompt": "Create a cylinder 120mm tall with a diameter of 30mm."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["specification"]["operation"]["type"] == "cylinder"
    assert seen["op"].radius == 15
    assert seen["name"] == "shaft"
    assert body["files"]["step"]["download_url"].startswith("/download/")
    assert body["files"]["stl"]["download_url"].startswith("/download/")
    assert body["files"]["step"]["filename"] == "shaft.step"


def test_generate_cut_mocked(monkeypatch, tmp_path):
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "shaft_with_hole",
            "operation": {
                "type": "cut",
                "base": {"type": "cylinder", "radius": 15, "height": 120},
                "tool": {
                    "type": "cylinder",
                    "radius": 7.5,
                    "height": 120,
                    "through": True,
                },
            },
        }
    )

    def fake_export(operation, name="part", out_dir=None):
        assert operation.type == "cut"
        assert operation.tool.through is True
        step_path, stl_path = _write_valid_pair(tmp_path, stem="cut_tmp")
        return {
            "operation": "cut",
            "step_bytes": 333,
            "stl_bytes": 444,
            "step_path": step_path,
            "stl_path": stl_path,
        }

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    monkeypatch.setattr("app.services.generation.cadquery_engine.export_operation", fake_export)

    r = client.post(
        "/generate",
        json={
            "prompt": "Create a 120mm long shaft with a 30mm diameter "
            "and a 15mm hole through the center."
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["specification"]["operation"]["type"] == "cut"


def test_generate_nonbox_download_roundtrip(monkeypatch, tmp_path):
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "ball",
            "operation": {"type": "sphere", "radius": 25},
        }
    )
    step_file = tmp_path / "ball.step"
    stl_file = tmp_path / "ball.stl"
    step_file.write_bytes(b"ISO-10303-21; fake step")
    stl_file.write_bytes(b"solid ball\nfacet normal 0 0 0\nendsolid ball\n")

    def fake_export(operation, name="part", out_dir=None):
        return {
            "operation": "sphere",
            "step_bytes": step_file.stat().st_size,
            "stl_bytes": stl_file.stat().st_size,
            "step_path": str(step_file),
            "stl_path": str(stl_file),
        }

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    monkeypatch.setattr("app.services.generation.cadquery_engine.export_operation", fake_export)

    r = client.post("/generate", json={"prompt": "Create a sphere of radius 25mm."})
    assert r.status_code == 200, r.text
    files = r.json()["files"]

    dl = client.get(files["step"]["download_url"])
    assert dl.status_code == 200, dl.text
    assert b"ISO-10303" in dl.content
    assert "ball.step" in dl.headers.get("content-disposition", "")
    dl = client.get(files["stl"]["download_url"])
    assert dl.status_code == 200, dl.text


def test_download_unknown_token_404():
    assert client.get("/download/does-not-exist?format=step").status_code == 404


# --- Milestone 4: hardened download endpoint --------------------------------


def test_download_invalid_format_400(monkeypatch, tmp_path):
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "cube",
            "operation": {"type": "box", "width": 10, "depth": 10, "height": 10},
        }
    )
    step_path, stl_path = _write_valid_pair(tmp_path, stem="fmt_tmp")

    def fake_export(*, width, depth, height):
        return {"step_path": step_path, "stl_path": stl_path}

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    monkeypatch.setattr("app.services.generation.cadquery_engine.export_box", fake_export)
    token = (
        client.post("/generate", json={"prompt": "cube"})
        .json()["files"]["step"]["download_url"]
        .split("/download/")[1]
        .split("?")[0]
    )
    for bad_format in ("binary", "STEP", "stl ", "", "step%00"):
        r = client.get(f"/download/{token}?format={bad_format}")
        assert r.status_code == 400, (bad_format, r.text)


def test_download_random_and_traversal_tokens_404():
    assert client.get("/download/abc123XYZ_Proposition?format=stl").status_code == 404
    # Path traversal can never resolve: tokens are dict keys, not paths.
    assert client.get("/download/..%2F..%2Fetc%2Fpasswd?format=step").status_code == 404
    assert client.get("/download/..?format=step").status_code == 404


def test_download_missing_file_404(monkeypatch, tmp_path):
    import os

    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "ghost",
            "operation": {"type": "sphere", "radius": 5},
        }
    )
    step_path, stl_path = _write_valid_pair(tmp_path, stem="ghost_tmp")

    def fake_export(operation, name="part", out_dir=None):
        return {
            "operation": "sphere",
            "step_path": step_path,
            "stl_path": stl_path,
        }

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    monkeypatch.setattr("app.services.generation.cadquery_engine.export_operation", fake_export)
    url = client.post("/generate", json={"prompt": "ghost"}).json()["files"][
        "stl"
    ]["download_url"]
    os.remove(tmp_path / "ghost.stl")  # ephemeral disk lost the renamed file
    assert client.get(url).status_code == 404


def test_export_validation_failure_is_500(monkeypatch, tmp_path):
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "corrupt",
            "operation": {"type": "sphere", "radius": 5},
        }
    )
    bad_step = tmp_path / "bad.step"
    bad_stl = tmp_path / "bad.stl"
    bad_step.write_bytes(b"not a step file at all")
    bad_stl.write_bytes(b"\x00\x01")

    def fake_export(operation, name="part", out_dir=None):
        return {
            "operation": "sphere",
            "step_path": str(bad_step),
            "stl_path": str(bad_stl),
        }

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    monkeypatch.setattr("app.services.generation.cadquery_engine.export_operation", fake_export)
    r = client.post("/generate", json={"prompt": "corrupt"})
    assert r.status_code == 500, r.text
    assert "validation failed" in r.json()["detail"]
    assert "Traceback" not in r.text


def test_request_ids_unique_per_request(monkeypatch, tmp_path):
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "cube",
            "operation": {"type": "box", "width": 10, "depth": 10, "height": 10},
        }
    )
    step_path, stl_path = _write_valid_pair(tmp_path, stem="rid_tmp")

    def fake_export(*, width, depth, height):
        # Re-materialize: the service renames exports to the public stem.
        _write_valid_pair(tmp_path, stem="rid_tmp")
        return {"step_path": step_path, "stl_path": stl_path}

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    monkeypatch.setattr("app.services.generation.cadquery_engine.export_box", fake_export)
    first = client.post("/generate", json={"prompt": "one"}).json()["request_id"]
    second = client.post("/generate", json={"prompt": "two"}).json()["request_id"]
    assert first and second and first != second


# --- Milestone 7: POST /modify (all mocked, no CadQuery, no network) -------


BOX_SPEC = {
    "document_type": "3d_part",
    "units": "mm",
    "name": "rectangular_block",
    "operation": {"type": "box", "width": 100, "depth": 60, "height": 30},
}

MODIFIED_BOX_SPEC = {
    "document_type": "3d_part",
    "units": "mm",
    "name": "rectangular_block",
    "operation": {"type": "box", "width": 100, "depth": 60, "height": 80},
}

PART_WITH_HOLE_SPEC = {
    "document_type": "3d_part",
    "units": "mm",
    "name": "plate_with_hole",
    "operation": {
        "type": "part",
        "build": {"type": "box", "width": 100, "depth": 60, "height": 10},
        "features": [{"type": "hole", "diameter": 8, "through": True}],
    },
}

PART_WITH_LARGER_HOLE_SPEC = {
    "document_type": "3d_part",
    "units": "mm",
    "name": "plate_with_hole",
    "operation": {
        "type": "part",
        "build": {"type": "box", "width": 100, "depth": 60, "height": 10},
        "features": [{"type": "hole", "diameter": 12, "through": True}],
    },
}

PART_WITH_PATTERN_SPEC = {
    "document_type": "3d_part",
    "units": "mm",
    "name": "flange_plate",
    "operation": {
        "type": "part",
        "build": {"type": "cylinder", "radius": 50, "height": 15},
        "features": [
            {
                "type": "hole_pattern",
                "diameter": 8,
                "count": 4,
                "circle_diameter": 70,
                "through": True,
            }
        ],
    },
}

PART_WITH_6_HOLES_SPEC = {
    "document_type": "3d_part",
    "units": "mm",
    "name": "flange_plate",
    "operation": {
        "type": "part",
        "build": {"type": "cylinder", "radius": 50, "height": 15},
        "features": [
            {
                "type": "hole_pattern",
                "diameter": 8,
                "count": 6,
                "circle_diameter": 70,
                "through": True,
            }
        ],
    },
}

PART_WITH_BLIND_HOLE_SPEC = {
    "document_type": "3d_part",
    "units": "mm",
    "name": "plate_with_hole",
    "operation": {
        "type": "part",
        "build": {"type": "box", "width": 100, "depth": 60, "height": 10},
        "features": [{"type": "hole", "diameter": 8, "through": False, "depth": 5}],
    },
}


def _modify_fake_client(modified_spec_dict, captured=None):
    """Fake Groq client for modify_spec that returns a fixed modified spec."""
    content = json.dumps(modified_spec_dict, separators=(",", ":"))

    def create(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        msg = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


import json


def test_modify_dimension_change_mocked(monkeypatch, tmp_path):
    """M7: change a dimension (height 30 -> 80) through /modify."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    step_path, stl_path = _write_valid_pair(tmp_path, stem="modified_box")
    captured = {}

    monkeypatch.setattr(
        groq_client,
        "_get_client",
        lambda key: _modify_fake_client(MODIFIED_BOX_SPEC, captured),
    )
    monkeypatch.setattr(
        "app.services.generation.cadquery_engine.export_box",
        lambda **kw: {
            "step_path": step_path,
            "stl_path": stl_path,
            "step_bytes": 100,
            "stl_bytes": 200,
        },
    )

    r = client.post(
        "/modify",
        json={
            "specification": BOX_SPEC,
            "instruction": "Make the height 80mm instead of 30mm.",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["specification"]["operation"]["height"] == 80.0
    assert body["specification"]["operation"]["width"] == 100.0
    assert body["specification"]["operation"]["depth"] == 60.0
    assert body["files"]["step"]["download_url"].startswith("/download/")
    assert body["files"]["stl"]["download_url"].startswith("/download/")
    # Verify the modification system prompt was used
    system_msg = captured["messages"][0]["content"]
    assert "modify" in system_msg.lower()


def test_modify_hole_diameter_mocked(monkeypatch, tmp_path):
    """M7: change hole diameter from 8mm to 12mm."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    step_path, stl_path = _write_valid_pair(tmp_path, stem="modified_hole")
    captured = {}

    monkeypatch.setattr(
        groq_client,
        "_get_client",
        lambda key: _modify_fake_client(PART_WITH_LARGER_HOLE_SPEC, captured),
    )
    monkeypatch.setattr(
        "app.services.generation.cadquery_engine.export_operation",
        lambda op, name="part", **kw: {
            "operation": op.type,
            "step_path": step_path,
            "stl_path": stl_path,
            "step_bytes": 100,
            "stl_bytes": 200,
        },
    )

    r = client.post(
        "/modify",
        json={
            "specification": PART_WITH_HOLE_SPEC,
            "instruction": "Change the hole diameter from 8mm to 12mm.",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    features = body["specification"]["operation"]["features"]
    assert len(features) == 1
    assert features[0]["type"] == "hole"
    assert features[0]["diameter"] == 12.0


def test_modify_pattern_count_mocked(monkeypatch, tmp_path):
    """M7: change hole_pattern count from 4 to 6."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    step_path, stl_path = _write_valid_pair(tmp_path, stem="modified_pattern")
    captured = {}

    monkeypatch.setattr(
        groq_client,
        "_get_client",
        lambda key: _modify_fake_client(PART_WITH_6_HOLES_SPEC, captured),
    )
    monkeypatch.setattr(
        "app.services.generation.cadquery_engine.export_operation",
        lambda op, name="part", **kw: {
            "operation": op.type,
            "step_path": step_path,
            "stl_path": stl_path,
            "step_bytes": 100,
            "stl_bytes": 200,
        },
    )

    r = client.post(
        "/modify",
        json={
            "specification": PART_WITH_PATTERN_SPEC,
            "instruction": "Change to 6 holes instead of 4.",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    features = body["specification"]["operation"]["features"]
    assert features[0]["type"] == "hole_pattern"
    assert features[0]["count"] == 6


def test_modify_through_to_blind_mocked(monkeypatch, tmp_path):
    """M7: convert a through hole to a blind hole with 5mm depth."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    step_path, stl_path = _write_valid_pair(tmp_path, stem="blind_hole")
    captured = {}

    monkeypatch.setattr(
        groq_client,
        "_get_client",
        lambda key: _modify_fake_client(PART_WITH_BLIND_HOLE_SPEC, captured),
    )
    monkeypatch.setattr(
        "app.services.generation.cadquery_engine.export_operation",
        lambda op, name="part", **kw: {
            "operation": op.type,
            "step_path": step_path,
            "stl_path": stl_path,
            "step_bytes": 100,
            "stl_bytes": 200,
        },
    )

    r = client.post(
        "/modify",
        json={
            "specification": PART_WITH_HOLE_SPEC,
            "instruction": "Make the hole blind with a depth of 5mm.",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    features = body["specification"]["operation"]["features"]
    assert features[0]["through"] is False
    assert features[0]["depth"] == 5.0


def test_modify_empty_instruction_rejected(monkeypatch):
    """M7: empty instruction returns 400 without calling Groq."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Groq must not be called for an empty instruction")

    monkeypatch.setattr(groq_client, "modify_spec", fail_if_called)
    r = client.post("/modify", json={"specification": BOX_SPEC, "instruction": ""})
    assert r.status_code == 400, r.text
    r = client.post("/modify", json={"specification": BOX_SPEC, "instruction": "   "})
    assert r.status_code == 400, r.text


def test_modify_oversized_instruction_rejected(monkeypatch):
    """M7: instruction exceeding MAX_INSTRUCTION_LENGTH returns 400."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Groq must not be called for oversized instruction")

    monkeypatch.setattr(groq_client, "modify_spec", fail_if_called)
    r = client.post(
        "/modify",
        json={"specification": BOX_SPEC, "instruction": "x" * 2001},
    )
    assert r.status_code == 400, r.text


def test_modify_diff_guard_rejects_unrelated_change(monkeypatch):
    """M7: diff guard rejects modification that changes document_type."""
    from app.services.generation import ModificationRejectedError, validate_modification
    from app.cad.schema import CADSpec

    old = CADSpec.model_validate(BOX_SPEC)
    bad_new = CADSpec.model_validate(BOX_SPEC)
    # Force a change that the diff guard should catch
    # We'll test the validate_modification function directly
    # by creating a spec that changes constants
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    # Test the diff guard directly
    changed_spec = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "different_name",
        "operation": {"type": "box", "width": 100, "depth": 60, "height": 30},
    }
    new_spec = CADSpec.model_validate(changed_spec)
    try:
        validate_modification(old, new_spec, "just make it taller")
        assert False, "Should have raised ModificationRejectedError"
    except ModificationRejectedError:
        pass  # expected


def test_modify_preserves_unrelated_fields(monkeypatch, tmp_path):
    """M7: modification preserves width and depth when only height changes."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    step_path, stl_path = _write_valid_pair(tmp_path, stem="preserve_fields")

    monkeypatch.setattr(
        groq_client,
        "_get_client",
        lambda key: _modify_fake_client(MODIFIED_BOX_SPEC),
    )
    monkeypatch.setattr(
        "app.services.generation.cadquery_engine.export_box",
        lambda **kw: {
            "step_path": step_path,
            "stl_path": stl_path,
            "step_bytes": 100,
            "stl_bytes": 200,
        },
    )

    r = client.post(
        "/modify",
        json={"specification": BOX_SPEC, "instruction": "Make it taller"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    op = body["specification"]["operation"]
    assert op["width"] == 100.0, "width should be preserved"
    assert op["depth"] == 60.0, "depth should be preserved"
    assert op["height"] == 80.0, "height should be modified"


def test_modify_success_path_returns_same_contract_as_generate(monkeypatch, tmp_path):
    """M7: /modify returns the same response shape as /generate."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    step_path, stl_path = _write_valid_pair(tmp_path, stem="contract_check")

    monkeypatch.setattr(
        groq_client,
        "_get_client",
        lambda key: _modify_fake_client(MODIFIED_BOX_SPEC),
    )
    monkeypatch.setattr(
        "app.services.generation.cadquery_engine.export_box",
        lambda **kw: {
            "step_path": step_path,
            "stl_path": stl_path,
            "step_bytes": 100,
            "stl_bytes": 200,
        },
    )

    r = client.post(
        "/modify",
        json={"specification": BOX_SPEC, "instruction": "Make it taller"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Same contract as /generate
    assert body["status"] == "completed"
    assert isinstance(body["request_id"], str) and body["request_id"]
    assert body["units"] == "mm"
    assert body["generation_time_ms"] >= 0
    assert "step" in body["files"] and "stl" in body["files"]
    step_meta = body["files"]["step"]
    assert step_meta["format"] == "step"
    assert step_meta["filename"].endswith(".step")
    assert step_meta["bytes"] > 0
    assert step_meta["download_url"].startswith("/download/")


def test_modify_missing_api_key_is_server_error(monkeypatch):
    """M7: missing API key returns 500."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    r = client.post(
        "/modify",
        json={"specification": BOX_SPEC, "instruction": "Make it taller"},
    )
    assert r.status_code == 500, r.text
    assert "GROQ_API_KEY" in r.json()["detail"]


def test_modify_invalid_groq_json_is_bad_gateway(monkeypatch):
    """M7: non-JSON from Groq returns 502."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        groq_client, "_get_client", lambda key: make_fake_client("not json {{{")
    )
    r = client.post(
        "/modify",
        json={"specification": BOX_SPEC, "instruction": "Make it taller"},
    )
    assert r.status_code == 502, r.text


def test_modify_invalid_spec_from_model_is_422(monkeypatch):
    """M7: model returns invalid CADSpec returns 422."""
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    bad = (
        '{"document_type": "3d_part", "units": "mm", "name": "bad", '
        '"operation": {"type": "box", "width": -5, "depth": 60, "height": 30}}'
    )
    monkeypatch.setattr(groq_client, "_get_client", lambda key: make_fake_client(bad))
    r = client.post(
        "/modify",
        json={"specification": BOX_SPEC, "instruction": "Make it taller"},
    )
    assert r.status_code == 422, r.text
