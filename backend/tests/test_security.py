from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import Unauthorized
from app.core.security import (
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    mask_secret,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("Admin@12345")
    assert hashed != "Admin@12345"
    assert verify_password("Admin@12345", hashed)
    assert not verify_password("wrong", hashed)


def test_jwt_roundtrip_and_expiry() -> None:
    token = create_access_token(
        user_id=7,
        role="admin",
        jti="abc123",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    payload = decode_access_token(token)
    assert payload["sub"] == "7"
    assert payload["role"] == "admin"
    assert payload["jti"] == "abc123"

    expired = create_access_token(
        user_id=7,
        role="admin",
        jti="abc123",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    with pytest.raises(Unauthorized):
        decode_access_token(expired)


def test_secret_encryption_roundtrip() -> None:
    ciphertext = encrypt_secret("sk-super-secret")
    assert ciphertext != "sk-super-secret"
    assert decrypt_secret(ciphertext) == "sk-super-secret"
    assert decrypt_secret(encrypt_secret("another")) == "another"


def test_mask_secret() -> None:
    assert mask_secret("") == ""
    assert mask_secret("short") == "****"
    assert mask_secret("sk-1234567890") == "sk-****7890"
