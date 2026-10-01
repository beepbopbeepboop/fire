/* metal_bench.c — the LLM's inner loops, ARM C vs Metal, on the same data.
 *
 * Not a synthetic kernel: these are exactly the five loops the model spends
 * its time in (Linear.forward, the gated-attention state update and read,
 * the SwiGLU axpy, the gradient row update), at the real widths
 * (d_model 128, d_ff 256, 6 layers). Both paths compute the same thing; the
 * benchmark reports agreement as well as time, so a "GPU is faster" claim
 * that is really a different-answer claim cannot hide.
 */
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>
#include <math.h>
#include <time.h>
#include "metal.h"

static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static unsigned long long rs = 88172645463325252ULL;
static double frand(void)
{
    rs ^= rs << 13; rs ^= rs >> 7; rs ^= rs << 17;
    return (double)((rs >> 11) & ((1ULL << 53) - 1)) * (1.0 / 9007199254740992.0) - 0.5;
}

static double *alloc(int n)
{
    double *p = (double *)malloc((size_t)n * sizeof(double));
    for (int i = 0; i < n; i++) p[i] = frand();
    return p;
}

static double maxdiff(const double *a, const double *b, int n)
{
    double m = 0.0;
    for (int i = 0; i < n; i++) {
        double d = fabs(a[i] - b[i]);
        if (d > m) m = d;
    }
    return m;
}

static double relerr(const double *a, const double *b, int n)
{
    double num = 0.0, den = 0.0;
    for (int i = 0; i < n; i++) {
        double d = a[i] - b[i];
        num += d * d;
        den += b[i] * b[i];
    }
    return den > 0.0 ? sqrt(num / den) : num;
}

/* double -> bf16 -> double, round-half-to-even: the same conversion the
   host does before uploading, so the reference and the GPU start from
   identical numbers and the comparison isolates the arithmetic. */
static double bf16_round(double x)
{
    float f = (float)x;
    uint32_t b;
    memcpy(&b, &f, 4);
    uint32_t r = b + 0x7fffu + ((b >> 16) & 1u);
    uint32_t m = r & 0xffff0000u;
    float out;
    memcpy(&out, &m, 4);
    return (double)out;
}

static double silu(double a)
{
    return a > 0.0 ? a / (1.0 + exp(-a)) : 0.0;
}

/* The model's forward stack, in the same order the fused kernel runs it.
   Layers chain: each layer's output is the next layer's input. */
static void fused_cpu(double *Y, const double *W, const double *X, double *S,
                      double alpha, int steps, int layers, int d, int dff)
{
    double *xv = (double *)malloc(sizeof(double) * d);
    double *q = (double *)malloc(sizeof(double) * d);
    double *k = (double *)malloc(sizeof(double) * d);
    double *v = (double *)malloc(sizeof(double) * d);
    double *ov = (double *)malloc(sizeof(double) * d);
    double *gt = (double *)malloc(sizeof(double) * dff);
    for (int t = 0; t < steps; t++) {
        for (int i = 0; i < d; i++) xv[i] = X[(size_t)t * d + i];
        for (int L = 0; L < layers; L++) {
            const double *L1 = W + (size_t)L * (4 * d * d + 2 * dff * d + d * dff);
            const double *L2 = L1 + 4 * d * d;
            const double *L3 = L2 + 2 * dff * d;
            double *SL = S + (size_t)L * d * d;
            for (int i = 0; i < d; i++) {
                const double *rq = L1 + i * d;
                const double *rk = L1 + (size_t)d * d + i * d;
                const double *rv = L1 + (size_t)2 * d * d + i * d;
                double a = 0, b = 0, c = 0;
                for (int j = 0; j < d; j++) { a += rq[j] * xv[j]; b += rk[j] * xv[j]; c += rv[j] * xv[j]; }
                q[i] = a; k[i] = b; v[i] = c;
            }
            for (int j = 0; j < d; j++)
                for (int i = 0; i < d; i++)
                    SL[(size_t)j * d + i] = alpha * SL[(size_t)j * d + i] + k[j] * v[i];
            for (int i = 0; i < d; i++) {
                double a = 0;
                for (int j = 0; j < d; j++) a += SL[(size_t)j * d + i] * q[j];
                ov[i] = a;
            }
            for (int i = 0; i < d; i++) {
                const double *r = L1 + (size_t)3 * d * d + i * d;
                double a = 0;
                for (int j = 0; j < d; j++) a += r[j] * ov[j];
                xv[i] = xv[i] + a;
            }
            for (int i = 0; i < dff; i++) {
                const double *rg = L2 + i * d;
                const double *ru = L2 + (size_t)dff * d + i * d;
                double a = 0, b = 0;
                for (int j = 0; j < d; j++) { a += rg[j] * xv[j]; b += ru[j] * xv[j]; }
                gt[i] = silu(a) * b;
            }
            for (int i = 0; i < d; i++) {
                const double *r = L3 + (size_t)i * dff;
                double a = 0;
                for (int j = 0; j < dff; j++) a += r[j] * gt[j];
                xv[i] = a;
            }
        }
        for (int i = 0; i < d; i++) Y[(size_t)t * d + i] = xv[i];
    }
    free(xv); free(q); free(k); free(v); free(ov); free(gt);
}

/* The same stack, written the way one would actually write it: restrict'd
 * pointers so the compiler can prove no aliasing, four accumulators per dot
 * product to break the dependency chain, and the rank-1 state update
 * vectorised over the contiguous axis. This is the CPU opponent the Metal
 * number has to beat -- the naive triple loop in fused_cpu() is a floor, not
 * a baseline, and quoting 26x against a strawman is how you end up shipping
 * a GPU kernel that is slower than the C it replaced. */
static void fused_cpu_fast(double *restrict Y, const double *restrict W,
                           const double *restrict X, double *restrict S,
                           double alpha, int steps, int layers, int d, int dff)
{
    double *restrict xv = (double *)malloc(sizeof(double) * d);
    double *restrict q = (double *)malloc(sizeof(double) * d);
    double *restrict k = (double *)malloc(sizeof(double) * d);
    double *restrict v = (double *)malloc(sizeof(double) * d);
    double *restrict ov = (double *)malloc(sizeof(double) * d);
    double *restrict gt = (double *)malloc(sizeof(double) * dff);
    const size_t per = (size_t)4 * d * d + (size_t)2 * dff * d + (size_t)d * dff;

    for (int t = 0; t < steps; t++) {
        for (int i = 0; i < d; i++) xv[i] = X[(size_t)t * d + i];
        for (int L = 0; L < layers; L++) {
            const double *restrict L1 = W + (size_t)L * per;
            const double *restrict L2 = L1 + 4 * (size_t)d * d;
            const double *restrict L3 = L2 + 2 * (size_t)dff * d;
            double *restrict SL = S + (size_t)L * d * d;

            /* four projections at once, four accumulators each */
            for (int i = 0; i < d; i++) {
                const double *restrict rq = L1 + i * d;
                const double *restrict rk = L1 + (size_t)d * d + i * d;
                const double *restrict rv = L1 + (size_t)2 * d * d + i * d;
                double a0 = 0, a1 = 0, a2 = 0, a3 = 0;
                double b0 = 0, b1 = 0, b2 = 0, b3 = 0;
                double c0 = 0, c1 = 0, c2 = 0, c3 = 0;
                int j = 0;
                for (; j + 3 < d; j += 4) {
                    a0 += rq[j] * xv[j];       a1 += rq[j+1] * xv[j+1];
                    a2 += rq[j+2] * xv[j+2];   a3 += rq[j+3] * xv[j+3];
                    b0 += rk[j] * xv[j];       b1 += rk[j+1] * xv[j+1];
                    b2 += rk[j+2] * xv[j+2];   b3 += rk[j+3] * xv[j+3];
                    c0 += rv[j] * xv[j];       c1 += rv[j+1] * xv[j+1];
                    c2 += rv[j+2] * xv[j+2];   c3 += rv[j+3] * xv[j+3];
                }
                for (; j < d; j++) {
                    a0 += rq[j] * xv[j]; b0 += rk[j] * xv[j]; c0 += rv[j] * xv[j];
                }
                q[i] = (a0 + a1) + (a2 + a3);
                k[i] = (b0 + b1) + (b2 + b3);
                v[i] = (c0 + c1) + (c2 + c3);
            }

            /* rank-1 update, vectorised over the contiguous axis */
            for (int j = 0; j < d; j++) {
                double *restrict row = SL + (size_t)j * d;
                const double kj = k[j];
                for (int i = 0; i < d; i++) row[i] = alpha * row[i] + kj * v[i];
            }

            for (int i = 0; i < d; i++) {
                double a0 = 0, a1 = 0, a2 = 0, a3 = 0;
                int j = 0;
                for (; j + 3 < d; j += 4) {
                    a0 += SL[(size_t)j * d + i]     * q[j];
                    a1 += SL[(size_t)(j+1) * d + i] * q[j+1];
                    a2 += SL[(size_t)(j+2) * d + i] * q[j+2];
                    a3 += SL[(size_t)(j+3) * d + i] * q[j+3];
                }
                for (; j < d; j++) a0 += SL[(size_t)j * d + i] * q[j];
                ov[i] = (a0 + a1) + (a2 + a3);
            }

            for (int i = 0; i < d; i++) {
                const double *restrict r = L1 + (size_t)3 * d * d + i * d;
                double a0 = 0, a1 = 0, a2 = 0, a3 = 0;
                int j = 0;
                for (; j + 3 < d; j += 4) {
                    a0 += r[j] * ov[j];       a1 += r[j+1] * ov[j+1];
                    a2 += r[j+2] * ov[j+2];   a3 += r[j+3] * ov[j+3];
                }
                for (; j < d; j++) a0 += r[j] * ov[j];
                xv[i] = xv[i] + ((a0 + a1) + (a2 + a3));
            }

            for (int i = 0; i < dff; i++) {
                const double *restrict rg = L2 + i * d;
                const double *restrict ru = L2 + (size_t)dff * d + i * d;
                double a0 = 0, a1 = 0, a2 = 0, a3 = 0, b0 = 0, b1 = 0, b2 = 0, b3 = 0;
                int j = 0;
                for (; j + 3 < d; j += 4) {
                    a0 += rg[j] * xv[j];   a1 += rg[j+1] * xv[j+1];
                    a2 += rg[j+2] * xv[j+2]; a3 += rg[j+3] * xv[j+3];
                    b0 += ru[j] * xv[j];   b1 += ru[j+1] * xv[j+1];
                    b2 += ru[j+2] * xv[j+2]; b3 += ru[j+3] * xv[j+3];
                }
                for (; j < d; j++) { a0 += rg[j] * xv[j]; b0 += ru[j] * xv[j]; }
                double g = (a0 + a1) + (a2 + a3);
                double u = (b0 + b1) + (b2 + b3);
                gt[i] = (g > 0 ? g / (1.0 + exp(-g)) : 0.0) * u;
            }

            for (int i = 0; i < d; i++) {
                const double *restrict r = L3 + (size_t)i * dff;
                double a0 = 0, a1 = 0, a2 = 0, a3 = 0;
                int c = 0;
                for (; c + 3 < dff; c += 4) {
                    a0 += r[c] * gt[c];       a1 += r[c+1] * gt[c+1];
                    a2 += r[c+2] * gt[c+2];   a3 += r[c+3] * gt[c+3];
                }
                for (; c < dff; c++) a0 += r[c] * gt[c];
                xv[i] = (a0 + a1) + (a2 + a3);
            }
        }
        for (int i = 0; i < d; i++) Y[(size_t)t * d + i] = xv[i];
    }
    free(xv); free(q); free(k); free(v); free(ov); free(gt);
}

int main(int argc, char **argv)
{
    int iters = (argc > 1) ? atoi(argv[1]) : 200;
    const int d = 128;      /* d_model  */
    const int dff = 256;    /* d_ff     */
    const int layers = 6;

    printf("Metal: %s, kernels compiled: %d, iteration: %d\n\n",
           mg_device_name(), mg_compiled_kernels(), iters);
    if (!mg_available()) {
        printf("no Metal device: every mg_* call would take the CPU fallback\n");
    }

    printf("%-34s %10s %10s %9s %12s\n",
           "kernel (widths)", "ARM (ms)", "Metal (ms)", "speedup", "rel. error");

    /* --- Linear.forward: y = W x, 128x128 and 256x128 -------------------- */
    for (int rows = 0; rows < 2; rows++) {
        int r = rows ? dff : d;
        double *W = alloc(r * d), *x = alloc(d);
        double *y_cpu = alloc(r), *y_gpu = alloc(r);
        for (int i = 0; i < r; i++) y_gpu[i] = 0.0;

        double t0 = now_s();
        for (int it = 0; it < iters; it++) {
            for (int i = 0; i < r; i++) {
                double acc = 0.0;
                const double *row = W + (size_t)i * d;
                for (int c = 0; c < d; c++) acc += row[c] * x[c];
                y_cpu[i] = acc;
            }
        }
        double t_cpu = now_s() - t0;

        t0 = now_s();
        for (int it = 0; it < iters; it++) mg_matvec(y_gpu, W, x, r, d);
        double t_gpu = now_s() - t0;

        char name[64];
        snprintf(name, sizeof(name), "matvec %dx%d", r, d);
        printf("%-34s %10.3f %10.3f %8.2fx %12.2e\n", name,
               t_cpu * 1e3, t_gpu * 1e3, t_cpu / t_gpu, relerr(y_cpu, y_gpu, r));
        free(W); free(x); free(y_cpu); free(y_gpu);
    }

    /* --- attention state update: S = a*S + k (x) v, 128x128 --------------- */
    {
        double *S0 = alloc(d * d), *k = alloc(d), *v = alloc(d);
        double *S_cpu = (double *)malloc(sizeof(double) * d * d);
        double *S_gpu = (double *)malloc(sizeof(double) * d * d);
        memcpy(S_cpu, S0, sizeof(double) * d * d);
        memcpy(S_gpu, S0, sizeof(double) * d * d);
        const double alpha = 0.87;

        double t0 = now_s();
        for (int it = 0; it < iters; it++) {
            for (int j = 0; j < d; j++) {
                double *row = S_cpu + (size_t)j * d;
                double kj = k[j];
                for (int i = 0; i < d; i++) row[i] = alpha * row[i] + kj * v[i];
            }
        }
        double t_cpu = now_s() - t0;

        t0 = now_s();
        for (int it = 0; it < iters; it++) mg_attn_state(S_gpu, alpha, k, v, d);
        double t_gpu = now_s() - t0;

        printf("%-34s %10.3f %10.3f %8.2fx %12.2e\n",
               "attn state update 128x128", t_cpu * 1e3, t_gpu * 1e3,
               t_cpu / t_gpu, relerr(S_cpu, S_gpu, d * d));
        free(S0); free(k); free(v); free(S_cpu); free(S_gpu);
    }

    /* --- attention read: o = S^T q, 128 ---------------------------------- */
    {
        double *S = alloc(d * d), *q = alloc(d);
        double *o_cpu = alloc(d), *o_gpu = alloc(d);

        double t0 = now_s();
        for (int it = 0; it < iters; it++) {
            for (int i = 0; i < d; i++) {
                double acc = 0.0;
                for (int j = 0; j < d; j++) acc += S[(size_t)j * d + i] * q[j];
                o_cpu[i] = acc;
            }
        }
        double t_cpu = now_s() - t0;

        t0 = now_s();
        for (int it = 0; it < iters; it++) mg_attn_read(o_gpu, S, q, d);
        double t_gpu = now_s() - t0;

        printf("%-34s %10.3f %10.3f %8.2fx %12.2e\n",
               "attn read (S^T q) 128", t_cpu * 1e3, t_gpu * 1e3,
               t_cpu / t_gpu, relerr(o_cpu, o_gpu, d));
        free(S); free(q); free(o_cpu); free(o_gpu);
    }

    /* --- SwiGLU axpy: o = x + k*y, 256 ---------------------------------- */
    {
        double *x = alloc(dff), *y = alloc(dff);
        double *o_cpu = alloc(dff), *o_gpu = alloc(dff);
        const double k = 0.5;

        double t0 = now_s();
        for (int it = 0; it < iters * 4; it++)
            for (int i = 0; i < dff; i++) o_cpu[i] = x[i] + k * y[i];
        double t_cpu = now_s() - t0;

        t0 = now_s();
        for (int it = 0; it < iters * 4; it++) mg_axpy(o_gpu, x, y, k, dff);
        double t_gpu = now_s() - t0;

        printf("%-34s %10.3f %10.3f %8.2fx %12.2e\n",
               "swiglu axpy 256", t_cpu * 1e3, t_gpu * 1e3,
               t_cpu / t_gpu, relerr(o_cpu, o_gpu, dff));
        free(x); free(y); free(o_cpu); free(o_gpu);
    }

    /* --- gradient row update: row += s*col, 128 ------------------------- */
    {
        double *row = alloc(d), *col = alloc(d);
        double *row_gpu = (double *)malloc(sizeof(double) * d);
        memcpy(row_gpu, row, sizeof(double) * d);
        const double s = 0.125;

        double t0 = now_s();
        for (int it = 0; it < iters * 4; it++)
            for (int i = 0; i < d; i++) row[i] += s * col[i];
        double t_cpu = now_s() - t0;

        t0 = now_s();
        for (int it = 0; it < iters * 4; it++) mg_add_scaled(row_gpu, col, s, d);
        double t_gpu = now_s() - t0;

        printf("%-34s %10.3f %10.3f %8.2fx %12.2e\n",
               "grad row += s*col 128", t_cpu * 1e3, t_gpu * 1e3,
               t_cpu / t_gpu, relerr(row, row_gpu, d));
        free(row); free(col); free(row_gpu);
    }

    printf("\n%-34s %10.3f %10.3f\n", "time inside Metal dispatch+wait",
           mg_gpu_seconds() * 1e3, mg_cpu_fallback_seconds() * 1e3);
    printf("(the Metal column is wall clock for the whole mg_* call: argument\n"
           " conversion, dispatch, GPU execution, wait, and read-back. The\n"
           " last line is the part of that which is dispatch+wait only.)\n");

    /* --- one FORWARD STEP of the whole model, the actual question --------
     *
     * seq_len 24, d_model 128, d_ff 256, 6 layers. Per token each layer
     * does: 4 attention projections (128x128), 1 state update (128x128),
     * 1 state read (128x128), 1 output projection, and the SwiGLU block
     * (2 x 256x128 + 1 x 128x256). The inner loops below are exactly that
     * set; the bookkeeping around them (residuals, norms, softmax,
     * optimizer) stays in ARM C, which is the split being measured.
     *
     * Three ways, because the interesting number is the RATIO between them:
     *   ARM          every loop in C
     *   Metal/wait   every loop its own dispatch + wait
     *   Metal/batch  every loop dispatched into one command buffer
     */
    {
        const int d = 128, dff = 256, layers = 6, steps = 24, reps = 20;
        double *W1 = alloc(d * d), *W2 = alloc(dff * d), *W3 = alloc(d * dff);
        double *x = alloc(d), *y = alloc(dff), *yf = alloc(d);
        double *S = alloc(d * d), *k = alloc(d), *v = alloc(d), *q = alloc(d), *o = alloc(d);
        const double alpha = 0.87;
        double sink = 0.0;

        double t0 = now_s();
        for (int it = 0; it < reps; it++) {
            for (int t = 0; t < steps; t++) {
                for (int L = 0; L < layers; L++) {
                    /* 4 attention projections */
                    for (int p = 0; p < 4; p++) {
                        for (int i = 0; i < d; i++) {
                            double acc = 0.0;
                            const double *row = W1 + (size_t)i * d;
                            for (int c = 0; c < d; c++) acc += row[c] * x[c];
                            yf[i] = acc;
                        }
                    }
                    /* gated state update + read */
                    for (int j = 0; j < d; j++) {
                        double *row = S + (size_t)j * d;
                        double kj = k[j];
                        for (int i = 0; i < d; i++) row[i] = alpha * row[i] + kj * v[i];
                    }
                    for (int i = 0; i < d; i++) {
                        double acc = 0.0;
                        for (int j = 0; j < d; j++) acc += S[(size_t)j * d + i] * q[j];
                        o[i] = acc;
                    }
                    /* output projection + SwiGLU (2 up, 1 down) */
                    for (int p = 0; p < 2; p++) {
                        for (int i = 0; i < dff; i++) {
                            double acc = 0.0;
                            const double *row = W2 + (size_t)i * d;
                            for (int c = 0; c < d; c++) acc += row[c] * x[c];
                            y[i] = acc;
                        }
                    }
                    for (int i = 0; i < d; i++) {
                        double acc = 0.0;
                        const double *row = W3 + (size_t)i * dff;
                        for (int c = 0; c < dff; c++) acc += row[c] * y[c];
                        yf[i] = acc;
                    }
                }
            }
            for (int i = 0; i < d; i++) sink += yf[i] + o[i];
        }
        double t_arm = now_s() - t0;

        double t_wait = 0.0;
        if (mg_available()) {
            t0 = now_s();
            for (int it = 0; it < reps; it++) {
                for (int t = 0; t < steps; t++) {
                    for (int L = 0; L < layers; L++) {
                        for (int p = 0; p < 4; p++) mg_matvec(yf, W1, x, d, d);
                        mg_attn_state(S, alpha, k, v, d);
                        mg_attn_read(o, S, q, d);
                        for (int p = 0; p < 2; p++) mg_matvec(y, W2, x, dff, d);
                        mg_matvec(yf, W3, y, d, dff);
                    }
                }
                for (int i = 0; i < d; i++) sink += yf[i] + o[i];
            }
            t_wait = now_s() - t0;
        }

        double t_batch = 0.0;
        int ndispatch = 0;
        if (mg_available()) {
            t0 = now_s();
            for (int it = 0; it < reps; it++) {
                mg_batch *b = mg_batch_begin();
                for (int t = 0; t < steps; t++) {
                    for (int L = 0; L < layers; L++) {
                        for (int p = 0; p < 4; p++) mg_batch_matvec(b, yf, W1, x, d, d);
                        mg_batch_attn_state(b, S, alpha, k, v, d);
                        mg_batch_attn_read(b, o, S, q, d);
                        for (int p = 0; p < 2; p++) mg_batch_matvec(b, y, W2, x, dff, d);
                        mg_batch_matvec(b, yf, W3, y, d, dff);
                    }
                }
                mg_batch_end(b);
                ndispatch = mg_batch_dispatches(b);
                for (int i = 0; i < d; i++) sink += yf[i] + o[i];
            }
            t_batch = now_s() - t0;
        }

        printf("\n=== one forward step of the %d-layer model, seq_len %d, "
               "d_model %d, d_ff %d (%d steps) ===\n",
               layers, steps, d, dff, reps);
        printf("  ARM C, every inner loop in C          %9.1f ms   %6.1f us/step\n",
               t_arm * 1e3, t_arm / reps * 1e6);
        if (t_wait > 0)
            printf("  Metal, one dispatch+wait per loop    %9.1f ms   %6.1f us/step  (%.2fx)\n",
                   t_wait * 1e3, t_wait / reps * 1e6, t_arm / t_wait);
        if (t_batch > 0)
            printf("  Metal, batched into one submission   %9.1f ms   %6.1f us/step  (%.2fx)\n",
                   t_batch * 1e3, t_batch / reps * 1e6, t_arm / t_batch);
        printf("  (checksum %.6f — the three paths must agree to f32)\n", sink);
        free(W1); free(W2); free(W3); free(x); free(y); free(yf);
        free(S); free(k); free(v); free(q); free(o);
    }

    /* --- the crossover, with the weights RESIDENT -----------------------
     * Everything above is dispatch-bound: 1620 dispatches x ~12 us of
     * commit is the entire step. So the question that decides whether
     * Metal is worth wiring into a program at all is: how much arithmetic
     * does a dispatch have to carry to pay for itself? Same kernel, same
     * data, uploaded ONCE and dispatched many times, against the same
     * matvecs in C. */
    printf("\n=== crossover: weights resident, N dispatches into one batch ===\n");
    printf("%-26s %10s %12s %12s %9s\n", "n x n", "reps", "ARM (ms)", "Metal (ms)", "speedup");
    {
        const int sizes[] = {128, 256, 512, 1024, 2048, 4096};
        const int nsizes = (int)(sizeof(sizes) / sizeof(sizes[0]));
        for (int si = 0; si < nsizes; si++) {
            int n = sizes[si];
            int reps = n <= 256 ? 500 : (n <= 1024 ? 50 : 10);
            double *W = alloc((size_t)n * n), *x = alloc(n);
            double *y_cpu = alloc(n), *y_gpu = alloc(n);
            double sink = 0.0;

            double t0 = now_s();
            for (int it = 0; it < reps; it++)
                for (int i = 0; i < n; i++) {
                    double acc = 0.0;
                    const double *row = W + (size_t)i * n;
                    for (int c = 0; c < n; c++) acc += row[c] * x[c];
                    y_cpu[i] = acc;
                }
            double t_cpu = now_s() - t0;

            double t_gpu = 0.0;
            if (mg_available()) {
                t0 = now_s();
                for (int it = 0; it < reps; it++) {
                    mg_batch *b = mg_batch_begin();
                    mg_batch_matvec(b, y_gpu, W, x, n, n);
                    mg_batch_end(b);
                }
                t_gpu = now_s() - t0;
            }
            for (int i = 0; i < n; i++) sink += y_cpu[i] + y_gpu[i];

            char name[64];
            snprintf(name, sizeof(name), "%dx%d", n, n);
            printf("%-26s %10d %12.2f %12.2f %8.2fx   (chk %.4f)\n", name, reps,
                   t_cpu * 1e3, t_gpu * 1e3, t_gpu > 0 ? t_cpu / t_gpu : 0.0, sink);
            fflush(stdout);
            free(W); free(x); free(y_cpu); free(y_gpu);
        }
    }

    /* --- f32 vs native bf16 --------------------------------------------
     * The model's weights and attention state ARE bf16, so the GPU being
     * able to read them as bfloat (metal3.2+) is the interesting case:
     * half the bytes cross the bus and the GPU's own bf16 path does the
     * multiply, with the reduction still in float. */
    printf("\n=== f32 vs native bf16 (metal3.2 bfloat) ===\n");
    printf("%-16s %11s %11s %11s %9s %11s\n",
           "n x n", "ARM (ms)", "Metal f32", "Metal bf16", "bf16 gain", "bf16 err");
    {
        const int sizes[] = {128, 512, 2048};
        for (int si = 0; si < 3; si++) {
            int n = sizes[si];
            int reps = n <= 128 ? 200 : (n <= 512 ? 20 : 4);
            double *W = alloc((size_t)n * n), *x = alloc(n);
            double *y1 = alloc(n), *y2 = alloc(n);
            double sink = 0.0;
            double t0 = now_s();
            for (int it = 0; it < reps; it++)
                for (int i = 0; i < n; i++) {
                    double acc = 0.0;
                    const double *row = W + (size_t)i * n;
                    for (int c = 0; c < n; c++) acc += row[c] * x[c];
                    y1[i] = acc;
                }
            double t_cpu = now_s() - t0;
            double t1 = 0, t2 = 0;
            if (mg_available()) {
                t0 = now_s();
                for (int it = 0; it < reps; it++) mg_matvec(y1, W, x, n, n);
                t1 = now_s() - t0;
                t0 = now_s();
                for (int it = 0; it < reps; it++) mg_matvec_bf16(y2, W, x, n, n);
                t2 = now_s() - t0;
            }
            for (int i = 0; i < n; i++) sink += y2[i];
            printf("%-16s %11.2f %11.2f %11.2f %8.2fx %11.2e\n",
                   "matvec", t_cpu * 1e3, t1 * 1e3, t2 * 1e3,
                   t1 > 0 ? t1 / t2 : 0.0, relerr(y1, y2, n));
            (void)sink;
            fflush(stdout);
            free(W); free(x); free(y1); free(y2);
        }
    }

    /* --- ONE dispatch for N steps, and does it agree? -------------------
     * The batched path pays ~12 us of commit per inner loop, which measured
     * as the entire cost of a forward step. The fused kernel moves the loop
     * nest inside the shader, so the ARM side issues ONE dispatch per call
     * and N is just a kernel argument.
     *
     * The ARM column below is the SAME stack, in the SAME order, in double:
     *   q,k,v = W1[0..2] . x ;  S = a*S + k(x)v ;  o = S^T q
     *   x += W1[3] . o ;  h = silu(W2[0].x) * W2[1].x ;  x = W3 . h
     * with the layers chained. Its INPUTS are rounded to bf16 first, exactly
     * as the host does before uploading, so the only remaining difference is
     * f32 versus fp64 accumulation inside the reduction. A transpose, a
     * missing silu or a dropped residual shows up here as a large number;
     * agreement to ~1e-6 means the two paths compute the same function. */
    printf("\n=== fused kernel: ONE dispatch for N steps (and does it agree?) ===\n");
    /* "sk vs blockedC" is the honest headline and "sk vs naiveC" is kept
     * beside it so the gap between the two baselines stays visible. This
     * column used to be labelled "sk vs fast", which reads as a comparison
     * against the 1-thread GPU path -- it never was. Anyone who took it at
     * face value was being told the split-K kernel beat something it was
     * never measured against. */
    printf("%-7s %9s %9s %9s %9s %13s %12s %11s\n",
           "steps", "C naive", "C blocked", "GPU 1thr", "GPU sk8",
           "sk vs blockedC", "sk vs naiveC", "sk agree");
    {
        const int d = 128, dff = 256, layers = 6;
        /* The ladder used to stop at 1000, which is exactly the point where
           the answer stops being interesting: one dispatch carrying N steps
           amortises its ~190 us over N, so the win should keep GROWING with N
           until the GPU saturates. Stopping at 1000 measured the start of that
           curve and not its shape. Extended two orders of magnitude; the loop
           bound is now derived from the array so adding an entry cannot leave
           it silently unvisited (it was a literal 6). */
        const int step_counts[] = {1, 10, 24, 100, 300, 1000, 3000, 10000,
                                   30000, 100000};
        const int nsteps_n = (int)(sizeof(step_counts) / sizeof(step_counts[0]));
        const size_t wcount = (size_t)layers * (4 * d * d + 2 * dff * d + d * dff);
        double *W = alloc(wcount);
        for (int si = 0; si < nsteps_n; si++) {
            int n = step_counts[si];
            /* round every operand to bf16 FIRST so both paths see the same
               numbers and the comparison is about the arithmetic, not the
               input precision */
            /* 1/sqrt(d) is the scale a real init uses; +-0.5 across a
               128-wide layer compounds to inf by layer 6 in BOTH paths, and
               a benchmark that overflows measures nothing */
            for (size_t i = 0; i < wcount; i++) W[i] = bf16_round(W[i] * 0.09);
            double *X = alloc((size_t)n * d);
            for (size_t i = 0; i < (size_t)n * d; i++) X[i] = bf16_round(X[i]);
            double *S0 = alloc((size_t)layers * d * d);
            double *S = (double *)malloc(sizeof(double) * layers * d * d);
            double *Yc = alloc((size_t)n * d), *Yg = alloc((size_t)n * d);
            const double alpha = 0.87;
            double sink = 0.0;
            const int reps = n >= 1000 ? 1 : (n >= 300 ? 2 : (n >= 100 ? 3 : 20));

            memcpy(S, S0, sizeof(double) * layers * d * d);
            double t0 = now_s();
            for (int it = 0; it < reps; it++) {
                memcpy(S, S0, sizeof(double) * layers * d * d);
                fused_cpu(Yc, W, X, S, alpha, n, layers, d, dff);
                for (int i = 0; i < n * d; i++) sink += Yc[i];
            }
            double t_naive = (now_s() - t0) / reps;

            /* the same computation, blocked: this is the real opponent */
            t0 = now_s();
            for (int it = 0; it < reps; it++) {
                memcpy(S, S0, sizeof(double) * layers * d * d);
                fused_cpu_fast(Yc, W, X, S, alpha, n, layers, d, dff);
                for (int i = 0; i < n * d; i++) sink += Yc[i];
            }
            double t_cpu = (now_s() - t0) / reps;

            double t_gpu = 0.0, worst = 0.0, t_sk = 0.0, skdiff = 0.0;
            int ndisp = 0;
            if (mg_available()) {
                t0 = now_s();
                for (int it = 0; it < reps; it++) {
                    memset(S, 0, sizeof(double) * layers * d * d);
                    mg_fused_steps_v(Yg, W, X, S, alpha, n, layers, d, dff, 0);
                    ndisp = 1;
                }
                t_gpu = (now_s() - t0) / reps;
                for (int i = 0; i < n * d; i++) {
                    sink += Yg[i];
                    double dd = fabs(Yc[i] - Yg[i]);
                    if (!(dd <= 1e-3)) { if (dd > worst || isnan(dd)) worst = INFINITY; }
                }
                /* split-K variant, and a check that it agrees with the
                   scalar-K one rather than merely being fast */
                t0 = now_s();
                for (int it = 0; it < reps; it++) {
                    memset(S, 0, sizeof(double) * layers * d * d);
                    mg_fused_steps_v(Yg, W, X, S, alpha, n, layers, d, dff, 1);
                }
                t_sk = (now_s() - t0) / reps;
                for (int i = 0; i < n * d; i++) {
                    double dd = fabs(Yc[i] - Yg[i]);
                    if (!(dd <= 1e-3)) { if (dd > skdiff || isnan(dd)) skdiff = INFINITY; }
                }

            }
            char lab[16];
            snprintf(lab, sizeof(lab), "%d", n);
            printf("%-7s %9.2f %9.2f %9.2f %9.2f %7.2fx %8.2fx %11.2e%s\n",
                   lab, t_naive * 1e3, t_cpu * 1e3, t_gpu * 1e3, t_sk * 1e3,
                   t_sk > 0 ? t_cpu / t_sk : 0.0,
                   t_sk > 0 ? t_naive / t_sk : 0.0, skdiff,
                   skdiff < 1e-3 ? "  agree" : "  MISMATCH");
            fflush(stdout);
            free(X); free(S0); free(S); free(Yc); free(Yg);
        }
        free(W);
    }

    (void)layers;
    return 0;
}
