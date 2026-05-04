# factlet — Python reference SDK

Reference Python implementation of the [Factlet Protocol v0.1](https://github.com/factlet-ai/spec).

Minimal, dependency-light (only PyYAML), MIT-licensed. Intended as the canonical example against which other implementations validate.

## Install

```bash
pip install -e .
```

(PyPI release once v0.1 spec stabilizes.)

## Quick usage

```python
from factlet import load_factbook, retrieve, factsignal, on_low_factsignal

fb = load_factbook("factbook.yaml")

# Retrieve relevant factlets for a query
facts = retrieve("how do refunds work?", fb)
for f in facts:
    print(f.id, f.statement)

# Score coverage (0-5 bars)
bars = factsignal("how do refunds work?", fb)

# Runtime callback when grounding is thin
def warn(query, score, retrieved, threshold):
    print(f"Low FactSignal ({score} bars) for: {query}")

score, retrieved = on_low_factsignal(
    "fraud detection in checkout",
    fb,
    threshold=2,
    callback=warn,
)
```

## Render for vendors

```python
from factlet import render_for_claude, render_for_gpt

# Anthropic-flavored XML for system blocks
xml = render_for_claude(facts)

# Markdown for GPT system messages
md = render_for_gpt(facts)
```

## Run tests

```bash
pip install -e ".[dev]"
pytest tests/
```

13 tests cover: factbook parsing (and validation errors), retrieval (with and without archived facts), FactSignal scoring (dead zone through dense coverage), low-FactSignal callback firing logic, and vendor rendering.

## Architecture notes

- **Retrieval algorithm**: token-overlap with confidence weighting. Per [SPEC.md §4](https://github.com/factlet-ai/spec/blob/main/SPEC.md#4-factmap), implementations MAY use embeddings, BM25, etc. — the contract is the relevance ordering, not the algorithm.
- **FactSignal scoring**: maps retrieved factlet count + top-result confidence to bars. Per [SPEC.md §6](https://github.com/factlet-ai/spec/blob/main/SPEC.md#6-factsignal), the contract is the integer 0-5, not the algorithm.
- **No embeddings, no LLM calls**: this reference SDK is intentionally simple so it's easy to read, fast to run, and has no external service dependencies. Production implementations (e.g. [Kernora's Nora](https://kernora.ai)) layer embedding-based retrieval and LLM-based scoring on top of the same protocol contract.

## License

MIT — see [LICENSE](../LICENSE).
