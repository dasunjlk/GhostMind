"""
Secure API-key storage.

Primary store: the OS credential manager via the `keyring` package
(Windows Credential Manager on Windows — no native build needed).
Fallback: a plaintext `[key_storage]` table inside `config/settings.toml`,
used only when keyring is unavailable (documented tradeoff).

Order of operations (matches the release plan, R-03):
- save_key(): keyring first; on failure writes the plaintext fallback.
- load_key(): keyring first, then the plaintext fallback.
- clear_key(): removes the secret from both stores.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

SERVICE_NAME = "GhostMind"
KEY_NAME = "GROQ_API_KEY"

# Cache for the lazily imported keyring module.
# None = not resolved yet; False = import failed (unavailable); otherwise the module.
_KEYRING = None


def _get_keyring():
    """Return the keyring module, or None if it is unavailable."""
    global _KEYRING
    if _KEYRING is None:
        try:
            import keyring  # type: ignore

            _KEYRING = keyring
        except Exception as e:  # ImportError or a broken backend import
            logger.warning("keyring unavailable (%s); using settings.toml fallback", e)
            _KEYRING = False
    return _KEYRING or None


def _fallback_path() -> Path:
    """Plaintext fallback file (same settings.toml the app already uses)."""
    return Path(__file__).resolve().parent.parent / "config" / "settings.toml"


def is_keyring_available() -> bool:
    return _get_keyring() is not None


def backend_name() -> str:
    """Human/pytest-readable name of the backend that would be used."""
    kr = _get_keyring()
    if kr is None:
        return "plaintext"
    try:
        return kr.get_keyring().__class__.__name__  # type: ignore[attr-defined]
    except Exception:
        return "keyring"


def load_key() -> str:
    """Return the stored API key ('' if none).

    Order: keyring (Windows Credential Manager) -> settings.toml fallback.
    """
    kr = _get_keyring()
    if kr is not None:
        try:
            secret = kr.get_password(SERVICE_NAME, KEY_NAME)  # type: ignore[attr-defined]
            if secret:
                return str(secret).strip()
        except Exception as e:
            logger.warning("keyring read failed: %s", e)
    # Fallback: plaintext [key_storage] table in settings.toml
    try:
        import toml

        path = _fallback_path()
        if path.is_file():
            data = toml.load(path)
            section = data.get("key_storage")
            if isinstance(section, dict):
                return str(section.get("api_key", "") or "").strip()
    except Exception as e:
        logger.warning("settings.toml key fallback read failed: %s", e)
    return ""


def key_is_stored() -> bool:
    return bool(load_key())


def save_key(key: str) -> str:
    """Persist the API key. Returns which backend was used: 'keyring' or 'plaintext'.

    An empty key clears all stored copies (same as clear_key()).
    """
    key = (key or "").strip()
    if not key:
        clear_key()
        return "keyring" if is_keyring_available() else "plaintext"

    kr = _get_keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE_NAME, KEY_NAME, key)  # type: ignore[attr-defined]
            # Do not leave stale plaintext copies around once keyring works.
            _clear_fallback()
            logger.info("API key stored in %s", backend_name())
            return "keyring"
        except Exception as e:
            logger.warning("keyring write failed (%s); storing in settings.toml", e)

    _write_fallback(key)
    return "plaintext"


def clear_key() -> None:
    """Remove the stored key from the keyring and the plaintext fallback."""
    kr = _get_keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE_NAME, KEY_NAME)  # type: ignore[attr-defined]
            logger.info("API key removed from %s", backend_name())
        except Exception:
            pass  # nothing stored, or backend refused; still clear the fallback
    _clear_fallback()


# --- plaintext fallback helpers -------------------------------------------------


def _read_fallback_data() -> Tuple[Optional[Path], dict]:
    path = _fallback_path()
    if not path.is_file():
        return path, {}
    try:
        import toml

        return path, (toml.load(path) or {})
    except Exception as e:
        logger.warning("Could not parse %s: %s", path, e)
        return path, {}


def _write_fallback(key: str) -> None:
    import toml

    path, data = _read_fallback_data()
    path.parent.mkdir(parents=True, exist_ok=True)
    section = data.get("key_storage")
    if not isinstance(section, dict):
        section = {}
        data["key_storage"] = section
    section["api_key"] = key
    with open(path, "w", encoding="utf-8") as f:
        toml.dump(data, f)
    logger.warning(
        "API key stored PLAINTEXT in %s (keyring unavailable) — "
        "this is a documented tradeoff; consider installing keyring",
        path,
    )


def _clear_fallback() -> None:
    import toml

    path, data = _read_fallback_data()
    section = data.get("key_storage")
    if not isinstance(section, dict) or "api_key" not in section:
        return
    section.pop("api_key", None)
    if not section:
        data.pop("key_storage", None)
    try:
        with open(path, "w", encoding="utf-8") as f:
            toml.dump(data, f)
    except Exception as e:
        logger.warning("Could not update %s: %s", path, e)
