"""
Anonymous error reporting via Sentry (errors only, no PII).

What is captured:
- Uncaught exceptions (main thread, Qt slots, worker threads) via the SDK's
  default excepthook/threading integrations — our wrapper flush()es them
  before PyQt may abort the process.
- Every ``logger.error`` / ``logger.exception`` / ``logger.critical`` record
  app-wide (LoggingIntegration: WARNING+ breadcrumbs, ERROR+ events).
- ``QtCriticalMsg`` / ``QtFatalMsg`` emitted through qInstallMessageHandler.

What is NEVER sent:
- Transcripts, questions, window titles, API keys, file contents.
- Local variables are excluded (include_local_variables=False) — user data
  frequently lives in frame locals in this app.
- Usernames, hostnames, and home paths are scrubbed from every string field
  (see ``scrub_text``), as are obvious secret patterns.

Identity: a random UUID4 in ``config/anonymous_id.txt`` (separate from
settings.toml so Settings export can never leak it). No other user data.

Silently disabled when: no DSN is configured, GHOSTMIND_NO_TELEMETRY=1,
or running under pytest. Everything here is exception-safe: error reporting
must never break the app.

QA hooks (same spirit as utils/updater.py):
    GHOSTMIND_SENTRY_DSN     — override the DSN (e.g. a scratch project)
    GHOSTMIND_NO_TELEMETRY   — "1" disables reporting entirely
    GHOSTMIND_FORCE_TELEMETRY — "1" forces on even under pytest (tests)
    GHOSTMIND_TEST_ERROR     — "1" logs a synthetic error at startup
"""
from __future__ import annotations

import logging
import os
import re
import socket
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from version import __version__

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

# Sentry DSN — paste the value from your Sentry project (Settings → Client Keys).
# DSNs are write-only ingest keys designed to ship inside client apps.
SENTRY_DSN = "https://394b56f0371559115df97920f5aebe4e@o4512281741754368.ingest.us.sentry.io/4512281771442176"

ENV_DSN = "GHOSTMIND_SENTRY_DSN"
ENV_NO_TELEMETRY = "GHOSTMIND_NO_TELEMETRY"
ENV_FORCE_TELEMETRY = "GHOSTMIND_FORCE_TELEMETRY"
ENV_TEST_ERROR = "GHOSTMIND_TEST_ERROR"

ID_FILENAME = "anonymous_id.txt"

_MAX_MESSAGE = 2000
_MAX_TRACEBACK = 8000
_MAX_BREADCRUMBS = 30

# --------------------------------------------------------------------------- #
# Redaction patterns
# --------------------------------------------------------------------------- #

_USER_PATH_RE = re.compile(r"([A-Za-z]:[\\/]+Users[\\/]+)[^\\/:\s\"']+", re.IGNORECASE)
_KEY_RE = re.compile(r"\b(gsk_[A-Za-z0-9]{8,}|sk-[A-Za-z0-9_-]{8,})")
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|token|password|passwd|secret|authorization)"
    r"(\s*[:=]\s*)([^\s,;\"']+)"
)

# --------------------------------------------------------------------------- #
# Module state
# --------------------------------------------------------------------------- #

_SDK: Any = None
_INSTALLED = False
_PREV_EXCEPTHOOK: Optional[Callable[..., Any]] = None


# --------------------------------------------------------------------------- #
# Anonymous install id
# --------------------------------------------------------------------------- #

def load_or_create_install_id(root: Path) -> Optional[str]:
    """Return the stable random UUID4 install id, creating it on first run."""
    path = Path(root) / "config" / ID_FILENAME
    try:
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        value = str(uuid.uuid4())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return value
    except Exception as e:
        logger.warning("Could not persist anonymous install id: %s", e)
        return None


# --------------------------------------------------------------------------- #
# Scrubbing (pure, fully unit-testable)
# --------------------------------------------------------------------------- #

def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"…[truncated {len(text) - limit} chars]"


# Generic built-in account names identify nobody and would collide with the
# "<user>" path placeholder — never used as scrub needles.
GENERIC_ACCOUNTS = {
    "user", "users", "admin", "administrator", "guest", "owner",
    "default", "desktop", "laptop", "windows", "home",
}


def identity_needles() -> List[str]:
    """Strings that identify this machine/user and must never leave it."""
    raw: List[str] = [
        os.environ.get("USERNAME", ""),
        os.environ.get("USER", ""),
        os.environ.get("COMPUTERNAME", ""),
        os.environ.get("HOSTNAME", ""),
    ]
    try:
        import getpass

        raw.append(getpass.getuser())
    except Exception:
        pass
    try:
        host = socket.gethostname()
        raw.append(host)
        raw.append(host.split(".")[0])
    except Exception:
        pass
    unique = {n for n in raw if n and len(n) >= 3 and n.lower() not in GENERIC_ACCOUNTS}
    # Longest first: replace the full name before any short prefix of it.
    return sorted(unique, key=len, reverse=True)


def scrub_text(text: str, needles: Optional[List[str]] = None) -> str:
    """Redact home paths, API keys, secret assignments, and identity strings."""
    if not isinstance(text, str) or not text:
        return text
    out = _USER_PATH_RE.sub(r"\1<user>", text)
    out = _KEY_RE.sub("***", out)
    out = _SECRET_ASSIGN_RE.sub(r"\1\2***", out)
    for needle in needles or ():
        if needle and len(needle) >= 3:
            out = re.sub(re.escape(needle), "***", out, flags=re.IGNORECASE)
    return out


def _scrub_obj(obj: Any, needles: List[str], depth: int = 0) -> None:
    """Recursively scrub string values of a dict/list in place (bounded depth)."""
    if depth > 6:
        return
    if isinstance(obj, dict):
        for key, value in list(obj.items()):
            if isinstance(value, str):
                obj[key] = scrub_text(value, needles)
            elif isinstance(value, (dict, list)):
                _scrub_obj(value, needles, depth + 1)
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            if isinstance(value, str):
                obj[index] = scrub_text(value, needles)
            elif isinstance(value, (dict, list)):
                _scrub_obj(value, needles, depth + 1)


def _scrub_stacktrace(stacktrace: Any, needles: List[str]) -> None:
    if not isinstance(stacktrace, dict):
        return
    for frame in stacktrace.get("frames") or []:
        if not isinstance(frame, dict):
            continue
        for key in ("filename", "abs_path"):
            if isinstance(frame.get(key), str):
                frame[key] = scrub_text(frame[key], needles)
        # Source context and locals are disable-flags in init(); drop them here
        # too so an SDK default change can never leak them.
        for key in ("context_line", "pre_context", "post_context", "vars", "source_link"):
            frame.pop(key, None)


def _scrub_event(event: Dict[str, Any], _hint: Any, needles: List[str]) -> Optional[Dict[str, Any]]:
    """before_send hook: redact, slim down, and drop noisy internal events."""
    try:
        if str(event.get("logger") or "").startswith("sentry_sdk"):
            return None  # never report the reporter's own transport failures
        event.pop("server_name", None)  # SDK default would send the hostname
        event.pop("request", None)
        user = event.get("user")
        if isinstance(user, dict):
            uid = user.get("id")
            event["user"] = {"id": uid} if uid else {}
        if isinstance(event.get("message"), str):
            event["message"] = _clip(scrub_text(event["message"], needles), _MAX_MESSAGE)
        logentry = event.get("logentry")
        if isinstance(logentry, dict):
            if isinstance(logentry.get("message"), str):
                logentry["message"] = _clip(scrub_text(logentry["message"], needles), _MAX_MESSAGE)
            # "formatted" holds the interpolated text and "params" the raw
            # values — scrub every string in the logentry, not just message.
            _scrub_obj(logentry, needles)
        for exc in (event.get("exception") or {}).get("values") or []:
            if not isinstance(exc, dict):
                continue
            if isinstance(exc.get("value"), str):
                exc["value"] = _clip(scrub_text(exc["value"], needles), _MAX_TRACEBACK)
            _scrub_stacktrace(exc.get("stacktrace"), needles)
        _scrub_stacktrace(event.get("stacktrace"), needles)
        threads = event.get("threads")
        if isinstance(threads, dict):
            for thread in threads.get("values") or []:
                if isinstance(thread, dict):
                    _scrub_stacktrace(thread.get("stacktrace"), needles)
        breadcrumbs = event.get("breadcrumbs")
        if isinstance(breadcrumbs, dict):
            for crumb in breadcrumbs.get("values") or []:
                if isinstance(crumb, dict):
                    if isinstance(crumb.get("message"), str):
                        crumb["message"] = scrub_text(crumb["message"], needles)
                    _scrub_obj(crumb.get("data"), needles)
        for key in ("tags", "extra", "contexts"):
            _scrub_obj(event.get(key), needles)
        return event
    except Exception:
        return event  # a scrub bug must never silence the report itself


# --------------------------------------------------------------------------- #
# Wiring
# --------------------------------------------------------------------------- #

def _reporting_disabled() -> Tuple[bool, str]:
    if os.environ.get(ENV_NO_TELEMETRY, "").strip() == "1":
        return True, f"{ENV_NO_TELEMETRY}=1"
    if os.environ.get(ENV_FORCE_TELEMETRY, "").strip() == "1":
        return False, ""
    if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
        return True, "running under pytest"
    return False, ""


def _resolve_dsn() -> str:
    return os.environ.get(ENV_DSN, "").strip() or SENTRY_DSN.strip()


def _environment() -> str:
    return "production" if getattr(sys, "frozen", False) else "development"


def _excepthook(exc_type: Any, exc_value: Any, exc_tb: Any) -> None:
    """Chain to the SDK's hook, then flush — PyQt may abort right after this."""
    prev = _PREV_EXCEPTHOOK
    if prev is not None:
        try:
            prev(exc_type, exc_value, exc_tb)
        except Exception:
            pass
    flush(timeout=3.0)


def _install_qt_message_handler() -> None:
    try:
        from PyQt6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:
        return

    def handler(mode: Any, _context: Any, message: str) -> None:
        if mode not in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            return
        try:
            if _SDK is not None:
                _SDK.capture_message(f"Qt: {message}", level="error")
                if mode == QtMsgType.QtFatalMsg:
                    flush(timeout=3.0)
        except Exception:
            pass

    try:
        qInstallMessageHandler(handler)
    except Exception:
        pass


def _maybe_emit_test_error() -> None:
    if os.environ.get(ENV_TEST_ERROR, "").strip() != "1":
        return
    try:
        try:
            raise RuntimeError(f"{ENV_TEST_ERROR} synthetic error (QA hook)")
        except RuntimeError:
            logging.getLogger("ghostmind.qa").exception("QA hook: synthetic error report")
        flush(timeout=5.0)
    except Exception:
        pass


def install(root: Path) -> bool:
    """Install hooks and initialize Sentry. Returns True when active.

    Call once, after QApplication exists. Never raises; when inactive the
    app behaves exactly as before (no hooks, no network).
    """
    global _SDK, _INSTALLED, _PREV_EXCEPTHOOK
    if _INSTALLED:
        return _SDK is not None
    _INSTALLED = True

    disabled, reason = _reporting_disabled()
    if disabled:
        logger.info("Error reporting disabled (%s)", reason)
        return False
    dsn = _resolve_dsn()
    if not dsn:
        logger.info("Error reporting disabled (no Sentry DSN configured)")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration
    except Exception as e:
        logger.warning("sentry-sdk unavailable; error reporting disabled: %s", e)
        return False

    install_id = load_or_create_install_id(Path(root))
    needles = identity_needles()

    def before_send(event: Dict[str, Any], hint: Any) -> Optional[Dict[str, Any]]:
        return _scrub_event(event, hint, needles)

    try:
        sentry_sdk.init(
            dsn=dsn,
            release=f"ghostmind@{__version__}",
            environment=_environment(),
            integrations=[LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR)],
            send_default_pii=False,
            include_local_variables=False,
            include_source_context=False,
            attach_stacktrace=True,
            traces_sample_rate=0.0,
            auto_session_tracking=False,
            server_name=install_id or "ghostmind-client",
            max_breadcrumbs=_MAX_BREADCRUMBS,
            before_send=before_send,
        )
        if install_id:
            sentry_sdk.set_user({"id": install_id})
        sentry_sdk.set_tag("frozen", "true" if getattr(sys, "frozen", False) else "false")
    except Exception as e:
        logger.warning("Sentry init failed; error reporting disabled: %s", e)
        return False

    _SDK = sentry_sdk
    _PREV_EXCEPTHOOK = sys.excepthook
    sys.excepthook = _excepthook
    _install_qt_message_handler()
    _maybe_emit_test_error()
    logger.info("Anonymous error reporting enabled (release ghostmind@%s)", __version__)
    return True


def flush(timeout: float = 2.0) -> None:
    """Flush pending events (safe no-op when reporting is inactive)."""
    sdk = _SDK
    if sdk is None:
        return
    try:
        sdk.flush(timeout=timeout)
    except Exception:
        pass


def reset() -> None:
    """Reset module state (tests only; does not uninstall SDK integrations)."""
    global _SDK, _INSTALLED, _PREV_EXCEPTHOOK
    _SDK = None
    _INSTALLED = False
    _PREV_EXCEPTHOOK = None
