"""
Microphone and optional WASAPI loopback capture with faster-whisper transcription.
Runs in a QThread; emits subtitle lines with source labels.
"""
from __future__ import annotations

import logging
import queue
import time
from collections import deque
from typing import Deque, List, Optional, Tuple

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


def _find_wasapi_hostapi_index() -> Optional[int]:
    for i, h in enumerate(sd.query_hostapis()):
        if "wasapi" in h["name"].lower():
            return i
    return None


def find_loopback_device_index() -> Optional[int]:
    """Best-effort default loopback input device on Windows WASAPI."""
    wasapi = _find_wasapi_hostapi_index()
    if wasapi is None:
        return None
    devices = sd.query_devices()
    for i, d in enumerate(devices):
        if d["hostapi"] != wasapi or int(d.get("max_input_channels", 0)) < 1:
            continue
        name = str(d.get("name", "")).lower()
        if "loopback" in name or "stereo mix" in name or "what u hear" in name:
            return i
    return None


def _open_loopback_stream(device_index: int, callback, blocksize: int = 1024):
    """Open WASAPI loopback InputStream; tries WasapiSettings when available."""
    kwargs = dict(
        channels=1,
        samplerate=SAMPLE_RATE,
        dtype="float32",
        callback=callback,
        blocksize=blocksize,
    )
    try:
        wasapi_settings = getattr(sd, "WasapiSettings", None)
        if wasapi_settings is not None:
            return sd.InputStream(device=(device_index, wasapi_settings(loopback=True)), **kwargs)
    except Exception as e:
        logger.debug("WasapiSettings loopback failed: %s", e)
    return sd.InputStream(device=device_index, **kwargs)


class AudioListener(QThread):
    """Background capture + transcription; emits human-readable subtitle lines."""

    subtitle_updated = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        capture_mic: bool = True,
        capture_system: bool = False,
        loopback_device: Optional[int] = None,
        model_size: str = "base",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._capture_mic = capture_mic
        self._capture_system = capture_system
        self._loopback_device = loopback_device
        self._model_size = model_size
        self._running = False
        self._transcript: Deque[Tuple[float, str, str]] = deque()
        self._full_transcript: List[Tuple[float, str, str]] = []

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
            self.failed.emit("faster-whisper is not installed")
            return
        self._running = True
        try:
            model = WhisperModel(self._model_size, device="cpu", compute_type="int8")
        except Exception as e:
            logger.exception("Whisper model load failed")
            self.failed.emit(f"Whisper model load failed: {e}")
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
        try:
            if self._capture_mic:
                streams.append(
                    sd.InputStream(
                        device=None,
                        channels=1,
                        samplerate=SAMPLE_RATE,
                        dtype="float32",
                        callback=make_cb(mic_q),
                        blocksize=1024,
                    )
                )
            if self._capture_system:
                lb = self._loopback_device
                if lb is None:
                    lb = find_loopback_device_index()
                if lb is None:
                    logger.warning("No WASAPI loopback device found; system capture disabled")
                else:
                    try:
                        streams.append(_open_loopback_stream(lb, make_cb(sys_q)))
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
                    self._process_audio(model, audio, "Mic")

                if self._capture_system and now - last_sys_proc >= CHUNK_INTERVAL_SEC and sys_buf:
                    audio = np.concatenate(sys_buf)
                    sys_buf = []
                    last_sys_proc = now
                    self._process_audio(model, audio, "System")

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
