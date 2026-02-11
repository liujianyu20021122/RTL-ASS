module sync_fifo_hidden_tb;
    localparam int WIDTH = 8;
    localparam int DEPTH = 3;

    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic push = 1'b0;
    logic pop = 1'b0;
    logic [WIDTH-1:0] din = '0;
    logic [WIDTH-1:0] dout;
    logic full;
    logic empty;
    logic [WIDTH-1:0] model [0:127];
    int head = 0;
    int tail = 0;
    int occupancy = 0;

    sync_fifo #(.WIDTH(WIDTH), .DEPTH(DEPTH)) dut (.*);

    always #5 clk = ~clk;

    task automatic cycle(input logic do_push, input logic do_pop, input logic [WIDTH-1:0] value);
        logic accepted_push;
        logic accepted_pop;
        @(negedge clk);
        if (!empty && dout !== model[head]) begin
            $fatal(1, "pre-cycle mismatch expected=%0h actual=%0h", model[head], dout);
        end
        accepted_push = do_push && !full;
        accepted_pop = do_pop && !empty;
        push = do_push;
        pop = do_pop;
        din = value;
        @(posedge clk);
        #1;
        if (accepted_push) begin
            model[tail] = value;
            tail = tail + 1;
        end
        if (accepted_pop) begin
            head = head + 1;
        end
        occupancy = occupancy + accepted_push - accepted_pop;
        if (empty !== (occupancy == 0)) $fatal(1, "empty flag mismatch occupancy=%0d", occupancy);
        if (full !== (occupancy == DEPTH)) $fatal(1, "full flag mismatch occupancy=%0d", occupancy);
        push = 1'b0;
        pop = 1'b0;
    endtask

    initial begin
        repeat (2) @(negedge clk);
        rst_n = 1'b1;

        cycle(1, 0, 8'h10);
        cycle(1, 0, 8'h20);
        cycle(1, 0, 8'h30);
        cycle(1, 0, 8'hff); // rejected while full
        cycle(0, 1, '0);
        cycle(1, 1, 8'h40);
        cycle(0, 1, '0);
        cycle(0, 1, '0);
        cycle(0, 1, '0);
        cycle(0, 1, '0); // rejected while empty

        for (int unsigned i = 0; i < 24; i++) begin
            cycle(1, 0, WIDTH'(i + 8'h50));
            cycle(0, 1, '0);
        end

        if (occupancy != 0 || !empty || full) $fatal(1, "final state mismatch");
        $display("HIDDEN_PASS");
        $finish;
    end

    initial begin
        #10000;
        $fatal(1, "timeout");
    end
endmodule
