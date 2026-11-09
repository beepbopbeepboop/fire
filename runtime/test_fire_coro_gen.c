/* test_mojo_coro_gen.c -- the Mojo-facing int64_t shim (mojo_coro_gen.c),
   driven by hand-written "bodies" that stand in for gimple_gen_coro.py's
   output. Everything crosses the boundary as int64_t. */
#include "fire_coro.h"
#include <setjmp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
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

/* `mojo_read_type_tag` / `mojo_read_type_tag_safe` answer "which registered
   struct is this boxed value?", and every producer of a `__mojo_type_id`
   masks it to 31 bits. A BOXED STRING is the value that used to slip past
   them: a heap `char *` is a real pointer, is 8-byte aligned, and
   `malloc_size` says it holds at least eight bytes as soon as the text is
   five characters or longer — so every ADDRESS check passed and the string's
   own eight BYTES came back as a type identity. Measured on the self-hosted
   binary: the text "print" read back as 0x746e697270, which is not a struct,
   not a small value, and therefore not dereferenceable-by-accident either —
   it was dereferenced anyway, by `mojo_dict_get_int_kw`'s `_kw_kind`, which
   classified any pointer-shaped word as a boxed string.

   The invariant these two now hold is DISJOINTNESS, in both directions, and
   that is what the assertions below check rather than the value in isolation:

     * a word outside [0, 0x7fffffff] is not a tag, so a boxed string never
       produces one — a string of five characters or more always has a
       nonzero fifth byte, so its word is always >= 2^32;
     * a tag is always below 2 GiB, so `mojo_boxed_is_str` /
       `_mojo_ptr_shaped` can never call one a pointer and dereference it
       (that direction is CRASH.md's, and the reason the strict reader has a
       2 GiB floor at all).

   CRASH.md fixed the second and could not see the first, because in that
   fault the tag was SMALL; here the value is a pointer-sized word, so every
   range test passed. */
struct fake_tagged { int64_t __mojo_type_id; int64_t payload; };

#define NO_TAG ((int64_t)0x80000000LL)

static void test_type_tag_reads_reject_a_boxed_string(void)
{
    extern int64_t mojo_read_type_tag(int64_t addr);
    extern int64_t mojo_read_type_tag_safe(int64_t addr);

    /* Heap strings rather than literals, so the address is unambiguously a
       malloc block — the shape the crash arrived as, and the one the
       size/alignment guards are written about. */
    char *s = (char *)malloc(16);
    memcpy(s, "print", 6);
    CHECK(mojo_read_type_tag_safe((int64_t)(intptr_t)s) == 0,
          "a boxed string is not a tagged struct (got 0x%llx)",
          (unsigned long long)mojo_read_type_tag_safe((int64_t)(intptr_t)s));
    CHECK(mojo_read_type_tag((int64_t)(intptr_t)s) == 0,
          "the strict reader agrees (got 0x%llx)",
          (unsigned long long)mojo_read_type_tag((int64_t)(intptr_t)s));

    /* Four characters or fewer CAN read back as a plausible identity — the
       bytes of "abcd" are 0x64636261, which is inside the 31-bit tag range
       and no predicate on the word alone can tell it from a struct's, since
       every 31-bit value is some struct name's hash. What must hold is the
       bound: whatever comes back can never be pointer-shaped, so nothing can
       dereference it. This is the residual the fix leaves, stated as a
       property rather than left to be rediscovered. */
    char *tiny = (char *)malloc(5);
    memcpy(tiny, "abcd", 5);
    int64_t t = mojo_read_type_tag_safe((int64_t)(intptr_t)tiny);
    CHECK(t >= 0 && t < NO_TAG,
          "a short string's word is bounded by the tag range (got 0x%llx)",
          (unsigned long long)t);

    /* The positive half: a heap-allocated tagged struct reads back its own
       tag, exactly. Heap rather than automatic because the guard asks
       `malloc_size` — an address that is not a live allocation is not a
       tagged struct as far as this runtime is concerned, which is what keeps
       the 8-byte read off a stack or rodata address. */
    struct fake_tagged *st = (struct fake_tagged *)malloc(sizeof(*st));
    st->__mojo_type_id = 1234567;   /* what a _struct_type_id hash looks like */
    st->payload = 1;
    CHECK(mojo_read_type_tag_safe((int64_t)(intptr_t)st) == 1234567,
          "a real tagged struct reads back its tag (got 0x%llx)",
          (unsigned long long)mojo_read_type_tag_safe((int64_t)(intptr_t)st));
    CHECK(mojo_read_type_tag((int64_t)(intptr_t)st) == 1234567,
          "the strict reader reads the same tag (got 0x%llx)",
          (unsigned long long)mojo_read_type_tag((int64_t)(intptr_t)st));

    /* And the chain the crash actually took, end to end: the tag of a boxed
       string goes into the dict accessor that dereferences a pointer-shaped
       key. With the fix the word is 0, `_kw_kind` answers "an integer key",
       and the lookup misses; before it, the same call took the
       `_KW_STR` arm on 0x746e697270 and faulted inside `_canon_int`. This is
       the assertion that fails LOUDLY (a SIGSEGV, not a CHECK line) if the
       range check is ever dropped, which is why it is here and not just the
       reasoning above it. */
    /* `void *`, not `MojoDict *`: this file declares the runtime's entry
       points by hand rather than including fire_runtime.h, so the struct tag
       is not in scope here (the same reason every other extern above is
       spelled out). */
    extern void *mojo_dict_new(void);
    extern int64_t mojo_dict_get_int_kw(void *d, int64_t kw);
    extern void mojo_dict_free(void *d);
    void *d = mojo_dict_new();
    CHECK(d != NULL, "the dict constructor answered");
    CHECK(mojo_dict_get_int_kw(d, mojo_read_type_tag_safe((int64_t)(intptr_t)s)) == 0,
          "a string's tag is a usable dict key (no fault above)");
    mojo_dict_free(d);

    free(st);
    free(tiny);
    free(s);
}

int main(void)
{
    test_range();
    test_send();
    test_run_gen_rejects_non_handle();
    test_iscoroutine_answers_for_handles_and_non_handles();
    test_type_tag_reads_reject_a_boxed_string();
    if (failures) { printf("%d failure(s)\n", failures); return 1; }
    printf("all Layer 1 shim (mojo_coro_gen) tests passed\n");
    return 0;
}
