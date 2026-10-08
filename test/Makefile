# Default target
all: testsuite

# ==============================================================================
# CONFIGURATION
# ==============================================================================

# Default testbench
TB ?= tb_GPGPU.sv

# Output executable
OUT ?= main

# Include/source directories
SRC_DIR := ../hw/gpgpu

VERILOG_SOURCES := \
	$(SRC_DIR)/*.svh \
	$(SRC_DIR)/*.sv \
	$(SRC_DIR)/control/*.sv \
	$(SRC_DIR)/memory/*.sv \
	$(SRC_DIR)/sp/*.sv

IVERILOG_FLAGS := -g2012 -Wall -Wno-timescale -Winfloop -I $(SRC_DIR)

UART_PORT ?= /dev/ttyACM0
UART_BAUD ?= 115200

# ==============================================================================
# MODULAR TEST SUITE PIPELINE
# ==============================================================================

testsuite: assemble expected simulate

gen: assemble expected

assemble:
	python3 assembler.py

expected:
	python3 expected_generator.py

compile:
	@echo "Compiling testbench: $(TB)"
	iverilog $(IVERILOG_FLAGS) $(EXTRA_FLAGS) -o $(OUT) $(TB) $(VERILOG_SOURCES)

simulate: compile
	vvp ./main | tee simulation.log
	@if grep -qE "\[FAIL\]|\[Error\]" simulation.log; then \
		exit 1; \
	fi

host: gen
	python3 host_uart_tester.py --port $(UART_PORT) --baud $(UART_BAUD)

# ==============================================================================
# UTILITY TARGETS
# ==============================================================================

visualize:
	open http://0.0.0.0:8000/visualizer.html
	python3 -m http.server

clean:
	rm -f ./tests/test*/program.mem
	rm -f ./tests/test*/trace.csv
	rm -f ./tests/test*/data.mem          
	rm -f ./tests/test*/regfile_c*.mem    
	rm -f ./main
	rm -f ./dumpfile.vcd
	rm -f ./*.log
	rm -f ./*.jou