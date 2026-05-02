"""Cryptographic utilities: password hashing, session tokens, CSRF tokens.

See ADR-0008 for parameter rationale.
"""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(plain: str) -> str:
    """argon2id hash with random salt."""
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time verify. False on any failure (mismatch or malformed hash)."""
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def generate_session_token() -> str:
    """256-bit random, base64url, no padding. Used as user_sessions.id."""
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    """128-bit random, base64url. Used in double-submit cookie."""
    return secrets.token_urlsafe(16)
