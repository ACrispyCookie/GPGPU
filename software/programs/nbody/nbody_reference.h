#ifndef nbody_reference_h
#define nbody_reference_h

#include "nbody.h"

/*
 * Sequential version of the nbody kernel, shared by the native build and the
 * Zynq ARM benchmark. Body i corresponds to GPGPU thread i; the arrays hold
 * `bodies` elements and next_x/next_y are scratch space of the same size.
 */

static inline void nbody_reference_init(unsigned int bodies,
                                        int *pos_x, int *pos_y,
                                        int *vel_x, int *vel_y)
{
    for (unsigned int tid = 0; tid < bodies; tid++) {
        pos_x[tid] = init_x(tid);
        pos_y[tid] = init_y(tid);
        vel_x[tid] = init_vx(tid);
        vel_y[tid] = init_vy(tid);
    }
}

static inline void nbody_reference_step(unsigned int bodies,
                                        int *pos_x, int *pos_y,
                                        int *vel_x, int *vel_y,
                                        int *next_x, int *next_y)
{
    for (unsigned int tid = 0; tid < bodies; tid++) {
        int xi = pos_x[tid];
        int yi = pos_y[tid];

        int ax = 0;
        int ay = 0;

        for (unsigned int j = 0; j < bodies; j++) {
            int dx = pos_x[j] - xi;
            int dy = pos_y[j] - yi;

            int w = force_weight(dx, dy) * body_mass(j);

            ax += sign_int(dx) * w;
            ay += sign_int(dy) * w;
        }

        /* Velocities are only read by their own body: update them in place. */
        vel_x[tid] += ax >> 2;
        vel_y[tid] += ay >> 2;

        next_x[tid] = xi + vel_x[tid];
        next_y[tid] = yi + vel_y[tid];
    }

    for (unsigned int tid = 0; tid < bodies; tid++) {
        pos_x[tid] = next_x[tid];
        pos_y[tid] = next_y[tid];
    }
}

#endif // nbody_reference_h
