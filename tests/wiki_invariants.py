# BSD 3-Clause License
# Copyright (c) 2026, UChicago Argonne, LLC, Argonne National Laboratory.
"""Reusable correctness invariants for wake's rendered wiki output
(dossiers, themes, narrative sections/outline/stitched doc, impact.md,
README.md).

There is no formal external schema for "OKF" or for Obsidian-flavored
Markdown to validate against -- both are conventions, not specifications.
These helpers instead encode the specific correctness properties wake's
own renderers are supposed to guarantee, distilled from real bugs found
in this wiki's rendered output (see git history for
`_render_refs_in_section_prose`'s `[[ID]](path)` double-bracket bug and
`stitch()`'s `<a name>`/`#rN` Obsidian-incompatible anchor bug). Each
helper raises AssertionError with a descriptive message on failure, so
these read the same as a normal `assert` inside a test.

Not a general-purpose Markdown or Obsidian linter -- deliberately scoped
to the small set of properties wake's own generated content must
satisfy, not to arbitrary hand-authored notes in a vault.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

_MALFORMED_WIKILINK_RE = re.compile(r"\[\[[^\]]+\]\]\(")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_BLOCK_ID_RE = re.compile(r"\^([A-Za-z0-9-]+)\s*$", re.MULTILINE)

KNOWN_TYPES = {
    "wiki-home",
    "impact-brief",
    "narrative",
    "narrative-outline",
    "narrative-section",
    "theme",
    "citing-work-evidence",
    "index",
    "log",
}

# Required frontmatter keys per `type:` value, over and above `type`
# itself. Intentionally a loose lower bound (only keys every renderer
# unconditionally writes) rather than a full schema -- optional fields
# (e.g. impact-brief's seed_doi, only present when the seed has a DOI)
# are not enforced here.
REQUIRED_KEYS_BY_TYPE: dict[str, set[str]] = {
    "wiki-home": {"title", "timestamp"},
    "impact-brief": {
        "title", "seed_openalex_id", "citing_count", "verified_count",
        "provisional_count", "themes_confirmed", "themes_draft",
        "narrative_status", "seed_pdf_status", "generated_at", "tags",
    },
    "narrative": {
        "title", "seed_openalex_id", "confirmed_sections", "draft_sections",
        "missing_sections", "reference_count", "timestamp", "tags",
    },
    "narrative-outline": {"title", "timestamp"},
    "narrative-section": {"title", "tags", "timestamp"},
    "theme": {"title", "description", "tags", "timestamp"},
    "citing-work-evidence": {"title", "description", "resource", "tags", "timestamp"},
    "index": {"title", "timestamp"},
    "log": {"title"},
}


def assert_no_malformed_wikilinks(text: str, source: str | Path = "<text>") -> None:
    """A `[[ID]]` Obsidian wikilink immediately followed by a standard
    Markdown `(...)` parenthetical is not valid syntax anywhere -- the
    `[[ID]]` is consumed as a self-contained wikilink (resolved by
    filename search across the whole vault in Obsidian, rendered as
    literal bracket text everywhere else), and the trailing `(...)` is
    left as orphaned, visible plain text. wake's own cross-links must
    always be plain `[text](path)`, never this mixed form."""
    m = _MALFORMED_WIKILINK_RE.search(text)
    if m:
        raise AssertionError(
            f"{source}: found malformed '[[...]](' mixed wikilink/Markdown-link "
            f"syntax at position {m.start()}: {text[m.start():m.start() + 60]!r}. "
            "Use a plain [text](path) link instead."
        )


def assert_frontmatter_valid(
    text: str,
    source: str | Path = "<text>",
    *,
    expected_type: str | None = None,
) -> dict[str, Any]:
    """Parse and validate a rendered wiki `.md`'s YAML frontmatter block.

    Asserts: frontmatter is present, parses as a YAML mapping, has a
    `type` key drawn from KNOWN_TYPES (or matching *expected_type* if
    given), and includes every key REQUIRED_KEYS_BY_TYPE lists for that
    type. Returns the parsed frontmatter dict for further assertions.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise AssertionError(f"{source}: missing YAML frontmatter block (expected leading '---\\n...\\n---\\n').")

    try:
        frontmatter = yaml.safe_load(m.group(1))
    except yaml.YAMLError as exc:
        raise AssertionError(f"{source}: frontmatter is not valid YAML: {exc}") from exc

    if not isinstance(frontmatter, dict):
        raise AssertionError(f"{source}: frontmatter did not parse as a mapping: {frontmatter!r}")

    doc_type = frontmatter.get("type")
    if doc_type not in KNOWN_TYPES:
        raise AssertionError(f"{source}: frontmatter 'type: {doc_type!r}' is not one of the known types {KNOWN_TYPES}.")
    if expected_type is not None and doc_type != expected_type:
        raise AssertionError(f"{source}: expected type {expected_type!r}, got {doc_type!r}.")

    required = REQUIRED_KEYS_BY_TYPE.get(doc_type, set())
    missing = required - frontmatter.keys()
    if missing:
        raise AssertionError(f"{source}: frontmatter for type {doc_type!r} is missing required key(s): {sorted(missing)}.")

    return frontmatter


def _iter_markdown_links(text: str):
    """Yield (link_text, target) for every `[text](target)` Markdown
    link in *text*, in order of appearance."""
    for m in _MD_LINK_RE.finditer(text):
        yield m.group(1), m.group(2)


def assert_all_relative_md_links_exist(text: str, source_path: Path, wiki_root: Path) -> None:
    """Every relative link in *text* pointing at another file in this
    wiki must resolve to a file that actually exists on disk, resolved
    relative to *source_path*'s own directory (the same rule any
    Markdown renderer, Obsidian included, uses for a relative link).

    Skips: external links (http(s)://, mailto:), fragment-only links
    (#foo, #^foo -- same-file anchors, checked separately by
    assert_r_anchors_resolve), and links whose target isn't a .md file
    (e.g. a plain OpenAlex ID reference with no link at all is fine;
    this only checks well-formed [text](path) links).
    """
    for link_text, target in _iter_markdown_links(text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if target.startswith("#"):
            continue
        target_path_str = target.split("#", 1)[0]
        if not target_path_str:
            continue
        resolved = (source_path.parent / target_path_str).resolve()
        if not resolved.exists():
            raise AssertionError(
                f"{source_path}: link [{link_text}]({target}) points at "
                f"{resolved}, which does not exist (wiki_root={wiki_root})."
            )


def assert_ref_link_syntax(
    text: str,
    *,
    ids_with_dossier: set[str],
    ids_without_dossier: set[str],
    seed_linked: bool = False,
    source: str | Path = "<text>",
) -> None:
    """For a rendered narrative section `.md`, assert every citing ID in
    *ids_with_dossier* appears as a plain `[ID](../../evidence/ID.md)`
    link, every ID in *ids_without_dossier* appears as the untouched raw
    `[ref:ID]` marker (nothing to link to), and -- if *seed_linked* --
    `[SEED](../../impact.md)` appears for the seed reference. No other
    rendering of these markers is valid; in particular no `[[ID]]`
    wikilink form and no leftover `[ref:ID]` for an ID that does have a
    dossier."""
    for cid in ids_with_dossier:
        expected = f"[{cid}](../../evidence/{cid}.md)"
        if expected not in text:
            raise AssertionError(f"{source}: expected dossier link {expected!r} not found.")
        if f"[ref:{cid}]" in text:
            raise AssertionError(f"{source}: raw marker [ref:{cid}] left unrendered despite a dossier existing.")

    for cid in ids_without_dossier:
        expected = f"[ref:{cid}]"
        if expected not in text:
            raise AssertionError(f"{source}: expected raw marker {expected!r} (no dossier) not found.")

    if seed_linked:
        expected = "[SEED](../../impact.md)"
        if expected not in text:
            raise AssertionError(f"{source}: expected SEED link {expected!r} not found.")


def assert_r_anchors_resolve(text: str, source: str | Path = "<text>") -> None:
    """For a stitched `narrative.md`: every in-prose `[R<n>](#^r<n>)`
    link must have a matching `^r<n>` Obsidian block ID somewhere in the
    document (in practice, at the end of its References-list entry), and
    the count of distinct R-numbers referenced in prose must equal the
    count of block IDs defined -- no dangling links, no unused anchors.
    Also asserts no leftover `<a name=...>` HTML anchors (Obsidian
    ignores these as navigation targets) and no bare `#rN`
    non-block-ID fragment links remain from the pre-Obsidian-fix form.
    """
    if "<a name" in text:
        raise AssertionError(f"{source}: found a leftover HTML '<a name=...>' anchor -- Obsidian does not navigate to these.")

    prose_link_re = re.compile(r"\[R(\d+)\]\(#\^r(\d+)\)")
    bare_fragment_re = re.compile(r"\[R\d+\]\(#r\d+\)")
    if bare_fragment_re.search(text):
        raise AssertionError(
            f"{source}: found a bare '[R<n>](#r<n>)' fragment link (missing the '^' block-ID "
            "marker) -- this form does not navigate in Obsidian."
        )

    prose_numbers = set()
    for m in prose_link_re.finditer(text):
        n1, n2 = m.group(1), m.group(2)
        if n1 != n2:
            raise AssertionError(f"{source}: [R{n1}] links to #^r{n2} -- mismatched numbers.")
        prose_numbers.add(n1)

    block_ids = set(_BLOCK_ID_RE.findall(text))
    block_ids = {b[1:] for b in block_ids if b.startswith("r") and b[1:].isdigit()}

    missing = prose_numbers - block_ids
    if missing:
        raise AssertionError(f"{source}: [R<n>] link(s) with no matching ^r<n> block ID: {sorted(missing)}.")

    unused = block_ids - prose_numbers
    if unused:
        raise AssertionError(f"{source}: ^r<n> block ID(s) with no matching in-prose [R<n>] link: {sorted(unused)}.")


# Frontmatter keys that hold a path relative to the file's own directory
# (as opposed to e.g. `resource:`, which is an external URL). Only
# `citing-work-evidence`'s `pdf:` exists today; a dict (not a flat set)
# so a future type can add its own path-valued key without ambiguity.
PATH_KEYS_BY_TYPE: dict[str, set[str]] = {
    "citing-work-evidence": {"pdf"},
}


def assert_frontmatter_relative_paths_resolve(
    frontmatter: dict[str, Any], source_path: Path,
) -> None:
    """For any frontmatter key in PATH_KEYS_BY_TYPE[doc_type] that is
    present, assert its value is a relative (not absolute) path and that
    it resolves to a real file relative to *source_path*'s own directory.

    These keys are optional (e.g. a dossier with no cached PDF omits
    `pdf:` entirely), so a missing key is not itself a failure -- call
    this after assert_frontmatter_valid() has already confirmed the
    required keys are present.
    """
    doc_type = frontmatter.get("type")
    for key in PATH_KEYS_BY_TYPE.get(doc_type, set()):
        value = frontmatter.get(key)
        if not value:
            continue
        if Path(value).is_absolute():
            raise AssertionError(
                f"{source_path}: frontmatter '{key}: {value!r}' is an absolute path -- "
                "should be relative to this file's own directory so the wiki stays "
                "portable if wake-out/<seed>/ is moved."
            )
        resolved = (source_path.parent / value).resolve()
        if not resolved.exists():
            raise AssertionError(
                f"{source_path}: frontmatter '{key}: {value!r}' resolves to "
                f"{resolved}, which does not exist."
            )


# Mirrors classify.py's CANONICAL_RELATIONSHIPS/MAX_FACETS/
# MIN_FACET_CONFIDENCE -- duplicated here (rather than imported) so this
# test-only module has no import-time dependency on wake's package
# internals, consistent with the rest of this file's "encode the
# properties, don't import the implementation" approach.
_CANONICAL_RELATIONSHIPS = frozenset({
    "extends", "builds-on", "uses-as-tool", "benchmarks",
    "applies-to-domain", "related-infrastructure", "background-mention",
})
_MAX_FACETS = 3
_MIN_FACET_CONFIDENCE = 0.5


def assert_agents_md_declares_all_types(
    agents_md_text: str, rendered_md_files: list[Path], source: str | Path = "AGENTS.md",
) -> None:
    """An agent handed the wiki folder cold relies on AGENTS.md's
    "Frontmatter `type:` values" section to know every concept-doc shape
    it might encounter. This walks every actually-rendered `.md` file,
    collects its frontmatter `type:` value (skipping AGENTS.md/README.md,
    which carry no frontmatter), and asserts each one is mentioned
    somewhere in AGENTS.md's text -- catching the case where a new
    artifact type is added to the renderers but AGENTS.md's hand-written
    schema section is never updated to describe it.
    """
    seen_types: set[str] = set()
    for md_path in rendered_md_files:
        if md_path.name in {"AGENTS.md", "README.md"}:
            continue
        text = md_path.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            continue
        try:
            frontmatter = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            continue
        if isinstance(frontmatter, dict) and frontmatter.get("type"):
            seen_types.add(frontmatter["type"])

    missing = {t for t in seen_types if f"`{t}`" not in agents_md_text}
    if missing:
        raise AssertionError(
            f"{source}: frontmatter type(s) {sorted(missing)} appear in the "
            "rendered wiki but are not mentioned in AGENTS.md's schema "
            "section -- an agent reading only AGENTS.md would not know "
            "this file type exists."
        )


def assert_facet_list_valid(facets: list[dict[str, Any]], source: str | Path = "<text>") -> None:
    """Validate a multi-facet "relationships" list (see classify.py's
    module docstring for the schema: a citing work's relationship to the
    seed is sometimes genuinely more than one story, e.g. both
    "uses-as-tool" and "applies-to-domain").

    Asserts: the list is non-empty, has at most _MAX_FACETS entries, every
    facet has a label drawn from _CANONICAL_RELATIONSHIPS, every facet's
    confidence is a number in [_MIN_FACET_CONFIDENCE, 1.0], and facets are
    ordered confidence-descending (ties allowed in either order).

    Not called unconditionally by assert_frontmatter_valid -- callers
    that have a facets list in hand (e.g. from a dossier's parsed JSON
    sidecar) call this directly; a dossier's rendered .md alone doesn't
    expose per-facet confidence values, only labels via its tags.
    """
    if not facets:
        raise AssertionError(f"{source}: facets list is empty -- must always have at least one facet.")
    if len(facets) > _MAX_FACETS:
        raise AssertionError(f"{source}: facets list has {len(facets)} entries, exceeding MAX_FACETS={_MAX_FACETS}.")

    prev_confidence = None
    for i, f in enumerate(facets):
        label = f.get("label")
        if label not in _CANONICAL_RELATIONSHIPS:
            raise AssertionError(f"{source}: facet {i} has unknown label {label!r}.")
        confidence = f.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise AssertionError(f"{source}: facet {i} ({label!r}) confidence {confidence!r} is not a number.")
        if not (_MIN_FACET_CONFIDENCE <= confidence <= 1.0):
            raise AssertionError(
                f"{source}: facet {i} ({label!r}) confidence {confidence} is outside "
                f"[{_MIN_FACET_CONFIDENCE}, 1.0]."
            )
        if prev_confidence is not None and confidence > prev_confidence:
            raise AssertionError(
                f"{source}: facets are not confidence-descending -- facet {i} ({label!r}, "
                f"{confidence}) follows a higher-confidence facet ({prev_confidence})."
            )
        prev_confidence = confidence
