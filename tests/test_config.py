# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.config — env-var tiers, validate/show, init_local."""
from __future__ import annotations

import pytest
from wake import config


ALL_REQUIRED = list(config._REQUIRED_ENVS.keys())
ALL_RECOMMENDED = list(config._RECOMMENDED_ENVS.keys())
ALL_OPTIONAL = list(config._OPTIONAL_ENVS.keys())
ALL_ENVS = ALL_REQUIRED + ALL_RECOMMENDED + ALL_OPTIONAL


@pytest.fixture(autouse=True)
def _clear_all_env(monkeypatch):
    """Every test starts with a clean env-var slate for all registered vars,
    then tests opt in to setting whichever ones they need."""
    for var in ALL_ENVS:
        monkeypatch.delenv(var, raising=False)
    yield


def test_env_status_shape_has_three_tiers():
    status = config.env_status()
    assert set(status.keys()) == {"required", "recommended", "optional"}


def test_env_status_all_unset(monkeypatch):
    status = config.env_status()
    for tier in ("required", "recommended", "optional"):
        for var, info in status[tier].items():
            assert info["set"] is False
            assert info["value"] is None


def test_env_status_reports_set_non_sensitive_value(monkeypatch):
    monkeypatch.setenv("OPENALEX_MAILTO", "test@example.com")
    status = config.env_status()
    info = status["recommended"]["OPENALEX_MAILTO"]
    assert info["set"] is True
    assert info["value"] == "test@example.com"


def test_env_status_never_leaks_sensitive_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value")
    monkeypatch.setenv("SEMANTICSCHOLAR_API_KEY", "s2-secret")
    monkeypatch.setenv("CORE_API_KEY", "core-secret")
    status = config.env_status()
    assert status["required"]["OPENAI_API_KEY"]["set"] is True
    assert status["required"]["OPENAI_API_KEY"]["value"] is None
    assert status["optional"]["SEMANTICSCHOLAR_API_KEY"]["value"] is None
    assert status["optional"]["CORE_API_KEY"]["value"] is None


def test_env_status_includes_previously_undocumented_optional_vars():
    """Regression guard: SEMANTICSCHOLAR_API_KEY, CORE_API_KEY, and
    WAKE_WORK_DIR are read by the code (semanticscholar.py, core.py,
    seed.py) but were missing from config.py's registry before this fix."""
    status = config.env_status()
    assert "SEMANTICSCHOLAR_API_KEY" in status["optional"]
    assert "CORE_API_KEY" in status["optional"]
    assert "WAKE_WORK_DIR" in status["optional"]


def test_validate_passes_with_required_set(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    assert config.validate() == []


def test_validate_fails_without_required():
    errors = config.validate()
    assert len(errors) == 2
    assert any("OPENAI_API_KEY" in e for e in errors)
    assert any("OPENAI_BASE_URL" in e for e in errors)


def test_validate_ignores_recommended_and_optional_gaps(monkeypatch):
    """Missing recommended/optional vars must never cause validate() to fail
    -- only required vars are blocking."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    # OPENALEX_MAILTO, SEMANTICSCHOLAR_API_KEY, CORE_API_KEY, WAKE_WORK_DIR
    # are all deliberately left unset by the autouse fixture.
    assert config.validate() == []


def test_validate_report_shape_ok(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    report = config.validate_report()
    assert report["ok"] is True
    assert report["errors"] == []
    assert "env" in report
    assert set(report["env"].keys()) == {"required", "recommended", "optional"}


def test_validate_report_shape_not_ok():
    report = config.validate_report()
    assert report["ok"] is False
    assert len(report["errors"]) == 2


def test_show_includes_tiered_environment_section(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    text = config.show()
    assert "Required:" in text
    assert "Recommended:" in text
    assert "Optional:" in text
    assert "SEMANTICSCHOLAR_API_KEY" in text
    assert "CORE_API_KEY" in text
    assert "WAKE_WORK_DIR" in text


def test_show_masks_sensitive_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    text = config.show()
    assert "sk-super-secret-value" not in text
    assert "<set>" in text


def test_show_reflects_correct_model_defaults():
    """Regression guard: config.yaml's packaged models must all say
    Claude Sonnet 4.6, not the stale 4.7."""
    text = config.show()
    assert "Claude Sonnet 4.7" not in text
    assert "Claude Sonnet 4.6" in text


def test_init_local_writes_consistent_model_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path, created = config.init_local()
    assert created is True
    content = path.read_text()
    assert "Claude Sonnet 4.7" not in content
    assert "Claude Sonnet 4.6" in content


def test_init_local_does_not_overwrite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path, created_first = config.init_local()
    original_content = path.read_text()
    path.write_text("# modified by user\n")
    path2, created_second = config.init_local()
    assert created_first is True
    assert created_second is False
    assert path2.read_text() == "# modified by user\n"
