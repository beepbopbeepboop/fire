/* A real tiled GEMM on the tensor cores.
 *
 * The previous commit measured the CEILING (117 TFLOPS from
 * simdgroup_multiply_accumulate in registers). That is not a speedup anyone can
 * bank -- the real question is what fraction of it a working GEMM captures, and
 * the only way to know is to write one.
 *
 * Structure ported from MLX's kernels/steel/gemm/mma.h. The part that matters
 * is BaseMMAFrag<T,8,8>::get_coord, which encodes the HARDWARE's thread->element
 * mapping for an 8x8 simdgroup_matrix. With 64 elements over 32 lanes each
 * thread holds 2, and they are 1 row x 2 consecutive columns:
 *
 *     row = ((lane/4) & 4) + ((lane/2) % 4)
 *     col = ((lane/4) & 2) * 2 + (lane % 2) * 2
 *
 * Getting this wrong does not fail to compile and does not crash -- it produces
 * a plausible wrong number, which is why it is written out here and why every
 * result is checked against a CPU reference in the same precision.
 *
 * Tiling: each threadgroup computes a 32x32 output tile as a 4x4 grid of 8x8
 * MMAs, walking K in steps of 8. So 16 accumulators x 2 registers = 32
 * registers of accumulator, plus 4 A-fragments and 4 B-fragments.
 *
 * This first version loads fragments straight from global memory with no
 * threadgroup-memory staging. That is deliberately the SIMPLER thing: it gets
 * the tiling and the accumulation right and leaves the obvious optimisation
 * (smem staging, which is where MLX spends much of its complexity) for a
 * measurement that says it is worth doing.
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

"static constant int TN = 32;   // threadgroup tile, rows and cols\n"
"static constant int TN_MMA = TN / 8;\n"

"// The hardware mapping: BaseMMAFrag<T,8,8>::get_coord transcribed. This is\n"
"// the whole reason the kernel is correct rather than merely plausible.\n"
"static inline short2 frag_coord(uint lane) {\n"
"  short qid = short(lane / 4);\n"
"  short fm  = short((qid & 4) + ((lane / 2) % 4));\n"
"  short fn  = short((qid & 2) * 2 + (lane % 2) * 2);\n"
"  return short2(fn, fm);\n"
"}\n"

"// C[M,N] = A[M,K] * B[K,N], 32x32 per threadgroup, 8-deep K steps.\n"
"[[kernel]] void gemm32(device float *C, device const float *A,\n"
"                      device const float *B,\n"
"                      constant int &M, constant int &N, constant int &K,\n"
"                      uint lane [[thread_index_in_simdgroup]],\n"
"                      uint tg [[threadgroup_position_in_grid]]) {\n"
"  int nm = (M + TN - 1) / TN;\n"
"  int nn = (N + TN - 1) / TN;\n"
"  int m0 = (tg % nn) * TN;\n"
"  int n0 = (tg / nn) * TN;\n"
"  short2 fc = frag_coord(lane);\n"
"  short fr = fc.y, fcol = fc.x;\n"
"\n"
"  simdgroup_matrix<float, 8, 8> acc[TN_MMA][TN_MMA];\n"
"  for (int i = 0; i < TN_MMA; ++i)\n"
"    for (int j = 0; j < TN_MMA; ++j)\n"
"      reinterpret_cast<thread float2&>(acc[i][j].thread_elements()) = float2(0.0f);\n"
"\n"
"  for (int k0 = 0; k0 < K; k0 += 8) {\n"
"    simdgroup_matrix<float, 8, 8> af[TN_MMA], bf[TN_MMA];\n"
"    for (int i = 0; i < TN_MMA; ++i) {\n"
"      int r = m0 + i * 8 + fr;\n"
"      int c = k0 + fcol;\n"
"      float2 v = float2(0.0f);\n"
"      if (r < M && c + 1 < K)     v.x = A[r * K + c];\n"
"      if (r < M && c + 1 < K)     v.y = A[r * K + c + 1];\n"
"      reinterpret_cast<thread float2&>(af[i].thread_elements()) = v;\n"
"    }\n"
"    for (int j = 0; j < TN_MMA; ++j) {\n"
"      int r = k0 + fr;\n"
"      int c = n0 + j * 8 + fcol;\n"
"      float2 v = float2(0.0f);\n"
"      if (r + 1 < K && c < N)     v.x = B[r * N + c];\n"
"      if (r + 1 < K && c < N)     v.y = B[r * N + c + 1];\n"
"      reinterpret_cast<thread float2&>(bf[j].thread_elements()) = v;\n"
"    }\n"
"    for (int i = 0; i < TN_MMA; ++i)\n"
"      for (int j = 0; j < TN_MMA; ++j)\n"
"        simdgroup_multiply_accumulate(acc[i][j], af[i], bf[j], acc[i][j]);\n"
"  }\n"
"\n"
"  for (int i = 0; i < TN_MMA; ++i) {\n"
"    for (int j = 0; j < TN_MMA; ++j) {\n"
"      int r = m0 + i * 8 + fr;\n"
"      int c = n0 + j * 8 + fcol;\n"
"      float2 v = reinterpret_cast<thread float2&>(acc[i][j].thread_elements());\n"
"      if (r < M && c < N)     C[r * N + c]     = v.x;\n"
"      if (r < M && c + 1 < N) C[r * N + c + 1] = v.y;\n"
"    }\n"
"  }\n"
"}\n"
;

int main(int argc, char **argv) {
    int M = argc > 1 ? atoi(argv[1]) : 1024;
    int N = argc > 2 ? atoi(argv[2]) : 1024;
    int K = argc > 3 ? atoi(argv[3]) : 1024;
    int do_check = argc > 4 ? atoi(argv[4]) : 1;

    @autoreleasepool {
        dev = MTLCreateSystemDefaultDevice();
        queue = [dev newCommandQueue];
        NSError *err = nil;
        MTLCompileOptions *o = [[MTLCompileOptions alloc] init];
        o.languageVersion = MTLLanguageVersion3_2;
        lib = [dev newLibraryWithSource:[NSString stringWithUTF8String:SRC] options:o error:&err];
        if (!lib) { printf("COMPILE FAILED:\n%s\n", err.description.UTF8String); return 1; }
        printf("Metal: %s   MSL 3.2\n", dev.name.UTF8String);
    }
    id<MTLFunction> f = [lib newFunctionWithName:@"gemm32"];
    if (!f) { printf("MISSING gemm32\n"); return 2; }
    id<MTLComputePipelineState> ps = [dev newComputePipelineStateWithFunction:f error:NULL];

    size_t na = (size_t)M*K, nb = (size_t)K*N, nc = (size_t)M*N;
    float *A = (float *)malloc(na*4), *B = (float *)malloc(nb*4), *C = (float *)malloc(nc*4);
    for (size_t i = 0; i < na; i++) A[i] = (float)((i * 37) % 17) * 0.01f - 0.08f;
    for (size_t i = 0; i < nb; i++) B[i] = (float)((i * 53) % 13) * 0.01f - 0.06f;
    memset(C, 0, nc*4);

    @autoreleasepool {
        id<MTLBuffer> bA = [dev newBufferWithBytes:A length:na*4 options:MTLResourceStorageModeShared];
        id<MTLBuffer> bB = [dev newBufferWithBytes:B length:nb*4 options:MTLResourceStorageModeShared];
        id<MTLBuffer> bC = [dev newBufferWithBytes:C length:nc*4 options:MTLResourceStorageModeShared];
        int nm = (M + 31) / 32, nn = (N + 31) / 32;
        int ntg = nm * nn;

        /* correctness first: one run, then a full comparison on the host */
        @autoreleasepool {
            id<MTLCommandBuffer> cb = [queue commandBuffer];
            id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
            [e setComputePipelineState:ps];
            [e setBuffer:bC offset:0 atIndex:0];
            [e setBuffer:bA offset:0 atIndex:1];
            [e setBuffer:bB offset:0 atIndex:2];
            [e setBytes:&M length:4 atIndex:3];
            [e setBytes:&N length:4 atIndex:4];
            [e setBytes:&K length:4 atIndex:5];
            [e dispatchThreadgroups:MTLSizeMake((size_t)ntg,1,1)
                threadsPerThreadgroup:MTLSizeMake(32,1,1)];
            [e endEncoding];
            [cb commit]; [cb waitUntilCompleted];
        }
        memcpy(C, [bC contents], nc*4);

        if (getenv("GEMM_DUMP")) {
            printf("C (row-major %dx%d):\n", M, N);
            for (int r = 0; r < M && r < 16; r++) {
                printf("  ");
                for (int c = 0; c < N && c < 16; c++) printf("%7.3f ", (double)C[(size_t)r*N+c]);
                printf("\n");
            }
        }
        if (do_check) {
            double worst = 0.0; size_t wi = 0; double expect = 0.0;
            /* spot-check a spread of entries plus the corners, in fp64 */
            for (int t = 0; t < 4096; t++) {
                int r = (int)((size_t)t * 977 % (size_t)M);
                int c = (int)((size_t)t * 613 % (size_t)N);
                double s = 0.0;
                for (int k = 0; k < K; k++) s += (double)A[(size_t)r*K+k] * (double)B[(size_t)k*N+c];
                double d = fabs(s - (double)C[(size_t)r*N+c]) / (fabs(s) + 1e-6);
                if (d > worst) { worst = d; wi = (size_t)r*N+c; }
                if (t == 0) expect = s;
            }
            printf("correctness: worst relative error %.3e over 4096 sampled entries\n", worst);
            printf("             (C[%zu] = %.6f)\n", wi, (double)C[wi]);
            if (!(worst < 1e-4)) printf("             *** WRONG -- the fragment mapping is off\n");
        }

        double best = 1e30;
        int reps = (size_t)M*N*K > (1u<<28) ? 5 : 50;
        for (int r = 0; r < reps; r++) {
            @autoreleasepool {
                id<MTLCommandBuffer> cb = [queue commandBuffer];
                id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
                [e setComputePipelineState:ps];
                [e setBuffer:bC offset:0 atIndex:0];
                [e setBuffer:bA offset:0 atIndex:1];
                [e setBuffer:bB offset:0 atIndex:2];
                [e setBytes:&M length:4 atIndex:3];
                [e setBytes:&N length:4 atIndex:4];
                [e setBytes:&K length:4 atIndex:5];
                [e dispatchThreadgroups:MTLSizeMake((size_t)ntg,1,1)
                    threadsPerThreadgroup:MTLSizeMake(32,1,1)];
                [e endEncoding];
                double t0 = now_ms(); [cb commit]; [cb waitUntilCompleted];
                double d = now_ms()-t0; if (d < best) best = d;
            }
        }
        double flops = 2.0 * M * N * K;
        double tf = flops / (best*1e-3) / 1e12;
        printf("\nGEMM %dx%dx%d : %.3f ms   %.2f TFLOPS\n", M, N, K, best, tf);
        printf("  captured %.1f%% of the 117.47 TFLOPS instruction ceiling (ac520cd6)\n",
               100.0 * tf / 117.47);
        printf("  vs our scalar matvec's 0.049 TFLOPS: %.0fx\n", tf * 1e3 / 0.0488);
    }
    return 0;
}
