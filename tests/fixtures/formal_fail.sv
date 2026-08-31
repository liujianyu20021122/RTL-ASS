module formal_fail (
    input logic [1:0] value
);
    always_comb begin
        assert (value == 2'b00);
    end
endmodule
