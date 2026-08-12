# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.seed.resolve_and_cache's non-destructive re-resolve
behavior -- offline.

See PLAN.md's "classify-4 description-only + required" for the live bug
this covers: a re-resolve triggered by a missing/stale .state.json seed
stage was silently overwriting seed.json wholesale, destroying
`wake describe`/`wake fetch-pdf` enrichment (description, described_at,
seed_pdf) with no warning.
"""
from __future__ import annotations

from unittest.mock import patch

from wake.io import atomic_write_json, read_json
from wake.seed import resolve_and_cache, work_dir

from .conftest import PARALLEL_NETCDF_WORK

_SEED = PARALLEL_NETCDF_WORK


def _write_enriched_seed(tmp_path, extra=None):
    wd = work_dir(_SEED["openalex_id"], tmp_path)
    wd.mkdir(parents=True, exist_ok=True)
    payload = {
        **_SEED,
        "resolved_at": "2020-01-01T00:00:00",
        "description": "Existing contribution paragraph from a prior wake describe run.",
        "described_at": "2020-01-02T00:00:00",
        "seed_pdf": {
            "path": str(wd / "seed.pdf"),
            "extracted_text_path": str(wd / "seed.pdf.json"),
            "source": "supplied",
            "fetched_at": "2020-01-03T00:00:00",
        },
        **(extra or {}),
    }
    atomic_write_json(wd / "seed.json", payload)
    return wd


def test_resolve_and_cache_preserves_enrichment_on_reresolve(tmp_path):
    """A re-resolve that falls through the is_stage_current fast path
    (e.g. no .state.json seed-stage entry recorded, or --force) must not
    drop description/described_at/seed_pdf -- only core bibliographic
    fields should reflect the fresh resolve."""
    _write_enriched_seed(tmp_path)

    fresh_from_openalex = {**_SEED, "title": "Parallel netCDF (updated title)"}
    with patch("wake.seed.resolve", return_value=fresh_from_openalex), \
         patch("wake.config.pdf_fetch_cfg", return_value={"seed_pdf_at_resolve": False}):
        result = resolve_and_cache(_SEED["openalex_id"], base=tmp_path, force=True)

    assert result["title"] == "Parallel netCDF (updated title)"
    assert result["description"] == "Existing contribution paragraph from a prior wake describe run."
    assert result["described_at"] == "2020-01-02T00:00:00"
    assert result["seed_pdf"]["source"] == "supplied"

    on_disk = read_json(work_dir(_SEED["openalex_id"], tmp_path) / "seed.json")
    assert on_disk["description"] == "Existing contribution paragraph from a prior wake describe run."
    assert on_disk["seed_pdf"]["source"] == "supplied"


def test_resolve_and_cache_reresolve_still_updates_core_fields(tmp_path):
    """Core bibliographic fields must still reflect the fresh resolve --
    this is a merge-preserve of enrichment fields only, not a full
    seed.json freeze."""
    _write_enriched_seed(tmp_path, extra={"cited_by_count": 100})

    fresh_from_openalex = {**_SEED, "cited_by_count": 999}
    with patch("wake.seed.resolve", return_value=fresh_from_openalex), \
         patch("wake.config.pdf_fetch_cfg", return_value={"seed_pdf_at_resolve": False}):
        result = resolve_and_cache(_SEED["openalex_id"], base=tmp_path, force=True)

    assert result["cited_by_count"] == 999


def test_resolve_and_cache_fresh_seed_has_no_enrichment_to_preserve(tmp_path):
    """A genuinely first-time resolve (no existing seed.json) must not
    error or synthesize enrichment fields out of nothing."""
    with patch("wake.seed.resolve", return_value={**_SEED}), \
         patch("wake.config.pdf_fetch_cfg", return_value={"seed_pdf_at_resolve": False}):
        result = resolve_and_cache(_SEED["openalex_id"], base=tmp_path)

    assert result["openalex_id"] == _SEED["openalex_id"]
    assert result.get("description") is None
    assert result.get("seed_pdf") is None
