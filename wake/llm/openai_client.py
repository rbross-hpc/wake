# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
# Adapted from pub-analysis/puba/llm/openai_client.py
"""OpenAI-compatible LLM client wrapper with retries.

Retry policy is split by failure class (see PLAN.md "Phase 3 --
Structural Hardening" / BACKLOG.md Theme L): a *transient* provider
failure (rate limit, timeout, connection error, 5xx) is worth retrying
with backoff, since the same request may well succeed a moment later.
An *invalid request* (bad API key, malformed request, model doesn't
exist, permission denied) will never succeed no matter how many times
it's retried -- see ``_is_transient_openai_error`` below -- so
``chat_json``/``chat_text`` fail on the first attempt for those,
instead of the previous behavior (every ``openai.*Error`` subclass,
transient or not, got the same 3-attempt exponential-backoff treatment,
wasting real wall-clock time on a request that could never succeed).

Malformed *model output* (valid HTTP response, but the response body
isn't parseable as the JSON schema the caller asked for) is a third,
independent failure class from transport, handled by its own retry
loop inside ``chat_json`` (``_parse_json_response``) rather than by
tenacity re-issuing the whole request -- a request that fails to
transport wants a fresh full retry (network glitch, rate limit); a
request that succeeded at the network layer but returned malformed JSON
almost certainly doesn't need re-sending, only re-parsing (see
``_extract_json_object``'s prefixed-prose recovery) or, failing that,
a distinct, clearly-labeled error rather than tenacity's opaque
``RetryError`` wrapping a ``json.JSONDecodeError``.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import openai
from openai import OpenAI
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from .. import config

CostSink = Callable[[str, str, str, str], None]
"""Callback invoked as sink(model, system, user, response_text) after each call."""


class LLMInvalidRequestError(Exception):
    """Raised immediately (no retry) for a request that can never
    succeed regardless of how many times it's retried -- bad API key,
    malformed request body, model name doesn't exist on this endpoint,
    permission denied, etc. Wraps the original openai.* exception as
    ``__cause__`` so the underlying provider error is never lost."""


class LLMResponseError(Exception):
    """Raised when the provider responded successfully (no transport
    failure) but the response body couldn't be parsed as the JSON shape
    the caller asked for, even after the prefixed-prose recovery pass.
    Distinct from a transport failure -- re-sending the exact same
    request is unlikely to help, since the model produced a real,
    complete response that simply wasn't valid JSON."""


# openai.APIStatusError subclasses carrying a 4xx status that retrying
# can never fix. RateLimitError (429) and InternalServerError (5xx) are
# APIStatusError subclasses too, but are deliberately *not* listed here
# -- both are transient by nature (see _is_transient_openai_error).
_PERMANENT_OPENAI_ERRORS: tuple[type[Exception], ...] = (
    openai.AuthenticationError,
    openai.BadRequestError,
    openai.NotFoundError,
    openai.PermissionDeniedError,
    openai.UnprocessableEntityError,
    openai.ConflictError,
)


def _is_transient_openai_error(exc: BaseException) -> bool:
    """True for a provider failure worth retrying with backoff: a
    connection problem, a timeout, a rate limit, or a 5xx server error.
    False for anything in _PERMANENT_OPENAI_ERRORS (or any other
    exception type) -- those fail on the first attempt via
    LLMInvalidRequestError instead of being retried into the same
    guaranteed failure three times.
    """
    if isinstance(exc, _PERMANENT_OPENAI_ERRORS):
        return False
    return isinstance(exc, (
        openai.APIConnectionError,
        openai.APITimeoutError,
        openai.RateLimitError,
        openai.InternalServerError,
    ))


def _client() -> OpenAI:
    return OpenAI()


def _model(role: str) -> str:
    return config.models().get(role, "Claude Sonnet 4.6")


def _strip_markdown_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        start = 1
        end = len(lines)
        for i in range(len(lines) - 1, 0, -1):
            if lines[i].strip() == "```":
                end = i
                break
        text = "\n".join(lines[start:end]).strip()
        if text.startswith("json"):
            text = text[4:].strip()
    return text


def _extract_json_object(text: str) -> str:
    """Best-effort recovery when a model prefixes its JSON response with
    prose (despite instructions not to) — e.g. "Looking at the text, I
    find... {...}". Finds the first '{' and its matching closing '}'
    (brace-depth counting, string-aware so braces inside quoted strings
    don't confuse it) and returns just that span. Returns *text* unchanged
    if no balanced object is found, so the caller's json.loads still
    raises a clear error rather than silently returning something wrong.
    """
    start = text.find("{")
    if start == -1:
        return text
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text


def _raise_classified(exc: openai.OpenAIError) -> None:
    """Re-raise *exc* as LLMInvalidRequestError if it's a permanent
    failure (see _PERMANENT_OPENAI_ERRORS); otherwise re-raise it
    unchanged so the transient-only @retry decorator below can catch and
    retry it. Called from inside _stream_completion's except clause, not
    from the @retry'd functions themselves, so the classification happens
    exactly once per raw provider exception regardless of retry count.
    """
    if not _is_transient_openai_error(exc):
        raise LLMInvalidRequestError(
            f"{type(exc).__name__}: {exc} -- not retrying, this request cannot succeed "
            "regardless of retry count (bad API key, malformed request, unknown model, "
            "or similar)."
        ) from exc
    raise exc


@retry(
    retry=retry_if_exception(_is_transient_openai_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=20),
)
def _stream_completion(
    client: OpenAI,
    model: str,
    system: str,
    user: str,
    temperature: float,
) -> str:
    """Stream a chat completion and return the concatenated text.

    Some OpenAI-compatible endpoints (e.g. Argo's Claude/Anthropic proxy)
    reject non-streaming requests outright with a 500 ("Streaming is
    required for operations that may take longer than 10 minutes"). We
    always stream and accumulate here so wake works uniformly against
    endpoints that require it and those that don't.

    Retries only transient provider failures (rate limit, timeout,
    connection error, 5xx) with exponential backoff; a permanent failure
    (bad API key, malformed request, unknown model, 4xx other than 429)
    raises LLMInvalidRequestError on the first attempt instead of being
    retried 3 times into the same guaranteed failure.
    """
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            stream=True,
        )
        chunks: list[str] = []
        for event in stream:
            if not event.choices:
                continue
            delta = event.choices[0].delta.content
            if delta:
                chunks.append(delta)
        return "".join(chunks).strip()
    except openai.OpenAIError as exc:
        _raise_classified(exc)
        raise  # pragma: no cover -- _raise_classified always raises


def _parse_json_response(raw: str) -> Any:
    """Parse *raw* as JSON, with one fallback pass for a model that
    prefixed its JSON with reasoning prose despite instructions not to
    (observed live with the 'evidence' role's long full-text prompt).

    This is a distinct retry policy from _stream_completion's transport
    retry, by design: a malformed response body is not a transport
    failure (the request succeeded at the network layer, the model
    produced a real, complete response), so re-sending the exact same
    request is unlikely to help -- only re-parsing might. Raises
    LLMResponseError (not the raw json.JSONDecodeError, and never
    tenacity's opaque RetryError) if both the direct parse and the
    prefixed-prose recovery fail, so a caller can tell "the model's
    output wasn't valid JSON" apart from "the network/provider failed."
    """
    stripped = _strip_markdown_fence(raw)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(_extract_json_object(stripped))
    except json.JSONDecodeError as exc:
        raise LLMResponseError(
            f"Model response was not valid JSON, even after prefixed-prose "
            f"recovery: {exc}. Raw response (truncated): {raw[:500]!r}"
        ) from exc


def chat_json(
    system: str,
    user: str,
    model_role: str = "classify",
    model: str | None = None,
    temperature: float = 0,
    cost_sink: CostSink | None = None,
) -> Any:
    client = _client()
    resolved = model if model is not None else _model(model_role)
    raw = _stream_completion(client, resolved, system, user, temperature)
    if cost_sink is not None:
        cost_sink(resolved, system, user, raw)
    return _parse_json_response(raw)


def chat_text(
    system: str,
    user: str,
    model_role: str = "describe",
    model: str | None = None,
    temperature: float = 0,
    cost_sink: CostSink | None = None,
) -> str:
    client = _client()
    resolved = model if model is not None else _model(model_role)
    text = _stream_completion(client, resolved, system, user, temperature)
    if cost_sink is not None:
        cost_sink(resolved, system, user, text)
    return text
