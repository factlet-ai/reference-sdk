# Security policy

## Reporting a vulnerability

If you discover a security vulnerability in the Factlet Protocol specification, reference SDK, or registry tooling, please report it privately.

**Do not open a public issue.** Instead:

- Use GitHub's private vulnerability reporting: open the **Security** tab on the affected repository → **Report a vulnerability**.
- Or email **hello@kernora.ai** with a description of the issue, reproduction steps, and your contact information.

We will acknowledge your report within 3 business days and aim to provide a remediation timeline within 10 business days. Coordinated disclosure timelines are negotiable depending on severity and complexity.

## Scope

In scope:
- The Factlet Protocol specification (parsing, schema, semantics that could lead to consumer-side vulnerabilities)
- Reference SDK code (Python + TypeScript)
- Registry tooling and example factbooks (e.g. malicious factbook content that exploits a reader)

Out of scope:
- Vulnerabilities in third-party LLM providers consuming Factbook artifacts
- Vulnerabilities in non-reference implementations of the protocol (please report to those projects directly)

## Supported versions

The latest released version of the v0.1 specification and reference SDK receives security fixes. Pre-v1.0, breaking changes may accompany security fixes when necessary.

## Recognition

We credit reporters in release notes unless anonymity is requested.
