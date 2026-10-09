# Build-owned settings override snapshots while preserving every other GUI edit.
proc bd_range_bytes {value} {
    # Vivado may report RANGE as 64K rather than a hexadecimal integer.
    if {[string is entier -strict $value]} {
        return [expr {wide($value)}]
    }
    if {[regexp -nocase {^([0-9]+)([KMG])$} $value -> amount unit]} {
        set shift [dict get {K 10 M 20 G 30} [string toupper $unit]]
        return [expr {wide($amount) << $shift}]
    }
    error "Unrecognized BD address range: $value"
}

proc configure_block_design {} {
    global NUM_CORES HOST_ADDRESS_GPIO HOST_CMD_GPIO HOST_RDATA_GPIO HOST_STATUS_GPIO HOST_WDATA_GPIO
    set changed 0
    set gpgpu_cell [get_bd_cells -quiet GPGPU_0]
    if {[llength $gpgpu_cell] != 1} {
        error "Expected exactly one GPGPU module-reference cell named GPGPU_0"
    }
    if {[get_property CONFIG.SP_PER_SM $gpgpu_cell] ne $NUM_CORES} {
        set_property CONFIG.SP_PER_SM $NUM_CORES $gpgpu_cell
        set changed 1
    }
    set host_address_space [get_bd_addr_spaces -quiet processing_system7_0/Data]
    if {[llength $host_address_space] != 1} {
        error "Expected processing_system7_0/Data address space"
    }
    set host_address_map [list \
        [list axi_gpio_address/S_AXI/Reg $HOST_ADDRESS_GPIO] \
        [list axi_gpio_cmd/S_AXI/Reg $HOST_CMD_GPIO] \
        [list axi_gpio_rdata/S_AXI/Reg $HOST_RDATA_GPIO] \
        [list axi_gpio_status/S_AXI/Reg $HOST_STATUS_GPIO] \
        [list axi_gpio_wdata/S_AXI/Reg $HOST_WDATA_GPIO]]
    foreach mapping $host_address_map {
        lassign $mapping segment_name offset
        set segment [get_bd_addr_segs -quiet $segment_name]
        if {[llength $segment] != 1} {
            error "Expected AXI host-interface segment: $segment_name"
        }
        set cell_name [lindex [split $segment_name /] 0]
        set mapped [get_bd_addr_segs -quiet "${host_address_space}/SEG_${cell_name}_Reg"]
        if {[llength $mapped] != 1 ||
            [get_property OFFSET $mapped] != $offset ||
            [bd_range_bytes [get_property RANGE $mapped]] != 0x00010000} {
            assign_bd_address -offset $offset -range 0x00010000 \
                -target_address_space $host_address_space $segment -force
            set changed 1
        }
    }
    return $changed
}
