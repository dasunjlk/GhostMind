"""
U-01 update checker: discovery, grace-period state, download + verification.

Design notes (release plan PART 3):
- Source of truth: GitHub releases/latest JSON (URL overridable for QA).
- The 5-day grace clock starts the FIRST time a given newer version is seen,
  not at the release date (offline users get their full grace).
- "now" prefers the HTTP Date header (anti clock-rollback); local time falls back.
- Network failure = silently skip: offline users are never nagged, never locked.
- QA hooks (read once per call, for tests/QA only):
    GHOSTMIND_UPDATE_URL   — override the releases URL (file:// JSON works)
    GHOSTMIND_FORCE_UPDATE — 1 pretends a newer version exists
    GHOSTMIND_GRACE_DAYS   — override the 5-day grace (e.g. 0 for lock testing)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_UPDATE_URL = "https://api.github.com/repos/dasunjlk/GhostMind/releases/latest"
GRACE_DAYS_DEFAULT = 5
DAY_SEC = 86_400
CHECK_INTERVAL_SEC = 6 * 3_600  # in-app re-check cadence
POPUP_SNOOZE_SEC = DAY_SEC  # "Later" hides the popup for 24h

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = REPO_ROOT / "config" / "update_state.json"

# Consecutive failed download attempts before the 24h safety valve appears (3.6).
MAX_CONSECUTIVE_FAILURES = 3

_ASSET_RE = re.compile(r"GhostMind-Setup-(?P<ver>[0-9][\w.]*)\.exe$", re.IGNORECASE)
_SHA_LINE_RE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$")


class UpdaterError(RuntimeError):
    """User-actionable updater failure (download, checksum, missing asset)."""


# --------------------------------------------------------------------------- #
# Version math
# --------------------------------------------------------------------------- #

def parse_version(version: str) -> Tuple[int, int, int]:
    """'v1.10.2' -> (1, 10, 2); missing parts are 0; non-numeric parts ignored."""
    v = (version or "").strip().lower().lstrip("v")
    parts: List[int] = []
    for chunk in v.split("."):
        m = re.match(r"\d+", chunk)
        parts.append(int(m.group()) if m else 0)
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


# --------------------------------------------------------------------------- #
# State file (config/update_state.json, gitignored)
# --------------------------------------------------------------------------- #

def default_state() -> Dict[str, object]:
    return {
        "known_latest_version": "",
        "first_seen_epoch": 0,
        "last_popup_epoch": 0,
        "popup_count": 0,
        "snooze_until_epoch": 0,
        "failed_attempts": 0,
    }


def load_state(path: Path = STATE_PATH) -> Dict[str, object]:
    state = default_state()
    try:
        if Path(path).is_file():
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                state.update({k: v for k, v in data.items() if k in state})
    except Exception as e:
        logger.warning("Could not read update state %s: %s", path, e)
    return state


def save_state(state: Dict[str, object], path: Path = STATE_PATH) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.warning("Could not write update state %s: %s", path, e)


# --------------------------------------------------------------------------- #
# Release discovery
# --------------------------------------------------------------------------- #

def _update_url() -> str:
    return os.environ.get("GHOSTMIND_UPDATE_URL", "").strip() or DEFAULT_UPDATE_URL


def _grace_days() -> int:
    raw = os.environ.get("GHOSTMIND_GRACE_DAYS", "").strip()
    if raw:
        try:
            return max(0, int(raw))
        except ValueError:
            logger.warning("Invalid GHOSTMIND_GRACE_DAYS=%r; using default", raw)
    return GRACE_DAYS_DEFAULT


def fetch_latest_release(timeout: float = 10.0) -> Optional[Tuple[dict, int]]:
    """Return (release_json, now_epoch) or None on ANY failure.

    now_epoch prefers the server Date header (hardens the grace clock against
    system-clock rollback); local time is the fallback (file:// QA payloads).
    Never raises.
    """
    url = _update_url()
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "GhostMind-Updater",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            date_header = resp.headers.get("Date") if hasattr(resp, "headers") else None
    except Exception as e:
        logger.info("Update check skipped (%s: %s)", type(e).__name__, e)
        return None
    now_epoch: Optional[int] = None
    if date_header:
        try:
            now_epoch = int(
                parsedate_to_datetime(date_header).timestamp()
            )
        except Exception:
            now_epoch = None
    return data, (now_epoch if now_epoch is not None else int(time.time()))


# --------------------------------------------------------------------------- #
# Pure decision logic (fully unit-testable, no network)
# --------------------------------------------------------------------------- #

@dataclass
class UpdateCheck:
    tag: str = ""                 # remote version, e.g. "1.1.0"
    notes: str = ""               # release body (plain text)
    assets: List[dict] = None     # type: ignore[assignment]  # release assets (installer, checksums)
    update_available: bool = False
    locked: bool = False          # grace expired AND not snoozed → must update
    grace_expired: bool = False   # grace over even if snoozed right now
    days_left: int = 0            # whole days remaining in grace
    should_popup: bool = False    # 24h popup throttle satisfied
    first_popup_for_version: bool = False  # for the one-time tray balloon
    now: int = 0
    state: Optional[Dict[str, object]] = None


def evaluate_check(
    release: dict,
    local_version: str,
    state: Dict[str, object],
    now: int,
    grace_days: Optional[int] = None,
) -> UpdateCheck:
    """Pure transition function: release JSON + local state → what the UI does."""
    if grace_days is None:
        grace_days = _grace_days()
    state = dict(state)
    tag = str(release.get("tag_name", "") or "").strip().lstrip("vV")
    notes = str(release.get("body", "") or "")

    # No newer release (or user already updated) → reset the clock/state.
    if not tag or not is_newer(tag, local_version):
        if state.get("known_latest_version"):
            state = default_state()
        return UpdateCheck(
            tag=tag, notes=notes, assets=list(release.get("assets") or []),
            update_available=False,
            now=now, state=state,
        )

    update_available = True
    first_popup_for_version = False

    # First time THIS version is detected → (re)start the grace clock.
    if state.get("known_latest_version") != tag or not state.get("first_seen_epoch"):
        state["known_latest_version"] = tag
        state["first_seen_epoch"] = now
        state["last_popup_epoch"] = 0
        state["popup_count"] = 0
        state["snooze_until_epoch"] = 0
        state["failed_attempts"] = 0
        first_popup_for_version = True

    first_seen = int(state.get("first_seen_epoch") or now)
    elapsed_days = max(0.0, (now - first_seen) / DAY_SEC)
    grace_expired = elapsed_days >= grace_days
    # Whole days of grace remaining (ceil), 0 once expired.
    days_left = max(0, int(grace_days - elapsed_days + 0.999)) if not grace_expired else 0

    snoozed = now < int(state.get("snooze_until_epoch") or 0)
    locked = grace_expired and not snoozed

    last_popup = int(state.get("last_popup_epoch") or 0)
    should_popup = (last_popup == 0) or (now - last_popup >= POPUP_SNOOZE_SEC)

    return UpdateCheck(
        tag=tag,
        notes=notes,
        assets=list(release.get("assets") or []),
        update_available=update_available,
        locked=locked,
        grace_expired=grace_expired,
        days_left=days_left,
        should_popup=should_popup,
        first_popup_for_version=first_popup_for_version,
        now=now,
        state=state,
    )


def check_for_update(
    local_version: str,
    state_path: Path = STATE_PATH,
    now: Optional[int] = None,
) -> Optional[UpdateCheck]:
    """Full check: fetch → evaluate → persist state. None = skip silently."""
    fetched = fetch_latest_release()
    if fetched is None:
        return None  # offline / rate-limited / bad payload → never nag, never lock
    release, server_now = fetched
    if os.environ.get("GHOSTMIND_FORCE_UPDATE", "").strip() == "1":
        release = dict(release)
        release["tag_name"] = "v999.0.0"
        release.setdefault("body", "QA forced update")

    now = now if now is not None else server_now
    state = load_state(state_path)
    result = evaluate_check(release, local_version, state, now)
    if result.state is not None and result.state != state:
        save_state(result.state, state_path)
    return result


# --------------------------------------------------------------------------- #
# Popup / snooze bookkeeping
# --------------------------------------------------------------------------- #

def record_popup(state_path: Path = STATE_PATH, now: Optional[int] = None) -> None:
    now = now if now is not None else int(time.time())
    state = load_state(state_path)
    state["last_popup_epoch"] = now
    state["popup_count"] = int(state.get("popup_count") or 0) + 1
    save_state(state, state_path)


def record_snooze(state_path: Path = STATE_PATH, until_epoch: Optional[int] = None) -> None:
    if until_epoch is None:
        until_epoch = int(time.time()) + POPUP_SNOOZE_SEC
    state = load_state(state_path)
    state["snooze_until_epoch"] = int(until_epoch)
    save_state(state, state_path)


def record_failed_attempt(state_path: Path = STATE_PATH) -> int:
    """Increment and return the consecutive-failure counter (safety valve)."""
    state = load_state(state_path)
    count = int(state.get("failed_attempts") or 0) + 1
    state["failed_attempts"] = count
    save_state(state, state_path)
    return count


def reset_failed_attempts(state_path: Path = STATE_PATH) -> None:
    state = load_state(state_path)
    state["failed_attempts"] = 0
    save_state(state, state_path)


# --------------------------------------------------------------------------- #
# Assets, download, SHA-256 verification
# --------------------------------------------------------------------------- #

def pick_release_assets(release: dict) -> Tuple[Optional[dict], Optional[dict]]:
    """Return (setup_exe_asset, checksums_asset) from a release JSON."""
    setup: Optional[dict] = None
    checksums: Optional[dict] = None
    for asset in release.get("assets", []) or []:
        name = str(asset.get("name", ""))
        if _ASSET_RE.search(name) and setup is None:
            setup = asset
        elif name.strip().lower() == "sha256sums.txt" and checksums is None:
            checksums = asset
    return setup, checksums


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_sha256(path: Path, checksums_text: str) -> bool:
    """True if path's name maps to a matching sha256 in checksums_text."""
    want = None
    for line in checksums_text.splitlines():
        m = _SHA_LINE_RE.match(line.strip())
        if m and m.group(2).strip().lower() == path.name.lower():
            want = m.group(1).lower()
            break
    if not want:
        return False  # no entry → treat as unverified
    return sha256_of(path) == want


def installer_dest(version: str) -> Path:
    return Path(os.environ.get("TEMP", os.getcwd())) / f"GhostMind-Setup-{version}.exe"


def download_file(
    url: str,
    dest: Path,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    timeout: float = 30.0,
) -> Path:
    """Chunked download to dest. progress_cb(received_bytes, total_bytes_or_0)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "GhostMind-Updater"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        received = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                received += len(chunk)
                if progress_cb:
                    progress_cb(received, total)
    return dest


def download_installer(
    release: dict,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    state_path: Path = STATE_PATH,
) -> Path:
    """Pick assets → download to %TEMP% → verify SHA256.

    Returns the verified installer path.
    Raises UpdaterError with a user-actionable message on any failure and
    records the failure for the 24h safety-valve counter.
    """
    setup, checksums = pick_release_assets(release)
    if setup is None:
        _fail(state_path, "The installer asset was not found on the release page. "
                          "Use 'Open release page in browser' to download it manually.")
    if checksums is None:
        _fail(state_path, "Checksums file (SHA256SUMS.txt) missing on the release. "
                          "Refusing to run an unverified installer.")

    tag = str(release.get("tag_name", "")).strip().lstrip("vV")
    dest = installer_dest(tag)
    try:
        download_file(str(setup.get("browser_download_url", "")), dest, progress_cb)  # type: ignore[arg-type]
        sums_url = str(checksums.get("browser_download_url", ""))  # type: ignore[union-attr]
        req = urllib.request.Request(sums_url, headers={"User-Agent": "GhostMind-Updater"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            sums_text = resp.read().decode("utf-8", errors="replace")
        if not verify_sha256(dest, sums_text):
            try:
                dest.unlink()
            except OSError:
                pass
            _fail(state_path, "Checksum mismatch — the download is corrupt or tampered with. "
                              "It was deleted. Use 'Open release page in browser' to retry manually.")
    except UpdaterError:
        raise
    except Exception as e:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        _fail(state_path, f"Download failed: {e}")

    reset_failed_attempts(state_path)
    logger.info("Installer downloaded and verified: %s", dest)
    return dest


def _fail(state_path: Path, message: str) -> None:
    record_failed_attempt(state_path)
    raise UpdaterError(message)
