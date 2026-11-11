"""
Secure API-key storage, one slot per provider host.

Primary store: the OS credential manager via the `keyring` package
(Windows Credential Manager on Windows — no native build needed).
Fallback: a plaintext `[key_storage."<host>"]` table inside the active
`settings.toml`, used only when keyring is unavailable (documented tradeoff).

Order of operations (matches the release plan, R-03):
- save_key_for(): keyring first; on failure writes the plaintext fallback.
- load_key_for(): keyring first, then the plaintext fallback.
- clear_key_for(): removes the secret from both stores.

Legacy installs used a single `GROQ_API_KEY` keyring slot and a flat
`[key_storage].api_key` entry. Both are still read as a fallback for
`api.groq.com`; they are never copied into the new slot automatically.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlparse

from utils import app_paths

logger = logging.getLogger(__name__)

SERVICE_NAME = "GhostMind"
LEGACY_KEY_NAME = "GROQ_API_KEY"
# Backwards-compatible alias for callers/tests that still refer to the old name.
KEY_NAME = LEGACY_KEY_NAME
GROQ_HOST = "api.groq.com"

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
    return app_paths.settings_path()


def sanitize_host(host: str) -> str:
    """Normalize a host (or URL) into a stable, TOML/keyring-safe label."""
    raw = (host or "").strip().lower()
    if "://" in raw:
        try:
            raw = urlparse(raw).netloc or raw
        except ValueError:
            pass
    raw = raw.rsplit("@", 1)[-1]
    cleaned = re.sub(r"[^a-z0-9.-]+", "_", raw).strip("._")
    return cleaned or "default"


def _key_name(host: str) -> str:
    return f"API_KEY::{sanitize_host(host)}"


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


def _read_fallback_section() -> dict:
    """Return the `[key_storage]` table from settings.toml (or {})."""
    path = _fallback_path()
    if not path.is_file():
        return {}
    try:
        import toml

        data = toml.load(path)
        section = data.get("key_storage") if isinstance(data, dict) else None
        return section if isinstance(section, dict) else {}
    except Exception as e:
        logger.warning("settings.toml key fallback read failed: %s", e)
        return {}


def load_key_for(host: str) -> str:
    """Return the stored API key for `host` ('' if none).

    Order: keyring slot -> settings.toml slot -> legacy Groq keyring slot ->
    legacy flat settings.toml key (Groq only).
    """
    host = sanitize_host(host)
    kr = _get_keyring()

    if kr is not None:
        try:
            secret = kr.get_password(SERVICE_NAME, _key_name(host))  # type: ignore[attr-defined]
            if secret:
                return str(secret).strip()
        except Exception as e:
            logger.warning("keyring read failed for %s: %s", host, e)

    section = _read_fallback_section()
    entry = section.get(host)
    if isinstance(entry, dict):
        key = str(entry.get("api_key", "") or "").strip()
        if key:
            return key

    # Legacy single-slot installs: only the default Groq host may use them.
    if host == GROQ_HOST:
        if kr is not None:
            try:
                secret = kr.get_password(SERVICE_NAME, LEGACY_KEY_NAME)  # type: ignore[attr-defined]
                if secret:
                    return str(secret).strip()
            except Exception as e:
                logger.warning("legacy keyring read failed: %s", e)
        legacy = str(section.get("api_key", "") or "").strip()
        if legacy:
            return legacy

    return ""


def key_is_stored_for(host: str) -> bool:
    return bool(load_key_for(host))


def save_key_for(host: str, key: str) -> str:
    """Persist the key for `host`. Returns 'keyring' or 'plaintext'.

    An empty key clears all stored copies for that host (same as clear_key_for()).
    """
    host = sanitize_host(host)
    key = (key or "").strip()
    if not key:
        clear_key_for(host)
        return "keyring" if is_keyring_available() else "plaintext"

    kr = _get_keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE_NAME, _key_name(host), key)  # type: ignore[attr-defined]
            # Do not leave stale plaintext copies around once keyring works.
            _clear_fallback_for(host, clear_legacy=(host == GROQ_HOST))
            logger.info("API key for %s stored in %s", host, backend_name())
            return "keyring"
        except Exception as e:
            logger.warning(
                "keyring write failed for %s (%s); storing in settings.toml", host, e
            )

    _write_fallback_for(host, key)
    return "plaintext"


def clear_key_for(host: str) -> None:
    """Remove the stored key for `host` from the keyring and plaintext fallback."""
    host = sanitize_host(host)
    kr = _get_keyring()
    names = [_key_name(host)]
    if host == GROQ_HOST:
        names.append(LEGACY_KEY_NAME)
    if kr is not None:
        for name in names:
            try:
                kr.delete_password(SERVICE_NAME, name)  # type: ignore[attr-defined]
                logger.info("API key for %s removed from %s", host, backend_name())
            except Exception:
                pass  # nothing stored, or backend refused; still clear fallback
    _clear_fallback_for(host, clear_legacy=(host == GROQ_HOST))


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


def _write_fallback_for(host: str, key: str) -> None:
    import toml

    host = sanitize_host(host)
    path, data = _read_fallback_data()
    path.parent.mkdir(parents=True, exist_ok=True)
    section = data.get("key_storage")
    if not isinstance(section, dict):
        section = {}
        data["key_storage"] = section
    entry = section.get(host)
    if not isinstance(entry, dict):
        entry = {}
    entry["api_key"] = key
    section[host] = entry
    if host == GROQ_HOST:
        # The nested slot is canonical now; don't keep a second plaintext copy.
        section.pop("api_key", None)
    with open(path, "w", encoding="utf-8") as f:
        toml.dump(data, f)
    logger.warning(
        "API key stored PLAINTEXT in %s (keyring unavailable) — "
        "this is a documented tradeoff; consider installing keyring",
        path,
    )


def _clear_fallback_for(host: str, clear_legacy: bool = False) -> None:
    import toml

    host = sanitize_host(host)
    path, data = _read_fallback_data()
    section = data.get("key_storage")
    if not isinstance(section, dict):
        return
    changed = False
    if host in section:
        section.pop(host, None)
        changed = True
    if clear_legacy and "api_key" in section:
        section.pop("api_key", None)
        changed = True
    if not changed:
        return
    if not section:
        data.pop("key_storage", None)
    try:
        with open(path, "w", encoding="utf-8") as f:
            toml.dump(data, f)
    except Exception as e:
        logger.warning("Could not update %s: %s", path, e)


# --- backwards-compatible Groq wrappers ----------------------------------------


def load_key() -> str:
    """Legacy alias: load the key for the default Groq host."""
    return load_key_for(GROQ_HOST)


def key_is_stored() -> bool:
    return bool(load_key())


def save_key(key: str) -> str:
    """Legacy alias: save the key for the default Groq host."""
    return save_key_for(GROQ_HOST, key)


def clear_key() -> None:
    """Legacy alias: clear the key for the default Groq host."""
    clear_key_for(GROQ_HOST)


def _write_fallback(key: str) -> None:
    """Legacy test/helper alias: write the Groq plaintext fallback."""
    _write_fallback_for(GROQ_HOST, key)


def _clear_fallback() -> None:
    """Legacy test/helper alias: clear the Groq plaintext fallback."""
    _clear_fallback_for(GROQ_HOST, clear_legacy=True)
