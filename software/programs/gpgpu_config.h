#ifndef GPGPU_CONFIG_H
#define GPGPU_CONFIG_H

/* The gpgpu CLI supplies this from architecture.num_cores for both native and
 * RISC-V builds. Keep a fallback so programs remain directly compilable. */
#ifndef GPGPU_NUM_CORES
#define GPGPU_NUM_CORES 32u
#endif

#endif /* GPGPU_CONFIG_H */