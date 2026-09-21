"""Milestone 8.1 tests: POST /rebuild (no Groq anywhere on this path).

The success path mocks the CAD exporter (CadQuery only exists in
cloud/Docker); one invalid-geometry test uses the real engine to prove
end-to-end rejection. Every test asserts Groq is never touched.
"""

import pytest
from fastapi.testclient import TestClient

from app.ai import groq_client
from app.cad.schema import CADSpec
from app.main import app

client = TestClient(app)

BASE_BOX = {
    "document_type": "3d_part",
    "units": "mm",
    "name": "plate",
    "operation": {"type": "box", "width": 100, "depth": 60, "height": 20},
}

BASE_PART = {
    "document_type": "3d_part",
    "units": "mm",
    "name": "plate_with_hole",
    "operation": {
        "type": "part",
        "build": {"type": "box", "width": 100, "depth": 60, "height": 20},
        "features": [
            {"type": "hole", "diameter": 10, "through": True},
            {"type": "fillet", "radius": 2},
        ],
    },
}


def _write_valid_pair(tmp_path, stem="part"):
    step = tmp_path / f"{stem}.step"
    stl = tmp_path / f"{stem}.stl"
    step.write_bytes(b"ISO-10303-21;\nFAKE STEP FOR TESTS\n")
    stl.write_bytes(b"solid test\nendsolid test\n")
    return str(step), str(stl)


def _no_groq(monkeypatch):
    """Prove the rebuild path needs no AI: no key, and every Groq entry
    point fails loudly if touched."""

    def fail_if_called(*args, **kwargs):
        raise AssertionError("Groq must not be called on /rebuild")

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", fail_if_called)
    monkeypatch.setattr(groq_client, "modify_spec", fail_if_called)
    monkeypatch.setattr(groq_client, "_get_client", fail_if_called)


def _mock_box_export(monkeypatch, tmp_path, seen, stem="rebuild_tmp"):
    step_path, stl_path = _write_valid_pair(tmp_path, stem=stem)

    def fake_export(*, width, depth, height):
        seen["dims"] = (width, depth, height)
        return {"step_path": step_path, "stl_path": stl_path}

    monkeypatch.setattr(
        "app.services.generation.cadquery_engine.export_box", fake_export
    )


def _mock_op_export(monkeypatch, tmp_path, seen, stem="rebuild_tmp"):
    step_path, stl_path = _write_valid_pair(tmp_path, stem=stem)

    def fake_export(operation, name="part", out_dir=None):
        seen["op"] = operation
        seen["name"] = name
        return {"step_path": step_path, "stl_path": stl_path}

    monkeypatch.setattr(
        "app.services.generation.cadquery_engine.export_operation", fake_export
    )


def _edited_box(**dims):
    spec = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "plate",
        "operation": {"type": "box", "width": 100, "depth": 60, "height": 20},
    }
    spec["operation"].update(dims)
    return spec


def test_rebuild_box_width_succeeds(monkeypatch, tmp_path):
    _no_groq(monkeypatch)
    seen = {}
    _mock_box_export(monkeypatch, tmp_path, seen)
    r = client.post(
        "/rebuild",
        json={"base_specification": BASE_BOX, "specification": _edited_box(width=120)},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["specification"]["operation"]["width"] == 120.0
    assert seen["dims"] == (120.0, 60.0, 20.0)
    assert body["files"]["step"]["download_url"].startswith("/download/")
    assert isinstance(body["request_id"], str) and body["request_id"]


def test_rebuild_box_height_succeeds(monkeypatch, tmp_path):
    _no_groq(monkeypatch)
    seen = {}
    _mock_box_export(monkeypatch, tmp_path, seen)
    r = client.post(
        "/rebuild",
        json={"base_specification": BASE_BOX, "specification": _edited_box(height=25)},
    )
    assert r.status_code == 200, r.text
    assert r.json()["specification"]["operation"]["height"] == 25.0
    assert seen["dims"] == (100.0, 60.0, 25.0)


def test_rebuild_cylinder_radius_succeeds(monkeypatch, tmp_path):
    _no_groq(monkeypatch)
    seen = {}
    _mock_op_export(monkeypatch, tmp_path, seen)
    base = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "shaft",
        "operation": {"type": "cylinder", "radius": 15, "height": 120},
    }
    edited = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "shaft",
        "operation": {"type": "cylinder", "radius": 18, "height": 120},
    }
    r = client.post(
        "/rebuild", json={"base_specification": base, "specification": edited}
    )
    assert r.status_code == 200, r.text
    assert r.json()["specification"]["operation"]["radius"] == 18.0
    assert seen["op"].radius == 18.0


def _edited_part(monkeypatch, tmp_path, seen, feature_index, **fields):
    import copy

    _no_groq(monkeypatch)
    _mock_op_export(monkeypatch, tmp_path, seen)
    edited = copy.deepcopy(BASE_PART)
    edited["operation"]["features"][feature_index].update(fields)
    return client.post(
        "/rebuild", json={"base_specification": BASE_PART, "specification": edited}
    )


def test_rebuild_hole_diameter_succeeds(monkeypatch, tmp_path):
    seen = {}
    r = _edited_part(monkeypatch, tmp_path, seen, 0, diameter=14)
    assert r.status_code == 200, r.text
    feats = r.json()["specification"]["operation"]["features"]
    assert feats[0]["diameter"] == 14.0
    assert feats[1] == {"type": "fillet", "radius": 2.0}


def test_rebuild_blind_hole_depth_succeeds(monkeypatch, tmp_path):
    import copy

    _no_groq(monkeypatch)
    seen = {}
    _mock_op_export(monkeypatch, tmp_path, seen)
    base = copy.deepcopy(BASE_PART)
    base["operation"]["features"][0] = {
        "type": "hole",
        "diameter": 10,
        "through": False,
        "depth": 8,
    }
    edited = copy.deepcopy(base)
    edited["operation"]["features"][0]["depth"] = 12
    r = client.post(
        "/rebuild", json={"base_specification": base, "specification": edited}
    )
    assert r.status_code == 200, r.text
    assert r.json()["specification"]["operation"]["features"][0]["depth"] == 12.0


def test_rebuild_fillet_radius_succeeds(monkeypatch, tmp_path):
    seen = {}
    r = _edited_part(monkeypatch, tmp_path, seen, 1, radius=5)
    assert r.status_code == 200, r.text
    feats = r.json()["specification"]["operation"]["features"]
    assert feats[1]["radius"] == 5.0
    assert feats[0]["diameter"] == 10.0


def _rejects(monkeypatch, base, edited, fragment):
    _no_groq(monkeypatch)
    r = client.post(
        "/rebuild", json={"base_specification": base, "specification": edited}
    )
    assert r.status_code == 422, r.text
    assert fragment in r.json()["detail"]
    return r


def test_rebuild_rejects_primitive_type_change(monkeypatch):
    import copy

    edited = copy.deepcopy(BASE_BOX)
    edited["operation"] = {"type": "cylinder", "radius": 15, "height": 120}
    _rejects(monkeypatch, BASE_BOX, edited, "operation structure")


def test_rebuild_rejects_feature_type_change(monkeypatch):
    import copy

    edited = copy.deepcopy(BASE_PART)
    edited["operation"]["features"][1] = {"type": "chamfer", "size": 2}
    _rejects(monkeypatch, BASE_PART, edited, "feature list")


def test_rebuild_rejects_feature_addition(monkeypatch):
    import copy

    edited = copy.deepcopy(BASE_PART)
    edited["operation"]["features"].append({"type": "chamfer", "size": 1})
    _rejects(monkeypatch, BASE_PART, edited, "feature list")


def test_rebuild_rejects_feature_removal(monkeypatch):
    import copy

    edited = copy.deepcopy(BASE_PART)
    edited["operation"]["features"] = edited["operation"]["features"][:1]
    _rejects(monkeypatch, BASE_PART, edited, "feature list")


def test_rebuild_rejects_feature_reorder(monkeypatch):
    import copy

    edited = copy.deepcopy(BASE_PART)
    edited["operation"]["features"] = list(
        reversed(edited["operation"]["features"])
    )
    _rejects(monkeypatch, BASE_PART, edited, "feature list")


def test_rebuild_rejects_hole_count_change(monkeypatch):
    base = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "flange",
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
    import copy

    edited = copy.deepcopy(base)
    edited["operation"]["features"][0]["count"] = 6
    _rejects(monkeypatch, base, edited, "non-numeric")


def test_rebuild_rejects_grid_rows_change(monkeypatch):
    base = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "plate",
        "operation": {
            "type": "part",
            "build": {"type": "box", "width": 120, "depth": 80, "height": 10},
            "features": [
                {
                    "type": "hole_grid",
                    "diameter": 8,
                    "rows": 2,
                    "cols": 2,
                    "spacing_x": 40,
                    "spacing_y": 20,
                    "through": True,
                }
            ],
        },
    }
    import copy

    edited = copy.deepcopy(base)
    edited["operation"]["features"][0]["rows"] = 1
    edited["operation"]["features"][0]["spacing_y"] = None
    _rejects(monkeypatch, base, edited, "non-numeric")


def test_rebuild_rejects_polygon_sides_change(monkeypatch):
    base = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "boss",
        "operation": {
            "type": "polygon_prism",
            "sides": 6,
            "circumradius": 10,
            "height": 8,
        },
    }
    import copy

    edited = copy.deepcopy(base)
    edited["operation"]["sides"] = 8
    _rejects(monkeypatch, base, edited, "operation structure")


def test_rebuild_rejects_through_flip(monkeypatch):
    import copy

    edited = copy.deepcopy(BASE_PART)
    edited["operation"]["features"][0] = {
        "type": "hole",
        "diameter": 10,
        "through": False,
        "depth": 8,
    }
    _rejects(monkeypatch, BASE_PART, edited, "non-numeric")


def test_rebuild_rejects_build_tree_change(monkeypatch):
    import copy

    edited = copy.deepcopy(BASE_BOX)
    edited["operation"] = {
        "type": "union",
        "base": {"type": "box", "width": 100, "depth": 60, "height": 20},
        "tool": {"type": "box", "width": 20, "depth": 20, "height": 20},
    }
    _rejects(monkeypatch, BASE_BOX, edited, "operation structure")


def test_rebuild_rejects_rename(monkeypatch):
    import copy

    edited = copy.deepcopy(BASE_BOX)
    edited["name"] = "other_name"
    _rejects(monkeypatch, BASE_BOX, edited, "never renames")


def test_rebuild_rejects_no_change(monkeypatch):
    import copy

    _rejects(monkeypatch, BASE_BOX, copy.deepcopy(BASE_BOX), "No changes")


def test_rebuild_rejects_invalid_geometry_real_engine(monkeypatch):
    """Oversize grid passes the schema but fails the engine fit check."""
    _no_groq(monkeypatch)
    base = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "plate",
        "operation": {
            "type": "part",
            "build": {"type": "box", "width": 120, "depth": 80, "height": 10},
            "features": [
                {
                    "type": "hole_grid",
                    "diameter": 8,
                    "rows": 2,
                    "cols": 2,
                    "spacing_x": 40,
                    "spacing_y": 20,
                    "through": True,
                }
            ],
        },
    }
    import copy

    edited = copy.deepcopy(base)
    edited["operation"]["features"][0]["spacing_x"] = 400
    # CADSpec validates (fields in range); the spec is well-formed.
    CADSpec.model_validate(edited)
    r = client.post(
        "/rebuild", json={"base_specification": base, "specification": edited}
    )
    assert r.status_code == 422, r.text
    assert "hole_grid does not fit" in r.json()["detail"]


def test_rebuild_rejects_malformed_spec(monkeypatch):
    _no_groq(monkeypatch)
    bad = {
        "document_type": "3d_part",
        "units": "mm",
        "name": "bad",
        "operation": {"type": "box", "width": -5, "depth": 60, "height": 20},
    }
    r = client.post(
        "/rebuild", json={"base_specification": BASE_BOX, "specification": bad}
    )
    assert r.status_code == 422, r.text
