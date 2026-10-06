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
#include <sys/time.h>

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
/* Device buffers, reused across calls, keyed by ARGUMENT SLOT.
 *
 * `newBufferWithBytes:` was called once per buffer per call -- at 512x512x4096
 * that is two 8 MB allocations and copies every iteration, for data that is
 * usually the SAME data every iteration. Allocating and freeing that repeatedly
 * is most of why the offload path moved bytes at ~1 GB/s while a plain memcpy on
 * the same machine manages ~10.
 *
 * Keyed by slot, not by size. The buffer at index `bi` is the same ROLE on every
 * call (A is A, C is C), and the generated wrapper always passes them in the
 * same order, so a role-keyed cache hits where a size-keyed one would thrash
 * between two shapes. Grow-only: a smaller request reuses the larger buffer and
 * uses a prefix of it.
 *
 * CORRECTNESS does not depend on the host data being unchanged, because the
 * host bytes are memcpy'd in on EVERY call. The cache only removes the
 * allocation, never the upload. That distinction is the whole safety argument:
 * a cache that skipped the upload would need to know the host buffer had not
 * been written, and nothing here can know that.
 *
 * A stale-but-correct buffer is still a hazard in one direction: a previous
 * call may have left MORE live elements than this one uploads, so a kernel that
 * read past `sizes[bi]` would see old data instead of nothing. Bounds are
 * checked against the m/k/n scalars, which are re-uploaded every call, so that
 * cannot happen -- but it is why the sizes are not cached alongside.
 *
 * Retention is bounded two ways: _MG_BUF_MAX slots, and _MG_BUF_TOTAL bytes.
 * Past the byte cap we stop caching and allocate per call, which is no worse
 * than the behaviour this replaced.
 *
 * Not thread-safe. Neither is the rest of this file: g_dispatches and the
 * pipeline cache below are plain statics mutated without a lock, and this
 * runtime has always been called from the one thread that owns the device.
 */
#define _MG_BUF_MAX 16
#define _MG_BUF_TOTAL (256u << 20)
#define _MG_SCAL_OFF _MG_BUF_MAX
#define _MG_BUF_SLOTS (_MG_BUF_MAX * 2)
static id<MTLBuffer> g_buf[_MG_BUF_SLOTS] __attribute__((unused));
static NSUInteger g_buf_len[_MG_BUF_SLOTS] __attribute__((unused));
static size_t g_buf_total __attribute__((unused));
static int64_t g_buf_hits, g_buf_misses __attribute__((unused));

static id<MTLBuffer> _mg_upload(id<MTLDevice> dev, const void *host,
                                NSUInteger nbytes, int slot) {
    if (slot >= 0 && slot < _MG_BUF_MAX) {
        if (g_buf[slot] && g_buf_len[slot] >= nbytes) {
            g_buf_hits++;
            /* The upload happens whether or not the buffer was reused -- that
             * is what makes a hit safe. */
            if (nbytes) memcpy([g_buf[slot] contents], host, nbytes);
            return g_buf[slot];
        }
        g_buf_misses++;
        if (g_buf[slot]) {
            g_buf_total -= g_buf_len[slot];
            g_buf[slot] = nil;      /* ARC releases the old one */
        }
        /* Only adopt the new one if the cache is not already over its cap. */
        if (g_buf_total + nbytes <= _MG_BUF_TOTAL) {
            id<MTLBuffer> b = [dev newBufferWithLength:nbytes
                options:MTLResourceStorageModeShared];
            if (b) {
                if (nbytes) memcpy([b contents], host, nbytes);
                g_buf[slot] = b;
                g_buf_len[slot] = nbytes;
                g_buf_total += nbytes;
                return b;
            }
            g_buf[slot] = nil;
            g_buf_len[slot] = 0;
        }
    }
    /* Uncached path, and the fallback when the cap is hit. */
    return [dev newBufferWithBytes:host length:nbytes
        options:MTLResourceStorageModeShared];
}

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
        const int _mg_tr = getenv("MOJO_GEMM_TRACE") != NULL;
        double _mg_t[8]; int _mg_i = 0;
        double _mg_up = 0, _mg_bind = 0;
        #define MG_NOW() ({ struct timeval _tv; gettimeofday(&_tv, 0); \
            (double)_tv.tv_sec * 1e6 + (double)_tv.tv_usec; })
        #define MG_BUMP(acc) do { if (_mg_tr) { double _n = MG_NOW(); \
            acc += _n - _mg_last; _mg_last = _n; } } while (0)
        double _mg_last = 0;
        #define MG_TICK() do { if (_mg_tr) { struct timeval _tv; \
            gettimeofday(&_tv, 0); \
            _mg_t[_mg_i++] = (double)_tv.tv_sec * 1e6 + (double)_tv.tv_usec; \
        } } while (0)
        #define MG_MARK(i) do { if (_mg_tr) { struct timeval _tv; \
            gettimeofday(&_tv, 0); \
            _mg_t[(i)] = (double)_tv.tv_sec * 1e6 + (double)_tv.tv_usec; \
        } } while (0)
        MG_TICK(); _mg_last = MG_NOW();
        id<MTLFunction> fn = [g_lib newFunctionWithName:
                              [NSString stringWithUTF8String:kernel_name]];
        MG_MARK(1);
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
        MG_MARK(2);
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
                NSUInteger nbytes = (NSUInteger)(n * (int64_t)sizeof(float));
                id<MTLBuffer> db = _mg_upload(g_device, bufs[bi], nbytes,
                                              (int)bi);
                MG_BUMP(_mg_up);
                if (!db) {
                    _set_error("buffer %lld allocation failed", (long long)bi);
                    goto fail;
                }
                [enc setBuffer:db offset:0 atIndex:(NSUInteger)bi];
                MG_BUMP(_mg_bind);
                devbufs[bi] = db;
            } else {
                int64_t si = bi - n_bufs;
                NSUInteger w = widths ? widths[si] : (NSUInteger)sizeof(int64_t);
                if (w == 0) w = (NSUInteger)sizeof(int64_t);
                /* Cached like the data buffers, and for the same reason. This
                 * was the whole fixed per-dispatch cost: phase timing showed
                 * ~190 us in bind+upload for a 12 KB payload, and a 12 KB
                 * memcpy is ~1 us, so the time was never the copying. A GEMM
                 * has three scalars (m, k, n) and each was a fresh
                 * `newBufferWithLength:` on every single call -- three MTLBuffer
                 * allocations to hold 4 bytes each. MTLBuffer allocation is
                 * not free and this was paying it 3x per dispatch to pass three
                 * integers.
                 *
                 * Keyed by scalar slot and grow-only, like the data buffers, and
                 * the value is still written on every call -- the cache removes
                 * the allocation, never the store. */
                id<MTLBuffer> db = NULL;
                int _s = (int)si;
                if (_s >= 0 && _s < _MG_BUF_MAX && g_buf[_MG_SCAL_OFF + _s]
                        && g_buf_len[_MG_SCAL_OFF + _s] >= w) {
                    g_buf_hits++;
                    db = g_buf[_MG_SCAL_OFF + _s];
                } else {
                    g_buf_misses++;
                    db = [g_device newBufferWithLength:w
                        options:MTLResourceStorageModeShared];
                    if (db && _s >= 0 && _s < _MG_BUF_MAX
                        && g_buf_total + w <= _MG_BUF_TOTAL) {
                        g_buf[_MG_SCAL_OFF + _s] = db;
                        g_buf_len[_MG_SCAL_OFF + _s] = w;
                        g_buf_total += w;
                    }
                }
                if (!db) {
                    _set_error("scalar %lld allocation failed", (long long)si);
                    goto fail;
                }
                if (scalars && scalars[si])
                    memcpy([db contents], scalars[si], w);
                else
                    memset([db contents], 0, w);
                [enc setBuffer:db offset:0 atIndex:(NSUInteger)bi];
                MG_BUMP(_mg_bind);
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
        MG_MARK(3);
        [enc dispatchThreadgroups:MTLSizeMake(tg, 1, 1)
            threadsPerThreadgroup:MTLSizeMake(use, 1, 1)];
        MG_MARK(4);
        [enc endEncoding];
        [cb commit];
        MG_MARK(5);
        [cb waitUntilCompleted];
        MG_MARK(6);
        if (cb.error) {
            _set_error("dispatch of '%s' failed: %s", kernel_name,
                       cb.error.description.UTF8String);
            return 0;
        }
        MG_MARK(7);
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
        MG_MARK(6);
        if (_mg_tr) {
            static int64_t _mg_n = 0;
            if ((++_mg_n % 200) == 0) {
                fprintf(stderr, "[mg] %-22s fn %4.0f  pipe %4.0f  "
                        "bind %5.0f  dispatch %6.0f  commit %5.0f  wait %6.0f  "
                        "copybk %5.0f  TOTAL %6.0f us\n",
                        kernel_name,
                        _mg_t[1] - _mg_t[0], _mg_t[2] - _mg_t[1],
                        _mg_t[3] - _mg_t[2], _mg_t[4] - _mg_t[3],
                        _mg_t[5] - _mg_t[4], _mg_t[6] - _mg_t[5],
                        _mg_t[7] - _mg_t[6], _mg_t[7] - _mg_t[0]);
            }
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
