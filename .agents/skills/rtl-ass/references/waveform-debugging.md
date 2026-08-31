# Waveform debugging

Use machine-readable VCD/FST queries before opening a GUI or loading an unbounded trace into context.

For FST, bind the original FST hash, converter executable hash/version, exact conversion command, converted VCD hash, timeout, and maximum converted bytes. A converter failure, timeout, or expansion-limit breach is blocked evidence, not an empty or matching waveform.

## Procedure

1. Confirm the waveform belongs to the failing source and test hashes.
2. Identify clock/reset domains and the transaction or assertion that first reports failure.
3. Search backward to the first divergence between expected and observed behavior.
4. Extract a bounded window and the smallest relevant signal cone.
5. State the sampling edge/region, expected value, actual value, and causal chain.
6. Map signals and source lines back to original modules, not concatenated temporary sources.
7. After a patch, replay the same window and then run the wider regression.

## Common traps

- final mismatch mistaken for root cause;
- NBA-updated values sampled in the wrong region;
- READY/VALID acceptance inferred from post-edge deasserted signals;
- reset deassertion races;
- X converted to zero by a 2-state checker;
- unrelated clock domains compared by cycle number;
- stale waveform from a different candidate.

Do not report a waveform diff if no waveform parser or simulator event evidence was read.
