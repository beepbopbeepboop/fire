/* Read the ACCUMULATOR's fragment layout back, rather than assume it matches A's.
 *
 * The GEMM in gemm_tensorcore.m is exact for rows 0-6 and identically zero for
 * row 7. A's layout is MLX's BaseMMAFrag<T,8,8>::get_coord, transcribed and
 * verified; the A fragment demonstrably reaches the MMA. So the operand never
 * read back is D, the accumulator.
 *
 * Two probes identify D's rows and columns BY VALUE, which needs no assumption
 * about the layout at all:
 *
 *   ROWS: A[r][k] = 100r + k + 1  (distinct per element), B = all ones.
 *         Then D[r][c] = sum_k A[r][k] = 100r + 44, a value that identifies r
 *         and is the same for all 8 columns of that row. Whatever layout D
 *         has, each lane's two reads come back tagged with their row.
 *
 *   COLS: A = all ones, B[k][c] = 100k + c + 1.
 *         Then D[r][c] = sum_k B[k][c] = 232 + 8c, which identifies c.
 *
 * Together they give the full thread -> (row, col) map for D. Both A and B are
 * written with the KNOWN mapping, so the probe cannot be circular.
 */
#include <stdio.h>
#include <stdlib.h>
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>

static const char *SRC =
"#include <metal_stdlib>\n"
"#include <metal_simdgroup_matrix>\n"
"using namespace metal;\n"

// MLX BaseMMAFrag<T,8,8>::get_coord, transcribed.
"static inline short2 known_coord(uint lane) {\n"
"  short qid = short(lane / 4);\n"
"  short fm  = short((qid & 4) + ((lane / 2) % 4));\n"
"  short fn  = short((qid & 2) * 2 + (lane % 2) * 2);\n"
"  return short2(fn, fm);\n"
"}\n"

"[[kernel]] void probe_rows(device float *out, uint lane [[thread_index_in_simdgroup]]) {\n"
"  short2 c = known_coord(lane);\n"
"  simdgroup_matrix<float,8,8> A, B, D;\n"
"  // A[r][k] = 100r + k + 1, written with the KNOWN mapping\n"
"  reinterpret_cast<thread float2&>(A.thread_elements()) =\n"
"      float2(100.0f*c.y + c.x + 1.0f, 100.0f*c.y + c.x + 2.0f);\n"
"  // B = all ones: every lane writes 1 at its own two positions\n"
"  reinterpret_cast<thread float2&>(B.thread_elements()) = float2(1.0f, 1.0f);\n"
"  reinterpret_cast<thread float2&>(D.thread_elements()) = float2(0.0f);\n"
"  simdgroup_multiply_accumulate(D, A, B, D);\n"
"  float2 d = reinterpret_cast<thread float2&>(D.thread_elements());\n"
"  ((device float *)out)[2*lane]     = d.x;\n"
"  ((device float *)out)[2*lane + 1] = d.y;\n"
"}\n"

"[[kernel]] void probe_cols(device float *out, uint lane [[thread_index_in_simdgroup]]) {\n"
"  short2 c = known_coord(lane);\n"
"  simdgroup_matrix<float,8,8> A, B, D;\n"
"  reinterpret_cast<thread float2&>(A.thread_elements()) = float2(1.0f, 1.0f);\n"
"  // B[k][c] = 100k + c + 1, same KNOWN mapping\n"
"  reinterpret_cast<thread float2&>(B.thread_elements()) =\n"
"      float2(100.0f*c.y + c.x + 1.0f, 100.0f*c.y + c.x + 2.0f);\n"
"  reinterpret_cast<thread float2&>(D.thread_elements()) = float2(0.0f);\n"
"  simdgroup_multiply_accumulate(D, A, B, D);\n"
"  float2 d = reinterpret_cast<thread float2&>(D.thread_elements());\n"
"  ((device float *)out)[2*lane]     = d.x;\n"
"  ((device float *)out)[2*lane + 1] = d.y;\n"
"}\n"
;

static float run(id<MTLDevice> dev, id<MTLCommandQueue> q, id<MTLLibrary> lib,
                 const char *name) {
    id<MTLFunction> f = [lib newFunctionWithName:[NSString stringWithUTF8String:name]];
    if (!f) { fprintf(stderr, "missing %s\n", name); exit(2); }
    id<MTLComputePipelineState> ps = [dev newComputePipelineStateWithFunction:f error:NULL];
    float out[64];
    @autoreleasepool {
        id<MTLBuffer> b = [dev newBufferWithLength:sizeof(out) options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> cb = [q commandBuffer];
        id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
        [e setComputePipelineState:ps];
        [e setBuffer:b offset:0 atIndex:0];
        [e dispatchThreadgroups:MTLSizeMake(1,1,1) threadsPerThreadgroup:MTLSizeMake(32,1,1)];
        [e endEncoding]; [cb commit]; [cb waitUntilCompleted];
        memcpy(out, [b contents], sizeof(out));
    }
    return out[0];   /* caller re-runs for the full array; see below */
}

int main(void) {
    id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
    id<MTLCommandQueue> q = [dev newCommandQueue];
    NSError *err = nil;
    MTLCompileOptions *o = [[MTLCompileOptions alloc] init];
    o.languageVersion = MTLLanguageVersion3_2;
    id<MTLLibrary> lib = [dev newLibraryWithSource:[NSString stringWithUTF8String:SRC]
                                options:o error:&err];
    if (!lib) { printf("COMPILE FAILED:\n%s\n", err.description.UTF8String); return 1; }

    struct { const char *name; const char *label; double base; const char *what; } probes[] = {
        {"probe_rows", "ROWS", 36.0,  "D[r][c] = 800r + 36"},
        {"probe_cols", "COLS", 2808.0, "D[r][c] = 2808 + 8c"},
    };
    for (int pi = 0; pi < 2; pi++) {
        id<MTLFunction> f = [lib newFunctionWithName:
            [NSString stringWithUTF8String:probes[pi].name]];
        id<MTLComputePipelineState> ps =
            [dev newComputePipelineStateWithFunction:f error:NULL];
        float out[64];
        @autoreleasepool {
            id<MTLBuffer> b = [dev newBufferWithLength:sizeof(out)
                                options:MTLResourceStorageModeShared];
            id<MTLCommandBuffer> cb = [q commandBuffer];
            id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
            [e setComputePipelineState:ps];
            [e setBuffer:b offset:0 atIndex:0];
            [e dispatchThreadgroups:MTLSizeMake(1,1,1)
                threadsPerThreadgroup:MTLSizeMake(32,1,1)];
            [e endEncoding]; [cb commit]; [cb waitUntilCompleted];
            memcpy(out, [b contents], sizeof(out));
        }
        printf("\n=== %s probe:  %s ===\n", probes[pi].label, probes[pi].what);
        printf("lane  assumed(fm,fn)   D elem0 -> %-4s  D elem1 -> %-4s   %s\n",
               "row/col", "row/col", "");
        for (int l = 0; l < 32; l++) {
            int qid = l / 4;
            int fm = (qid & 4) + ((l / 2) % 4);
            int fn = (qid & 2) * 2 + (l % 2) * 2;
            int idx0 = (int)lround((out[2*l]   - probes[pi].base) / (pi==0 ? 800.0 : 8.0));
            int idx1 = (int)lround((out[2*l+1] - probes[pi].base) / (pi==0 ? 800.0 : 8.0));
            const char *tag = "";
            if (pi == 0) {
                int a0 = fm, a1 = fm;                 /* assumed: same row */
                tag = (idx0 == a0 && idx1 == a1) ? "ok" : "MISMATCH";
            } else {
                int a0 = fn, a1 = fn + 1;             /* assumed: fn, fn+1 */
                tag = (idx0 == a0 && idx1 == a1) ? "ok" : "MISMATCH";
            }
            printf("%4d  (%d,%d)        %-14d %-14d %s\n", l, fm, fn, idx0, idx1, tag);
        }
    }
    return 0;
}
