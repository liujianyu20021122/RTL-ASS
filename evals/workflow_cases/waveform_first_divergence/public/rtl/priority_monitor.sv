module priority_monitor (
    input  logic [1:0] request_i,
    input  logic [1:0] data_i,
    output logic       actual_o
);
    always_comb begin
        if (request_i[1]) begin
            actual_o = data_i[1];
        end else begin
            actual_o = data_i[0];
        end
    end
endmodule
