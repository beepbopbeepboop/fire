/* test_mojo_coro_ctx.c -- standalone unit test for Layer 3 (SEAM B), the
   architecture context-switch primitive. Builds against either
   mojo_coro_ctx_generic.c (ucontext) or an arch .S; both must pass
   identically.

     cc -O2 -o /tmp/t runtime/test_mojo_coro_ctx.c runtime/mojo_coro_ctx_generic.c && /tmp/t
     cc -O2 -o /tmp/t runtime/test_mojo_coro_ctx.c runtime/mojo_coro_ctx_aarch64.S && /tmp/t
*/
#include "mojo_coro_ctx.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* the generic (ucontext) Layer 3 impl trips macOS deprecation warnings;
   they are expected and harmless -- silence them for a clean test build */
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"

static int failures = 0;
#define CHECK(cond, ...) do { \
    if (!(cond)) { failures++; printf("FAIL %s:%d: ", __FILE__, __LINE__); \
                   printf(__VA_ARGS__); printf("\n"); } } while (0)

/* ---- test 1: a context that yields 10, 20, 30 then finishes ------------- */

static void
t1_body(mojo_xfer_t in)
{
    /* First entry: in.from is the caller's context, in.data is the arg. */
    long start = (long)in.data;
    mojo_fctx_t back = in.from;

    for (int i = 1; i <= 3; i++) {
        mojo_xfer_t r = mojo_jump_fctx(back, (void *)(start + i * 10));
        back = r.from;                     /* caller may have moved stacks */
        /* r.data is the "send" value from the caller */
        CHECK((long)r.data == i * 100, "send mismatch: got %ld want %d", (long)r.data, i * 100);
    }
    /* final: signal done with a sentinel and never return */
    mojo_jump_fctx(back, (void *)-1);
    abort();
}

static void
test_yield_sequence(void)
{
    size_t sz = 64 * 1024;
    void  *stk = malloc(sz);
    mojo_fctx_t co = mojo_make_fctx((char *)stk + sz, sz, t1_body);

    /* prime with arg 5 */
    mojo_xfer_t r = mojo_jump_fctx(co, (void *)5);
    CHECK((long)r.data == 15, "yield 1: got %ld want 15", (long)r.data);

    r = mojo_jump_fctx(r.from, (void *)100);
    CHECK((long)r.data == 25, "yield 2: got %ld want 25", (long)r.data);

    r = mojo_jump_fctx(r.from, (void *)200);
    CHECK((long)r.data == 35, "yield 3: got %ld want 35", (long)r.data);

    r = mojo_jump_fctx(r.from, (void *)300);
    CHECK((long)r.data == -1, "done sentinel: got %ld want -1", (long)r.data);

    free(stk);
}

/* ---- test 2: callee-saved registers survive the switch ----------------- */

static void
t2_body(mojo_xfer_t in)
{
    mojo_fctx_t back = in.from;
    /* Force the compiler to keep values in callee-saved regs across the
       switch by using many longs in a loop that spans the jump. */
    volatile long a = 0x1111, b = 0x2222, c = 0x3333, d = 0x4444;
    volatile long e = 0x5555, f = 0x6666, g = 0x7777, h = 0x8888;
    mojo_xfer_t r = mojo_jump_fctx(back, (void *)0);
    long sum = a + b + c + d + e + f + g + h;
    long want = 0x1111+0x2222+0x3333+0x4444+0x5555+0x6666+0x7777+0x8888;
    CHECK(sum == want, "stack values clobbered across switch: sum=%lx want=%lx", sum, want);
    mojo_jump_fctx(r.from, (void *)sum);
    abort();
}

static void
test_callee_saved(void)
{
    size_t sz = 64 * 1024;
    void  *stk = malloc(sz);
    mojo_fctx_t co = mojo_make_fctx((char *)stk + sz, sz, t2_body);
    mojo_xfer_t r = mojo_jump_fctx(co, (void *)0);
    /* clobber our own callee-saved regs while the coroutine is parked */
    volatile long junk = 0;
    for (int i = 0; i < 1000; i++) junk += i * i;
    (void)junk;
    r = mojo_jump_fctx(r.from, (void *)0);
    CHECK((long)r.data == 0x26664, "sum came back wrong: %lx", (long)r.data);
    free(stk);
}

/* ---- test 3: mojo_ontop_fctx runs fn on the target stack -------------- */

static long t3_marker;

static mojo_xfer_t
t3_ontop(mojo_xfer_t in)
{
    t3_marker = 0xDEAD;
    return in;   /* pass the xfer straight through to the resuming context */
}

static void
t3_body(mojo_xfer_t in)
{
    mojo_fctx_t back = in.from;
    mojo_xfer_t r = mojo_jump_fctx(back, (void *)1);   /* suspend */
    /* resumed via ontop: t3_ontop must have run already */
    CHECK(t3_marker == 0xDEAD, "ontop fn did not run before resume");
    mojo_jump_fctx(r.from, (void *)2);
    abort();
}

static void
test_ontop(void)
{
    size_t sz = 64 * 1024;
    void  *stk = malloc(sz);
    mojo_fctx_t co = mojo_make_fctx((char *)stk + sz, sz, t3_body);
    mojo_xfer_t r = mojo_jump_fctx(co, (void *)0);
    CHECK((long)r.data == 1, "t3 first yield");
    t3_marker = 0;
    r = mojo_ontop_fctx(r.from, (void *)0, t3_ontop);
    CHECK((long)r.data == 2, "t3 second yield after ontop");
    free(stk);
}

int
main(void)
{
    test_yield_sequence();
    test_callee_saved();
    test_ontop();
    if (failures) { printf("%d failure(s)\n", failures); return 1; }
    printf("all Layer 3 context-switch tests passed\n");
    return 0;
}
