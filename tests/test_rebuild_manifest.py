# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Tests for build.py's persisted rebuild manifest (rebuild-manifest.json):
the Phase 2 follow-on to making rendering an explicit `wake rebuild` step
(see build.py's module docstring). The manifest reports which JSON
render-input sources changed since the previous `wake rebuild` call --
it is a report only, and must never cause rebuild_seed() to skip a
render step.

Reuses tests/test_wiki_invariants.py's `_build_full_wiki` fixture, same
as test_build.py.
"""
from __future__ import annotations

import json

from wake.build import rebuild_seed
from wake.io import atomic_write_json
from wake.seed import work_dir

from .test_wiki_invariants import PARALLEL_NETCDF_WORK, _build_full_wiki


def test_first_rebuild_reports_first_render_and_all_sources_added(tmp_path):
    result = rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    changes = result["changes"]
    assert changes["first_render"] is True
    assert changes["previous_render"] is None
    assert changes["removed"] == []
    assert changes["changed"] == []
    assert "seed.json" not in changes["added"]  # no seed.json in an empty packet


def test_first_rebuild_writes_manifest_file(tmp_path):
    rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    manifest_path = work_dir(seed_id, tmp_path) / "rebuild-manifest.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] >= 1
    assert "rendered_at" in manifest
    assert manifest["sources"] == {}  # empty packet: no JSON sources yet


def test_full_packet_first_rebuild_tracks_every_source(tmp_path):
    # _build_full_wiki() already ends with one rebuild_seed() call (see
    # its docstring), so the manifest written there is the "first render"
    # this test inspects -- no need to call rebuild_seed() again.
    fixture = _build_full_wiki(tmp_path)
    seed_id = fixture["seed_id"]

    manifest_path = work_dir(seed_id, tmp_path) / "rebuild-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tracked = set(manifest["sources"].keys())

    assert f"evidence/{fixture['w0']['openalex_id']}.json" in tracked
    assert f"evidence/{fixture['w1']['openalex_id']}.json" in tracked
    assert f"evidence/{fixture['w3']['openalex_id']}.json" in tracked
    assert "evidence/themes/t1.json" in tracked
    assert "narrative/outline.json" in tracked
    assert "narrative/sections/s1.json" in tracked

    # A second rebuild with nothing changed should report all of the
    # above as already-tracked, not newly added.
    result = rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)
    assert result["changes"]["added"] == []
    assert result["changes"]["first_render"] is False


def test_repeated_rebuild_with_no_source_changes_reports_nothing_changed(tmp_path):
    _build_full_wiki(tmp_path)
    rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    result = rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    changes = result["changes"]
    assert changes["first_render"] is False
    assert changes["added"] == []
    assert changes["changed"] == []
    assert changes["removed"] == []


def test_rebuild_still_re_renders_everything_even_with_no_source_changes(tmp_path):
    """The manifest is report-only -- rebuild_seed() must never skip a
    render step just because no source hash changed."""
    fixture = _build_full_wiki(tmp_path)
    rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    dossier_md = fixture["wiki_root"] / "evidence" / f"{fixture['w0']['openalex_id']}.md"
    dossier_md.unlink()
    assert not dossier_md.exists()

    result = rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    assert result["changes"]["added"] == []
    assert result["changes"]["changed"] == []
    assert dossier_md.exists()  # rendered anyway -- unconditional, not gated by the manifest


def test_editing_a_dossier_json_is_reported_as_changed(tmp_path):
    fixture = _build_full_wiki(tmp_path)
    seed_id = fixture["seed_id"]
    citing_id = fixture["w0"]["openalex_id"]
    rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    from wake.evidence import dossier_json_path
    json_path = dossier_json_path(seed_id, citing_id, tmp_path)
    data = json.loads(json_path.read_text(encoding="utf-8"))
    data["proposed_relationship"] = "extends"
    json_path.write_text(json.dumps(data), encoding="utf-8")

    result = rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    assert result["changes"]["changed"] == [f"evidence/{citing_id}.json"]
    assert result["changes"]["added"] == []
    assert result["changes"]["removed"] == []


def test_deleting_a_theme_json_is_reported_as_removed(tmp_path):
    fixture = _build_full_wiki(tmp_path)
    seed_id = fixture["seed_id"]
    rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    from wake.themes import theme_json_path
    theme_json_path(seed_id, "t1", tmp_path).unlink()

    result = rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    assert result["changes"]["removed"] == ["evidence/themes/t1.json"]
    assert result["changes"]["changed"] == []


def test_adding_a_new_dossier_between_rebuilds_is_reported_as_added(tmp_path):
    # _build_full_wiki() already performs one rebuild (see its
    # docstring), so the manifest is already primed before this test
    # adds a new dossier. Clone an existing dossier's valid shape rather
    # than hand-writing one, so rerender_all_dossiers has a shape it can
    # actually render.
    fixture = _build_full_wiki(tmp_path)
    seed_id = fixture["seed_id"]

    from wake.evidence import dossier_json_path
    from wake.io import read_json
    existing = dossier_json_path(seed_id, fixture["w0"]["openalex_id"], tmp_path)
    data = dict(read_json(existing))
    new_id = "W9999999999"
    data["citing_openalex_id"] = new_id
    atomic_write_json(dossier_json_path(seed_id, new_id, tmp_path), data)

    result = rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    assert result["changes"]["added"] == [f"evidence/{new_id}.json"]


def test_manifest_never_hashes_rendered_markdown(tmp_path):
    """The manifest tracks JSON render inputs only -- never .md/index
    output. Editing a rendered .md file (without rebuilding) must not
    show up in any subsequent diff."""
    fixture = _build_full_wiki(tmp_path)
    rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    dossier_md = fixture["wiki_root"] / "evidence" / f"{fixture['w0']['openalex_id']}.md"
    dossier_md.write_text(dossier_md.read_text(encoding="utf-8") + "\nhand-edited\n", encoding="utf-8")

    result = rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    assert result["changes"]["added"] == []
    assert result["changes"]["changed"] == []
    assert result["changes"]["removed"] == []


def test_manifest_round_trips_through_migrate_manifest(tmp_path):
    """A hand-written legacy manifest (no schema_version key) must not
    break rebuild_seed()."""
    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    wd = work_dir(seed_id, tmp_path)
    wd.mkdir(parents=True, exist_ok=True)
    atomic_write_json(wd / "seed.json", PARALLEL_NETCDF_WORK)
    atomic_write_json(wd / "rebuild-manifest.json", {
        "rendered_at": "2020-01-01T00:00:00+00:00",
        "sources": {"seed.json": "deadbeef"},
    })

    result = rebuild_seed(PARALLEL_NETCDF_WORK, base=tmp_path, verbose=False)

    assert result["ok"] is True
    assert result["changes"]["first_render"] is False
    assert result["changes"]["changed"] == ["seed.json"]


def test_cli_rebuild_json_includes_changes_block(tmp_path, capsys):
    from wake.state import mark_stage_complete

    from .test_build import _run_cli

    fixture = _build_full_wiki(tmp_path)
    seed_id = fixture["seed_id"]
    wd = work_dir(seed_id, tmp_path)
    atomic_write_json(wd / "seed.json", {**PARALLEL_NETCDF_WORK, "resolved_at": "2020-01-01T00:00:00"})
    mark_stage_complete(wd, "seed", seed_id=seed_id, prompt_version="seed-1")

    code, captured = _run_cli(["--json", "rebuild", seed_id], tmp_path, capsys)

    assert code == 0
    envelope = json.loads(captured.out)
    # _build_full_wiki() already performed one rebuild -- this CLI call
    # adds seed.json (written above, after the fixture's own rebuild) and
    # is otherwise a no-op second render.
    assert envelope["data"]["changes"]["first_render"] is False
    assert envelope["data"]["changes"]["added"] == ["seed.json"]


def test_cli_rebuild_human_output_reports_first_render(tmp_path, capsys):
    from wake.state import mark_stage_complete

    from .test_build import _run_cli

    seed_id = PARALLEL_NETCDF_WORK["openalex_id"]
    wd = work_dir(seed_id, tmp_path)
    atomic_write_json(wd / "seed.json", {**PARALLEL_NETCDF_WORK, "resolved_at": "2020-01-01T00:00:00"})
    mark_stage_complete(wd, "seed", seed_id=seed_id, prompt_version="seed-1")

    code, captured = _run_cli(["rebuild", seed_id], tmp_path, capsys)

    assert code == 0
    assert "First render" in captured.out


def test_cli_rebuild_human_output_reports_no_changes_on_second_call(tmp_path, capsys):
    from wake.state import mark_stage_complete

    from .test_build import _run_cli

    fixture = _build_full_wiki(tmp_path)
    seed_id = fixture["seed_id"]
    wd = work_dir(seed_id, tmp_path)
    atomic_write_json(wd / "seed.json", {**PARALLEL_NETCDF_WORK, "resolved_at": "2020-01-01T00:00:00"})
    mark_stage_complete(wd, "seed", seed_id=seed_id, prompt_version="seed-1")

    _run_cli(["rebuild", seed_id], tmp_path, capsys)
    code, captured = _run_cli(["rebuild", seed_id], tmp_path, capsys)

    assert code == 0
    assert "No source changes since" in captured.out
