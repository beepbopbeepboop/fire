/* test_mojo_coro.c -- Layer 2 unit test: the __mojo_coro_* primitives
   (SEAM A) driven by hand-written C "bodies" that stand in for what
   gimple_gen_coro.py will emit.

     cc -O2 -I runtime -o /tmp/t runtime/test_mojo_coro.c runtime/mojo_coro.c \
        runtime/mojo_coro_ctx_aarch64.S runtime/test_mojo_coro_exc_stub.c && /tmp/t
*/
#include "fire_coro.h"
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#define MOJO_EXC_STACK_MAX 64
extern jmp_buf _mojo_exc_stack[MOJO_EXC_STACK_MAX];
extern int     _mojo_exc_top;
extern void    mojo_raise(void);
extern void    mojo_exc_type_set(int64_t);
extern int64_t mojo_exc_type_get(void);
extern void    mojo_exc_msg_set(char *);
extern char   *mojo_exc_msg_get(void);

static int failures = 0;
#define CHECK(c, ...) do { if (!(c)) { failures++; \
    printf("FAIL %s:%d: ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while (0)

#define MOJO_TAG_GENERATOREXIT  2146172193
#define MOJO_TAG_STOPITERATION   590612416
#define MOJO_TAG_VALUEERROR      (1 /* whatever; test only checks round-trip */)

/* ── body 1: yield 10, 20, 30 ; return 99 ─────────────────────────────── */
static void body_count(MojoCoro *c, void *env)
{
    (void)env;
    __mojo_coro_yield(c, 10);
    __mojo_coro_yield(c, 20);
    __mojo_coro_yield(c, 30);
    __mojo_coro_set_return(c, 99);
}

static void test_basic_sequence(void)
{
    MojoCoro *c = __mojo_coro_new(body_count, NULL, 0);
    int64_t v = 0;
    CHECK(__mojo_coro_resume(c, 0, &v) == 1 && v == 10, "y1 v=%lld", (long long)v);
    CHECK(__mojo_coro_resume(c, 0, &v) == 1 && v == 20, "y2 v=%lld", (long long)v);
    CHECK(__mojo_coro_resume(c, 0, &v) == 1 && v == 30, "y3 v=%lld", (long long)v);
    CHECK(__mojo_coro_resume(c, 0, &v) == 0 && v == 99, "ret v=%lld", (long long)v);
    /* resuming an exhausted coroutine keeps returning done+retval */
    CHECK(__mojo_coro_resume(c, 0, &v) == 0 && v == 99, "post-done v=%lld", (long long)v);
    __mojo_coro_destroy(c);
}

/* ── body 2: echo the sent value, doubled, forever ───────────────────── */
static void body_echo(MojoCoro *c, void *env)
{
    (void)env;
    int64_t got = __mojo_coro_yield(c, 0);       /* first yield: priming */
    for (;;) got = __mojo_coro_yield(c, got * 2);
}

static void test_send(void)
{
    MojoCoro *c = __mojo_coro_new(body_echo, NULL, 0);
    int64_t v = -1;
    CHECK(__mojo_coro_resume(c, 0, &v) == 1 && v == 0, "prime v=%lld", (long long)v);
    CHECK(__mojo_coro_resume(c, 7, &v) == 1 && v == 14, "send 7 -> %lld", (long long)v);
    CHECK(__mojo_coro_resume(c, 100, &v) == 1 && v == 200, "send 100 -> %lld", (long long)v);
    __mojo_coro_destroy(c);
}

/* ── body 3: try/finally around a yield -- finally must run on exhaustion ─ */
static int finally_ran;
static void body_finally(MojoCoro *c, void *env)
{
    (void)env;
    int sj_top = ++_mojo_exc_top;
    if (setjmp(_mojo_exc_stack[sj_top]) == 0) {
        __mojo_coro_yield(c, 1);
        --_mojo_exc_top;           /* leave the protected region normally */
        finally_ran = 1;           /* "finally" */
    } else {
        finally_ran = 1;           /* "finally" on the exception path */
        mojo_raise();              /* re-raise after cleanup */
    }
    __mojo_coro_set_return(c, 0);
}

static void test_finally_on_exhaust(void)
{
    finally_ran = 0;
    MojoCoro *c = __mojo_coro_new(body_finally, NULL, 0);
    int64_t v = 0;
    CHECK(__mojo_coro_resume(c, 0, &v) == 1 && v == 1, "y v=%lld", (long long)v);
    CHECK(__mojo_coro_resume(c, 0, &v) == 0, "done");
    CHECK(finally_ran == 1, "finally did not run on exhaustion");
    __mojo_coro_destroy(c);
}

/* ── body 4: raises an uncaught exception mid-run ────────────────────── */
static void body_raises(MojoCoro *c, void *env)
{
    (void)env;
    __mojo_coro_yield(c, 42);
    mojo_exc_type_set(1234);
    mojo_exc_msg_set((char *)"boom");
    mojo_raise();                  /* uncaught -> trampoline landing pad */
    __mojo_coro_set_return(c, 0);  /* unreachable */
}

static int caught_type; static char *caught_msg;
static void test_escaped_exception(void)
{
    MojoCoro *c = __mojo_coro_new(body_raises, NULL, 0);
    int64_t v = 0;
    CHECK(__mojo_coro_resume(c, 0, &v) == 1 && v == 42, "y v=%lld", (long long)v);

    int top = ++_mojo_exc_top;
    if (setjmp(_mojo_exc_stack[top]) == 0) {
        __mojo_coro_resume(c, 0, &v);           /* should re-raise here */
        CHECK(0, "resume did not re-raise the escaped exception");
    } else {
        --_mojo_exc_top;
        caught_type = (int)mojo_exc_type_get();
        caught_msg  = mojo_exc_msg_get();
    }
    CHECK(caught_type == 1234, "re-raised type = %d", caught_type);
    CHECK(caught_msg && caught_msg[0] == 'b', "re-raised msg = %s", caught_msg ? caught_msg : "(null)");
    __mojo_coro_destroy(c);
}

/* ── body 5: throw() delivered at the yield, caught by the body ──────── */
static int body_caught_throw;
static void body_catches(MojoCoro *c, void *env)
{
    (void)env;
    int top = ++_mojo_exc_top;
    if (setjmp(_mojo_exc_stack[top]) == 0) {
        __mojo_coro_yield(c, 1);        /* throw arrives here */
        --_mojo_exc_top;
    } else {
        --_mojo_exc_top;
        body_caught_throw = (int)mojo_exc_type_get();
    }
    __mojo_coro_yield(c, 2);            /* keep going after catching */
    __mojo_coro_set_return(c, 0);
}

static void test_throw_caught(void)
{
    body_caught_throw = 0;
    MojoCoro *c = __mojo_coro_new(body_catches, NULL, 0);
    int64_t v = 0;
    CHECK(__mojo_coro_resume(c, 0, &v) == 1 && v == 1, "y1");
    int r = __mojo_coro_throw(c, 777, NULL, NULL, &v);
    CHECK(r == 1 && v == 2, "after throw: r=%d v=%lld", r, (long long)v);
    CHECK(body_caught_throw == 777, "body caught type = %d", body_caught_throw);
    __mojo_coro_destroy(c);
}

/* ── body 6: destroy() while suspended -> GeneratorExit runs cleanup ─── */
static int cleanup_ran;
static void body_with(MojoCoro *c, void *env)
{
    (void)env;
    int top = ++_mojo_exc_top;
    if (setjmp(_mojo_exc_stack[top]) == 0) {
        __mojo_coro_yield(c, 1);
        --_mojo_exc_top;
        cleanup_ran = 1;
    } else {
        --_mojo_exc_top;
        cleanup_ran = 1;               /* __exit__ */
        mojo_raise();                  /* propagate GeneratorExit */
    }
    __mojo_coro_set_return(c, 0);
}

static void test_destroy_runs_cleanup(void)
{
    cleanup_ran = 0;
    MojoCoro *c = __mojo_coro_new(body_with, NULL, 0);
    int64_t v = 0;
    CHECK(__mojo_coro_resume(c, 0, &v) == 1 && v == 1, "y1");
    __mojo_coro_destroy(c);            /* must not raise out of destroy */
    CHECK(cleanup_ran == 1, "cleanup did not run on destroy");
}

/* ── many coroutines interleaved (stack isolation) ──────────────────── */
static void test_interleaved(void)
{
    enum { N = 8 };
    MojoCoro *cs[N];
    for (int i = 0; i < N; i++) cs[i] = __mojo_coro_new(body_count, NULL, 0);
    int64_t v;
    for (int i = 0; i < N; i++) { CHECK(__mojo_coro_resume(cs[i], 0, &v) == 1 && v == 10, "il y1 %d", i); }
    for (int i = N - 1; i >= 0; i--) { CHECK(__mojo_coro_resume(cs[i], 0, &v) == 1 && v == 20, "il y2 %d", i); }
    for (int i = 0; i < N; i++) { CHECK(__mojo_coro_resume(cs[i], 0, &v) == 1 && v == 30, "il y3 %d", i); }
    for (int i = 0; i < N; i++) { CHECK(__mojo_coro_resume(cs[i], 0, &v) == 0 && v == 99, "il ret %d", i); }
    for (int i = 0; i < N; i++) __mojo_coro_destroy(cs[i]);
}

int main(void)
{
    test_basic_sequence();
    test_send();
    test_finally_on_exhaust();
    test_escaped_exception();
    test_throw_caught();
    test_destroy_runs_cleanup();
    test_interleaved();
    if (failures) { printf("%d failure(s)\n", failures); return 1; }
    printf("all Layer 2 coroutine-runtime tests passed\n");
    return 0;
}
