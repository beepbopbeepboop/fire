/* Roofline probe: what is the ceiling, and is one kernel leaving the machine
 * idle?
 *
 * Loop under test -- the one the auto-offload recognises:
 *     c[i] = a[i] * b[i] + a[i]
 * Minimum traffic 16 B/element (read a, read b, read c, write c).
 *
 * Two ceilings are measured first, because 95% of an unmeasured number is not
 * a target:
 *     k_copy  8 B/elem   the practical write roof
 *     k_read  4 B/elem   the practical read roof
 *
 * Then the axpy variants, best-of-20, buffers resident so this is KERNEL time
 * with marshalling excluded. Finally the same axpy on N independent buffers
 * encoded back to back into ONE command buffer: if a single kernel is
 * latency-bound rather than bandwidth-bound, N of them should beat N
 * sequential ones, and that is the whole concurrency question.
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

"kernel void k_copy(device float *c, device const float *a,\n"
"                  constant int &n4, uint gid [[thread_position_in_grid]]) {\n"
"    uint i = gid;\n"
"    if (i < (uint)n4) ((device float4 *)c)[i] = ((const device float4 *)a)[i];\n"
"}\n"

/* A read probe whose LOADS ARE LIVE. The first version guarded the store with
 * `if (v.x == 1e30f)`, which is never true -- so every load fed a dead
 * dependency and could be eliminated, and the "read bandwidth" it reported was
 * the speed of nothing. This accumulates unconditionally and stores once per
 * thread, so all n4 loads must happen. */
"kernel void k_read4(device float *sink, device const float *a,\n"
"                    constant int &n16, constant int &stride,\n"
"                    uint gid [[thread_position_in_grid]]) {\n"
"    float4 acc = float4(0.0f);\n"
"    for (uint i = gid; i < (uint)n16; i += (uint)stride) {\n"
"        acc += ((const device float4 *)a)[4*i];\n"
"        acc += ((const device float4 *)a)[4*i+1];\n"
"        acc += ((const device float4 *)a)[4*i+2];\n"
"        acc += ((const device float4 *)a)[4*i+3];\n"
"    }\n"
"    if (acc.x == 1e30f) ((device float *)sink)[gid & 63] = acc.x+acc.y+acc.z+acc.w;\n"
"}\n"

"kernel void k_read(device float *sink, device const float *a,\n"
"                   constant int &n4, uint gid [[thread_position_in_grid]]) {\n"
"    uint i = gid;\n"
"    float4 acc = float4(0.0f);\n"
"    if (i < (uint)n4) acc = ((const device float4 *)a)[i];\n"
"    if (acc.x == 1e30f) ((device float *)sink)[gid & 63] = acc.x+acc.y+acc.z+acc.w;\n"
"}\n"

/* v0: THE SHAPE THE COMPILER EMITS. One thread per element, scalar. */
"kernel void axpy_v0(device float *c, device const float *a, device const float *b,\n"
"                    constant int &n, uint gid [[thread_position_in_grid]]) {\n"
"    if (gid < (uint)n) c[gid] = a[gid] * b[gid] + a[gid];\n"
"}\n"

/* v1: float4 -- 4 elements/thread, 128-bit accesses. */
"kernel void axpy_v1(device float *c, device const float *a, device const float *b,\n"
"                    constant int &n4, uint gid [[thread_position_in_grid]]) {\n"
"    uint i = gid;\n"
"    if (i < (uint)n4) {\n"
"        float4 av = ((const device float4 *)a)[i];\n"
"        float4 bv = ((const device float4 *)b)[i];\n"
"        float4 cv = ((const device float4 *)c)[i];\n"
"        ((device float4 *)c)[i] = av * bv + av;\n"
"        (void)cv;\n"
"    }\n"
"}\n"

/* v2: PERSISTENT / grid-stride. Fixed grid = the machine, each thread strides.
 * The trick that matters for a latency-bound streaming kernel: every thread
 * stays resident, so iteration k+1's loads issue while k is still in flight,
 * and the bounds check leaves the hot path. */
"kernel void axpy_v2(device float *c, device const float *a, device const float *b,\n"
"                    constant int &n4, constant int &stride4,\n"
"                    uint gid [[thread_position_in_grid]]) {\n"
"    for (uint i = gid; i < (uint)n4; i += (uint)stride4) {\n"
"        float4 av = ((const device float4 *)a)[i];\n"
"        float4 bv = ((const device float4 *)b)[i];\n"
"        float4 cv = ((const device float4 *)c)[i];\n"
"        ((device float4 *)c)[i] = av * bv + av;\n"
"        (void)cv;\n"
"    }\n"
"}\n"

/* v3: persistent AND 8 elements per iteration -- double the memory-level
 * parallelism per thread, the other way to cover latency once occupancy is
 * already maxed. */
"kernel void axpy_v3(device float *c, device const float *a, device const float *b,\n"
"                    constant int &n8, constant int &stride8,\n"
"                    uint gid [[thread_position_in_grid]]) {\n"
"    for (uint i = gid; i < (uint)n8; i += (uint)stride8) {\n"
"        float4 a0 = ((const device float4 *)a)[2*i], a1 = ((const device float4 *)a)[2*i+1];\n"
"        float4 b0 = ((const device float4 *)b)[2*i], b1 = ((const device float4 *)b)[2*i+1];\n"
"        float4 cv = ((const device float4 *)c)[2*i];\n"
"        ((device float4 *)c)[2*i]   = a0 * b0 + a0;\n"
"        ((device float4 *)c)[2*i+1] = a1 * b1 + a1;\n"
"        (void)cv;\n"
"    }\n"
"}\n";

/* one buffer triple */
typedef struct { id<MTLBuffer> a, b, c; } Trip;

static id<MTLComputePipelineState> ps_for(const char *n) {
    id<MTLFunction> f = [lib newFunctionWithName:[NSString stringWithUTF8String:n]];
    if (!f) { fprintf(stderr, "no function %s\n", n); exit(1); }
    return [dev newComputePipelineStateWithFunction:f error:NULL];
}

typedef enum { M_COPY, M_READ, M_V0, M_V1, M_V2, M_V3 } Mode;

/* one timed submission: `ntrip` independent axpys encoded into ONE command
 * buffer, so the hardware can overlap them with no stream or sync overhead. */
static double submit(Mode m, id<MTLComputePipelineState> ps, Trip *t,
                     int ntrip, int64_t n, int tpg, int grid,
                     id<MTLBuffer> sink) {
    double best = 1e30;
    for (int r = 0; r < 20; r++) {
        @autoreleasepool {
            id<MTLCommandBuffer> cb = [queue commandBuffer];
            for (int k = 0; k < ntrip; k++) {
                id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
                [e setComputePipelineState:ps];
                int n4 = (int)(n/4), n8 = (int)(n/8);
                switch (m) {
                case M_COPY:
                    [e setBuffer:t[k].c offset:0 atIndex:0];
                    [e setBuffer:t[k].a offset:0 atIndex:1];
                    [e setBytes:&n4 length:sizeof(int) atIndex:2];
                    [e dispatchThreads:MTLSizeMake((size_t)n4,1,1)
                      threadsPerThreadgroup:MTLSizeMake((size_t)tpg,1,1)];
                    break;
                case M_READ:
                    [e setBuffer:sink offset:0 atIndex:0];
                    [e setBuffer:t[k].a offset:0 atIndex:1];
                    [e setBytes:&n4 length:sizeof(int) atIndex:2];
                    [e dispatchThreads:MTLSizeMake((size_t)n4,1,1)
                      threadsPerThreadgroup:MTLSizeMake((size_t)tpg,1,1)];
                    break;
                case M_V0:
                    [e setBuffer:t[k].c offset:0 atIndex:0];
                    [e setBuffer:t[k].a offset:0 atIndex:1];
                    [e setBuffer:t[k].b offset:0 atIndex:2];
                    { int nn = (int)n; [e setBytes:&nn length:sizeof(int) atIndex:3]; }
                    [e dispatchThreads:MTLSizeMake((size_t)n,1,1)
                      threadsPerThreadgroup:MTLSizeMake((size_t)tpg,1,1)];
                    break;
                case M_V1:
                    [e setBuffer:t[k].c offset:0 atIndex:0];
                    [e setBuffer:t[k].a offset:0 atIndex:1];
                    [e setBuffer:t[k].b offset:0 atIndex:2];
                    [e setBytes:&n4 length:sizeof(int) atIndex:3];
                    [e dispatchThreads:MTLSizeMake((size_t)n4,1,1)
                      threadsPerThreadgroup:MTLSizeMake((size_t)tpg,1,1)];
                    break;
                case M_V2: case M_V3: {
                    [e setBuffer:t[k].c offset:0 atIndex:0];
                    [e setBuffer:t[k].a offset:0 atIndex:1];
                    [e setBuffer:t[k].b offset:0 atIndex:2];
                    int units = (m == M_V3) ? n8 : n4;
                    int g = grid < units ? grid : units;
                    [e setBytes:&units length:sizeof(int) atIndex:3];
                    [e setBytes:&g length:sizeof(int) atIndex:4];
                    [e dispatchThreads:MTLSizeMake((size_t)g,1,1)
                      threadsPerThreadgroup:MTLSizeMake((size_t)tpg,1,1)];
                    break; }
                }
                [e endEncoding];
            }
            double t0 = now_ms();
            [cb commit];
            [cb waitUntilCompleted];
            double d = now_ms() - t0;
            if (d < best) best = d;
        }
    }
    return best;
}

int main(int argc, char **argv) {
    int64_t n     = argc > 1 ? atoll(argv[1]) : 16777216;
    int maxTrip   = argc > 2 ? atoi(argv[2]) : 8;

    @autoreleasepool {
        dev = MTLCreateSystemDefaultDevice();
        queue = [dev newCommandQueue];
        NSError *err = nil;
        MTLCompileOptions *o = [[MTLCompileOptions alloc] init];
        o.languageVersion = MTLLanguageVersion3_2;
        lib = [dev newLibraryWithSource:[NSString stringWithUTF8String:SRC] options:o error:&err];
        if (!lib) { printf("compile failed: %s\n", err.description.UTF8String); return 1; }
    }
    int maxtpg = (int)dev.maxThreadsPerThreadgroup.width;
    /* a grid that fills the machine: max threads/threadgroup x a generous
     * number of threadgroups. If the device is smaller this is clamped to the
     * work available, so it is never wrong, only idle. */
    int fullgrid = maxtpg * 1024;

    printf("Metal: %s\nn = %lld floats per buffer (%.1f MB)\n"
           "maxThreadsPerThreadgroup = %d, full grid = %d\n\n",
           dev.name.UTF8String, (long long)n, n*4/1e6, maxtpg, fullgrid);

    Trip *trips = (Trip *)calloc(maxTrip, sizeof(Trip));
    for (int k = 0; k < maxTrip; k++) {
        float *a = (float *)malloc(n*4), *b = (float *)malloc(n*4), *c = (float *)malloc(n*4);
        for (int64_t j = 0; j < n; j++) { a[j] = 1.0f + (j%7)*0.01f; b[j] = 2.0f; c[j] = 0.5f; }
        trips[k].a = [dev newBufferWithBytes:a length:n*4 options:MTLResourceStorageModeShared];
        trips[k].b = [dev newBufferWithBytes:b length:n*4 options:MTLResourceStorageModeShared];
        trips[k].c = [dev newBufferWithBytes:c length:n*4 options:MTLResourceStorageModeShared];
        free(a); free(b); free(c);
    }
    id<MTLBuffer> sink = [dev newBufferWithLength:256 options:MTLResourceStorageModeShared];

    id<MTLComputePipelineState> p_copy = ps_for("k_copy");
    id<MTLComputePipelineState> p_read = ps_for("k_read");
    id<MTLComputePipelineState> p_read4 = ps_for("k_read4");
    id<MTLComputePipelineState> p_v0   = ps_for("axpy_v0");
    id<MTLComputePipelineState> p_v1   = ps_for("axpy_v1");
    id<MTLComputePipelineState> p_v2   = ps_for("axpy_v2");
    id<MTLComputePipelineState> p_v3   = ps_for("axpy_v3");

    printf("=== ceilings (1 buffer) ===\n");
    printf("%-14s %9s %10s %9s\n", "kernel", "ms", "ns/elem", "GB/s");
    double t;
    t = submit(M_COPY, p_copy, trips, 1, n, maxtpg, fullgrid, sink);
    printf("%-14s %9.3f %10.3f %9.1f\n", "k_copy", t, t*1e6/n, 8.0*n/(t*1e-3)/1e9);
    t = submit(M_READ, p_read, trips, 1, n, maxtpg, fullgrid, sink);
    printf("%-14s %9.3f %10.3f %9.1f\n", "k_read", t, t*1e6/n, 4.0*n/(t*1e-3)/1e9);

    {
        id<MTLComputePipelineState> ps1 = p_read4;
        id<MTLComputePipelineState> one[1] = { ps1 };
        (void)one;
        int n16 = (int)(n/16);
        int grid = maxtpg * 32;
        if (grid > n16) grid = n16;
        double best = 1e30;
        for (int r = 0; r < 20; r++) {
            @autoreleasepool {
                id<MTLCommandBuffer> cbx = [queue commandBuffer];
                id<MTLComputeCommandEncoder> e = [cbx computeCommandEncoder];
                [e setComputePipelineState:p_read4];
                [e setBuffer:sink offset:0 atIndex:0];
                [e setBuffer:trips[0].a offset:0 atIndex:1];
                [e setBytes:&n16 length:sizeof(int) atIndex:2];
                [e setBytes:&grid length:sizeof(int) atIndex:3];
                [e dispatchThreads:MTLSizeMake((size_t)grid,1,1)
                  threadsPerThreadgroup:MTLSizeMake((size_t)maxtpg,1,1)];
                [e endEncoding];
                double t0 = now_ms(); [cbx commit]; [cbx waitUntilCompleted];
                double d = now_ms() - t0; if (d < best) best = d;
            }
        }
        printf("%-14s %9.3f %10.3f %9.1f\n", "k_read4 (MLP)", best, best*1e6/n,
               4.0*n/(best*1e-3)/1e9);
        t = best;
    }
    printf("\n=== axpy variants (1 buffer; v0 is 12 B/elem, the rest 16) ===\n");
    printf("%-24s %9s %10s %9s %8s\n", "kernel", "ms", "ns/elem", "GB/s", "% of copy");
    struct { const char *nm; Mode m; id<MTLComputePipelineState> p; int tpg; int grid; } vs[] = {
        {"v0 compiler shape",   M_V0, p_v0, maxtpg, 0},
        {"v1 float4",           M_V1, p_v1, maxtpg, 0},
        {"v2 persistent",       M_V2, p_v2, maxtpg, fullgrid},
        {"v2 persistent tpg=64",M_V2, p_v2, 64,     fullgrid},
        {"v2 persistent tpg=128",M_V2, p_v2, 128,    fullgrid},
        {"v3 persistent x2 MLP",M_V3, p_v3, maxtpg, fullgrid},
    };
    double copy_gbs = 8.0*n/(submit(M_COPY, p_copy, trips, 1, n, maxtpg, fullgrid, sink)*1e-3)/1e9;
    double copy_ms  = submit(M_COPY, p_copy, trips, 1, n, maxtpg, fullgrid, sink);
    for (unsigned i = 0; i < sizeof(vs)/sizeof(*vs); i++) {
        double ms = submit(vs[i].m, vs[i].p, trips, 1, n, vs[i].tpg, vs[i].grid, sink);
        /* v0's body is `c[gid] = a[gid]*b[gid] + a[gid]`: it reads a and b and
           writes c, and never READS c. That is 12 B/element, not 16. The
           float4 and persistent variants were written with an explicit `cv`
           read, so they really do move 16. Counting 16 for v0 overstated its
           bandwidth by a third. */
        double bpe = (vs[i].m == M_V0) ? 12.0 : 16.0;
        double gbs = bpe*n/(ms*1e-3)/1e9;
        /* fraction of the copy ROOF: copy moves 8 B/elem, axpy moves 16, so a
           perfect axpy costs 2x a copy's time. Roof in ns/elem is 2x copy's. */
        double roof_ns = copy_ms*1e6/n*(16.0/bpe);
        printf("%-24s %9.3f %10.3f %9.1f %7.1f%%\n", vs[i].nm, ms, ms*1e6/n, gbs,
               100.0*roof_ns/(ms*1e6/n));
    }

    printf("\n=== concurrency: K independent axpys, ONE command buffer ===\n");
    printf("%6s %10s %11s %11s %10s\n", "K", "ms", "ns/elem/buf", "GB/s total", "vs K=1");
    double base = 0;
    for (int K = 1; K <= maxTrip; K *= 2) {
        double ms = submit(M_V2, p_v2, trips, K, n, maxtpg, fullgrid, sink);
        if (K == 1) base = ms;
        double elems = (double)n * K;
        printf("%6d %10.3f %11.4f %11.1f %9.2fx\n", K, ms, ms*1e6/elems,
               16.0*elems/(ms*1e-3)/1e9, base/ms);
        (void)0;
    }
    return 0;
}
