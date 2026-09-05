/* mojo_async_sched.c -- plain-C event loop for A3 stack-switch `async def`
   (doc/COROUTINE.html). A faithful port of the algorithms in
   runtime/mojo_async_runtime.cpp (ready queue, timer min-heap, kqueue
   reactor) with ONE change: resuming a handle calls __mojo_coro_resume
   (Layer 2), not the C++20 coroutine-handle ABI. Every stack-switch async
   coroutine is structurally the same MojoCoro, so unlike the C++ path
   there is no per-function resume/destroy function pointer to carry
   around -- one generic resume serves all of them.

   Wait-descriptor convention: an async coroutine that suspends yields one
   int64_t word via __mojo_coro_yield, packed by mojo_wd.h's WD_* macros:
   kind in the top byte, payload in the low 56 bits. A coroutine awaiting
   ANOTHER compiled async coroutine forwards its inner wait-descriptor
   upward unchanged (the same shape yield-from's for-loop already uses for
   generators) until it reaches this scheduler, which is the only thing
   that ever interprets the kind.
*/
#include "mojo_coro.h"
#include "mojo_wd.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/event.h>
#include <sys/time.h>

/* ── ready queue: a simple growable FIFO of MojoCoro* ─────────────────── */
static MojoCoro **g_ready;
static int g_ready_n, g_ready_cap, g_ready_head;

static void ready_push(MojoCoro *c)
{
    if (g_ready_head > 0 && g_ready_n == g_ready_cap) {
        memmove(g_ready, g_ready + g_ready_head, (g_ready_n - g_ready_head) * sizeof(*g_ready));
        g_ready_n -= g_ready_head; g_ready_head = 0;
    }
    if (g_ready_n == g_ready_cap) {
        g_ready_cap = g_ready_cap ? g_ready_cap * 2 : 16;
        g_ready = realloc(g_ready, g_ready_cap * sizeof(*g_ready));
    }
    g_ready[g_ready_n++] = c;
}

static MojoCoro *ready_pop(void)
{
    return (g_ready_head < g_ready_n) ? g_ready[g_ready_head++] : NULL;
}

static int ready_empty(void) { return g_ready_head >= g_ready_n; }

/* ── timer min-heap, keyed by wake_time_ns ─────────────────────────────── */
typedef struct { uint64_t wake_ns; MojoCoro *c; } TimerEnt;
static TimerEnt *g_timers;
static int g_timers_n, g_timers_cap;

static void timer_push(uint64_t wake_ns, MojoCoro *c)
{
    if (g_timers_n == g_timers_cap) {
        g_timers_cap = g_timers_cap ? g_timers_cap * 2 : 16;
        g_timers = realloc(g_timers, g_timers_cap * sizeof(*g_timers));
    }
    int i = g_timers_n++;
    g_timers[i] = (TimerEnt){wake_ns, c};
    while (i > 0) {
        int p = (i - 1) / 2;
        if (g_timers[p].wake_ns <= g_timers[i].wake_ns) break;
        TimerEnt t = g_timers[p]; g_timers[p] = g_timers[i]; g_timers[i] = t;
        i = p;
    }
}

static TimerEnt timer_pop(void)
{
    TimerEnt top = g_timers[0];
    g_timers[0] = g_timers[--g_timers_n];
    int i = 0;
    for (;;) {
        int l = 2 * i + 1, r = 2 * i + 2, sm = i;
        if (l < g_timers_n && g_timers[l].wake_ns < g_timers[sm].wake_ns) sm = l;
        if (r < g_timers_n && g_timers[r].wake_ns < g_timers[sm].wake_ns) sm = r;
        if (sm == i) break;
        TimerEnt t = g_timers[sm]; g_timers[sm] = g_timers[i]; g_timers[i] = t;
        i = sm;
    }
    return top;
}

/* ── kqueue reactor: fd -> waiting MojoCoro*, small linear tables ─────── */
#define MAX_REGS 256
typedef struct { int fd; MojoCoro *c; } Reg;
static Reg g_reads[MAX_REGS], g_writes[MAX_REGS];
static int g_nreads, g_nwrites;
static int g_kq = -1;

static int ensure_kq(void) { if (g_kq < 0) g_kq = kqueue(); return g_kq; }
static int regs_pending(void) { return g_nreads > 0 || g_nwrites > 0; }

static void reg_add(Reg *tab, int *n, int fd, MojoCoro *c)
{
    if (*n < MAX_REGS) tab[(*n)++] = (Reg){fd, c};
}
static int reg_take(Reg *tab, int *n, int fd, MojoCoro **out)
{
    for (int i = 0; i < *n; i++) {
        if (tab[i].fd == fd) {
            *out = tab[i].c;
            tab[i] = tab[--(*n)];
            return 1;
        }
    }
    return 0;
}

/* ── SEAM A ─────────────────────────────────────────────────────────── */

void __mojo_async_init(void)
{
    g_ready_n = g_ready_head = 0;
    g_timers_n = 0;
    g_nreads = g_nwrites = 0;
    if (g_kq >= 0) { close(g_kq); g_kq = -1; }
}

uint64_t __mojo_async_now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

void __mojo_async_schedule_ready(MojoCoro *c) { ready_push(c); }
void __mojo_async_schedule_timer(MojoCoro *c, uint64_t wake_ns) { timer_push(wake_ns, c); }
void __mojo_async_register_read(int fd, MojoCoro *c) { ensure_kq();
    struct kevent kev; EV_SET(&kev, fd, EVFILT_READ, EV_ADD | EV_ONESHOT, 0, 0, NULL);
    kevent(g_kq, &kev, 1, NULL, 0, NULL); reg_add(g_reads, &g_nreads, fd, c); }
void __mojo_async_register_write(int fd, MojoCoro *c) { ensure_kq();
    struct kevent kev; EV_SET(&kev, fd, EVFILT_WRITE, EV_ADD | EV_ONESHOT, 0, 0, NULL);
    kevent(g_kq, &kev, 1, NULL, 0, NULL); reg_add(g_writes, &g_nwrites, fd, c); }

static void drain_due_timers(void)
{
    uint64_t now = __mojo_async_now_ns();
    while (g_timers_n > 0 && g_timers[0].wake_ns <= now) {
        TimerEnt t = timer_pop();
        ready_push(t.c);
    }
}

/* Resume `c` once; if it suspended with a wait descriptor, re-arm the
   right primitive; if it finished, it is the caller's responsibility to
   have already recorded whatever it needed from its return value (the
   scheduler itself doesn't own completion callbacks -- see
   gimple_gen_coro.py's asyncio.run bridge, which polls __mojo_coro-level
   status itself rather than through this loop for the OUTERMOST task). */
static void drive_once(MojoCoro *c)
{
    int64_t out = 0;
    int more = __mojo_coro_resume(c, 0, &out);
    if (!more) return;             /* done -- caller already holds the handle */
    int64_t kind = MOJO_WD_KIND(out);
    int64_t payload = MOJO_WD_PAYLOAD(out);
    if (kind == MOJO_WD_SLEEP) {
        __mojo_async_schedule_timer(c, (uint64_t)payload);
    } else if (kind == MOJO_WD_READ) {
        __mojo_async_register_read((int)payload, c);
    } else if (kind == MOJO_WD_WRITE) {
        __mojo_async_register_write((int)payload, c);
    } else {
        /* MOJO_WD_READY or unknown -- just reschedule immediately rather
           than drop the task. */
        ready_push(c);
    }
}

void __mojo_async_run_until_complete(void)
{
    for (;;) {
        while (!ready_empty()) drive_once(ready_pop());

        if (g_timers_n == 0 && !regs_pending()) break;

        struct timespec ts, *tsp = NULL;
        if (g_timers_n > 0) {
            uint64_t now = __mojo_async_now_ns();
            uint64_t wake = g_timers[0].wake_ns;
            uint64_t delta = wake > now ? wake - now : 0;
            ts.tv_sec = (time_t)(delta / 1000000000ull);
            ts.tv_nsec = (long)(delta % 1000000000ull);
            tsp = &ts;
        }
        ensure_kq();
        struct kevent events[16];
        int n = kevent(g_kq, NULL, 0, events, 16, tsp);
        for (int i = 0; i < n; i++) {
            int fd = (int)events[i].ident;
            MojoCoro *c;
            if (events[i].filter == EVFILT_READ && reg_take(g_reads, &g_nreads, fd, &c))
                ready_push(c);
            else if (events[i].filter == EVFILT_WRITE && reg_take(g_writes, &g_nwrites, fd, &c))
                ready_push(c);
        }
        drain_due_timers();
    }
}

/* Drive one coroutine (already started, e.g. via __mojo_gen_new_0-style
   construction wrapped as a MojoCoro) to completion synchronously --
   asyncio.run(f())'s bridge: schedule it ready, run the loop, then read
   its return value off the caller's own handle. */
void __mojo_async_run(MojoCoro *c)
{
    __mojo_async_schedule_ready(c);
    __mojo_async_run_until_complete();
}
