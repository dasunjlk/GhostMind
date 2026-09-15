# GhostMind — TODO

> Living task list. Completed items are checked off and moved to the bottom.

---

## Priority 1 — API Switch

- [x] ~~Switch AI engine from Anthropic to Groq (Llama 3.1 70B)~~
- [x] ~~Update `requirements.txt` — replace `anthropic` with `groq`~~
- [x] ~~Update `.env.example` — `GROQ_API_KEY`~~
- [x] ~~Update `settings_panel.py` — API key field + test button for Groq~~
- [x] ~~Update `README.md` — reflect Groq instead of Claude~~

## Priority 2 — Core Missing Features

- [x] ~~Add system tray icon (restore overlay from hidden)~~
- [x] ~~Add transcript export (save meeting transcript to `.txt` / `.md`)~~
- [x] ~~Graceful error messages when Tesseract or other deps are missing~~
- [x] ~~Add logging to file for crash diagnostics (`ghostmind.log`)~~

## Priority 3 — Quality & Polish

- [x] ~~Unit tests: `formatter.py` (markdown → HTML)~~
- [x] ~~Unit tests: `ai_engine.py` prompt routing (`_classify_screen_text`)~~
- [x] ~~Unit tests: `hotkey_manager.py` signal wiring~~
- [x] ~~Improve subtitle question detection (smarter regex)~~
- [x] ~~Click-through toggle UX (hotkey-only escape hatch when enabled)~~
- [x] ~~Add window icon (`assets/icon.ico`) — generated with Pillow~~
- [ ] Add custom fonts (`assets/fonts/` — JetBrains Mono, Inter)
- [x] ~~Auto-start on Windows login (optional, via registry)~~
- [x] ~~Settings import/export (share configs across machines)~~
- [x] ~~Keyboard navigation within the overlay UI~~

## Completed

- [x] Core overlay architecture (frameless, always-on-top, drag/resize)
- [x] Windows stealth (taskbar/Alt+Tab/capture exclusion)
- [x] Screen OCR pipeline (mss + Tesseract + OpenCV)
- [x] Audio transcription (faster-whisper + sounddevice)
- [x] Global hotkeys (keyboard library)
- [x] Settings panel (in-overlay, TOML persistence)
- [x] Markdown rendering in answers
- [x] Subtitle highlighting (questions in gold)
- [x] MIT License
- [x] System tray icon (green circle with 'G', context menu, double-click toggle, close→hide)
- [x] Transcript export (full history to .txt/.md, Save button, Ctrl+Shift+E, tray menu)
- [x] Startup dependency check (warns about missing Tesseract, Groq, Whisper, etc.)
- [x] Graceful error handling (OCR, audio, AI, screen capture)
- [x] File logging with rotation (ghostmind.log, 1MB x 3 backups)
- [x] Unit tests (formatter: 20 tests, prompt routing, hotkey manager)
- [x] Improved subtitle question detection (40+ question patterns)
- [x] Click-through toggle hotkey (Ctrl+Shift+X) with tray notification
- [x] Window icon (programmatic ICO with Pillow)
- [x] Auto-start on Windows login (registry-based, toggleable)
- [x] Settings import/export (JSON format, shareable)
- [x] Keyboard navigation (Escape, Tab, Backtab)
- [x] .gitignore updated with TODO.md, ghostmind.log

---

*Last updated: 2026-08-22*
