module equiv_initial_zero (
    input  logic clk,
    output logic q = 1'b0
);
    always_ff @(posedge clk) begin
        q <= 1'b0;
    end
endmodule
