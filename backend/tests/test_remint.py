"""File revival tests: POST /remint (no Groq anywhere on this path).

/remint re-exports fresh STEP/STL files for an already-valid stored spec so
expired download links can be revived with one click. Unlike /rebuild it has
no diff guard: re-exporting an unchanged spec must succeed here where
/rebuild rejects it as a no-op.
"""

from fastapi.testclient import TestClient

from app.ai import groq_client
from app.main import app

client = TestClient(app)

BASE_BOX = {
    "document_type": "3d_part",
    "units": "mm",
    "name": "plate",
    "operation": {"type": "box", "width": 100, "depth": 60, "height": 20},
}


def _write_valid_pair(tmp_path, stem="part"):
    step = tmp_path / f"{stem}.step"
    stl = tmp_path / f"{stem}.stl"
    step.write_bytes(b"ISO-10303-21;\nFAKE STEP FOR TESTS\n")
    stl.write_bytes(b"solid test\nendsolid test\n")
    return str(step), str(stl)


def _no_groq(monkeypatch):
    """Prove the remint path needs no AI: every Groq entry point fails loudly."""

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Groq must not be called on /remint")

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", fail_if_called)
    monkeypatch.setattr(groq_client, "modify_spec", fail_if_called)
    monkeypatch.setattr(groq_client, "_get_client", fail_if_called)


def _fake_assembly_export(assembly, *, request_id, file_store, artifacts=None):
    from app.cad.assembly import resolve_relationships, validate_registry
    from app.services.generation import GeneratedFile, GenerationResult

    resolved = resolve_relationships(validate_registry(assembly))
    files = {
        "step": GeneratedFile("step", "a.step", 10, "/download/TOK?format=step"),
        "stl": GeneratedFile("stl", "a.stl", 20, "/download/TOK?format=stl"),
    }
    return GenerationResult(
        request_id=request_id,
        specification=resolved.model_dump(),
        units="mm",
        files=files,
        generation_time_ms=12,
        component_files={c.id: dict(files) for c in resolved.components},
    )


def test_remint_part_identical_spec_succeeds(monkeypatch, tmp_path):
    """The core revival property: an unchanged spec re-exports fine."""
    _no_groq(monkeypatch)
    step_path, stl_path = _write_valid_pair(tmp_path)

    def fake_export(*, width, depth, height):
        assert (width, depth, height) == (100, 60, 20)
        return {"step_path": step_path, "stl_path": stl_path}

    monkeypatch.setattr(
        "app.services.generation.cadquery_engine.export_box", fake_export
    )

    r = client.post("/remint", json={"specification": BASE_BOX})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["specification"] == BASE_BOX
    assert body["files"]["step"]["download_url"]
    assert body["files"]["stl"]["download_url"]


def test_remint_part_invalid_spec_is_422(monkeypatch):
    _no_groq(monkeypatch)
    bad = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "bad",
        "operation": {"type": "box", "width": -5, "depth": 60, "height": 20},
    }
    r = client.post("/remint", json={"specification": bad})
    assert r.status_code == 422, r.text


def test_remint_garbage_is_422(monkeypatch):
    _no_groq(monkeypatch)
    r = client.post("/remint", json={"specification": {"nonsense": True}})
    assert r.status_code == 422, r.text


def test_remint_assembly_identical_spec_succeeds(monkeypatch):
    """Assemblies re-export as-is with per-component files, no no-op rejection."""
    _no_groq(monkeypatch)
    monkeypatch.setattr(
        "app.services.assembly.export_assembly_document", _fake_assembly_export
    )

    # Build a valid stored spec through the deterministic assembly path.
    added = client.post(
        "/assembly/add",
        json={
            "component_type": "box",
            "parameters": {"width": 40, "depth": 20, "height": 10},
        },
    )
    assert added.status_code == 200, added.text
    stored = added.json()["specification"]

    # /rebuild rejects the unchanged spec as a no-op...
    rebuilt = client.post(
        "/rebuild", json={"base_specification": stored, "specification": stored}
    )
    assert rebuilt.status_code == 422, rebuilt.text

    # ...while /remint re-exports it with fresh files.
    r = client.post("/remint", json={"specification": stored})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["specification"]["document_type"] == "3d_assembly"
    assert "box_1" in body["component_files"]


def test_remint_assembly_unknown_type_is_422(monkeypatch):
    _no_groq(monkeypatch)
    spec = {
        "document_type": "3d_assembly",
        "units": "mm",
        "name": "kit",
        "components": [
            {
                "id": "box_1",
                "component_type": "flux_capacitor",
                "name": "Box",
                "parameters": {},
                "transform": {"position": [0, 0, 0], "rotation": [0, 0, 0]},
                "visible": True,
                "instances": [],
                "relationships": [],
            }
        ],
    }
    r = client.post("/remint", json={"specification": spec})
    assert r.status_code == 422, r.text
