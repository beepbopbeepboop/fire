// The user's hypothesis: the feed (operand supply) is the bottleneck, so fan the
// SAME loaded data out to more consumers instead of loading more.
//
// One 64x64 output tile per threadgroup, staged in threadgroup memory once per
// k-step, then read by 16 SIMDGROUPS -- each owning one 16x16 sub-tile and
// keeping only FOUR accumulators. That last part is the whole design: the naive
// sweep collapsed past 4 accumulators, so this gets its reuse from SHARING
// (16 readers of one staged tile) rather than from per-thread blocking.
//
// Arithmetic intensity against DRAM:
//   16x16 tile alone            32 FLOP/byte   (each element used once)
//   64x64 staged, 16 readers   128 FLOP/byte   (each element used 4x)
// and the register count per thread is UNCHANGED from the fast config.
//
// At 307.8 GB/s that is a 9.9 -> 39.6 TFLOPS roofline, so if the user's reading
// of the bottleneck is right there is ~4x on the table here.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <mach/mach_time.h>

#ifndef TN
#define TN 64      // threadgroup tile, rows and cols
#endif
#ifndef TKS
#define TKS 8      // k-depth staged per step
#endif
#ifndef NREAD
#define NREAD 16   // simdgroups per threadgroup
#endif

#define Q_(x) #x
#define Q(x) Q_(x)

static double now_ms(void){static mach_timebase_info_data_t tb;
  if(!tb.denom)mach_timebase_info(&tb);
  return (double)mach_absolute_time()*tb.numer/tb.denom/1e6;}

static const char *SRC =
"#include <metal_stdlib>\n"
"#include <metal_simdgroup_matrix>\n"
"using namespace metal;\n"
"#define TN " Q(TN) "\n"
"#define TKS " Q(TKS) "\n"
"#define NREAD " Q(NREAD) "\n"
"#define RPB (TN/16)\n"          // 16x16 readers per row-block
"static inline short2 frag_coord(uint lane){\n"
"  short q=short(lane/4);\n"
"  return short2(short((q&2)*2+(lane%2)*2), short((q&4)+((lane/2)%4)));\n"
"}\n"
"kernel void gemm(device const float *A, device const float *B, device float *C,\n"
"                 constant int &M, constant int &N, constant int &K,\n"
"                 uint tg [[threadgroup_position_in_grid]],\n"
"                 uint tid [[thread_position_in_threadgroup]],\n"
"                 uint lane [[thread_index_in_simdgroup]],\n"
"                 uint sgi [[simdgroup_index_in_threadgroup]],\n"
"                 uint nsg [[simdgroups_per_threadgroup]],\n"
"                 uint nthreads [[threads_per_threadgroup]]) {\n"
"  uint NT = nthreads;\n"
"  threadgroup float As[TN][TKS];\n"
"  threadgroup float Bs[TKS][TN];\n"
"  int nm=(M+TN-1)/TN, nn=(N+TN-1)/TN;\n"
"  int m0=tg%nn*TN, n0=tg/nn*TN;\n"
"  short2 fc=frag_coord(lane);\n"
"  short fr=fc.y, fcol=fc.x;\n"
"  simdgroup_matrix<float,8,8> acc[2][2];\n"
"  for(int i=0;i<2;i++)for(int j=0;j<2;j++)\n"
"    reinterpret_cast<thread float2&>(acc[i][j].thread_elements())=float2(0.0f);\n"
"  for(int k0=0;k0<K;k0+=TKS){\n"
"    for(int e=tid;e<TN*TKS;e+=NT)\n"
"      As[e/TKS][e%TKS]=(m0+e/TKS<M)?A[(size_t)(m0+e/TKS)*K+k0+e%TKS]:0.0f;\n"
"    for(int e=tid;e<TKS*TN;e+=NT)\n"
"      Bs[e/TN][e%TN]=(k0+e/TN<K)?B[(size_t)(k0+e/TN)*N+n0+e%TN]:0.0f;\n"
"    threadgroup_barrier(mem_flags::mem_threadgroup);\n"
"    for(int kk=0;kk<TKS;kk+=8){\n"
"      simdgroup_matrix<float,8,8> af[2],bf[2];\n"
"      int rl=(int)(sgi%RPB)*16, cl=(int)(sgi/RPB)*16;\n"
"      for(int i=0;i<2;i++){\n"
"        int r=rl+i*8+fr, c=kk+fcol;\n"
"        reinterpret_cast<thread float2&>(af[i].thread_elements())=\n"
"          float2(As[r][c],As[r][c+1]);\n"
"      }\n"
"      for(int j=0;j<2;j++){\n"
"        int r=kk+fr, c=cl+j*8+fcol;\n"
"        reinterpret_cast<thread float2&>(bf[j].thread_elements())=\n"
"          float2(Bs[r][c],Bs[r][c+1]);\n"
"      }\n"
"      for(int i=0;i<2;i++)for(int j=0;j<2;j++)\n"
"        simdgroup_multiply_accumulate(acc[i][j],af[i],bf[j],acc[i][j]);\n"
"    }\n"
"    threadgroup_barrier(mem_flags::mem_threadgroup);\n"
"  }\n"
"  int rl=(int)(sgi%RPB)*16, cl=(int)(sgi/RPB)*16;\n"
"  for(int i=0;i<2;i++)for(int j=0;j<2;j++){\n"
"    int r=m0+rl+i*8+fr, c=n0+cl+j*8+fcol;\n"
"    float2 v=reinterpret_cast<thread float2&>(acc[i][j].thread_elements());\n"
"    if(r<M&&c<N)C[(size_t)r*N+c]=v.x;\n"
"    if(r<M&&c+1<N)C[(size_t)r*N+c+1]=v.y;\n"
"  }\n"
"}\n";

int main(int argc,char**argv){
  int M=argc>1?atoi(argv[1]):2048,N=argc>2?atoi(argv[2]):2048,K=argc>3?atoi(argv[3]):2048;
  int check=argc>4?atoi(argv[4]):0;
  @autoreleasepool{
    id<MTLDevice> dev=MTLCreateSystemDefaultDevice();
    id<MTLCommandQueue> q=[dev newCommandQueue];
    { const char*d=getenv("GEMM_DUMP"); if(d){FILE*f=fopen(d,"w");fputs(SRC,f);fclose(f);} }
    NSError*e=nil;
    id<MTLLibrary> lib=[dev newLibraryWithSource:[NSString stringWithUTF8String:SRC] options:nil error:&e];
    if(!lib){printf("lib fail: %s\n",e.description.UTF8String);return 1;}
    id<MTLComputePipelineState> ps=[dev newComputePipelineStateWithFunction:[lib newFunctionWithName:@"gemm"] error:&e];
    if(!ps){printf("ps fail: %s\n",e.description.UTF8String);return 1;}
    size_t na=(size_t)M*K,nb=(size_t)K*N,nc=(size_t)M*N;
    float*hA=malloc(na*4),*hB=malloc(nb*4),*hC=malloc(nc*4);
    srand(7);
    for(size_t i=0;i<na;i++)hA[i]=(float)((rand()%17)-8)/16.0f;
    for(size_t i=0;i<nb;i++)hB[i]=(float)((rand()%13)-6)/16.0f;
    memset(hC,0,nc*4);
    id<MTLBuffer>A=[dev newBufferWithBytes:hA length:na*4 options:MTLResourceStorageModeShared];
    id<MTLBuffer>B=[dev newBufferWithBytes:hB length:nb*4 options:MTLResourceStorageModeShared];
    id<MTLBuffer>C=[dev newBufferWithLength:nc*4 options:MTLResourceStorageModeShared];
    int tpb=NREAD*32;
    long gx=((long)M+TN-1)/TN, gy=((long)N+TN-1)/TN;
    MTLSize grid=MTLSizeMake((NSUInteger)(gx*gy),1,1);
    double ts[15];
    for(int t=0;t<15;t++){
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
      ts[t]=now_ms()-t0;
    }
    for(int a=0;a<15;a++)for(int b=a+1;b<15;b++)if(ts[b]<ts[a]){double x=ts[a];ts[a]=ts[b];ts[b]=x;}
    double med=ts[7];
    double fl=2.0*M*N*K;
    printf("fanout TN=%d TKS=%d readers=%d tpb=%-3d grid %5lu  %7.3f ms  %7.2f TFLOPS  %5.1f%% of 117  [%.3f-%.3f]\n",
           TN,TKS,NREAD,tpb,(unsigned long)(gx*gy),med,fl/(med/1e3)/1e12,
           100.0*fl/(med/1e3)/1e12/117.47,ts[0],ts[14]);
    if(check){
      memcpy(hC,[C contents],nc*4);
      long bad=0;double worst=0;
      for(int i=0;i<M&&bad<5;i++)for(int j=0;j<N;j++){
        double ref=0;for(int p=0;p<K;p++)ref+=(double)hA[(size_t)i*K+p]*hB[(size_t)p*N+j];
        double d=fabs(ref-hC[(size_t)i*N+j]);if(d>worst)worst=d;if(d!=0.0)bad++;}
      printf("   check: %ld/%d differ, max |err| %.3e\n",bad,M*N,worst);
    }
    free(hA);free(hB);free(hC);
  }
  return 0;
}
