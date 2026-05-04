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


__all__ = [
    "Factlet",
    "Factbook",
    "load_factbook",
    "retrieve",
    "factsignal",
    "on_low_factsignal",
    "render_for_claude",
    "render_for_gpt",
    "SPEC_VERSION",
    "__version__",
]
