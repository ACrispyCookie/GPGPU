# Default target
all: testsuite

SHELL := /bin/bash
.SHELLFLAGS := -o pipefail -c

# ==============================================================================
# CONFIGURATION
# ==============================================================================

TB ?= tb_GPGPU.sv
# The SMX bench's module name differs from its filename.
TOP ?= $(if $(filter tb_GPGPU.sv,$(notdir $(TB))),tb_GPGPU_smx_only,$(basename $(notdir $(TB))))
OUT ?= main
VERILATOR ?= verilator
JOBS ?= 2
PLUSARGS ?=
EXTRA_FLAGS ?=
SRC_DIR := ../hw/gpgpu
BUILD_DIR ?= $(abspath .sim/$(TOP))
SIM_EXE := $(BUILD_DIR)/$(notdir $(OUT))

# Parse the interface before consumers. Headers are included, not source units.
MEMORY_INTERFACE := $(SRC_DIR)/memory/MemoryInterface.sv
VERILOG_SOURCES := $(MEMORY_INTERFACE) $(filter-out $(MEMORY_INTERFACE),$(wildcard \
	$(SRC_DIR)/*.sv $(SRC_DIR)/control/*.sv $(SRC_DIR)/memory/*.sv $(SRC_DIR)/sp/*.sv))
# Keep existing datapath warnings visible; they must not prevent simulation.
VERILATOR_FLAGS := --binary --timing --assert --trace -Wno-fatal \
	--timescale 1ns/1ps -I$(SRC_DIR)

UART_PORT ?= /dev/ttyACM0
UART_BAUD ?= 115200

.PHONY: all testsuite gen assemble expected compile simulate host visualize clean

# ==============================================================================
# MODULAR TEST SUITE PIPELINE
# ==============================================================================

# Keep generation ordered even when the outer make uses -j.
testsuite: gen
	$(MAKE) --no-print-directory simulate

gen: assemble
	$(MAKE) --no-print-directory expected

assemble:
	python3 assembler.py

expected:
	python3 expected_generator.py

compile:
	@echo "Compiling testbench: $(TB) (Verilator, top $(TOP))"
	mkdir -p $(BUILD_DIR) $(dir $(abspath $(OUT)))
	$(VERILATOR) $(VERILATOR_FLAGS) $(EXTRA_FLAGS) --top-module $(TOP) \
		--Mdir $(BUILD_DIR) -j $(JOBS) -o $(notdir $(OUT)) $(VERILOG_SOURCES) $(TB)
	@if [[ '$(SIM_EXE)' != '$(abspath $(OUT))' ]]; then cp $(SIM_EXE) $(abspath $(OUT)); fi

simulate: compile
	$(SIM_EXE) $(PLUSARGS) | tee simulation.log
	@if grep -qiE '\[FAIL\]|\[ERROR\]|%Error|Fatal:' simulation.log; then exit 1; fi

host: gen
	python3 host_uart_tester.py --port $(UART_PORT) --baud $(UART_BAUD)

# ==============================================================================
# UTILITY TARGETS
# ==============================================================================

visualize:
	open http://0.0.0.0:8000/visualizer.html
	python3 -m http.server

clean:
	rm -f ./tests/test*/program.mem ./tests/test*/trace.csv ./tests/test*/data.mem ./tests/test*/regfile_c*.mem
	rm -f ./main ./dumpfile.vcd ./*.log ./*.jou
	rm -rf ./.sim
