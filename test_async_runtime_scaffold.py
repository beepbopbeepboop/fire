#!/usr/bin/env python3
"""Toolchain/runtime proof for Step A of the compiled-path async/await
codegen project (see runtime/fire_async_runtime.h/.cpp for the design
rationale). Mirrors test_mixed_cpp_link.py's structure exactly: this
compiles+links+runs through the REAL project build system
(build_config.find_gxx() + mojo.link_executable(cxx=True)), not a bypassed
scratch script.

Nothing here touches gimple_codegen.py or any Mojo-level codegen — this
proves the scheduler/timer-queue/kqueue-reactor scaffold in
mojo_async_runtime.cpp works correctly, exercised only by a hand-written
C++20 coroutine test program (HAND_WRITTEN_MAIN_CPP below), never anything
the Mojo compiler emits.

Two things are verified with real wall-clock timing, not just "did it
print the right value":

  1. A coroutine that does `co_await mojo_sleep_for(50ms)` genuinely
     suspends and is resumed roughly 50ms later (not immediately) — proven
     by the hand-written program's own std::chrono measurement, printed as
     a `TIMER_DT_MS=<n>` line this test parses and asserts on
     (`>= 45` — an ~5ms scheduling-slack floor below the 50ms target,
     mirroring test_async_execution.py's `dt >= 0.06` style assertion for a
     50ms sleep).
  2. The kqueue reactor scaffold: one coroutine awaits readability of one
     end of a socketpair; a second coroutine sleeps 50ms then writes to the
     other end. The reader coroutine must NOT resume until the write
     actually happens — proven the same way, via a `REACTOR_DT_MS=<n>`
     line asserted `>= 45` — plus a correctness check that the byte
     actually received is the one the writer sent.
"""
import os
import sys
import subprocess
import tempfile
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_config import find_gxx
import fire

GXX = find_gxx()
RUNTIME_DIR = os.path.join(HERE, 'runtime')
ASYNC_RUNTIME_CPP = os.path.join(RUNTIME_DIR, 'mojo_async_runtime.cpp')

_PASS = 0
_FAIL = 0


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


HAND_WRITTEN_MAIN_CPP = r"""
// Hand-written (NOT Mojo-compiled) C++20 coroutine test exercising
// mojo_async_runtime's scheduler for real. See fire_async_runtime.h for the
// extern "C" API this drives.
#include "fire_async_runtime.h"

#include <coroutine>
#include <cstdio>
#include <cstring>
#include <chrono>

#include <sys/socket.h>
#include <unistd.h>

// Minimal fire-and-forget coroutine return type: initial_suspend is
// suspend_never so the body runs eagerly up to its first real co_await;
// final_suspend is suspend_never so the frame self-destroys on completion
// (this test never touches the coroutine_handle after the Task is
// returned, which is exactly what makes that safe).
struct Task {
    struct promise_type {
        Task get_return_object() { return {}; }
        std::suspend_never initial_suspend() { return {}; }
        std::suspend_never final_suspend() noexcept { return {}; }
        void return_void() {}
        void unhandled_exception() { std::terminate(); }
    };
};

struct SleepAwaiter {
    uint64_t delay_ns;
    bool await_ready() const { return false; }
    void await_suspend(std::coroutine_handle<> h) const {
        mojo_async_schedule_timer(h.address(), mojo_async_now_ns() + delay_ns);
    }
    void await_resume() const {}
};

static SleepAwaiter mojo_sleep_for_ms(uint64_t ms) {
    return SleepAwaiter{ms * 1000000ull};
}

struct ReadAwaiter {
    int fd;
    bool await_ready() const { return false; }
    void await_suspend(std::coroutine_handle<> h) const {
        mojo_async_register_read(fd, h.address());
    }
    void await_resume() const {}
};

// --- Test 1: timer suspend/resume ---
static uint64_t g_timer_start_ns = 0;
static uint64_t g_timer_resumed_ns = 0;
static bool g_timer_done = false;

static Task sleeper_coro() {
    g_timer_start_ns = mojo_async_now_ns();
    co_await mojo_sleep_for_ms(50);
    g_timer_resumed_ns = mojo_async_now_ns();
    g_timer_done = true;
}

// --- Test 2: kqueue reactor (socketpair) ---
static uint64_t g_reactor_start_ns = 0;
static uint64_t g_reactor_resumed_ns = 0;
static bool g_reactor_done = false;
static char g_reactor_byte = 0;

static Task reactor_reader_coro(int read_fd) {
    g_reactor_start_ns = mojo_async_now_ns();
    co_await ReadAwaiter{read_fd};
    char buf[1] = {0};
    ssize_t n = read(read_fd, buf, 1);
    g_reactor_byte = (n == 1) ? buf[0] : 0;
    g_reactor_resumed_ns = mojo_async_now_ns();
    g_reactor_done = true;
}

static Task delayed_writer_coro(int write_fd, uint64_t delay_ms, char byte_to_write) {
    co_await mojo_sleep_for_ms(delay_ms);
    write(write_fd, &byte_to_write, 1);
}

int main() {
    int failures = 0;

    // --- Test 1 ---
    mojo_async_init();
    sleeper_coro();
    mojo_async_run_until_complete();

    double timer_dt_ms = (double)(g_timer_resumed_ns - g_timer_start_ns) / 1e6;
    printf("TIMER_DONE=%d\n", g_timer_done ? 1 : 0);
    printf("TIMER_DT_MS=%.3f\n", timer_dt_ms);
    if (!g_timer_done) failures++;

    // --- Test 2 ---
    mojo_async_init();
    int fds[2];
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, fds) != 0) {
        printf("SOCKETPAIR_FAILED=1\n");
        return 1;
    }
    reactor_reader_coro(fds[0]);
    delayed_writer_coro(fds[1], 50, 'X');
    mojo_async_run_until_complete();

    double reactor_dt_ms = (double)(g_reactor_resumed_ns - g_reactor_start_ns) / 1e6;
    printf("REACTOR_DONE=%d\n", g_reactor_done ? 1 : 0);
    printf("REACTOR_BYTE=%d\n", (int)g_reactor_byte);
    printf("REACTOR_DT_MS=%.3f\n", reactor_dt_ms);
    if (!g_reactor_done) failures++;
    if (g_reactor_byte != 'X') failures++;

    close(fds[0]);
    close(fds[1]);

    mojo_async_shutdown();

    return failures == 0 ? 0 : 1;
}
"""


def _parse_kv(stdout):
    kv = {}
    for line in stdout.splitlines():
        if '=' in line:
            k, _, v = line.partition('=')
            kv[k.strip()] = v.strip()
    return kv


def test_compile_link_run(wd):
    main_cpp = os.path.join(wd, 'async_scaffold_main.cpp')
    with open(main_cpp, 'w') as f:
        f.write(HAND_WRITTEN_MAIN_CPP)

    runtime_o = os.path.join(wd, 'mojo_async_runtime.o')
    main_o = os.path.join(wd, 'async_scaffold_main.o')

    r = subprocess.run(
        [GXX, '-std=c++20', '-I', RUNTIME_DIR, '-c', '-o', runtime_o, ASYNC_RUNTIME_CPP],
        capture_output=True, text=True)
    check("g++ compiles mojo_async_runtime.cpp -> .o", r.returncode == 0, detail=r.stderr)

    r = subprocess.run(
        [GXX, '-std=c++20', '-I', RUNTIME_DIR, '-c', '-o', main_o, main_cpp],
        capture_output=True, text=True)
    check("g++ compiles hand-written coroutine test -> .o", r.returncode == 0, detail=r.stderr)

    if not (os.path.exists(runtime_o) and os.path.exists(main_o)):
        return

    exe_file = os.path.join(wd, 'async_scaffold_exe')
    # Real project link path: mojo.link_executable(cxx=True) — the exact
    # function build_executable() itself will call once Step B needs this
    # runtime linked in, per Milestone A's precedent (test_mixed_cpp_link.py).
    result = mojo.link_executable([main_o, runtime_o], exe_file, cxx=True)
    check("link_executable(cxx=True) links the scaffold test", result.returncode == 0,
          detail=result.stderr)

    if not os.path.exists(exe_file):
        return
    os.chmod(exe_file, 0o755)

    run = subprocess.run([exe_file], capture_output=True, text=True, timeout=10)
    check("scaffold executable runs and exits 0", run.returncode == 0,
          detail=f"returncode={run.returncode} stdout={run.stdout!r} stderr={run.stderr!r}")

    kv = _parse_kv(run.stdout)

    # --- Timer suspend/resume assertions ---
    check("timer coroutine completed", kv.get('TIMER_DONE') == '1', detail=run.stdout)
    timer_dt = float(kv['TIMER_DT_MS']) if 'TIMER_DT_MS' in kv else -1.0
    # Genuinely suspended-and-resumed proof: real elapsed time must be close
    # to the requested 50ms, not ~0 (which would mean await_suspend never
    # actually yielded control / the "sleep" was faked as a no-op).
    check("timer resumed ~50ms later, not immediately (>= 45ms)",
          timer_dt >= 45.0, detail=f"TIMER_DT_MS={timer_dt}")
    check("timer resumed without a huge unexplained stall (< 1000ms)",
          0 <= timer_dt < 1000.0, detail=f"TIMER_DT_MS={timer_dt}")

    # --- kqueue reactor assertions ---
    check("reactor coroutine completed", kv.get('REACTOR_DONE') == '1', detail=run.stdout)
    check("reactor received the exact byte the writer sent ('X' == 88)",
          kv.get('REACTOR_BYTE') == '88', detail=run.stdout)
    reactor_dt = float(kv['REACTOR_DT_MS']) if 'REACTOR_DT_MS' in kv else -1.0
    # Genuinely-detected-readiness proof: the reader coroutine must not have
    # resumed until ~50ms in (when the writer actually wrote), not
    # immediately (which would mean the reactor faked readiness / resumed
    # on registration instead of on an actual kevent() report) and not
    # never (which would have made this test time out instead of exiting).
    check("reactor resumed only once data was actually written (>= 45ms)",
          reactor_dt >= 45.0, detail=f"REACTOR_DT_MS={reactor_dt}")
    check("reactor resumed without a huge unexplained stall (< 1000ms)",
          0 <= reactor_dt < 1000.0, detail=f"REACTOR_DT_MS={reactor_dt}")


def main():
    wd = tempfile.mkdtemp(prefix='mojo_async_runtime_scaffold_')
    try:
        test_compile_link_run(wd)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    print()
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    return _FAIL == 0


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
