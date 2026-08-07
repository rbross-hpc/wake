# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake cost / wake show / wake seed / wake config / wake skill.

Part of the cli/commands/ split (see PLAN.md "Phase 3 -- Structural
Hardening" / BACKLOG.md Theme L): cli/main.py used to hold every
command's parser-building and dispatch logic in one ~2,000-line file.
Each module here owns one command family's argparse subparser
construction (`_build_*_parser`) and handler (`run_*`) functions;
cli/main.py itself is reduced to constructing the top-level parser,
registering each family's parser, and dispatching to its `run_*`.
"""
from __future__ import annotations

import json
import sys

from ..emit import emit, emit_error, is_quiet
from ..main_helpers import _resolve_seed_to_work, _work_dir_base


def _build_cost_parser(sub) -> None:
    p = sub.add_parser("cost", help="Show estimated LLM token/cost usage for a seed.")
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")


def _build_show_parser(sub) -> None:
    p = sub.add_parser("show", help="Re-emit cached results.")
    ssub = p.add_subparsers(dest="show_what", required=True, metavar="WHAT")

    sp = ssub.add_parser("brief", help="Print impact.md for a seed.")
    sp.add_argument("seed", help="OpenAlex ID or seed string.")

    sm = ssub.add_parser("metrics", help="Print impact.json metrics for a seed.")
    sm.add_argument("seed", help="OpenAlex ID or seed string.")

    st = ssub.add_parser("top", help="Print top-evidence table for a seed.")
    st.add_argument("seed", help="OpenAlex ID or seed string.")
    st.add_argument("-n", type=int, default=10, help="Number of top works to show (default: 10).")

    sd = ssub.add_parser("dossier", help="Print an already-built evidence dossier for one citing work.")
    sd.add_argument("seed", help="OpenAlex ID or seed string.")
    sd.add_argument("citing_id", help="OpenAlex ID of the citing work whose dossier to print.")


def _build_seed_parser(sub) -> None:
    p = sub.add_parser(
        "seed",
        help="Seed-paper management commands (fetch-pdf, ...).",
    )
    ssub = p.add_subparsers(dest="seed_action", required=True, metavar="ACTION")

    fp = ssub.add_parser(
        "fetch-pdf",
        help="Acquire the seed paper's own PDF. Tried automatically at wake resolve "
             "time; use this to retry, supply one manually, or force a re-fetch.",
    )
    fp.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    fp.add_argument(
        "--from-pdf", metavar="PATH",
        help="Path to a locally-obtained PDF of the seed paper. wake validates it "
             "matches the seed's metadata (title similarity, author, DOI) before "
             "copying and extracting. Refuses on mismatch unless --force.",
    )
    fp.add_argument(
        "--force", action="store_true",
        help="Re-fetch/re-copy even if a seed PDF is already cached. When used with "
             "--from-pdf, bypasses the metadata-mismatch refusal (mismatch still logged).",
    )


def _build_config_parser(sub) -> None:
    p = sub.add_parser("config", help="Show, validate, or initialise wake configuration.")
    ssub = p.add_subparsers(dest="config_action", required=True, metavar="ACTION")
    ssub.add_parser("show", help="Print resolved configuration.")
    ssub.add_parser("validate", help="Validate configuration and environment.")
    ssub.add_parser("init", help="Write a starter wake.config.yaml in the current directory.")


def _build_skill_parser(sub) -> None:
    p = sub.add_parser("skill", help="Show or export the bundled Agent Skill.")
    ssub = p.add_subparsers(dest="skill_action", required=True, metavar="ACTION")
    ssub.add_parser("show", help="Print the bundled SKILL.md to stdout.")
    ep = ssub.add_parser("export", help="Copy the skill directory to PATH.")
    ep.add_argument("path", metavar="PATH", help="Destination directory.")
    ep.add_argument("--force", action="store_true", help="Overwrite if non-empty.")


def run_cost(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ... import cost as cost_mod
    base = _work_dir_base(args)
    summary = cost_mod.summarize(work["openalex_id"], base)

    def human(d):
        print(f"Total calls: {d['total_calls']:,}")
        print(f"Total estimated cost: ${d['total_cost_usd_est']:.4f}"
              + (" (some models unpriced)" if d["any_unpriced"] else ""))
        for stage, s in d["by_stage"].items():
            print(f"  {stage:<12} calls={s['calls']:>4}  "
                  f"in={s['in_tokens_est']:>7,}  out={s['out_tokens_est']:>6,}  "
                  f"cost_est=${s['cost_usd_est']:.4f}")

    emit("cost", summary, as_json=args.json_out, human=human)


def run_show(args) -> None:
    from ...errors import SeedNotFound
    from ...seed import resolve_and_cache, work_dir

    what = args.show_what
    base = _work_dir_base(args)
    try:
        work = resolve_and_cache(args.seed, base=base)
    except SeedNotFound as exc:
        emit_error("show", exc, as_json=args.json_out)
        sys.exit(1)

    oid = work["openalex_id"]
    wd = work_dir(oid, base)

    if what == "brief":
        md_path = wd / "impact.md"
        if not md_path.exists():
            emit_error("show", RuntimeError(
                f"No impact.md found at {md_path}. Run: wake citing / classify / bake {args.seed}"
            ), as_json=args.json_out)
            sys.exit(1)
        text = md_path.read_text(encoding="utf-8")
        emit("show", {"markdown": text}, as_json=args.json_out, human=lambda d: print(d["markdown"]))

    elif what == "metrics":
        json_path = wd / "impact.json"
        if not json_path.exists():
            emit_error("show", RuntimeError(
                f"No impact.json found. Run: wake citing / classify / bake {args.seed}"
            ), as_json=args.json_out)
            sys.exit(1)
        from ...io import read_json
        metrics = read_json(json_path)
        emit("show", metrics, as_json=args.json_out, human=lambda d: print(json.dumps(d, indent=2)))

    elif what == "top":
        json_path = wd / "impact.json"
        if not json_path.exists():
            emit_error("show", RuntimeError(
                f"No impact.json found. Run: wake citing / classify / bake {args.seed}"
            ), as_json=args.json_out)
            sys.exit(1)
        from ...io import read_json
        metrics = read_json(json_path)
        top = metrics.get("top_evidence", [])[:args.n]

        def human(t):
            for i, ev in enumerate(t, 1):
                print(
                    f"{i:>3}. [{ev.get('relationship','?'):<22}] "
                    f"{ev.get('title','?')[:60]}  "
                    f"({ev.get('cited_by_count',0):,} cites)"
                )

        emit("show", {"top_evidence": top}, as_json=args.json_out, human=lambda d: human(d["top_evidence"]))

    elif what == "dossier":
        from ...evidence import dossier_json_path, dossier_path
        p = dossier_path(oid, args.citing_id, base)
        if not p.exists():
            if dossier_json_path(oid, args.citing_id, base).exists():
                emit_error("show", RuntimeError(
                    f"Dossier for {args.citing_id} exists but hasn't been rendered yet. "
                    f"Run `wake rebuild {args.seed}` first."
                ), as_json=args.json_out)
            else:
                emit_error("show", RuntimeError(
                    f"No dossier found for {args.citing_id}. Run `wake evidence {args.seed} {args.citing_id}` first."
                ), as_json=args.json_out)
            sys.exit(1)
        text = p.read_text(encoding="utf-8")
        emit("show", {"markdown": text}, as_json=args.json_out, human=lambda d: print(d["markdown"]))


def run_config(args) -> None:
    from ... import config

    if args.config_action == "show":
        text = config.show()
        emit("config", {"text": text, "env": config.env_status()},
             as_json=args.json_out, human=lambda d: print(d["text"]))

    elif args.config_action == "validate":
        report = config.validate_report()

        def human(d):
            if d["ok"]:
                print("[wake] Configuration OK.")
            else:
                for e in d["errors"]:
                    print(f"  ERROR: {e}", file=sys.stderr)

        emit("config", report, as_json=args.json_out, human=human)
        if not report["ok"]:
            sys.exit(1)

    elif args.config_action == "init":
        path, created = config.init_local()
        data = {"path": str(path), "created": created}

        def human(d):
            if d["created"]:
                print(f"[wake] Created {d['path']}")
            else:
                print(f"[wake] Already exists: {d['path']}")

        emit("config", data, as_json=args.json_out, human=human)


def run_skill(args) -> None:
    from ..skill import run_skill as _run
    _run(args)


def run_seed(args) -> None:
    if args.seed_action == "fetch-pdf":
        run_seed_fetch_pdf(args)


def run_seed_fetch_pdf(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    base = _work_dir_base(args)
    quiet = is_quiet(args)

    from_pdf = getattr(args, "from_pdf", None)

    if from_pdf:
        from ...seed_pdf import acquire_seed_pdf_from_path
        try:
            result = acquire_seed_pdf_from_path(
                work, from_pdf, base=base, force=args.force, verbose=not quiet,
            )
        except (FileNotFoundError, ValueError) as exc:
            emit_error("seed", exc, as_json=args.json_out)
            sys.exit(1)
    else:
        from ...seed_pdf import acquire_seed_pdf
        result = acquire_seed_pdf(work, base=base, force=args.force, verbose=not quiet)

    def human(d):
        if d["ok"]:
            print(f"Seed PDF acquired ({d['source']}): {d['path']}")
            if d.get("extracted_text_path"):
                print(f"  Text extracted: {d['extracted_text_path']}")
            else:
                print("  Text extraction failed (scanned PDF?). PDF is still cached.")
        else:
            tried = ", ".join(d.get("tried", [])) or "(no applicable sources)"
            print(f"Could not automatically acquire the seed PDF (tried: {tried}).")
            print("Get one manually and run:")
            print(f"  wake seed fetch-pdf {args.seed} --from-pdf /path/to/paper.pdf")
            for label, url in d.get("fallback_links", {}).items():
                print(f"  {label}: {url}")

    emit("seed", result, as_json=args.json_out, human=human)
