# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.describe.describe_seed -- the LLM-generated contribution
paragraph, and its Theme K Pass 2 seed-excerpt context (describe-2)."""
from __future__ import annotations

from unittest.mock import patch

from wake import describe
from wake.io import atomic_write_json
from wake.seed import work_dir

from .conftest import PARALLEL_NETCDF_WORK


def test_describe_seed_uses_abstract_when_no_seed_pdf(tmp_path):
    with patch("wake.describe.chat_text", return_value="A description.") as mock_chat:
        result = describe.describe_seed(PARALLEL_NETCDF_WORK, base=tmp_path, record_cost=False)

    assert result == "A description."
    user_msg = mock_chat.call_args[0][1]
    assert "Seed paper excerpt" not in user_msg
    assert PARALLEL_NETCDF_WORK["abstract"] in user_msg


def _seed_with_pdf_text(tmp_path, pages):
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    wd = work_dir(seed_id, tmp_path)
    ext_path = wd / "seed.pdf.json"
    atomic_write_json(wd / "seed.json", {
        **PARALLEL_NETCDF_WORK,
        "seed_pdf": {
            "path": str(wd / "seed.pdf"), "extracted_text_path": str(ext_path),
            "source": "osti", "fetched_at": "2020-01-01T00:00:00",
        },
    })
    atomic_write_json(ext_path, {"pdf_sha256": "x", "pages": pages})


def test_describe_seed_includes_seed_excerpt_when_available(tmp_path):
    _seed_with_pdf_text(tmp_path, ["This paper introduces PnetCDF, a parallel I/O library."])

    with patch("wake.describe.chat_text", return_value="A description.") as mock_chat:
        describe.describe_seed(PARALLEL_NETCDF_WORK, base=tmp_path, record_cost=False)

    user_msg = mock_chat.call_args[0][1]
    assert "Seed paper excerpt" in user_msg
    assert "PnetCDF, a parallel I/O library" in user_msg


def test_describe_seed_respects_seed_excerpt_chars_config(tmp_path):
    _seed_with_pdf_text(tmp_path, ["A" * 500])

    with patch("wake.describe.chat_text", return_value="A description.") as mock_chat, \
         patch("wake.describe.config.describe_cfg", return_value={"prompt_version": "describe-2", "seed_excerpt_chars": 10}):
        describe.describe_seed(PARALLEL_NETCDF_WORK, base=tmp_path, record_cost=False)

    user_msg = mock_chat.call_args[0][1]
    assert "A" * 11 not in user_msg


def test_describe_seed_omits_excerpt_when_extraction_empty(tmp_path):
    """Scanned seed PDF with no extractable text -- fall back cleanly to
    abstract-only, matching pre-describe-2 behavior."""
    _seed_with_pdf_text(tmp_path, ["", "  "])

    with patch("wake.describe.chat_text", return_value="A description.") as mock_chat:
        describe.describe_seed(PARALLEL_NETCDF_WORK, base=tmp_path, record_cost=False)

    user_msg = mock_chat.call_args[0][1]
    assert "Seed paper excerpt" not in user_msg
