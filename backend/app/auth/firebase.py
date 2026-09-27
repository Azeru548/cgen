"""Firebase ID token verification (M11).

  The browser signs in with Firebase Auth and sends the resulting ID token as
  `Authorization: Bearer <token>`. This module verifies that token with
  Google's public certificates, so the backend can trust `uid` without
  talking to Firebase on every request and without ever holding a
  service-account key.

  Only the *ID token* is accepted: it is short-lived (one hour) and carries the
  authenticated subject. Firebase is configured as the expected audience, so
  a token minted for another Firebase project is rejected.

  Auth is optional by default. `REQUIRE_AUTH` gates the protected endpoints so
  a deployment without Firebase configured keeps working exactly as before.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

logger = logging.getLogger(__name__)

GOOGLE_CERTS_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
)
ALGORITHM = "RS256"
AUTH_SCHEME = "bearer"
REQUIRE_AUTH_ENV = "REQUIRE_AUTH"
FIREBASE_PROJECT_ENV = "FIREBASE_PROJECT_ID"
TOKEN_LEEWAY_SECONDS = 30


class AuthError(RuntimeError):
    """A request failed authentication. Maps to HTTP 401."""


def _jwk_client() -> PyJWKClient:
    return PyJWKClient(GOOGLE_CERTS_URL)


def auth_required() -> bool:
    """True when protected endpoints must reject anonymous callers."""
    return os.environ.get(REQUIRE_AUTH_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def expected_project() -> str | None:
    return os.environ.get(FIREBASE_PROJECT_ENV, "").strip() or None


def bearer_token(authorization: str | None) -> str:
    """Extract the bearer token, or raise AuthError."""
    if not authorization:
        raise AuthError("Missing Authorization header.")
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != AUTH_SCHEME or not value.strip():
        raise AuthError("Authorization header must be a bearer token.")
    return value.strip()


def verify_id_token(
    token: str,
    *,
    project_id: str | None = None,
    jwk_client: PyJWKClient | None = None,
) -> dict[str, Any]:
    """Verify a Firebase ID token and return its claims.

    Raises AuthError for anything untrustworthy: bad signature, expired token,
    wrong audience/project, or wrong issuer.
    """
    client = jwk_client or _jwk_client()
    try:
        signing_key = client.get_signing_key_from_jwt(token)
    except Exception as exc:  # noqa: BLE001 - any failure is an auth failure
        raise AuthError("Invalid or unverifiable token.") from exc

    audience = project_id or expected_project()
    options: dict[str, Any] = {"verify_aud": audience is not None}
    try:
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=[ALGORITHM],
            audience=audience,
            issuer="https://securetoken.google.com/" + (audience or "<project>"),
            options=options,
            leeway=TOKEN_LEEWAY_SECONDS,
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("Session expired. Sign in again.") from exc
    except jwt.InvalidAudienceError as exc:
        raise AuthError("Token was not issued for this app.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("Invalid or unverifiable token.") from exc

    uid = claims.get("sub")
    if not isinstance(uid, str) or not uid:
        raise AuthError("Token has no subject.")
    return claims


def fetch_public_certs(timeout: float = 10.0) -> dict[str, str]:
    """Fetch Google's signing certificates (used to validate the JWKS URL)."""
    response = httpx.get(GOOGLE_CERTS_URL, timeout=timeout)
    response.raise_for_status()
    payload: dict[str, str] = response.json()
    return payload
