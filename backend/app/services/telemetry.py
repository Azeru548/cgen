"""First-party launch telemetry (M13).

Two things a launch needs that the server logs alone cannot give:

  * **Product counts** - how many generations actually completed, how many
    were attempted, how many workspaces were opened. Aggregates only: no
    prompt text, no user identifiers, no file contents.
  * **Client errors** - uncaught browser exceptions and render crashes,
    reported here so they land in the same log stream as the API.

Everything is an in-process counter for the current UTC day, exposed as
aggregates through `GET /metrics`. This is deliberately not analytics
infrastructure: it is enough to answer "did the launch work today?" and
"is the viewer crashing?" without adding a third-party script or a cookie.

The counters reset with the process, exactly like `FileStore`.
"""

from __future__ import annotations

import logging
import re
import threading
import time

logger = logging.getLogger(__name__)

#: Event names are a closed vocabulary so a public endpoint cannot be used to
#: write arbitrary strings into the log stream.
ALLOWED_EVENTS = (
    "landing_view",
    "landing_cta",
    "sign_in",
    "sign_out",
    "workspace_open",
    "generate_started",
    "generate_completed",
    "generate_failed",
    "modify_started",
    "modify_completed",
    "modify_failed",
    "revision_selected",
    "files_expired",
    "download_clicked",
)

_EVENT_NAME = re.compile(r"^[a-z][a-z0-9_]{1,47}$")

MAX_MESSAGE_CHARS = 300
MAX_CONTEXT_CHARS = 500


def _day_key() -> int:
    return int(time.time() // 86400)


class Telemetry:
    """Thread-safe per-day counters for events and client errors."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._day = _day_key()
        self._events: dict[str, int] = {}
        self._errors = 0

    def record_event(self, name: str) -> None:
        if not _EVENT_NAME.match(name):
            return
        with self._lock:
            self._roll_locked()
            self._events[name] = self._events.get(name, 0) + 1

    def record_client_error(self) -> None:
        with self._lock:
            self._roll_locked()
            self._errors += 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            self._roll_locked()
            return {
                "day": self._day,
                "client_errors": self._errors,
                "events": dict(sorted(self._events.items())),
            }

    def _roll_locked(self) -> None:
        today = _day_key()
        if today != self._day:
            self._day = today
            self._events.clear()
            self._errors = 0

    def reset(self) -> None:
        with self._lock:
            self._day = _day_key()
            self._events.clear()
            self._errors = 0


telemetry = Telemetry()


def clean_message(value: str) -> str:
    """One line, capped, no control characters."""
    flat = " ".join(str(value).split())
    return flat[:MAX_MESSAGE_CHARS]


def clean_context(value: str) -> str:
    flat = " ".join(str(value).split())
    return flat[:MAX_CONTEXT_CHARS]
