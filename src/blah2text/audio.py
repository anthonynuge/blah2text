"""Microphone capture: start on hotkey press, stop on release."""

from __future__ import annotations

import numpy as np

from .config import AudioConfig


class Recorder:
    """Buffers mic audio between start() and stop() as 16 kHz float32 mono."""

    def __init__(self, cfg: AudioConfig):
        self.cfg = cfg
        self._stream = None
        self._chunks: list[np.ndarray] = []

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self._stream is not None:
            return
        import sounddevice as sd  # deferred: needs PortAudio/mic

        self._chunks = []

        def _callback(indata, _frames, _time, _status):
            self._chunks.append(indata[:, 0].copy())

        device = self.cfg.device if self.cfg.device >= 0 else None
        self._stream = sd.InputStream(
            samplerate=self.cfg.samplerate,
            channels=1,
            dtype="float32",
            device=device,
            callback=_callback,
        )
        self._stream.start()

    def stop(self) -> np.ndarray:
        """Stop capturing and return everything recorded since start()."""
        if self._stream is None:
            return np.zeros(0, dtype=np.float32)
        self._stream.stop()
        self._stream.close()
        self._stream = None
        if not self._chunks:
            return np.zeros(0, dtype=np.float32)
        audio = np.concatenate(self._chunks)
        self._chunks = []
        return audio
