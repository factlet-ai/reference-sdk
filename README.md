# Factlet Protocol — reference SDK

Minimal Python and TypeScript reference implementations of the [Factlet Protocol](https://factlet.ai). Other implementations test against these.

## Status

**Pre-v0.1 implementation in progress.** APIs unstable. Pin to a specific commit for any consumption until v0.1.0 ships.

## Layout

```
python/        # Reference Python implementation
typescript/    # Reference TypeScript implementation
tests/         # Cross-language test fixtures (shared)
examples/      # Runnable usage examples
```

## What this SDK does

The reference SDK implements the five protocol primitives (factlet / FactMap / Factbook / FactSignal / low-FactSignal warning) in the smallest, most dependency-light way possible. It is not optimized for production use — it is the canonical example against which other implementations validate.

For production use, see [Kernora's Nora](https://kernora.ai), which is a production-grade implementation of the protocol.

## Develop

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).

## Code of Conduct

[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Security

Vulnerability disclosure: see [SECURITY.md](SECURITY.md).
