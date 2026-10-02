# Recreate the exported block design, generate products, and create its HDL wrapper.

source [file join [file dirname [info script]] "common.tcl"]
open_project $PROJECT_FILE

# A newer committed export must be able to replace the generated design in place.
set existing_wrapper [get_files -quiet "${TOP_NAME}.v"]
if {[llength $existing_wrapper] > 0} {
    remove_files $existing_wrapper
}

set existing_bd [get_files -quiet "${BD_NAME}.bd"]
if {[llength $existing_bd] > 0} {
    set existing_bd_dir [file dirname [lindex $existing_bd 0]]
    remove_files $existing_bd
    file delete -force $existing_bd_dir
}
file delete -force [file join \
    $PROJECT_DIR \
    "$PROJECT_NAME.gen" \
    "sources_1" \
    "bd" \
    $BD_NAME]

source [file join $SCRIPT_DIR "${BD_NAME}.tcl"]

set gpgpu_cell [get_bd_cells -quiet GPGPU_0]
if {[llength $gpgpu_cell] != 1} {
    error "Expected exactly one GPGPU module-reference cell named GPGPU_0"
}
set_property CONFIG.SP_PER_SM $NUM_CORES $gpgpu_cell
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
    assign_bd_address -offset $offset -range 0x00010000 \
        -target_address_space $host_address_space $segment -force
}
validate_bd_design
save_bd_design

set bd_file [get_files -quiet "${BD_NAME}.bd"]
if {[llength $bd_file] != 1} {
    error "Expected exactly one block design named ${BD_NAME}.bd"
}

generate_target all $bd_file
make_wrapper -files $bd_file -top

set wrapper_file [file join \
    $PROJECT_DIR \
    "$PROJECT_NAME.gen" \
    "sources_1" \
    "bd" \
    $BD_NAME \
    "hdl" \
    "${TOP_NAME}.v"]
if {![file isfile $wrapper_file]} {
    error "Expected HDL wrapper was not generated: $wrapper_file"
}

add_files -norecurse $wrapper_file
set_property top $TOP_NAME [get_filesets sources_1]
update_compile_order -fileset sources_1
close_project

puts "INFO: Recreated block design and HDL wrapper: $wrapper_file"
