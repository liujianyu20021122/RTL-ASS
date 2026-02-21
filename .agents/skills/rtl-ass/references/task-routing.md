# RTL task routing

Use this reference when a request combines design, debug, verification, optimization, or knowledge work.

## Generation

Extract observable behavior before choosing microarchitecture: interfaces, legal transactions, ordering, backpressure, reset behavior, latency, throughput, parameter ranges, and error handling. Resolve material ambiguity or make a clearly stated reversible assumption. Codex writes the implementation and a verification plan together.

## Existing-design analysis

Start from the actual build boundary: source list, includes, defines, parameters, top, clock/reset domains, tests, and constraints. Separate facts found in source or tool output from inference. Trace behavior through hierarchy rather than reviewing files independently.

## Debugging

Reproduce on unchanged inputs, preserve the failing artifact, locate the first divergence, and maintain competing hypotheses across specification, TB, RTL, constraints, and infrastructure. Prefer a minimal patch after the cause is supported. Replay the focused case, then the broader regression.

## Verification

Translate requirements into checks. Use directed edge cases, assertions, reference models, constrained/random exploration, coverage, mutation, and formal where each adds distinct confidence. Assess the testbench itself; a weak checker can pass a broken DUT.

Select evidence by claim, not by habit:

| Claim | Normal first evidence | Add only when needed |
|---|---|---|
| TB/scoreboard behavior | focused self-checking simulation | waveform for sampling/divergence diagnosis |
| RTL functional repair | lint and focused self-checking simulation | independent frontend or equivalence for a concrete semantic risk |
| Width, signedness, or parameter boundary | lint and boundary simulation | equivalence when a trustworthy reference exists |
| Assertion/property behavior | bounded formal with explicit scope | deeper bound only when the property requires it |
| Synthesizability, area, or structure | synthesis | mapped synthesis when a Liberty-specific claim exists |
| Timing | Liberty-mapped synthesis and linked STA | functional/equivalence evidence to freeze behavior |

Do not synthesize a TB-only change, produce a waveform without a trace question, run formal without a property claim, or run STA without a mapped netlist, Liberty, and constraints.

## Optimization

Freeze behavior and baseline metrics first. Generate bounded alternatives, then require functional regression and equivalence when applicable before comparing synthesis or timing evidence. Treat interface latency, protocol, clocks, and exceptions as contract changes.

## Knowledge work

Search before ingesting duplicates. Imported content stays raw or candidate. Distill reusable behavior, constraints, evidence, and failure conditions instead of treating complete upstream files as universally applicable templates.
