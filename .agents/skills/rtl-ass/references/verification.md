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

For bounded formal, require at least one assertion after elaboration, record the bound and initialization assumptions, and retain the counterexample. A passing bound does not establish behavior beyond that bound. For equivalence, keep the reference and implementation source identities and tops distinct; do not compare a candidate with itself or erase the direction of the comparison.

## RTL versus TB attribution

Check whether stimulus matches the specification, the checker samples the intended phase, expected values use the correct transaction, the DUT revision matches the waveform, and source-map lines refer to original files. Preserve both RTL and TB hypotheses until one is contradicted by evidence.

## Testbench knowledge records

Index a TB separately from its DUT. Link exact hashes and record simulator, command, parameters, expected contract, observed outcome, coverage, and known limitations. A TB is reusable only when its assumptions are explicit.
