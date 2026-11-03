"""Abuse limits for a public deployment.

`/generate`, `/modify` and the assembly routes spend the operator's Groq
credits and CadQuery CPU, and `REQUIRE_AUTH` is optional, so a public launch
needs a ceiling that does not depend on a well-behaved client.

Two independent limits, both enforced before any CAD or AI work happens:

  * **Per-IP rate limit** - a sliding one-minute window
    (`RATE_LIMIT_PER_MINUTE`, default 20, `0` disables). Stops a single
    client from running the pipeline in a loop.
  * **Global daily budget** - every accepted costly request counts against
    `DAILY_OPERATION_LIMIT` (default 500, `0` disables), reset at UTC
    midnight. Stops a distributed script from draining the key or the box
    in one afternoon.

State is in-process and therefore single-instance, matching Render Free's
one-instance deployment (same trade-off as `FileStore`). Rejected requests
never reach the expensive code path, and nothing user-supplied is stored:
the limiter keeps an address key and timestamps only.

The client address comes from `X-Forwarded-For` (Render terminates TLS and
sets it) with `request.client.host` as the fallback.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60.0

#: Keys tracked at once. Beyond this the limiter forgets the least recently
#: seen address rather than growing without bound under a spray of addresses.
MAX_TRACKED_CLIENTS = 5000

RATE_ENV = "RATE_LIMIT_PER_MINUTE"
BUDGET_ENV = "DAILY_OPERATION_LIMIT"

DEFAULT_RATE_PER_MINUTE = 20
DEFAULT_DAILY_LIMIT = 500


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("limits_bad_env name=%s", name)
        return default
    return max(value, 0)


def rate_limit_per_minute() -> int:
    """Requests allowed per client per minute; 0 disables the per-IP limit."""
    return _env_int(RATE_ENV, DEFAULT_RATE_PER_MINUTE)


def daily_operation_limit() -> int:
    """Costly operations allowed per UTC day; 0 disables the global budget."""
    return _env_int(BUDGET_ENV, DEFAULT_DAILY_LIMIT)


def client_key(request: Request) -> str:
    """Best-effort client address. Never logged in full."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    client = request.client
    if client is not None and client.host:
        return client.host
    return "unknown"


class OperationLimiter:
    """Sliding-window per-client limiter plus a global daily budget."""

    def __init__(self, *, window_seconds: float = WINDOW_SECONDS) -> None:
        self._window = window_seconds
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = {}
        self._day: int | None = None
        self._day_count = 0

    def consume(self, key: str, *, per_minute: int, daily_limit: int) -> tuple[bool, int]:
        """Charge one operation to `key`.

        Returns `(allowed, retry_after_seconds)`. When `allowed` is False the
        caller must reject; `retry_after_seconds` is a safe Retry-After value.
        A rejected call is not charged to either bucket.
        """
        now = time.monotonic()
        with self._lock:
            self._roll_day_locked()
            if daily_limit > 0 and self._day_count >= daily_limit:
                return False, self._seconds_to_utc_midnight()

            window = self._hits.get(key)
            if window is None:
                if len(self._hits) >= MAX_TRACKED_CLIENTS:
                    self._hits.pop(next(iter(self._hits)), None)
                window = deque()
                self._hits[key] = window
            cutoff = now - self._window
            while window and window[0] < cutoff:
                window.popleft()
            if per_minute > 0 and len(window) >= per_minute:
                retry = int(self._window - (now - window[0])) + 1
                return False, max(retry, 1)
            window.append(now)
            self._day_count += 1
            return True, 0

    def _roll_day_locked(self) -> None:
        today = int(time.time() // 86400)
        if self._day != today:
            self._day = today
            self._day_count = 0

    @staticmethod
    def _seconds_to_utc_midnight() -> int:
        return int(86400 - (time.time() % 86400)) + 1

    def reset(self) -> None:
        """Drop all state (tests, and a manual reset after an incident)."""
        with self._lock:
            self._hits.clear()
            self._day = None
            self._day_count = 0

    def usage(self) -> dict[str, int]:
        """Non-identifying counters for `/metrics`."""
        with self._lock:
            self._roll_day_locked()
            return {
                "tracked_clients": len(self._hits),
                "operations_today": self._day_count,
                "daily_limit": daily_operation_limit(),
                "per_minute_limit": rate_limit_per_minute(),
            }


limiter = OperationLimiter()

#: Telemetry is cheap, so it gets a much wider window and never touches the
#: daily operation budget: page views and error reports must not compete with
#: someone else's generation.
TELEMETRY_PER_MINUTE = 60

telemetry_limiter = OperationLimiter()


def rate_limit(request: Request) -> None:
    """FastAPI dependency: charge one costly operation, or raise 429."""
    allowed, retry_after = limiter.consume(
        client_key(request),
        per_minute=rate_limit_per_minute(),
        daily_limit=daily_operation_limit(),
    )
    if allowed:
        return
    logger.warning("rate_limited path=%s retry_after=%d", request.url.path, retry_after)
    raise HTTPException(
        status_code=429,
        detail="Too many requests. Wait a moment and try again.",
        headers={"Retry-After": str(retry_after)},
    )


def telemetry_rate_limit(request: Request) -> None:
    """FastAPI dependency for the cheap telemetry routes."""
    allowed, retry_after = telemetry_limiter.consume(
        client_key(request),
        per_minute=TELEMETRY_PER_MINUTE,
        daily_limit=0,
    )
    if allowed:
        return
    raise HTTPException(
        status_code=429,
        detail="Too many telemetry events.",
        headers={"Retry-After": str(retry_after)},
    )
