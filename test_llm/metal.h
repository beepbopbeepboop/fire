/* fire_metal.h — GPU dispatch for the inner loops, callable from plain C.
 *
 * The C side of the compiler keeps everything: allocation, control flow,
 * scalar bookkeeping, the optimizer. Only the innermost loops of a hot
 * numeric kernel are handed to Metal, through the mg_* entry points below.
 *
 * Buffers are passed as raw pointers and wrapped ZERO-COPY: on Apple
 * Silicon the CPU and the GPU share one address space, so a dispatch needs
 * no copy in either direction and the same allocation is readable by both
 * engines. That is what makes a mixed ARM/Metal program practical — a
 * kernel can hand a pointer to the next one without staging.
 *
 * Every entry point is synchronous (dispatch + wait), and every one falls
 * back to the identical scalar C loop when Metal is unavailable, so a
 * program built against this header runs anywhere.
 */
#ifndef FIRE_METAL_H
#define FIRE_METAL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Non-zero when a Metal device and all kernels are up. */
int mg_available(void);

/* The host caches the bf16 weight copy across calls; a training step that
 * overwrites the weights in place must say so. */
void mg_weights_dirty(void);

/* Device/queue/lib names, for --metal reporting. */
const char *mg_device_name(void);
int mg_compiled_kernels(void);

/* o[i] = x[i] + k * y[i] */
void mg_axpy(double *o, const double *x, const double *y, double k, int n);

/* y[r] = sum_c W[r * cols + c] * x[c]  — the Linear-layer inner loop. */
void mg_matvec(double *y, const double *W, const double *x, int rows, int cols);

/* S[j * d + i] = alpha * S[j * d + i] + k[j] * v[i] — the gated-attention
 * state update, the single hottest loop in the model. */
void mg_attn_state(double *S, double alpha, const double *k, const double *v, int d);

/* o[i] = sum_j S[j * d + i] * q[j]  — the attention read (S transposed). */
void mg_attn_read(double *o, const double *S, const double *q, int d);

/* row[i] += scale * col[i], in place. */
void mg_add_scaled(double *row, const double *col, double scale, int n);

/* bf16 variants: operands are converted to native bfloat on the host (the
 * GPU reads them as bf16, half the width), the reduction stays in float.
 * Requires the metal3.2 language version, which the host requests; falls
 * back to the f32 path if unavailable. */
void mg_matvec_bf16(double *y, const double *W, const double *x, int rows, int cols);
void mg_attn_state_bf16(double *S, double alpha, const double *k, const double *v, int d);

/* `steps` tokens x `layers` layers, ALL of the inner loops, in ONE dispatch.
 * The fused kernel keeps the sequence inside the shader, so the ~12 us
 * commit is paid once instead of once per loop. */
void mg_fused_steps(double *Y, const double *W, const double *X,
                    double *S, double alpha,
                    int steps, int layers, int d, int dff);

/* Same, choosing the split-K variant (8 threads per output row, 1024 per
 * threadgroup) when splitk is nonzero. Both compute the same function. */
void mg_fused_steps_v(double *Y, const double *W, const double *X,
                      double *S, double alpha,
                      int steps, int layers, int d, int dff, int splitk);

/* ---------------------------------------------------------------------
 * Batched dispatch — the form a real program uses.
 *
 * Measured on this machine: a no-op kernel costs ~12 us to commit but
 * ~173 us to complete, so the round trip, not the arithmetic, is the
 * whole cost at the widths a transformer layer actually uses. One wait
 * per inner loop therefore throws away 99% of the GPU; a batch issues
 * every inner loop of a step into ONE command buffer and waits once.
 *
 * The ARM side keeps all control flow — it decides which loops to issue,
 * with which pointers, in what order — and only the innermost arithmetic
 * crosses to the GPU. Usage:
 *
 *     mg_batch *b = mg_batch_begin();
 *     for (t = 0; t < steps; t++) {
 *         mg_batch_matvec(b, y, W, x, rows, cols);
 *         mg_batch_attn_state(b, S, alpha, k, v, d);
 *         mg_batch_attn_read(b, o, S, q, d);
 *     }
 *     mg_batch_end(b);            // one commit, one wait
 *
 * Every mg_batch_* call is asynchronous with respect to the CPU: the
 * results are only valid after mg_batch_end.
 * ------------------------------------------------------------------- */

typedef struct mg_batch mg_batch;

mg_batch *mg_batch_begin(void);
void mg_batch_end(mg_batch *b);
void mg_batch_abort(mg_batch *b);   /* free without submitting */
int  mg_batch_dispatches(mg_batch *b);

void mg_batch_axpy(mg_batch *b, double *o, const double *x, const double *y, double k, int n);
void mg_batch_matvec(mg_batch *b, double *y, const double *W, const double *x, int rows, int cols);
void mg_batch_attn_state(mg_batch *b, double *S, double alpha, const double *k, const double *v, int d);
void mg_batch_attn_read(mg_batch *b, double *o, const double *S, const double *q, int d);
void mg_batch_add_scaled(mg_batch *b, double *row, const double *col, double scale, int n);

/* wall-clock seconds spent inside Metal (dispatch + wait), for the
 * ARM-vs-Metal split the benchmark reports. */
double mg_gpu_seconds(void);
double mg_cpu_fallback_seconds(void);

#ifdef __cplusplus
}
#endif

#endif /* FIRE_METAL_H */
