`include "constants.svh"

// Software-visible CSR bank. Decode is combinational; i_write_fire is a
// validated, one-cycle commit from the sibling MMIO endpoint, not a bus.
module GPGPURegs #(
    parameter int unsigned SP_PER_SM = 32
) (
    input logic clk,
    input logic rst_n,
    input logic i_write,
    input logic [31:0] i_addr,
    input logic [31:0] i_wdata,
    input logic [3:0] i_byte_en,
    input logic i_write_fire,
    output logic [31:0] o_rdata,
    output logic [2:0] o_status,

    input logic i_idle,
    input logic i_running,
    input logic i_stopped,
    input logic i_complete_pulse,
    output logic o_start,
    output logic o_stop,
    output logic o_clear_stopped,
    output logic o_irq
);
    localparam logic [15:0] INTERFACE_VERSION = 16'd1;
    localparam logic [15:0] SP_COUNT = SP_PER_SM[15:0];
    logic irq_enable, completion_pending;

    wire [31:0] status_value = (i_idle ? `STATUS_IDLE : 32'b0) |
                               (i_running ? `STATUS_RUNNING : 32'b0) |
                               (i_stopped && i_idle ? `STATUS_STOPPED : 32'b0);
    wire [31:0] write_mask = {{8{i_byte_en[3]}}, {8{i_byte_en[2]}},
                             {8{i_byte_en[1]}}, {8{i_byte_en[0]}}};
    wire [31:0] write_value = i_wdata & write_mask;
    wire write_commit = i_write_fire && i_write && o_status == `RSP_OK;
    wire acknowledge_done = write_commit && i_addr == `REG_IRQ_STATUS && write_value[0];
    wire write_irq_enable = write_commit && i_addr == `REG_IRQ_ENABLE && i_byte_en[0];

    // Only requested fields and semantic State outputs participate in validation.
    // In particular, o_status is independent of i_write_fire and action outputs.
    always_comb begin
        o_rdata = 32'b0;
        o_status = `RSP_OK;
        if (i_addr[1:0] != 2'b00) begin
            o_status = `RSP_INVALID_ADDRESS;
        end else begin
            case (i_addr)
                `REG_INFO: begin
                    if (i_write) begin
                        o_status = `RSP_ACCESS_DENIED;
                    end else begin
                        o_rdata = {INTERFACE_VERSION, SP_COUNT};
                    end
                end
                `REG_CONTROL: begin
                    if (!i_write) begin
                        o_status = `RSP_ACCESS_DENIED;
                    end else if ((write_value & ~(`CONTROL_START | `CONTROL_STOP)) != 32'b0 ||
                                 write_value == (`CONTROL_START | `CONTROL_STOP)) begin
                        o_status = `RSP_INVALID_REQUEST;
                    end else if (write_value == `CONTROL_START && (!i_idle || i_stopped)) begin
                        o_status = `RSP_INVALID_STATE;
                    end
                end
                `REG_STATUS: begin
                    if (!i_write) begin
                        o_rdata = status_value;
                    end else if ((write_value & ~`STATUS_STOPPED) != 32'b0) begin
                        o_status = `RSP_ACCESS_DENIED;
                    end
                end
                `REG_IRQ_ENABLE: begin
                    if (!i_write) begin
                        o_rdata = {31'b0, irq_enable};
                    end else if (write_value[31:1] != 31'b0) begin
                        o_status = `RSP_INVALID_REQUEST;
                    end
                end
                `REG_IRQ_STATUS: begin
                    if (!i_write) begin
                        o_rdata = {31'b0, completion_pending};
                    end else if (write_value[31:1] != 31'b0) begin
                        o_status = `RSP_INVALID_REQUEST;
                    end
                end
                default: o_status = `RSP_INVALID_ADDRESS;
            endcase
        end
    end

    // These pulses connect directly to State; MMIO does not relay them.
    assign o_start = rst_n && write_commit && i_addr == `REG_CONTROL && write_value == `CONTROL_START;
    assign o_stop = rst_n && write_commit && i_addr == `REG_CONTROL && write_value == `CONTROL_STOP;
    assign o_clear_stopped = rst_n && write_commit && i_addr == `REG_STATUS &&
                             (write_value & `STATUS_STOPPED) != 32'b0;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            irq_enable <= 1'b0;
        end else if (write_irq_enable) begin
            irq_enable <= i_wdata[0];
        end
    end

    // Preserve reset > new START > normal completion > software W1C priority.
    // State suppresses i_complete_pulse when STOP wins a completion edge.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            completion_pending <= 1'b0;
        end else if (o_start) begin
            completion_pending <= 1'b0;
        end else if (i_complete_pulse) begin
            completion_pending <= 1'b1;
        end else if (acknowledge_done) begin
            completion_pending <= 1'b0;
        end
    end

    assign o_irq = rst_n && irq_enable && completion_pending;
endmodule
