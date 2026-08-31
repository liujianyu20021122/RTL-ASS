`timescale 1ns/1ps

module priority_select_hidden_tb;
    logic clk = 1'b0;
    logic [3:0] request_i = '0;
    logic [3:0] data_i = '0;
    logic data_o;
    logic expected;

    priority_select dut (.*);
    always #5 clk = !clk;

    initial begin
        for (int unsigned request_value = 0; request_value < 16; request_value++) begin
            for (int unsigned data_value = 0; data_value < 16; data_value++) begin
                request_i = 4'(request_value);
                data_i = 4'(data_value);
                expected = 1'b0;
                for (int index = 0; index < 4; index++) begin
                    if (request_i[index]) expected = data_i[index];
                end
                #1;
                if (data_o !== expected) begin
                    $fatal(1, "request=%b data=%b expected=%b actual=%b", request_i, data_i, expected, data_o);
                end
            end
        end
        $display("HIDDEN_PRIORITY_SELECT_PASS");
        $finish;
    end

    initial begin
        #10000;
        $fatal(1, "timeout");
    end
endmodule
