# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.llm.openai_client — offline (no network)."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from wake.llm.openai_client import _strip_markdown_fence, _extract_json_object, chat_json


def test_strip_markdown_fence_removes_fence():
    text = '```json\n{"a": 1}\n```'
    assert _strip_markdown_fence(text) == '{"a": 1}'


def test_strip_markdown_fence_noop_without_fence():
    text = '{"a": 1}'
    assert _strip_markdown_fence(text) == text


def test_extract_json_object_finds_balanced_object():
    raw = 'Some preamble text.\n\n{"a": 1, "b": {"c": 2}}'
    extracted = _extract_json_object(raw)
    assert json.loads(extracted) == {"a": 1, "b": {"c": 2}}


def test_extract_json_object_handles_braces_in_strings():
    raw = 'Preamble {"text": "a sentence with a { brace } inside it", "n": 1}'
    extracted = _extract_json_object(raw)
    assert json.loads(extracted) == {"text": "a sentence with a { brace } inside it", "n": 1}


def test_extract_json_object_no_object_returns_unchanged():
    raw = "no json here at all"
    assert _extract_json_object(raw) == raw


def test_extract_json_object_ignores_trailing_text_after_object():
    raw = '{"a": 1} some trailing commentary after the object'
    extracted = _extract_json_object(raw)
    assert json.loads(extracted) == {"a": 1}


def test_chat_json_recovers_from_prefixed_prose(monkeypatch):
    """Regression test: some models occasionally prefix JSON output with
    reasoning prose despite explicit instructions not to (observed live
    with the 'evidence' role's long full-text verification prompt).
    chat_json must recover the JSON object rather than failing outright."""
    prefixed_response = (
        "Looking at the text, I find the following.\n\n"
        '{"relationship": "extends", "confidence": 0.9, "quotes": []}'
    )
    with patch("wake.llm.openai_client._stream_completion", return_value=prefixed_response):
        result = chat_json("system prompt", "user prompt")
    assert result == {"relationship": "extends", "confidence": 0.9, "quotes": []}


def test_chat_json_still_raises_on_truly_unparseable_response():
    from tenacity import RetryError
    with patch("wake.llm.openai_client._stream_completion", return_value="not json at all"):
        with pytest.raises(RetryError):
            chat_json("system prompt", "user prompt")


def test_chat_json_clean_json_still_works_directly():
    with patch("wake.llm.openai_client._stream_completion", return_value='{"x": 1}'):
        result = chat_json("system prompt", "user prompt")
    assert result == {"x": 1}
