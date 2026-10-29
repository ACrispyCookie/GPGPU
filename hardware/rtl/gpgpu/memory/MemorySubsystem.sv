module MemorySubsystem #(
    parameter int unsigned N = 32
) (
    input logic clk,
    input logic rst_n,
    input logic abort,

    MemorySubsystemInterface.responder memory_bus [N],

    output logic idle
);

endmodule
