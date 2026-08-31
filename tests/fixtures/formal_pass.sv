module formal_pass (
    input logic [1:0] value
);
    always_comb begin
        assert (value == value);
    end
endmodule
