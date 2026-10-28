module ExecutionController 
    import ControlPkg::*;
(
    input logic clk,
    input logic rst_n,
    input logic i_start,
    input logic i_stop,
    input logic i_clear_stopped,
    input logic i_core_complete,

    output core_state_t o_core_state,
    output logic o_stopped,
    output logic o_complete_pulse
);
    core_state_t current_state, next_state;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            current_state <= CORE_IDLE;
        end else begin
            current_state <= next_state;
        end
    end

    always_comb begin
        case (current_state)
            CORE_IDLE: begin
                if (i_start && !i_stop && !o_stopped) begin
                    next_state = CORE_RESET;
                end else begin
                    next_state = CORE_IDLE;
                end
            end
            CORE_RESET: begin
                if (i_stop) begin
                    next_state = CORE_IDLE;
                end else begin
                    next_state = CORE_RUNNING;
                end
            end
            CORE_RUNNING: begin
                if (i_stop || i_core_complete) begin
                    next_state = CORE_IDLE;
                end else begin
                    next_state = CORE_RUNNING;
                end
            end
            default: next_state = CORE_IDLE;
        endcase
    end

    always_comb begin
        case (current_state)
            CORE_IDLE: begin
                o_core_state = CORE_IDLE;
            end
            CORE_RESET: begin
                o_core_state = CORE_RESET;
            end
            CORE_RUNNING: begin
                o_core_state = CORE_RUNNING;
            end
            default: begin
                o_core_state = CORE_IDLE;
            end
        endcase
    end

    // Pre-edge normal-completion event: consumers latch it on the same edge
    // that returns CORE_RUNNING to CORE_IDLE. STOP suppresses completion, preserving abort.
    assign o_complete_pulse = (o_core_state == CORE_RUNNING) && i_core_complete && !i_stop;

    // STOPPED inhibits START until explicitly acknowledged or externally CORE_RESET.
    always_ff @(posedge clk) begin
        if (!rst_n) begin
            o_stopped <= '0;
        end else if (i_stop && current_state != CORE_IDLE) begin
            o_stopped <= '1;
        end else if (i_clear_stopped) begin
            o_stopped <= '0;
        end
    end

endmodule
