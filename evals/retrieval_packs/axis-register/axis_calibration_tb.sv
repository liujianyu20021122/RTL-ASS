`timescale 1ns/1ps
module axis_calibration_tb;
    parameter integer MODE=2;
    reg clk=0, rst=1;
    always #5 clk=~clk;
    reg [12:0] s_axis_tdata=0;
    wire [12:0] m_axis_tdata;
    reg [1:0] s_axis_tkeep=0;
    wire [1:0] m_axis_tkeep;
    reg s_axis_tvalid=0, s_axis_tlast=0, m_axis_tready=0;
    wire s_axis_tready, m_axis_tvalid, m_axis_tlast;
    reg [2:0] s_axis_tid=0, s_axis_tdest=0;
    wire [2:0] m_axis_tid, m_axis_tdest;
    reg s_axis_tuser=0;
    wire m_axis_tuser;
    axis_register #(.DATA_WIDTH(13),.KEEP_ENABLE(1),.KEEP_WIDTH(2),.LAST_ENABLE(1),
        .ID_ENABLE(1),.ID_WIDTH(3),.DEST_ENABLE(1),.DEST_WIDTH(3),.USER_ENABLE(1),.USER_WIDTH(1),.REG_TYPE(MODE)) dut(.*);
    reg [22:0] queue[0:255];
    integer head=0, tail=0, n=0;
    reg held=0;
    reg [22:0] held_beat;
    wire [22:0] out_beat={m_axis_tdata,m_axis_tkeep,m_axis_tlast,m_axis_tid,m_axis_tdest,m_axis_tuser};
    always @(posedge clk) begin
        if (rst) begin head=0; tail=0; held=0; end
        else begin
            if (held && (!m_axis_tvalid || out_beat !== held_beat)) $fatal(1,"unstable sideband or payload");
            if (m_axis_tvalid && m_axis_tready) begin
                if (head==tail || out_beat !== queue[head]) $fatal(1,"transport mismatch");
                head=head+1;
            end
            if (s_axis_tvalid && s_axis_tready) begin
                queue[tail]={s_axis_tdata,s_axis_tkeep,s_axis_tlast,s_axis_tid,s_axis_tdest,s_axis_tuser};
                tail=tail+1;
            end
            held=m_axis_tvalid && !m_axis_tready; held_beat=out_beat;
        end
    end
    initial begin
        repeat(2) @(negedge clk);
        rst=0;
        for(n=0;n<96;n=n+1) begin
            if (!s_axis_tvalid || s_axis_tready) begin
                s_axis_tvalid=1;
                s_axis_tdata=13'(n*101); s_axis_tkeep=2'(n); s_axis_tlast=1'(n);
                s_axis_tid=3'(n); s_axis_tdest=3'(~n); s_axis_tuser=1'(~n);
            end
            m_axis_tready=n<32 ? 1'b1 : n%7>3;
            if (n>4 && n<30 && (!s_axis_tready || !m_axis_tvalid)) $fatal(1,"mode introduces bubbles");
            @(negedge clk);
        end
        // Flush occupied output/skid registers, then drain without a new source.
        rst=1; @(negedge clk); s_axis_tvalid=0; rst=0; m_axis_tready=1;
        repeat(4) @(negedge clk);
        if (m_axis_tvalid || head!=0) $fatal(1,"reset leaked a beat");
        $display("AXIS_CALIBRATION_PASS"); $finish;
    end
    initial begin #10000; $fatal(1,"timeout"); end
endmodule
