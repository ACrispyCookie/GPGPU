interface MemorySubsystemInterface #(
    parameter int N = 32
);

    import MemorySubsystemPkg::*;

    // Per-lane request handshakes
    logic [N-1:0] req_valid;
    logic [N-1:0] req_ready;
    mem_req_t req [N];

    // One response for the completed batch
    logic [N-1:0] rsp_valid;
    logic [N-1:0] rsp_ready;
    // logic [N-1:0] rsp_mask;
    mem_rsp_t rsp [N];

    modport requester (
        output req_valid,
        output req,
        output rsp_ready,

        input req_ready,
        input rsp_valid,
        input rsp_mask,
        input rsp
    );

    modport responder (
        input req_valid,
        input req,
        input rsp_ready,

        output req_ready,
        output rsp_valid,
        output rsp_mask,
        output rsp
    );

endinterface
