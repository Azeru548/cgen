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
    for required in ("JSON ONLY", "NEVER return Python", "ONLY \"box\"", "millimeters"):
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
