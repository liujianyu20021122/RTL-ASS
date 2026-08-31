`timescale 1ns/1ps

module ready_valid_register_hidden_tb;
    localparam int unsigned DATA_WIDTH = 5;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic in_valid = 1'b0;
    logic in_ready;
    logic [DATA_WIDTH-1:0] in_data = '0;
    logic out_valid;
    logic out_ready = 1'b0;
    logic [DATA_WIDTH-1:0] out_data;

    logic [DATA_WIDTH-1:0] model [0:63];
    int unsigned head = 0;
    int unsigned tail = 0;
    int unsigned count = 0;

    ready_valid_register #(.DATA_WIDTH(DATA_WIDTH)) dut (.*);

    always #5 clk = !clk;

    task automatic cycle(
        input logic drive_valid,
        input logic drive_ready,
        input logic [DATA_WIDTH-1:0] value
    );
        logic accepted_input;
        logic accepted_output;
        @(negedge clk);
        if (out_valid !== (count != 0)) begin
            $fatal(1, "out_valid mismatch count=%0d", count);
        end
        if (count != 0 && out_data !== model[head]) begin
            $fatal(1, "out_data mismatch expected=%0h actual=%0h", model[head], out_data);
        end
        in_valid = drive_valid;
        in_data = value;
        out_ready = drive_ready;
        #1;
        accepted_input = in_valid && in_ready;
        accepted_output = out_valid && out_ready;
        @(posedge clk);
        #1;
        if (accepted_output) begin
            head = head + 1;
            count = count - 1;
        end
        if (accepted_input) begin
            model[tail] = value;
            tail = tail + 1;
            count = count + 1;
        end
        if (count > 1) $fatal(1, "one-entry occupancy exceeded");
    endtask

    initial begin
        repeat (2) @(negedge clk);
        rst_n = 1'b1;

        cycle(1, 0, 5'h03);
        cycle(1, 0, 5'h07);
        cycle(1, 1, 5'h0b);
        cycle(1, 1, 5'h0d);
        cycle(0, 1, '0);
        cycle(0, 0, '0);

        for (int unsigned i = 0; i < 20; i++) begin
            cycle(i[0], i[1], DATA_WIDTH'(i + 1));
        end
        while (count != 0) cycle(0, 1, '0);

        @(negedge clk);
        if (out_valid || !in_ready) $fatal(1, "final empty state mismatch");
        $display("HIDDEN_READY_VALID_PASS");
        $finish;
    end

    initial begin
        #10000;
        $fatal(1, "timeout");
    end
endmodule
