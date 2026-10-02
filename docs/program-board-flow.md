## Create the GPGPU Block Design

1) IP Integrator > Create Block Design > `gpgpu_block_design`.

2) Add the following blocks:
- 1 x ZYNQ 7000 PS
- 5 x AXI GPIO blocks:
	- name `axi_gpio_cmd`, select All Outputs, GPIO Width: 4
	- name `axi_gpio_address`, select All Outputs, GPIO Width: 32
	- name `axi_gpio_wdata`, select All Outputs, GPIO Width: 32
	- name `axi_gpio_rdata`, select All Inputs, GPIO Width: 32
	- name `axi_gpio_status`, select All Inputs, GPIO Width: 5
- 2 x Inline Slice blocks, 
- 1 x Inline Concat
- 1 x the GPGPU RTL design (drag and drop).

3) Connect `GPGPU_0`'s wires `o_loading`, `o_running`, `o_dumping`, `o_host_busy`, `o_host_done` to the Inline Concat Block (5 inputs, 1 output), and connect its output to `axi_gpio_status/gpio_io_i`.

4) Connect `axi_gpio_cmd/gpio_io_o` output to the first Inline Slice block: Din Width 4, Din From 2, Din Down To 0, Dout Width 3, and connect the `axi_gpio_cmd/gpio_io_o` output to the second Inline Slice block: Din Width 4, Din From 3, Din Down To 3, Dout Width 1.

5) Set PS output clock frequency: double tap on PS > Clock configuration > PL Fabric Clocks > `FCLK_CLK0`, change the Requested Frequency.

6) Select DDR configuration in PS (Memory part MT41K256M16 RE-125 for hellofpga's board).

7) Select PS > MIO Configuration > I/O Peripherals > Peripheral: UART 0 and IO: EMIO.

8) Run Design Automation Assistant.

9) Connect `processing_system7_0/FCLK_CLK0` to `GPGPU_0/clk_in` and `proc_sys_reset_0/peripheral_aresetn` to `GPGPU_0/rst`, if not connected by the assistant.

10) Make the port `processing_system7_0/UART_0` external, then go to RTL Analysis > Open Elaborate Design.

11) Click Sources > Design Sources > `gpgpu_block_design` > Create HDL Wrapper (all options default), which creates `gpgpu_block_design_wrapper`.

12) Set `gpgpu_block_design_wrapper` as Top Level Module.

![The final block design](./block-design-diagram.png)

13) Generate bitstream

## Vitis Setup

1) In vivado, go to File > Export > Export Hardware, select include bitstream, but not binary, name it, for example, `gpgpu_platform.xsa`.

2) Open Vitis Tools > Launch Vitis IDE

3) Create Platform: File > New Component > Platform, select the `gpgpu_platform.xsa` file vivado generated.

4) Create ARM application: New Component > Application, name it, for example, `gpgpu_host`, select Platform > `gpgpu_platform`, in the Source Files page select add the sources and select the repo's `software/host/xc7z020/` directory.

5) Select VITIS COMPONENTS > `gpgpu_host`, FLOW > select `gpgpu_host` > Build.

6) Select VITIS COMPONENTS > `gpgpu_platform`, FLOW > select `gpgpu_platform` > Build.
