# Explicit dependency-ordered production manifest. No recursive source discovery.
# constants is an include; MemoryInterface must precede modules using modports.
set PRODUCTION_RTL_SOURCES {
    constants.svh
    memory/MemoryInterface.sv
    sp/ALU.sv
    sp/Multiplier.sv
    sp/Decoder.sv
    sp/ForwardingUnit.sv
    sp/GUCounter.sv
    sp/HazardUnit.sv
    sp/Regfile.sv
    sp/StreamingProcessor.sv
    memory/MemoryCrossbarNx2.sv
    memory/MemoryDualPort.sv
    memory/MemorySinglePort.sv
    control/CSRBank.sv
    control/ExecutionController.sv
    control/MMIOController.sv
    packages/alu_pkg.sv
    packages/control_pkg.sv
    packages/gpu_pkg.sv
    packages/pipeline_pkg.sv
    packages/riscv_pkg.sv
    StreamingMultiprocessor.sv
    GPGPU.sv
    interfaces/AXI4LiteSlave.sv
    interfaces/AXI4LiteTop.v
}
proc production_source_paths {rtl_dir script_dir} {
    global PRODUCTION_RTL_SOURCES
    # Put initialization data before HDL, so filesets end in an HDL source.
    set memory [file join $script_dir ip empty.mem]
    if {![file isfile $memory]} {error "Required memory initialization missing: $memory"}
    set result [list [file normalize $memory]]
    foreach relative $PRODUCTION_RTL_SOURCES {
        set path [file normalize [file join $rtl_dir $relative]]
        if {![file isfile $path]} {error "Required production source missing: $path"}
        lappend result $path
    }
    # Keep the basename empty.mem: RTL's default $readmemh names this file.
    return $result
}
