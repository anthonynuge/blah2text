"""Minimal waveform overlay shown while recording.

A borderless, always-on-top, transparent strip at the bottom center of the
primary screen that renders mirrored bars from live mic levels. Runs
entirely in its own daemon thread (tkinter is not thread-safe, so ALL tk
calls happen there); the audio thread only appends numbers to a deque.
"""

from __future__ import annotations

import ctypes
import math
import queue
import threading
from collections import deque

from .config import VizConfig

_TRANSPARENT = "#010203"  # magic color keyed out of the window


def scale_rms(rms: float, gain: float = 14.0) -> float:
    """Map an audio block's RMS (~0..0.3 for speech) to a 0..1 bar height.

    sqrt compresses the range so quiet speech still visibly moves the bars.
    """
    return min(1.0, math.sqrt(max(0.0, rms * gain)))


class Visualizer:
    def __init__(self, cfg: VizConfig):
        self.cfg = cfg
        self._levels = deque(maxlen=cfg.bars)  # atomic appends: thread-safe
        self._commands: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._failed = False

    # -- called from any thread ---------------------------------------------

    def start(self) -> None:
        if self._thread is not None or self._failed:
            return
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="blah2text-viz")
        self._thread.start()

    def show(self) -> None:
        self._levels.clear()
        self._commands.put("show")

    def hide(self) -> None:
        self._commands.put("hide")

    def push_level(self, rms: float) -> None:
        """Feed one audio block's RMS. Called from the audio callback."""
        self._levels.append(scale_rms(rms, self.cfg.gain))

    # -- tk thread ------------------------------------------------------------

    def _work_area(self) -> tuple[int, int, int, int]:
        """Primary monitor work area (excludes the taskbar)."""
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        rect = RECT()
        SPI_GETWORKAREA = 0x0030
        ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
        return rect.left, rect.top, rect.right, rect.bottom

    def _run(self) -> None:
        try:
            import tkinter as tk

            root = tk.Tk()
            root.overrideredirect(True)          # no title bar / border
            root.attributes("-topmost", True)
            if self.cfg.background == "transparent":
                bg = _TRANSPARENT
                root.attributes("-transparentcolor", _TRANSPARENT)
            else:
                bg = self.cfg.background
            canvas = tk.Canvas(root, width=self.cfg.width,
                               height=self.cfg.height, bg=bg,
                               highlightthickness=0)
            canvas.pack()

            left, _top, right, bottom = self._work_area()
            x = left + (right - left - self.cfg.width) // 2
            y = bottom - self.cfg.height - 8
            root.geometry(f"{self.cfg.width}x{self.cfg.height}+{x}+{y}")
            root.withdraw()                      # hidden until recording

            interval = max(15, 1000 // self.cfg.fps)
            visible = False

            def tick():
                nonlocal visible
                try:
                    while True:
                        cmd = self._commands.get_nowait()
                        if cmd == "show" and not visible:
                            root.deiconify()
                            root.attributes("-topmost", True)
                            visible = True
                        elif cmd == "hide" and visible:
                            root.withdraw()
                            visible = False
                except queue.Empty:
                    pass
                if visible:
                    self._draw(canvas)
                root.after(interval, tick)

            root.after(interval, tick)
            root.mainloop()
        except Exception as exc:
            self._failed = True
            print(f"[viz] visualizer disabled ({exc.__class__.__name__}: {exc})")

    def _draw(self, canvas) -> None:
        w, h = self.cfg.width, self.cfg.height
        cy = h // 2
        levels = list(self._levels)
        step = w / self.cfg.bars
        canvas.delete("all")
        # newest level on the right, history scrolling left
        for i, level in enumerate(levels):
            x = w - (len(levels) - i) * step + step / 2
            half = max(1.5, level * (cy - 2))
            canvas.create_line(x, cy - half, x, cy + half,
                               fill=self.cfg.color, width=2,
                               capstyle="round")
