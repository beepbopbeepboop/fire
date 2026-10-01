/* Where does each lane's thread_elements actually LAND?
 *
 * The GEMM is wrong in a way that says the mapping is nearly right: with
 * A=identity, B=ones, C came out all-ones EXCEPT row 7. So rows 0-6 are right
 * and row 7 is never reached. Guessing at transposes has not resolved it, so
 * measure it.
 *
 * Each lane puts 100*lane+1 and 100*lane+2 into its two fragment elements, B is
 * all ones, so row r of C is the SUM of the two values belonging to row r. Read
 * the sums back and the mapping is determined, not guessed.
 */
#include <stdio.h>
#include <stdlib.h>
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>

static const char *SRC =
"#include <metal_stdlib>\n"
"#include <metal_simdgroup_matrix>\n"
"using namespace metal;\n"
"[[kernel]] void probe(device float *out, uint lane [[thread_index_in_simdgroup]]) {\n"
"  simdgroup_matrix<float,8,8> A, B, C;\n"
"  reinterpret_cast<thread float2&>(A.thread_elements()) = float2(100.0f*lane + 1.0f, 100.0f*lane + 2.0f);\n"
"  for (int k = 0; k < 2; ++k) {\n"
"    reinterpret_cast<thread float2&>(B.thread_elements()) = float2(1.0f, 1.0f);\n"
"  }\n"
"  reinterpret_cast<thread float2&>(C.thread_elements()) = float2(0.0f);\n"
"  simdgroup_multiply_accumulate(C, A, B, C);\n"
"  // publish this lane's two accumulator values at a lane-indexed slot\n"
"  float2 c = reinterpret_cast<thread float2&>(C.thread_elements());\n"
"  ((device float *)out)[2*lane]     = c.x;\n"
"  ((device float *)out)[2*lane + 1] = c.y;\n"
"}\n"
;
int main(void) {
    id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
    id<MTLCommandQueue> q = [dev newCommandQueue];
    NSError *err = nil;
    MTLCompileOptions *o = [[MTLCompileOptions alloc] init];
    o.languageVersion = MTLLanguageVersion3_2;
    id<MTLLibrary> lib = [dev newLibraryWithSource:[NSString stringWithUTF8String:SRC]
                                options:o error:&err];
    if (!lib) { printf("COMPILE FAILED: %s\n", err.description.UTF8String); return 1; }
    id<MTLFunction> f = [lib newFunctionWithName:@"probe"];
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
    printf("lane -> the two values its fragment contributed (row sums are these):\n");
    for (int l = 0; l < 32; l++) printf("  lane %2d: %8.1f %8.1f\n", l, out[2*l], out[2*l+1]);
    /* regroup: which lane-pairs sum to which value? */
    printf("\nrows implied by pairing (each lane's 2 values must land in one row):\n");
    for (int l = 0; l < 32; l += 2)
        printf("  lanes %2d,%2d -> %.1f\n", l, l+1, out[2*l] + out[2*l+1]);
    return 0;
}
