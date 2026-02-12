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

Equivalence must bind separate reference and implementation identities. Depth 1 may support a combinational equivalence claim after compatible elaboration; a larger `equiv_simple -seq` depth is bounded-sequential evidence. The default `--input-domain defined` proves ordinary hardware bit behavior. Use `--input-domain undefined` only when X/undefined propagation is part of the stated contract; algebraically equivalent topologies can intentionally differ there. The input domain is part of the evidence hash. Unproven `$equiv` cells are a failed equivalence result, while interface/elaboration/tool failures are blocked evidence.

If either side depends on packages, interfaces, or functional cell models, pass each dependency explicitly with repeated `--reference-source` and `--implementation-source` options in compilation order. Do not rely on a relative Verilog `` `include `` path: the evidence runner executes Yosys from its isolated artifact directory.

For STA record each clock/path group, setup and hold metrics, constrained/unconstrained endpoint counts, corner/library, command, input hashes, and raw reports. Audit false paths and multicycle paths; do not introduce them only to remove violations.

## Optimization

Freeze a functional baseline. Make one coherent structural hypothesis per candidate. Re-run regression and equivalence where applicable before accepting QoR changes. Keep a Pareto comparison of correctness, latency, timing, area, churn, and runtime instead of hiding correctness inside a weighted score.
