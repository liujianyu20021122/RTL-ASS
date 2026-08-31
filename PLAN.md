# RTL-ASS 1.0 plan and acceptance record

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

Status: completed for the frozen 1.0 source.

- Required: compilation; normal and optimized unit suites; Ruff format/lint; strict mypy; Draft 2020-12 schema checks; Skill Creator validation; evaluation manifest validation.
- Required: representative release audit across lint, simulation, waveform VCD/FST, bounded formal pass/counterexample, equivalence pass/mismatch, synthesis, OpenSTA, pack import/idempotency, and audit chain.
- Required: wheel, sdist, standalone skill archive, SPDX SBOM, SHA-256 checksums, `twine check`, clean virtual-environment install, and standalone launcher smoke.
- Required: scan distributions for secrets, workstation paths, caches, generated databases/waves, upstream checkouts, and proprietary dependencies.

### M7 — Public release

Status: completed by the `v1.0.0` tag and corresponding public GitHub Release; the remote objects are the external evidence for this step.

- Create one reviewed `main` commit, tag `v1.0.0`, publish `liujianyu20021122/RTL-ASS`, upload all five release assets, and verify remote tag/assets/checksums.

## Post-1.0 roadmap

- Controlled multi-seed Codex skill-off/skill-on campaign using the published protocol.
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

The record is updated only from executed evidence. Final artifact hashes live in `SHA256SUMS`; commit, tag, and asset publication are evidenced by the immutable GitHub release rather than duplicated inside the files they hash.
