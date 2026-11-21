"""
Cryptographic utilities for API key generation, hashing, and password management.
"""

import hashlib
import hmac
import os
import secrets
from typing import Optional, Tuple

_DEFAULT_PBKDF2_ROUNDS = 100_000


def hash_password(password: str, rounds: int = _DEFAULT_PBKDF2_ROUNDS) -> str:
    """Hash a password using salted PBKDF2-HMAC-SHA256."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        rounds,
    )
    return f"pbkdf2_sha256${rounds}${salt}${key.hex()}"


def verify_password(password: str, stored_hash: Optional[str]) -> bool:
    """Verify a plaintext password against a stored hash string using constant-time comparison."""
    if not password or not stored_hash:
        return False

    if stored_hash.startswith("pbkdf2_sha256$"):
        parts = stored_hash.split("$")
        if len(parts) != 4:
            return False
        try:
            rounds = int(parts[1])
            salt = bytes.fromhex(parts[2])
            expected_hex = parts[3]
            computed = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                salt,
                rounds,
            ).hex()
            return hmac.compare_digest(computed, expected_hex)
        except Exception:
            return False

    # Check for legacy argon2 / bcrypt if installed
    try:
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt", "argon2"], deprecated="auto")
        return pwd_context.verify(password, stored_hash)
    except Exception:
        pass

    return False


def generate_api_key(prefix: str = "sem_live_") -> Tuple[str, str]:
    """Generate a high-entropy API key.

    Returns:
        A tuple of (full_raw_key, key_prefix) where key_prefix is the first 12 characters.
    """
    token = secrets.token_urlsafe(32)
    raw_key = f"{prefix}{token}"
    key_prefix = raw_key[:12]
    return raw_key, key_prefix


def hash_api_key(raw_key: str, salt: Optional[str] = None, rounds: int = _DEFAULT_PBKDF2_ROUNDS) -> Tuple[str, str]:
    """Compute a salted hash of an API key.

    Returns:
        A tuple of (key_hash_hex, salt_hex).
    """
    if salt is None:
        salt = secrets.token_hex(16)
    key_hash = hashlib.pbkdf2_hmac(
        "sha256",
        raw_key.encode("utf-8"),
        bytes.fromhex(salt),
        rounds,
    ).hex()
    return key_hash, salt


def verify_api_key_hash(raw_key: str, stored_hash: str, salt: str, rounds: int = _DEFAULT_PBKDF2_ROUNDS) -> bool:
    """Constant-time verification of an API key against its salted hash."""
    if not raw_key or not stored_hash or not salt:
        return False
    try:
        computed = hashlib.pbkdf2_hmac(
            "sha256",
            raw_key.encode("utf-8"),
            bytes.fromhex(salt),
            rounds,
        ).hex()
        return hmac.compare_digest(computed, stored_hash)
    except Exception:
        return False
