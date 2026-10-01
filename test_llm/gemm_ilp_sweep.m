// How close can a real GEMM get to the 117 TFLOPS MMA ceiling on this GPU?
//
// The ceiling is an INSTRUCTION rate: simdgroup_multiply_accumulate issued
// back to back with operands already in registers. A GEMM also has to fetch
// operands. Measured achievable bandwidth here is 308 GB/s, and at an 8x8 tile
// (2 FLOP/byte) that still permits 616 TFLOPS -- so bandwidth is NOT the
// binding constraint at any usable tile size. What binds is LATENCY: with one
// accumulator, every MMA waits on two fresh global loads and there is nothing
// to hide the latency behind.
//
// So the variable that matters is the number of independent accumulators, i.e.
// the ILP available between a fragment load and its use. TMxTN MMA tiles per
// simdgroup gives TM*TN accumulators, and each k-step issues TM+TN fragment
// loads to feed TM*TN MMAs. That ratio is the whole game:
//
//   accumulators   loads/k-step   MMA per load
//        1             2              0.5     <- 8x8 tile: latency bound
//        4             4              1.0     <- 16x16
//        16            8              2.0     <- 32x32
//        32           12              2.7     <- 64x32
//
// Compiled with -DTM= -DTN= to sweep. Correctness is checked against a
// reference for the small case, because a fast wrong kernel is the default
// failure mode here.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <mach/mach_time.h>

#ifndef TM
#define TM 4
#endif
#ifndef TN
#define TN 4
#endif
#define MMA_M (TM*8)
#define MMA_N (TN*8)

#define Q_(x) #x
#define Q(x) Q_(x)

static double now_ms(void){static mach_timebase_info_data_t tb;
  if(!tb.denom)mach_timebase_info(&tb);
  return (double)mach_absolute_time()*tb.numer/tb.denom/1e6;}

static const char *SRC =
"#include <metal_stdlib>\n"
"#include <metal_simdgroup_matrix>\n"
"using namespace metal;\n"
"#define TM " Q(TM) "\n"
"#define TN " Q(TN) "\n"
"#define MMA_M " Q(MMA_M) "\n"
"#define MMA_N " Q(MMA_N) "\n"
"static inline short2 frag_coord(uint lane){\n"
"  short q=short(lane/4);\n"
"  return short2(short((q&2)*2+(lane%2)*2), short((q&4)+((lane/2)%4)));\n"
"}\n"
"kernel void gemm(device const float *A, device const float *B, device float *C,\n"
"                 constant int &M, constant int &N, constant int &K,\n"
"                 uint tg [[threadgroup_position_in_grid]],\n"
"                 uint lane [[thread_index_in_simdgroup]],\n"
"                 uint sgi [[simdgroup_index_in_threadgroup]],\n"
"                 uint nsg [[simdgroups_per_threadgroup]]) {\n"
"  int nm = (M + MMA_M - 1)/MMA_M;\n"
"  int nn = (N + MMA_N - 1)/MMA_N;\n"
"  int gt = int(tg * nsg + sgi);\n"
"  if (gt >= nm * nn) return;\n"
"  int m0 = (gt % nn) * MMA_M;\n"
"  int n0 = (gt / nn) * MMA_N;\n"
"  short2 fc = frag_coord(lane);\n"
"  short fr = fc.y, fcol = fc.x;\n"
"  simdgroup_matrix<float,8,8> acc[TM][TN];\n"
"  for (int i=0;i<TM;i++) for (int j=0;j<TN;j++)\n"
"    reinterpret_cast<thread float2&>(acc[i][j].thread_elements())=float2(0.0f);\n"
"  for (int k0=0;k0<K;k0+=8){\n"
"    simdgroup_matrix<float,8,8> af[TM], bf[TN];\n"
"    for (int i=0;i<TM;i++){\n"
"      int r=m0+i*8+fr, c=k0+fcol; float2 v=float2(0.0f);\n"
"      if (r<M && c<K)     v.x=A[r*K+c];\n"
"      if (r<M && c+1<K)   v.y=A[r*K+c+1];\n"
"      reinterpret_cast<thread float2&>(af[i].thread_elements())=v;\n"
"    }\n"
"    for (int j=0;j<TN;j++){\n"
"      int r=k0+fr, c=n0+j*8+fcol; float2 v=float2(0.0f);\n"
"      if (r<K && c<N)     v.x=B[r*N+c];\n"
"      if (r<K && c+1<N)   v.y=B[r*N+c+1];\n"
"      reinterpret_cast<thread float2&>(bf[j].thread_elements())=v;\n"
"    }\n"
"    for (int i=0;i<TM;i++) for (int j=0;j<TN;j++)\n"
"      simdgroup_multiply_accumulate(acc[i][j],af[i],bf[j],acc[i][j]);\n"
"  }\n"
"  for (int i=0;i<TM;i++) for (int j=0;j<TN;j++){\n"
"    int r=m0+i*8+fr, c=n0+j*8+fcol;\n"
"    float2 v=reinterpret_cast<thread float2&>(acc[i][j].thread_elements());\n"
"    if (r<M && c<N)     C[r*N+c]=v.x;\n"
"    if (r<M && c+1<N)   C[r*N+c+1]=v.y;\n"
"  }\n"
"}\n";

int main(int argc, char**argv){
  int M=argc>1?atoi(argv[1]):1024, N=argc>2?atoi(argv[2]):1024, K=argc>3?atoi(argv[3]):1024;
  int check=argc>4?atoi(argv[4]):0;
  @autoreleasepool {
    id<MTLDevice> dev=MTLCreateSystemDefaultDevice();
    id<MTLCommandQueue> q=[dev newCommandQueue];
    NSError*e=nil;
    NSString *src=[NSString stringWithUTF8String:SRC];
    id<MTLLibrary> lib=[dev newLibraryWithSource:src options:nil error:&e];
    if(!lib){printf("lib fail: %s\n",e.description.UTF8String);
      printf("SRC had %d conversions\n",0);return 1;}
    id<MTLFunction> fn=[lib newFunctionWithName:@"gemm"];
    id<MTLComputePipelineState> ps=[dev newComputePipelineStateWithFunction:fn error:&e];
    if(!ps){printf("ps fail: %s\n",e.description.UTF8String);return 1;}
    size_t na=(size_t)M*K, nb=(size_t)K*N, nc=(size_t)M*N;
    float *hA=malloc(na*4), *hB=malloc(nb*4), *hC=malloc(nc*4);
    srand(7);
    // multiples of 1/16 so partial sums are exact in f32
    for(size_t i=0;i<na;i++) hA[i]=(float)((rand()%17)-8)/16.0f;
    for(size_t i=0;i<nb;i++) hB[i]=(float)((rand()%13)-6)/16.0f;
    memset(hC,0,nc*4);
    id<MTLBuffer> A=[dev newBufferWithBytes:hA length:na*4 options:MTLResourceStorageModeShared];
    id<MTLBuffer> B=[dev newBufferWithBytes:hB length:nb*4 options:MTLResourceStorageModeShared];
    id<MTLBuffer> C=[dev newBufferWithLength:nc*4 options:MTLResourceStorageModeShared];
    int nm=(M+MMA_M-1)/MMA_M, nn=(N+MMA_N-1)/MMA_N;
    long tiles=(long)nm*nn;
    int tpb=256; int nsg=tpb/32;
    if(nsg>1 && tiles<nsg) tpb=(int)tiles*32;
    if(tpb<32) tpb=32;
    nsg=tpb/32;
    MTLSize grid=MTLSizeMake((NSUInteger)((tiles+nsg-1)/nsg),1,1);
    double best=1e9;
    for(int trial=0;trial<5;trial++){
      memset([C contents],0,nc*4);
      double t0=now_ms();
      id<MTLCommandBuffer> cb=[q commandBuffer];
      id<MTLComputeCommandEncoder> enc=[cb computeCommandEncoder];
      [enc setComputePipelineState:ps];
      [enc setBuffer:A offset:0 atIndex:0];[enc setBuffer:B offset:0 atIndex:1];
      [enc setBuffer:C offset:0 atIndex:2];
      [enc setBytes:&M length:4 atIndex:3];[enc setBytes:&N length:4 atIndex:4];
      [enc setBytes:&K length:4 atIndex:5];
      [enc dispatchThreadgroups:grid threadsPerThreadgroup:MTLSizeMake(tpb,1,1)];
      [enc endEncoding];[cb commit];[cb waitUntilCompleted];
      double dt=now_ms()-t0; if(dt<best)best=dt;
    }
    double fl=2.0*M*N*K;
    printf("TM=%d TN=%d  tile %dx%d/simdgroup  acc=%d  grid %lux%u  ",TM,TN,
           MMA_M,MMA_N,TM*TN,nsg,(unsigned)grid.width);
    printf("%7.3f ms  %7.2f TFLOPS  %5.1f%% of 117\n",best,fl/(best/1e3)/1e12,
           100.0*fl/(best/1e3)/1e12/117.47);
    if(check){
      memcpy(hC,[C contents],nc*4);
      long bad=0; double worst=0;
      for(int i=0;i<M&&bad<5;i++) for(int j=0;j<N;j++){
        double ref=0; for(int p=0;p<K;p++) ref+=(double)hA[(size_t)i*K+p]*hB[(size_t)p*N+j];
        double d=fabs(ref-hC[(size_t)i*N+j]); if(d>worst)worst=d;
        if(d!=0.0){bad++;}
      }
      printf("   check: %ld/%d differ, max |err| %.3e\n",bad,M*N,worst);
    }
    free(hA);free(hB);free(hC);
  }
  return 0;
}
