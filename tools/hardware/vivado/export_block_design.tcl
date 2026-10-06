# Export the current editable block design to raw Vivado Tcl.
# Python post-processing compares and publishes the portable committed version.

source [file join [file dirname [info script]] "common.tcl"]

if {![file isfile $PROJECT_FILE]} {
    error "Vivado project does not exist: $PROJECT_FILE. Run vivado:project first."
}

open_project $PROJECT_FILE
set bd_file [get_files -quiet "${BD_NAME}.bd"]
if {[llength $bd_file] != 1} {
    error "Expected exactly one block design named ${BD_NAME}.bd"
}

open_bd_design $bd_file
set gpgpu_cell [get_bd_cells -quiet GPGPU_0]
if {[llength $gpgpu_cell] != 1} {
    error "Refusing to export incomplete block design: missing GPGPU_0. The committed Tcl has not been changed."
}
validate_bd_design
file mkdir [file dirname $EXPORT_FILE]
write_bd_tcl -force $EXPORT_FILE
close_project

puts "INFO: Exported raw block-design Tcl: $EXPORT_FILE"
