"""M11: Firebase ID token verification and the optional auth gate.

No test needs a real Firebase project. Tokens are signed locally with a
throwaway RSA key and verified through a stubbed JWKS client, so the tests
prove the real verification path (signature, audience, issuer, expiry)
without contacting Google.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.auth import firebase
from app.auth.firebase import AuthError
from app.dependencies import get_caller

PROJECT = "vouch-c28ec"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PRIVATE_PEM = KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
)
PRIVATE_KEY_STR = PRIVATE_PEM.decode()
PUBLIC_JWK = jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key())


class FakeSigningKey:
    """Mirrors PyJWK: `.key` is a usable public-key object."""

    def __init__(self) -> None:
        self.key = KEY.public_key()


class StubJWKClient:
    """Stands in for PyJWKClient: resolves our throwaway key, or fails."""

    def __init__(self, *, broken: bool = False) -> None:
        self.broken = broken

    def get_signing_key_from_jwt(self, token: str) -> FakeSigningKey:
        if self.broken:
            raise ValueError("cannot fetch keys")
        return FakeSigningKey()


def make_token(
    *,
    aud: str = PROJECT,
    iss: str | None = None,
    sub: str = "user-123",
    expires_in: int = 3600,
    extra: dict | None = None,
) -> str:
    now = int(time.time())
    payload: dict = {
        "aud": aud,
        "iss": iss if iss is not None else f"https://securetoken.google.com/{aud}",
        "sub": sub,
        "iat": now,
        "exp": now + expires_in,
        "email": "maker@example.com",
        "email_verified": True,
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, PRIVATE_PEM, algorithm="RS256")


def verify(token: str, **kwargs) -> dict:
    return firebase.verify_id_token(token, project_id=PROJECT, **kwargs)


# --- Bearer parsing --------------------------------------------------------


def test_bearer_token_extracted():
    assert firebase.bearer_token("Bearer abc.def.ghi") == "abc.def.ghi"
    assert firebase.bearer_token("bearer abc") == "abc"


@pytest.mark.parametrize(
    "header",
    [None, "", "Basic abc", "Bearer", "Bearer   ", "Token abc"],
)
def test_bad_authorization_headers_rejected(header):
    with pytest.raises(AuthError):
        firebase.bearer_token(header)


# --- Token verification ---------------------------------------------------


def test_valid_token_returns_claims():
    claims = verify(make_token(), jwk_client=StubJWKClient())
    assert claims["sub"] == "user-123"
    assert claims["email"] == "maker@example.com"


def test_token_signed_by_another_key_rejected():
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        {
            "aud": PROJECT,
            "iss": f"https://securetoken.google.com/{PROJECT}",
            "sub": "attacker",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        },
        other.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode(),
        algorithm="RS256",
    )
    with pytest.raises(AuthError):
        verify(forged, jwk_client=StubJWKClient())


def test_token_for_another_project_rejected():
    with pytest.raises(AuthError):
        verify(make_token(aud="someone-else"), jwk_client=StubJWKClient())


def test_wrong_issuer_rejected():
    bad_issuer = make_token(iss="https://evil.example.com/securetoken")
    with pytest.raises(AuthError):
        verify(bad_issuer, jwk_client=StubJWKClient())


def test_expired_token_rejected():
    with pytest.raises(AuthError, match="expired"):
        verify(make_token(expires_in=-3600), jwk_client=StubJWKClient())


def test_token_without_subject_rejected():
    token = jwt.encode(
        {
            "aud": PROJECT,
            "iss": f"https://securetoken.google.com/{PROJECT}",
            "sub": "",
            "exp": int(time.time()) + 3600,
        },
        PRIVATE_KEY_STR,
        algorithm="RS256",
    )
    with pytest.raises(AuthError):
        verify(token, jwk_client=StubJWKClient())


def test_unfetchable_keys_rejected():
    with pytest.raises(AuthError):
        verify(make_token(), jwk_client=StubJWKClient(broken=True))


# --- Config ---------------------------------------------------------------


def test_auth_is_optional_by_default(monkeypatch):
    monkeypatch.delenv(firebase.REQUIRE_AUTH_ENV, raising=False)
    assert firebase.auth_required() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_auth_required_truthy_values(monkeypatch, value):
    monkeypatch.setenv(firebase.REQUIRE_AUTH_ENV, value)
    assert firebase.auth_required() is True


def test_auth_not_required_for_falsy_values(monkeypatch):
    for value in ("0", "false", "", "off"):
        monkeypatch.setenv(firebase.REQUIRE_AUTH_ENV, value)
        assert firebase.auth_required() is False


def test_project_id_read_from_env(monkeypatch):
    monkeypatch.setenv(firebase.FIREBASE_PROJECT_ENV, "abc-123")
    assert firebase.expected_project() == "abc-123"
    monkeypatch.delenv(firebase.FIREBASE_PROJECT_ENV, raising=False)
    assert firebase.expected_project() is None


# --- The FastAPI dependency ----------------------------------------------


def test_caller_is_anonymous_when_auth_optional(monkeypatch):
    monkeypatch.delenv(firebase.REQUIRE_AUTH_ENV, raising=False)

    class FakeRequest:
        headers: dict = {}

    caller = get_caller(FakeRequest())
    assert caller.uid is None
    assert caller.verified is False


def test_caller_rejects_anonymous_when_auth_required(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setenv(firebase.REQUIRE_AUTH_ENV, "true")

    class FakeRequest:
        headers: dict = {}

    with pytest.raises(HTTPException) as exc:
        get_caller(FakeRequest())
    assert exc.value.status_code == 401


def test_caller_resolves_uid(monkeypatch):
    from app import dependencies

    monkeypatch.setenv(firebase.REQUIRE_AUTH_ENV, "true")
    monkeypatch.setattr(
        dependencies,
        "verify_id_token",
        lambda token, **kw: {"sub": "u1", "email": "a@b.c", "email_verified": True},
    )

    class FakeRequest:
        headers = {"authorization": "Bearer good.token.here"}

    caller = get_caller(FakeRequest())
    assert caller.uid == "u1"
    assert caller.email == "a@b.c"
    assert caller.verified is True


def test_protected_route_returns_401_without_token(monkeypatch):
    """With auth on, /generate rejects an anonymous caller."""
    monkeypatch.setenv(firebase.REQUIRE_AUTH_ENV, "true")
    from app import main as main_module

    client = TestClient(main_module.app, raise_server_exceptions=False)
    response = client.post("/generate", json={"prompt": "a 10mm cube"})
    assert response.status_code == 401


def test_protected_route_rejects_bad_token(monkeypatch):
    monkeypatch.setenv(firebase.REQUIRE_AUTH_ENV, "true")
    from app import main as main_module

    client = TestClient(main_module.app, raise_server_exceptions=False)
    response = client.post(
        "/generate",
        json={"prompt": "a 10mm cube"},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert response.status_code == 401


def test_routes_still_open_when_auth_disabled(monkeypatch):
    """Auth-off must not change existing behaviour (M1-M9 regressions)."""
    monkeypatch.delenv(firebase.REQUIRE_AUTH_ENV, raising=False)
    from app import main as main_module

    client = TestClient(main_module.app, raise_server_exceptions=False)
    # No token, yet the request reaches validation rather than 401.
    response = client.post("/generate", json={"prompt": ""})
    assert response.status_code == 400
