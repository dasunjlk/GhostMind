GhostMind v1.0.1 — a small patch focused on a smoother first run.

### Fixed

- Removed the startup "No Groq API key found" dependency warning. New users can now launch GhostMind and add their key whenever they are ready via **Settings → API**.

### Install

- **Installer:** `GhostMind-Setup-1.0.1.exe` — per-user install (`%LOCALAPPDATA%\GhostMind`), no admin rights required.
- **Portable:** `GhostMind-Portable-1.0.1.zip` — extract and run `ghostmind.exe`.
- **Verify:** compare downloads against `SHA256SUMS.txt`.

### Requirements

- Windows 10/11 (x64)
- Tesseract OCR installed separately (required for screen scanning)
- A Groq API key — add it in **Settings → API** on first launch

The installer is unsigned, so Windows SmartScreen may show a warning — choose **More info → Run anyway**.

**Full changelog:** https://github.com/dasunjlk/GhostMind/compare/v1.0.0...v1.0.1
