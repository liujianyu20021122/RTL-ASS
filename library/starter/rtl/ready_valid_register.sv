// SPDX-License-Identifier: Apache-2.0
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
    assign in_ready = !out_valid || out_ready;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            out_data  <= '0;
        end else if (in_ready) begin
            out_valid <= in_valid;
            if (in_valid) begin
                out_data <= in_data;
            end
        end
    end
endmodule
