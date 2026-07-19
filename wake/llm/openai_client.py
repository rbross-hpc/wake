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
    return config.models().get(role, "Claude Sonnet 4.7")


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
    response = client.chat.completions.create(
        model=resolved,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    raw = (response.choices[0].message.content or "").strip()
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
    response = client.chat.completions.create(
        model=resolved,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
    )
    text = (response.choices[0].message.content or "").strip()
    if cost_sink is not None:
        cost_sink(resolved, system, user, text)
    return text
