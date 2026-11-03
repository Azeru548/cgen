"""Shared test configuration.

Abuse limits are for a public deployment, not for a test suite: 260+ requests
from one TestClient address would start returning 429 halfway through and make
unrelated tests fail. The suite disables both limits here, and
`tests/test_limits.py` opts back in with explicit values for the cases it
pins.
"""

from __future__ import annotations

import pytest

from app.services.limits import limiter, telemetry_limiter


@pytest.fixture(autouse=True)
def _limits_off_in_tests(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "0")
    monkeypatch.setenv("DAILY_OPERATION_LIMIT", "0")
    limiter.reset()
    telemetry_limiter.reset()
    yield
    limiter.reset()
    telemetry_limiter.reset()
