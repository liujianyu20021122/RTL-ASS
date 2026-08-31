module counter_tb;
    logic clk = 1'b0;
    logic rst_n = 1'b0;
    logic enable = 1'b0;
    logic [7:0] count;

    counter dut (.*);

    always #5 clk = ~clk;

    initial begin
        repeat (2) @(posedge clk);
        rst_n <= 1'b1;
        enable <= 1'b1;
        repeat (3) @(posedge clk);
        assert (count == 2);
        $finish;
    end
endmodule
