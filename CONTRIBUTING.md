# Contributing to the reference SDK

The reference SDK is the authoritative implementation of the Factlet Protocol — other implementations test against it. Keep it minimal, dependency-light, and correct.

## Repository layout

```
python/        # Reference Python implementation
typescript/    # Reference TypeScript implementation
tests/         # Cross-language test fixtures (shared)
examples/      # Runnable usage examples
```

## Development

### Python

```bash
cd python/
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

### TypeScript

```bash
cd typescript/
npm install
npm test
```

## Pull request guidelines

- All PRs must pass CI (lint + test) on both Python and TypeScript when behavior is shared.
- Behavioral changes require corresponding test additions in `tests/` (shared fixtures).
- Spec-divergence is a bug: if the SDK behavior diverges from the published spec, fix the SDK or open an RFC against the spec — never silently divergent.
- Keep dependencies minimal. New dependencies require justification in the PR description.
- Public API changes require a CHANGELOG entry and follow semver.

## Issue triage

- **Bug** → file an issue with reproduction steps and expected vs actual behavior
- **Feature** → if it implies a spec change, open an RFC against `factlet-ai/spec` first
- **Security** → see [SECURITY.md](SECURITY.md)

## Code of Conduct

Participation requires adherence to the [Code of Conduct](CODE_OF_CONDUCT.md).
