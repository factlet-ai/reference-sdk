"""Smoke tests for the reference SDK.

Run with: pytest python/tests/
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from factlet import (
    Factbook,
    Factlet,
    factsignal,
    load_factbook,
    on_low_factsignal,
    render_for_claude,
    render_for_gemini,
    render_for_gpt,
    retrieve,
)


SAMPLE_YAML = """
schema_version: v1.0
last_updated: 2026-05-04T00:00:00Z
metadata:
  name: payments-test
content:
  - id: f001
    statement: "We use Stripe webhooks (not polling) for payment status updates."
    confidence: 0.95
    sources: ["docs/payments.md:42"]
    tags: [payments, stripe]
  - id: f002
    statement: "Refunds older than 90 days require manual ops approval."
    confidence: 1.0
    sources: ["docs/refund-policy.md:8"]
    tags: [payments, refunds, ops]
  - id: f900
    statement: "Old archived fact about integer customer IDs."
    confidence: 0.0
    sources: ["legacy/customer.py"]
    archived: true
    archived_reason: "superseded by f003"
"""


@pytest.fixture
def factbook(tmp_path):
    p = tmp_path / "factbook.yaml"
    p.write_text(SAMPLE_YAML)
    return load_factbook(str(p))


def test_load_factbook_parses_required_fields(factbook):
    assert factbook.schema_version == "v1.0"
    assert len(factbook.content) == 3
    f1 = factbook.content[0]
    assert f1.id == "f001"
    assert f1.confidence == 0.95
    assert "docs/payments.md:42" in f1.sources


def test_load_factbook_missing_required_field_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        "schema_version: v1.0\n"
        "content:\n"
        "  - id: f001\n"
        "    statement: missing confidence and sources\n"
    )
    with pytest.raises(ValueError, match="missing required field"):
        load_factbook(str(bad))


def test_retrieve_returns_relevant_factlets(factbook):
    results = retrieve("how do refunds work in our system?", factbook)
    assert len(results) >= 1
    assert results[0].id == "f002"  # refund-related fact ranks first


def test_retrieve_excludes_archived_by_default(factbook):
    results = retrieve("integer customer IDs", factbook)
    assert all(not f.archived for f in results)


def test_retrieve_includes_archived_when_requested(factbook):
    results = retrieve("integer customer IDs", factbook, include_archived=True)
    assert any(f.archived for f in results)


def test_factsignal_dead_zone_returns_zero(factbook):
    assert factsignal("kubernetes deployment strategies", factbook) == 0


def test_factsignal_strong_match_high_score(factbook):
    score = factsignal("payments stripe webhooks refunds", factbook)
    assert score >= 3, f"expected >=3 bars for multi-fact query, got {score}"


def test_factsignal_returns_integer_in_range(factbook):
    queries = ["random", "payments", "refunds", "stripe webhooks", "fraud detection"]
    for q in queries:
        score = factsignal(q, factbook)
        assert isinstance(score, int)
        assert 0 <= score <= 5


def test_on_low_factsignal_fires_below_threshold(factbook):
    fired = []

    def cb(query, score, retrieved, threshold):
        fired.append((query, score, threshold))

    score, _ = on_low_factsignal(
        "kubernetes deployment", factbook, threshold=2, callback=cb
    )
    assert score < 2
    assert len(fired) == 1
    assert fired[0][2] == 2


def test_on_low_factsignal_does_not_fire_above_threshold(factbook):
    fired = []

    def cb(*args):
        fired.append(args)

    score, _ = on_low_factsignal(
        "payments stripe refunds", factbook, threshold=2, callback=cb
    )
    assert score >= 2
    assert fired == []


def test_render_for_claude_includes_id_and_confidence(factbook):
    out = render_for_claude(factbook.content[:2])
    assert '<factbook>' in out
    assert 'id="f001"' in out
    assert 'confidence="0.95"' in out


def test_render_for_gpt_uses_markdown(factbook):
    out = render_for_gpt(factbook.content[:2])
    assert out.startswith("## Factbook")
    assert "**f001**" in out
    assert "0.95" in out


def test_render_for_gemini_includes_grounding_instructions(factbook):
    out = render_for_gemini(factbook.content[:2])
    assert "defer to factlets" in out
    assert "f001" in out
    assert "f002" in out
    assert "Cite the factlet id" in out


def test_render_for_gemini_handles_empty_factlet_list():
    out = render_for_gemini([])
    assert "no relevant factlets" in out


def test_dataclass_construction():
    """Direct construction (not from YAML) should also work."""
    f = Factlet(
        id="f100",
        statement="Test fact",
        confidence=0.9,
        sources=["test:1"],
    )
    fb = Factbook(schema_version="v1.0", content=[f])
    assert factsignal("test", fb) >= 1


# ─── RFC-001 / v0.2 strict-scoping validation ────────────────────────────────

VALID_SCOPED_YAML = """
schema_version: v1.0
scope: project:factlet-ai
content:
  - id: f001
    statement: "Internal fact A."
    confidence: 1.0
    sources: ["doc:1"]
    supersedes: []
  - id: f002
    statement: "Internal fact B referencing internal A."
    confidence: 1.0
    sources: ["doc:2"]
    supersedes: [f001]
  - id: f003
    statement: "Fact referencing an external scope."
    confidence: 1.0
    sources: ["doc:3"]
    supersedes: ["kernora:f042"]
"""

DANGLING_BARE_REF_YAML = """
schema_version: v1.0
scope: project:factlet-ai
content:
  - id: f001
    statement: "Has a bare ref that doesn't resolve."
    confidence: 1.0
    sources: ["doc:1"]
    supersedes: [f999]
"""

NO_SCOPE_YAML = """
schema_version: v1.0
content:
  - id: f001
    statement: "Factbook missing top-level scope: field."
    confidence: 1.0
    sources: ["doc:1"]
"""


def _write_tmp_yaml(content: str) -> str:
    from factlet import validate, load_factbook
    p = Path(tempfile.mktemp(suffix=".yaml"))
    p.write_text(content)
    return str(p)


def test_validate_default_lenient_passes_v01_factbook(factbook):
    from factlet import validate
    assert validate(factbook) == []


def test_validate_strict_scoping_passes_when_internal_and_scoped_external():
    from factlet import validate, load_factbook
    fb = load_factbook(_write_tmp_yaml(VALID_SCOPED_YAML))
    errs = validate(fb, strict_scoping=True)
    assert errs == [], errs


def test_validate_strict_scoping_flags_dangling_bare_ref():
    from factlet import validate, load_factbook
    fb = load_factbook(_write_tmp_yaml(DANGLING_BARE_REF_YAML))
    errs = validate(fb, strict_scoping=True)
    assert any("f999" in e and "RFC-001" in e for e in errs), errs


def test_validate_strict_scoping_flags_missing_top_level_scope():
    from factlet import validate, load_factbook
    fb = load_factbook(_write_tmp_yaml(NO_SCOPE_YAML))
    errs = validate(fb, strict_scoping=True)
    assert any("scope:" in e and "RFC-001" in e for e in errs), errs


def test_validate_detects_duplicate_ids():
    from factlet import Factbook, Factlet, validate
    fb = Factbook(
        schema_version="v1.0",
        content=[
            Factlet(id="f001", statement="A", confidence=1.0, sources=["x"]),
            Factlet(id="f001", statement="B", confidence=1.0, sources=["y"]),
        ],
    )
    errs = validate(fb)
    assert any("duplicate id" in e and "f001" in e for e in errs), errs


# ─── v0.2 RFC tests ──────────────────────────────────────────────────────


def test_rfc_0002_known_profile():
    """RFC 0002: SDK reports known profiles via is_profile_known()."""
    from factlet import is_profile_known
    assert is_profile_known("software-engineering") is True
    assert is_profile_known("manufacturing") is False  # future profile, not yet registered


def test_rfc_0002_unknown_profile_warns(tmp_path):
    """RFC 0002 §4: loading a Factbook with unknown profile emits UserWarning."""
    import warnings
    from factlet import load_factbook
    fb_path = tmp_path / "fb.yaml"
    fb_path.write_text(
        "schema_version: v1.0\n"
        "profile: unknown-future-profile\n"
        "content:\n"
        "  - id: f001\n    statement: t\n    confidence: 1.0\n    sources: [x]\n"
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        fb = load_factbook(str(fb_path))
    assert any(issubclass(w.category, UserWarning) and "unknown profile" in str(w.message)
               for w in caught), [str(w.message) for w in caught]
    # Round-trip preservation: profile field still set
    assert fb.profile == "unknown-future-profile"


def test_rfc_0003_origination_round_trip(tmp_path):
    """RFC 0003: origination block parses + survives round-trip."""
    from factlet import load_factbook
    fb_path = tmp_path / "fb.yaml"
    fb_path.write_text(
        "schema_version: v1.0\n"
        "content:\n"
        "  - id: f001\n"
        "    statement: t\n"
        "    confidence: 1.0\n"
        "    sources: [x]\n"
        "    origination:\n"
        "      source_type: llm\n"
        "      source_ref: 'session:abc'\n"
        "      authored_at: '2026-05-08T00:00:00Z'\n"
        "      authored_by: 'llm:claude-opus-4-7'\n"
        "      trust_prior: 0.7\n"
    )
    fb = load_factbook(str(fb_path))
    f = fb.content[0]
    assert f.origination is not None
    assert f.origination.source_type == "llm"
    assert f.origination.source_ref == "session:abc"
    assert f.origination.authored_by == "llm:claude-opus-4-7"
    assert abs(f.origination.trust_prior - 0.7) < 1e-9


def test_rfc_0003_filter_by_source_type():
    """RFC 0003: filter_by_source_type returns only matching factlets."""
    from factlet import Factlet, Origination, filter_by_source_type
    facts = [
        Factlet(id="f001", statement="a", confidence=1.0, sources=["x"],
                origination=Origination(source_type="manual")),
        Factlet(id="f002", statement="b", confidence=1.0, sources=["y"],
                origination=Origination(source_type="llm")),
        Factlet(id="f003", statement="c", confidence=1.0, sources=["z"]),  # no origination
    ]
    manual = filter_by_source_type(facts, "manual")
    assert [f.id for f in manual] == ["f001"]
    llm = filter_by_source_type(facts, "llm")
    assert [f.id for f in llm] == ["f002"]
    none_match = filter_by_source_type(facts, "import")
    assert none_match == []


def test_rfc_0004_dependencies_parse(tmp_path):
    """RFC 0004: dependencies.factbooks parses with all sub-fields."""
    from factlet import load_factbook
    fb_path = tmp_path / "fb.yaml"
    fb_path.write_text(
        "schema_version: v1.0\n"
        "dependencies:\n"
        "  factbooks:\n"
        "    - id: 'best-practices:python-3.12-2026'\n"
        "      version: 'v1.2'\n"
        "      source: 'github.com/factlet-ai/registry/best-practices-python-3.12-2026'\n"
        "      trust_prior: 0.9\n"
        "      retrieval_mode: merged\n"
        "    - id: 'security:owasp-top-10-2026'\n"
        "      retrieval_mode: fallback\n"
        "content:\n"
        "  - id: f001\n    statement: t\n    confidence: 1.0\n    sources: [x]\n"
    )
    fb = load_factbook(str(fb_path))
    assert len(fb.dependencies) == 2
    d1 = fb.dependencies[0]
    assert d1.id == "best-practices:python-3.12-2026"
    assert d1.version == "v1.2"
    assert d1.retrieval_mode == "merged"
    assert abs(d1.trust_prior - 0.9) < 1e-9
    d2 = fb.dependencies[1]
    assert d2.retrieval_mode == "fallback"
    assert d2.trust_prior is None


def test_rfc_0004_retrieval_mode_invalid_falls_back_to_merged(tmp_path):
    """RFC 0004: invalid retrieval_mode value defaults to merged."""
    from factlet import load_factbook
    fb_path = tmp_path / "fb.yaml"
    fb_path.write_text(
        "schema_version: v1.0\n"
        "dependencies:\n"
        "  factbooks:\n"
        "    - id: 'x:y'\n"
        "      retrieval_mode: bogus\n"
        "content:\n"
        "  - id: f001\n    statement: t\n    confidence: 1.0\n    sources: [x]\n"
    )
    fb = load_factbook(str(fb_path))
    assert fb.dependencies[0].retrieval_mode == "merged"


def test_rfc_0004_cycle_detection():
    """RFC 0004 §5: detect_cycles raises CycleDetected on circular graph."""
    from factlet import Factbook, FactbookDependency, detect_cycles, CycleDetected

    fb_a = Factbook(schema_version="v1.0", content=[],
                    dependencies=[FactbookDependency(id="b")])
    fb_b = Factbook(schema_version="v1.0", content=[],
                    dependencies=[FactbookDependency(id="a")])

    def resolver(fb_id: str):
        return {"a": fb_a, "b": fb_b}.get(fb_id)

    try:
        detect_cycles("a", resolver)
        assert False, "expected CycleDetected"
    except CycleDetected as e:
        assert "cycle" in str(e).lower()


def test_rfc_0004_no_cycle_passes():
    """RFC 0004 §5: detect_cycles returns silently on acyclic graph."""
    from factlet import Factbook, FactbookDependency, detect_cycles

    fb_a = Factbook(schema_version="v1.0", content=[],
                    dependencies=[FactbookDependency(id="b")])
    fb_b = Factbook(schema_version="v1.0", content=[],
                    dependencies=[FactbookDependency(id="c")])
    fb_c = Factbook(schema_version="v1.0", content=[])  # leaf

    def resolver(fb_id: str):
        return {"a": fb_a, "b": fb_b, "c": fb_c}.get(fb_id)

    detect_cycles("a", resolver)  # should not raise


def test_rfc_0005_phase_filter():
    """RFC 0005: filter_by_phase returns matching + phase-agnostic factlets."""
    from factlet import Factlet, filter_by_phase
    facts = [
        Factlet(id="f001", statement="a", confidence=1.0, sources=["x"], phase="design"),
        Factlet(id="f002", statement="b", confidence=1.0, sources=["y"], phase="implementation"),
        Factlet(id="f003", statement="c", confidence=1.0, sources=["z"]),  # phase-agnostic
        Factlet(id="f004", statement="d", confidence=1.0, sources=["w"], phase="runtime"),
    ]
    impl = filter_by_phase(facts, "implementation")
    # Should return f002 (matches) + f003 (phase-agnostic) per RFC 0005 §5
    ids = [f.id for f in impl]
    assert "f002" in ids
    assert "f003" in ids
    assert "f001" not in ids
    assert "f004" not in ids


def test_rfc_0005_phase_filter_invalid_raises():
    """RFC 0005: filter_by_phase rejects values outside the enum."""
    from factlet import filter_by_phase
    try:
        filter_by_phase([], "deployment")
        assert False, "expected ValueError"
    except ValueError as e:
        assert "phase must be" in str(e)


def test_rfc_0005_validate_profile_fields(tmp_path):
    """RFC 0002 + 0005: validate_profile_fields rejects out-of-enum phase."""
    from factlet import load_factbook, validate_profile_fields
    fb_path = tmp_path / "fb.yaml"
    fb_path.write_text(
        "schema_version: v1.0\n"
        "profile: software-engineering\n"
        "content:\n"
        "  - id: f001\n    statement: t\n    confidence: 1.0\n    sources: [x]\n    phase: design\n"
        "  - id: f002\n    statement: t\n    confidence: 1.0\n    sources: [y]\n    phase: deployment\n"
    )
    fb = load_factbook(str(fb_path))
    errs = validate_profile_fields(fb)
    assert len(errs) == 1
    assert "f002" in errs[0]
    assert "phase" in errs[0]
    assert "deployment" in errs[0]


def test_rfc_0005_validate_no_profile_no_op():
    """RFC 0002: profile-neutral Factbook → validate_profile_fields is a no-op."""
    from factlet import Factbook, Factlet, validate_profile_fields
    fb = Factbook(
        schema_version="v1.0",
        content=[Factlet(id="f001", statement="t", confidence=1.0, sources=["x"], phase="anything")],
        # no profile declared
    )
    errs = validate_profile_fields(fb)
    assert errs == []
