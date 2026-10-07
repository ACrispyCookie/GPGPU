`include "constants.vh"

module GPGPUControlPlane #(
    parameter SP_PER_SM = 32
) (
    input wire clk,
    input wire rst_n,

    input wire i_req_valid,
    output reg o_req_ready,
    input wire i_req_write,
    input wire [31:0] i_req_addr,
    input wire [31:0] i_req_wdata,
    input wire [3:0] i_req_wstrb,
    output reg o_rsp_valid,
    input wire i_rsp_ready,
    output reg [31:0] o_rsp_rdata,
    output reg [2:0] o_rsp_status,

    input wire [1:0] i_core_state,
    input wire i_stopped,
    input wire i_core_complete,
    output reg o_start,
    output reg o_stop,
    output reg o_clear_stopped,
    output wire o_irq,

    output reg [31:0] o_host_address,
    output reg [31:0] o_host_wdata,
    output reg o_host_imem_ren,
    output reg o_host_imem_wen,
    output reg o_host_dmem_ren,
    output reg o_host_dmem_wen,
    input wire [31:0] i_imem_rdata,
    input wire [31:0] i_dmem_rdata
);
    localparam [15:0] INTERFACE_VERSION = 16'd1;
    localparam [15:0] SP_COUNT = SP_PER_SM[15:0];
    localparam ACCESS_IDLE = 2'd0;
    localparam ACCESS_MEMORY = 2'd1;
    localparam ACCESS_CAPTURE = 2'd2;
    localparam ACCESS_RESPONSE = 2'd3;

    reg [1:0] current_state, next_state;
    reg memory_imem, memory_write;
    reg irq_enable, completion_pending;
    reg [31:0] decoded_rdata;
    reg [2:0] decoded_status;
    reg decoded_memory;

    wire device_idle = i_core_state == `CORE_IDLE;
    wire device_running = i_core_state == `CORE_RUNNING;
    wire [31:0] status_value = (device_idle ? `STATUS_IDLE : 32'b0) |
                               (device_running ? `STATUS_RUNNING : 32'b0) |
                               (i_stopped && device_idle ? `STATUS_STOPPED : 32'b0);
    wire [31:0] write_mask = {{8{i_req_wstrb[3]}}, {8{i_req_wstrb[2]}},
                             {8{i_req_wstrb[1]}}, {8{i_req_wstrb[0]}}};
    wire [31:0] write_value = i_req_wdata & write_mask;
    wire imem_selected = i_req_addr >= `IMEM_BASE &&
                         i_req_addr < `IMEM_BASE + 32'd4 * `IMEM_ENTRIES;
    wire dmem_selected = i_req_addr >= `DMEM_BASE &&
                         i_req_addr < `DMEM_BASE + 32'd4 * `DMEM_ENTRIES;
    wire request_accepted = i_req_valid && o_req_ready;
    wire write_accepted = request_accepted && i_req_write && decoded_status == `RSP_OK;
    wire acknowledge_done = write_accepted && i_req_addr == `REG_IRQ_STATUS && write_value[0];
    wire write_irq_enable = write_accepted && i_req_addr == `REG_IRQ_ENABLE && i_req_wstrb[0];
    wire kernel_completed = device_running && i_core_complete && !o_stop;

    // Decode byte offsets and validate the access without changing device state.
    always @(*) begin
        decoded_rdata = 32'b0;
        decoded_status = `RSP_OK;
        decoded_memory = 1'b0;

        if (i_req_addr[1:0] != 2'b00) begin
            decoded_status = `RSP_INVALID_ADDRESS;
        end else if (imem_selected || dmem_selected) begin
            if (!device_idle) begin
                decoded_status = `RSP_INVALID_STATE;
            end else if (i_req_write && i_req_wstrb != 4'b1111 && i_req_wstrb != 4'b0000) begin
                decoded_status = `RSP_INVALID_REQUEST;
            end else begin
                decoded_memory = !i_req_write || i_req_wstrb != 4'b0000;
            end
        end else begin
            case (i_req_addr)
                `REG_INFO: begin
                    if (i_req_write) begin
                        decoded_status = `RSP_ACCESS_DENIED;
                    end else begin
                        decoded_rdata = {INTERFACE_VERSION, SP_COUNT};
                    end
                end
                `REG_CONTROL: begin
                    if (!i_req_write) begin
                        decoded_status = `RSP_ACCESS_DENIED;
                    end else if ((write_value & ~(`CONTROL_START | `CONTROL_STOP)) != 0 ||
                                 write_value == (`CONTROL_START | `CONTROL_STOP)) begin
                        decoded_status = `RSP_INVALID_REQUEST;
                    end else if (write_value == `CONTROL_START && (!device_idle || i_stopped)) begin
                        decoded_status = `RSP_INVALID_STATE;
                    end
                end
                `REG_STATUS: begin
                    if (!i_req_write) begin
                        decoded_rdata = status_value;
                    end else if ((write_value & ~`STATUS_STOPPED) != 0) begin
                        decoded_status = `RSP_ACCESS_DENIED;
                    end
                end
                `REG_IRQ_ENABLE: begin
                    if (!i_req_write) begin
                        decoded_rdata = {31'b0, irq_enable};
                    end else if (write_value[31:1] != 0) begin
                        decoded_status = `RSP_INVALID_REQUEST;
                    end
                end
                `REG_IRQ_STATUS: begin
                    if (!i_req_write) begin
                        decoded_rdata = {31'b0, completion_pending};
                    end else if (write_value[31:1] != 0) begin
                        decoded_status = `RSP_INVALID_REQUEST;
                    end
                end
                default: decoded_status = `RSP_INVALID_ADDRESS;
            endcase
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            current_state <= ACCESS_IDLE;
        end else begin
            current_state <= next_state;
        end
    end

    always @(*) begin
        case (current_state)
            ACCESS_IDLE: next_state = request_accepted ? (decoded_memory ? ACCESS_MEMORY : ACCESS_RESPONSE) : ACCESS_IDLE;
            ACCESS_MEMORY: next_state = memory_write ? ACCESS_RESPONSE : ACCESS_CAPTURE;
            ACCESS_CAPTURE: next_state = ACCESS_RESPONSE;
            ACCESS_RESPONSE: next_state = i_rsp_ready ? ACCESS_IDLE : ACCESS_RESPONSE;
            default: next_state = ACCESS_IDLE;
        endcase
    end

    // State outputs are separate from state transitions and registered payloads.
    always @(*) begin
        o_req_ready = 1'b0;
        o_rsp_valid = 1'b0;
        o_start = 1'b0;
        o_stop = 1'b0;
        o_clear_stopped = 1'b0;
        o_host_imem_ren = 1'b0;
        o_host_imem_wen = 1'b0;
        o_host_dmem_ren = 1'b0;
        o_host_dmem_wen = 1'b0;

        case (current_state)
            ACCESS_IDLE: begin
                o_req_ready = 1'b1;
                if (i_req_valid && i_req_write && decoded_status == `RSP_OK) begin
                    case (i_req_addr)
                        `REG_CONTROL: begin
                            o_start = write_value == `CONTROL_START;
                            o_stop = write_value == `CONTROL_STOP;
                        end
                        `REG_STATUS: begin
                            o_clear_stopped = (write_value & `STATUS_STOPPED) != 0;
                        end
                        default: begin end
                    endcase
                end
            end
            ACCESS_MEMORY: begin
                if (device_idle) begin
                    o_host_imem_ren = memory_imem;
                    o_host_imem_wen = memory_imem && memory_write;
                    o_host_dmem_ren = !memory_imem;
                    o_host_dmem_wen = !memory_imem && memory_write;
                end
            end
            ACCESS_RESPONSE: begin
                o_rsp_valid = 1'b1;
            end
            default: begin end
        endcase
    end

    // Capture an accepted request once, then retain the response until consumed.
    always @(posedge clk) begin
        if (!rst_n) begin
            memory_imem <= 1'b0;
            memory_write <= 1'b0;
            o_host_address <= 32'b0;
            o_host_wdata <= 32'b0;
            o_rsp_rdata <= 32'b0;
            o_rsp_status <= `RSP_OK;
        end else if (request_accepted) begin
            o_rsp_rdata <= decoded_rdata;
            o_rsp_status <= decoded_status;
            if (decoded_memory) begin
                o_host_address <= (i_req_addr - (imem_selected ? `IMEM_BASE : `DMEM_BASE)) >> 2;
                o_host_wdata <= i_req_wdata;
                memory_imem <= imem_selected;
                memory_write <= i_req_write;
            end
        end else if (current_state == ACCESS_CAPTURE) begin
            o_rsp_rdata <= memory_imem ? i_imem_rdata : i_dmem_rdata;
        end
    end

    // Interrupt registers belong to the control plane, not the execution FSM.
    always @(posedge clk) begin
        if (!rst_n) begin
            irq_enable <= 1'b0;
        end else if (write_irq_enable) begin
            irq_enable <= i_req_wdata[0];
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            completion_pending <= 1'b0;
        end else if (o_start) begin
            completion_pending <= 1'b0;
        end else if (kernel_completed) begin
            completion_pending <= 1'b1;
        end else if (acknowledge_done) begin
            completion_pending <= 1'b0;
        end
    end

    assign o_irq = rst_n && irq_enable && completion_pending;

endmodule
