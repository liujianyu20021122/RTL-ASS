# Priority-select timing refinement contract

`rtl/priority_select.v` implements a four-request combinational priority selector. Bit 3 has highest priority, bit 0 has lowest priority, and `data_o` is zero when no request is asserted. Preserve the exact module ports and combinational latency contract.

The supplied source is also the structural gate netlist consumed by OpenSTA. Functional cell models are in `lib/cells.v`; matching timing models are in `lib/cells.lib`. `constraints/priority_select.sdc` is the complete timing contract. Do not modify the interface, cell models, Liberty, SDC, testbench, or add timing exceptions.

First record the baseline timing result. Then change only `rtl/priority_select.v` to an equivalent topology that removes the measured priority-path setup violation. Run the supplied self-checking simulation, lint, synthesis, an independently structured equivalence check through at least one combinational step, and real OpenSTA. A successful result must have nonnegative setup and hold worst slack, one clock, and zero unconstrained endpoints.

Place verification-only reference files and evidence under `artifacts/`. Report exact baseline and final timing metrics; a synthesis estimate is not STA.
