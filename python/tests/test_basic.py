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
