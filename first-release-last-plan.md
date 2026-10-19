# GhostMind — First Release Last Plan

**Version:** 1.0.0
**Branch for this work:** `feat/first-release-refinements`
**Mainline for release:** `main`
**Date started:** 2026-10-08

This is the working plan for the last refinements before the first public release. It complements `release plan.md` and `future-plan.md`. Anything cut from the first release goes here and into `future-plan.md` so it is not lost.

## 1. Current state snapshot

### Packaging
- `ghostmind.spec` written, PyInstaller ONEDIR build succeeds.
- `installer/ghostmind.iss` written for the per-user Inno Setup installer.
- `dist/ghostmind/ghostmind.exe` exists; `dist/SHA256SUMS.txt` generated.
- `assets/icon.ico` now exists for the window and installer.

### Release plan items
| ID | Item | Status |
|----|------|--------|
| R-01 | Packaging (.exe + installer) | Built; still needs installer polish work + installer UI doc below |
| R-02 | Update popup (U-01) | Open |
| R-03 | API key persistence (keyring) | Done |
| R-04 | Window geometry restore | Done |
| R-05 | Pre-release fixes a–g | Done |
| R-06 | Release automation workflow | Open |

### Behavior notes already in the app
- The dependency check still warns about a missing API key every launch. **We are removing that warning.**
- The settings panel already verifies key + model together when Save is clicked.
- Mic and system-audio capture settings exist and work, but are **hidden from v1.0 UI**, not deleted.

## 2. Branch plan

- All first-release refinements in this document happen on `feat/first-release-refinements`, branched from `main`.
- When this branch is ready, PR it into `main`, then build/tag the release from `main`.
- Existing feature/hotfix branch `feat/bug-fix` is not used for this work.

## 3. First-release TODO (before v1.0.0 tagging)

### 3.1 Remove the API key startup warning
- `main.py` dependency check must no longer emit `"No Groq API key found"` as a hard warning.
- If no key is present, the app still starts normally. Users set the key themselves in Settings.
- Keep Tesseract, groq package, faster-whisper, sounddevice, and keyboard checks as they are.

### 3.2 First-run guide
- Do not use a static note. Use a modern popup anchored near the Settings button with a small connecting arrow.
- First popup text example: `"To add your API key first, go to Settings."`
- Second popup appears near the API key area: `"Click here to add key."`
- Similar guided hints for other first-time actions: `"Click here to see shortcuts"`, `"Click here to scan"`, etc.
- For the items to be decided by you, the supported actions are:
  - Shortcuts tab annotated hint,
  - Scan button annotated hint,
  - README and future-plan notes for removed-first-release features.
- Show these hints only on first use. Add a `"View Guide"` button in Settings so the user can replay the guide later.
- Visual style must be modern, consistent with the app theme, not an old-style message box.
- The guide is not one big dialog. It is a sequence of small arrow-anchored hints, one per relevant UI spot:
  - near Settings button,
  - near the API key row in Settings,
  - near the Shortcuts tab,
  - near the scan button/scan area.

### 3.3 API key + model validation UX
- When the user enters a key and picks a model, verify both together before relying on them.
- If the key is valid but the model is not available for that key, warn the user clearly.
- The existing settings-panel self-test flow already does this; make sure the warning is clear and recoverable.

### 3.4 First-release feature cuts (hide, do not delete)
For v1.0 we keep the app simple:
- Simple screen scan is enough for the first release.
- Mic capture, system audio capture, subtitles, and the wider audio/ Whisper flow are **not part of v1.0**.
- Do **not** delete the related code.
- For now, wire these features so they are not surfaced in the UI:
  - hide the mic/system toggles from the overlay header,
  - hide the audio/capture controls from Settings,
  - do not show captions/subtitle UI.

### 3.5 Installer UI flow documentation
Before finalizing the installer look, document what the user sees when they run the setup. This section is a placeholder for that documentation:

- Step 1: user downloads `GhostMind-Setup-<version>.exe`.
- Step 2: user runs the setup exe.
- Step 3: describe the installer dialogs/the user experience during installation.
- Step 4: describe post-install first run behavior.

This document will be updated once the installer UI direction is decided.

### 3.6 Make the Settings API key self-test warning clear and recoverable
- The settings panel already runs a key+model self-test on Save.
- Make sure the result is readable and not buried.
- If the check fails, tell the user exactly what failed and what to do next.
- Keep the existing Check button behavior; this item is about clarity and recovery, not a new flow.
- Add a second first-run guide anchor near the API key row: `"Click here to add key."`

### 3.7 Shortcuts and scan hints
- Add a first-run hint near the Shortcuts tab: `"Click here to see shortcuts."`
- Add a first-run hint near scan: `"Click here to scan."`
- These are small arrow-anchored hints, same style as the Settings and API key hints.

## 4. Features removed or hidden for the first release

These are moved to the future plan so we do not lose them:

- Mic capture quick-toggle in the overlay header
- System audio capture quick-toggle in the overlay header
- Subtitles/captions panel
- Full audio capture + Whisper transcription path
- Any Settings UI items that only exist to control the above
- Whisper first-run download progress
- Pause/resume capture hotkey
- OCR language setting
- Speaker diarization
- Auto session-type detection
- Screen-change detection

These are deferred to a later update. Code is retained; UI exposure is removed for v1.0.

## 5. Branches referenced

- `feat/first-release-refinements` — this work
- `main` — release baseline
- `feat/bug-fix` — earlier feature/hotfix branch, not used for this work

## 6. Installer UI flow (what the user sees)

These are the steps we document for the installer UI:

1. User downloads `GhostMind-Setup-<version>.exe` from the release page.
2. User runs the installer exe.
3. User sees a modern Inno Setup install wizard with:
   - app icon and app name/version in the title,
   - a welcome/info page,
   - a per-user install path,
   - an optional Start-with-Windows checkbox,
   - a clean install progress page,
   - a finish page.
4. The wizard uses a standard Next/Install/Finish flow.
5. After install, the user can launch GhostMind from the desktop shortcut or Start Menu entry and complete first-run setup in the app.

This section is the concrete UI description for the installer; it is not a placeholder anymore.

## 7. Immediate next actions for this branch

- Decide the installer UI direction with you (this doc is a placeholder for that decision).
- Decide whether the first-run guide text/captions need wording changes.
- If you want, convert the v1.0 cut list into a feature flag in code instead of UI hiding.

## 8. First-run guide sequence implemented on this branch

- Settings button hint: `"Welcome — To add your API key first, go to Settings."`
- API key row hint: `"Click here to add key. Paste a free Groq key and Save — the app checks the key and model for you."`
- View Guide button in Preferences: replays the Settings-button hint.
- Hidden v1.0 cuts verified: mic/system header toggles hidden, Settings Audio tab capture/whisper rows hidden, subtitles still in code but Settings now has 6 tabs and the v1.0 cut list is documented.
- Installer UI flow documented in section 6 of this file.

### Still to do from the plan doc
- Shortcuts tab hint: `"Click here to see shortcuts."`
- Scan hint: `"Click here to scan."`
- Rating the installer UI direction with you and documenting the final flow.
