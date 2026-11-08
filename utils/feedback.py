"""In-app user feedback via the privacy-safe Sentry channel (C13).

Users send praise, bug reports, and ideas from the Feedback tab in Settings.
Transport is the SAME Sentry project the error reports use — no new backend,
no tokens in the binary — so a feedback can be correlated with the sending
install's earlier crash events via the anonymous install UUID.

Privacy rules, mirroring utils/error_reporter.py:
- Free text and the optional contact are scrubbed (API keys, secret
  assignments, home paths, identity strings) before anything is stored.
- The whole channel respects GHOSTMIND_NO_TELEMETRY=1: nothing is sent and
  nothing is stored when reporting is disabled — the UI offers a
  copy-to-clipboard fallback instead.
- Send failures park the payload in a local outbox (JSONL in the app data
  dir) that is flushed best-effort on the next launch.

The installed sentry-sdk has no dedicated feedback API, so the payload goes
out as a Sentry feedback event (`type: "feedback"` + `contexts.feedback`,
the documented ingest format) via capture_event. The C13 manual QA item
verifies arrival in the Sentry User Feedback dashboard.
"""
from __future__ import annotations

import json
import logging
import platform
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils import app_paths, error_reporter
from version import __version__

logger = logging.getLogger(__name__)

FEEDBACK_TYPES = ("works_great", "bug", "suggestion", "other")
RATING_MIN = 1
RATING_MAX = 5
OUTBOX_DIRNAME = "config"
OUTBOX_FILENAME = "feedback_outbox.jsonl"

_DISABLED_NOTE = (
    "Anonymous reporting is disabled on this install ({reason}). "
    "Copy your feedback and post it at "
    "https://github.com/dasunjlk/GhostMind/issues instead."
)
_SAVED_NOTE = "Saved — we'll send it next time you're online."
_RETRY_NOTE = "We couldn't send your feedback right now. Please try again later."


def outbox_path(data_dir: Optional[Path] = None) -> Path:
    """JSONL outbox location, resolved at call time (test-overridable)."""
    root = Path(data_dir) if data_dir is not None else app_paths.data_dir()
    return root / OUTBOX_DIRNAME / OUTBOX_FILENAME


def os_label() -> str:
    """Short OS string for the 'what gets sent' line."""
    try:
        return f"{platform.system()} {platform.release()}".strip()
    except Exception:  # pragma: no cover - platform never fails realistically
        return "Windows"


def install_id_prefix() -> str:
    """First 8 chars of the anonymous install UUID (never the whole id)."""
    try:
        iid = error_reporter.load_or_create_install_id(app_paths.data_dir())
        return (iid or "anonymous")[:8]
    except Exception:  # pragma: no cover - defensive
        return "anonymous"


def build_payload(
    type_key: str,
    rating: Optional[int],
    text: str,
    contact: str,
) -> Dict[str, Any]:
    """Build the scrubbed, self-contained feedback payload.

    Everything the user typed is scrubbed here — the outbox and the Sentry
    event both carry only this dict. Unknown types fall back to "other" and
    out-of-range ratings become None rather than raising: feedback must
    never fail to build.
    """
    clean_type = type_key if type_key in FEEDBACK_TYPES else "other"
    try:
        rating_val = int(rating) if rating is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        rating_val = None
    if rating_val is not None and not (RATING_MIN <= rating_val <= RATING_MAX):
        rating_val = None
    return {
        "type": clean_type,
        "rating": rating_val,
        "text": error_reporter.scrub_text(str(text or "").strip()),
        "contact": error_reporter.scrub_text(str(contact or "").strip()),
        "version": __version__,
        "os": os_label(),
        "install_id": install_id_prefix(),
    }


def _send_event(payload: Dict[str, Any]) -> bool:
    """Transmit one payload as a Sentry feedback event. Never raises."""
    import sentry_sdk

    contact = str(payload.get("contact") or "")
    event: Dict[str, Any] = {
        "type": "feedback",
        "level": "info",
        "contexts": {
            "feedback": {
                "message": str(payload.get("text") or "(no message)"),
                "name": contact or "GhostMind user",
                "contact_email": contact or None,
                "source": "not_user",
            }
        },
        "user": {"id": str(payload.get("install_id") or "anonymous")},
        "extra": {
            "app_version": payload.get("version"),
            "os": payload.get("os"),
            "rating": payload.get("rating"),
        },
        "tags": {"feedback_type": str(payload.get("type") or "other")},
    }
    event_id = sentry_sdk.capture_event(event)
    return bool(event_id)


def submit_feedback(
    payload: Dict[str, Any],
    data_dir: Optional[Path] = None,
) -> Tuple[bool, str]:
    """Send one feedback payload; on failure park it in the local outbox.

    Returns (True, "") on success, or (False, user-facing reason). When the
    telemetry channel is disabled nothing is sent AND nothing is stored —
    the UI shows the reason and its copy-to-clipboard fallback instead.
    """
    active, reason = error_reporter.feedback_channel_state()
    if not active:
        return False, _DISABLED_NOTE.format(reason=reason)
    try:
        if _send_event(payload):
            return True, ""
    except Exception as e:
        logger.warning("Feedback send failed: %s", e)
    try:
        _append_outbox(payload, data_dir)
    except Exception as e:
        logger.warning("Feedback outbox write failed: %s", e)
        return False, _RETRY_NOTE
    return False, _SAVED_NOTE


def _append_outbox(payload: Dict[str, Any], data_dir: Optional[Path] = None) -> None:
    path = outbox_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_outbox(data_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Read queued payloads; corrupt lines are skipped, never raised."""
    path = outbox_path(data_dir)
    items: List[Dict[str, Any]] = []
    try:
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except Exception:
                    continue
                if isinstance(data, dict):
                    items.append(data)
    except Exception as e:
        logger.warning("Could not read feedback outbox %s: %s", path, e)
    return items


def flush_outbox(data_dir: Optional[Path] = None) -> int:
    """Best-effort resend of outboxed feedback. Returns the count sent.

    Silently does nothing when reporting is disabled. Unsent payloads stay
    queued for the next launch.
    """
    active, _reason = error_reporter.feedback_channel_state()
    if not active:
        return 0
    items = load_outbox(data_dir)
    if not items:
        return 0
    remaining: List[Dict[str, Any]] = []
    sent = 0
    for payload in items:
        try:
            if _send_event(payload):
                sent += 1
            else:
                remaining.append(payload)
        except Exception as e:
            logger.warning("Outbox resend failed: %s", e)
            remaining.append(payload)
    path = outbox_path(data_dir)
    try:
        if remaining:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in remaining),
                encoding="utf-8",
            )
        elif path.exists():
            path.unlink()
    except Exception as e:
        logger.warning("Could not rewrite feedback outbox: %s", e)
    return sent
