"""Small standard-library authentication helpers for the prototype API."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from functools import lru_cache


SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_KEY_LENGTH = 32
MIN_PASSWORD_LENGTH = 4
MAX_PASSWORD_LENGTH = 128
TOKEN_LIFETIME_SECONDS = 60 * 60
TOKEN_ISSUER = "littleleaf-api"


class InvalidTokenError(ValueError):
    """Raised when a bearer token is invalid or expired."""


def hash_password(password: str) -> str:
    """Hash a password in the same format used by the demo-data seeder."""
    if (
        not isinstance(password, str)
        or not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH
    ):
        raise ValueError(
            f"Password must contain {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters."
        )
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=SCRYPT_KEY_LENGTH,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify local scrypt hashes, including hashes created by the seed script."""
    try:
        algorithm, n_text, r_text, p_text, salt_hex, digest_hex = encoded_hash.split("$")
        if (
            algorithm != "scrypt"
            or int(n_text) != SCRYPT_N
            or int(r_text) != SCRYPT_R
            or int(p_text) != SCRYPT_P
            or len(salt_hex) != 32
            or len(digest_hex) != SCRYPT_KEY_LENGTH * 2
        ):
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            dklen=SCRYPT_KEY_LENGTH,
        )
    except (TypeError, ValueError, UnicodeError):
        return False
    return hmac.compare_digest(actual, expected)


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """Provide a process-local hash so unknown-email login checks cost scrypt too."""
    return hash_password(secrets.token_urlsafe(32))


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _urlsafe_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def create_access_token(
    user_id: int,
    secret: str,
    *,
    expires_in_seconds: int = TOKEN_LIFETIME_SECONDS,
) -> str:
    """Create a compact HMAC-SHA256 signed bearer token with an expiry claim."""
    _validate_secret(secret)
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + expires_in_seconds,
        "iss": TOKEN_ISSUER,
    }
    encoded_payload = _urlsafe_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.new(
        secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{encoded_payload}.{_urlsafe_encode(signature)}"


def verify_access_token(token: str, secret: str) -> int:
    """Verify token signature and claims, returning its integer subject ID."""
    _validate_secret(secret)
    if not token or len(token) > 4096 or token.count(".") != 1:
        raise InvalidTokenError("Invalid bearer token.")
    encoded_payload, encoded_signature = token.split(".", maxsplit=1)
    try:
        supplied_signature = _urlsafe_decode(encoded_signature)
        payload = json.loads(_urlsafe_decode(encoded_payload))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise InvalidTokenError("Invalid bearer token.") from exc

    expected_signature = hmac.new(
        secret.encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise InvalidTokenError("Invalid bearer token.")

    now = int(time.time())
    if not isinstance(payload, dict) or payload.get("iss") != TOKEN_ISSUER:
        raise InvalidTokenError("Invalid bearer token.")
    subject = payload.get("sub")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    if (
        not isinstance(subject, str)
        or not subject.isdecimal()
        or not isinstance(issued_at, int)
        or isinstance(issued_at, bool)
        or not isinstance(expires_at, int)
        or isinstance(expires_at, bool)
        or issued_at > now + 60
        or expires_at <= now
        or expires_at <= issued_at
        or expires_at - issued_at > TOKEN_LIFETIME_SECONDS
    ):
        raise InvalidTokenError("Bearer token is expired or invalid.")
    return int(subject)


def _validate_secret(secret: str) -> None:
    validate_auth_secret(secret)


def validate_auth_secret(secret: str | None) -> None:
    """Require a random environment secret with at least 256 bits of text."""
    if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
        raise ValueError("AUTH_SECRET_KEY must contain at least 32 bytes.")
