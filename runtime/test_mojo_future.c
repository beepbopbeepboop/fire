/* test_mojo_future.c -- Layer 2 async: the Awaitable protocol (Future /
   Event handles with a waiter list + cross-coroutine wakeup), driving
   hand-written coroutine bodies that stand in for what gimple_gen_coro.py's
   `await <future>` / `await <event>.wait()` lowering emits. */
#include "mojo_coro.h"
#include "mojo_wd.h"
#include <stdio.h>
#include <stdint.h>

extern void     __mojo_async_schedule_ready(MojoCoro *c);
extern void     __mojo_async_run_until_complete(void);
extern uint64_t __mojo_async_now_ns(void);

extern int64_t __mojo_future_new(void);
extern int64_t __mojo_future_done(int64_t h);
extern int64_t __mojo_future_result(int64_t h);
extern void    __mojo_future_set_result(int64_t h, int64_t val);
extern int64_t __mojo_async_await_future(int64_t coro, int64_t h);
extern int64_t __mojo_event_new(void);
extern void    __mojo_event_set(int64_t h);
extern int64_t __mojo_event_is_set(int64_t h);
extern int64_t __mojo_async_await_event_wait(int64_t coro, int64_t h);

static int failures = 0;
#define CHECK(c, ...) do { if (!(c)) { failures++; \
    printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* ── test 1: consumer awaits a future; producer sets it later ─────────── */
static int64_t g_fut;
static int64_t g_consumer_got;

static void body_consumer(MojoCoro *c, void *env)
{
    (void)env;
    int64_t v = __mojo_async_await_future((int64_t)(uintptr_t)c, g_fut);
    g_consumer_got = v;
    __mojo_coro_set_return(c, v);
}

static void body_producer(MojoCoro *c, void *env)
{
    (void)env;
    /* suspend once so the consumer parks first */
    uint64_t wake = __mojo_async_now_ns();
    __mojo_coro_yield(c, mojo_wd_make(MOJO_WD_SLEEP, (int64_t)wake));
    __mojo_future_set_result(g_fut, 99);
    __mojo_coro_set_return(c, 0);
}

static void test_future_cross_coroutine(void)
{
    g_consumer_got = -1;
    g_fut = __mojo_future_new();
    MojoCoro *cons = __mojo_coro_new(body_consumer, NULL, 0);
    MojoCoro *prod = __mojo_coro_new(body_producer, NULL, 0);
    __mojo_async_schedule_ready(cons);
    __mojo_async_schedule_ready(prod);
    __mojo_async_run_until_complete();
    CHECK(g_consumer_got == 99, "consumer got %lld want 99", (long long)g_consumer_got);
    CHECK(__mojo_coro_return_value(cons) == 99, "consumer retval wrong");
    CHECK(__mojo_future_done(g_fut), "future not marked done");
    __mojo_coro_destroy(cons);
    __mojo_coro_destroy(prod);
}

/* ── test 2: await an ALREADY-resolved future returns immediately ─────── */
static int64_t g_fut2;
static void body_already(MojoCoro *c, void *env)
{
    (void)env;
    int64_t v = __mojo_async_await_future((int64_t)(uintptr_t)c, g_fut2);
    __mojo_coro_set_return(c, v + 1);
}
static void test_future_already_done(void)
{
    g_fut2 = __mojo_future_new();
    __mojo_future_set_result(g_fut2, 41);
    MojoCoro *co = __mojo_coro_new(body_already, NULL, 0);
    __mojo_async_schedule_ready(co);
    __mojo_async_run_until_complete();
    CHECK(__mojo_coro_return_value(co) == 42, "got %lld want 42",
          (long long)__mojo_coro_return_value(co));
    __mojo_coro_destroy(co);
}

/* ── test 3: multiple waiters on one event, all woken by a single set ── */
static int64_t g_ev;
static int g_woken;
static void body_ev_waiter(MojoCoro *c, void *env)
{
    (void)env;
    __mojo_async_await_event_wait((int64_t)(uintptr_t)c, g_ev);
    g_woken++;
    __mojo_coro_set_return(c, 0);
}
static void body_ev_setter(MojoCoro *c, void *env)
{
    (void)env;
    uint64_t wake = __mojo_async_now_ns();
    __mojo_coro_yield(c, mojo_wd_make(MOJO_WD_SLEEP, (int64_t)wake));
    CHECK(!__mojo_event_is_set(g_ev), "event set too early");
    __mojo_event_set(g_ev);
    __mojo_coro_set_return(c, 0);
}
static void test_event_multi_waiter(void)
{
    g_woken = 0;
    g_ev = __mojo_event_new();
    MojoCoro *w1 = __mojo_coro_new(body_ev_waiter, NULL, 0);
    MojoCoro *w2 = __mojo_coro_new(body_ev_waiter, NULL, 0);
    MojoCoro *w3 = __mojo_coro_new(body_ev_waiter, NULL, 0);
    MojoCoro *s  = __mojo_coro_new(body_ev_setter, NULL, 0);
    __mojo_async_schedule_ready(w1);
    __mojo_async_schedule_ready(w2);
    __mojo_async_schedule_ready(w3);
    __mojo_async_schedule_ready(s);
    __mojo_async_run_until_complete();
    CHECK(g_woken == 3, "woken %d want 3", g_woken);
    CHECK(__mojo_event_is_set(g_ev), "event should latch set");
    __mojo_coro_destroy(w1); __mojo_coro_destroy(w2);
    __mojo_coro_destroy(w3); __mojo_coro_destroy(s);
}

int main(void)
{
    test_future_cross_coroutine();
    test_future_already_done();
    test_event_multi_waiter();
    if (failures) { printf("%d failure(s)\n", failures); return 1; }
    printf("all future/event tests passed\n");
    return 0;
}
