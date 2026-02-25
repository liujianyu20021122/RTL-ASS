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

9. One CompileManifest contract owns language mode, ordered sources, library files, include directories, defines, top parameters, and top module for every source-based adapter.

Alternative SystemVerilog frontends, OpenROAD, vector retrieval, and a plugin wrapper remain discoverable or planned extensions until their semantics and installations have dedicated integration evidence. Proprietary EDA integration is outside scope.

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

Status: completed; `main`, annotated `v1.1.0`, and the GitHub Release were published after clean branch and tag CI.

- Preserve the existing immutable `v1.0.0` tag and GitHub Release; publish the audited corpus and six-class workflow work under a new `v1.1.0` version.
- Freeze package, CLI, release-audit, asset-builder, CI, installation, Changelog, and release-note versions with an executable consistency regression.
- Rerun normal/optimized tests, static and Skill/schema gates, the representative open-tool audit, clean builds, Twine, checksums, clean installation, and distribution leakage scans.
- Prepare five reviewed assets with deterministic standalone Skill packaging and SHA-256 identities. Approval was received before updating `main`; create the annotated tag and GitHub Release only after the final commit passes public CI.

### M12 — post-v1.1 workflow-audit hardening

Status: completed locally and incorporated into the v1.2.0 candidate; no v1.1.1 release is planned.

- Replace sequential `equiv_induct` completion with a bounded miter/SAT proof that preserves source initialization, zero-defaults unspecified state, and includes the explicit policy in evidence identity.
- Reuse central run-evidence validation in the Codex evaluator, require current in-workspace subjects/artifacts/waveforms, and reject inert Skill-path activation signals.
- Terminate timed-out Codex process groups before grading; a future effectiveness rerun must use an OS-isolated agent container that cannot read hidden grader inputs.
- Add a no-skip pinned OpenSTA CI gate and validate wheel/sdist structure before auxiliary release assets are created.
- Build and publish one exact set of bytes from successful tag CI. Preserve the historical v1.1.0 payload report rather than implying it evaluated later code.

### M13 — v1.2.0 unified open-tool layer

Status: local release candidate complete and audited; commit, tag, and publication require explicit approval.

- Add a path-independent but compile-semantic-bound manifest with strict schema, path containment, symlink, injection, duplicate, mutation, and resource-limit checks.
- Route all source frontends through the same compile contract and one stable simulation/formal/equivalence dispatch boundary.
- Add Verilator binary simulation plus native SymbiYosys and EQY evidence. Require explicit driver markers, bounded claim scope, matching source-built tool versions, and counterexamples before accepting a negative result.
- Package the validated wheel inside the Skill archive, verify its checksum before import, and prove isolated execution without a separate installation.
- Run normal/optimized suites, static/schema/Skill/documentation gates, real open-tool positive and negative paths, deterministic double builds, clean installation, isolated Skill extraction, and distribution leakage scans before requesting publication approval.

### M14 — Resource-supervised v1.2 workflow evaluation

Status: in progress; the unsafe parallel campaign and transport-interrupted restarts are quarantined and do not support a release claim. Fresh five-pair NBA, signed-width, and pre-repair STA-priority campaigns are complete. The repaired synthesis-linked STA workflow has passed a resource-supervised paired smoke; a replicated post-repair timing campaign remains pending before making a general effectiveness claim for that task class.

- Preserve the completed samples from the interrupted campaign as diagnostic evidence, but never merge incomplete pairs or reconstruct missing results.
- Require formal outer-isolation campaigns to use a cross-process global concurrency of one, cgroup CPU/memory/swap/task limits, a host-memory start gate, continuously flushed telemetry, and explicit infrastructure-failure attribution.
- Monitor observable commands for network/package acquisition, proprietary EDA, nested model/agent invocation, Skill leakage, protected-fixture changes, malformed traces, and evidence outside each case's declared policy. Keep this audit independent of RTL correctness grading.
- Re-run the three incomplete task classes from fresh immutable campaign directories with five complete pairs each, then review per-task confidence intervals, activation, structured evidence, workflow compliance, resource peaks, and all raw paired outcomes before making any v1.2 effectiveness statement.
- Treat the embedded `report_hash` as the canonical hash of the report before that self-referential field is inserted; record the final file SHA-256 separately when citing the bytes on disk.
- Review the Verilator helper's warning policy after the frozen campaigns. The NBA traces show that mixed RTL/testbench timescale warnings can make a semantically valid compilation return structured `fail`, and that source order can affect whether the warning is emitted. Do not change the helper or fixtures during an active A/B campaign.

### M15 — Task-scoped verification and deterministic stopping

Status: completed and audited for the v1.3.0 source candidate after the v1.2.0 baseline was pushed to `main` at `85198b9`.

- Add one strict verification-plan contract in which Codex names the task class, concrete claims, required evidence, optional evidence, and retry budget. The helper validates this contract but never selects a patch or invents a claim.
- Add one evidence-summary operation that accepts explicit claim-to-evidence links, revalidates current subjects/artifacts, reports missing or non-passing requirements, detects duplicate unchanged evidence identities, and emits an unambiguous `ready_to_stop` result.
- Serialize high-cost `verify` CLI executions with one bounded workspace lock. A busy workspace returns a structured error instead of allowing concurrent EDA processes to approach the host memory limit.
- Tighten Skill routing so TB-only, waveform, formal, synthesis, and STA checks are selected only for a distinct requested claim. Once the required current evidence passes, Codex must stop launching EDA tools and deliver the result.
- Extend workflow auditing with observable redundant-evidence and post-ready activity findings. Keep efficiency findings separate from candidate correctness, evidence validity, and infrastructure attribution.

Acceptance: contract/schema tests, lock contention and cleanup tests, transactional/current-hash evidence-summary tests, CLI tests, Skill Creator validation, and realistic open-tool checks pass in normal and optimized modes. No identical required evidence is executed twice in the maintained efficient-path fixture, and default high-cost CLI concurrency is one.

### M16 — Retrieval-effect and workflow-efficiency evaluation

Status: completed for the executable mechanism and one difficult-task paired smoke. General correctness uplift, expected retrieval overhead, broader task-class benefit, and model/effort ranking remain `not_evaluated`.

- Add contamination-safe retrieval-off/retrieval-on fixtures that expose only permitted namespaces and measure whether bounded provenance-bearing cards improve a difficult RTL decision. Do not treat corpus size or retrieval occurrence as model uplift.
- Retain top-k, namespaces, record roles/statuses, exact record/content hashes, and whether Codex actually inspected each returned record. Default retrieval remains small and optional.
- Re-run representative easy and hard task classes against one frozen harness/payload. Report correctness, complete evidence, redundant executions, post-ready tool calls, latency, tokens, peak resources, and infrastructure exclusions without combining incompatible harness identities.

Acceptance: the knowledge layer has an executable ablation test without benchmark-answer leakage; easy-task Skill overhead and hard-task evidence benefits are reported separately. Model/effort ranking remains `not_evaluated` if transport instability prevents the declared sample count.

## Post-1.1 roadmap

- Controlled paired Codex skill-off/skill-on campaigns across multiple task classes; use fixed seeds only when the evaluated interface exposes them.
- Additional first-party packs for FIFO, arbiter, CDC/reset, memory, arithmetic, FSM, and reusable assertion/TB patterns; each requires compatible licensing and executable evidence.
- Optional vector retrieval only after a measured benefit over FTS plus structural filters.
- Physical-context adapters only when installed engines, assumptions, limits, reports, and schemas are explicit.
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
- 2026-09-01: The v1.1.0 candidate normal and optimized suites each passed 123 tests, including a regression that preserves the historical evaluated runtime identity across the version-only package change. Compilation, Ruff, strict mypy over all tracked `src`, `tests`, `tools`, and `evals` Python modules, ten schemas, Skill Creator validation, the six-case manifest, starter-pack validation, and the representative real-tool release audit passed. A zero-warning build produced a 37-file wheel, 160-file sdist, and deterministic 9-file standalone Skill; `twine`, four recorded asset checksums, clean installation, metadata/dependency checks, three explicitly allowed waveform fixtures, and forbidden-artifact/workstation-path/credential-shape scans passed. Local and remote `v1.1.0` remain absent pending approval.
- 2026-09-01: The documentation freeze audit covered all 39 tracked Markdown files, 21 internal links, and 29 CLI command paths. UTF-8/LF, final-newline, fence, heading, whitespace, link-target, current-version wording, workstation-path, proprietary-coupling, numeric corpus/evaluation/pack claims, and 39-of-39 sdist inclusion checks passed. Ignored historical research notes are explicitly marked non-canonical and excluded from Git, the Skill, and release packages.
- 2026-09-01: The first approved public v1.1 candidate CI run `33468495513` rejected two local-only assumptions before tagging: FST container bytes varied across GTKWave converter versions, and Yosys 0.33 left sequential output cells unproven with `equiv_simple` alone. The shared evidence flow now uses the standard `equiv_simple` plus `equiv_induct` completion sequence, and the waveform regression separately pins the committed container hash and compares decoded bounded semantics. Both repairs reproduce against the Ubuntu Yosys 0.33 tool floor; final publication remains gated on a clean rerun.
- 2026-09-01: After the portability repair, normal and optimized suites each passed all 123 tests with `ResourceWarning` promoted to errors. The complete normal suite also passed against an extracted Ubuntu Yosys 0.33/Yosys-ABC pair; the sequential reference passed while the independent mismatch and broken-fixture regressions remained rejecting. Compilation, Ruff, strict mypy over 53 modules, ten schemas, Skill Creator validation, the six-case manifest, starter pack, and the representative open-tool release audit passed.
- 2026-09-01: The v1.1.1 hardening candidate passed 132 normal and 132 optimized tests with `ResourceWarning` promoted to errors. Regressions reject missing sequential initialization, the formerly false-passing source-init mismatch, forged run/wave evidence, inert Skill-path activation, incomplete token-accounting claims, and common Skill-activation false negatives. The bounded miter/SAT flow passed both current Yosys and Ubuntu Yosys 0.33, while real mismatches failed. A source-pinned OpenSTA 3.1.0 plus CUDD 3.0.0 build passed all mandatory STA tests, the timing workflow grader, and the representative release audit. Ruff, strict mypy over 55 modules, ten schemas, Skill Creator, the six-case manifest, starter pack, CI YAML, and 40 canonical Markdown files/links passed. Two independently built and normalized wheel/sdist/Skill/SBOM/checksum sets were byte-identical; malformed distributions were rejected before auxiliary assets were created.
- 2026-09-01: The v1.2.0 local release candidate passed 145 normal and 145 optimized tests with `ResourceWarning` promoted to errors and no native-driver skip. Real Yosys 0.68+, SBY v0.68, EQY v0.68, Z3 5.1.0, Verilator 5.050, Icarus 12.0, and OpenSTA 3.1.0 positive/negative paths passed, including retained formal/equivalence counterexamples and the representative release audit. Review found and fixed a manifest-internal source-symlink bypass, removed assertion-dependent evaluator narrowing, and hardened distribution validation against parseable path/link/special/encrypted/duplicate-member inputs. Ruff, strict mypy over 59 files, 11 schemas, Skill Creator, CI YAML, 40 canonical Markdown files and 21 local links passed. Two normalized wheel/sdist/Skill/SBOM/checksum sets were byte-identical; Twine, checksum verification, isolated wheel and Skill-only execution, the 11-member self-contained Skill contract, and archive path/content/leakage scans passed. Commit, tag, and publication remain unperformed pending approval.
- 2026-09-02: The first v1.2 paired rerun completed 41 of 60 planned samples before the workstation stopped responding. The last sysstat samples did not show contemporaneous host OOM, CPU saturation, or storage saturation, so no single crash cause is claimed; the evaluator's lack of resource containment and cross-process concurrency control is nevertheless a confirmed design defect. A normal cgroup supervision smoke test then recorded seven samples, 36,851,712-byte peak memory, zero swap, and zero limit/OOM events with clean service collection. The replacement harness adds formal-run serialization, resource telemetry and limits, explicit monitor-failure invalidation, raw artifact hashes, and a separate allowed-workflow audit. Fresh completion campaigns remain pending.
- 2026-09-02: A resource-supervised one-pair NBA probe completed with both candidates correct and workflow-compliant, on-only Skill activation and complete structured simulation/waveform evidence, no resource events, and report hash `fd29d0af8e7cf3b70020b6d1698f24259d9c080b30470e2353d387a9d04b8717`. The first five-pair restart was quarantined after four valid samples when pair three entered a sustained API transport reconnect. Review added a 120-second network-stall terminator, terminal-network infrastructure attribution, direct single-worker interrupt cleanup, and a systemd runtime backstop; a two-second active-termination smoke test killed and collected the complete unit with no residual process. No partial campaign is used for an effectiveness claim.
- 2026-09-02: The fresh resource-supervised NBA campaign completed all five pairs in `.rtl-ass/evals/v1.2.0-ab-safe3-20260902-attribute-nba-scoreboard`. Both conditions were 5/5 correct, complete, and workflow-compliant; all five on runs activated the hash-matched Skill and produced complete structured simulation/waveform evidence, while all five off runs showed neither. No run timed out or had a resource, transport, or monitor failure. Per-run peak memory was 51–350 MiB, peak task count was 64–72, swap was zero, and every available terminal memory event count was zero. All ten trace, stderr, and telemetry hashes plus the embedded report hash were independently rechecked; the embedded report hash is `8b3224b9266c50710372ae5bf640d9da5cb95f5b9debd0f050c7a8e9fac0c260` and the final report-file SHA-256 is `3fe141cd8b573f986eca8580954c4e72735a9f7feac22aaf65833e46c76bf5be`. This easy task shows an evidence-quality and workflow-separation effect, not a correctness uplift: every pair succeeded in both conditions. The traces also expose a follow-up warning-policy issue for mixed-timescale Verilator helper runs; the original structured failures remain retained.
- 2026-09-02: After recording the completed NBA campaign, normal and optimized suites each passed 155 tests with `ResourceWarning` promoted to errors; one optional native-driver check skipped in each mode. Ruff, strict mypy over 59 files, the six-case manifest, and Skill Creator validation passed before the next formal task class was started.
- 2026-09-02: The first fresh signed-width campaign produced four valid samples, then pair three off lost the Codex transport. The trace records WebSocket TLS handshake EOF, failed HTTPS fallback, and continuous reconnect; the supervisor terminated the exact cgroup after the configured 120-second stall and the formal campaign failed fast without a report. The interrupted candidate itself graded correct, but is an infrastructure failure and is not reusable. Its 1,701 resource samples show a 60,395,520-byte peak, zero swap, no memory events, and clean resource/transport monitor shutdown. A post-stop health check resolved `chatgpt.com`, returned HTTP 200 from its public endpoint and the expected unauthenticated HTTP 401 from the API endpoint, with successful TLS setup. The entire campaign remains quarantined and the signed-width class must restart in a new directory.
- 2026-09-02: Signed-width traces exposed two additional follow-up audits that remain frozen until the formal campaigns finish: shell pipelines can report zero while a piped EDA command failed unless `pipefail` or `PIPESTATUS` is preserved, and generic Yosys synthesis can spend its full 120-second allowance in ABC for a very small RTL block. Independent grading prevented either observation from becoming a false correctness result; future helper and observable-command policy work must address the responsible abstraction rather than add case-specific exceptions.
- 2026-09-02: The replacement signed-width campaign completed all five pairs in `.rtl-ass/evals/v1.2.0-ab-safe4-20260902-systemverilog-signed-width`. All ten candidates were correct, deliverable-complete, and workflow-compliant. Off task success was 5/5; on task success was 4/5 because pair five on reached the 900-second Codex limit after already producing a correct candidate and complete current-hash simulation/lint/equivalence evidence. This is a valid efficiency loss, not an infrastructure exclusion. All five on runs activated the Skill and completed required structured evidence; all five off runs did neither. No transport or resource failure occurred. Per-run peak memory was 55–2,108 MiB, peak tasks were 63–70, and swap was zero; pair three on's near-`MemoryHigh` peak came from concurrent verification commands inside one Codex sample and motivates an inner-tool concurrency audit. All ten trace, stderr, and telemetry hashes plus the embedded report hash were independently rechecked. The embedded report hash is `f447bec16760444f06053d6442a21901c4b409580106c67b02bdd762854491c4`; the final report-file SHA-256 is `e9198a808d0297f7e7c9210a1417887d5d67d1de0b47b2be719c9bb0a0092d27`.
- 2026-09-02: The completed signed-width traces confirmed a product evidence-attribution defect: simulation compilation failures were reported with `missing_executable: true` even when Icarus or Verilator existed. The two observed causes were an unwritable temporary directory and Verilator warnings-as-errors; one failed version probe also placed the temporary-directory error text in `tool.version`. The shared bounded-process/version abstraction now preserves discovery, launch, timeout, return-code, and missing-output states separately; failed probe output is a bounded diagnostic with version `unknown`. Icarus and Verilator compiler-rejection regressions plus discovery, launch, missing-output, probe-failure, and real-tool tests pass. Normal and optimized full suites each passed 159 tests with one optional native-driver skip after this repair. A new 11-file standalone Skill was frozen with embedded-wheel hash `6304f33c5c4d67638dfad7a6337c12adc9073e334a00e0d4645b06f42de0a196`; two independent builds of all five release assets were byte-identical, and checksum, Twine, Skill Creator, isolated launcher, representative open-tool, and starter audit-chain checks passed. Earlier NBA/signed-width reports remain valid workflow-mechanism evidence for their recorded historical payload, not evidence for the repaired payload.
- 2026-09-02: The repaired-payload STA campaign completed five valid pairs in `.rtl-ass/evals/v1.2.0-ab-safe5-20260902-timing-refine-priority-path`. Off produced 5/5 correct candidates and 3/5 timely task successes; on produced 4/5 correct candidates and 1/5 timely task success, with paired task outcomes of one both-success, two off-only, zero on-only, and two neither-success. All five on runs activated the exact Skill, all ten runs were workflow-compliant, and no resource, transport, or monitor failure occurred. On produced observable complete-evidence command sets in 4/5 but complete required structured evidence in 0/5; repeated generic Yosys `synth` failures/timeouts and absent final normalized STA records were the dominant closure gap. Private outer `/tmp` was also not writable after privilege drop, causing initial Icarus/Yosys temporary-file failures and retries; the repaired evidence correctly recorded version `unknown`, the probe diagnostic, and compiler return code without claiming tool absence. All ten result copies, trace/stderr/telemetry hashes, telemetry counts/peaks, and the embedded report hash rechecked; embedded report hash is `4ea417aac7c32ae92ef79874832a5569f941efe1bc1cda740531e0068015c65a`, report-file SHA-256 is `dfe79e042c7655d20ba448d6caef26e705455ef7553651e0f5ae15b2f6a96472`, per-run kernel memory peaks were 78,569,472–134,238,208 bytes, sampled-current peaks were 52,736,000–82,382,848 bytes, peak tasks were 63–75, and swap/memory events were zero. The monitor summary omitted the already-sampled kernel peak and has been corrected for future runs. Fix the private temporary-directory contract and add a Liberty-bound mapped-synthesis/netlist evidence mode before claiming a usable STA closure workflow; do not raise the 900-second budget or resource ceilings to hide this result.
- 2026-09-02: The STA-campaign defects were repaired at their shared boundaries. Outer isolation now binds a per-run mode-0700 host directory to `/tmp` after privilege drop; future summaries aggregate both sampled current memory and the cgroup kernel peak. Generic synthesis stops before ABC, while `verify synth --liberty` binds and imports the exact Liberty cells as black boxes, runs bounded fast mapping, and emits `netlist.v`. The timing grader now feeds that exact mapped artifact plus the same Liberty and SDC to OpenSTA. A real initial candidate reproduced -0.600000083 setup slack and a historical correct candidate passed the repaired chain at +1.039999843 setup slack with zero unconstrained endpoints. Targeted boundary, mapped-synthesis, and outer-mount regressions pass; a fresh isolated Codex smoke campaign and full release gates remain pending.
- 2026-09-02: The one-pair repaired-workflow smoke completed in `.rtl-ass/evals/v1.2.0-ab-safe6-20260902-timing-workflow-fix-smoke`. Both candidates were independently correct, timely, deliverable-complete, and workflow-compliant; off took 730.067 seconds and on took 369.320 seconds. On activated the exact frozen Skill and recorded simulation, lint, equivalence, Liberty-mapped synthesis, and final STA; neither run timed out or had resource/transport/monitor failures. Private `/tmp` was demonstrably writable from both runs. The new report records sampled-current/kernel memory peaks separately: 82,010,112/88,457,216 bytes off and 109,539,328/121,151,488 bytes on, with zero swap/events. Audit then found that on passed behavioral gate-level RTL rather than the emitted synthesis `netlist.v` to final STA; therefore its published `complete_structured_evidence: 1` is an overpermissive historical harness result, not strict synthesis-to-STA closure. The grader now requires the deterministic mapped-netlist content hash for STA completeness and has a regression proving direct candidate RTL cannot satisfy it. A fresh post-tightening smoke remains required before closure.
- 2026-09-02: Added an explicit synthesis-evidence link for final STA rather than relying on Codex to copy an artifact path correctly. `verify sta --synthesis-evidence` centrally validates passing status, evidence and artifact hashes, Liberty subject identity, synthesis mode, top, and exactly one current `netlist.v`; a changed netlist is rejected before OpenSTA. Direct `--netlist` remains available for externally produced netlists, while the timing evaluator's completeness gate requires the mapped-netlist hash. This is deterministic evidence composition and does not select or modify RTL.
- 2026-09-03: The post-tightening one-pair smoke completed in `.rtl-ass/evals/v1.2.0-ab-safe7-20260902-timing-evidence-link-smoke` against frozen ab4 Skill/runtime payload hash `239db1df6c449a11629fc9c41dd819db969ae45e5d8931a5ddf1435497cbf3a3`. Both candidates were independently correct, deliverable-complete, timely, and workflow-compliant, with no resource, transport, or monitor failure. Off took 486.731 seconds and 736,113/13,674 input/output tokens; on took 263.613 seconds and 276,795/7,720 tokens, reductions of 45.840%, 62.398%, and 43.542% respectively. On activated the exact frozen Skill and produced current-hash simulation, equivalence, Liberty-mapped synthesis, and synthesis-linked STA evidence; off produced no complete required structured set. Independent revalidation confirmed synthesis and STA passed, the exact mapped `netlist.v` hash `7215477cd808c363ef38e533b0b44262dc25344a5c8e6059bf673bfe8a642c71` was the STA netlist subject, setup/hold slack was +0.340000033/+0.719999969 ns with one clock and zero unconstrained endpoints, and every result/trace/stderr/telemetry hash, telemetry count, and peak matched the report. Sampled-current/kernel memory peaks were 77,193,216/79,208,448 bytes off and 68,550,656/132,526,080 bytes on; peak tasks were 75, swap and memory events were zero, and no evaluation processes or scopes remained. Embedded report hash is `c38d60915d930133fe54ef9cf576f494bce6b615ab4837eebe29609ab3a144b7`; final report-file SHA-256 is `e84bdefe0b2b587c87f0481fa4b7dba33187aee243777ce78ae5c595f6fae67d`. One pair validates mechanism and a concrete efficiency win, not a general timing-task uplift.
- 2026-09-03: A post-smoke distribution scan rejected the evaluator's machine-specific open-tool and sandbox-home paths before release. The outer evaluator now discovers open-source tool installation prefixes from the invoking `PATH`, reuses the existing read-only `/usr` mount for system tools, mounts only discovered non-system prefixes under stable sandbox targets, uses an internal `/opt/rtl-ass-home`, and drops to the invoking non-root UID/GID instead of a fixed account. A real root-created `bwrap`/`setpriv` smoke confirmed the new home is writable only after the 1000/1000 privilege drop on this host. The release builder now rejects Unix or Windows workstation-home paths in every UTF-8 sdist member, with a malformed-distribution regression. Targeted normal/optimized suites passed, then full normal and optimized suites each passed 167 tests with one optional native-driver skip; Ruff covered 99 files and strict mypy covered 59 source files. The representative real-tool audit passed. Two independent ab6 builds produced five byte-identical assets; Twine, checksums, 39-member wheel, 239-member sdist, 11-member Skill, the three explicit waveform exceptions, workstation-path/private-key scans, SBOM binding, clean wheel install, Skill Creator, isolated bundled runtime, and a real mapped-synthesis-to-STA chain passed. The deliberately mistyped top used during an additional negative smoke produced structured synthesis `fail` and was rejected as STA input rather than being misreported. The final documentation-inclusive freeze is rebuilt after this record without further implementation changes.
- 2026-09-03: Final review tightened the new distribution path matcher so a bare workstation home is rejected even without a trailing path separator. Normal and optimized suites again passed 167 tests with one optional skip each; Ruff, strict mypy, and whitespace checks passed. The final release freeze is built only after this audit entry.
- 2026-09-03: The v1.2.0 parameter screen expanded the reasoning axis to `none/low/medium/high/xhigh/max` and the real CompileManifest frontend matrix to widths 1, 2, 7, 31, and 64 across Icarus, Verilator, and Yosys. Exploratory Codex traces exposed two evaluator defects rather than a Skill defect: terminal `request timed out`/HTTPS-fallback events were not classified as transport failures, and a non-executing `codex --help` probe was falsely treated as nested-agent execution. Shared classifiers plus positive, negative, recovery, and probe regressions repair both boundaries. Replayed traces exclude the affected low/high and medium-off samples; fresh low, terra-medium, and final-freeze none campaigns failed fast on continuing transport stalls, emitted no aggregate report, recorded zero swap/OOM/limit events, and left no scopes or processes. Normal and optimized suites each passed 171 tests with one explicit optional native-driver skip; Ruff covered 99 files, strict mypy covered 59 source files, 11 schemas and the six-case manifest passed. The final campaign harness is `02a4b07a7d3dd629d672d14a3dfff4fb0b30c859624e915a987861d85537cbec` and the unchanged ab8 payload is `239db1df6c449a11629fc9c41dd819db969ae45e5d8931a5ddf1435497cbf3a3`. Cross-effort/model ranking and five-pair confirmation remain not evaluated until this exact frozen harness can run without transport failure; details are in `evals/results/2026-09-03-v1.2.0-parameter-screen.md`.
- 2026-09-03: The v1.3.0 task-scoped verification slice passed 198 normal and 198 optimized tests with one explicit optional native-driver skip in each mode. Thirteen schemas, Ruff, strict mypy over 63 source files, Skill Creator validation, the six-case manifest, the reviewed retrieval pack, compilation, and the representative real-tool release audit passed. The audit exercised positive and negative formal/equivalence, Icarus/Verilator, generic and Liberty-mapped synthesis, direct and synthesis-linked OpenSTA, VCD/FST, verification readiness, knowledge transactions, audit chains, and explicit any-token retrieval. Two preliminary five-asset builds were byte-identical; Twine, checksums, archive integrity/leakage scans, isolated wheel installation, and standalone Skill execution passed.
- 2026-09-03: The final frozen retrieval ablation completed one serial signed-width off/on pair under cgroup supervision after the evaluator bound each receipt replay to the exact pre-run database bytes and retained the last successful cgroup event snapshot. Both database identities remained unchanged; both candidates were independently correct, deliverable-complete, evidence-complete, workflow-compliant, and efficient under the observable policy, with zero duplicate evidence, post-ready EDA calls, timeout, swap, memory events, or infrastructure failure. Off returned/inspected 0/0 records in 336.620 seconds using 928,936/11,763 input/output tokens; on returned/inspected the one receipt-bound record in 359.992 seconds using 1,112,684/13,369 tokens. Kernel memory peaks were 82,407,424 and 81,854,464 bytes. Embedded report hash is `571de309be293759350cec6b50aeea8d91d362831da04218457dd0914eea36b7`; report-file SHA-256 is `4d94dd84769f147561acb99bec960c4782af1b04e3eb5658bd413f8c7d28df08`. The pair proves real, inspected, contamination-gated retrieval and stopping behavior, but equal correctness and variable one-sample efficiency across diagnostic reruns forbid a quality-uplift or expected-efficiency claim. See `evals/results/2026-09-03-v1.3.0-retrieval-ablation.md`.
- 2026-09-03: Pushed-candidate CI runs `33748965474`, `33750650205`, `33752512896`, and `33753499821` exposed environment contracts that the newer local tool stack had masked. Ubuntu Verilator 5.020 treated warning-only initial-block scheduling diagnostics as fatal during binary simulation; the adapter now uses `-Wno-fatal` only for simulation compilation and still retains warnings and rejects compiler/runtime errors. OpenSTA 3.1.0 under runner CMake 4 could not infer its Flex C++ header, and `flex` did not install the recommended `libfl-dev` when already present; CI now installs the owning package, checks the header explicitly, and binds its directory. The source-built SBY/EQY runtime imported Click, but the previous isolated target made the hash-installed module invisible to their Python interpreter; Click and Z3 are now hash-locked into the active CI Python environment while the formal tools remain in their separate prefix. A bounded annotation wrapper preserves command/tee status, neutralizes child workflow commands, and emits only an escaped log tail; every CI job also has a wall-clock limit. Run `33753499821` independently confirmed both Python 3.11/3.12 matrices and the pinned formal source build before the remaining two boundary failures. With the corrected contracts, `env -u VERILATOR_ROOT -u VERILATOR_HOME PYTHONPATH=src PYTHONWARNINGS=error::ResourceWarning python -m unittest discover -s tests -v` passed 204 normal and 204 optimized tests against Ubuntu Verilator 5.020 and a source-pinned OpenSTA 3.1.0, with one explicit optional native-formal skip in each local run. The pinned OpenSTA source also configured and built completely under CMake 4.1.2, reported version 3.1.0, passed all five mandatory STA tests, and passed `tools/release_audit.py`; the hash-locked formal Python environment launched pinned SBY and Z3 without `PYTHONPATH`. Ruff, strict mypy over 65 source files, compilation, ShellCheck, 13 schemas, six evaluation cases, both first-party packs, Skill Creator validation, two byte-identical five-asset builds, Twine/checksums, a clean wheel install, and the isolated 11-member Skill passed. Publication remains gated on the public CI run for the exact commit containing this record; the final assets must be rebuilt from that commit and must not be tagged or released without explicit approval.

The record is updated only from executed evidence. Final artifact hashes live in `SHA256SUMS`; commit, tag, and asset publication are evidenced by the immutable GitHub release rather than duplicated inside the files they hash.
