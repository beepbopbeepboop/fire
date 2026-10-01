/* Metal device runtime: a C API over Apple's Objective-C framework.
 * See fire_metal.h for the contract and for WHY this file exists (the
 * generated .ci is gimple C, and gimple has no Objective-C).
 *
 * Everything device-touching is reached through a lazily-initialised
 * library compiled from a source STRING handed in by the compiler's
 * sidecar, not from a precompiled .metallib.
 */
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>

#include "fire_metal.h"

#include <stdio.h>
#include <string.h>

/* Device-side singletons. `g_ready` guards init so a dispatch from any
 * thread, or a second dispatch, is a no-op check rather than a second
 * library compile. */
static id<MTLDevice>          g_device = nil;
static id<MTLCommandQueue>    g_queue = nil;
static id<MTLLibrary>         g_lib = nil;
static int                    g_have_device = 0;
static int64_t                g_dispatches = 0;
/* Failed dispatches since load, process-wide, alongside g_dispatches.
 * The generated sidecar used to keep its own per-translation-unit
 * `_mg_failures`, which meant a query from a different unit than the
 * dispatch read that unit's zero. The counters belong HERE, next to the
 * device state they describe, so there is one answer per process. */
static int64_t                g_failures = 0;
static char                   g_error[512] = "";

static void _set_error(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(g_error, sizeof g_error, fmt, ap);
    va_end(ap);
}

const char *mojo_metal_last_error(void) { return g_error; }

static int mojo_metal_dispatch_impl(const char *, int64_t, void *const *,
                          const int64_t *, int64_t, void *const *,
                          const uint8_t *, const uint8_t *, int64_t,
                          int64_t);
int64_t mojo_metal_dispatch_count(void) { return g_dispatches; }
int64_t mojo_metal_failure_count(void) { return g_failures; }
int64_t mojo_metal_have_device(void) { return g_have_device; }

int mojo_metal_init(const char *msl_source) {
    if (g_have_device) return 1;
    if (g_device != nil) return g_have_device;   /* already tried, no device */

    @autoreleasepool {
        g_device = MTLCreateSystemDefaultDevice();
        if (!g_device) {
            _set_error("no Metal device on this machine");
            return 0;
        }
        NSError *err = nil;
        MTLCompileOptions *opts = [[MTLCompileOptions alloc] init];
        /* metal3.2 is the first language version with a native `bfloat`
         * type, which the generated kernels use for the bf16 paths. There
         * is no setting that gets a `double` -- MSL has none at any
         * version -- which is why the host side is fp64 and the device
         * side is fp32, and why agreement is checked rather than assumed. */
        opts.languageVersion = MTLLanguageVersion3_2;
        g_lib = [g_device newLibraryWithSource:
                 [NSString stringWithUTF8String:msl_source ? msl_source : ""]
                                      options:opts error:&err];
        if (!g_lib) {
            _set_error("MSL compile failed: %s",
                       err ? err.description.UTF8String : "(no error detail)");
            return 0;
        }
        g_queue = [g_device newCommandQueue];
        if (!g_queue) {
            _set_error("device has no command queue");
            return 0;
        }
        g_have_device = 1;
    }
    return 1;
}

/* The real body. Everything that decides success or failure is in here, and
 * it returns 1 or 0 -- it does NOT count. The counting is one line, in the
 * wrapper below, so no early return and no `fail:` label can be missed. An
 * earlier version counted at the success tail only, which meant every one of
 * the failure paths (no device, no library, no function, no pipeline, OOM,
 * encoder failure) silently reported zero failures. */
/* Pipeline states, cached by kernel name.
 *
 * Creating one is NOT free: `newComputePipelineStateWithFunction:` asks the
 * driver to compile and validate the function against the device, and it was
 * being called ONCE PER DISPATCH. That was the single largest cost in the whole
 * offload path, and it was invisible in the obvious way -- a 32x32x32 GEMM,
 * which does 65 KFLOP and should cost nothing, took 1 ms per call, and so did
 * a 128x128x128. A fixed cost that does not shrink with the work is a
 * per-call setup cost by definition, and this was the only one.
 *
 * It is safe to cache because a pipeline state is a function of (library,
 * function) and the device, all three of which are fixed for the process --
 * g_lib is built once by mojo_metal_init and never replaced, and g_device is
 * the system default. Nothing in this file can produce a second library, so
 * there is no way for a cache hit to return a state built from a stale source.
 *
 * Bounded and linear: a module has a handful of kernels, and this only runs on
 * a miss. A miss past the bound simply stops caching rather than evicting,
 * because a workload that needs more than this many DISTINCT kernels is not
 * one where a linear scan is the bottleneck.
 */
#define _MG_PS_MAX 64
static id<MTLComputePipelineState> g_ps[_MG_PS_MAX] __attribute__((unused));
static char *g_ps_name[_MG_PS_MAX] __attribute__((unused));
static int64_t g_ps_hits, g_ps_misses __attribute__((unused));

static id<MTLComputePipelineState> _mg_pipeline(id<MTLDevice> dev,
                                                id<MTLLibrary> lib,
                                                id<MTLFunction> fn,
                                                const char *name) {
    for (int i = 0; i < _MG_PS_MAX; i++) {
        if (g_ps_name[i] && strcmp(g_ps_name[i], name) == 0) {
            g_ps_hits++;
            return g_ps[i];
        }
    }
    g_ps_misses++;
    NSError *err = nil;
    id<MTLComputePipelineState> ps =
        [dev newComputePipelineStateWithFunction:fn error:&err];
    if (!ps) {
        _set_error("no pipeline for '%s': %s", name,
                   err ? err.description.UTF8String : "?");
        return nil;
    }
    for (int i = 0; i < _MG_PS_MAX; i++) {
        if (!g_ps_name[i]) {
            g_ps_name[i] = strdup(name);
            g_ps[i] = ps;           /* ARC retains into the strong static */
            break;
        }
    }
    (void)lib;
    return ps;
}

static int mojo_metal_dispatch_impl(const char *kernel_name,
                        int64_t n_bufs, void *const *bufs,
                        const int64_t *sizes,
                        int64_t n_scalars, void *const *scalars,
                        const uint8_t *widths,
                        const uint8_t *writable,
                        int64_t nthreads, int64_t ngroups) {
    if (!g_have_device || !g_lib) {
        _set_error("no Metal device");
        return 0;
    }
    @autoreleasepool {
        id<MTLFunction> fn = [g_lib newFunctionWithName:
                              [NSString stringWithUTF8String:kernel_name]];
        if (!fn) {
            _set_error("no kernel named '%s' in the compiled library", kernel_name);
            return 0;
        }
        id<MTLComputePipelineState> ps = _mg_pipeline(g_device, g_lib, fn,
                                                      kernel_name);
        if (!ps) return 0;
    if (getenv("MOJO_GEMM_TRACE"))
        fprintf(stderr, "[mg] %s ps_hits=%lld ps_misses=%lld\n", kernel_name,
                (long long)g_ps_hits, (long long)g_ps_misses);
        id<MTLBuffer> __strong *devbufs = NULL;
        if (n_bufs > 0) {
            devbufs = (id<MTLBuffer> __strong *)
                calloc((size_t)n_bufs, sizeof(id<MTLBuffer>));
            if (!devbufs) { _set_error("out of memory"); return 0; }
        }
        id<MTLCommandBuffer> cb = [g_queue commandBuffer];
        id<MTLComputeCommandEncoder> enc = [cb computeCommandEncoder];
        [enc setComputePipelineState:ps];
        /* Bind in ARGUMENT ORDER, not "all buffers then all scalars".
         *
         * The MSL the compiler emits declares scalar kernel parameters as
         * `constant T &`, which in Metal is a typed reference into constant
         * space at a specific buffer index -- and T is whatever the emitter
         * chose (an `Int` lowers to `int`, 4 bytes). So each scalar gets its
         * own constant buffer holding exactly `widths[i]` bytes, copied
         * verbatim from the host value the generated wrapper already
         * narrowed. Binding a double here and hoping the device reads the
         * low half is how an earlier version turned `len=1024` into
         * `len=0` and made the kernel compute nothing at exit 0.
         */
        for (int64_t bi = 0; bi < n_bufs + n_scalars; bi++) {
            BOOL is_buffer = (bi < n_bufs);
            if (is_buffer) {
                int64_t n = sizes ? sizes[bi] : 0;
                id<MTLBuffer> db = [g_device newBufferWithBytes:bufs[bi]
                    length:(NSUInteger)(n * (int64_t)sizeof(float))
                    options:MTLResourceStorageModeShared];
                if (!db) {
                    _set_error("buffer %lld allocation failed", (long long)bi);
                    goto fail;
                }
                [enc setBuffer:db offset:0 atIndex:(NSUInteger)bi];
                devbufs[bi] = db;
            } else {
                int64_t si = bi - n_bufs;
                NSUInteger w = widths ? widths[si] : (NSUInteger)sizeof(int64_t);
                if (w == 0) w = (NSUInteger)sizeof(int64_t);
                id<MTLBuffer> db = [g_device newBufferWithLength:w
                    options:MTLResourceStorageModeShared];
                if (!db) {
                    _set_error("scalar %lld allocation failed", (long long)si);
                    goto fail;
                }
                if (scalars && scalars[si])
                    memcpy([db contents], scalars[si], w);
                else
                    memset([db contents], 0, w);
                [enc setBuffer:db offset:0 atIndex:(NSUInteger)bi];
            }
        }
        /* The grid has to cover the whole output. Kernels in this tree guard
         * with `if tid >= len { return; }`, so over-dispatching is safe and
         * under-dispatching silently leaves the tail uninitialised. Take the
         * element count from the largest buffer and cover it exactly. */
        NSUInteger w = ps.threadExecutionWidth;
        NSUInteger tptg = ps.maxTotalThreadsPerThreadgroup;
        if (w == 0) w = 1;
        if (tptg < w) tptg = w;
        NSUInteger tg;
        if (ngroups > 0) {
            tg = (NSUInteger)ngroups;
        } else {
            int64_t need = 0;
            for (int64_t i = 0; i < n_bufs; i++)
                if (sizes && sizes[i] > need) need = sizes[i];
            tg = need > 0 ? (NSUInteger)((need + (int64_t)tptg - 1) / (int64_t)tptg)
                          : 1;
            /* Metal's own limit; anything past this is a caller bug, and
             * silently wrapping would produce a plausible partial result. */
            if (tg > 0xFFFFFFFFu) {
                _set_error("output of %lld elements needs more threadgroups "
                           "than Metal can dispatch", (long long)need);
                goto fail;
            }
        }
        if (tg == 0) tg = 1;
        NSUInteger use = nthreads > 0 ? (NSUInteger)nthreads : tptg;
        if (use > tptg) use = tptg;
        [enc dispatchThreadgroups:MTLSizeMake(tg, 1, 1)
            threadsPerThreadgroup:MTLSizeMake(use, 1, 1)];
        [enc endEncoding];
        [cb commit];
        [cb waitUntilCompleted];
        if (cb.error) {
            _set_error("dispatch of '%s' failed: %s", kernel_name,
                       cb.error.description.UTF8String);
            return 0;
        }
        /* Copy back only the buffers the kernel could have WRITTEN, so the
         * caller's arrays hold the result.
         *
         * This used to copy every buffer back, including the ones bound as
         * read-only inputs. For the GEMM that is A and B -- 16 of the 17 MB
         * moved per call at 512x512x512 -- copied from device to host and
         * then thrown away, because the caller already has those bytes and
         * the kernel did not touch them.
         *
         * The mask is per buffer, from the pointer's address space at the
         * call site (ImmutAnyOrigin vs MutAnyOrigin), so it is the TYPE's
         * claim, not a heuristic. A NULL mask means "copy everything", which
         * is what every pre-existing caller gets.
         */
        for (int64_t i = 0; i < n_bufs; i++) {
            int64_t n = sizes ? sizes[i] : 0;
            if (devbufs[i] && (!writable || writable[i]))
                memcpy(bufs[i], [devbufs[i] contents],
                       (size_t)(n * (int64_t)sizeof(float)));
        }
        free(devbufs);
        return 1;

    fail:
        /* A dispatch that fails after the command encoder exists still has to
         * END it. Returning without endEncoding leaves the encoder to the
         * @autoreleasepool, and Metal asserts on that --
         *
         *   -[_MTLCommandEncoder dealloc]: failed assertion `Command encoder
         *   released without endEncoding'
         *
         * which ABORTS the process. So a failed dispatch killed the program
         * instead of returning 0, which turns an ordinary, reportable
         * condition (a zero-length buffer allocation, a grid too large to
         * dispatch) into a crash that hides the real error the caller was
         * already told about by `_set_error`.
         *
         * Found by auto-offload: a length that reached the device as 0 made
         * every list pack to zero elements, `newBufferWithBytes:length:0`
         * returned nil, and that `return 0` aborted here. The underlying bug
         * was fixed at the source; this is the runtime not being allowed to
         * escalate a recoverable failure into a SIGABRT.
         *
         * endEncoding + commit is the documented way to discard an encoded
         * command; the work never runs, which is what a failure means.
         */
        [enc endEncoding];
        [cb commit];
        free(devbufs);
        return 0;
    }
}

int mojo_metal_dispatch(const char *kernel_name,
                        int64_t n_bufs, void *const *bufs,
                        const int64_t *sizes,
                        int64_t n_scalars, void *const *scalars,
                        const uint8_t *widths,
                        const uint8_t *writable,
                        int64_t nthreads, int64_t ngroups) {
    int rc = mojo_metal_dispatch_impl(kernel_name, n_bufs, bufs, sizes,
                                      n_scalars, scalars, widths, writable,
                                      nthreads, ngroups);
    if (rc) g_dispatches++; else g_failures++;
    return rc;
}
