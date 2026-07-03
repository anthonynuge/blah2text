#!/usr/bin/env python
"""blah2text — local push-to-talk dictation with AI cleanup.

Usage:
  python run.py                       start the push-to-talk app (hold F9)
  python run.py --dry-run FILE.wav    transcribe+clean a WAV, print stages
  python run.py --list-devices        show audio input devices
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def _dry_run(wav_path: str, cfg) -> None:
    """End-to-end pipeline on a WAV file: VAD -> faster-whisper -> cleanup.

    No microphone, no injection — prints every stage instead.
    """
    from blah2text.cleanup import clean, rule_clean
    from blah2text.stt import Transcriber

    path = Path(wav_path)
    if not path.is_file():
        sys.exit(f"error: WAV file not found: {path}")

    print(f"[dry-run] file: {path}")
    transcriber = Transcriber(cfg.stt)
    print(f"[stt] loading model '{cfg.stt.model}'...")
    transcriber.load()
    print(f"[stt] device={transcriber.device} compute={transcriber.compute_type}")

    raw = transcriber.transcribe(str(path))
    print(f"[raw]   {raw!r}")
    if not raw:
        print("[final] (no speech detected)")
        return

    ruled = rule_clean(raw)
    print(f"[rules] {ruled!r}")
    words = len(ruled.split())
    if not cfg.cleanup.enabled:
        print("[llm]   disabled in config")
    elif words < cfg.cleanup.min_words_for_llm:
        print(f"[llm]   skipped ({words} words < "
              f"{cfg.cleanup.min_words_for_llm} - latency rule)")
    final = clean(raw, cfg.cleanup)
    print(f"[final] {final}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="blah2text",
        description="Local push-to-talk dictation: hold a hotkey, speak, "
                    "release - transcribed by faster-whisper, cleaned by a "
                    "local Ollama LLM, typed at your cursor. Fully offline.",
    )
    parser.add_argument("--config", metavar="PATH", default=None,
                        help="path to config.toml (default: auto-detect)")
    parser.add_argument("--dry-run", metavar="WAV", default=None,
                        help="run the STT+cleanup pipeline on a WAV file and "
                             "print the result (no mic, no injection)")
    parser.add_argument("--list-devices", action="store_true",
                        help="list audio input devices and exit")
    args = parser.parse_args()

    from blah2text.config import load_config  # stdlib-only import
    cfg = load_config(args.config)

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return
    if args.dry_run:
        _dry_run(args.dry_run, cfg)
        return

    from blah2text.app import App
    App(cfg).run()


if __name__ == "__main__":
    main()
