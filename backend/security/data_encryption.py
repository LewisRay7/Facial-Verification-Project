from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.config import settings


PREFIX = "ev1:"
AAD = b"examverify-student-biometric-v1"


def encrypt_text(value: str) -> str:
    if not value or value.startswith(PREFIX):
        return value
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key()).encrypt(nonce, value.encode("utf-8"), AAD)
    return PREFIX + base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_text(value: str) -> str:
    if not value or not value.startswith(PREFIX):
        return value
    payload = base64.urlsafe_b64decode(value[len(PREFIX) :].encode("ascii"))
    return AESGCM(_key()).decrypt(payload[:12], payload[12:], AAD).decode("utf-8")


def encrypt_json(value: dict[str, Any]) -> str:
    return encrypt_text(json.dumps(value, sort_keys=True, separators=(",", ":")))


def decrypt_json(value: str) -> dict[str, Any]:
    decoded = decrypt_text(value or "{}")
    result = json.loads(decoded or "{}")
    return result if isinstance(result, dict) else {}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _key() -> bytes:
    configured = settings.data_encryption_key.strip()
    if configured:
        try:
            decoded = base64.urlsafe_b64decode(configured.encode("ascii"))
            if len(decoded) == 32:
                return decoded
        except Exception:
            pass
        return hashlib.sha256(configured.encode("utf-8")).digest()
    if settings.is_production:
        raise RuntimeError("DATA_ENCRYPTION_KEY is required in production.")
    return hashlib.sha256(settings.jwt_secret.encode("utf-8")).digest()
