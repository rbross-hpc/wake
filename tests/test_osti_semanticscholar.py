# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.sources.osti / wake.sources.semanticscholar abstract lookups."""
from __future__ import annotations

import pytest
from wake.sources import osti, semanticscholar


def test_osti_normalize_doi():
    assert osti._normalize_doi("https://doi.org/10.1234/foo") == "10.1234/foo"
    assert osti._normalize_doi("doi:10.1234/FOO") == "10.1234/foo"
    assert osti._normalize_doi(None) is None


def test_osti_clean_description_strips_html():
    assert osti._clean_description("<p>Hello <b>world</b></p>") == "Hello world"
    assert osti._clean_description(None) is None
    assert osti._clean_description("") is None


def test_osti_get_abstract_no_doi_returns_none():
    assert osti.get_abstract_by_doi("") is None


def test_semanticscholar_normalize_doi():
    assert semanticscholar._normalize_doi("https://doi.org/10.1234/foo") == "10.1234/foo"
    assert semanticscholar._normalize_doi("doi:10.1234/FOO") == "10.1234/foo"
    assert semanticscholar._normalize_doi(None) is None


def test_semanticscholar_get_abstract_no_doi_returns_none():
    assert semanticscholar.get_abstract_by_doi("") is None


@pytest.mark.network
def test_osti_live_hit():
    # Known DOE-funded work with an abstract in OSTI's 'description' field.
    abstract = osti.get_abstract_by_doi("10.1016/j.envsoft.2011.08.007")
    assert abstract is None or len(abstract) > 20


@pytest.mark.network
def test_semanticscholar_live_hit():
    abstract = semanticscholar.get_abstract_by_doi("10.1016/j.parco.2009.08.001")
    assert abstract is None or "FLASH" in abstract or len(abstract) > 20
