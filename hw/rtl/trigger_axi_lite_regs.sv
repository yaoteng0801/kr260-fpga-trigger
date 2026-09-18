`timescale 1ns/1ps

// Small, one-outstanding-transaction AXI4-Lite register bank.
module trigger_axi_lite_regs #(
    parameter logic [31:0] RESET_HT_CUT = 32'd436,
    parameter logic [31:0] RESET_AD_CUT = 32'd64229
) (
    input  logic         s_axi_aclk,
    input  logic         s_axi_aresetn,
    input  logic [5:0]   s_axi_awaddr,
    input  logic [2:0]   s_axi_awprot,
    input  logic         s_axi_awvalid,
    output logic         s_axi_awready,
    input  logic [31:0]  s_axi_wdata,
    input  logic [3:0]   s_axi_wstrb,
    input  logic         s_axi_wvalid,
    output logic         s_axi_wready,
    output logic [1:0]   s_axi_bresp,
    output logic         s_axi_bvalid,
    input  logic         s_axi_bready,
    input  logic [5:0]   s_axi_araddr,
    input  logic [2:0]   s_axi_arprot,
    input  logic         s_axi_arvalid,
    output logic         s_axi_arready,
    output logic [31:0]  s_axi_rdata,
    output logic [1:0]   s_axi_rresp,
    output logic         s_axi_rvalid,
    input  logic         s_axi_rready,
    output logic [31:0]  ht_cut,
    output logic [31:0]  ad_cut
);
    localparam logic [31:0] VERSION = 32'h0001_0000;
    localparam logic [31:0] CAPABILITIES = 32'h0000_000f;

    logic        aw_pending;
    logic [5:0]  awaddr_pending;
    logic        w_pending;
    logic [31:0] wdata_pending;
    logic [3:0]  wstrb_pending;
    logic [5:0]  write_addr;
    logic [31:0] write_data;
    logic [3:0]  write_strb;
    logic        write_fire;
    integer      byte_index;

    assign s_axi_awready = s_axi_aresetn && !aw_pending && !s_axi_bvalid;
    assign s_axi_wready  = s_axi_aresetn && !w_pending  && !s_axi_bvalid;
    assign s_axi_bresp   = 2'b00;
    assign s_axi_arready = s_axi_aresetn && !s_axi_rvalid;
    assign s_axi_rresp   = 2'b00;

    always_comb begin
        write_fire = !s_axi_bvalid
                   && (aw_pending || (s_axi_awready && s_axi_awvalid))
                   && (w_pending  || (s_axi_wready  && s_axi_wvalid));
        write_addr = aw_pending ? awaddr_pending : s_axi_awaddr;
        write_data = w_pending  ? wdata_pending  : s_axi_wdata;
        write_strb = w_pending  ? wstrb_pending  : s_axi_wstrb;
    end

    always_ff @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            aw_pending    <= 1'b0;
            awaddr_pending <= 6'b0;
            w_pending     <= 1'b0;
            wdata_pending <= 32'b0;
            wstrb_pending <= 4'b0;
            s_axi_bvalid  <= 1'b0;
            ht_cut        <= RESET_HT_CUT;
            ad_cut        <= RESET_AD_CUT;
        end else begin
            if (s_axi_awready && s_axi_awvalid) begin
                aw_pending     <= 1'b1;
                awaddr_pending <= s_axi_awaddr;
            end
            if (s_axi_wready && s_axi_wvalid) begin
                w_pending     <= 1'b1;
                wdata_pending <= s_axi_wdata;
                wstrb_pending <= s_axi_wstrb;
            end

            if (write_fire) begin
                aw_pending   <= 1'b0;
                w_pending    <= 1'b0;
                s_axi_bvalid <= 1'b1;
                case (write_addr[5:2])
                    4'h0: for (byte_index = 0; byte_index < 4; byte_index = byte_index + 1)
                        if (write_strb[byte_index])
                            ht_cut[byte_index*8 +: 8] <= write_data[byte_index*8 +: 8];
                    4'h1: for (byte_index = 0; byte_index < 4; byte_index = byte_index + 1)
                        if (write_strb[byte_index])
                            ad_cut[byte_index*8 +: 8] <= write_data[byte_index*8 +: 8];
                    default: begin end
                endcase
            end else if (s_axi_bvalid && s_axi_bready) begin
                s_axi_bvalid <= 1'b0;
            end
        end
    end

    always_ff @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_rvalid <= 1'b0;
            s_axi_rdata  <= 32'b0;
        end else begin
            if (s_axi_arready && s_axi_arvalid) begin
                s_axi_rvalid <= 1'b1;
                case (s_axi_araddr[5:2])
                    4'h0: s_axi_rdata <= ht_cut;
                    4'h1: s_axi_rdata <= ad_cut;
                    4'h2: s_axi_rdata <= VERSION;
                    4'h3: s_axi_rdata <= CAPABILITIES;
                    default: s_axi_rdata <= 32'b0;
                endcase
            end else if (s_axi_rvalid && s_axi_rready) begin
                s_axi_rvalid <= 1'b0;
            end
        end
    end

    // Protection attributes are accepted but do not alter this register bank.
    logic unused_prot;
    always_comb unused_prot = ^{s_axi_awprot, s_axi_arprot};
endmodule
