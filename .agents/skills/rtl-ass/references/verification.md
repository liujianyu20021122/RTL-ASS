# RTL verification guidance

## Build checks from requirements

For every requirement, identify stimulus, observation point, sampling phase, expected response, timeout, and failure message. Keep the oracle independent of implementation details when possible.

## Testbench semantics

- Drive and sample in defined simulation regions. Prefer SystemVerilog clocking blocks or cocotb phase primitives over arbitrary delays.
- Define reset assertion/deassertion timing and post-reset observation explicitly.
- Record every accepted transaction in a scoreboard using the protocol's real handshake condition.
- Include backpressure, consecutive transactions, boundaries, parameter corners, X-sensitive situations, and timeout behavior.

## Evidence ladder

Use the least expensive evidence that answers the current question, then increase confidence:

1. parse/lint and elaboration;
2. focused simulation with self-checks;
3. regression and assertions;
4. coverage and mutation testing of the checker;
5. formal properties or equivalence where bounded/exhaustive reasoning is valuable;
6. synthesis and timing evidence for implementation claims.

Do not collapse these into one pass/fail flag.

## Verification plan and stopping gate

For a material edit that needs multiple evidence classes, write one small plan before the final checks. Codex chooses every claim; the helper only validates the contract and current evidence.

```json
{
  "schema_version": "1.0",
  "plan_id": "focused-repair",
  "task_class": "debugging",
  "claims": [
    {
      "id": "regression",
      "statement": "The supplied self-checking regression passes.",
      "evidence_kind": "simulation",
      "requirement": "required",
      "expected_status": "pass"
    },
    {
      "id": "synth-readiness",
      "statement": "The changed design remains synthesizable.",
      "evidence_kind": "synthesis",
      "requirement": "optional",
      "expected_status": "pass"
    }
  ],
  "stop_policy": {
    "max_retries_per_claim": 1,
    "max_parallel_eda": 1
  }
}
```

Validate it with `verify plan verification-plan.json`. After the selected final runs, use one explicit link per attempt:

```bash
rtl-ass verify summarize --plan verification-plan.json \
  --evidence regression=artifacts/rtl-ass/simulation/<run>/run-evidence.json \
  --require-ready
```

Optional evidence does not block readiness. The summary rechecks current subjects, raw artifacts, and evidence JSON; it reports duplicate `(kind, input_hash)` executions and retry-budget excess. If `--require-ready` succeeds, stop running EDA tools and deliver. If an input changes, the old record becomes stale and cannot close the plan.

For a material post-change check, prefer the RTL-ASS `verify` subcommands over an unrecorded final command when the helper is available. Each evidence class must use the exact ordered sources and top for that check, live in its own artifact directory, and end with an inspected `run-evidence.json`. Ad hoc commands remain useful for diagnosis but do not replace the normalized final record.

Use one validated CompileManifest when the build needs include directories, library files, defines, parameter overrides, or an explicit language mode. The manifest paths are relative to its own directory. Pass the same manifest to lint, simulation, synthesis, and formal runs so backend differences cannot silently change elaboration. Inline `--source` remains suitable for small checks but cannot be mixed with `--manifest`.

```json
{
  "schema_version": "1.0",
  "top": "dut_tb",
  "language": "systemverilog",
  "sources": ["tb/dut_tb.sv"],
  "library_files": ["rtl/dut.sv"],
  "include_dirs": ["include"],
  "defines": {"RTL_ASS_SIM": null},
  "parameters": {"WIDTH": "8"}
}
```

Icarus is the default simulation backend and is useful for quick self-checking testbenches. Select `--backend verilator` for an independent compiled simulation frontend. Backend agreement strengthens confidence only when both runs use the same manifest and checker; it is not a substitute for inspecting the checker contract.

Interpret the recorded phase before attributing a failed run. `not_available` means discovery did not find a required tool; a launch failure is `blocked`; a nonzero compiler result is `fail`; and a zero-result compile without its promised executable is `blocked` with `missing_compiled_artifact`. A failed version probe leaves `tool.version` as `unknown` and retains the probe diagnostic separately. None of these infrastructure or elaboration states alone proves an RTL behavioral defect.

Do not turn an optional confidence check into an open-ended subtask. If a supplemental formal, equivalence, waveform, or timing run is blocked or fails because its harness or inputs are incomplete, retain that first evidence and state the boundary. Continue only when it indicates a plausible product defect or the task specifically requires that class to pass. Never repeat the same evidence identity merely under a new artifact-directory name.

For bounded formal, require at least one assertion after elaboration, record the bound and initialization assumptions, and retain the counterexample. Use the Yosys backend for a focused local SAT check or `--backend sby` for native SymbiYosys orchestration with an explicit open solver. A passing bound does not establish behavior beyond that bound. For equivalence, keep the reference and implementation source identities and tops distinct; do not compare a candidate with itself or erase the direction of the comparison.

## RTL versus TB attribution

Check whether stimulus matches the specification, the checker samples the intended phase, expected values use the correct transaction, the DUT revision matches the waveform, and source-map lines refer to original files. Preserve both RTL and TB hypotheses until one is contradicted by evidence.

## Testbench knowledge records

Index a TB separately from its DUT. Link exact hashes and record simulator, command, parameters, expected contract, observed outcome, coverage, and known limitations. A TB is reusable only when its assumptions are explicit.
