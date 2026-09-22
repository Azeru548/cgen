"""Milestone 9 assembly HTTP API (Groq mocked, CadQuery export mocked)."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.ai import groq_client
from app.cad.assembly import AssemblySpec, ComponentInstance
from app.main import app

client = TestClient(app)


def _fake_export(assembly, *, request_id, file_store):
    from app.cad.assembly import resolve_relationships, validate_registry
    from app.services.generation import GeneratedFile, GenerationResult

    resolved = resolve_relationships(validate_registry(assembly))
    files = {
        "step": GeneratedFile("step", "a.step", 10, "/download/TOK?format=step"),
        "stl": GeneratedFile("stl", "a.stl", 20, "/download/TOK?format=stl"),
    }
    component_files = {
        c.id: dict(files) for c in resolved.components
    }
    return GenerationResult(
        request_id=request_id,
        specification=resolved.model_dump(),
        units="mm",
        files=files,
        generation_time_ms=12,
        component_files=component_files,
    )


def test_get_components_catalog():
    r = client.get("/components")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["schema_version"] == "4.0"
    types = {c["type"] for c in body["components"]}
    assert "m3_screw" in types
    assert "arduino_uno" in types
    assert "enclosure" in types
    m3 = next(c for c in body["components"] if c["type"] == "m3_screw")
    assert m3["insertable"] is True
    assert m3["category"] == "fasteners"


def test_assembly_add_unknown_type_is_422(monkeypatch):
    monkeypatch.setattr(
        "app.services.assembly.export_assembly_document", _fake_export
    )
    r = client.post(
        "/assembly/add",
        json={"component_type": "flux_capacitor", "count": 1},
    )
    assert r.status_code == 422
    assert "Unknown component type" in r.json()["detail"]


def test_assembly_add_box(monkeypatch):
    monkeypatch.setattr(
        "app.services.assembly.export_assembly_document", _fake_export
    )
    r = client.post(
        "/assembly/add",
        json={
            "component_type": "box",
            "parameters": {"width": 40, "depth": 20, "height": 10},
        },
    )
    assert r.status_code == 200, r.text
    spec = r.json()["specification"]
    assert spec["document_type"] == "3d_assembly"
    assert spec["components"][0]["component_type"] == "box"
    assert spec["components"][0]["parameters"]["width"] == 40
    assert "box_1" in r.json()["component_files"]


def test_assembly_add_four_screws_uses_instances(monkeypatch):
    monkeypatch.setattr(
        "app.services.assembly.export_assembly_document", _fake_export
    )
    r = client.post(
        "/assembly/add",
        json={"component_type": "m3_screw", "count": 4},
    )
    assert r.status_code == 200, r.text
    screws = r.json()["specification"]["components"][0]
    assert screws["component_type"] == "m3_screw"
    assert len(screws["instances"]) == 4


def test_assembly_add_promotes_existing_part(monkeypatch):
    monkeypatch.setattr(
        "app.services.assembly.export_assembly_document", _fake_export
    )
    part = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "block",
        "operation": {"type": "box", "width": 100, "depth": 60, "height": 30},
    }
    r = client.post(
        "/assembly/add",
        json={"specification": part, "component_type": "cylinder"},
    )
    assert r.status_code == 200, r.text
    types = [c["component_type"] for c in r.json()["specification"]["components"]]
    assert types == ["generated_part", "cylinder"]


def test_assembly_remove(monkeypatch):
    monkeypatch.setattr(
        "app.services.assembly.export_assembly_document", _fake_export
    )
    spec = AssemblySpec(
        name="two",
        components=[
            ComponentInstance(
                id="box_1",
                component_type="box",
                name="Box",
                parameters={"width": 10, "depth": 10, "height": 10},
            ),
            ComponentInstance(
                id="sphere_1",
                component_type="sphere",
                name="Sphere",
                parameters={"radius": 5},
            ),
        ],
    )
    r = client.post(
        "/assembly/remove",
        json={"specification": spec.model_dump(), "component_id": "sphere_1"},
    )
    assert r.status_code == 200, r.text
    ids = [c["id"] for c in r.json()["specification"]["components"]]
    assert ids == ["box_1"]


def test_assembly_remove_last_object_rejected(monkeypatch):
    monkeypatch.setattr(
        "app.services.assembly.export_assembly_document", _fake_export
    )
    spec = AssemblySpec(
        name="one",
        components=[
            ComponentInstance(
                id="box_1",
                component_type="box",
                name="Box",
                parameters={"width": 10, "depth": 10, "height": 10},
            )
        ],
    )
    r = client.post(
        "/assembly/remove",
        json={"specification": spec.model_dump(), "component_id": "box_1"},
    )
    assert r.status_code == 422
    assert "last object" in r.json()["detail"]


def test_assembly_update_length(monkeypatch):
    monkeypatch.setattr(
        "app.services.assembly.export_assembly_document", _fake_export
    )
    spec = AssemblySpec(
        name="s",
        components=[
            ComponentInstance(
                id="m3_screw_1",
                component_type="m3_screw",
                name="M3",
                parameters={"length": 12},
            )
        ],
    )
    r = client.post(
        "/assembly/update",
        json={
            "specification": spec.model_dump(),
            "component_id": "m3_screw_1",
            "parameters": {"length": 16},
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["specification"]["components"][0]["parameters"]["length"] == 16


def test_assembly_update_missing_id(monkeypatch):
    monkeypatch.setattr(
        "app.services.assembly.export_assembly_document", _fake_export
    )
    spec = AssemblySpec(
        name="s",
        components=[
            ComponentInstance(
                id="box_1",
                component_type="box",
                name="Box",
                parameters={"width": 10, "depth": 10, "height": 10},
            )
        ],
    )
    r = client.post(
        "/assembly/update",
        json={
            "specification": spec.model_dump(),
            "component_id": "nope",
            "visible": False,
        },
    )
    assert r.status_code == 422


def test_generate_assembly_plan(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "sk-test")
    plan = {
        "document_type": "3d_assembly",
        "units": "mm",
        "name": "arduino_enclosure",
        "schema_version": "4.0",
        "components": [
            {
                "id": "enclosure_1",
                "component_type": "enclosure",
                "name": "Enclosure",
                "parameters": {
                    "width": 90,
                    "depth": 70,
                    "height": 40,
                    "wall_thickness": 2.5,
                    "board": "arduino_uno",
                    "usb_cutout": True,
                },
                "transform": {"position": [0, 0, 0], "rotation": [0, 0, 0]},
                "visible": True,
                "instances": [],
                "relationships": [],
            },
            {
                "id": "arduino_1",
                "component_type": "arduino_uno",
                "name": "Arduino Uno",
                "parameters": {},
                "transform": {"position": [0, 0, 8], "rotation": [0, 0, 0]},
                "visible": True,
                "instances": [],
                "relationships": [
                    {"type": "centered_on", "target_id": "enclosure_1"}
                ],
            },
            {
                "id": "screws_1",
                "component_type": "m3_screw",
                "name": "M3 screws",
                "parameters": {"length": 12},
                "transform": {"position": [0, 0, 0], "rotation": [0, 0, 0]},
                "visible": True,
                "instances": [],
                "relationships": [
                    {"type": "mounted_on", "target_id": "arduino_1"}
                ],
            },
        ],
    }

    def create(**kwargs):
        import json

        msg = SimpleNamespace(content=json.dumps(plan))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(groq_client, "_get_client", lambda key: fake)
    monkeypatch.setattr(
        "app.services.assembly.export_assembly_document", _fake_export
    )
    r = client.post(
        "/generate",
        json={
            "prompt": "Create an enclosure for an Arduino Uno with four M3 mounting screws and a USB opening."
        },
    )
    assert r.status_code == 200, r.text
    spec = r.json()["specification"]
    assert spec["document_type"] == "3d_assembly"
    types = {c["component_type"] for c in spec["components"]}
    assert types == {"enclosure", "arduino_uno", "m3_screw"}
    screws = next(c for c in spec["components"] if c["component_type"] == "m3_screw")
    assert len(screws["instances"]) == 4


def test_generate_rejects_invented_component_type(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "sk-test")
    plan = {
        "document_type": "3d_assembly",
        "units": "mm",
        "name": "bad",
        "schema_version": "4.0",
        "components": [
            {
                "id": "magic_1",
                "component_type": "magic_widget",
                "name": "Magic",
                "parameters": {},
                "transform": {"position": [0, 0, 0], "rotation": [0, 0, 0]},
                "visible": True,
                "instances": [],
                "relationships": [],
            }
        ],
    }

    def create(**kwargs):
        import json

        msg = SimpleNamespace(content=json.dumps(plan))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    fake = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )
    monkeypatch.setattr(groq_client, "_get_client", lambda key: fake)
    r = client.post("/generate", json={"prompt": "Make a magic widget assembly."})
    assert r.status_code == 422
    assert "Unknown component type" in r.json()["detail"] or "component_type" in r.json()["detail"]


def test_export_assembly_document_calls_export_solid_with_optional_out_dir(monkeypatch, tmp_path):
    """Regression: _export_solid(solid, stem) used to TypeError without out_dir."""
    from app.cad import cadquery_engine
    from app.services.assembly import export_assembly_document
    from app.services.file_store import FileStore

    calls: list[tuple] = []

    def fake_export_solid(solid, stem, out_dir=None):
        calls.append((stem, out_dir))
        step = tmp_path / f"{stem}.step"
        stl = tmp_path / f"{stem}.stl"
        step.write_bytes(b"ISO-10303-21;")
        stl.write_bytes(b"solid x\nendsolid x\n")
        return {
            "step_path": str(step),
            "stl_path": str(stl),
            "step_bytes": step.stat().st_size,
            "stl_bytes": stl.stat().st_size,
        }

    monkeypatch.setattr(cadquery_engine, "_export_solid", fake_export_solid)
    monkeypatch.setattr(cadquery_engine, "apply_transform", lambda s, p, r: s)
    monkeypatch.setattr(
        cadquery_engine,
        "export_solids",
        lambda solids, stem, out_dir=None: fake_export_solid(solids, stem, out_dir),
    )
    monkeypatch.setattr(
        cadquery_engine, "validate_exported_files", lambda *a, **k: {"ok": True}
    )
    monkeypatch.setattr(
        "app.services.assembly._build_local_solid", lambda component: object()
    )

    spec = AssemblySpec(
        name="kit",
        components=[
            ComponentInstance(
                id="box_1",
                component_type="box",
                name="Box",
                parameters={"width": 10, "depth": 10, "height": 10},
            )
        ],
    )
    result = export_assembly_document(
        spec, request_id="req", file_store=FileStore()
    )
    assert result.specification["document_type"] == "3d_assembly"
    assert "box_1" in result.component_files
    assert calls, "expected _export_solid to be invoked"
    assert all(len(c) == 2 for c in calls)
