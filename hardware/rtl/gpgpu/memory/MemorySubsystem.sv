module MemorySubsystem #(
    parameter int unsigned N = 32
) (
    input logic clk,
    input logic rst,
    input logic abort,

    MemorySubsystemInterface.responder memory_bus [N]
);

endmodule
