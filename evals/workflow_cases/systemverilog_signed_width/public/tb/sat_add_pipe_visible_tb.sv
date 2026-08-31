`timescale 1ns/1ps

module sat_add_pipe_visible_tb;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic valid_i = 1'b0;
    logic signed [7:0] a_i = '0;
    logic signed [7:0] b_i = '0;
    logic valid_o;
    logic signed [5:0] y_o;

    sat_add_pipe dut (.*);
    always #5 clk = !clk;

    task automatic check(input logic signed [7:0] a, input logic signed [7:0] b, input logic signed [5:0] expected);
        @(negedge clk);
        valid_i = 1'b1;
        a_i = a;
        b_i = b;
        @(posedge clk);
        @(negedge clk);
        if (!valid_o || y_o !== expected) begin
            $fatal(1, "expected=%0d actual=%0d valid=%0b", expected, y_o, valid_o);
        end
    endtask

    initial begin
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        check(8'sd100, 8'sd100, 6'sd31);
        check(-8'sd100, -8'sd100, -6'sd32);
        check(8'sd12, -8'sd5, 6'sd7);
        $display("VISIBLE_SAT_ADD_PASS");
        $finish;
    end

    initial begin
        #2000;
        $fatal(1, "timeout");
    end
endmodule
