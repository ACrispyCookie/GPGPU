`include "constants.svh"

// Generic one-outstanding MMIO endpoint. CSR meaning belongs to GPGPURegs;
// local-memory accesses retain the synchronous BRAM sequencing contract.
module GPGPUMMIO (
    input logic clk,
    input logic rst_n,

    input logic i_req_valid,
    output logic o_req_ready,
    input logic i_req_write,
    input logic [31:0] i_req_addr,
    input logic [31:0] i_req_wdata,
    input logic [3:0] i_req_wstrb,

    output logic o_rsp_valid,
    input logic i_rsp_ready,
    output logic [31:0] o_rsp_rdata,
    output logic [2:0] o_rsp_status,

    input logic i_idle,
    MemoryInterface.master imem,
    MemoryInterface.master dmem,

    // Combinational CSR description, committed only on the accepted edge.
    output logic o_csr_write,
    output logic [31:0] o_csr_addr,
    output logic [31:0] o_csr_wdata,
    output logic [3:0] o_csr_byte_en,
    output logic o_csr_write_fire,
    input logic [31:0] i_csr_rdata,
    input logic [2:0] i_csr_status
);
    typedef enum logic [1:0] {
        ACCESS_IDLE = 2'd0,
        ACCESS_MEMORY = 2'd1,
        ACCESS_CAPTURE = 2'd2,
        ACCESS_RESPONSE = 2'd3
    } access_state_t;
    localparam int unsigned HOST_ADDR_WIDTH =
        (`IMEM_AW > `DMEM_AW) ? `IMEM_AW : `DMEM_AW;

    access_state_t current_state, next_state;
    logic memory_imem, memory_write;
    logic [HOST_ADDR_WIDTH-1:0] memory_address;
    logic [31:0] memory_wdata;
    logic [31:0] decoded_rdata;
    logic [2:0] decoded_status;
    logic decoded_memory;

    // The CSR aperture is the existing space below the instruction window.
    // Unimplemented CSR addresses are rejected by the register bank itself.
    wire csr_selected = i_req_addr < `IMEM_BASE;
    wire imem_selected = i_req_addr >= `IMEM_BASE &&
                         i_req_addr < `IMEM_BASE + 32'd4 * `IMEM_ENTRIES;
    wire dmem_selected = i_req_addr >= `DMEM_BASE &&
                         i_req_addr < `DMEM_BASE + 32'd4 * `DMEM_ENTRIES;
    wire request_accepted = i_req_valid && o_req_ready;

    assign o_csr_write = i_req_write;
    assign o_csr_addr = i_req_addr;
    assign o_csr_wdata = i_req_wdata;
    assign o_csr_byte_en = i_req_wstrb;
    assign o_csr_write_fire = request_accepted && csr_selected && i_req_write &&
                              decoded_status == `RSP_OK;
    assign imem.addr = memory_address[`IMEM_AW-1:0];
    assign dmem.addr = memory_address[`DMEM_AW-1:0];
    assign imem.wdata = memory_wdata;
    assign dmem.wdata = memory_wdata;

    // Validation never depends on write_fire or CSR-generated action strobes.
    always_comb begin
        decoded_rdata = 32'b0;
        decoded_status = `RSP_OK;
        decoded_memory = 1'b0;

        if (i_req_addr[1:0] != 2'b00) begin
            decoded_status = `RSP_INVALID_ADDRESS;
        end else if (imem_selected || dmem_selected) begin
            if (!i_idle) begin
                decoded_status = `RSP_INVALID_STATE;
            end else if (i_req_write && i_req_wstrb != 4'b1111 && i_req_wstrb != 4'b0000) begin
                decoded_status = `RSP_INVALID_REQUEST;
            end else begin
                decoded_memory = !i_req_write || i_req_wstrb != 4'b0000;
            end
        end else if (csr_selected) begin
            decoded_rdata = i_csr_rdata;
            decoded_status = i_csr_status;
        end else begin
            decoded_status = `RSP_INVALID_ADDRESS;
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            current_state <= ACCESS_IDLE;
        end else begin
            current_state <= next_state;
        end
    end

    always_comb begin
        case (current_state)
            ACCESS_IDLE: next_state = request_accepted ? (decoded_memory ? ACCESS_MEMORY : ACCESS_RESPONSE) : ACCESS_IDLE;
            ACCESS_MEMORY: next_state = memory_write ? ACCESS_RESPONSE : ACCESS_CAPTURE;
            ACCESS_CAPTURE: next_state = ACCESS_RESPONSE;
            ACCESS_RESPONSE: next_state = i_rsp_ready ? ACCESS_IDLE : ACCESS_RESPONSE;
            default: next_state = ACCESS_IDLE;
        endcase
    end

    always_comb begin
        o_req_ready = 1'b0;
        o_rsp_valid = 1'b0;
        imem.ren = 1'b0;
        imem.wen = 1'b0;
        dmem.ren = 1'b0;
        dmem.wen = 1'b0;

        case (current_state)
            ACCESS_IDLE: begin
                o_req_ready = 1'b1;
            end
            ACCESS_MEMORY: begin
                if (i_idle) begin
                    imem.ren = memory_imem;
                    imem.wen = memory_imem && memory_write;
                    dmem.ren = !memory_imem;
                    dmem.wen = !memory_imem && memory_write;
                end
            end
            ACCESS_RESPONSE: begin
                o_rsp_valid = 1'b1;
            end
            default: begin end
        endcase
    end

    // At acceptance, CSR/invalid/no-op response fields are captured immediately.
    // A memory write commits on the following MEMORY edge before RESPONSE.
    // A memory read uses that edge for the BRAM read, then CAPTURE for rdata.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            memory_imem <= 1'b0;
            memory_write <= 1'b0;
            memory_address <= '0;
            memory_wdata <= 32'b0;
            o_rsp_rdata <= 32'b0;
            o_rsp_status <= `RSP_OK;
        end else if (request_accepted) begin
            o_rsp_rdata <= decoded_rdata;
            o_rsp_status <= decoded_status;
            if (decoded_memory) begin
                memory_address <= HOST_ADDR_WIDTH'((i_req_addr - (imem_selected ? `IMEM_BASE : `DMEM_BASE)) >> 2);
                memory_wdata <= i_req_wdata;
                memory_imem <= imem_selected;
                memory_write <= i_req_write;
            end
        end else if (current_state == ACCESS_CAPTURE) begin
            o_rsp_rdata <= memory_imem ? imem.rdata : dmem.rdata;
        end
    end
endmodule
