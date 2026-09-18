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
    ):
        assert required in system_text


def test_generate_success_path_mocked(monkeypatch):
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "rectangular_block",
            "operation": {"type": "box", "width": 100, "depth": 60, "height": 30},
        }
    )
    seen = {}

    def fake_parse(prompt):
        seen["prompt"] = prompt
        return spec

    def fake_export(*, width, depth, height):
        seen["dims"] = (width, depth, height)
        return {"step_bytes": 1234, "stl_bytes": 5678}

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", fake_parse)
    monkeypatch.setattr("app.main.cadquery_engine.export_box", fake_export)

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
    assert body["files"] == {"step_bytes": 1234, "stl_bytes": 5678}
    assert seen["dims"] == (100.0, 60.0, 30.0)
    assert "format=step" in body["download"]["step"]
    assert "format=stl" in body["download"]["stl"]


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

    monkeypatch.setattr("app.main.cadquery_engine.export_box", fail_export)
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


def test_generate_cylinder_mocked(monkeypatch):
    spec = CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": "shaft",
            "operation": {"type": "cylinder", "radius": 15, "height": 120},
        }
    )
    seen = {}

    def fake_export(operation, name="part", out_dir=None):
        seen["op"] = operation
        seen["name"] = name
        return {
            "operation": "cylinder",
            "step_bytes": 111,
            "stl_bytes": 222,
            "step_path": "/tmp/x.step",
            "stl_path": "/tmp/x.stl",
        }

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    monkeypatch.setattr("app.main.cadquery_engine.export_operation", fake_export)

    r = client.post(
        "/generate",
        json={"prompt": "Create a cylinder 120mm tall with a diameter of 30mm."},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["specification"]["operation"]["type"] == "cylinder"
    assert body["files"] == {"step_bytes": 111, "stl_bytes": 222}
    assert seen["op"].radius == 15
    assert seen["name"] == "shaft"
    assert body["download"]["step"].startswith("/download/")
    assert body["download"]["stl"].startswith("/download/")


def test_generate_cut_mocked(monkeypatch):
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
        return {
            "operation": "cut",
            "step_bytes": 333,
            "stl_bytes": 444,
            "step_path": "/tmp/y.step",
            "stl_path": "/tmp/y.stl",
        }

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    monkeypatch.setattr("app.main.cadquery_engine.export_operation", fake_export)

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
    stl_file.write_bytes(b"solid fake stl")

    def fake_export(operation, name="part", out_dir=None):
        return {
            "operation": "sphere",
            "step_bytes": step_file.stat().st_size,
            "stl_bytes": stl_file.stat().st_size,
            "step_path": str(step_file),
            "stl_path": str(stl_file),
        }

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    monkeypatch.setattr("app.main.cadquery_engine.export_operation", fake_export)

    r = client.post("/generate", json={"prompt": "Create a sphere of radius 25mm."})
    assert r.status_code == 200, r.text
    links = r.json()["download"]

    dl = client.get(links["step"])
    assert dl.status_code == 200, dl.text
    assert b"ISO-10303" in dl.content
    dl = client.get(links["stl"])
    assert dl.status_code == 200, dl.text


def test_download_unknown_token_404():
    assert client.get("/download/does-not-exist?format=step").status_code == 404
