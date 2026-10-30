#include "benchmark.h"
#include "gpgpu_driver.h"

#include "xil_printf.h"
#include "xparameters.h"
#include "xiltimer.h"
#include "xtimer_config.h" /* COUNTS_PER_SECOND */

#include "../../programs/nbody/nbody_reference.h"

/* nbody kernel ABI (software/programs/gpgpu.ld, nbody/fpga.py): GPGPU_ARGS at
 * DMEM words 16..19 = {state base (bytes), steps, reset, 0}; the state is
 * pos_x, pos_y, vel_x, vel_y with one word per body, from the base. */
#define NBODY_ARGS_WORD   16U
#define NBODY_STATE_BYTES 0x1000U
#define NBODY_STATE_WORD  (NBODY_STATE_BYTES / 4U)
/* The state must end below the per-lane stacks at DMEM word 1536. */
#define NBODY_MAX_BODIES  128U
/* Written over the state before every GPGPU run, so a kernel that did not run
 * cannot match the ARM result with a previous run's data. */
#define NBODY_POISON      0xDEADBEEFU

static int arm_pos_x[NBODY_MAX_BODIES];
static int arm_pos_y[NBODY_MAX_BODIES];
static int arm_vel_x[NBODY_MAX_BODIES];
static int arm_vel_y[NBODY_MAX_BODIES];
static int arm_next_x[NBODY_MAX_BODIES];
static int arm_next_y[NBODY_MAX_BODIES];

static u64 gpgpu_ticks[BENCH_MAX_REPETITIONS];
static u64 arm_ticks[BENCH_MAX_REPETITIONS];

static int nbody_gpgpu_prepare(u32 bodies, u32 steps)
{
    const u32 args[4] = {NBODY_STATE_BYTES, steps, 1U, 0U};

    for (u32 i = 0U; i < 4U * bodies; i++) {
        if (gpgpu_write_dmem(NBODY_STATE_WORD + i, NBODY_POISON) != 0)
            return -1;
    }
    for (u32 i = 0U; i < 4U; i++) {
        if (gpgpu_write_dmem(NBODY_ARGS_WORD + i, args[i]) != 0)
            return -1;
    }
    return 0;
}

static int nbody_gpgpu_run(u32 bodies, u32 steps, u64 *ticks)
{
    XTime start, end;

    if (nbody_gpgpu_prepare(bodies, steps) != 0)
        return -1;
    XTime_GetTime(&start);
    if (gpgpu_start_and_wait() != 0)
        return -1;
    XTime_GetTime(&end);
    *ticks = end - start;
    return 0;
}

static void nbody_arm_run(u32 bodies, u32 steps, u64 *ticks)
{
    XTime start, end;

    /* Initialisation is timed on both sides: the kernel does it on reset. */
    XTime_GetTime(&start);
    nbody_reference_init(bodies, arm_pos_x, arm_pos_y, arm_vel_x, arm_vel_y);
    for (u32 step = 0U; step < steps; step++)
        nbody_reference_step(bodies, arm_pos_x, arm_pos_y, arm_vel_x, arm_vel_y,
                             arm_next_x, arm_next_y);
    XTime_GetTime(&end);
    *ticks = end - start;
}

/* Words of the GPGPU state that differ from the ARM state, or -1 on error. */
static int nbody_mismatches(u32 bodies)
{
    const int *expected[4] = {arm_pos_x, arm_pos_y, arm_vel_x, arm_vel_y};
    int mismatches = 0;
    u32 word;

    for (u32 array = 0U; array < 4U; array++) {
        for (u32 body = 0U; body < bodies; body++) {
            if (gpgpu_read_dmem(NBODY_STATE_WORD + array * bodies + body, &word) != 0)
                return -1;
            if (word != (u32)expected[array][body])
                mismatches++;
        }
    }
    return mismatches;
}

static void sort_ticks(u64 *values, u32 count)
{
    for (u32 i = 1U; i < count; i++) {
        const u64 value = values[i];
        u32 j = i;
        for (; j > 0U && values[j - 1U] > value; j--)
            values[j] = values[j - 1U];
        values[j] = value;
    }
}

/* xil_printf has no 64-bit conversions. */
static void print_u64(u64 value)
{
    char digits[21];
    u32 length = 0U;

    do {
        digits[length++] = (char)('0' + value % 10U);
        value /= 10U;
    } while (value != 0U);
    while (length != 0U)
        xil_printf("%c", digits[--length]);
}

static void print_statistics(const char *name, u64 *values, u32 count)
{
    sort_ticks(values, count);
    xil_printf(" %s_min=", name);
    print_u64(values[0]);
    xil_printf(" %s_median=", name);
    print_u64(values[count / 2U]);
    xil_printf(" %s_max=", name);
    print_u64(values[count - 1U]);
}

int benchmark_nbody(u32 steps, u32 repetitions)
{
    const u32 bodies = gpgpu_core_count();
    u64 warmup;
    int mismatches;

    if (steps == 0U || repetitions == 0U || repetitions > BENCH_MAX_REPETITIONS) {
        xil_printf("ERROR: bench_nbody needs steps >= 1 and 1..%u repetitions\r\n",
                   (unsigned int)BENCH_MAX_REPETITIONS);
        return -1;
    }
    if (bodies == 0U || bodies > NBODY_MAX_BODIES) {
        xil_printf("ERROR: bench_nbody supports 1..%u cores, INFO reports %u\r\n",
                   (unsigned int)NBODY_MAX_BODIES, (unsigned int)bodies);
        return -1;
    }

    /* One untimed run each warms the ARM caches and branch predictors. */
    nbody_arm_run(bodies, steps, &warmup);
    if (nbody_gpgpu_run(bodies, steps, &warmup) != 0)
        return -1;

    for (u32 i = 0U; i < repetitions; i++) {
        if (nbody_gpgpu_run(bodies, steps, &gpgpu_ticks[i]) != 0)
            return -1;
        nbody_arm_run(bodies, steps, &arm_ticks[i]);
    }

    /* Both hold the state after the last repetition. */
    mismatches = nbody_mismatches(bodies);
    if (mismatches < 0)
        return -1;

    xil_printf("BENCH_RESULT program=nbody bodies=%u steps=%u repetitions=%u timer_hz=%u cpu_hz=%u",
               (unsigned int)bodies, (unsigned int)steps, (unsigned int)repetitions,
               (unsigned int)COUNTS_PER_SECOND, (unsigned int)XPAR_CPU_CORE_CLOCK_FREQ_HZ);
    print_statistics("gpgpu", gpgpu_ticks, repetitions);
    print_statistics("arm", arm_ticks, repetitions);
    xil_printf(" mismatches=%d\r\n", mismatches);
    return 0;
}
