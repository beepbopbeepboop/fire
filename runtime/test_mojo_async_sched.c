/* test_mojo_async_sched.c -- Layer 2 async: the plain-C scheduler
   (mojo_async_sched.c) driving hand-written coroutine bodies that stand
   in for what gimple_gen_coro.py's `async def`/`await` lowering emits. */
#include "mojo_coro.h"
#include "mojo_wd.h"
#include <stdio.h>
#include <stdint.h>
#include <time.h>

extern void __mojo_async_run(MojoCoro *c);
extern uint64_t __mojo_async_now_ns(void);

static int failures = 0;
#define CHECK(c, ...) do { if (!(c)) { failures++; \
    printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* leaf: await asyncio.sleep(50ms); return 42 */
static void body_leaf(MojoCoro *c, void *env)
{
    (void)env;
    uint64_t wake = __mojo_async_now_ns() + 50ull * 1000000ull;
    __mojo_coro_yield(c, mojo_wd_make(MOJO_WD_SLEEP, (int64_t)wake));
    __mojo_coro_set_return(c, 42);
}

/* outer: v = await leaf(); return v * 2   -- forwards leaf's wait
   descriptor upward exactly like yield-from forwards a generator's
   yields (the mechanism gimple_gen_coro.py's await-on-async-call
   desugar reuses). */
static MojoCoro *g_leaf;   /* constructed fresh per test */

static void body_outer(MojoCoro *c, void *env)
{
    (void)env;
    for (;;) {
        int64_t out = 0;
        int more = __mojo_coro_resume(g_leaf, 0, &out);
        if (!more) break;
        __mojo_coro_yield(c, out);      /* forward the wait descriptor */
    }
    int64_t v = __mojo_coro_return_value(g_leaf);
    __mojo_coro_destroy(g_leaf);
    __mojo_coro_set_return(c, v * 2);
}

static void test_sleep_then_return(void)
{
    g_leaf = __mojo_coro_new(body_leaf, NULL, 0);
    MojoCoro *outer = __mojo_coro_new(body_outer, NULL, 0);

    uint64_t t0 = __mojo_async_now_ns();
    __mojo_async_run(outer);
    uint64_t elapsed_ms = (__mojo_async_now_ns() - t0) / 1000000ull;

    CHECK(elapsed_ms >= 45, "real suspension didn't happen: elapsed=%llums (want >=45)",
          (unsigned long long)elapsed_ms);
    int64_t rv = __mojo_coro_return_value(outer);
    CHECK(rv == 84, "outer return value = %lld want 84", (long long)rv);
    __mojo_coro_destroy(outer);
}

/* two independent sleepers scheduled together must run CONCURRENTLY, not
   sequentially -- proves the scheduler, not just one coroutine's suspend. */
static int g_done_order[2];
static int g_done_n;

static void body_sleeper(MojoCoro *c, void *env)
{
    int id = (int)(intptr_t)env;
    int64_t ms = (id == 0) ? 60 : 20;
    uint64_t wake = __mojo_async_now_ns() + (uint64_t)ms * 1000000ull;
    __mojo_coro_yield(c, mojo_wd_make(MOJO_WD_SLEEP, (int64_t)wake));
    g_done_order[g_done_n++] = id;
    __mojo_coro_set_return(c, id);
}

extern void __mojo_async_schedule_ready(MojoCoro *c);
extern void __mojo_async_run_until_complete(void);

static void test_concurrent_sleepers(void)
{
    g_done_n = 0;
    MojoCoro *a = __mojo_coro_new(body_sleeper, (void *)(intptr_t)0, 0);
    MojoCoro *b = __mojo_coro_new(body_sleeper, (void *)(intptr_t)1, 0);
    uint64_t t0 = __mojo_async_now_ns();
    __mojo_async_schedule_ready(a);
    __mojo_async_schedule_ready(b);
    __mojo_async_run_until_complete();
    uint64_t elapsed_ms = (__mojo_async_now_ns() - t0) / 1000000ull;
    /* if sequential this would be ~80ms; concurrent should be ~60ms */
    CHECK(elapsed_ms < 75, "sleepers ran sequentially, not concurrently: %llums",
          (unsigned long long)elapsed_ms);
    CHECK(g_done_n == 2 && g_done_order[0] == 1 && g_done_order[1] == 0,
          "wrong completion order: n=%d [%d,%d]", g_done_n, g_done_order[0], g_done_order[1]);
    __mojo_coro_destroy(a);
    __mojo_coro_destroy(b);
}

int main(void)
{
    test_sleep_then_return();
    test_concurrent_sleepers();
    if (failures) { printf("%d failure(s)\n", failures); return 1; }
    printf("all async scheduler tests passed\n");
    return 0;
}
