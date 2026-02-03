# Changelog

All notable changes use semantic versioning.

## 1.0.0 — 2026-08-31

Initial stable release.

- Added the Codex-first, vendor-neutral RTL skill and progressive RTL references.
- Added safe Verilog/SystemVerilog inspection and open-tool discovery.
- Added Verilator, Icarus Verilog, Yosys synthesis/formal/equivalence, and OpenSTA evidence adapters.
- Added bounded VCD and resource-bounded FST waveform query and first-divergence workflows.
- Added the transactional SQLite/FTS5 knowledge store, explicit migrations, namespace isolation, guarded lifecycle, atomic verification and observation, and tamper-evident audit chain.
- Added candidate derivation and strict portable knowledge-pack import/export.
- Added the first-party ready/valid RTL, TB, assertion, and engineering-card starter pack.
- Added JSON schemas, Python 3.11/3.12 CI, optimized-runtime tests, strict typing/linting, source/wheel/skill packaging, SBOM/checksum generation, and reproducible release auditing.

Known boundaries: Yosys-native formal and equivalence are bounded; OpenSTA is not physical signoff; controlled Codex skill-off/skill-on model evaluation results are not asserted by this release.
