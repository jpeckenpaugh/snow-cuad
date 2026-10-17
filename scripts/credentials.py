"""Password generation and hashing.

Shared by scripts/create_users.py (seeding) and app/admin.py (admin-initiated
creation and resets) so the PBKDF2 parameters live in exactly one place.
"""
from __future__ import annotations

import hashlib
import secrets
import string

DEFAULT_ITERATIONS = 200_000
ALPHABET = string.ascii_letters + string.digits

# Ordered least to most privileged; the UI shows them in this order.
ROLES = ("lawyer", "auditor", "admin")

STATUSES = ("active", "suspended")

USERNAME_RE = r"^[a-z0-9][a-z0-9_-]{2,31}$"
USERNAME_HELP = "3-32 characters: lowercase letters, digits, hyphen or underscore"


def generate_password(length: int = 16) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def hash_password(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations).hex()


def verify_password(password: str, salt_hex: str, digest_hex: str, iterations: int) -> bool:
    import hmac

    computed = hash_password(password, bytes.fromhex(salt_hex), int(iterations))
    return hmac.compare_digest(computed, digest_hex)


def new_credential(password: str | None = None, iterations: int = DEFAULT_ITERATIONS) -> dict:
    """Return a fresh password plus its salt and hash.

    The plaintext is returned once for display and never stored.
    """
    password = password or generate_password()
    salt = secrets.token_bytes(16)
    return {
        "password": password,
        "salt": salt.hex(),
        "digest": hash_password(password, salt, iterations),
        "iterations": iterations,
    }
