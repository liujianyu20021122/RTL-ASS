// SPDX-License-Identifier: Apache-2.0
module ready_valid_register_formal #(
    parameter int unsigned DATA_WIDTH = 8
) (
    input logic                  clk,
    input logic                  rst_n,
    input logic                  in_valid,
    input logic [DATA_WIDTH-1:0] in_data,
    input logic                  out_ready
);
    logic                  in_ready;
    logic                  out_valid;
    logic [DATA_WIDTH-1:0] out_data;

    ready_valid_register #(.DATA_WIDTH(DATA_WIDTH)) dut (.*);

    always_comb begin
        assert (in_ready == (!out_valid || out_ready));
        if (out_valid && !out_ready) begin
            assert (!in_ready);
        end
    end
endmodule
