`timescale 1ns/1ps

module registered_pulse_hidden_tb;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic valid_i = 1'b0;
    logic [7:0] data_i = '0;
    logic valid_o;
    logic [7:0] data_o;

    registered_pulse dut (.*);
    always #5 clk = !clk;

    task automatic check(input logic valid, input logic [7:0] value);
        @(negedge clk);
        valid_i = valid;
        data_i = value;
        @(posedge clk);
        @(negedge clk);
        if (valid_o !== valid) $fatal(1, "valid_o mismatch");
        if (valid && data_o !== value) $fatal(1, "data_o mismatch");
    endtask

    initial begin
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        check(1, 8'ha5);
        check(0, '0);
        check(1, 8'h5a);
        check(1, 8'hc3);
        check(0, '0);
        $display("HIDDEN_REGISTERED_PULSE_PASS");
        $finish;
    end

    initial begin
        #2000;
        $fatal(1, "timeout");
    end
endmodule
