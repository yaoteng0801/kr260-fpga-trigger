`timescale 1ns/1ps

// One-register AXI4-Stream trigger pipeline.
//
// Event TDATA:
//   [31:0]  quantized unsigned HT
//   [63:32] quantized unsigned anomaly score
// Result TDATA:
//   [0] HT pass, [1] AD pass, [2] OR, [3] input TKEEP error
//
// The elastic output register permits one transfer per clock while preserving
// TDATA/TKEEP/TLAST for an arbitrarily long downstream stall.
module axis_trigger_core (
    input  logic         aclk,
    input  logic         aresetn,

    input  logic [31:0]  ht_cut,
    input  logic [31:0]  ad_cut,

    input  logic [63:0]  s_axis_tdata,
    input  logic [7:0]   s_axis_tkeep,
    input  logic         s_axis_tlast,
    input  logic         s_axis_tvalid,
    output logic         s_axis_tready,

    output logic [31:0]  m_axis_tdata,
    output logic [3:0]   m_axis_tkeep,
    output logic         m_axis_tlast,
    output logic         m_axis_tvalid,
    input  logic         m_axis_tready
);
    logic ht_pass;
    logic ad_pass;

    always_comb begin
        ht_pass = s_axis_tdata[31:0] > ht_cut;
        ad_pass = s_axis_tdata[63:32] > ad_cut;
        s_axis_tready = ~m_axis_tvalid | m_axis_tready;
    end

    always_ff @(posedge aclk) begin
        if (!aresetn) begin
            m_axis_tdata  <= 32'b0;
            m_axis_tkeep  <= 4'b0;
            m_axis_tlast  <= 1'b0;
            m_axis_tvalid <= 1'b0;
        end else if (s_axis_tready) begin
            if (s_axis_tvalid) begin
                m_axis_tdata  <= {
                    28'b0,
                    (s_axis_tkeep != 8'hff),
                    (ht_pass | ad_pass),
                    ad_pass,
                    ht_pass
                };
                m_axis_tkeep  <= 4'hf;
                m_axis_tlast  <= s_axis_tlast;
                m_axis_tvalid <= 1'b1;
            end else begin
                m_axis_tvalid <= 1'b0;
            end
        end
    end
endmodule
