# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.pdf_fetch — the PDF-acquisition orchestrator, offline."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from wake import pdf_fetch


_FAKE_PDF_BYTES = b"%PDF-1.4\n" + b"x" * 3000  # valid-looking, above min_valid_pdf_bytes
_FAKE_HTML_BYTES = b"<html><body>Access Denied</body></html>" + b"x" * 3000


def _mock_response(status_code=200, content=_FAKE_PDF_BYTES):
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    return resp


def test_pdf_path_structure(tmp_path):
    p = pdf_fetch.pdf_path("W123", "W456", base=tmp_path)
    assert p.name == "W456.pdf"
    assert p.parent.name == "pdfs"


def test_fetch_pdf_returns_cached_without_network(tmp_path):
    seed_id, citing_id = "W123", "W456"
    dest = pdf_fetch.pdf_path(seed_id, citing_id, base=tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(_FAKE_PDF_BYTES)

    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi") as mock_osti:
        result = pdf_fetch.fetch_pdf(
            seed_id, citing_id, doi="10.1016/fake", base=tmp_path, verbose=False,
        )
    mock_osti.assert_not_called()
    assert result["ok"] is True
    assert result["source"] == "cache"


def test_fetch_pdf_force_bypasses_cache(tmp_path):
    seed_id, citing_id = "W123", "W456"
    dest = pdf_fetch.pdf_path(seed_id, citing_id, base=tmp_path)
    dest.parent.mkdir(parents=True)
    dest.write_bytes(b"old content")

    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value="https://osti.example/paper.pdf"), \
         patch("wake.pdf_fetch.requests.get", return_value=_mock_response()):
        result = pdf_fetch.fetch_pdf(
            seed_id, citing_id, doi="10.1016/fake", base=tmp_path, force=True,
            verbose=False,
        )
    assert result["ok"] is True
    assert result["source"] == "osti"
    assert dest.read_bytes() == _FAKE_PDF_BYTES


def test_fetch_pdf_tries_sources_in_order_first_hit_wins(tmp_path):
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value=None) as mock_osti, \
         patch("wake.pdf_fetch.semanticscholar.get_open_access_pdf_url_by_doi", return_value="https://s2.example/paper.pdf") as mock_s2, \
         patch("wake.pdf_fetch.unpaywall.get_oa_pdf_url_by_doi") as mock_unpaywall, \
         patch("wake.pdf_fetch.requests.get", return_value=_mock_response()):
        result = pdf_fetch.fetch_pdf(
            "W123", "W456", doi="10.1016/fake", base=tmp_path, verbose=False,
        )
    mock_osti.assert_called_once()
    mock_s2.assert_called_once()
    mock_unpaywall.assert_not_called()  # never reached — s2 already succeeded
    assert result["ok"] is True
    assert result["source"] == "semanticscholar"


def test_fetch_pdf_falls_through_when_url_yields_non_pdf(tmp_path):
    """A source returning a URL that doesn't actually serve a PDF (e.g. a
    paywall HTML page) should fall through to the next source, not stop."""
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value="https://osti.example/paywalled.pdf"), \
         patch("wake.pdf_fetch.semanticscholar.get_open_access_pdf_url_by_doi", return_value="https://s2.example/real.pdf"), \
         patch("wake.pdf_fetch.requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_response(content=_FAKE_HTML_BYTES),  # osti: not a real PDF
            _mock_response(content=_FAKE_PDF_BYTES),   # semanticscholar: real PDF
        ]
        result = pdf_fetch.fetch_pdf(
            "W123", "W456", doi="10.1016/fake", base=tmp_path, verbose=False,
        )
    assert result["ok"] is True
    assert result["source"] == "semanticscholar"


def test_fetch_pdf_source_exception_falls_through(tmp_path):
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", side_effect=RuntimeError("boom")), \
         patch("wake.pdf_fetch.semanticscholar.get_open_access_pdf_url_by_doi", return_value="https://s2.example/paper.pdf"), \
         patch("wake.pdf_fetch.requests.get", return_value=_mock_response()):
        result = pdf_fetch.fetch_pdf(
            "W123", "W456", doi="10.1016/fake", base=tmp_path, verbose=False,
        )
    assert result["ok"] is True
    assert result["source"] == "semanticscholar"


def test_fetch_pdf_all_sources_fail_returns_fallback_links(tmp_path):
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.semanticscholar.get_open_access_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.unpaywall.get_oa_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.arxiv_fetch.find_pdf_url_by_title", return_value=None), \
         patch("wake.pdf_fetch.core.is_enabled", return_value=False):
        result = pdf_fetch.fetch_pdf(
            "W123", "W456", doi="10.1016/fake", title="Some Paper Title",
            base=tmp_path, verbose=False,
        )
    assert result["ok"] is False
    assert "osti" in result["tried"]
    assert "semanticscholar" in result["tried"]
    assert "unpaywall" in result["tried"]
    assert "arxiv" in result["tried"]
    assert "core" not in result["tried"]  # disabled, never attempted
    assert "google_scholar" in result["fallback_links"]
    assert "unpaywall" in result["fallback_links"]


def test_fetch_pdf_skips_arxiv_without_title(tmp_path):
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.semanticscholar.get_open_access_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.unpaywall.get_oa_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.arxiv_fetch.find_pdf_url_by_title") as mock_arxiv, \
         patch("wake.pdf_fetch.core.is_enabled", return_value=False):
        result = pdf_fetch.fetch_pdf(
            "W123", "W456", doi="10.1016/fake", title=None, base=tmp_path, verbose=False,
        )
    mock_arxiv.assert_not_called()
    assert "arxiv" not in result["tried"]


def test_fetch_pdf_skips_core_when_disabled(tmp_path):
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.semanticscholar.get_open_access_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.unpaywall.get_oa_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.arxiv_fetch.find_pdf_url_by_title", return_value=None), \
         patch("wake.pdf_fetch.core.is_enabled", return_value=False), \
         patch("wake.pdf_fetch.core.get_oa_pdf_url_by_doi") as mock_core:
        pdf_fetch.fetch_pdf(
            "W123", "W456", doi="10.1016/fake", title="Some Title", base=tmp_path, verbose=False,
        )
    mock_core.assert_not_called()


def test_fetch_pdf_uses_core_when_enabled(tmp_path):
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.semanticscholar.get_open_access_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.unpaywall.get_oa_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.arxiv_fetch.find_pdf_url_by_title", return_value=None), \
         patch("wake.pdf_fetch.core.is_enabled", return_value=True), \
         patch("wake.pdf_fetch.core.get_oa_pdf_url_by_doi", return_value="https://core.example/paper.pdf"), \
         patch("wake.pdf_fetch.requests.get", return_value=_mock_response()):
        result = pdf_fetch.fetch_pdf(
            "W123", "W456", doi="10.1016/fake", title="Some Title", base=tmp_path, verbose=False,
        )
    assert result["ok"] is True
    assert result["source"] == "core"


def test_fetch_pdf_tries_springer_between_unpaywall_and_arxiv(tmp_path):
    """springer.get_fulltext_pdf_url_by_doi makes no network call (pure URL
    construction), so it should be attempted for every Springer DOI even
    though it sits after unpaywall/before arxiv in the default chain."""
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.semanticscholar.get_open_access_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.unpaywall.get_oa_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.arxiv_fetch.find_pdf_url_by_title") as mock_arxiv, \
         patch("wake.pdf_fetch.core.is_enabled", return_value=False), \
         patch("wake.pdf_fetch.requests.get", return_value=_mock_response()):
        result = pdf_fetch.fetch_pdf(
            "W123", "W456", doi="10.1007/978-3-540-92859-1_9", title="Some Title",
            base=tmp_path, verbose=False,
        )
    mock_arxiv.assert_not_called()  # springer already succeeded
    assert result["ok"] is True
    assert result["source"] == "springer"
    assert "springer" in result["url"]


def test_fetch_pdf_springer_noop_for_non_springer_doi(tmp_path):
    """A non-Springer DOI should fall through springer with no network call
    (get_fulltext_pdf_url_by_doi returns None immediately) and proceed to
    the next source in the chain."""
    with patch("wake.pdf_fetch.osti.get_fulltext_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.semanticscholar.get_open_access_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.unpaywall.get_oa_pdf_url_by_doi", return_value=None), \
         patch("wake.pdf_fetch.arxiv_fetch.find_pdf_url_by_title", return_value="https://arxiv.org/pdf/1234.5678"), \
         patch("wake.pdf_fetch.core.is_enabled", return_value=False), \
         patch("wake.pdf_fetch.requests.get", return_value=_mock_response()):
        result = pdf_fetch.fetch_pdf(
            "W123", "W456", doi="10.1109/icpp.2009.68", title="Some Title",
            base=tmp_path, verbose=False,
        )
    # springer.get_fulltext_pdf_url_by_doi is real (not mocked) here — a
    # non-Springer DOI returns None immediately, so the chain correctly
    # falls through to arxiv, which succeeds.
    assert result["ok"] is True
    assert result["source"] == "arxiv"


def test_fallback_links_includes_google_scholar_when_title_present():
    links = pdf_fetch.fallback_links(doi=None, title="A Paper Title")
    assert "google_scholar" in links
    assert "scholar.google.com" in links["google_scholar"]


def test_fallback_links_no_title_no_google_scholar():
    links = pdf_fetch.fallback_links(doi="10.1016/fake", title=None)
    assert "google_scholar" not in links
    assert "unpaywall" in links


def test_fallback_links_no_doi_no_url_scholar_only():
    links = pdf_fetch.fallback_links(doi=None, title="Some Title")
    assert links == {"google_scholar": links["google_scholar"]}


def test_download_rejects_non_pdf_content(tmp_path):
    dest = tmp_path / "out.pdf"
    with patch("wake.pdf_fetch.requests.get", return_value=_mock_response(content=_FAKE_HTML_BYTES)):
        ok = pdf_fetch._download("https://example.com/fake.pdf", dest, timeout=10, min_bytes=2048)
    assert ok is False
    assert not dest.exists()


def test_download_rejects_too_small_file(tmp_path):
    dest = tmp_path / "out.pdf"
    tiny_pdf = b"%PDF-1.4\n"  # valid header but far too small
    with patch("wake.pdf_fetch.requests.get", return_value=_mock_response(content=tiny_pdf)):
        ok = pdf_fetch._download("https://example.com/fake.pdf", dest, timeout=10, min_bytes=2048)
    assert ok is False
    assert not dest.exists()


def test_download_accepts_valid_pdf(tmp_path):
    dest = tmp_path / "out.pdf"
    with patch("wake.pdf_fetch.requests.get", return_value=_mock_response(content=_FAKE_PDF_BYTES)):
        ok = pdf_fetch._download("https://example.com/real.pdf", dest, timeout=10, min_bytes=2048)
    assert ok is True
    assert dest.read_bytes() == _FAKE_PDF_BYTES


def test_download_rejects_non_200_status(tmp_path):
    dest = tmp_path / "out.pdf"
    with patch("wake.pdf_fetch.requests.get", return_value=_mock_response(status_code=403)):
        ok = pdf_fetch._download("https://example.com/forbidden.pdf", dest, timeout=10, min_bytes=2048)
    assert ok is False
    assert not dest.exists()


def test_download_handles_request_exception(tmp_path):
    import requests
    dest = tmp_path / "out.pdf"
    with patch("wake.pdf_fetch.requests.get", side_effect=requests.RequestException("timeout")):
        ok = pdf_fetch._download("https://example.com/timeout.pdf", dest, timeout=10, min_bytes=2048)
    assert ok is False
    assert not dest.exists()
