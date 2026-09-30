/* fire_metal.metal — the inner loops of fire_metal.h, as MSL compute kernels.
 *
 * f32 throughout, and that is a LANGUAGE constraint, not a hardware one:
 * MSL has no `double` type at all (Apple Silicon's GPU does fp64 in
 * hardware; the shading language never exposed it), so a Metal inner loop
 * is f32 or f16/bf16. The ARM C path stays fp64 and is the reference the
 * benchmark compares against. For this model — bf16 weights, bf16 storage
 * — f32 on the GPU is the natural precision anyway: it is strictly finer
 * than the weights it multiplies, so a Metal result is at least as accurate
 * as the bf16 numbers the model actually holds.
 *
 * Thread indices come from the [[thread_position_in_*]] attributes, never
 * from kernel parameters: MSL does not pass them, and a kernel that declares
 * an extra `constant unsigned int &gid` binds it to whatever the NEXT buffer
 * index happens to be — which compiles clean and computes with gid == 0.
 *
 * Every kernel is shaped so one threadgroup owns one output row (or one
 * 16x16 tile of the state matrix) and its threads walk the reduction
 * dimension in strided chunks. That is the shape a tiled GEMM would use,
 * with no atomics and no second pass.
 *
 * The `mg_*_bf16_kernel` family is the same arithmetic with the DATA in
 * native bfloat and the ACCUMULATION in float. `bfloat` needs
 * -std=metal3.2 (the runtime equivalent is
 * MTLCompileOptions.languageVersion = MTLLanguageVersion3_2; the host sets
 * it), which is worth having for exactly this model: the weights and the
 * attention state ARE bf16, so the GPU can consume them in their own type
 * at half the transfer width, and the reduction still happens in float so
 * the sum is no worse than the f32 path. Below metal3.2 there is no
 * bfloat type at all — and no language version has `double`.
 */
#include <metal_stdlib>

using namespace metal;

kernel void mg_axpy_kernel(device float *o,
                           device const float *x,
                           device const float *y,
                           constant float &k,
                           constant unsigned int &n,
                           uint gid [[thread_position_in_grid]])
{
    if (gid < n) {
        o[gid] = x[gid] + k * y[gid];
    }
}

/* y[r] = sum_c W[r * cols + c] * x[c]
   one threadgroup per output row, threads stride the columns, then a tree
   reduction in threadgroup memory. */
kernel void mg_matvec_kernel(device float *y,
                             device const float *W,
                             device const float *x,
                             constant unsigned int &rows,
                             constant unsigned int &cols,
                             uint tgid_row [[threadgroup_position_in_grid]],
                             uint lid [[thread_position_in_threadgroup]])
{
    if (tgid_row >= rows) return;
    threadgroup float partial[256];
    float acc = 0.0f;
    unsigned int base = tgid_row * cols;
    for (unsigned int c = lid; c < cols; c += 256) {
        acc += W[base + c] * x[c];
    }
    partial[lid] = acc;
    threadgroup_barrier(mem_flags::mem_threadgroup);
    for (unsigned int s = 128; s > 0; s = s >> 1) {
        if (lid < s) {
            partial[lid] += partial[lid + s];
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }
    if (lid == 0) {
        y[tgid_row] = partial[0];
    }
}

/* S[j * d + i] = alpha * S[j * d + i] + k[j] * v[i]
   One 16x16 tile per threadgroup; the state is updated in place, with no
   temporary — this is the model's hottest loop and must not allocate. */
kernel void mg_attn_state_kernel(device float *S,
                                 device const float *k,
                                 device const float *v,
                                 constant float &alpha,
                                 constant unsigned int &d,
                                 uint2 p [[thread_position_in_threadgroup]],
                                 uint2 tile [[threadgroup_position_in_grid]])
{
    uint j = tile.y * 16 + p.x;
    uint i = tile.x * 16 + p.y;
    if (j >= d || i >= d) return;
    unsigned int idx = j * d + i;
    S[idx] = alpha * S[idx] + k[j] * v[i];
}

/* o[i] = sum_j S[j * d + i] * q[j]   (S read transposed) */
kernel void mg_attn_read_kernel(device float *o,
                                device const float *S,
                                device const float *q,
                                constant unsigned int &d,
                                uint gid [[thread_position_in_grid]])
{
    if (gid >= d) return;
    float acc = 0.0f;
    for (unsigned int j = 0; j < d; ++j) {
        acc += S[j * d + gid] * q[j];
    }
    o[gid] = acc;
}

kernel void mg_add_scaled_kernel(device float *row,
                                 device const float *col,
                                 constant float &scale,
                                 constant unsigned int &n,
                                 uint gid [[thread_position_in_grid]])
{
    if (gid < n) {
        row[gid] += scale * col[gid];
    }
}

/* ---- bf16 variants: data in native bfloat, accumulation in float ------ */

kernel void mg_matvec_bf16_kernel(device float *y,
                                  device const bfloat *W,
                                  device const bfloat *x,
                                  constant unsigned int &rows,
                                  constant unsigned int &cols,
                                  uint tgid_row [[threadgroup_position_in_grid]],
                                  uint lid [[thread_position_in_threadgroup]])
{
    if (tgid_row >= rows) return;
    threadgroup float partial[256];
    float acc = 0.0f;
    unsigned int base = tgid_row * cols;
    for (unsigned int c = lid; c < cols; c += 256) {
        acc += float(W[base + c]) * float(x[c]);
    }
    partial[lid] = acc;
    threadgroup_barrier(mem_flags::mem_threadgroup);
    for (unsigned int s = 128; s > 0; s = s >> 1) {
        if (lid < s) {
            partial[lid] += partial[lid + s];
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }
    if (lid == 0) {
        y[tgid_row] = partial[0];
    }
}

kernel void mg_attn_state_bf16_kernel(device bfloat *S,
                                      device const bfloat *k,
                                      device const bfloat *v,
                                      constant float &alpha,
                                      constant unsigned int &d,
                                      uint2 p [[thread_position_in_threadgroup]],
                                      uint2 tile [[threadgroup_position_in_grid]])
{
    uint j = tile.y * 16 + p.x;
    uint i = tile.x * 16 + p.y;
    if (j >= d || i >= d) return;
    unsigned int idx = j * d + i;
    S[idx] = bfloat(alpha * float(S[idx]) + float(k[j]) * float(v[i]));
}

/* ---------------------------------------------------------------------------
 * fused_step_kernel — the real forward stack for `steps` tokens, in ONE
 * dispatch.
 *
 * The batched path issues one dispatch per inner loop (~12 us of commit
 * each), and that measured as the entire cost of a forward step. Here the
 * loop nest lives inside the shader: the grid is layers*steps threadgroups,
 * each owning one (layer, token) pair and running that pair's full stack.
 *
 * Unlike the first cut of this kernel, it computes the ACTUAL model, so its
 * output can be compared against the scalar path term by term:
 *
 * The weights arrive TRANSPOSED (the host packs them that way when it
 * converts to bf16). With one thread per output row, a row-major W has the
 * 128 active threads reading addresses d floats apart, so every 32-byte
 * sector serves exactly one thread -- 16x the traffic it should be. With W
 * transposed, the same loop has the whole threadgroup walking contiguous
 * memory, which is the difference between this kernel being memory-starved
 * and not.
 *
 *   x            layer input (the previous layer's output)
 *   q,k,v        = W1[0..2] . x
 *   S            = alpha*S + k (x) v                      in place
 *   o            = S^T q
 *   attn         = W1[3] . o
 *   x            = x + attn                               (residual)
 *   gate,up      = W2[0..1] . x
 *   h            = silu(gate) * up
 *   y            = W3 . h                                 -> next layer's x
 *
 * That needs cross-thread cooperation, so unlike the single-kernel-per-loop
 * versions this one does use threadgroup memory and barriers: the vectors
 * are per-token and shared across the d rows each thread owns, so they live
 * in threadgroup memory and the layer boundaries are barrier-separated.
 * 7 * 256 floats = 7 KB, well inside the 32 KB limit.
 * ------------------------------------------------------------------------- */
kernel void fused_step_kernel(
    device const bfloat *W,
    device const bfloat *X,
    device float *S,
    device float *Y,
    constant float &alpha,
    constant unsigned int &steps,
    constant unsigned int &layers,
    constant unsigned int &d,
    constant unsigned int &dff,
    uint gid [[threadgroup_position_in_grid]],
    uint tid [[thread_position_in_threadgroup]])
{
    /* 1D grid of layers*steps threadgroups: MSL requires every non-buffer
       kernel parameter to be either all-scalar or all-vector, and mixing a
       uint2 grid index with a uint thread index is rejected. */
    const unsigned int t = gid % steps;
    const unsigned int L = gid / steps;

    threadgroup float xv[256];
    threadgroup float qv[256];
    threadgroup float kv[256];
    threadgroup float vv[256];
    threadgroup float ov[256];
    threadgroup float gate[256];
    threadgroup float up[256];

    device const bfloat *Lbase = W + (size_t)L * (4u * d * d + 2u * dff * d + d * dff);
    device const bfloat *L1 = Lbase;
    device const bfloat *L2 = L1 + 4u * d * d;
    device const bfloat *L3 = L2 + 2u * dff * d;
    device float *SL = S + (size_t)L * d * d;
    device const bfloat *x0 = X + (size_t)t * d;

    /* layer 0's input comes from the buffer; later layers chain */
    if (tid < d) xv[tid] = float(x0[tid]);
    threadgroup_barrier(mem_flags::mem_threadgroup);

    for (unsigned int lay = 0; lay < layers; ++lay) {
        device const bfloat *Wq = L1 + (size_t)0 * d * d;
        device const bfloat *Wk = L1 + (size_t)1 * d * d;
        device const bfloat *Wv = L1 + (size_t)2 * d * d;
        device const bfloat *Wo = L1 + (size_t)3 * d * d;

        /* --- q, k, v = W . x ------------------------------------------- */
        if (tid < d) {
            float a = 0.0f, b = 0.0f, c = 0.0f;
            for (unsigned int i = 0; i < d; ++i) {
                /* W^T[j][i]: the threadgroup walks a contiguous row */
                a += float(Wq[(size_t)i * d + tid]) * xv[i];
                b += float(Wk[(size_t)i * d + tid]) * xv[i];
                c += float(Wv[(size_t)i * d + tid]) * xv[i];
            }
            qv[tid] = a;
            kv[tid] = b;
            vv[tid] = c;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        /* --- S = alpha*S + k (x) v, in place --------------------------- */
        if (tid < d) {
            device float *row = SL + (size_t)tid * d;
            const float kj = kv[tid];
            for (unsigned int i = 0; i < d; ++i) {
                row[i] = alpha * row[i] + kj * vv[i];
            }
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        /* --- o = S^T q -------------------------------------------------- */
        if (tid < d) {
            float a = 0.0f;
            for (unsigned int j = 0; j < d; ++j) {
                a += SL[(size_t)j * d + tid] * qv[j];
            }
            ov[tid] = a;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        /* --- attn = W_o . o,  x = x + attn (residual) -------------------- */
        if (tid < d) {
            float a = 0.0f;
            for (unsigned int i = 0; i < d; ++i) a += float(Wo[(size_t)i * d + tid]) * ov[i];
            xv[tid] = xv[tid] + a;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        /* --- gate, up = W2 . x ----------------------------------------- */
        if (tid < dff) {
            float a = 0.0f, b = 0.0f;
            for (unsigned int i = 0; i < d; ++i) {
                a += float(L2[(size_t)i * d + tid]) * xv[i];
                b += float(L2[(size_t)dff * d + (size_t)i * d + tid]) * xv[i];
            }
            gate[tid] = a;
            up[tid] = b;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        /* --- h = silu(gate) * up --------------------------------------- */
        if (tid < dff) {
            const float g = gate[tid];
            gate[tid] = (g > 0.0f ? g / (1.0f + exp(-g)) : 0.0f) * up[tid];
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        /* --- y = W3 . h, and that is the next layer's input ------------- */
        if (tid < d) {
            float a = 0.0f;
            for (unsigned int c = 0; c < dff; ++c) a += float(L3[(size_t)c * d + tid]) * gate[c];
            xv[tid] = a;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }

    if (tid < d) Y[(size_t)t * d + tid] = xv[tid];
}

/* ---------------------------------------------------------------------------
 * fused_step_sk_kernel — the same stack, 8 threads per output row.
 *
 * The one-thread-per-row version leaves the GPU at a few percent of peak: each
 * thread runs a single dependent accumulator chain over 128 terms, so there
 * is no instruction-level parallelism to hide the load latency behind, and
 * 256 threads is not enough of a warp to fill a core. This variant puts 1024
 * threads in the threadgroup and splits each dot product SPLIT ways, so each
 * thread sums d/SPLIT terms into its own accumulator and the SPLIT partials
 * are combined in threadgroup memory at the end of each stage.
 *
 * It costs one extra barrier per stage and buys 8x the parallelism and 8
 * independent accumulator chains per row. The stage structure is otherwise
 * identical, so the two kernels compute the same function and the benchmark
 * checks that they agree.
 *
 * Requires d <= 1024 and dff <= 1024 (one threadgroup covers the whole
 * output axis at SPLIT=8), which is every width this model uses.
 * ------------------------------------------------------------------------- */
#define MG_SPLIT 8

kernel void fused_step_sk_kernel(
    device const bfloat *W,
    device const bfloat *X,
    device float *S,
    device float *Y,
    constant float &alpha,
    constant unsigned int &steps,
    constant unsigned int &layers,
    constant unsigned int &d,
    constant unsigned int &dff,
    uint gid [[threadgroup_position_in_grid]],
    uint tid [[thread_position_in_threadgroup]])
{
    const unsigned int t = gid % steps;
    const unsigned int L = gid / steps;

    threadgroup float red[1024];
    threadgroup float red2[1024];
    threadgroup float xv[256];
    threadgroup float qv[256];
    threadgroup float kv[256];
    threadgroup float vv[256];
    threadgroup float ov[256];
    threadgroup float gate[256];
    threadgroup float up[256];

    device const bfloat *L1 = W + (size_t)L * (4u * d * d + 2u * dff * d + d * dff);
    device const bfloat *L2 = L1 + 4u * d * d;
    device const bfloat *L3 = L2 + 2u * dff * d;
    device float *SL = S + (size_t)L * d * d;
    device const bfloat *x0 = X + (size_t)t * d;

    const uint part = tid % MG_SPLIT;        /* which slice of the sum */
    const uint row = tid / MG_SPLIT;        /* which output element */

    if (tid < d) xv[tid] = float(x0[tid]);
    threadgroup_barrier(mem_flags::mem_threadgroup);

    for (unsigned int lay = 0; lay < layers; ++lay) {
        /* --- q, k, v = W . x, split-K --------------------------------- */
        if (row < d) {
            float a = 0.0f, b = 0.0f, c = 0.0f;
            for (unsigned int i = part; i < d; i += MG_SPLIT) {
                a += float(L1[(size_t)i * d + row]) * xv[i];
                b += float(L1[(size_t)d * d + (size_t)i * d + row]) * xv[i];
                c += float(L1[(size_t)2 * d * d + (size_t)i * d + row]) * xv[i];
            }
            red[tid] = a;
            red[tid + 256] = b;
            red[tid + 512] = c;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
        if (part == 0 && row < d) {
            float a = 0.0f, b = 0.0f, c = 0.0f;
            for (unsigned int s2 = 0; s2 < MG_SPLIT; s2++) {
                a += red[row * MG_SPLIT + s2];
                b += red[256 + row * MG_SPLIT + s2];
                c += red[512 + row * MG_SPLIT + s2];
            }
            qv[row] = a; kv[row] = b; vv[row] = c;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        /* --- S = alpha*S + k (x) v, in place --------------------------- */
        if (tid < d) {
            device float *rp = SL + (size_t)tid * d;
            const float kj = kv[tid];
            for (unsigned int i = 0; i < d; ++i) rp[i] = alpha * rp[i] + kj * vv[i];
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        /* --- o = S^T q, split-K ---------------------------------------- */
        if (row < d) {
            float a = 0.0f;
            for (unsigned int j = part; j < d; j += MG_SPLIT) {
                a += SL[(size_t)j * d + row] * qv[j];
            }
            red[tid] = a;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
        if (part == 0 && row < d) {
            float a = 0.0f;
            for (unsigned int s2 = 0; s2 < MG_SPLIT; s2++) a += red[row * MG_SPLIT + s2];
            ov[row] = a;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        /* --- x += W_o . o, split-K ------------------------------------ */
        if (row < d) {
            float a = 0.0f;
            for (unsigned int i = part; i < d; i += MG_SPLIT) {
                a += float(L1[(size_t)3 * d * d + (size_t)i * d + row]) * ov[i];
            }
            red[tid] = a;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
        if (part == 0 && row < d) {
            float a = 0.0f;
            for (unsigned int s2 = 0; s2 < MG_SPLIT; s2++) a += red[row * MG_SPLIT + s2];
            xv[row] = xv[row] + a;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        /* --- gate, up = W2 . x, split-K (dff rows, 4 per row) ----------
         * Two reductions live at once here, so they go in two arrays; a
         * single one had both partials landing in red[tid] and `up` coming
         * out as a copy of `gate`. */
        if (row < dff) {
            const unsigned int s4 = tid & 3u;
            float a = 0.0f, b = 0.0f;
            for (unsigned int i = s4; i < d; i += 4u) {
                a += float(L2[(size_t)i * d + row]) * xv[i];
                b += float(L2[(size_t)dff * d + (size_t)i * d + row]) * xv[i];
            }
            red[tid] = a;
            red2[tid] = b;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
        if (row < dff && (tid & 3u) == 0) {
            float a = 0.0f, b = 0.0f;
            for (unsigned int s2 = 0; s2 < 4u; s2++) {
                a += red[row * 4u + s2];
                b += red2[row * 4u + s2];
            }
            const float g = a;
            gate[row] = (g > 0.0f ? g / (1.0f + exp(-g)) : 0.0f) * b;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);

        /* --- y = W3 . h, split-K (d rows, 8 per row) ------------------- */
        if (row < d) {
            float a = 0.0f;
            for (unsigned int c = part; c < dff; c += MG_SPLIT) {
                a += float(L3[(size_t)c * d + row]) * gate[c];
            }
            red[tid] = a;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
        if (part == 0 && row < d) {
            float a = 0.0f;
            for (unsigned int s2 = 0; s2 < MG_SPLIT; s2++) a += red[row * MG_SPLIT + s2];
            xv[row] = a;
        }
        threadgroup_barrier(mem_flags::mem_threadgroup);
    }
    if (tid < d) Y[(size_t)t * d + tid] = xv[tid];
}
