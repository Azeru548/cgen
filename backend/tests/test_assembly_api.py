"""Milestone 9 assembly HTTP API (Groq mocked, CadQuery export mocked)."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.ai import groq_client
from app.cad.assembly import AssemblySpec, ComponentInstance, Transform
from app.cad.schema import CADSpec
from app.main import app

client = TestClient(app)


def _fake_export(assembly, *, request_id, file_store, artifacts=None, **_kwargs):
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
    assert body["schema_version"] == "4.1"
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


def test_assembly_update_lock(monkeypatch):
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
            "component_id": "box_1",
            "locked": True,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["specification"]["components"][0]["locked"] is True


def test_rebuild_allows_grouping_generated_parts(monkeypatch):
    """Group/lock only change assembly metadata; nested parts stay identical."""
    monkeypatch.setattr(
        "app.services.assembly.export_assembly_document", _fake_export
    )
    box = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "block",
        "operation": {"type": "box", "width": 40, "depth": 40, "height": 20},
    }
    spec = AssemblySpec(
        name="two",
        schema_version="4.1",
        components=[
            ComponentInstance(
                id="generated_part_1",
                component_type="generated_part",
                name="Block",
                generated=CADSpec.model_validate(box),
            ),
            ComponentInstance(
                id="generated_part_2",
                component_type="generated_part",
                name="Block 2",
                generated=CADSpec.model_validate({**box, "name": "block_2"}),
            ),
        ],
    )
    updated = spec.model_dump()
    updated["groups"] = [
        {
            "id": "group_1",
            "name": "Pair",
            "component_ids": ["generated_part_1", "generated_part_2"],
        }
    ]
    updated["components"][0]["locked"] = True
    r = client.post(
        "/rebuild",
        json={
            "base_specification": spec.model_dump(),
            "specification": updated,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()["specification"]
    assert body["groups"][0]["id"] == "group_1"
    assert body["components"][0]["locked"] is True


def test_assembly_remove_prunes_groups(monkeypatch):
    monkeypatch.setattr(
        "app.services.assembly.export_assembly_document", _fake_export
    )
    spec = AssemblySpec(
        name="two",
        schema_version="4.1",
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
            ComponentInstance(
                id="cyl_1",
                component_type="cylinder",
                name="Cylinder",
                parameters={"radius": 5, "height": 20},
            ),
        ],
        groups=[
            {
                "id": "group_1",
                "name": "Pair",
                "component_ids": ["box_1", "sphere_1"],
            }
        ],
    )
    r = client.post(
        "/assembly/remove",
        json={"specification": spec.model_dump(), "component_id": "sphere_1"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["specification"]["groups"] == []


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


def _file_pair(url: str):
    from app.services.generation import GeneratedFile

    return {
        "step": GeneratedFile("step", "a.step", 10, f"{url}?format=step"),
        "stl": GeneratedFile("stl", "a.stl", 20, f"{url}?format=stl"),
    }


def test_reusable_ids_ignore_pose_name_and_lock():
    from app.services.assembly import geometry_signature, reusable_ids

    box = ComponentInstance(
        id="box_1",
        component_type="box",
        name="Box",
        parameters={"width": 10, "depth": 10, "height": 10},
    )
    moved = box.model_copy(
        update={
            "name": "Moved",
            "locked": True,
            "transform": Transform(position=(40.0, 0.0, 0.0), rotation=(0.0, 0.0, 90.0)),
        }
    )
    assert geometry_signature(box) == geometry_signature(moved)
    available = {"box_1": _file_pair("/download/box")}
    assert reusable_ids([box], [moved], available) == {"box_1"}
    taller = moved.model_copy(
        update={"parameters": {"width": 10, "depth": 10, "height": 20}}
    )
    assert reusable_ids([box], [taller], available) == set()


def _stub_export(monkeypatch, tmp_path):
    from app.cad import cadquery_engine

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
    return calls


def test_export_reuses_unchanged_solids(monkeypatch, tmp_path):
    from app.services.assembly import export_assembly_document
    from app.services.file_store import FileStore

    calls = _stub_export(monkeypatch, tmp_path)
    box = ComponentInstance(
        id="box_1",
        component_type="box",
        name="Box",
        parameters={"width": 10, "depth": 10, "height": 10},
    )
    sphere = ComponentInstance(
        id="sphere_1",
        component_type="sphere",
        name="Sphere",
        parameters={"radius": 5},
    )
    moved = box.model_copy(
        update={"transform": Transform(position=(50.0, 0.0, 0.0))}
    )
    result = export_assembly_document(
        AssemblySpec(name="kit", components=[moved, sphere]),
        request_id="req",
        file_store=FileStore(),
        previous_components=[box, sphere],
        reuse_component_files={
            "box_1": _file_pair("/download/box"),
            "sphere_1": _file_pair("/download/sphere"),
        },
        reuse_combined_files=_file_pair("/download/combined"),
    )
    assert calls == []
    assert result.component_files["box_1"]["stl"].download_url == "/download/box?format=stl"
    assert result.files["step"].download_url == "/download/combined?format=step"


def test_export_rebuilds_only_new_component(monkeypatch, tmp_path):
    from app.services.assembly import export_assembly_document
    from app.services.file_store import FileStore

    calls = _stub_export(monkeypatch, tmp_path)
    box = ComponentInstance(
        id="box_1",
        component_type="box",
        name="Box",
        parameters={"width": 10, "depth": 10, "height": 10},
    )
    cylinder = ComponentInstance(
        id="cylinder_1",
        component_type="cylinder",
        name="Cylinder",
        parameters={"radius": 5, "height": 20},
    )
    result = export_assembly_document(
        AssemblySpec(name="kit", components=[box, cylinder]),
        request_id="req",
        file_store=FileStore(),
        previous_components=[box],
        reuse_component_files={"box_1": _file_pair("/download/box")},
        reuse_combined_files=_file_pair("/download/combined"),
    )
    stems = [stem for stem, _ in calls]
    assert any("cylinder_1" in stem for stem in stems)
    assert not any("box_1" in stem for stem in stems)
    assert result.component_files["box_1"]["stl"].download_url == "/download/box?format=stl"
    assert "cylinder_1" in result.component_files


def test_assembly_add_forwards_prior_files(monkeypatch):
    seen: dict = {}

    def fake(assembly, *, request_id, file_store, artifacts=None, **kwargs):
        seen.update(kwargs)
        return _fake_export(
            assembly,
            request_id=request_id,
            file_store=file_store,
            artifacts=artifacts,
            **kwargs,
        )

    monkeypatch.setattr("app.services.assembly.export_assembly_document", fake)
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
    files = {
        "step": {
            "format": "step",
            "filename": "a.step",
            "bytes": 10,
            "download_url": "/download/box?format=step",
        },
        "stl": {
            "format": "stl",
            "filename": "a.stl",
            "bytes": 20,
            "download_url": "/download/box?format=stl",
        },
    }
    r = client.post(
        "/assembly/add",
        json={
            "specification": spec.model_dump(),
            "component_type": "sphere",
            "component_files": {"box_1": files},
            "files": files,
        },
    )
    assert r.status_code == 200, r.text
    assert "box_1" in seen["reuse_component_files"]
    assert seen["reuse_combined_files"]["stl"].download_url == "/download/box?format=stl"


def test_parameter_change_rebuilds_combined_downloads(monkeypatch, tmp_path):
    """A changed solid must refresh the combined STEP/STL, not just its own STL."""
    from app.services.assembly import export_assembly_document
    from app.services.file_store import FileStore

    calls = _stub_export(monkeypatch, tmp_path)
    box = ComponentInstance(
        id="box_1",
        component_type="box",
        name="Box",
        parameters={"width": 30, "depth": 30, "height": 10},
    )
    taller = box.model_copy(
        update={"parameters": {"width": 30, "depth": 30, "height": 20}}
    )
    result = export_assembly_document(
        AssemblySpec(name="kit", components=[taller]),
        request_id="req",
        file_store=FileStore(),
        previous_components=[box],
        reuse_component_files={"box_1": _file_pair("/download/box")},
        reuse_combined_files=_file_pair("/download/combined"),
    )
    stems = [stem for stem, _ in calls]
    assert any("box_1" in stem for stem in stems)
    assert "kit" in stems, "combined export must run when a solid changed"
    assert result.files["step"].download_url != "/download/combined?format=step"


def test_add_rebuilds_combined_downloads(monkeypatch, tmp_path):
    from app.services.assembly import export_assembly_document
    from app.services.file_store import FileStore

    calls = _stub_export(monkeypatch, tmp_path)
    box = ComponentInstance(
        id="box_1",
        component_type="box",
        name="Box",
        parameters={"width": 30, "depth": 30, "height": 10},
    )
    cylinder = ComponentInstance(
        id="cylinder_1",
        component_type="cylinder",
        name="Cylinder",
        parameters={"radius": 5, "height": 20},
    )
    result = export_assembly_document(
        AssemblySpec(name="kit", components=[box, cylinder]),
        request_id="req",
        file_store=FileStore(),
        previous_components=[box],
        reuse_component_files={"box_1": _file_pair("/download/box")},
        reuse_combined_files=_file_pair("/download/combined"),
    )
    stamps = [stem for stem, _ in calls]
    assert not any("box_1" in stem for stem in stamps)
    assert any("cylinder_1" in stem for stem in stamps)
    assert "kit" in stamps
    assert result.files["stl"].download_url != "/download/combined?format=stl"


def test_combined_files_reused_only_when_nothing_rebuilt(monkeypatch, tmp_path):
    """Pose/name/lock/group edits stay free: no component and no combined export."""
    from app.services.assembly import export_assembly_document
    from app.services.file_store import FileStore

    calls = _stub_export(monkeypatch, tmp_path)
    box = ComponentInstance(
        id="box_1",
        component_type="box",
        name="Box",
        parameters={"width": 30, "depth": 30, "height": 10},
    )
    moved = box.model_copy(
        update={
            "name": "Moved",
            "locked": True,
            "transform": Transform(position=(40.0, 0.0, 0.0), rotation=(0.0, 0.0, 90.0)),
        }
    )
    result = export_assembly_document(
        AssemblySpec(name="kit", components=[moved]),
        request_id="req",
        file_store=FileStore(),
        previous_components=[box],
        reuse_component_files={"box_1": _file_pair("/download/box")},
        reuse_combined_files=_file_pair("/download/combined"),
    )
    assert calls == []
    assert result.files["step"].download_url == "/download/combined?format=step"
    assert result.component_files["box_1"]["stl"].download_url == "/download/box?format=stl"


# --- motion metadata (schema 4.1, viewer only) --------------------------------


def _two_part_assembly(animation=None):
    box = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "block",
        "operation": {"type": "box", "width": 40, "depth": 40, "height": 20},
    }
    return AssemblySpec(
        name="animated",
        schema_version="4.1",
        components=[
            ComponentInstance(
                id="generated_part_1",
                component_type="generated_part",
                name="Block",
                generated=CADSpec.model_validate(box),
            ),
            ComponentInstance(
                id="generated_part_2",
                component_type="generated_part",
                name="Block 2",
                generated=CADSpec.model_validate({**box, "name": "block_2"}),
            ),
        ],
        animation=animation
        if animation is not None
        else {
            "duration": 4.0,
            "tracks": [
                {
                    "component_id": "generated_part_1",
                    "keys": [
                        {"t": 0.0, "position": [0, 0, 0]},
                        {"t": 2.0, "position": [0, 0, 40], "rotation": [0, 0, 90]},
                    ],
                }
            ],
        },
    )


def test_motion_keys_are_sorted_on_validation():
    spec = _two_part_assembly()
    track = spec.animation.tracks[0]
    assert [key.t for key in track.keys] == [0.0, 2.0]
    key = track.keys[1]
    assert key.position == (0.0, 0.0, 40.0)
    assert key.rotation == (0.0, 0.0, 90.0)


def test_motion_rejects_unknown_component():
    with pytest.raises(Exception, match="missing component"):
        _two_part_assembly(
            animation={
                "duration": 4.0,
                "tracks": [
                    {
                        "component_id": "nope_1",
                        "keys": [{"t": 0.0}],
                    }
                ],
            }
        )


def test_motion_rejects_key_past_duration():
    with pytest.raises(Exception, match="past the"):
        _two_part_assembly(
            animation={
                "duration": 1.0,
                "tracks": [
                    {
                        "component_id": "generated_part_1",
                        "keys": [{"t": 0.0}, {"t": 5.0}],
                    }
                ],
            }
        )


def test_motion_rejects_duplicate_key_times():
    with pytest.raises(Exception, match="same time"):
        _two_part_assembly(
            animation={
                "duration": 4.0,
                "tracks": [
                    {
                        "component_id": "generated_part_1",
                        "keys": [{"t": 1.0}, {"t": 1.0}],
                    }
                ],
            }
        )


def test_rebuild_keeps_motion_metadata(monkeypatch):
    monkeypatch.setattr(
        "app.services.assembly.export_assembly_document", _fake_export
    )
    spec = _two_part_assembly()
    # The stored revision predates the animation; adding motion is not a
    # geometry change, so the rebuild must keep the new metadata as given.
    base = spec.model_copy(update={"animation": None})
    r = client.post(
        "/rebuild",
        json={
            "base_specification": base.model_dump(),
            "specification": spec.model_dump(),
        },
    )
    assert r.status_code == 200, r.text
    animation = r.json()["specification"]["animation"]
    assert animation["duration"] == 4.0
    assert animation["tracks"][0]["component_id"] == "generated_part_1"
    assert len(animation["tracks"][0]["keys"]) == 2
