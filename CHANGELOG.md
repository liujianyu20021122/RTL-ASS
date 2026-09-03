# Changelog

All notable changes use semantic versioning.

## 1.3.0 — 2026-09-03

- Added Codex-selected verification plans and current-evidence summaries with explicit required/optional claims, bounded retry policy, duplicate evidence detection, and an observable ready-to-stop gate.
- Serialized CLI EDA execution with one bounded, symlink-safe workspace lock and added workflow-efficiency reporting for redundant evidence and post-ready tool calls.
- Tightened Skill routing so TB-only and functional RTL tasks no longer default to synthesis, waveform, formal, equivalence, or STA without a distinct claim.
- Centralized stable waveform-result validation for both product summaries and the isolated Codex evaluator.
- Added immutable retrieval receipts that bind the exact query, explicit namespaces, match policy, filters, ordered result identities, provenance, licenses, and content hashes.
- Added explicit all-token/any-token FTS modes after real Codex traces showed that long natural-language AND queries could silently miss a relevant card; no hidden fallback is performed.
- Added a contamination-gated retrieval A/B mode that keeps RTL-ASS constant, distinguishes returned cards from full-content reads, and reports retrieval effects independently from correctness and infrastructure.
- Replaced substring-based EDA command classification with parsed helper subcommands and exact tool executables, preventing log-inspection paths from becoming false post-ready evidence findings.
- Made Verilator binary simulation retain warnings as evidence without treating warning-only compilations as fatal; real compile errors and nonzero simulations still fail.
- Bound source-built OpenSTA's Flex header input across runner CMake versions, hash-locked the complete formal-driver Python runtime, selected explicit build tools, added job time limits, and added bounded public failure annotations without masking exit status.

## 1.2.0 — 2026-09-01

- Added a strict CompileManifest schema and runtime contract shared by lint, Icarus/Verilator simulation, Yosys synthesis/formal/equivalence, SymbiYosys, and EQY; language, libraries, includes, defines, parameters, top, and exact input identities no longer diverge between adapters.
- Added native Verilator binary simulation, SymbiYosys bounded assertion, and EQY equivalence adapters with one stable backend-dispatch API and CLI selection.
- Require real driver status markers and counterexample traces before classifying negative formal/equivalence evidence; ambiguous, missing, tool-error, or unproved outputs remain blocked.
- Added matching source-pinned Yosys/SBY/EQY v0.68 CI with a hash-pinned Z3 wheel and positive/negative no-skip integration tests.
- Made the release Skill self-contained by embedding and verifying the exact pure-Python wheel; isolated extraction tests no longer rely on a separately installed package.
- Replaced weak sequential-equivalence convergence claims with bounded miter/SAT evidence that preserves source initial values, zero-defaults unspecified state, and hashes that explicit policy.
- Made Codex workflow evidence reuse the central artifact/subject validator, reject escaped or forged evidence, and recognize Skill activation only from parsed read/helper commands.
- Kill and reap complete Codex process groups on evaluation timeout.
- Added a mandatory pinned OpenSTA CI gate and reject malformed wheel/sdist inputs before producing release assets.
- Require GitHub releases to reuse the exact successful tag-CI artifact rather than a second local build.

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
- Expanded strict static typing from the release subset to all repository Python modules under `src`, `tests`, `tools`, and `evals`.
- Made sequential Yosys equivalence portable across the supported open-tool floor and replaced a converter-version-dependent FST byte comparison with separate container-integrity and decoded-semantic checks.

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
