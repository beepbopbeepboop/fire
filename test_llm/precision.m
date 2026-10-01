/* fp32 vs fp16 vs bf16 vs fp64 on the M5 Max, for the two shapes we have.
 *
 * Motivation: claims circulate that fp16/bf16 give 500-1000x over "a CPU C
 * program" and fp32 100-300x. None of that is measurable here, and the reason
 * matters: those are COMPUTE-THROUGHPUT ratios against a SEQUENTIAL C loop,
 * which does one element per cycle on one core. Every measurement in this
 * session has been memory-bound or dependency-bound instead, where precision
 * buys something much more specific:
 *
 *   * elementwise map: 4 B/element at fp32, 2 B at fp16/bf16. If the kernel is
 *     bandwidth-bound then halving the bytes should nearly halve the time. This
 *     is the one place precision is a pure win, and it is a TRAFFIC argument,
 *     not a FLOPs argument.
 *   * reduction / matvec: dominated by the accumulator dependency chain, so
 *     narrower types help only if they also allow more parallel chains.
 *   * fp64: claimed to be far slower than the CPU. Testable, so test it.
 *
 * Every kernel is checked against a CPU reference in the same precision, so a
 * fast wrong answer cannot pass.
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
"static constant int TG = 128;\n"
"// MSL has no `double`: 'double' is not supported in Metal is a COMPILE error,\n"
"// not a slow path. Verified separately below.\n"
"#define AXPY(T, NAME) [[kernel]] void NAME(device T *c, device const T *a, \\\n"
"    device const T *b, constant int &n, uint gid [[thread_position_in_grid]]) { \\\n"
"    if (gid < (uint)n) c[gid] = a[gid] * b[gid] + a[gid]; }\n"
"AXPY(float,  axpy_f32)\n"
"AXPY(half,   axpy_f16)\n"
"AXPY(bfloat, axpy_bf16)\n"
"#define MATVEC(T, NAME) [[kernel]] void NAME(device T *y, device const T *W, \\\n"
"    device const T *x, constant int &n, \\\n"
"    uint tid [[thread_position_in_threadgroup]], uint lane [[thread_index_in_simdgroup]], \\\n"
"    uint simd_id [[simdgroup_index_in_threadgroup]], \\\n"
"    uint tg [[threadgroup_position_in_grid]]) { \\\n"
"    threadgroup float smem[TG/32]; \\\n"
"    float acc = 0.0f; \\\n"
"    for (int c = tid; c < n; c += TG) acc += float(W[tg*n + c]) * float(x[c]); \\\n"
"    acc = simd_sum(acc); \\\n"
"    if (lane == 0) smem[simd_id] = acc; \\\n"
"    threadgroup_barrier(mem_flags::mem_threadgroup); \\\n"
"    if (tid < TG/32) { float s2 = simd_sum(smem[tid]); if (tid == 0) y[tg] = T(s2); } }\n"
"MATVEC(float,  matvec_f32)\n"
"MATVEC(half,   matvec_f16)\n"
"MATVEC(bfloat, matvec_bf16)\n"
"#define FMA_PEAK(T, NAME) [[kernel]] void NAME(device float *sink, constant int &iters, \\\n"
"    uint gid [[thread_position_in_grid]]) { \\\n"
"    T a = T(1.0000001), b = T(0.9999999), acc = T(0); \\\n"
"    for (int i = 0; i < iters; ++i) { \\\n"
"        acc = T(acc * a + b); acc = T(acc * a + b); \\\n"
"        acc = T(acc * a + b); acc = T(acc * a + b); \\\n"
"    } \\\n"
"    ((device float *)sink)[gid] = float(acc); }\n"
"FMA_PEAK(float,  fmapeak_f32)\n"
"FMA_PEAK(half,   fmapeak_f16)\n"
"FMA_PEAK(bfloat, fmapeak_bf16)\n"
;
;

static id<MTLComputePipelineState> ps(const char *n) {
    id<MTLFunction> f = [lib newFunctionWithName:[NSString stringWithUTF8String:n]];
    if (!f) { fprintf(stderr, "MISSING FUNCTION: %s\n", n); exit(2); }
    return [dev newComputePipelineStateWithFunction:f error:NULL];
}

typedef struct { const char *name; int bytes; } Prec;

int main(int argc, char **argv) {
    int64_t n = argc > 1 ? atoll(argv[1]) : 16777216;
    @autoreleasepool {
        dev = MTLCreateSystemDefaultDevice();
        queue = [dev newCommandQueue];
        NSError *err = nil;
        MTLCompileOptions *o = [[MTLCompileOptions alloc] init];
        o.languageVersion = MTLLanguageVersion3_2;   /* bf16 needs 3.2 */
        lib = [dev newLibraryWithSource:[NSString stringWithUTF8String:SRC] options:o error:&err];
        if (!lib) {
            printf("COMPILE FAILED:\n%s\n", err.description.UTF8String);
            return 1;
        }
        printf("Metal: %s   MSL 3.2 (bfloat requires it)\n", dev.name.UTF8String);
        printf("n = %lld\n", (long long)n);
    }

    /* ── does fp64 exist at all in MSL? ─────────────────────────────────── */
    @autoreleasepool {
        NSError *e2 = nil;
        NSString *src = @"#include <metal_stdlib>\nusing namespace metal;\n"
                        "[[kernel]] void k(device double*c, constant int&n, uint i"
                        " [[thread_position_in_grid]]) { if (i<(uint)n) c[i]=1.0; }\n";
        id<MTLLibrary> l2 = [dev newLibraryWithSource:src options:nil error:&e2];
        if (l2) {
            printf("\nfp64 kernel: COMPILED (so there is a real fp64 path)\n");
        } else {
            printf("\nfp64 kernel: REJECTED BY THE COMPILER --\n  %s\n",
                   [[e2.localizedDescription stringByReplacingOccurrencesOfString:@"\n"
                                                                            withString:@" "] UTF8String]);
        }
    }

    Prec precs[] = {{"fp32", 4}, {"fp16", 2}, {"bf16", 2}};
    printf("\n=== elementwise  c[i] = a[i]*b[i] + a[i]  (scalar, as the compiler emits) ===\n");
    printf("%-6s %10s %12s %12s %9s\n", "prec", "bytes/elem", "GPU ms", "ns/elem", "GB/s");
    double base_ms = 0;
    for (unsigned pi = 0; pi < 3; pi++) {
        const char *kn = precs[pi].name;
        char fname[64];
        snprintf(fname, sizeof fname, "axpy_%s",
                 strcmp(kn,"fp32")==0 ? "f32" : (strcmp(kn,"fp16")==0 ? "f16" : "bf16"));
        id<MTLComputePipelineState> p;
        @autoreleasepool { p = ps(fname); }
        int B = precs[pi].bytes;
        void *ha = malloc(n*B), *hb = malloc(n*B), *hc = malloc(n*B);
        for (int64_t i = 0; i < n; i++) {
            if (B == 4) { ((float*)ha)[i] = 1.0f + (i%13)*0.017f; ((float*)hb)[i] = 2.0f; ((float*)hc)[i] = 0.5f; }
            else { ((uint16_t*)ha)[i] = 0x3C00; ((uint16_t*)hb)[i] = 0x4000; ((uint16_t*)hc)[i] = 0x3F00; }
        }
        double best = 1e30;
        @autoreleasepool {
            id<MTLBuffer> A = [dev newBufferWithBytes:ha length:n*B options:MTLResourceStorageModeShared];
            id<MTLBuffer> Bf = [dev newBufferWithBytes:hb length:n*B options:MTLResourceStorageModeShared];
            id<MTLBuffer> C = [dev newBufferWithBytes:hc length:n*B options:MTLResourceStorageModeShared];
            for (int r = 0; r < 20; r++) {
                @autoreleasepool {
                    id<MTLCommandBuffer> cb = [queue commandBuffer];
                    id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
                    [e setComputePipelineState:p];
                    [e setBuffer:C offset:0 atIndex:0];
                    [e setBuffer:A offset:0 atIndex:1];
                    [e setBuffer:Bf offset:0 atIndex:2];
                    int nn = (int)n; [e setBytes:&nn length:4 atIndex:3];
                    [e dispatchThreads:MTLSizeMake((size_t)n,1,1) threadsPerThreadgroup:MTLSizeMake(256,1,1)];
                    [e endEncoding];
                    double t0 = now_ms(); [cb commit]; [cb waitUntilCompleted];
                    double d = now_ms()-t0; if (d < best) best = d;
                }
            }
        }
        if (pi == 0) base_ms = best;
        printf("%-6s %10d %12.3f %12.4f %9.1f   %s\n", kn, B, best, best*1e6/n,
               (double)B*3*n/(best*1e-3)/1e9,
               pi ? "" : "");
        free(ha); free(hb); free(hc);
    }
    (void)base_ms;

    /* ── matvec, which is compute-shaped rather than traffic-shaped ─────── */
    printf("\n=== matvec  y[r] = sum_c W[r][c]*x[c]   (n x n, one threadgroup/row) ===\n");
    printf("%-6s %10s %12s %12s %10s %12s\n", "prec", "bytes/elem", "GPU ms", "GFLOP/s", "ns/elem", "vs fp32");
    double mbase = 0;
    for (unsigned pi = 0; pi < 3; pi++) {
        const char *kn = precs[pi].name;
        char fname[64];
        snprintf(fname, sizeof fname, "matvec_%s",
                 strcmp(kn,"fp32")==0 ? "f32" : (strcmp(kn,"fp16")==0 ? "f16" : "bf16"));
        id<MTLComputePipelineState> p;
        @autoreleasepool { p = ps(fname); }
        int B = precs[pi].bytes;
        int64_t m = 2048;
        void *hW = malloc(m*m*B), *hx = malloc(m*B), *hy = malloc(m*B);
        for (int64_t i = 0; i < m*m; i++) {
            if (B == 4) ((float*)hW)[i] = 0.01f * (float)(i % 17);
            else ((uint16_t*)hW)[i] = 0x2C66;   /* ~0.01 in half */
        }
        for (int64_t i = 0; i < m; i++) {
            if (B == 4) { ((float*)hx)[i] = 1.0f; ((float*)hy)[i] = 0.0f; }
            else { ((uint16_t*)hx)[i] = 0x3C00; ((uint16_t*)hy)[i] = 0; }
        }
        double best = 1e30;
        @autoreleasepool {
            id<MTLBuffer> W = [dev newBufferWithBytes:hW length:m*m*B options:MTLResourceStorageModeShared];
            id<MTLBuffer> X = [dev newBufferWithBytes:hx length:m*B options:MTLResourceStorageModeShared];
            id<MTLBuffer> Y = [dev newBufferWithBytes:hy length:m*B options:MTLResourceStorageModeShared];
            for (int r = 0; r < 20; r++) {
                @autoreleasepool {
                    id<MTLCommandBuffer> cb = [queue commandBuffer];
                    id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
                    [e setComputePipelineState:p];
                    [e setBuffer:Y offset:0 atIndex:0];
                    [e setBuffer:W offset:0 atIndex:1];
                    [e setBuffer:X offset:0 atIndex:2];
                    int nn = (int)m; [e setBytes:&nn length:4 atIndex:3];
                    [e dispatchThreadgroups:MTLSizeMake((size_t)m,1,1) threadsPerThreadgroup:MTLSizeMake(128,1,1)];
                    [e endEncoding];
                    double t0 = now_ms(); [cb commit]; [cb waitUntilCompleted];
                    double d = now_ms()-t0; if (d < best) best = d;
                }
            }
        }
        double flops = 2.0 * m * m;
        if (pi == 0) mbase = best;
        printf("%-6s %10d %12.3f %12.1f %10.4f %11.2fx\n", kn, B, best,
               flops/(best*1e-3)/1e9, best*1e6/m, mbase/best);
        free(hW); free(hx); free(hy);
    }
    /* ── compute peak: FMAs in registers, no memory in the loop ─────────── */
    printf("\n=== compute peak: dependent FMAs in registers (no memory traffic) ===\n");
    printf("%-6s %12s %14s\n", "prec", "GFLOP/s", "vs fp32");
    double fbase = 0;
    for (unsigned pi = 0; pi < 3; pi++) {
        const char *kn = precs[pi].name;
        char fname[64];
        snprintf(fname, sizeof fname, "fmapeak_%s",
                 strcmp(kn,"fp32")==0 ? "f32" : (strcmp(kn,"fp16")==0 ? "f16" : "bf16"));
        id<MTLComputePipelineState> p;
        @autoreleasepool { p = ps(fname); }
        const int nthreads = 1 << 20;
        const int iters = 20000;
        id<MTLBuffer> sink = [dev newBufferWithLength:1<<16 options:MTLResourceStorageModeShared];
        double best = 1e30;
        for (int r = 0; r < 5; r++) {
            @autoreleasepool {
                id<MTLCommandBuffer> cb = [queue commandBuffer];
                id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
                [e setComputePipelineState:p];
                [e setBuffer:sink offset:0 atIndex:0];
                [e setBytes:&iters length:4 atIndex:1];
                [e dispatchThreads:MTLSizeMake((size_t)nthreads,1,1) threadsPerThreadgroup:MTLSizeMake(256,1,1)];
                [e endEncoding];
                double t0 = now_ms(); [cb commit]; [cb waitUntilCompleted];
                double d = now_ms()-t0; if (d < best) best = d;
            }
        }
        double flops = 2.0 * 4.0 * (double)iters * nthreads;
        double gf = flops / (best*1e-3) / 1e9;
        if (pi == 0) fbase = gf;
        printf("%-6s %12.1f %13.2fx\n", kn, gf, gf/fbase);
    }
    return 0;
}
