# Default target
all: testsuite

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Default testbench
TB ?= tb_GPGPU.v

# Output executable
OUT ?= main

# Include/source directories
REPO_ROOT := $(shell git rev-parse --show-toplevel)
RTL_DIR := $(REPO_ROOT)/hardware/rtl
TEST_CASES_DIR := cases

VERILOG_SOURCES := \
	$(RTL_DIR)/*.vh \
	$(RTL_DIR)/*.v \
	$(RTL_DIR)/memory/*.v \
	$(RTL_DIR)/sp/*.v

IVERILOG_FLAGS := -Wall -Wno-timescale -Winfloop -I $(RTL_DIR)

UART_PORT ?= /dev/ttyACM0
UART_BAUD ?= 115200

# ==============================================================================
# MODULAR TEST SUITE PIPELINE
# ==============================================================================

testsuite: assemble expected simulate

gen: assemble expected

assemble:
	python3 $(REPO_ROOT)/tests/tools/assembler.py $(TEST_CASES_DIR)

expected:
	python3 $(REPO_ROOT)/tests/tools/expected_generator.py $(TEST_CASES_DIR)

compile:
	@echo "Compiling testbench: $(TB)"
	iverilog $(IVERILOG_FLAGS) -o $(OUT) $(TB) $(VERILOG_SOURCES)

simulate: compile
	vvp ./main | tee simulation.log
	@if grep -qE "\[FAIL\]|\[Error\]" simulation.log; then \
		exit 1; \
	fi

host: gen
	python3 $(REPO_ROOT)/tests/software/host/host_uart_tester.py --port $(UART_PORT) --baud $(UART_BAUD)

# ==============================================================================
# UTILITY TARGETS
# ==============================================================================

visualize:
	open http://0.0.0.0:8000/visualizer.html
	python3 -m http.server

clean:
	rm -f ./$(TEST_CASES_DIR)/test*/program.mem
	rm -f ./$(TEST_CASES_DIR)/test*/trace.csv
	rm -f ./$(TEST_CASES_DIR)/test*/data.mem
	rm -f ./$(TEST_CASES_DIR)/test*/regfile_c*.mem
	rm -f ./main
	rm -f ./dumpfile.vcd
	rm -f ./*.log
	rm -f ./*.jou
