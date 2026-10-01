/* Is the 1000x real? Measure the tensor cores before building anything on them.
 *
 * Previous commit established the machine's GENERAL-PURPOSE ALU ceiling at
 * ~11.9 TFLOPS (fp32/fp16/bf16 all identical), and our scalar matvec at
 * 48.8 GFLOP/s -- 0.4% of it. The claim is that the MATRIX CORES are
 * dramatically faster, which is a different instruction:
 * `simdgroup_multiply_accumulate` on `simdgroup_matrix<T,8,8>`, the same
 * primitive MLX's GEMM uses (kernels/steel/gemm/mma.h).
 *
 * This is a MICRO-BENMARKMARK on purpose: back-to-back MMAs with every operand
 * already in registers, so it measures the instruction, not memory, not tiling,
 * not a GEMM. It answers one question -- what is the ceiling -- and the answer
 * decides whether writing a tiled GEMM is worth the day.
 *
 * Layout note: the thread->element mapping of an 8x8 simdgroup_matrix is fixed
 * by hardware. For a THROUGHPUT measurement it does not matter what values each
 * thread holds, only that the MMAs are not optimised away -- so the store at the
 * end is unconditional and per-thread, which is the same fix the compute-peak
 * probe needed.
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
"#include <metal_simdgroup_matrix>\n"
"using namespace metal;\n"
"// Back-to-back simdgroup_multiply_accumulate, every operand already in\n"
"// registers. Measures the INSTRUCTION, not memory, not tiling.\n"
"// 8 independent accumulator chains so the tensor cores are fed rather than\n"
"// serialised on one dependency. Each 8x8x8 MMA is 2*8*8*8 = 1024 FLOP.\n"
"[[kernel]] void mmapeak_f32(device float *sink, constant int &iters,\n"
"    uint gid [[thread_position_in_grid]], uint lane [[thread_index_in_simdgroup]]) {\n"
"  simdgroup_matrix<float, 8, 8> acc[8];\n"
"  simdgroup_matrix<float, 8, 8> A, B, C;\n"
"  // Every operand INITIALISED. Left uninitialised the first run reported\n"
"  // 2660 TFLOPS -- ~200x above the machine's spec -- because the compiler\n"
"  // could treat the whole loop as undefined. A throughput number above\n"
"  // hardware is the tell that you measured nothing.\n"
"  for (int k = 0; k < 8; ++k) {\n"
"    reinterpret_cast<thread float2&>(acc[k].thread_elements()) = float2(0.5f + k, 0.25f);\n"
"  }\n"
"  reinterpret_cast<thread float2&>(A.thread_elements()) = float2(1.001f, 0.999f);\n"
"  reinterpret_cast<thread float2&>(B.thread_elements()) = float2(0.998f, 1.002f);\n"
"  reinterpret_cast<thread float2&>(C.thread_elements()) = float2(0.5f, 0.5f);\n"
"  for (int it = 0; it < iters; ++it) {\n"
"    reinterpret_cast<thread float2&>(B.thread_elements()) =\n"
"        float2(0.998f + it * 1e-6f, 1.002f);\n"
"    _Pragma(\"clang loop unroll(full)\")\n"
"    for (int k = 0; k < 8; ++k) {\n"
"      simdgroup_multiply_accumulate(acc[k], A, B, C);\n"
"    }\n"
"  }\n"
"  float s = 0.0f;\n"
"  _Pragma(\"clang loop unroll(full)\")\n"
"  for (int k = 0; k < 8; ++k) {\n"
"    float2 t = reinterpret_cast<thread float2&>(acc[k].thread_elements());\n"
"    s += t.x + t.y;\n"
"  }\n"
"  ((device float *)sink)[gid] = s;\n"
"}\n"
"[[kernel]] void mmapeak_f16(device float *sink, constant int &iters,\n"
"    uint gid [[thread_position_in_grid]], uint lane [[thread_index_in_simdgroup]]) {\n"
"  simdgroup_matrix<half, 8, 8> acc[8];\n"
"  simdgroup_matrix<half, 8, 8> A, B, C;\n"
"  for (int k = 0; k < 8; ++k) {\n"
"    reinterpret_cast<thread half2&>(acc[k].thread_elements()) = half2(half(0.5f + k), half(0.25f));\n"
"  }\n"
"  reinterpret_cast<thread half2&>(A.thread_elements()) = half2(half(1.001f), half(0.999f));\n"
"  reinterpret_cast<thread half2&>(B.thread_elements()) = half2(half(0.998f), half(1.002f));\n"
"  reinterpret_cast<thread half2&>(C.thread_elements()) = half2(half(0.5f), half(0.5f));\n"
"  for (int it = 0; it < iters; ++it) {\n"
"    reinterpret_cast<thread float2&>(B.thread_elements()) =\n"
"        float2(0.998f + it * 1e-6f, 1.002f);\n"
"    _Pragma(\"clang loop unroll(full)\")\n"
"    for (int k = 0; k < 8; ++k) {\n"
"      simdgroup_multiply_accumulate(acc[k], A, B, C);\n"
"    }\n"
"  }\n"
"  float s = 0.0f;\n"
"  _Pragma(\"clang loop unroll(full)\")\n"
"  for (int k = 0; k < 8; ++k) {\n"
"    half2 t = reinterpret_cast<thread half2&>(acc[k].thread_elements());\n"
"    s += float(t.x) + float(t.y);\n"
"  }\n"
"  ((device float *)sink)[gid] = s;\n"
"}\n"
;

static id<MTLComputePipelineState> ps(const char *n) {
    id<MTLFunction> f = [lib newFunctionWithName:[NSString stringWithUTF8String:n]];
    if (!f) { fprintf(stderr, "MISSING: %s\n", n); exit(2); }
    return [dev newComputePipelineStateWithFunction:f error:NULL];
}

int main(int argc, char **argv) {
    int iters = argc > 1 ? atoi(argv[1]) : 20000;
    @autoreleasepool {
        dev = MTLCreateSystemDefaultDevice();
        queue = [dev newCommandQueue];
        NSError *err = nil;
        MTLCompileOptions *o = [[MTLCompileOptions alloc] init];
        o.languageVersion = MTLLanguageVersion3_2;
        lib = [dev newLibraryWithSource:[NSString stringWithUTF8String:SRC] options:o error:&err];
        if (!lib) { printf("COMPILE FAILED:\n%s\n", err.description.UTF8String); return 1; }
        printf("Metal: %s   MSL 3.2\n", dev.name.UTF8String);
        printf("iters = %d per thread\n", iters);
    }

    /* A 32-wide simdgroup is one hardware matrix unit; launch a whole number of
       simdgroups and count MMA ops from that. */
    const int nthreads = 1 << 20;
    id<MTLBuffer> sink = [dev newBufferWithLength:(size_t)nthreads*4
                            options:MTLResourceStorageModeShared];

    printf("\n=== tensor-core peak: simdgroup_multiply_accumulate, all in registers ===\n");
    printf("%-6s %12s %12s %14s %12s\n", "prec", "TFLOPS", "vs ALU fp32", "MMA ops", "elapsed");
    double alu = 11856.8;   /* measured in 596044cd, GFLOP/s */
    struct { const char *kn; const char *fn; } v[] = {
        {"fp32", "mmapeak_f32"}, {"fp16", "mmapeak_f16"},
    };
    for (int i = 0; i < 2; i++) {
        id<MTLComputePipelineState> p;
        @autoreleasepool { p = ps(v[i].fn); }
        double best = 1e30;
        for (int r = 0; r < 5; r++) {
            @autoreleasepool {
                id<MTLCommandBuffer> cb = [queue commandBuffer];
                id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
                [e setComputePipelineState:p];
                [e setBuffer:sink offset:0 atIndex:0];
                [e setBytes:&iters length:4 atIndex:1];
                [e dispatchThreads:MTLSizeMake((size_t)nthreads,1,1)
                  threadsPerThreadgroup:MTLSizeMake(256,1,1)];
                [e endEncoding];
                double t0 = now_ms(); [cb commit]; [cb waitUntilCompleted];
                double d = now_ms()-t0; if (d < best) best = d;
            }
        }
        /* 8 chained MMAs per iteration, each 2*8*8*8 = 1024 FLOP, and ONE MMA
           is a SIMDGROUP operation: all 32 lanes cooperate on it. Counting it
           per thread overstated TFLOPS by 32x, which is how the first
           corrected-looking run still claimed 3758 TFLOP/s. */
        double flops = 8.0 * 1024.0 * iters * (nthreads / 32.0);
        double tf = flops / (best*1e-3) / 1e12;
        float sample = ((float *)[sink contents])[0];
        printf("%-6s %12.2f %11.1fx %14.3g  ms=%8.2f sample=%.4g%s\n", v[i].kn, tf,
               tf*1e3/alu, 8.0*iters*nthreads/32.0, best, sample,
               isfinite(sample) && fabsf(sample) > 0 ? "" : "   <-- NOT REAL");
    }
    printf("\n(vs ALU fp32 compares tensor-core TFLOPS with the 11.86 TFLOP/s\n"
           " general-purpose FMA ceiling measured in 596044cd.)\n");
    return 0;
}
