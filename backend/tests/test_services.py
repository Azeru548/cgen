"""Milestone 4 tests: name sanitization, file store, export validation,
generation orchestration. No Groq calls; CadQuery only where guarded.
"""

import time

import pytest

from app.ai import groq_client
from app.cad import cadquery_engine
from app.cad.schema import CADSpec
from app.services import file_store as file_store_module
from app.services.file_store import FileStore
from app.services.generation import InvalidPromptError, run_generation
from app.services.names import default_name_for, sanitize_name


def _spec(name, operation):
    return CADSpec.model_validate(
        {
            "document_type": "3d_part",
            "units": "mm",
            "name": name,
            "operation": operation,
        }
    )


# --- Names ------------------------------------------------------------------


def test_sanitize_name_basics():
    assert sanitize_name("Shaft With Hole!") == "shaft_with_hole"
    assert sanitize_name("cylinder_shaft") == "cylinder_shaft"
    assert sanitize_name("Sphere v2 (50mm)") == "sphere_v2_50mm"


def test_sanitize_name_blocks_traversal_and_separators():
    assert sanitize_name("../../etc/passwd") == "etc_passwd"
    assert sanitize_name("..\\windows\\x") == "windows_x"
    assert sanitize_name("/absolute/path") == "absolute_path"
    for bad in ("/", "\\", ".", ".."):
        assert bad not in sanitize_name(f"a{bad}b")


def test_sanitize_name_fallback_and_limits():
    assert sanitize_name("", fallback="cylinder") == "cylinder_part"
    assert sanitize_name("   ", fallback="sphere") == "sphere_part"
    assert sanitize_name(None, fallback="box") == "box_part"
    assert len(sanitize_name("a" * 200, fallback="box")) <= 60
    assert default_name_for("cut") == "cut_part"


# --- FileStore ----------------------------------------------------------------


def test_file_store_roundtrip_and_unknown(tmp_path):
    store = FileStore()
    step = tmp_path / "a.step"
    stl = tmp_path / "a.stl"
    step.write_bytes(b"x")
    stl.write_bytes(b"y")
    token = store.put(step_path=str(step), stl_path=str(stl), stem="a")
    assert token and isinstance(token, str)
    assert store.resolve(token, "step") == step
    assert store.resolve(token, "stl") == stl
    assert store.filename_for(token, "step") == "a.step"
    assert store.resolve("nope", "step") is None
    assert store.resolve(token, "binary") is None
    assert store.resolve(token, "") is None
    assert store.resolve(None, "step") is None


def test_file_store_tokens_unique():
    store = FileStore()
    tokens = {
        store.put(step_path="/s.step", stl_path="/s.stl", stem="s") for _ in range(50)
    }
    assert len(tokens) == 50


def test_file_store_traversal_token_cannot_resolve():
    store = FileStore()
    for evil in ("../secret", "..", "/etc/passwd", "", "../" * 10):
        assert store.resolve(evil, "step") is None


def test_file_store_ttl_and_count_eviction(tmp_path):
    step = tmp_path / "a.step"
    step.write_bytes(b"x")
    store = FileStore(max_entries=2, ttl_seconds=3600)
    t1 = store.put(step_path=str(step), stl_path=str(step), stem="a")
    t2 = store.put(step_path=str(step), stl_path=str(step), stem="b")
    store.put(step_path=str(step), stl_path=str(step), stem="c")
    assert store.resolve(t1, "step") is None  # evicted oldest
    assert store.resolve(t2, "step") is not None

    expired = FileStore(ttl_seconds=0.01)
    token = expired.put(step_path=str(step), stl_path=str(step), stem="a")
    time.sleep(0.02)
    assert expired.resolve(token, "step") is None


def test_file_store_missing_file_resolves_none(tmp_path):
    store = FileStore()
    token = store.put(
        step_path=str(tmp_path / "gone.step"),
        stl_path=str(tmp_path / "gone.stl"),
        stem="gone",
    )
    assert store.resolve(token, "step") is None


# --- Export validation --------------------------------------------------------


def test_validate_exported_files_accepts_good_pair(tmp_path):
    step = tmp_path / "p.step"
    stl = tmp_path / "p.stl"
    step.write_bytes(b"ISO-10303-21;\nHEADER;\n")
    stl.write_bytes(b"solid t\nendsolid t\n")
    checks = cadquery_engine.validate_exported_files(step, stl)
    assert all(checks.values())


def test_validate_exported_files_accepts_binary_stl(tmp_path):
    import struct

    step = tmp_path / "p.step"
    step.write_bytes(b"ISO-10303-21;\n")
    stl = tmp_path / "p.stl"
    # 84-byte header + one 50-byte facet record (12 floats + uint16).
    stl.write_bytes(b"\x00" * 84 + struct.pack("<12fH", *([0.0] * 12), 0))
    assert cadquery_engine.validate_exported_files(step, stl)["stl_structure_ok"]


def test_validate_exported_files_rejects_bad_pair(tmp_path):
    step = tmp_path / "p.step"
    stl = tmp_path / "p.stl"
    step.write_bytes(b"garbage, no magic here")
    stl.write_bytes(b"\x00\x01short")
    with pytest.raises(RuntimeError, match="step_magic_ok"):
        cadquery_engine.validate_exported_files(step, stl)
    with pytest.raises(RuntimeError, match="step_exists"):
        cadquery_engine.validate_exported_files(tmp_path / "missing.step", stl)


def test_validate_real_exports(tmp_path):
    pytest.importorskip("cadquery")
    spec = _spec(
        "shaft_with_hole",
        {
            "type": "cut",
            "base": {"type": "cylinder", "radius": 15, "height": 120},
            "tool": {
                "type": "cylinder",
                "radius": 7.5,
                "height": 120,
                "through": True,
            },
        },
    )
    result = cadquery_engine.export_operation(
        spec.operation, name=spec.name, out_dir=tmp_path
    )
    checks = cadquery_engine.validate_exported_files(
        result["step_path"], result["stl_path"]
    )
    assert all(checks.values())


# --- Orchestration --------------------------------------------------------------


def _wire_box_export(monkeypatch, tmp_path, stem="box_10x10x10"):
    step = tmp_path / f"{stem}.step"
    stl = tmp_path / f"{stem}.stl"
    step.write_bytes(b"ISO-10303-21;\n")
    stl.write_bytes(b"solid t\nendsolid t\n")

    def fake_export(*, width, depth, height):
        return {"step_path": str(step), "stl_path": str(stl)}

    monkeypatch.setattr("app.services.generation.cadquery_engine.export_box", fake_export)


def test_run_generation_rejects_bad_prompts():
    store = FileStore()
    with pytest.raises(InvalidPromptError):
        run_generation("", request_id="r1", file_store=store)
    with pytest.raises(InvalidPromptError):
        run_generation("x" * 2001, request_id="r1", file_store=store)


def test_run_generation_full_contract(monkeypatch, tmp_path):
    spec = _spec("My Shaft!", {"type": "cylinder", "radius": 15, "height": 120})
    step = tmp_path / "shaft_cylinder.step"
    stl = tmp_path / "shaft_cylinder.stl"
    step.write_bytes(b"ISO-10303-21;\n")
    stl.write_bytes(b"solid t\nendsolid t\n")

    def fake_export(operation, name="part", out_dir=None):
        assert name == "my_shaft"  # sanitized stem reaches the exporter
        return {"step_path": str(step), "stl_path": str(stl)}

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    monkeypatch.setattr(
        "app.services.generation.cadquery_engine.export_operation", fake_export
    )
    result = run_generation("make a shaft", request_id="req-1", file_store=FileStore())
    assert result.request_id == "req-1"
    assert result.units == "mm"
    assert result.generation_time_ms >= 0
    assert set(result.files) == {"step", "stl"}
    assert result.files["step"].filename == "my_shaft.step"
    assert result.files["step"].bytes > 0
    assert result.files["step"].download_url.startswith("/download/")


def test_run_generation_fixes_echoed_example_name(monkeypatch, tmp_path):
    # Model echoes "rectangular_block" for a non-box part -> deterministic fallback.
    spec = _spec(
        "rectangular_block", {"type": "cylinder", "radius": 15, "height": 120}
    )
    step = tmp_path / "x.step"
    stl = tmp_path / "x.stl"
    step.write_bytes(b"ISO-10303-21;\n")
    stl.write_bytes(b"solid t\nendsolid t\n")

    def fake_export(operation, name="part", out_dir=None):
        assert name == "cylinder_part"
        return {"step_path": str(step), "stl_path": str(stl)}

    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    monkeypatch.setattr(
        "app.services.generation.cadquery_engine.export_operation", fake_export
    )
    result = run_generation("cylinder", request_id="req-2", file_store=FileStore())
    assert result.files["step"].filename == "cylinder_part.step"
    # The validated specification itself is untouched (source of truth).
    assert result.specification["name"] == "rectangular_block"


def test_run_generation_box_uses_legacy_exporter(monkeypatch, tmp_path):
    spec = _spec("cube", {"type": "box", "width": 10, "depth": 10, "height": 10})
    _wire_box_export(monkeypatch, tmp_path)
    monkeypatch.setattr(groq_client, "parse_prompt_to_spec", lambda prompt: spec)
    result = run_generation("cube", request_id="req-3", file_store=FileStore())
    assert result.files["step"].filename == "cube.step"
