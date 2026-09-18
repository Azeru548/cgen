"""PoC tests: box creation, validation, STEP/STL export (Milestone 1)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # On Render with Deps installed this must be True; locally it is True
    # once `pip install -r requirements.txt` has run.
    assert "cadquery_available" in body


def test_box_step_stl():
    # Needs real CadQuery (cloud/Docker only); skipped locally where the
    # heavy OCP wheel is not installed. Still runs on Render.
    pytest.importorskip("cadquery")
    r = client.get("/test/cad?width=100&depth=60&height=30")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed"
    assert body["files"]["step_bytes"] > 0
    assert body["files"]["stl_bytes"] > 0
    assert all(body["validation"].values())


def test_invalid_dimensions_rejected():
    r = client.get("/test/cad?width=-5&depth=60&height=30")
    assert r.status_code == 422
