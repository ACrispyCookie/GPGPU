`timescale 1ns/1ps
`include "constants.svh"

// Test-only CSR at a previously unused aperture address: the MMIO FSM must
// route it without knowing its register number or implementation semantics.
module tb_GPGPUMMIORouting;
    logic clk = 0;
    always #5 clk = ~clk;
    logic rst_n = 0, idle = 1;
    logic req_valid = 0, req_write = 0, rsp_ready = 0;
    logic [31:0] req_addr = 0, req_wdata = 0;
    logic [3:0] req_wstrb = 0;
    wire req_ready, rsp_valid;
    wire [31:0] rsp_rdata;
    wire [2:0] rsp_status;
    wire csr_write, csr_write_fire;
    wire [31:0] csr_addr, csr_wdata;
    wire [3:0] csr_byte_en;
    logic [31:0] csr_rdata, value = 0;
    logic [2:0] csr_status;
    wire [31:0] byte_mask = {{8{csr_byte_en[3]}}, {8{csr_byte_en[2]}},
                             {8{csr_byte_en[1]}}, {8{csr_byte_en[0]}}};
    integer accepted = 0, committed = 0, checks = 0;

    MemoryInterface #(.ADDR_WIDTH(`IMEM_AW)) imem();
    MemoryInterface #(.ADDR_WIDTH(`DMEM_AW)) dmem();
    assign imem.rdata = 32'b0;
    assign dmem.rdata = 32'b0;

    GPGPUMMIO mmio (
        .clk(clk), .rst_n(rst_n), .i_idle(idle),
        .i_req_valid(req_valid), .o_req_ready(req_ready),
        .i_req_write(req_write), .i_req_addr(req_addr),
        .i_req_wdata(req_wdata), .i_req_wstrb(req_wstrb),
        .o_rsp_valid(rsp_valid), .i_rsp_ready(rsp_ready),
        .o_rsp_rdata(rsp_rdata), .o_rsp_status(rsp_status),
        .o_csr_write(csr_write), .o_csr_addr(csr_addr),
        .o_csr_wdata(csr_wdata), .o_csr_byte_en(csr_byte_en),
        .o_csr_write_fire(csr_write_fire),
        .i_csr_rdata(csr_rdata), .i_csr_status(csr_status),
        .imem(imem), .dmem(dmem)
    );

    always_comb begin
        case (csr_addr)
            32'h1f00: csr_status = `RSP_OK;
            32'h1f04: csr_status = `RSP_ACCESS_DENIED;
            32'h1f08: csr_status = `RSP_INVALID_REQUEST;
            32'h1f0c: csr_status = `RSP_INVALID_STATE;
            default: csr_status = `RSP_INVALID_ADDRESS;
        endcase
        csr_rdata = !csr_write && csr_status == `RSP_OK ? value : 32'b0;
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            value <= 0;
            accepted = 0;
            committed = 0;
        end else begin
            if (req_valid && req_ready) accepted = accepted + 1;
            if (csr_write_fire) begin
                if (!csr_write || csr_status != `RSP_OK || csr_addr != 32'h1f00)
                    $fatal(1, "Unvalidated CSR commit");
                value <= (value & ~byte_mask) | (csr_wdata & byte_mask);
                committed = committed + 1;
            end
        end
    end

    task automatic check(input logic condition, input string message);
        if (!condition) $fatal(1, "%s", message);
        checks = checks + 1;
    endtask

    task automatic request(input logic write_op, input logic [31:0] address,
                           input logic [31:0] data, input logic [3:0] strobes);
        integer timeout_cycles;
        @(negedge clk);
        req_write = write_op; req_addr = address; req_wdata = data;
        req_wstrb = strobes; req_valid = 1;
        timeout_cycles = 0;
        while (!req_ready && timeout_cycles < 20) begin
            @(negedge clk); timeout_cycles = timeout_cycles + 1;
        end
        check(req_ready, "Request was never ready");
        @(posedge clk); #1;
        @(negedge clk); req_valid = 0;
        timeout_cycles = 0;
        while (!rsp_valid && timeout_cycles < 20) begin
            @(negedge clk); timeout_cycles = timeout_cycles + 1;
        end
        check(rsp_valid, "Response timed out");
    endtask

    task automatic consume(input logic [2:0] expected_status,
                           input logic [31:0] expected_data);
        check(rsp_valid && rsp_status == expected_status && rsp_rdata == expected_data,
              "Wrong delegated CSR response");
        @(negedge clk); rsp_ready = 1;
        @(posedge clk); #1;
        @(negedge clk); rsp_ready = 0;
    endtask

    task automatic access(input logic write_op, input logic [31:0] address,
                          input logic [31:0] data, input logic [3:0] strobes,
                          input logic [2:0] expected_status, input logic [31:0] expected_data);
        request(write_op, address, data, strobes);
        consume(expected_status, expected_data);
    endtask

    initial begin
        repeat (3) @(negedge clk);
        rst_n = 1;
        access(1, 32'h1f00, 32'h12345678, 4'hf, `RSP_OK, 0);
        access(0, 32'h1f00, 0, 4'h0, `RSP_OK, 32'h12345678);
        access(1, 32'h1f00, 32'habcd0000, 4'hc, `RSP_OK, 0);
        access(0, 32'h1f00, 0, 4'hf, `RSP_OK, 32'habcd5678);
        access(1, 32'h1f00, 32'hffffffff, 4'h0, `RSP_OK, 0);
        check(value == 32'habcd5678 && committed == 3, "Zero-mask CSR changed storage");
        access(1, 32'h1f04, 1, 4'hf, `RSP_ACCESS_DENIED, 0);
        access(1, 32'h1f08, 1, 4'hf, `RSP_INVALID_REQUEST, 0);
        access(1, 32'h1f0c, 1, 4'hf, `RSP_INVALID_STATE, 0);
        access(1, 32'h1f10, 1, 4'hf, `RSP_INVALID_ADDRESS, 0);
        access(1, 32'h1f01, 1, 4'hf, `RSP_INVALID_ADDRESS, 0);
        access(1, 32'h6000, 1, 4'hf, `RSP_INVALID_ADDRESS, 0);
        check(committed == 3, "Invalid access reached CSR commit");
        idle = 0;
        access(0, 32'h1f00, 0, 4'hf, `RSP_OK, 32'habcd5678);
        access(1, `DMEM_BASE, 1, 4'hf, `RSP_INVALID_STATE, 0);
        check(committed == 3, "Memory operation reached the register model");
        idle = 1;

        // Hold a second request during response backpressure. It may be
        // accepted only on the edge after the first response is consumed.
        request(1, 32'h1f00, 32'h11111111, 4'hf);
        check(committed == 4 && value == 32'h11111111, "First write did not commit once");
        req_valid = 1; req_write = 1; req_addr = 32'h1f00;
        req_wdata = 32'h22222222; req_wstrb = 4'hf;
        repeat (6) begin
            @(posedge clk); #1;
            check(!req_ready && rsp_valid && rsp_status == `RSP_OK && rsp_rdata == 0,
                  "Held response changed or accepted a second request");
            check(committed == 4 && value == 32'h11111111, "Write repeated under backpressure");
        end
        consume(`RSP_OK, 0);
        check(committed == 4 && req_ready, "Second request accepted on response edge");
        @(posedge clk); #1;
        check(committed == 5 && value == 32'h22222222 && rsp_valid,
              "Back-to-back request did not commit exactly once");
        @(negedge clk); req_valid = 0;
        consume(`RSP_OK, 0);
        access(0, 32'h1f00, 0, 4'hf, `RSP_OK, 32'h22222222);
        $display("[PASS] MMIO routing: %0d checks, %0d accepted requests, %0d CSR commits; future CSR, delegated errors, strobes, backpressure and back-to-back traffic", checks, accepted, committed);
        $finish;
    end

    initial begin
        #100000;
        $fatal(1, "MMIO routing test timed out");
    end
endmodule
