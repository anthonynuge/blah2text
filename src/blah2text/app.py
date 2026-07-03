"""Push-to-talk app loop: hold the hotkey to record, release to dictate."""

from __future__ import annotations

import threading
import time

from .audio import Recorder
from .cleanup import clean
from .config import Config
from .inject import inject
from .stt import Transcriber

MIN_AUDIO_SECONDS = 0.3  # ignore accidental taps


class App:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.viz = None
        if cfg.visualizer.enabled:
            from .viz import Visualizer
            self.viz = Visualizer(cfg.visualizer)
        self.recorder = Recorder(
            cfg.audio,
            on_level=self.viz.push_level if self.viz else None)
        self.transcriber = Transcriber(cfg.stt)
        self._busy = threading.Lock()

    # -- hotkey callbacks --------------------------------------------------

    def _on_press(self) -> None:
        if self._busy.locked() or self.recorder.recording:
            return
        try:
            self.recorder.start()
            if self.viz:
                self.viz.show()
            print("[rec] listening... (release to transcribe)")
        except Exception as exc:
            print(f"[rec] could not open microphone: {exc}")

    def _on_release(self) -> None:
        if not self.recorder.recording:
            return
        if self.viz:
            self.viz.hide()
        audio = self.recorder.stop()
        threading.Thread(target=self._process, args=(audio,),
                         daemon=True).start()

    def _process(self, audio) -> None:
        with self._busy:
            seconds = len(audio) / self.cfg.audio.samplerate if len(audio) else 0
            if seconds < MIN_AUDIO_SECONDS:
                print("[rec] too short, ignored")
                return
            t0 = time.perf_counter()
            raw = self.transcriber.transcribe(audio)
            if not raw:
                print("[stt] (no speech detected)")
                return
            final = clean(raw, self.cfg.cleanup)
            elapsed = time.perf_counter() - t0
            print(f"[out] {final!r}  ({seconds:.1f}s audio -> {elapsed:.1f}s)")
            try:
                inject(final, method=self.cfg.inject.method,
                       restore_clipboard=self.cfg.inject.restore_clipboard,
                       terminal_processes=self.cfg.inject.terminal_processes)
            except Exception as exc:
                print(f"[inject] failed ({exc}); text printed above.")

    # -- main loop -----------------------------------------------------------

    def run(self) -> None:
        import global_hotkeys  # deferred: installs a Windows keyboard hook

        if self.viz:
            self.viz.start()
        print(f"[stt] loading model '{self.cfg.stt.model}'...")
        self.transcriber.load()
        print(f"[stt] ready on {self.transcriber.device} "
              f"({self.transcriber.compute_type})")

        key = self.cfg.hotkey.key
        global_hotkeys.register_hotkeys([
            [key, self._on_press, self._on_release],
        ])
        global_hotkeys.start_checking_hotkeys()
        print(f"[app] hold <{key}> to dictate; Ctrl+C here to quit.")
        try:
            while True:
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
        finally:
            global_hotkeys.stop_checking_hotkeys()
            print("\n[app] bye")
