`timescale 1ns/1ps

// V2 22-item trigger comparator.
//
// Each event is 11 consecutive 64-bit AXI4-Stream beats. Every beat carries
// two little-endian uint32 event variables. Item i is compared against cut i
// with a strict unsigned greater-than operation. TLAST marks the last beat of
// the final event in a DMA chunk, not every event.
//
// Result TDATA:
//   [21:0] individual item pass bits
//   [22]   OR of all item pass bits
//   [23]   at least one input beat had TKEEP != 8'hff
//   [24]   TLAST arrived before beat 10
//   [31:25] zero
module axis_trigger_core_v2 #(
    parameter integer N_ITEMS = 22
) (
    input  logic                         aclk,
    input  logic                         aresetn,
    input  logic [N_ITEMS*32-1:0]        cuts_flat,

    input  logic [63:0]                  s_axis_tdata,
    input  logic [7:0]                   s_axis_tkeep,
    input  logic                         s_axis_tlast,
    input  logic                         s_axis_tvalid,
    output logic                         s_axis_tready,

    output logic [31:0]                  m_axis_tdata,
    output logic [3:0]                   m_axis_tkeep,
    output logic                         m_axis_tlast,
    output logic                         m_axis_tvalid,
    input  logic                         m_axis_tready
);
    localparam integer BEATS_PER_EVENT = N_ITEMS / 2;

    logic [31:0] cuts [0:N_ITEMS-1];
    logic [4:0] beat_index;
    logic [N_ITEMS-1:0] pass_accum;
    logic keep_error_accum;
    logic [N_ITEMS-1:0] event_pass;
    logic event_keep_error;
    logic event_complete;
    logic early_tlast;
    integer low_index;
    integer high_index;
    genvar cut_index;

    generate
        for (cut_index = 0; cut_index < N_ITEMS; cut_index = cut_index + 1) begin : unpack_cuts
            assign cuts[cut_index] = cuts_flat[cut_index*32 +: 32];
        end
    endgenerate

    always_comb begin
        low_index = beat_index * 2;
        high_index = low_index + 1;
        event_pass = pass_accum;
        event_pass[low_index] = s_axis_tdata[31:0] > cuts[low_index];
        event_pass[high_index] = s_axis_tdata[63:32] > cuts[high_index];
        event_keep_error = keep_error_accum | (s_axis_tkeep != 8'hff);
        event_complete = (beat_index == BEATS_PER_EVENT - 1);
        early_tlast = s_axis_tlast && !event_complete;
        s_axis_tready = ~m_axis_tvalid | m_axis_tready;
    end

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            beat_index        <= 5'd0;
            pass_accum        <= '0;
            keep_error_accum  <= 1'b0;
            m_axis_tdata      <= 32'b0;
            m_axis_tkeep      <= 4'b0;
            m_axis_tlast      <= 1'b0;
            m_axis_tvalid     <= 1'b0;
        end else begin
            if (m_axis_tvalid && m_axis_tready)
                m_axis_tvalid <= 1'b0;

            if (s_axis_tvalid && s_axis_tready) begin
                if (event_complete || early_tlast) begin
                    m_axis_tdata <= {
                        7'b0,
                        early_tlast,
                        event_keep_error,
                        (|event_pass),
                        event_pass
                    };
                    m_axis_tkeep     <= 4'hf;
                    m_axis_tlast     <= s_axis_tlast;
                    m_axis_tvalid    <= 1'b1;
                    beat_index       <= 5'd0;
                    pass_accum       <= '0;
                    keep_error_accum <= 1'b0;
                end else begin
                    beat_index       <= beat_index + 1'b1;
                    pass_accum       <= event_pass;
                    keep_error_accum <= event_keep_error;
                end
            end
        end
    end
endmodule
