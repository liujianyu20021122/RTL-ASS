`timescale 1ns/1ps

module sat_add_pipe_hidden_tb;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic valid_i = 1'b0;
    logic signed [7:0] a_i = '0;
    logic signed [7:0] b_i = '0;
    logic valid_o;
    logic signed [5:0] y_o;

    sat_add_pipe dut (.*);
    always #5 clk = !clk;

    function automatic logic signed [5:0] reference(input integer a, input integer b);
        integer sum;
        begin
            sum = a + b;
            if (sum > 31) reference = 31;
            else if (sum < -32) reference = -32;
            else reference = sum;
        end
    endfunction

    task automatic check(input integer a, input integer b);
        logic signed [5:0] expected;
        expected = reference(a, b);
        @(negedge clk);
        valid_i = 1'b1;
        a_i = 8'(a);
        b_i = 8'(b);
        @(posedge clk);
        @(negedge clk);
        if (!valid_o || y_o !== expected) begin
            $fatal(1, "a=%0d b=%0d expected=%0d actual=%0d", a, b, expected, y_o);
        end
    endtask

    initial begin
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        check(127, 127);
        check(-128, -128);
        check(31, 0);
        check(32, 0);
        check(-32, 0);
        check(-33, 0);
        check(75, -60);
        check(-75, 60);
        check(100, 40);
        check(-100, -40);
        @(negedge clk);
        valid_i = 1'b0;
        @(posedge clk);
        @(negedge clk);
        if (valid_o) $fatal(1, "valid latency mismatch on bubble");
        $display("HIDDEN_SAT_ADD_PASS");
        $finish;
    end

    initial begin
        #5000;
        $fatal(1, "timeout");
    end
endmodule
