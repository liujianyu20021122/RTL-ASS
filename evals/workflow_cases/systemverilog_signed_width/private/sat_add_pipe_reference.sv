module sat_add_pipe_reference #(
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
    localparam int unsigned SUM_WIDTH = IN_WIDTH + 1;
    localparam logic signed [OUT_WIDTH-1:0] MAX_VALUE = {1'b0, {(OUT_WIDTH-1){1'b1}}};
    localparam logic signed [OUT_WIDTH-1:0] MIN_VALUE = {1'b1, {(OUT_WIDTH-1){1'b0}}};

    logic signed [SUM_WIDTH-1:0] sum;
    logic signed [SUM_WIDTH-1:0] max_extended;
    logic signed [SUM_WIDTH-1:0] min_extended;
    logic signed [OUT_WIDTH-1:0] saturated;

    always_comb begin
        sum = {a_i[IN_WIDTH-1], a_i} + {b_i[IN_WIDTH-1], b_i};
        max_extended = SUM_WIDTH'(MAX_VALUE);
        min_extended = SUM_WIDTH'(MIN_VALUE);
        if (sum > max_extended) saturated = MAX_VALUE;
        else if (sum < min_extended) saturated = MIN_VALUE;
        else saturated = OUT_WIDTH'(sum);
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
