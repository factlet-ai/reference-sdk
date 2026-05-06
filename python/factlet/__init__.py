"""Factlet Protocol reference SDK (Python).

Implements the v0.1 spec at https://github.com/factlet-ai/spec/blob/main/SPEC.md.

Public API:

    from factlet import load_factbook, retrieve, factsignal, on_low_factsignal

    fb = load_factbook("factbook.yaml")
    facts = retrieve("how do refunds work?", fb)
    bars = factsignal("how do refunds work?", fb)
    on_low_factsignal(query, fb, threshold=2,
                     callback=lambda q, score, retrieved, t: print(f"Low: {score} bars"))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional
import re
import yaml  # PyYAML

__version__ = "0.1.0"
SPEC_VERSION = "v1.0"


@dataclass
class Factlet:
    """One atomic, source-cited truth. See SPEC.md §3."""
    id: str
    statement: str
    confidence: float
    sources: list[str]
    tags: list[str] = field(default_factory=list)
    scope_level: Optional[str] = None
    supersedes: list[str] = field(default_factory=list)
    merged_into: Optional[str] = None
    archived: bool = False
    archived_reason: Optional[str] = None
    retired_at: Optional[str] = None
    extension: dict[str, Any] = field(default_factory=dict)


@dataclass
class Factbook:
    """A packaged FactMap. See SPEC.md §5."""
    schema_version: str
    content: list[Factlet]
    last_updated: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


def load_factbook(path: str) -> Factbook:
    """Parse a YAML/JSON Factbook from disk into a Factbook object.

    Validates required fields per SPEC.md §3.1. Raises ValueError on
    structural issues; does not enforce confidence range etc. (use the
    JSON Schema from factlet-ai/spec for full validation).
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"Factbook root must be a mapping, got {type(raw).__name__}")
    if "schema_version" not in raw or "content" not in raw:
        raise ValueError("Factbook MUST have schema_version and content (SPEC.md §5.1)")

    facts: list[Factlet] = []
    for i, item in enumerate(raw["content"] or []):
        if not isinstance(item, dict):
            raise ValueError(f"content[{i}] must be a mapping")
        for required in ("id", "statement", "confidence", "sources"):
            if required not in item:
                raise ValueError(f"content[{i}] missing required field '{required}' (SPEC.md §3.1)")
        sources = item["sources"]
        if not isinstance(sources, list) or not sources:
            raise ValueError(f"content[{i}].sources must be a non-empty list")
        facts.append(Factlet(
            id=str(item["id"]),
            statement=str(item["statement"]),
            confidence=float(item["confidence"]),
            sources=[str(s) for s in sources],
            tags=list(item.get("tags") or []),
            scope_level=item.get("scope_level"),
            supersedes=list(item.get("supersedes") or []),
            merged_into=item.get("merged_into"),
            archived=bool(item.get("archived", False)),
            archived_reason=item.get("archived_reason"),
            retired_at=item.get("retired_at"),
            extension=dict(item.get("extension") or {}),
        ))
    return Factbook(
        schema_version=str(raw["schema_version"]),
        content=facts,
        last_updated=raw.get("last_updated"),
        metadata=dict(raw.get("metadata") or {}),
    )


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def retrieve(query: str, factbook: Factbook, *, include_archived: bool = False) -> list[Factlet]:
    """Return factlets relevant to the query, ordered by relevance.

    Reference algorithm: token-overlap scoring across statement + tags.
    Implementations MAY use embeddings, BM25, graph distance, etc. The
    contract is the relevance ordering, not the algorithm (SPEC.md §4).
    """
    query_tokens = set(_tokenize(query))
    if not query_tokens:
        return []

    scored: list[tuple[float, Factlet]] = []
    for fact in factbook.content:
        if fact.archived and not include_archived:
            continue
        text_tokens = set(_tokenize(fact.statement)) | {t.lower() for t in fact.tags}
        if not text_tokens:
            continue
        overlap = len(query_tokens & text_tokens)
        if overlap == 0:
            continue
        # Weighted by confidence so high-confidence facts rank higher.
        score = overlap * (0.5 + fact.confidence * 0.5)
        scored.append((score, fact))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [fact for _, fact in scored]


def factsignal(query: str, factbook: Factbook) -> int:
    """Return FactSignal bars (0-5) for the query against the factbook.

    Reference algorithm: maps the count and quality of retrieved factlets
    to bars per SPEC.md §6. Implementations MAY use embeddings or other
    scoring; the contract is the integer 0-5 output.
    """
    retrieved = retrieve(query, factbook)
    if not retrieved:
        return 0
    n = len(retrieved)
    # Top-result confidence as a quality proxy.
    top_conf = retrieved[0].confidence

    if n >= 4 and top_conf >= 0.85:
        return 5
    if n >= 2 and top_conf >= 0.75:
        return 4
    if n >= 2:
        return 3
    if top_conf >= 0.7:
        return 2
    return 1


def on_low_factsignal(
    query: str,
    factbook: Factbook,
    *,
    threshold: int = 2,
    callback: Optional[Callable[[str, int, list[Factlet], int], None]] = None,
) -> tuple[int, list[Factlet]]:
    """Compute FactSignal and invoke callback if below threshold.

    See SPEC.md §7. Returns (score, retrieved_factlets) regardless of
    whether the callback fired, so the consuming agent can act on the
    score directly too.
    """
    score = factsignal(query, factbook)
    retrieved = retrieve(query, factbook)
    if score < threshold and callback is not None:
        callback(query, score, retrieved, threshold)
    return score, retrieved


def render_for_claude(factlets: Iterable[Factlet]) -> str:
    """Render factlets as Anthropic-flavored XML for system blocks (§8)."""
    parts = ["<factbook>"]
    for f in factlets:
        parts.append(
            f'  <factlet id="{f.id}" confidence="{f.confidence:.2f}">'
            f"\n    <statement>{f.statement}</statement>"
            f"\n    <sources>{', '.join(f.sources)}</sources>"
            f"\n  </factlet>"
        )
    parts.append("</factbook>")
    return "\n".join(parts)


def render_for_gpt(factlets: Iterable[Factlet]) -> str:
    """Render factlets as Markdown for GPT system messages (§8)."""
    lines = ["## Factbook (private team facts — defer over training data)"]
    for f in factlets:
        lines.append(
            f"- **{f.id}** ({f.confidence:.2f}): {f.statement} "
            f"_(sources: {', '.join(f.sources)})_"
        )
    return "\n".join(lines)


def render_for_gemini(factlets: Iterable[Factlet]) -> str:
    """Render factlets for Gemini's systemInstruction field (§8).

    Gemini works best with explicit grounding instructions followed by
    a structured factlet list. Cite-the-id discipline is included so
    answers reference fact_ids the user can audit.
    """
    factlets = list(factlets)
    lines = [
        "You have access to a private Factbook with team-specific truths.",
        "When answering, defer to factlets over your training data.",
        "Cite the factlet id (e.g. 'per f001') whenever you use one.",
        "If no factlet covers part of the question, say so explicitly.",
        "",
        "## Factbook",
    ]
    if not factlets:
        lines.append("(no relevant factlets retrieved — answer from training data)")
    else:
        for f in factlets:
            lines.append(
                f"- {f.id} (confidence {f.confidence:.2f}): {f.statement} "
                f"[sources: {', '.join(f.sources)}]"
            )
    return "\n".join(lines)


_SCOPED_REF_RE = re.compile(r"^[a-z][a-z0-9-]*:[a-zA-Z0-9_-]+$")
_BARE_REF_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate(factbook: Factbook, *, strict_scoping: bool = False) -> list[str]:
    """Validate a parsed Factbook against the v0.1 spec.

    Returns a list of error messages. Empty list means valid.

    Per RFC-001 (factlet-ai/spec rfcs/0001-scoped-fact-ids.md, targeting v0.2):
    when ``strict_scoping=True``, references to other factlets in
    ``supersedes``, ``merged_into``, and reference-shaped fields MUST use the
    scoped form ``<scope>:<id>`` (e.g. ``factlet-ai:f001``) when pointing to
    facts outside this Factbook. Bare IDs (``f001``) are valid only for
    references to facts inside this same Factbook.

    The file-level ``scope:`` field (when present in the raw YAML, captured
    in ``Factbook.metadata['scope']``) is treated as the implicit prefix for
    all bare IDs declared in this file. Internal cross-references using the
    bare form are allowed; external references (different scope) MUST be
    scoped.

    Conformance: this is a v0.1-permissive default (``strict_scoping=False``).
    Setting the flag opts in to v0.2 RFC-001 conformance and MAY emit errors
    that the v0.1 spec does not flag.
    """
    errors: list[str] = []

    # 1. ID uniqueness within file (v0.1 §3.1)
    seen_ids: set[str] = set()
    for fact in factbook.content:
        if fact.id in seen_ids:
            errors.append(f"duplicate id '{fact.id}' (SPEC §3.1: id MUST be unique within a Factbook)")
        seen_ids.add(fact.id)

    # 2. Required fields already enforced at parse time by load_factbook;
    #    validate() exists to layer additional schema checks like §3.1 ID shape.

    # 3. Strict scoping per RFC-001 (v0.2 forward-conformance check)
    if not strict_scoping:
        return errors

    file_scope = (factbook.metadata or {}).get("scope")
    # File-level scope is needed to disambiguate "is this an internal or external ref?"
    if not file_scope:
        errors.append(
            "strict_scoping requires a top-level `scope:` field in the Factbook YAML "
            "(per RFC-001). Add e.g. `scope: project:my-team`."
        )
        # Continue checking refs against bare-only namespace.
        file_scope = None

    def _check_ref(ref: str, where: str) -> None:
        if _SCOPED_REF_RE.match(ref):
            # Scoped form is always valid; we don't cross-repo-resolve in the SDK.
            return
        if _BARE_REF_RE.match(ref):
            # Bare form: must resolve within this file.
            if ref not in seen_ids:
                errors.append(
                    f"{where}: bare reference '{ref}' does not exist in this Factbook. "
                    f"Either fix the id, or use the scoped form '<scope>:{ref}' for external refs (RFC-001)."
                )
            return
        errors.append(
            f"{where}: reference '{ref}' is neither a bare id nor a scoped <scope>:<id> form (RFC-001)."
        )

    for fact in factbook.content:
        for sup in fact.supersedes:
            _check_ref(sup, where=f"factlet '{fact.id}'.supersedes")
        if fact.merged_into:
            _check_ref(fact.merged_into, where=f"factlet '{fact.id}'.merged_into")

    return errors


# Capture file-level metadata fields the parser doesn't already extract.
_orig_load = load_factbook
def load_factbook(path: str) -> Factbook:  # type: ignore[no-redef]
    """Parse a YAML/JSON Factbook from disk.

    Same as the original loader but also captures file-level fields like
    `scope:` into ``Factbook.metadata`` so callers (e.g. ``validate``) can
    consult them. See SPEC.md §3.1 + RFC-001.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    fb = _orig_load(path)
    if isinstance(raw, dict):
        # Top-level fields useful for validation (scope, name, version, lifecycle).
        for key in ("scope", "name", "version", "id", "pack_type", "lifecycle"):
            if key in raw and key not in fb.metadata:
                fb.metadata[key] = raw[key]
    return fb


__all__ = [
    "Factlet",
    "Factbook",
    "load_factbook",
    "retrieve",
    "factsignal",
    "on_low_factsignal",
    "render_for_claude",
    "render_for_gpt",
    "render_for_gemini",
    "validate",
    "SPEC_VERSION",
    "__version__",
]
