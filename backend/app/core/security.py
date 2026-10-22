import base64
import os
from datetime import UTC, datetime

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings
from app.core.errors import Unauthorized

JWT_ALGORITHM = "HS256"
COOKIE_NAME = "access_token"
SESSION_HOURS = 8

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(*, user_id: int, role: str, jti: str, expires_at: datetime) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "jti": jti,
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthorized("登录状态无效") from exc


def _aes_key() -> bytes:
    raw = get_settings().data_encryption_key
    try:
        key = base64.b64decode(raw, validate=True)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("DATA_ENCRYPTION_KEY 不是合法的 base64") from exc
    if len(key) != 32:
        raise RuntimeError("DATA_ENCRYPTION_KEY 必须是 32 字节")
    return key


def encrypt_secret(plain: str) -> str:
    if not plain:
        return ""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    ciphertext = AESGCM(_aes_key()).encrypt(nonce, plain.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(token: str) -> str:
    if not token:
        return ""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        blob = base64.b64decode(token, validate=True)
        nonce, ciphertext = blob[:12], blob[12:]
        return AESGCM(_aes_key()).decrypt(nonce, ciphertext, None).decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - 密钥不匹配视为配置损坏
        raise RuntimeError("敏感配置解密失败，请检查 DATA_ENCRYPTION_KEY") from exc


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:3]}****{value[-4:]}"
