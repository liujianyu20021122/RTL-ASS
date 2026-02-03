# RTL design guidance

## Contract before structure

Record ports, parameters, accepted transactions, ordering, reset state, latency, throughput, backpressure, arithmetic rules, and illegal inputs. Preserve these constraints across refinement.

## Sequential semantics

- Use nonblocking assignments for clocked state and blocking assignments for local combinational calculation unless a justified style requires otherwise.
- Define priority intentionally when multiple conditions update the same state.
- Account for SystemVerilog scheduling regions in both DUT and checker; a delay such as `#1` is not a protocol definition.
- Give combinational outputs complete assignments and avoid unintended storage, multiple drivers, and combinational loops.

## Width and arithmetic

- Derive intermediate widths deliberately. Check signedness at every mixed signed/unsigned boundary.
- Make truncation, saturation, rounding, overflow, and division behavior part of the contract.
- Validate parameter corner cases such as width one, depth one, non-power-of-two depth, and `$clog2` results.

## Protocol and state

- Define transaction acceptance exactly, for example `valid && ready` at a named sampling edge.
- Hold payload and control stable under backpressure when the protocol requires it.
- For FSMs, document state meaning, legal transitions, output timing, and recovery behavior; avoid adding default recovery that hides an unreachable-state defect.
- Treat CDC/RDC structures separately from ordinary data paths. A two-flop synchronizer is for suitable single-bit level signals, not arbitrary buses or pulse protocols.

## Timing-aware coding

Prefer clear register boundaries, bounded priority depth, deliberate fanout, and inference-friendly memories/arithmetic. Do not add pipeline stages unless the latency contract permits them. Validate any optimization against behavior before considering QoR evidence.
