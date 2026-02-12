module INV_X1 (input wire A, output wire Y);
    assign Y = ~A;
endmodule

module AND2_X1 (input wire A, input wire B, output wire Y);
    assign Y = A & B;
endmodule

module OR2_X1 (input wire A, input wire B, output wire Y);
    assign Y = A | B;
endmodule

module MUX2_X1 (input wire A, input wire B, input wire S, output wire Y);
    assign Y = S ? B : A;
endmodule
