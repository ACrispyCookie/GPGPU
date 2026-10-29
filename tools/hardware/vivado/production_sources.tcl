# Production inputs are resolved from configuration (hardware.sources minus hardware.vivado.exclude)
# by the Python flow and passed in as -memory-init, -rtl-sources (compile order)
# and -header-sources. This file only validates them; it names no sources.
proc production_source_paths {memory_init rtl_sources header_sources} {
    # Put initialization data before HDL, so filesets end in an HDL source.
    set result {}
    foreach path [list $memory_init {*}$rtl_sources] {
        set path [file normalize $path]
        if {![file isfile $path]} {error "Required production source missing: $path"}
        lappend result $path
    }
    # Everything is staged flat into one src/ directory.
    set names [lmap path $result {file tail $path}]
    if {[llength [lsort -unique $names]] != [llength $names]} {
        error "Production sources must have unique file names: $names"
    }
    foreach header $header_sources {
        if {[file normalize $header] ni $result} {error "Header is not a production source: $header"}
    }
    return $result
}
