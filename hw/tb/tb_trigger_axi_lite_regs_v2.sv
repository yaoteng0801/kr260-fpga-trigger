`timescale 1ns/1ps

module tb_trigger_axi_lite_regs_v2;
    logic clk = 1'b0;
    logic resetn = 1'b0;
    logic [6:0] awaddr = 7'b0;
    logic [2:0] awprot = 3'b0;
    logic awvalid = 1'b0;
    logic awready;
    logic [31:0] wdata = 32'b0;
    logic [3:0] wstrb = 4'b0;
    logic wvalid = 1'b0;
    logic wready;
    logic [1:0] bresp;
    logic bvalid;
    logic bready = 1'b1;
    logic [6:0] araddr = 7'b0;
    logic [2:0] arprot = 3'b0;
    logic arvalid = 1'b0;
    logic arready;
    logic [31:0] rdata;
    logic [1:0] rresp;
    logic rvalid;
    logic rready = 1'b1;
    logic [22*32-1:0] cuts_flat;
    logic [31:0] value;
    integer errors = 0;

    always #5 clk = ~clk;

    trigger_axi_lite_regs_v2 dut (
        .s_axi_aclk(clk), .s_axi_aresetn(resetn),
        .s_axi_awaddr(awaddr), .s_axi_awprot(awprot),
        .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(wstrb),
        .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arprot(arprot),
        .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp),
        .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .cuts_flat(cuts_flat)
    );

    task automatic axi_write(
        input logic [6:0] address,
        input logic [31:0] data,
        input logic [3:0] strobes
    );
        begin
            @(negedge clk);
            awaddr = address;
            wdata = data;
            wstrb = strobes;
            awvalid = 1'b1;
            wvalid = 1'b1;
            do @(posedge clk); while (!(awready && wready));
            @(negedge clk);
            awvalid = 1'b0;
            wvalid = 1'b0;
            do @(posedge clk); while (!bvalid);
            if (bresp !== 2'b00) begin
                $error("write response was %b", bresp);
                errors = errors + 1;
            end
        end
    endtask

    task automatic axi_read(
        input logic [6:0] address,
        output logic [31:0] data
    );
        begin
            @(negedge clk);
            araddr = address;
            arvalid = 1'b1;
            do @(posedge clk); while (!arready);
            @(negedge clk);
            arvalid = 1'b0;
            do @(posedge clk); while (!rvalid);
            data = rdata;
            if (rresp !== 2'b00) begin
                $error("read response was %b", rresp);
                errors = errors + 1;
            end
        end
    endtask

    task automatic expect_read(
        input logic [6:0] address,
        input logic [31:0] expected
    );
        begin
            axi_read(address, value);
            if (value !== expected) begin
                $error("read %02x got %08x expected %08x", address, value, expected);
                errors = errors + 1;
            end
        end
    endtask

    initial begin
        repeat (4) @(posedge clk);
        resetn <= 1'b1;

        expect_read(7'h00, 32'd102400);
        expect_read(7'h3c, 32'd76800);
        expect_read(7'h54, 32'd256000);
        expect_read(7'h58, 32'h0002_0000);
        expect_read(7'h5c, 32'h0000_003f);

        axi_write(7'h54, 32'h1234_5678, 4'hf);
        expect_read(7'h54, 32'h1234_5678);
        if (cuts_flat[21*32 +: 32] !== 32'h1234_5678) begin
            $error("flattened VBF threshold did not update");
            errors = errors + 1;
        end

        axi_write(7'h00, 32'hdead_beef, 4'b0101);
        expect_read(7'h00, 32'h00ad_90ef);

        if (errors == 0) begin
            $display("PASS: V2 22-cut AXI-Lite defaults, writes, strobes and identity");
            $finish;
        end else begin
            $fatal(1, "FAIL: %0d V2 register errors", errors);
        end
    end
endmodule
