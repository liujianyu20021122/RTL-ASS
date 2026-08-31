module sync_fifo #(
    parameter int unsigned WIDTH = 8,
    parameter int unsigned DEPTH = 3
) (
    input  logic             clk,
    input  logic             rst_n,
    input  logic             push,
    input  logic             pop,
    input  logic [WIDTH-1:0] din,
    output logic [WIDTH-1:0] dout,
    output logic             full,
    output logic             empty
);
    localparam int unsigned PTR_W = (DEPTH <= 2) ? 1 : $clog2(DEPTH);
    localparam int unsigned COUNT_W = $clog2(DEPTH + 1);

    logic [WIDTH-1:0] mem [0:DEPTH-1];
    logic [PTR_W-1:0] write_ptr;
    logic [PTR_W-1:0] read_ptr;
    logic [COUNT_W-1:0] count;

    assign full  = (count == COUNT_W'(DEPTH));
    assign empty = (count == '0);
    assign dout  = mem[read_ptr];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            write_ptr <= '0;
            read_ptr  <= '0;
            count     <= '0;
        end else begin
            if (push && !full) begin
                mem[write_ptr] <= din;
                write_ptr      <= write_ptr + 1'b1;
            end
            if (pop && !empty) begin
                read_ptr <= read_ptr + 1'b1;
            end
            unique case ({push && !full, pop && !empty})
                2'b10: count <= count + 1'b1;
                2'b01: count <= count - 1'b1;
                default: count <= count;
            endcase
        end
    end
endmodule
