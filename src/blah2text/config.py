"""Configuration loading (config.toml -> dataclasses, stdlib only)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class HotkeyConfig:
    key: str = "f9"


@dataclass
class AudioConfig:
    samplerate: int = 16000
    device: int = -1  # -1 = system default input device


@dataclass
class SttConfig:
    model: str = "small.en"
    device: str = "auto"        # auto -> CUDA float16, CPU int8 fallback
    compute_type: str = "auto"
    language: str = "en"


@dataclass
class CleanupConfig:
    enabled: bool = True
    ollama_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:7b"
    min_words_for_llm: int = 10
    timeout_seconds: float = 20.0


@dataclass
class InjectConfig:
    method: str = "clipboard"   # "clipboard" or "type"
    restore_clipboard: bool = True
    # Foreground apps that paste with Ctrl+Shift+V instead of Ctrl+V
    terminal_processes: list[str] = field(default_factory=lambda: [
        "wezterm-gui.exe",
        "windowsterminal.exe",
        "alacritty.exe",
        "mintty.exe",
        "hyper.exe",
        "ghostty.exe",
    ])


@dataclass
class VizConfig:
    enabled: bool = True
    color: str = "#e8e8e8"      # any Tk color: "#7dd3a8", "white", ...
    background: str = "transparent"  # "transparent" or a solid color
    width: int = 420
    height: int = 56
    bars: int = 56
    fps: int = 30
    gain: float = 14.0          # mic level -> bar height sensitivity


@dataclass
class Config:
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    stt: SttConfig = field(default_factory=SttConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    inject: InjectConfig = field(default_factory=InjectConfig)
    visualizer: VizConfig = field(default_factory=VizConfig)


def _apply(section_obj, data: dict) -> None:
    known = {f.name for f in fields(section_obj)}
    for key, value in data.items():
        if key in known:
            setattr(section_obj, key, value)


def find_config_file() -> Path | None:
    candidates = [
        Path.cwd() / "config.toml",
        Path(__file__).resolve().parents[2] / "config.toml",  # repo root
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_config(path: str | Path | None = None) -> Config:
    """Load config.toml if present; missing file/keys fall back to defaults."""
    cfg = Config()
    config_path = Path(path) if path else find_config_file()
    if config_path is None:
        return cfg
    with open(config_path, "rb") as fh:
        data = tomllib.load(fh)
    for section_name in ("hotkey", "audio", "stt", "cleanup", "inject",
                         "visualizer"):
        if isinstance(data.get(section_name), dict):
            _apply(getattr(cfg, section_name), data[section_name])
    return cfg
