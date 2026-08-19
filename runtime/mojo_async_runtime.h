#ifndef MOJO_ASYNC_RUNTIME_H
#define MOJO_ASYNC_RUNTIME_H
/*
 * mojo_async_runtime.h / .cpp — Step A (toolchain/runtime scaffolding) of the
 * compiled-path async/await codegen project, which follows directly on from
 * the compiled-generator project (see BACKLOG-CODEGEN.md / commits 70e08ae
 * through 11631d1).
 *
 * This is deliberately proof-of-mechanism ONLY: nothing in gimple_codegen.py
 * emits calls into this header yet (that's Step B). This is a real C++20
 * coroutine scheduler — a ready queue, a monotonic-clock timer min-heap, and
 * a kqueue-based reactor scaffold — exercised only by hand-written C++ test
 * code (test_async_runtime_scaffold.py), proven through the REAL project
 * build system (build_config.find_gxx() + mojo.link_executable(cxx=True)),
 * exactly mirroring how the generator project's Milestone A
 * (test_mixed_cpp_link.py) proved its own toolchain plumbing before any real
 * codegen touched it.
 *
 * Calling convention: a `std::coroutine_handle<>` is exactly a wrapped
 * pointer to the compiler-allocated coroutine frame (this is the exact same
 * observation the generator codegen's MojoGenerator* convention relies on —
 * see _gen_cpp_generator_unit's docstring in gimple_codegen.py) so the
 * `extern "C"` boundary below represents a handle as a plain `void*`
 * (`.address()` / `from_address()`), never a C++ type, so that a future
 * mixed C/C++ build (an ordinary -fgimple C translation unit produced by
 * gimple_codegen.py) can eventually call these functions without needing to
 * know anything about C++ coroutines.
 *
 * Threading model: single-threaded, cooperative — exactly like the
 * semantics `async def`/`await` need. There is no locking anywhere in this
 * scaffold; it is not meant to be called from more than one thread.
 */

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* A type-erased coroutine-handle address (std::coroutine_handle<>::address()
 * on the C++ side; from_address() reconstructs it before .resume()). */
typedef void *mojo_coro_handle;

/* Reset all queues/reactor state to empty. Safe to call multiple times;
 * mojo_async_run_until_complete() also works correctly without an explicit
 * init call (lazy first-use initialization), this is provided mainly so
 * tests can get a clean slate between cases. */
void mojo_async_init(void);

/* Release the kqueue fd (if one was ever created) and clear all queues.
 * Not required for correctness of a single run, but keeps repeated test
 * runs within one process from leaking kqueue fds. */
void mojo_async_shutdown(void);

/* Current CLOCK_MONOTONIC time in nanoseconds — the same clock/units the
 * timer queue is keyed by, exposed so callers can compute absolute wake
 * times (mojo_async_now_ns() + delay_ns) without needing <time.h> plumbing
 * of their own. */
uint64_t mojo_async_now_ns(void);

/* Push a coroutine handle onto the ready queue — it will be resumed the
 * next time the run loop drains the ready queue. */
void mojo_async_schedule_ready(mojo_coro_handle h);

/* Schedule a coroutine handle to become ready at absolute time
 * wake_time_ns (CLOCK_MONOTONIC, same clock as mojo_async_now_ns()). This is
 * the primitive a hand-written `co_await mojo_sleep_for(...)` awaiter's
 * `await_suspend` uses to arm the wakeup. */
void mojo_async_schedule_timer(mojo_coro_handle h, uint64_t wake_time_ns);

/* --- kqueue reactor scaffold ---
 *
 * Proof-of-mechanism only (full Mojo-level socket I/O is Step F of this
 * project, explicitly out of scope here): registers interest in a fd
 * becoming readable/writable, waking the given coroutine handle exactly
 * once (one-shot, like EV_ONESHOT) when kevent() reports it ready. The run
 * loop folds these registrations into the same wait as the timer queue's
 * next deadline (the standard "timer deadline as the kevent timeout"
 * pattern), so a coroutine can be waiting on a timer and a fd at the same
 * time and whichever fires first wins.
 */

/* Register interest in fd becoming readable. When ready, h is moved to the
 * ready queue and the registration is automatically removed (one-shot). */
void mojo_async_register_read(int fd, mojo_coro_handle h);

/* Register interest in fd becoming writable. Same one-shot semantics. */
void mojo_async_register_write(int fd, mojo_coro_handle h);

/* Cancel any pending read/write registration for fd (e.g. on early
 * cancellation/timeout of an await). Safe to call even if fd has no
 * pending registration. */
void mojo_async_cancel(int fd);

/* Run the scheduler until the ready queue, timer queue, and reactor
 * registrations are ALL empty. Drains the ready queue (resuming each
 * handle — which may itself schedule more ready/timer/reactor work), and
 * whenever the ready queue empties out but there is still timer or reactor
 * work pending, blocks (via kevent, with a timeout derived from the next
 * timer deadline) until either the next timer is due or a registered fd
 * becomes ready, then loops. Returns once there is genuinely nothing left
 * to do. */
void mojo_async_run_until_complete(void);

/* --- Generic (promise-type-erased) resume/destroy ---
 *
 * For Mojo source that extracts a raw coroutine handle via
 * `Coroutine._take_handle()` and hands it to native code that will
 * resume/destroy it itself, later, on its own schedule (e.g.
 * std.gpu.host.DeviceContext.enqueue_cpu_function's `_coro_resume_fn`/
 * `_coro_destroy_fn` arguments to AsyncRT_DeviceContext_enqueueHostFunction,
 * below) — added alongside gimple_codegen.py's "detached async" codegen
 * path (the narrow shape: an `async def` with parameters allowed only when
 * its body never itself contains `await` and its only use at the call site
 * is `_take_handle()`; see _detached_async_quick_eligible's docstring).
 *
 * A C++20 coroutine's resume()/destroy() functions live INSIDE the
 * coroutine frame itself (the Itanium C++ coroutine ABI stores them
 * there) — std::coroutine_handle<>::from_address(h).resume()/.destroy()
 * reads them back out generically, with NO dependency on which concrete
 * promise type produced the handle. So, unlike the per-function
 * <base>_start/_value/_destroy trampolines gimple_codegen.py emits
 * elsewhere in this project (one set per compiled async/generator
 * function), ONE pair of these functions genuinely serves EVERY compiled
 * coroutine this codegen ever emits — this mirrors real Mojo's own
 * `_coro_resume_fn`/`_coro_destroy_fn` builtins (std.builtin.coroutine)
 * exactly, which gimple_codegen.py's lowering for the `_take_handle()`-
 * based external-dispatch call shape substitutes references to these two
 * functions for (rather than ever attempting to compile the real
 * `_coro_resume_fn`/`_coro_destroy_fn` Mojo source bodies themselves,
 * which use raw `__mlir_op.co.resume`/`co.destroy` ops this codegen has
 * no general lowering for — see coroutine.mojo's compiled output, which
 * already reduces those to inert "deferred: coroutine lowering not
 * modeled" stubs; letting THOSE stubs leak into this call path would
 * silently make `func()` never actually run).
 *
 * Handles are plain `int64_t` here (not `void*`), matching how this
 * codegen already represents AnyCoroutine/opaque handle values everywhere
 * else (see coroutine.mojo's compiled `_coro_resume_fn_...(int64_t)`). */
void mojo_coro_resume_generic(int64_t handle);
void mojo_coro_destroy_generic(int64_t handle);

/* --- AsyncRT_DeviceContext_enqueueHostFunction(Range) ---
 *
 * DELIBERATE SYNCHRONOUS SIMPLIFICATION, not real GPU stream-ordered
 * dispatch — see bugs/CODEGEN_device_context_host_function_enqueue_
 * synchronous_stub.md for the full writeup. Real AsyncRT enqueues the
 * given host callback onto whichever GPU stream `device_ctx_handle`
 * names and returns immediately; the callback runs later, out-of-line,
 * once every op enqueued before it on that stream has completed. This
 * project's compiled path has no GPU stream model at all (building one is
 * a separate, much larger future project — see this project's own MSL/
 * Metal-offload long-term notes), so these stubs run the wrapped callback
 * SYNCHRONOUSLY, immediately, inline, before returning: call
 * resume_fn(handle) exactly once (the wrapped Mojo closure's whole body
 * has no internal suspension point — see
 * gimple_codegen.py's `_detached_async_quick_eligible` — so one resume()
 * genuinely drives it to completion, this is not merely "close enough"),
 * then destroy_fn(handle) to free the coroutine frame. This is honest for
 * every CURRENT call site (device_context.mojo's four `wrapper()`
 * closures, which only ever wrap a plain, synchronous host callback with
 * no awaits of its own) but is NOT a substitute for real ordered GPU
 * dispatch — a caller that actually depended on stream ordering relative
 * to other enqueued GPU work would observe different (wrong) behavior.
 * Returns NULL (success) always — matching this codegen's established
 * `_CString`/`_checked()` "NULL or an error message" convention — since a
 * purely local, synchronous function-pointer call has no real failure
 * mode to report here. */
const char *AsyncRT_DeviceContext_enqueueHostFunction(
    int64_t device_ctx_handle,
    void (*resume_fn)(int64_t),
    void (*destroy_fn)(int64_t),
    int64_t coro_handle);

const char *AsyncRT_DeviceContext_enqueueHostFunctionRange(
    int64_t device_ctx_handle,
    void (*resume_fn)(int64_t),
    void (*destroy_fn)(int64_t),
    const int64_t *coro_handles,
    int64_t count);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* MOJO_ASYNC_RUNTIME_H */
