`timescale 1ns/1ps

module registered_pulse_tb;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic valid_i = 1'b0;
    logic [7:0] data_i = '0;
    logic valid_o;
    logic [7:0] data_o;
    logic expected_valid;
    logic [7:0] expected_data;

    registered_pulse dut (.*);

    always #5 clk = !clk;

    task automatic drive_and_check(input logic valid, input logic [7:0] value);
        @(negedge clk);
        valid_i = valid;
        data_i = value;
        @(posedge clk);
        expected_valid = valid_i;
        expected_data = data_i;
        if (valid_o !== expected_valid) begin
            $fatal(1, "valid mismatch expected=%0b actual=%0b", expected_valid, valid_o);
        end
        if (expected_valid && data_o !== expected_data) begin
            $fatal(1, "data mismatch expected=%0h actual=%0h", expected_data, data_o);
        end
    endtask

    initial begin
        if ($test$plusargs("DUMP")) begin
            $dumpfile("artifacts/registered_pulse.vcd");
            $dumpvars(0, registered_pulse_tb);
        end
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        drive_and_check(1'b1, 8'h12);
        drive_and_check(1'b0, '0);
        drive_and_check(1'b1, 8'h34);
        drive_and_check(1'b1, 8'h56);
        drive_and_check(1'b0, '0);
        $display("REGISTERED_PULSE_PASS");
        $finish;
    end

    initial begin
        #1000;
        $fatal(1, "timeout");
    end
endmodule
