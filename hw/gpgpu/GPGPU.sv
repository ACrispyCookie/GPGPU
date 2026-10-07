`include "constants.svh"

module GPGPUDevice #(
    parameter SP_PER_SM = 32,
    parameter MEMORY_INIT = "empty.mem"
) (
    input wire clk,
    input wire rst_n,

    // Request signals
    input wire i_req_valid,
    output wire o_req_ready,
    input wire i_req_write,
    input wire [31:0] i_req_addr,
    input wire [31:0] i_req_wdata,
    input wire [3:0] i_req_wstrb,

    // Response signals
    output wire o_rsp_valid,
    input wire i_rsp_ready,
    output wire [31:0] o_rsp_rdata,
    output wire [2:0] o_rsp_status,

    output wire o_irq
);
    // Control for the core
    wire [1:0] core_state;
    wire core_run, core_clear;
    wire core_complete, stopped;
    wire control_start, control_stop, clear_stopped;

    // Host memory signals
    wire [31:0] host_address, host_wdata;
    wire host_imem_ren, host_dmem_ren, host_imem_wen, host_dmem_wen;

    // SMX memory signals
    wire [`DMEM_AW-1:0] core_dmem_addr_a, core_dmem_addr_b;
    wire [`IMEM_AW-1:0] core_imem_addr;
    wire [31:0] core_dmem_wdata_a, core_dmem_wdata_b;
    wire core_imem_ren, core_dmem_ren_a, core_dmem_ren_b, core_dmem_wen_a, core_dmem_wen_b;

    // MUX-ed memory signals
    wire [`DMEM_AW-1:0] dmem_addr_a, dmem_addr_b;
    wire [`IMEM_AW-1:0] imem_addr;
    wire [31:0] imem_rdata, imem_wdata, dmem_rdata_a, dmem_wdata_a, dmem_rdata_b, dmem_wdata_b;
    wire imem_ren, imem_wen, dmem_ren_a, dmem_wen_a, dmem_ren_b, dmem_wen_b;

    assign core_run = core_state == `CORE_RUNNING;
    assign core_clear = core_state == `CORE_RESET;

    assign dmem_addr_a = core_run ? core_dmem_addr_a : host_address[`DMEM_AW-1:0];
    assign dmem_wdata_a = core_run ? core_dmem_wdata_a : host_wdata;
    assign dmem_ren_a = core_run ? core_dmem_ren_a : host_dmem_ren;
    assign dmem_wen_a = core_run ? core_dmem_wen_a : host_dmem_wen;

    assign dmem_addr_b = core_dmem_addr_b;
    assign dmem_wdata_b = core_dmem_wdata_b;
    assign dmem_ren_b = core_run ? core_dmem_ren_b : 1'b0;
    assign dmem_wen_b = core_run ? core_dmem_wen_b : 1'b0;

    assign imem_addr = core_run ? core_imem_addr : host_address[`IMEM_AW-1:0];
    assign imem_wdata = host_wdata;
    assign imem_ren = core_run ? core_imem_ren : host_imem_ren;
    assign imem_wen = core_run ? 1'b0 : host_imem_wen;

    GPGPUControlPlane #(.SP_PER_SM(SP_PER_SM)) control_plane (
        .clk(clk), .rst_n(rst_n),
        .i_req_valid(i_req_valid), .o_req_ready(o_req_ready),
        .i_req_write(i_req_write), .i_req_addr(i_req_addr),
        .i_req_wdata(i_req_wdata), .i_req_wstrb(i_req_wstrb),
        .o_rsp_valid(o_rsp_valid), .i_rsp_ready(i_rsp_ready),
        .o_rsp_rdata(o_rsp_rdata), .o_rsp_status(o_rsp_status),
        .i_core_state(core_state), .i_stopped(stopped), .i_core_complete(core_complete),
        .o_start(control_start), .o_stop(control_stop), .o_clear_stopped(clear_stopped),
        .o_irq(o_irq),
        .o_host_address(host_address), .o_host_wdata(host_wdata),
        .o_host_imem_ren(host_imem_ren), .o_host_imem_wen(host_imem_wen),
        .o_host_dmem_ren(host_dmem_ren), .o_host_dmem_wen(host_dmem_wen),
        .i_imem_rdata(imem_rdata), .i_dmem_rdata(dmem_rdata_a)
    );

    GPGPUController controller (
        .clk(clk), .rst_n(rst_n),
        .i_start(control_start), .i_stop(control_stop),
        .i_clear_stopped(clear_stopped), .i_core_complete(core_complete),
        .o_core_state(core_state), .o_stopped(stopped)
    );

    StreamingMultiprocessor #(
        .NUM_CORES(SP_PER_SM)
    ) smx (
        .clk(clk),
        .rst(rst_n && !core_clear),
        .i_enable(core_run),
        .i_ifid_instruction(imem_rdata),
        .o_imem_addr(core_imem_addr),
        .o_imem_ren(core_imem_ren),

        .i_dmem_rdata_a(dmem_rdata_a),
        .o_dmem_addr_a(core_dmem_addr_a),
        .o_dmem_ren_a(core_dmem_ren_a),
        .o_dmem_wen_a(core_dmem_wen_a),
        .o_dmem_wdata_a(core_dmem_wdata_a),

        .i_dmem_rdata_b(dmem_rdata_b),
        .o_dmem_addr_b(core_dmem_addr_b),
        .o_dmem_ren_b(core_dmem_ren_b),
        .o_dmem_wen_b(core_dmem_wen_b),
        .o_dmem_wdata_b(core_dmem_wdata_b),

        .o_kernel_complete(core_complete)
    );

    (* dont_touch = `DEBUG *)
    MemorySinglePort #(
        .DEPTH(`IMEM_ENTRIES),
        .INIT_FILE(MEMORY_INIT)
    ) instructionMemory (
        .clk(clk),
        .i_addr_a(imem_addr),
        .i_ren_a(imem_ren),
        .i_wen_a(imem_wen),
        .i_data_a(imem_wdata),
        .o_out_a(imem_rdata)
    );

    (* dont_touch = `DEBUG *)
    MemoryDualPort #(
        .DEPTH(`DMEM_ENTRIES),
        .INIT_FILE(MEMORY_INIT)
    ) dataMemory (
        .clk(clk),
        .i_addr_a(dmem_addr_a),
        .i_ren_a(dmem_ren_a),
        .i_wen_a(dmem_wen_a),
        .i_data_a(dmem_wdata_a),
        .o_out_a(dmem_rdata_a),
        .i_addr_b(dmem_addr_b),
        .i_ren_b(dmem_ren_b),
        .i_wen_b(dmem_wen_b),
        .i_data_b(dmem_wdata_b),
        .o_out_b(dmem_rdata_b)
    );

endmodule
