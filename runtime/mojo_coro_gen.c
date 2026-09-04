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
