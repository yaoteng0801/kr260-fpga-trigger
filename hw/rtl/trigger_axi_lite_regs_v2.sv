`timescale 1ns/1ps

// AXI4-Lite threshold bank for the V2 22-item menu.
module trigger_axi_lite_regs_v2 #(
    parameter integer N_ITEMS = 22
) (
    input  logic                         s_axi_aclk,
    input  logic                         s_axi_aresetn,
    input  logic [6:0]                   s_axi_awaddr,
    input  logic [2:0]                   s_axi_awprot,
    input  logic                         s_axi_awvalid,
    output logic                         s_axi_awready,
    input  logic [31:0]                  s_axi_wdata,
    input  logic [3:0]                   s_axi_wstrb,
    input  logic                         s_axi_wvalid,
    output logic                         s_axi_wready,
    output logic [1:0]                   s_axi_bresp,
    output logic                         s_axi_bvalid,
    input  logic                         s_axi_bready,
    input  logic [6:0]                   s_axi_araddr,
    input  logic [2:0]                   s_axi_arprot,
    input  logic                         s_axi_arvalid,
    output logic                         s_axi_arready,
    output logic [31:0]                  s_axi_rdata,
    output logic [1:0]                   s_axi_rresp,
    output logic                         s_axi_rvalid,
    input  logic                         s_axi_rready,
    output logic [N_ITEMS*32-1:0]        cuts_flat
);
    localparam logic [31:0] VERSION = 32'h0002_0000;
    localparam logic [31:0] CAPABILITIES = 32'h0000_003f;

    logic [31:0] cuts [0:N_ITEMS-1];
    logic aw_pending;
    logic [6:0] awaddr_pending;
    logic w_pending;
    logic [31:0] wdata_pending;
    logic [3:0] wstrb_pending;
    logic [6:0] write_addr;
    logic [31:0] write_data;
    logic [3:0] write_strb;
    logic write_fire;
    integer byte_index;
    integer reg_index;
    genvar cut_index;

    function automatic logic [31:0] reset_cut(input integer index);
        begin
            case (index)
                0:  reset_cut = 32'd102400; // 1j 400
                1:  reset_cut = 32'd51200;  // 3j 200
                2:  reset_cut = 32'd40960;  // 4j 160
                3:  reset_cut = 32'd30720;  // 5j 120
                4:  reset_cut = 32'd20480;  // 6j 80
                5:  reset_cut = 32'd102400;
                6:  reset_cut = 32'd51200;
                7:  reset_cut = 32'd40960;
                8:  reset_cut = 32'd30720;
                9:  reset_cut = 32'd20480;
                10: reset_cut = 32'd51200;  // 1j_forward 200
                11: reset_cut = 32'd51200;
                12: reset_cut = 32'd40960;
                13: reset_cut = 32'd30720;
                14: reset_cut = 32'd20480;
                15: reset_cut = 32'd76800;  // HT 300
                16: reset_cut = 32'd58880;  // HT central 230
                17: reset_cut = 32'd51200;  // MET 200
                18: reset_cut = 32'd46080;  // MET central 180
                19: reset_cut = 32'd76800;  // AD 300
                20: reset_cut = 32'd256000; // dijet 1000
                21: reset_cut = 32'd256000; // VBF 1000
                default: reset_cut = 32'd0;
            endcase
        end
    endfunction

    generate
        for (cut_index = 0; cut_index < N_ITEMS; cut_index = cut_index + 1) begin : flatten_cuts
            assign cuts_flat[cut_index*32 +: 32] = cuts[cut_index];
        end
    endgenerate

    assign s_axi_awready = s_axi_aresetn && !aw_pending && !s_axi_bvalid;
    assign s_axi_wready  = s_axi_aresetn && !w_pending && !s_axi_bvalid;
    assign s_axi_bresp   = 2'b00;
    assign s_axi_arready = s_axi_aresetn && !s_axi_rvalid;
    assign s_axi_rresp   = 2'b00;

    always_comb begin
        write_fire = !s_axi_bvalid
                   && (aw_pending || (s_axi_awready && s_axi_awvalid))
                   && (w_pending || (s_axi_wready && s_axi_wvalid));
        write_addr = aw_pending ? awaddr_pending : s_axi_awaddr;
        write_data = w_pending ? wdata_pending : s_axi_wdata;
        write_strb = w_pending ? wstrb_pending : s_axi_wstrb;
    end

    always_ff @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            aw_pending     <= 1'b0;
            awaddr_pending <= 7'b0;
            w_pending      <= 1'b0;
            wdata_pending  <= 32'b0;
            wstrb_pending  <= 4'b0;
            s_axi_bvalid   <= 1'b0;
            for (reg_index = 0; reg_index < N_ITEMS; reg_index = reg_index + 1)
                cuts[reg_index] <= reset_cut(reg_index);
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
                if (write_addr[6:2] < N_ITEMS) begin
                    for (byte_index = 0; byte_index < 4; byte_index = byte_index + 1)
                        if (write_strb[byte_index])
                            cuts[write_addr[6:2]][byte_index*8 +: 8]
                                <= write_data[byte_index*8 +: 8];
                end
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
                if (s_axi_araddr[6:2] < N_ITEMS)
                    s_axi_rdata <= cuts[s_axi_araddr[6:2]];
                else if (s_axi_araddr[6:2] == N_ITEMS)
                    s_axi_rdata <= VERSION;
                else if (s_axi_araddr[6:2] == N_ITEMS + 1)
                    s_axi_rdata <= CAPABILITIES;
                else
                    s_axi_rdata <= 32'b0;
            end else if (s_axi_rvalid && s_axi_rready) begin
                s_axi_rvalid <= 1'b0;
            end
        end
    end

    logic unused_prot;
    always_comb unused_prot = ^{s_axi_awprot, s_axi_arprot};
endmodule
