---
name: rtl-ass
description: Strengthen Codex for vendor-neutral Verilog/SystemVerilog RTL design, repository analysis, testbench and assertion work, simulation or waveform debugging, formal/synthesis/STA evidence, and retrieval from a verified local RTL knowledge base. Use for RTL engineering tasks that benefit from open-source tools; do not use as a replacement coding agent or for proprietary-tool-only operation.
---

# RTL-ASS

Codex remains the engineer: inspect the user's project, reason about the specification, edit the RTL or testbench, and choose the final solution. Use RTL-ASS for domain-specific decisions, compact retrieval, and deterministic open-source evidence.

## Route the task

1. Preserve the user's interface, protocol, clock/reset, latency, language, and verification constraints.
2. Classify the work as generation, analysis, debugging, verification, optimization, or knowledge curation. Read [task-routing.md](references/task-routing.md) when the task spans more than one class or the required evidence is unclear.
3. Read only the relevant references:
   - RTL architecture or coding: [rtl-design.md](references/rtl-design.md)
   - Testbench, assertions, or correctness evidence: [verification.md](references/verification.md)
   - Simulation mismatch or waveform diagnosis: [waveform-debugging.md](references/waveform-debugging.md)
   - Synthesis, formal equivalence, or STA: [synthesis-sta.md](references/synthesis-sta.md)
   - Knowledge ingest, retrieval, or promotion: [knowledge-governance.md](references/knowledge-governance.md)
   Do not read a reference merely because it is listed. In particular, load waveform guidance only when a real trace is needed and knowledge guidance only for retrieval or curation work.
4. Query the local knowledge base only when existing patterns or verified cases can materially improve the task. Retrieve a small number of records, inspect provenance and applicability, then decide independently.
5. Edit with the smallest coherent change. Do not ask a helper script or another model to write the RTL for Codex.
6. Validate in proportion to risk. Keep compilation, simulation, waveform, formal, synthesis, and STA as separate evidence classes.

## Delivery contract

When a task materially changes RTL, a testbench, assertions, or constraints and the local helper is available:

1. Reproduce the baseline failure without changing the supplied checker.
2. Use direct tool commands as needed for diagnosis, but record the final applicable checks with the helper so each check has a hashed `run-evidence.json`.
3. For an RTL repair with a runnable testbench, normally record separate lint, self-checking simulation, and synthesis runs. Add formal, equivalence, waveform, or STA only when they answer a distinct claim.
4. Inspect every recorded status. A generated evidence file is not a pass, and a missing class must be reported as `not_available` or `not_evaluated` with its reason.
5. In the final response, identify the exact changed files, the evidence classes and statuses, and the unverified boundary.

Finish after the lowest-cost evidence set supports the requested claim. Do not add formal, waveform, synthesis, or STA merely to make the report look comprehensive; each extra class needs a concrete unresolved risk or user requirement.

When formal, equivalence, waveform, or STA is only supplemental, preserve and report its first `fail` or `blocked` result instead of repeatedly rewriting harnesses or constraints. Retry only when the result plausibly exposes a candidate defect and resolving it is necessary for the requested claim. If the user explicitly requests that evidence class, treat it as primary and diagnose it to the agreed budget.

For a simple check, the helper accepts one `--source` option per ordered source file. When includes, library files, language mode, defines, parameters, or multiple tools matter, create one `compile.json`, validate it with `manifest validate`, and pass it unchanged through `--manifest`. Never rebuild different source flags independently for each backend. Use a different artifact directory for each evidence class, for example:

```bash
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py verify lint --source rtl/dut.sv --top dut --artifact-dir artifacts/rtl-ass/lint
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py verify simulate --source rtl/dut.sv --source tb/dut_tb.sv --top dut_tb --artifact-dir artifacts/rtl-ass/simulation
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py verify simulate --backend verilator --manifest compile.json --artifact-dir artifacts/rtl-ass/verilator
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py verify synth --source rtl/dut.sv --top dut --artifact-dir artifacts/rtl-ass/synthesis
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py verify synth --source rtl/dut.sv --top dut --liberty lib/cells.lib --artifact-dir artifacts/rtl-ass/mapped-synthesis
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py verify formal --backend sby --manifest formal.json --depth 20 --initialization defined --solver z3 --artifact-dir artifacts/rtl-ass/sby
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py verify equiv --backend eqy --reference-manifest reference.json --implementation-manifest implementation.json --depth 1 --solver z3 --artifact-dir artifacts/rtl-ass/eqy
```

## Evidence rules

- Distinguish specification, testbench, RTL, constraints, and infrastructure hypotheses before assigning a root cause.
- A passing process exit is not proof of functional correctness; inspect the checker contract and relevant assertions.
- A bounded formal or sequential-equivalence run proves only its recorded scope; require a non-empty property/equivalence scope and retain counterexamples.
- A waveform conclusion must cite a real VCD/FST event window and the first relevant divergence.
- A synthesis result is not STA. STA requires a netlist, Liberty timing data, constraints, and a real timing-engine run.
- For timing work, run Liberty-mapped synthesis once and pass its exact `netlist.v`, the same Liberty file, and the SDC to `verify sta`. Do not pass Verilog simulation models of those same cells into mapped synthesis.
- Prefer `verify sta --synthesis-evidence <mapped-run-evidence.json>` for the final timing run; it validates the synthesis record and selects its unique `netlist.v`, preventing a direct-RTL substitution.
- Missing tools or inputs produce `not_available` or `not_evaluated`, never an inferred pass.
- Do not change latency, protocol behavior, clocks, reset semantics, or timing exceptions as an implicit optimization.

## Local helper

Prefer an installed `rtl-ass` command. From this repository, use:

```bash
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py doctor
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py inspect <project> --json
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py manifest validate <compile.json>
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py verify lint --source <rtl.sv> --top <top> --artifact-dir <dir>
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py verify simulate --backend <iverilog-or-verilator> --source <rtl.sv> --source <tb.sv> --top <tb-top> --artifact-dir <dir>
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py verify synth --source <rtl.sv> --top <top> --artifact-dir <dir>
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py verify sta --synthesis-evidence <synthesis-run-evidence.json> --liberty <cells.lib> --constraints <design.sdc> --top <top> --artifact-dir <dir>
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py verify formal --backend <yosys-or-sby> --source <properties.sv> --top <top> --depth <n> --artifact-dir <dir>
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py verify equiv --backend <yosys-or-eqy> --reference-source <reference.sv> --implementation-source <candidate.sv> --reference-top <reference> --implementation-top <candidate> --input-domain defined --artifact-dir <dir>
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py wave query <trace.vcd-or-fst> --signal <glob> --start <time> --end <time> > artifacts/rtl-ass/wave-query.json
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py kb search <query> --db <index.db> --namespace <name>
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py kb derive <source-id> --db <index.db> --namespace <name> --actor <actor> --role <role> --language <language> --title <title> --summary <summary> --content-file <file> --source-path <path> --method <method>
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py kb import-pack <pack.json> --db <index.db> --namespace <name> --actor <actor>
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py kb verify <record-id> --actor <actor> --evidence-json <run-evidence.json>
python3 .agents/skills/rtl-ass/scripts/rtl_ass.py kb observe <record-id> --actor <actor> --attribution <cause> --evidence-json <run-evidence.json>
```

Helpers inspect, index, retrieve, and normalize evidence. They do not choose or apply RTL patches.

## Knowledge safety

- Imported and generated content starts untrusted.
- Preserve source URL/revision, file hash, license status, namespace, record role, and verification state.
- Treat RTL, testbench, assertion, reference model, fixture, and tool evidence as distinct linkable records.
- Never promote automatically. Read [knowledge-governance.md](references/knowledge-governance.md) before changing lifecycle state.
- Derive reusable cards separately from immutable sources. Preserve exact source hashes and inherited license metadata; import portable packs as `raw`, never as trusted knowledge.
- Preserve non-passing runs with explicit attribution; do not infer that timeout, blocked, or infrastructure evidence is an RTL defect.
- Do not expose project-private records through a broader namespace or use benchmark answers while evaluating that benchmark.
