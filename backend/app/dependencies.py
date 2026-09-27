"""Request identity for the API (M11).

`require_user` is a FastAPI dependency. It is *optional* by default: with
`REQUIRE_AUTH` unset, anonymous callers pass through unchanged and `uid` is
None, so an existing deployment keeps working. Setting `REQUIRE_AUTH=true`
turns the same dependency into a hard gate on the protected routes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from .auth.firebase import AuthError, auth_required, bearer_token, verify_id_token

BEARER_HEADER = "authorization"


@dataclass(frozen=True)
class Caller:
    """Who is calling. `uid` is None for anonymous (auth-optional) requests."""

    uid: str | None
    email: str | None
    verified: bool


def get_caller(request: Request) -> Caller:
    """Resolve the caller's identity from the Authorization header."""
    if not auth_required():
        return Caller(uid=None, email=None, verified=False)
    raw = request.headers.get(BEARER_HEADER)
    try:
        token = bearer_token(raw)
        claims = verify_id_token(token)
    except AuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    email = claims.get("email")
    email_verified = claims.get("email_verified")
    return Caller(
        uid=claims["sub"],
        email=email if isinstance(email, str) else None,
        verified=email_verified is True,
    )


Caller_ = Annotated[Caller, Depends(get_caller)]
