`timescale 1ns/1ps
module packet_tag_skid_tb;
    parameter integer W=13, T=3, CHECK=0;
    localparam [W-1:0] MASK = {W{1'b1}} ^ W'(2);
    reg clk=0;
    always #5 clk=~clk;
    reg rst_n=0, in_valid=0, in_last=0, out_ready=0;
    reg [W-1:0] in_data=0;
    reg [T-1:0] in_tag=0;
    wire in_ready, out_valid, out_last;
    wire [W-1:0] out_data;
    wire [T-1:0] out_tag;
    packet_tag_skid #(.W(W),.T(T),.MASK(MASK)) dut(.*);
    reg [W+T:0] expected[0:1023];
    reg [W+T:0] held;
    reg stalled=0, ready_before, accepted=0;
    reg [W:0] output_before;
    integer wr=0, rd=0, cycles=0;
    integer sent=0, received=0;
    reg [31:0] rng=32'h519ad783;
    task tick;
        begin
            @(posedge clk);
            if (!rst_n) begin
                wr=0; rd=0; stalled=0; accepted=0;
            end else begin
                if ((in_ready !== 1'b0 && in_ready !== 1'b1) ||
                    (out_valid !== 1'b0 && out_valid !== 1'b1)) $fatal(1,"unknown handshake");
                if (stalled && (!out_valid || {out_data,out_last,out_tag} !== held))
                    $fatal(1,"stalled beat changed");
                if (out_valid && out_ready) begin
                    if (rd == wr) $fatal(1,"unexpected or zero-latency output");
                    if ({out_data,out_last,out_tag} !== expected[rd]) $fatal(1,"beat mismatch");
                    rd=rd+1; received=received+1;
                end
                accepted=in_valid && in_ready;
                if (accepted) begin
                    expected[wr] = {in_data ^ MASK, in_last, T'(in_tag + 1'b1)};
                    wr=wr+1; sent=sent+1;
                end
                stalled=out_valid && !out_ready;
                held={out_data,out_last,out_tag};
            end
            #1;
            if (!rst_n && out_valid !== 1'b0) $fatal(1,"reset did not flush valid");
            @(negedge clk);
        end
    endtask
    initial begin
        tick(); tick(); rst_n=1;
        if (CHECK == 3) begin
            // No edge occurs while the downstream ready and input change.
            #1; ready_before=in_ready; output_before={out_valid,out_data};
            out_ready=1; in_valid=1; in_data='1;
            #1;
            if (in_ready !== ready_before || {out_valid,out_data} !== output_before)
                $fatal(1,"combinational boundary");
            // Input readiness may legally take an edge to recover after reset.
            // Measure latency from the first accepted beat, not reset release.
            while (in_ready !== 1'b1) tick();
            tick();
            if (!out_valid) $fatal(1,"empty-stage latency is not one edge");
            out_ready=0;
            tick();
            if (wr != 2) $fatal(1,"missing skid capacity");
            #1; ready_before=in_ready; out_ready=1; #1;
            if (in_ready !== ready_before) $fatal(1,"ready lookahead path");
        end else if (CHECK == 2) begin
            in_valid=1; out_ready=0;
            repeat (3) tick();
            if (wr < 2) $fatal(1,"reset test did not fill skid storage");
            rst_n=0; tick(); rst_n=1; in_valid=0; out_ready=1;
            repeat (5) tick();
        end else begin
            for (cycles=0; cycles<160; cycles=cycles+1) begin
                rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
                if (!in_valid || accepted) begin
                    in_valid = CHECK == 4 ? 1'b1 : rng[1];
                    in_data=W'(cycles*73+19); in_tag=T'(cycles); in_last=rng[2];
                end
                out_ready = CHECK == 4 ? 1'b1 : (CHECK == 1 ? cycles%11 >= 7 : rng[3]);
                tick();
                if (CHECK == 4 && cycles>3 && (!in_ready || !out_valid)) $fatal(1,"throughput bubble");
            end
            // Finish any outstanding input before deasserting valid.
            out_ready=1;
            while (in_valid && !in_ready) tick();
            tick(); in_valid=0;
            repeat (4) tick();
            if (rd != wr || received<10) $fatal(1,"incomplete drain or vacuous test");
        end
        $display("PACKET_CHECK_PASS %0d",CHECK); $finish;
    end
    initial begin #20000; $fatal(1,"timeout"); end
endmodule
