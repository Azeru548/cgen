"""M5 tests: CORS for browser frontend origins (no CAD, no Groq)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_allows_local_frontend_origin():
    r = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_preflight_allows_post_generate():
    r = client.options(
        "/generate",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    assert r.status_code == 200
    allow_methods = r.headers.get("access-control-allow-methods", "")
    assert "POST" in allow_methods


def test_unlisted_origin_gets_no_cors_header():
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers
