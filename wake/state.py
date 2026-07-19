# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
# Adapted from pub-analysis/puba/state.py
"""Per-seed .state.json management — cache keys, stage timestamps."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import __version__
from .io import atomic_write_json, now_iso


def state_path(work_dir: Path) -> Path:
    return work_dir / ".state.json"


def load_state(work_dir: Path) -> dict[str, Any]:
    p = state_path(work_dir)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(work_dir: Path, state: dict[str, Any]) -> None:
    atomic_write_json(state_path(work_dir), state)


def is_stage_current(
    work_dir: Path,
    stage: str,
    *,
    seed_id: str,
    prompt_version: str | None = None,
    model: str | None = None,
    extra_key: dict[str, Any] | None = None,
) -> bool:
    """Return True if the stage output is current and can be reused."""
    state = load_state(work_dir)

    if state.get("seed_id") != seed_id:
        return False

    stage_state = state.get("stages", {}).get(stage, {})
    if not stage_state.get("completed_at"):
        return False
    if prompt_version is not None and stage_state.get("prompt_version") != prompt_version:
        return False
    if model is not None and stage_state.get("model") != model:
        return False
    if extra_key is not None:
        for k, v in extra_key.items():
            if stage_state.get(k) != v:
                return False
    return True


def mark_stage_complete(
    work_dir: Path,
    stage: str,
    *,
    seed_id: str,
    prompt_version: str | None = None,
    model: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    state = load_state(work_dir)
    state["seed_id"] = seed_id
    state["tool_version"] = __version__

    stages = state.setdefault("stages", {})
    entry: dict[str, Any] = {
        "completed_at": now_iso(),
        "tool_version": __version__,
    }
    if prompt_version is not None:
        entry["prompt_version"] = prompt_version
    if model is not None:
        entry["model"] = model
    if extra:
        entry.update(extra)
    stages[stage] = entry

    save_state(work_dir, state)
