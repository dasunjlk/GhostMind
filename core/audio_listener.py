"""
Microphone and system audio (WASAPI / Stereo Mix / Loopback) capture with faster-whisper transcription.
Runs in a QThread; emits subtitle lines with source labels.
"""
from __future__ import annotations

import logging
import queue
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np
import sounddevice as sd
from PyQt6.QtCore import QThread, pyqtSignal

logger = logging.getLogger(__name__)

try:
    from faster_whisper import WhisperModel
except ImportError:  # pragma: no cover
    WhisperModel = None  # type: ignore

SAMPLE_RATE = 16000
CHUNK_INTERVAL_SEC = 2.0
ROLLING_SEC = 60.0


def resample_to_16k(audio: np.ndarray, orig_rate: int) -> np.ndarray:
    """Resample any 1D audio array to 16,000 Hz."""
    if orig_rate == SAMPLE_RATE or len(audio) == 0:
        return audio.astype(np.float32)
    if orig_rate == 48000:
        return audio[::3].astype(np.float32)
    target_len = int(len(audio) * SAMPLE_RATE / orig_rate)
    if target_len <= 0:
        return np.empty(0, dtype=np.float32)
    return np.interp(
        np.linspace(0, len(audio), target_len, endpoint=False),
        np.arange(len(audio)),
        audio,
    ).astype(np.float32)


def get_input_devices() -> List[Dict[str, Any]]:
    """Return all available input audio devices across host APIs."""
    devices = []
    hostapis = {i: h.get("name", "") for i, h in enumerate(sd.query_hostapis())}
    for i, d in enumerate(sd.query_devices()):
        ch = int(d.get("max_input_channels", 0))
        if ch > 0:
            hname = hostapis.get(d.get("hostapi", -1), "")
            devices.append(
                {
                    "id": i,
                    "name": f"[{hname}] {d.get('name', 'Unknown')}",
                    "raw_name": d.get("name", ""),
                    "channels": ch,
                    "hostapi": hname,
                    "samplerate": int(d.get("default_samplerate", 48000)),
                }
            )
    return devices


def _find_wasapi_hostapi_index() -> Optional[int]:
    for i, h in enumerate(sd.query_hostapis()):
        if "wasapi" in h["name"].lower():
            return i
    return None


def find_loopback_device_index() -> Optional[int]:
    """Best-effort search for loopback / stereo mix / system audio recording device."""
    devices = sd.query_devices()
    # 1. Look for explicit loopback / stereo mix keywords across all host APIs
    keywords = ["stereo mix", "loopback", "what u hear", "wave out", "virtual audio", "cable output"]
    for i, d in enumerate(devices):
        if int(d.get("max_input_channels", 0)) < 1:
            continue
        name = str(d.get("name", "")).lower()
        if any(k in name for k in keywords):
            return i

    # 2. Look in WASAPI specifically
    wasapi = _find_wasapi_hostapi_index()
    if wasapi is not None:
        for i, d in enumerate(devices):
            if d.get("hostapi") == wasapi and int(d.get("max_input_channels", 0)) > 0:
                name = str(d.get("name", "")).lower()
                if any(k in name for k in keywords):
                    return i

    return None


def _create_stream(device_idx: Optional[int], callback: Any) -> Tuple[sd.InputStream, int]:
    """Open an InputStream trying 16kHz first, falling back to native device sample rate."""
    native_rate = SAMPLE_RATE
    channels = 1
    if device_idx is not None:
        try:
            d_info = sd.query_devices(device_idx)
            native_rate = int(d_info.get("default_samplerate", 48000))
            channels = min(1, int(d_info.get("max_input_channels", 1)))
        except Exception:
            pass

    # Attempt 1: 16kHz directly
    try:
        stream = sd.InputStream(
            device=device_idx,
            channels=channels,
            samplerate=SAMPLE_RATE,
            dtype="float32",
            callback=callback,
            blocksize=1024,
        )
        return stream, SAMPLE_RATE
    except Exception as e1:
        logger.debug("Opening stream at 16kHz failed (%s), trying native rate %d", e1, native_rate)

    # Attempt 2: Device native sample rate
    stream = sd.InputStream(
        device=device_idx,
        channels=channels,
        samplerate=native_rate,
        dtype="float32",
        callback=callback,
        blocksize=1024,
    )
    return stream, native_rate


class AudioListener(QThread):
    """Background capture + transcription; emits human-readable subtitle lines."""

    subtitle_updated = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        capture_mic: bool = True,
        capture_system: bool = True,
        loopback_device: Optional[int] = None,
        model_size: str = "base",
        session_type: str = "meeting",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._capture_mic = capture_mic
        self._capture_system = capture_system
        self._loopback_device = loopback_device
        self._model_size = model_size
        self._session_type = session_type
        self._running = False
        self._transcript: Deque[Tuple[float, str, str]] = deque()
        self._full_transcript: List[Tuple[float, str, str]] = []

    def set_session_type(self, session_type: str) -> None:
        self._session_type = session_type

    def get_session_type(self) -> str:
        return self._session_type

    def clear_transcript(self) -> None:
        self._transcript.clear()
        self._full_transcript.clear()

    def transcript_snapshot(self) -> List[Tuple[float, str, str]]:
        """(timestamp, source, text) tuples within rolling window."""
        now = time.time()
        return [(t, s, x) for t, s, x in self._transcript if now - t <= ROLLING_SEC]

    def full_transcript(self) -> List[Tuple[float, str, str]]:
        """All recorded transcript entries since start."""
        return list(self._full_transcript)

    def start_listening(self) -> None:
        if not self.isRunning():
            self.start()

    def stop_listening(self) -> None:
        self._running = False
        if self.isRunning():
            self.wait(8000)

    def run(self) -> None:
        if WhisperModel is None:
            self.failed.emit(
                "faster-whisper is not installed.\n"
                "Audio transcription is unavailable.\n"
                "Install it with: pip install faster-whisper"
            )
            return
        self._running = True
        try:
            model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
        except Exception as e:
            logger.exception("Whisper model load failed")
            self.failed.emit(
                f"Whisper model '{self._model_size}' failed to load: {e}\n\n"
                "Try a smaller model (tiny) in Settings, or check your internet connection."
            )
            return

        mic_q: queue.Queue = queue.Queue()
        sys_q: queue.Queue = queue.Queue()

        def make_cb(q: queue.Queue):
            def cb(indata, frames, t, status) -> None:
                if status:
                    logger.debug("sounddevice status: %s", status)
                try:
                    q.put(indata.copy(), block=False)
                except queue.Full:
                    pass

            return cb

        streams: List[sd.InputStream] = []
        mic_rate = SAMPLE_RATE
        sys_rate = SAMPLE_RATE

        try:
            if self._capture_mic:
                try:
                    s, mic_rate = _create_stream(None, make_cb(mic_q))
                    streams.append(s)
                except Exception as e:
                    logger.warning("Microphone stream open failed: %s", e)

            if self._capture_system:
                lb = self._loopback_device
                if lb is None:
                    lb = find_loopback_device_index()
                if lb is None:
                    logger.warning("No loopback device found; system capture disabled")
                else:
                    try:
                        s, sys_rate = _create_stream(lb, make_cb(sys_q))
                        streams.append(s)
                        logger.info("Opened loopback stream on device index %d at %d Hz", lb, sys_rate)
                    except Exception as e:
                        logger.exception("Loopback stream open failed")
                        logger.warning("System audio capture disabled: %s", e)

            for s in streams:
                s.start()

            mic_buf: List[np.ndarray] = []
            sys_buf: List[np.ndarray] = []
            last_mic_proc = time.time()
            last_sys_proc = time.time()

            while self._running:
                try:
                    while True:
                        mic_buf.append(mic_q.get_nowait().flatten())
                except queue.Empty:
                    pass
                try:
                    while True:
                        sys_buf.append(sys_q.get_nowait().flatten())
                except queue.Empty:
                    pass

                now = time.time()
                if self._capture_mic and now - last_mic_proc >= CHUNK_INTERVAL_SEC and mic_buf:
                    audio = np.concatenate(mic_buf)
                    mic_buf = []
                    last_mic_proc = now
                    audio_16k = resample_to_16k(audio, mic_rate)
                    self._process_audio(model, audio_16k, "Mic")

                if self._capture_system and now - last_sys_proc >= CHUNK_INTERVAL_SEC and sys_buf:
                    audio = np.concatenate(sys_buf)
                    sys_buf = []
                    last_sys_proc = now
                    audio_16k = resample_to_16k(audio, sys_rate)
                    source_label = "Lecturer" if self._session_type == "lecture" else "System"
                    self._process_audio(model, audio_16k, source_label)

                self._prune_transcript()
                self.msleep(40)

        except Exception as e:
            logger.exception("Audio listener crashed")
            self.failed.emit(str(e))
        finally:
            for s in streams:
                try:
                    s.stop()
                    s.close()
                except Exception:
                    pass

    def _prune_transcript(self) -> None:
        now = time.time()
        while self._transcript and now - self._transcript[0][0] > ROLLING_SEC:
            self._transcript.popleft()

    def _process_audio(self, model: WhisperModel, audio: np.ndarray, source: str) -> None:
        if audio.size < SAMPLE_RATE // 2:
            return
        try:
            audio = np.clip(audio.astype(np.float32), -1.0, 1.0)
            segments, info = model.transcribe(
                audio,
                beam_size=1,
                vad_filter=True,
                language=None,
            )
            parts: List[str] = []
            for seg in segments:
                t = seg.text.strip()
                if t:
                    parts.append(t)
            text = " ".join(parts).strip()
            if not text:
                return
            ts = time.time()
            self._transcript.append((ts, source, text))
            self._full_transcript.append((ts, source, text))
            line = f"{source}: {text}"
            self.subtitle_updated.emit(line)
        except Exception as e:
            logger.warning("Transcription failed (%s): %s", source, e)
