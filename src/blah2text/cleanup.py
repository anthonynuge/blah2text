"""Transcript cleanup: fast rule-based pass, then optional Ollama LLM pass.

Latency rules:
  * the rule-based pass ALWAYS runs (cheap, milliseconds);
  * utterances under ``min_words_for_llm`` words skip the LLM entirely;
  * any Ollama failure falls back to the rule-cleaned text.
"""

from __future__ import annotations

import re

import requests

from .config import CleanupConfig

# Standalone fillers only. Word boundaries guarded on both sides so real
# words are never touched ("umpire", "ahead", "her" all survive).
_FILLER_RE = re.compile(
    r"(?i)(?<![\w'-])(?:um+|uh+|hmm+|er+|ah+)(?![\w'-])[,;]?"
)

_LLM_PROMPT = (
    "You clean up dictated speech transcripts. Fix casing and punctuation, "
    "remove filler words and false starts, and apply light formatting. "
    "Do NOT change the meaning, do NOT add or invent content, and do NOT "
    "answer questions that appear in the text. "
    "Return ONLY the cleaned text, nothing else.\n\n"
    "Transcript: {text}"
)


def rule_clean(text: str) -> str:
    """Deterministic cleanup: strip standalone fillers, tidy whitespace."""
    cleaned = _FILLER_RE.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"\s+([,.!?;:])", r"\1", cleaned)   # no space before punctuation
    cleaned = re.sub(r"^[,.;:\s]+", "", cleaned)          # leftovers like ", hello"
    if cleaned and cleaned[0].islower():
        cleaned = cleaned[0].upper() + cleaned[1:]
    return cleaned


def llm_clean(text: str, cfg: CleanupConfig) -> str | None:
    """Ask the local Ollama server to clean the transcript.

    Returns None (caller falls back to rule-cleaned text) if the response
    is empty or looks degenerate.
    """
    resp = requests.post(
        f"{cfg.ollama_url.rstrip('/')}/api/generate",
        json={
            "model": cfg.model,
            "prompt": _LLM_PROMPT.format(text=text),
            "stream": False,
            "options": {"temperature": 0.1},
        },
        timeout=cfg.timeout_seconds,
    )
    resp.raise_for_status()
    out = (resp.json().get("response") or "").strip()
    # Models sometimes wrap the answer in quotes.
    if len(out) >= 2 and out[0] == out[-1] and out[0] in "\"'":
        out = out[1:-1].strip()
    if not out:
        return None
    # Guard against the model rambling instead of cleaning.
    if len(out) > max(80, 2 * len(text)):
        return None
    return out


def clean(text: str, cfg: CleanupConfig) -> str:
    """Full cleanup pipeline. Never raises; never returns worse than rules."""
    base = rule_clean(text)
    if not cfg.enabled or not base:
        return base
    if len(base.split()) < cfg.min_words_for_llm:
        return base  # short utterance: skip the LLM for latency
    try:
        out = llm_clean(base, cfg)
    except Exception as exc:  # Ollama down, timeout, bad JSON, ...
        print(f"[cleanup] Ollama unavailable ({exc.__class__.__name__}); "
              f"using rule-cleaned text.")
        return base
    return out or base
