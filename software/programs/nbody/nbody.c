#include "../gpgpu_runtime.h"
#include "nbody.h"

#define CORES GPGPU_NUM_CORES

#ifdef __riscv

void main(void)
{
    unsigned int tid = gpgpu_thread_id();

    volatile int *base = (volatile int *)(uintptr_t)GPGPU_ARGS[0];

    volatile int *pos_x = base;
    volatile int *pos_y = base + CORES;
    volatile int *vel_x = base + 2 * CORES;
    volatile int *vel_y = base + 3 * CORES;

    int steps = GPGPU_ARGS[1];
    int reset = GPGPU_ARGS[2];

    int reset_mask = -nonzero_int(reset);

    int old_px = pos_x[tid];
    int old_py = pos_y[tid];
    int old_vx = vel_x[tid];
    int old_vy = vel_y[tid];

    pos_x[tid] = select_int(old_px, init_x(tid), reset_mask);
    pos_y[tid] = select_int(old_py, init_y(tid), reset_mask);
    vel_x[tid] = select_int(old_vx, init_vx(tid), reset_mask);
    vel_y[tid] = select_int(old_vy, init_vy(tid), reset_mask);

    for (int step = 0; step < steps; step++) {
        int xi = pos_x[tid];
        int yi = pos_y[tid];

        int ax = 0;
        int ay = 0;

        for (unsigned int j = 0; j < CORES; j++) {
            int xj = pos_x[j];
            int yj = pos_y[j];

            int dx = xj - xi;
            int dy = yj - yi;

            int w = force_weight(dx, dy) * body_mass(j);

            ax += sign_int(dx) * w;
            ay += sign_int(dy) * w;
        }

        int vx = vel_x[tid] + (ax >> 2);
        int vy = vel_y[tid] + (ay >> 2);

        int new_x = xi + vx;
        int new_y = yi + vy;

        vel_x[tid] = vx;
        vel_y[tid] = vy;
        pos_x[tid] = new_x;
        pos_y[tid] = new_y;
    }

    return;
}

GPGPU_START(main)

#else

#include <stdio.h>
#include <stdlib.h>

#include "nbody_reference.h"

static int pos_x[CORES];
static int pos_y[CORES];
static int vel_x[CORES];
static int vel_y[CORES];
static int next_x[CORES];
static int next_y[CORES];

static void print_csv_header(void)
{
    printf("step");

    for (unsigned int body = 0; body < CORES; body++) {
        printf(",x%u,y%u", body, body);
    }

    printf("\n");
}

static void print_csv_row(int step)
{
    printf("%d", step);

    for (unsigned int body = 0; body < CORES; body++) {
        printf(",%d,%d", pos_x[body], pos_y[body]);
    }

    printf("\n");
}

int main(int argc, char **argv)
{
    int steps = 100;

    if (argc >= 2) {
        steps = atoi(argv[1]);

        if (steps < 1) {
            steps = 1;
        }
    }

    nbody_reference_init(CORES, pos_x, pos_y, vel_x, vel_y);

    print_csv_header();

    for (int step = 1; step <= steps; step++) {
        nbody_reference_step(CORES, pos_x, pos_y, vel_x, vel_y, next_x, next_y);
        print_csv_row(step);
    }

    return 0;
}

#endif
