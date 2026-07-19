# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
# Adapted from pub-analysis/puba/config.py
"""Configuration loading, override resolution, show, and validate."""
from __future__ import annotations

import os
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

_PACKAGED_CONFIG = files("wake") / "config.yaml"
_LOCAL_CONFIG_NAME = "wake.config.yaml"

# Three tiers, in descending order of urgency. This registry backs both
# `wake config show`/`validate` and the "Setup Check" step an agent runs
# before starting an analysis (see skills/impact-analysis/SKILL.md).
#
# required    — nothing works without these; validate() fails without them.
# recommended — things work, but degrade (slower/less reliable); worth
#               asking the human about once, early.
# optional    — pure feature-gates (an extra PDF source, a higher rate
#               limit, a cache-location preference); never worth asking
#               about unless the specific feature is about to matter.
_REQUIRED_ENVS = {
    "OPENAI_API_KEY": "LLM API key (set in .env or environment)",
    "OPENAI_BASE_URL": "OpenAI-compatible API endpoint URL",
}

_RECOMMENDED_ENVS = {
    "OPENALEX_MAILTO": "Your email for OpenAlex/Unpaywall/OSTI polite pool (faster, more reliable)",
}

_OPTIONAL_ENVS = {
    "SEMANTICSCHOLAR_API_KEY": "Raises Semantic Scholar's unauthenticated rate limit (~100 req/5min without one)",
    "CORE_API_KEY": "Enables CORE.ac.uk as a `wake fetch-pdf` source (free key at core.ac.uk/services/api)",
    "WAKE_WORK_DIR": "Default root for wake-out/ cache (else cwd, or per-call --work-dir)",
}

_ALL_ENV_TIERS: dict[str, dict[str, str]] = {
    "required": _REQUIRED_ENVS,
    "recommended": _RECOMMENDED_ENVS,
    "optional": _OPTIONAL_ENVS,
}

_SENSITIVE_ENV_SUBSTRINGS = ("KEY",)


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _local_config() -> Path:
    return Path.cwd() / _LOCAL_CONFIG_NAME


@lru_cache(maxsize=1)
def load() -> dict[str, Any]:
    if not _PACKAGED_CONFIG.exists():
        raise FileNotFoundError(f"Packaged config.yaml not found at {_PACKAGED_CONFIG}")
    with open(_PACKAGED_CONFIG, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    lc = _local_config()
    if lc.exists():
        with open(lc, encoding="utf-8") as f:
            local = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, local)

    return cfg


def reload() -> dict[str, Any]:
    load.cache_clear()
    return load()


def models() -> dict[str, str]:
    return load()["models"]


def openalex_cfg() -> dict[str, Any]:
    return load()["openalex"]


def classify_cfg() -> dict[str, Any]:
    return load()["classify"]


def describe_cfg() -> dict[str, Any]:
    return load()["describe"]


def report_cfg() -> dict[str, Any]:
    return load()["report"]


def gaps_cfg() -> dict[str, Any]:
    return load().get("gaps", {})


def pdf_extract_cfg() -> dict[str, Any]:
    return load().get("pdf_extract", {})


def pdf_fetch_cfg() -> dict[str, Any]:
    return load().get("pdf_fetch", {})


def evidence_cfg() -> dict[str, Any]:
    return load().get("evidence", {})


def _is_sensitive(var: str) -> bool:
    return any(s in var for s in _SENSITIVE_ENV_SUBSTRINGS)


def env_status() -> dict[str, dict[str, dict[str, Any]]]:
    """Return the set/unset status of every registered env var, grouped by
    tier. Values for sensitive vars (API keys) are never included — only
    whether they're set. Shape:

        {"required": {"OPENAI_API_KEY": {"set": true, "value": None, "description": "..."}}, ...}
    """
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for tier, envs in _ALL_ENV_TIERS.items():
        result[tier] = {}
        for var, desc in envs.items():
            val = os.environ.get(var, "")
            result[tier][var] = {
                "set": bool(val),
                "value": None if (_is_sensitive(var) or not val) else val,
                "description": desc,
            }
    return result


def show() -> str:
    cfg = load()
    lc = _local_config()
    lines = ["Resolved wake configuration:\n"]
    lines.append(f"  Packaged config : {_PACKAGED_CONFIG}")
    if lc.exists():
        lines.append(f"  Local override  : {lc}")
    else:
        lines.append(f"  Local override  : (none — {lc} not found)")
    lines.append("")

    def _render(d: dict, indent: int = 2) -> None:
        pad = " " * indent
        for k, v in d.items():
            if k.startswith("_"):
                continue
            if isinstance(v, dict):
                lines.append(f"{pad}{k}:")
                _render(v, indent + 2)
            elif isinstance(v, list):
                lines.append(f"{pad}{k}: [{', '.join(str(i) for i in v[:5])}{'...' if len(v) > 5 else ''}]")
            else:
                lines.append(f"{pad}{k}: {v}")

    _render(cfg)

    lines.append("\nEnvironment:")
    for tier_label, tier_key in (("Required", "required"), ("Recommended", "recommended"), ("Optional", "optional")):
        lines.append(f"  {tier_label}:")
        for var, info in env_status()[tier_key].items():
            display = "<set>" if info["set"] and _is_sensitive(var) else (info["value"] or ("<set>" if info["set"] else "NOT SET"))
            lines.append(f"    {var}: {display}  ({info['description']})")

    return "\n".join(lines)


def validate() -> list[str]:
    """Return a list of blocking errors (missing required env vars only).
    Recommended/optional gaps are never validation failures — surface those
    via env_status() instead."""
    errors: list[str] = []
    for env, desc in _REQUIRED_ENVS.items():
        if not os.environ.get(env):
            errors.append(f"Missing required env var {env}: {desc}")
    return errors


def validate_report() -> dict[str, Any]:
    """Structured validation result for --json consumers: pass/fail plus
    the full env_status() breakdown, so an agent can decide what to ask
    the human about without re-implementing the tier logic."""
    errors = validate()
    return {
        "ok": not errors,
        "errors": errors,
        "env": env_status(),
    }


def init_local() -> tuple[Path, bool]:
    """Write a starter wake.config.yaml in the cwd. Returns (path, created)."""
    lc = _local_config()
    if lc.exists():
        return lc, False
    starter = (
        "# wake local configuration override\n"
        "# Values here override the packaged defaults.\n"
        "# See: wake config show\n\n"
        "models:\n"
        "  describe: \"Claude Sonnet 4.6\"\n"
        "  classify: \"Claude Sonnet 4.6\"\n\n"
        "openalex:\n"
        "  rate_limit_s: 1.0\n"
    )
    lc.write_text(starter, encoding="utf-8")
    return lc, True
