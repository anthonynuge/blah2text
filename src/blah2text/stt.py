"""Speech-to-text via faster-whisper (CTranslate2) with Silero VAD gating."""

from __future__ import annotations

from .config import SttConfig


def _add_nvidia_dll_dirs() -> None:
    """Make pip-installed cuBLAS/cuDNN DLLs findable by CTranslate2.

    `pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` drops the DLLs under
    site-packages/nvidia/*/bin, which is not on the DLL search path.
    """
    import os
    import sys
    from pathlib import Path

    base = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not base.is_dir():
        return
    for bin_dir in base.glob("*/bin"):
        try:
            os.add_dll_directory(str(bin_dir))
        except OSError:
            pass
        # CTranslate2 resolves cuBLAS/cuDNN with a plain LoadLibrary-by-name,
        # which searches PATH but ignores add_dll_directory entries.
        os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


class Transcriber:
    """Lazy-loading wrapper around faster_whisper.WhisperModel.

    device="auto" tries CUDA float16 first and falls back to CPU int8 with a
    printed message — it never crashes on a missing/broken CUDA setup.
    """

    def __init__(self, cfg: SttConfig):
        self.cfg = cfg
        self.device: str | None = None
        self.compute_type: str | None = None
        self._model = None

    def load(self) -> None:
        if self._model is not None:
            return
        from faster_whisper import WhisperModel  # heavy import, deferred

        want_cuda = self.cfg.device in ("auto", "cuda")
        if want_cuda:
            _add_nvidia_dll_dirs()
            compute = ("float16" if self.cfg.compute_type == "auto"
                       else self.cfg.compute_type)
            try:
                model = WhisperModel(self.cfg.model, device="cuda",
                                     compute_type=compute)
                # Force a real kernel launch so unsupported GPU arches
                # (e.g. Blackwell sm_120 on an old ctranslate2) fail HERE,
                # inside the try, instead of mid-dictation.
                import numpy as np
                warmup = np.zeros(1600, dtype=np.float32)
                list(model.transcribe(warmup, language=self.cfg.language)[0])
                self._model = model
                self.device, self.compute_type = "cuda", compute
                return
            except Exception as exc:
                print(f"[stt] CUDA unavailable ({exc.__class__.__name__}: {exc})")
                print('[stt] Falling back to CPU int8. RTX 50-series (sm_120) '
                      'users: pip install --upgrade "ctranslate2>=4.6.0" '
                      "(CUDA 12.8 build).")

        compute = ("int8" if self.cfg.compute_type in ("auto", "float16")
                   else self.cfg.compute_type)
        self._model = WhisperModel(self.cfg.model, device="cpu",
                                   compute_type=compute)
        self.device, self.compute_type = "cpu", compute

    def transcribe(self, audio) -> str:
        """Transcribe a float32 numpy array (16 kHz mono) or a WAV file path.

        vad_filter=True runs Silero VAD so silence/noise-only audio yields
        an empty string instead of hallucinated text.
        """
        self.load()
        segments, _info = self._model.transcribe(
            audio,
            language=self.cfg.language,
            vad_filter=True,
            beam_size=5,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
