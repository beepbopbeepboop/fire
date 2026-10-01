// Achievable memory bandwidth on this GPU, so the GEMM's roofline ceiling can
// be computed instead of guessed. Streaming read+write, no compute.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <mach/mach_time.h>
static double now_ms(void){static mach_timebase_info_data_t tb;
  if(!tb.denom)mach_timebase_info(&tb);
  return (double)mach_absolute_time()*tb.numer/tb.denom/1e6;}

static const char *SRC =
"#include <metal_stdlib>\n"
"using namespace metal;\n"
"kernel void copyk(device const float *A, device float *B, constant int &n,\n"
"                  uint gid [[thread_position_in_grid]]) {\n"
"  if (gid < (uint)n) B[gid] = A[gid] * 1.0000001f;\n"
"}\n"
// float4 version: a scalar copy never reaches peak, because each thread issues
// one 4-byte access and the memory system wants 16-byte transactions.
"kernel void copyk4(device const float4 *A, device float4 *B, constant int &n4,\n"
"                   uint gid [[thread_position_in_grid]]) {\n"
"  if (gid < (uint)n4) B[gid] = A[gid] * float4(1.0000001f);\n"
"}\n";

int main(int argc, char**argv){
  size_t n = (argc>1? (size_t)atol(argv[1]) : (size_t)64*1024*1024); // floats
  int reps = argc>2?atoi(argv[2]):20;
  @autoreleasepool {
    id<MTLDevice> dev = MTLCreateSystemDefaultDevice();
    printf("device: %s\n", dev.name.UTF8String);
    id<MTLCommandQueue> q=[dev newCommandQueue];
    NSError*e=nil;
    id<MTLLibrary> lib=[dev newLibraryWithSource:[NSString stringWithUTF8String:SRC] options:nil error:&e];
    if(!lib){printf("lib fail %s\n",e.description.UTF8String);return 1;}
    id<MTLComputePipelineState> ps=[dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"copyk"] error:&e];
    size_t bytes=n*sizeof(float);
    id<MTLBuffer> A=[dev newBufferWithLength:bytes options:MTLResourceStorageModeShared];
    id<MTLBuffer> B=[dev newBufferWithLength:bytes options:MTLResourceStorageModeShared];
    memset([A contents],0,bytes);
    double best=1e9;
    for(int trial=0;trial<5;trial++){
      double t0=now_ms();
      for(int r=0;r<reps;r++){
        id<MTLCommandBuffer> cb=[q commandBuffer];
        id<MTLComputeCommandEncoder> enc=[cb computeCommandEncoder];
        [enc setComputePipelineState:ps];
        [enc setBuffer:A offset:0 atIndex:0];
        [enc setBuffer:B offset:0 atIndex:1];
        [enc setBytes:&n length:sizeof(int) atIndex:2];
        [enc dispatchThreadgroups:MTLSizeMake((n+1023)/1024,1,1) threadsPerThreadgroup:MTLSizeMake(1024,1,1)];
        [enc endEncoding];[cb commit];[cb waitUntilCompleted];
      }
      double dt=(now_ms()-t0)/reps;
      if(dt<best)best=dt;
    }
    double gb = (double)bytes*2/1e9;   // read + write
    printf("payload %.0f MB  best %.3f ms  =>  %.1f GB/s (read+write)\n",
           bytes/1e6, best, gb/(best/1e3));
    // roofline for the MMA ceiling
    // float4 variant
    {
      int n4 = (int)(n/4);
      id<MTLComputePipelineState> ps4=[dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"copyk4"] error:&e];
      id<MTLBuffer> A4=[dev newBufferWithLength:n/4*16 options:MTLResourceStorageModeShared];
      id<MTLBuffer> B4=[dev newBufferWithLength:n/4*16 options:MTLResourceStorageModeShared];
      memset([A4 contents],0,n/4*16);
      double b4=1e9;
      for(int trial=0;trial<5;trial++){
        double s0=now_ms();
        for(int r=0;r<reps;r++){
          id<MTLCommandBuffer> cb=[q commandBuffer];
          id<MTLComputeCommandEncoder> enc=[cb computeCommandEncoder];
          [enc setComputePipelineState:ps4];
          [enc setBuffer:A4 offset:0 atIndex:0];
          [enc setBuffer:B4 offset:0 atIndex:1];
          [enc setBytes:&n4 length:sizeof(int) atIndex:2];
          [enc dispatchThreadgroups:MTLSizeMake((n4+1023)/1024,1,1) threadsPerThreadgroup:MTLSizeMake(1024,1,1)];
          [enc endEncoding];[cb commit];[cb waitUntilCompleted];
        }
        double dt=(now_ms()-s0)/reps; if(dt<b4)b4=dt;
      }
      double gb4=(double)(n/4*16)*2/1e9;
      printf("float4 copy        : %.3f ms  =>  %.1f GB/s  <-- PEAK\n", b4, gb4/(b4/1e3));
      printf("\nroofline at %.0f GB/s: sustaining 117 TFLOPS needs >= %.0f FLOP/byte\n",
             gb4/(b4/1e3), 117.0/(gb4/(b4/1e3)));
      for (int R=8;R<=256;R*=2)
        printf("    single-pass %3dx%-3d -> %6.1f FLOP/byte -> max %7.1f TFLOPS\n",
               R,R,(double)R/4.0, (R/4.0)*(gb4/(b4/1e3)));
    }
    printf("\n(old scalar roofline: to sustain 117 TFLOPS at this bandwidth you need\n"
           "  arithmetic intensity >= %.0f FLOP/byte\n",
           117.0/(gb/(best/1e3)));
    for (int R=8;R<=256;R*=2){
      double ai = (double)R*R/(2.0*(2*R));
      printf("    single-pass tile %3dx%-3d -> %6.1f FLOP/byte -> max %6.1f TFLOPS\n",
             R,R,ai, ai*gb/(best/1e3));
    }
  }
  return 0;
}
