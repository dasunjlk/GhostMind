# GHOSTMIND — FUTURE FEATURE PLAN

**Version:** 1.0  
**Created:** 2026-09-12  
**Branch:** `feat/bug-fix`  
**Scope:** All planned features, Tier 1 → Tier 4, with implementation details.

## Legend

- `[ ]` = not started
- `[~]` = in progress
- `[x]` = done
- Effort: H = hours, D = 1-3 days, W = 1 week+

## Priority Summary

**Recommended order for next sprint:**

1. F-01 Manual question input box
2. F-03 Stop button + request queue
3. F-06 Persist window geometry
4. F-05 Vision-based screen understanding (big differentiator)
5. F-21 CI pipeline, F-22 packaging, F-24 code fixes (parallel track)

**Quick wins (under 2 hours each):** F-06, F-14, F-16, F-24 (all sub-items)

---

## TIER 1 — HIGH-IMPACT FEATURES (1-3 days each)

### F-01 [ ] MANUAL QUESTION INPUT BOX

**Effort:** D

**Problem:**
The only ways to ask the AI something are OCR scan (Ctrl+Shift+S) and the audio question debounce. There is no way to type a question directly.

**What to build:**
A collapsible input area at the bottom of the Answers tab.

**Details:**

- One-line `QLineEdit` + "Ask" button, expands to `QTextEdit` on focus for multi-line questions (Shift+Enter = newline, Enter = send).
- New global hotkey `Ctrl+Shift+Q` to focus the input (add to `DEFAULT_SETTINGS["hotkeys"]` as `"ask_question"` and `HotkeyManager` as a 7th signal + a `QLineEdit` in settings_panel Shortcuts tab).
- Sending calls `OverlayWindow.request_ai_answer(text, "manual")` — add a new context_type `"manual"` in `ai_engine.build_system_prompt()` that uses plain `BASE_SYSTEM` (no screen/meeting framing in the user message).
- `build_user_message()` for `"manual"`: return content unchanged.
- Keep input text after send for easy editing; Esc collapses the input.

**Files to touch:**

- `ui/overlay_window.py` — input row layout, hotkey focus
- `core/ai_engine.py` — "manual" context type
- `utils/hotkey_manager.py` — ask_question signal
- `ui/settings_panel.py` — hotkey field
- `main.py` — DEFAULT_SETTINGS hotkey default, wiring
- `tests/test_ai_engine.py` — prompt routing for "manual"

**Acceptance:**

- Type question → streamed answer appears as a new block.
- Ctrl+Shift+Q focuses input from anywhere the overlay is visible.

### F-02 [ ] MULTI-TURN CHAT / FOLLOW-UPS

**Effort:** D

**Problem:**
Every answer is one-shot. No way to ask "explain point 3" without repeating all context.

**What to build:**
Follow-up action on the last answer block + conversation memory.

**Details:**

- Add "Follow-up" button to `_AnswerBlock` row (next to Copy).
- Clicking opens the F-01 input pre-filled with `">> "` prefix, stores the last answer's raw markdown + the original question in a short history list on AnswerPanel: `self._history: list[dict]` (role, content), capped at 6 turns to bound token usage.
- `AiStreamWorker` accepts optional `messages_history` param; `run()` builds `messages = [system] + history + [user]` instead of 2-message list.
- `generate_answer()` gets the same optional param for tests.
- Clearing answers (Ctrl+Shift+C) also clears `_history`.

**Files to touch:**

- `core/ai_engine.py` — AiStreamWorker signature, history support
- `ui/answer_panel.py` — _AnswerBlock follow-up button, history list
- `ui/overlay_window.py` — wire follow-up click → input focus w/ prefix

**Acceptance:**
Ask "what is quicksort" then "show python code" → second answer knows the context of the first.

### F-03 [ ] STOP BUTTON + REQUEST QUEUE

**Effort:** D

**Problem:**

- (a) A running stream cannot be cancelled — must wait for full response.
- (b) A meeting question arriving while busy is silently DROPPED (`main.py _start_ai: "if _is_worker_active: return"`).
- (c) Auto-scan mode can stack requests.

**What to build:**
Cancellation + a small FIFO queue with priority.

**Details:**

- `AiStreamWorker`: add `request_stop()` setting a `threading.Event` (`self._stop_event`). In `run()`'s chunk loop:
  - `if self._stop_event.is_set(): stream.close(); break`
  - After loop, if stopped emit "stopped" signal instead of `finished_ok` (new pyqtSignal `cancelled`).
  - `time.sleep` in retry loop should use `_stop_event.wait(0.3 * attempts)` so sleeps are interruptible.
- `AnswerPanel`: while `_current_block` is streaming show a small "Stop" button in the block header row; clicked → `stop_signal` emitted.
- `OverlayWindow._start_ai`: replace drop-behavior with a queue:
  - `self._pending: deque[tuple[str, str]]` — (content, context_type)
  - Priority rules:
    - `meeting_question` → push FRONT (urgent, small)
    - `screen` / `manual` → push BACK
    - `meeting_audio` → drop if queue already has one (avoid spam)
  - On worker finished/cancelled → if queue non-empty, pop and start.
  - Cap queue at 3; overflow drops oldest screen items first.
- Stop button also appears during "Thinking" state to cancel OCR wait.

**Files to touch:**

- `core/ai_engine.py` — stop_event, cancelled signal
- `ui/answer_panel.py` — stop button, stop_signal
- `ui/overlay_window.py` — queue logic

**Acceptance:**

- Stream long answer → Stop → generation halts, partial text kept as final block marked "(stopped)".
- Fire 3 meeting questions rapidly → all eventually answered in order.

### F-04 [ ] REGION-SELECT OCR

**Effort:** D

**Problem:**
Full-monitor OCR sends a wall of text to the model: slow, more tokens, and classification accuracy drops when unrelated text surrounds the question.

**What to build:**
Hotkey enters "snip mode": drag a rectangle on screen, OCR only that region.

**Details:**

- New hotkey `ctrl+shift+r` (settings key: `region_scan`, new HotkeyManager signal `trigger_region_scan`).
- `RegionSelector(QDialog or QWidget)`:
  - fullscreen transparent frameless widget spanning the target monitor
  - dark 25% overlay; drawn rectangle stays fully clear + green border
  - mousePress/Move/Release capture QRect; Esc cancels
  - On release: hide immediately (before capture!) so the selector is never in the screenshot.
- Extend `ScreenScanWorker(monitor_id, region: Optional[QRect] = None)`:
  - `capture_screen()` uses `mss.grab` with `{"left": mon.left + region.x, "top": mon.top + region.y, "width": region.w, "height": region.h}`
  - Convert Qt logical coords → physical pixels (devicePixelRatio).
- Classification already handles short MCQ text well; short regions make quiz_mcq routing far more reliable.
- Consider keeping the last region and offering "re-scan same region" hotkey (Ctrl+Shift+R again) before re-selecting.

**Files to touch:**

- `ui/region_selector.py` — NEW file
- `core/screen_reader.py` — region param on capture_screen + worker
- `ui/overlay_window.py` — snip mode entry, worker call
- `utils/hotkey_manager.py` (signal), `main.py`, `ui/settings_panel.py`

**Acceptance:**
Drag over one MCQ → answer formatted via the quiz_mcq prompt path.

### F-05 [ ] VISION INSTEAD OF OCR (SCREENSHOT → VLM)

**Effort:** W

**Problem:**
Tesseract fails on diagrams, charts, dark themes, styled MCQ buttons, and any non-Latin layout. A vision model understands all of these.

**What to build:**
Send the raw PNG to a Groq vision model; keep OCR as fallback.

**Details:**

- Candidate models (verify current availability in Groq catalog):
  - `meta-llama/llama-4-scout-17b-16e-instruct`
  - `meta-llama/llama-4-maverick-17b-128e-instruct`
- `core/vision_engine.py` (NEW):
  - `def image_to_base64_png(img: PIL.Image) -> str` (optimize: JPEG q=80 for speed, cap width at 1568px)
  - `AiStreamWorker` variant `VisionStreamWorker` that sends:

    ```python
    messages=[{system}, {user: [
        {"type": "text", "text": user_msg},
        {"type": "image_url",
         "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}]
    ```

    with `stream=True`, same model-fallback chain.
- Settings: `"screen_input_mode": "vision" | "ocr" | "auto"` (auto = try vision, on failure fall back to OCR pipeline). New combo box in the General tab.
- Prompt routing: reuse `_classify_screen_text` on the model's own description, or keep a tiny classification pass first: ask the VLM in the same call ("If this is a multiple choice question, answer with option + explanation...") — preferred, saves a round-trip.
- Keep `ScreenScanWorker` for OCR path and for the `[Active Window]` header, which can still be prepended as text context.

**Files to touch:**

- `core/vision_engine.py` — NEW
- `core/screen_reader.py` — return image + text
- `ui/overlay_window.py` — choose path per setting
- `ui/settings_panel.py` — input-mode combo
- `main.py` — `DEFAULT_SETTINGS["screen_input_mode"]="auto"`

**Acceptance:**

- Screenshot of a chart → correct description/answer (OCR path fails on the same image).
- Vision API failure → automatic OCR fallback, user sees no error.

### F-06 [ ] REMEMBER WINDOW POSITION / SIZE

**Effort:** H

**Problem:**
Overlay resets to 480x600 at default position every launch.

**What to build:**
Persist geometry in `settings.toml`.

**Details:**

- `DEFAULT_SETTINGS` additions: `"window_x": None, "window_y": None, "window_w": 480, "window_h": 600`.
- `OverlayWindow`: on init, if `window_x/y` are ints → `move()` there (clamp into available screen geometry via `QApplication.screenAt` + `availableGeometry` so a disconnected monitor doesn't strand the window offscreen). `resize(window_w, window_h)` before move.
- On `moveEvent`/`resizeEvent` (and on hide): debounce with a 500ms `QTimer.singleShot` then write geometry back into `self._settings` and emit a lightweight `settings_changed` so main.py saves TOML. NOTE: avoid saving during the fade animation.
- Multi-monitor: store screen name too (`"window_screen"`); restore fails gracefully to default position if screen not found.

**Files to touch:**

- `ui/overlay_window.py` — restore + debounced persist
- `main.py` — DEFAULT_SETTINGS

**Acceptance:**
Move/resize/quit/relaunch → same spot, same size.

---

## TIER 2 — SMARTER BEHAVIOR (1-2 days each)

### F-07 [ ] SCREEN-CHANGE DETECTION (SKIP DUPLICATE SCANS)

**Effort:** D

**Problem:**
Auto-scan mode (default every 30s) re-OCRs an unchanged screen and burns API calls producing near-identical answers.

**What to build:**
Perceptual hash of the captured frame; skip AI if unchanged.

**Details:**

- In `ScreenScanWorker.run()`: after capture, compute ahash = `PIL.Image.Image.hash` / ImageOps or simple: `img.convert("L").resize((16,16))` → bytes → `hashlib.md5`. Store the last hash + its capture time on the worker's owner (`OverlayWindow._last_screen_hash`, `_last_hash_time`).
- Skip rules:
  - hash == last hash → do nothing (no OCR even)
  - hash differs but < 5s since last scan → wait (avoid animation spam)
- OCR text hash as second check: same text → skip AI call but still update the timestamp (defeats trivial pixel noise from video content).
- Setting: `"skip_unchanged_screen": True` (General tab, on/off).

**Files to touch:**

- `core/screen_reader.py`, `ui/overlay_window.py`, `ui/settings_panel.py`, `main.py`

**Acceptance:**
Idle desktop + auto scan on: log shows OCR runs but zero AI calls for 10 minutes.

### F-08 [ ] AUTO SESSION-TYPE DETECTION (MEETING VS LECTURE)

**Effort:** D

**Problem:**
User must manually pick Meeting/Lecture in settings; wrong choice gives wrong prompt style (summary vs lecture notes).

**What to build:**
Classify the first ~30s of transcript and switch prompts automatically.

**Details:**

- `AudioListener`: after collecting >= 25s of transcript text (concatenated from `_full_transcript`), emit new signal `session_detected(str guess)`.
- Classification: one tiny Groq call (`max_tokens=8, temp=0`) with prompt:
  `"Meeting or lecture? Reply with one word only.\n\n<transcript>"`
  If API unavailable → heuristic fallback: keyword density (`"chapter", "theorem", "slide", "definition"` → lecture; `"agenda", "sprint", "let's", "action item", "ping"` → meeting).
- Result propagates: `AudioListener.set_session_type(new)` + label on the Subtitle tab ("Detected: Lecture"). Existing manual choice becomes "Auto (detect)" option value `"auto"` as the new default.
- `_flush_meeting_question` and `_summarize_meeting` already read session_type dynamically — they just work after switch.

**Files to touch:**

- `core/audio_listener.py` — detection trigger + signal
- `core/ai_engine.py` — tiny classifier helper
- `main.py` — wire signal → set session_type
- `ui/settings_panel.py` — add "auto" option, default

**Acceptance:**
Start a lecture transcript → after ~30s UI shows Lecture mode and summaries come in lecture-notes format without user action.

### F-09 [ ] ANSWER ACTION BUTTONS (SHORTER / EXPLAIN / BULLETS)

**Effort:** D

**Problem:**
Answers are fixed once streamed; getting a different format means re-asking everything manually.

**What to build:**
Three small buttons under each finished answer block.

**Details:**

- `_AnswerBlock` row gains: "Shorter" | "Explain" | "Bullets".
- Clicking emits `refactor_requested(style)` up to AnswerPanel, which calls `OverlayWindow._start_ai` with a synthetic prompt built by `ai_engine.build_refine_prompt(original_answer, style)`:
  - `shorter`: "Rewrite the following answer in at most 3 bullet points, keep every key fact: ..."
  - `explain`: "Explain the following answer in simpler terms for a beginner, keep technical terms defined: ..."
  - `bullets`: "Reformat the following answer as compact bullet points: ..."
- New block streams below the original (original stays for comparison).
- One level of nesting max: refactor buttons hidden on blocks created by a refactor (track `block.origin = "refine"`).

**Files to touch:**

- `ui/answer_panel.py`, `ui/overlay_window.py`, `core/ai_engine.py`, `tests/test_ai_engine.py` (refine prompt builder)

**Acceptance:**
Long answer → Shorter → 3-bullet version appears in <= 2s without re-sending the question.

### F-10 [ ] ANSWER CACHE

**Effort:** D

**Problem:**
Re-scanning the same quiz region or re-triggering on the same screen wastes latency + rate limits.

**What to build:**
TTL cache keyed by (context_type, normalized content).

**Details:**

- `utils/answer_cache.py` (NEW):
  - `class AnswerCache`: `dict[(ctx, sha1(content.strip().lower()))]` → (answer, ts); get/write with TTL 10 min (meeting_question: 2 min), max 50 entries LRU eviction.
- `OverlayWindow._start_ai`: check cache first (only for non-streamed replay: `begin_answer_stream` then append full cached text as one chunk then `end_stream_success` — identical UX, zero latency).
- Settings: `"answer_cache_enabled": True`; Ctrl+Shift+C clears it too.
- NOT cached: `"manual"` context (user intent may differ) — or cache it with a short 2-min TTL for accidental double-Enter.

**Files to touch:**

- `utils/answer_cache.py` (NEW), `ui/overlay_window.py`, `main.py`

**Acceptance:**
Trigger scan twice on identical screen → second answer is instant and identical.

### F-11 [ ] SPEAKER LABELS VIA DIARIZATION

**Effort:** W

**Problem:**
Transcripts are flat "Mic:"/"System:" — meeting summaries can't tell who said what.

**What to build:**
Lightweight diarization to label speakers (Speaker A/B/...).

**Details:**

- **Option A (preferred, cheap):** energy + pitch clustering on the mic chunks before transcription. Keep a rolling feature vector (RMS mean, zero-crossing rate, spectral centroid via numpy FFT — no new deps) per 2s chunk; online k-means (k<=4) assigns cluster ids; map stable clusters to "Speaker A.." labels; store label in transcript tuples `(ts, source_label, text)` where source becomes "Mic (A)".
- **Option B (better, heavier):** pyannote.audio speaker-diarization as an optional extra (`requirements-optional.txt`) — document GPU/CPU cost, gate behind a settings checkbox, off by default.
- Prompt update: `_meeting_system_block` instructs the model to use the speaker labels when summarizing ("attribute decisions to speakers").
- Transcript export gains speaker columns automatically (same tuples).

**Files to touch:**

- `core/audio_listener.py` — feature extraction + clustering
- `core/ai_engine.py` — prompt tweak
- `main.py` — export formatting unchanged (tuples already)

**Acceptance:**
Two people talking on mic → summary references "Speaker A said X, Speaker B disagreed".

### F-12 [ ] SMART TRANSCRIPT TRIMMING (TOKEN BUDGET)

**Effort:** D

**Problem:**
`transcript_snapshot()` sends the last 60s verbatim; `full_transcript()` for summarize sends EVERYTHING — a 2-hour lecture blows past the model context and the request fails.

**What to build:**
Budget-based trimming with priority to recent + question lines.

**Details:**

- `utils/transcript_budget.py` (NEW):
  - `fit_to_budget(lines: list[tuple], max_chars: int) -> list[tuple]`
  - Strategy: keep the LAST `max_chars//2` chars verbatim; fill remaining budget from the oldest lines (head); if still over, drop from the middle; always keep lines containing `"?"` (questions drive answers).
- Budget per context (chars, ~4 chars/token):
  - `meeting_question` 6_000
  - `meeting_audio`/summary 12_000
  - `lecture_notes` 16_000
- Apply in `_flush_meeting_question` and `_summarize_meeting` before `request_ai_answer`. For summarize of very long lectures, chunk: split into 12k-char parts, summarize each (sequential small calls), then final "summary of summaries" — queue via F-03 mechanism.
- Log dropped-char count for tuning.

**Files to touch:**

- `utils/transcript_budget.py` (NEW), `main.py`, `core/ai_engine.py` (chunked-summarize helper)

**Acceptance:**
2-hour transcript → summarize succeeds via chunking; no 413/context errors in `ghostmind.log`.

---

## TIER 3 — QUALITY OF LIFE (hours each)

### F-13 [ ] LIVE MARKDOWN RENDERING DURING STREAM

**Effort:** H

**Problem:**
Stream shows raw plain text (with `**` and ` ``` ` visible); markdown only renders at the end — jarring flip.

**Details:**

- `_AnswerBlock.set_streaming_plain`: every 300ms (throttle via QTimer) re-render the buffer with `parse_and_render()` but WITHOUT finalize sizing; strip a trailing partial fence to avoid half-rendered code:
  `display_text = re.sub(r"```[^`]*$", "", buffer)`
- `setMinimumHeight` recompute stays as-is; performance is fine at 13px body width, but guard with: only re-render if len(buffer) changed since last render.
- Fallback toggle `"live_markdown": True` in settings in case some models stream in a format that renders badly mid-flight.

**Files:** `ui/answer_panel.py`, `main.py` (setting)

**Acceptance:** Code fences render styled DURING streaming; no flicker.

### F-14 [ ] WHISPER MODEL DOWNLOAD PROGRESS

**Effort:** H

**Problem:**
First run downloads the model (base: ~140MB) with zero feedback — app looks frozen in the Subtitles tab.

**Details:**

- faster-whisper (huggingface_hub) download supports tqdm; instead of replicating, detect first-run: model dir `%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-<size>` missing → before starting AudioListener, show an AnswerPanel info block: "Downloading Whisper 'base' model (one-time, ~140MB)..."
- Better UX: pass `download_root` and use `huggingface_hub.snapshot_download` with tqdm hook → forward percentage to the same info block every 500ms.
- Wrap model load failure (offline) with the existing `failed` signal + friendly retry hint.

**Files:** `core/audio_listener.py`, `ui/overlay_window.py` (info block helper)

**Acceptance:** Fresh install → visible progress % until transcription starts.

### F-15 [ ] PAUSE/RESUME CAPTURE HOTKEY + PRIVACY INDICATOR

**Effort:** H

**Problem:**
No quick way to temporarily stop mic/system capture (private conversation) without opening settings and restarting audio.

**Details:**

- New hotkey `ctrl+shift+p` (`pause_capture`). Implementation WITHOUT tearing down AudioListener: `AudioListener.set_paused(bool)` flips a `threading.Event` checked at the top of the `run()` loop — when paused, drain and discard queues, skip processing; streams stay open (silent). This avoids Whisper reload latency (model load is the slow part).
- Indicator: 3px red strip across the top of the header while paused + tray balloon "Capture paused".
- Settings key stays `"subtitles_enabled"` for startup; pause is runtime only, not persisted.

**Files:** `core/audio_listener.py`, `utils/hotkey_manager.py`, `ui/overlay_window.py` (indicator), `main.py`, `settings_panel.py`

**Acceptance:** Hotkey toggles capture; indicator appears; resume needs no model reload (< 1s).

### F-16 [ ] OCR LANGUAGE SETTING

**Effort:** H

**Problem:**
Whisper auto-detects language, but Tesseract defaults to English only.

**Details:**

- `DEFAULT_SETTINGS["ocr_lang"] = "eng"`.
- `extract_text(image, lang="eng")` → `pytesseract.image_to_string(work, lang=lang)`.
- Settings panel (General tab): combo populated at runtime from `tesseract --list-langs` (run once, cache; on failure fallback list: eng, spa, fra, deu, hin, sin, tam + free-text field).
- Pass through `ScreenScanWorker(monitor_id, ocr_lang)` → `scan_and_extract`.
- Show hint in settings if the chosen lang isn't installed: "Language pack missing — run the Tesseract installer again."

**Files:** `core/screen_reader.py`, `ui/settings_panel.py`, `ui/overlay_window.py`, `main.py`

**Acceptance:** Non-English screen text OCRs correctly when pack installed.

### F-17 [ ] THEMES / ACCENT COLOR PICKER

**Effort:** H

**Problem:**
Green `#00FF88` is hardcoded in ~10 files; no user customization.

**Details:**

- **Step 1 (prereq):** `utils/theme.py` (NEW) — `ACCENT = "#00FF88"`, `ACCENT_DIM`, `BG`, `BG_PANEL`, `TEXT`, `TEXT_DIM`, `ERROR = "#FF4444"`, `GOLD`, `BLUE` + function `qss()` returning the shared stylesheet fragments. Replace literals across `ui/*` and `utils/formatter.py` (keep tests' `#00FF88` assertions valid by keeping the default identical).
- **Step 2:** settings `"accent_color": "#00FF88"`; settings_panel gets a color-picker button (QColorDialog) + 6 preset swatches.
- All runtime styling goes through a single `OverlayWindow.retheme(accent)` that re-applies `setStyleSheet` on the widgets (keep references list `self._themed_widgets` built during init).

**Files:** `utils/theme.py` (NEW), `ui/*` (mechanical replace), `ui/settings_panel.py` (picker)

**Acceptance:** Pick red → borders/code/buttons/tab highlight all follow, restart keeps choice.

### F-18 [ ] EXPORT COMBINED REPORT (ANSWERS + TRANSCRIPT)

**Effort:** H

**Problem:**
Answers and transcript export separately; no single session record.

**Details:**

- Extend export dialog: third filter choice "Session report (*.md)".
- Report layout:
  - `# GhostMind Session Report`
  - date, duration, model, session_type
  - `## Transcript` (existing markdown format, speaker-labeled)
  - `## AI Answers` (each: question/source context + final markdown)
- AnswerPanel needs `dump_history()` → `list[dict]` (raw markdown, source context_type, timestamp at block creation — track on `_AnswerBlock`).
- Save via the existing QFileDialog flow in `main.py export_transcript`; branch on chosen suffix.

**Files:** `ui/answer_panel.py`, `main.py`

**Acceptance:** One .md contains full transcript + every answer in order.

### F-19 [ ] OFFLINE / PRIVACY FALLBACK (LOCAL LLM VIA OLLAMA)

**Effort:** D

**Problem:**
Everything stops without a Groq key / internet; also some users want zero-cloud transcription+answering.

**Details:**

- `utils/local_llm.py` (NEW): OpenAI-compatible client against `http://localhost:11434/v1` (Ollama). Detect via 1s GET `/api/tags`; list installed models (filter small instruct models: `llama3.1:8b`, `qwen2.5:7b`).
- `AiStreamWorker`: if `settings["ai_backend"] == "local"` (or auto: no GROQ_API_KEY and Ollama reachable) → use local endpoint with the same streaming messages; same prompts, larger max_tokens (local models are slower — 2048) and no fallback chain (single model).
- Settings (AI & API tab): Backend combo [Groq (cloud) | Ollama (local) | Auto] + status dot "Ollama: connected (llama3.1:8b)".
- `.env.example` gains `OLLAMA_HOST=http://localhost:11434`.

**Files:** `utils/local_llm.py` (NEW), `core/ai_engine.py` (backend switch in `run()`), `ui/settings_panel.py`, `main.py`, `.env.example`

**Acceptance:** Kill internet → Auto falls back to Ollama; answers stream locally; nothing leaves the machine.

### F-20 [ ] PIN / POPOUT ANSWER WINDOW

**Effort:** D

**Problem:**
Only one overlay; users may want one answer pinned while continuing to ask new questions.

**Details:**

- `_AnswerBlock` gains a "pin" icon button: creates a `PopoutAnswerWindow` (QMainWindow, frameless, always-on-top, TOOLWINDOW, WDA_EXCLUDEFROMCAPTURE via `core.stealth.apply_stealth` — same stealth guarantees as the main overlay!) sized ~380x260, showing the finalized HTML (read-only) + Copy.
- Original block keeps a "pinned" state chip; block still deletable from the panel (popout already owns its HTML copy).
- Popouts tracked in `OverlayWindow._popouts: list`; on app quit, close all. Drag = header drag filter (reuse `_HeaderDragFilter`).

**Files:** `ui/popout_window.py` (NEW), `ui/answer_panel.py`, `ui/overlay_window.py`

**Acceptance:** Pin answer → separate capture-proof mini window; closes with app quit.

---

## TIER 4 — ENGINEERING HYGIENE (mechanical / infrastructure)

### F-21 [ ] CI PIPELINE (GITHUB ACTIONS)

**Effort:** H

**Details:**

- `.github/workflows/ci.yml` (NEW):
  - `runs-on: windows-latest` (keyboard/pywin32/sounddevice are Windows-specific; audio device tests need sounddevice importable — it is, even without devices)
  - steps: checkout → setup-python 3.11 → `pip install -r requirements.txt -r requirements-dev.txt` → `ruff check .` → `mypy core ui utils --ignore-missing-imports` → `pytest -q --tb=short`
- `requirements-dev.txt` (NEW): pytest, ruff, mypy, pytest-qt.
- Matrix note: add ubuntu-latest only after guarding win32 imports (`core/stealth.py` already try/excepts win32gui — keep it that way).
- Cache pip (actions/setup-python `cache: pip`) — Whisper NOT downloaded in CI; audio tests must not instantiate AudioListener (current tests already avoid it — keep it that way).
- Badge in README.

**Acceptance:** Green pipeline on push + PR; ruff clean.

### F-22 [ ] PACKAGING (.EXE) + UPDATE CHECK

**Effort:** W

**Details:**

- PyInstaller onedir (one-file breaks faster-whisper/tesseract discovery):
  - `ghostmind.spec`: hiddenimports for faster_whisper, sounddevice, pywin32; datas: assets/ (fonts, icon.ico); exclude tests/.
- Tesseract cannot ship inside the exe (GPL + huge): on first run, if tesseract missing, show the existing dependency dialog with a button that downloads the UB-Mannheim installer and runs it silently (user consent checkbox) OR just deep-link to the wiki page.
- Version/update check: `utils/updater.py` (NEW) — GET `https://api.github.com/repos/dasunjlk/GhostMind/releases/latest` (1/day, cached to `config/last_update_check.json`), compare against `version.__version__` (`packaging.version.parse`), tray balloon with release link; never auto-download.
- Release workflow: `.github/workflows/release.yml` on tag push → build exe → zip with README/LICENSE → attach to GitHub Release.

**Acceptance:** Fresh Windows VM: exe runs, OCR installs via helper, update balloon appears when repo has newer tag.

### F-23 [ ] TEST GAPS

**Effort:** D

Currently untested (add tests/ files):

- `core/stealth.py`: style-flag math (`_apply_extended_styles` logic) — refactor the flag math into a pure function `compute_exstyle(current, click_through) -> int` and unit-test it (WS_EX_TOOLWINDOW set, APPWINDOW cleared, TRANSPARENT conditional). The win32 calls themselves stay thin/unmocked.
- `utils/config_io.py`: export/import round-trip (tmp_path fixture), underscore-prefixed keys stripped, invalid JSON → None.
- `main.py`: load_settings merging (TOML present/absent/corrupt; hotkeys deep-merge), `_format_transcript` txt/md snapshots, `check_dependencies` warning list (monkeypatch imports).
- Question→debounce→AI flow: `main._on_subtitle_line` with a fake audio listener — assert `_meeting_timer` started only for questions, `_flush_meeting_question` builds correct context_type.
- `utils/formatter`: already 20 tests — add edge cases for the Answer badge with lowercase `"**answer:**"`, nested code fence in list.
- `ui/region_selector` (after F-04): geometry math pure functions.

**Acceptance:** Coverage (`pytest --cov`) >= 70% on utils/ and core/ pure logic files.

### F-24 [ ] KNOWN CODE FIXES (DO FIRST — SMALL)

**Effort:** H

- **24a.** [ ] README model mismatch: "Llama 3.1 70B" (Features + Architecture diagram + ai_engine comment) vs actual `qwen/qwen3.8-27b`. `grep -n "Llama 3.1" README.md core/ai_engine.py`
- **24b.** [ ] `.env.example`: remove the two stray "[TEMPLATE]" lines (copy-paste artifact; harmless for dotenv but confusing).
- **24c.** [ ] Delete stray pip artifact file `"=0.10.2"` in repo root (created by a malformed `pip install toml >=0.10.2` command). `git rm "=0.10.2"` (quote it — shell glob chars!)
- **24d.** [ ] Move `_QUESTION_RE` from `ui/subtitle_bar.py` to `core/` (e.g. `core/question_detect.py`) — controller logic (main.py) currently imports from a UI module; subtitle_bar should import it from the new location. Add unit tests for the regex (40+ patterns claim).
- **24e.** [ ] AiStreamWorker rate-limit handling: on HTTP 429 read `e.response` headers retry-after (groq SDK exposes it) and back off exponentially (1s, 2s, 4s, cap 30s, max 3 retries) instead of the flat 0.3s sleep; emit a chunk "(rate limited, retrying...)" only if delay > 3s.
- **24f.** [ ] `resample_to_16k`: 48k path uses `audio[::3]` naive decimation — aliases high frequencies into speech band. Use `np.interp` for all rates (drop the `::3` shortcut) OR `scipy.signal.resample_poly` if scipy is acceptable (it is NOT a current dep — prefer np.interp). Update `tests/test_features.py::test_resample_48k_to_16k` only if length math changes (it won't with np.interp target_len).
- **24g.** [ ] API key storage: move from .env plaintext to Windows Credential Manager via the `keyring` package (new dep, win_cred backend); fallback to .env when keyring unavailable. Settings panel Save writes `keyring.set_password("GhostMind", "GROQ_API_KEY", k)`; `_get_client()` reads keyring first. Add "Clear stored key" button.

---

## OUT OF SCOPE / BACKLOG (NOT PLANNED)

- macOS/Linux support (Win32 stealth is the product's core identity).
- Cloud sync of settings/transcripts (privacy posture).
- Auto-start changes (already implemented, registry-based).

---

## CHANGELOG OF THIS PLAN

- **2026-09-12 v1.0** — Initial plan: 24 features across 4 tiers.
