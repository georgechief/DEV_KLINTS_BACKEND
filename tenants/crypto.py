from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    key = settings.CONNECTOR_FERNET_KEY
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def encrypt_api_key(api_key: str) -> str:
    return _fernet().encrypt(api_key.encode()).decode()


def decrypt_api_key(encrypted_api_key: str) -> str:
    return _fernet().decrypt(encrypted_api_key.encode()).decode()


# Connector config fields that hold credentials and must never be stored
# or exposed in plaintext.
SECRET_CONFIG_FIELDS = ("api_key", "access_token", "refresh_token", "api_v3_key")


def encrypt_config(config: dict) -> dict:
    encrypted = dict(config)
    for field in SECRET_CONFIG_FIELDS:
        value = encrypted.get(field)
        if isinstance(value, str) and value:
            encrypted[field] = encrypt_api_key(value)
    return encrypted


def mask_api_key(api_key: str) -> str:
    if not isinstance(api_key, str) or not api_key:
        return "****"
    if "_" in api_key:
        prefix, _sep, _rest = api_key.rpartition("_")
        return f"{prefix}_****"
    return "****"


def masked_config(config: dict) -> dict:
    """Return config for API responses with secret fields decrypted then masked."""
    result = dict(config or {})
    for field in SECRET_CONFIG_FIELDS:
        value = result.get(field)
        if not isinstance(value, str) or not value:
            continue
        try:
            plain = decrypt_api_key(value)
        except (InvalidToken, ValueError):
            plain = value
        result[field] = mask_api_key(plain)
    return result


def has_api_v3_key_in_config(config: dict) -> bool:
    """Return True when connector config stores a non-empty Manago API v3 key."""
    value = (config or {}).get("api_v3_key")
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        plain = decrypt_api_key(value)
    except (InvalidToken, ValueError):
        plain = value
    return bool(str(plain).strip())
