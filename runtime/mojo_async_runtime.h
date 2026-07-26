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

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* MOJO_ASYNC_RUNTIME_H */
