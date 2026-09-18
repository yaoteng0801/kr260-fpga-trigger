`timescale 1ns/1ps

module axis_trigger_top (
    (* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 aclk CLK" *)
    (* X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF S_AXIS:M_AXIS:S_AXI, ASSOCIATED_RESET aresetn" *)
    input  logic         aclk,
    (* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 aresetn RST" *)
    (* X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *)
    input  logic         aresetn,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TDATA" *) input logic [63:0] s_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TKEEP" *) input logic [7:0]  s_axis_tkeep,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TLAST" *) input logic        s_axis_tlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TVALID" *) input logic       s_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 S_AXIS TREADY" *) output logic      s_axis_tready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TDATA" *) output logic [31:0] m_axis_tdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TKEEP" *) output logic [3:0]  m_axis_tkeep,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TLAST" *) output logic        m_axis_tlast,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TVALID" *) output logic       m_axis_tvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:axis:1.0 M_AXIS TREADY" *) input logic        m_axis_tready,

    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWADDR" *)
    (* X_INTERFACE_PARAMETER = "PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 6, HAS_BURST 0, HAS_LOCK 0, HAS_PROT 1, HAS_CACHE 0, HAS_QOS 0, HAS_REGION 0" *)
    input logic [5:0]  s_axi_awaddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWPROT" *) input logic [2:0]  s_axi_awprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *) input logic       s_axi_awvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *) output logic      s_axi_awready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WDATA" *) input logic [31:0] s_axi_wdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *) input logic [3:0]  s_axi_wstrb,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WVALID" *) input logic       s_axi_wvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI WREADY" *) output logic      s_axi_wready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BRESP" *) output logic [1:0] s_axi_bresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BVALID" *) output logic      s_axi_bvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI BREADY" *) input logic       s_axi_bready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *) input logic [5:0] s_axi_araddr,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARPROT" *) input logic [2:0] s_axi_arprot,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *) input logic      s_axi_arvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *) output logic     s_axi_arready,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RDATA" *) output logic [31:0] s_axi_rdata,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RRESP" *) output logic [1:0] s_axi_rresp,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RVALID" *) output logic      s_axi_rvalid,
    (* X_INTERFACE_INFO = "xilinx.com:interface:aximm:1.0 S_AXI RREADY" *) input logic       s_axi_rready
);
    logic [31:0] ht_cut;
    logic [31:0] ad_cut;

    trigger_axi_lite_regs regs_i (
        .s_axi_aclk(aclk), .s_axi_aresetn(aresetn),
        .s_axi_awaddr(s_axi_awaddr), .s_axi_awprot(s_axi_awprot),
        .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready),
        .s_axi_wdata(s_axi_wdata), .s_axi_wstrb(s_axi_wstrb),
        .s_axi_wvalid(s_axi_wvalid), .s_axi_wready(s_axi_wready),
        .s_axi_bresp(s_axi_bresp), .s_axi_bvalid(s_axi_bvalid),
        .s_axi_bready(s_axi_bready), .s_axi_araddr(s_axi_araddr),
        .s_axi_arprot(s_axi_arprot), .s_axi_arvalid(s_axi_arvalid),
        .s_axi_arready(s_axi_arready), .s_axi_rdata(s_axi_rdata),
        .s_axi_rresp(s_axi_rresp), .s_axi_rvalid(s_axi_rvalid),
        .s_axi_rready(s_axi_rready), .ht_cut(ht_cut), .ad_cut(ad_cut)
    );
    axis_trigger_core trigger_i (.*);
endmodule
