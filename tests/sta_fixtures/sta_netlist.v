module sta_top (
    input  wire clk,
    input  wire data_in,
    output wire data_out
);
    BUF_X1 u_buffer (
        .A(data_in),
        .Y(data_out)
    );
endmodule
