# Fresh synthesis/implementation/bitstream build plus report and XSA export.
# Run after create_project.tcl, or use hardware/vivado/run.sh --bitstream.

source [file join [file dirname [info script]] "config.tcl"]

set JOBS 32
for {set i 0} {$i < [llength $argv]} {incr i} {
    set arg [lindex $argv $i]
    switch -- $arg {
        -jobs {
            incr i
            if {$i >= [llength $argv]} {
                error "Missing value for -jobs"
            }
            set JOBS [lindex $argv $i]
        }
        default {
            error "Unknown build.tcl argument: $arg"
        }
    }
}

set_param general.maxThreads $JOBS

open_project [file join $PROJECT_DIR "$PROJECT_NAME.xpr"]

# Keep run settings explicit and do not reuse incremental checkpoints.
set_property strategy "Vivado Synthesis Defaults" [get_runs synth_1]
set_property strategy "Congestion_SpreadLogic_high" [get_runs impl_1]

set_property AUTO_INCREMENTAL_CHECKPOINT 0 [get_runs synth_1]
set_property AUTO_INCREMENTAL_CHECKPOINT 0 [get_runs impl_1]
set_property STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY rebuilt [get_runs synth_1]

# Regenerate generated output products from source Tcl/BD state.
set bd_file [get_files [file join $PROJECT_DIR "$PROJECT_NAME.srcs" "sources_1" "bd" $BD_NAME "$BD_NAME.bd"]]
generate_target all $bd_file

reset_run synth_1
launch_runs synth_1 -jobs $JOBS
wait_on_run synth_1

if {[get_property PROGRESS [get_runs synth_1]] ne "100%"} {
    error "synth_1 did not complete successfully"
}

reset_run impl_1
launch_runs impl_1 -to_step write_bitstream -jobs $JOBS
wait_on_run impl_1

if {[get_property PROGRESS [get_runs impl_1]] ne "100%"} {
    error "impl_1 did not complete successfully"
}

open_run impl_1

report_timing_summary \
    -file [file join $REPORT_DIR "timing_summary.rpt"] \
    -warn_on_violation \
    -max_paths 20

report_timing \
    -file [file join $REPORT_DIR "timing_paths.rpt"] \
    -max_paths 20 \
    -sort_by group

report_utilization -file [file join $REPORT_DIR "utilization.rpt"]
report_power       -file [file join $REPORT_DIR "power.rpt"]
report_route_status -file [file join $REPORT_DIR "route_status.rpt"]

write_checkpoint -force [file join $REPORT_DIR "post_route.dcp"]

# Export hardware for Vitis/baremetal software. Command is valid for recent
# Vivado versions; if your install complains, open_hw_design/export may need
# minor version-specific adjustment.
write_hw_platform \
    -fixed \
    -include_bit \
    -force \
    -file [file join $HW_DIR "gpgpu_system.xsa"]

puts "INFO: Build complete. Reports: $REPORT_DIR"
puts "INFO: Hardware platform: [file join $HW_DIR gpgpu_system.xsa]"
