# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Single source of truth for wake's relationship vocabulary.

This module is the only place the canonical relationship labels and their
``Literal`` type alias are defined.  It has no dependencies on any other
wake module, so both ``wake.models`` (schema layer) and ``wake.classify``
(prompt/classification layer) can import from here without creating a
circular dependency.

The previous arrangement duplicated ``CANONICAL_RELATIONSHIPS`` as a tuple
in both ``models.py`` and ``classify.py``, with a test asserting equality.
That test is replaced by a single import in each consumer.
"""
from __future__ import annotations

from typing import Literal

CANONICAL_RELATIONSHIPS: tuple[str, ...] = (
    "extends",
    "builds-on",
    "uses-as-tool",
    "benchmarks",
    "applies-to-domain",
    "related-infrastructure",
    "background-mention",
)

RelationshipLabel = Literal[
    "extends",
    "builds-on",
    "uses-as-tool",
    "benchmarks",
    "applies-to-domain",
    "related-infrastructure",
    "background-mention",
]
