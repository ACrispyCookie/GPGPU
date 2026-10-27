module DataMemorySubsystem #(
    .SP_PER_SM(SP_PER_SM)
) (
    input  logic clk,
    input  logic rst,

    input  logic abort,
    output logic idle,

    MemorySubsystemInterface.responder memory_bus
);
    import MemorySubsystemPkg::*;

    
endmodule
