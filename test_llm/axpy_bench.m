/* Same loop, four ways:  c[i] = a[i] * b[i] + a[i]
 *
 * The question is what the compiler's SYNTHESISED kernel costs against a Metal
 * kernel written for speed, and against C that is actually optimised -- because
 * the honest opponent to a GPU is not a naive -O2 triple loop. notes.html says
 * as much: "the ARM column is an unoptimised -O2 scalar loop, so a
 * blocked/vectorised C kernel would only widen the gap."
 *
 * The synthesized kernel is the shape emitted from a loop body verbatim: one
 * thread per element, a bounds guard, no vectorisation. mg_axpy_kernel in
 * test_llm/kernels.metal has the SAME shape, so it is not a speed reference
 * either -- which is why `fast4` exists here.
 *
 * Two timings per GPU kernel, because conflating them is how a 14x becomes a
 * 0.4x:
 *   KERNEL   -- dispatch + GPU + wait, no host marshalling, no read-back
 *   MARSHALL  -- + build the MTLBuffers, + copy results back (what a real
 *               per-call offload actually pays)
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
"using namespace metal;\n"
/* What the compiler emits from a loop body verbatim: one thread per element. */
"kernel void naive(device float *c, device const float *a, device const float *b,\n"
"                 constant int &n, uint gid [[thread_position_in_grid]]) {\n"
"    if (gid < (uint)n) { c[gid] = a[gid] * b[gid] + a[gid]; }\n"
"}\n"
/* Hand-written for speed: 4 elements per thread via float4, so one quarter of
   the threads, 128-bit loads, and the bounds check hoisted out of the inner
   body. A 4-wide load is the whole game here -- the loop is memory-bound at
   20 bytes/element, so it is issue width and coalescing, nothing else. */
"kernel void fast4(device float *c, device const float *a, device const float *b,\n"
"                  constant int &n4, uint gid [[thread_position_in_grid]]) {\n"
"    uint i = gid * 4;\n"
"    if (i < (uint)n4) {\n"
"        float4 av = ((const device float4 *)a)[gid];\n"
"        float4 bv = ((const device float4 *)b)[gid];\n"
"        float4 cv = ((device float4 *)c)[gid];\n"
"        ((device float4 *)c)[gid] = float4(av.x*bv.x+av.x, av.y*bv.y+av.y,\n"
"                                             av.z*bv.z+av.z, av.w*bv.w+av.w);\n"
"        (void)cv;\n"
"    }\n"
"}\n";

/* ── C baselines ────────────────────────────────────────────────────────── */

static void c_scalar(float *c, const float *a, const float *b, int64_t n) {
    for (int64_t i = 0; i < n; i++) c[i] = a[i] * b[i] + a[i];
}

/* The honest opponent, and the one notes.html says is missing. restrict so the
   compiler may assume no aliasing (it may not: a[i] is both read and written
   through c, so without restrict it must serialise every store). */
static void c_vec(float *restrict c, const float *restrict a,
                  const float *restrict b, int64_t n) {
    for (int64_t i = 0; i < n; i++) c[i] = a[i] * b[i] + a[i];
}

static double best_of(double (*fn)(float *, const float *, const float *,
                                   int64_t, int),
                      float *c, const float *a, const float *b, int64_t n,
                      int reps) {
    double best = 1e30;
    for (int r = 0; r < reps; r++) {
        double t0 = now_ms();
        fn(c, a, b, n, 0);
        double dt = now_ms() - t0;
        if (dt < best) best = dt;
    }
    return best;
}

static double run_c_scalar(float *c, const float *a, const float *b, int64_t n, int r) {
    (void)r; double best = 1e30;
    for (int k = 0; k < r; k++) { double t0 = now_ms(); c_scalar(c,a,b,n); double d = now_ms()-t0; if (d<best) best=d; }
    return best;
}
static double run_c_vec(float *c, const float *a, const float *b, int64_t n, int r) {
    (void)r; double best = 1e30;
    for (int k = 0; k < r; k++) { double t0 = now_ms(); c_vec(c,a,b,n); double d = now_ms()-t0; if (d<best) best=d; }
    return best;
}

/* ── GPU ────────────────────────────────────────────────────────────────── */

static id<MTLFunction> fn_naive, fn_fast4;

static void gpu_time(const char *which, float *c, const float *a,
                     const float *b, int64_t n, double *out_kernel,
                     double *out_marshall) {
    id<MTLFunction> f = strcmp(which, "naive") == 0 ? fn_naive : fn_fast4;
    id<MTLComputePipelineState> ps =
        [dev newComputePipelineStateWithFunction:f error:NULL];
    const uint64_t bytes = (uint64_t)n * sizeof(float);
    const bool wide = strcmp(which, "fast4") == 0;
    const uint64_t nthreads = wide ? (uint64_t)n / 4 : (uint64_t)n;
    const int n4 = (int)(n / 4);

    /* KERNEL only: buffers already resident. */
    double best_k = 1e30;
    for (int r = 0; r < 20; r++) {
        @autoreleasepool {
            id<MTLCommandBuffer> cb = [queue commandBuffer];
            id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
            [e setComputePipelineState:ps];
            [e setBuffer:[dev newBufferWithBytes:c length:bytes options:MTLResourceStorageModeShared]
                offset:0 atIndex:0];
            [e setBuffer:[dev newBufferWithBytes:a length:bytes options:MTLResourceStorageModeShared]
                offset:0 atIndex:1];
            [e setBuffer:[dev newBufferWithBytes:b length:bytes options:MTLResourceStorageModeShared]
                offset:0 atIndex:2];
            [e setBuffer:[dev newBufferWithLength:sizeof(int) options:MTLResourceStorageModeShared]
                offset:0 atIndex:3];
            int v = wide ? n4 : (int)n;
            [e setBytes:&v length:sizeof(int) atIndex:3];
            [e dispatchThreads:MTLSizeMake(nthreads, 1, 1)
              threadsPerThreadgroup:MTLSizeMake(wide ? 64 : 256, 1, 1)];
            [e endEncoding];
            double t0 = now_ms();
            [cb commit];
            [cb waitUntilCompleted];
            double d = now_ms() - t0;
            if (d < best_k) best_k = d;
        }
    }
    *out_kernel = best_k;

    /* MARSHALL: what a per-call offload actually pays -- new buffers and a
       copy back every time, exactly as the compiler's host path does. */
    double best_m = 1e30;
    for (int r = 0; r < 20; r++) {
        @autoreleasepool {
            double t0 = now_ms();
            id<MTLBuffer> bc = [dev newBufferWithLength:bytes options:MTLResourceStorageModeShared];
            id<MTLBuffer> ba = [dev newBufferWithBytes:a length:bytes options:MTLResourceStorageModeShared];
            id<MTLBuffer> bb = [dev newBufferWithBytes:b length:bytes options:MTLResourceStorageModeShared];
            id<MTLBuffer> bl = [dev newBufferWithLength:sizeof(int) options:MTLResourceStorageModeShared];
            int v = wide ? n4 : (int)n;
            [bl contents] && (memcpy([bl contents], &v, sizeof(int)), 1);
            id<MTLCommandBuffer> cb = [queue commandBuffer];
            id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
            [e setComputePipelineState:ps];
            [e setBuffer:bc offset:0 atIndex:0];
            [e setBuffer:ba offset:0 atIndex:1];
            [e setBuffer:bb offset:0 atIndex:2];
            [e setBuffer:bl offset:0 atIndex:3];
            [e dispatchThreads:MTLSizeMake(nthreads, 1, 1)
              threadsPerThreadgroup:MTLSizeMake(wide ? 64 : 256, 1, 1)];
            [e endEncoding];
            [cb commit];
            [cb waitUntilCompleted];
            memcpy(c, [bc contents], bytes);
            double d = now_ms() - t0;
            if (d < best_m) best_m = d;
        }
    }
    *out_marshall = best_m;
}

int main(void) {
    @autoreleasepool {
        dev = MTLCreateSystemDefaultDevice();
        if (!dev) { printf("no Metal device\n"); return 1; }
        queue = [dev newCommandQueue];
        NSError *err = nil;
        MTLCompileOptions *o = [[MTLCompileOptions alloc] init];
        o.languageVersion = MTLLanguageVersion3_2;
        lib = [dev newLibraryWithSource:[NSString stringWithUTF8String:SRC]
                                options:o error:&err];
        if (!lib) { printf("compile failed: %s\n",
                           err.description.UTF8String); return 1; }
        fn_naive = [lib newFunctionWithName:@"naive"];
        fn_fast4 = [lib newFunctionWithName:@"fast4"];
        printf("Metal: %s, language 3.2\n\n", dev.name.UTF8String);
    }

    printf("c[i] = a[i]*b[i] + a[i]   -- ns per element\n");
    printf("%10s %11s %11s %11s %11s %11s\n", "n", "C scalar", "C vec+restrict",
           "GPU naive", "GPU float4", "fast4 vs Cvec");

    int64_t sizes[] = {65536, 262144, 1048576, 4194304, 16777216};
    for (int i = 0; i < 5; i++) {
        int64_t n = sizes[i];
        int reps = n <= 262144 ? 200 : (n <= 4194304 ? 40 : 10);
        float *a = malloc(n * 4), *b = malloc(n * 4), *c = malloc(n * 4);
        for (int64_t k = 0; k < n; k++) { a[k] = 1.0f + (k % 7) * 0.01f; b[k] = 2.0f; }

        double ts = run_c_scalar(c, a, b, n, reps) * 1e6 / n;
        double tv = run_c_vec(c, a, b, n, reps) * 1e6 / n;
        double kn = 0, km = 0, kf = 0, kfm = 0;
        gpu_time("naive", c, a, b, n, &kn, &km);
        gpu_time("fast4", c, a, b, n, &kf, &kfm);

        printf("%10lld %11.2f %11.2f %11.2f %11.2f %11.2fx\n",
               (long long)n, ts, tv, kn, kf, tv / kf);

        /* The compiler's measured end-to-end figure was 190 us fixed + 5.29
           ns/element, which is the MARSHALL column, not the kernel column.
           Print it so the two are never confused again. */
        printf("%10s %11s %11s %11s %11.2f\n", "", "", "", "GPU+marshal", kfm);
        free(a); free(b); free(c);
    }
    return 0;
}
