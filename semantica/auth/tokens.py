"""
Lightweight RFC 7519 compliant JSON Web Token (JWT) implementation using Python standard library.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional


class TokenError(Exception):
    """Base exception for JWT token errors."""
    pass


class TokenExpiredError(TokenError):
    """Raised when the token timestamp is in the past."""
    pass


class TokenInvalidError(TokenError):
    """Raised when token signature or payload is invalid or malformed."""
    pass


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _base64url_decode(data: str) -> bytes:
    padding = 4 - (len(data) % 4)
    if padding != 4:
        data += "=" * padding
    return base64.urlsafe_b64decode(data.encode("utf-8"))


def get_jwt_secret() -> str:
    """Retrieve the configured JWT secret key from the environment."""
    return (
        os.environ.get("SEMANTICA_JWT_SECRET")
        or os.environ.get("SEMANTICA_API_KEY")
        or "semantica-default-secret-key-change-in-production"
    )


def create_access_token(
    payload: Dict[str, Any],
    secret: Optional[str] = None,
    expires_delta_seconds: int = 7200,
) -> str:
    """Create a signed HMAC-SHA256 JWT access token.

    Args:
        payload: Dictionary of token claims (sub, type, groups, etc.).
        secret: Optional custom secret key. Defaults to SEMANTICA_JWT_SECRET.
        expires_delta_seconds: Expiration delta in seconds (default 2 hours / 7200s).

    Returns:
        The encoded compact JWT string: header.payload.signature
    """
    key = secret or get_jwt_secret()
    header = {"alg": "HS256", "typ": "JWT"}
    body = dict(payload)
    now = int(time.time())
    if "iat" not in body:
        body["iat"] = now
    if "exp" not in body:
        body["exp"] = now + expires_delta_seconds

    header_json = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_json = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")

    header_b64 = _base64url_encode(header_json)
    payload_b64 = _base64url_encode(payload_json)

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _base64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def verify_access_token(
    token: str,
    secret: Optional[str] = None,
) -> Dict[str, Any]:
    """Verify and decode an HMAC-SHA256 JWT access token.

    Args:
        token: The encoded compact JWT string.
        secret: Optional custom secret key. Defaults to SEMANTICA_JWT_SECRET.

    Returns:
        The decoded claims payload dictionary.

    Raises:
        TokenInvalidError: If the token format or signature is invalid.
        TokenExpiredError: If the token expiration time is in the past.
    """
    key = secret or get_jwt_secret()
    parts = token.strip().split(".")
    if len(parts) != 3:
        raise TokenInvalidError("Invalid token format: expected 3 dot-separated segments.")

    header_b64, payload_b64, sig_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected_sig = hmac.new(key.encode("utf-8"), signing_input, hashlib.sha256).digest()

    try:
        received_sig = _base64url_decode(sig_b64)
    except Exception as exc:
        raise TokenInvalidError(f"Invalid token signature encoding: {exc}")

    if not hmac.compare_digest(expected_sig, received_sig):
        raise TokenInvalidError("Token signature verification failed.")

    try:
        payload_bytes = _base64url_decode(payload_b64)
        claims = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        raise TokenInvalidError(f"Invalid token payload JSON: {exc}")

    exp = claims.get("exp")
    if exp is not None:
        now = int(time.time())
        if now > exp:
            raise TokenExpiredError("Token has expired.")

    return claims
