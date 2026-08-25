"""Password hashing utilities based on bcrypt.

Security rules:
- bcrypt with cost (log rounds) = 12.
- Never store plaintext passwords.
- bcrypt silently ignores bytes beyond 72, so we reject over-long
  passwords explicitly instead of truncating silently.
"""

import bcrypt

BCRYPT_LOG_ROUNDS = 12
# bcrypt only uses the first 72 bytes of the password.
BCRYPT_MAX_PASSWORD_BYTES = 72


def hash_password(plain: str) -> str:
    """Hash a plaintext password with bcrypt (cost=12).

    Returns the hash as a str (bcrypt returns bytes; decoded here).

    Raises:
        TypeError: if plain is not a str.
        ValueError: if plain exceeds 72 bytes when UTF-8 encoded
            (bcrypt's hard limit).
    """
    if not isinstance(plain, str):
        raise TypeError("password must be a str")
    encoded = plain.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(
            f"password exceeds bcrypt limit of {BCRYPT_MAX_PASSWORD_BYTES} bytes "
            f"(got {len(encoded)} bytes); please use a shorter password"
        )
    hashed = bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=BCRYPT_LOG_ROUNDS))
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash.

    Returns False (never raises) when hashed is None or malformed,
    or when plain is invalid.
    """
    if not isinstance(plain, str) or not isinstance(hashed, str):
        return False
    encoded = plain.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
