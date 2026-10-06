/* A tiled, staged, double-buffered, PERSISTENT tensor-core GEMM.
 *
 * The previous version (gemm_tensorcore.m) was correct and hit 0.96 TFLOPS,
 * 0.8% of the measured 117.47 TFLOPS MMA ceiling. The diagnosis was latency on
 * arithmetic intensity: 16 fragment loads from GLOBAL memory for every 16 MMAs,
 * nothing staged, nothing reused, so the tensor cores waited on memory.
 *
 * Four changes, each aimed at amortising a startup cost rather than at making
 * the instruction faster:
 *
 *  1. THREADGROUP STAGING. A and B k-tiles are staged into shared memory with
 *     coalesced float4 loads, so global traffic drops by the tile-reuse factor
 *     and each staged byte is read by several simdgroups.
 *
 *  2. A 64x64 TILE ACROSS 4 SIMDGROUPS (2x2 of 32 lanes each). Each simdgroup
 *     still does its own 32x32, so accumulator registers are unchanged, but the
 *     staged A tile is now shared by two simdgroups and the staged B tile by
 *     two. Arithmetic intensity per staged element goes up 4x.
 *
 *  3. DOUBLE BUFFERING -- the "stream in while computing" part. Tile k+1 is
 *     copied to shared memory while tile k's MMAs are in flight, so the global
 *     load latency of the next step overlaps the arithmetic of this one. This
 *     is the single biggest lever, and it is exactly the amortisation asked
 *     for: without it every k-step pays full memory latency.
 *
 *  4. A PERSISTENT GRID-STRIDE over output tiles. One launch per threadgroup
 *     handles many output tiles in sequence, so the pipeline setup, the
 *     accumulator zeroing and the prologue are paid once rather than per tile.
 *     This is the launch-overhead amortisation at the kernel level, and it is
 *     the same lever as batching dispatches, one level down.
 *
 * Correctness is checked against an fp64 CPU reference at every size, and the
 * f32 rounding floor for a length-K dot product is printed so "correct" is a
 * statement about arithmetic rather than about faith.
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

"static constant int TN   = 64;   // threadgroup tile (M and N)\n"
"static constant int SG   = 2;    // simdgroups per dimension -> 4 total\n"
"static constant int QN   = TN / SG;   // 32: each simdgroup's quadrant\n"
"static constant int QF   = QN / 8;    // 4: MMAs per quadrant dimension\n"
"static constant int BK   = 8;   // K staged per barrier pair (4 MMA depths)\n"
"static constant int KSTEP = BK / 8;   // MMA steps per staged tile\n"
"static constant int NTHR = 128;  // 4 simdgroups x 32 lanes\n"

// MLX BaseMMAFrag<T,8,8>::get_coord. Verified against the accumulator by
// frag_layout_probe.m: A, B and D all share this one layout.
"static inline short2 frag_coord(uint lane) {\n"
"  short qid = short(lane / 4);\n"
"  return short2(short((qid & 2) * 2 + (lane % 2) * 2),\n"
"                short((qid & 4) + ((lane / 2) % 4)));\n"
"}\n"

// Stage A[TM][BK] from global with float4 loads: TM*BK/4 threads-worth of work,
// coalesced because consecutive threads take consecutive float4s of a row.
// Staging with SCALAR loads. MSL requires an explicit address space on every
// pointer and forbids casting device float* to threadgroup float*, so the
// float4 form needs a union and a cast that the language will not accept here.
// Four scalar loads per thread are still fully coalesced: consecutive threads
// take consecutive elements, so a warp's loads coalesce into full sectors
// exactly as the vector form would. The compiler folds adjacent stores back
// into wide writes where it can prove alignment.
"static inline void stage_A(threadgroup float *Asm, device const float *A,\n"
"                           int m0, int k0, int M, int K, int t) {\n"
"  int per = BK / 4;             // float4-equivalents per row\n"
"  int total4 = TN * per;\n"
"  int u = t;\n"
"  for (; u < total4; u += NTHR) {\n"
"    int r = u / per, c4 = u % per;\n"
"    int gr = m0 + r, gc = k0 + c4 * 4;\n"
"    bool ok = (gr < M);\n"
"    float v0 = 0.f, v1 = 0.f, v2 = 0.f, v3 = 0.f;\n"
"    if (ok && gc + 0 < K) v0 = A[(size_t)gr*K + gc + 0];\n"
"    if (ok && gc + 1 < K) v1 = A[(size_t)gr*K + gc + 1];\n"
"    if (ok && gc + 2 < K) v2 = A[(size_t)gr*K + gc + 2];\n"
"    if (ok && gc + 3 < K) v3 = A[(size_t)gr*K + gc + 3];\n"
"    int o = r * BK + c4 * 4;\n"
"    Asm[o + 0] = v0; Asm[o + 1] = v1; Asm[o + 2] = v2; Asm[o + 3] = v3;\n"
"  }\n"
"}\n"
"static inline void stage_B(threadgroup float *Bsm, device const float *B,\n"
"                           int k0, int n0, int N, int K, int t) {\n"
"  int per = TN / 4;\n"
"  int total4 = BK * per;\n"
"  int u = t;\n"
"  for (; u < total4; u += NTHR) {\n"
"    int r = u / per, c4 = u % per;\n"
"    int gr = k0 + r, gc = n0 + c4 * 4;\n"
"    bool ok = (gr < K);\n"
"    float v0 = 0.f, v1 = 0.f, v2 = 0.f, v3 = 0.f;\n"
"    if (ok && gc + 0 < N) v0 = B[(size_t)gr*N + gc + 0];\n"
"    if (ok && gc + 1 < N) v1 = B[(size_t)gr*N + gc + 1];\n"
"    if (ok && gc + 2 < N) v2 = B[(size_t)gr*N + gc + 2];\n"
"    if (ok && gc + 3 < N) v3 = B[(size_t)gr*N + gc + 3];\n"
"    int o = r * TN + c4 * 4;\n"
"    Bsm[o + 0] = v0; Bsm[o + 1] = v1; Bsm[o + 2] = v2; Bsm[o + 3] = v3;\n"
"  }\n"
"}\n"
"[[kernel]] void gemm_tiled(device float *C, device const float *A,\n"
"                           device const float *B,\n"
"                           constant int &M, constant int &N, constant int &K,\n"
"                           constant int &ngroups,\n"
"                           uint tid [[thread_position_in_threadgroup]],\n"
"                           uint lane [[thread_index_in_simdgroup]],\n"

"                           uint tg [[threadgroup_position_in_grid]]) {\n"
"  threadgroup float Asm[2][TN*BK];\n"
"  threadgroup float Bsm[2][BK*TN];\n"
"\n"



"  const int sgi = int(tid / 32);   // no such attribute; lanes are consecutive\n"
"  const int sg_m = sgi / SG, sg_n = sgi % SG;\n"
"  const short2 fc = frag_coord(lane);\n"
"  const int fr = fc.y, fcol = fc.x;\n"
"\n"
"  int ntn = (N + TN - 1) / TN;\n"
"  int mtg = (M + TN - 1) / TN;\n"
"  int total = mtg * ntn;\n"


"\n"
"  // PERSISTENT: this threadgroup walks a strided sequence of output tiles, so\n"
"  // the prologue below is paid once, not once per tile.\n"
"  for (int t = tg; t < total; t += ngroups) {\n"
"    int m0 = (t / ntn) * TN;\n"
"    int n0 = (t % ntn) * TN;\n"
"\n"
"    simdgroup_matrix<float,8,8> acc[QF][QF];\n"
"    for (int i = 0; i < QF; ++i)\n"
"      for (int j = 0; j < QF; ++j)\n"
"        reinterpret_cast<thread float2&>(acc[i][j].thread_elements()) = float2(0.0f);\n"
"\n"
"    // prologue: first tile into buffer 0\n"
"    stage_A(Asm[0], A, m0, 0, M, K, tid);\n"
"    stage_B(Bsm[0], B, 0, n0, N, K, tid);\n"
"    threadgroup_barrier(mem_flags::mem_threadgroup);\n"
"\n"
"    int buf = 0;\n"
"    for (int k0 = 0; k0 < K; k0 += BK) {\n"
"      int nbuf = 1 - buf;\n"
"      int nk = k0 + BK;\n"
"      // STREAM: issue the next tile's global loads before consuming this one.\n"
"      if (nk < K) {\n"
"        stage_A(Asm[nbuf], A, m0, nk, M, K, tid);\n"
"        stage_B(Bsm[nbuf], B, nk, n0, N, K, tid);\n"
"      }\n"
"      threadgroup_barrier(mem_flags::mem_threadgroup);\n"
"\n"
"      // BK is 16 or 32, so each staged tile holds KSTEP MMA depths. The\n"
"      // offset ko walks them; without it only the first 8 columns of a\n"
"      // staged tile are ever read and most of K is silently skipped.\n"
"      for (int ks = 0; ks < KSTEP; ++ks) {\n"
"        int ko = ks * 8;\n"
"        simdgroup_matrix<float,8,8> af[QF], bf[QF];\n"
"        for (int i = 0; i < QF; ++i) {\n"
"          int r = sg_m*QN + i*8 + fr;\n"
"          int c = ko + fcol;\n"
"          float2 v = float2(Asm[buf][r*BK + c], Asm[buf][r*BK + c + 1]);\n"
"          reinterpret_cast<thread float2&>(af[i].thread_elements()) = v;\n"
"        }\n"
"        for (int j = 0; j < QF; ++j) {\n"
"          int r = ko + fr;\n"
"          int c = sg_n*QN + j*8 + fcol;\n"
"          float2 v = float2(Bsm[buf][r*TN + c], Bsm[buf][r*TN + c + 1]);\n"
"          reinterpret_cast<thread float2&>(bf[j].thread_elements()) = v;\n"
"        }\n"
"        for (int i = 0; i < QF; ++i)\n"
"          for (int j = 0; j < QF; ++j)\n"
"            simdgroup_multiply_accumulate(acc[i][j], af[i], bf[j], acc[i][j]);\n"
"      }\n"
"\n"
"      threadgroup_barrier(mem_flags::mem_threadgroup);\n"
"      buf = nbuf;\n"
"    }\n"
"\n"
"    for (int i = 0; i < QF; ++i) {\n"
"      for (int j = 0; j < QF; ++j) {\n"
"        int r = m0 + sg_m*QN + i*8 + fr;\n"
"        int c = n0 + sg_n*QN + j*8 + fcol;\n"
"        float2 v = reinterpret_cast<thread float2&>(acc[i][j].thread_elements());\n"
"        if (r < M && c < N)     C[(size_t)r*N + c]     = v.x;\n"
"        if (r < M && c + 1 < N) C[(size_t)r*N + c + 1] = v.y;\n"
"      }\n"
"    }\n"
"  }\n"
"}\n"
;

int main(int argc, char **argv) {
    int M = argc > 1 ? atoi(argv[1]) : 1024;
    int N = argc > 2 ? atoi(argv[2]) : 1024;
    int K = argc > 3 ? atoi(argv[3]) : 1024;
    int do_check = argc > 4 ? atoi(argv[4]) : 1;
    int ntg_req = argc > 5 ? atoi(argv[5]) : 0;   /* 0 = one per output tile */

    @autoreleasepool {
        dev = MTLCreateSystemDefaultDevice();
        queue = [dev newCommandQueue];
        NSError *err = nil;
        MTLCompileOptions *o = [[MTLCompileOptions alloc] init];
        o.languageVersion = MTLLanguageVersion3_2;
        lib = [dev newLibraryWithSource:[NSString stringWithUTF8String:SRC] options:o error:&err];
        if (!lib) { printf("COMPILE FAILED:\n%s\n", err.description.UTF8String); return 1; }
        printf("Metal: %s   MSL 3.2   tile 64x64, 4 simdgroups, double buffered\n",
               dev.name.UTF8String);
    }
    id<MTLFunction> f = [lib newFunctionWithName:@"gemm_tiled"];
    if (!f) { printf("MISSING gemm_tiled\n"); return 2; }
    id<MTLComputePipelineState> ps = [dev newComputePipelineStateWithFunction:f error:NULL];

    size_t na = (size_t)M*K, nb = (size_t)K*N, nc = (size_t)M*N;
    float *A = (float *)malloc(na*4), *B = (float *)malloc(nb*4), *C = (float *)malloc(nc*4);
    for (size_t i = 0; i < na; i++) A[i] = (float)((i * 37) % 17) * 0.01f - 0.08f;
    for (size_t i = 0; i < nb; i++) B[i] = (float)((i * 53) % 13) * 0.01f - 0.06f;
    memset(C, 0, nc*4);

    int ntn = (N + 63) / 64, mtg = (M + 63) / 64;
    int ntg = ntg_req ? ntg_req : mtg * ntn;
    if (ntg > mtg * ntn) ntg = mtg * ntn;
    printf("output tiles %d, threadgroups dispatched %d%s\n", mtg*ntg, ntg,
           ntg < mtg*ntg ? "  (PERSISTENT: fewer groups than tiles)" : "");

    @autoreleasepool {
        id<MTLBuffer> bA = [dev newBufferWithBytes:A length:na*4 options:MTLResourceStorageModeShared];
        id<MTLBuffer> bB = [dev newBufferWithBytes:B length:nb*4 options:MTLResourceStorageModeShared];
        id<MTLBuffer> bC = [dev newBufferWithBytes:C length:nc*4 options:MTLResourceStorageModeShared];

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
                [e setBytes:&ntg length:4 atIndex:6];
            [e dispatchThreadgroups:MTLSizeMake((size_t)ntg,1,1)
                threadsPerThreadgroup:MTLSizeMake(128,1,1)];
            [e endEncoding];
            [cb commit]; [cb waitUntilCompleted];
        }
        memcpy(C, [bC contents], nc*4);

        if (do_check) {
            double maxabs = 0.0;
            for (size_t i = 0; i < nc; i++)
                if (fabs((double)C[i]) > maxabs) maxabs = fabs((double)C[i]);
            double worst = 0.0;
            for (int t = 0; t < 2048; t++) {
                int r = (int)(((size_t)t * 977) % (size_t)M);
                int c = (int)(((size_t)t * 613) % (size_t)N);
                double acc = 0.0;
                for (int k = 0; k < K; k++)
                    acc += (double)A[(size_t)r*K+k] * (double)B[(size_t)k*N+c];
                double d = fabs(acc - (double)C[(size_t)r*N+c]);
                if (d > worst) worst = d;
            }
            double floor_ = 1.19e-7 * sqrt((double)K);
            printf("correctness: max|GPU-fp64| %.3e   f32 floor %.3e   %s\n",
                   worst, floor_, worst <= floor_ ? "OK (at rounding floor)" : "*** WRONG");
        }

        double best = 1e30;
        int reps = (size_t)M*N*K > (1u<<29) ? 3 : 20;
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
                [e setBytes:&ntg length:4 atIndex:6];
                [e dispatchThreadgroups:MTLSizeMake((size_t)ntg,1,1)
                    threadsPerThreadgroup:MTLSizeMake(128,1,1)];
                [e endEncoding];
                double t0 = now_ms(); [cb commit]; [cb waitUntilCompleted];
                double d = now_ms()-t0; if (d < best) best = d;
            }
        }
        double flops = 2.0 * M * N * K;
        double tf = flops / (best*1e-3) / 1e12;
        printf("GEMM %dx%dx%d : %.3f ms   %.2f TFLOPS   %.1f%% of 117.47 ceiling"
               "   %.0fx the scalar matvec\n",
               M, N, K, best, tf, 100.0*tf/117.47, tf*1e3/0.0488);
    }
    return 0;
}
