# Contributing to RTL-ASS

Contributions must preserve the Codex-first boundary: helpers may inspect, retrieve, and normalize evidence, but they must not choose or apply RTL patches. Only open-source runtime tools are accepted.

## Workflow

1. Open an issue for public-contract or schema changes.
2. Make one coherent change with a regression test for every confirmed defect.
3. Keep untrusted corpus material in quarantine; do not copy upstream code without a recorded compatible license and attribution.
4. Run the complete checks from the README.
5. Update schemas, documentation, `CHANGELOG.md`, and `PLAN.md` when a public contract changes.

Database writes must be transactional, audit events append-only, and validation centralized at boundaries. Do not add silent fallbacks, sample-specific branches, automatic promotion, cross-namespace retrieval, or success evidence that did not execute its named tool.

New runtime dependencies require an open-source license, a documented measurable benefit, and an architecture review. The standard-library core is intentional.

By submitting a contribution, you agree that it is licensed under Apache-2.0 and that you have the right to provide it.
