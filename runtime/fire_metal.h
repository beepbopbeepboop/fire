/* Metal device runtime: a C API over Apple's Objective-C framework.
 *
 * Seam 3's counterpart. The generated `.ci` is compiled with
 * `gcc -fgimple -x c` (see jit/arm64.py), and gimple is a C front end --
 * `@autoreleasepool`, `id<MTLLibrary>` and `MTLCreateSystemDefaultDevice`
 * do not survive it. So every Metal call the generated code needs is
 * reached through the four C functions below, and this file is the only
 * place that has to be Objective-C.
 *
 * The API is deliberately tiny: compile a library from a string, dispatch
 * a named kernel with N buffers and M scalars, and report whether any
 * device was there. Argument marshalling is the caller's job because only
 * the caller knows which arguments are buffers.
 *
 * The MSL arrives as a string from the compiler's sidecar rather than as a
 * precompiled `.metallib`. That is the whole reason doc/METAL.md's offline
 * `xcrun metal` / `xcrun metallib` step is not needed: the driver compiles
 * the same text for whatever GPU is actually present, at load time, and
 * there is no second artifact to ship, cache-key, or wire into a build.
 */
#ifndef FIRE_METAL_H
#define FIRE_METAL_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Compile `msl_source` into a library, once per process.
 *
 * Returns 1 if a Metal device was found and the source compiled, 0
 * otherwise -- no device, or source that failed to compile. A failure is
 * reported through mojo_metal_last_error() rather than by aborting,
 * because a program containing a kernel it never dispatches must still
 * load and run on a machine with no GPU.
 */
int mojo_metal_init(const char *msl_source);

/* Dispatch a named kernel.
 *
 *   n_bufs    number of device buffers
 *   bufs      n_bufs host pointers to float data (uploaded, and the
 *             outputs copied back)
 *   sizes     n_bufs element counts, or NULL to use a length table derived
 *             at the call site
 *   n_scalars number of scalar kernel arguments
 *   scalars   n_scalars POINTERS to the scalar values, already narrowed to
 *             the exact width the MSL declares for that argument
 *   widths    n_scalars byte widths, parallel to `scalars`
 *   nthreads  threads per threadgroup, or 0 to let the runtime choose
 *   ngroups   threadgroups to dispatch, or 0 to cover the largest buffer
 *
 * Scalars are passed as (pointer, width) rather than as an array of
 * doubles because an MSL scalar kernel parameter is `constant T &` -- a
 * reference into a specific address space, at a specific width, and the
 * device reads exactly those bytes. The first version of this API passed
 * doubles and let the runtime guess: the device read the low 4 bytes of
 * the 8 it was given, so an `int len` of 1024 arrived as 0, every thread
 * took the bounds guard, and the kernel silently wrote nothing. Each
 * scalar is bound in its own constant buffer here, so the width is
 * whatever the compiler emitted rather than a host-side assumption.
 *
 * Returns 1 on a completed dispatch, 0 if there is no device, the kernel
 * name is unknown, or the GPU reported an error. mojo_metal_last_error()
 * says which.
 */
int mojo_metal_dispatch(const char *kernel_name,
                        int64_t n_bufs, void *const *bufs,
                        const int64_t *sizes,
                        int64_t n_scalars, void *const *scalars,
                        const uint8_t *widths,
                        int64_t nthreads, int64_t ngroups);

/* A human-readable reason for the last failure, or "" if none. */
const char *mojo_metal_last_error(void);

/* Number of successfully dispatched kernels since load. Lets a caller
 * assert that the device path was actually taken rather than trusting a
 * plausible-looking result. */
int64_t mojo_metal_dispatch_count(void);

#ifdef __cplusplus
}
#endif

#endif /* FIRE_METAL_H */
