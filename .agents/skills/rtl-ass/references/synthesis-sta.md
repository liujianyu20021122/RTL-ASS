# Open synthesis, formal, and STA evidence

## Tool roles

- Verilator/Icarus: parsing, linting, elaboration, and simulation evidence.
- Yosys: synthesizability, transformed netlist, cell/resource statistics, bounded SAT property checks, and equivalence plumbing.
- SymbiYosys/EQY with an open solver: stronger property and equivalence flows when the selected engine and proof mode are recorded.
- OpenSTA: timing analysis from a real netlist, Liberty data, and SDC.
- OpenROAD: optional physical-context implementation evidence when an open PDK and flow are available.

## Evidence boundaries

Yosys `stat` is not STA. Generic delay estimates are not signoff. OpenSTA without clocks, I/O delays, timing libraries, or constrained endpoints is incomplete and must be reported as `not_evaluated` or partial evidence.

A finite SAT depth is bounded evidence, not an unbounded proof. Bind the depth, top, ordered source hashes, initialization policy, assumptions, and defined-input policy into the run identity. Reject an empty assertion scope. Preserve a generated counterexample waveform on failure, and classify syntax/elaboration/tool failures as `blocked` rather than a disproved property.

`verify formal --backend yosys` runs the direct bounded SAT adapter. `--backend sby` writes and runs a native SymbiYosys BMC job with the selected open SMT solver. Treat the SBY status marker as authoritative only when it is well formed; a reported failure requires a retained VCD counterexample before it becomes negative evidence.

Equivalence must bind separate reference and implementation identities. Depth 1 supports a combinational `$equiv` check after compatible elaboration. A larger depth uses a bounded miter/SAT check and requires the explicit `--initialization zero` contract; never infer initial-state or reset synchronization from structural similarity. This preserves explicit source initial values and defaults otherwise-unspecified state to zero, so different source initial values remain a mismatch. Use a separate reset simulation or formal harness when the contract instead depends on a reset sequence; do not relabel the zero-default result. The default `--input-domain defined` proves ordinary hardware bit behavior. Use `--input-domain undefined` only when X/undefined propagation is part of the stated contract; algebraically equivalent topologies can intentionally differ there. Depth, initialization, and input domain are part of the evidence hash. A disproved miter or unproven `$equiv` cell is failed equivalence; interface, elaboration, or tool failures are blocked evidence.

`verify equiv --backend eqy` runs EQY with its SBY strategy. An EQY `PASS` marker and zero driver return are required for pass. A `FAIL` marker becomes failed equivalence only when a counterexample VCD exists; without a trace it means the selected strategy did not establish the claim and remains blocked.

If either side depends on includes, macros, parameters, or functional cell models, use separate reference and implementation CompileManifest files. Do not rely on the process working directory: manifest-relative inputs are resolved and content-bound before the evidence runner enters an isolated artifact directory.

For STA record each clock/path group, setup and hold metrics, constrained/unconstrained endpoint counts, corner/library, command, input hashes, and raw reports. Audit false paths and multicycle paths; do not introduce them only to remove violations.

## Mapped synthesis to STA

Generic `verify synth` is a fast structural synthesizability check. It deliberately stops before technology mapping and cannot feed a timing-closure claim.

For a timing task, run `verify synth --liberty <cells.lib>`. This binds the exact Liberty file into the evidence identity, imports its cells as black boxes, maps the design with Yosys/ABC, and emits a unique `netlist.v` artifact. Do not include Verilog behavioral models for those same standard cells in this mapped-synthesis input; keep them in lint/simulation manifests only. A name collision is an invalid mapped input, not a reason to synthesize the cell models.

Pass that exact `netlist.v`, the same Liberty file, and the supplied SDC to `verify sta`. Prefer `--synthesis-evidence <run-evidence.json>` over manually copying the netlist path: this validates the passing mapped-synthesis record, current artifact hashes, Liberty subject hash, top, and unique `netlist.v` before OpenSTA starts. Do not run OpenSTA directly on behavioral RTL and describe it as post-synthesis timing. Inspect both evidence statuses and confirm the STA subject hashes bind the generated netlist, Liberty, and SDC.

For timing refinement, establish one baseline, make one coherent RTL change, then run functional regression or equivalence, mapped synthesis, and STA once on the final candidate. Stop when the required checks pass. Retry only for a diagnosed candidate or infrastructure defect; do not spend the task budget repeating unchanged evidence commands.

## Optimization

Freeze a functional baseline. Make one coherent structural hypothesis per candidate. Re-run regression and equivalence where applicable before accepting QoR changes. Keep a Pareto comparison of correctness, latency, timing, area, churn, and runtime instead of hiding correctness inside a weighted score.
