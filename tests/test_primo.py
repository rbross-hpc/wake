# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.sources.primo — offline (mocked HTTP), plus the
no-endpoint-configured safety contract that guarantees no wake install
ever silently queries an institution's Primo endpoint it wasn't given."""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

from wake import config
from wake.errors import RateLimited
from wake.sources import primo

_ENV_VARS = ("WAKE_PRIMO_BASE_URL", "WAKE_PRIMO_VID", "WAKE_PRIMO_INST", "WAKE_PRIMO_SCOPE")


@pytest.fixture(autouse=True)
def _clear_primo_env_and_config(monkeypatch):
    """Every test starts with Primo fully unconfigured (no env vars, no
    config block) unless it opts in explicitly — this is the default
    posture for every wake install."""
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(primo, "_cfg", lambda: {})
    config.reload()
    yield
    config.reload()


def _doc(title: str, abstract: str | None = None, doi: str | None = None) -> dict:
    display: dict = {"title": [title]}
    if abstract is not None:
        display["description"] = [abstract]
    addata: dict = {}
    if doi is not None:
        addata["doi"] = [doi]
    return {"pnx": {"display": display, "addata": addata}}


# --- Safety: no endpoint configured => always a no-op, never touches network ---


def test_is_enabled_false_with_no_config_or_env():
    assert primo.is_enabled() is False


def test_endpoint_none_without_base_url():
    assert primo._endpoint() is None


def test_get_abstract_by_doi_noop_without_endpoint():
    with patch("wake.sources.primo.requests.get") as mock_get:
        result = primo.get_abstract_by_doi("10.1234/fake")
    mock_get.assert_not_called()
    assert result is None


def test_get_abstract_by_title_noop_without_endpoint():
    with patch("wake.sources.primo.requests.get") as mock_get:
        result = primo.get_abstract_by_title("Some Paper Title")
    mock_get.assert_not_called()
    assert result is None


def test_get_doi_by_title_noop_without_endpoint():
    with patch("wake.sources.primo.requests.get") as mock_get:
        result = primo.get_doi_by_title("Some Paper Title")
    mock_get.assert_not_called()
    assert result is None


def test_endpoint_requires_vid_and_inst_even_with_base_url(monkeypatch):
    monkeypatch.setenv("WAKE_PRIMO_BASE_URL", "https://example.primo.exlibrisgroup.com")
    # vid/inst deliberately left unset.
    assert primo._endpoint() is None
    assert primo.is_enabled() is False


# --- Endpoint resolution: env vars take precedence over config ---


def test_endpoint_resolves_from_env(monkeypatch):
    monkeypatch.setenv("WAKE_PRIMO_BASE_URL", "https://example.primo.exlibrisgroup.com/")
    monkeypatch.setenv("WAKE_PRIMO_VID", "01EX_INST:01EX")
    monkeypatch.setenv("WAKE_PRIMO_INST", "01EX_INST")
    endpoint = primo._endpoint()
    assert endpoint is not None
    assert endpoint["base_url"] == "https://example.primo.exlibrisgroup.com"  # trailing slash stripped
    assert endpoint["vid"] == "01EX_INST:01EX"
    assert endpoint["inst"] == "01EX_INST"
    assert endpoint["scope"] == "MyInst_and_CI"  # default
    assert primo.is_enabled() is True


def test_endpoint_env_overrides_config(monkeypatch):
    monkeypatch.setattr(
        primo,
        "_cfg",
        lambda: {
            "base_url": "https://config-configured.example.com",
            "vid": "CONFIG_VID",
            "inst": "CONFIG_INST",
        },
    )
    monkeypatch.setenv("WAKE_PRIMO_BASE_URL", "https://env-configured.example.com")
    monkeypatch.setenv("WAKE_PRIMO_VID", "ENV_VID")
    monkeypatch.setenv("WAKE_PRIMO_INST", "ENV_INST")
    endpoint = primo._endpoint()
    assert endpoint["base_url"] == "https://env-configured.example.com"
    assert endpoint["vid"] == "ENV_VID"
    assert endpoint["inst"] == "ENV_INST"


def test_endpoint_falls_back_to_config_when_env_unset(monkeypatch):
    monkeypatch.setattr(
        primo,
        "_cfg",
        lambda: {
            "base_url": "https://config-configured.example.com",
            "vid": "CONFIG_VID",
            "inst": "CONFIG_INST",
            "scope": "CustomScope",
        },
    )
    endpoint = primo._endpoint()
    assert endpoint["base_url"] == "https://config-configured.example.com"
    assert endpoint["scope"] == "CustomScope"


def _configure(monkeypatch):
    monkeypatch.setenv("WAKE_PRIMO_BASE_URL", "https://example.primo.exlibrisgroup.com")
    monkeypatch.setenv("WAKE_PRIMO_VID", "01EX_INST:01EX")
    monkeypatch.setenv("WAKE_PRIMO_INST", "01EX_INST")


# --- DOI normalization / description cleaning (pure functions) ---


def test_normalize_doi():
    assert primo._normalize_doi("https://doi.org/10.1234/foo") == "10.1234/foo"
    assert primo._normalize_doi("doi:10.1234/FOO") == "10.1234/foo"
    assert primo._normalize_doi(None) is None
    assert primo._normalize_doi("") is None


def test_clean_description_strips_html():
    assert primo._clean_description("<p>Hello <b>world</b></p>") == "Hello world"
    assert primo._clean_description(None) is None
    assert primo._clean_description("") is None


# --- get_metadata_by_doi / get_abstract_by_doi (mocked HTTP, endpoint configured) ---


def _mock_response(status_code: int, json_body: dict | None = None, headers: dict | None = None):
    resp = Mock()
    resp.status_code = status_code
    resp.headers = headers or {}
    if json_body is not None:
        resp.json.return_value = json_body
    return resp


def test_get_abstract_by_doi_hit(monkeypatch):
    _configure(monkeypatch)
    resp = _mock_response(200, {"docs": [_doc("A Paper", abstract="<p>An abstract.</p>", doi="10.1234/real")]})
    with patch("wake.sources.primo.requests.get", return_value=resp) as mock_get:
        abstract = primo.get_abstract_by_doi("10.1234/real")
    assert abstract == "An abstract."
    args, kwargs = mock_get.call_args
    assert kwargs["params"]["q"] == "any,contains,10.1234/real"


def test_get_abstract_by_doi_no_doi_returns_none(monkeypatch):
    _configure(monkeypatch)
    assert primo.get_abstract_by_doi("") is None
    assert primo.get_abstract_by_doi(None) is None  # type: ignore[arg-type]


def test_get_abstract_by_doi_miss(monkeypatch):
    _configure(monkeypatch)
    resp = _mock_response(200, {"docs": []})
    with patch("wake.sources.primo.requests.get", return_value=resp):
        assert primo.get_abstract_by_doi("10.1234/nomatch") is None


def test_get_abstract_by_doi_404_returns_none(monkeypatch):
    _configure(monkeypatch)
    resp = _mock_response(404)
    with patch("wake.sources.primo.requests.get", return_value=resp):
        assert primo.get_abstract_by_doi("10.1234/missing") is None


def test_get_abstract_by_doi_429_raises_rate_limited(monkeypatch):
    _configure(monkeypatch)
    resp = _mock_response(429, headers={"Retry-After": "30"})
    with patch("wake.sources.primo.requests.get", return_value=resp):
        with pytest.raises(RateLimited) as excinfo:
            primo.get_abstract_by_doi("10.1234/throttled")
    assert excinfo.value.retry_after == 30.0


def test_get_metadata_by_doi_returns_full_record(monkeypatch):
    _configure(monkeypatch)
    resp = _mock_response(
        200, {"docs": [_doc("Full Record Title", abstract="The abstract.", doi="10.5555/x")]}
    )
    with patch("wake.sources.primo.requests.get", return_value=resp):
        record = primo.get_metadata_by_doi("10.5555/x")
    assert record == {"title": "Full Record Title", "abstract": "The abstract.", "doi": "10.5555/x"}


# --- Title-fallback lookups, with the similarity guard ---


def test_get_abstract_by_title_accepts_close_match(monkeypatch):
    _configure(monkeypatch)
    resp = _mock_response(
        200,
        {
            "docs": [
                _doc("PVFS: A Parallel File System for Linux Clusters", abstract="The real abstract."),
                _doc("An Unrelated Paper About Compilers", abstract="Wrong abstract."),
            ]
        },
    )
    with patch("wake.sources.primo.requests.get", return_value=resp):
        abstract = primo.get_abstract_by_title("PVFS: A Parallel File System for Linux Clusters")
    assert abstract == "The real abstract."


def test_get_abstract_by_title_rejects_dissimilar_top_hit(monkeypatch):
    _configure(monkeypatch)
    # Simulates the "Handbook of parallel computing" case: many loosely
    # related hits, none actually matching closely enough to trust.
    resp = _mock_response(
        200,
        {
            "docs": [
                _doc("Deterministic and Randomized Sorting Algorithms", abstract="Unrelated."),
                _doc("Some Other Handbook Chapter", abstract="Also unrelated."),
            ]
        },
    )
    with patch("wake.sources.primo.requests.get", return_value=resp):
        abstract = primo.get_abstract_by_title("Handbook of Parallel Computing Models and Applications")
    assert abstract is None


def test_get_abstract_by_title_empty_title_returns_none(monkeypatch):
    _configure(monkeypatch)
    with patch("wake.sources.primo.requests.get") as mock_get:
        assert primo.get_abstract_by_title("") is None
    mock_get.assert_not_called()


def test_get_doi_by_title_accepts_close_match(monkeypatch):
    _configure(monkeypatch)
    resp = _mock_response(
        200,
        {"docs": [_doc("File System Semantics Requirements of HPC Applications", doi="10.1145/3431379.3460637")]},
    )
    with patch("wake.sources.primo.requests.get", return_value=resp):
        doi = primo.get_doi_by_title("File System Semantics Requirements of HPC Applications")
    assert doi == "10.1145/3431379.3460637"


def test_get_doi_by_title_no_doi_on_matched_record_returns_none(monkeypatch):
    _configure(monkeypatch)
    resp = _mock_response(200, {"docs": [_doc("Exact Title Match Here")]})  # no doi field
    with patch("wake.sources.primo.requests.get", return_value=resp):
        assert primo.get_doi_by_title("Exact Title Match Here") is None


def test_title_similarity_threshold_configurable(monkeypatch):
    monkeypatch.setattr(primo, "_cfg", lambda: {"title_similarity_threshold": 0.99})
    assert primo._title_similarity_threshold() == 0.99


@pytest.mark.network
def test_primo_live_hit_requires_real_endpoint_env():
    """Only runs meaningfully with WAKE_PRIMO_BASE_URL/_VID/_INST set in
    the live environment; otherwise this is just is_enabled() == False
    and the assertion is trivially satisfied (no network call made)."""
    if not primo.is_enabled():
        pytest.skip("Primo not configured in this environment")
    abstract = primo.get_abstract_by_doi("10.1016/j.jpdc.2010.08.004")
    assert abstract is None or len(abstract) > 20
