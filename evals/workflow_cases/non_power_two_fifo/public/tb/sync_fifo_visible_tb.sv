module sync_fifo_visible_tb;
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

    sync_fifo #(.WIDTH(WIDTH), .DEPTH(DEPTH)) dut (.*);

    always #5 clk = ~clk;

    task automatic put(input logic [WIDTH-1:0] value);
        @(negedge clk);
        push = 1'b1;
        din = value;
        @(negedge clk);
        push = 1'b0;
    endtask

    task automatic get_and_expect(input logic [WIDTH-1:0] expected);
        @(negedge clk);
        if (empty || dout !== expected) begin
            $fatal(1, "FIFO mismatch: expected=%0h actual=%0h empty=%0b", expected, dout, empty);
        end
        pop = 1'b1;
        @(negedge clk);
        pop = 1'b0;
    endtask

    initial begin
        repeat (2) @(negedge clk);
        rst_n = 1'b1;
        put(8'h11);
        put(8'h22);
        put(8'h33);
        get_and_expect(8'h11);
        get_and_expect(8'h22);
        get_and_expect(8'h33);
        put(8'h44);
        get_and_expect(8'h44);
        if (!empty) $fatal(1, "FIFO must be empty after balanced traffic");
        $display("VISIBLE_PASS");
        $finish;
    end

    initial begin
        #2000;
        $fatal(1, "timeout");
    end
endmodule
