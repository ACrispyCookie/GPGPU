package MemorySubsystemPkg;

    typedef enum logic [2:0] {
        MEM_OK         = 3'd0,
        MEM_OUT_BOUNDS = 3'd1,
        MEM_AXI_ERROR  = 3'd2,
        MEM_PERMISSION = 3'd3,
        MEM_MISALIGNED = 3'd4,
        MEM_ABORTED    = 3'd5
    } mem_fault_t;

    typedef struct packed {
        logic        write;
        logic [31:0] addr;
        logic [31:0] wdata;
        // logic [3:0]  wstrb; // for future use
    } mem_req_t;

    typedef struct packed {
        logic [31:0] rdata;
        mem_fault_t  fault;
    } mem_rsp_t;

endpackage
