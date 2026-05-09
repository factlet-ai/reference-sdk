"""Factlet Protocol reference SDK (Python).

Implements the v0.1 spec at https://github.com/factlet-ai/spec/blob/main/SPEC.md
and the v0.2 additions ratified by RFCs 0002 (Profiles mechanism), 0003
(Origination provenance block), 0004 (Composable factbooks via dependencies),
and 0005 (Software Profile — phase enum).

Public API (v0.1 — unchanged):

    from factlet import load_factbook, retrieve, factsignal, on_low_factsignal

    fb = load_factbook("factbook.yaml")
    facts = retrieve("how do refunds work?", fb)
    bars = factsignal("how do refunds work?", fb)
    on_low_factsignal(query, fb, threshold=2,
                     callback=lambda q, score, retrieved, t: print(f"Low: {score} bars"))

Public API (v0.2 additions):

    # RFC 0002 — Profiles mechanism
    fb.profile                         # "software-engineering" or None
    fb.profile_version                 # "0.2" or None
    is_profile_known("software-engineering")  # True

    # RFC 0003 — Origination provenance block
    fact.origination                   # Origination(...) or None
    filter_by_source_type(facts, "manual")
    filter_by_source_type(facts, "llm")

    # RFC 0004 — Dependencies
    fb.dependencies                    # list[FactbookDependency]
    detect_cycles(fb_chain)            # raises CycleDetected on cycles

    # RFC 0005 — Software Profile (phase enum)
    fact.phase                         # "design" / "implementation" / "testing" / "runtime" / None
    filter_by_phase(facts, "implementation")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional
import re
import warnings
import yaml  # PyYAML

__version__ = "0.2.0"
SPEC_VERSION = "v1.0"  # base spec version; v0.2 additions are additive

# ─── RFC 0002 — Profiles mechanism ────────────────────────────────────────
# Registered profiles known to this SDK. Profiles add domain-specific
# vocabulary on top of the base spec. Adding a profile here enables
# profile-specific schema validation when a Factbook declares it.
KNOWN_PROFILES: dict[str, dict[str, Any]] = {
    "software-engineering": {
        # RFC 0005 — phase enum on factlets within software-engineering profile
        "factlet_fields": {
            "phase": {"type": "enum", "values": ["design", "implementation", "testing", "runtime"]},
        },
    },
    # Future: "manufacturing", "healthcare", "legal" via separate sub-RFCs.
}


def is_profile_known(profile: str) -> bool:
    """Return True if this SDK has schema-extension support for the named profile.

    Per RFC 0002 §4: an SDK that does not know a profile MUST still parse
    Factbooks declaring it (round-trip preservation), but only profile-aware
    SDKs apply richer validation.
    """
    return profile in KNOWN_PROFILES


@dataclass
class Origination:
    """Provenance of the factlet RECORD itself (RFC 0003).

    Distinct from `Factlet.sources` which provides provenance for the
    underlying CLAIM. `Origination` records WHO/WHAT produced the YAML
    record, WHEN, BY WHOM, and with what PRIOR TRUST level.

    The `source_type` enum is profile-extensible per RFC 0003 §2.1 —
    registered Profiles MAY add domain-specific source_type values
    (e.g. a future Manufacturing Profile may add `opc-ua-server`,
    `historian-extract`).
    """
    source_type: str  # manual | llm | import | forward-pass | reverse-pass | <profile-extension>
    source_ref: Optional[str] = None
    authored_at: Optional[str] = None
    authored_by: Optional[str] = None
    trust_prior: Optional[float] = None


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
    # v0.2 additions:
    origination: Optional[Origination] = None  # RFC 0003
    profile: Optional[str] = None              # RFC 0002 — per-factlet profile override
    phase: Optional[str] = None                # RFC 0005 — software-engineering profile (design|implementation|testing|runtime)


@dataclass
class FactbookDependency:
    """Declared dependency on another Factbook for composition (RFC 0004).

    `retrieval_mode`:
        - "merged" (default): union of host + dependency factlets
        - "fallback": dependency consulted only when host returns nothing
        - "disabled": recorded for documentation; excluded from retrieval
    """
    id: str
    version: Optional[str] = None
    source: Optional[str] = None
    trust_prior: Optional[float] = None
    retrieval_mode: str = "merged"


@dataclass
class Factbook:
    """A packaged FactMap. See SPEC.md §5."""
    schema_version: str
    content: list[Factlet]
    last_updated: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    # v0.2 additions:
    profile: Optional[str] = None                 # RFC 0002 — file-level profile
    profile_version: Optional[str] = None         # RFC 0002 — profile schema version
    dependencies: list[FactbookDependency] = field(default_factory=list)  # RFC 0004


def _parse_origination(item: dict[str, Any]) -> Optional[Origination]:
    """Parse the optional origination block per RFC 0003."""
    block = item.get("origination")
    if not block or not isinstance(block, dict):
        return None
    if "source_type" not in block:
        return None  # source_type is required within the block; treat malformed as absent
    return Origination(
        source_type=str(block["source_type"]),
        source_ref=block.get("source_ref"),
        authored_at=block.get("authored_at"),
        authored_by=block.get("authored_by"),
        trust_prior=float(block["trust_prior"]) if block.get("trust_prior") is not None else None,
    )


def _parse_dependencies(raw: dict[str, Any]) -> list[FactbookDependency]:
    """Parse the optional dependencies block per RFC 0004."""
    deps_block = raw.get("dependencies")
    if not deps_block or not isinstance(deps_block, dict):
        return []
    factbooks = deps_block.get("factbooks") or []
    if not isinstance(factbooks, list):
        return []
    deps: list[FactbookDependency] = []
    for entry in factbooks:
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        mode = entry.get("retrieval_mode", "merged")
        if mode not in ("merged", "fallback", "disabled"):
            mode = "merged"
        deps.append(FactbookDependency(
            id=str(entry["id"]),
            version=entry.get("version"),
            source=entry.get("source"),
            trust_prior=float(entry["trust_prior"]) if entry.get("trust_prior") is not None else None,
            retrieval_mode=mode,
        ))
    return deps


def load_factbook(path: str) -> Factbook:
    """Parse a YAML/JSON Factbook from disk into a Factbook object.

    Validates required fields per SPEC.md §3.1. Raises ValueError on
    structural issues; does not enforce confidence range etc. (use the
    JSON Schema from factlet-ai/spec for full validation).

    v0.2 additions (RFCs 0002, 0003, 0004, 0005):
      - Parses optional `profile` and `profile_version` at Factbook root.
      - Parses optional `dependencies.factbooks` list.
      - Parses optional `origination` block on each factlet.
      - Parses optional per-factlet `profile` override.
      - Parses optional `phase` field on factlets (semantic only when
        the Factbook declares `profile: software-engineering`).
      - Captures other top-level fields like `scope`, `name`, `version`
        into `metadata` for downstream use (e.g. validate()).
      - Emits a UserWarning when an unknown profile is declared
        (per RFC 0002 §4 conformance) — preserves the field on
        round-trip without applying profile-specific validation.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"Factbook root must be a mapping, got {type(raw).__name__}")
    if "schema_version" not in raw or "content" not in raw:
        raise ValueError("Factbook MUST have schema_version and content (SPEC.md §5.1)")

    # v0.2 — profile fields at root
    profile = raw.get("profile")
    profile_version = raw.get("profile_version")
    if profile and not is_profile_known(str(profile)):
        warnings.warn(
            f"Factbook declares unknown profile '{profile}'. "
            f"Per RFC 0002 §4, this SDK will preserve profile-specific fields on "
            f"round-trip but cannot apply profile-specific validation. "
            f"Known profiles: {sorted(KNOWN_PROFILES)}",
            UserWarning,
            stacklevel=2,
        )

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
            origination=_parse_origination(item),
            profile=item.get("profile"),
            phase=item.get("phase"),
        ))

    fb = Factbook(
        schema_version=str(raw["schema_version"]),
        content=facts,
        last_updated=raw.get("last_updated"),
        metadata=dict(raw.get("metadata") or {}),
        profile=profile,
        profile_version=profile_version,
        dependencies=_parse_dependencies(raw),
    )

    # Capture file-level metadata fields for downstream validators.
    for key in ("scope", "name", "version", "id", "pack_type", "lifecycle"):
        if key in raw and key not in fb.metadata:
            fb.metadata[key] = raw[key]

    return fb


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


# NOTE: file-level metadata capture (scope/name/version/etc.) and v0.2 field
# parsing (profile/profile_version/dependencies/origination/phase) are now
# integrated directly into load_factbook() above. The previous _orig_load
# decorator pattern was removed for clarity.


# ─── RFC 0003 + RFC 0005 — query helpers ──────────────────────────────────

def filter_by_source_type(facts: Iterable[Factlet], source_type: str) -> list[Factlet]:
    """Filter factlets by `origination.source_type` (RFC 0003 §2).

    Returns factlets whose `origination` block has the given source_type.
    Factlets with no origination block are excluded. Useful for audit
    queries like "what fraction of cited facts were LLM-proposed?".
    """
    return [f for f in facts if f.origination and f.origination.source_type == source_type]


def filter_by_phase(facts: Iterable[Factlet], phase: str) -> list[Factlet]:
    """Filter factlets by `phase` (RFC 0005, software-engineering profile).

    Returns factlets whose `phase` matches OR are phase-agnostic (phase is
    None — relevant across phases per RFC 0005 §2). This matches the
    recommended consumer behavior: when scoping retrieval to a phase,
    include phase-agnostic factlets too.

    `phase` MUST be one of: design, implementation, testing, runtime.
    """
    if phase not in ("design", "implementation", "testing", "runtime"):
        raise ValueError(
            f"phase must be one of design/implementation/testing/runtime; got '{phase}'"
        )
    return [f for f in facts if f.phase is None or f.phase == phase]


# ─── RFC 0004 — dependency cycle detection ────────────────────────────────

class CycleDetected(Exception):
    """Raised by `detect_cycles` when the dependency graph contains a cycle."""


def detect_cycles(
    factbook_id: str,
    resolver: Callable[[str], Optional[Factbook]],
    _visiting: Optional[set[str]] = None,
) -> None:
    """Detect cycles in a Factbook dependency graph (RFC 0004 §5).

    `resolver(id)` returns the resolved Factbook for a dependency id, or
    None if it cannot be resolved (treated as a leaf — no further
    descent). Implementations supply their own resolver (filesystem,
    registry HTTP, etc.) — the SDK does not mandate a specific one.

    Raises `CycleDetected` if a cycle is found in the transitive graph.
    """
    if _visiting is None:
        _visiting = set()
    if factbook_id in _visiting:
        raise CycleDetected(
            f"dependency cycle detected: '{factbook_id}' transitively depends on itself"
        )
    _visiting.add(factbook_id)
    fb = resolver(factbook_id)
    if fb is not None:
        for dep in fb.dependencies:
            if dep.retrieval_mode == "disabled":
                continue
            detect_cycles(dep.id, resolver, _visiting)
    _visiting.remove(factbook_id)


# ─── RFC 0002 + 0005 — profile-specific schema validation ────────────────

def validate_profile_fields(factbook: Factbook) -> list[str]:
    """Apply profile-specific schema validation per RFC 0002 §4.

    For each factlet in a Factbook declaring a known profile, verify
    profile-specific fields. Returns a list of error strings (empty on
    success). Factbooks declaring unknown profiles return [] — preservation
    happens at parse time; validation is no-op for unknown profiles.

    For software-engineering profile (RFC 0005): validates `phase` is one
    of {design, implementation, testing, runtime} when present.
    """
    errors: list[str] = []
    if not factbook.profile or not is_profile_known(factbook.profile):
        return errors

    profile_spec = KNOWN_PROFILES[factbook.profile]
    factlet_field_specs = profile_spec.get("factlet_fields", {})

    for fact in factbook.content:
        # Per-factlet profile override: only validate against named profile
        # if the factlet's profile matches the file profile (or is unset).
        if fact.profile and fact.profile != factbook.profile:
            continue
        for field_name, spec in factlet_field_specs.items():
            value = getattr(fact, field_name, None)
            if value is None:
                continue  # field is optional
            if spec["type"] == "enum" and value not in spec["values"]:
                errors.append(
                    f"factlet '{fact.id}': field '{field_name}' value '{value}' is not in "
                    f"profile '{factbook.profile}' enum {spec['values']}"
                )
    return errors


__all__ = [
    "Factlet",
    "Factbook",
    "Origination",
    "FactbookDependency",
    "load_factbook",
    "retrieve",
    "factsignal",
    "on_low_factsignal",
    "render_for_claude",
    "render_for_gpt",
    "render_for_gemini",
    "validate",
    "validate_profile_fields",
    "filter_by_source_type",
    "filter_by_phase",
    "detect_cycles",
    "CycleDetected",
    "is_profile_known",
    "KNOWN_PROFILES",
    "SPEC_VERSION",
    "__version__",
]
