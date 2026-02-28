# RTL-ASS Repository Instructions

## Mission

RTL-ASS is an open-source, vendor-neutral, retrieval-first Codex skill that strengthens Codex for RTL engineering. Codex remains responsible for understanding the user's intent, planning, editing RTL, reasoning about failures, and choosing the final implementation. RTL-ASS primarily supplies calibrated, provenance-bearing knowledge records; deterministic open-source tool helpers and structured evidence are an explicitly authorized fallback.

Do not turn RTL-ASS into a separate RTL coding agent, an autonomous replacement for Codex, or a fixed end-to-end EDA pipeline.

## Product Boundaries

- Support Verilog and SystemVerilog RTL, testbenches, assertions, simulation debugging, waveform analysis, synthesis readiness, formal/equivalence checks, and STA when sufficient open inputs exist.
- Use only open-source RTL/EDA tools in product code and documented default workflows.
- Do not add Vivado, Quartus, VCS, Verdi, Questa, Xcelium, or other proprietary/vendor tools as dependencies or required backends.
- Do not call another LLM or create a hidden multi-agent coding service. Codex itself is the reasoning and coding engine.
- Tool helpers return evidence; they do not decide what RTL patch Codex must apply.
- Preserve a user-selected tool or verification flow. Otherwise prefer an applicable documented project-local flow. RTL-ASS EDA adapters may run only when verification is required and neither prior flow applies; Codex must ask the user to confirm both that no other local flow should be used because it is unavailable or disallowed and that the named fallback may run. An explicit request for an RTL-ASS backend is already a user-selected flow.
- Read-only knowledge and record inspection are the default Skill mechanism. Do not run `doctor`, project inspection, verification planning, or EDA adapters merely because the helper exposes them.
- Never claim STA closure without a real netlist, Liberty timing library, constraints, and an executed timing engine.
- Never claim waveform analysis without reading a real waveform or simulator event artifact.
- Treat SystemVerilog as a first-class language for synthesizable RTL, testbenches, assertions, interfaces, and packages.
- Maintain separate but linkable knowledge objects for design RTL, testbenches, assertions, reference models, fixtures, and verification results.

## Audit-First Engineering

- Auditability is a system property, not a final report. Every ingest, search result, lifecycle transition, and verification claim must be traceable to immutable inputs and an actor or tool action.
- Prefer a small set of explicit invariants and typed boundaries over scattered defensive checks.
- Do not accumulate sample-specific branches, hidden fallbacks, permissive exception swallowing, or duplicate parsers to make individual tests pass.
- When an invariant fails, return a structured error at the boundary. Do not continue with partially valid state.
- Centralize validation for record schemas, lifecycle transitions, namespaces, paths, licenses, and evidence status.
- Database mutations must be transactional. Audit records are append-only; corrections create new events instead of rewriting history.
- Database migrations must be explicit per source/target version, validate their structural preconditions, verify invariants before commit, and roll back all DDL/DML on failure. Never auto-guess a migration.
- Candidate verification must use the atomic `kb verify` workflow. Direct lifecycle transition to `verified` is forbidden.
- Hash raw evidence artifacts as well as source inputs, and recheck both before committing a verification gate.
- Validate each implementation slice before starting the next. Do not defer integration testing until the end.
- Add a regression test for every confirmed defect, but fix the responsible abstraction rather than only the observed input.
- Periodically audit dead code, duplicate concepts, obsolete compatibility paths, and unreferenced artifacts.

## Canonical Repository Layout

- `.agents/skills/rtl-ass/`: Codex skill entrypoint, progressive references, and thin helper launchers.
- `src/rtl_ass/`: deterministic Python implementation for knowledge indexing, project inspection, search, and evidence normalization.
- `schemas/`: stable JSON schemas for knowledge and run artifacts.
- `config/`: example configuration with safe local defaults.
- `tests/`: unit and integration tests; fixtures must be small and redistributable.
- `evals/`: behavioral evaluations comparing Codex with and without the skill.
- `docs/`: maintained architecture and contributor documentation.
- `research/`: research artifacts only; code under `research/upstream/` is not product source.

## Skill Authoring Rules

- Keep `SKILL.md` concise and discriminating. Put conditional RTL guidance in `references/` and load only what the current task needs.
- Assume Codex is already a strong general programmer. Include RTL-specific knowledge that changes decisions; omit generic coding advice.
- Preserve user-selected language, interface, latency, protocol, clock/reset behavior, and verification scope.
- Prefer minimal, reviewable RTL patches over whole-file rewrites during debugging.
- Require Codex to distinguish specification, testbench, RTL, constraints, and infrastructure hypotheses before attributing a failure.
- Treat compilation, simulation, waveform, formal, synthesis, and STA as distinct evidence classes.
- Make calibrated retrieval the first Skill action when an in-scope database exists. Prefer `promoted`, then relevant `verified`, records; do not use `raw` or `candidate` records as default coding guidance.
- Keep the complete optional-tool inventory and fallback authorization boundary in one canonical reference. Do not duplicate an EDA command catalog in `SKILL.md`.

## Knowledge Base Governance

- The knowledge base augments retrieval; it does not modify model weights.
- Keep project, user, organization, and built-in namespaces isolated.
- Every record must retain provenance, content hash, license status, verification status, and applicable tool versions when known.
- Use the lifecycle `raw -> analyzed -> candidate -> verified -> promoted -> deprecated`.
- Generated or imported RTL must not enter `verified` or `promoted` automatically.
- Promotion requires configured evidence gates and an explicit command or review action.
- Preserve failed fixes as negative evidence. Do not mix infrastructure failures with RTL repair knowledge.
- Retain non-passing runs through `kb observe` with explicit attribution. Only an executed `fail` explicitly attributed to the target may create `negative-for`; timeout, blocked, infrastructure, and unattributed results must not teach a target anti-pattern.
- Do not ingest secrets, private source code into a broader namespace, benchmark hidden answers, or code with incompatible/unknown redistribution terms.
- Imported GitHub content starts in a quarantined corpus namespace. Upstream popularity or upstream tests do not make it trusted.
- Keep original source and distilled knowledge separate. Distilled records link back to immutable upstream hashes and license metadata.
- RTL and TB records must declare their role. Link a testbench to the exact DUT revision, command, expected behavior, and observed outcome when available.
- Never index benchmark reference answers into a retrieval namespace used while evaluating on that benchmark.

## Implementation Standards

- Target Python 3.11 or newer and prefer the standard library for the core MVP.
- Use SQLite and FTS5 as the default local index. Optional vector backends must remain optional.
- Make CLI output deterministic and provide JSON output for Codex consumption.
- Route every source-based evidence adapter through `CompileManifest`; do not reconstruct language, source order, libraries, includes, defines, parameters, or top independently per backend.
- Treat external formal-driver markers as necessary but not sufficient evidence. Ambiguous output is blocked, and a negative formal/equivalence claim requires its retained counterexample.
- Store paths portably; do not embed this machine's absolute paths in product defaults.
- Use content hashes and transactional writes for mutable knowledge state.
- Validate untrusted paths and never execute ingested RTL as part of indexing.
- Keep database files, generated waveforms, reports, caches, and downloaded research repositories out of Git.

## Verification Requirements

- Run the relevant unit tests for every code change.
- Run `python3 -m unittest discover -s tests -v` for changes spanning the core package.
- Run the Skill Creator validator against `.agents/skills/rtl-ass` after changing the skill.
- Test observable behavior and artifact content, not wording-only assertions.
- If an optional EDA tool is unavailable, report `not_available` or `not_evaluated`; do not silently pass.
- Validate incrementally in this order when applicable: schema and unit invariants, database transaction tests, CLI contract tests, fixture integration tests, then realistic RTL/TB tool tests.
- Finish a milestone only when its acceptance criteria and audit checks pass; record the exact commands and gaps in `PLAN.md`.

## Open-Source and Contribution Rules

- Do not copy code from `research/upstream/` into product source without checking its license and recording attribution.
- Reimplement concepts behind a clean interface when license compatibility or provenance is unclear.
- New runtime dependencies require a concrete benefit, an open-source license, and documentation in the plan.
- Keep `PLAN.md` current when a milestone, architecture decision, or acceptance criterion changes.
- GitHub corpus acquisition requires a reproducible manifest with repository URL, revision, retrieval date, license finding, intended record roles, and ingestion status.
- Do not interpret corpus ingestion as permission to redistribute every upstream file. Publish only what licenses and project policy permit.

## Code Review Rules

- Flag any change that makes RTL-ASS generate or apply RTL without Codex review.
- Flag evidence artifacts that can report success without running the corresponding tool.
- Flag automatic knowledge promotion, cross-namespace leakage, missing provenance, or license loss.
- Flag proprietary-tool coupling and assumptions that hard-code a single clock, reset, top module, simulator, or technology library.
