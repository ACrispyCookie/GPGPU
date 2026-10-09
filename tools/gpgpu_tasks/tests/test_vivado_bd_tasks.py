from pathlib import Path

import pytest

from tools.gpgpu_tasks.tests.test_vivado_tasks import invoke, make_repo, tasks_by_name
from tools.hardware.vivado import tasks as vivado


@pytest.mark.parametrize("orphan_name", ["gpgpu_block_design", "design_1"])
def test_project_refuses_to_delete_orphan_bd_without_project(tmp_path, orphan_name):
    tasks = tasks_by_name(make_repo(tmp_path))
    project = Path(tasks["vivado:project"]["targets"][0])
    orphan = project.parent / f"GPU.srcs/sources_1/bd/{orphan_name}/{orphan_name}.bd"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("irreplaceable")
    with pytest.raises(RuntimeError, match=r"\.bd"):
        invoke(tasks["vivado:project"])
    assert orphan.read_text() == "irreplaceable"


def test_project_refuses_mismatched_bd_anywhere_in_managed_project(tmp_path):
    tasks = tasks_by_name(make_repo(tmp_path))
    project = Path(tasks["vivado:project"]["targets"][0])
    other = project.parent / "old_project.srcs/sources_1/bd/design_1/design_1.bd"
    other.parent.mkdir(parents=True)
    other.write_text("saved mismatched design")
    project.write_text("project")
    with pytest.raises(RuntimeError, match="design_1.bd"):
        invoke(tasks["vivado:project"])
    assert other.read_text() == "saved mismatched design"


def test_export_driver_validates_live_design_before_writing():
    source = (
        Path(__file__).resolve().parents[3]
        / "tools/hardware/vivado/export_block_design.tcl"
    ).read_text()
    assert source.index("validate_bd_design") < source.index("write_bd_tcl -force")


def test_configuration_helper_is_a_real_build_input(tmp_path):
    tasks = tasks_by_name(make_repo(tmp_path))
    assert (
        str(tmp_path / "tools/hardware/vivado/configure_block_design.tcl")
        in tasks["vivado:block-design:build"]["file_dep"]
    )


def test_wrapper_task_validates_promised_output(tmp_path, monkeypatch):
    tasks = tasks_by_name(make_repo(tmp_path))
    monkeypatch.setattr(vivado.subprocess, "run", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="wrapper"):
        invoke(tasks["vivado:block-design:run"])


def tcl_stage(tmp_path, stage, *, warm=True, cores=8, range_value="0x00010000"):
    tkinter = pytest.importorskip(
        "tkinter", reason="Tcl stub checks need Python Tcl support"
    )
    config = make_repo(tmp_path)
    task = tasks_by_name(config)[stage]
    args = task["actions"][0][1][0][6:]
    script_root = Path(__file__).resolve().parents[3] / "tools/hardware/vivado"
    script_name = Path(task["actions"][0][1][0][4]).name
    interpreter = tkinter.Tcl()
    interpreter.setvar("argv", tuple(args))
    interpreter.setvar("design_exists", int(warm))
    interpreter.setvar("actual_cores", cores)
    interpreter.setvar("range_value", range_value)
    interpreter.eval("""
        set saved 0; set assignments 0; set bootstraps 0; set wrappers 0
        proc open_project {args} {}
        proc close_project {} {}
        proc open_bd_design {args} {}
        proc validate_bd_design {} {}
        proc save_bd_design {} {incr ::saved}
        proc get_files {args} {
            if {$::design_exists} {return [list "$::BD_NAME.bd"]}
            return {}
        }
        proc get_bd_cells {args} {return GPGPU_0}
        proc get_bd_addr_spaces {args} {return processing_system7_0/Data}
        proc get_bd_addr_segs {args} {return [lindex $args end]}
        proc get_property {key object} {
            if {$key eq "CONFIG.SP_PER_SM"} {return $::actual_cores}
            if {$key eq "RANGE"} {return $::range_value}
            foreach {cell variable} {
                axi_gpio_address HOST_ADDRESS_GPIO axi_gpio_cmd HOST_CMD_GPIO
                axi_gpio_rdata HOST_RDATA_GPIO axi_gpio_status HOST_STATUS_GPIO
                axi_gpio_wdata HOST_WDATA_GPIO
            } {
                if {[string match "*/SEG_${cell}_Reg" $object]} {return [set ::$variable]}
            }
            error "Unexpected property: $key $object"
        }
        proc set_property {args} {set ::property $args}
        proc assign_bd_address {args} {incr ::assignments}
        proc generate_target {args} {}
        proc make_wrapper {args} {
            incr ::wrappers
            set path [file join $::PROJECT_DIR "$::PROJECT_NAME.gen" sources_1 bd $::BD_NAME hdl "$::TOP_NAME.v"]
            file mkdir [file dirname $path]
            close [open $path w]
        }
        proc add_files {args} {}
        proc get_filesets {args} {return sources_1}
        proc update_compile_order {args} {}
        rename source original_source
        proc source {path} {
            if {[file tail $path] eq "create_block_design.tcl"} {
                incr ::bootstraps; set ::design_exists 1
                return
            }
            uplevel 1 [list original_source $path]
        }
    """)
    interpreter.call("source", str(script_root / script_name))
    return interpreter


@pytest.mark.parametrize("range_value", ["64K", "0x00010000", "65536"])
def test_warm_bd_keeps_gui_state_and_does_not_save_unchanged_settings(
    tmp_path, range_value
):
    interpreter = tcl_stage(
        tmp_path, "vivado:block-design:build", range_value=range_value
    )
    assert interpreter.eval("set bootstraps") == "0"
    assert interpreter.eval("set saved") == "0"
    assert interpreter.eval("set assignments") == "0"


def test_cold_bd_sources_template_and_applies_requested_core_count(tmp_path):
    interpreter = tcl_stage(tmp_path, "vivado:block-design:build", warm=False, cores=24)
    assert interpreter.eval("set bootstraps") == "1"
    assert interpreter.eval("set saved") == "1"
    assert interpreter.splitlist(interpreter.eval("set property")) == (
        "CONFIG.SP_PER_SM",
        "8",
        "GPGPU_0",
    )


def test_wrapper_only_generates_products_and_registers_top(tmp_path):
    interpreter = tcl_stage(tmp_path, "vivado:block-design:run")
    assert interpreter.eval("set bootstraps") == "0"
    assert interpreter.eval("set saved") == "0"
    assert interpreter.eval("set wrappers") == "1"
    assert interpreter.splitlist(interpreter.eval("set property")) == (
        "top",
        "gpgpu_block_design_wrapper",
        "sources_1",
    )
