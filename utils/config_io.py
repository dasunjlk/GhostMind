"""
Settings import/export utilities.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import toml

logger = logging.getLogger(__name__)


def export_settings(data: Dict[str, Any], path: str) -> None:
    """Export settings to a JSON file (human-readable, shareable)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    # Remove internal fields that shouldn't be shared
    clean = {k: v for k, v in data.items() if not k.startswith("_")}
    p.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Settings exported to %s", path)


def import_settings(path: str) -> Optional[Dict[str, Any]]:
    """Import settings from a JSON file. Returns None on failure."""
    p = Path(path)
    if not p.is_file():
        logger.warning("Settings file not found: %s", path)
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            logger.warning("Invalid settings format in %s", path)
            return None
        logger.info("Settings imported from %s", path)
        return data
    except Exception as e:
        logger.error("Failed to import settings: %s", e)
        return None
