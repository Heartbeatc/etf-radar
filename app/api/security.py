from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import Header, HTTPException, status

from app.core.config import Settings, get_settings
from app.domain.models import WebSessionResponse

PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 260_000
SESSION_TOKEN_VERSION = "ws1"


@dataclass(frozen=True)
class AuthPrincipal:
    principal_type: str
    username: str
    expires_at: datetime | None = None


def require_api_token(
    authorization: str | None = Header(default=None),
    x_api_token: str | None = Header(default=None),
) -> AuthPrincipal:
    settings = get_settings()
    token = x_api_token or _bearer_token(authorization)

    if settings.api_token and token and secrets.compare_digest(token, settings.api_token):
        return AuthPrincipal(principal_type="api_token", username="api-token")

    if settings.web_auth_enabled and token:
        principal = verify_web_session_token(token, settings)
        if principal is not None:
            return principal

    if not settings.api_token and not settings.web_auth_enabled:
        return AuthPrincipal(principal_type="anonymous", username="anonymous")

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def authenticate_web_user(username: str, password: str, settings: Settings) -> WebSessionResponse | None:
    if not settings.web_auth_enabled or not settings.web_password_hash or not settings.web_session_secret:
        return None
    if not secrets.compare_digest(username.strip(), settings.web_username.strip()):
        return None
    if not verify_password(password, settings.web_password_hash):
        return None
    return create_web_session(username=settings.web_username.strip(), settings=settings)


def create_web_session(username: str, settings: Settings) -> WebSessionResponse:
    now = int(time.time())
    expires_in = settings.web_session_ttl_seconds
    expires_at_epoch = now + expires_in
    payload = {
        "typ": "web_session",
        "sub": username,
        "iat": now,
        "exp": expires_at_epoch,
    }
    payload_b64 = _b64encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _session_signature(payload_b64, settings.web_session_secret)
    token = f"{SESSION_TOKEN_VERSION}.{payload_b64}.{signature}"
    return WebSessionResponse(
        access_token=token,
        expires_at=datetime.fromtimestamp(expires_at_epoch, tz=timezone.utc),
        expires_in_seconds=expires_in,
        username=username,
    )


def verify_web_session_token(token: str, settings: Settings) -> AuthPrincipal | None:
    if not settings.web_session_secret:
        return None
    try:
        version, payload_b64, signature = token.split(".", 2)
    except ValueError:
        return None
    if version != SESSION_TOKEN_VERSION:
        return None
    expected = _session_signature(payload_b64, settings.web_session_secret)
    if not secrets.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_b64decode(payload_b64).decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not _valid_session_payload(payload):
        return None
    expires_at_epoch = int(payload["exp"])
    if expires_at_epoch <= int(time.time()):
        return None
    return AuthPrincipal(
        principal_type="web_session",
        username=str(payload["sub"]),
        expires_at=datetime.fromtimestamp(expires_at_epoch, tz=timezone.utc),
    )


def create_password_hash(password: str, *, iterations: int = PASSWORD_HASH_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{PASSWORD_HASH_ALGORITHM}:{iterations}:{_b64encode(salt)}:{_b64encode(digest)}"


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        separator = "$" if "$" in encoded_hash else ":"
        algorithm, iterations_text, salt_b64, digest_b64 = encoded_hash.split(separator, 3)
        iterations = int(iterations_text)
        salt = _b64decode(salt_b64)
        expected_digest = _b64decode(digest_b64)
    except (ValueError, TypeError):
        return False
    if algorithm != PASSWORD_HASH_ALGORITHM or iterations < 100_000:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return secrets.compare_digest(digest, expected_digest)


def _valid_session_payload(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("typ") == "web_session"
        and isinstance(payload.get("sub"), str)
        and isinstance(payload.get("iat"), int)
        and isinstance(payload.get("exp"), int)
    )


def _bearer_token(value: str | None) -> str | None:
    if not value:
        return None
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token.strip()


def _session_signature(payload_b64: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64encode(digest)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
