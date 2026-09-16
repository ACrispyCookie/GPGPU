# Recreate the gpgpu_system block design.
# Assumes config.tcl has already been sourced and RTL files are already present
# in sources_1 so Vivado can discover the GPGPU module reference.

create_bd_design $BD_NAME
current_bd_design $BD_NAME

# -----------------------------------------------------------------------------
# Processing system / board interfaces
# -----------------------------------------------------------------------------
create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 processing_system7_0

# Apply ZC702 board automation to expose DDR and FIXED_IO. This captures the
# board-specific DDR/MIO preset without committing generated .bd/.xci files.
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {make_external "FIXED_IO, DDR" Master "Disable" Slave "Disable"} \
    [get_bd_cells processing_system7_0]

# Explicit settings used by the existing GUI project / host flow.
set_property -dict [list \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {42} \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_EN_CLK0_PORT {1} \
] [get_bd_cells processing_system7_0]

# -----------------------------------------------------------------------------
# User RTL module
# -----------------------------------------------------------------------------
create_bd_cell -type module -reference GPGPU GPGPU_0

# -----------------------------------------------------------------------------
# AXI GPIO host interface
# -----------------------------------------------------------------------------
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_cmd
set_property -dict [list \
    CONFIG.C_ALL_OUTPUTS {1} \
    CONFIG.C_GPIO_WIDTH {4} \
] [get_bd_cells axi_gpio_cmd]

create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_address
set_property -dict [list \
    CONFIG.C_ALL_OUTPUTS {1} \
    CONFIG.C_GPIO_WIDTH {32} \
] [get_bd_cells axi_gpio_address]

create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_wdata
set_property -dict [list \
    CONFIG.C_ALL_OUTPUTS {1} \
    CONFIG.C_GPIO_WIDTH {32} \
] [get_bd_cells axi_gpio_wdata]

create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_rdata
set_property -dict [list \
    CONFIG.C_ALL_INPUTS {1} \
    CONFIG.C_GPIO_WIDTH {32} \
] [get_bd_cells axi_gpio_rdata]

create_bd_cell -type ip -vlnv xilinx.com:ip:axi_gpio:2.0 axi_gpio_status
set_property -dict [list \
    CONFIG.C_ALL_INPUTS {1} \
    CONFIG.C_GPIO_WIDTH {5} \
] [get_bd_cells axi_gpio_status]

# One GP master from PS to five AXI-Lite GPIO peripherals.
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_smc
set_property -dict [list \
    CONFIG.NUM_SI {1} \
    CONFIG.NUM_MI {5} \
] [get_bd_cells axi_smc]

create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_ps7_0_70M

# Inline bit slicing / concatenation used by the GUI-created design.
# Vivado's inline_hdl utility blocks are not normal IP catalog cells; create
# them with -type inline_hdl, not -type ip.
create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilslice:1.0 ilslice_0
set_property -dict [list \
    CONFIG.DIN_WIDTH {4} \
    CONFIG.DIN_FROM {3} \
    CONFIG.DIN_TO {3} \
] [get_bd_cells ilslice_0]

create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilslice:1.0 ilslice_1
set_property -dict [list \
    CONFIG.DIN_WIDTH {4} \
    CONFIG.DIN_FROM {2} \
] [get_bd_cells ilslice_1]

create_bd_cell -type inline_hdl -vlnv xilinx.com:inline_hdl:ilconcat:1.0 ilconcat_0
set_property -dict [list \
    CONFIG.NUM_PORTS {5} \
] [get_bd_cells ilconcat_0]

# -----------------------------------------------------------------------------
# Clocking / reset
# -----------------------------------------------------------------------------
connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
    [get_bd_pins GPGPU_0/clk_in] \
    [get_bd_pins axi_smc/aclk] \
    [get_bd_pins axi_gpio_cmd/s_axi_aclk] \
    [get_bd_pins axi_gpio_address/s_axi_aclk] \
    [get_bd_pins axi_gpio_wdata/s_axi_aclk] \
    [get_bd_pins axi_gpio_rdata/s_axi_aclk] \
    [get_bd_pins axi_gpio_status/s_axi_aclk] \
    [get_bd_pins processing_system7_0/M_AXI_GP0_ACLK] \
    [get_bd_pins rst_ps7_0_70M/slowest_sync_clk]

connect_bd_net [get_bd_pins processing_system7_0/FCLK_RESET0_N] \
    [get_bd_pins rst_ps7_0_70M/ext_reset_in]

connect_bd_net [get_bd_pins rst_ps7_0_70M/peripheral_aresetn] \
    [get_bd_pins GPGPU_0/rst] \
    [get_bd_pins axi_smc/aresetn] \
    [get_bd_pins axi_gpio_cmd/s_axi_aresetn] \
    [get_bd_pins axi_gpio_address/s_axi_aresetn] \
    [get_bd_pins axi_gpio_wdata/s_axi_aresetn] \
    [get_bd_pins axi_gpio_rdata/s_axi_aresetn] \
    [get_bd_pins axi_gpio_status/s_axi_aresetn]

# -----------------------------------------------------------------------------
# AXI interconnect
# -----------------------------------------------------------------------------
connect_bd_intf_net [get_bd_intf_pins processing_system7_0/M_AXI_GP0] \
    [get_bd_intf_pins axi_smc/S00_AXI]

connect_bd_intf_net [get_bd_intf_pins axi_smc/M00_AXI] [get_bd_intf_pins axi_gpio_address/S_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_smc/M01_AXI] [get_bd_intf_pins axi_gpio_cmd/S_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_smc/M02_AXI] [get_bd_intf_pins axi_gpio_rdata/S_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_smc/M03_AXI] [get_bd_intf_pins axi_gpio_status/S_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_smc/M04_AXI] [get_bd_intf_pins axi_gpio_wdata/S_AXI]

# -----------------------------------------------------------------------------
# GPIO <-> GPGPU host command/data/status wiring
# -----------------------------------------------------------------------------
connect_bd_net [get_bd_pins axi_gpio_address/gpio_io_o] [get_bd_pins GPGPU_0/i_host_address]
connect_bd_net [get_bd_pins axi_gpio_wdata/gpio_io_o]   [get_bd_pins GPGPU_0/i_host_wdata]
connect_bd_net [get_bd_pins GPGPU_0/o_host_rdata]       [get_bd_pins axi_gpio_rdata/gpio_io_i]

connect_bd_net [get_bd_pins axi_gpio_cmd/gpio_io_o] [get_bd_pins ilslice_0/Din]
connect_bd_net [get_bd_pins axi_gpio_cmd/gpio_io_o] [get_bd_pins ilslice_1/Din]
connect_bd_net [get_bd_pins ilslice_0/Dout] [get_bd_pins GPGPU_0/i_host_command_valid]
connect_bd_net [get_bd_pins ilslice_1/Dout] [get_bd_pins GPGPU_0/i_host_command]

connect_bd_net [get_bd_pins GPGPU_0/o_loading]   [get_bd_pins ilconcat_0/In0]
connect_bd_net [get_bd_pins GPGPU_0/o_running]   [get_bd_pins ilconcat_0/In1]
connect_bd_net [get_bd_pins GPGPU_0/o_dumping]   [get_bd_pins ilconcat_0/In2]
connect_bd_net [get_bd_pins GPGPU_0/o_host_busy] [get_bd_pins ilconcat_0/In3]
connect_bd_net [get_bd_pins GPGPU_0/o_host_done] [get_bd_pins ilconcat_0/In4]
connect_bd_net [get_bd_pins ilconcat_0/dout] [get_bd_pins axi_gpio_status/gpio_io_i]

# LED/debug status outputs that are constrained in hardware/vivado/constraints/zc702_debug.xdc.
# Create these top-level BD ports explicitly instead of relying on
# make_bd_pins_external's version-dependent auto-naming.
create_bd_port -dir O o_loading_0
create_bd_port -dir O o_running_0
create_bd_port -dir O o_dumping_0

connect_bd_net [get_bd_pins GPGPU_0/o_loading] [get_bd_ports o_loading_0]
connect_bd_net [get_bd_pins GPGPU_0/o_running] [get_bd_ports o_running_0]
connect_bd_net [get_bd_pins GPGPU_0/o_dumping] [get_bd_ports o_dumping_0]

# -----------------------------------------------------------------------------
# AXI address map. These addresses match software/host/baremetal/gpgpu_host.c.
# -----------------------------------------------------------------------------
assign_bd_address

set_property offset 0x41200000 [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_gpio_address_Reg}]
set_property range  64K        [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_gpio_address_Reg}]

set_property offset 0x41210000 [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_gpio_cmd_Reg}]
set_property range  64K        [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_gpio_cmd_Reg}]

set_property offset 0x41220000 [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_gpio_rdata_Reg}]
set_property range  64K        [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_gpio_rdata_Reg}]

set_property offset 0x41230000 [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_gpio_status_Reg}]
set_property range  64K        [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_gpio_status_Reg}]

set_property offset 0x41240000 [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_gpio_wdata_Reg}]
set_property range  64K        [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_gpio_wdata_Reg}]

validate_bd_design
save_bd_design
