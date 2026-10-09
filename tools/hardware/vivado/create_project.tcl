# Recreate only the Vivado project and register repository RTL/XDC sources.

source [file join [file dirname [info script]] "common.tcl"]

if {![file isdirectory $RTL_DIR]} {
    error "RTL directory does not exist: $RTL_DIR"
}
if {![file isfile $XDC_FILE]} {
    error "Constraint file does not exist: $XDC_FILE"
}

create_project $PROJECT_NAME $PROJECT_DIR -part $FPGA_PART -force
set_property target_language Verilog [current_project]
set_property simulator_language Mixed [current_project]
set_property default_lib xil_defaultlib [current_project]

set rtl_files [list]
foreach source_dir [list $RTL_DIR [file join $RTL_DIR "memory"] [file join $RTL_DIR "sp"]] {
    foreach file [lsort [glob -nocomplain [file join $source_dir "*.vh"]]] {
        lappend rtl_files $file
    }
    foreach file [lsort [glob -nocomplain [file join $source_dir "*.v"]]] {
        lappend rtl_files $file
    }
    foreach file [lsort [glob -nocomplain [file join $source_dir "*.sv"]]] {
        lappend rtl_files $file
    }
}
if {[llength $rtl_files] == 0} {
    error "No .vh, .v, or .sv sources found under: $RTL_DIR"
}

# Reference the checkout in place. Generated project state stays under build/.
add_files -norecurse $rtl_files
set_property include_dirs [list $RTL_DIR] [get_filesets sources_1]
add_files -fileset constrs_1 -norecurse $XDC_FILE
update_compile_order -fileset sources_1
close_project

puts "INFO: Recreated Vivado project: $PROJECT_FILE"
