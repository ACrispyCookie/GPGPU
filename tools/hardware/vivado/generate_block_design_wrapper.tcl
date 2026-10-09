# Generate products and register the wrapper without rebuilding or removing the BD.
source [file join [file dirname [info script]] "common.tcl"]
open_project $PROJECT_FILE
set bd_file [get_files -quiet "${BD_NAME}.bd"]
if {[llength $bd_file] != 1} {
    error "Expected exactly one block design named ${BD_NAME}.bd; run vivado:block-design:build first"
}
open_bd_design $bd_file
validate_bd_design
generate_target all $bd_file
make_wrapper -files $bd_file -top
set wrapper_file [file join $PROJECT_DIR "$PROJECT_NAME.gen" sources_1 bd $BD_NAME hdl "${TOP_NAME}.v"]
if {![file isfile $wrapper_file]} {
    error "Expected HDL wrapper was not generated: $wrapper_file"
}
add_files -norecurse $wrapper_file
set_property top $TOP_NAME [get_filesets sources_1]
update_compile_order -fileset sources_1
close_project
puts "INFO: Generated block-design products and HDL wrapper: $wrapper_file"
