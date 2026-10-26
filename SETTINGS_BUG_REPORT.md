# Bug Report — Settings will not open / API key cannot be added

| Field | Value |
| --- | --- |
| Report ID | GM-BUG-2026-10-26-01 |
| Date | 2026-10-26 |
| Status | Open — root cause confirmed |
| Severity | P0 — blocks first-run setup; app is unusable |
| Affected versions | v1.0.0, v1.0.1 (and any build with the current startup dialog) |
| Fixed in | TBD (target v1.0.2) |
| Baseline | `main` @ `b5b470e` (v1.0.1) |
| Proposed branch | `fix/settings-open-api-key` |
| Reporter | User's friend (Windows, installed build) |

---

## 1. Executive summary

Yes — this is a real bug, not a user mistake.

On startup, GhostMind schedules a **parentless, application-modal "Dependency Warnings" dialog** 200 ms after launch (`main.py:729-738`, `main.py:661-681`). The main overlay is an **always-on-top Tool window** (`ui/overlay_window.py:310-314`). The dialog is not topmost, so it can render **behind** the overlay — but because it is modal, the visible overlay ignores every click while it is open. That makes the Settings gear appear dead.

A new user triggers this dialog easily:

- **v1.0.0:** "No Groq API key found" is always a warning. A new user has no key, so they get the dialog on every launch — but they cannot open Settings to add the key, because the dialog is blocking it.
- **v1.0.1:** The API-key warning was removed, but **Tesseract OCR is an external dependency** that most users do not have. If Tesseract is missing, the same blocking dialog appears on every launch. It has no "Don't show again" option.
- v1.0.1 is safe **only** on machines where Tesseract is already installed (verified here: no warnings → no dialog → Settings works).

The reported symptoms — "cannot open Settings by clicking the gear", "cannot put the API key", "app not working" — match this failure exactly.

---

## 2. Reported symptoms

From the reporter (translated/normalized):

- Clicking the Settings gear does nothing, no matter how many times it is clicked.
- Settings cannot be opened, so the API key cannot be entered.
- The app does not work (AI answers fail without a key).
- She tried repeatedly.

Still needed from the reporter: exact version, Windows version, Tesseract installed or not, whether a "GhostMind — Dependency Warnings" window appears in Alt+Tab, display scaling, and the log tail. See §10.

---

## 3. Affected versions and scope

| Version | Affected? | When |
| --- | --- | --- |
| v1.0.0 | Yes | Always, until an API key is already stored; also when Tesseract is missing |
| v1.0.1 | Yes | Whenever Tesseract is missing (or any startup dependency warning fires) |
| Source/dev run | Only if Tesseract is missing | The startup dialog still exists in source |
| Future builds | Yes, until fixed | Current code path is unchanged |

The Settings panel itself works when no modal dialog is present. This bug is about **startup warnings blocking input**, not about the gear button or the Settings page.

---

## 4. Reproduction

### 4.1 Confirmed: modal dialog is behind the topmost overlay

A standalone test recreated the exact window flags:

1. Always-on-top, frameless `Qt.Tool` window (the overlay pattern).
2. A parentless `QMessageBox` with `ApplicationModal`, shown 300 ms later.
3. `EnumWindows` z-order check while both were visible.

Result on Windows 11:

```text
z[7]  GhostMind overlay (topmost test)
z[20] GhostMind - Dependency Warnings
```

Lower index = higher in the z-order. The overlay is above the dialog; the screenshot shows the dialog partially hidden behind the overlay. The dialog still owns the application-modal input lock, so clicks on the overlay are discarded.

This is exactly the production pattern in `main.py` and `ui/overlay_window.py`.

### 4.2 Fresh v1.0.1 install without Tesseract

1. Install v1.0.1 on a Windows machine without Tesseract.
2. Launch GhostMind. The overlay appears.
3. At +200 ms, a parentless "Dependency Warnings" message box is opened with `exec()`.
4. Depending on the overlay position, the dialog is fully or partly hidden behind the overlay.
5. Click the gear: nothing happens. The overlay is input-blocked by the modal dialog.
6. Press `Enter` (the hidden dialog still has focus) or find it with `Alt+Tab` and click OK.
7. The overlay becomes interactive; the gear now opens Settings.

Installing Tesseract removes the warning entirely. On the developer machine with Tesseract installed, v1.0.1 launches with no dialog and the gear works.

### 4.3 Fresh v1.0.0 install (no API key)

Even with Tesseract installed, v1.0.0 adds a "No Groq API key found" warning. That guarantees the blocking dialog on first launch — the dialog tells the user to open Settings → API while simultaneously making Settings unreachable.

### 4.4 Settings panel itself (control test)

With no modal dialog, `_toggle_settings()` switches the stacked page to Settings and shows it (`ui/overlay_window.py:655-662`). Verified live:

- Overlay: 480 x 600.
- Settings panel: 474 x 558.
- API key field: visible at `x=108, y=123`, size `341 x 26`.
- "Check key & model" button: visible at `y=196`, size `341 x 30`.
- "Clear stored key": visible.
- Save button: visible at `y=519`.

So the gear handler, the panel layout, and the API controls are not the blocker at the default window size.

---

## 5. Findings

### P0-1 — Startup warning dialog can be invisible yet input-blocking

**Evidence**

- `main.py:729-738` — after the overlay is shown, `QTimer.singleShot(200, lambda: _dependency_dialog(msg).exec())` opens an application-modal message box.
- `main.py:661-681` — `_dependency_dialog()` constructs `QMessageBox()` **with no parent** and never sets a topmost flag or raises it above the overlay.
- `ui/overlay_window.py:310-314` — overlay window flags include `WindowStaysOnTopHint | Tool | FramelessWindowHint`.
- `main.py:758` — the overlay is shown before the event loop; the dialog fires 200 ms later.
- Qt `ApplicationModal` blocks input to every window in the application, including the overlay.

**Impact**

- Gear/Settings can never receive a click while the dialog is open.
- API key cannot be entered; AI cannot work.
- The app looks frozen; there is no visible error on top.
- A non-technical user has no obvious recovery.

**Why it varies by machine**

- v1.0.0: the missing API key warning always fires.
- v1.0.1+: missing Tesseract (very common) fires it.
- Whether the dialog is fully hidden or partly visible depends on screen size and the overlay's saved position/geometry.

**Recommended fix (pick one primary strategy)**

1. **Non-modal, in-overlay warning banner** (preferred): never block startup. Show a dismissible banner inside the overlay with "Install Tesseract" and "Open Settings" actions.
2. If a modal dialog is kept: parent it to the overlay, add `WindowStaysOnTopHint`, show it centered on the overlay, and call `raise_()`/`activateWindow()`. Add a "Don't show again" checkbox and a Settings shortcut.
3. Remove startup warnings for dependencies that are bundled in the frozen app (groq, faster-whisper, sounddevice, keyboard). Warn only when the user actually tries a feature that needs an external dependency.
4. Add a regression test that asserts the dialog is raised above the overlay and that Settings is reachable while warnings exist.

### P0-2 — The warning is repeated on every launch with no dismissal or route to Settings

- No "Don't show again" state is persisted.
- The dialog has an "Install Tesseract OCR" action only when Tesseract is the missing piece; otherwise just OK.
- It never offers "Open Settings", which is ironic because the user's next required step is Settings.
- If the dialog is hidden behind the overlay, there is no visible cue that a dialog exists.

**Fix:** persist dismissal, add "Open Settings" and "Install Tesseract" actions, and show a small warning badge/button in the overlay when action is required.

### P1-1 — Settings is only reachable through a small unlabeled gear

- The only entry point is the 26 x 26 gear glyph (`ui/overlay_window.py:387-396`); its meaning depends on hover tooltip.
- The system tray menu contains only Show, Hide, and Quit (`main.py:289-314`). There is no Settings item.
- If the overlay is hidden or input-blocked, Settings is unreachable.

**Fix:** add a "Settings…" tray action (show overlay + open Settings), add a keyboard shortcut, and add a visible "Add API key" call-to-action on the answer panel when no key is stored. Consider labeling the gear or making it more prominent.

### P1-2 — Click-through mode is a recovery trap

- The pointer icon sits immediately left of the gear (`ui/overlay_window.py:417-424`). Clicking it enables click-through, where the overlay passes mouse input to the window underneath.
- The click guard polls the cursor every 50 ms and makes the header interactive when hovered (`ui/overlay_window.py:300-306`, `767-802`), but a quick click immediately after moving the cursor can be lost.
- The tray menu has no click-through toggle, and the only documented recovery is `Ctrl+Shift+X`. A novice can easily turn this on by accident and conclude the gear is broken.
- This is a second plausible explanation for "the gear does nothing" and cannot be ruled out from the report alone.

**Fix:** add click-through on/off to the tray menu, show a clear on-screen indicator when it is active, and/or remove the pointer toggle from the header. Never enable click-through while Settings is open.

### P2-1 — API key Save flow reports success even when the save failed

- `ui/settings_panel.py:521-540`: after `key_store.save_key(k)`, the handler emits `saved` (which closes Settings) regardless of whether the key save raised. The warning is shown, but Settings still closes.
- It clears the key field and then calls `_on_test_api()`, which re-reads the now-empty field and relies on the just-saved key being present in the keyring/fallback. If the save failed, the test runs without the pasted key and can show a misleading error.
- On the developer machine, keyring works (`API key stored in WinVaultKeyring` in `ghostmind.log`), so this is not the primary blocker here, but it is a likely source of "I pasted the key but it does not work" reports.

**Fix:** emit `saved` only after a successful save, pass the key explicitly to the validation call, keep Settings open on failure, and show the error next to the field.

### P2-2 — Frozen keyring backend is not explicitly collected

- `ghostmind.spec:61` adds only `'keyring'` to `hiddenimports`; keyring's platform backends (`keyring.backends.Windows`) are not listed.
- Keyring backend discovery can fail in frozen builds, silently falling back to the plaintext `[key_storage]` section.
- Not reproduced on this machine (WinVaultKeyring worked in the installed v1.0.0), but it should be verified on a clean VM and made explicit.

**Fix:** collect keyring backends/submodules in the spec and add a packaged-app test that asserts the backend name.

### P2-3 — User data lives inside the install directory

- `main.py:111-112` and `main.py:153` place `settings.toml`, `update_state.json`, and `ghostmind.log` under `REPO_ROOT` (`_internal` in the frozen app).
- This works for the per-user `%LOCALAPPDATA%` install, but it mixes user data with program files. The plaintext key fallback and user settings are then inside the install folder, at risk during updates/uninstall, and harder for users to find.
- **Fix:** move user data to `%LOCALAPPDATA%\GhostMind\data` (with a one-time migration) and keep the install directory read-only.

### P2-4 — No first-run onboarding for the API key

- v1.0.1 starts silently with no key. The only guidance is the error text produced after the first AI action (`core/ai_engine.py:289-292`), and there is no clickable "Open Settings" action.
- A user whose first action fails may not know the gear is the way to fix it.

**Fix:** on first launch (or whenever no key is stored), show a non-blocking "Add your free Groq API key" banner with an Open Settings button.

### Ruled out / not the cause

- **Gear click handler / Settings page construction:** works; `_toggle_settings` switches and shows the panel; 325 tests passed before the dependency merges.
- **API tab layout at the default 480 x 600 window:** the key field, test button, and Save button are visible (measurements in §4.4), although the hidden Audio tab inflates the panel size hint; low-DPI layout is fine. Still test 125%/150% scaling and the 320 x 360 minimum window.
- **Key storage on the developer machine:** works via Windows Credential Manager (log evidence). The friend's machine is unverified.
- **Config file permissions:** the per-user install under `%LOCALAPPDATA%` is writable.

---

## 6. Evidence

| Evidence | Result |
| --- | --- |
| Z-order test with topmost overlay + parentless modal box | Overlay `z[7]`, dialog `z[20]` — overlay is above the dialog |
| Live screenshot of the same test | Dialog visibly partly behind the overlay |
| Source Settings toggle with no warnings | Settings opens; API key field and Save visible |
| Installed v1.0.1 log on this machine | `ghostmind@1.0.1`, `API key stored in WinVaultKeyring`, no dependency warnings |
| `tests/test_dependency_dialog.py` | Tests the dialog's buttons only; does not test parenting, z-order, or blocking |
| `tests/test_click_through.py` | Tests Settings interactivity while click-through is on; does not cover the startup dialog or tray recovery |

The z-order test is not committed; it was a one-off script using:
`FramelessWindowHint | WindowStaysOnTopHint | Tool` for the overlay and a parentless `QMessageBox` with `ApplicationModal`, then `win32gui.EnumWindows` and a screenshot.

---

## 7. Fix plan

### Branch

```text
fix/settings-open-api-key
```

### Commits / PRs (suggested, one concern each)

1. `fix(ui): stop dependency warning from blocking the overlay`
   - Replace the modal startup dialog with a non-modal in-overlay banner, or parent + topmost it and add "Don't show again" and "Open Settings".
   - Warn only when an external dependency is actually needed.
   - Tests: warning present + gear opens Settings; dialog is not hidden behind the overlay.
2. `fix(ui): make Settings reachable from the tray and first run`
   - Tray "Settings…" action; show overlay and switch to Settings.
   - "Add API key" CTA in the answer panel when no key exists.
   - Optional hotkey (e.g., `Ctrl+,`).
3. `fix(ui): make click-through safe and recoverable`
   - Tray toggle, active-state banner, never click-through while Settings is open.
   - Test: toggle on → banner visible → hotkey/tray recovers.
4. `fix(settings): only report a key save when it succeeded`
   - Emit `saved` after a successful save; validate the explicit pasted key; keep Settings open on failure.
5. `build: verify frozen keyring backend and move user data`
   - Collect keyring backends; store config/log in `%LOCALAPPDATA%\GhostMind\data`; migrate existing data.
6. `release: v1.0.2` + release notes.

### Acceptance criteria

- Fresh Windows VM **without Tesseract and without an API key**: launch → overlay is interactive; gear opens Settings; API key can be saved; no hidden blocking dialog; app remains usable without Tesseract (scan shows a clear, non-blocking install prompt).
- Upgrade v1.0.1 → v1.0.2 preserves settings and key.
- 100%, 125%, 150% display scaling; 1366 x 768 and 1920 x 1080; window at default and 320 x 360 minimum.
- Click-through on/off; overlay hidden/shown; tray Settings; Ctrl+Shift+X recovery.
- Existing test suite + new regression tests green; packaged installer smoke test.

---

## 8. Immediate workaround for the affected user

Until v1.0.2 is released:

1. Press **Enter** — the hidden warning dialog usually has keyboard focus, and Enter activates its OK button. Alternatively, use **Alt+Tab** to find "GhostMind — Dependency Warnings" and click OK.
2. After dismissing it, click the gear; Settings should open.
3. Install **Tesseract OCR** so the warning does not return: https://github.com/UB-Mannheim/tesseract/wiki
4. Make sure she is on **v1.0.1** (removes the API-key warning; see About tab).
5. If clicks still pass through the overlay: press **Ctrl+Shift+X** to turn click-through off, then try the gear again. The tray icon can show/hide the overlay.

Do **not** ask her to disable antivirus or reinstall Windows; neither is indicated by this failure.

---

## 9. What to collect from the friend

- Installer filename / app version (About tab, or the first `release ghostmind@x.y.z` line in the log).
- Windows version + display scaling; screen resolution.
- Is Tesseract installed? (`tesseract --version`)
- Does Alt+Tab show a "Dependency Warnings" window? Screenshot it if possible.
- Does the pointer icon next to the gear show a red slash (click-through on)? Does `Ctrl+Shift+X` change anything?
- Log tail (redact any keys):
  `%LOCALAPPDATA%\GhostMind\_internal\ghostmind.log`
- Settings file (remove the `[key_storage]` section before sharing):
  `%LOCALAPPDATA%\GhostMind\_internal\config\settings.toml`
- A short screen recording of launch → click gear would confirm the z-order/blocking behavior.

---

## 10. Draft release note for v1.0.2

```markdown
GhostMind v1.0.2 — reliability patch for first-run setup.

### Fixed
- Fixed a startup warning that could appear behind the overlay and block all
  clicks, making Settings impossible to open.
- Settings is now reachable from the system tray, and the app shows a clear
  "Add API key" prompt on first run.
- Click-through mode now has a visible indicator and a tray/hotkey recovery path.
- API key save errors are reported in Settings instead of silently closing it.

### Install
- Installer: GhostMind-Setup-1.0.2.exe
- Portable: GhostMind-Portable-1.0.2.zip
- Verify downloads against SHA256SUMS.txt.

The installer is unsigned, so SmartScreen may warn — choose More info → Run anyway.
```

---

## 11. Code reference index

| File | Lines | What |
| --- | --- | --- |
| `main.py` | 729-738 | Startup dependency check and modal dialog scheduling |
| `main.py` | 661-681 | `_dependency_dialog()` — parentless `QMessageBox` |
| `main.py` | 758 | Overlay shown before the event loop |
| `main.py` | 111-112, 153 | Config/log paths under the install root |
| `main.py` | 289-314 | Tray menu — no Settings action |
| `main.py` | 730 | Dependency check; Tesseract is external |
| `ui/overlay_window.py` | 310-314 | Overlay is always-on-top, frameless, Tool |
| `ui/overlay_window.py` | 387-396 | Settings gear button |
| `ui/overlay_window.py` | 417-424 | Click-through pointer toggle |
| `ui/overlay_window.py` | 300-306, 767-802 | Click-through guard |
| `ui/overlay_window.py` | 655-662 | `_toggle_settings()` |
| `ui/settings_panel.py` | 198-204 | API tab controls |
| `ui/settings_panel.py` | 270-315 | Bottom Save/Close buttons |
| `ui/settings_panel.py` | 421-436 | Key status / `apply_data` |
| `ui/settings_panel.py` | 521-540 | `_emit_save()` — key save + test flow |
| `ui/settings_panel.py` | 561-582 | `_on_test_api()` |
| `utils/key_store.py` | 44-46, 96-118, 149-165 | Keyring / plaintext fallback |
| `ghostmind.spec` | 61 | Only `keyring` hidden import (backends not explicit) |
| `core/ai_engine.py` | 274-292 | API key resolution and "No API key" message |
| `tests/test_dependency_dialog.py` | all | Existing coverage gap |
| `tests/test_click_through.py` | 146-252 | Settings/click-through coverage |

---

## 12. Test coverage gap

- `tests/test_dependency_dialog.py` verifies the dialog's buttons but not:
  - parent window,
  - topmost/raise behavior,
  - modal input blocking,
  - Settings reachability while warnings exist.
- No test covers tray Settings, first-run onboarding, or "no key" call-to-action.
- Add regression tests with the warning path active and assert that `_toggle_settings()` changes the stack index and that the dialog is above the overlay or non-modal.
