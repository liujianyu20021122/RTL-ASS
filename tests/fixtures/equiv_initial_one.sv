module equiv_initial_one (
    input  logic clk,
    output logic q = 1'b1
);
    always_ff @(posedge clk) begin
        q <= 1'b0;
    end
endmodule
