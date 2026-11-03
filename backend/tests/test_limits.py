"""Abuse limits and launch telemetry.

The limiter is what keeps a public launch from draining the Groq key or the
box in one afternoon, so the tests pin the exact behaviours the deployment
relies on: a rejected request is not charged, the budget resets per day, and
`0` disables a limit rather than blocking everything.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.limits import OperationLimiter, limiter, telemetry_limiter
from app.services.telemetry import telemetry

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_PER_MINUTE", raising=False)
    monkeypatch.delenv("DAILY_OPERATION_LIMIT", raising=False)
    limiter.reset()
    telemetry_limiter.reset()
    telemetry.reset()
    yield
    limiter.reset()
    telemetry_limiter.reset()
    telemetry.reset()


def test_per_client_window_allows_then_rejects():
    bucket = OperationLimiter()
    for _ in range(3):
        allowed, _retry = bucket.consume("1.2.3.4", per_minute=3, daily_limit=0)
        assert allowed
    allowed, retry = bucket.consume("1.2.3.4", per_minute=3, daily_limit=0)
    assert allowed is False
    assert retry >= 1


def test_rejected_request_is_not_charged():
    """A 429 must not consume budget, or a retry loop could starve the day."""
    bucket = OperationLimiter()
    bucket.consume("a", per_minute=1, daily_limit=5)
    bucket.consume("a", per_minute=1, daily_limit=5)
    usage = bucket.usage()
    assert usage["operations_today"] == 1


def test_other_clients_are_unaffected():
    bucket = OperationLimiter()
    assert bucket.consume("a", per_minute=1, daily_limit=0)[0]
    assert bucket.consume("b", per_minute=1, daily_limit=0)[0]


def test_daily_budget_blocks_across_clients():
    bucket = OperationLimiter()
    assert bucket.consume("a", per_minute=0, daily_limit=2)[0]
    assert bucket.consume("b", per_minute=0, daily_limit=2)[0]
    allowed, retry = bucket.consume("c", per_minute=0, daily_limit=2)
    assert allowed is False
    assert retry > 0


def test_zero_disables_the_limit():
    bucket = OperationLimiter()
    for _ in range(50):
        assert bucket.consume("a", per_minute=0, daily_limit=0)[0]


def test_expired_hits_leave_the_window():
    bucket = OperationLimiter(window_seconds=0.0)
    assert bucket.consume("a", per_minute=1, daily_limit=0)[0]
    # A zero-length window means the previous hit is already stale.
    assert bucket.consume("a", per_minute=1, daily_limit=0)[0]


def test_costly_route_returns_429_with_retry_after(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "1")
    bad = {"specification": {"nonsense": True}}

    first = client.post("/remint", json=bad)
    assert first.status_code == 422
    second = client.post("/remint", json=bad)

    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1
    assert "too many requests" in second.json()["detail"].lower()


def test_daily_budget_returns_429(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "0")
    monkeypatch.setenv("DAILY_OPERATION_LIMIT", "1")
    bad = {"specification": {"nonsense": True}}

    assert client.post("/remint", json=bad).status_code == 422
    limited = client.post("/remint", json=bad)
    assert limited.status_code == 429


def test_unknown_event_name_is_rejected():
    assert client.post("/telemetry/event", json={"name": "made_up"}).status_code == 400


def test_known_event_is_counted():
    r = client.post("/telemetry/event", json={"name": "workspace_open", "path": "/workspace"})
    assert r.status_code == 204

    snapshot = telemetry.snapshot()
    assert snapshot["events"]["workspace_open"] == 1


def test_client_error_is_counted_and_bounded():
    long_message = "x" * 5000
    r = client.post("/telemetry/error", json={"message": long_message, "path": "/workspace"})
    assert r.status_code == 204
    assert telemetry.snapshot()["client_errors"] == 1


def test_metrics_exposes_aggregates_only():
    client.post("/telemetry/event", json={"name": "landing_cta"})
    body = client.get("/metrics").json()

    assert body["events"]["landing_cta"] == 1
    assert "limits" in body
    assert body["limits"]["operations_today"] >= 0
    assert body["artifact_storage"] in {"local", "byteship"}
    # Nothing request-specific may leak into a public aggregate.
    serialised = str(body)
    assert "prompt" not in serialised
    assert "sk-" not in serialised
