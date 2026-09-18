`timescale 1ns/1ps

module tb_axis_trigger_core;
    localparam int N = 12;
    logic clk = 1'b0;
    logic resetn = 1'b0;
    logic [31:0] ht_cut = 32'd200;
    logic [31:0] ad_cut = 32'd1000;
    logic [63:0] s_data = 64'b0;
    logic [7:0] s_keep = 8'hff;
    logic s_last = 1'b0;
    logic s_valid = 1'b0;
    logic s_ready;
    logic [31:0] m_data;
    logic [3:0] m_keep;
    logic m_last;
    logic m_valid;
    logic m_ready = 1'b0;
    logic [31:0] ht [0:N-1];
    logic [31:0] ad [0:N-1];
    logic [7:0] keep [0:N-1];
    logic last [0:N-1];
    logic [31:0] expected [0:N-1];
    logic expected_last [0:N-1];
    logic [31:0] stalled_data;
    logic stalled_last;
    logic stalled = 1'b0;
    integer sent = 0;
    integer received = 0;
    integer cycle = 0;
    integer errors = 0;
    integer i;

    always #5 clk = ~clk;

    axis_trigger_core dut (
        .aclk(clk), .aresetn(resetn), .ht_cut(ht_cut), .ad_cut(ad_cut),
        .s_axis_tdata(s_data), .s_axis_tkeep(s_keep), .s_axis_tlast(s_last),
        .s_axis_tvalid(s_valid), .s_axis_tready(s_ready),
        .m_axis_tdata(m_data), .m_axis_tkeep(m_keep), .m_axis_tlast(m_last),
        .m_axis_tvalid(m_valid), .m_axis_tready(m_ready)
    );

    initial begin
        ht[0]=199; ad[0]=999;  keep[0]=8'hff; last[0]=1; // one-event packet, neither
        ht[1]=200; ad[1]=1000; keep[1]=8'hff; last[1]=0; // exactly equal: neither
        ht[2]=201; ad[2]=1000; keep[2]=8'hff; last[2]=0; // HT only
        ht[3]=200; ad[3]=1001; keep[3]=8'hff; last[3]=0; // AD only
        ht[4]=201; ad[4]=1001; keep[4]=8'hff; last[4]=1; // both
        ht[5]=0;   ad[5]=0;    keep[5]=8'hff; last[5]=0;
        ht[6]=32'hffff_ffff; ad[6]=0; keep[6]=8'hff; last[6]=0;
        ht[7]=0; ad[7]=32'hffff_ffff; keep[7]=8'hff; last[7]=1;
        ht[8]=201; ad[8]=0; keep[8]=8'h0f; last[8]=0; // malformed keep flag
        ht[9]=1; ad[9]=1001; keep[9]=8'hff; last[9]=0;
        ht[10]=200; ad[10]=999; keep[10]=8'hff; last[10]=0;
        ht[11]=201; ad[11]=1001; keep[11]=8'hff; last[11]=1; // partial final chunk
        for (i=0; i<N; i=i+1) begin
            expected[i] = {
                28'b0,
                (keep[i] != 8'hff),
                ((ht[i] > ht_cut) | (ad[i] > ad_cut)),
                (ad[i] > ad_cut),
                (ht[i] > ht_cut)
            };
            expected_last[i] = last[i];
        end

        repeat (4) @(posedge clk);
        resetn <= 1'b1;

        while (received < N && cycle < 300) begin
            @(negedge clk);
            cycle = cycle + 1;
            m_ready = ((cycle % 7) != 2) && ((cycle % 7) != 3);
            if (sent < N) begin
                s_valid = 1'b1;
                s_data = {ad[sent], ht[sent]};
                s_keep = keep[sent];
                s_last = last[sent];
            end else begin
                s_valid = 1'b0;
            end

            @(posedge clk);
            if (s_valid && s_ready)
                sent = sent + 1;

            if (m_valid && !m_ready) begin
                if (stalled && (m_data !== stalled_data || m_last !== stalled_last)) begin
                    $error("Output changed under backpressure");
                    errors = errors + 1;
                end
                stalled_data = m_data;
                stalled_last = m_last;
                stalled = 1'b1;
            end else begin
                stalled = 1'b0;
            end

            if (m_valid && m_ready) begin
                if (m_data !== expected[received]) begin
                    $error("word %0d got %08x expected %08x", received, m_data, expected[received]);
                    errors = errors + 1;
                end
                if (m_keep !== 4'hf || m_last !== expected_last[received]) begin
                    $error("sideband %0d keep=%x last=%b expected last=%b", received, m_keep, m_last, expected_last[received]);
                    errors = errors + 1;
                end
                received = received + 1;
            end
        end

        if (sent != N || received != N) begin
            $error("timeout sent=%0d received=%0d", sent, received);
            errors = errors + 1;
        end
        if (errors == 0) begin
            $display("PASS: %0d events, strict comparisons, packets, TLAST and backpressure", received);
            $finish;
        end else begin
            $fatal(1, "FAIL: %0d errors", errors);
        end
    end
endmodule
