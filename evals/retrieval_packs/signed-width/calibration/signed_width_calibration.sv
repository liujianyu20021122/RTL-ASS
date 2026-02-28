module signed_width_calibration;
    localparam int IN_WIDTH = 4;
    localparam int OUT_WIDTH = 3;
    localparam int SUM_WIDTH = IN_WIDTH + 1;

    function automatic logic signed [OUT_WIDTH-1:0] reference_saturate(input integer value);
        integer maximum;
        integer minimum;
        begin
            maximum = (1 << (OUT_WIDTH - 1)) - 1;
            minimum = -(1 << (OUT_WIDTH - 1));
            if (value > maximum)
                reference_saturate = OUT_WIDTH'(maximum);
            else if (value < minimum)
                reference_saturate = OUT_WIDTH'(minimum);
            else
                reference_saturate = OUT_WIDTH'(value);
        end
    endfunction

    function automatic logic signed [OUT_WIDTH-1:0] explicit_saturate(
        input logic signed [IN_WIDTH-1:0] left,
        input logic signed [IN_WIDTH-1:0] right
    );
        logic signed [SUM_WIDTH-1:0] sum;
        logic signed [SUM_WIDTH-1:0] maximum;
        logic signed [SUM_WIDTH-1:0] minimum;
        begin
            sum = {left[IN_WIDTH-1], left} + {right[IN_WIDTH-1], right};
            maximum = SUM_WIDTH'((1 << (OUT_WIDTH - 1)) - 1);
            minimum = SUM_WIDTH'(-(1 << (OUT_WIDTH - 1)));
            if (sum > maximum)
                explicit_saturate = OUT_WIDTH'(maximum);
            else if (sum < minimum)
                explicit_saturate = OUT_WIDTH'(minimum);
            else
                explicit_saturate = OUT_WIDTH'(sum);
        end
    endfunction

    function automatic logic signed [OUT_WIDTH-1:0] narrow_mutant(
        input logic signed [IN_WIDTH-1:0] left,
        input logic signed [IN_WIDTH-1:0] right
    );
        logic signed [IN_WIDTH-1:0] sum;
        begin
            sum = left + right;
            narrow_mutant = reference_saturate(sum);
        end
    endfunction

    integer left_value;
    integer right_value;
    integer mutant_mismatches;
    logic signed [IN_WIDTH-1:0] left_operand;
    logic signed [IN_WIDTH-1:0] right_operand;
    logic signed [OUT_WIDTH-1:0] expected;
    logic signed [OUT_WIDTH-1:0] observed;

    initial begin
        mutant_mismatches = 0;
        for (left_value = -(1 << (IN_WIDTH - 1)); left_value < (1 << (IN_WIDTH - 1)); left_value++) begin
            for (right_value = -(1 << (IN_WIDTH - 1)); right_value < (1 << (IN_WIDTH - 1)); right_value++) begin
                left_operand = IN_WIDTH'(left_value);
                right_operand = IN_WIDTH'(right_value);
                expected = reference_saturate(left_value + right_value);
                observed = explicit_saturate(left_operand, right_operand);
                if (observed !== expected)
                    $fatal(1, "explicit sizing mismatch: left=%0d right=%0d expected=%0d observed=%0d",
                           left_value, right_value, expected, observed);
                if (narrow_mutant(left_operand, right_operand) !== expected)
                    mutant_mismatches = mutant_mismatches + 1;
            end
        end
        if (mutant_mismatches == 0)
            $fatal(1, "narrow intermediate mutant was not detected");
        if (explicit_saturate(4'sd7, 4'sd7) !== 3'sd3)
            $fatal(1, "positive saturation boundary failed");
        if (explicit_saturate(4'sh8, 4'sh8) !== 3'sh4)
            $fatal(1, "negative saturation boundary failed");
        if (explicit_saturate(4'sd2, -4'sd1) !== 3'sd1)
            $fatal(1, "mixed-sign interior case failed");
        $display("SIGNED_WIDTH_CALIBRATION_PASS mutant_mismatches=%0d", mutant_mismatches);
        $finish;
    end
endmodule
