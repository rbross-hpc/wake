# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.similarity."""
from __future__ import annotations

import pytest
from wake.similarity import title_ratio, _normalize


def test_identical_titles():
    assert title_ratio("Parallel netCDF", "Parallel netCDF") == pytest.approx(1.0)


def test_case_insensitive():
    assert title_ratio("parallel netcdf", "PARALLEL NETCDF") == pytest.approx(1.0)


def test_unicode_normalization():
    assert title_ratio("Café", "Cafe") > 0.8


def test_empty_inputs():
    assert title_ratio(None, "foo") == 0.0
    assert title_ratio("foo", None) == 0.0
    assert title_ratio("", "") == 0.0


def test_dissimilar_titles():
    assert title_ratio("Parallel netCDF", "Deep Learning for Image Classification") < 0.3


def test_partial_match():
    ratio = title_ratio(
        "Parallel netCDF: A High-Performance Scientific I/O Interface",
        "Parallel netCDF",
    )
    assert 0.3 < ratio < 1.0
