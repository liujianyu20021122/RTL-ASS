# RTL-ASS 1.x plan and acceptance record

## Objective

Ship RTL-ASS as an open-source, vendor-neutral Codex skill that supplements Codex with RTL-specific reasoning references, deterministic open-source evidence helpers, bounded waveform analysis, and an audited local knowledge layer. Codex remains the author and decision-maker; RTL-ASS never generates or applies a hidden patch.

## Stable 1.0 contract

1. Verilog/SystemVerilog inspection, lint, simulation, VCD/FST analysis, bounded formal, equivalence, synthesis, and OpenSTA evidence bind exact inputs and explicit scope.
2. Missing tools or inputs are `not_available`, `not_evaluated`, or `blocked`; they never become inferred passes.
3. STA requires a real netlist, Liberty data, SDC, and executed OpenSTA. Yosys-native formal/equivalence is bounded and is not described as an unbounded proof.
4. SQLite/FTS5 retrieval requires explicit namespaces. Lifecycle is `raw -> analyzed -> candidate -> verified -> promoted`, with explicit deprecation and no automatic promotion.
5. Verification, observations, derivation, pack import, links, and audit events are transaction-owned. Audit history is append-only and hash-chained.
6. Portable packs preserve record role, source identity, content hash, license metadata, and relationship policy. Import always starts `raw`.
7. The Python core has no runtime package dependency and supports Python 3.11/3.12. Product workflows use only open-source tools.
8. CLI names, JSON schemas marked `1.0`, knowledge-pack hash rules, and explicit database migration edges are public 1.x compatibility surfaces.

SymbiYosys, EQY, SMT solvers, alternative SystemVerilog frontends, OpenROAD, vector retrieval, and a plugin wrapper remain discoverable or planned extensions until their semantics and installations have dedicated integration evidence. Proprietary EDA integration is outside scope.

## Repository structure

```text
.agents/skills/rtl-ass/  Codex skill, references, thin launcher
src/rtl_ass/             deterministic helper implementation
schemas/                 stable JSON contracts
library/starter/         first-party Apache-2.0 RTL/TB/assertion/card pack
config/                  strict local configuration example
tests/                   unit, transaction, schema, and real-tool fixtures
evals/                   public controlled Codex A/B protocol and cases
docs/                    architecture, trust, installation, evaluation, release
corpus/                  quarantine manifest only
research/upstream/       ignored upstream research checkouts, never product
tools/                   reproducible release audit and asset builders
```

## Milestones

### M0 — Repository and product boundary

Status: completed.

- Root `AGENTS.md`, this plan, Apache-2.0 license, canonical layout, Codex-first and open-source-only rules.

### M1 — Skill and domain references

Status: completed.

- Compact `SKILL.md`, exact `$rtl-ass` metadata, and progressive references for routing, RTL design, verification, waveform diagnosis, formal/synthesis/STA, and knowledge governance.
- Skill Creator validation and repository contract tests pass.

### M2 — Audited knowledge store

Status: completed.

- SQLite/FTS5 namespace isolation, content identity, explicit record roles, guarded lifecycle, atomic verification/observations, append-only audit chain, and explicit v1-to-v2 migration.
- Distilled candidates retain exact source hashes and inherited provenance/license metadata.
- Strict portable pack validation/import/export includes resource bounds, path containment, semantic hashes, role policy, transaction rollback, and audit-neutral retries.
- Identity collisions with changed immutable metadata fail instead of silently deduplicating.

### M3 — Open evidence and waveform closure

Status: completed.

- Verilator lint, Icarus simulation, Yosys synthesis, bounded SAT formal, combinational/bounded-sequential equivalence, and OpenSTA adapters.
- VCD query/divergence is bounded and same-time-update safe.
- FST uses bounded streamed `fst2vcd` conversion and binds original FST, converter binary/command, and converted VCD hashes.
- Input/artifact changes, timeouts, non-empty assertion scope, unconstrained endpoints, negative slack, counterexamples, and equivalence mismatches have regression coverage.

### M4 — Starter knowledge and executable example

Status: completed.

- First-party Apache-2.0 ready/valid RTL, self-checking TB, bounded formal harness, design contract, and TB sampling card are separate linked records.
- Pack hash: `4a0920ca7ae7d5ca6a01203a2d7611f2f667b7e3de343cc2e5dec8e3668dad6f`.
- Real Verilator, Icarus, Yosys synthesis, and bounded formal runs pass; import creates five raw records/four links, repeated import creates none, and the audit chain validates.

### M5 — Corpus and evaluation governance

Status: completed for 1.0 scope.

- Twenty-one upstream projects remain represented only by pinned quarantine metadata; no unknown-license upstream code enters the starter pack.
- Six public model-evaluation cases cover generation, repair, RTL/TB attribution, FST localization, SystemVerilog semantics, and timing-aware refinement.
- Model effectiveness is explicitly `not_evaluated`; 1.0 makes no fabricated uplift claim. Controlled paired Codex runs with hidden tests are post-1.0 measurement work.
- GK/KY repository auto-discovery is rejected as a release score because it can select quarantined upstream projects. Future scores require explicit candidate/task/log/run paths.

### M6 — Static, packaging, and clean-install release gate

Status: completed for the frozen 1.0 source and rerun for the 1.1.0 release candidate.

- Required: compilation; normal and optimized unit suites; Ruff format/lint; strict mypy; Draft 2020-12 schema checks; Skill Creator validation; evaluation manifest validation.
- Required: representative release audit across lint, simulation, waveform VCD/FST, bounded formal pass/counterexample, equivalence pass/mismatch, synthesis, OpenSTA, pack import/idempotency, and audit chain.
- Required: wheel, sdist, standalone skill archive, SPDX SBOM, SHA-256 checksums, `twine check`, clean virtual-environment install, and standalone launcher smoke.
- Required: scan distributions for secrets, workstation paths, caches, generated databases/waves, upstream checkouts, and proprietary dependencies.

### M7 — Public release

Status: completed by the `v1.0.0` tag and corresponding public GitHub Release; the remote objects are the external evidence for this step.

- Create one reviewed `main` commit, tag `v1.0.0`, publish `liujianyu20021122/RTL-ASS`, upload all five release assets, and verify remote tag/assets/checksums.

### M8 — Reviewed local corpus import

Status: completed after 1.0; included in the 1.1.0 release candidate.

- Audited 21 research sources and recorded seven inclusions plus fourteen explicit exclusions. Unknown-license, benchmark-answer, generated-bulk, proprietary-flow, and intentionally broken sources remain outside engineering retrieval.
- Added a deterministic semantic lock for 1,429 tracked Verilog/SystemVerilog files (6,621,871 bytes) across isolated source namespaces; no upstream HDL is committed or packaged.
- Added strict policy/lock schemas, canonical path and source identity checks, tracked license verification, bounded selections, raw-byte-stable hashes, atomic/idempotent import, collision rollback, and audited inventory statistics.
- Imported the lock into the ignored local database. Standalone Verilator lint and Yosys synthesis passed for PicoRV32 and `axis_register`; the PULP AXI standalone dependency failure is retained as infrastructure evidence rather than an RTL defect.

### M9 — Observable Codex workflow audit

Status: completed and superseded by the six-class audit; included in the 1.1.0 release candidate.

- Add isolated skill-off/skill-on `codex exec --json` runs with an identical prompt, model, budget, public fixture, and external hidden grader.
- Sanitize the observable trace into exact skill/reference reads, commands, file changes, final agent messages, usage, normalized evidence, and grader results; never publish reasoning content or authentication state.
- Reject infrastructure-contaminated pairs and verify that passing normalized evidence binds the final candidate and unchanged supplied testbench.
- Run at least five independent paired replications on the transparent FIFO repair fixture. Treat this as a workflow-mechanism audit, not proof of general model uplift.
- Add regression tests, CI/static coverage, packaging coverage, documentation, and a compact public result after the campaign is reviewed.

The first FIFO campaign exposed an open-ended supplemental-formal stopping failure and a timeout-trace decoder defect. Both were corrected and retained as historical audit evidence; its results are not used as the final six-class measurement.

### M10 — Six-class Codex mechanism evaluation

Status: completed; included in the 1.1.0 release candidate.

- Implemented executable public/private fixtures and independent graders for all six manifest classes, including mutation checks, protected-file checks, independent reference equivalence, real OpenSTA constraints, and native FST first-divergence validation.
- Isolated the off condition from repository skill/runtime and inherited `PYTHONPATH`; bound prompt, fixture, hidden grader, harness, skill, runtime, combined payload, and sanitized report identities.
- Separated external candidate correctness, contract deliverable completeness, timely task success, current structured evidence, and observed skill activation.
- Corrected audit-discovered waveform leaf matching, equivalence input-domain semantics, FST evidence recognition, runtime leakage, and module-probe activation false positives before freezing the final harness.
- Ran five independent off/on pairs for each class with the clean stable harness. On activation and complete structured evidence were 30/30; off was 0/30 for both. External candidate correctness was 30/30 on versus 28/30 off. Task success was 29/30 on versus 23/30 off: signed-width and STA each contributed one on-only success, all five FST pairs were on-only deliverables, and one otherwise-correct skill-on FIFO run timed out.
- Published the reviewed report and machine-readable summary in `evals/results/`. The result validates the workflow/evidence mechanism, not a universal RTL correctness or efficiency uplift; the public manifest retains `effectiveness_status: not_evaluated` for that broader claim.

### M11 — v1.1.0 formal release

Status: audited local release candidate prepared; remote publication requires explicit user approval.

- Preserve the existing immutable `v1.0.0` tag and GitHub Release; publish the audited corpus and six-class workflow work under a new `v1.1.0` version.
- Freeze package, CLI, release-audit, asset-builder, CI, installation, Changelog, and release-note versions with an executable consistency regression.
- Rerun normal/optimized tests, static and Skill/schema gates, the representative open-tool audit, clean builds, Twine, checksums, clean installation, and distribution leakage scans.
- Prepare five reviewed assets with deterministic standalone Skill packaging and SHA-256 identities, plus an annotated-tag command; do not create or push the tag, update `main`, or create the GitHub Release until approval.

## Post-1.1 roadmap

- Controlled paired Codex skill-off/skill-on campaigns across multiple task classes; use fixed seeds only when the evaluated interface exposes them.
- Additional first-party packs for FIFO, arbiter, CDC/reset, memory, arithmetic, FSM, and reusable assertion/TB patterns; each requires compatible licensing and executable evidence.
- Optional vector retrieval only after a measured benefit over FTS plus structural filters.
- Stronger formal/equivalence and physical-context adapters only when installed engines, assumptions, limits, counterexamples, and schemas are explicit.
- External audit-chain anchoring for organization deployments.

## Verification record

- 2026-08-31: 84 tests passed with `PYTHONWARNINGS=error::ResourceWarning`; the same 84 passed with `PYTHONOPTIMIZE=1`.
- 2026-08-31: Ruff format and selected strict lint rules passed; `mypy --strict` passed for 32 source/release modules.
- 2026-08-31: Skill Creator validation passed.
- 2026-08-31: Seven schemas parsed; generated evidence/pack contract tests passed.
- 2026-08-31: Representative release audit passed all expected positive and negative paths, including OpenSTA and FST, with a valid ten-event starter database audit chain.
- 2026-08-31: Explicit-candidate GK/KY usability audit selected `library/starter` correctly but had an unknown task contract and could not consume RTL-ASS JSON evidence as its legacy flat report names; its conservative single-candidate number is therefore withheld as neither a full-suite nor a model-effectiveness score.
- 2026-08-31: The reviewed corpus lock reproduced byte-for-byte at hash `73855d55370257469793d7504c1fc79c74eb20a481ba42bfedd6ea54c0963046`; first import created 1,429 records, the identical retry created zero and changed no database bytes, and the post-sampling 1,457-event audit chain validated.
- 2026-08-31: Post-corpus normal and optimized suites each passed 92 tests; ten JSON schemas, Ruff, strict mypy over 33 modules, Skill Creator validation, representative release audit, SQLite integrity/foreign keys, exact lock-to-database set equality, and sdist/wheel isolation scans passed.
- 2026-08-31: Observable workflow audit added ten trace/grader regressions; normal and optimized suites each passed 102 tests. Ruff, strict mypy over 34 modules, ten schemas, Skill Creator validation, the public evaluation manifest, representative release audit, wheel/sdist metadata, and a 124-file sdist isolation/secret-shape scan passed. The reviewed five-pair report hash is `595c41f8f2442879f35acc4375d1e309f71fbc117fee8731c1b55cb728831428`; the corrected forward-pair report hash is `574db311ec0957f0d23d065cb817ba7f241bdb126b20dca0668887e0abc67dbe`.
- 2026-09-01: Clean stable-harness six-class audit completed 60 runs after bytecode/symlink payload contamination was removed from both hashing and copied trees. All 30 on traces showed hash-matched isolated RTL-ASS activation and complete required structured evidence; all 30 off traces showed neither. Candidate correctness was 30/30 on versus 28/30 off and task success was 29/30 on versus 23/30 off, with seven on-only, one off-only, 22 both-success, and zero neither-success pairs. The heterogeneous five-pair cases support mechanism validity, not a general uplift claim. All six reports bind harness hash `7ea68fd2bbfdcc9aeb45f97847f0b0972fa08dc3139f8f8270ba93669d58e722` and on-payload hash `14eccf7a04e5db2a9a5bfce1092941d617098df2571db6729c9d1ef5ec514cea`.
- 2026-09-01: Post-audit normal and optimized suites each passed 122 tests with `ResourceWarning` promoted to errors. Ruff, strict mypy over 36 checked files, ten schemas, Skill Creator validation, the six-case manifest, starter-pack validation, and the representative real-tool release audit passed. A zero-warning build produced a 37-file wheel, 159-file sdist, and 9-file standalone skill; `twine`, checksums, clean installation, required-fixture, forbidden-artifact, workstation-path, and credential-shape checks passed.
- 2026-09-01: The v1.1.0 candidate normal and optimized suites each passed 123 tests, including a regression that preserves the historical evaluated runtime identity across the version-only package change. Compilation, Ruff, strict mypy over the CI release boundary, ten schemas, Skill Creator validation, the six-case manifest, starter-pack validation, and the representative real-tool release audit passed. A zero-warning build produced a 37-file wheel, 160-file sdist, and deterministic 9-file standalone Skill; `twine`, four recorded asset checksums, clean installation, metadata/dependency checks, three explicitly allowed waveform fixtures, and forbidden-artifact/workstation-path/credential-shape scans passed. Local and remote `v1.1.0` remain absent pending approval.

The record is updated only from executed evidence. Final artifact hashes live in `SHA256SUMS`; commit, tag, and asset publication are evidenced by the immutable GitHub release rather than duplicated inside the files they hash.
