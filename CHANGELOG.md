# Changelog

All notable changes use semantic versioning.

## Unreleased

## 1.1.0 — 2026-09-01

- Added an explicit 21-source corpus admission policy and a reproducible file-level lock for 1,429 reviewed Verilog/SystemVerilog files across seven quarantined namespaces.
- Added atomic, idempotent corpus import; audited inventory statistics; raw-byte-stable hashing; resource, provenance, license, namespace, and path validation; and public JSON schemas.
- Added real Verilator/Yosys sampling evidence without promoting raw upstream records; dependency-context failures remain explicitly attributed observations.
- Pinned current GitHub Actions releases by commit SHA to keep CI reproducible and remove deprecated Node.js runtime warnings.
- Added an isolated Codex skill-off/skill-on workflow auditor with sanitized JSONL observability, exact activation detection, hidden external grading, normalized evidence binding, infrastructure-failure exclusion, and a transparent non-power-of-two FIFO fixture.
- Strengthened the skill delivery contract so material RTL changes produce separate hashed lint, self-checking simulation, and synthesis evidence without replacing Codex's design decisions.
- Expanded the auditor to six first-party workflow classes: specification-to-RTL, FIFO repair, RTL/testbench attribution, native FST localization, SystemVerilog signed-width repair, and timing-aware refinement.
- Added fixture/prompt/grader/harness/skill/runtime/payload identities, isolated on-only runtime delivery, explicit candidate/deliverable/task outcomes, Wilson intervals, paired outcomes, and a reviewed 30-pair result.
- Fixed leaf-name waveform glob matching, explicit defined/undefined equivalence domains, FST evidence recognition, inherited `PYTHONPATH` leakage, and false activation from successful compound module probes.
- Corrected the public FIFO manifest's stale minimum-evidence field to match the executed lint/simulation/synthesis protocol; supplemental formal outcomes remain separate and are never inferred as passing.
- Removed transient bytecode and symlinks from evaluated runtime identity/copying, excluded infrastructure failures consistently from aggregate workflow metrics, and reran all six final campaigns with a clean-clone-stable payload hash.

Known boundaries: the reviewed corpus remains local and untrusted until explicitly verified; Yosys formal/equivalence evidence is bounded; OpenSTA is not physical signoff; the transparent five-pair-per-class Codex audit validates Skill activation and evidence behavior but does not establish universal correctness or efficiency uplift.

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
