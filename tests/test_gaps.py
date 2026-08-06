# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.gaps — offline (manual-abstract store, gap-finding logic)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from wake import gaps

from .conftest import SAMPLE_CITING_WORKS


def test_manual_abstracts_path(tmp_path):
    p = gaps.manual_abstracts_path("W123", base=tmp_path)
    assert p.name == "manual_abstracts.jsonl"


def test_load_manual_abstracts_missing_returns_empty(tmp_path):
    assert gaps.load_manual_abstracts("W999", base=tmp_path) == {}


def test_load_manual_abstracts_falls_back_to_legacy_dotfile(tmp_path):
    """A packet built before the .manual_abstracts.jsonl ->
    manual_abstracts.jsonl rename should still be readable without any
    migration ceremony."""
    import json as _json

    seed_id, citing_id = "W123", "W456"
    legacy_path = gaps._legacy_manual_abstracts_path(seed_id, base=tmp_path)
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"citing_id": citing_id, "abstract": "Legacy abstract.", "abstract_source": "human-text"}
    legacy_path.write_text(_json.dumps(entry) + "\n", encoding="utf-8")

    assert not gaps.manual_abstracts_path(seed_id, base=tmp_path).exists()
    loaded = gaps.load_manual_abstracts(seed_id, base=tmp_path)
    assert loaded[citing_id]["abstract"] == "Legacy abstract."


def test_add_manual_abstract_migrates_legacy_dotfile_in_place(tmp_path):
    """The first `wake fill-abstract` call after the rename should move
    existing legacy entries over rather than starting a fresh, empty
    manual_abstracts.jsonl next to the stale .manual_abstracts.jsonl."""
    import json as _json

    seed_id = "W123"
    legacy_path = gaps._legacy_manual_abstracts_path(seed_id, base=tmp_path)
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_entry = {"citing_id": "W_old", "abstract": "Old.", "abstract_source": "human-text"}
    legacy_path.write_text(_json.dumps(legacy_entry) + "\n", encoding="utf-8")

    gaps.add_manual_abstract(seed_id, "W_new", abstract="New.", source="human-text", base=tmp_path)

    assert not legacy_path.exists()
    loaded = gaps.load_manual_abstracts(seed_id, base=tmp_path)
    assert "W_old" in loaded
    assert "W_new" in loaded


def test_add_and_load_manual_abstract(tmp_path):
    seed_id = "W123"
    citing_id = "W456"
    entry = gaps.add_manual_abstract(
        seed_id, citing_id,
        abstract="This is the recovered abstract.",
        source="human-text",
        base=tmp_path,
    )
    assert entry["abstract"] == "This is the recovered abstract."
    assert entry["abstract_source"] == "human-text"

    loaded = gaps.load_manual_abstracts(seed_id, base=tmp_path)
    assert citing_id in loaded
    assert loaded[citing_id]["abstract"] == "This is the recovered abstract."


def test_manual_abstract_last_write_wins(tmp_path):
    seed_id = "W123"
    citing_id = "W456"
    gaps.add_manual_abstract(seed_id, citing_id, abstract="First version.", source="human-text", base=tmp_path)
    gaps.add_manual_abstract(seed_id, citing_id, abstract="Corrected version.", source="pdf-extract", base=tmp_path)

    loaded = gaps.load_manual_abstracts(seed_id, base=tmp_path)
    assert loaded[citing_id]["abstract"] == "Corrected version."
    assert loaded[citing_id]["abstract_source"] == "pdf-extract"


def test_apply_manual_abstracts_no_manual():
    result = gaps.apply_manual_abstracts(SAMPLE_CITING_WORKS, {})
    assert result == SAMPLE_CITING_WORKS


def test_apply_manual_abstracts_fills_in():
    target_id = SAMPLE_CITING_WORKS[2]["openalex_id"]  # has abstract=None
    manual = {target_id: {"abstract": "Filled in.", "abstract_source": "human-text"}}
    result = gaps.apply_manual_abstracts(SAMPLE_CITING_WORKS, manual)
    target = next(w for w in result if w["openalex_id"] == target_id)
    assert target["abstract"] == "Filled in."
    assert target["abstract_source"] == "human-text"
    others = [w for w in result if w["openalex_id"] != target_id]
    assert others == [w for w in SAMPLE_CITING_WORKS if w["openalex_id"] != target_id]


def test_find_gaps_filters_by_min_cited_by():
    # SAMPLE_CITING_WORKS[2] has cited_by_count=5, abstract=None, doi=None
    with patch("wake.gaps._backfill_enabled", return_value=False):
        found = gaps.find_gaps(
            SAMPLE_CITING_WORKS, min_cited_by_count=3, try_auto_backfill=False,
        )
    ids = {w["openalex_id"] for w in found}
    assert SAMPLE_CITING_WORKS[2]["openalex_id"] in ids


def test_find_gaps_excludes_works_with_abstract():
    with patch("wake.gaps._backfill_enabled", return_value=False):
        found = gaps.find_gaps(
            SAMPLE_CITING_WORKS, min_cited_by_count=0, try_auto_backfill=False,
        )
    # Only the one work with abstract=None should show up.
    assert len(found) == 1
    assert found[0]["abstract"] is None


def test_find_gaps_excludes_manually_resolved(tmp_path):
    target_id = SAMPLE_CITING_WORKS[2]["openalex_id"]
    gaps.add_manual_abstract("W-seed", target_id, abstract="Resolved.", source="human-text", base=tmp_path)

    found = gaps.find_gaps(
        SAMPLE_CITING_WORKS,
        seed_id="W-seed", base=tmp_path,
        min_cited_by_count=0, try_auto_backfill=False,
    )
    assert found == []


def test_find_gaps_respects_limit():
    works = [
        {**SAMPLE_CITING_WORKS[2], "openalex_id": f"W{i}", "cited_by_count": 100 - i}
        for i in range(5)
    ]
    found = gaps.find_gaps(works, min_cited_by_count=0, limit=2, try_auto_backfill=False)
    assert len(found) == 2
    # Ranked by cited_by_count descending.
    assert found[0]["cited_by_count"] > found[1]["cited_by_count"]


def test_find_gaps_auto_backfill_resolves_and_excludes():
    work = {**SAMPLE_CITING_WORKS[2], "doi": "10.1234/has-a-doi"}
    with patch("wake.gaps.backfill_one", return_value={**work, "abstract": "Recovered by OSTI."}):
        found = gaps.find_gaps(
            [work], min_cited_by_count=0, try_auto_backfill=True,
        )
    assert found == []  # auto-backfill resolved it, so it's not a "gap"


def test_resolve_pdf_path_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        gaps.resolve_pdf_path(tmp_path / "does_not_exist.pdf")


def test_fill_from_text_records_entry(tmp_path):
    entry = gaps.fill_from_text("W-seed", "W-citing", "  A pasted abstract.  ", base=tmp_path)
    assert entry["abstract"] == "A pasted abstract."
    assert entry["abstract_source"] == "human-text"


def test_fill_from_text_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        gaps.fill_from_text("W-seed", "W-citing", "   ", base=tmp_path)
