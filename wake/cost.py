# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Estimate-only LLM cost/token telemetry.

We do not depend on the upstream endpoint returning usage data (Argo may or
may not). Instead we estimate tokens from character counts (a standard
~4 chars/token heuristic) and record per-call estimates to a JSONL sidecar,
so `wake status` / `wake cost` can report a running estimate. Rates are
sourced from config; unpriced models report cost_usd_est = 0.0 and are
flagged unpriced=true so we never silently lie about accuracy.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import atomic_write_text, now_iso
from .seed import work_dir

_CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: str) -> int:
    """Rough token estimate from character count (~4 chars/token)."""
    if not text:
        return 0
    return max(1, round(len(text) / _CHARS_PER_TOKEN))


def _rates() -> dict[str, dict[str, float]]:
    from . import config
    return config.load().get("cost", {}).get("rates_per_1k_usd", {})


def estimate_cost_usd(model: str, in_tokens: int, out_tokens: int) -> tuple[float, bool]:
    """Return (estimated_usd, unpriced). unpriced=True if model has no rate entry."""
    rates = _rates()
    rate = rates.get(model)
    if not rate:
        return 0.0, True
    in_rate = rate.get("in", 0.0)
    out_rate = rate.get("out", 0.0)
    cost = (in_tokens / 1000.0) * in_rate + (out_tokens / 1000.0) * out_rate
    return round(cost, 6), False


def cost_log_path(seed_id: str, base: Path | None = None) -> Path:
    return work_dir(seed_id, base) / ".cost.jsonl"


def record_call(
    seed_id: str,
    *,
    stage: str,
    model: str,
    system: str,
    user: str,
    response_text: str,
    base: Path | None = None,
) -> dict[str, Any]:
    """Estimate tokens/cost for one LLM call and append to .cost.jsonl.

    Returns the recorded entry.
    """
    in_tokens = estimate_tokens(system) + estimate_tokens(user)
    out_tokens = estimate_tokens(response_text)
    cost_usd_est, unpriced = estimate_cost_usd(model, in_tokens, out_tokens)

    entry = {
        "ts": now_iso(),
        "stage": stage,
        "model": model,
        "in_tokens_est": in_tokens,
        "out_tokens_est": out_tokens,
        "cost_usd_est": cost_usd_est,
        "unpriced": unpriced,
    }

    p = cost_log_path(seed_id, base)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, default=str) + "\n"
    with open(p, "a", encoding="utf-8") as f:
        f.write(line)

    return entry


def read_log(seed_id: str, base: Path | None = None) -> list[dict[str, Any]]:
    p = cost_log_path(seed_id, base)
    if not p.exists():
        return []
    entries = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def summarize(seed_id: str, base: Path | None = None) -> dict[str, Any]:
    """Sum up recorded cost entries by stage and overall."""
    entries = read_log(seed_id, base)
    by_stage: dict[str, dict[str, Any]] = {}
    total_cost = 0.0
    total_calls = 0
    any_unpriced = False

    for e in entries:
        stage = e.get("stage", "unknown")
        s = by_stage.setdefault(stage, {
            "calls": 0, "in_tokens_est": 0, "out_tokens_est": 0, "cost_usd_est": 0.0,
        })
        s["calls"] += 1
        s["in_tokens_est"] += e.get("in_tokens_est", 0)
        s["out_tokens_est"] += e.get("out_tokens_est", 0)
        s["cost_usd_est"] += e.get("cost_usd_est", 0.0)
        total_cost += e.get("cost_usd_est", 0.0)
        total_calls += 1
        if e.get("unpriced"):
            any_unpriced = True

    for s in by_stage.values():
        s["cost_usd_est"] = round(s["cost_usd_est"], 6)

    return {
        "total_calls": total_calls,
        "total_cost_usd_est": round(total_cost, 6),
        "any_unpriced": any_unpriced,
        "by_stage": by_stage,
    }


def estimate_remaining_classify_cost(
    seed_id: str,
    model: str,
    pending_count: int,
    *,
    avg_system_chars: int = 900,
    avg_user_chars: int = 500,
    avg_response_chars: int = 200,
    base: Path | None = None,
) -> dict[str, Any]:
    """Estimate the cost of classifying *pending_count* more works.

    Uses average call sizes from config defaults (classify prompt is
    roughly constant size); does not require any prior calls to exist.
    """
    in_tokens = estimate_tokens("x" * avg_system_chars) + estimate_tokens("x" * avg_user_chars)
    out_tokens = estimate_tokens("x" * avg_response_chars)
    per_call_cost, unpriced = estimate_cost_usd(model, in_tokens, out_tokens)
    return {
        "pending_count": pending_count,
        "model": model,
        "per_call_cost_usd_est": per_call_cost,
        "total_cost_usd_est": round(per_call_cost * pending_count, 4),
        "unpriced": unpriced,
    }
