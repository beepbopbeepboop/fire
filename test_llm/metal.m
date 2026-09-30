/* fire_metal.m — the ObjC host for runtime/kernels.metal.
 *
 * Two things make a mixed ARM/Metal program cheap:
 *
 *  1. Zero copy. Every buffer is wrapped with newBufferWithBytesNoCopy in
 *     SHARED storage mode, which on Apple Silicon is the same memory the CPU
 *     reads and writes. A dispatch neither copies nor invalidates anything,
 *     so a kernel can hand a raw C pointer straight to the next one and both
 *     engines operate on it. That is the whole reason this file can be a
 *     plain C API at all (fire_metal.h) — the compiled program's scalar code
 *     never learns that Metal exists.
 *
 *  2. Lazy, once-only setup. Device, queue, library and pipelines are built
 *     on the first dispatch, from the .metal source embedded below (so the
 *     shipped artifact is one file with no build-time Metal step), and every
 *     mg_* entry point falls back to the identical scalar C loop if any of
 *     that failed. mg_available() reports which path is live.
 *
 * fp32 on the GPU vs fp64 on the CPU is deliberate and unavoidable: MSL has
 * no double. The scalars are converted at the buffer boundary.
 */
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <math.h>
#import <stdlib.h>
#import <string.h>
#import <time.h>

#include "metal.h"

static const char *kFireMetalSource =
#include "kernels.metal.inc"
;

static id<MTLDevice>          g_device = nil;
static id<MTLCommandQueue>    g_queue = nil;
static id<MTLLibrary>         g_lib = nil;
static id<MTLComputePipelineState> g_p_axpy = nil;
static id<MTLComputePipelineState> g_p_matvec = nil;
static id<MTLComputePipelineState> g_p_state = nil;
static id<MTLComputePipelineState> g_p_read = nil;
static id<MTLComputePipelineState> g_p_adds = nil;
static id<MTLComputePipelineState> g_p_matvec_bf = nil;
static id<MTLComputePipelineState> g_p_state_bf = nil;
static id<MTLComputePipelineState> g_p_fused = nil;
static id<MTLComputePipelineState> g_p_fused_sk = nil;
static int                    g_tried = 0;
static int                    g_ok = 0;
static int                    g_kernels = 0;
static double                 g_gpu_s = 0.0;
static double                 g_cpu_s = 0.0;

static double now_s(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static id<MTLComputePipelineState> pipeline(NSString *name)
{
    NSError *err = nil;
    id<MTLFunction> fn = [g_lib newFunctionWithName:name];
    if (!fn) return nil;
    id<MTLComputePipelineState> ps =
        [g_device newComputePipelineStateWithFunction:fn error:&err];
    if (!ps) return nil;
    g_kernels++;
    return ps;
}

static void mg_init(void)
{
    if (g_tried) return;
    g_tried = 1;
    @autoreleasepool {
        g_device = MTLCreateSystemDefaultDevice();
        if (!g_device) return;
        g_queue = [g_device newCommandQueue];
        if (!g_queue) return;
        NSString *src = [NSString stringWithUTF8String:kFireMetalSource];
        NSError *err = nil;
        /* metal3.2: the first language version with a native `bfloat` type.
         * Without this the source below fails to compile ("unknown type
         * name 'bfloat'"). There is no setting that gets `double` — MSL has
         * no double at any language version, including 4.0. */
        MTLCompileOptions *copts = [[MTLCompileOptions alloc] init];
        copts.languageVersion = MTLLanguageVersion3_2;
        g_lib = [g_device newLibraryWithSource:src options:copts error:&err];
        if (!g_lib) {
            if (err) {
                fprintf(stderr, "fire_metal: MSL compile failed: %s\n",
                        err.description.UTF8String);
            }
            g_device = nil;
            return;
        }
        g_p_axpy   = pipeline(@"mg_axpy_kernel");
        g_p_matvec = pipeline(@"mg_matvec_kernel");
        g_p_state  = pipeline(@"mg_attn_state_kernel");
        g_p_read   = pipeline(@"mg_attn_read_kernel");
        g_p_adds   = pipeline(@"mg_add_scaled_kernel");
        g_p_matvec_bf = pipeline(@"mg_matvec_bf16_kernel");
        g_p_state_bf = pipeline(@"mg_attn_state_bf16_kernel");
        g_p_fused = pipeline(@"fused_step_kernel");
        g_p_fused_sk = pipeline(@"fused_step_sk_kernel");
        g_ok = (g_p_axpy && g_p_matvec && g_p_state && g_p_read && g_p_adds) ? 1 : 0;
    }
}

int mg_available(void)
{
    mg_init();
    return g_ok;
}

const char *mg_device_name(void)
{
    mg_init();
    if (!g_device) return "(none)";
    return g_device.name.UTF8String;
}

int mg_compiled_kernels(void)
{
    mg_init();
    return g_kernels;
}

double mg_gpu_seconds(void) { return g_gpu_s; }
double mg_cpu_fallback_seconds(void) { return g_cpu_s; }

/* Shared-storage, no-copy view of CPU memory. Apple Silicon makes this the
 * same physical pages, so the GPU writes land directly in the caller's
 * buffer and the CPU sees them after the wait. */
static id<MTLBuffer> wrap(const void *p, size_t n)
{
    if (!p || n == 0) return nil;
    /* This SDK only ships the deallocator: form, and a nil deallocator is
     * exactly "no copy, caller keeps ownership". */
    return [g_device newBufferWithBytesNoCopy:(void *)p
                                       length:n
                                      options:MTLResourceStorageModeShared
                                  deallocator:nil];
}

static id<MTLBuffer> wrap_mut(void *p, size_t n)
{
    return wrap(p, n);
}

/* float view of a double buffer: MSL has no double, so the boundary does
 * the widening. Kept out of the kernels on purpose. */
static void d2f(const double *src, float *dst, size_t n)
{
    for (size_t i = 0; i < n; i++) dst[i] = (float)src[i];
}
static void f2d(const float *src, double *dst, size_t n)
{
    for (size_t i = 0; i < n; i++) dst[i] = (double)src[i];
}

static id<MTLBuffer> upload_d(const double *src, size_t n)
{
    float *tmp = (float *)malloc(n * sizeof(float));
    if (!tmp) return nil;
    d2f(src, tmp, n);
    id<MTLBuffer> b = [g_device newBufferWithBytes:tmp
                                            length:n * sizeof(float)
                                           options:MTLResourceStorageModeShared];
    free(tmp);
    return b;
}

static void download_b(id<MTLBuffer> b, double *dst, size_t n)
{
    f2d((const float *)b.contents, dst, n);
}

static double dispatch_and_wait(id<MTLCommandBuffer> cb)
{
    double t0 = now_s();
    [cb commit];
    [cb waitUntilCompleted];
    NSError *e = cb.error;
    if (e && !getenv("MG_QUIET")) {
        fprintf(stderr, "fire_metal: command buffer error: %s\n",
                e.description.UTF8String);
    }
    return now_s() - t0;
}

void mg_axpy(double *o, const double *x, const double *y, double k, int n)
{
    if (n <= 0) return;
    if (!mg_available()) {
        double t0 = now_s();
        for (int i = 0; i < n; i++) o[i] = x[i] + k * y[i];
        g_cpu_s += now_s() - t0;
        return;
    }
    @autoreleasepool {
        /* The kernels are f32 and the C buffers are f64, so NOTHING crosses
         * the boundary raw: a no-copy view of a double array handed to an
         * f32 kernel reinterprets the mantissa halves (it "works", writes
         * plausible-looking numbers, and is completely wrong). Convert on
         * the way in and on the way out. */
        id<MTLBuffer> bo = [g_device newBufferWithLength:(size_t)n * sizeof(float)
                                                 options:MTLResourceStorageModeShared];
        id<MTLBuffer> bx = upload_d(x, (size_t)n);
        id<MTLBuffer> by = upload_d(y, (size_t)n);
        float fk = (float)k;
        unsigned int un = (unsigned int)n;
        id<MTLBuffer> bk = [g_device newBufferWithBytes:&fk
                                                length:sizeof(float)
                                               options:MTLResourceStorageModeShared];
        id<MTLBuffer> bn = [g_device newBufferWithBytes:&un
                                                length:sizeof(unsigned int)
                                               options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> cb = [g_queue commandBuffer];
        id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
        [e setComputePipelineState:g_p_axpy];
        [e setBuffer:bo offset:0 atIndex:0];
        [e setBuffer:bx offset:0 atIndex:1];
        [e setBuffer:by offset:0 atIndex:2];
        [e setBuffer:bk offset:0 atIndex:3];
        [e setBuffer:bn offset:0 atIndex:4];
        [e dispatchThreads:MTLSizeMake(n, 1, 1)
            threadsPerThreadgroup:MTLSizeMake(64, 1, 1)];
        [e endEncoding];
        g_gpu_s += dispatch_and_wait(cb);
        download_b(bo, o, (size_t)n);
    }
}

void mg_matvec(double *y, const double *W, const double *x, int rows, int cols)
{
    if (rows <= 0 || cols <= 0) return;
    if (!mg_available()) {
        double t0 = now_s();
        for (int r = 0; r < rows; r++) {
            double acc = 0.0;
            const double *row = W + (size_t)r * cols;
            for (int c = 0; c < cols; c++) acc += row[c] * x[c];
            y[r] = acc;
        }
        g_cpu_s += now_s() - t0;
        return;
    }
    @autoreleasepool {
        size_t wx = (size_t)rows * cols;
        id<MTLBuffer> bW = upload_d(W, wx);
        id<MTLBuffer> bx = upload_d(x, (size_t)cols);
        id<MTLBuffer> by = [g_device newBufferWithLength:(size_t)rows * sizeof(float)
                                                 options:MTLResourceStorageModeShared];
        unsigned int urows = (unsigned int)rows, ucols = (unsigned int)cols;
        id<MTLBuffer> br = [g_device newBufferWithBytes:&urows length:sizeof(unsigned int)
                                                options:MTLResourceStorageModeShared];
        id<MTLBuffer> bc = [g_device newBufferWithBytes:&ucols length:sizeof(unsigned int)
                                                options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> cb = [g_queue commandBuffer];
        id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
        [e setComputePipelineState:g_p_matvec];
        [e setBuffer:by offset:0 atIndex:0];
        [e setBuffer:bW offset:0 atIndex:1];
        [e setBuffer:bx offset:0 atIndex:2];
        [e setBuffer:br offset:0 atIndex:3];
        [e setBuffer:bc offset:0 atIndex:4];
        /* one threadgroup per output row, 256 threads over the columns */
        [e dispatchThreadgroups:MTLSizeMake(rows, 1, 1)
            threadsPerThreadgroup:MTLSizeMake(256, 1, 1)];
        [e endEncoding];
        g_gpu_s += dispatch_and_wait(cb);
        download_b(by, y, (size_t)rows);
    }
}

void mg_attn_state(double *S, double alpha, const double *k, const double *v, int d)
{
    if (d <= 0) return;
    if (!mg_available()) {
        double t0 = now_s();
        for (int j = 0; j < d; j++) {
            double *row = S + (size_t)j * d;
            double kj = k[j];
            for (int i = 0; i < d; i++) row[i] = alpha * row[i] + kj * v[i];
        }
        g_cpu_s += now_s() - t0;
        return;
    }
    @autoreleasepool {
        size_t n = (size_t)d * d;
        float fa = (float)alpha;
        /* S is in/out: upload, dispatch in place, download back. The state is
         * small (16K doubles at d=128) and this kernel is the model's hottest
         * loop, so the round trip is worth the simplicity. */
        float *tmp = (float *)malloc(n * sizeof(float));
        if (!tmp) return;
        d2f(S, tmp, n);
        id<MTLBuffer> bS = [g_device newBufferWithBytesNoCopy:tmp
                                                     length:n * sizeof(float)
                                                    options:MTLResourceStorageModeShared
                                                deallocator:nil];
        id<MTLBuffer> bk = upload_d(k, (size_t)d);
        id<MTLBuffer> bv = upload_d(v, (size_t)d);
        id<MTLBuffer> ba = [g_device newBufferWithBytes:&fa length:sizeof(float)
                                                options:MTLResourceStorageModeShared];
        unsigned int ud = (unsigned int)d;
        id<MTLBuffer> bd = [g_device newBufferWithBytes:&ud length:sizeof(unsigned int)
                                                options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> cb = [g_queue commandBuffer];
        id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
        [e setComputePipelineState:g_p_state];
        [e setBuffer:bS offset:0 atIndex:0];
        [e setBuffer:bk offset:0 atIndex:1];
        [e setBuffer:bv offset:0 atIndex:2];
        [e setBuffer:ba offset:0 atIndex:3];
        [e setBuffer:bd offset:0 atIndex:4];
        [e dispatchThreadgroups:MTLSizeMake((d + 15) / 16, (d + 15) / 16, 1)
            threadsPerThreadgroup:MTLSizeMake(16, 16, 1)];
        [e endEncoding];
        g_gpu_s += dispatch_and_wait(cb);
        f2d(tmp, S, n);
        free(tmp);
    }
}

void mg_attn_read(double *o, const double *S, const double *q, int d)
{
    if (d <= 0) return;
    if (!mg_available()) {
        double t0 = now_s();
        for (int i = 0; i < d; i++) {
            double acc = 0.0;
            for (int j = 0; j < d; j++) acc += S[(size_t)j * d + i] * q[j];
            o[i] = acc;
        }
        g_cpu_s += now_s() - t0;
        return;
    }
    @autoreleasepool {
        size_t n = (size_t)d * d;
        id<MTLBuffer> bS = upload_d(S, n);
        id<MTLBuffer> bq = upload_d(q, (size_t)d);
        id<MTLBuffer> bo = [g_device newBufferWithLength:(size_t)d * sizeof(float)
                                                 options:MTLResourceStorageModeShared];
        unsigned int ud = (unsigned int)d;
        id<MTLBuffer> bd = [g_device newBufferWithBytes:&ud length:sizeof(unsigned int)
                                                options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> cb = [g_queue commandBuffer];
        id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
        [e setComputePipelineState:g_p_read];
        [e setBuffer:bo offset:0 atIndex:0];
        [e setBuffer:bS offset:0 atIndex:1];
        [e setBuffer:bq offset:0 atIndex:2];
        [e setBuffer:bd offset:0 atIndex:3];
        [e dispatchThreads:MTLSizeMake(d, 1, 1)
            threadsPerThreadgroup:MTLSizeMake(64, 1, 1)];
        [e endEncoding];
        g_gpu_s += dispatch_and_wait(cb);
        download_b(bo, o, (size_t)d);
    }
}

void mg_add_scaled(double *row, const double *col, double scale, int n)
{
    if (n <= 0) return;
    if (!mg_available()) {
        double t0 = now_s();
        for (int i = 0; i < n; i++) row[i] += scale * col[i];
        g_cpu_s += now_s() - t0;
        return;
    }
    @autoreleasepool {
        id<MTLBuffer> br = upload_d(row, (size_t)n);   /* read-modify-write */
        id<MTLBuffer> bc = upload_d(col, (size_t)n);
        float fs = (float)scale;
        unsigned int un = (unsigned int)n;
        id<MTLBuffer> bs = [g_device newBufferWithBytes:&fs
                                                length:sizeof(float)
                                               options:MTLResourceStorageModeShared];
        id<MTLBuffer> bn = [g_device newBufferWithBytes:&un
                                                length:sizeof(unsigned int)
                                               options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> cb = [g_queue commandBuffer];
        id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
        [e setComputePipelineState:g_p_adds];
        [e setBuffer:br offset:0 atIndex:0];
        [e setBuffer:bc offset:0 atIndex:1];
        [e setBuffer:bs offset:0 atIndex:2];
        [e setBuffer:bn offset:0 atIndex:3];
        [e dispatchThreads:MTLSizeMake(n, 1, 1)
            threadsPerThreadgroup:MTLSizeMake(64, 1, 1)];
        [e endEncoding];
        g_gpu_s += dispatch_and_wait(cb);
        download_b(br, row, (size_t)n);
    }
}

/* ---------------------------------------------------------------------
 * Batched dispatch. See the header for why this is the form that wins.
 *
 * One MTLCommandBuffer, many compute encoders' worth of work, one wait.
 * A kernel that is issued but not yet run is still just a recorded
 * dispatch: the operands have to survive until the GPU gets to them, so
 * every buffer handed in is copied into batch-owned storage (f32, which
 * is also the precision the kernels speak) and every result is copied
 * back to the caller's f64 array at mg_batch_end.
 * ------------------------------------------------------------------- */

struct mg_batch {
    id<MTLCommandBuffer> cb;
    int ndispatch;
    int cap;
    void **ptrs;        /* caller arrays to write back on end */
    size_t *lens;
    __strong id<MTLBuffer> *keep;   /* batch-owned operand buffers, alive until end */
    int nkeep;
    int nresult;
    __strong id<MTLBuffer> *outs;   /* per-result destination buffer, in issue order */
    /* Operand cache. Within one step the same weight matrix is handed to
     * the same kernel 24 times (once per token) and the same state matrix
     * to two; re-converting and re-uploading each time was 100 MB of
     * malloc+copy per forward step and swamped the GPU entirely. Keyed by
     * the CALLER's pointer, which is stable for the duration of a step.
     *
     * It is also what makes a chained dispatch cheap: `y` written by one
     * kernel and read by the next stays resident on the GPU, so the
     * intermediate never round-trips through system memory at all. The
     * ARM side must therefore treat batched outputs as opaque until
     * mg_batch_end — that is the deal, and it is the deal that makes the
     * GPU worth using. */
    const void **ckey;
    __strong id<MTLBuffer> *cbuf;   /* flat, like `keep` */
    size_t *cn;
    int ccount;
};

static id<MTLBuffer> batch_float_buffer(mg_batch *b, const double *src, size_t n);

static id<MTLBuffer> batch_cached(mg_batch *b, const void *p, size_t n)
{
    for (int i = 0; i < b->ccount; i++) {
        if (b->ckey[i] == p && b->cn[i] == n) return b->cbuf[i];
    }
    id<MTLBuffer> buf = batch_float_buffer(b, (const double *)p, n);
    if (!buf) return nil;
    if (b->ccount < b->cap) {
        b->ckey[b->ccount] = p;
        b->cbuf[b->ccount] = buf;
        b->cn[b->ccount] = n;
        b->ccount++;
    }
    return buf;
}

static id<MTLBuffer> batch_float_buffer(mg_batch *b, const double *src, size_t n)
{
    float *tmp = (float *)malloc(n * sizeof(float));
    if (!tmp) return nil;
    d2f(src, tmp, n);
    id<MTLBuffer> buf = [g_device newBufferWithBytes:tmp
                                              length:n * sizeof(float)
                                             options:MTLResourceStorageModeShared];
    if (b->nkeep < b->cap) b->keep[b->nkeep++] = buf;
    return buf;
}

static id<MTLBuffer> batch_out_buffer(mg_batch *b, void *dst, size_t nbytes)
{
    if (b->nresult < b->cap) {
        b->ptrs[b->nresult] = dst;
        b->lens[b->nresult] = nbytes / sizeof(double);
        b->nresult++;
    }
    return [g_device newBufferWithLength:nbytes options:MTLResourceStorageModeShared];
}

static id<MTLBuffer> batch_u32(mg_batch *b, unsigned int v)
{
    id<MTLBuffer> buf = [g_device newBufferWithBytes:&v
                                              length:sizeof(unsigned int)
                                             options:MTLResourceStorageModeShared];
    if (b->nkeep < b->cap) b->keep[b->nkeep++] = buf;
    return buf;
}

static id<MTLBuffer> batch_f32(mg_batch *b, float v)
{
    id<MTLBuffer> buf = [g_device newBufferWithBytes:&v
                                              length:sizeof(float)
                                             options:MTLResourceStorageModeShared];
    if (b->nkeep < b->cap) b->keep[b->nkeep++] = buf;
    return buf;
}

mg_batch *mg_batch_begin(void)
{
    if (!mg_available()) return NULL;
    @autoreleasepool {
        mg_batch *b = (mg_batch *)calloc(1, sizeof(mg_batch));
        if (!b) return NULL;
        b->cap = 4096;
        b->ptrs = (void **)calloc((size_t)b->cap, sizeof(void *));
        b->lens = (size_t *)calloc((size_t)b->cap, sizeof(size_t));
        b->keep = (__strong id<MTLBuffer> *)calloc((size_t)b->cap, sizeof(id<MTLBuffer>));
        b->outs = (__strong id<MTLBuffer> *)calloc((size_t)b->cap, sizeof(id<MTLBuffer>));
        if (!b->ptrs || !b->lens || !b->keep || !b->outs) { free(b); return NULL; }
        b->ckey = (const void **)calloc((size_t)b->cap, sizeof(void *));
        b->cbuf = (__strong id<MTLBuffer> *)calloc((size_t)b->cap, sizeof(id<MTLBuffer>));
        b->cn = (size_t *)calloc((size_t)b->cap, sizeof(size_t));
        if (!b->ckey || !b->cbuf || !b->cn) { free(b); return NULL; }
        b->cb = [g_queue commandBuffer];
        if (!b->cb) { free(b); return NULL; }
        return b;
    }
}

int mg_batch_dispatches(mg_batch *b) { return b ? b->ndispatch : 0; }

void mg_batch_abort(mg_batch *b)
{
    if (!b) return;
    for (int i = 0; i < b->nkeep; i++) b->keep[i] = nil;
    free(b->ptrs); free(b->lens); free(b->outs);
    free(b->ckey); free(b->cbuf); free(b->cn); free(b->keep);
    free(b);
}

void mg_batch_end(mg_batch *b)
{
    if (!b) return;
    @autoreleasepool {
        if (b->ndispatch > 0) {
            g_gpu_s += dispatch_and_wait(b->cb);
        }
        for (int i = 0; i < b->nresult; i++) {
            f2d((const float *)b->outs[i].contents, (double *)b->ptrs[i], b->lens[i]);
        }
        free(b->ptrs); free(b->lens); free(b->outs);
        free(b->ckey); free(b->cbuf); free(b->cn);
        for (int i = 0; i < b->nkeep; i++) b->keep[i] = nil;
        free(b->keep);
        free(b);
    }
}

void mg_batch_axpy(mg_batch *b, double *o, const double *x, const double *y, double k, int n)
{
    if (!b || n <= 0) return;
    @autoreleasepool {
        id<MTLBuffer> bo = batch_out_buffer(b, o, (size_t)n * sizeof(double));
        id<MTLBuffer> bx = batch_cached(b, x, (size_t)n);
        id<MTLBuffer> by = batch_cached(b, y, (size_t)n);
        id<MTLBuffer> bk = batch_f32(b, (float)k);
        id<MTLBuffer> bn = batch_u32(b, (unsigned int)n);
        id<MTLComputeCommandEncoder> e = [b->cb computeCommandEncoder];
        [e setComputePipelineState:g_p_axpy];
        [e setBuffer:bo offset:0 atIndex:0];
        [e setBuffer:bx offset:0 atIndex:1];
        [e setBuffer:by offset:0 atIndex:2];
        [e setBuffer:bk offset:0 atIndex:3];
        [e setBuffer:bn offset:0 atIndex:4];
        [e dispatchThreads:MTLSizeMake(n, 1, 1) threadsPerThreadgroup:MTLSizeMake(64, 1, 1)];
        [e endEncoding];
        b->ndispatch++;
        b->outs[b->nresult - 1] = bo;
    }
}

void mg_batch_matvec(mg_batch *b, double *y, const double *W, const double *x, int rows, int cols)
{
    if (!b || rows <= 0 || cols <= 0) return;
    @autoreleasepool {
        id<MTLBuffer> bo = batch_out_buffer(b, y, (size_t)rows * sizeof(double));
        id<MTLBuffer> bW = batch_cached(b, W, (size_t)rows * cols);
        id<MTLBuffer> bx = batch_cached(b, x, (size_t)cols);
        id<MTLBuffer> br = batch_u32(b, (unsigned int)rows);
        id<MTLBuffer> bc = batch_u32(b, (unsigned int)cols);
        id<MTLComputeCommandEncoder> e = [b->cb computeCommandEncoder];
        [e setComputePipelineState:g_p_matvec];
        [e setBuffer:bo offset:0 atIndex:0];
        [e setBuffer:bW offset:0 atIndex:1];
        [e setBuffer:bx offset:0 atIndex:2];
        [e setBuffer:br offset:0 atIndex:3];
        [e setBuffer:bc offset:0 atIndex:4];
        [e dispatchThreadgroups:MTLSizeMake(rows, 1, 1)
            threadsPerThreadgroup:MTLSizeMake(256, 1, 1)];
        [e endEncoding];
        b->ndispatch++;
        b->outs[b->nresult - 1] = bo;
    }
}

void mg_batch_attn_state(mg_batch *b, double *S, double alpha, const double *k, const double *v, int d)
{
    if (!b || d <= 0) return;
    @autoreleasepool {
        id<MTLBuffer> bS = batch_float_buffer(b, S, (size_t)d * d);
        id<MTLBuffer> bk = batch_float_buffer(b, k, (size_t)d);
        id<MTLBuffer> bv = batch_float_buffer(b, v, (size_t)d);
        id<MTLBuffer> ba = batch_f32(b, (float)alpha);
        id<MTLBuffer> bd = batch_u32(b, (unsigned int)d);
        id<MTLComputeCommandEncoder> e = [b->cb computeCommandEncoder];
        [e setComputePipelineState:g_p_state];
        [e setBuffer:bS offset:0 atIndex:0];
        [e setBuffer:bk offset:0 atIndex:1];
        [e setBuffer:bv offset:0 atIndex:2];
        [e setBuffer:ba offset:0 atIndex:3];
        [e setBuffer:bd offset:0 atIndex:4];
        [e dispatchThreadgroups:MTLSizeMake((d + 15) / 16, (d + 15) / 16, 1)
            threadsPerThreadgroup:MTLSizeMake(16, 16, 1)];
        [e endEncoding];
        b->ndispatch++;
        b->outs[b->nresult - 1] = bS;   /* read-modify-write: in place */
    }
}

void mg_batch_attn_read(mg_batch *b, double *o, const double *S, const double *q, int d)
{
    if (!b || d <= 0) return;
    @autoreleasepool {
        id<MTLBuffer> bo = batch_out_buffer(b, o, (size_t)d * sizeof(double));
        id<MTLBuffer> bS = batch_cached(b, S, (size_t)d * d);
        id<MTLBuffer> bq = batch_cached(b, q, (size_t)d);
        id<MTLBuffer> bd = batch_u32(b, (unsigned int)d);
        id<MTLComputeCommandEncoder> e = [b->cb computeCommandEncoder];
        [e setComputePipelineState:g_p_read];
        [e setBuffer:bo offset:0 atIndex:0];
        [e setBuffer:bS offset:0 atIndex:1];
        [e setBuffer:bq offset:0 atIndex:2];
        [e setBuffer:bd offset:0 atIndex:3];
        [e dispatchThreads:MTLSizeMake(d, 1, 1) threadsPerThreadgroup:MTLSizeMake(64, 1, 1)];
        [e endEncoding];
        b->ndispatch++;
        b->outs[b->nresult - 1] = bo;
    }
}

void mg_batch_add_scaled(mg_batch *b, double *row, const double *col, double scale, int n)
{
    if (!b || n <= 0) return;
    @autoreleasepool {
        id<MTLBuffer> br = batch_out_buffer(b, row, (size_t)n * sizeof(double));
        id<MTLBuffer> bc = batch_cached(b, col, (size_t)n);
        id<MTLBuffer> bs = batch_f32(b, (float)scale);
        id<MTLBuffer> bn = batch_u32(b, (unsigned int)n);
        id<MTLComputeCommandEncoder> e = [b->cb computeCommandEncoder];
        [e setComputePipelineState:g_p_adds];
        [e setBuffer:br offset:0 atIndex:0];
        [e setBuffer:bc offset:0 atIndex:1];
        [e setBuffer:bs offset:0 atIndex:2];
        [e setBuffer:bn offset:0 atIndex:3];
        [e dispatchThreads:MTLSizeMake(n, 1, 1) threadsPerThreadgroup:MTLSizeMake(64, 1, 1)];
        [e endEncoding];
        b->ndispatch++;
        b->outs[b->nresult - 1] = br;
    }
}

/* double -> bfloat, round-half-to-even on the low 16 mantissa bits.
   Identical to what the model's own Python bf16() does, so a value that
   round-trips through the GPU comes back bit-identical. */
static void d2bf(const double *src, uint16_t *dst, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        float f = (float)src[i];
        uint32_t b;
        memcpy(&b, &f, 4);
        if ((b & 0x7f800000u) == 0x7f800000u && (b & 0x007fffffu)) {
            dst[i] = 0x7fc0;                    /* NaN */
            continue;
        }
        uint32_t lsb = (b >> 16) & 1u;
        uint32_t rounded = b + 0x7fffu + lsb;
        dst[i] = (uint16_t)(rounded >> 16);
    }
}

static void bf2d(const uint16_t *src, double *dst, size_t n)
{
    for (size_t i = 0; i < n; i++) {
        uint32_t b = ((uint32_t)src[i]) << 16;
        float f;
        memcpy(&f, &b, 4);
        dst[i] = (double)f;
    }
}

static id<MTLBuffer> upload_bf(const double *src, size_t n);

/* Weight cache. Converting the weights costs ~1.5 ms for this model's
 * 983040 doubles -- more than the GPU work of a 100-step run -- and they do
 * not change between steps. Cache the converted buffer keyed on the caller's
 * pointer and length; a training loop that updates weights in place must
 * invalidate (mg_weights_dirty) or hand over a different pointer. */
static const void *g_wkey = NULL;
static size_t g_wn = 0;
static __strong id<MTLBuffer> g_wbuf = nil;

void mg_weights_dirty(void) { g_wkey = NULL; g_wn = 0; g_wbuf = nil; }

/* Per layer the packed layout is
 *   [4 * d*d][2 * dff*d][d*dff]
 * and each of those is a ROW-major (out x in) matrix, which the fused
 * kernel wants TRANSPOSED (in x out) so the threadgroup reads contiguously.
 * Transposing here costs one pass, once per model, at cache time. */
static id<MTLBuffer> upload_bf_t_cached(const double *src, size_t n,
                                       int layers, int d, int dff)
{
    if (g_wkey == src && g_wn == n) return g_wbuf;
    size_t per = 4 * (size_t)d * d + 2 * (size_t)dff * d + (size_t)d * dff;
    size_t out_n = (size_t)layers * per;
    double *tmp = (double *)malloc(out_n * sizeof(double));
    if (!tmp) return nil;
    double *o = tmp;
    for (int L = 0; L < layers; L++) {
        const double *in = src + (size_t)L * per;
        for (int blk = 0; blk < 4; blk++) {              /* d x d */
            int m = d, ncol = d;
            const double *b = in + (size_t)blk * d * d;
            for (int r = 0; r < m; r++)
                for (int c = 0; c < ncol; c++) *o++ = b[(size_t)c * m + r];
            in += (size_t)d * d;
        }
        for (int blk = 0; blk < 2; blk++) {              /* dff x d */
            int m = dff, ncol = d;
            const double *b = in + (size_t)blk * dff * d;
            for (int r = 0; r < m; r++)
                for (int c = 0; c < ncol; c++) *o++ = b[(size_t)c * m + r];
            in += (size_t)dff * d;
        }
        { int m = d, ncol = dff;                        /* d x dff */
            const double *b = in;
            for (int r = 0; r < m; r++)
                for (int c = 0; c < ncol; c++) *o++ = b[(size_t)c * m + r];
        }
    }
    g_wbuf = upload_bf(tmp, out_n);
    free(tmp);
    g_wkey = src;
    g_wn = n;
    return g_wbuf;
}

static id<MTLBuffer> upload_bf(const double *src, size_t n)
{
    uint16_t *tmp = (uint16_t *)malloc(n * sizeof(uint16_t));
    if (!tmp) return nil;
    d2bf(src, tmp, n);
    id<MTLBuffer> b = [g_device newBufferWithBytes:tmp
                                            length:n * sizeof(uint16_t)
                                           options:MTLResourceStorageModeShared];
    free(tmp);
    return b;
}

void mg_matvec_bf16(double *y, const double *W, const double *x, int rows, int cols)
{
    if (rows <= 0 || cols <= 0) return;
    if (!mg_available() || !g_p_matvec_bf) {
        mg_matvec(y, W, x, rows, cols);
        return;
    }
    @autoreleasepool {
        size_t wx = (size_t)rows * cols;
        id<MTLBuffer> bW = upload_bf(W, wx);
        id<MTLBuffer> bx = upload_bf(x, (size_t)cols);
        id<MTLBuffer> by = [g_device newBufferWithLength:(size_t)rows * sizeof(float)
                                                 options:MTLResourceStorageModeShared];
        unsigned int urows = (unsigned int)rows, ucols = (unsigned int)cols;
        id<MTLBuffer> br = [g_device newBufferWithBytes:&urows length:sizeof(unsigned int)
                                                options:MTLResourceStorageModeShared];
        id<MTLBuffer> bc = [g_device newBufferWithBytes:&ucols length:sizeof(unsigned int)
                                                options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> cb = [g_queue commandBuffer];
        id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
        [e setComputePipelineState:g_p_matvec_bf];
        [e setBuffer:by offset:0 atIndex:0];
        [e setBuffer:bW offset:0 atIndex:1];
        [e setBuffer:bx offset:0 atIndex:2];
        [e setBuffer:br offset:0 atIndex:3];
        [e setBuffer:bc offset:0 atIndex:4];
        [e dispatchThreadgroups:MTLSizeMake(rows, 1, 1)
            threadsPerThreadgroup:MTLSizeMake(256, 1, 1)];
        [e endEncoding];
        g_gpu_s += dispatch_and_wait(cb);
        download_b(by, y, (size_t)rows);
    }
}

void mg_attn_state_bf16(double *S, double alpha, const double *k, const double *v, int d)
{
    if (d <= 0) return;
    if (!mg_available() || !g_p_state_bf) {
        mg_attn_state(S, alpha, k, v, d);
        return;
    }
    @autoreleasepool {
        size_t n = (size_t)d * d;
        uint16_t *tmp = (uint16_t *)malloc(n * sizeof(uint16_t));
        if (!tmp) return;
        d2bf(S, tmp, n);
        id<MTLBuffer> bS = [g_device newBufferWithBytes:tmp
                                                length:n * sizeof(uint16_t)
                                               options:MTLResourceStorageModeShared];
        id<MTLBuffer> bk = upload_bf(k, (size_t)d);
        id<MTLBuffer> bv = upload_bf(v, (size_t)d);
        float fa = (float)alpha;
        id<MTLBuffer> ba = [g_device newBufferWithBytes:&fa length:sizeof(float)
                                                options:MTLResourceStorageModeShared];
        unsigned int ud = (unsigned int)d;
        id<MTLBuffer> bd = [g_device newBufferWithBytes:&ud length:sizeof(unsigned int)
                                                options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> cb = [g_queue commandBuffer];
        id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
        [e setComputePipelineState:g_p_state_bf];
        [e setBuffer:bS offset:0 atIndex:0];
        [e setBuffer:bk offset:0 atIndex:1];
        [e setBuffer:bv offset:0 atIndex:2];
        [e setBuffer:ba offset:0 atIndex:3];
        [e setBuffer:bd offset:0 atIndex:4];
        [e dispatchThreadgroups:MTLSizeMake((d + 15) / 16, (d + 15) / 16, 1)
            threadsPerThreadgroup:MTLSizeMake(16, 16, 1)];
        [e endEncoding];
        g_gpu_s += dispatch_and_wait(cb);
        bf2d((const uint16_t *)bS.contents, S, n);
        free(tmp);
    }
}

/* ---------------------------------------------------------------------------
 * mg_fused_steps — `steps` tokens, all layers, ONE dispatch.
 *
 * This is the shape the measurements point at: the batched path still
 * issues one dispatch per inner loop and pays ~12 us of commit each, which
 * is the entire cost of a forward step. Here the whole step sequence is
 * inside the shader and the ARM side issues exactly one dispatch per call.
 *
 * The trade is explicit: f32 in, f32 out, and the intermediates stay on the
 * GPU (the per-token SwiGLU activations are computed and consumed inside
 * the kernel), so this is NOT a bit-identical replacement for the scalar
 * path — it is the shape a production kernel would have.
 * ------------------------------------------------------------------------- */
void mg_fused_steps(double *Y, const double *W, const double *X,
                    double *S, double alpha,
                    int steps, int layers, int d, int dff)
{
    mg_fused_steps_v(Y, W, X, S, alpha, steps, layers, d, dff, 0);
}

void mg_fused_steps_v(double *Y, const double *W, const double *X,
                      double *S, double alpha,
                      int steps, int layers, int d, int dff, int splitk)
{
    if (steps <= 0 || layers <= 0 || d <= 0 || dff <= 0) return;
    if (!mg_available() || !g_p_fused) {
        /* Scalar fallback: the same stack, on the CPU, so the results are
         * interchangeable whichever path ran. */
        double t0 = now_s();
        double *xv = (double *)malloc(sizeof(double) * d);
        double *q = (double *)malloc(sizeof(double) * d);
        double *k = (double *)malloc(sizeof(double) * d);
        double *v = (double *)malloc(sizeof(double) * d);
        double *ov = (double *)malloc(sizeof(double) * d);
        double *gt = (double *)malloc(sizeof(double) * dff);
        for (int t = 0; t < steps; t++) {
            for (int i = 0; i < d; i++) xv[i] = X[(size_t)t * d + i];
            for (int L = 0; L < layers; L++) {
                const double *L1 = W + (size_t)L * (4 * d * d + 2 * dff * d + d * dff);
                const double *L2 = L1 + 4 * d * d;
                const double *L3 = L2 + 2 * dff * d;
                double *SL = S + (size_t)L * d * d;
                for (int i = 0; i < d; i++) {
                    const double *rq = L1 + i * d, *rk = L1 + d * d + i * d, *rv = L1 + 2 * d * d + i * d;
                    double a = 0, b = 0, c = 0;
                    for (int j = 0; j < d; j++) { a += rq[j] * xv[j]; b += rk[j] * xv[j]; c += rv[j] * xv[j]; }
                    q[i] = a; k[i] = b; v[i] = c;
                }
                for (int j = 0; j < d; j++)
                    for (int i = 0; i < d; i++) SL[(size_t)j * d + i] = alpha * SL[(size_t)j * d + i] + k[j] * v[i];
                for (int i = 0; i < d; i++) {
                    double a = 0;
                    for (int j = 0; j < d; j++) a += SL[(size_t)j * d + i] * q[j];
                    ov[i] = a;
                }
                for (int i = 0; i < d; i++) {
                    const double *r = L1 + 3 * d * d + i * d;
                    double a = 0;
                    for (int j = 0; j < d; j++) a += r[j] * ov[j];
                    xv[i] = xv[i] + a;
                }
                for (int i = 0; i < dff; i++) {
                    const double *rg = L2 + i * d, *ru = L2 + dff * d + i * d;
                    double a = 0, b = 0;
                    for (int j = 0; j < d; j++) { a += rg[j] * xv[j]; b += ru[j] * xv[j]; }
                    gt[i] = (a > 0 ? a / (1.0 + exp(-a)) : 0.0) * b;
                }
                for (int i = 0; i < d; i++) {
                    const double *r = L3 + i * dff;
                    double a = 0;
                    for (int j = 0; j < dff; j++) a += r[j] * gt[j];
                    xv[i] = a;
                }
            }
            for (int i = 0; i < d; i++) Y[(size_t)t * d + i] = xv[i];
        }
        free(xv); free(q); free(k); free(v); free(ov); free(gt);
        g_cpu_s += now_s() - t0;
        return;
    }
    @autoreleasepool {
        size_t wcount = (size_t)layers * (4 * d * d + 2 * dff * d + d * dff);
        size_t xcount = (size_t)steps * d;
        id<MTLBuffer> bW = upload_bf_t_cached(W, wcount, layers, d, dff);
        id<MTLBuffer> bX = upload_bf(X, xcount);
        /* The state changes every step, so it is never cached. */
        /* The state is IN/OUT: it is uploaded, the kernel decays it in
         * place, and it comes back — that is the whole point of a recurrent
         * layer, and a newBufferWithLength of uninitialised shared memory is
         * how this produced a step full of NaN. */
        size_t scount = (size_t)layers * d * d;
        id<MTLBuffer> bS = upload_d(S, scount);
        id<MTLBuffer> bY = [g_device newBufferWithLength:xcount * sizeof(float)
                                                options:MTLResourceStorageModeShared];
        float fa = (float)alpha;
        unsigned int us = (unsigned int)steps, ul = (unsigned int)layers;
        unsigned int ud = (unsigned int)d, udff = (unsigned int)dff;
        id<MTLBuffer> ba = [g_device newBufferWithBytes:&fa length:sizeof(float)
                                                options:MTLResourceStorageModeShared];
        id<MTLBuffer> bs = [g_device newBufferWithBytes:&us length:sizeof(unsigned int)
                                                options:MTLResourceStorageModeShared];
        id<MTLBuffer> bl = [g_device newBufferWithBytes:&ul length:sizeof(unsigned int)
                                                options:MTLResourceStorageModeShared];
        id<MTLBuffer> bd = [g_device newBufferWithBytes:&ud length:sizeof(unsigned int)
                                                options:MTLResourceStorageModeShared];
        id<MTLBuffer> bff = [g_device newBufferWithBytes:&udff length:sizeof(unsigned int)
                                                 options:MTLResourceStorageModeShared];
        id<MTLCommandBuffer> cb = [g_queue commandBuffer];
        id<MTLComputeCommandEncoder> e = [cb computeCommandEncoder];
        [e setComputePipelineState:(splitk && g_p_fused_sk) ? g_p_fused_sk : g_p_fused];
        [e setBuffer:bW offset:0 atIndex:0];
        [e setBuffer:bX offset:0 atIndex:1];
        [e setBuffer:bS offset:0 atIndex:2];
        [e setBuffer:bY offset:0 atIndex:3];
        [e setBuffer:ba offset:0 atIndex:4];
        [e setBuffer:bs offset:0 atIndex:5];
        [e setBuffer:bl offset:0 atIndex:6];
        [e setBuffer:bd offset:0 atIndex:7];
        [e setBuffer:bff offset:0 atIndex:8];
        [e dispatchThreadgroups:MTLSizeMake((unsigned int)(layers * steps), 1, 1)
            threadsPerThreadgroup:MTLSizeMake(splitk ? 1024 : 256, 1, 1)];
        [e endEncoding];
        g_gpu_s += dispatch_and_wait(cb);
        download_b(bY, Y, xcount);
        f2d((const float *)bS.contents, S, scount);
    }
}
