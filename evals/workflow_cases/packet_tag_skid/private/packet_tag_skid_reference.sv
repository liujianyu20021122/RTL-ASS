module packet_tag_skid #(
    parameter integer W=13, T=3,
    parameter [W-1:0] MASK=1
) (
    input wire clk, rst_n, in_valid,
    output wire in_ready,
    input wire [W-1:0] in_data,
    input wire in_last,
    input wire [T-1:0] in_tag,
    output wire out_valid,
    input wire out_ready,
    output wire [W-1:0] out_data,
    output wire out_last,
    output wire [T-1:0] out_tag
);
    reg [1:0] count;
    reg [W+T:0] front, spare;
    wire push = in_valid && in_ready;
    wire pop = out_valid && out_ready;
    wire [T-1:0] next_tag = in_tag + {{(T-1){1'b0}}, 1'b1};
    wire [W+T:0] beat = {in_data ^ MASK, in_last, next_tag};
    assign in_ready = count < 2;
    assign out_valid = count != 0;
    assign {out_data, out_last, out_tag} = front;
    always @(posedge clk) begin
        if (!rst_n) begin
            count <= 0;
            front <= 0;
            spare <= 0;
        end else begin
            case ({push,pop})
                2'b10: begin
                    if (count == 0) front <= beat;
                    else spare <= beat;
                    count <= count + 1'b1;
                end
                2'b01: begin
                    front <= spare;
                    count <= count - 1'b1;
                end
                2'b11: begin
                    if (count == 1) front <= beat;
                    else begin front <= spare; spare <= beat; end
                end
                default: begin end
            endcase
        end
    end
endmodule
