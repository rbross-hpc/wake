# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.llm.openai_client — offline (no network)."""
from __future__ import annotations

import json
import time
from unittest.mock import patch

import httpx
import openai
import pytest

from wake.llm.openai_client import (
    LLMInvalidRequestError,
    LLMResponseError,
    _extract_json_object,
    _is_transient_openai_error,
    _strip_markdown_fence,
    chat_json,
)

from .conftest import PARALLEL_NETCDF_WORK


@pytest.fixture(autouse=True)
def _fake_openai_credentials(monkeypatch):
    """chat_json/chat_text call _client(), which constructs a real
    openai.OpenAI() -- this validates credentials at construction time
    even though every test below mocks the actual network call
    (_stream_completion or Completions.create), never reaching a real
    request. Without OPENAI_API_KEY set, OpenAI() itself raises
    openai.OpenAIError before the mock is ever exercised -- this passed
    only by accident in any environment with a real key already set
    (e.g. a developer's shell), and failed for real in CI, which
    correctly has no credentials configured. Set a fake key so
    construction succeeds; no real request is ever made."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake-key-for-tests")


def _fake_openai_error(cls, status: int, message: str = "fake error"):
    """Build a real instance of an openai.APIStatusError subclass --
    these require a genuine httpx.Response in their constructor, not
    just a status code, so every test needing one goes through this
    helper rather than hand-rolling an incomplete fake."""
    response = httpx.Response(status, request=httpx.Request("POST", "https://example.com"))
    return cls(message, response=response, body=None)


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


def test_chat_json_raises_llm_response_error_on_truly_unparseable_response():
    """Malformed model output is a distinct failure class from a
    transport failure (see openai_client.py's module docstring) -- it
    must raise a clearly-labeled LLMResponseError, not tenacity's opaque
    RetryError (the previous behavior, before retry policy was split by
    failure class)."""
    with patch("wake.llm.openai_client._stream_completion", return_value="not json at all"):
        with pytest.raises(LLMResponseError, match="not valid JSON"):
            chat_json("system prompt", "user prompt")


def test_chat_json_clean_json_still_works_directly():
    with patch("wake.llm.openai_client._stream_completion", return_value='{"x": 1}'):
        result = chat_json("system prompt", "user prompt")
    assert result == {"x": 1}


# --- Retry policy split by failure class -----------------------------------

@pytest.mark.parametrize("cls,status", [
    (openai.RateLimitError, 429),
    (openai.InternalServerError, 500),
])
def test_is_transient_true_for_rate_limit_and_server_errors(cls, status):
    assert _is_transient_openai_error(_fake_openai_error(cls, status)) is True


def test_is_transient_true_for_connection_and_timeout_errors():
    request = httpx.Request("POST", "https://example.com")
    assert _is_transient_openai_error(openai.APIConnectionError(request=request)) is True
    assert _is_transient_openai_error(openai.APITimeoutError(request=request)) is True


@pytest.mark.parametrize("cls,status", [
    (openai.AuthenticationError, 401),
    (openai.BadRequestError, 400),
    (openai.NotFoundError, 404),
    (openai.PermissionDeniedError, 403),
    (openai.UnprocessableEntityError, 422),
    (openai.ConflictError, 409),
])
def test_is_transient_false_for_permanent_errors(cls, status):
    assert _is_transient_openai_error(_fake_openai_error(cls, status)) is False


def test_is_transient_false_for_non_openai_exceptions():
    assert _is_transient_openai_error(ValueError("something else entirely")) is False


def test_chat_json_fails_fast_on_permanent_error_no_retry_no_backoff():
    """The core bug this phase fixes: an unrecoverable request (bad API
    key, here) used to get the exact same 3-attempt exponential-backoff
    treatment as a rate limit, wasting ~4s per call on a request that
    could never succeed. It must now fail on the first attempt."""
    call_count = 0

    def _raise(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise _fake_openai_error(openai.AuthenticationError, 401, "bad api key")

    start = time.monotonic()
    with patch("openai.resources.chat.completions.Completions.create", side_effect=_raise):
        with pytest.raises(LLMInvalidRequestError, match="AuthenticationError"):
            chat_json("system prompt", "user prompt")
    elapsed = time.monotonic() - start

    assert call_count == 1
    assert elapsed < 1.0, f"expected no backoff delay, took {elapsed:.2f}s"


def test_chat_json_retries_transient_error_with_backoff():
    """The complementary case: a genuinely transient failure (rate
    limit) must still get the full 3-attempt retry treatment -- the
    fix above must not accidentally stop retrying errors that are worth
    retrying."""
    from tenacity import RetryError

    call_count = 0

    def _raise(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise _fake_openai_error(openai.RateLimitError, 429, "rate limited")

    with patch("openai.resources.chat.completions.Completions.create", side_effect=_raise):
        with pytest.raises(RetryError):
            chat_json("system prompt", "user prompt")

    assert call_count == 3


def test_llm_invalid_request_error_preserves_original_exception_as_cause():
    call_count = 0

    def _raise(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise _fake_openai_error(openai.BadRequestError, 400, "malformed request")

    with patch("openai.resources.chat.completions.Completions.create", side_effect=_raise):
        with pytest.raises(LLMInvalidRequestError) as exc_info:
            chat_json("system prompt", "user prompt")

    assert isinstance(exc_info.value.__cause__, openai.BadRequestError)


# --- CLI-level handling: LLMInvalidRequestError/LLMResponseError -----------
# main() catches these two well-defined LLM-boundary failure modes and emits
# a clean error instead of an uncaught traceback (see cli/main.py).

def test_cli_describe_reports_clean_error_on_invalid_request(tmp_path, capsys):
    import sys as _sys

    from wake.cli.main import main
    from wake.io import atomic_write_json
    from wake.seed import work_dir
    from wake.state import mark_stage_complete

    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    wd = work_dir(seed_id, tmp_path)
    wd.mkdir(parents=True, exist_ok=True)
    atomic_write_json(wd / "seed.json", {**PARALLEL_NETCDF_WORK, "resolved_at": "2020-01-01T00:00:00"})
    mark_stage_complete(wd, "seed", seed_id=seed_id, prompt_version="seed-1")

    def _raise(*args, **kwargs):
        raise _fake_openai_error(openai.AuthenticationError, 401, "bad api key")

    with patch.object(_sys, "argv", ["wake", "--json", "--work-dir", str(tmp_path), "describe", seed_id]), \
         patch("openai.resources.chat.completions.Completions.create", side_effect=_raise):
        with pytest.raises(SystemExit) as exc_info:
            main()

    assert exc_info.value.code == 1
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["ok"] is False
    assert envelope["error"]["type"] == "LLMInvalidRequestError"
