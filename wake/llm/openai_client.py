# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
# Adapted from pub-analysis/puba/llm/openai_client.py
"""OpenAI-compatible LLM client wrapper with retries."""
from __future__ import annotations

import json
from typing import Any, Callable

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from .. import config

CostSink = Callable[[str, str, str, str], None]
"""Callback invoked as sink(model, system, user, response_text) after each call."""


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
    """
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


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
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
    raw = _strip_markdown_fence(raw)
    return json.loads(raw)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=20))
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
