# GPGPU programs

## Structure

Each program lives in `software/programs/<program>/` and keeps only source inputs there. A program normally provides `<program>.c` with separate native and RISC-V paths selected by `__riscv`.

```c
#ifdef __riscv
int _start(void) {
    int threadIdx_x;
    __asm__ volatile("mv %0, x31" : "=r"(threadIdx_x));

    // RISC-V kernel code
}
#else
#include <stdio.h>
int main(void) {
    // Native reference implementation
}
#endif
```

## Build

Use the task runner so compiler settings, `architecture.num_cores`, and `paths.build.root` come from the resolved configuration:

```bash
./gpgpu run software:programs:<program>:all
./gpgpu run software:programs:<program>:mem
```

Generated files are written to:

```text
<build-root>/software/programs/<program>/
├── <program>_x86
├── <program>.elf
├── <program>.map
├── <program>_dump_real.asm
├── <program>_program.asm
└── <program>_instructions.mem
```

The source directory is not used for generated artifacts. To select an external build root:

```bash
./gpgpu \
  --set paths.build.root=/workspace/gpgpu-build \
  run software:programs:<program>:all
```

The build root must not overlap the repository root or any source/config/tool
directory; unsafe values are rejected before task dispatch.

The legacy `Makefile` uses the same output layout and accepts `BUILD_ROOT` as an override, but the `gpgpu` task runner is the authoritative config-driven entry point.
