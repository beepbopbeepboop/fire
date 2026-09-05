/* mojo_coro_gen.c -- the Mojo-facing shim for Layer 1 (gimple_gen_coro.py).

   Everything here takes and returns `int64_t` handles so NO pointer types
   cross the generated-code boundary (the -fgimple C the ordinary codegen
   emits stays clean). Internally these cast to the real MojoCoro * /
   MojoGenerator * and call Layer 2 (mojo_coro.c).

   A generator `fn g(a, b) -> T` is lowered by Layer 1 to:
       fn __mgco_g_body(__c):                 # runs on the coroutine stack
           var a = __mojo_gen_arg(__c, 0)
           var b = __mojo_gen_arg(__c, 1)
           <original body; yield e -> __mojo_coro_yield_i(__c, box e);
                            return e -> __mojo_gen_set_return(__c, box e); return>
       fn __mgco_g_start(a, b) -> Int:  return __mojo_gen_new_2(__mgco_g_body, a, b)
       fn __mgco_g_resume(g) -> Bool:   return __mojo_gen_resume(g, 0)
       fn __mgco_g_value(g)  -> T:      return __mojo_gen_value(g)
       fn __mgco_g_destroy(g):          __mojo_gen_destroy(g)
   and _generator_api[g] points the ordinary for/next/yield-from consumers
   at __mgco_g_{start,resume,value,destroy} exactly as today.
*/
#include "mojo_coro.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Layer 2 also needs a way to hand a body its stashed args: */
extern void *__mojo_coro_env(MojoCoro *c);   /* defined in mojo_coro.c (added) */

#define MOJO_GEN_MAX_ARGS 8

typedef struct MojoGen {
    MojoCoro *coro;
    void    (*body)(int64_t /* coro handle */);
    int64_t   args[MOJO_GEN_MAX_ARGS];
    int       nargs;
    int       is_method;   /* args[0] is a `self`/`cls` pointer passed as arg 2 */
    int64_t   value;      /* last yielded box */
    int64_t   retval;     /* return box once done */
    int       done;
    int       pending_exc;
} MojoGen;

/* The trampoline Layer 2 actually enters (void(MojoCoro*, void*)); it
   forwards to the Mojo-lowered body with an int64_t coro handle, plus (for
   a generator METHOD) the receiver pointer as a real 2nd argument so the
   ordinary codegen can type `self` as `Struct *`. */
static void
mgen_thunk(MojoCoro *c, void *env)
{
    MojoGen *g = (MojoGen *)env;
    if (g->is_method) {
        ((void (*)(int64_t, void *))g->body)((int64_t)(uintptr_t)c,
                                             (void *)(uintptr_t)g->args[0]);
    } else {
        g->body((int64_t)(uintptr_t)c);
    }
}

static int64_t
mgen_new_impl(void (*body)(int64_t), const int64_t *args, int n, int is_method)
{
    MojoGen *g = (MojoGen *)calloc(1, sizeof *g);
    if (!g) return 0;
    g->body      = body;
    g->nargs     = n;
    g->is_method = is_method;
    for (int i = 0; i < n && i < MOJO_GEN_MAX_ARGS; i++) g->args[i] = args[i];
    g->coro = __mojo_coro_new(mgen_thunk, g, 0);
    if (!g->coro) { free(g); return 0; }
    return (int64_t)(uintptr_t)g;
}

static int64_t
mgen_new(void (*body)(int64_t), const int64_t *args, int n)
{
    return mgen_new_impl(body, args, n, 0);
}

int64_t __mojo_gen_new_0(int64_t body)
{ return mgen_new((void (*)(int64_t))(uintptr_t)body, 0, 0); }

int64_t __mojo_gen_new_1(int64_t body, int64_t a0)
{ int64_t a[1] = { a0 }; return mgen_new((void (*)(int64_t))(uintptr_t)body, a, 1); }

int64_t __mojo_gen_new_2(int64_t body, int64_t a0, int64_t a1)
{ int64_t a[2] = { a0, a1 }; return mgen_new((void (*)(int64_t))(uintptr_t)body, a, 2); }

int64_t __mojo_gen_new_3(int64_t body, int64_t a0, int64_t a1, int64_t a2)
{ int64_t a[3] = { a0, a1, a2 }; return mgen_new((void (*)(int64_t))(uintptr_t)body, a, 3); }

int64_t __mojo_gen_new_4(int64_t body, int64_t a0, int64_t a1, int64_t a2, int64_t a3)
{ int64_t a[4] = { a0, a1, a2, a3 }; return mgen_new((void (*)(int64_t))(uintptr_t)body, a, 4); }

int64_t __mojo_gen_new_5(int64_t body, int64_t a0, int64_t a1, int64_t a2, int64_t a3, int64_t a4)
{ int64_t a[5] = { a0,a1,a2,a3,a4 }; return mgen_new((void (*)(int64_t))(uintptr_t)body, a, 5); }

int64_t __mojo_gen_new_6(int64_t body, int64_t a0, int64_t a1, int64_t a2, int64_t a3, int64_t a4, int64_t a5)
{ int64_t a[6] = { a0,a1,a2,a3,a4,a5 }; return mgen_new((void (*)(int64_t))(uintptr_t)body, a, 6); }

/* Method variants: a0 is the receiver pointer (self/cls), passed to the
   body as a real 2nd argument; a1.. are the ordinary params. */
int64_t __mojo_gen_new_m0(int64_t body, int64_t self)
{ int64_t a[1] = { self }; return mgen_new_impl((void (*)(int64_t))(uintptr_t)body, a, 1, 1); }

int64_t __mojo_gen_new_m1(int64_t body, int64_t self, int64_t a1)
{ int64_t a[2] = { self, a1 }; return mgen_new_impl((void (*)(int64_t))(uintptr_t)body, a, 2, 1); }

int64_t __mojo_gen_new_m2(int64_t body, int64_t self, int64_t a1, int64_t a2)
{ int64_t a[3] = { self, a1, a2 }; return mgen_new_impl((void (*)(int64_t))(uintptr_t)body, a, 3, 1); }

int64_t __mojo_gen_new_m3(int64_t body, int64_t self, int64_t a1, int64_t a2, int64_t a3)
{ int64_t a[4] = { self, a1, a2, a3 }; return mgen_new_impl((void (*)(int64_t))(uintptr_t)body, a, 4, 1); }

/* Called from inside the body (via __c) to read a stashed argument. */
int64_t
__mojo_gen_arg(int64_t coro, int64_t idx)
{
    MojoGen *g = (MojoGen *)__mojo_coro_env((MojoCoro *)(uintptr_t)coro);
    if (!g || idx < 0 || idx >= g->nargs) return 0;
    return g->args[idx];
}

/* async-generator body: yield e -> is_wd=0, await's wait-descriptor ->
   is_wd=1, on the SAME channel (see mojo_coro.h). The consuming `async
   for` reads back __mojo_gen_last_yield_was_wd(coro) right after a
   resume to tell them apart. */
int64_t
__mojo_gen_yield_tagged(int64_t coro, int64_t val, int64_t is_wd)
{
    return __mojo_coro_yield_tagged((MojoCoro *)(uintptr_t)coro, val, (int)is_wd);
}

/* Takes a MojoGenerator handle (like _resume/_value/_destroy), not a raw
   MojoCoro -- consistent with every other <base>_* consumer entry point. */
int64_t
__mojo_gen_last_yield_was_wd(int64_t genHandle)
{
    MojoGen *g = (MojoGen *)(uintptr_t)genHandle;
    return (g && g->coro) ? __mojo_coro_last_yield_was_wd(g->coro) : 0;
}

/* yield e -- returns the value sent in by the next resume. Typed variants
   so gimple_gen_coro can pass a char* / double straight through without a
   codegen-inserted cast; all funnel to the one int64_t-box yield. */
int64_t
__mojo_coro_yield_i(int64_t coro, int64_t v)
{
    return __mojo_coro_yield((MojoCoro *)(uintptr_t)coro, v);
}

int64_t
__mojo_coro_yield_p(int64_t coro, void *v)
{
    return __mojo_coro_yield((MojoCoro *)(uintptr_t)coro, (int64_t)(uintptr_t)v);
}

int64_t
__mojo_coro_yield_d(int64_t coro, double v)
{
    int64_t bits;
    __builtin_memcpy(&bits, &v, sizeof bits);
    return __mojo_coro_yield((MojoCoro *)(uintptr_t)coro, bits);
}

void
__mojo_gen_set_return(int64_t coro, int64_t v)
{
    __mojo_coro_set_return((MojoCoro *)(uintptr_t)coro, v);
}

/* `yield (a, b, ...)` -- box the slots into a MojoList (each stored as its
   raw int64_t bits, exactly the convention _emit_generator_tuple_unpack
   reads back via mojo_list_get_{int,str,...}) and hand the list pointer
   bits to the yield as one int64_t. */
extern void   *mojo_list_new(void);
extern void    mojo_list_append_int(void *, int64_t);

static int64_t
tuple_box(const int64_t *slots, int n)
{
    void *l = mojo_list_new();
    for (int i = 0; i < n; i++) mojo_list_append_int(l, slots[i]);
    return (int64_t)(uintptr_t)l;
}

int64_t __mojo_tuple_box_2(int64_t a, int64_t b)
{ int64_t s[2] = { a, b }; return tuple_box(s, 2); }
int64_t __mojo_tuple_box_3(int64_t a, int64_t b, int64_t c)
{ int64_t s[3] = { a, b, c }; return tuple_box(s, 3); }
int64_t __mojo_tuple_box_4(int64_t a, int64_t b, int64_t c, int64_t d)
{ int64_t s[4] = { a, b, c, d }; return tuple_box(s, 4); }
int64_t __mojo_tuple_box_5(int64_t a, int64_t b, int64_t c, int64_t d, int64_t e)
{ int64_t s[5] = { a, b, c, d, e }; return tuple_box(s, 5); }
int64_t __mojo_tuple_box_6(int64_t a, int64_t b, int64_t c, int64_t d, int64_t e, int64_t f)
{ int64_t s[6] = { a, b, c, d, e, f }; return tuple_box(s, 6); }
int64_t __mojo_tuple_box_7(int64_t a, int64_t b, int64_t c, int64_t d, int64_t e, int64_t f, int64_t g)
{ int64_t s[7] = { a, b, c, d, e, f, g }; return tuple_box(s, 7); }
int64_t __mojo_tuple_box_8(int64_t a, int64_t b, int64_t c, int64_t d, int64_t e, int64_t f, int64_t g, int64_t h)
{ int64_t s[8] = { a, b, c, d, e, f, g, h }; return tuple_box(s, 8); }

/* resume: 1 = produced a value (read via __mojo_gen_value), 0 = done. On an
   uncaught exception in the body, __mojo_coro_resume re-raises here (live
   stack) -- so a 0 return is always genuine exhaustion by the time we see
   it, matching the ordinary consumers' mojo_exc_pending check contract. */
int64_t
__mojo_gen_resume(int64_t gen, int64_t send)
{
    MojoGen *g = (MojoGen *)(uintptr_t)gen;
    if (!g || g->done) return 0;
    int64_t out = 0;
    int r = __mojo_coro_resume(g->coro, send, &out);
    if (r == 1) { g->value = out; return 1; }
    g->retval = out;
    g->done = 1;
    return 0;
}

int64_t __mojo_gen_value(int64_t gen)
{ MojoGen *g = (MojoGen *)(uintptr_t)gen; return g ? g->value : 0; }

int64_t __mojo_gen_retval(int64_t gen)
{ MojoGen *g = (MojoGen *)(uintptr_t)gen; return g ? g->retval : 0; }

/* throw(exc) into a suspended generator. */
int64_t
__mojo_gen_throw(int64_t gen, int64_t exc_type, int64_t exc_msg, int64_t exc_obj)
{
    MojoGen *g = (MojoGen *)(uintptr_t)gen;
    if (!g || g->done) return 0;
    int64_t out = 0;
    int r = __mojo_coro_throw(g->coro, exc_type, (char *)(uintptr_t)exc_msg,
                              (void *)(uintptr_t)exc_obj, &out);
    if (r == 1) { g->value = out; return 1; }
    g->retval = out; g->done = 1;
    return 0;
}

void
__mojo_gen_destroy(int64_t gen)
{
    MojoGen *g = (MojoGen *)(uintptr_t)gen;
    if (!g) return;
    __mojo_coro_destroy(g->coro);
    free(g);
}

/* "Detached async" (bugs/hard/CODEGEN_coro_detached_async_take_handle.md):
   the stack-switch equivalent of mojo_coro_resume_generic (runtime/
   mojo_async_runtime.cpp) -- a `void (*)(int64_t)` resume primitive that
   drives a coroutine ONE resume step, matching the signature
   AsyncRT_DeviceContext_enqueueHostFunction(Range) (runtime/
   mojo_async_runtime.h) expects for its resume_fn argument. Substituted in
   for `_coro_resume_fn` by gimple_codegen.py's BUILTIN_VALUE_MAP override
   when MOJO_CORO=stackswitch (gimple_gen_coro.py); `__mojo_gen_destroy`
   above already has the exact `void (*)(int64_t)` shape needed for
   `_coro_destroy_fn` as-is, so no separate wrapper is needed for that one.
   Callers of this path only ever hand it a coroutine whose body has no
   internal suspension point of its own (device_context.mojo's `wrapper()`
   closures, gated by gimple_gen_coro's ordinary async eligibility -- no
   `await` in the body), so one resume() always drives it to completion,
   same honesty argument as the cpp-path stub. */
void
__mojo_gen_resume_once(int64_t gen)
{
    (void)__mojo_gen_resume(gen, 0);
}

/* Nested-async mutable closure capture (bugs/hard/CODEGEN_coro_nested_
   async_closure_capture.md) -- v0: a plain int64_t heap box, one malloc'd
   cell per captured outer local. Handles are plain int64_t (never a raw
   pointer type), matching every other cross-boundary handle in this file,
   so the -fgimple-compiled enclosing function and coroutine body can both
   pass the handle around as an ordinary scalar. No free() -- the box's
   lifetime is exactly one call of the enclosing (ordinary) function, and
   this is a small, bounded, deliberate leak for v0 (same simplification
   this codegen already accepts for other short-lived handles); a real
   lifetime-tracked free is future work, not required for correctness of
   the captured VALUE. */
int64_t
__mojo_box_new_i64(int64_t init)
{
    int64_t *p = (int64_t *)malloc(sizeof(int64_t));
    if (p) *p = init;
    return (int64_t)(uintptr_t)p;
}

int64_t
__mojo_box_get_i64(int64_t box)
{
    return box ? *(int64_t *)(uintptr_t)box : 0;
}

void
__mojo_box_set_i64(int64_t box, int64_t v)
{
    if (box) *(int64_t *)(uintptr_t)box = v;
}

/* ── async def / await bridge (runtime/mojo_async_sched.c) ────────────── */
#include "mojo_wd.h"

extern uint64_t __mojo_async_now_ns(void);
extern void     __mojo_async_run(MojoCoro *c);

/* `await asyncio.sleep(secs)` -- called from inside a lowered async body
   with its own __c; suspends until secs have elapsed. */
void
__mojo_async_await_sleep(int64_t coro, double secs)
{
    uint64_t wake = __mojo_async_now_ns() + (uint64_t)(secs * 1e9);
    __mojo_coro_yield_tagged((MojoCoro *)(uintptr_t)coro, mojo_wd_make(MOJO_WD_SLEEP, (int64_t)wake), 1);
}

/* `await asyncio.sock_recv(fd)` -- reads ONE byte once fd is readable,
   matching the existing cpp-path _mojoasync_SockRecvAwaiter exactly:
   returns the byte value on success, -1 on EOF (peer closed), -2 on a
   real read error. */
int64_t
__mojo_async_await_sock_recv(int64_t coro, int64_t fd)
{
    __mojo_coro_yield_tagged((MojoCoro *)(uintptr_t)coro, mojo_wd_make(MOJO_WD_READ, fd), 1);
    unsigned char c;
    ssize_t n = read((int)fd, &c, 1);
    if (n == 1) return (int64_t)c;
    if (n == 0) return (int64_t)-1;
    return (int64_t)-2;
}

/* `asyncio.run(f())`'s bridge: genHandle is the MojoGenerator f() already
   constructed (via the ordinary __mgco_f_start call, routed there because
   f is registered in _generator_api). Drive its underlying MojoCoro to
   completion through the scheduler, then make the handle's own bookkeeping
   agree (so a subsequent __mojo_gen_retval(genHandle) reads the right
   value) -- __mojo_async_run resumes the raw MojoCoro directly (bypassing
   MojoGen's own resume/value tracking, which only matters for the
   intermediate wait-descriptor forwarding, not the final result: the body
   itself already stored the real return box on the MojoCoro via
   __mojo_gen_set_return -> __mojo_coro_set_return). */
void
__mojo_async_run_gen(int64_t genHandle)
{
    MojoGen *g = (MojoGen *)(uintptr_t)genHandle;
    if (!g || g->done) return;
    __mojo_async_run(g->coro);
    g->retval = __mojo_coro_return_value(g->coro);
    g->done = 1;
}
