# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Extract a clean abstract from a PDF's lead-page text via a small LLM call.

This is deliberately narrow: given only the first few pages of a paper (see
sources/pdf_abstract.py), ask the model to locate and return the abstract
verbatim (or lightly cleaned of OCR/layout artifacts), not to summarize the
paper. If the abstract genuinely isn't present in the lead pages, the model
is instructed to say so rather than fabricate one — this keeps the
downstream classify step honest about what came from the paper vs. what
came from a human override.
"""
from __future__ import annotations

from typing import Any

from . import cost as cost_mod
from .llm.openai_client import chat_json

_SYSTEM = """\
You are extracting the abstract from the first few pages of a scanned or
converted research paper. The text may contain OCR artifacts, running
headers/footers, author affiliations, and keyword lists mixed in with the
abstract — clean these out and return only the abstract's prose.

Respond with ONLY a single JSON object:
{
  "found": <true or false>,
  "abstract": "<the cleaned abstract text, or empty string if not found>"
}

Set "found" to false (and "abstract" to "") if no abstract is present in
the given text — do not fabricate or summarize the paper's content as a
substitute for a genuine abstract.\
"""

_USER_TEMPLATE = """\
Paper title (if known): {title}

Extracted text from the first {n_pages} page(s):
---
{lead_text}
---

Extract the abstract.\
"""


def extract_abstract_from_lead_text(
    lead_text: str,
    *,
    title: str | None = None,
    n_pages: int = 3,
    seed_id: str | None = None,
    base: Any = None,
    record_cost: bool = True,
) -> str | None:
    """Return the cleaned abstract text, or None if not found in *lead_text*."""
    user_msg = _USER_TEMPLATE.format(
        title=title or "Unknown",
        n_pages=n_pages,
        lead_text=lead_text.strip()[:8000],
    )

    cost_sink = None
    if record_cost and seed_id is not None:
        def cost_sink(model: str, system: str, user: str, response_text: str) -> None:
            cost_mod.record_call(
                seed_id, stage="pdf_abstract_extract", model=model,
                system=system, user=user, response_text=response_text, base=base,
            )

    result = chat_json(_SYSTEM, user_msg, model_role="pdf_abstract_extract", cost_sink=cost_sink)

    if not result.get("found"):
        return None
    abstract = (result.get("abstract") or "").strip()
    return abstract or None
