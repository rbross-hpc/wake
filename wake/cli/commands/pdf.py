# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake fill-abstract / wake fetch-pdf.

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

from ..emit import emit, emit_error, is_quiet
from ..main_helpers import _find_citing_work, _resolve_seed_to_work, _work_dir_base


def _build_fill_abstract_parser(sub) -> None:
    p = sub.add_parser(
        "fill-abstract",
        help="Manually resolve a missing abstract for one citing work, "
             "from a local PDF's lead pages or human-supplied text.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("citing_id", help="OpenAlex ID of the citing work to fill in.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-pdf", metavar="PATH",
                      help="Path to a locally-downloaded PDF of the citing work. "
                           "Extracts the first few pages (config.pdf_extract.max_pages, "
                           "default 3) and asks an LLM to locate the abstract within them.")
    src.add_argument("--text", metavar="TEXT",
                      help="The abstract text itself, supplied directly (no LLM call).")


def _build_fetch_pdf_parser(sub) -> None:
    p = sub.add_parser(
        "fetch-pdf",
        help="Try to automatically acquire a PDF for one citing work "
             "(OSTI, Semantic Scholar, Unpaywall, arXiv, optional CORE). "
             "Falls back to human-actionable links (incl. Google Scholar) on failure.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("citing_id", help="OpenAlex ID of the citing work to fetch a PDF for.")
    p.add_argument("--force", action="store_true", help="Re-fetch even if already cached.")


def run_fill_abstract(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...gaps import fill_from_pdf, fill_from_text
    base = _work_dir_base(args)
    seed_id = work["openalex_id"]

    try:
        if args.from_pdf:
            entry = fill_from_pdf(seed_id, args.citing_id, args.from_pdf, base=base)
        else:
            entry = fill_from_text(seed_id, args.citing_id, args.text, base=base)
    except (FileNotFoundError, ValueError, ImportError) as exc:
        emit_error("fill-abstract", exc, as_json=args.json_out)
        sys.exit(1)

    def human(d):
        print(f"Abstract recorded for {args.citing_id} (source: {d['abstract_source']}):")
        print(f"  {d['abstract'][:300]}{'...' if len(d['abstract']) > 300 else ''}")
        print()
        print("This will be picked up automatically the next time you run:")
        print(f"  wake classify {args.seed} --ids {args.citing_id} --force")

    emit("fill-abstract", entry, as_json=args.json_out, human=human)


def run_fetch_pdf(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...pdf_fetch import fetch_pdf
    base = _work_dir_base(args)
    seed_id = work["openalex_id"]
    quiet = is_quiet(args)

    citing_work = _find_citing_work(seed_id, args.citing_id, base)
    if citing_work is None:
        emit_error("fetch-pdf", RuntimeError(
            f"{args.citing_id} not found in cached citing works. "
            f"Run `wake citing {args.seed}` first."
        ), as_json=args.json_out)
        sys.exit(1)

    result = fetch_pdf(
        seed_id, args.citing_id,
        doi=citing_work.get("doi"),
        title=citing_work.get("title"),
        oa_pdf_url=citing_work.get("oa_pdf_url"),
        primo_pdf_url=citing_work.get("primo_pdf_url"),
        seed_title=work.get("title"),
        base=base,
        force=args.force,
        verbose=not quiet,
    )

    def human(d):
        if d["ok"]:
            print(f"PDF acquired via {d['source']}: {d['path']}")
        else:
            tried = ", ".join(d["tried"]) if d["tried"] else "(no applicable sources)"
            print(f"Could not automatically acquire a PDF (tried: {tried}).")
            print("Try one of these manually:")
            for label, url in d["fallback_links"].items():
                print(f"  {label}: {url}")

    emit("fetch-pdf", result, as_json=args.json_out, human=human)
