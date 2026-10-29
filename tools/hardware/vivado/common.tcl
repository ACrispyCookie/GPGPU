# Runtime inputs shared by IP packaging and Zynq system stages. No workstation paths.
set SCRIPT_DIR [file normalize [file dirname [info script]]]
array set options {
    -project-dir "" -project-name "" -part "" -bd-name "" -top ""
    -memory-init "" -rtl-sources "" -header-sources "" -xdc-file "" -bitstream-dir "" -platform-dir ""
    -xsa-name "" -export-file "" -num-cores "" -jobs ""
    -repo-root "" -ip-repo-dir "" -axi-base "" -axi-range "" -flow-version "" -ip-revision 1
}
# Source lists are Tcl lists; a design may legitimately have no headers.
set optional_empty {-header-sources}
array set given {}
foreach {key value} $argv {
    if {![info exists options($key)] || ($value eq "" && $key ni $optional_empty)} {
        error "Invalid/missing Vivado argument: $key"
    }
    set options($key) $value
    set given($key) 1
}
foreach key [array names options] {
    if {![info exists given($key)] && ($options($key) eq "" || $key in $optional_empty)} {
        error "Required Vivado argument missing: $key"
    }
}
foreach {key name} {
    -project-dir PROJECT_DIR -project-name PROJECT_NAME -part FPGA_PART
    -bd-name BD_NAME -top TOP_NAME -memory-init MEMORY_INIT -rtl-sources RTL_SOURCES
    -header-sources HEADER_SOURCES -xdc-file XDC_FILE
    -bitstream-dir BITSTREAM_DIR -platform-dir PLATFORM_DIR -xsa-name XSA_NAME
    -export-file EXPORT_FILE -num-cores NUM_CORES -jobs JOBS -repo-root REPO_ROOT
    -ip-repo-dir IP_REPO_DIR -axi-base AXI_BASE -axi-range AXI_RANGE -flow-version FLOW_VERSION
    -ip-revision IP_REVISION
} {set $name $options($key)}
foreach name {PROJECT_DIR MEMORY_INIT XDC_FILE BITSTREAM_DIR PLATFORM_DIR EXPORT_FILE REPO_ROOT IP_REPO_DIR} {
    set $name [file normalize [set $name]]
}
foreach name {RTL_SOURCES HEADER_SOURCES} {
    set $name [lmap path [set $name] {file normalize $path}]
}
set PROJECT_FILE [file join $PROJECT_DIR "$PROJECT_NAME.xpr"]
foreach name {NUM_CORES JOBS IP_REVISION} {
    if {![string is integer -strict [set $name]] || [set $name] < 1} {error "$name must be positive"}
}
foreach name {AXI_BASE AXI_RANGE} {
    if {![regexp {^0[xX][0-9a-fA-F]{1,8}$} [set $name]]} {error "Invalid $name"}
}
if {$AXI_RANGE != 0x10000 || $AXI_BASE % $AXI_RANGE != 0 || $AXI_BASE + $AXI_RANGE > 0x100000000} {
    error "GPGPU AXI aperture must be 64 KiB with an aligned 32-bit base"
}
if {[string first $FLOW_VERSION [version -short]] != 0} {
    error "Vivado $FLOW_VERSION required; running [version -short]"
}
