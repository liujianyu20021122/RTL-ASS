module priority_select (
    input  wire       clk,
    input  wire [3:0] request_i,
    input  wire [3:0] data_i,
    output wire       data_o
);
    wire stage0;
    wire stage1;
    wire stage2;

    MUX2_X1 u_priority_0 (.A(1'b0),  .B(data_i[0]), .S(request_i[0]), .Y(stage0));
    MUX2_X1 u_priority_1 (.A(stage0), .B(data_i[1]), .S(request_i[1]), .Y(stage1));
    MUX2_X1 u_priority_2 (.A(stage1), .B(data_i[2]), .S(request_i[2]), .Y(stage2));
    MUX2_X1 u_priority_3 (.A(stage2), .B(data_i[3]), .S(request_i[3]), .Y(data_o));
endmodule
