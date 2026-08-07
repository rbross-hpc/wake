# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake theme create/confirm/queue/show/rerender-all.

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


def _build_theme_parser(sub) -> None:
    p = sub.add_parser(
        "theme",
        help="Combined-evidence thematic documents synthesizing several citing works.",
    )
    ssub = p.add_subparsers(dest="theme_action", required=True, metavar="ACTION")

    create = ssub.add_parser(
        "create",
        help="Write (or overwrite) a theme document. wake validates and persists this "
             "judgment -- it never decides which works belong together or writes the "
             "summary itself. Always a draft -- no LLM call; the agent supplies the "
             "title/summary/citing-ids after reading the underlying dossiers/"
             "classifications itself.",
    )
    create.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    create.add_argument("slug", help="Theme identifier, e.g. 'earth-system-modeling' (lowercase, hyphenated).")
    create.add_argument("--title", required=True, help="Human-readable theme title.")
    create.add_argument("--summary", required=True, help="Synthesis paragraph, written by the agent.")
    create.add_argument("--citing-ids", required=True, metavar="ID,ID,...",
                         help="Comma-separated OpenAlex IDs of the citing works that support this theme.")

    confirm = ssub.add_parser(
        "confirm",
        help="Human-approved sign-off promoting a theme from 'draft' to 'confirmed'. "
             "wake only validates the sign-off (every cited work already human-verified) "
             "and records it -- the human's approval is the actual decision. Always run "
             "by the agent on the human's behalf, never by asking the human to run this "
             "command themselves (see SKILL.md). Refuses unless every cited work is "
             "already human-verified via `wake override`.",
    )
    confirm.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    confirm.add_argument("slug", help="Theme identifier to confirm.")

    queue = ssub.add_parser(
        "queue",
        help="List outstanding work across all themes for a seed: citing works with no "
             "evidence dossier yet, and dossiers that have appeared since a theme was "
             "last created/reviewed but haven't been re-confirmed.",
    )
    queue.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")

    show = ssub.add_parser("show", help="Print an already-written theme document.")
    show.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    show.add_argument("slug", help="Theme identifier to print.")

    rerender_all = ssub.add_parser(
        "rerender-all",
        help="Re-emit every theme's .md from its .json sidecar -- a rendering-only "
             "pass (no change to any theme's status or citing-works list) that "
             "refreshes derived content like the \"Referenced By\" narrative-section "
             "back-link. Use after a wake upgrade changes theme rendering, to "
             "backfill an existing wiki.",
    )
    rerender_all.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")


def run_theme(args) -> None:
    if args.theme_action == "create":
        run_theme_create(args)
    elif args.theme_action == "confirm":
        run_theme_confirm(args)
    elif args.theme_action == "queue":
        run_theme_queue(args)
    elif args.theme_action == "show":
        run_theme_show(args)
    elif args.theme_action == "rerender-all":
        run_theme_rerender_all(args)


def run_theme_create(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...themes import create_theme
    base = _work_dir_base(args)
    citing_ids = [c.strip() for c in args.citing_ids.split(",") if c.strip()]

    try:
        result = create_theme(
            work, args.slug,
            title=args.title, summary=args.summary, citing_ids=citing_ids,
            base=base,
        )
    except ValueError as exc:
        emit_error("theme", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Theme JSON written (draft): {d['theme_json_path']}")
        if d["needs_evidence"]:
            print(f"  {len(d['needs_evidence'])} cited work(s) have no evidence dossier yet: "
                  f"{', '.join(d['needs_evidence'])}")
        print("  Present to the human; run `wake theme confirm` on their behalf once "
              "they approve (requires every cited work to be human-verified first).")
        print(f"  Run `wake rebuild {args.seed}` to render this theme's Markdown.")

    emit("theme", result, as_json=args.json_out, human=human)


def run_theme_confirm(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...themes import confirm_theme
    base = _work_dir_base(args)

    try:
        result = confirm_theme(work, args.slug, base=base)
    except ValueError as exc:
        emit_error("theme", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        if not d["ok"]:
            print(d["message"])
            return
        print(f"Theme confirmed: {d['theme_json_path']}")
        print(f"Run `wake rebuild {args.seed}` to render this in the wiki.")

    emit("theme", result, as_json=args.json_out, human=human)
    if not result["ok"]:
        sys.exit(1)


def run_theme_queue(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...themes import list_theme_needs_evidence
    base = _work_dir_base(args)

    entries = list_theme_needs_evidence(work["openalex_id"], base)

    def human(d):
        if not d:
            print("No outstanding theme work.")
            return
        by_theme: dict[str, list[dict]] = {}
        for e in d:
            by_theme.setdefault(e["theme_slug"], []).append(e)
        for slug, items in by_theme.items():
            print(f'Theme "{slug}":')
            for item in items:
                if item["status"] == "dossier-available-unreviewed":
                    print(f"  {item['citing_id']} — dossier now available — re-review and "
                          "re-run `wake theme create` to confirm it still supports this theme")
                else:
                    print(f"  {item['citing_id']} — still needs a `wake evidence` dossier")

    emit("theme", {"queue": entries}, as_json=args.json_out, human=lambda d: human(d["queue"]))


def run_theme_show(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...themes import theme_json_path, theme_path
    base = _work_dir_base(args)
    seed_id = work["openalex_id"]

    p = theme_path(seed_id, args.slug, base)
    if not p.exists():
        if theme_json_path(seed_id, args.slug, base).exists():
            emit_error("theme", RuntimeError(
                f"Theme {args.slug!r} exists but hasn't been rendered yet. "
                f"Run `wake rebuild {args.seed}` first."
            ), as_json=args.json_out)
        else:
            emit_error("theme", RuntimeError(
                f"No theme {args.slug!r} found for {args.seed}. Run `wake theme create` first."
            ), as_json=args.json_out)
        sys.exit(1)

    text = p.read_text(encoding="utf-8")
    emit("theme", {"markdown": text}, as_json=args.json_out, human=lambda d: print(d["markdown"]))


def run_theme_rerender_all(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...themes import rerender_all_themes
    base = _work_dir_base(args)

    rerendered = rerender_all_themes(work["openalex_id"], work, base=base)
    emit(
        "theme", {"ok": True, "rerendered": rerendered, "count": len(rerendered)},
        as_json=args.json_out,
        human=lambda d: print(f"Re-rendered {d['count']} theme(s)."),
    )
