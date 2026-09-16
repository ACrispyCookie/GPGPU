# Vivado build configuration for ECE338 GPGPU.
# This file is sourced by the other Tcl scripts in this directory.

# Repository root = two levels above hardware/vivado/.
set REPO_ROOT [file normalize [file join [file dirname [info script]] ".." ".."]]

# Generated Vivado project location. Keep this under build/ so it can be deleted
# and regenerated from the committed Tcl scripts.
set PROJECT_NAME "gpgpu_vivado"
set PROJECT_DIR  [file join $REPO_ROOT "build" "hardware" "vivado" $PROJECT_NAME]

# Current GUI-created project settings observed from gpgpu_vivado.xpr.
set FPGA_PART  "xc7z020clg484-1"
set BOARD_PART "xilinx.com:zc702:part0:1.4"

set BD_NAME  "gpgpu_system"
set TOP_NAME "gpgpu_system_wrapper"

set RTL_DIR [file join $REPO_ROOT "hardware" "rtl"]
set TEST_DIR [file join $REPO_ROOT "tests" "hardware" "rtl"]
set VIVADO_DIR [file join $REPO_ROOT "hardware" "vivado"]
set CONSTRAINTS_DIR [file join $VIVADO_DIR "constraints"]
set XDC_FILE [file join $CONSTRAINTS_DIR "zc702_debug.xdc"]

set REPORT_DIR [file join $REPO_ROOT "build" "hardware" "reports"]
set HW_DIR     [file join $REPO_ROOT "build" "hardware" "hw"]

file mkdir $PROJECT_DIR
file mkdir $REPORT_DIR
file mkdir $HW_DIR
