# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.evidence's multi-facet full-text verification (evidence-2
prompt version) -- see classify.py's module docstring for the design
rationale, and test_multi_facet_classify.py for the abstract-only
(classify) side of the same schema.

Covers: evidence-2 multi-facet response parsing (with per-facet quotes),
evidence-1 legacy single-facet parsing, the top-level "quotes"
deduplicated union, agrees_with_provisional against a multi-facet
provisional, and dossier markdown rendering of 1 vs. 2+ facets.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

from wake import evidence
from .conftest import PARALLEL_NETCDF_WORK, SAMPLE_CITING_WORKS

_FIXTURE = Path(__file__).parent / "fixtures" / "osti_1343551_netcdf_bigdata.pdf"


def _copy_fixture_pdf(tmp_path: Path) -> Path:
    dest = tmp_path / "pdfs" / "citing.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_FIXTURE, dest)
    return dest


CLASSIFIED_CITING_WORK = {
    **SAMPLE_CITING_WORKS[0],
    "relationship": "uses-as-tool",
    "confidence": 0.4,
    "justification": "Likely uses PnetCDF for I/O, based on the abstract alone.",
    "has_abstract": True,
    "verification_status": "provisional",
}


# --- _parse_proposed_relationships ----------------------------------------

def test_parse_proposed_multi_facet_response_with_per_facet_quotes():
    result = {
        "relationships": [
            {
                "label": "uses-as-tool", "confidence": 0.95,
                "justification": "Integrates PnetCDF for all I/O.",
                "quotes": [{"page": 9, "text": "PnetCDF was integrated into IFM for all I/O.", "note": "Direct statement."}],
            },
            {
                "label": "applies-to-domain", "confidence": 0.8,
                "justification": "Applies it to flood modeling.",
                "quotes": [{"page": 2, "text": "IFM is a flood-modeling framework.", "note": "Domain framing."}],
            },
        ],
        "agrees_with_provisional": True,
    }
    facets = evidence._parse_proposed_relationships(result)
    assert [f["label"] for f in facets] == ["uses-as-tool", "applies-to-domain"]
    assert facets[0]["quotes"] == [{"page": 9, "text": "PnetCDF was integrated into IFM for all I/O.", "note": "Direct statement."}]
    assert facets[1]["quotes"][0]["page"] == 2


def test_parse_proposed_legacy_single_facet_response():
    result = {
        "relationship": "extends", "confidence": 0.9,
        "justification": "Direct extension.",
        "quotes": [{"page": 2, "text": "We extend the method.", "note": "x"}],
    }
    facets = evidence._parse_proposed_relationships(result)
    assert len(facets) == 1
    assert facets[0]["label"] == "extends"
    assert facets[0]["quotes"] == [{"page": 2, "text": "We extend the method.", "note": "x"}]


def test_parse_proposed_drops_empty_quote_text():
    result = {
        "relationships": [{
            "label": "extends", "confidence": 0.9, "justification": "x",
            "quotes": [{"page": 1, "text": "   ", "note": "blank"}, {"page": 2, "text": "Real quote.", "note": "y"}],
        }]
    }
    facets = evidence._parse_proposed_relationships(result)
    assert len(facets[0]["quotes"]) == 1
    assert facets[0]["quotes"][0]["text"] == "Real quote."


def test_parse_proposed_falls_back_to_background_mention_when_nothing_usable():
    result = {"relationships": [{"label": "bogus-label", "confidence": 0.9, "justification": "x"}]}
    facets = evidence._parse_proposed_relationships(result)
    assert facets == [{"label": "background-mention", "confidence": 0.5, "justification": "", "quotes": []}]


# --- verify_full_text end-to-end -------------------------------------------

def _fake_multi_facet_evidence_response(*args, **kwargs):
    return {
        "relationships": [
            {
                "label": "uses-as-tool", "confidence": 0.95,
                "justification": "Integrates PnetCDF for all I/O.",
                "quotes": [{"page": 9, "text": "PnetCDF was integrated for all I/O.", "note": "Direct statement."}],
            },
            {
                "label": "applies-to-domain", "confidence": 0.8,
                "justification": "Applies it to flood modeling on supercomputers.",
                "quotes": [{"page": 2, "text": "IFM is a flood-modeling framework for petascale HPC.", "note": "Domain framing."}],
            },
        ],
        "agrees_with_provisional": True,
    }


def test_verify_full_text_with_evidence_2_produces_multi_facet_proposed():
    with patch("wake.evidence.config.evidence_cfg", return_value={"prompt_version": "evidence-2"}), \
         patch("wake.evidence.chat_json", side_effect=_fake_multi_facet_evidence_response):
        finding = evidence.verify_full_text(
            PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, "full text here",
            record_cost=False,
        )

    proposed = finding["proposed"]
    assert len(proposed["relationships"]) == 2
    assert proposed["relationships"][0]["label"] == "uses-as-tool"
    assert proposed["relationships"][1]["label"] == "applies-to-domain"
    # Legacy scalars set from the top (most-confident) facet.
    assert proposed["relationship"] == "uses-as-tool"
    assert proposed["confidence"] == 0.95
    assert proposed["agrees_with_provisional"] is True

    # Top-level "quotes" is the deduplicated union across every facet, in
    # facet order -- for legacy readers (e.g. the CLI's human printer)
    # that only look at the finding as a whole.
    assert len(finding["quotes"]) == 2
    assert finding["quotes"][0]["page"] == 9
    assert finding["quotes"][1]["page"] == 2


def test_verify_full_text_dedups_identical_quotes_across_facets():
    def _fake_overlapping_quotes(*args, **kwargs):
        shared_quote = {"page": 5, "text": "Same passage cited by both facets.", "note": "shared"}
        return {
            "relationships": [
                {"label": "uses-as-tool", "confidence": 0.9, "justification": "x", "quotes": [shared_quote]},
                {"label": "applies-to-domain", "confidence": 0.85, "justification": "y", "quotes": [shared_quote]},
            ],
        }

    with patch("wake.evidence.config.evidence_cfg", return_value={"prompt_version": "evidence-2"}), \
         patch("wake.evidence.chat_json", side_effect=_fake_overlapping_quotes):
        finding = evidence.verify_full_text(
            PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, "full text here",
            record_cost=False,
        )
    assert len(finding["quotes"]) == 1


def test_verify_full_text_with_evidence_1_produces_single_facet_proposed():
    def _fake_single(*args, **kwargs):
        return {
            "relationship": "extends", "confidence": 0.9,
            "justification": "Direct extension.", "agrees_with_provisional": False,
            "quotes": [{"page": 2, "text": "We extend the method.", "note": "x"}],
        }

    with patch("wake.evidence.config.evidence_cfg", return_value={"prompt_version": "evidence-1"}), \
         patch("wake.evidence.chat_json", side_effect=_fake_single):
        finding = evidence.verify_full_text(
            PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, "full text here",
            record_cost=False,
        )

    proposed = finding["proposed"]
    assert proposed["relationships"] == [{
        "label": "extends", "confidence": 0.9, "justification": "Direct extension.",
        "quotes": [{"page": 2, "text": "We extend the method.", "note": "x"}],
    }]
    assert proposed["relationship"] == "extends"


def test_verify_full_text_provisional_facets_from_classify_one_output():
    """A citing_work whose classify sidecar already has a multi-facet
    "relationships" list (classify-3) must have that same multi-facet
    provisional carried through into the dossier's "provisional" block."""
    multi_facet_citing_work = {
        **CLASSIFIED_CITING_WORK,
        "relationships": [
            {"label": "uses-as-tool", "confidence": 0.6, "justification": "a"},
            {"label": "applies-to-domain", "confidence": 0.55, "justification": "b"},
        ],
    }

    def _fake_single(*args, **kwargs):
        return {"relationship": "extends", "confidence": 0.9, "justification": "x", "quotes": []}

    with patch("wake.evidence.chat_json", side_effect=_fake_single):
        finding = evidence.verify_full_text(
            PARALLEL_NETCDF_WORK, multi_facet_citing_work, "full text here",
            record_cost=False,
        )

    assert len(finding["provisional"]["relationships"]) == 2
    assert finding["provisional"]["relationship"] == "uses-as-tool"


# --- build_dossier + dossier markdown rendering (multi-facet) ------------

def _build_multi_facet_dossier(tmp_path):
    pdf_copy = _copy_fixture_pdf(tmp_path)
    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(pdf_copy), "source": "osti",
    }), patch("wake.evidence.config.evidence_cfg", return_value={"prompt_version": "evidence-2"}), \
         patch("wake.evidence.chat_json", side_effect=_fake_multi_facet_evidence_response):
        return evidence.build_dossier(PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, base=tmp_path, verbose=False)


def test_build_dossier_multi_facet_renders_per_facet_sections(tmp_path):
    result = _build_multi_facet_dossier(tmp_path)
    assert result["ok"] is True

    md_text = Path(result["dossier_path"]).read_text()
    assert "### uses-as-tool (confidence: 0.95)" in md_text
    assert "### applies-to-domain (confidence: 0.80)" in md_text
    assert "PnetCDF was integrated for all I/O." in md_text
    assert "IFM is a flood-modeling framework for petascale HPC." in md_text


def test_build_dossier_multi_facet_frontmatter_lists_one_entry_per_facet(tmp_path):
    result = _build_multi_facet_dossier(tmp_path)
    md_text = Path(result["dossier_path"]).read_text()
    proposed_line = next(line for line in md_text.splitlines() if line.startswith("proposed_relationships:"))
    assert "uses-as-tool" in proposed_line
    assert "applies-to-domain" in proposed_line
    # Facets are listed in ranking order within the array.
    assert proposed_line.index("uses-as-tool") < proposed_line.index("applies-to-domain")


def test_build_dossier_multi_facet_json_sidecar_round_trips(tmp_path):
    result = _build_multi_facet_dossier(tmp_path)
    loaded = evidence.load_dossier(
        PARALLEL_NETCDF_WORK["openalex_id"], CLASSIFIED_CITING_WORK["openalex_id"], base=tmp_path,
    )
    assert len(loaded["proposed"]["relationships"]) == 2
    assert loaded["proposed"]["relationships"][0]["label"] == "uses-as-tool"


def test_rerender_dossier_md_preserves_multi_facet_shape(tmp_path):
    """wake evidence --rerender-all must round-trip a multi-facet dossier
    without collapsing it back to single-facet."""
    result = _build_multi_facet_dossier(tmp_path)
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    citing_id = CLASSIFIED_CITING_WORK["openalex_id"]

    md_path = evidence.rerender_dossier_md(PARALLEL_NETCDF_WORK, citing_id, base=tmp_path)
    md_text = md_path.read_text()
    assert "### uses-as-tool (confidence: 0.95)" in md_text
    assert "### applies-to-domain (confidence: 0.80)" in md_text


def test_build_dossier_multi_facet_provisional_renders_per_facet_sections(tmp_path):
    """When classify.py already produced a multi-facet provisional (e.g.
    classify-3), the dossier's ## Provisional Classification section must
    render one subsection per facet too, not just the top one."""
    pdf_copy = _copy_fixture_pdf(tmp_path)
    multi_facet_citing_work = {
        **CLASSIFIED_CITING_WORK,
        "relationships": [
            {"label": "uses-as-tool", "confidence": 0.6, "justification": "Abstract mentions PnetCDF adoption."},
            {"label": "applies-to-domain", "confidence": 0.55, "justification": "Abstract mentions flood modeling."},
        ],
    }

    def _fake_single(*args, **kwargs):
        return {"relationship": "extends", "confidence": 0.9, "justification": "x", "quotes": []}

    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(pdf_copy), "source": "osti",
    }), patch("wake.evidence.chat_json", side_effect=_fake_single):
        result = evidence.build_dossier(PARALLEL_NETCDF_WORK, multi_facet_citing_work, base=tmp_path, verbose=False)

    md_text = Path(result["dossier_path"]).read_text()
    assert "### uses-as-tool (confidence: 0.60)" in md_text
    assert "### applies-to-domain (confidence: 0.55)" in md_text
    provisional_line = next(line for line in md_text.splitlines() if line.startswith("provisional_relationships:"))
    assert "uses-as-tool" in provisional_line
    assert "applies-to-domain" in provisional_line


def test_single_facet_dossier_still_renders_without_subsections(tmp_path):
    """The common case (1 facet, which is almost always what happens per
    classify.py's prompt discipline) must render exactly like the
    original pre-multi-facet single-block form -- no ### subsection
    headings, no visible change for the overwhelmingly common case."""
    pdf_copy = _copy_fixture_pdf(tmp_path)

    def _fake_single(*args, **kwargs):
        return {
            "relationship": "extends", "confidence": 0.9,
            "justification": "Direct extension.", "agrees_with_provisional": False,
            "quotes": [{"page": 2, "text": "We extend the method.", "note": "x"}],
        }

    with patch("wake.evidence.fetch_pdf", return_value={
        "ok": True, "path": str(pdf_copy), "source": "osti",
    }), patch("wake.evidence.chat_json", side_effect=_fake_single):
        result = evidence.build_dossier(PARALLEL_NETCDF_WORK, CLASSIFIED_CITING_WORK, base=tmp_path, verbose=False)

    md_text = Path(result["dossier_path"]).read_text()
    assert "### extends" not in md_text
    assert "> *extends* (confidence: 0.90)" in md_text
