"""SHA-256 hash for stored refresh tokens (never store raw tokens)."""

import hashlib
import secrets


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_raw_token() -> str:
    return secrets.token_urlsafe(48)
