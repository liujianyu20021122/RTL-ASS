module registered_pulse #(
    parameter int unsigned WIDTH = 8
) (
    input  logic             clk,
    input  logic             rst_n,
    input  logic             valid_i,
    input  logic [WIDTH-1:0] data_i,
    output logic             valid_o,
    output logic [WIDTH-1:0] data_o
);
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            valid_o <= 1'b0;
            data_o <= '0;
        end else begin
            valid_o <= valid_i;
            if (valid_i) data_o <= data_i;
        end
    end
endmodule
