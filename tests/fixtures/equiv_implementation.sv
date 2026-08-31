module equiv_implementation (
    input  logic a,
    input  logic b,
    output logic y
);
    always_comb begin
        y = (a | b) & ~(a & b);
    end
endmodule
