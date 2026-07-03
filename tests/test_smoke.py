"""Smoke tests: cleanup rules, the <10-word LLM skip, and inject dispatch.

All OS keystroke and Ollama calls are mocked — no mic, GPU, or network.
"""

from unittest import mock

import pytest

from blah2text import cleanup, inject
from blah2text.config import CleanupConfig


# --- rule-based cleanup ---------------------------------------------------

def test_rule_clean_strips_filler_words():
    assert cleanup.rule_clean("um, hello there uh I think") == \
        "Hello there I think"


def test_rule_clean_never_deletes_real_words():
    # "um" in umpire, "ah" in ahead, "er" in her must survive
    assert cleanup.rule_clean("The umpire ran ahead of her") == \
        "The umpire ran ahead of her"


def test_rule_clean_collapses_whitespace():
    assert cleanup.rule_clean("so   many    spaces") == "So many spaces"


# --- LLM skip / fallback logic --------------------------------------------

def _cfg(**kwargs) -> CleanupConfig:
    return CleanupConfig(**kwargs)


def test_short_utterance_skips_llm():
    with mock.patch.object(cleanup, "llm_clean") as llm:
        result = cleanup.clean("um hello world", _cfg())
    llm.assert_not_called()
    assert result == "Hello world"


def test_long_utterance_calls_llm():
    text = "one two three four five six seven eight nine ten eleven"
    fake = mock.Mock()
    fake.json.return_value = {"response": "Cleaned by the LLM."}
    fake.raise_for_status.return_value = None
    with mock.patch.object(cleanup.requests, "post",
                           return_value=fake) as post:
        result = cleanup.clean(text, _cfg())
    post.assert_called_once()
    assert result == "Cleaned by the LLM."


def test_ollama_failure_falls_back_to_rules():
    text = "um one two three four five six seven eight nine ten eleven"
    with mock.patch.object(cleanup.requests, "post",
                           side_effect=ConnectionError("ollama down")):
        result = cleanup.clean(text, _cfg())
    assert result == "One two three four five six seven eight nine ten eleven"


def test_cleanup_disabled_uses_rules_only():
    text = "one two three four five six seven eight nine ten eleven"
    with mock.patch.object(cleanup, "llm_clean") as llm:
        result = cleanup.clean(text, _cfg(enabled=False))
    llm.assert_not_called()
    assert result.startswith("One two")


# --- injection dispatch -----------------------------------------------------

def test_inject_dispatches_clipboard_method():
    with mock.patch.object(inject, "_paste_clipboard") as paste, \
         mock.patch.object(inject, "_type_unicode") as typer:
        inject.inject("hello", method="clipboard", restore_clipboard=True)
    paste.assert_called_once_with("hello", restore=True)
    typer.assert_not_called()


def test_inject_dispatches_type_method():
    with mock.patch.object(inject, "_paste_clipboard") as paste, \
         mock.patch.object(inject, "_type_unicode") as typer:
        inject.inject("hello", method="type")
    typer.assert_called_once_with("hello")
    paste.assert_not_called()


def test_inject_rejects_unknown_method():
    with pytest.raises(ValueError):
        inject.inject("hello", method="carrier-pigeon")


def test_inject_empty_text_is_noop():
    with mock.patch.object(inject, "_paste_clipboard") as paste, \
         mock.patch.object(inject, "_type_unicode") as typer:
        inject.inject("", method="clipboard")
    paste.assert_not_called()
    typer.assert_not_called()


def test_type_unicode_builds_keyup_keydown_pairs():
    sent = []
    with mock.patch.object(inject, "_send_inputs", side_effect=sent.append):
        inject._type_unicode("hi")
    events = sent[0]
    assert len(events) == 4  # down+up per character
    assert events[0].union.ki.wScan == ord("h")
    assert events[1].union.ki.dwFlags & inject.KEYEVENTF_KEYUP
