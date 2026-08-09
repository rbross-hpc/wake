# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake timeline candidates/period/stitch/show.

Part of the cli/commands/ split (see PLAN.md "Phase 3 -- Structural
Hardening" / BACKLOG.md Theme L): cli/main.py used to hold every
command's parser-building and dispatch logic in one ~2,000-line file.
Each module here owns one command family's argparse subparser
construction (`_build_*_parser`) and handler (`run_*`) functions;
cli/main.py itself is reduced to constructing the top-level parser,
registering each family's parser, and dispatching to its `run_*`.
"""
from __future__ import annotations

import sys

from ..emit import emit, emit_error
from ..main_helpers import _resolve_seed_to_work, _work_dir_base


def _build_timeline_parser(sub) -> None:
    p = sub.add_parser(
        "timeline",
        help="Curate a timeline of the seed's key developments over time, one period at a time, then stitch.",
    )
    tsub = p.add_subparsers(dest="timeline_action", required=True, metavar="ACTION")

    candidates = tsub.add_parser(
        "candidates",
        help="Read-only, complete, scored view of every dated classified work, bucketed "
             "by year (or an N-year window) -- the material to choose highlights from. "
             "Never pre-selects a 'top N'; the agent/human decide the threshold in "
             "conversation.",
    )
    candidates.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    candidates.add_argument("--bucket-years", type=int, default=1, metavar="N",
                             help="Group buckets into windows of N years (default: 1, per-year).")
    candidates.add_argument("--min-strength", type=float, default=None, metavar="S",
                             help="Query-time filter: only include works whose best relationship "
                                  "facet has strength >= S (omit to see everything).")
    candidates.add_argument("--since", type=int, default=None, metavar="YEAR",
                             help="Only include works published in or after YEAR.")
    candidates.add_argument("--until", type=int, default=None, metavar="YEAR",
                             help="Only include works published in or before YEAR.")

    period = tsub.add_parser("period", help="Draft or confirm one timeline period's highlighted works.")
    period_sub = period.add_subparsers(dest="period_action", required=True, metavar="ACTION")

    period_create = period_sub.add_parser(
        "create",
        help="Write (or overwrite) one period's highlighted works. wake validates and "
             "persists this selection -- it never decides which works belong. Always a "
             "draft. slug may be a bare year (e.g. '2012', an emergent single-year period) "
             "or a named span (e.g. 'early-adoption', pair with --from/--to).",
    )
    period_create.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    period_create.add_argument("slug", help="Period identifier -- a bare year, or a kebab-case slug.")
    period_create.add_argument("--highlights", required=True, metavar="ID,ID,...",
                                help="Comma-separated citing OpenAlex IDs to highlight in this period.")
    period_create.add_argument("--label", default=None, help="Human-readable period label (e.g. 'Early adoption').")
    period_create.add_argument("--from", dest="from_year", type=int, default=None, metavar="YEAR")
    period_create.add_argument("--to", dest="to_year", type=int, default=None, metavar="YEAR")
    period_create.add_argument("--note", default=None, help="Framing note for the whole period.")
    period_create.add_argument(
        "--highlight-note", action="append", default=[], metavar="ID=NOTE",
        help="Per-highlight note, e.g. --highlight-note W123='First major reuse.' "
             "May be repeated.",
    )

    period_confirm = period_sub.add_parser(
        "confirm",
        help="Human-approved sign-off promoting a period from 'draft' to 'confirmed'. "
             "Refuses unless every highlighted work is currently human-verified (via "
             "`wake override`) -- a confirmed period is an evidentiary claim, not just "
             "an agent's classification guess. Always run by the agent on the human's "
             "behalf (see SKILL.md).",
    )
    period_confirm.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    period_confirm.add_argument("slug", help="Period identifier to confirm.")

    period_show = period_sub.add_parser("show", help="Print one already-drafted period's Markdown.")
    period_show.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    period_show.add_argument("slug", help="Period identifier to print.")

    stitch = tsub.add_parser(
        "stitch",
        help="Assemble every period (chronological) into timeline.md (working artifact, "
             "all periods) and timeline.json (confirmed periods only -- the handoff to a "
             "graphic-rendering tool).",
    )
    stitch.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")

    show = tsub.add_parser("show", help="Print the assembled top-level timeline.md.")
    show.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")


def run_timeline(args) -> None:
    if args.timeline_action == "candidates":
        run_timeline_candidates(args)
    elif args.timeline_action == "period":
        run_timeline_period(args)
    elif args.timeline_action == "stitch":
        run_timeline_stitch(args)
    elif args.timeline_action == "show":
        run_timeline_show(args)


def run_timeline_candidates(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...timeline import build_candidates
    base = _work_dir_base(args)

    data = build_candidates(
        work, base=base,
        bucket_years=args.bucket_years, min_strength=args.min_strength,
        since=args.since, until=args.until,
    )

    def human(d):
        if not d["buckets"]:
            print("No dated, classified works found.")
            return
        for b in d["buckets"]:
            span = f"{b['bucket_start']}" if b["bucket_start"] == b["bucket_end"] else f"{b['bucket_start']}\u2013{b['bucket_end']}"
            print(f"{span}: {b['count']} work(s), weighted intensity {b['weighted_intensity']}")
            for w in b["works"]:
                vtag = "[VERIFIED]" if w["verification_status"] == "verified" else "[PROVISIONAL]"
                flags = []
                if w["excluded"]:
                    flags.append("excluded")
                if w["duplicate"]:
                    flags.append("duplicate")
                flag_str = f"  ({', '.join(flags)})" if flags else ""
                print(f"  {vtag} score={w['score']}  {w['relationship']}  {w['title']} ({w['openalex_id']}){flag_str}")
        if d["undated_count"]:
            print(f"\n{d['undated_count']} classified work(s) have no year and are omitted above.")

    emit("timeline", data, as_json=args.json_out, human=human)


def run_timeline_period(args) -> None:
    if args.period_action == "create":
        run_timeline_period_create(args)
    elif args.period_action == "confirm":
        run_timeline_period_confirm(args)
    elif args.period_action == "show":
        run_timeline_period_show(args)


def _parse_highlight_notes(entries: list[str]) -> dict[str, str]:
    notes = {}
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"--highlight-note must be ID=NOTE, got {entry!r}.")
        cid, note = entry.split("=", 1)
        notes[cid.strip()] = note
    return notes


def run_timeline_period_create(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...timeline import create_period
    base = _work_dir_base(args)

    highlight_ids = [h.strip() for h in args.highlights.split(",") if h.strip()]

    try:
        highlight_notes = _parse_highlight_notes(args.highlight_note)
        result = create_period(
            work, args.slug,
            highlight_ids=highlight_ids, highlight_notes=highlight_notes,
            label=args.label, from_year=args.from_year, to_year=args.to_year,
            note=args.note, base=base,
        )
    except ValueError as exc:
        emit_error("timeline", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Period JSON written (draft): {d['period_json_path']}")
        for h in d["highlights"]:
            tag = "[VERIFIED]" if h["status"] == "verified" else f"[{h['status'].upper()}]"
            print(f"  {tag} {h.get('title') or h['citing_id']} ({h['citing_id']})")
        print("  Present to the human; run `wake timeline period confirm` on their behalf "
              "once every highlighted work is human-verified.")
        print(f"  Run `wake rebuild {args.seed}` to render this period's Markdown.")

    emit("timeline", result, as_json=args.json_out, human=human)


def run_timeline_period_confirm(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...timeline import confirm_period
    base = _work_dir_base(args)

    try:
        result = confirm_period(work, args.slug, base=base)
    except ValueError as exc:
        emit_error("timeline", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        if not d["ok"]:
            print(d["message"])
            return
        print(f"Period confirmed: {d['period_json_path']}")
        print(f"Run `wake timeline stitch {args.seed}` to include it in timeline.json.")

    emit("timeline", result, as_json=args.json_out, human=human)
    if not result["ok"]:
        sys.exit(1)


def run_timeline_period_show(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...timeline import period_json_path, period_md_path
    base = _work_dir_base(args)
    seed_id = work["openalex_id"]

    p = period_md_path(seed_id, args.slug, base)
    if not p.exists():
        if period_json_path(seed_id, args.slug, base).exists():
            emit_error("timeline", RuntimeError(
                f"Period {args.slug!r} exists but hasn't been rendered yet. "
                f"Run `wake rebuild {args.seed}` first."
            ), as_json=args.json_out)
        else:
            emit_error("timeline", RuntimeError(
                f"No period {args.slug!r} found for {args.seed}. Run `wake timeline period create` first."
            ), as_json=args.json_out)
        sys.exit(1)

    text = p.read_text(encoding="utf-8")
    emit("timeline", {"markdown": text}, as_json=args.json_out, human=lambda d: print(d["markdown"]))


def run_timeline_stitch(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...timeline import stitch
    base = _work_dir_base(args)

    result = stitch(work, base=base)
    if not result["ok"]:
        emit_error("timeline", RuntimeError(result["message"]), as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Timeline written: {d['timeline_path']}")
        print(f"  {d['confirmed_count']} confirmed, {d['draft_count']} draft period(s).")
        print(f"  {d['timeline_json_path']} carries the confirmed periods only (graphic-tool handoff).")
        if d["overlaps"]:
            for o in d["overlaps"]:
                print(f"  Note: overlapping period ranges: {o['a']} / {o['b']}")

    emit("timeline", result, as_json=args.json_out, human=human)


def run_timeline_show(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...timeline import timeline_json_path, timeline_md_path
    base = _work_dir_base(args)
    seed_id = work["openalex_id"]

    p = timeline_md_path(seed_id, base)
    if not p.exists():
        if timeline_json_path(seed_id, base).exists():
            emit_error("timeline", RuntimeError(
                f"Timeline exists but hasn't been rendered yet. Run `wake rebuild {args.seed}` first."
            ), as_json=args.json_out)
        else:
            emit_error("timeline", RuntimeError(
                f"No timeline found for {args.seed}. Run `wake timeline period create` + `wake timeline stitch` first."
            ), as_json=args.json_out)
        sys.exit(1)

    text = p.read_text(encoding="utf-8")
    emit("timeline", {"markdown": text}, as_json=args.json_out, human=lambda d: print(d["markdown"]))
