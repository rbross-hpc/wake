# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.cost — estimate-only telemetry."""
from __future__ import annotations

import pytest
from wake.cost import (
    estimate_tokens,
    estimate_cost_usd,
    record_call,
    read_log,
    summarize,
    estimate_remaining_classify_cost,
    cost_log_path,
)


def test_estimate_tokens_basic():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 400) == 100


def test_estimate_cost_usd_unpriced_model():
    cost, unpriced = estimate_cost_usd("some-unknown-model", 1000, 1000)
    assert cost == 0.0
    assert unpriced is True


def test_record_call_and_read_log(tmp_path):
    seed_id = "W123"
    entry = record_call(
        seed_id, stage="classify", model="test-model",
        system="system prompt", user="user prompt",
        response_text="response", base=tmp_path,
    )
    assert entry["stage"] == "classify"
    assert entry["model"] == "test-model"
    assert entry["in_tokens_est"] > 0
    assert entry["out_tokens_est"] > 0

    log = read_log(seed_id, base=tmp_path)
    assert len(log) == 1
    assert log[0]["stage"] == "classify"


def test_read_log_missing_returns_empty(tmp_path):
    assert read_log("W999", base=tmp_path) == []


def test_summarize_aggregates_by_stage(tmp_path):
    seed_id = "W123"
    record_call(seed_id, stage="classify", model="m", system="s", user="u", response_text="r", base=tmp_path)
    record_call(seed_id, stage="classify", model="m", system="s", user="u", response_text="r", base=tmp_path)
    record_call(seed_id, stage="describe", model="m", system="s", user="u", response_text="r", base=tmp_path)

    summary = summarize(seed_id, base=tmp_path)
    assert summary["total_calls"] == 3
    assert summary["by_stage"]["classify"]["calls"] == 2
    assert summary["by_stage"]["describe"]["calls"] == 1


def test_estimate_remaining_classify_cost(tmp_path):
    est = estimate_remaining_classify_cost("W123", "some-model", 100, base=tmp_path)
    assert est["pending_count"] == 100
    assert est["unpriced"] is True
    assert est["total_cost_usd_est"] == 0.0


def test_cost_log_path(tmp_path):
    p = cost_log_path("W123", base=tmp_path)
    assert p.name == ".cost.jsonl"
