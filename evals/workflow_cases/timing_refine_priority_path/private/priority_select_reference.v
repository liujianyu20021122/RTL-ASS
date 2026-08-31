module priority_select_reference (
    input  wire       clk,
    input  wire [3:0] request_i,
    input  wire [3:0] data_i,
    output wire       data_o
);
    wire not_request_1;
    wire not_request_2;
    wire not_request_3;
    wire no_32;
    wire no_321;
    wire term0_enable;
    wire term0;
    wire term1_enable;
    wire term1;
    wire term2_enable;
    wire term2;
    wire term3;
    wire upper_terms;
    wire lower_terms;

    INV_X1 u_not_1 (.A(request_i[1]), .Y(not_request_1));
    INV_X1 u_not_2 (.A(request_i[2]), .Y(not_request_2));
    INV_X1 u_not_3 (.A(request_i[3]), .Y(not_request_3));
    AND2_X1 u_no_32 (.A(not_request_3), .B(not_request_2), .Y(no_32));
    AND2_X1 u_no_321 (.A(no_32), .B(not_request_1), .Y(no_321));
    AND2_X1 u_term0_enable (.A(no_321), .B(request_i[0]), .Y(term0_enable));
    AND2_X1 u_term0 (.A(term0_enable), .B(data_i[0]), .Y(term0));
    AND2_X1 u_term1_enable (.A(no_32), .B(request_i[1]), .Y(term1_enable));
    AND2_X1 u_term1 (.A(term1_enable), .B(data_i[1]), .Y(term1));
    AND2_X1 u_term2_enable (.A(not_request_3), .B(request_i[2]), .Y(term2_enable));
    AND2_X1 u_term2 (.A(term2_enable), .B(data_i[2]), .Y(term2));
    AND2_X1 u_term3 (.A(request_i[3]), .B(data_i[3]), .Y(term3));
    OR2_X1 u_upper (.A(term3), .B(term2), .Y(upper_terms));
    OR2_X1 u_lower (.A(term1), .B(term0), .Y(lower_terms));
    OR2_X1 u_result (.A(upper_terms), .B(lower_terms), .Y(data_o));
endmodule
