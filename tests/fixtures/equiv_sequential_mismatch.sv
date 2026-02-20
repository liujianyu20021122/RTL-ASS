module equiv_sequential_mismatch (
    input  logic clk,
    input  logic d,
    output logic q
);
    always_ff @(posedge clk) begin
        q <= 1'b0;
    end
endmodule
