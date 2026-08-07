# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""wake evidence (full-text verification dossiers).

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


def _build_evidence_parser(sub) -> None:
    p = sub.add_parser(
        "evidence",
        help="Full-text verification of one citing work's provisional classification: "
             "fetches the PDF, reads the whole document, and proposes a relationship "
             "with quoted, page-cited supporting passages. Never auto-applied -- "
             "the agent presents the finding to the human and runs `wake override` "
             "on their behalf once accepted.",
    )
    p.add_argument("seed", help="DOI, arXiv ID, OpenAlex ID, or title.")
    p.add_argument("citing_id", nargs="?", default=None,
                   help="OpenAlex ID of the citing work to investigate. Omit when using "
                        "--rerender-all.")
    p.add_argument("--force", action="store_true",
                   help="Re-run verification even if a dossier already exists. Also: "
                        "when used with --from-pdf, bypasses the metadata-mismatch "
                        "refusal but still runs the check and logs any mismatch.")
    p.add_argument("--from-pdf", metavar="PATH",
                   help="Path to a locally-obtained PDF for this citing work. "
                        "wake validates that the PDF matches the citing work's metadata "
                        "(title similarity, author name, DOI) before copying it into the "
                        "packet and running full-text verification. Refuses on mismatch "
                        "unless --force is also given (mismatch is always logged).")
    p.add_argument("--rerender-all", action="store_true",
                   help="Re-emit every evidence dossier's .md from its .json sidecar -- "
                        "a rendering-only pass (no LLM call, no PDF fetch, no state "
                        "change) that refreshes derived content like the \"Referenced "
                        "by\" back-link line. Use after a wake upgrade changes dossier "
                        "rendering, to backfill an existing wiki. Mutually exclusive "
                        "with citing_id/--force/--from-pdf.")


def _find_classified_work(seed_id: str, citing_id: str, base) -> dict | None:
    """Find a citing work's *classified* record (with relationship/
    confidence/justification), falling back to the plain citing-works
    record if it hasn't been classified yet."""
    from ...classify import load_classified
    classified = load_classified(seed_id, base) or []
    for w in classified:
        if w.get("openalex_id") == citing_id:
            return w
    return _find_citing_work(seed_id, citing_id, base)


def _run_evidence_from_pdf(args, seed_work, citing_work, pdf_path_str, base, quiet):
    """Handle `wake evidence --from-pdf PATH`: validate PDF metadata, copy
    into the packet, then run build_dossier on it. The metadata check always
    runs; --force bypasses the copy refusal but does not suppress the check."""
    import shutil
    from pathlib import Path as _Path

    from ...evidence import build_dossier
    from ...evidence_wiki import append_log_entry
    from ...pdf_fetch import pdf_path as _pdf_dest_path
    from ...pdf_verify import check_pdf_metadata
    from ...sources.pdf_abstract import extract_lead_text

    seed_id = seed_work["openalex_id"]
    citing_id = citing_work["openalex_id"]
    supplied = _Path(pdf_path_str).expanduser().resolve()

    if not supplied.exists():
        emit_error("evidence", FileNotFoundError(f"PDF not found: {supplied}"), as_json=args.json_out)
        sys.exit(1)

    if not quiet:
        print(f"[wake] Extracting lead text for metadata check: {supplied}", file=sys.stderr)
    lead_text = extract_lead_text(supplied, max_pages=3)

    check = check_pdf_metadata(citing_work, lead_text)

    log_event = "pdf_supplied_verified" if check["ok"] else "pdf_supplied_mismatch"
    if not check["ok"] and args.force:
        log_event = "pdf_forced_despite_mismatch"
    append_log_entry(
        seed_id, event=log_event, citing_id=citing_id,
        detail=(
            f"title_sim={check['title_similarity']:.2f} "
            f"author={check['author_matched']} "
            f"doi={check['doi_found']}"
        ),
        seed_title=seed_work.get("title"), base=base,
    )

    if not check["ok"] and not args.force:
        emit_error("evidence", ValueError(check["message"]), as_json=args.json_out)
        sys.exit(1)

    dest = _pdf_dest_path(seed_id, citing_id, base)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(supplied, dest)
    if not quiet:
        print(f"[wake] PDF copied to: {dest}", file=sys.stderr)
        if not check["ok"]:
            print(f"[wake] WARN: metadata mismatch overridden (--force): {check['message']}", file=sys.stderr)

    return build_dossier(seed_work, citing_work, base=base, force=True, verbose=not quiet)


def run_evidence(args) -> None:
    work = _resolve_seed_to_work(args.seed, args)
    from ...evidence import build_dossier
    base = _work_dir_base(args)
    seed_id = work["openalex_id"]
    quiet = is_quiet(args)

    if getattr(args, "rerender_all", False):
        from ...evidence import rerender_all_dossiers
        rerendered = rerender_all_dossiers(seed_id, work, base=base)
        emit(
            "evidence", {"ok": True, "rerendered": rerendered, "count": len(rerendered)},
            as_json=args.json_out,
            human=lambda d: print(f"Re-rendered {d['count']} dossier(s)."),
        )
        return

    if not args.citing_id:
        emit_error("evidence", ValueError(
            "citing_id is required unless --rerender-all is given."
        ), as_json=args.json_out)
        sys.exit(1)

    citing_work = _find_classified_work(seed_id, args.citing_id, base)
    if citing_work is None:
        emit_error("evidence", RuntimeError(
            f"{args.citing_id} not found in cached citing works. "
            f"Run `wake citing {args.seed}` first."
        ), as_json=args.json_out)
        sys.exit(1)
    if not citing_work.get("relationship"):
        emit_error("evidence", RuntimeError(
            f"{args.citing_id} has not been classified yet. "
            f"Run `wake classify {args.seed} --ids {args.citing_id}` first "
            "so there's a provisional classification to verify against."
        ), as_json=args.json_out)
        sys.exit(1)

    from_pdf = getattr(args, "from_pdf", None)
    if from_pdf:
        result = _run_evidence_from_pdf(args, work, citing_work, from_pdf, base, quiet)
    else:
        result = build_dossier(work, citing_work, base=base, force=args.force, verbose=not quiet)

    def human(d):
        if not d["ok"]:
            if d["reason"] == "no_pdf":
                fr = d["fetch_result"]
                tried = ", ".join(fr.get("tried", [])) or "(no applicable sources)"
                print(f"Could not acquire a PDF to verify against (tried: {tried}).")
                print("Try one of these manually, then run:")
                print(f"  wake fetch-pdf {args.seed} {args.citing_id}  (after obtaining a PDF)")
                for label, url in fr.get("fallback_links", {}).items():
                    print(f"  {label}: {url}")
            else:
                print(f"Evidence verification failed: {d.get('message', d['reason'])}")
            return

        title = d.get("citing_title") or args.citing_id
        authors = d.get("citing_authors") or []
        author_str = ", ".join(authors[:8]) + (" et al." if len(authors) > 8 else "")
        print(f"  {title}")
        if author_str:
            print(f"  {author_str}")
        print()

        prov = d["provisional"]
        prop = d["proposed"]
        print(f"Provisional (abstract-only): {prov['relationship']} (confidence {prov['confidence']:.2f})")
        print(f"Proposed (full-text reading): {prop['relationship']} (confidence {prop['confidence']:.2f})")
        print(f"  {prop['justification']}")
        # A dossier can genuinely propose more than one facet (see
        # evidence.py's multi-facet schema) -- the scalars above are
        # always the top (most-confident) one; list any others too so
        # a second well-supported reading isn't hidden from the CLI.
        other_facets = (prop.get("relationships") or [])[1:]
        for f in other_facets:
            print(f"  + also: {f['label']} (confidence: {f.get('confidence', 0):.2f}) — {f.get('justification', '')}")
        if not prop["agrees_with_provisional"]:
            print("  -> differs from the provisional guess")
        print()

        quotes = d.get("quotes") or []
        if quotes:
            shown = quotes[:3]
            remaining = len(quotes) - len(shown)
            print(f"{len(quotes)} supporting passage(s) — paste verbatim to the human, not a paraphrase:")
            print()
            for q in shown:
                page = q.get("page")
                page_str = f"p. {page}" if page else "page unknown"
                print(f"  [{page_str}]")
                for line in q["text"].splitlines():
                    print(f"  > {line}")
                if q.get("note"):
                    print(f"  ({q['note']})")
                print()
            if remaining:
                print(f"  (+ {remaining} more — see dossier: {d['dossier_path']})")
                print()
        else:
            print("No supporting passages found in the full text.")
            print()

        print(
            "This is a proposed finding, not applied to the brief. Present the "
            "quoted passages above to the human, then run `wake override` yourself "
            "once they accept or adjust it — never ask the human to run the "
            "override command."
        )
        if d.get("rebuild_needed"):
            print(f"Run `wake rebuild {args.seed}` to render this dossier's Markdown.")

    emit("evidence", result, as_json=args.json_out, human=human)
