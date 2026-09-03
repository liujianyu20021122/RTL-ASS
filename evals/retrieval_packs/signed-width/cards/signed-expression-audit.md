# Auditing signed SystemVerilog expressions

When arithmetic must preserve values beyond an operand's declared width, determine the required mathematical range first and size the intermediate expression explicitly. Do not assume that assigning an expression to a wider destination retroactively widens the operands or changes the expression's signedness.

At every arithmetic or comparison boundary, record:

- each operand's width and signedness;
- the expression width and signedness before assignment;
- the mathematical bounds needed by later range checks;
- the cycle at which the value is sampled and observed.

Extend operands deliberately before addition or subtraction. Make comparison operands compatible in width and signedness instead of relying on contextual coercion. Check the most-positive value, most-negative value, one value inside each limit, mixed-sign operands, and reset/valid latency.

This card is diagnostic guidance. It does not specify a module interface, constants, pipeline implementation, or patch.
