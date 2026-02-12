# One-entry ready/valid register contract

Create `rtl/ready_valid_register.sv` and `tb/ready_valid_register_tb.sv`.

The synthesizable module must be named `ready_valid_register` and expose:

```systemverilog
module ready_valid_register #(
    parameter int unsigned DATA_WIDTH = 8
) (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic                  in_valid,
    output logic                  in_ready,
    input  logic [DATA_WIDTH-1:0] in_data,
    output logic                  out_valid,
    input  logic                  out_ready,
    output logic [DATA_WIDTH-1:0] out_data
);
```

The block is a one-entry elastic buffer. A transfer occurs only when `valid && ready` is true. While an output item is stalled, `out_valid` and `out_data` must remain stable. When the current output is accepted, a new input may replace it on the same rising edge without a bubble. Active-low synchronous reset clears `out_valid` and `out_data`. The design must work for multiple positive `DATA_WIDTH` values.

The testbench top must be `ready_valid_register_tb`, must terminate on success, must have a timeout, and must fail for a DUT that violates the one-entry latency or backpressure contract.
