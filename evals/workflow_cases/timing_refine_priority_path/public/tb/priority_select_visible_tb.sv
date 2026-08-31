`timescale 1ns/1ps

module priority_select_visible_tb;
    logic clk = 1'b0;
    logic [3:0] request_i = '0;
    logic [3:0] data_i = '0;
    logic data_o;

    priority_select dut (.*);
    always #5 clk = !clk;

    task automatic check(input logic [3:0] request_value, input logic [3:0] data_value, input logic expected);
        request_i = request_value;
        data_i = data_value;
        #1;
        if (data_o !== expected) begin
            $fatal(1, "request=%b data=%b expected=%b actual=%b", request_value, data_value, expected, data_o);
        end
    endtask

    initial begin
        check(4'b0000, 4'b1111, 1'b0);
        check(4'b0001, 4'b0001, 1'b1);
        check(4'b0101, 4'b1111, 1'b1);
        check(4'b1101, 4'b0111, 1'b0);
        check(4'b1111, 4'b1010, 1'b1);
        $display("VISIBLE_PRIORITY_SELECT_PASS");
        $finish;
    end

    initial begin
        #1000;
        $fatal(1, "timeout");
    end
endmodule
