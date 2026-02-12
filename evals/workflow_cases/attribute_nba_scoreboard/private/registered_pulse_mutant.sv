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
    logic pending_valid;
    logic [WIDTH-1:0] pending_data;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            pending_valid <= 1'b0;
            pending_data <= '0;
            valid_o <= 1'b0;
            data_o <= '0;
        end else begin
            pending_valid <= valid_i;
            pending_data <= data_i;
            valid_o <= pending_valid;
            if (pending_valid) data_o <= pending_data;
        end
    end
endmodule
