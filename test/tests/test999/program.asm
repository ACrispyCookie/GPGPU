# INITIALIZATION
addi x1, x0, 0  # Reserved Base Memory Pointer (Address 0)
addi x2, x0, 5
addi x3, x0, 8
addi x4, x0, 7
addi x5, x0, -1
addi x6, x0, 2
addi x7, x0, 7
addi x8, x0, -3
addi x9, x0, 10
addi x10, x0, 10
addi x11, x0, 7
addi x12, x0, -2
addi x13, x0, -1
addi x14, x0, -5
addi x15, x0, -6
addi x16, x0, -1
addi x17, x0, 6
addi x18, x0, -8
addi x19, x0, 0
addi x20, x0, 5
addi x21, x0, -3
addi x22, x0, -4
addi x23, x0, 0
addi x24, x0, 1
addi x25, x0, 8
addi x26, x0, -5
addi x27, x0, -1
addi x28, x0, 10
addi x29, x0, 5
addi x30, x0, -7

# BIASED RANDOM OPERATIONS
srl x21, x10, x2
or x26, x21, x6
or x6, x21, x26
add x5, x6, x6
slti x21, x26, 28
slli x16, x21, 30
sw x28, 12(x1)
sltiu x25, x16, -24
or x28, x25, x26

# --- EVIL SEQUENCE: STORE_LOAD ---
sw x27, 8(x1)
lw x16, 8(x1)

# --- EVIL SEQUENCE: MUL_TRAP ---
mul x26, x13, x13
addi x30, x0, 5
add x13, x26, x30
sra x6, x13, x9
and x20, x6, x5
andi x13, x20, -47
sll x28, x3, x20
sltu x24, x28, x19
lw x20, 8(x1)
sltiu x26, x14, 7
sll x12, x11, x26
sltu x16, x12, x12
add x2, x16, x16
sw x7, 16(x1)
slt x10, x3, x25
beq x10, x26, skip_0
skip_0:

# --- EVIL SEQUENCE: STORE_LOAD ---
sw x25, 0(x1)
lw x9, 0(x1)
slt x2, x17, x25
andi x12, x2, 1
sltu x29, x12, x12
beq x24, x3, skip_1
slli x24, x29, 9
sub x11, x9, x24
srl x6, x11, x11
add x27, x6, x6
slli x24, x8, 26
addi x29, x24, -1
skip_1:

# --- EVIL SEQUENCE: LOAD_USE ---
lw x29, 12(x1)
add x11, x29, x29

# --- EVIL SEQUENCE: STORE_LOAD ---
sw x19, 12(x1)
lw x12, 12(x1)
srai x3, x19, 19
sra x29, x3, x3
and x10, x29, x29
sltiu x11, x10, 0
slt x25, x12, x10
srli x19, x22, 26
sra x6, x19, x3

# KERNEL COMPLETE TRAP
jalr x0, 0(x1)
