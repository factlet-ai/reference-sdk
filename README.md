# Factlet Protocol — reference SDK

Reference implementations of the [Factlet Protocol v0.1](https://github.com/factlet-ai/spec/blob/main/SPEC.md). Other implementations validate against these.

## Status

| Implementation | Status | Tests | Path |
|---|---|---|---|
| **Python** | ✅ Working v0.1.0 | 13 passing | [`python/`](python/) |
| **TypeScript** | ⚠️ Planned for v0.1.1 (not yet implemented) | — | [`typescript/`](typescript/) |

Python ships first to lock the contract via tests; TypeScript ports byte-identical behavior next. We chose this over simultaneous development to avoid diverging implementations during the protocol's pre-v1.0 phase.

## Quick start (Python)

```bash
cd python/
pip install -e .
python -c "from factlet import load_factbook, factsignal; \
  fb = load_factbook('../../registry/examples/payments/payments-factbook.yaml'); \
  print(factsignal('how do refunds work?', fb))"
```

## Public API

The five protocol primitives, exposed as callable functions:

- `load_factbook(path)` → `Factbook` — parses YAML/JSON Factbook from disk
- `retrieve(query, factbook)` → `list[Factlet]` — relevance-ordered factlets (§4)
- `factsignal(query, factbook)` → `int` — coverage bars 0-5 (§6)
- `on_low_factsignal(query, factbook, threshold, callback)` → `(score, retrieved)` — runtime warning hook (§7)
- `render_for_claude(factlets)` / `render_for_gpt(factlets)` → `str` — vendor-flavored rendering (§8)

See [python/README.md](python/README.md) for full usage and [python/tests/test_basic.py](python/tests/test_basic.py) for behavior under each scenario.

## Algorithm contracts vs choices

Per [SPEC.md §4](https://github.com/factlet-ai/spec/blob/main/SPEC.md#4-factmap) and [§6](https://github.com/factlet-ai/spec/blob/main/SPEC.md#6-factsignal), implementations choose their own retrieval and scoring algorithms. The reference SDK uses:

- **Retrieval**: token-overlap weighted by confidence. Simple, fast, deterministic.
- **FactSignal**: maps (retrieved factlet count) × (top-result confidence) to bars 0-5.

Production implementations (e.g. [Kernora's Nora](https://kernora.ai)) layer embedding-based retrieval and LLM-based scoring on top of the same protocol contract.

## Contribute

See [CONTRIBUTING.md](CONTRIBUTING.md). Behavioral changes require corresponding test additions; spec divergence is a bug.

## License

MIT — see [LICENSE](LICENSE).
