module mapped_logic (
    input  logic a,
    input  logic b,
    input  logic select,
    output logic y
);
    assign y = select ? (a & b) : ~(a | b);
endmodule
