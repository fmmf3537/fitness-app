"""Tests for app.utils.password."""

import pytest

from app.utils.password import hash_password, verify_password


def test_hash_password_returns_bcrypt_hash_string():
    hashed = hash_password("S3cureP@ssw0rd")
    assert isinstance(hashed, str)
    assert hashed  # non-empty
    assert hashed.startswith("$2")  # bcrypt identifier ($2a/$2b/$2y)


def test_hash_password_uses_cost_12():
    hashed = hash_password("cost-check")
    # bcrypt hash format: $2b$12$...
    assert hashed.split("$")[2] == "12"


def test_verify_password_correct_password_returns_true():
    plain = "MyP@ssw0rd!"
    hashed = hash_password(plain)
    assert verify_password(plain, hashed) is True


def test_verify_password_wrong_password_returns_false():
    hashed = hash_password("right-password")
    assert verify_password("wrong-password", hashed) is False


def test_same_plaintext_produces_different_hashes():
    plain = "same-password"
    hash1 = hash_password(plain)
    hash2 = hash_password(plain)
    assert hash1 != hash2  # random salt
    # ...but both verify against the same plaintext
    assert verify_password(plain, hash1) is True
    assert verify_password(plain, hash2) is True


def test_verify_password_none_plain_returns_false():
    hashed = hash_password("some-password")
    assert verify_password(None, hashed) is False


def test_verify_password_none_hash_returns_false():
    assert verify_password("some-password", None) is False


def test_verify_password_malformed_hash_returns_false():
    assert verify_password("some-password", "not-a-bcrypt-hash") is False
    assert verify_password("some-password", "") is False


def test_hash_password_rejects_over_72_bytes():
    long_password = "a" * 73  # 73 bytes in UTF-8
    with pytest.raises(ValueError):
        hash_password(long_password)


def test_hash_password_accepts_exactly_72_bytes():
    hashed = hash_password("a" * 72)
    assert hashed.startswith("$2")
    assert verify_password("a" * 72, hashed) is True
