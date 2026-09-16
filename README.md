# GhostMind

GhostMind is a **stealth AI overlay** for Windows. It stays above other windows as a semi-transparent, frameless panel that is hidden from the taskbar and Alt+Tab, and is excluded from most screen-capture APIs so it stays off Zoom, Teams, OBS, and similar tools (OS-dependent). It can OCR the selected monitor, transcribe microphone (and optional system loopback) audio with local Whisper, and send context to **qwen3.8-27B** (via Groq) for concise answers inside the app.

## Features

- Always-on-top, draggable, resizable overlay with custom edge handles
- Windows extended styles: tool window (no taskbar / Alt+Tab entry), optional click-through
- `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` for capture exclusion; optional `DWMWA_CLOAK` via settings
- Screen capture across monitors (`mss`) + Tesseract OCR + optional OpenCV preprocessing
- Local speech-to-text with **faster-whisper**; optional WASAPI loopback for system audio
- **qwen3.8-27B** (via Groq) with ultra-fast streaming replies and markdown-like rendering in the answer panel
- Default model will be **qwen3.8-27B** as a backup **qwen3.6-27B**, **gpt-oss-120B**, and **gpt-oss-20B** model are available.
- Global hotkeys via the `keyboard` library
- System tray icon with context menu (show/hide/export/quit)
- Transcript export to `.txt` or `.md`
- Settings import/export (JSON)
- Auto-start on Windows login
- File logging with rotation (`ghostmind.log`)
- Startup dependency check with friendly warnings
- Keyboard navigation (Escape, Tab, Backtab)
- Settings stored in `config/settings.toml` (created on first save; file is gitignored)

## Prerequisites

- **Windows 10 (2004+)** recommended for `WDA_EXCLUDEFROMCAPTURE` capture exclusion
- **Python 3.11+**
- **Tesseract OCR** installed and on `PATH` (or configure `pytesseract` to point at `tesseract.exe`)

  Install example (Chocolatey): `choco install tesseract`  
  Or download from: https://github.com/UB-Mannheim/tesseract/wiki

- **Groq API key** — free tier available at [console.groq.com](https://console.groq.com). Paste it in the app under **Settings → API** (stored securely in Windows Credential Manager), or set `GROQ_API_KEY` in `.env` as a fallback.

### Optional: faster GPU for Whisper

`faster-whisper` can use CUDA if you install a CUDA-enabled build of CTranslate2 and compatible drivers. The default configuration uses CPU `int8` for broad compatibility.

## Installation

```text
git clone <your-fork-or-repo-url> GhostMind
cd GhostMind
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Then launch the app and paste your Groq key under **Settings → API → Save** — it persists across restarts (Windows Credential Manager, with a `config/settings.toml` plaintext fallback if keyring is unavailable). Optionally, `copy .env.example .env` and set `GROQ_API_KEY` there instead.

### Fonts (optional)

For the intended look, place **JetBrains Mono**, **Inter**, or **DM Sans** under `assets/fonts/` (`.ttf` / `.otf`). If they are missing, the UI falls back to **Segoe UI** / **Consolas**.

### Run

```text
python main.py
```

GhostMind checks for missing dependencies on startup and shows a warning dialog if anything is unavailable. The app still starts — just with reduced functionality.

## Usage

### Scan button & hotkeys

The ⚡ **Scan** button in the overlay's header bar triggers the same action as the screen-scan hotkey — use whichever is convenient. All hotkeys remain fully functional:

### Audio capture quick toggles

Next to the Scan button, two small icons let you enable/disable audio sources without opening Settings — click to toggle:

- 🎙 **Microphone capture** — shows a red slash when off (Zoom-style); if your system has no microphone at all, the icon shows an amber "❗" warning badge instead
- 🔊 **System audio capture** — same slash treatment

Enable either one alone, both together, or neither. Changes take effect immediately (same as saving on the Audio tab); the icons stay in sync with the Audio tab checkboxes.

| Action | Default hotkey |
|--------|----------------|
| Toggle overlay visibility | `Ctrl+Shift+G` |
| Trigger screen OCR + AI | `Ctrl+Shift+S` |
| Clear answers | `Ctrl+Shift+C` |
| Switch Answers ↔ Subtitles tab | `Ctrl+Shift+T` |
| Export transcript | `Ctrl+Shift+E` |
| Toggle click-through mode | `Ctrl+Shift+X` |
| Focus the question input box | `Ctrl+Shift+Q` |

### Keyboard Navigation

| Key | Action |
|-----|--------|
| `Escape` | Close settings (if open) or hide overlay |
| `Tab` | Cycle to next tab |
| `Shift+Tab` | Cycle to previous tab |

### Tabs

- **Answers** tab: shows streamed AI answers with copy per block.
- **Subtitles** tab: rolling transcript (`Mic:` / `System:`). Lines containing `?` or question keywords schedule a short debounce, then the recent transcript is sent to Llama as **meeting** context.

### System Tray

The green "G" icon lives in the system tray. Right-click for:
- Show/Hide overlay
- Export transcript
- Quit

Double-click the tray icon to toggle overlay visibility.

### Settings

Click the **green dot** in the header to open settings. Configure:
- Monitor selection, scan mode (manual/auto), opacity
- Click-through mode, capture settings (mic/system audio)
- Whisper model size, all hotkeys
- API key (with test button)
- Import/Export settings (JSON)

### Export

Save the full meeting transcript via:
- `Ctrl+Shift+E` hotkey
- "Save" button in the Subtitles tab
- Tray menu → "Export transcript"

Choose `.txt` (plain text) or `.md` (markdown with timestamps and formatting).

## Configuration (`config/settings.toml`)

Created when you click **Save** in settings. Keys include:

| Key | Meaning |
|-----|---------|
| `monitor_id` | `mss` monitor index (1 = first physical monitor) |
| `scan_mode` | `manual` or `auto` |
| `auto_scan_interval_sec` | Seconds between OCR runs when `auto` |
| `opacity` | Window opacity `0.5`–`1.0` |
| `click_through` | If true, `WS_EX_TRANSPARENT` so clicks pass through |
| `dwm_cloak` | If true, applies `DWMWA_CLOAK` (default false) |
| `subtitles_enabled` | Start Whisper listeners on launch |
| `capture_mic` | Capture microphone |
| `capture_system` | Capture WASAPI loopback when available |
| `whisper_model` | `tiny` / `base` / `small` / `medium` |
| `loopback_device` | Optional integer sounddevice index; `null` = auto-detect |
| `hotkeys.*` | Combo strings for all actions |

Hotkey strings follow the `keyboard` library format (e.g. `ctrl+shift+g`).

## Updates

GhostMind checks GitHub **once at launch and every 6 hours** while running (cached — never more than one check per 6h window, even across restarts).

- **Update available** → a popup shows the release notes. During the first **5 days** you can close it and keep using the current version ("Later" snoozes it for 24h).
- **After 5 days** the popup can no longer be closed: use **Update Now** to download `GhostMind-Setup-<version>.exe` (SHA-256 verified against `SHA256SUMS.txt` before it runs) — the installer closes GhostMind; start GhostMind again when it finishes.
- **Safety valve:** if downloads keep failing after the grace period (e.g. GitHub is unreachable), a **Continue for 24 hours** option appears — it re-locks after 24h. A machine that is fully offline is never locked out.
- Fully automatic: no user data leaves your machine; only GitHub is contacted to check/download releases.

QA/testing hooks (dev only): `GHOSTMIND_UPDATE_URL` (point at another releases URL, `file://` JSON works), `GHOSTMIND_FORCE_UPDATE=1`, `GHOSTMIND_GRACE_DAYS=0`.

## Troubleshooting

- **`TesseractNotFoundError` / empty OCR**  
  Install Tesseract and ensure `tesseract` is on `PATH`. GhostMind shows a friendly warning on startup if Tesseract is missing.

- **Invalid / missing API key**  
  Paste your key in **Settings → API** and hit **Save** — the app checks the key and model immediately and shows the problem inline. Keys are stored in Windows Credential Manager. Free keys at the [Groq console](https://console.groq.com). The default model is `qwen/qwen3.8-27b` with backups `qwen/qwen3.6-27b`, `openai/gpt-oss-120b`, and `openai/gpt-oss-20b`; use **＋ Add custom model…** for any other Groq model ID.


- **No microphone or loopback device**  
  Grant microphone permission on Windows. Loopback requires a WASAPI loopback-capable device; if none is found, only mic capture runs.

- **Global hotkeys not firing**  
  The `keyboard` library on Windows may need **Run as administrator** for low-level hooks in some environments.

- **Window still visible in a specific recorder**  
  Capture exclusion depends on the app honoring `WDA_EXCLUDEFROMCAPTURE`. Some tools or GPU drivers may behave differently.

- **Check the log file**  
  GhostMind writes detailed logs to `ghostmind.log` (rotating, 1MB x 3 backups). Check this file for crash diagnostics.

## Architecture

```text
+------------------------------------------------------------------+
|                          main.py                                 |
|  QApplication, settings load/save, SIGINT, GhostMindController   |
|  System tray, dependency check, file logging                     |
+----------+--------------+-------------------+--------------------+
           |              |                   |
           v              v                   v
+----------------+  +------------------+  +------------------+
| HotkeyManager  |  |  AudioListener   |  |  System Tray     |
| (keyboard lib) |  |  (QThread + STT) |  |  (QSystemTray)   |
+--------+-------+  +---------+--------+  +------------------+
         |                    |
         | signals            | subtitle_updated
         v                    v
+-------------------------------------------------------------+
|                     OverlayWindow (QMainWindow)             |
|  stealth.apply_stealth(hwnd) on show / move / resize        |
|  + Header (drag) + Tabs (Answers | Subtitles) + Settings    |
+-------+------------------------------------+----------------+
        |                                    |
        v                                    v
 +-------------+                     +---------------+
 | AnswerPanel |                     | SubtitleBar   |
 | + AI stream |                     | + formatter   |
 +------+------+                     +-------+-------+
        |                                    |
        v                                    v
 +-------------+                     +---------------+
 | AiStream    |                     | Save/Export   |
 | Worker      |                     |               |
 +------+------+                     +---------------+
        |
        v
 +-------------+     +------------------+
 | AiStream    |<--->| Groq API         |
 | Worker      |     | (qwen3.8-27b)    |
 +-------------+     +------------------+

 +------------------+       +-------------------+
 | ScreenScanWorker | ----> | mss + pytesseract |
 +------------------+       +-------------------+

 +------------------+       +-------------------+
 | utils/autostart  | ----> | Windows Registry  |
 +------------------+       +-------------------+

 +------------------+       +-------------------+
 | utils/config_io  | ----> | JSON import/export|
 +------------------+       +-------------------+
```

## Project Structure

```text
GhostMind/
├── main.py                 # Entry point, controller, tray, logging
├── core/
│   ├── ai_engine.py        # Groq API (qwen3.8-27B) with streaming
│   ├── audio_listener.py   # Mic/system capture + faster-whisper STT
│   ├── screen_reader.py    # mss screenshot + Tesseract OCR
│   └── stealth.py          # Win32 stealth (hide from capture/taskbar)
├── ui/
│   ├── overlay_window.py   # Main frameless window (drag, resize, tabs)
│   ├── answer_panel.py     # Scrollable answer history with markdown
│   ├── subtitle_bar.py     # Live transcript ticker with highlighting
│   └── settings_panel.py   # In-overlay settings (all options)
├── utils/
│   ├── formatter.py        # Markdown → HTML renderer
│   ├── hotkey_manager.py   # Global hotkeys (6 signals)
│   ├── autostart.py        # Windows auto-start (registry)
│   └── config_io.py        # Settings import/export (JSON)
├── tests/
│   ├── test_formatter.py   # 20 formatter tests
│   ├── test_ai_engine.py   # 16 prompt routing tests
│   └── test_hotkey_manager.py  # 8 hotkey manager tests
├── assets/
│   ├── icon.ico            # Window/tray icon (generated)
│   └── fonts/              # Optional custom fonts
├── config/
│   └── settings.toml       # Persisted settings (gitignored)
├── .env                    # API key (gitignored)
├── .env.example            # Template
├── requirements.txt
├── TODO.md                 # Task tracking (gitignored)
└── ghostmind.log           # Rotating log file (gitignored)
```

## Security & ethics

GhostMind is built for legitimate personal productivity (e.g. private assistance during your own calls or content). **Bypassing exam proctoring, workplace policy, or consent rules is misuse.** You are responsible for compliance with laws, contracts, and platform terms.

## License

See `LICENSE` in the repository.
