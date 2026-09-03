/* test_mojo_coro_gen.c -- the Mojo-facing int64_t shim (mojo_coro_gen.c),
   driven by hand-written "bodies" that stand in for gimple_gen_coro.py's
   output. Everything crosses the boundary as int64_t. */
#include "mojo_coro.h"
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>

extern int64_t __mojo_gen_new_0(int64_t body);
extern int64_t __mojo_gen_new_2(int64_t body, int64_t a0, int64_t a1);
extern int64_t __mojo_gen_arg(int64_t coro, int64_t idx);
extern int64_t __mojo_coro_yield_i(int64_t coro, int64_t v);
extern void    __mojo_gen_set_return(int64_t coro, int64_t v);
extern int64_t __mojo_gen_resume(int64_t gen, int64_t send);
extern int64_t __mojo_gen_value(int64_t gen);
extern int64_t __mojo_gen_retval(int64_t gen);
extern void    __mojo_gen_destroy(int64_t gen);

static int failures = 0;
#define CHECK(c, ...) do { if (!(c)) { failures++; \
    printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

/* fn range_gen(lo, hi):  for i in [lo, hi): yield i ; return hi-lo  */
static void body_range(int64_t c)
{
    int64_t lo = __mojo_gen_arg(c, 0);
    int64_t hi = __mojo_gen_arg(c, 1);
    for (int64_t i = lo; i < hi; i++)
        __mojo_coro_yield_i(c, i);
    __mojo_gen_set_return(c, hi - lo);
}

static void test_range(void)
{
    int64_t g = __mojo_gen_new_2((int64_t)(uintptr_t)body_range, 3, 7);
    int64_t want = 3;
    while (__mojo_gen_resume(g, 0)) {
        CHECK(__mojo_gen_value(g) == want, "value %lld want %lld",
              (long long)__mojo_gen_value(g), (long long)want);
        want++;
    }
    CHECK(want == 7, "iterations: stopped at %lld", (long long)want);
    CHECK(__mojo_gen_retval(g) == 4, "retval %lld", (long long)__mojo_gen_retval(g));
    __mojo_gen_destroy(g);
}

/* fn counter():  n=0; while True: n += (yield n)   -- send accumulation */
static void body_counter(int64_t c)
{
    int64_t n = 0;
    for (;;) n += __mojo_coro_yield_i(c, n);
}

static void test_send(void)
{
    int64_t g = __mojo_gen_new_0((int64_t)(uintptr_t)body_counter);
    CHECK(__mojo_gen_resume(g, 0) && __mojo_gen_value(g) == 0, "prime");
    CHECK(__mojo_gen_resume(g, 5) && __mojo_gen_value(g) == 5, "send 5");
    CHECK(__mojo_gen_resume(g, 10) && __mojo_gen_value(g) == 15, "send 10 -> 15");
    __mojo_gen_destroy(g);
}

int main(void)
{
    test_range();
    test_send();
    if (failures) { printf("%d failure(s)\n", failures); return 1; }
    printf("all Layer 1 shim (mojo_coro_gen) tests passed\n");
    return 0;
}
