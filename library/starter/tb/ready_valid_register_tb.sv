// SPDX-License-Identifier: Apache-2.0
`timescale 1ns/1ps

module ready_valid_register_tb;
    localparam int unsigned DATA_WIDTH = 8;

    logic                  clk = 1'b0;
    logic                  rst_n = 1'b0;
    logic                  in_valid = 1'b0;
    logic                  in_ready;
    logic [DATA_WIDTH-1:0] in_data = '0;
    logic                  out_valid;
    logic                  out_ready = 1'b0;
    logic [DATA_WIDTH-1:0] out_data;

    ready_valid_register #(.DATA_WIDTH(DATA_WIDTH)) dut (.*);

    always #5 clk = !clk;

    task automatic check_output(
        input logic expected_valid,
        input logic [DATA_WIDTH-1:0] expected_data,
        input string phase
    );
        #1;
        if (out_valid !== expected_valid) begin
            $fatal(1, "%s: out_valid expected %0b, got %0b", phase, expected_valid, out_valid);
        end
        if (expected_valid && out_data !== expected_data) begin
            $fatal(1, "%s: out_data expected 0x%0h, got 0x%0h", phase, expected_data, out_data);
        end
    endtask

    initial begin
        $dumpfile("ready_valid_register.vcd");
        $dumpvars(0, ready_valid_register_tb);

        repeat (2) @(posedge clk);
        rst_n <= 1'b1;
        @(posedge clk);
        check_output(1'b0, '0, "after reset");

        @(negedge clk);
        in_valid <= 1'b1;
        in_data  <= 8'hA5;
        @(posedge clk);
        check_output(1'b1, 8'hA5, "first transfer accepted");

        @(negedge clk);
        in_data <= 8'h3C;
        repeat (2) begin
            @(posedge clk);
            check_output(1'b1, 8'hA5, "payload held under backpressure");
        end

        @(negedge clk);
        out_ready <= 1'b1;
        @(posedge clk);
        check_output(1'b1, 8'h3C, "simultaneous dequeue and enqueue");

        @(negedge clk);
        in_valid <= 1'b0;
        @(posedge clk);
        check_output(1'b0, '0, "drained");

        $display("PASS: ready_valid_register");
        $finish;
    end

    initial begin
        repeat (30) @(posedge clk);
        $fatal(1, "timeout");
    end
endmodule
