`include "constants.svh"

module GPGPUController (
    input clk,
    input rst_n,
    input wire i_start,
    input wire i_stop,
    input wire i_clear_stopped,
    input wire i_core_complete,

    output reg [1:0] o_core_state,
    output reg o_stopped
);
    reg [1:0] current_state, next_state;

    always @(posedge clk) begin
        if (!rst_n) begin
            current_state <= `CORE_IDLE;
        end else begin
            current_state <= next_state;
        end
    end

    always @(*) begin
        case (current_state)
            `CORE_IDLE: next_state = (i_start && !i_stop && !o_stopped) ? `CORE_RESET : `CORE_IDLE;
            `CORE_RESET: next_state = i_stop ? `CORE_IDLE : `CORE_RUNNING;
            `CORE_RUNNING: next_state = (i_stop || i_core_complete) ? `CORE_IDLE : `CORE_RUNNING;
            default: next_state = `CORE_IDLE;
        endcase
    end

    always @(*) begin
        case (current_state)
            `CORE_IDLE: begin
                o_core_state = `CORE_IDLE;
            end
            `CORE_RESET: begin
                o_core_state = `CORE_RESET;
            end
            `CORE_RUNNING: begin
                o_core_state = `CORE_RUNNING;
            end
            default: begin
                o_core_state = `CORE_IDLE;
            end
        endcase
    end

    // STOPPED inhibits START until explicitly acknowledged or externally reset.
    always @(posedge clk) begin
        if (!rst_n) begin
            o_stopped <= 1'b0;
        end else if (i_stop && current_state != `CORE_IDLE) begin
            o_stopped <= 1'b1;
        end else if (i_clear_stopped) begin
            o_stopped <= 1'b0;
        end
    end

endmodule
