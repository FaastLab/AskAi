"""Password hashing — bcrypt with a sane work factor.

bcrypt is the standard for password storage; we deliberately avoid the
allure of "newer" algorithms here because every regulated firm's
infosec questionnaire knows bcrypt and we don't need to defend the
choice in audits.

Work factor 12 = ~0.3s per hash on a modern CPU — slow enough to thwart
offline brute-force, fast enough not to be a login DoS vector.
"""

from __future__ import annotations

import re

import bcrypt

_BCRYPT_ROUNDS = 12

_MIN_PASSWORD_LEN = 8
_PASSWORD_TOO_WEAK_PATTERNS = (
    re.compile(r"^[0-9]+$"),  # all digits
    re.compile(r"^[a-zA-Z]+$"),  # all letters, no digits/symbols
)


class WeakPasswordError(ValueError):
    """Raised when a password fails the basic strength check."""


def hash_password(password: str) -> str:
    """Return a bcrypt hash for `password`. Validates min strength first."""
    _validate(password)
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time-ish bcrypt verify. Never raises on bad input."""
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        # Malformed hash on disk — fail closed.
        return False


def _validate(password: str) -> None:
    if not isinstance(password, str) or len(password) < _MIN_PASSWORD_LEN:
        raise WeakPasswordError(
            f"password must be at least {_MIN_PASSWORD_LEN} characters"
        )
    for pat in _PASSWORD_TOO_WEAK_PATTERNS:
        if pat.fullmatch(password):
            raise WeakPasswordError(
                "password too weak — mix letters and numbers/symbols"
            )
