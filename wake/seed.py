# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Resolve a seed identifier (DOI, arXiv ID, OpenAlex ID, or title) to a canonical work."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from . import config
from .errors import SeedNotFound
from .io import atomic_write_json, now_iso, read_json
from .sources.openalex import (
    get_work_by_doi,
    get_work_by_arxiv_id,
    get_work_by_openalex_id,
    search_work_by_title,
)
from .state import is_stage_current, mark_stage_complete

_STAGE = "seed"
_VERSION = "seed-1"


def _is_openalex_id(s: str) -> bool:
    return bool(re.match(r"^W\d+$", s, re.IGNORECASE)) or "openalex.org" in s


def _is_arxiv_id(s: str) -> bool:
    return bool(re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", s)) or s.lower().startswith("arxiv:")


def _is_doi(s: str) -> bool:
    return (
        s.startswith("10.")
        or s.lower().startswith("doi:")
        or "doi.org" in s.lower()
    )


def resolve(seed: str) -> dict[str, Any]:
    """Resolve a seed string to a canonical OpenAlex work dict.

    Tries DOI → arXiv → OpenAlex ID → title search in order.
    Raises SeedNotFound if nothing matches.
    """
    seed = seed.strip()

    work: dict | None = None

    if _is_openalex_id(seed):
        work = get_work_by_openalex_id(seed)
        if work:
            return work

    if _is_arxiv_id(seed):
        bare = re.sub(r"^arxiv:\s*", "", seed, flags=re.IGNORECASE)
        work = get_work_by_arxiv_id(bare)
        if work:
            return work

    if _is_doi(seed):
        work = get_work_by_doi(seed)
        if work:
            return work

    work = search_work_by_title(seed)
    if work:
        return work

    raise SeedNotFound(
        f"Could not resolve seed to an OpenAlex work: {seed!r}\n"
        "Try a DOI (10.xxxx/...), arXiv ID (2301.12345), "
        "OpenAlex ID (W2156077349), or the paper title."
    )


def work_dir(openalex_id: str, base: Path | None = None) -> Path:
    """Return the cache directory for a given seed OpenAlex ID.

    Resolution order for the root: explicit *base* argument, then
    the WAKE_WORK_DIR environment variable, then the current directory.
    In all cases the seed's artifacts live under <root>/wake-out/<id>/.
    """
    if base is not None:
        root = base
    else:
        env_root = os.environ.get("WAKE_WORK_DIR", "").strip()
        root = Path(env_root) if env_root else Path.cwd()
    return root / "wake-out" / openalex_id


def load_seed(openalex_id: str, base: Path | None = None) -> dict[str, Any] | None:
    """Load cached seed.json if present."""
    p = work_dir(openalex_id, base) / "seed.json"
    if not p.exists():
        return None
    return read_json(p)


def resolve_and_cache(seed: str, base: Path | None = None, force: bool = False) -> dict[str, Any]:
    """Resolve seed and cache the result; return cached if current.

    After writing seed.json, automatically attempts to acquire the seed
    paper's own PDF if `pdf_fetch.seed_pdf_at_resolve` is true in config
    (the default). The attempt is always silent on failure -- a missing
    seed PDF is surfaced via wake status and the fallback-links message,
    not by blocking resolve. This means resolve is idempotent: re-running
    on a cached seed skips the metadata re-fetch but still tries to get
    the PDF if it isn't already cached.
    """
    work = resolve(seed)
    oid = work["openalex_id"]
    wd = work_dir(oid, base)

    if not force and is_stage_current(wd, _STAGE, seed_id=oid, prompt_version=_VERSION):
        cached = load_seed(oid, base)
        if cached:
            _maybe_auto_fetch_seed_pdf(cached, base=base, verbose=True)
            return cached

    wd.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {**work, "resolved_at": now_iso()}
    atomic_write_json(wd / "seed.json", payload)
    mark_stage_complete(wd, _STAGE, seed_id=oid, prompt_version=_VERSION)
    _maybe_auto_fetch_seed_pdf(payload, base=base, verbose=True)
    return load_seed(oid, base) or payload


def _maybe_auto_fetch_seed_pdf(
    seed_work: dict[str, Any],
    *,
    base: Path | None = None,
    verbose: bool = True,
) -> None:
    """Auto-attempt the seed PDF fetch if enabled and not already cached.
    Never raises -- any failure is recorded in seed.json and logged but
    never propagates to the caller.
    """
    cfg = config.pdf_fetch_cfg()
    if not cfg.get("seed_pdf_at_resolve", True):
        return

    from .pdf_fetch import seed_pdf_path
    seed_id = seed_work["openalex_id"]
    dest = seed_pdf_path(seed_id, base)
    if dest.exists():
        return

    existing = load_seed(seed_id, base) or {}
    if existing.get("seed_pdf", {}).get("path") is None and "attempted_at" in existing.get("seed_pdf", {}):
        return

    try:
        from .seed_pdf import acquire_seed_pdf
        result = acquire_seed_pdf(seed_work, base=base, verbose=verbose)
        if not result["ok"] and verbose:
            title = seed_work.get("title", seed_id)
            tried = ", ".join(result.get("tried", [])) or "none applicable"
            print(
                f"[wake] Could not automatically acquire the seed PDF (tried: {tried}).\n"
                f"       The agent will need your help finding it. Once you have it, run:\n"
                f"         wake seed fetch-pdf \"{title}\" --from-pdf /path/to/paper.pdf\n"
                f"       Or try one of these links:",
                file=sys.stderr,
            )
            for label, url in result.get("fallback_links", {}).items():
                print(f"         {label}: {url}", file=sys.stderr)
    except Exception:
        pass


def print_seed_table(work: dict[str, Any]) -> None:
    """Print a human-readable one-page summary of the seed work."""
    print(f"Title   : {work.get('title', 'N/A')}")
    print(f"Authors : {', '.join(work.get('authors', [])[:5])}"
          + (" et al." if len(work.get('authors', [])) > 5 else ""))
    print(f"Year    : {work.get('year', 'N/A')}")
    print(f"Venue   : {work.get('venue', 'N/A')}")
    print(f"DOI     : {work.get('doi', 'N/A')}")
    print(f"OA ID   : {work.get('openalex_id', 'N/A')}")
    print(f"Cited   : {work.get('cited_by_count', 0):,} times")
    if work.get("abstract"):
        print(f"Abstract: {work['abstract'][:300]}...")
