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
    "uses-method-from",
    "uses-data-from",
    "applies-to-domain",
    "benchmarks",
    "related",
    "cites",
)

RelationshipLabel = Literal[
    "extends",
    "uses-method-from",
    "uses-data-from",
    "applies-to-domain",
    "benchmarks",
    "related",
    "cites",
]

# Labels retired by the CiTO-alignment refactor (v0.4.21), mapped to their
# replacement.  `uses-as-tool` split into two more specific labels;
# `builds-on` folded into `uses-method-from` (a paper that builds a new
# system depending on the seed's method IS using that method, just to
# build something new rather than apply it directly -- one label, not
# two, once "as-is use" and "component dependency" are both read as
# uses-method-from).  `related-infrastructure` and `background-mention`
# were renamed for closer alignment with CiTO's `citesAsRelated` and
# `cites` respectively, with no change in meaning.
#
# Consumed by models.py's migrate_* functions to rewrite a persisted
# label forward -- never consulted by classify/evidence (which only ever
# emit CANONICAL_RELATIONSHIPS) or by scoring (which only ever reads
# CANONICAL_RELATIONSHIPS via relationship_strength()).
RETIRED_RELATIONSHIPS: dict[str, str] = {
    "uses-as-tool": "uses-method-from",
    "builds-on": "uses-method-from",
    "related-infrastructure": "related",
    "background-mention": "cites",
}
