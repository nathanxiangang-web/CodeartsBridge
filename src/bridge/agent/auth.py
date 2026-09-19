"""Bearer token authentication for Agent API."""
from __future__ import annotations

import hmac
import os
import secrets
from typing import Any


class AuthError(Exception):
    pass


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def get_token_from_env(env_var: str) -> str | None:
    return os.environ.get(env_var)


def compare_token(provided: str, expected: str) -> bool:
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided, expected)


def extract_bearer(headers: dict[str, str]) -> str | None:
    auth = headers.get("Authorization", "") or headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


def check_auth(headers: dict[str, Any], expected_token: str) -> None:
    if not expected_token:
        raise AuthError("Server has no token configured")
    provided = extract_bearer(headers)
    if not provided:
        raise AuthError("Missing Authorization header")
    if not compare_token(provided, expected_token):
        raise AuthError("Invalid token")