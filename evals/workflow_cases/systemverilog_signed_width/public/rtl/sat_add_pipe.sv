module sat_add_pipe #(
    parameter int unsigned IN_WIDTH = 8,
    parameter int unsigned OUT_WIDTH = 6
) (
    input  logic                           clk,
    input  logic                           rst_n,
    input  logic                           valid_i,
    input  logic signed [IN_WIDTH-1:0]     a_i,
    input  logic signed [IN_WIDTH-1:0]     b_i,
    output logic                           valid_o,
    output logic signed [OUT_WIDTH-1:0]    y_o
);
    localparam logic signed [OUT_WIDTH-1:0] MAX_VALUE = {1'b0, {(OUT_WIDTH-1){1'b1}}};
    localparam logic signed [OUT_WIDTH-1:0] MIN_VALUE = {1'b1, {(OUT_WIDTH-1){1'b0}}};

    logic signed [IN_WIDTH-1:0] sum;
    logic signed [OUT_WIDTH-1:0] saturated;

    always_comb begin
        sum = a_i + b_i;
        if (sum > MAX_VALUE) begin
            saturated = MAX_VALUE;
        end else if (sum < MIN_VALUE) begin
            saturated = MIN_VALUE;
        end else begin
            saturated = OUT_WIDTH'(sum);
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            valid_o <= 1'b0;
            y_o <= '0;
        end else begin
            valid_o <= valid_i;
            y_o <= saturated;
        end
    end
endmodule
