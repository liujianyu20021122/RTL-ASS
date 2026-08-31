# Changelog

All notable changes use semantic versioning.

## Unreleased

- Added an explicit 21-source corpus admission policy and a reproducible file-level lock for 1,429 reviewed Verilog/SystemVerilog files across seven quarantined namespaces.
- Added atomic, idempotent corpus import; audited inventory statistics; raw-byte-stable hashing; resource, provenance, license, namespace, and path validation; and public JSON schemas.
- Added real Verilator/Yosys sampling evidence without promoting raw upstream records; dependency-context failures remain explicitly attributed observations.
- Pinned current GitHub Actions releases by commit SHA to keep CI reproducible and remove deprecated Node.js runtime warnings.

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
