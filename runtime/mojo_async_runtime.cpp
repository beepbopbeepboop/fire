/*
 * mojo_async_runtime.cpp — implementation of the Step A scheduler scaffold.
 * See mojo_async_runtime.h for the design rationale and extern "C" contract.
 *
 * Compiled with g++ -std=c++20 (via build_config.find_gxx()), the same
 * toolchain path the generator project's Milestone A
 * (test_mixed_cpp_link.py) proved out. Nothing in the rest of the project
 * links this in yet — that is Step B, once gimple_codegen.py actually emits
 * `async def`/`await` codegen that needs it.
 */
#include "mojo_async_runtime.h"

#include <coroutine>
#include <queue>
#include <vector>
#include <unordered_map>

#include <time.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/event.h>
#include <sys/time.h>

namespace {

struct TimerEntry {
    uint64_t wake_time_ns;
    mojo_coro_handle handle;
};

/* Min-heap by wake_time_ns: std::priority_queue is a max-heap by default, so
 * the comparator is inverted (a > b means "a sorts after b", i.e. later
 * wake times are "smaller priority" / come out last). */
struct TimerLater {
    bool operator()(const TimerEntry &a, const TimerEntry &b) const {
        return a.wake_time_ns > b.wake_time_ns;
    }
};

struct ReactorReg {
    mojo_coro_handle handle;
};

std::vector<mojo_coro_handle> g_ready;
std::priority_queue<TimerEntry, std::vector<TimerEntry>, TimerLater> g_timers;
std::unordered_map<int, ReactorReg> g_read_regs;
std::unordered_map<int, ReactorReg> g_write_regs;
int g_kq = -1;

int ensure_kqueue() {
    if (g_kq < 0) {
        g_kq = kqueue();
    }
    return g_kq;
}

void resume_handle(mojo_coro_handle h) {
    std::coroutine_handle<>::from_address(h).resume();
}

bool reactor_has_registrations() {
    return !g_read_regs.empty() || !g_write_regs.empty();
}

/* Move every timer whose deadline has already passed onto the ready queue.
 * Called right after mojo_async_now_ns() advances (either because we just
 * woke from a kevent() wait, or because the ready-queue drain loop above
 * took long enough that a timer became due without any wait at all). */
void drain_due_timers() {
    uint64_t now = mojo_async_now_ns();
    while (!g_timers.empty() && g_timers.top().wake_time_ns <= now) {
        g_ready.push_back(g_timers.top().handle);
        g_timers.pop();
    }
}

} // namespace

extern "C" {

void mojo_async_init(void) {
    g_ready.clear();
    while (!g_timers.empty()) {
        g_timers.pop();
    }
    g_read_regs.clear();
    g_write_regs.clear();
    if (g_kq >= 0) {
        close(g_kq);
        g_kq = -1;
    }
}

void mojo_async_shutdown(void) {
    mojo_async_init();
}

uint64_t mojo_async_now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

void mojo_async_schedule_ready(mojo_coro_handle h) {
    g_ready.push_back(h);
}

void mojo_async_schedule_timer(mojo_coro_handle h, uint64_t wake_time_ns) {
    g_timers.push(TimerEntry{wake_time_ns, h});
}

void mojo_async_register_read(int fd, mojo_coro_handle h) {
    ensure_kqueue();
    struct kevent kev;
    EV_SET(&kev, fd, EVFILT_READ, EV_ADD | EV_ONESHOT, 0, 0, NULL);
    kevent(g_kq, &kev, 1, NULL, 0, NULL);
    g_read_regs[fd] = ReactorReg{h};
}

void mojo_async_register_write(int fd, mojo_coro_handle h) {
    ensure_kqueue();
    struct kevent kev;
    EV_SET(&kev, fd, EVFILT_WRITE, EV_ADD | EV_ONESHOT, 0, 0, NULL);
    kevent(g_kq, &kev, 1, NULL, 0, NULL);
    g_write_regs[fd] = ReactorReg{h};
}

void mojo_async_cancel(int fd) {
    if (g_kq >= 0) {
        struct kevent kevs[2];
        int n = 0;
        if (g_read_regs.count(fd)) {
            EV_SET(&kevs[n++], fd, EVFILT_READ, EV_DELETE, 0, 0, NULL);
        }
        if (g_write_regs.count(fd)) {
            EV_SET(&kevs[n++], fd, EVFILT_WRITE, EV_DELETE, 0, 0, NULL);
        }
        if (n > 0) {
            kevent(g_kq, kevs, n, NULL, 0, NULL);
        }
    }
    g_read_regs.erase(fd);
    g_write_regs.erase(fd);
}

void mojo_async_run_until_complete(void) {
    for (;;) {
        /* Drain the ready queue fully first — resuming a handle may itself
         * call mojo_async_schedule_ready/_timer/_register_* synchronously,
         * so re-check emptiness on every iteration rather than snapshotting
         * a size up front. */
        while (!g_ready.empty()) {
            mojo_coro_handle h = g_ready.front();
            g_ready.erase(g_ready.begin());
            resume_handle(h);
        }

        if (g_timers.empty() && !reactor_has_registrations()) {
            break; /* genuinely nothing left to do */
        }

        /* Fold the next timer deadline into the kevent() wait timeout — the
         * standard reactor pattern: block until whichever comes first, a
         * registered fd becoming ready or the next timer firing. If there
         * are no timers at all, wait indefinitely (NULL timeout) until a
         * reactor event arrives. */
        struct timespec ts_timeout;
        struct timespec *timeoutp = nullptr;
        if (!g_timers.empty()) {
            uint64_t now = mojo_async_now_ns();
            uint64_t wake = g_timers.top().wake_time_ns;
            uint64_t delta = (wake > now) ? (wake - now) : 0;
            ts_timeout.tv_sec = (time_t)(delta / 1000000000ull);
            ts_timeout.tv_nsec = (long)(delta % 1000000000ull);
            timeoutp = &ts_timeout;
        }

        /* Even a purely timer-driven wait (no fds registered at all) goes
         * through kevent() on a lazily-created, empty kqueue: it behaves
         * exactly like a plain timed sleep in that case (0 events, returns
         * once the timeout elapses), which keeps exactly one wait code path
         * for both "just sleeping" and "waiting on a reactor event too". */
        ensure_kqueue();
        struct kevent events[16];
        int n = kevent(g_kq, NULL, 0, events, 16, timeoutp);
        for (int i = 0; i < n; i++) {
            int fd = (int)events[i].ident;
            if (events[i].filter == EVFILT_READ) {
                auto it = g_read_regs.find(fd);
                if (it != g_read_regs.end()) {
                    g_ready.push_back(it->second.handle);
                    g_read_regs.erase(it);
                }
            } else if (events[i].filter == EVFILT_WRITE) {
                auto it = g_write_regs.find(fd);
                if (it != g_write_regs.end()) {
                    g_ready.push_back(it->second.handle);
                    g_write_regs.erase(it);
                }
            }
        }

        drain_due_timers();
    }
}

/* --- Generic (promise-type-erased) resume/destroy — see the doc comment
 * on these two in mojo_async_runtime.h. */

void mojo_coro_resume_generic(int64_t handle) {
    if (handle == 0) return;
    std::coroutine_handle<>::from_address(
        reinterpret_cast<void *>(handle)).resume();
}

void mojo_coro_destroy_generic(int64_t handle) {
    if (handle == 0) return;
    std::coroutine_handle<>::from_address(
        reinterpret_cast<void *>(handle)).destroy();
}

/* --- AsyncRT_DeviceContext_enqueueHostFunction(Range) — deliberate
 * synchronous stub, see the doc comment on these two in
 * mojo_async_runtime.h and bugs/CODEGEN_device_context_host_function_
 * enqueue_synchronous_stub.md. */

const char *AsyncRT_DeviceContext_enqueueHostFunction(
        int64_t /*device_ctx_handle*/,
        void (*resume_fn)(int64_t),
        void (*destroy_fn)(int64_t),
        int64_t coro_handle) {
    resume_fn(coro_handle);
    destroy_fn(coro_handle);
    return nullptr;
}

const char *AsyncRT_DeviceContext_enqueueHostFunctionRange(
        int64_t /*device_ctx_handle*/,
        void (*resume_fn)(int64_t),
        void (*destroy_fn)(int64_t),
        const int64_t *coro_handles,
        int64_t count) {
    for (int64_t i = 0; i < count; ++i) {
        resume_fn(coro_handles[i]);
        destroy_fn(coro_handles[i]);
    }
    return nullptr;
}

} /* extern "C" */
