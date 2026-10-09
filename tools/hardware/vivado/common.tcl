# Shared argument parsing for the staged Vivado batch scripts.

set SCRIPT_DIR [file normalize [file dirname [info script]]]

array set options {
    -project-dir ""
    -project-name ""
    -part ""
    -bd-name ""
    -top ""
    -rtl-dir ""
    -xdc-file ""
    -bitstream-dir ""
    -platform-dir ""
    -xsa-name ""
    -export-file ""
    -num-cores ""
    -jobs ""
    -host-address-gpio ""
    -host-cmd-gpio ""
    -host-rdata-gpio ""
    -host-status-gpio ""
    -host-wdata-gpio ""
}

for {set i 0} {$i < [llength $argv]} {incr i} {
    set option [lindex $argv $i]
    if {![info exists options($option)]} {
        error "Unknown Vivado flow argument: $option"
    }
    incr i
    if {$i >= [llength $argv]} {
        error "Missing value for Vivado flow argument: $option"
    }
    set options($option) [lindex $argv $i]
}

foreach option [array names options] {
    if {$options($option) eq ""} {
        error "Required Vivado flow argument was not supplied: $option"
    }
}

set PROJECT_DIR  [file normalize $options(-project-dir)]
set PROJECT_NAME $options(-project-name)
set FPGA_PART    $options(-part)
set BD_NAME      $options(-bd-name)
set TOP_NAME     $options(-top)
set RTL_DIR      [file normalize $options(-rtl-dir)]
set XDC_FILE     [file normalize $options(-xdc-file)]
set BITSTREAM_DIR [file normalize $options(-bitstream-dir)]
set PLATFORM_DIR  [file normalize $options(-platform-dir)]
set XSA_NAME      $options(-xsa-name)
set EXPORT_FILE   [file normalize $options(-export-file)]
set NUM_CORES     $options(-num-cores)
set JOBS         $options(-jobs)
set HOST_ADDRESS_GPIO $options(-host-address-gpio)
set HOST_CMD_GPIO     $options(-host-cmd-gpio)
set HOST_RDATA_GPIO   $options(-host-rdata-gpio)
set HOST_STATUS_GPIO  $options(-host-status-gpio)
set HOST_WDATA_GPIO   $options(-host-wdata-gpio)
if {![string is integer -strict $NUM_CORES] || $NUM_CORES < 1} {
    error "-num-cores must be a positive integer, got: $NUM_CORES"
}
if {![string is integer -strict $JOBS] || $JOBS < 1} {
    error "-jobs must be a positive integer, got: $JOBS"
}

set host_addresses [list \
    $HOST_ADDRESS_GPIO \
    $HOST_CMD_GPIO \
    $HOST_RDATA_GPIO \
    $HOST_STATUS_GPIO \
    $HOST_WDATA_GPIO]
foreach address $host_addresses {
    if {![regexp {^0[xX][0-9A-Fa-f]{1,8}$} $address]} {
        error "Host-interface addresses must be 32-bit hexadecimal strings, got: $address"
    }
    scan $address %x numeric_address
    if {$numeric_address > 0xFFFFFFFF || $numeric_address % 0x10000 != 0} {
        error "Host-interface address must fit in 32 bits and be 64-KiB aligned: $address"
    }
}
if {[llength [lsort -unique $host_addresses]] != [llength $host_addresses]} {
    error "Host-interface addresses must be unique"
}

set PROJECT_FILE [file join $PROJECT_DIR "$PROJECT_NAME.xpr"]
file mkdir [file dirname $PROJECT_DIR]
file mkdir $BITSTREAM_DIR
