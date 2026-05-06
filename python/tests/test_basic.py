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
