/* test_mojo_coro_gen.c -- the Mojo-facing int64_t shim (mojo_coro_gen.c),
   driven by hand-written "bodies" that stand in for gimple_gen_coro.py's
   output. Everything crosses the boundary as int64_t. */
#include "fire_coro.h"
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

extern int64_t __mojo_gen_new_0(int64_t body);
extern int64_t __mojo_gen_new_2(int64_t body, int64_t a0, int64_t a1);
extern int64_t __mojo_gen_arg(int64_t coro, int64_t idx);
extern int64_t __mojo_coro_yield_i(int64_t coro, int64_t v);
extern void    __mojo_gen_set_return(int64_t coro, int64_t v);
extern int64_t __mojo_gen_resume(int64_t gen, int64_t send);
extern int64_t __mojo_gen_value(int64_t gen);
extern int64_t __mojo_gen_retval(int64_t gen);
extern void    __mojo_gen_destroy(int64_t gen);
extern void    __mojo_async_run_gen(int64_t genHandle);
/* The real fire_runtime.c is linked by this test (see test_coro_runtime.py's
   per-case note), so the exception frame slots and accessors are real here
   rather than the standalone stub. */
#define MOJO_EXC_STACK_MAX 64
extern jmp_buf _mojo_exc_stack[MOJO_EXC_STACK_MAX];
extern int     _mojo_exc_top;
extern int64_t mojo_exc_type_get(void);
extern char   *mojo_exc_msg_get(void);
extern void    mojo_cleanup_checkpoint_save(void);

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

/* `asyncio.run(x)` drives a coroutine handle, and the static inference
   behind accepting a NAME there (mojo/middle/coro.py's `_scan_handle_vars`)
   deliberately covers only same-module, statically-named callees. The
   runtime boundary is what makes the bridge safe rather than merely
   usually-right: `__mojo_async_run_gen` checks the handle against the live
   -handle registry and raises ValueError otherwise, exactly as Python does
   for `asyncio.run(<not a coroutine>)`. Before the registry existed, the
   value was cast straight to `MojoGen *` and `->done` read out of whatever
   memory the integer happened to point at.

   Driven here directly, because the static side refuses every shape the
   compiler can actually produce wrong -- a regression test through the
   compiler could only ever exercise the already-correct path. */
static void test_run_gen_rejects_non_handle(void)
{
    /* A plain small integer, a plausible string address, and NULL: three
       shapes that all read as "a pointer" to a cast. */
    int64_t bogus[3] = { 0, 12345, 0x7f0000000000LL };
    for (int i = 0; i < 3; i++) {
        int top = _mojo_exc_top;
        /* The generated code's own landing-pad convention (see
           gimple_gen_stmts's TryStmt emitter): bump `_mojo_exc_top` FIRST,
           then `setjmp(_mojo_exc_stack[_mojo_exc_top])` — because
           `mojo_raise` longjmps to index `_mojo_exc_top`, not `_mojo_exc_top
           - 1`. `mojo_cleanup_checkpoint_save()` goes between them, and is
           what `mojo_raise`'s cleanup unwind reads. */
        _mojo_exc_top = top + 1;
        mojo_cleanup_checkpoint_save();
        if (setjmp(_mojo_exc_stack[_mojo_exc_top]) == 0) {
            __mojo_async_run_gen(bogus[i]);
            _mojo_exc_top = top;              /* no raise: the guard is gone */
            CHECK(0, "bogus handle %lld was accepted and driven",
                  (long long)bogus[i]);
            return;
        }
        _mojo_exc_top = top;
        CHECK(mojo_exc_type_get() == 663468903,
              "bogus handle %lld raised type %lld, want ValueError's 663468903",
              (long long)bogus[i], (long long)mojo_exc_type_get());
        CHECK(strcmp(mojo_exc_msg_get(), "a coroutine was expected") == 0,
              "bogus handle %lld raised message %s",
              (long long)bogus[i], mojo_exc_msg_get());
    }
}

/* `asyncio.iscoroutine(x)` / `asyncio.isawaitable(x)` ask the SAME question
   `__mojo_async_run_gen` asks before driving anything, and the answer is the
   registry lookup rather than a cast -- so unlike the drive path it does not
   raise, it returns 0, which is CPython's own answer for a value that is not
   a coroutine. (`isawaitable` is deliberately NOT here: it is
   `inspect.isawaitable` in CPython 3.14, so answering for it under the
   `asyncio.` spelling would be the divergence.)

   Driven here for the same reason as the case above, and with the same
   property to protect: the positive case needs a REAL live handle (a value
   the compiler produced is the only way to get one), and the negative cases
   are shapes a cast would read as a pointer. The positive half is the
   regression that matters — before the predicate existed, a value that WAS a
   coroutine answered 0, so `if asyncio.iscoroutine(c):` took the else
   branch, silently. */
static void test_iscoroutine_answers_for_handles_and_non_handles(void)
{
    extern _Bool __mojo_async_iscoroutine(int64_t genHandle);

    CHECK(__mojo_async_iscoroutine(0) == 0, "NULL is not a coroutine");
    CHECK(__mojo_async_iscoroutine(12345) == 0, "small int is not a coroutine");
    CHECK(__mojo_async_iscoroutine(0x7f0000000000LL) == 0,
          "plausible pointer is not a coroutine");

    int64_t g = __mojo_gen_new_2((int64_t)(intptr_t)&body_range, 0, 3);
    CHECK(__mojo_async_iscoroutine(g) == 1,
          "a live handle is a coroutine (got %d)", (int)__mojo_async_iscoroutine(g));
    __mojo_gen_destroy(g);
    /* Freed: the registry entry went with it, so the very same address is no
       longer a coroutine. That is the property a stale registry would lose,
       and the reason the check cannot be an address->type table. */
    CHECK(__mojo_async_iscoroutine(g) == 0,
          "a destroyed handle is not a coroutine (got %d)",
          (int)__mojo_async_iscoroutine(g));
}

int main(void)
{
    test_range();
    test_send();
    test_run_gen_rejects_non_handle();
    test_iscoroutine_answers_for_handles_and_non_handles();
    if (failures) { printf("%d failure(s)\n", failures); return 1; }
    printf("all Layer 1 shim (mojo_coro_gen) tests passed\n");
    return 0;
}
