# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.seed — offline (ID detection) and live (network)."""
from __future__ import annotations

import pytest
from wake.seed import _is_doi, _is_arxiv_id, _is_openalex_id, resolve, work_dir
from wake.errors import SeedNotFound


def test_is_doi():
    assert _is_doi("10.1145/1048935.1050189")
    assert _is_doi("doi:10.1234/foo")
    assert _is_doi("https://doi.org/10.1234/foo")
    assert not _is_doi("W2156077349")
    assert not _is_doi("2301.04567")


def test_is_arxiv_id():
    assert _is_arxiv_id("2301.04567")
    assert _is_arxiv_id("1901.00001v2")
    assert _is_arxiv_id("arxiv:2301.04567")
    assert not _is_arxiv_id("10.1145/foo")
    assert not _is_arxiv_id("W2156077349")


def test_is_openalex_id():
    assert _is_openalex_id("W2156077349")
    assert _is_openalex_id("https://openalex.org/W2156077349")
    assert not _is_openalex_id("10.1145/foo")
    assert not _is_openalex_id("2301.04567")


def test_work_dir(tmp_path):
    wd = work_dir("W2156077349", base=tmp_path)
    assert wd.name == "W2156077349"
    assert wd.parent.name == "wake-out"


@pytest.mark.network
def test_resolve_by_doi():
    work = resolve("10.1145/1048935.1050189")
    assert work["openalex_id"] == "W2156077349"
    assert "netCDF" in work["title"]
    assert work["year"] == 2003


@pytest.mark.network
def test_resolve_by_openalex_id():
    work = resolve("W2156077349")
    assert work["openalex_id"] == "W2156077349"


@pytest.mark.network
def test_resolve_by_title():
    work = resolve("Parallel netCDF: A High-Performance Scientific I/O Interface")
    assert work["openalex_id"] == "W2156077349"


@pytest.mark.network
def test_resolve_not_found():
    with pytest.raises(SeedNotFound):
        resolve("this title definitely does not exist xyzzy12345zxcvbn")
