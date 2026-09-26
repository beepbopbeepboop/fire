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
#include "fire_coro.h"

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

/* Same, for a `double`-typed generator parameter: the argument's raw 64
   bits were stashed by a bit-cast at the `<base>_start` call site (see
   gimple_gen_coro.emit_c's arg_fwd), so reinterpret rather than convert.
   Symmetric with __mojo_coro_yield_d / <base>_value's memcpy unbox. */
double
__mojo_gen_arg_d(int64_t coro, int64_t idx)
{
    int64_t b = __mojo_gen_arg(coro, idx);
    double d;
    __builtin_memcpy(&d, &b, sizeof d);
    return d;
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

/* The value a `x = yield <double>` receives. The yield shims all return the
   raw int64_t slot (that is the whole channel), so a DOUBLE-valued
   generator's body has to reinterpret those bits -- the exact inverse of
   `__mojo_coro_yield_d`'s bit-cast on the way out, and the same
   memcpy-unbox idiom `<base>_value` uses for a 'd' generator's yields.
   Without this, `x = yield 1.5` bound x to the raw bit pattern of whatever
   was sent and every later use of x computed on garbage. */
double
__mojo_gen_send_d(int64_t bits)
{
    double d;
    __builtin_memcpy(&d, &bits, sizeof d);
    return d;
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

/* ── tagged nested-tuple slots (cluster B) ───────────────────────────────
 * A generator `yield` whose tuple has a slot that is ITSELF a tuple with a
 * heterogeneous inner shape across sites (Lib/modulefinder.py's
 * `yield "store", (name,)` / `yield "absolute_import", (fromlist, name)` /
 * `yield "relative_import", (level, fromlist, name)`) boxes that inner
 * tuple as a MojoList carrying a runtime TYPE TAG next to each element:
 *
 *     [ tag0, word0, tag1, word1, ... ]        (2*K int64 slots)
 *
 * `word_i` is the element's raw 64-bit representation (int value, pointer,
 * or a double's IEEE bits), `tag_i` names its kind (below). The consumer
 * (`_emit_generator_tuple_unpack` + the tagged unpack path in
 * `_assign_target`) reads a name back via the `mojo_tagged_*` accessor
 * matching that name's own C type, so each per-branch unpack is correct
 * regardless of which yield site produced the value -- the reason plain
 * box-without-tags would silently miscompile. */
#define MOJO_TAG_INT    0
#define MOJO_TAG_STR    1
#define MOJO_TAG_DOUBLE 2
#define MOJO_TAG_LIST   3
#define MOJO_TAG_NONE   4

extern void   *mojo_list_new(void);
extern void    mojo_list_append_int(void *, int64_t);
extern int64_t mojo_list_get_int(void *, int64_t);
extern int64_t mojo_list_len(void *);

static int64_t
tuple_box_tagged(const int64_t *pairs, int k)
{
    void *l = mojo_list_new();
    for (int i = 0; i < k; i++) {
        mojo_list_append_int(l, pairs[2 * i]);      /* tag */
        mojo_list_append_int(l, pairs[2 * i + 1]);  /* word */
    }
    return (int64_t)(uintptr_t)l;
}

int64_t __mojo_tuple_box_tag_1(int64_t t0, int64_t v0)
{ int64_t s[2] = { t0, v0 }; return tuple_box_tagged(s, 1); }
int64_t __mojo_tuple_box_tag_2(int64_t t0, int64_t v0, int64_t t1, int64_t v1)
{ int64_t s[4] = { t0, v0, t1, v1 }; return tuple_box_tagged(s, 2); }
int64_t __mojo_tuple_box_tag_3(int64_t t0, int64_t v0, int64_t t1, int64_t v1, int64_t t2, int64_t v2)
{ int64_t s[6] = { t0, v0, t1, v1, t2, v2 }; return tuple_box_tagged(s, 3); }
int64_t __mojo_tuple_box_tag_4(int64_t t0, int64_t v0, int64_t t1, int64_t v1, int64_t t2, int64_t v2, int64_t t3, int64_t v3)
{ int64_t s[8] = { t0, v0, t1, v1, t2, v2, t3, v3 }; return tuple_box_tagged(s, 4); }
int64_t __mojo_tuple_box_tag_5(int64_t t0, int64_t v0, int64_t t1, int64_t v1, int64_t t2, int64_t v2, int64_t t3, int64_t v3, int64_t t4, int64_t v4)
{ int64_t s[10] = { t0, v0, t1, v1, t2, v2, t3, v3, t4, v4 }; return tuple_box_tagged(s, 5); }
int64_t __mojo_tuple_box_tag_6(int64_t t0, int64_t v0, int64_t t1, int64_t v1, int64_t t2, int64_t v2, int64_t t3, int64_t v3, int64_t t4, int64_t v4, int64_t t5, int64_t v5)
{ int64_t s[12] = { t0, v0, t1, v1, t2, v2, t3, v3, t4, v4, t5, v5 }; return tuple_box_tagged(s, 6); }
int64_t __mojo_tuple_box_tag_7(int64_t t0, int64_t v0, int64_t t1, int64_t v1, int64_t t2, int64_t v2, int64_t t3, int64_t v3, int64_t t4, int64_t v4, int64_t t5, int64_t v5, int64_t t6, int64_t v6)
{ int64_t s[14] = { t0, v0, t1, v1, t2, v2, t3, v3, t4, v4, t5, v5, t6, v6 }; return tuple_box_tagged(s, 7); }
int64_t __mojo_tuple_box_tag_8(int64_t t0, int64_t v0, int64_t t1, int64_t v1, int64_t t2, int64_t v2, int64_t t3, int64_t v3, int64_t t4, int64_t v4, int64_t t5, int64_t v5, int64_t t6, int64_t v6, int64_t t7, int64_t v7)
{ int64_t s[16] = { t0, v0, t1, v1, t2, v2, t3, v3, t4, v4, t5, v5, t6, v6, t7, v7 }; return tuple_box_tagged(s, 8); }

int64_t mojo_double_bits(double d)
{ int64_t w; __builtin_memcpy(&w, &d, 8); return w; }

static int64_t
_tagged_word(int64_t box, int64_t p)
{
    if (p < 0 || 2 * p + 1 >= mojo_list_len((void *)(uintptr_t)box)) return 0;
    return mojo_list_get_int((void *)(uintptr_t)box, 2 * p + 1);
}
static int64_t
_tagged_tag(int64_t box, int64_t p)
{
    if (p < 0 || 2 * p >= mojo_list_len((void *)(uintptr_t)box)) return MOJO_TAG_NONE;
    return mojo_list_get_int((void *)(uintptr_t)box, 2 * p);
}
int64_t mojo_tagged_int(int64_t box, int64_t p)
{ return _tagged_tag(box, p) == MOJO_TAG_INT ? _tagged_word(box, p) : 0; }
int64_t mojo_tagged_word_dyn(int64_t box, int64_t p)
{ return _tagged_word(box, p); }
int64_t mojo_tagged_tag_dyn(int64_t box, int64_t p)
{ return _tagged_tag(box, p); }
char *mojo_tagged_str(int64_t box, int64_t p)
{ return _tagged_tag(box, p) == MOJO_TAG_STR ? (char *)(uintptr_t)_tagged_word(box, p) : NULL; }
int64_t mojo_tagged_list(int64_t box, int64_t p)
{ int64_t t = _tagged_tag(box, p); return (t == MOJO_TAG_LIST) ? _tagged_word(box, p) : 0; }
double mojo_tagged_double(int64_t box, int64_t p)
{
    int64_t t = _tagged_tag(box, p);
    if (t != MOJO_TAG_DOUBLE) return 0.0;
    int64_t w = _tagged_word(box, p);
    double d; __builtin_memcpy(&d, &w, 8);
    return d;
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

/* Typed variants of the nested-async capture box (Increment C): a captured
   outer local that is a `Float64`/`Float32` (double cell) or a
   `String`/`StringLiteral` (char * cell). The HANDLE stays a plain int64_t
   (the malloc'd cell address) exactly like the i64 box, so the hidden
   trailing param threading is unchanged; only the element type differs. */
int64_t
__mojo_box_new_d(double init)
{
    double *p = (double *)malloc(sizeof(double));
    if (p) *p = init;
    return (int64_t)(uintptr_t)p;
}

double
__mojo_box_get_d(int64_t box)
{
    return box ? *(double *)(uintptr_t)box : 0.0;
}

void
__mojo_box_set_d(int64_t box, double v)
{
    if (box) *(double *)(uintptr_t)box = v;
}

int64_t
__mojo_box_new_p(char *init)
{
    char **p = (char **)malloc(sizeof(char *));
    if (p) *p = init;
    return (int64_t)(uintptr_t)p;
}

char *
__mojo_box_get_p(int64_t box)
{
    return box ? *(char **)(uintptr_t)box : (char *)0;
}

void
__mojo_box_set_p(int64_t box, char *v)
{
    if (box) *(char **)(uintptr_t)box = v;
}

/* ── async def / await bridge (runtime/mojo_async_sched.c) ────────────── */
#include "fire_wd.h"

extern uint64_t __mojo_async_now_ns(void);
extern void     __mojo_async_run(MojoCoro *c);
extern void     __mojo_async_run_until_complete(void);
extern void     __mojo_async_task_register(MojoCoro *coro, int64_t genHandle);
extern int      __mojo_async_task_is_registered(int64_t genHandle);

/* `create_task(f(...))`: f() already built the MojoGen handle; enqueue its
   coroutine onto the shared scheduler ready queue so sibling tasks run
   concurrently (bugs/COMPILE_FAIL_asyncio_queues.md gap 3). */
void
__mojo_async_task_schedule(int64_t genHandle)
{
    MojoGen *g = (MojoGen *)(uintptr_t)genHandle;
    if (!g || !g->coro || g->done) return;
    __mojo_async_task_register(g->coro, genHandle);
}

/* Called by the scheduler (mojo_async_sched.c finalize_task) when a
   registered task coroutine runs off the end: publish its result onto the
   MojoGen handle so a subsequent __mojo_async_await_task / __mojo_gen_retval
   reads it. */
void
__mojo_gen_finalize(int64_t genHandle, int64_t retbox)
{
    MojoGen *g = (MojoGen *)(uintptr_t)genHandle;
    if (!g || g->done) return;
    g->retval = retbox;
    g->done = 1;
}

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
    if (__mojo_async_task_is_registered(genHandle)) {
        /* Eagerly scheduled at create_task() time -- it is already on the
           scheduler's ready queue. Just drain the loop (which also drives
           every sibling task); finalize_task publishes g->retval/g->done. */
        __mojo_async_run_until_complete();
    } else {
        __mojo_async_run(g->coro);
    }
    if (!g->done) {
        g->retval = __mojo_coro_return_value(g->coro);
        g->done = 1;
    }
}

/* `await <task>` where <task> came from create_task(): the task coroutine
   was scheduled onto the ready queue at creation. Park this coroutine on
   it (MOJO_WD_TASK, payload = the task's MojoCoro* bits) until the
   scheduler's finalize_task publishes its result. Returns the task's
   return box. */
int64_t
__mojo_async_await_task(int64_t coro, int64_t genHandle)
{
    MojoGen *g = (MojoGen *)(uintptr_t)genHandle;
    if (!g) return 0;
    while (!g->done) {
        __mojo_coro_yield_tagged((MojoCoro *)(uintptr_t)coro,
                                 mojo_wd_make(MOJO_WD_TASK,
                                              (int64_t)(uintptr_t)g->coro), 1);
    }
    return g->retval;
}

/* ── Awaitable protocol: Future / Event handles ───────────────────────────
   The real asyncio suspension primitive: an allocatable handle with a
   waiter list. `await <future>` parks the current coroutine on the handle
   (MOJO_WD_FUTURE wait-descriptor -- the scheduler does NOT reschedule it);
   `future.set_result(v)` / `event.set()` from ANY other coroutine (or from
   ordinary synchronous code, e.g. Queue.put_nowait waking a blocked
   getter) records the result and schedules every parked waiter back onto
   the scheduler's ready queue. All handles are plain int64_t, like every
   other cross-boundary handle in this file.

   Event is the same object with result unused: it stays "done" once set
   (so a wait() after set() returns immediately), and clear() re-arms it. */
extern void __mojo_async_notify_future(int64_t future_handle);

/* Exception-class tags -- must match GimpleGen._exc_type_id
   (`(zlib.crc32(b"Name") & 0x7fffffff) or 1`). */
#define _MOJO_EXC_TAG_EXCEPTION       2100825294
#define _MOJO_EXC_TAG_CANCELLEDERROR   760980751

extern void    mojo_exc_type_set(int64_t);
extern void    mojo_exc_msg_set(char *);
extern void    mojo_raise(void);

typedef struct MojoFutureCB {
    int64_t              cb;      /* callback handle (see __mojo_future_invoke_callback) */
    int64_t              tag;     /* 0 = bare fn ptr, 1 = MojoBoundMethod* / closure */
    struct MojoFutureCB *next;
} MojoFutureCB;

/* Mirror of runtime/fire_runtime.h's MojoBoundMethod -- a method or
   capturing closure referenced as a value: { fn, self }. Kept local so
   this TU needn't pull in the whole runtime header. */
typedef struct { void *fn; void *self; } MojoCoroBoundMethod;

typedef struct MojoFuture {
    int          done;           /* resolved: result OR exception OR cancelled */
    int          cancelled;
    int          has_exc;
    int64_t      result;
    int64_t      exc_type;       /* _exc_type_id tag, when has_exc */
    char        *exc_msg;
    MojoFutureCB *callbacks;     /* done-callback list, LIFO; fired on resolve */
} MojoFuture;

/* Invoke one recorded done-callback, dispatching on the handle-kind `tag`
   the codegen emitted alongside it (gimple_gen_coro._done_callback_tag /
   gimple_gen_methods._future_callback_tag):

     tag 0 -- bare C function pointer: a top-level `def cb(fut)` passed by
       name, or a non-capturing nested closure. Both lower to a
       `_funcptr_<csym>` / `void *` value; call it `((void(*)(int64_t))h)
       (fut)`, matching asyncio's `callback(fut)` signature.

     tag 1 -- MojoBoundMethod* : a bound method `self.on_done`, or a
       capturing closure (env carried as `self`). Lowered via
       `mojo_bound_method_new(fn, self)`; invoke as `fn(self, fut)` -- the
       same "self, then N ordinary args" convention every compiled method
       uses, i.e. runtime/fire_runtime.h's mojo_bound_method_call_1.

   A NULL / obviously-non-pointer handle is ignored. */
void
__mojo_future_invoke_callback(int64_t cb, int64_t tag, int64_t future_handle)
{
    if (cb <= 0xffff) return;
    if (tag == 1) {
        MojoCoroBoundMethod *bm = (MojoCoroBoundMethod *)(uintptr_t)cb;
        ((int64_t (*)(void *, int64_t))bm->fn)(bm->self, future_handle);
        return;
    }
    void (*fn)(int64_t) = (void (*)(int64_t))(uintptr_t)cb;
    fn(future_handle);
}

static void
future_fire_callbacks(int64_t h, MojoFuture *f)
{
    MojoFutureCB *cb = f->callbacks;
    f->callbacks = NULL;
    while (cb) {
        MojoFutureCB *nx = cb->next;
        __mojo_future_invoke_callback(cb->cb, cb->tag, h);
        free(cb);
        cb = nx;
    }
}

/* Common resolution path for set_result / set_exception / cancel: wake
   every parked awaiter first (so it is on the ready queue), then run the
   done-callbacks. */
static void
future_resolve(int64_t h, MojoFuture *f)
{
    __mojo_async_notify_future(h);
    future_fire_callbacks(h, f);
}

int64_t
__mojo_future_new(void)
{
    MojoFuture *f = (MojoFuture *)calloc(1, sizeof *f);
    return (int64_t)(uintptr_t)f;
}

int64_t
__mojo_future_done(int64_t h)
{
    MojoFuture *f = (MojoFuture *)(uintptr_t)h;
    return f && f->done;
}

int64_t
__mojo_future_result(int64_t h)
{
    MojoFuture *f = (MojoFuture *)(uintptr_t)h;
    return f ? f->result : 0;
}

void
__mojo_future_set_result(int64_t h, int64_t val)
{
    MojoFuture *f = (MojoFuture *)(uintptr_t)h;
    if (!f || f->done) return;
    f->done   = 1;
    f->result = val;
    /* Wake every top-level coroutine the scheduler parked on this handle
       (it re-drives its await chain, which re-enters __mojo_async_await_
       future -> now f->done -> returns the result). */
    future_resolve(h, f);
}

/* (1) exception slot -- `fut.set_exception(Exc("msg"))` / `fut.exception()`.
   The codegen hook lowers the argument the same way `raise` does: an
   exception-class name to its _exc_type_id tag, a string message to a
   char*. `exception()` returns the tag (truthy when an exception is set),
   0 otherwise. `await fut` re-raises it on the awaiting coroutine's own
   stack (see __mojo_async_await_future). */
void
__mojo_future_set_exception(int64_t h, int64_t exc_type, char *msg)
{
    MojoFuture *f = (MojoFuture *)(uintptr_t)h;
    if (!f || f->done) return;
    f->done     = 1;
    f->has_exc  = 1;
    f->exc_type = exc_type ? exc_type : _MOJO_EXC_TAG_EXCEPTION;
    f->exc_msg  = msg;
    future_resolve(h, f);
}

int64_t
__mojo_future_exception(int64_t h)
{
    MojoFuture *f = (MojoFuture *)(uintptr_t)h;
    return (f && f->has_exc) ? f->exc_type : 0;
}

/* (2) cancelled state -- `fut.cancel()` / `fut.cancelled()` /
   `fut.set_running_or_notify_cancel()`. cancel() resolves the future
   (returns 1 if it took effect, 0 if it was already resolved);
   `await fut` on a cancelled future raises CancelledError. */
int64_t
__mojo_future_cancel(int64_t h)
{
    MojoFuture *f = (MojoFuture *)(uintptr_t)h;
    if (!f || f->done) return 0;
    f->done      = 1;
    f->cancelled = 1;
    future_resolve(h, f);
    return 1;
}

int64_t
__mojo_future_cancelled(int64_t h)
{
    MojoFuture *f = (MojoFuture *)(uintptr_t)h;
    return f && f->cancelled;
}

/* asyncio semantics: False if the future was cancelled (caller must abort),
   True otherwise. */
int64_t
__mojo_future_set_running_or_notify_cancel(int64_t h)
{
    MojoFuture *f = (MojoFuture *)(uintptr_t)h;
    return f && !f->cancelled;
}

/* (3) done-callback list -- `fut.add_done_callback(cb)` /
   `fut.remove_done_callback(cb)`. Callbacks fire (LIFO) on resolution via
   future_fire_callbacks; `tag` records the callable-value kind -- see
   __mojo_future_invoke_callback for the invocation contract. */
void
__mojo_future_add_done_callback(int64_t h, int64_t cb, int64_t tag)
{
    MojoFuture *f = (MojoFuture *)(uintptr_t)h;
    if (!f) return;
    if (f->done) { __mojo_future_invoke_callback(cb, tag, h); return; }
    MojoFutureCB *node = (MojoFutureCB *)calloc(1, sizeof *node);
    node->cb   = cb;
    node->tag  = tag;
    node->next = f->callbacks;
    f->callbacks = node;
}

/* Identity for removal is the handle value only: `tag` is accepted for a
   uniform 3-arg shim signature but callbacks with the same `cb` are the
   same registration regardless of tag. */
int64_t
__mojo_future_remove_done_callback(int64_t h, int64_t cb, int64_t tag)
{
    (void)tag;
    MojoFuture *f = (MojoFuture *)(uintptr_t)h;
    if (!f) return 0;
    int removed = 0;
    MojoFutureCB **pp = &f->callbacks;
    while (*pp) {
        if ((*pp)->cb == cb) {
            MojoFutureCB *d = *pp;
            *pp = d->next;
            free(d);
            removed++;
        } else {
            pp = &(*pp)->next;
        }
    }
    return removed;
}

/* `await <future>` / `await <event>.wait()` -- called from inside a lowered
   async body with its own __c. Returns the future's result box (0 for an
   Event). If the handle is already done, returns immediately with no
   suspension (matching asyncio). Otherwise forwards a MOJO_WD_FUTURE
   wait-descriptor (payload = the handle) upward -- through every enclosing
   await drive loop, exactly like a SLEEP/READ descriptor -- until it
   reaches mojo_async_sched.c, which records (handle -> outermost coro). */
int64_t
__mojo_async_await_future(int64_t coro, int64_t h)
{
    MojoFuture *f = (MojoFuture *)(uintptr_t)h;
    if (!f) return 0;
    while (!f->done) {
        __mojo_coro_yield_tagged((MojoCoro *)(uintptr_t)coro,
                                 mojo_wd_make(MOJO_WD_FUTURE, h), 1);
    }
    /* Resolved by cancel() / set_exception() -> re-raise on THIS
       coroutine's stack (its body's landing pad catches it, exactly as if
       the body had executed a `raise`). */
    if (f->cancelled) {
        mojo_exc_type_set(_MOJO_EXC_TAG_CANCELLEDERROR);
        mojo_exc_msg_set((char *)"");
        mojo_raise();
    }
    if (f->has_exc) {
        mojo_exc_type_set(f->exc_type);
        mojo_exc_msg_set(f->exc_msg ? f->exc_msg : (char *)"");
        mojo_raise();
    }
    return f->result;
}

/* Event is a Future whose result is ignored and which latches. */
int64_t __mojo_event_new(void)            { return __mojo_future_new(); }
void    __mojo_event_set(int64_t h)       { __mojo_future_set_result(h, 1); }
int64_t __mojo_event_is_set(int64_t h)    { return __mojo_future_done(h); }
void    __mojo_event_clear(int64_t h)
{
    MojoFuture *f = (MojoFuture *)(uintptr_t)h;
    if (f) { f->done = 0; f->result = 0; }
}
int64_t __mojo_async_await_event_wait(int64_t coro, int64_t h)
{
    return __mojo_async_await_future(coro, h);
}
