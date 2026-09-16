# Generate reports from an already implemented project.

source [file join [file dirname [info script]] "config.tcl"]

open_project [file join $PROJECT_DIR "$PROJECT_NAME.xpr"]
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

puts "INFO: Reports written to $REPORT_DIR"
