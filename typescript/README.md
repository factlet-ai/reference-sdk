# factlet — TypeScript reference SDK

**Status: not yet implemented.** The TypeScript reference SDK is planned for v0.1.1, after the Python implementation has stabilized and the spec ships v0.1 final.

## Why Python first

The reference SDK is the canonical example against which other implementations validate. To avoid diverging behavior between two simultaneously-evolving implementations, we ship Python first, lock the contract via the Python test suite, and then port to TypeScript with byte-identical behavior on the shared test fixtures.

## Want to help?

Open an issue or PR — the API surface mirrors the Python SDK at [`../python/factlet/__init__.py`](../python/factlet/__init__.py):

```typescript
import { loadFactbook, retrieve, factsignal, onLowFactsignal } from "factlet";

const fb = loadFactbook("factbook.yaml");
const facts = retrieve("how do refunds work?", fb);
const bars = factsignal("how do refunds work?", fb);
```

Same algorithm contracts apply (see [SPEC.md §4 and §6](https://github.com/factlet-ai/spec/blob/main/SPEC.md)).

## Production users

If you need a TypeScript implementation today, look at how [Kernora's Nora](https://kernora.ai) wraps the Python SDK from its TypeScript-based desktop app, or wait for v0.1.1.

## License

MIT — see [LICENSE](../LICENSE).
