# GHOSTMIND — RELEASE PLAN (Windows Desktop, v1.0.0)

**Created:** 2026-09-12  
**Platform:** WINDOWS ONLY for this release (Win 10 2004+ / Win 11)  
**Source:** Feature selection from future-plan.md (24 features, 4 tiers)  
**Target:** Distributable `.exe` installer published on GitHub Releases

## Release Philosophy

Ship the smallest version that is stable, installable by a non-technical user, self-updating, and honest about its dependencies. Everything else is a future update. A feature is RELEASE-MANDATORY only if:

- (a) the app is broken/embarrassing without it, OR
- (b) a non-technical user cannot use the app without it, OR
- (c) it protects the user or the project legally/operationally.

---

## PART 1 — FEATURES INCLUDED IN v1.0 (MANDATORY)

### R-01 [MUST] PACKAGING: .EXE + INSTALLER *(future-plan F-22)*

**Why mandatory:** the definition of "desktop app release".

**Details** (from F-22, condensed for release):

- PyInstaller ONEDIR build (NOT one-file: faster-whisper / sounddevice / pywin32 binaries break in one-file mode).

  `ghostmind.spec`:
  - hiddenimports: `faster_whisper`, `sounddevice`, `win32gui`, `win32con`, `win32api`, `keyboard`
  - datas: `assets/**` (icon.ico, fonts), LICENSE
  - excludes: `tests/`, tkinter, matplotlib

- Installer: Inno Setup (script: `installer/ghostmind.iss`)
  - Per-user install (no admin required): `DefaultDirName={localappdata}\GhostMind`
  - Desktop shortcut (checkbox, default on), Start Menu folder
  - Optional "Start with Windows" checkbox → writes the existing registry autostart key (`utils/autostart.py` already supports it)
  - Uninstaller removes app dir; leaves `config/` and logs (document this)
- Tesseract: NOT bundled. On first run the existing dependency dialog shows a "Install Tesseract OCR" button that opens the UB-Mannheim download page (F-22's deep-link option — the silent-downloader variant is deferred to v1.1).
- Sound: PyInstaller apps trigger AV false positives occasionally. Run the built exe through Windows Defender + upload to virustotal BEFORE release; document any residual SmartScreen warning in README.

**Acceptance:**

- Fresh Windows 10 VM with NO Python installed: install → run → OCR works after Tesseract side-install; Whisper downloads on first use; tray + overlay + hotkeys all functional.
- Uninstall leaves no Start Menu entry; relaunch-after-install works.

### R-02 [MUST] UPDATE CHECK + UPDATE POPUP WITH 5-DAY GRACE RULE *(NEW, see PART 3)*

**Why mandatory:** the user's explicit release requirement. Fully specified in PART 3 of this file (feature U-01).

**Acceptance (summary):**

- New release detected → popup appears.
- Days 0–4: popup can be closed; app fully usable; reminded again later.
- Day 5+: popup cannot be closed; user must update to keep using the app (with the offline safety valve described in PART 3).

### R-03 [MUST] API KEY PERSISTENCE *(future-plan F-24g)*

**Why mandatory:** today the API key set in the Settings panel is stored ONLY in `os.environ` for the current session (`settings_panel._emit_save`). A non-technical desktop user has no way to persist a key across restarts without hand-editing a `.env` file. The app would appear broken every reboot.

**Details:**

- New dependency: `keyring` (Windows Credential Manager backend, no native build needed on Windows).
- Settings Save → `keyring.set_password("GhostMind", "GROQ_API_KEY", k)`
- `core/ai_engine._get_client()`: read keyring first, then `GROQ_API_KEY` env/.env (existing behavior) as fallback.
- Settings panel: "Key saved to Windows Credential Manager" status line + "Clear stored key" button.
- If keyring import fails (rare) → fall back to writing the key into `config/settings.toml` with a console warning (accept the plaintext tradeoff; document it).

**Acceptance:**
Paste key in Settings, Save, restart app → AI answers work with no `.env` file present.

### R-04 [MUST] REMEMBER WINDOW POSITION / SIZE *(future-plan F-06)*

**Why mandatory:** effort is hours; forgetting geometry is the most visible polish gap for a desktop overlay app (resets to 480x600 center every launch). Users will read it as "buggy".

**Details:** exactly as F-06 (persist `window_x/y/w/h` + `window_screen` in `config/settings.toml`, debounced save on move/resize/hide, clamp into available geometry on restore, graceful default if screen is gone).

**Acceptance:** move/resize/quit/relaunch → same spot, same size.

### R-05 [MUST] PRE-RELEASE CODE FIXES *(future-plan F-24 a-f)*

**Why mandatory:** release blockers or cheap hygiene that ships broken in every screenshot of the app.

- a) [ ] README "Llama 3.1 70B" references → actual model `qwen/qwen3.8-27b` (Features section, Architecture diagram, and the stale comment in `core/ai_engine.py` header).
- b) [ ] `.env.example`: delete the two stray "[TEMPLATE]" lines.
- c) [ ] Delete stray pip artifact `"=0.10.2"` from repo root: `git rm "=0.10.2"` (MUST quote it — leading `=` and glob chars)
- d) [ ] Move `_QUESTION_RE` out of `ui/subtitle_bar.py` into a new `core/question_detect.py`; subtitle_bar imports from there; add unit tests for the question patterns.
- e) [ ] AiStreamWorker 429 handling: read retry-after from the Groq error response; exponential backoff 1s/2s/4s (cap 30s, max 3 retries) replacing the flat 0.3s sleep; surface "(rate limited, retrying...)" in the stream only when delay > 3s.
- f) [ ] `resample_to_16k`: remove the aliasing `audio[::3]` 48kHz shortcut; use `np.interp` for every rate (no new dependency). Verify `tests/test_features.py` still pass (length math unchanged).
- g) → covered separately as R-03 (keyring), released with v1.0.

**Acceptance:** ruff clean, pytest green, grep shows no "Llama 3.1" left.

### R-06 [MUST] RELEASE AUTOMATION *(future-plan F-22)*

**Why mandatory:** reproducible, low-risk releases.

**Details:**

- `.github/workflows/release.yml`: on tag push (`v*`):
  checkout → setup-python 3.11 → `pip install -r requirements.txt pyinstaller` → build Inno Setup (iscc via choco on runner) → zip onedir output → create GitHub Release (softprops/action-gh-release) → attach installer + portable zip + SHA256 checksums.
- Versioning discipline:
  - `version.py` is the single source of truth (`__version__ = "1.0.0"`)
  - Tag must match version.py; add a CI assertion step that fails the release job if git tag != version.py value.
- Artifacts naming:
  - `GhostMind-Setup-1.0.0.exe`
  - `GhostMind-Portable-1.0.0.zip`
  - `SHA256SUMS.txt`

**Acceptance:** pushing tag v1.0.0 produces a Release page with all three artifacts, download-verified on a clean VM.

---

## PART 2 — SHOULD-HAVE (IN v1.0 ONLY IF TIME ALLOWS; CUT WITHOUT BLOCKING)

Ordered by value-per-hour. Cut from the bottom up if the release date slips. Each maps to a future-plan feature ID.

### S-01 [SHOULD] STOP BUTTON FOR STREAMING *(F-03, cancellation half only)*

- `request_stop()` threading.Event + `cancelled` signal in AiStreamWorker; Stop button on the streaming block; partial text kept as "(stopped)".
- The request QUEUE half of F-03 is DEFERRED to v1.1 (current drop-when-busy behavior is acceptable for v1.0 with a clear error message: "Already processing another answer.").

### S-02 [SHOULD] WHISPER FIRST-RUN DOWNLOAD PROGRESS *(F-14)*

- Strongly recommended because the target user is non-technical: today the app looks frozen for ~1-2 min on first run while the Whisper model downloads. Info block with % in the Answers panel.

### S-03 [SHOULD] PAUSE/RESUME CAPTURE HOTKEY *(F-15)*

- Ctrl+Shift+P, runtime-only pause via threading.Event (no model reload), red strip indicator + tray balloon. Privacy escape hatch = trust builder for a screen+mic-capturing app.

### S-04 [SHOULD] MANUAL QUESTION INPUT BOX *(F-01)*

- Biggest UX gap after packaging, but the app is usable without it (OCR + audio flows), so it yields to schedule pressure.

### S-05 [SHOULD] OCR LANGUAGE SETTING *(F-16)*

- `ocr_lang` setting, `tesseract --list-langs` population, pass-through to `extract_text()`.

### S-06 [SHOULD] BASIC CI *(F-21)*

- windows-latest: ruff + pytest on push/PR. mypy and pytest-qt can wait for v1.1. The release workflow (R-06) is independent and mandatory.

---

## PART 3 — FEATURE SPEC: U-01 UPDATE POPUP WITH 5-DAY GRACE RULE

### U-01 [MUST, NEW FEATURE] FORCED-UPDATE NAGGER

**REQUIREMENT (verbatim intent):**
When a new update is released and the user has not updated, show a popup window. Within the FIRST 5 DAYS the user may close the popup and keep using the app. AFTER 5 DAYS the popup can no longer be closed: the user must update, otherwise they cannot use the app.

#### 3.1 UPDATE DISCOVERY

- `utils/updater.py` (NEW). Source of truth:
  `GET https://api.github.com/repos/dasunjlk/GhostMind/releases/latest`
  Parse `tag_name` (strip leading `v`), compare with `version.__version__` using tuple comparison of integer parts — `(1,10,0) > (1,9,0)`; tolerate missing patch part.
- Check cadence:
  - once at app launch (after tray init, before `overlay.show`)
  - then every 6 hours while running (QTimer)

  Cache responses in `config/update_state.json` — never check more than once per 6h window even across restarts.
- Network failure / GitHub unreachable / rate-limited → SILENTLY skip. Offline users are never nagged and never locked out (see 3.6).
- QA/testing hooks (document in README-dev section):
  - `GHOSTMIND_UPDATE_URL` — override the releases URL (point at a private test repo or local `file://` JSON)
  - `GHOSTMIND_FORCE_UPDATE` — `0|1`, pretend a newer version exists
  - `GHOSTMIND_GRACE_DAYS` — override the 5 for testing (e.g. 0)

  These env vars are for QA only and are read once at startup.

#### 3.2 STATE FILE

`config/update_state.json` (gitignored; created on first detection):

```json
{
  "known_latest_version": "1.1.0",
  "first_seen_epoch": 1760000000,
  "last_popup_epoch": 1760000000,
  "popup_count": 3,
  "snooze_until_epoch": 0
}
```

- `first_seen_epoch` = start of grace clock; `last_popup_epoch` = throttle re-prompting; `snooze_until_epoch` = used by safety valve 3.6.
- The 5-day clock starts the FIRST TIME this version is detected (`first_seen_epoch`), NOT at the release date — so users who were offline get their full 5 days.
- Reset the file when `version.__version__ >= known_latest_version` (user updated) or when a DIFFERENT newer version is detected (clock restarts for the new version).

#### 3.3 AUTHORITATIVE TIME (ANTI CLOCK-ROLLBACK)

- Grace math uses the `Date` HTTP response header from api.github.com (server time) as "now" when available; local `time.time()` is the fallback. This prevents bypassing the lock by rolling the system clock back. Note the caveat honestly: a user who is fully offline falls into the never-locked-out path (3.6) anyway, so this only hardens the online case.

#### 3.4 POPUP WINDOW — PHASE 1: GRACE PERIOD (day 0 to day 4)

- QDialog (or frameless custom window matching app style):
  - Title: "GhostMind update available"
  - Body: "Version 1.1.0 is available (you have 1.0.0)."
    + release notes (release body, plain text, scrollable, max ~400px)
    + "Update recommended. You can keep using this version for X more days."
  - Buttons: **[Update Now]** [Later]
  - Close (X) button: ENABLED in this phase.
- "Update Now" → see 3.7 (download & run installer).
- "Later" / X → close; snooze: do not show again for 24h (`last_popup_epoch + 86400`). Also shown at most once per app launch even if the 24h math says so.
- Tray balloon on detection (first time only per version): "GhostMind 1.1.0 available — click for details".

#### 3.5 POPUP WINDOW — PHASE 2: LOCK (day 5 and later)

- Trigger: at launch, or when the 6-hour in-app timer fires and `now - first_seen_epoch >= 5 days` AND newer version still installed.
- Window becomes a persistent, application-modal, always-on-top dialog:
  - close (X) button HIDDEN, Esc and Alt+F4 blocked (reject/ignore closeEvent), window has no system menu
  - Title: "Update required"
  - Body: "Your version (1.0.0) is no longer supported. Update to 1.1.0 to continue using GhostMind."
  - Progress bar during download (3.7), errors inline with [Retry]
  - Buttons: [Update Now] (only button; becomes [Restart installer] once downloaded)
- While locked:
  - the main overlay is hidden and disabled
  - tray menu reduced to "Update now" and "Quit" (quit is allowed — quitting is not updating, and the lock reapplies at next launch)
  - hotkeys unregistered (`HotkeyManager.unregister_all`) so the overlay cannot be resurrected
- IMPLEMENTATION NOTE: `apply_stealth`/WDA_EXCLUDEFROMCAPTURE must NOT be applied to the update window (it must be visible in screen shares so support can see it) — the opposite of the main overlay.

#### 3.6 SAFETY VALVE (MANDATORY — PREVENTS BRICKING USERS)

- If, AFTER the grace period expired, the app CANNOT complete an update because the network/GitHub/installer download fails on 3 consecutive attempts, show within the locked window:
  **[Continue for 24 hours]**
  which unlocks the app until `now + 24h` (`snooze_until_epoch`), then locks again. This keeps the 5-day rule intact (it cannot be used to avoid updating indefinitely: it re-locks) while guaranteeing a temporary GitHub outage or a broken mirror never permanently locks a paying... er, an innocent user out of the app they already have installed.
- Fully offline at launch + grace expired: attempt check 3x with 30s gaps, then apply the same 24h unlock automatically and log it. On a machine that is genuinely never online again, the app keeps working (acceptable tradeoff; a user with no internet cannot download an update no matter what we do).

#### 3.7 THE "UPDATE NOW" FLOW (v1.0 SCOPE — SIMPLE AND ROBUST)

1. GET the release assets from the releases/latest JSON; pick the asset named `GhostMind-Setup-<version>.exe` (+ `SHA256SUMS.txt`).
2. Download to `%TEMP%\GhostMind-Setup-<version>.exe` with `urllib.request` (chunked, progress → popup progress bar, 30s connect / no global timeout).
3. Verify SHA256 against `SHA256SUMS.txt`. Mismatch → delete file, inline error, [Retry]. No verification → NO execution, ever.
4. `os.startfile(installer_path)`; `app.quit()` (Inno Setup will prompt to close/replace; per-user install needs no elevation).
5. Fallback link in the popup: "Open release page in browser" — always present, covers every failure mode.
- AUTO-RELAUNCH after install is a v1.1 nice-to-have; for v1.0 the user starts the app manually after the installer finishes (document this in the popup: "The installer will close GhostMind. Start GhostMind again when the installer finishes.")

#### 3.8 FILES TO TOUCH

- `utils/updater.py` — NEW: check, state file, download+verify
- `ui/update_popup.py` — NEW: grace dialog + locked modal
- `main.py` — startup check wiring, 6h QTimer, lock mode: overlay hide, hotkey unregister, tray menu reduction
- `config/update_state.json` — runtime artifact, gitignored (add entry)
- `tests/test_updater.py` — NEW: version compare, state transitions, grace math (pure logic, no network: inject fake JSON + frozen timestamps)
- `README.md` — "Updates" section for users

#### 3.9 ACCEPTANCE TESTS (QA SCRIPT — SEE PART 5)

- **T1** New version published → popup within 6h or at next launch.
- **T2** Close popup on day 2 → app usable; popup returns at next launch after 24h snooze.
- **T3** Set `GHOSTMIND_GRACE_DAYS=0` → locked modal appears; X/Esc/Alt+F4 do nothing; overlay hidden; hotkeys dead.
- **T4** Update Now on locked window → download % → SHA256 verified → installer runs → app quits → after install, new version starts with NO popup (state reset).
- **T5** Block network on locked window (grace expired) → 3 failed attempts → [Continue for 24 hours] works; re-locks after 24h.
- **T6** Offline machine, never updated → never locked out.
- **T7** System clock rolled back after first_seen → server Date header defeats it (grace does not reset).

---

## PART 4 — DEFERRED TO FUTURE UPDATES (NOT IN v1.0)

Everything from future-plan.md not listed in PART 1/2, with targets. (Feature IDs refer to future-plan.md.)

### v1.1 (first patch feature drop)

- F-03 queue half (meeting-question priority queue)
- F-04 region-select OCR
- F-07 screen-change detection
- F-13 live markdown streaming
- F-17 themes/accent picker (needs `utils/theme.py` refactor first)
- F-18 combined session report
- F-23 remaining test coverage (config_io, stealth pure-math, settings merge, question-flow)
- Auto-relaunch after update (U-01 3.7 enhancement)

### v1.2

- F-02 multi-turn chat / follow-ups
- F-05 vision-based screen understanding (needs Groq catalog check + cost review)
- F-08 auto session-type detection
- F-09 answer action buttons (Shorter/Explain/Bullets)
- F-10 answer cache

### v1.3+ / later

- F-11 speaker diarization
- F-12 chunked summarize for long lectures (token budgeting)
- F-19 Ollama/local offline backend
- F-20 popout answer windows
- Silent Tesseract installer download (R-01 upgrade)
- mypy strict, pytest-qt UI tests, coverage >= 70% gate

### Explicitly OUT of scope (unchanged from future-plan.md)

- macOS / Linux support
- Cloud sync of settings or transcripts
- Any server-side component (GhostMind stays a pure client app)

---

## PART 5 — PRE-RELEASE QA CHECKLIST

### Environment matrix (manual, VM snapshots)

- [ ] Win 10 2004, clean (no Python, no Tesseract)
- [ ] Win 10 22H2, clean
- [ ] Win 11, clean
- [ ] Win 11, multi-monitor (geometry restore + mss monitor ids)

### Functional

- [ ] Install per-user (no admin), first launch, tray icon appears
- [ ] Dependency dialog: Tesseract deep-link works; app still starts
- [ ] API key: paste → save → restart → answers work (R-03)
- [ ] OCR scan, audio capture (mic + loopback), meeting question flow
- [ ] All 6 hotkeys; tray show/hide/export/quit; close → hides to tray
- [ ] Settings save/reload round-trip; import/export JSON
- [ ] Window geometry restore across restart and across monitor changes
- [ ] Transcript export .txt and .md
- [ ] Whisper first-run download on a clean VM (S-02 if included)

### Update system (U-01): run tests T1–T7 from 3.9

- [ ] (Use `GHOSTMIND_UPDATE_URL` against a private test repo with a fake v1.0.1 release — never test the flow against the real repo)

### Distribution

- [ ] virustotal scan of installer: explain/disperse any hits BEFORE release (PyInstaller + keyboard lib are common false-positive sources)
- [ ] SmartScreen behavior documented in README if unsigned
- [ ] SHA256SUMS.txt matches artifacts
- [ ] Uninstaller: app removed, config/logs retained, Start Menu clean

### Legal/paperwork

- [ ] LICENSE (MIT) present in installer dir and Release page
- [ ] Third-party notices: PyInstaller bundles; note Tesseract is NOT distributed (Apache-2.0 — only installed by the user separately)
- [ ] Security & ethics section of README visible on the Release page (this app's stealth features make the disclaimer non-optional)

---

## PART 6 — RELEASE-DAY RUNBOOK (v1.0.0)

1. [ ] Freeze: PART 1 + chosen PART 2 items merged to main; CI green.
2. [ ] Bump `version.py` to 1.0.0 (if not already), update TODO.md.
3. [ ] Tag: `git tag -a v1.0.0 -m "GhostMind 1.0.0 — first Windows release"` then `git push origin v1.0.0`
4. [ ] Release workflow builds; verify artifacts + checksums on Release page; smoke-test the installer from the Release page on a clean VM (do NOT reuse the dev VM).
5. [ ] Publish Release with notes:
   - What it is (2 lines), features, prerequisites (Tesseract, Groq free key), known limitations (Windows only, unsigned exe SmartScreen note, no region OCR yet)
   - Security & ethics section
6. [ ] Post-release: watch Issues; keep v1.0.1 hotfix path ready (re-run runbook with version bump; hotfixes ship via the SAME update channel — which also exercises U-01 in the wild).
7. [ ] Start v1.1 branch work from PART 4 order.

### Timeline (suggested, ~1.5 weeks elapsed)

| Day | Work |
|-----|------|
| Day 1–2 | R-05 code fixes + R-04 geometry + R-03 keyring |
| Day 3 | U-01 updater + popup + tests |
| Day 4 | R-01 packaging (PyInstaller + Inno Setup) iterations |
| Day 5 | R-06 release workflow; should-have items (S-01..S-06) as time allows |
| Day 6–7 | Full QA matrix (PART 5) |
| Day 8 | v1.0.0 tag + publish |

---

## CHANGELOG OF THIS PLAN

- **2026-09-12 — v1.0:** Initial release plan: 6 mandatory items (R-01..R-06), 6 should-have (S-01..S-06), forced-update spec U-01 with 5-day grace rule + offline safety valve, deferred-feature roadmap, QA matrix, runbook.
