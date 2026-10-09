# Run implementation through routing only. Bitstream generation is a later stage.

source [file join [file dirname [info script]] "common.tcl"]
set_param general.maxThreads $JOBS
open_project $PROJECT_FILE

reset_run impl_1
launch_runs impl_1 -to_step route_design -jobs $JOBS
wait_on_run impl_1

set routed_checkpoint [file join \
    $PROJECT_DIR \
    "$PROJECT_NAME.runs" \
    "impl_1" \
    "${TOP_NAME}_routed.dcp"]
if {![file isfile $routed_checkpoint]} {
    error "Implementation did not produce the routed checkpoint: $routed_checkpoint"
}

close_project
puts "INFO: Implementation completed successfully: $routed_checkpoint"
