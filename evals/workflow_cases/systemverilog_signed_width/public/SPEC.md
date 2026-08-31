# Signed saturating adder pipeline contract

`rtl/sat_add_pipe.sv` computes the mathematical signed sum of `a_i` and `b_i`, then saturates it to the declared `OUT_WIDTH` range. It must preserve the public widths and support positive `IN_WIDTH >= OUT_WIDTH >= 2` values.

`valid_o` is `valid_i` registered by one rising edge. `y_o` is also registered every non-reset rising edge, regardless of `valid_i`; `valid_o` declares whether that cycle carries a transaction. Active-low synchronous reset clears both outputs. There is no rounding or extra pipeline stage.

Repair only the RTL. The supplied self-checking testbench is part of the contract and must remain unchanged.

This evaluation requires equivalence evidence in addition to lint and simulation. Create a verification-only, independently structured mathematical reference under `artifacts/` rather than copying the repaired RTL, then record bounded sequential equivalence through at least four rising edges. State the reference scope and any initialization assumptions. The reference is evidence, not a second product implementation.
