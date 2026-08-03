import pytest

from app.config import decrypt_value, encrypt_value, get_settings


def test_encrypt_decrypt_roundtrip():
    plain = "xj_secret_key_123!@#"
    token = encrypt_value(plain)
    assert token != plain
    assert decrypt_value(token) == plain


def test_encrypt_produces_different_ciphertext_each_time():
    plain = "same-input"
    assert encrypt_value(plain) != encrypt_value(plain)
    assert decrypt_value(encrypt_value(plain)) == plain


def test_missing_fernet_key_raises(monkeypatch):
    monkeypatch.delenv("FERNET_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="FERNET_KEY"):
        encrypt_value("x")
