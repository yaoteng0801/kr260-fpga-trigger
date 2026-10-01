`timescale 1ns/1ps

module tb_axis_trigger_core_v2;
    localparam integer N_ITEMS = 22;
    localparam integer MAX_BEATS = 44;
    localparam integer N_RESULTS = 4;
    logic clk = 1'b0;
    logic resetn = 1'b0;
    logic [N_ITEMS*32-1:0] cuts_flat = '0;
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
    logic [63:0] beats [0:MAX_BEATS-1];
    logic [7:0] keeps [0:MAX_BEATS-1];
    logic lasts [0:MAX_BEATS-1];
    logic [31:0] expected [0:N_RESULTS-1];
    logic expected_last [0:N_RESULTS-1];
    logic [31:0] stalled_data;
    logic stalled_last;
    logic stalled = 1'b0;
    logic [21:0] mask;
    integer beat_count = 0;
    integer sent = 0;
    integer received = 0;
    integer cycle = 0;
    integer errors = 0;
    integer event_index;
    integer beat_index;
    integer item_index;
    integer flat_index;
    logic [31:0] low_value;
    logic [31:0] high_value;

    always #5 clk = ~clk;

    axis_trigger_core_v2 dut (
        .aclk(clk), .aresetn(resetn), .cuts_flat(cuts_flat),
        .s_axis_tdata(s_data), .s_axis_tkeep(s_keep),
        .s_axis_tlast(s_last), .s_axis_tvalid(s_valid),
        .s_axis_tready(s_ready), .m_axis_tdata(m_data),
        .m_axis_tkeep(m_keep), .m_axis_tlast(m_last),
        .m_axis_tvalid(m_valid), .m_axis_tready(m_ready)
    );

    initial begin
        for (item_index = 0; item_index < N_ITEMS; item_index = item_index + 1)
            cuts_flat[item_index*32 +: 32] = 32'd1000 + item_index;

        // Three complete events. Only the third closes the first DMA packet.
        for (event_index = 0; event_index < 3; event_index = event_index + 1) begin
            for (beat_index = 0; beat_index < 11; beat_index = beat_index + 1) begin
                flat_index = beat_count;
                if (event_index == 0) begin
                    low_value = 32'd1000 + beat_index*2;
                    high_value = 32'd1001 + beat_index*2;
                end else if (event_index == 1) begin
                    low_value = 32'd1000 + beat_index*2
                              + (((beat_index*2) % 3) == 0 ? 1 : 0);
                    high_value = 32'd1001 + beat_index*2
                               + ((((beat_index*2)+1) % 3) == 0 ? 1 : 0);
                end else begin
                    low_value = 32'd1001 + beat_index*2;
                    high_value = 32'd1002 + beat_index*2;
                end
                beats[flat_index] = {high_value, low_value};
                keeps[flat_index] = (event_index == 2 && beat_index == 4) ? 8'h0f : 8'hff;
                lasts[flat_index] = (event_index == 2 && beat_index == 10);
                beat_count = beat_count + 1;
            end
        end

        // A deliberately truncated event verifies early-TLAST recovery.
        for (beat_index = 0; beat_index < 4; beat_index = beat_index + 1) begin
            flat_index = beat_count;
            low_value = 32'd1001 + beat_index*2;
            high_value = 32'd1002 + beat_index*2;
            beats[flat_index] = {high_value, low_value};
            keeps[flat_index] = 8'hff;
            lasts[flat_index] = (beat_index == 3);
            beat_count = beat_count + 1;
        end

        expected[0] = 32'b0;
        expected_last[0] = 1'b0;
        mask = 22'b0;
        for (item_index = 0; item_index < N_ITEMS; item_index = item_index + 1)
            if ((item_index % 3) == 0)
                mask[item_index] = 1'b1;
        expected[1] = {7'b0, 1'b0, 1'b0, 1'b1, mask};
        expected_last[1] = 1'b0;
        expected[2] = {7'b0, 1'b0, 1'b1, 1'b1, 22'h3f_ffff};
        expected_last[2] = 1'b1;
        expected[3] = {7'b0, 1'b1, 1'b0, 1'b1, 14'b0, 8'hff};
        expected_last[3] = 1'b1;

        repeat (4) @(posedge clk);
        resetn <= 1'b1;

        while (received < N_RESULTS && cycle < 600) begin
            @(negedge clk);
            cycle = cycle + 1;
            m_ready = ((cycle % 9) != 2) && ((cycle % 9) != 3);
            if (sent < beat_count) begin
                s_valid = 1'b1;
                s_data = beats[sent];
                s_keep = keeps[sent];
                s_last = lasts[sent];
            end else begin
                s_valid = 1'b0;
            end

            @(posedge clk);
            if (s_valid && s_ready)
                sent = sent + 1;

            if (m_valid && !m_ready) begin
                if (stalled && (m_data !== stalled_data || m_last !== stalled_last)) begin
                    $error("V2 output changed under backpressure");
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
                    $error("result %0d got %08x expected %08x", received, m_data, expected[received]);
                    errors = errors + 1;
                end
                if (m_keep !== 4'hf || m_last !== expected_last[received]) begin
                    $error("sideband %0d keep=%x last=%b", received, m_keep, m_last);
                    errors = errors + 1;
                end
                received = received + 1;
            end
        end

        if (sent != beat_count || received != N_RESULTS) begin
            $error("timeout sent=%0d/%0d received=%0d", sent, beat_count, received);
            errors = errors + 1;
        end
        if (errors == 0) begin
            $display("PASS: V2 22-item packets, strict comparisons, TLAST, errors, backpressure");
            $finish;
        end else begin
            $fatal(1, "FAIL: %0d V2 core errors", errors);
        end
    end
endmodule
