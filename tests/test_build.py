# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for wake.build.rebuild_seed() -- the centralized rebuild entry
point (see wake/build.py's module docstring for the gap this closes:
before this module existed, resyncing a hand-edited/corrupted
wake-out/<seed>/ packet required knowing to run 4+ separate bulk
commands in a specific undocumented order, and two derived files
(evidence/index.md, evidence/themes/index.md) had no standalone rebuild
entry point at all).

Reuses tests/test_wiki_invariants.py's `_build_full_wiki` fixture (a
real, complete packet: dossiers, a confirmed theme, a stitched
narrative, a baked impact brief) rather than reimplementing the same
multi-stage setup here.
"""
from __future__ import annotations

from wake.build import rebuild_seed

from .test_wiki_invariants import _NO_FRONTMATTER_FILES, PARALLEL_NETCDF_WORK, _build_full_wiki
from .wiki_invariants import (
    assert_all_relative_md_links_exist,
    assert_frontmatter_valid,
)


def test_rebuild_seed_on_empty_packet_is_a_safe_no_op(tmp_path):
    """A seed with nothing beyond seed.json yet -- every step should be
    skipped/False except the always-run wiki orientation refresh."""
    result = rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    assert result["ok"] is True
    by_step = {s["step"]: s for s in result["steps"]}
    assert by_step["dossiers"]["rebuilt"] == []
    assert by_step["evidence_index"]["rebuilt"] is False
    assert by_step["themes"]["rebuilt"] == []
    assert by_step["themes_index"]["rebuilt"] is False
    assert by_step["outline"]["rebuilt"] is False
    assert by_step["sections"]["rebuilt"] == []
    assert by_step["narrative"]["rebuilt"] is False
    assert by_step["impact"]["rebuilt"] is False
    assert by_step["wiki_orientation"]["rebuilt"] is True

    wiki_root = tmp_path / "wake-out" / PARALLEL_NETCDF_WORK["openalex_id"]
    assert (wiki_root / "README.md").exists()
    assert (wiki_root / "AGENTS.md").exists()


def test_rebuild_seed_touches_every_populated_artifact_type(tmp_path):
    fixture = _build_full_wiki(tmp_path)
    fixture["seed_id"]

    result = rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    by_step = {s["step"]: s for s in result["steps"]}
    assert set(by_step["dossiers"]["rebuilt"]) == {
        fixture["w0"]["openalex_id"], fixture["w1"]["openalex_id"], fixture["w3"]["openalex_id"],
    }
    assert by_step["evidence_index"]["rebuilt"] is True
    assert by_step["themes"]["rebuilt"] == ["t1"]
    assert by_step["themes_index"]["rebuilt"] is True
    assert by_step["outline"]["rebuilt"] is True
    assert by_step["sections"]["rebuilt"] == ["s1"]
    assert by_step["narrative"]["rebuilt"] is True
    # _build_full_wiki calls report.bake_and_save() directly without ever
    # calling citing.save_citing() (no citing.json on disk) -- rebuild_seed
    # correctly mirrors `wake bake`'s own precondition (it needs citing.json
    # to know the full candidate set, not just classified.json) and skips
    # the impact step rather than fabricating a citing set.
    assert by_step["impact"]["rebuilt"] is False
    assert by_step["wiki_orientation"]["rebuilt"] is True


def test_rebuild_seed_restores_a_deleted_dossier_md(tmp_path):
    """The core promise: hand-delete a derived .md, rebuild_seed puts it
    back, purely from the still-present .json sidecar -- no LLM call."""
    fixture = _build_full_wiki(tmp_path)
    fixture["seed_id"]
    citing_id = fixture["w0"]["openalex_id"]

    dossier_md = fixture["wiki_root"] / "evidence" / f"{citing_id}.md"
    assert dossier_md.exists()
    dossier_md.unlink()
    assert not dossier_md.exists()

    rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    assert dossier_md.exists()
    assert citing_id in dossier_md.read_text(encoding="utf-8")


def test_rebuild_seed_restores_evidence_index_after_it_is_deleted(tmp_path):
    """evidence/index.md has no standalone CLI rebuild verb today (see
    build.py's docstring) -- rebuild_seed is the only way to regenerate
    it without re-running `wake evidence` on every citing work again."""
    fixture = _build_full_wiki(tmp_path)
    index_md = fixture["wiki_root"] / "evidence" / "index.md"
    assert index_md.exists()
    index_md.unlink()

    rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    assert index_md.exists()


def test_rebuild_seed_restores_themes_index_after_it_is_deleted(tmp_path):
    """Same gap as evidence/index.md -- evidence/themes/index.md also
    has no standalone rebuild verb before this module."""
    fixture = _build_full_wiki(tmp_path)
    themes_index = fixture["wiki_root"] / "evidence" / "themes" / "index.md"
    assert themes_index.exists()
    themes_index.unlink()

    rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    assert themes_index.exists()


def test_rebuild_seed_restores_outline_status_after_manual_json_edit(tmp_path):
    """wake narrative section rerender-all doesn't refresh outline.md's
    live per-component status column (see build.py's docstring) --
    rebuild_seed's separate outline step closes that gap."""
    import json
    fixture = _build_full_wiki(tmp_path)
    seed_id = fixture["seed_id"]

    from wake.narrative import section_json_path
    section_path = section_json_path(seed_id, "s1", tmp_path)
    section = json.loads(section_path.read_text(encoding="utf-8"))
    section["section_status"] = "draft"
    section_path.write_text(json.dumps(section), encoding="utf-8")

    outline_md = fixture["wiki_root"] / "narrative" / "outline.md"
    assert "Confirmed" in outline_md.read_text(encoding="utf-8") or "confirmed" in outline_md.read_text(encoding="utf-8")

    rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    # Re-render must reflect the (hand-edited) draft status, not the
    # stale "confirmed" text baked into the now-outdated outline.md.
    refreshed_text = outline_md.read_text(encoding="utf-8")
    assert "draft" in refreshed_text.lower()


def test_rebuild_seed_rebuilds_impact_when_citing_json_present(tmp_path):
    """The impact step requires citing.json (same precondition wake bake
    itself enforces) -- confirm it actually fires once that's present,
    complementing the "correctly skips it when absent" assertion above."""
    import json

    from wake.io import atomic_write_json

    fixture = _build_full_wiki(tmp_path)
    seed_id = fixture["seed_id"]

    citing_path = tmp_path / "wake-out" / seed_id / "citing.json"
    atomic_write_json(citing_path, {
        "seed_openalex_id": seed_id,
        "fetched_at": "2026-01-01T00:00:00",
        "min_year": None,
        "count": 1,
        "works": [fixture["w0"]],
    })

    result = rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    by_step = {s["step"]: s for s in result["steps"]}
    assert by_step["impact"]["rebuilt"] is True
    impact_json = json.loads((tmp_path / "wake-out" / seed_id / "impact.json").read_text(encoding="utf-8"))
    assert impact_json  # non-empty -- a real rebake happened


def test_rebuild_seed_never_calls_an_llm(tmp_path, monkeypatch):
    """rebuild_seed is a pure re-render pass -- it must never call
    chat_json/chat_text, even transitively."""
    _build_full_wiki(tmp_path)

    def _fail(*args, **kwargs):
        raise AssertionError("rebuild_seed must never call the LLM client")

    monkeypatch.setattr("wake.llm.openai_client.chat_json", _fail)
    monkeypatch.setattr("wake.llm.openai_client.chat_text", _fail)

    result = rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)
    assert result["ok"] is True


def test_rebuild_seed_output_satisfies_wiki_invariants(tmp_path):
    """After a full rebuild, the wiki must still satisfy the same
    frontmatter/link invariants as a freshly-built one (see
    test_wiki_invariants.py) -- a rebuild must not degrade output
    quality relative to the original write path."""
    fixture = _build_full_wiki(tmp_path)
    rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    wiki_root = fixture["wiki_root"]
    for md_path in wiki_root.rglob("*.md"):
        text = md_path.read_text(encoding="utf-8")
        assert_all_relative_md_links_exist(text, md_path, wiki_root)
        if md_path.name in _NO_FRONTMATTER_FILES:
            continue
        assert_frontmatter_valid(text, source=md_path)


# --- CLI wiring: `wake rebuild <seed>` -------------------------------------
# End-to-end through wake.cli.main.main() via sys.argv, same convention as
# tests/test_show_verbs.py -- verifies the parser -> dispatch -> handler ->
# emit wiring, not just the underlying rebuild_seed() function.

def _run_cli(argv, tmp_path, capsys):
    import sys as _sys
    from unittest.mock import patch as _patch

    from wake.cli.main import main as _main
    with _patch.object(_sys, "argv", ["wake", "--work-dir", str(tmp_path), *argv]):
        try:
            _main()
            code = 0
        except SystemExit as exc:
            code = exc.code or 0
    return code, capsys.readouterr()


def test_cli_rebuild_human_output(tmp_path, capsys):
    from wake.io import atomic_write_json
    from wake.seed import work_dir
    from wake.state import mark_stage_complete

    fixture = _build_full_wiki(tmp_path)
    seed_id = fixture["seed_id"]
    wd = work_dir(seed_id, tmp_path)
    atomic_write_json(wd / "seed.json", {**PARALLEL_NETCDF_WORK, "resolved_at": "2020-01-01T00:00:00"})
    mark_stage_complete(wd, "seed", seed_id=seed_id, prompt_version="seed-1")

    code, captured = _run_cli(["rebuild", seed_id], tmp_path, capsys)

    assert code == 0
    assert "Rebuild complete:" in captured.out
    assert "dossiers:" in captured.out
    assert "wiki_orientation:" in captured.out


def test_cli_rebuild_json_output(tmp_path, capsys):
    from wake.io import atomic_write_json
    from wake.seed import work_dir
    from wake.state import mark_stage_complete

    fixture = _build_full_wiki(tmp_path)
    seed_id = fixture["seed_id"]
    wd = work_dir(seed_id, tmp_path)
    atomic_write_json(wd / "seed.json", {**PARALLEL_NETCDF_WORK, "resolved_at": "2020-01-01T00:00:00"})
    mark_stage_complete(wd, "seed", seed_id=seed_id, prompt_version="seed-1")

    import json as _json
    code, captured = _run_cli(["--json", "rebuild", seed_id], tmp_path, capsys)

    assert code == 0
    envelope = _json.loads(captured.out)
    assert envelope["ok"] is True
    assert envelope["data"]["seed_openalex_id"] == seed_id
    step_names = {s["step"] for s in envelope["data"]["steps"]}
    assert step_names == {
        "dossiers", "evidence_index", "themes", "themes_index",
        "outline", "sections", "narrative", "impact", "wiki_orientation",
    }


def test_rebuild_seed_over_pre_migration_dossier(tmp_path):
    """rebuild_seed must succeed when the evidence/ dir contains a legacy
    dossier (no schema_version) produced by an older Wake version.  The
    rebuild re-renders the .md from the .json sidecar via rerender_dossier_md,
    which in turn persists the migrated (schema_version=2) form.
    """
    import json as _json

    from wake.evidence import dossier_json_path
    from wake.models import EVIDENCE_DOSSIER_VERSION

    fixture = _build_full_wiki(tmp_path)
    seed_id = fixture["seed_id"]
    citing_id = fixture["w0"]["openalex_id"]

    json_path = dossier_json_path(seed_id, citing_id, tmp_path)
    current = _json.loads(json_path.read_text())
    current.pop("schema_version", None)
    json_path.write_text(_json.dumps(current))

    assert "schema_version" not in _json.loads(json_path.read_text())

    result = rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)
    assert result["ok"] is True

    on_disk = _json.loads(json_path.read_text())
    assert on_disk.get("schema_version") == EVIDENCE_DOSSIER_VERSION
