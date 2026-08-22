# GhostMind

GhostMind is a **stealth AI overlay** for Windows. It stays above other windows as a semi-transparent, frameless panel that is hidden from the taskbar and Alt+Tab, and is excluded from most screen-capture APIs so it stays off Zoom, Teams, OBS, and similar tools (OS-dependent). It can OCR the selected monitor, transcribe microphone (and optional system loopback) audio with local Whisper, and send context to **Groq** (Llama 3.1 70B) for concise answers inside the app.

## Features

- Always-on-top, draggable, resizable overlay with custom edge handles
- Windows extended styles: tool window (no taskbar / Alt+Tab entry), optional click-through
- `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` for capture exclusion; optional `DWMWA_CLOAK` via settings (normally hides the window locally—off by default)
- Screen capture across monitors (`mss`) + Tesseract OCR + optional OpenCV preprocessing
- Local speech-to-text with **faster-whisper**; optional WASAPI loopback for system audio
- **Llama 3.1 70B** (via Groq) with ultra-fast streaming replies and markdown-like rendering in the answer panel
- Global hotkeys via the `keyboard` library
- Settings stored in `config/settings.toml` (created on first save; file is gitignored)

## Prerequisites

- **Windows 10 (2004+)** recommended for `WDA_EXCLUDEFROMCAPTURE` capture exclusion
- **Python 3.11+**
- **Tesseract OCR** installed and on `PATH` (or configure `pytesseract` to point at `tesseract.exe`)

  Install example (Chocolatey): `choco install tesseract`  
  Or download the Windows installer from the UB Mannheim / GitHub Tesseract releases and add the install folder to `PATH`.

- **Groq API key** in `.env` as `GROQ_API_KEY` (free tier available at [console.groq.com](https://console.groq.com))

### Optional: faster GPU for Whisper

`faster-whisper` can use CUDA if you install a CUDA-enabled build of CTranslate2 and compatible drivers. The default configuration uses CPU `int8` for broad compatibility.

## Installation

```text
git clone <your-fork-or-repo-url> GhostMind
cd GhostMind
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Edit .env — set GROQ_API_KEY
```

### Fonts (optional)

For the intended look, place **JetBrains Mono**, **Inter**, or **DM Sans** under `assets/fonts/` (`.ttf` / `.otf`). If they are missing, the UI falls back to **Segoe UI** / **Consolas**.

### Window icon (optional)

If you add `assets/icon.ico`, GhostMind uses it as the window icon.

### Run

```text
python main.py
```

## Usage

| Action | Default hotkey |
|--------|----------------|
| Toggle overlay visibility | `Ctrl+Shift+G` |
| Trigger screen OCR + AI | `Ctrl+Shift+S` |
| Clear answers | `Ctrl+Shift+C` |
| Switch Answers ↔ Subtitles tab | `Ctrl+Shift+T` |

- **Answers** tab: shows streamed Llama output with copy per block.
- **Subtitles** tab: rolling transcript (`Mic:` / `System:`). Lines containing `?` schedule a short debounce, then the recent transcript is sent to Llama as **meeting** context (the model decides whether to answer or summarize).

Use the **green** header dot to open settings (saved to `config/settings.toml`).

## Configuration (`config/settings.toml`)

Created when you click **Save** in settings. Keys include:

| Key | Meaning |
|-----|---------|
| `monitor_id` | `mss` monitor index (1 = first physical monitor) |
| `scan_mode` | `manual` or `auto` |
| `auto_scan_interval_sec` | Seconds between OCR runs when `auto` |
| `opacity` | Window opacity `0.5`–`1.0` |
| `click_through` | If true, `WS_EX_TRANSPARENT` so clicks pass through |
| `dwm_cloak` | If true, applies `DWMWA_CLOAK` (**usually hides the window locally**—default false) |
| `subtitles_enabled` | Start Whisper listeners on launch |
| `capture_mic` | Capture microphone |
| `capture_system` | Capture WASAPI loopback when available |
| `whisper_model` | `tiny` / `base` / `small` / `medium` |
| `loopback_device` | Optional integer sounddevice index; `null` = auto-detect |
| `hotkeys.*` | Combo strings for the four actions |

Hotkey strings follow the `keyboard` library format (e.g. `ctrl+shift+g`).

## Troubleshooting

- **`TesseractNotFoundError` / empty OCR**  
  Install Tesseract and ensure `tesseract` is on `PATH`, or set `pytesseract.pytesseract.tesseract_cmd` in code if you use a custom location.

- **Invalid / missing API key**  
  Check `.env` and use **Test** in settings (or verify in the [Groq console](https://console.groq.com)). The model id used is `llama-3.1-70b-versatile`.

- **No microphone or loopback device**  
  Grant microphone permission on Windows. Loopback requires a WASAPI loopback-capable device; if none is found, only mic capture runs (see log messages).

- **Global hotkeys not firing**  
  The `keyboard` library on Windows may need **Run as administrator** for low-level hooks in some environments.

- **Window still visible in a specific recorder**  
  Capture exclusion depends on the app honoring `WDA_EXCLUDEFROMCAPTURE`. Some tools or GPU drivers may behave differently; there is no universal guarantee.

## Architecture (ASCII)

```text
+------------------------------------------------------------------+
|                          main.py                                 |
|  QApplication, settings load/save, SIGINT, GhostMindController   |
+----------+------------------------------+------------------------+
           |                              |
           v                              v
+----------------+              +------------------+
| HotkeyManager  |              |  AudioListener   |
| (keyboard lib) |              |  (QThread + STT) |
+--------+-------+              +---------+--------+
         |                                |
         | signals                          | subtitle_updated
         v                                v
+-------------------------------------------------------------+
|                     OverlayWindow (QMainWindow)              |
|  stealth.apply_stealth(hwnd) on show / move / resize         |
|  + Header (drag) + Tabs (Answers | Subtitles) + Settings   |
+-------+------------------------------------+---------------+
        |                                    |
        v                                    v
 +-------------+                     +---------------+
 | AnswerPanel |                     | SubtitleBar   |
 | + AI stream |                     | + formatter   |
 +------+------+                     +---------------+
        |
        v
 +-------------+     +------------------+
 | AiStream    |<--->| Groq API         |
 | Worker      |     | (Llama 3.1 70B)  |
 +-------------+     +------------------+

 +------------------+       +-------------------+
 | ScreenScanWorker | ----> | mss + pytesseract |
 +------------------+       +-------------------+
```

## Security & ethics

GhostMind is built for legitimate personal productivity (e.g. private assistance during your own calls or content). **Bypassing exam proctoring, workplace policy, or consent rules is misuse.** You are responsible for compliance with laws, contracts, and platform terms.

## License

See `LICENSE` in the repository.
