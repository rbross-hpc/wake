# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
# Vendored from ref-checker/ref_checker/similarity.py
"""Shared similarity utilities for wake."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher


def _normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def title_ratio(ref_title: str | None, cand_title: str | None) -> float:
    """Return SequenceMatcher ratio of two Unicode-normalized titles."""
    if not ref_title or not cand_title:
        return 0.0
    return SequenceMatcher(None, _normalize(ref_title), _normalize(cand_title)).ratio()
