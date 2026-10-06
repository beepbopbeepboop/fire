/* Does MLX's reduction recipe beat what we have?
 *
 * Stolen from /Users/mrs/net/mlx/mlx/backend/metal/kernels/dot.h, which is
 * the closest thing in that tree to the loop the auto-offload refuses.
 *
 * Three ideas, and only one of them is the obvious one:
 *
 *  1. float4 loads. Obvious. In an ELEMENTWISE kernel this buys ~6% (measured
 *     earlier: 41% more bandwidth, 6% less time, because elementwise is
 *     bandwidth-bound and adjacent threads already coalesce). In a REDUCTION
 *     it is different, and that difference is the point of idea 2.
 *
 *  2. FOUR INDEPENDENT float4 accumulators, not one. A reduction written as
 *     `sum += a[i]*b[i]` is a single serial dependency chain: each FMA must
 *     wait for the previous one, so the kernel runs at FMA LATENCY, not FMA
 *     throughput. Four accumulators give four independent chains and the
 *     machine issues four in parallel. MLX keeps them in a `float4` so they
 *     also vectorise at no extra cost -- the two ideas are the same register.
 *
 *  3. `simd_sum` -- the HARDWARE simdgroup reduction, not a shuffle tree.
 *     One instruction reduces across all 32 lanes. Then one float per simdgroup
 *     goes to threadgroup memory, a barrier, and a second `simd_sum` finishes
 *     it. Two levels, so the threadgroup is the unit of output.
 *
 * Plus `clang loop unroll(full)` and template parameters so the trip count is a
 * compile-time constant.
 *
 * This is the kernel I declined to build earlier on the grounds that it needed
 * a threadgroup local and a barrier. MLX is the evidence that it is a
 * well-trodden path rather than an exotic one, and the measurement below is
 * whether it is worth building.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <mach/mach_time.h>
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>

static double now_ms(void) {
    static mach_timebase_info_data_t tb;
    if (tb.denom == 0) mach_timebase_info(&tb);
    return (double)mach_absolute_time() * tb.numer / tb.denom / 1e6;
}

static id<MTLDevice> dev;
static id<MTLCommandQueue> queue;
static id<MTLLibrary> lib;

static const char *SRC =
"#include <metal_stdlib>\n"
"#include <metal_simdgroup>\n"
"using namespace metal;\n"


"// A: the naive reduction -- one accumulator, one element per thread.\n"
"// The shape a compiler emits from `sum = sum + a[i]*b[i]` verbatim:\n"
"// serial in the accumulator AND scalar in the loads.\n"

"kernel void dot_naive(device float *out, device const float *a,\n"
"                     device const float *b, constant int &n,\n"
"                     uint tid [[thread_position_in_grid]]) {\n"
"    if (tid < (uint)n) out[tid] = a[tid] * b[tid];\n"
"}\n"


"// B: float4 but STILL ONE accumulator -- isolates idea 1 from idea 2.\n"

"kernel void dot_v4_oneacc(device float *out, device const float *a,\n"
"                          device const float *b, constant int &n4,\n"
"                          uint tid [[thread_position_in_grid]]) {\n"
"    if (tid >= (uint)n4) return;\n"
"    float4 av = ((const device float4 *)a)[tid];\n"
"    float4 bv = ((const device float4 *)b)[tid];\n"
"    out[tid] = av.x*bv.x + av.y*bv.y + av.z*bv.z + av.w*bv.w;\n"
"}\n"


"// C: MLX's recipe. float4 AND four independent accumulators AND simd_sum AND\n"
"// *   a two-level threadgroup reduction.\n"

"static constant int TG_SIZE = 256;\n"
"static constant int SIMD_GROUPS = TG_SIZE / 32;\n"
"// Each threadgroup reduces a DISJOINT slice and writes one scalar. An\n"
"// earlier version let every threadgroup stride over the WHOLE array, so the\n"
"// host summed ntg copies of the full answer: rel error came out as exactly\n"
"// ntg-1 (1.0, 7.0, 31, 130, 510 for ntg = 2, 8, 32, 128, 512), which is how\n"
"// the bug was identified rather than guessed at.\n"
"[[kernel]] void dot_mlx(device float *out, device const float *a,\n"
"                       device const float *b, constant int &n,\n"
"                       constant int &ngroups,\n"
"                       uint tid [[thread_position_in_threadgroup]],\n"
"                       uint lane [[thread_index_in_simdgroup]],\n"
"                       uint simd_id [[simdgroup_index_in_threadgroup]],\n"
"                       uint tg_id [[threadgroup_position_in_grid]]) {\n"
"    int n4 = n / 4;\n"
"    int per = (n4 + ngroups - 1) / ngroups;\n"
"    int lo = tg_id * per, hi = min(lo + per, n4);\n"
"    float4 c = float4(0.0f);\n"
"    for (int i = lo + tid; i < hi; i += TG_SIZE) {\n"
"        float4 av = ((const device float4 *)a)[i];\n"
"        float4 bv = ((const device float4 *)b)[i];\n"
"        c += av * bv;\n"
"    }\n"
"    for (int i = (n4 * 4) + lo * 4 + tid; i < n; i += TG_SIZE) {\n"
"        c.x += ((const device float *)a)[i] * ((const device float *)b)[i];\n"
"    }\n"
"    threadgroup float smem[SIMD_GROUPS];\n"
"    float sum = c.x + c.y + c.z + c.w;\n"
"    sum = simd_sum(sum);\n"
"    if (lane == 0) smem[simd_id] = sum;\n"
"    threadgroup_barrier(mem_flags::mem_threadgroup);\n"
"    if (tid < SIMD_GROUPS) {\n"
"        float s2 = simd_sum(smem[tid]);\n"
"        if (tid == 0) out[tg_id] = s2;\n"
"    }\n"
"}\n"
;

/* ── CPU references ──────────────────────────────────────────────────────── */

static double cpu_dot(const double *a, const double *b, int64_t n) {
    double s = 0.0;
    for (int64_t i = 0; i < n; i++) s += a[i] * b[i];
    return s;
}
/* four accumulators on the CPU too, so the comparison is not "GPU vs naive C"
   but "GPU recipe vs the same recipe on the CPU" */
static double cpu_dot_ilp(const double *a, const double *b, int64_t n) {
    double c0=0,c1=0,c2=0,c3=0;
    int64_t i = 0;
    for (; i + 4 <= n; i += 4) {
        c0 += a[i]*b[i]; c1 += a[i+1]*b[i+1];
        c2 += a[i+2]*b[i+2]; c3 += a[i+3]*b[i+3];
    }
    for (; i < n; i++) c0 += a[i]*b[i];
    return (c0+c1)+(c2+c3);
}

int main(void) {
    @autoreleasepool {
        dev = MTLCreateSystemDefaultDevice();
        queue = [dev newCommandQueue];
        NSError *err = nil;
        MTLCompileOptions *o = [[MTLCompileOptions alloc] init];
        o.languageVersion = MTLLanguageVersion3_2;
        lib = [dev newLibraryWithSource:[NSString stringWithUTF8String:SRC] options:o error:&err];
        if (!lib) { printf("COMPILE FAILED:\n%s\n",
                           err.description.UTF8String); return 1; }
        printf("Metal: %s\n", dev.name.UTF8String);
        for (NSString *nm in lib.functionNames) {
            printf("  library has: %s\n", nm.UTF8String);
        }
    }

    printf("\n%-10s %11s %11s %11s %11s %11s %11s\n", "n",
           "CPU naive", "CPU 4acc", "GPU naive", "GPU v4/1acc", "GPU MLX", "MLX vs CPU");
    int64_t sizes[] = {65536, 262144, 1048576, 4194304, 16777216, 67108864};
    for (int si = 0; si < 6; si++) {
        int64_t n = sizes[si];
        float *af = (float *)malloc(n*4), *bf = (float *)malloc(n*4);
        double *ad = (double *)malloc(n*8), *bd = (double *)malloc(n*8);
        for (int64_t i = 0; i < n; i++) {
            float x = (float)(1.0 + (i % 13) * 0.017);
            af[i] = x; bf[i] = 2.0f; ad[i] = x; bd[i] = 2.0;
        }
        const int reps = n <= 1048576 ? 50 : (n <= 16777216 ? 10 : 3);

        /* CPU, double, best of reps */
        double bc1 = 1e30, bc2 = 1e30;
        for (int r = 0; r < reps; r++) {
            double t0 = now_ms(); volatile double s1 = cpu_dot(ad, bd, n); (void)s1;
            double t1 = now_ms(); volatile double s2 = cpu_dot_ilp(ad, bd, n); (void)s2;
            double t2 = now_ms();
            if (t1-t0 < bc1) bc1 = t1-t0;
            if (t2-t1 < bc2) bc2 = t2-t1;
        }

        id<MTLBuffer> ab = [dev newBufferWithBytes:af length:n*4 options:MTLResourceStorageModeShared];
        id<MTLBuffer> bb = [dev newBufferWithBytes:bf length:n*4 options:MTLResourceStorageModeShared];
        id<MTLBuffer> ob;

        /* A: naive, one partial per element, then sum on the host (that host sum
           is outside the timed region, so this measures the kernel only) */
        ob = [dev newBufferWithLength:n*4 options:MTLResourceStorageModeShared];
        id<MTLComputePipelineState> pA =
          [dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"dot_naive"] error:NULL];
        double bA = 1e30;
        for (int r = 0; r < reps; r++) {
            @autoreleasepool {
                id<MTLCommandBuffer> cb = [queue commandBuffer];
                id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
                [e setComputePipelineState:pA];
                [e setBuffer:ob offset:0 atIndex:0];
                [e setBuffer:ab offset:0 atIndex:1];
                [e setBuffer:bb offset:0 atIndex:2];
                int nn = (int)n; [e setBytes:&nn length:4 atIndex:3];
                [e dispatchThreads:MTLSizeMake((size_t)n,1,1) threadsPerThreadgroup:MTLSizeMake(256,1,1)];
                [e endEncoding];
                double t0 = now_ms(); [cb commit]; [cb waitUntilCompleted];
                double d = now_ms()-t0; if (d < bA) bA = d;
            }
        }

        /* B: float4, one accumulator */
        ob = [dev newBufferWithLength:((n/4)+1)*4 options:MTLResourceStorageModeShared];
        id<MTLComputePipelineState> pB =
          [dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"dot_v4_oneacc"] error:NULL];
        double bB = 1e30;
        for (int r = 0; r < reps; r++) {
            @autoreleasepool {
                id<MTLCommandBuffer> cb = [queue commandBuffer];
                id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
                [e setComputePipelineState:pB];
                [e setBuffer:ob offset:0 atIndex:0];
                [e setBuffer:ab offset:0 atIndex:1];
                [e setBuffer:bb offset:0 atIndex:2];
                int nn = (int)(n/4); [e setBytes:&nn length:4 atIndex:3];
                [e dispatchThreads:MTLSizeMake((size_t)(n/4),1,1) threadsPerThreadgroup:MTLSizeMake(256,1,1)];
                [e endEncoding];
                double t0 = now_ms(); [cb commit]; [cb waitUntilCompleted];
                double d = now_ms()-t0; if (d < bB) bB = d;
            }
        }

        /* C: MLX recipe, one output per THREADGROUP */
        const int TG = 256, SG = TG/32;
        int ntg = (int)((n/4 + TG - 1) / TG);   /* one wave per threadgroup slice */
        if (ntg > 4096) ntg = 4096;
        if (ntg < 1) ntg = 1;
        ob = [dev newBufferWithLength:(size_t)ntg*4 options:MTLResourceStorageModeShared];
        id<MTLComputePipelineState> pC =
          [dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"dot_mlx"] error:NULL];
        double bC = 1e30; double got = 0;
        for (int r = 0; r < reps; r++) {
            @autoreleasepool {
                id<MTLCommandBuffer> cb = [queue commandBuffer];
                id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
                [e setComputePipelineState:pC];
                [e setBuffer:ob offset:0 atIndex:0];
                [e setBuffer:ab offset:0 atIndex:1];
                [e setBuffer:bb offset:0 atIndex:2];
                int nn = (int)n; [e setBytes:&nn length:4 atIndex:3];
                int ng = ntg; [e setBytes:&ng length:4 atIndex:4];
                [e dispatchThreadgroups:MTLSizeMake((size_t)ntg,1,1)
                    threadsPerThreadgroup:MTLSizeMake((size_t)TG,1,1)];
                [e endEncoding];
                double t0 = now_ms(); [cb commit]; [cb waitUntilCompleted];
                double d = now_ms()-t0; if (d < bC) bC = d;
            }
        }
        {   /* correctness: sum the per-threadgroup partials on the host */
            float *h = (float *)[ob contents];
            double s = 0; for (int i = 0; i < ntg; i++) s += h[i];
            got = s;
        }
        double expect = cpu_dot(ad, bd, n);
        double rel = fabs(got - expect) / fabs(expect);

        printf("%-10lld %11.1f %11.1f %11.1f %11.1f %11.1f %10.2fx  rel %.1e\n",
               (long long)n,
               bc1*1e6/n, bc2*1e6/n, bA*1e6/n, bB*1e6/n, bC*1e6/n,
               bc2/bC, rel);
        free(af); free(bf); free(ad); free(bd);
    }
    printf("\n(all ns per element except the last column; MLX vs CPU is 4-acc CPU"
           " / MLX, so >1 means the GPU wins. `rel` is the MLX kernel against a"
           " double-precision CPU reference.)\n");
    return 0;
}
