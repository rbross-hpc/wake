# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""The single explicit render step for a seed's derived Markdown.

wake's canonical data is JSON: seed.json, citing.json, classified.json,
evidence/<id>.json dossier sidecars, evidence/themes/<slug>.json,
narrative/outline.json, narrative/sections/<slug>.json, overrides.jsonl,
and the sibling append-only decision logs (exclusions.jsonl,
duplicates.jsonl, etc.). Every Markdown file wake writes --
evidence/<id>.md, evidence/index.md, evidence/themes/<slug>.md,
evidence/themes/index.md, narrative/outline.md, narrative/sections/
<slug>.md, narrative.md, impact.md, README.md, AGENTS.md -- is a
deterministic render *derived* from that JSON, with one exception:
evidence/log.md is an append-only history with no JSON backing (see
below), so it cannot be "rebuilt from scratch," only appended to going
forward.

Before this module existed, each of those derived-render functions
(evidence.rerender_dossier_md/rerender_all_dossiers,
evidence_wiki.rebuild_index/rebuild_themes_index/
rebuild_wiki_orientation, themes.rerender_all_themes,
narrative.rerender_all_sections/_refresh_outline_md/stitch,
report.bake_and_save) was invoked piecemeal -- most of them fired as an
implicit side effect of an unrelated write command (build_dossier,
add_override, create_theme, create_section, ...) in addition to (or,
for rebuild_index/rebuild_themes_index, instead of) any standalone CLI
verb, and even the bulk CLI verbs didn't call the others they logically
depend on (`wake theme rerender-all` doesn't refresh themes/index.md;
`wake narrative section rerender-all` doesn't refresh outline.md's live
status column) -- see PLAN.md "Phase 3" / BACKLOG.md Theme L's research
notes for the full call-graph audit this module is built from.

As of the Structural Hardening follow-on that made rendering explicit
(v0.4.16), every one of those write-time side effects has been removed:
JSON-mutating functions (build_dossier, add_override, unverify_work,
create_theme, confirm_theme, create_outline, create_section,
confirm_section) now write only JSON and return `"rebuild_needed":
True`. `wake bake`/`wake narrative stitch` remain explicit render verbs
for impact.md/narrative.md respectively, but no longer additionally
refresh README.md/AGENTS.md orientation as a side effect. `rebuild_seed()`
is now genuinely the *only* place any of dossiers/index/themes/outline/
narrative/impact/wiki-orientation gets (re-)rendered -- not a recovery
tool for gaps in piecemeal rendering, but the render step itself. A
human or agent who wants the wiki's Markdown to reflect the JSON that's
currently on disk always runs exactly one command: `wake rebuild`.

`rebuild_seed()` walks every derived artifact type that currently has
*any* JSON backing on disk for this seed, in dependency order (dossiers
before the indexes that summarize them; dossiers/themes before the wiki
orientation counts that reference them; outline/sections before the
stitched narrative), and reports exactly what it touched. It never makes
an LLM or network call -- `rebuild_seed()` only re-derives Markdown/index
files from JSON that's already there. It also never invents JSON that
doesn't exist: a seed with no evidence/ directory yet simply skips that
step, same as every individual `rerender_*`/`rebuild_*` function already
does.

As of the Phase 2 follow-on to the above (v0.4.17), every rebuild also
reports what changed on the *input* side since the previous rebuild: a
persisted `rebuild-manifest.json` sidecar (models.RebuildManifest) holds
a sha256 per JSON render-input source (seed.json, citing.json,
classified.json, overrides.jsonl, every dossier/theme/section JSON,
outline.json -- never the rendered Markdown/index files themselves).
Each call to `rebuild_seed()` compares the current hashes to that
sidecar, reports which sources were added/changed/removed since the
last rebuild under the returned `"changes"` key, and rewrites the
sidecar with the fresh hashes. This is report-only: it never gates or
skips a render step above; the manifest exists to answer "what changed
between renders" (a question that's only meaningful now that rendering
is a single distinct act), not to make `rebuild_seed()` incremental. See
`_collect_source_hashes()`/`_diff_and_write_manifest()` below.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .io import atomic_write_json, now_iso, read_json, sha256_bytes
from .models import RebuildManifestWrite, migrate_manifest


def _manifest_path(seed_id: str, base: Path | None = None) -> Path:
    from .seed import work_dir

    return work_dir(seed_id, base) / "rebuild-manifest.json"


def _collect_source_hashes(seed_id: str, base: Path | None = None) -> dict[str, str]:
    """Hash every JSON file that currently feeds a render for this seed,
    keyed by a stable path-like key relative to the seed's work dir.

    This is the *input* side of "what changed between renders" -- render
    outputs (.md/index files) are never hashed here, and this map is
    never consulted to decide whether to render something; see this
    module's docstring.
    """
    from .evidence import evidence_dir
    from .narrative import narrative_dir, outline_json_path, sections_dir
    from .seed import work_dir
    from .themes import themes_dir

    wd = work_dir(seed_id, base)
    sources: dict[str, str] = {}

    def _hash_file(path: Path, key: str) -> None:
        if path.exists():
            sources[key] = sha256_bytes(path.read_bytes())

    _hash_file(wd / "seed.json", "seed.json")
    _hash_file(wd / "citing.json", "citing.json")
    _hash_file(wd / "classified.json", "classified.json")
    _hash_file(wd / "overrides.jsonl", "overrides.jsonl")

    ed = evidence_dir(seed_id, base)
    if ed.exists():
        for p in sorted(ed.glob("*.json")):
            _hash_file(p, f"evidence/{p.name}")

    td = themes_dir(seed_id, base)
    if td.exists():
        for p in sorted(td.glob("*.json")):
            _hash_file(p, f"evidence/themes/{p.name}")

    nd = narrative_dir(seed_id, base)
    if nd.exists():
        _hash_file(outline_json_path(seed_id, base), "narrative/outline.json")

    sd = sections_dir(seed_id, base)
    if sd.exists():
        for p in sorted(sd.glob("*.json")):
            _hash_file(p, f"narrative/sections/{p.name}")

    return sources


def _load_manifest(seed_id: str, base: Path | None = None) -> dict[str, Any] | None:
    p = _manifest_path(seed_id, base)
    if not p.exists():
        return None
    return migrate_manifest(read_json(p))


def _diff_and_write_manifest(seed_id: str, base: Path | None = None) -> dict[str, Any]:
    """Compare this seed's current JSON source hashes to the manifest
    left by the previous rebuild (if any), write the refreshed manifest,
    and return a report of what changed. Report-only: callers never skip
    a render step based on this."""
    prior = _load_manifest(seed_id, base)
    prior_sources: dict[str, str] = prior["sources"] if prior else {}
    current_sources = _collect_source_hashes(seed_id, base)

    added = sorted(k for k in current_sources if k not in prior_sources)
    removed = sorted(k for k in prior_sources if k not in current_sources)
    changed = sorted(
        k for k in current_sources
        if k in prior_sources and current_sources[k] != prior_sources[k]
    )

    manifest = RebuildManifestWrite(rendered_at=now_iso(), sources=current_sources)
    atomic_write_json(_manifest_path(seed_id, base), manifest.to_json_dict())

    return {
        "first_render": prior is None,
        "previous_render": prior["rendered_at"] if prior else None,
        "added": added,
        "changed": changed,
        "removed": removed,
    }


def rebuild_seed(
    seed_work: dict[str, Any],
    *,
    base: Path | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """Resync every derived (JSON-sidecar-backed) Markdown/index file for
    one seed, in dependency order. Safe to call at any point in a
    packet's lifecycle -- each step is a no-op if that artifact type
    doesn't exist yet for this seed (e.g. a packet with no themes/
    directory skips the themes steps entirely).

    Returns a summary dict:
        {
          "ok": True,
          "seed_openalex_id": "...",
          "steps": [
            {"step": "dossiers", "rebuilt": [...citing_ids...]},
            {"step": "evidence_index", "rebuilt": true|false},
            {"step": "themes", "rebuilt": [...slugs...]},
            {"step": "themes_index", "rebuilt": true|false},
            {"step": "outline", "rebuilt": true|false},
            {"step": "sections", "rebuilt": [...slugs...]},
            {"step": "narrative", "rebuilt": true|false},
            {"step": "impact", "rebuilt": true|false},
            {"step": "wiki_orientation", "rebuilt": true},
          ],
          "changes": {
            "first_render": true|false,
            "previous_render": "<iso>"|null,
            "added": [...source keys...],
            "changed": [...source keys...],
            "removed": [...source keys...],
          },
        }

    "changes" reports which JSON render-input sources (not rendered
    output) differ from the previous `rebuild_seed()` call for this seed
    -- see this module's docstring. It never affects which steps above
    run; every step always runs, unconditionally.

    Does not call unverify/mark_verified/mark_pending -- those represent
    a human decision (a verification state change), not a re-render of
    already-decided data, and are out of scope for a pure rebuild.
    """
    from .evidence import evidence_dir, rerender_all_dossiers
    from .evidence_wiki import rebuild_index, rebuild_themes_index, rebuild_wiki_orientation
    from .narrative import (
        _refresh_outline_md,
        load_outline,
        narrative_dir,
        outline_json_path,
        rerender_all_sections,
        sections_dir,
        stitch,
    )
    from .themes import rerender_all_themes, themes_dir

    seed_id = seed_work["openalex_id"]
    seed_title = seed_work.get("title")
    steps: list[dict[str, Any]] = []

    def _log(msg: str) -> None:
        if verbose:
            print(f"[wake] rebuild: {msg}", file=sys.stderr)

    # 1. Dossiers first -- everything downstream (evidence/index.md, the
    # wiki orientation counts, a theme's "Referenced by" backlinks) reads
    # dossier JSON, so dossiers must be current before anything that
    # summarizes them.
    ed = evidence_dir(seed_id, base)
    if ed.exists() and any(ed.glob("*.json")):
        _log("re-rendering evidence dossiers...")
        rebuilt = rerender_all_dossiers(seed_id, seed_work, base=base)
        steps.append({"step": "dossiers", "rebuilt": rebuilt})

        _log("rebuilding evidence/index.md...")
        rebuild_index(seed_id, seed_title=seed_title, base=base)
        steps.append({"step": "evidence_index", "rebuilt": True})
    else:
        steps.append({"step": "dossiers", "rebuilt": []})
        steps.append({"step": "evidence_index", "rebuilt": False})

    # 2. Themes -- rerender_all_themes only touches each theme's own .md
    # (it deliberately doesn't call rebuild_themes_index; see this
    # module's docstring), so the index rebuild is a separate, explicit
    # second step here rather than assumed to happen automatically.
    td = themes_dir(seed_id, base)
    if td.exists() and any(td.glob("*.json")):
        _log("re-rendering themes...")
        rebuilt_themes = rerender_all_themes(seed_id, seed_work, base=base)
        steps.append({"step": "themes", "rebuilt": rebuilt_themes})

        _log("rebuilding evidence/themes/index.md...")
        rebuild_themes_index(seed_id, seed_title=seed_title, base=base)
        steps.append({"step": "themes_index", "rebuilt": True})
    else:
        steps.append({"step": "themes", "rebuilt": []})
        steps.append({"step": "themes_index", "rebuilt": False})

    # 3. Narrative: sections before outline (outline.md's per-component
    # status column reads each section's current status), outline before
    # the stitched narrative.md (stitch() reads the outline for component
    # order). rerender_all_sections doesn't call _refresh_outline_md (see
    # this module's docstring), so it's a separate explicit step here too.
    nd = narrative_dir(seed_id, base)
    sd = sections_dir(seed_id, base)
    if sd.exists() and any(sd.glob("*.json")):
        _log("re-rendering narrative sections...")
        rebuilt_sections = rerender_all_sections(seed_id, seed_work, base=base)
        steps.append({"step": "sections", "rebuilt": rebuilt_sections})
    else:
        steps.append({"step": "sections", "rebuilt": []})

    if nd.exists() and outline_json_path(seed_id, base).exists():
        _log("refreshing narrative/outline.md...")
        _refresh_outline_md(seed_work, base=base)
        steps.append({"step": "outline", "rebuilt": True})
    else:
        steps.append({"step": "outline", "rebuilt": False})

    if load_outline(seed_id, base) is not None:
        _log("re-stitching narrative.md...")
        stitch(seed_work, base=base)
        steps.append({"step": "narrative", "rebuilt": True})
    else:
        steps.append({"step": "narrative", "rebuilt": False})

    # 4. impact.md/impact.json -- rebuilt from classified.json (falling
    # back to citing.json if nothing has been classified yet), same
    # resolution `wake bake` itself uses. No LLM call: this only
    # re-aggregates already-classified/already-overridden data.
    from .citing import load_citing
    from .classify import load_classified
    from .report import bake_and_save

    citing = load_citing(seed_id, base)
    if citing is not None:
        classified = load_classified(seed_id, base)
        works = classified if classified is not None else citing
        _log("re-baking impact.md/impact.json...")
        bake_and_save(seed_work, works, base=base, verbose=False)
        steps.append({"step": "impact", "rebuilt": True})
    else:
        steps.append({"step": "impact", "rebuilt": False})

    # 5. README.md/AGENTS.md last -- the orientation counts summarize
    # everything rebuilt above (dossier/theme/verification/narrative/
    # seed-PDF status), so they must be refreshed after every other step,
    # not interleaved with them. Always run: rebuild_wiki_orientation is
    # itself a no-op-safe full recompute from whatever's on disk, even
    # for a seed with nothing beyond seed.json yet.
    _log("refreshing README.md/AGENTS.md...")
    rebuild_wiki_orientation(seed_id, seed_work, base=base)
    steps.append({"step": "wiki_orientation", "rebuilt": True})

    # 6. Manifest: report which JSON sources changed since the previous
    # rebuild, and persist the current hashes for next time. Every step
    # above already ran unconditionally -- this is purely a report, never
    # a gate (see this module's docstring and models.RebuildManifest).
    changes = _diff_and_write_manifest(seed_id, base)

    return {"ok": True, "seed_openalex_id": seed_id, "steps": steps, "changes": changes}
