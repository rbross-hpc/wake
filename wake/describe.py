# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""LLM-generated one-paragraph contribution description for a seed paper."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import config, cost as cost_mod
from .io import atomic_write_json, now_iso, read_json
from .llm.openai_client import chat_text
from .seed import work_dir
from .state import is_stage_current, mark_stage_complete

_STAGE = "describe"

_SYSTEM = """\
You are a research analyst writing concise, evidence-based impact assessments.
Your task is to describe the contribution of a research paper in one clear paragraph (3-5 sentences).
Focus on:
1. What specific problem or gap the paper addresses.
2. What the paper contributes (method, tool, dataset, theory, system).
3. Why this contribution matters — what it enables that wasn't possible before.
Be specific and precise; avoid generic phrases like "significant contribution" or "novel approach".\
"""

_USER_TEMPLATE = """\
Paper: {title}
Authors: {authors}
Year: {year}
Venue: {venue}
Abstract: {abstract}

Write a one-paragraph contribution description for this paper.\
"""


def _prompt_version() -> str:
    return config.describe_cfg().get("prompt_version", "describe-1")


def _model() -> str:
    return config.models().get("describe", "Claude Sonnet 4.6")


def describe_seed(
    seed_work: dict[str, Any],
    *,
    base: Path | None = None,
    record_cost: bool = True,
) -> str:
    """Call the LLM to produce a contribution paragraph for the seed paper."""
    authors = seed_work.get("authors", [])
    author_str = ", ".join(authors[:5]) + (" et al." if len(authors) > 5 else "")

    user_msg = _USER_TEMPLATE.format(
        title=seed_work.get("title") or "Unknown",
        authors=author_str or "Unknown",
        year=seed_work.get("year") or "Unknown",
        venue=seed_work.get("venue") or "Unknown",
        abstract=seed_work.get("abstract") or "(abstract not available)",
    )

    cost_sink = None
    if record_cost:
        seed_id = seed_work.get("openalex_id")
        if seed_id:
            def cost_sink(model: str, system: str, user: str, response_text: str) -> None:
                cost_mod.record_call(
                    seed_id, stage="describe", model=model,
                    system=system, user=user, response_text=response_text, base=base,
                )

    return chat_text(_SYSTEM, user_msg, model_role="describe", cost_sink=cost_sink)


def describe_and_cache(
    seed_work: dict[str, Any],
    *,
    base: Path | None = None,
    force: bool = False,
    verbose: bool = True,
) -> str:
    """Generate and cache the contribution description for a seed paper."""
    oid = seed_work["openalex_id"]
    wd = work_dir(oid, base)
    model = _model()
    pv = _prompt_version()

    desc_path = wd / "seed.json"

    if not force and is_stage_current(wd, _STAGE, seed_id=oid, prompt_version=pv, model=model):
        if desc_path.exists():
            cached = read_json(desc_path)
            if cached.get("description"):
                return cached["description"]

    if verbose:
        print(f"[wake] Generating contribution description (model={model})...", file=sys.stderr)
    description = describe_seed(seed_work, base=base)

    updated = {**seed_work, "description": description, "described_at": now_iso()}
    wd.mkdir(parents=True, exist_ok=True)
    atomic_write_json(desc_path, updated)
    mark_stage_complete(wd, _STAGE, seed_id=oid, prompt_version=pv, model=model)

    return description
