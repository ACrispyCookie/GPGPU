#define WIDTH  16
#define HEIGHT 16

#include "../gpgpu_config.h"

#define CORES GPGPU_NUM_CORES

// ======================================================
// Input Image
// ======================================================
// Simple synthetic image:
// left half black, right half white
// produces a strong vertical edge
// ======================================================

int image[WIDTH * HEIGHT] = {
    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,
    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,
    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,
    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,

    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,
    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,
    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,
    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,

    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,
    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,
    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,
    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,

    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,
    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,
    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255,
    0,0,0,0,0,0,0,0,255,255,255,255,255,255,255,255
};

#ifdef __riscv

void main(void)
{
    unsigned int tid = gpgpu_thread_id();

    volatile int *base = (volatile int *)(uintptr_t)GPGPU_ARGS[0];

    volatile int *output = base;

    // ==================================================
    // Flattened pixel index
    // Each SP processes multiple pixels
    // ==================================================

    for (int idx = tid; idx < WIDTH * HEIGHT; idx += CORES)
    {
        int x = idx % WIDTH;
        int y = idx / WIDTH;

        // ==============================================
        // Skip borders
        // ==============================================

        if (x == 0 || x == WIDTH - 1 ||
            y == 0 || y == HEIGHT - 1)
        {
            output[idx] = 0;
            continue;
        }

        // ==============================================
        // Neighbor pixels
        // ==============================================

        int p00 = image[(y - 1) * WIDTH + (x - 1)];
        int p01 = image[(y - 1) * WIDTH + (x    )];
        int p02 = image[(y - 1) * WIDTH + (x + 1)];

        int p10 = image[(y    ) * WIDTH + (x - 1)];
        int p12 = image[(y    ) * WIDTH + (x + 1)];

        int p20 = image[(y + 1) * WIDTH + (x - 1)];
        int p21 = image[(y + 1) * WIDTH + (x    )];
        int p22 = image[(y + 1) * WIDTH + (x + 1)];

        // ==============================================
        // Sobel X
        // ==============================================

        int gx =
            (p02 + (p12 << 1) + p22)
          - (p00 + (p10 << 1) + p20);

        // ==============================================
        // Sobel Y
        // ==============================================

        int gy =
            (p20 + (p21 << 1) + p22)
          - (p00 + (p01 << 1) + p02);

        // ==============================================
        // Approximate magnitude
        // abs(gx) + abs(gy)
        // ==============================================

        if (gx < 0)
            gx = -gx;

        if (gy < 0)
            gy = -gy;

        int mag = gx + gy;

        // ==============================================
        // Clamp to 255
        // ==============================================

        if (mag > 255)
            mag = 255;

        output[idx] = mag;
    }

    return;
}

GPGPU_START(main)

#else

#include <stdio.h>

int main()
{
    for (int idx = 0;
         idx < WIDTH * HEIGHT;
         idx++)
    {
        int x = idx % WIDTH;
        int y = idx / WIDTH;

        if (x == 0 || x == WIDTH - 1 ||
            y == 0 || y == HEIGHT - 1)
        {
            output[idx] = 0;
            continue;
        }

        int p00 = image[(y - 1) * WIDTH + (x - 1)];
        int p01 = image[(y - 1) * WIDTH + (x    )];
        int p02 = image[(y - 1) * WIDTH + (x + 1)];

        int p10 = image[(y    ) * WIDTH + (x - 1)];
        int p12 = image[(y    ) * WIDTH + (x + 1)];

        int p20 = image[(y + 1) * WIDTH + (x - 1)];
        int p21 = image[(y + 1) * WIDTH + (x    )];
        int p22 = image[(y + 1) * WIDTH + (x + 1)];

        int gx =
            (p02 + (p12 << 1) + p22)
          - (p00 + (p10 << 1) + p20);

        int gy =
            (p20 + (p21 << 1) + p22)
          - (p00 + (p01 << 1) + p02);

        if (gx < 0)
            gx = -gx;

        if (gy < 0)
            gy = -gy;

        int mag = gx + gy;

        if (mag > 255)
            mag = 255;

        output[idx] = mag;
    }

    // ==============================================
    // Print output image
    // ==============================================

    for (int y = 0; y < HEIGHT; y++)
    {
        for (int x = 0; x < WIDTH; x++)
        {
            printf("%3d ", output[y * WIDTH + x]);
        }

        printf("\n");
    }

    return 0;
}

#endif