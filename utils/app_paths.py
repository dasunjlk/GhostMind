"""Writable application-data paths for source runs, frozen builds, and tests."""
from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

APP_DIR_NAME = "GhostMind"
DATA_DIR_NAME = "data"
ENV_DATA_DIR = "GHOSTMIND_DATA_DIR"

SETTINGS_FILENAME = "settings.toml"
LOG_FILENAME = "ghostmind.log"
UPDATE_STATE_FILENAME = "update_state.json"
ANONYMOUS_ID_FILENAME = "anonymous_id.txt"


def is_frozen() -> bool:
    """True when running from a PyInstaller build."""
    return bool(getattr(sys, "frozen", False))


def install_root() -> Path:
    """Directory containing the app's bundled files."""
    return Path(__file__).resolve().parent.parent


def _override_dir() -> Optional[Path]:
    raw = os.environ.get(ENV_DATA_DIR, "").strip()
    return Path(raw).expanduser() if raw else None


def _flat_layout() -> bool:
    """Frozen builds and explicit overrides keep data files directly in the data dir."""
    return _override_dir() is not None or is_frozen()


def data_dir() -> Path:
    """Writable user-data root, outside the install directory when frozen."""
    override = _override_dir()
    if override is not None:
        return override
    if is_frozen():
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / APP_DIR_NAME / DATA_DIR_NAME
        return Path.home() / f".{APP_DIR_NAME.lower()}" / DATA_DIR_NAME
    return install_root()


def settings_path() -> Path:
    if _flat_layout():
        return data_dir() / SETTINGS_FILENAME
    return install_root() / "config" / SETTINGS_FILENAME


def log_path() -> Path:
    if _flat_layout():
        return data_dir() / LOG_FILENAME
    return install_root() / LOG_FILENAME


def update_state_path() -> Path:
    if _flat_layout():
        return data_dir() / UPDATE_STATE_FILENAME
    return install_root() / "config" / UPDATE_STATE_FILENAME


def migrate_legacy_data(
    legacy_root: Optional[Path] = None,
    data_root: Optional[Path] = None,
) -> List[Path]:
    """Copy install-local user data into the writable data dir, never overwriting."""
    legacy = Path(legacy_root) if legacy_root is not None else install_root()
    target = Path(data_root) if data_root is not None else data_dir()
    if legacy.resolve() == target.resolve():
        return []

    candidates = [
        (legacy / "config" / SETTINGS_FILENAME, target / SETTINGS_FILENAME),
        (legacy / "config" / UPDATE_STATE_FILENAME, target / UPDATE_STATE_FILENAME),
        (
            legacy / "config" / ANONYMOUS_ID_FILENAME,
            target / "config" / ANONYMOUS_ID_FILENAME,
        ),
    ]
    candidates.extend(
        (source, target / source.name)
        for source in sorted(legacy.glob(f"{LOG_FILENAME}*"))
        if source.is_file()
    )

    copied: List[Path] = []
    for source, destination in candidates:
        if not source.is_file() or destination.exists():
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        except OSError as error:
            logger.warning("Could not migrate %s to %s: %s", source, destination, error)
        else:
            copied.append(destination)
    return copied
