"""Deterministic, secret-safe fingerprints for persisted run inputs."""

from __future__ import annotations

import hashlib
import json
from typing import Any


_CREDENTIAL_KEYS = {
    "authorization",
    "token",
    "access_token",
    "api_key",
    "secret",
    "password",
}
_CREDENTIAL_SUFFIXES = ("_api_key", "_secret", "_password", "_token")


def _is_credential_key(key: Any) -> bool:
    normalized = str(key).strip().lower()
    if normalized.endswith("_env"):
        return False
    return normalized in _CREDENTIAL_KEYS or normalized.endswith(
        _CREDENTIAL_SUFFIXES
    )


def secret_safe_payload(
    value: Any, *, redact: bool = False, _in_auth: bool = False
) -> Any:
    """Return a copy with literal credentials redacted and safe config intact."""

    if redact:
        if isinstance(value, dict):
            return {str(key): "<redacted>" for key in value}
        return "<redacted>"
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            normalized = str(key).strip().lower()
            auth_mapping = normalized == "auth" and isinstance(item, dict)
            sensitive = _is_credential_key(key) or (
                _in_auth and normalized in {"value", "credential"}
            )
            if normalized == "auth" and not auth_mapping:
                sensitive = True
            out[str(key)] = secret_safe_payload(
                item,
                redact=sensitive,
                _in_auth=_in_auth or auth_mapping,
            )
        return out
    if isinstance(value, (list, tuple)):
        return [secret_safe_payload(item, _in_auth=_in_auth) for item in value]
    return value


def _secret_safe_payload(value: Any, *, redact: bool = False) -> Any:
    """Backward-compatible private alias for existing callers and tests."""

    return secret_safe_payload(value, redact=redact)


def fingerprint_payload(payload: Any) -> str:
    """Hash a canonical JSON representation without incorporating secrets."""

    canonical = json.dumps(
        secret_safe_payload(payload),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
