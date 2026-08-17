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

_ENV_VARS = ("PRIMO_BASE_URL", "PRIMO_VID", "PRIMO_INST", "PRIMO_SCOPE")


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


def _doc(
    title: str,
    abstract: str | None = None,
    doi: str | None = None,
    *,
    oa: bool = False,
    pdf_url: str | None = None,
) -> dict:
    display: dict = {"title": [title]}
    if abstract is not None:
        display["description"] = [abstract]
    if oa:
        display["oa"] = ["free_for_read"]
    addata: dict = {}
    if doi is not None:
        addata["doi"] = [doi]
    links: dict = {}
    if pdf_url is not None:
        links["linktopdf"] = [f"$$U{pdf_url}$$EPDF$$Gsource$$Hfree_for_read$$Pomit_proxy_true"]
    return {"pnx": {"display": display, "addata": addata, "links": links}}


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
    monkeypatch.setenv("PRIMO_BASE_URL", "https://example.primo.exlibrisgroup.com")
    # vid/inst deliberately left unset.
    assert primo._endpoint() is None
    assert primo.is_enabled() is False


# --- Endpoint resolution: env vars take precedence over config ---


def test_endpoint_resolves_from_env(monkeypatch):
    monkeypatch.setenv("PRIMO_BASE_URL", "https://example.primo.exlibrisgroup.com/")
    monkeypatch.setenv("PRIMO_VID", "01EX_INST:01EX")
    monkeypatch.setenv("PRIMO_INST", "01EX_INST")
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
    monkeypatch.setenv("PRIMO_BASE_URL", "https://env-configured.example.com")
    monkeypatch.setenv("PRIMO_VID", "ENV_VID")
    monkeypatch.setenv("PRIMO_INST", "ENV_INST")
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
    monkeypatch.setenv("PRIMO_BASE_URL", "https://example.primo.exlibrisgroup.com")
    monkeypatch.setenv("PRIMO_VID", "01EX_INST:01EX")
    monkeypatch.setenv("PRIMO_INST", "01EX_INST")


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
    assert record == {
        "title": "Full Record Title",
        "abstract": "The abstract.",
        "doi": "10.5555/x",
        "oa_pdf_url": None,
    }


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


# --- OA PDF URL extraction ---
#
# Primo exposes links.linktopdf only for records it marks free_for_read
# in display.oa (verified against Argonne's live Primo instance: every
# paywalled IEEE/Elsevier/ACM record returned only linktorsrc, an
# abstract-page link, never linktopdf). These tests exercise the
# extraction + OA gate in isolation from the endpoint/network plumbing
# already covered above.


def test_extract_pdf_url_present_and_oa():
    pnx = _doc("A Paper", oa=True, pdf_url="https://www.osti.gov/servlets/purl/754505")["pnx"]
    assert primo._extract_pdf_url(pnx) == "https://www.osti.gov/servlets/purl/754505"


def test_extract_pdf_url_absent_without_oa_flag():
    """A linktopdf entry present but the record NOT marked free_for_read
    -- should never happen in practice (Primo only emits linktopdf for OA
    records) but the gate must hold even if it did."""
    pnx = _doc("A Paper", oa=False, pdf_url="https://example.com/paper.pdf")["pnx"]
    assert primo._extract_pdf_url(pnx) is None


def test_extract_pdf_url_none_when_no_linktopdf():
    pnx = _doc("A Paper", oa=True)["pnx"]  # oa but no linktopdf, e.g. paywalled record
    assert primo._extract_pdf_url(pnx) is None


def test_get_oa_pdf_url_by_doi_hit(monkeypatch):
    _configure(monkeypatch)
    resp = _mock_response(
        200,
        {"docs": [_doc("PVFS Paper", doi="10.1234/oa", oa=True, pdf_url="https://osti.gov/servlets/purl/1")]},
    )
    with patch("wake.sources.primo.requests.get", return_value=resp):
        url = primo.get_oa_pdf_url_by_doi("10.1234/oa")
    assert url == "https://osti.gov/servlets/purl/1"


def test_get_oa_pdf_url_by_doi_paywalled_record_returns_none(monkeypatch):
    _configure(monkeypatch)
    # Mirrors what a real paywalled IEEE/Elsevier record looks like: no
    # oa flag, no linktopdf, only ever a linktorsrc (not modeled here
    # since _extract_pdf_url never reads it).
    resp = _mock_response(200, {"docs": [_doc("Closed-Access Paper", doi="10.1234/closed")]})
    with patch("wake.sources.primo.requests.get", return_value=resp):
        url = primo.get_oa_pdf_url_by_doi("10.1234/closed")
    assert url is None


def test_get_oa_pdf_url_by_title_accepts_close_match(monkeypatch):
    _configure(monkeypatch)
    resp = _mock_response(
        200,
        {
            "docs": [
                _doc(
                    "PVFS: A Parallel File System for Linux Clusters",
                    oa=True,
                    pdf_url="https://www.osti.gov/servlets/purl/754505",
                )
            ]
        },
    )
    with patch("wake.sources.primo.requests.get", return_value=resp):
        url = primo.get_oa_pdf_url_by_title("PVFS: A Parallel File System for Linux Clusters")
    assert url == "https://www.osti.gov/servlets/purl/754505"


def test_get_oa_pdf_url_by_title_rejects_dissimilar_top_hit(monkeypatch):
    _configure(monkeypatch)
    resp = _mock_response(
        200,
        {"docs": [_doc("An Unrelated Paper", oa=True, pdf_url="https://example.com/wrong.pdf")]},
    )
    with patch("wake.sources.primo.requests.get", return_value=resp):
        url = primo.get_oa_pdf_url_by_title("Something Completely Different Entirely")
    assert url is None


def test_get_oa_pdf_url_by_doi_noop_without_endpoint():
    with patch("wake.sources.primo.requests.get") as mock_get:
        assert primo.get_oa_pdf_url_by_doi("10.1234/x") is None
    mock_get.assert_not_called()


def test_get_record_by_title_single_query_for_multiple_fields(monkeypatch):
    """A caller wanting doi + abstract + oa_pdf_url from one title lookup
    should be able to do it in a single Primo round-trip via
    get_record_by_title, rather than three (one per get_*_by_title
    wrapper)."""
    _configure(monkeypatch)
    resp = _mock_response(
        200,
        {
            "docs": [
                _doc(
                    "Combined Fields Paper",
                    abstract="An abstract.",
                    doi="10.1234/combined",
                    oa=True,
                    pdf_url="https://example.com/combined.pdf",
                )
            ]
        },
    )
    with patch("wake.sources.primo.requests.get", return_value=resp) as mock_get:
        record = primo.get_record_by_title("Combined Fields Paper")
    mock_get.assert_called_once()
    assert record == {
        "title": "Combined Fields Paper",
        "abstract": "An abstract.",
        "doi": "10.1234/combined",
        "oa_pdf_url": "https://example.com/combined.pdf",
    }


@pytest.mark.network
def test_primo_live_hit_requires_real_endpoint_env():
    """Only runs meaningfully with PRIMO_BASE_URL/_VID/_INST set in
    the live environment; otherwise this is just is_enabled() == False
    and the assertion is trivially satisfied (no network call made)."""
    if not primo.is_enabled():
        pytest.skip("Primo not configured in this environment")
    abstract = primo.get_abstract_by_doi("10.1016/j.jpdc.2010.08.004")
    assert abstract is None or len(abstract) > 20
