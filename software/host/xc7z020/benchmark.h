#ifndef GPGPU_BENCHMARK_H
#define GPGPU_BENCHMARK_H

#include "xil_types.h"

/* Upper bound on timed repetitions per benchmark command. */
#define BENCH_MAX_REPETITIONS 64U

/* Time the nbody kernel (already loaded in IMEM) against the same simulation
 * on the ARM, compare their final state and print one BENCH_RESULT line with
 * the times in xiltimer ticks (COUNTS_PER_SECOND). Returns 0 on success. */
int benchmark_nbody(u32 steps, u32 repetitions);

#endif /* GPGPU_BENCHMARK_H */
