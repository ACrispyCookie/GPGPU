## Create the GPGPU Block Design

1) IP Integrator > Create Block Design > `design_1`.

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

6) Run Design Automation Assistant.

7) Connect `processing_system7_0/FCLK_CLK0` to `GPGPU_0/clk_in` and `proc_sys_reset_0/peripheral_aresetn` to `GPGPU_0/rst`, if not connected by the assistant.

8) Click Sources > Design Sources > `design_1` > Create HDL Wrapper (all options deafult), this will create `design_1_wrapper`.

9) Set `design_1_wrapper` as Top Level Module.

![The final block design](./block-design-diagram.png)
