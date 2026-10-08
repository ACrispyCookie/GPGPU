`timescale 1ns/1ps
`include "constants.svh"

// Control-plane regression: real sibling modules and synchronous BRAMs, with
// only the core-completion input substituted for the SMX. Run with --timing.
module tb_GPGPUControl;
    localparam logic [31:0] IMEM_LAST = `IMEM_BASE + 4 * (`IMEM_ENTRIES - 1);
    localparam logic [31:0] DMEM_LAST = `DMEM_BASE + 4 * (`DMEM_ENTRIES - 1);
    localparam logic [31:0] I_FIRST = 32'h1234_5678, I_LAST = 32'h89ab_cdef;
    localparam logic [31:0] D_FIRST = 32'hfedc_ba98, D_LAST = 32'h7654_3210;

    logic clk = 0, rst_n = 0;
    logic req_valid = 0, req_write = 0, rsp_ready = 0;
    logic [31:0] req_addr = 0, req_wdata = 0;
    logic [3:0] req_wstrb = 0;
    wire req_ready, rsp_valid;
    wire [31:0] rsp_rdata;
    wire [2:0] rsp_status;
    wire csr_write, csr_write_fire;
    wire [31:0] csr_addr, csr_wdata, csr_rdata;
    wire [3:0] csr_byte_en;
    wire [2:0] csr_status;
    logic core_complete = 0;
    wire start, stop, clear_stopped, irq, idle, running, stopped, complete_pulse;
    wire [1:0] core_state;

    MemoryInterface #(.ADDR_WIDTH(`IMEM_AW)) imem ();
    MemoryInterface #(.ADDR_WIDTH(`DMEM_AW)) dmem ();
    MemorySinglePort #(.DEPTH(`IMEM_ENTRIES), .INIT_FILE("")) imem_bram (
        .clk(clk), .memory(imem.slave)
    );
    MemorySinglePort #(.DEPTH(`DMEM_ENTRIES), .INIT_FILE("")) dmem_bram (
        .clk(clk), .memory(dmem.slave)
    );

    GPGPUMMIO mmio (
        .clk(clk), .rst_n(rst_n),
        .i_req_valid(req_valid), .o_req_ready(req_ready),
        .i_req_write(req_write), .i_req_addr(req_addr),
        .i_req_wdata(req_wdata), .i_req_wstrb(req_wstrb),
        .o_rsp_valid(rsp_valid), .i_rsp_ready(rsp_ready),
        .o_rsp_rdata(rsp_rdata), .o_rsp_status(rsp_status),
        .i_idle(idle), .imem(imem.master), .dmem(dmem.master),
        .o_csr_write(csr_write), .o_csr_addr(csr_addr),
        .o_csr_wdata(csr_wdata), .o_csr_byte_en(csr_byte_en),
        .o_csr_write_fire(csr_write_fire),
        .i_csr_rdata(csr_rdata), .i_csr_status(csr_status)
    );
    GPGPURegs #(.SP_PER_SM(32)) regs (
        .clk(clk), .rst_n(rst_n),
        .i_write(csr_write), .i_addr(csr_addr), .i_wdata(csr_wdata),
        .i_byte_en(csr_byte_en), .i_write_fire(csr_write_fire),
        .o_rdata(csr_rdata), .o_status(csr_status),
        .i_idle(idle), .i_running(running), .i_stopped(stopped),
        .i_complete_pulse(complete_pulse),
        .o_start(start), .o_stop(stop), .o_clear_stopped(clear_stopped), .o_irq(irq)
    );
    GPGPUState state (
        .clk(clk), .rst_n(rst_n), .i_start(start), .i_stop(stop),
        .i_clear_stopped(clear_stopped), .i_core_complete(core_complete),
        .o_core_state(core_state), .o_stopped(stopped),
        .o_idle(idle), .o_running(running), .o_complete_pulse(complete_pulse)
    );

    always #5 clk = ~clk;
    initial begin
        #100000;
        $fatal(1, "tb_GPGPUControl global timeout");
    end

    int checks = 0, cycles = 0;
    int accepted = 0, consumed = 0, aborted = 0;
    int starts = 0, stops = 0, clears = 0, commits = 0, completions = 0;
    int imem_writes = 0, dmem_writes = 0;
    int expected_imem_writes = 0, expected_dmem_writes = 0;
    string scenario = "initial reset";

    task automatic check(input logic condition, input string message);
        checks++;
        if (condition !== 1'b1)
            $fatal(1, "[%s] cycle %0d: %s", scenario, cycles, message);
    endtask

    // Independent software-visible model. No DUT internals or FSM encodings
    // beyond the published core-state constants are used by the scoreboard.
    logic [1:0] model_state = `CORE_IDLE;
    bit model_stopped = 0, model_enable = 0, model_pending = 0;
    bit busy = 0, saved_memory = 0, saved_imem = 0, saved_write = 0;
    int delay_left = 0;
    logic [31:0] saved_addr = 0, saved_wdata = 0, expected_rdata = 0;
    logic [2:0] expected_status = `RSP_OK;
    logic [31:0] model_imem [0:`IMEM_ENTRIES-1];
    logic [31:0] model_dmem [0:`DMEM_ENTRIES-1];
    bit valid_imem [0:`IMEM_ENTRIES-1];
    bit valid_dmem [0:`DMEM_ENTRIES-1];
    bit imem_output_known = 0, dmem_output_known = 0;
    logic [31:0] expected_imem_output = 0, expected_dmem_output = 0;

    function automatic logic [31:0] byte_mask(input logic [3:0] strobes);
        return {{8{strobes[3]}}, {8{strobes[2]}},
                {8{strobes[1]}}, {8{strobes[0]}}};
    endfunction
    function automatic bit in_imem(input logic [31:0] address);
        return address >= `IMEM_BASE && address <= IMEM_LAST;
    endfunction
    function automatic bit in_dmem(input logic [31:0] address);
        return address >= `DMEM_BASE && address <= DMEM_LAST;
    endfunction
    function automatic bit known_csr(input logic [31:0] address);
        return address == `REG_INFO || address == `REG_CONTROL ||
               address == `REG_STATUS || address == `REG_IRQ_ENABLE ||
               address == `REG_IRQ_STATUS;
    endfunction
    function automatic logic [31:0] model_status_word();
        return (model_state == `CORE_IDLE ? `STATUS_IDLE : 32'b0) |
               (model_state == `CORE_RUNNING ? `STATUS_RUNNING : 32'b0) |
               (model_state == `CORE_IDLE && model_stopped ? `STATUS_STOPPED : 32'b0);
    endfunction
    function automatic logic [2:0] access_status(
        input bit wr, input logic [31:0] address, data, input logic [3:0] strobes
    );
        logic [31:0] value;
        value = data & byte_mask(strobes);
        if (address[1:0] != 0) return `RSP_INVALID_ADDRESS;
        if (in_imem(address) || in_dmem(address)) begin
            if (model_state != `CORE_IDLE) return `RSP_INVALID_STATE;
            if (wr && strobes != 4'hf && strobes != 0) return `RSP_INVALID_REQUEST;
            return `RSP_OK;
        end
        case (address)
            `REG_INFO: return wr ? `RSP_ACCESS_DENIED : `RSP_OK;
            `REG_CONTROL: begin
                if (!wr) return `RSP_ACCESS_DENIED;
                if ((value & ~32'h3) != 0 || value == 3) return `RSP_INVALID_REQUEST;
                if (value == 1 && (model_state != `CORE_IDLE || model_stopped))
                    return `RSP_INVALID_STATE;
                return `RSP_OK;
            end
            `REG_STATUS: return wr && (value & ~32'h4) != 0 ? `RSP_ACCESS_DENIED : `RSP_OK;
            `REG_IRQ_ENABLE, `REG_IRQ_STATUS:
                return wr && value[31:1] != 0 ? `RSP_INVALID_REQUEST : `RSP_OK;
            default: return `RSP_INVALID_ADDRESS;
        endcase
    endfunction
    function automatic int response_latency(
        input bit wr, input logic [31:0] address,
        input logic [3:0] strobes, input logic [2:0] status_code
    );
        if (status_code != `RSP_OK || !(in_imem(address) || in_dmem(address)) ||
            (wr && strobes == 0)) return 0;
        return wr ? 1 : 2;
    endfunction

    // Sample pre-edge handshakes/events, update the reference model once, then
    // check after NBA. Drivers below change inputs only at falling edges.
    always @(posedge clk) begin : scoreboard
        bit accept_now, consume_now, commit_now, start_now, stop_now, clear_now;
        bit completion_now, memory_edge;
        logic [2:0] decoded_status;
        logic [31:0] value, decoded_data;
        int word_index;
        cycles++;
        if (!rst_n) begin
            if (busy) aborted++;
            busy = 0;
            delay_left = 0;
            saved_memory = 0;
            model_state = `CORE_IDLE;
            model_stopped = 0;
            model_enable = 0;
            model_pending = 0;
        end else begin
            check(req_ready === !busy, "single-outstanding request readiness");
            check(rsp_valid === (busy && delay_left == 0), "pre-edge response latency/valid");
            if (busy && delay_left == 0) begin
                check(rsp_status === expected_status, "held response status");
                check(rsp_rdata === expected_rdata, "held response data/snapshot");
            end
            accept_now = req_valid && !busy;
            consume_now = busy && delay_left == 0 && rsp_ready;
            decoded_status = access_status(req_write, req_addr, req_wdata, req_wstrb);
            value = req_wdata & byte_mask(req_wstrb);
            commit_now = accept_now && req_write && known_csr(req_addr) && decoded_status == `RSP_OK;
            start_now = commit_now && req_addr == `REG_CONTROL && value == 1;
            stop_now = commit_now && req_addr == `REG_CONTROL && value == 2;
            clear_now = commit_now && req_addr == `REG_STATUS && value[2];
            completion_now = model_state == `CORE_RUNNING && core_complete && !stop_now;
            check(csr_write_fire === commit_now, "CSR commit only on accepted valid CSR write");
            check(start === start_now, "START exactly once, not on invalid/unaccepted write");
            check(stop === stop_now, "STOP exactly once, not on invalid/unaccepted write");
            check(clear_stopped === clear_now, "STOPPED clear exactly once");
            check(complete_pulse === completion_now, "pre-edge normal-completion event; STOP priority");
            if (accept_now && known_csr(req_addr)) begin
                check(csr_write === req_write && csr_addr === req_addr &&
                      csr_wdata === req_wdata && csr_byte_en === req_wstrb,
                      "CSR request payload forwarding");
                check(csr_status === decoded_status, "combinational CSR validation");
            end
            starts += int'(start);
            stops += int'(stop);
            clears += int'(clear_stopped);
            commits += int'(csr_write_fire);
            completions += int'(complete_pulse);

            // A=accept, B=BRAM operation, C=read-response capture. The memory
            // target is write-first, and ren must gate both reads and writes.
            memory_edge = busy && saved_memory && delay_left == (saved_write ? 1 : 2);
            check(imem.ren === (memory_edge && saved_imem), "IMEM access edge/selection");
            check(dmem.ren === (memory_edge && !saved_imem), "DMEM access edge/selection");
            check(imem.wen === (memory_edge && saved_imem && saved_write), "IMEM write enable");
            check(dmem.wen === (memory_edge && !saved_imem && saved_write), "DMEM write enable");
            if (imem.ren && imem.wen) imem_writes++;
            if (dmem.ren && dmem.wen) dmem_writes++;
            if (memory_edge) begin
                word_index = int'((saved_addr - (saved_imem ? `IMEM_BASE : `DMEM_BASE)) >> 2);
                if (saved_imem) begin
                    check(int'(imem.addr) == word_index, "captured IMEM word address");
                    if (saved_write) begin
                        check(imem.wdata === saved_wdata, "captured IMEM write payload");
                        model_imem[word_index] = saved_wdata;
                        valid_imem[word_index] = 1;
                        expected_imem_writes++;
                    end else check(valid_imem[word_index], "read only initialized IMEM");
                    expected_imem_output = model_imem[word_index];
                    imem_output_known = 1;
                end else begin
                    check(int'(dmem.addr) == word_index, "captured DMEM word address");
                    if (saved_write) begin
                        check(dmem.wdata === saved_wdata, "captured DMEM write payload");
                        model_dmem[word_index] = saved_wdata;
                        valid_dmem[word_index] = 1;
                        expected_dmem_writes++;
                    end else check(valid_dmem[word_index], "read only initialized DMEM");
                    expected_dmem_output = model_dmem[word_index];
                    dmem_output_known = 1;
                end
            end

            if (accept_now) begin
                accepted++;
                busy = 1;
                expected_status = decoded_status;
                decoded_data = 0;
                if (!req_write && decoded_status == `RSP_OK) begin
                    case (req_addr)
                        `REG_INFO: decoded_data = 32'h0001_0020;
                        `REG_STATUS: decoded_data = model_status_word();
                        `REG_IRQ_ENABLE: decoded_data = {31'b0, model_enable};
                        `REG_IRQ_STATUS: decoded_data = {31'b0, model_pending};
                        default: begin
                            if (in_imem(req_addr)) begin
                                word_index = int'((req_addr - `IMEM_BASE) >> 2);
                                check(valid_imem[word_index], "initialized IMEM response source");
                                decoded_data = model_imem[word_index];
                            end else if (in_dmem(req_addr)) begin
                                word_index = int'((req_addr - `DMEM_BASE) >> 2);
                                check(valid_dmem[word_index], "initialized DMEM response source");
                                decoded_data = model_dmem[word_index];
                            end
                        end
                    endcase
                end
                expected_rdata = decoded_data;
                delay_left = response_latency(req_write, req_addr, req_wstrb, decoded_status);
                saved_memory = delay_left != 0;
                saved_imem = in_imem(req_addr);
                saved_write = req_write;
                saved_addr = req_addr;
                saved_wdata = req_wdata;
            end else if (consume_now) begin
                consumed++;
                busy = 0;
                saved_memory = 0;
            end else if (busy && delay_left > 0) delay_left--;

            // All response snapshots above use pre-edge register/state values.
            if (commit_now && req_addr == `REG_IRQ_ENABLE && req_wstrb[0])
                model_enable = req_wdata[0];
            if (start_now) model_pending = 0;
            else if (completion_now) model_pending = 1;
            else if (commit_now && req_addr == `REG_IRQ_STATUS && value[0]) model_pending = 0;
            if (stop_now && model_state != `CORE_IDLE) model_stopped = 1;
            else if (clear_now) model_stopped = 0;
            case (model_state)
                `CORE_IDLE: if (start_now) model_state = `CORE_RESET;
                `CORE_RESET: model_state = stop_now ? `CORE_IDLE : `CORE_RUNNING;
                `CORE_RUNNING: if (stop_now || core_complete) model_state = `CORE_IDLE;
                default: $fatal(1, "Illegal reference state");
            endcase
        end
        #1;
        check(core_state === model_state && stopped === model_stopped, "execution state and STOPPED");
        check(irq === (rst_n && model_enable && model_pending), "IRQ enable/pending/reset gating");
        check(req_ready === !busy, "post-edge request readiness");
        check(rsp_valid === (busy && delay_left == 0), "post-edge exact response latency");
        if (rst_n) begin
            check(idle === (model_state == `CORE_IDLE), "semantic IDLE output");
            check(running === (model_state == `CORE_RUNNING), "semantic RUNNING output");
            if (busy && delay_left == 0) begin
                check(rsp_status === expected_status, "post-edge response status");
                check(rsp_rdata === expected_rdata, "post-edge response snapshot");
            end
        end else begin
            check(rsp_rdata === 0 && rsp_status === `RSP_OK, "reset response metadata");
        end
        if (imem_output_known) check(imem.rdata === expected_imem_output, "IMEM clocked write-first/hold");
        if (dmem_output_known) check(dmem.rdata === expected_dmem_output, "DMEM clocked write-first/hold");
    end

    task automatic expect_response(input logic [2:0] status_code, input logic [31:0] data);
        check(rsp_valid === 1'b1, "response present");
        check(rsp_status === status_code,
              $sformatf("response status expected %0d got %0d", status_code, rsp_status));
        check(rsp_rdata === data,
              $sformatf("response data expected %08x got %08x", data, rsp_rdata));
    endtask

    // Returns at a negedge with the response deliberately unconsumed. Optional
    // completion stimulus is asserted on the SAME negedge as the request.
    task automatic begin_access(
        input bit wr, input logic [31:0] address, data, input logic [3:0] strobes,
        input logic [2:0] status_code, input logic [31:0] read_data,
        input bit complete_on_accept = 0
    );
        int before_accept, latency;
        @(negedge clk);
        req_valid = 1;
        req_write = wr;
        req_addr = address;
        req_wdata = data;
        req_wstrb = strobes;
        rsp_ready = 0;
        if (complete_on_accept) core_complete = 1;
        before_accept = accepted;
        latency = response_latency(wr, address, strobes, status_code);
        #1;
        check(req_ready === 1'b1, "request starts without outstanding response");
        @(posedge clk); #1;
        check(accepted == before_accept + 1, "one acceptance at A");
        check(rsp_valid === (latency == 0), "immediate versus BRAM response at A");
        if (latency == 0) expect_response(status_code, read_data);
        @(negedge clk);
        req_valid = 0;
        // Poison offered fields in the BRAM pipeline; operation must use the
        // captured request, including bank/address/data, not these live fields.
        if (latency != 0) begin
            req_write = !wr;
            req_addr = in_imem(address) ? `DMEM_BASE : `IMEM_BASE;
            req_wdata = ~data;
            req_wstrb = 4'h3;
        end
        for (int edge_number = 1; edge_number <= latency; edge_number++) begin
            @(posedge clk); #1;
            check(rsp_valid === (edge_number == latency), "BRAM B/C response timing");
            if (edge_number == latency) expect_response(status_code, read_data);
            @(negedge clk);
        end
    endtask

    task automatic hold_response(input int count);
        logic [31:0] snapshot_data;
        logic [2:0] snapshot_status;
        snapshot_data = rsp_rdata;
        snapshot_status = rsp_status;
        repeat (count) begin
            @(posedge clk); #1;
            expect_response(snapshot_status, snapshot_data);
            check(req_ready === 1'b0, "request blocked by held response");
            @(negedge clk);
        end
    endtask

    task automatic finish_access();
        int before_consume;
        @(negedge clk);
        before_consume = consumed;
        rsp_ready = 1;
        @(posedge clk); #1;
        check(consumed == before_consume + 1, "one response consumption");
        check(!rsp_valid && req_ready, "response retired before next acceptance");
        @(negedge clk);
        rsp_ready = 0;
    endtask

    task automatic transfer(
        input bit wr, input logic [31:0] address, data, input logic [3:0] strobes,
        input logic [2:0] status_code, input logic [31:0] read_data,
        input int hold_cycles = 0, input bit complete_on_accept = 0
    );
        begin_access(wr, address, data, strobes, status_code, read_data, complete_on_accept);
        hold_response(hold_cycles);
        finish_access();
    endtask
    task automatic rd(input logic [31:0] address, data, input logic [3:0] strobes = 4'hf);
        transfer(0, address, 0, strobes, `RSP_OK, data);
    endtask
    task automatic wr(
        input logic [31:0] address, data, input logic [3:0] strobes = 4'hf,
        input logic [2:0] status_code = `RSP_OK
    );
        transfer(1, address, data, strobes, status_code, 0);
    endtask

    // Keep a different, real second request valid throughout backpressure and
    // response consumption. It must first execute on the following edge, not
    // during the stall or on the first response's consumption edge.
    task automatic queue_behind_response(
        input bit second_write, input logic [31:0] address, data,
        input logic [3:0] strobes, input logic [2:0] status_code,
        input logic [31:0] read_data
    );
        int before_accept, before_consume, latency;
        logic [31:0] old_data;
        logic [2:0] old_status;
        before_accept = accepted;
        before_consume = consumed;
        old_data = rsp_rdata;
        old_status = rsp_status;
        latency = response_latency(second_write, address, strobes, status_code);
        @(negedge clk);
        req_valid = 1;
        req_write = second_write;
        req_addr = address;
        req_wdata = data;
        req_wstrb = strobes;
        repeat (3) begin
            @(posedge clk); #1;
            check(accepted == before_accept && consumed == before_consume,
                  "offered second request cannot execute under backpressure");
            expect_response(old_status, old_data);
            check(!req_ready && !csr_write_fire && !start && !stop && !clear_stopped,
                  "no repeated CSR side effects under backpressure");
            @(negedge clk);
        end
        rsp_ready = 1;
        @(posedge clk); #1;
        check(consumed == before_consume + 1 && accepted == before_accept,
              "consume first response without simultaneously accepting second");
        check(req_ready && !rsp_valid, "ready between consecutive transactions");
        @(negedge clk);
        rsp_ready = 0;
        @(posedge clk); #1;
        check(accepted == before_accept + 1, "held second request accepted next edge only");
        check(rsp_valid === (latency == 0), "queued request response timing at A");
        if (latency == 0) expect_response(status_code, read_data);
        @(negedge clk);
        req_valid = 0;
        for (int edge_number = 1; edge_number <= latency; edge_number++) begin
            @(posedge clk); #1;
            check(rsp_valid === (edge_number == latency), "queued BRAM response B/C timing");
            if (edge_number == latency) expect_response(status_code, read_data);
            @(negedge clk);
        end
        hold_response(3);
        finish_access();
    endtask

    task automatic reset_device(input bit already_at_negedge = 0, input bit completion_level = 0);
        if (!already_at_negedge) @(negedge clk);
        rst_n = 0;
        req_valid = 0;
        rsp_ready = 0;
        core_complete = completion_level;
        repeat (3) begin @(posedge clk); #1; end
        @(negedge clk);
        core_complete = 0;
        rst_n = 1;
        @(posedge clk); #1;
        check(idle && !running && !stopped && !irq && !rsp_valid && req_ready,
              "reset restores clean idle/control/transaction state");
    endtask

    task automatic start_run();
        begin_access(1, `REG_CONTROL, 1, 4'h1, `RSP_OK, 0);
        check(core_state === `CORE_RESET && !idle && !running && !stopped,
              "one hidden RESET launch cycle after START");
        // No second bus transaction can be accepted during this launch cycle,
        // but the simple combinational CSR description must still report zero.
        req_write = 0;
        req_addr = `REG_STATUS;
        req_wdata = 0;
        req_wstrb = 0;
        #1;
        check(csr_addr === `REG_STATUS && !csr_write && csr_status === `RSP_OK && csr_rdata === 0,
              "software STATUS hides RESET (neither IDLE nor RUNNING)");
        expect_response(`RSP_OK, 0);  // Original START response, not the new preview.
        finish_access();
        check(running && !idle && !stopped, "RESET advances to RUNNING");
        rd(`REG_STATUS, 2);
    endtask
    task automatic complete_run();
        int before_complete;
        @(negedge clk);
        before_complete = completions;
        check(running, "completion injected only while running");
        core_complete = 1;
        #1;
        check(complete_pulse, "normal completion is combinational before the edge");
        @(posedge clk); #1;
        check(idle && !stopped && completions == before_complete + 1, "one normal completion");
        repeat (3) begin
            @(posedge clk); #1;
            check(completions == before_complete + 1 && !complete_pulse,
                  "sustained completion does not retrigger in IDLE");
        end
        @(negedge clk);
        core_complete = 0;
    endtask

    initial begin : regression
        int before_complete, before_start;
        logic [3:0] mask;
        for (int n = 0; n < `IMEM_ENTRIES; n++) valid_imem[n] = 0;
        for (int n = 0; n < `DMEM_ENTRIES; n++) valid_dmem[n] = 0;
        reset_device();
        rd(`REG_INFO, 32'h0001_0020);
        rd(`REG_STATUS, 1);
        rd(`REG_IRQ_ENABLE, 0);
        rd(`REG_IRQ_STATUS, 0);

        scenario = "permissions, invalid addresses, masked reserved bits";
        wr(`REG_INFO, 32'hffff_ffff, 4'hf, `RSP_ACCESS_DENIED);
        wr(`REG_INFO, 0, 0, `RSP_ACCESS_DENIED);
        transfer(0, `REG_CONTROL, 0, 0, `RSP_ACCESS_DENIED, 0, 2);
        wr(`REG_CONTROL, 3, 4'hf, `RSP_INVALID_REQUEST);
        wr(`REG_CONTROL, 4, 4'h1, `RSP_INVALID_REQUEST);
        wr(`REG_CONTROL, 32'h100, 4'h2, `RSP_INVALID_REQUEST);
        wr(`REG_STATUS, 1, 4'h1, `RSP_ACCESS_DENIED);
        wr(`REG_STATUS, 2, 4'h1, `RSP_ACCESS_DENIED);
        wr(`REG_STATUS, 5, 4'h1, `RSP_ACCESS_DENIED);
        wr(`REG_STATUS, 32'h100, 4'h2, `RSP_ACCESS_DENIED);
        wr(`REG_IRQ_ENABLE, 2, 4'h1, `RSP_INVALID_REQUEST);
        wr(`REG_IRQ_STATUS, 2, 4'h1, `RSP_INVALID_REQUEST);
        wr(`REG_IRQ_ENABLE, 32'h100, 4'h2, `RSP_INVALID_REQUEST);
        wr(`REG_IRQ_STATUS, 32'h8000_0000, 4'h8, `RSP_INVALID_REQUEST);
        for (int reg_number = 0; reg_number < 5; reg_number++) begin
            for (int offset = 1; offset <= 3; offset++) begin
                transfer(0, 32'(reg_number * 4 + offset), 0, 4'hf, `RSP_INVALID_ADDRESS, 0);
                wr(32'(reg_number * 4 + offset), 32'hffff_ffff, 4'hf, `RSP_INVALID_ADDRESS);
            end
        end
        transfer(0, 32'h0014, 0, 4'hf, `RSP_INVALID_ADDRESS, 0);
        wr(32'h0014, 1, 4'hf, `RSP_INVALID_ADDRESS);
        transfer(0, 32'h1ffc, 0, 4'hf, `RSP_INVALID_ADDRESS, 0);
        wr(32'h6000, 32'hbad0_bad0, 4'hf, `RSP_INVALID_ADDRESS);
        transfer(0, 32'hffff_fffc, 0, 0, `RSP_INVALID_ADDRESS, 0);
        wr(32'hffff_ffff, 3, 0, `RSP_INVALID_ADDRESS);
        wr(`REG_CONTROL, 32'hffff_ff03, 0);  // All data unselected: no command.
        wr(`REG_CONTROL, 1, 4'he);           // Low byte unselected: no START.
        wr(`REG_CONTROL, 32'hffff_ff00, 4'h1);
        wr(`REG_STATUS, 32'hffff_ff00, 4'h1);
        wr(`REG_IRQ_ENABLE, 32'hffff_ff01, 4'h1);
        rd(`REG_IRQ_ENABLE, 1);
        wr(`REG_IRQ_ENABLE, 0, 0);
        wr(`REG_IRQ_ENABLE, 1, 4'he);
        wr(`REG_IRQ_ENABLE, 2, 4'h1, `RSP_INVALID_REQUEST);
        rd(`REG_IRQ_ENABLE, 1);
        wr(`REG_IRQ_ENABLE, 0, 4'h1);
        wr(`REG_CONTROL, 2, 4'h1);           // STOP in IDLE succeeds, no sticky flag.
        rd(`REG_STATUS, 1);
        rd(`REG_IRQ_STATUS, 0);

        scenario = "held OK read versus queued access-denied write";
        begin_access(0, `REG_INFO, 0, 4'hf, `RSP_OK, 32'h0001_0020);
        queue_behind_response(1, `REG_INFO, 0, 4'hf, `RSP_ACCESS_DENIED, 0);

        scenario = "BRAM boundaries, banks, synchronous latency, all byte masks";
        wr(`IMEM_BASE, I_FIRST);
        wr(IMEM_LAST, I_LAST);
        wr(`IMEM_BASE + 32'h100, 32'h0bad_f00d);
        wr(`DMEM_BASE, D_FIRST);
        wr(DMEM_LAST, D_LAST);
        wr(`DMEM_BASE + 32'h100, 32'hcafe_beef);
        rd(IMEM_LAST, I_LAST);
        // IMEM_LAST+4 is the adjacent valid DMEM base, NOT an invalid address.
        rd(IMEM_LAST + 4, D_FIRST);
        rd(DMEM_LAST, D_LAST);
        transfer(0, DMEM_LAST + 4, 0, 4'hf, `RSP_INVALID_ADDRESS, 0);
        for (int offset = 1; offset <= 3; offset++) begin
            wr(`IMEM_BASE + 32'(offset), 0, 4'hf, `RSP_INVALID_ADDRESS);
            transfer(0, IMEM_LAST + 32'(offset), 0, 0, `RSP_INVALID_ADDRESS, 0);
            wr(`DMEM_BASE + 32'(offset), 0, 0, `RSP_INVALID_ADDRESS);
            transfer(0, DMEM_LAST + 32'(offset), 0, 4'hf, `RSP_INVALID_ADDRESS, 0);
        end
        for (int m = 0; m < 16; m++) begin
            mask = 4'(m);
            rd(`REG_INFO, 32'h0001_0020, mask);
            rd(`IMEM_BASE, I_FIRST, mask);   // Reads ignore all byte strobes.
            rd(`DMEM_BASE, D_FIRST, mask);
            if (m != 15) begin
                wr(`IMEM_BASE, 32'hdead_beef, mask, m == 0 ? `RSP_OK : `RSP_INVALID_REQUEST);
                wr(`DMEM_BASE, 32'hdead_beef, mask, m == 0 ? `RSP_OK : `RSP_INVALID_REQUEST);
                rd(`IMEM_BASE, I_FIRST);
                rd(`DMEM_BASE, D_FIRST);
            end
        end
        rd(`IMEM_BASE + 32'h100, 32'h0bad_f00d);
        rd(`DMEM_BASE + 32'h100, 32'hcafe_beef);
        rd(IMEM_LAST, I_LAST);
        rd(DMEM_LAST, D_LAST);

        scenario = "completion while disabled, IRQ R/W and W1C masking";
        start_run();
        wr(`REG_CONTROL, 1, 4'h1, `RSP_INVALID_STATE);
        wr(`REG_CONTROL, 3, 4'h1, `RSP_INVALID_REQUEST);
        for (int m = 0; m < 16; m++) begin
            mask = 4'(m);
            wr(`IMEM_BASE, 0, mask, `RSP_INVALID_STATE);
            wr(`DMEM_BASE, 0, mask, `RSP_INVALID_STATE);
        end
        transfer(0, `IMEM_BASE, 0, 0, `RSP_INVALID_STATE, 0);
        transfer(0, `DMEM_BASE, 0, 4'hf, `RSP_INVALID_STATE, 0, 2);
        transfer(0, DMEM_LAST + 4, 0, 4'hf, `RSP_INVALID_ADDRESS, 0);
        rd(`REG_STATUS, 2);
        rd(`REG_INFO, 32'h0001_0020);
        complete_run();
        check(!irq, "completion pending with IRQ disabled");
        rd(`REG_STATUS, 1);
        rd(`REG_IRQ_STATUS, 1);
        wr(`REG_IRQ_ENABLE, 32'hffff_ff01, 4'h1);
        check(irq, "enabling IRQ exposes already-pending completion");
        wr(`REG_IRQ_ENABLE, 0, 4'h1);
        check(!irq, "disabling IRQ preserves pending but lowers IRQ");
        rd(`REG_IRQ_STATUS, 1);
        wr(`REG_IRQ_ENABLE, 1, 4'h1);
        wr(`REG_IRQ_STATUS, 0, 4'h1);
        wr(`REG_IRQ_STATUS, 1, 0);
        wr(`REG_IRQ_STATUS, 1, 4'he);
        wr(`REG_IRQ_STATUS, 3, 4'h1, `RSP_INVALID_REQUEST);
        wr(`REG_IRQ_ENABLE, 2, 4'h1, `RSP_INVALID_REQUEST);
        rd(`REG_IRQ_STATUS, 1);
        rd(`REG_IRQ_ENABLE, 1);
        check(irq, "invalid/no-op/masked writes preserve pending and IRQ enable");
        transfer(1, `REG_IRQ_STATUS, 32'hffff_ff01, 4'h1, `RSP_OK, 0, 3);
        rd(`REG_IRQ_STATUS, 0);
        check(!irq, "selected low-byte W1C clears IRQ once");

        scenario = "START clears old DONE; completion level ignored in launch/idle";
        start_run();
        complete_run();
        check(irq, "old completion available before relaunch");
        before_complete = completions;
        begin_access(1, `REG_CONTROL, 32'hffff_ff01, 4'h1, `RSP_OK, 0, 1);
        check(core_state === `CORE_RESET && !irq && completions == before_complete,
              "START clears old completion and does not complete in RESET");
        hold_response(1);  // B transitions RESET to RUNNING, no completion at B.
        check(running && completions == before_complete, "completion level ignored during RESET");
        hold_response(3);  // C completes; remaining held-level edges must be inert.
        check(idle && irq && completions == before_complete + 1, "one completion after launch");
        finish_access();
        @(negedge clk); core_complete = 0;
        rd(`REG_IRQ_STATUS, 1);
        wr(`REG_IRQ_STATUS, 1, 4'h1);

        scenario = "W1C plus completion: new event wins on same acceptance edge";
        start_run();
        transfer(1, `REG_IRQ_STATUS, 1, 4'h1, `RSP_OK, 0, 3, 1);
        check(idle && !stopped && irq, "completion wins simultaneous W1C");
        rd(`REG_IRQ_STATUS, 1);
        @(negedge clk); core_complete = 0;
        wr(`REG_IRQ_STATUS, 1, 4'h1);

        scenario = "old IRQ read snapshot; queued W1C cannot commit while stalled";
        start_run();
        begin_access(0, `REG_IRQ_STATUS, 0, 0, `RSP_OK, 0);
        @(negedge clk); core_complete = 1;
        @(posedge clk); #1;
        check(idle && irq, "completion occurs with an old IRQ read response outstanding");
        expect_response(`RSP_OK, 0);
        queue_behind_response(1, `REG_IRQ_STATUS, 1, 4'h1, `RSP_OK, 0);
        check(!irq, "queued W1C eventually commits exactly once");
        @(negedge clk); core_complete = 0;
        rd(`REG_IRQ_STATUS, 0);

        scenario = "old RUNNING status read remains stable through completion";
        start_run();
        begin_access(0, `REG_STATUS, 0, 4'hf, `RSP_OK, 2);
        complete_run();
        expect_response(`RSP_OK, 2);
        queue_behind_response(0, `REG_STATUS, 0, 0, `RSP_OK, 1);
        wr(`REG_IRQ_STATUS, 1, 4'h1);

        scenario = "held START, queued STOP, sticky STOPPED, explicit clear/restart";
        begin_access(1, `REG_CONTROL, 1, 4'h1, `RSP_OK, 0);
        check(core_state === `CORE_RESET, "START takes effect before response consumption");
        queue_behind_response(1, `REG_CONTROL, 2, 4'h1, `RSP_OK, 0);
        check(idle && stopped && !irq, "queued STOP aborts without normal completion");
        rd(`REG_STATUS, 5);
        rd(`REG_IRQ_STATUS, 0);
        wr(`REG_CONTROL, 1, 4'h1, `RSP_INVALID_STATE);
        wr(`REG_CONTROL, 2, 4'h1);  // An idle STOP must not clear an existing sticky flag.
        wr(`REG_STATUS, 5, 4'h1, `RSP_ACCESS_DENIED);
        wr(`REG_STATUS, 4, 0);
        wr(`REG_STATUS, 4, 4'he);
        wr(`REG_STATUS, 3, 4'he);  // Unselected read-only bits are ignored too.
        rd(`REG_STATUS, 5);
        begin_access(1, `REG_STATUS, 32'hffff_ff04, 4'h1, `RSP_OK, 0);
        check(idle && !stopped, "STOPPED clear does not auto-launch");
        before_start = starts;
        hold_response(2);
        check(idle && starts == before_start, "acknowledgment alone stays IDLE");
        queue_behind_response(1, `REG_CONTROL, 1, 4'h1, `RSP_OK, 0);
        check(running && starts == before_start + 1, "a later accepted START is required");

        scenario = "STOP plus completion: abort wins, no DONE event";
        before_complete = completions;
        transfer(1, `REG_CONTROL, 2, 4'h1, `RSP_OK, 0, 3, 1);
        check(idle && stopped && !irq && completions == before_complete,
              "STOP suppresses coincident completion");
        rd(`REG_IRQ_STATUS, 0);
        rd(`REG_STATUS, 5);
        @(negedge clk); core_complete = 0;
        wr(`REG_STATUS, 4, 4'h1);
        start_run();
        scenario = "invalid STOP cannot suppress a real completion";
        transfer(1, `REG_CONTROL, 3, 4'h1, `RSP_INVALID_REQUEST, 0, 2, 1);
        check(idle && !stopped && irq, "invalid command has no STOP side effect");
        @(negedge clk); core_complete = 0;
        wr(`REG_IRQ_STATUS, 1, 4'h1);

        scenario = "queued BRAM write/read and real single-outstanding ordering";
        begin_access(1, `DMEM_BASE + 32'h100, 32'ha5a5_5a5a, 4'hf, `RSP_OK, 0);
        queue_behind_response(1, `DMEM_BASE + 32'h100, 32'h55aa_33cc, 4'hf, `RSP_OK, 0);
        rd(`DMEM_BASE + 32'h100, 32'h55aa_33cc);
        begin_access(0, `IMEM_BASE, 0, 0, `RSP_OK, I_FIRST);
        queue_behind_response(0, `DMEM_BASE, 0, 4'hf, `RSP_OK, D_FIRST);
        // Recheck memory after every running/invalid/no-op write class above.
        rd(`IMEM_BASE, I_FIRST);
        rd(IMEM_LAST, I_LAST);
        rd(`DMEM_BASE, D_FIRST);
        rd(DMEM_LAST, D_LAST);

        scenario = "reset drops already-written BRAM response, retains BRAM contents";
        // Reset after the B write edge only. Do not require cancellation of a
        // captured write by reset before B: that is an unchanged baseline caveat.
        begin_access(1, `IMEM_BASE + 32'h100, 32'hd00d_fade, 4'hf, `RSP_OK, 0);
        reset_device(1);
        rd(`IMEM_BASE + 32'h100, 32'hd00d_fade);
        rd(`DMEM_BASE + 32'h100, 32'h55aa_33cc);
        rd(`REG_IRQ_ENABLE, 0);
        rd(`REG_IRQ_STATUS, 0);

        scenario = "reset clears enabled pending IRQ and held read metadata";
        wr(`REG_IRQ_ENABLE, 1, 4'h1);
        start_run();
        complete_run();
        begin_access(0, `REG_IRQ_STATUS, 0, 4'hf, `RSP_OK, 1);
        reset_device(1, 1);
        rd(`REG_IRQ_ENABLE, 0);
        rd(`REG_IRQ_STATUS, 0);
        rd(`REG_STATUS, 1);

        scenario = "reset wins over completion while RUNNING";
        wr(`REG_IRQ_ENABLE, 1, 4'h1);
        start_run();
        begin_access(0, `REG_STATUS, 0, 4'hf, `RSP_OK, 2);
        reset_device(1, 1);
        rd(`REG_IRQ_ENABLE, 0);
        rd(`REG_IRQ_STATUS, 0);
        rd(`REG_STATUS, 1);

        scenario = "reset clears STOPPED and permits a later launch";
        start_run();
        begin_access(1, `REG_CONTROL, 2, 4'h1, `RSP_OK, 0);
        check(stopped, "STOPPED set before reset");
        reset_device(1);
        rd(`REG_STATUS, 1);
        rd(`REG_IRQ_STATUS, 0);
        start_run();
        wr(`REG_CONTROL, 2, 4'h1);
        wr(`REG_STATUS, 4, 4'h1);

        scenario = "external reset during hidden launch state";
        begin_access(1, `REG_CONTROL, 1, 4'h1, `RSP_OK, 0);
        check(core_state === `CORE_RESET, "reset test begins in launch RESET");
        reset_device(1, 1);
        rd(`REG_STATUS, 1);
        rd(`REG_IRQ_STATUS, 0);
        rd(`REG_IRQ_ENABLE, 0);
        rd(`IMEM_BASE, I_FIRST);
        rd(IMEM_LAST, I_LAST);
        rd(`DMEM_BASE, D_FIRST);
        rd(DMEM_LAST, D_LAST);
        rd(`IMEM_BASE + 32'h100, 32'hd00d_fade);
        rd(`DMEM_BASE + 32'h100, 32'h55aa_33cc);
        start_run();
        complete_run();
        rd(`REG_IRQ_STATUS, 1);
        wr(`REG_IRQ_STATUS, 1, 4'h1);

        scenario = "final accounting";
        @(negedge clk);
        check(!busy && !rsp_valid && req_ready && idle && !stopped && !irq,
              "no outstanding transaction or lingering side effect");
        check(accepted == consumed + aborted, "all accepted transactions consumed or explicitly reset-aborted");
        check(imem_writes == expected_imem_writes && dmem_writes == expected_dmem_writes,
              "actual BRAM writes match expected writes; no duplication");
        check(starts > 0 && stops > 0 && clears > 0 && commits > 0 && completions > 0 && aborted > 0,
              "all counted event classes exercised");
        $display("[PASS] tb_GPGPUControl checks=%0d cycles=%0d accepted=%0d consumed=%0d reset_aborted=%0d START=%0d STOP=%0d clear=%0d CSR_commits=%0d completions=%0d IMEM_writes=%0d DMEM_writes=%0d",
                 checks, cycles, accepted, consumed, aborted, starts, stops, clears,
                 commits, completions, imem_writes, dmem_writes);
        $finish;
    end
endmodule
