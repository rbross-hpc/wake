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

_REQUIRED_ENVS = {
    "OPENAI_API_KEY": "LLM API key (set in .env or environment)",
    "OPENAI_BASE_URL": "OpenAI-compatible API endpoint URL",
}

_RECOMMENDED_ENVS = {
    "OPENALEX_MAILTO": "Your email for OpenAlex polite pool (faster, more reliable)",
}


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
    for var, desc in {**_REQUIRED_ENVS, **_RECOMMENDED_ENVS}.items():
        val = os.environ.get(var, "")
        display = "<set>" if val and "KEY" in var else (val or "NOT SET")
        lines.append(f"  {var}: {display}  ({desc})")

    return "\n".join(lines)


def validate() -> list[str]:
    errors: list[str] = []
    for env, desc in _REQUIRED_ENVS.items():
        if not os.environ.get(env):
            errors.append(f"Missing required env var {env}: {desc}")
    return errors


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
        "  describe: \"Claude Sonnet 4.7\"\n"
        "  classify: \"Claude Sonnet 4.7\"\n\n"
        "openalex:\n"
        "  rate_limit_s: 1.0\n"
    )
    lc.write_text(starter, encoding="utf-8")
    return lc, True
