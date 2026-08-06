# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for `wake skill export`/`wake skill show` (see wake-doc-bug.md).

opencode only registers a skill if its `SKILL.md` has a YAML frontmatter
block with at least a string `name` field (opencode's `isSkillFrontmatter`,
packages/opencode/src/skill/index.ts). A `SKILL.md` without that block is
silently dropped -- no error, no warning -- so the agent proceeds without
wake's workflow guidance. These tests assert the bundled SKILL.md (and
anything `wake skill export` copies) satisfies that contract, and that
`wake skill export` still requires an explicit destination path (no
default path baked into the CLI -- see wake-doc-bug.md's "Fix" section,
which we deliberately did not adopt in favor of fixing the README
instead).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import patch

import yaml

from wake.cli.main import main

_SKILL_MD = (
    Path(__file__).parent.parent
    / "wake"
    / "skills"
    / "impact-analysis"
    / "SKILL.md"
)

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _parse_frontmatter(text: str) -> dict:
    m = _FRONTMATTER_RE.match(text)
    assert m, "SKILL.md must open with a '---'-delimited YAML frontmatter block"
    data = yaml.safe_load(m.group(1))
    assert isinstance(data, dict), f"frontmatter did not parse as a mapping: {data!r}"
    return data


def _run_cli(argv, tmp_path, capsys):
    with patch.object(sys, "argv", ["wake", *argv]):
        try:
            main()
            code = 0
        except SystemExit as exc:
            code = exc.code or 0
    return code, capsys.readouterr()


def test_bundled_skill_md_has_valid_frontmatter():
    text = _SKILL_MD.read_text(encoding="utf-8")
    data = _parse_frontmatter(text)

    assert data.get("name") == "wake"
    description = data.get("description")
    assert isinstance(description, str) and description.strip()


def test_skill_export_preserves_frontmatter(tmp_path, capsys):
    dest = tmp_path / ".opencode" / "skills" / "wake"
    code, _ = _run_cli(["skill", "export", str(dest)], tmp_path, capsys)
    assert code == 0

    exported = dest / "SKILL.md"
    assert exported.exists()
    data = _parse_frontmatter(exported.read_text(encoding="utf-8"))
    assert data.get("name") == "wake"
    assert isinstance(data.get("description"), str) and data["description"].strip()


def test_skill_export_requires_path_argument(tmp_path, capsys):
    code, captured = _run_cli(["skill", "export"], tmp_path, capsys)
    assert code != 0
    assert "PATH" in captured.err or "path" in captured.err.lower()
