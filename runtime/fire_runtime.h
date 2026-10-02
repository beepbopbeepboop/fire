#pragma once
#include <stdint.h>
#include <stdio.h>
#include <setjmp.h>
#include <stdlib.h>  /* malloc — mojo_bound_method_new below; fire_runtime.c includes this
                       * header before its own <stdlib.h>, so the header must self-provide it. */

/* Milestone D (compiled-generator exception boundary) is the first thing in
 * this project to #include this header from a real .cpp translation unit
 * (gimple_codegen.py's generated generator .cpp calls mojo_exc_type_get/
 * mojo_exc_msg_get/mojo_exc_obj_get/mojo_exc_pending_get/set at the extern
 * "C" `_resume()` boundary — see that .cpp's own preamble). Without this
 * guard, every declaration below gets C++ (mangled) linkage when included
 * from a .cpp file, while fire_runtime.c itself is always compiled as plain
 * C — a real link failure ("symbol not found ... declaration possibly
 * missing 'extern \"C\"'"), found and fixed via this milestone's own
 * required real compile+link+run verification, not just a syntax-only
 * check (test_gimple.py's `-fsyntax-only` .c/.cpp checks never actually
 * link the two together, so this was invisible there). Verified this
 * header is otherwise already valid, unchanged, plain C++ (no `_Bool`-typed
 * declarations, no C-only syntax) before wrapping it wholesale rather than
 * hand-picking a handful of individual redeclarations (which would need to
 * exactly match every attribute of the header's own declaration anyway, or
 * conflict on language linkage — simplest and most robust to make the
 * WHOLE header C-linkage when seen from C++, once, here). */
#ifdef __cplusplus
extern "C" {
#endif

/* Mojo type aliases */
typedef int mojo_int;
typedef float mojo_float;
typedef char* mojo_string;
typedef void* mojo_any;

static inline uint8_t mojo_uint8_from_int64(int64_t v) { return (uint8_t)v; }
static inline uint16_t mojo_uint16_from_int64(int64_t v) { return (uint16_t)v; }
static inline uint32_t mojo_uint32_from_int64(int64_t v) { return (uint32_t)v; }
static inline uint64_t mojo_uint64_from_int64(int64_t v) { return (uint64_t)v; }
static inline int8_t mojo_int8_from_int64(int64_t v) { return (int8_t)v; }
static inline int16_t mojo_int16_from_int64(int64_t v) { return (int16_t)v; }
static inline int32_t mojo_int32_from_int64(int64_t v) { return (int32_t)v; }
static inline int64_t mojo_int64_from_int64(int64_t v) { return v; }

/* Generic function pointer type (for storing any function as void*) */
typedef void* (*mojo_func_ptr)(void);
typedef void* mojo_generic_func;

/* Sentinel passed as mojo_cstr_slice/mojo_str_slice/mojo_list_slice's `stop`
 * for an omitted upper bound (`s[start:]`) — must be distinguishable from
 * every real (possibly negative) Python slice index, including a literal
 * `s[:-1]`; this value can never arise from `len(s) + stop` for any real
 * string/list, unlike the previous sentinel of plain -1, which collided
 * with `s[:-1]` itself. Deliberately NOT INT64_MIN: that's only expressible
 * as the compound expression `(-9223372036854775807LL-1)` (see stdint.h),
 * and this sentinel gets inlined directly as a GIMPLE call argument — a
 * compound expression there is invalid (the exact class of bug this
 * project hit once already with the char_replace() macro; see
 * gimple_codegen.py's _char_replace_impl comment). A single literal token
 * avoids that entirely while still being an impossible real index. */
#define MOJO_SLICE_STOP_OMITTED -9223372036854775807LL

/* ── Higher-order function dispatch helpers ──────────────────────────────
 * __GIMPLE functions cannot cast-and-call in a single expression, so
 * we call through these small non-GIMPLE helpers that do the cast.
 * All args/returns are widened to int64_t; callers cast as needed.
 * Declared static inline so they generate no external symbol.           */
/* A CLOSING lambda is materialized as a MojoBoundMethod (fn + a heap env)
   rather than a bare function pointer, because the values it reads from the
   enclosing function have nowhere to live in a plain code address. So every
   one of these dispatches on the callee first: a registered bound method
   re-supplies its env as the leading argument, anything else is the bare
   function pointer it has always been. Doing the check HERE rather than at
   each call site is what lets a closing lambda work everywhere an ordinary
   one does — map/filter/sorted keys, a call straight through
   `_funcptr_*`, and a lambda handed to code this compiler never saw. */
/* ── Bound method values ──────────────────────────────────────────────────
 * A method referenced as a plain VALUE (not called immediately) — `f =
 * self.b`, `readline.set_completer(self.complete)` — needs to carry both
 * the method's C function pointer AND the bound `self` receiver as a single
 * first-class value; a bare function pointer alone (mojo_fnptr_call_N above,
 * used for FREE functions stored as values) has nowhere to keep `self`.
 * gimple_codegen.py's _lower_bound_method_value allocates one of these
 * (fn = the method's real, statically-known C symbol; self = the receiver
 * object pointer already in hand at the reference site) and a later call
 * through the stored value goes through mojo_bound_method_call_N, which
 * re-supplies `self` as the method's implicit first argument — the same
 * "self, then N ordinary args" convention every compiled struct method
 * already uses. See bugs/CODEGEN_bound_method_as_value_not_resolved.md. */
typedef struct { void *fn; void *self; } MojoBoundMethod;

/* Real (non-inline) so the single bound-method registry lives in one TU
 * (fire_runtime.c) — mojo_is_bound_method below consults it to tell a
 * `MojoBoundMethod *` value apart from a plain function pointer at a
 * dynamically-dispatched call site (`if c: f = lambda: 1 else: f =
 * self.m; f()`). */
MojoBoundMethod *mojo_bound_method_new(void *fn, void *self);
int mojo_is_bound_method(void *p);

/* ── Variadic callables ───────────────────────────────────────────────────
 * A `lambda *a, **k: ...` (or any function whose real C signature is
 * `(MojoList *, MojoDict *)` rather than N scalars) cannot be called
 * through mojo_fnptr_call_N: that helper is ARITY-based — it casts the
 * callee to `int64_t(*)(int64_t, ...)` and passes the arguments written
 * at the call site positionally. A variadic callee expects them PACKED
 * into a MojoList/MojoDict pair, so the first argument arrives as the
 * integer 4 where a `MojoList *` is wanted and the callee dereferences
 * address 4 — a hard SIGSEGV, not a wrong value.
 *
 * So a variadic callable's VALUE is not a bare function pointer but one
 * of these, which records the signature the call site cannot see. The
 * packing itself stays here in the runtime, which is the only place that
 * knows both the call's arity and the callee's real parameter list — the
 * same reason mojo_fnptr_call_N dispatches on MojoBoundMethod above
 * rather than at each call site.
 *
 *   kind   0 = `*args` only            -> fn(void *self, MojoList *a)
 *          1 = `*args, **kwargs`       -> fn(void *self, MojoList *a, MojoDict *k)
 *          2 = `**kwargs` only         -> fn(void *self, MojoDict *k)
 *   n_fixed  number of ORDINARY leading parameters declared before the
 *           `*args`. Those stay positional (the callee really does take
 *           them as scalars) and are passed straight through; the rest of
 *           the call's arguments are what gets packed into the list.
 *   self    the closure env, or NULL for a non-capturing variadic lambda.
 *   has_env whether the lifted callee actually DECLARES that leading
 *           `self` parameter. It does only when it captures something:
 *           passing `self` to a callee that has no such parameter would
 *           shift every real parameter one slot left, which is a silent
 *           wrong value (a `MojoList *a` parameter receiving the NULL env).
 */
typedef struct { void *fn; void *self; int64_t n_fixed; int64_t kind; int64_t has_env; } MojoVarargFn;

MojoVarargFn *mojo_vararg_fn_new(void *fn, void *self, int64_t n_fixed, int64_t kind,
                                 int64_t has_env);
int mojo_is_vararg_fn(void *p);
/* Packing entry points. `kw` is the call site's keyword arguments already
 * packed into a MojoDict (NULL when the call site passed none); it is
 * IGNORED unless the callee declares `**kwargs`, so an ordinary call site
 * can use the same helper unconditionally. Real (not inline) because they
 * build the MojoList/MojoDict and dispatch on a runtime-recorded kind —
 * fire_runtime.c is the one TU that has all of those declared. */
int64_t mojo_vararg_call_0(void *fp, void *kw);
int64_t mojo_vararg_call_1(void *fp, void *kw, int64_t a);
int64_t mojo_vararg_call_2(void *fp, void *kw, int64_t a, int64_t b);
int64_t mojo_vararg_call_3(void *fp, void *kw, int64_t a, int64_t b, int64_t c);
int64_t mojo_vararg_call_4(void *fp, void *kw, int64_t a, int64_t b, int64_t c, int64_t d);
int64_t mojo_vararg_call_5(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4);
int64_t mojo_vararg_call_6(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5);
int64_t mojo_vararg_call_7(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5, int64_t _a6);
int64_t mojo_vararg_call_8(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5, int64_t _a6, int64_t _a7);

/* The two frees for the two things a bound method can be — `self` belongs to
 * only one of them, so they cannot be one function. `mojo_bound_method_free`
 * is a METHOD taken as a value: the receiver is not ours, only the wrapper,
 * and its `_reg_bound_method` entry MUST be discarded or a later allocation
 * at the same address is dispatched as a bound method (a dangling registry
 * entry, the same shape as the container registries' `_destroy` helpers).
 * `mojo_closure_free` is a CAPTURING LAMBDA, whose `self` is the environment
 * the constructor allocated with it. */
void mojo_bound_method_free(MojoBoundMethod *bm);
void mojo_closure_free(void *bm);
static inline int64_t mojo_bound_method_call_0(MojoBoundMethod *bm) {
    return ((int64_t (*)(void *))bm->fn)(bm->self);
}
static inline int64_t mojo_bound_method_call_1(MojoBoundMethod *bm, int64_t a) {
    return ((int64_t (*)(void *, int64_t))bm->fn)(bm->self, a);
}
static inline int64_t mojo_bound_method_call_2(MojoBoundMethod *bm, int64_t a, int64_t b) {
    return ((int64_t (*)(void *, int64_t, int64_t))bm->fn)(bm->self, a, b);
}
static inline int64_t mojo_bound_method_call_3(MojoBoundMethod *bm, int64_t a, int64_t b, int64_t c) {
    return ((int64_t (*)(void *, int64_t, int64_t, int64_t))bm->fn)(bm->self, a, b, c);
}
static inline int64_t mojo_bound_method_call_4(MojoBoundMethod *bm, int64_t a, int64_t b, int64_t c, int64_t d) {
    return ((int64_t (*)(void *, int64_t, int64_t, int64_t, int64_t))bm->fn)(bm->self, a, b, c, d);
}

static inline int64_t mojo_bound_method_call_5(MojoBoundMethod *bm, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4) {
    return ((int64_t (*)(void *, int64_t, int64_t, int64_t, int64_t, int64_t))bm->fn)(bm->self, _a0, _a1, _a2, _a3, _a4);
}

static inline int64_t mojo_bound_method_call_6(MojoBoundMethod *bm, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5) {
    return ((int64_t (*)(void *, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t))bm->fn)(bm->self, _a0, _a1, _a2, _a3, _a4, _a5);
}

static inline int64_t mojo_bound_method_call_7(MojoBoundMethod *bm, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5, int64_t _a6) {
    return ((int64_t (*)(void *, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t))bm->fn)(bm->self, _a0, _a1, _a2, _a3, _a4, _a5, _a6);
}

static inline int64_t mojo_bound_method_call_8(MojoBoundMethod *bm, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5, int64_t _a6, int64_t _a7) {
    return ((int64_t (*)(void *, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t))bm->fn)(bm->self, _a0, _a1, _a2, _a3, _a4, _a5, _a6, _a7);
}










static inline int64_t mojo_fnptr_call_0(void *fp) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_0(fp, 0);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_0((MojoBoundMethod *)fp);
    return ((int64_t (*)(void))fp)();
}
static inline int64_t mojo_fnptr_call_1(void *fp, int64_t a) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_1(fp, 0, a);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_1((MojoBoundMethod *)fp, a);
    return ((int64_t (*)(int64_t))fp)(a);
}
static inline int64_t mojo_fnptr_call_2(void *fp, int64_t a, int64_t b) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_2(fp, 0, a, b);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_2((MojoBoundMethod *)fp, a, b);
    return ((int64_t (*)(int64_t, int64_t))fp)(a, b);
}
static inline int64_t mojo_fnptr_call_3(void *fp, int64_t a, int64_t b, int64_t c) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_3(fp, 0, a, b, c);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_3((MojoBoundMethod *)fp, a, b, c);
    return ((int64_t (*)(int64_t, int64_t, int64_t))fp)(a, b, c);
}
static inline int64_t mojo_fnptr_call_4(void *fp, int64_t a, int64_t b, int64_t c, int64_t d) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_4(fp, 0, a, b, c, d);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_4((MojoBoundMethod *)fp, a, b, c, d);
    return ((int64_t (*)(int64_t, int64_t, int64_t, int64_t))fp)(a, b, c, d);
}

static inline int64_t mojo_fnptr_call_5(void *fp, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_5(fp, 0, _a0, _a1, _a2, _a3, _a4);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_5((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4);
    return ((int64_t (*)(int64_t, int64_t, int64_t, int64_t, int64_t))fp)(_a0, _a1, _a2, _a3, _a4);
}

static inline int64_t mojo_fnptr_call_6(void *fp, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_6(fp, 0, _a0, _a1, _a2, _a3, _a4, _a5);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_6((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4, _a5);
    return ((int64_t (*)(int64_t, int64_t, int64_t, int64_t, int64_t, int64_t))fp)(_a0, _a1, _a2, _a3, _a4, _a5);
}

static inline int64_t mojo_fnptr_call_7(void *fp, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5, int64_t _a6) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_7(fp, 0, _a0, _a1, _a2, _a3, _a4, _a5, _a6);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_7((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4, _a5, _a6);
    return ((int64_t (*)(int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t))fp)(_a0, _a1, _a2, _a3, _a4, _a5, _a6);
}

static inline int64_t mojo_fnptr_call_8(void *fp, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5, int64_t _a6, int64_t _a7) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_8(fp, 0, _a0, _a1, _a2, _a3, _a4, _a5, _a6, _a7);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_8((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4, _a5, _a6, _a7);
    return ((int64_t (*)(int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t))fp)(_a0, _a1, _a2, _a3, _a4, _a5, _a6, _a7);
}









/* The same dispatch, for a call site that PASSES KEYWORD ARGUMENTS. A
 * callee that declares no `**kwargs` must not see them (real Python binds
 * them to named parameters, which needs a signature this value does not
 * carry — see the mojo_vararg_call_N comment), so the packed dict is
 * handed to the vararg path and dropped by the bound-method / bare-fnptr
 * paths, exactly as the pre-keyword helpers dropped it. */
static inline int64_t mojo_fnptr_call_kw_0(void *fp, void *kw) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_0(fp, kw);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_0((MojoBoundMethod *)fp);
    return ((int64_t (*)(void))fp)();
}
static inline int64_t mojo_fnptr_call_kw_1(void *fp, void *kw, int64_t a) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_1(fp, kw, a);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_1((MojoBoundMethod *)fp, a);
    return ((int64_t (*)(int64_t))fp)(a);
}
static inline int64_t mojo_fnptr_call_kw_2(void *fp, void *kw, int64_t a, int64_t b) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_2(fp, kw, a, b);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_2((MojoBoundMethod *)fp, a, b);
    return ((int64_t (*)(int64_t, int64_t))fp)(a, b);
}
static inline int64_t mojo_fnptr_call_kw_3(void *fp, void *kw, int64_t a, int64_t b, int64_t c) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_3(fp, kw, a, b, c);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_3((MojoBoundMethod *)fp, a, b, c);
    return ((int64_t (*)(int64_t, int64_t, int64_t))fp)(a, b, c);
}
static inline int64_t mojo_fnptr_call_kw_4(void *fp, void *kw, int64_t a, int64_t b, int64_t c, int64_t d) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_4(fp, kw, a, b, c, d);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_4((MojoBoundMethod *)fp, a, b, c, d);
    return ((int64_t (*)(int64_t, int64_t, int64_t, int64_t))fp)(a, b, c, d);
}

static inline int64_t mojo_fnptr_call_kw_5(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_5(fp, kw, _a0, _a1, _a2, _a3, _a4);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_5((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4);
    return ((int64_t (*)(int64_t, int64_t, int64_t, int64_t, int64_t))fp)(_a0, _a1, _a2, _a3, _a4);
}

static inline int64_t mojo_fnptr_call_kw_6(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_6(fp, kw, _a0, _a1, _a2, _a3, _a4, _a5);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_6((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4, _a5);
    return ((int64_t (*)(int64_t, int64_t, int64_t, int64_t, int64_t, int64_t))fp)(_a0, _a1, _a2, _a3, _a4, _a5);
}

static inline int64_t mojo_fnptr_call_kw_7(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5, int64_t _a6) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_7(fp, kw, _a0, _a1, _a2, _a3, _a4, _a5, _a6);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_7((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4, _a5, _a6);
    return ((int64_t (*)(int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t))fp)(_a0, _a1, _a2, _a3, _a4, _a5, _a6);
}

static inline int64_t mojo_fnptr_call_kw_8(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5, int64_t _a6, int64_t _a7) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_8(fp, kw, _a0, _a1, _a2, _a3, _a4, _a5, _a6, _a7);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_8((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4, _a5, _a6, _a7);
    return ((int64_t (*)(int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t))fp)(_a0, _a1, _a2, _a3, _a4, _a5, _a6, _a7);
}









/* The `double`-returning twin of each helper above. A callee whose real
 * return type is `double` cannot be called through an `int64_t (*)(...)`
 * cast and have the value survive: it comes back in an SSE register, not
 * the general-purpose one the `int64_t` return reads, so the bits are
 * whatever the ABI happened to leave there (measured: `d = lambda: 1.5;
 * print(d())` printed 2.1393696074e-314). These are the same helpers with
 * the real return type, so the call is well-typed and the value arrives.
 * The codegen picks them only when it knows the callee returns a double —
 * see `_lower_fnptr_call_value`. */
static inline double mojo_fnptr_call_d0(void *fp) {
    if (mojo_is_bound_method(fp)) return (double)mojo_bound_method_call_0((MojoBoundMethod *)fp);
    return ((double (*)(void))fp)();
}
static inline double mojo_fnptr_call_d1(void *fp, int64_t a) {
    if (mojo_is_bound_method(fp)) return (double)mojo_bound_method_call_1((MojoBoundMethod *)fp, a);
    return ((double (*)(int64_t))fp)(a);
}
static inline double mojo_fnptr_call_d2(void *fp, int64_t a, int64_t b) {
    if (mojo_is_bound_method(fp)) return (double)mojo_bound_method_call_2((MojoBoundMethod *)fp, a, b);
    return ((double (*)(int64_t, int64_t))fp)(a, b);
}
static inline double mojo_fnptr_call_d3(void *fp, int64_t a, int64_t b, int64_t c) {
    if (mojo_is_bound_method(fp)) return (double)mojo_bound_method_call_3((MojoBoundMethod *)fp, a, b, c);
    return ((double (*)(int64_t, int64_t, int64_t))fp)(a, b, c);
}
static inline double mojo_fnptr_call_d4(void *fp, int64_t a, int64_t b, int64_t c, int64_t d) {
    if (mojo_is_bound_method(fp)) return (double)mojo_bound_method_call_4((MojoBoundMethod *)fp, a, b, c, d);
    return ((double (*)(int64_t, int64_t, int64_t, int64_t))fp)(a, b, c, d);
}

/* Dynamic dispatch through a value that may be EITHER a MojoBoundMethod*
 * or a plain function pointer — the callee identity isn't known
 * statically (a local branch-joined from `lambda`/free-function and a
 * `self.method` value). A registered bound method re-supplies its
 * receiver via mojo_bound_method_call_N; anything else is a bare fnptr. */
static inline int64_t mojo_maybe_bound_call_0(void *f) {
    if (mojo_is_vararg_fn(f)) return mojo_vararg_call_0(f, 0);
    if (mojo_is_bound_method(f)) return mojo_bound_method_call_0((MojoBoundMethod *)f);
    return mojo_fnptr_call_0(f);
}
static inline int64_t mojo_maybe_bound_call_1(void *f, int64_t a) {
    if (mojo_is_vararg_fn(f)) return mojo_vararg_call_1(f, 0, a);
    if (mojo_is_bound_method(f)) return mojo_bound_method_call_1((MojoBoundMethod *)f, a);
    return mojo_fnptr_call_1(f, a);
}
static inline int64_t mojo_maybe_bound_call_2(void *f, int64_t a, int64_t b) {
    if (mojo_is_vararg_fn(f)) return mojo_vararg_call_2(f, 0, a, b);
    if (mojo_is_bound_method(f)) return mojo_bound_method_call_2((MojoBoundMethod *)f, a, b);
    return mojo_fnptr_call_2(f, a, b);
}
static inline int64_t mojo_maybe_bound_call_3(void *f, int64_t a, int64_t b, int64_t c) {
    if (mojo_is_vararg_fn(f)) return mojo_vararg_call_3(f, 0, a, b, c);
    if (mojo_is_bound_method(f)) return mojo_bound_method_call_3((MojoBoundMethod *)f, a, b, c);
    return mojo_fnptr_call_3(f, a, b, c);
}
static inline int64_t mojo_maybe_bound_call_4(void *f, int64_t a, int64_t b, int64_t c, int64_t d) {
    if (mojo_is_vararg_fn(f)) return mojo_vararg_call_4(f, 0, a, b, c, d);
    if (mojo_is_bound_method(f)) return mojo_bound_method_call_4((MojoBoundMethod *)f, a, b, c, d);
    return mojo_fnptr_call_4(f, a, b, c, d);
}

static inline int64_t mojo_maybe_bound_call_5(void *fp, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_5(fp, 0, _a0, _a1, _a2, _a3, _a4);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_5((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4);
    return mojo_fnptr_call_5(fp, _a0, _a1, _a2, _a3, _a4);
}

static inline int64_t mojo_maybe_bound_call_6(void *fp, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_6(fp, 0, _a0, _a1, _a2, _a3, _a4, _a5);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_6((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4, _a5);
    return mojo_fnptr_call_6(fp, _a0, _a1, _a2, _a3, _a4, _a5);
}

static inline int64_t mojo_maybe_bound_call_7(void *fp, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5, int64_t _a6) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_7(fp, 0, _a0, _a1, _a2, _a3, _a4, _a5, _a6);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_7((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4, _a5, _a6);
    return mojo_fnptr_call_7(fp, _a0, _a1, _a2, _a3, _a4, _a5, _a6);
}

static inline int64_t mojo_maybe_bound_call_8(void *fp, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5, int64_t _a6, int64_t _a7) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_8(fp, 0, _a0, _a1, _a2, _a3, _a4, _a5, _a6, _a7);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_8((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4, _a5, _a6, _a7);
    return mojo_fnptr_call_8(fp, _a0, _a1, _a2, _a3, _a4, _a5, _a6, _a7);
}









/* Keyword-argument twin of the mojo_maybe_bound_call_N family, for a local
 * branch-joined from a variadic lambda and something else that is called
 * WITH keywords. Same rule as mojo_fnptr_call_kw_N: the packed dict reaches
 * the vararg path (whose callee declares `**kwargs`) and is dropped by the
 * bound-method / bare-fnptr paths. */
static inline int64_t mojo_maybe_bound_call_kw_0(void *f, void *kw) {
    if (mojo_is_vararg_fn(f)) return mojo_vararg_call_0(f, kw);
    if (mojo_is_bound_method(f)) return mojo_bound_method_call_0((MojoBoundMethod *)f);
    return mojo_fnptr_call_kw_0(f, kw);
}
static inline int64_t mojo_maybe_bound_call_kw_1(void *f, void *kw, int64_t a) {
    if (mojo_is_vararg_fn(f)) return mojo_vararg_call_1(f, kw, a);
    if (mojo_is_bound_method(f)) return mojo_bound_method_call_1((MojoBoundMethod *)f, a);
    return mojo_fnptr_call_kw_1(f, kw, a);
}
static inline int64_t mojo_maybe_bound_call_kw_2(void *f, void *kw, int64_t a, int64_t b) {
    if (mojo_is_vararg_fn(f)) return mojo_vararg_call_2(f, kw, a, b);
    if (mojo_is_bound_method(f)) return mojo_bound_method_call_2((MojoBoundMethod *)f, a, b);
    return mojo_fnptr_call_kw_2(f, kw, a, b);
}
static inline int64_t mojo_maybe_bound_call_kw_3(void *f, void *kw, int64_t a, int64_t b, int64_t c) {
    if (mojo_is_vararg_fn(f)) return mojo_vararg_call_3(f, kw, a, b, c);
    if (mojo_is_bound_method(f)) return mojo_bound_method_call_3((MojoBoundMethod *)f, a, b, c);
    return mojo_fnptr_call_kw_3(f, kw, a, b, c);
}
static inline int64_t mojo_maybe_bound_call_kw_4(void *f, void *kw, int64_t a, int64_t b, int64_t c, int64_t d) {
    if (mojo_is_vararg_fn(f)) return mojo_vararg_call_4(f, kw, a, b, c, d);
    if (mojo_is_bound_method(f)) return mojo_bound_method_call_4((MojoBoundMethod *)f, a, b, c, d);
    return mojo_fnptr_call_kw_4(f, kw, a, b, c, d);
}

static inline int64_t mojo_maybe_bound_call_kw_5(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_5(fp, kw, _a0, _a1, _a2, _a3, _a4);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_5((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4);
    return mojo_fnptr_call_kw_5(fp, kw, _a0, _a1, _a2, _a3, _a4);
}

static inline int64_t mojo_maybe_bound_call_kw_6(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_6(fp, kw, _a0, _a1, _a2, _a3, _a4, _a5);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_6((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4, _a5);
    return mojo_fnptr_call_kw_6(fp, kw, _a0, _a1, _a2, _a3, _a4, _a5);
}

static inline int64_t mojo_maybe_bound_call_kw_7(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5, int64_t _a6) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_7(fp, kw, _a0, _a1, _a2, _a3, _a4, _a5, _a6);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_7((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4, _a5, _a6);
    return mojo_fnptr_call_kw_7(fp, kw, _a0, _a1, _a2, _a3, _a4, _a5, _a6);
}

static inline int64_t mojo_maybe_bound_call_kw_8(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5, int64_t _a6, int64_t _a7) {
    if (mojo_is_vararg_fn(fp)) return mojo_vararg_call_8(fp, kw, _a0, _a1, _a2, _a3, _a4, _a5, _a6, _a7);
    if (mojo_is_bound_method(fp)) return mojo_bound_method_call_8((MojoBoundMethod *)fp, _a0, _a1, _a2, _a3, _a4, _a5, _a6, _a7);
    return mojo_fnptr_call_kw_8(fp, kw, _a0, _a1, _a2, _a3, _a4, _a5, _a6, _a7);
}










/* ── Exception stack (for try/except/raise) ──────────────────────────────
 * setjmp is emitted directly in generated functions (see gimple_codegen).
 * mojo_exc_pop / mojo_raise are real functions (no setjmp, safe to wrap). */
#define MOJO_EXC_STACK_MAX 64
extern jmp_buf _mojo_exc_stack[MOJO_EXC_STACK_MAX];
extern int     _mojo_exc_top;
/* Pop the topmost exception frame. */
void mojo_exc_pop(void);
/* Raise (longjmp to current frame). */
void mojo_raise(void);
/* Exception message slot (optional string payload for raise). */
extern char *_mojo_exc_msg;
void        mojo_exc_msg_set(char *msg);
char *mojo_exc_msg_get(void);

/* Exception object slot (for typed exceptions like ReturnValue). */
extern void *_mojo_exc_obj;
void        mojo_exc_obj_set(void *obj);
void *      mojo_exc_obj_get(void);

/* Exception type tag (see fire_runtime.c for the dispatch rationale). */
extern int64_t _mojo_exc_type;
void    mojo_exc_type_set(int64_t type_id);
int64_t mojo_exc_type_get(void);

/* ── Cleanup-thunk registry (doc/OWNERSHIP_MODEL.md, exception-handling
 * option 2) ──────────────────────────────────────────────────────────────
 * `mojo_raise`'s `longjmp` skips every C statement between the raise site
 * and the catching try's `setjmp` — including any `mojo_*_free` call
 * gimple_gen_infra.py's Phase 3 wiring emitted for an owned local, since
 * those live at the function's return/fallthrough points, not on the
 * exception path. This registry is a userland reimplementation of what a
 * real unwinder's landing pads give for free: codegen pushes a thunk right
 * after constructing an owned local eligible for Phase-3 freeing, and
 * cancels it (without invoking) right at the same free call it already
 * emits on the normal path. `mojo_raise` walks and invokes every thunk
 * still live back down to the catching try's checkpoint before it
 * longjmps, so an owned local created here-or-in-a-callee is freed exactly
 * once, on whichever path (normal or exceptional) actually runs. */
extern int _mojo_cleanup_top;
void mojo_cleanup_push_dict(void *p);
void mojo_cleanup_push_list(void *p);
void mojo_cleanup_push_set(void *p);
/* Stack-allocated variants (doc/OWNERSHIP_MODEL.md Phase 6) -- an
 * exception unwinding past this thunk calls `mojo_*_destroy` (buffer-only
 * teardown), never `mojo_*_free` (which would `free()` a stack address). */
void mojo_cleanup_push_dict_stack(void *p);
void mojo_cleanup_push_list_stack(void *p);
void mojo_cleanup_push_set_stack(void *p);
void mojo_cleanup_push_ptr(void *p);   /* a struct instance: unwinding free()s the block */
/* A list that SOLELY owns its string elements (every one freshly allocated by
 * the runtime function that built it) — see mojo_list_free_owned_strs. A
 * list of strings is usually BORROWED, so this is chosen by the owner, never
 * inferred from the list's element type. */
void mojo_cleanup_push_list_strs(void *p);
/* A closure's bound method and its environment are one allocation unit; this
 * is the unwind thunk that frees both (see mojo_closure_free). */
void mojo_cleanup_push_closure(void *p);
/* Pop the `n` most-recently-pushed thunks WITHOUT invoking them -- call
 * immediately at a point that is itself about to (or just did) free those
 * same `n` locals inline. */
void mojo_cleanup_cancel_n(int64_t n);
/* Snapshot the current cleanup-stack depth as the level `_mojo_exc_top`
 * (already incremented) should unwind back down to. Call immediately
 * after bumping `_mojo_exc_top` for a new try/except level, before its
 * `setjmp`. */
void mojo_cleanup_checkpoint_save(void);

/* ── Compiled-generator (C++20 coroutine) exception boundary ─────────────
 * A coroutine body can't use setjmp/longjmp directly (the C stack frame
 * that ran setjmp() no longer exists once the coroutine has suspended by
 * returning to its caller once) -- see gimple_codegen.py's _cpp_stmt
 * TryStmt/RaiseStmt lowering. Instead, raise/try/except INSIDE a compiled
 * generator's .cpp body use real C++ exceptions, confined to that one
 * translation unit; an exception that escapes uncaught out of the whole
 * coroutine body is caught once, at the extern "C" `<base>_resume()`
 * boundary (a plain, never-suspended function call, so it's always
 * running on an ordinary live C stack frame), and translated into these
 * SAME mojo_exc_type/msg/obj slots above.
 *
 * `_resume()` still just returns a `_Bool` "did this produce a value"
 * flag, and returning false is otherwise ambiguous between "the generator
 * is genuinely exhausted" and "the generator's body raised, uncaught, and
 * unwound the whole coroutine" -- this flag disambiguates the two. Every
 * ordinary (never-suspended) consumer of a compiled generator's `_resume`
 * (a `for` loop, `next()`, or another generator's own `yield from`
 * delegation loop -- see gimple_codegen.py's _gen_for_generator_iter /
 * next() lowering / _cpp_yield_from) checks this flag immediately after
 * `_resume` reports false, and if set, propagates for real: ordinary
 * GIMPLE C code calls mojo_raise() itself (safe -- that call site was
 * never suspended, so the longjmp only ever crosses ordinary, live C
 * frames); a `yield from` delegation loop re-throws a fresh C++ exception
 * built from these same slots, so the exception keeps propagating as a
 * real C++ exception through any further-nested coroutine frames instead
 * of ever longjmp-ing across one. */
extern int _mojo_exc_pending;
void mojo_exc_pending_set(int v);
int  mojo_exc_pending_get(void);

/* ── List ─────────────────────────────────────────────────────────────────
 * Flat dynamic array of int64_t slots.  Doubles are stored as bit-casts;
 * string pointers are stored as uintptr_t casts (64-bit only).           */
/* Small-buffer storage: `data` points at `inl` (inside the struct itself)
 * until the list outgrows MOJO_LIST_INLINE elements, so a short list — the
 * overwhelmingly common case — never calls malloc, whether the struct lives
 * on the stack (a Phase-6 stack-homed local) or on the heap (mojo_list_new:
 * one allocation instead of two). Invariants every list function relies on:
 *   - `data` is NEVER NULL after init, and `cap >= MOJO_LIST_INLINE`;
 *   - `data == inl` iff the elements are still in the inline buffer, and only
 *     then must the buffer NOT be free()d or realloc()ed — the sole places
 *     that distinguish the two are _list_grow and mojo_list_destroy;
 *   - the struct must not be copied or moved by value while `data == inl`
 *     (the copy's `data` would point into the original). No code does; a
 *     MojoList is only ever used through a `MojoList *`. */
#define MOJO_LIST_INLINE 4
typedef struct {
    int64_t *data;
    int64_t  len;
    int64_t  cap;
    int64_t  inl[MOJO_LIST_INLINE];
} MojoList;

MojoList *mojo_list_new(void);
int mojo_is_registered_list(int64_t addr);
int mojo_boxed_is_str(int64_t v);
int mojo_is_registered_dict(int64_t addr);
/* Set-shaped sibling of the list/dict registries — see mojo_set_new. */
int mojo_is_registered_set(int64_t addr);
/* `x in <boxed container>`: resolves list/dict/set at runtime instead of
 * the old hardcoded-false fallback. See mojo_in_dispatch_str's definition. */
int mojo_in_dispatch_str(int64_t container, char *needle);
int mojo_in_dispatch_int(int64_t container, int64_t needle);
void mojo_mark_as_tuple(MojoList *l);
int mojo_is_tuple(MojoList *l);
/* Per-slot element kinds (see the MojoList comment above for why a flat
 * int64_t array cannot carry one). `kinds` is one byte per slot, from
 * 'i' int / 'd' double / 's' bytes / 'p' str / 'l' nested list / 'n' None,
 * and must outlive the list it describes (a `struct` format's compiled
 * field, or a codegen string-pool constant — never a temporary). Passing
 * NULL clears. A list that never had kinds costs one failed probe per
 * read and nothing anywhere else.
 * `mojo_list_slot_kind` answers 'i' for any slot this does not describe,
 * which is the same answer the int accessor would have given.
 * `mojo_list_inherit_kinds` is what every list->list copy calls, so
 * `list(t)` / `t[:]` / `t + t` of a heterogeneous list stay describable. */
void        mojo_list_set_kinds(MojoList *l, const char *kinds);
const char *mojo_list_get_kinds(MojoList *l);
char        mojo_list_slot_kind(MojoList *l, int64_t i);
void        mojo_list_inherit_kinds(MojoList *dst, MojoList *src);
/* The per-slot kind alphabet, as named constants. A MojoList slot is a raw
 * int64_t, so anything that ORDERS a list (mojo_list_sort) or READS one has
 * to be told what a slot holds — comparing the slots as integers orders a
 * list of strings by ADDRESS, which is non-deterministic across runs and
 * different from Python's alphabetical order. The call site passes what its
 * own element-type inference knows; the constants are here so the generated
 * C reads `mojo_list_sort (l, MOJO_KIND_STR, 0, 0)` instead of a bare
 * `'p'`, and so a new kind has one definition. */
#define MOJO_KIND_INT     'i'   /* int64_t (and bool, and None) */
#define MOJO_KIND_DOUBLE  'd'
#define MOJO_KIND_BYTES   's'
#define MOJO_KIND_STR     'p'
#define MOJO_KIND_LIST    'l'   /* nested container: not totally ordered */
#define MOJO_KIND_NONE    'n'
/* A read whose slot index is not known at compile time (`for x in
 * struct.unpack('<if', buf)`, `t[i]`) has to land in ONE C type, and for a
 * heterogeneous list no single accessor is right for every slot. This
 * returns the raw word for every slot that is not a float, and the ADDRESS
 * OF A BOX for a float slot — so the int64_t it returns is the box's, and
 * `mojo_is_boxed` is how a consumer tells the two apart. `mojo_box_double`
 * and `mojo_box_int` read a box (each returns the input unchanged if it is
 * not one), and `mojo_repr_boxed` is the whole resolution in one call for a
 * value that is only going to be printed. Boxes are cached per (list, slot),
 * so a loop boxes each slot once, and the cache is released with the list. */
int64_t     mojo_list_get_boxed(MojoList *l, int64_t i);
int         mojo_is_boxed(int64_t v);
double      mojo_box_double(int64_t v);
int64_t     mojo_box_int(int64_t v);
char       *mojo_repr_boxed(int64_t v);
void      mojo_list_free(MojoList *l);
/* A list that SOLELY owns its string elements: frees every element as a
 * `char *` and then the list. NOT the default free for a list of strings —
 * `mojo_list_append_str` borrows, so the elements of a list built by
 * `extend`, or read out of a dict, are somebody else's. Only the owner may
 * choose this; see mojo/backend_gimple/emit_infra.py's `_OWNS_STR_ELEMS`. */
void      mojo_list_free_owned_strs(MojoList *l);
/* mojo_list_init/mojo_list_destroy: the in-place halves of mojo_list_new/
 * mojo_list_free, for a stack-declared MojoList (doc/OWNERSHIP_MODEL.md
 * Phase 6) -- init/destroy never touch the MojoList* itself with
 * malloc/free, only its `data` buffer and registry membership. */
void      mojo_list_init(MojoList *l);
void      mojo_list_destroy(MojoList *l);

void    mojo_list_append_int(MojoList *l, int64_t v);
void    mojo_list_append_double(MojoList *l, double v);
void    mojo_list_append_str(MojoList *l, const char *v);

int64_t mojo_list_get_int(MojoList *l, int64_t i);
double  mojo_list_get_double(MojoList *l, int64_t i);

/* A double travels as its IEEE-754 BITS inside an int64_t — a list slot, a
 * box, or the int64_t the homogenized `mojo_fnptr_call_N` helpers return for
 * a callable value. The one definition of the conversion in each direction.
 * `mojo_double_from_bits` must not be written as a C cast: `(double)bits` is
 * the bits' NUMERIC value, not the double they encode. */
double  mojo_double_from_bits(int64_t bits);
int64_t mojo_double_to_bits(double v);

int64_t mojo_list_len(MojoList *l);

int mojo_list_contains_int(MojoList *l, int64_t v);
int mojo_list_contains_double(MojoList *l, double v);
int mojo_list_contains_str(MojoList *l, char *v);
/* `l.count(x)` — occurrence COUNT, not membership; see each definition.
 * The bytes needle is declared down at the MojoBytes block, which is where
 * that type is first defined. */
int64_t   mojo_list_count_int(MojoList *l, int64_t v);
int64_t   mojo_list_count_str(MojoList *l, char *v);

/* Item mutation and extra accessors */
void     mojo_list_set_int(MojoList *l, int64_t i, int64_t v);
void     mojo_list_insert_int(MojoList *l, int64_t i, int64_t v);
void     mojo_list_insert_double(MojoList *l, int64_t i, double v);
void     mojo_list_insert_str(MojoList *l, int64_t i, char *v);
void     mojo_list_set_double(MojoList *l, int64_t i, double v);
void     mojo_list_set_str(MojoList *l, int64_t i, char *v);
char    *mojo_list_get_str(MojoList *l, int64_t i);
MojoList*mojo_list_slice(MojoList *l, int64_t start, int64_t stop);
void     mojo_list_del_slice(MojoList *l, int64_t start, int64_t stop);
void     mojo_list_splice(MojoList *l, int64_t start, int64_t stop, MojoList *repl);
void     mojo_list_assign_step(MojoList *l, int has_start, int64_t start,
                               int has_stop, int64_t stop, int64_t step,
                               MojoList *repl);
MojoList*mojo_list_concat(MojoList *a, MojoList *b);
MojoList*mojo_list_repeat(MojoList *l, int64_t n);
void mojo_list_print(MojoList *l);

/* ── String ───────────────────────────────────────────────────────────────*/
typedef struct {
    char    *data;
    int64_t  len;
} MojoStr;

MojoStr    *mojo_str_new(char *s);
void        mojo_str_free(MojoStr *s);
MojoStr    *mojo_str_concat(MojoStr *a, MojoStr *b);
int64_t     mojo_str_len(MojoStr *s);
char *mojo_str_data(MojoStr *s);
int         mojo_str_eq(MojoStr *a, MojoStr *b);
char        mojo_str_char_at(MojoStr *s, int64_t i);
void        mojo_str_print(MojoStr *s);
char       *mojo_char_to_str(char c);
char       *mojo_char_at_str(char *s, int64_t i);   /* s[i] as a 1-char str */
int64_t     mojo_ord(char *s);
char       *mojo_chr(int64_t code);

/* New string operations */
MojoStr    *mojo_str_slice(MojoStr *s, int64_t start, int64_t stop);
char       *mojo_cstr_slice(char *s, int64_t start, int64_t stop);
char       *mojo_cstr_reverse(char *s);        /* reversed(<str>) */
/* `s[start:stop] == needle` / `!= needle` without ever materializing the
 * slice - see mojo_cstr_region_eq's comment in fire_runtime.c for why this
 * exists (a real, profiled hot path: mojo_compiler.py's own self-hosted
 * tokenizer scanning for a closing triple-quote does exactly this, once per
 * character scanned, and was spending ~90% of total runtime in
 * mojo_cstr_slice's malloc+memcpy just to immediately strcmp-and-discard). */
int         mojo_cstr_region_eq(char *s, int64_t start, int64_t stop, char *needle);
MojoStr    *mojo_str_from_char(char c);
MojoStr    *mojo_str_repeat(MojoStr *s, int64_t n);
int64_t     mojo_str_to_int(MojoStr *s);
double      mojo_str_to_float(MojoStr *s);

/* String method operations on char* */
int mojo_str_startswith(char *s, char *prefix);
int mojo_str_isalnum(char *s);
int mojo_str_isdigit(char *s);
int mojo_str_isalpha(char *s);
int mojo_str_isspace(char *s);
int mojo_str_isupper(char *s);
int mojo_str_islower(char *s);
/* The remaining str.isX() predicates CPython defines on `str` but NOT on
 * `bytes` (see mojo_bytes_is's header comment for why the two sets
 * differ). All ten go through ONE kernel (mojo_is_kind in
 * fire_runtime.c) so the str and bytes answers cannot drift apart. */
int mojo_str_istitle(char *s);
int mojo_str_isascii(char *s);
int mojo_str_isprintable(char *s);
int mojo_str_isnumeric(char *s);
int mojo_str_endswith(char *s, char *suffix);
int mojo_str_startswith_char(char *s, char c);
int mojo_str_endswith_char(char *s, char c);
int mojo_cstr_cmp(char *a, char *b);
int mojo_str_contains(char *haystack, char *needle);
int64_t mojo_str_find(char *s, char *needle);
int64_t mojo_str_rfind(char *s, char *needle);
int64_t mojo_str_find_from(char *s, char *needle, int64_t start);
MojoList *mojo_str_split(char *s, char *sep);
MojoList *mojo_str_splitlines(char *s);
int64_t mojo_str_count(char *s, char *sub);
MojoList *mojo_str_rsplit(char *s, char *sep, int64_t maxsplit);
MojoList *mojo_str_partition(char *s, char *sep);
MojoList *mojo_str_rpartition(char *s, char *sep);
char *mojo_c_getenv(char *name);

int mojo_truthy_cstr(char *s);
int64_t mojo_strlen(char *s);
int64_t mojo_utf8_codepoint_index(char *s, int64_t byte_offset);
char *mojo_platform_system(void);
char *mojo_platform_machine(void);
char *mojo_stdin_read(void);
/* `sys.stdout.write(s)` / `sys.stderr.write(s)` / `sys.stdin.write(s)`.
 * `sys.stdout` is a POSIX fd (1) boxed as an opaque handle — see
 * emit_exprs.py's sys-stream case for why that representation was chosen
 * — so a `.write()` on it has to be resolved against the fd, not against
 * a FILE*. Lowered by ast_rewriter.py's `sys_stdout_write` /
 * `sys_stderr_write` / `sys_stdin_write` rules, which is what the
 * `sys.stdin.read()` rule above already does for reads: there is no
 * Python file-object model here, and without these the call fell through
 * to the generic unknown-method stub, which emitted `int_write(1, s)` —
 * treating the integer 1 as a `FILE *` and faulting inside fputs.
 * `fd` is validated, so a handle that is not 0/1/2 is a no-op rather
 * than a wild write(2). */
void mojo_stream_write(int64_t fd, char *s);

/* ── bytes ──────────────────────────────────────────────────────────────
 * Immutable byte string.  Heap value passed as `MojoBytes *` across the C
 * boundary, exactly like MojoStr/MojoList.  `data` is NOT
 * NUL-significant — it may contain embedded 0 bytes; always use `len`.
 * `data` is over-allocated by one trailing NUL purely so debug prints and
 * accidental char* reads don't run off the end.
 * `readonly` records MUTABILITY, not the view question: 1 for every
 * `bytes` object, 0 for a `bytearray`. It exists because `bytearray`
 * shares this struct, so with nothing in the C type to tell the two
 * apart a `memoryview` built over one could not answer `.readonly`
 * (CPython: True over bytes, False over a bytearray) without guessing.
 * Set once, at construction — every bytearray mutator keeps it 0, and no
 * bytes operation ever flips it back. */
typedef struct {
    uint8_t *data;
    int64_t  len;
    int      readonly;
} MojoBytes;

MojoBytes *mojo_bytes_new_lit(const char *data, int64_t len); /* copies `len` bytes */
/* `x in <list of bytes>`: elements are boxed MojoBytes * pointers, so plain
 * mojo_list_contains_int would compare POINTER identity instead of `==`. */
int          mojo_list_contains_bytes(MojoList *l, MojoBytes *v);
int64_t      mojo_list_count_bytes(MojoList *l, MojoBytes *v);
MojoBytes *mojo_bytes_empty(void);
MojoBytes *mojo_bytes_zeros(int64_t n);
MojoBytes *mojo_bytes_from_list(MojoList *l);      /* list of ints 0-255 */
MojoBytes *mojo_bytes_from_str(char *s, char *encoding); /* 'utf-8'/'ascii' */
MojoBytes *mojo_bytes_from_cstr(const char *s);   /* NUL-terminated copy */
int64_t    mojo_bytes_len(MojoBytes *b);
int64_t    mojo_bytes_get(MojoBytes *b, int64_t i); /* -> int 0-255, neg idx ok */
/* `b[i]` at an explicit subscript: same read, but an out-of-range index
 * RAISES IndexError rather than answering 0. The lenient form above is
 * kept for the iteration loop, which bounds its own index. */
int64_t    mojo_bytes_get_checked(MojoBytes *b, int64_t i);
int        mojo_bytes_eq(MojoBytes *a, MojoBytes *b);
/* The three-way sibling, for `b'a' < b'b'` and for a bytes ELEMENT of an
 * ordered container. A prefix orders first. */
int        mojo_bytes_cmp(MojoBytes *a, MojoBytes *b);
int        mojo_bytes_truthy(MojoBytes *b);
char      *mojo_bytes_repr(MojoBytes *b);
void       mojo_bytes_print(MojoBytes *b);
MojoBytes *mojo_bytes_concat(MojoBytes *a, MojoBytes *b);
MojoBytes *mojo_bytes_repeat(MojoBytes *b, int64_t n);
MojoBytes *mojo_bytes_slice(MojoBytes *b, int64_t start, int64_t stop, int64_t step);
int        mojo_bytes_contains(MojoBytes *hay, MojoBytes *needle);
int64_t    mojo_bytes_find(MojoBytes *hay, MojoBytes *needle);
int64_t    mojo_bytes_rfind(MojoBytes *hay, MojoBytes *needle);
/* start/stop use the MOJO_SLICE_STOP_OMITTED sentinel for "not given" and are
 * otherwise Python's clamped [start, end) bounds (negatives count from the
 * end, start > end yields an empty range). */
int64_t    mojo_bytes_find_from(MojoBytes *hay, MojoBytes *needle, int64_t start, int64_t stop);
int64_t    mojo_bytes_rfind_from(MojoBytes *hay, MojoBytes *needle, int64_t start, int64_t stop);
/* index/count of a single byte VALUE (bytes/bytearray `.index(0xNN)`). */
/* find/rfind over a byte VALUE answer -1 when absent; index/rindex are the
 * same search that RAISES ValueError instead. They were one function, which
 * made `b'abc'.index(b'z')` answer -1 with exit 0. */
/* `index`/`rindex`'s failure mode over a BYTES needle: -1 becomes a
 * ValueError, since the search itself is shared with find/rfind. */
int64_t    _mojo_bytes_index_or_raise(int64_t at);
int64_t    mojo_bytes_find_int(MojoBytes *b, int64_t v, int64_t start, int64_t stop);
int64_t    mojo_bytes_rfind_int(MojoBytes *b, int64_t v, int64_t start, int64_t stop);
int64_t    mojo_bytes_index_int(MojoBytes *b, int64_t v, int64_t start, int64_t stop);
int64_t    mojo_bytes_rindex_int(MojoBytes *b, int64_t v, int64_t start, int64_t stop);
int64_t    mojo_bytes_count_int(MojoBytes *b, int64_t v, int64_t start, int64_t stop);
int64_t    mojo_bytes_count(MojoBytes *hay, MojoBytes *needle);
int64_t    mojo_bytes_count_from(MojoBytes *hay, MojoBytes *needle, int64_t start, int64_t stop);
int        mojo_bytes_startswith(MojoBytes *b, MojoBytes *p);
int        mojo_bytes_endswith(MojoBytes *b, MojoBytes *p);
char      *mojo_bytes_decode(MojoBytes *b, char *encoding);
char      *mojo_bytes_hex(MojoBytes *b);
char      *mojo_bytes_hash_hexdigest(MojoBytes *b);  /* hashlib(...).hexdigest() backing */
MojoBytes *mojo_bytes_removeprefix(MojoBytes *b, MojoBytes *p);
MojoBytes *mojo_bytes_removesuffix(MojoBytes *b, MojoBytes *p);
MojoBytes *mojo_bytes_title(MojoBytes *b);
MojoBytes *mojo_bytes_capitalize(MojoBytes *b);
MojoBytes *mojo_bytes_swapcase(MojoBytes *b);
MojoBytes *mojo_bytes_ljust(MojoBytes *b, int64_t width, int fill);
MojoBytes *mojo_bytes_rjust(MojoBytes *b, int64_t width, int fill);
MojoBytes *mojo_bytes_center(MojoBytes *b, int64_t width, int fill);
MojoBytes *mojo_bytes_zfill(MojoBytes *b, int64_t width);
/* ljust/rjust/center's `fillchar` resolved to the single byte VALUE it
 * stands for. CPython accepts ONLY a one-byte `bytes` here (`TypeError`
 * otherwise) and this compiler additionally accepts the bare int, so the
 * length check belongs at runtime — the fill expression is not a constant.
 * Passing a wrong length raises TypeError rather than silently padding
 * with the first byte. */
int         mojo_bytes_fill_byte(MojoBytes *fill);
/* partition/rpartition -> a 3-element list of (head, sep, tail). */
MojoList  *mojo_bytes_partition(MojoBytes *b, MojoBytes *sep);
MojoList  *mojo_bytes_rpartition(MojoBytes *b, MojoBytes *sep);
MojoBytes *mojo_bytes_fromhex(char *s);
/* NUL-terminated copy of the bytes' content, for the char*-keyed dict probe
 * path; truncates at an embedded NUL (documented lossiness). */
char      *mojo_bytes_cstr_key(MojoBytes *b);
MojoBytes *mojo_bytes_maketrans(MojoBytes *from, MojoBytes *to);
MojoBytes *mojo_bytes_translate(MojoBytes *b, MojoBytes *table);
/* `b.translate(table, delete)` — `delete` was silently dropped without it. */
MojoBytes *mojo_bytes_translate_del(MojoBytes *b, MojoBytes *table, MojoBytes *delbytes);
/* `b.expandtabs([tabsize])` — the bytes twin of mojo_str_expandtabs; this
 * had no bytes implementation and answered a raw int 0. */
MojoBytes *mojo_bytes_expandtabs(MojoBytes *b, int64_t tabsize);
/* startswith/endswith WITH the optional [start[, end]] window, which was
 * silently ignored when only the prefix/suffix was passed. */
int        mojo_bytes_startswith_from(MojoBytes *b, MojoBytes *p, int64_t start, int64_t stop);
int        mojo_bytes_endswith_from(MojoBytes *b, MojoBytes *p, int64_t start, int64_t stop);
/* The bytes.isX() predicates, selected by `kind` (the MOJO_IS_* codes in
 * fire_runtime.c). `kind` is deliberately restricted to the eight
 * predicates CPython actually defines on `bytes` — isalnum isalpha
 * isascii isdigit islower isspace istitle isupper. `isprintable` and
 * `isnumeric` are `str`-only and reach the kernel through
 * mojo_str_isprintable / mojo_str_isnumeric instead; a `bytes` receiver
 * asking for them is an AttributeError (raised in the backend, matching
 * both CPython and the interpreter reference). */
int        mojo_bytes_is(MojoBytes *b, int kind);
MojoBytes *mojo_bytes_replace(MojoBytes *b, MojoBytes *from, MojoBytes *to);
/* `.replace(old, new, count)` — count < 0 or MOJO_SLICE_STOP_OMITTED replaces
 * every occurrence. */
MojoBytes *mojo_bytes_replace_n(MojoBytes *b, MojoBytes *from, MojoBytes *to, int64_t count);
MojoBytes *mojo_bytes_strip(MojoBytes *b, MojoBytes *chars, int do_left, int do_right);
MojoBytes *mojo_bytes_upper(MojoBytes *b);
MojoBytes *mojo_bytes_lower(MojoBytes *b);
MojoList  *mojo_bytes_split(MojoBytes *b, MojoBytes *sep);
MojoList  *mojo_bytes_rsplit(MojoBytes *b, MojoBytes *sep);
/* maxsplit == MOJO_SLICE_STOP_OMITTED means unbounded; from_right selects
 * rsplit semantics (splitting anchored at the end). */
MojoList  *mojo_bytes_split_max(MojoBytes *b, MojoBytes *sep, int64_t maxsplit, int from_right);
MojoList  *mojo_bytes_splitlines(MojoBytes *b);
MojoList  *mojo_bytes_splitlines_keep(MojoBytes *b, int keepends);
MojoBytes *mojo_bytes_join(MojoBytes *sep, MojoList *parts);
MojoBytes *mojo_bytes_copy(MojoBytes *src);   /* bytes(bytearray) — real copy */
MojoBytes *mojo_bytes_reverse(MojoBytes *src);/* reversed(<bytes>) */

/* ── bytearray (mutable; shares the MojoBytes representation) ────────────
 * Every read op (len/index/slice/iter/in/eq/methods) is inherited from
 * the bytes path since the C type is identical. These add mutation. */
MojoBytes *mojo_bytearray_new(void);
MojoBytes *mojo_bytearray_copy(MojoBytes *src);
/* Mark an already-constructed MojoBytes as a bytearray (i.e. clear its
 * `readonly` flag). A separate call rather than a parameter on every
 * constructor because most bytearray sources are built by SHARING a
 * bytes-producing helper (`bytearray(b'x')`, `bytearray("x")`,
 * `bytearray([1,2])` all reuse the immutable ones' code); the flag is a
 * property of the CONSTRUCTOR SPELLING, which only the caller knows. */
MojoBytes *mojo_bytearray_mark(MojoBytes *b);
void       mojo_bytearray_setitem(MojoBytes *b, int64_t i, int64_t v);
void       mojo_bytearray_append(MojoBytes *b, int64_t v);
void       mojo_bytearray_extend(MojoBytes *b, MojoBytes *other);
int64_t    mojo_bytearray_pop(MojoBytes *b, int64_t i); /* i==MOJO_SLICE_STOP_OMITTED -> last */
void       mojo_bytearray_delitem(MojoBytes *b, int64_t i);
void       mojo_bytearray_splice(MojoBytes *b, int64_t start, int64_t stop, MojoBytes *repl);
void       mojo_bytearray_insert(MojoBytes *b, int64_t i, int64_t v);
void       mojo_bytearray_remove(MojoBytes *b, int64_t v);

/* ── memoryview (non-copying 1-D byte view, itemsize 1 / format 'B') ─────*/
/* `readonly` is inherited from the object the view was taken over (a
 * bytes is immutable, a bytearray is not) and is a real field rather
 * than a constant fold: this struct keeps only a raw window, so a view
 * over a bytearray and a view over a bytes are otherwise the same three
 * numbers, and folding `.readonly` to a constant got `memoryview(
 * bytearray(...)).readonly` backwards. `cast()` and slicing carry it. */
typedef struct {
    uint8_t *data;
    int64_t  len;
    int64_t  itemsize;
    int      readonly;
} MojoMemoryView;

MojoMemoryView *mojo_memoryview_new(uint8_t *data, int64_t len, int64_t itemsize);
MojoMemoryView *mojo_memoryview_from_bytes(MojoBytes *b);
int64_t         mojo_memoryview_len(MojoMemoryView *m);
int64_t         mojo_memoryview_get(MojoMemoryView *m, int64_t i);
MojoMemoryView *mojo_memoryview_slice(MojoMemoryView *m, int64_t start, int64_t stop, int64_t step);
MojoBytes      *mojo_memoryview_tobytes(MojoMemoryView *m);
int             mojo_memoryview_eq(MojoMemoryView *m, MojoBytes *b);
char           *mojo_memoryview_hex(MojoMemoryView *m);
MojoMemoryView *mojo_memoryview_cast(MojoMemoryView *m, char *fmt);
char           *mojo_memoryview_repr(MojoMemoryView *m);
/* The descriptive shape attributes. Exact for this representation, which is
 * always 1-D and contiguous; they previously had no lowering at all and
 * printed their own heap address as a decimal. The tuple-valued ones return
 * the SPELLING string, since there is no 1-tuple shape on this side. */
char           *mojo_memoryview_shape_str(MojoMemoryView *m);
char           *mojo_memoryview_strides_str(MojoMemoryView *m);
char           *mojo_memoryview_suboffsets_str(void);
int64_t         mojo_memoryview_ndim(MojoMemoryView *m);
int             mojo_memoryview_c_contiguous(MojoMemoryView *m);
int             mojo_memoryview_f_contiguous(MojoMemoryView *m);
int             mojo_memoryview_contiguous(MojoMemoryView *m);
MojoList       *mojo_memoryview_tolist(MojoMemoryView *m);
int64_t         mojo_memoryview_itemsize(MojoMemoryView *m);
int64_t         mojo_memoryview_nbytes(MojoMemoryView *m);
char           *mojo_memoryview_format(MojoMemoryView *m, char *fmt);
MojoBytes      *mojo_memoryview_obj(MojoMemoryView *m);
int             mojo_memoryview_readonly(MojoMemoryView *m);

/* ── struct module (binary pack / unpack) ───────────────────────────────
 * Format mini-language, a subset of CPython's `struct`:
 *   byte-order prefix  < > = ! @   (@ = native size+align, default)
 *   codes  x b B h H i I l L q Q f d s ? c  with optional leading count
 * A compiled format is an opaque `MojoStructFmt *`. Packed values ARE
 * `MojoBytes` (see CODEGEN_bytes_value_type). GIMPLE cannot pass a mixed
 * int64/double vararg list, so codegen lowers `struct.pack(fmt, a, b, …)`
 * to a `MojoList *` of values (ints via mojo_list_append_int, floats via
 * mojo_list_append_double, `s`/`c` fields as a MojoBytes* pointer stored
 * in an int slot) and calls mojo_struct_pack_list. unpack returns a
 * tuple-marked MojoList (`s`/`c` elements are MojoBytes* pointers in int
 * slots; float codes are doubles; everything else int64).
 * `struct.error` is raised via mojo_struct_raise_error with the tag
 * MOJO_STRUCT_ERROR_TAG (== crc32("struct.error") & 0x7fffffff, matching
 * gimple_gen_infra._exc_type_id). */
#define MOJO_STRUCT_ERROR_TAG 1315445615

typedef struct MojoStructFmt MojoStructFmt;

void            mojo_struct_raise_error(const char *msg);
MojoStructFmt  *mojo_struct_compile(const char *fmt);   /* raises struct.error on a bad format */
int64_t         mojo_struct_calcsize(const char *fmt);
MojoBytes      *mojo_struct_pack_list(const char *fmt, MojoList *values);
MojoList       *mojo_struct_unpack(const char *fmt, MojoBytes *buffer);
MojoList       *mojo_struct_unpack_from(const char *fmt, MojoBytes *buffer, int64_t offset);
void            mojo_struct_pack_into(const char *fmt, MojoBytes *buffer, int64_t offset, MojoList *values);
/* struct.Struct instance API (the handle is the compiled format itself) */
MojoStructFmt  *mojo_struct_new(const char *fmt);
int64_t         mojo_struct_size(MojoStructFmt *f);
char           *mojo_struct_format(MojoStructFmt *f);
MojoBytes      *mojo_struct_pack_h(MojoStructFmt *f, MojoList *values);
MojoList       *mojo_struct_unpack_h(MojoStructFmt *f, MojoBytes *buffer);
MojoList       *mojo_struct_unpack_from_h(MojoStructFmt *f, MojoBytes *buffer, int64_t offset);
void            mojo_struct_pack_into_h(MojoStructFmt *f, MojoBytes *buffer, int64_t offset, MojoList *values);

/* ── subprocess.run ──────────────────────────────────────────────────────
 * Mirrors Python's subprocess.CompletedProcess just enough for this
 * compiler's own build tooling (mojo.py, version.py, compile_stdlib.py, …):
 * a captured returncode/stdout/stderr. `capture_output`/`text` are the only
 * modes exercised by real call sites; `check`-triggered raising and
 * `timeout` enforcement are not implemented (see BACKLOG-CODEGEN.md).    */
typedef struct {
    int64_t returncode;
    char   *out;
    char   *err;
} MojoCompletedProcess;

MojoCompletedProcess *mojo_subprocess_run(MojoList *argv, int64_t capture_output);
int64_t mojo_subprocess_returncode(MojoCompletedProcess *p);
char   *mojo_subprocess_stdout(MojoCompletedProcess *p);
char   *mojo_subprocess_stderr(MojoCompletedProcess *p);

/* ── Dict ─────────────────────────────────────────────────────────────────
 * Open-addressing hash map with string keys and int64_t values.
 * Double and string values are stored as bit-casts / pointer casts.      */
typedef struct {
    char    *key;   /* NULL = empty slot */
    int64_t  val;
    int64_t  seq;   /* insertion order, assigned once when the key is first
                     * added — via mojo_dict_order_indices(), this drives
                     * BOTH generic repr() and real iteration (MojoDictIter,
                     * .keys()/.values()/.items()), matching Python's
                     * insertion-preserving dict guarantee, not raw
                     * hash-slot order. */
    int64_t  kind;  /* what `val` actually holds, needed by consumers that
                     * must re-interpret the untagged slot (runtime dict-keyed
                     * %-formatting): 0 = plain int64_t, 1 = double bit-cast,
                     * 2 = char * pointer, 3 = a Python bool (0/1, which is
                     * the same int64_t as case 0 and so is only separable
                     * because the tag is per SLOT). Maintained by the typed
                     * setters below; zero-defaulted everywhere else. */
    int64_t  keykind; /* key DOMAIN, since every key is stored as its own
                     * characters in `key` and matched with strcmp: 0 = a str
                     * key, 1 = a bytes key. Keeps `d[b'x']` and `d['x']` the
                     * two distinct entries Python says they are.
                     * 2 = an INTEGER key: `key` still holds its decimal
                     * string (so iteration, repr, copy and pop see exactly
                     * what they always did), and `ikey` holds the integer,
                     * which is what is hashed and compared. Every key that is
                     * a canonical decimal integer ("5", "-12", never "05" or
                     * "+5") is stored this way whether it arrived as the int 5
                     * or the string "5", so the two remain one key as before
                     * but a lookup by int needs no formatting at all. */
    int64_t  ikey;    /* the integer, for keykind == 2; otherwise unused */
} _DictSlot;

/* Value-kind tags for _DictSlot.kind. Kept in the header so generated code
 * never needs them — only runtime internals read/write kind today. */

/* The first slot table lives INSIDE the struct: a dict that stays within
 * MOJO_DICT_INLINE slots (it grows at half full, so up to 4 entries) never
 * allocates a table, and a stack-homed one allocates nothing at all. `slots`
 * points at `inl` until the first growth, after which `inl` is unused and
 * `slots` is a heap table. Anything that frees `slots` must first check
 * `slots != inl`; anything that copies a MojoDict struct by value would leave
 * `slots` pointing into the original and must not. */
#define MOJO_DICT_INLINE 8
typedef struct {
    _DictSlot *slots;
    int64_t    used;
    int64_t    cap;
    int64_t    next_seq;
    _DictSlot  inl[MOJO_DICT_INLINE];
} MojoDict;

MojoDict   *mojo_dict_new(void);
/* `os.environ` as a VALUE (the mapping). The per-key idioms
 * (`os.environ.get(k)`, `os.environ[k]`, `k in os.environ`,
 * `os.environ[k] = v`) are lowered to mojo_c_getenv by ast_rewriter.py
 * and do not go through this; see mojo_environ_dict's own comment in
 * fire_runtime.c for the singleton semantics and the honest, putenv-free
 * scope of writes. Declared HERE rather than beside mojo_c_getenv
 * because it is the first helper to return a container. */
MojoDict   *mojo_environ_dict(void);
int64_t    *mojo_dict_order_indices(MojoDict *d);
void        mojo_dict_free(MojoDict *d);
/* mojo_dict_init/mojo_dict_destroy: see mojo_list_init/mojo_list_destroy's
 * comment above (same Phase 6 rationale, same shape). */
void        mojo_dict_init(MojoDict *d);
void        mojo_dict_destroy(MojoDict *d);
void        mojo_dict_clear(MojoDict *d);

void        mojo_dict_set_int(MojoDict *d, char *key, int64_t v);
/* `_kw` variants: the key arrives as a raw machine WORD that is either a boxed
 * string pointer or an integer, and the same decision mojo_cstr_or_int_str
 * makes (mojo_boxed_is_str) is made here — but an integer is looked up directly,
 * with no decimal string built and nothing to release. Emitted by codegen for
 * dict operations whose key is an untracked int64_t. */
/* A CONTAINER used as a dict key needs a CONTENT key, not its address: a
 * tuple is the one container Python considers hashable, so `d[(p, mtime)]`
 * must find the entry a previous equal tuple stored. The returned string is
 * MALLOC'd and the caller OWNS it — it is NOT a `_int_str_block` pool block
 * and must not be released through `mojo_cstr_or_int_release`. Every `_kw`
 * entry point below copies or merely reads it, so free it with
 * `mojo_dict_key_free` once that one call returns. Raises for a dict / set
 * key, which Python refuses as unhashable. */
char       *mojo_dict_key_for(int64_t v);
void        mojo_dict_key_free(char *s);
int64_t     mojo_dict_get_int_kw(MojoDict *d, int64_t kw);
double      mojo_dict_get_double_kw(MojoDict *d, int64_t kw);
char       *mojo_dict_get_str_kw(MojoDict *d, int64_t kw);
void        mojo_dict_set_int_kw(MojoDict *d, int64_t kw, int64_t v);
void        mojo_dict_set_double_kw(MojoDict *d, int64_t kw, double v);
void        mojo_dict_set_str_kw(MojoDict *d, int64_t kw, char *v);
int         mojo_dict_contains_kw(MojoDict *d, int64_t kw);
int64_t     mojo_dict_pop_int_kw(MojoDict *d, int64_t kw);
int64_t     mojo_dict_setdefault_int_kw(MojoDict *d, int64_t kw, int64_t dflt);
char       *mojo_dict_setdefault_str_kw(MojoDict *d, int64_t kw, char *dflt);
void        mojo_dict_set_double(MojoDict *d, char *key, double v);
void        mojo_dict_set_bytes_double(MojoDict *d, MojoBytes *key, double v);
void        mojo_dict_set_str(MojoDict *d, char *key, char *v);
/* A Python bool stored as a dict VALUE: same 0/1 int64_t as
 * mojo_dict_set_int, but tagged `_DictSlot.kind == 3` so the dict's repr can
 * still say True/False. Emitted by codegen wherever the stored expression is a
 * Python bool (see `is_python_bool_expr`). */
void        mojo_dict_set_bool(MojoDict *d, char *key, int v);

int64_t     mojo_dict_get_int(MojoDict *d, char *key);
double      mojo_dict_get_double(MojoDict *d, char *key);
char *mojo_dict_get_str(MojoDict *d, char *key);
int64_t     mojo_dict_setdefault_int(MojoDict *d, char *key, int64_t dflt);
char       *mojo_dict_setdefault_str(MojoDict *d, char *key, char *dflt);
MojoList   *mojo_dict_keys(MojoDict *d);
MojoList   *mojo_dict_values(MojoDict *d);
MojoList   *mojo_dict_items(MojoDict *d);
MojoList   *mojo_dict_items_int(MojoDict *d);
void        mojo_dict_update(MojoDict *dst, MojoDict *src);
int64_t     mojo_dict_pop_int(MojoDict *d, char *key);
MojoDict   *mojo_dict_copy(MojoDict *d);
MojoDict   *mojo_dict_union(MojoDict *a, MojoDict *b);  /* a | b */
MojoDict   *mojo_dict_from_pairs(MojoList *pairs);  /* dict(list_of_pairs) */
MojoList   *mojo_list_copy(MojoList *l);
int         mojo_list_all(MojoList *l);
int         mojo_list_any(MojoList *l);
/* The same four over a `bytes` object, whose iteration yields INTEGERS.
 * Without these every such call answered the codegen's constant stub. */
int         mojo_bytes_all(MojoBytes *b);
int         mojo_bytes_any(MojoBytes *b);
int64_t     mojo_bytes_sum(MojoBytes *b);
MojoList   *mojo_bytes_reversed_list(MojoBytes *b);
MojoList   *mojo_bytes_sorted_list(MojoBytes *b);
int         mojo_bytes_max(MojoBytes *b);
int         mojo_bytes_min(MojoBytes *b);
int64_t     mojo_list_pop(MojoList *l);
int64_t     mojo_list_pop_at(MojoList *l, int64_t idx);
/* `del lst[i]` — same removal as mojo_list_pop_at, but a different Python
 * operation with a different refusal on a tuple (see its definition). */
int64_t     mojo_list_delitem(MojoList *l, int64_t idx);
void        mojo_list_extend(MojoList *dst, MojoList *src);
/* `l.sort()` in place. `kind` is a MOJO_KIND_* byte for the elements (or for
 * the KEYS, when `keys` is given), or 0 to let the runtime decide from the
 * per-slot kinds and then its own discriminator. `keys` is the parallel key
 * list codegen built for a `key=` call, or NULL. A list with no order (mixed
 * or nested-container elements) is a TypeError here exactly as it is in
 * Python — never a silent no-op, which is what this used to be. */
void        mojo_list_sort(MojoList *l, int kind, int reverse, MojoList *keys);
void        mojo_list_reverse(MojoList *l);
void        mojo_list_clear(MojoList *l);
void        mojo_list_remove_str(MojoList *l, const char *v);
void        mojo_list_remove_int(MojoList *l, int64_t v);
int64_t     mojo_list_index_str(MojoList *l, const char *v);
int64_t     mojo_list_index_int(MojoList *l, int64_t v);
int64_t     MojoList_index(MojoList *l, int v);

/* Generic Python-object attribute accessor (used by GIMPLE codegen for
 * opaque int nodes) — real per-object dynamic-attribute storage, raises a
 * genuine, catchable AttributeError on a miss. See fire_runtime.c's own
 * doc comment above the definition and bugs/hard/CODEGEN_dynamic_
 * attribute_on_generic_object.md. */
int64_t     mojo_obj_getattr(void *obj, char *attr);
/* 3-arg `getattr(obj, name, default)` support. `_mojo_dispatch_getattr`'s
 * own fallback (mojo_obj_getattr) RAISES AttributeError on a miss, so the
 * caller's default could never be substituted. The compiled lowering of a
 * 3-arg getattr sets `_mojo_getattr_nothrow` around the dispatch call;
 * while it is non-zero mojo_obj_getattr clears `_mojo_getattr_missed`,
 * sets it to 1 and returns 0 on a miss instead of raising. The lowering
 * then selects `default` whenever `_mojo_getattr_missed` is set. Plain int
 * globals (not a wide sentinel constant) so the emitted __GIMPLE stays a
 * bare load/store. */
extern int  _mojo_getattr_nothrow;
extern int  _mojo_getattr_missed;
/* Raises a real AttributeError for attribute `attr` — same runtime call
 * sequence compiled `raise AttributeError(...)` itself lowers to, so a
 * compiled `except AttributeError:` genuinely catches this. Used by
 * mojo_obj_getattr on a miss; also usable directly by any other runtime
 * helper that needs to raise the same typed exception. */
void        mojo_raise_attribute_error(char *attr);
void        mojo_raise_file_not_found(char *path);
/* Raises a real, catchable KeyError for `key` — same mechanism as
 * mojo_raise_attribute_error above (typed via the class-name CRC32 tag),
 * used by runtime dict-keyed %-formatting (mojo_str_format_dict) on a
 * missing key, matching real Python's `"...%(k)s..." % {}` behavior. */
void        mojo_raise_key_error(char *key);
/* Raises a real, catchable TypeError for calling something that is not
 * callable — the same mechanism as mojo_raise_attribute_error /
 * mojo_raise_key_error above (typed via the class-name CRC32 tag).
 * `detail` is the text CPython puts after "TypeError: ", e.g. "'str' object
 * is not callable". Used by the codegen for a call on a non-callable
 * attribute of a type whose attribute namespace it models as closed
 * (struct.Struct's `format`/`size`), which it previously answered with a
 * silent 0. */
void        mojo_raise_type_error(char *detail);
/* Raises a real, catchable ValueError for `detail` — the same mechanism and
 * the same tag derivation (crc32("ValueError") & 0x7fffffff) as
 * mojo_raise_attribute_error / mojo_raise_key_error / mojo_raise_type_error
 * above, so a compiled `except ValueError:` catches it. Used where a Python
 * operation rejects its ARGUMENT rather than failing to find something
 * (mojo_bytes_partition's empty separator). */
void        mojo_raise_value_error(char *detail);
void        mojo_raise_index_error(char *detail);
/* Runtime %-style string formatting with a DYNAMIC (non-literal) template:
 *
 *   char *out = mojo_str_format_dict("usage: %(prog)s v%(ver)d", d);
 *
 * `fmt` may mix literal text, '%%', and %(key)[flags][width][.prec]conv
 * specs; each spec's value is looked up in `vals` by key at RUNTIME and
 * formatted per the spec, using the slot's kind tag to interpret its
 * untagged int64 storage correctly (%s of an int value prints the decimal
 * number like real Python's str()-conversion, %d of a double truncates,
 * etc.). Missing keys raise a real catchable KeyError. Returns a heap
 * string. The compile-time counterpart (_lower_percent_format) only ever
 * fires when the template is a string LITERAL in the source; this covers
 * the real-world remainder — templates read from data/parameters
 * (`text % dict(prog=...)`, `readme % textvars`). */
char       *mojo_str_format_dict(char *fmt, MojoDict *vals);
void        mojo_unsupported_iter(const char *type_name);

/* Real `hash(x)` builtin -- see fire_runtime.c's docstring above their
 * definitions. mojo_hash_str for a statically-known string argument,
 * mojo_hash for the generic (statically-opaque-type) fallback. */
int64_t     mojo_hash_str(char *s);
int64_t     mojo_hash(int64_t val);

int         mojo_dict_contains(MojoDict *d, char *key);
/* bytes-keyed access — its own key DOMAIN (see _DictSlot.keykind), so
 * `d[b'x']` and `d['x']` stay distinct entries. Keyed by content. */
void        mojo_dict_set_bytes_int(MojoDict *d, MojoBytes *key, int64_t v);
void        mojo_dict_set_bytes_str(MojoDict *d, MojoBytes *key, char *v);
/* The bytes-key twin of mojo_dict_set_bool. */
void        mojo_dict_set_bytes_bool(MojoDict *d, MojoBytes *key, int v);
int64_t     mojo_dict_get_bytes_int(MojoDict *d, MojoBytes *key);
char       *mojo_dict_get_bytes_str(MojoDict *d, MojoBytes *key);
double      mojo_dict_get_bytes_double(MojoDict *d, MojoBytes *key);
int         mojo_dict_contains_bytes(MojoDict *d, MojoBytes *key);
int64_t     mojo_dict_setdefault_bytes_int(MojoDict *d, MojoBytes *key, int64_t dflt);
int64_t     mojo_dict_pop_bytes_int(MojoDict *d, MojoBytes *key, int64_t dflt);
/* str/double siblings of pop_bytes_int — same domain, read back as their own
 * type. A MISSING key pops nothing and yields 0/NULL/0.0 (the absent-box
 * convention mojo_dict_get_* already uses; Python's KeyError is not
 * modelled). */
char       *mojo_dict_pop_bytes_str(MojoDict *d, MojoBytes *key);
double      mojo_dict_pop_bytes_double(MojoDict *d, MojoBytes *key);
void        mojo_dict_print(MojoDict *d);
int64_t     mojo_dict_len(MojoDict *d);

/* Dict iterator — advance, then read key/value via accessor calls.
 * Walks in insertion order (via `order`, from mojo_dict_order_indices()),
 * matching Python's own dict iteration guarantee — NOT raw hash-slot order.
 * `pos` indexes into `order`, not directly into dict->slots. */
typedef struct {
    MojoDict *dict;
    int64_t   pos;      /* index into `order` (-1 = not yet started) */
    int64_t  *order;    /* insertion-order slot indices; NULL if dict empty */
} MojoDictIter;
MojoDictIter  *mojo_dict_iter_new(MojoDict *d);
int            mojo_dict_iter_next(MojoDictIter *it);     /* 1=has entry, 0=done */
char *mojo_dict_iter_key(MojoDictIter *it);
char *mojo_dict_slot_key(MojoDict *d, int64_t i);
int64_t mojo_dict_iter_key_int(MojoDictIter *it);
int64_t        mojo_dict_iter_val_int(MojoDictIter *it);
double         mojo_dict_iter_val_double(MojoDictIter *it);
char *mojo_dict_iter_val_str(MojoDictIter *it);
void           mojo_dict_iter_free(MojoDictIter *it);

/* ── Set ──────────────────────────────────────────────────────────────────
 * Hash set over int64_t or string values.                                 */
typedef struct {
    int     tag;   /* -1 = empty, 0 = int, 1 = str */
    int64_t val_i;
    char   *val_s;
    int64_t seq;   /* insertion order; see mojo_set_order_indices */
} _SetSlot;

/* As MojoDict: the first table is inside the struct (`slots == inl` until the
 * first growth), so a small set allocates no table. */
#define MOJO_SET_INLINE 8
typedef struct {
    _SetSlot *slots;
    int64_t   used;
    int64_t   cap;
    int64_t   next_seq;
    _SetSlot  inl[MOJO_SET_INLINE];
} MojoSet;

MojoSet *mojo_set_new(void);
void     mojo_set_free(MojoSet *s);
/* mojo_set_init/mojo_set_destroy: see mojo_list_init/mojo_list_destroy's
 * comment above (same Phase 6 rationale, same shape). */
void     mojo_set_init(MojoSet *s);
void     mojo_set_destroy(MojoSet *s);
void     mojo_set_clear(MojoSet *s);

void     mojo_set_add_int(MojoSet *s, int64_t v);
void     mojo_set_add_str(MojoSet *s, char *v);

int      mojo_set_contains_int(MojoSet *s, int64_t v);
int      mojo_set_contains_str(MojoSet *s, char *v);
void     mojo_set_add_bytes(MojoSet *s, MojoBytes *b);
int      mojo_set_contains_bytes(MojoSet *s, MojoBytes *b);
MojoBytes *mojo_set_val_bytes(MojoSet *s, int64_t idx);
int64_t  mojo_set_len(MojoSet *s);
MojoSet *mojo_set_union(MojoSet *a, MojoSet *b);
MojoSet *mojo_set_intersection(MojoSet *a, MojoSet *b);
MojoSet *mojo_set_difference(MojoSet *a, MojoSet *b);
MojoSet *mojo_set_copy(MojoSet *s);
void     mojo_set_update(MojoSet *dst, MojoSet *src);
void     mojo_set_discard_int(MojoSet *s, int64_t v);
void     mojo_set_discard_str(MojoSet *s, char *v);

int64_t *mojo_set_order_indices(MojoSet *s);

/* Set iterator. Walks in INSERTION order (mojo_set_order_indices), exactly
 * as MojoDictIter already does, NOT in slot/hash order.
 *
 * This is a determinism requirement, not a nicety. An int slot's hash is
 * derived from the value itself, and the self-hosted compiler routinely
 * stores boxed `char *` STRINGS through the int view (`mojo_set_add_int`
 * on a boxed name) — so those slots hash by heap ADDRESS. Addresses move
 * per run under ASLR, so hash-order iteration made the compiler emit
 * DIFFERENT output for identical input on consecutive runs. Insertion
 * order depends only on the program's own execution, so it is stable. */
typedef struct {
    MojoSet *set;
    int64_t  pos;   /* index into `order` */
    int64_t  n;     /* number of live entries */
    int64_t *order; /* slot indices, insertion-ordered */
} MojoSetIter;
MojoSetIter *mojo_set_iter_new(MojoSet *s);
int          mojo_set_iter_next(MojoSetIter *it);      /* 1=has entry, 0=done */
int64_t      mojo_set_iter_pos(MojoSetIter *it);       /* backing slot idx, or -1 */
int64_t      mojo_set_iter_val_int(MojoSetIter *it);
char *mojo_set_iter_val_str(MojoSetIter *it);
void         mojo_set_iter_free(MojoSetIter *it);

void     mojo_set_print(MojoSet *s);

/* ── Value equality ─────────────────────────────────────────────────────────
 * `a == b` / `a != b` between two VALUES, as Python defines it — not as C
 * does, where comparing two `MojoList *` is a pointer comparison that answers
 * True only for one object compared with itself. Every convergence test the
 * compiler's own source writes over containers is `while nxt != proven:` with
 * `nxt` and `proven` two separate allocations, so the pointer comparison
 * never fired and the loop never ended
 * (bugs/CODEGEN_container_eq_is_pointer_identity.md). See fire_runtime.c's
 * "`==` / `!=` between values" block for the whole story.
 *
 * `elem` is the element code the CODEGEN knows statically for the container
 * it built — MOJO_EQ_UNKNOWN asks the container's own per-slot kinds instead,
 * which is the only evidence available for an operand erased to int64_t. It is
 * PER SIDE (`ea`, `eb`) because `[1.0] == [1]` is a legitimate program and one
 * code cannot describe both halves of it.
 * Declared here, after all three container types, because unlike every other
 * comparison primitive these three need all of them. */
#define MOJO_EQ_UNKNOWN 0
#define MOJO_EQ_INT     1
#define MOJO_EQ_DOUBLE  2
#define MOJO_EQ_STR     3
#define MOJO_EQ_BYTES   4
#define MOJO_EQ_GENERIC 5
int mojo_list_eq(MojoList *a, MojoList *b, int ea, int eb);
int mojo_dict_eq(MojoDict *a, MojoDict *b, int va, int vb);
int mojo_set_eq(MojoSet *a, MojoSet *b, int ea, int eb);
/* `a == b` for two operands whose static types the codegen could not BOTH
 * resolve — the shape a container handed to an unannotated parameter takes.
 * `elem` describes the side the codegen knew and is applied to both. */
int mojo_value_eq(int64_t a, int64_t b, int elem);

/* ── the ORDERING comparisons, the same story one level up ────────────────
 * `a < b` between two containers used to lower to the same raw POINTER
 * comparison `==` did, so the answer was decided by heap addresses. Unlike
 * `==` this is answerable: CPython orders lists (lexicographic, shorter prefix
 * first) and sets (proper subset). A dict has NO ordering — `{'a':1} < {'b':2}`
 * is a genuine TypeError on 3.14 too — so the dict arm raises instead of
 * inventing an answer, as does any pair of different kinds.
 *
 * The three `mojo_*_cmp` functions return a three-way answer, not a boolean,
 * because the four operators are four folds of ONE comparison and re-deriving
 * the comparison per operator is how the `==` family ended up with several
 * near-identical implementations. `mojo_value_cmp` is mojo_value_eq's
 * ordering twin for the erased-handle shape.
 *
 * UNORDERABLE is not "equal": it is "these have no ordering". For a LIST it is
 * a TypeError, raised at the point it is produced so a comparison CPython
 * refuses does not silently become a False; for a SET it is an ordinary False
 * for all four operators, because a set ordering test is a subset question and
 * "neither is a subset of the other" is a real answer to it.
 *
 * `op` is the operator (MOJO_CMP_OP_*) because the three-way result and the
 * operator are both needed below: the result to fold, and the SPELLING for the
 * TypeError text, which must say the operator the source wrote. It is threaded
 * down rather than reconstructed at each raise so a nested container keeps
 * naming the outermost operator. */
#define MOJO_CMP_UNORDERABLE 2
#define MOJO_CMP_OP_LT 0
#define MOJO_CMP_OP_LE 1
#define MOJO_CMP_OP_GT 2
#define MOJO_CMP_OP_GE 3
int mojo_list_cmp(MojoList *a, MojoList *b, int ea, int eb, int op);
int mojo_set_cmp(MojoSet *a, MojoSet *b, int ea, int eb, int op);
int mojo_value_cmp(int64_t a, int64_t b, int elem, int op);
int mojo_cmp_fold(int c, int op);

/* ── Python integration ─────────────────────────────────────────────────*/
void mojo_print(char *str);
void mojo_print_stderr(char *str);
char *mojo_input(char *prompt);

/* Python built-in functions for C strings */
/* Both take the handle at FULL width — a 32-bit `obj` silently truncated
 * every heap pointer past 4 GB and made isinstance(x, list/dict) answer NO
 * for real containers once the self-hosted compile grew past that. See the
 * definition in fire_runtime.c. */
int mojo_isinstance(int64_t obj, int type_id);
int mojo_isinstance_p(int64_t obj, int type_id);
int64_t mojo_read_type_tag(int64_t addr);
int64_t mojo_read_type_tag_safe(int64_t addr);
char *mojo_str(void *obj);  /* Flexible signature for both int and char* */
char *mojo_repr_int(int64_t obj);
char *mojo_repr_str(char *s);
char *mojo_repr_obj(int64_t addr);
char *mojo_repr_float(double v);
char *mojo_repr_list_doubles(MojoList *l);
char *mojo_repr_list_ints(MojoList *l);
char *mojo_repr_list_bools(MojoList *l);
char *mojo_repr_list_bytes(MojoList *l);
/* A list whose per-slot kinds are known but NOT uniform — a `struct.unpack`
   result for a format mixing int/float/bytes fields. `kinds` is one byte per
   slot: 'i' int, 'd' double, 's' bytes (see mojo_repr_list_kinds). */
char *mojo_repr_list_kinds(MojoList *l, const char *kinds);
/* Lists of 2-element PAIR lists (enumerate/zip): `[(0, 7), (1, 8)]`. The
   second slot's type is fixed at codegen time, hence one wrapper per
   kind — the raw slot cannot tell an int from a double. */
char *mojo_repr_list_intlists(MojoList *l);
char *mojo_repr_list_pairs(MojoList *l);
char *mojo_repr_list_pairs_s(MojoList *l);
char *mojo_repr_list_pairs_d(MojoList *l);
/* A list whose elements are inner lists/tuples sharing ONE per-slot kind
   pattern — `[(1.5, 2)]`, `[('a', 0, 1) for i in range(2)]`. `kinds` is that
   pattern, one byte per INNER slot, same alphabet as `mojo_repr_list_kinds`. */
char *mojo_repr_list_slotkinds(MojoList *l, const char *kinds);
char *mojo_bool_to_str(int b);
/* RESTORED, and it has a caller that `nm` on fire_runtime.o cannot see.
 *
 * This was removed as a dead stub whose body is `return 0`.  The
 * zero-caller measurement was taken against the runtime OBJECT, and the
 * caller is not in the runtime at all: gimple_codegen._RUNTIME_FUNCS maps the
 * Mojo builtin `type` to this C function, so any generated C for a module
 * that calls `type(...)` emits a reference to it.  Removing the declaration
 * therefore broke the self-hosted compile of the compiler's own closure:
 *
 *   myinterpreter.py:1750:44: error: 'mojo_type' undeclared here
 *       (not in a function); did you mean '_mojo_type'?
 *
 * "not in a function" is the tell -- the reference is in a DECLARATION, at
 * file scope, not a call, so it is a prototype the imported-symbol extern
 * block emits for a builtin it resolved to this name.
 *
 * The prototype is now `int mojo_type(int obj)` rather than the old variadic
 * form.  An ellipsis with no named parameter before it is a hard error in
 * clang (not a warning), which is what stopped the runtime compiling for the
 * x86-64 dylib.  `int obj` is this header's own convention for "any boxed
 * object" -- see mojo_hasattr and mojo_getattr immediately below -- and it is
 * a real prototype both compilers accept. */
int mojo_type(int obj);
int mojo_hasattr(int obj, char *attr);
int mojo_getattr(int obj, char *attr);
/* Real per-object dynamic-attribute storage (see mojo_obj_getattr's own
 * doc comment in fire_runtime.c) — no longer a no-op. */
void mojo_setattr(void *obj, char *attr, int64_t val);
void mojo_delattr(void *obj, char *attr);
char *mojo_str_cat(char *a, char *b);
char *mojo_str_from_int(int64_t v);
/* str(float) for a float dict key — see mojo_str_from_double's own comment in
 * fire_runtime.c for why the key has to be materialized as text at all. */
char *mojo_str_from_double(double v);
MojoList *mojo_divmod(int64_t a, int64_t b);
int64_t mojo_pow_mod(int64_t base, int64_t exp, int64_t mod);
char *mojo_hex(int64_t v);
char *mojo_oct(int64_t v);
char *mojo_bin(int64_t v);
char *mojo_int_literal_decimal(char *raw);
char *mojo_path_join(char *base, char *name);
char *mojo_cstr_repeat(char *s, int64_t n);

/* Additional Python builtins */
int64_t mojo_len(int obj);
void *mojo_range(int64_t start, int64_t stop);
void *mojo_range3(int64_t start, int64_t stop, int64_t step);
void *mojo_enumerate(void *iterable);
void *mojo_zip(void *a, void *b);
void *mojo_map(void *func, void *iterable);
void *mojo_filter(void *func, void *iterable);
void *mojo_make_list(void);
void *mojo_make_dict(void);
void *mojo_make_set(void);
void *mojo_make_tuple(void);
int64_t mojo_make_int(char *s);
double mojo_make_float(char *s);
int mojo_make_bool(int val);
double mojo_div_double(double a, double b);
float  mojo_div_float(float a, float b);
int64_t mojo_max(void *args);
int64_t mojo_min(void *args);
int64_t mojo_sum(void *args);
double  mojo_max_double(void *args);
double  mojo_min_double(void *args);
double mojo_sum_double(void *args);
/* Python bool repr: "True"/"False", not 1/0. */
char *mojo_repr_bool(int b);

/* A callable-valued parameter default naming an IMPORTED module's function
 * (`def probe(x, *, g=os.walk)`) — see the block comment on
 * mojo_unavailable_callable in fire_runtime.c for why padding it with 0 was a
 * SIGSEGV and why ONE no-parameter function is the right stub for every
 * arity. `mojo_set_unavailable_callable_name` arms the name the diagnostic
 * prints; the codegen emits it immediately before the call it belongs to. */
void    mojo_set_unavailable_callable_name(const char *name);
int64_t mojo_unavailable_callable(void);
void   *mojo_unavailable_callable_ptr(void);
/* An int64_t used as a C string: itself when it is a boxed char*, else its
   decimal string (see mojo_cstr_or_int_str's comment in the .c). */
char *mojo_cstr_or_int_str(int64_t v);
/* The SAME conversion for a caller that already knows `v` is an integer, so
   the runtime is not asked to guess: mojo_boxed_is_str is a range test and
   misclassifies every positive int64 in [2^31, 2^47) as a pointer, which is
   what turned `d[3000000000] = 1` into a `strcmp` of address 3000000000.
   Transient block, same ownership and same release rule as the entry above. */
char *mojo_int_str_transient(int64_t v);
void mojo_cstr_or_int_release(int64_t orig, char *s);
void *mojo_sorted(void *iterable);
/* sorted(x, key=f[, reverse]) — `keys` is the caller's per-element key list. */
MojoList *mojo_sorted_by_keys(MojoList *items, MojoList *keys, int reverse);
/* Reverse in place — used for sorted(x, reverse=True) with no key. */
MojoList *mojo_list_reversed(MojoList *l);
void *mojo_reversed(void *iterable);
MojoList *mojo_list_sorted_str(MojoList *src);
MojoList *mojo_set_sorted(MojoSet *s);
MojoList *mojo_set_to_list(MojoSet *s);  /* insertion order, see fire_runtime.c */
MojoList *mojo_dict_sorted_keys(MojoDict *d);
MojoList *mojo_dict_items_sorted(MojoDict *d);

/* Context manager protocol.
 * `mojo_obj_enter`/`mojo_obj_exit` used to be declared here and were defined
 * nowhere, and nothing called them: `with` lowers to the DEFINING struct's own
 * qualified method symbol (measured in generated C:
 * `std_runtime_tracing_Trace___enter__`, per doc/ABI.md's module-qualified
 * rule), never to a bare `int___enter__`-style dispatch helper. There is
 * nothing left in this section, and that is the correct state — a context
 * manager's entry point is its own `__enter__`, and a table row here saying
 * otherwise is a claim about the ABI that is false. */

/* Call a method by name on an opaque object */
int64_t mojo_obj_call1(int64_t obj, char *method, int64_t arg1);

/* Method stubs for compatibility */
int MojoList_append(MojoList *l, char *v);
int char_join(char *sep, MojoList *items);
int int_items(int obj);

/* Command-line arguments */
void mojo_set_argv(int argc, const char **argv);
MojoList *mojo_get_argv(void);
void mojo_replace_argv(MojoList *lst);

/* File I/O - opaque handle for Python file objects */
typedef void* MojoFileHandle;

/* mojo_open and mojo_close are defined by the Mojo stdlib (renamed from 'open'/'close').
   Do not declare them here to avoid conflicting types. */
/* mojo_write: stdlib mode redefines this with all-int64_t params (raw fd/buf/len) */
#ifndef __MOJO_STDLIB_MODE__
int64_t mojo_write(MojoFileHandle fh, char *data, int64_t len);
#endif
int64_t mojo_read(MojoFileHandle fh, char *buffer, int64_t len);
char *mojo_file_read_all(char *filename);

/* Module function stubs */
void *mojo_parse(char *source);
MojoList *mojo_py_tokenize(char *source);

/* Builtin file I/O - defined in runtime */
int64_t mojo_open_file(char *path);  /* opens a file, returns handle as int64_t */

/* Wrappers for C library functions that take pointer-to-pointer args.
   Generated GIMPLE code passes int64_t/void* opaque values; these wrappers
   accept void* and forward to the real typed C functions. */
#include <sys/types.h>
static ssize_t _mojo_getdelim(void *lp, void *n, int d, void *f) {
    return getdelim((char **)lp, (size_t *)n, d, (FILE *)f);
}
static ssize_t _mojo_getline(void *lp, void *n, void *f) {
    return getline((char **)lp, (size_t *)n, (FILE *)f);
}
#include <stdarg.h>
/* The C CLOCKS, declared by hand rather than by including <time.h>.
 *
 * This header included only stdint/stdio/setjmp/stdlib, so EVERY C function
 * compiled Mojo can call reached its definition with NO PROTOTYPE in scope --
 * verified by preprocessing this header alone, which declares neither
 * `time_t time(` nor `clock_t clock(`. The backend mints a weak stub for an
 * unregistered name and lets the linker prefer the real libSystem symbol, so
 * the LINK is fine and the CALL is not: an unprototyped call is assumed to
 * return int, which truncates a 64-bit time_t. `time()` still looks right
 * because whole seconds fit in 32 bits until 2038.
 *
 * That finding is real and it is NOT fully fixed here, and the reason is
 * worth recording. The obvious fix -- `#include <time.h>` -- is what this
 * comment originally said, and it breaks the build immediately:
 *
 *   std/time/time.mojo:369: error: conflicting types for 'clock_gettime'
 *
 * because that include also declares `time`, `clock`, `strftime`, `localtime`,
 * `gmtime`, `mktime` and `clock_gettime`, every one of which is in
 * _C_RESERVED_FUNCS and every one of which the stdlib reaches through
 * `external_call` with its own declaration. The module calls
 * `external_call["clock_gettime", Int32](Int32(id), Pointer(to=ts))` and its
 * emitted declaration disagrees with the real
 * `int clock_gettime(clockid_t, struct timespec *)`. That is a genuine bug in
 * the module and it was invisible precisely BECAUSE there was no prototype to
 * disagree with -- the call worked by ABI luck.
 *
 * Fixing it properly means auditing every `external_call` in the stdlib
 * against its real C signature, which is its own project and not something to
 * smuggle in behind a benchmark. So only the two counters actually needed are
 * declared here, with the TRUE prototypes from the SDK headers
 * (`__uint64_t clock_gettime_nsec_np(clockid_t)`, `uint64_t
 * mach_absolute_time(void)`), and `<time.h>` is included only off Apple, where
 * it carries no conflicting declarations.
 *
 * What this buys, measured: `clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW)`
 * resolves to real libSystem and is TYPED. Untyped it returned 0 on one read
 * and a real timestamp on the next, because the 64-bit return was read through
 * an implicit `int`. CLOCK_MONOTONIC (6) resolves 1000 ns and cannot time a
 * dispatch honestly; MONOTONIC_RAW (4) resolves 41 ns. Note `time.time_ns`
 * remains unavailable in compiled Mojo -- that is a separate gap; this is the
 * C route around it. */
#if !defined(__APPLE__)
#include <time.h>
#else
/* SIGNED, deliberately, and not because the SDK says so: the SDK prototype is
 * `__uint64_t clock_gettime_nsec_np(clockid_t)`, but the stdlib reaches this
 * symbol through `external_call["clock_gettime_nsec_np", Int64](...)` --
 * std/time/time.mojo:91 -- so the generated translation unit declares it
 * `int64_t (int32_t)`. Declaring it `unsigned long long` here is
 *
 *   error: conflicting types for 'clock_gettime_nsec_np';
 *          have 'int64_t(int32_t)' {aka 'long long int(int)'}
 *   note: previous declaration ... with type 'long long unsigned int(int)'
 *
 * and the ABI is identical either way, so the signedness that AGREES with the
 * only caller in the tree is the one to write. Unregistering the name instead
 * would put it back to an implicit `int` return, which is the bug this whole
 * declaration exists to fix.
 *
 * `mach_absolute_time` is declared signed for the same reason and on the same
 * reasoning; nothing in the stdlib calls it today, so nothing constrains it
 * yet, and consistency is the safer default for a future `external_call`. */
long long clock_gettime_nsec_np(int clockid);
long long mach_absolute_time(void);
#endif
static int _mojo_vprintf(char *fmt, void *ap) {
    /* va_list is passed as void* from GIMPLE code; cast is implementation-defined
       but safe on all targets where va_list is a pointer type. */
    return vprintf(fmt, *(va_list *)ap);
}

/* Flattened method stubs for generated GIMPLE code */
char *int_read(int64_t f);
int64_t int_write(int64_t f, char *data);
int64_t int_parse_module(int parser);

/* REPL and string utilities — stdlib-equivalent C implementations */
char *mojo_input(char *prompt);  /* Read line from stdin */
char *input(char *prompt);       /* weak in the runtime; stdlib's overrides it */

char *string_strip(char *str);         /* Strip whitespace */
char *string_lower(char *str);         /* Convert to lowercase */
char *string_upper(char *str);         /* Convert to uppercase */
/* str.casefold / swapcase / title / capitalize — had no lowering at all
 * and answered the unknown-method stub's raw int 0. */
char *mojo_str_casefold(char *str);
char *mojo_str_swapcase(char *str);
char *mojo_str_title(char *str);
char *mojo_str_capitalize(char *str);
char *mojo_str_lstrip(char *str);
char *mojo_str_rstrip(char *str);
char *mojo_str_rstrip_chars(char *str, char *chars);
char *mojo_str_lstrip_chars(char *str, char *chars);
char *mojo_str_rjust(char *s, int64_t width, char *fill);
char *mojo_str_ljust(char *s, int64_t width, char *fill);
char *mojo_str_center(char *s, int64_t width, char *fill);
char *mojo_str_expandtabs(char *str, int tabsize);
char *mojo_str_join(char *sep, MojoList *parts);
/* shlex.join(iterable): space-join, POSIX-quoting each element like CPython's
 * shlex.quote() (a distinct helper from mojo_str_join since shlex.join takes
 * no separator argument at all — see gimple_codegen.py's shlex.join dispatch). */
char *mojo_shlex_join(MojoList *parts);

/* ── SIMD select helper ──────────────────────────────────────────────────
 * Lowers SIMD[_Bool,N].select(a, b) → cond ? a : b for scalar path.   */
static inline int64_t _Bool_select(int64_t cond, int64_t a, int64_t b) {
    return cond ? a : b;
}

/* ── Integer arithmetic helpers ──────────────────────────────────────────
 * Lowered floor-division for use in __GIMPLE code.                      */
static inline int64_t __mojo_floordiv(int64_t a, int64_t b) {
    int64_t q = a / b;
    return q - (a % b != 0 && (a ^ b) < 0);
}

/* ── Python exception type sentinels (bootstrap) ────────────────────────
 * Used as integer tokens when registering exception types in interpreter scope. */
#define Exception          1001
#define BaseException      1002
#define KeyboardInterrupt  1003
#define EOFError           1004
#define ValueError         1005
#define TypeError          1006
#define RuntimeError       1007
#define StopIteration      1008
#define NameError          1009
#define AttributeError     1010
#define IndexError         1011
#define KeyError           1012
#define ImportError        1013
#define FileNotFoundError  1014
#define OverflowError      1015
#define ZeroDivisionError  1016
#define NotImplementedError 1017
#define SystemExit         1018
#define RecursionError     1019

/* ── Interpreter entry points ─────────────────────────────────────────────
 * Declared here because GENERATED code calls them and this header is what
 * generated code sees. Each one is defined by whoever links the image — for
 * `py_tokenize` that is the self-hosted compiler's own transpiled
 * `fire_compiler.py` (it is in `reflect._NO_MANGLE_FUNCS` and in
 * `GimpleGen._KNOWN_SIGS` for exactly that reason), NOT this runtime, which
 * is why the runtime dylib's reflection table must not advertise it. A
 * declaration with no definition is fine here and only here: the definition
 * is the linker's business, and the alternative — guessing at one — is a
 * wrong answer rather than a missing one. */

/* Python builtins that appear as function calls */
void setattr(int obj, int attr, int value);  /* setattr builtin */

/* String utility functions for method access */
char *int64_t_basename(char *path);    /* basename() from os.path */
char *int64_t_splitext(char *path);    /* splitext() from os.path */
char *int64_t_expanduser(char *path);  /* expanduser() from os.path */
char *int64_t_realpath(char *path);    /* Path.resolve()-style realpath (strict=False) */
int64_t _char_replace_impl(int64_t s, int64_t old_s, int64_t new_s);
/* str.replace() — macro to suppress implicit int/pointer conversion warnings */
#define char_replace(s, old, new) _char_replace_impl((int64_t)(s), (int64_t)(old), (int64_t)(new))

/* eval() stub — Python's eval() cannot run in C bootstrap; returns first arg unchanged */
int mojo_eval(int expr, MojoDict *globals, MojoDict *locals);

/* Module functions that are imported.
 * `py_tokenize`'s arity must match fire_compiler.py's definition
 * (`py_tokenize(src: str)`) or every --dump-full self-host closure fails
 * with "too many arguments to function 'py_tokenize'; expected 1, have 2"
 * at each of its ~20 call sites, plus a "conflicting types" at the
 * definition. A DEFAULTED parameter still occupies a parameter slot in the
 * lowered C signature and the self-host MATERIALIZES it at every call
 * site, so a defaulted `filename` is an ABI change however invisible it
 * looks at the Python call site. That is why the filename-carrying lexer
 * entry point is a separate function, `py_tokenize_named(src, filename)`,
 * whose arity the codegen derives from its definition like any other's.
 * test_selfhost.py's `pinned_prototypes_match_their_definitions` checks
 * this line against the source. */
MojoList *py_tokenize(char *source);  /* lexer.tokenize -> list[Token] */
/* Parser is defined as a struct in generated code; no function stub needed */
char *gimple_codegen_compile_to_gimple(char *source, int do_imports, char *filename);  /* compile_to_gimple function */

/* os.path bridge functions (called from compiled module_loader code) */
int int_isdir(int64_t marker, int64_t path);           /* os.path.isdir */
int int_isfile(int64_t marker, int64_t path);          /* os.path.isfile */
int64_t int_abspath(int64_t marker, int64_t path);     /* os.path.abspath */
int64_t int_dirname(int64_t marker, int64_t path);     /* os.path.dirname */
int int_exists(int64_t marker, int64_t path);          /* os.path.exists */
int64_t int_join(int64_t marker, int64_t base, int64_t part);  /* os.path.join(a, b) */
int64_t int_join_list(int64_t marker, int64_t path_list);      /* os.path.join(*list) */
MojoList *int64_t_path_split(char *path);              /* os.path.split(path) -> [head, tail] */
MojoList *int64_t_path_splitdrive(char *path);         /* os.path.splitdrive(path) -> [drive, tail] */
MojoList *int64_t_path_splitroot(char *path);          /* os.path.splitroot(path) -> [drive, root, tail] */
MojoList *mojo_listdir(char *path);                    /* os.listdir(path) -> list[str] */
int64_t int_getcwd(int64_t marker);                    /* os.getcwd */

/* Forward declare ModuleLoader (defined in generated code) */
typedef struct ModuleLoader ModuleLoader;

/* Module loader bridge functions (called from compiled module_loader code) */
int int_load_module(ModuleLoader *ml_ptr, char *module_name);                           /* ModuleLoader.load_module */
char *int_get_symbol_type(ModuleLoader *ml_ptr, char *module_name, char *symbol_name);  /* ModuleLoader.get_symbol_type */

/* Parser bridge functions (called from compiled parser code) */
int int__peek(int parser);                      /* Parser._peek method */
int int__advance(int parser);                   /* Parser._advance method */
int int__is_kw(int parser, char *keyword);      /* Parser._is_kw method */
int int__expect(int parser, char *kind);        /* Parser._expect method */
int int__skip_bracketed(int parser);            /* Parser._skip_bracketed method */
int int__parse_type_ann(int parser);            /* Parser._parse_type_ann method */

/* Type checking functions */
int int_is_pointer(int cls, void *type_id);    /* Check if type is pointer */
int int_is_float(int cls, void *type_id);      /* Check if type is float */
int int_is_int(int cls, void *type_id);        /* Check if type is int */
int int_analyze(int obj);                       /* Analyze function */

/* Import function (not used in C, but may be called) */
int int_import_module(int importlib_obj, char *module_name);  /* _python_import wrapper */

/* NOTE: there used to be a bare `int any(void *iterable);` declaration here
 * ("Python builtin any() function"). It was dead: gimple_codegen.py's real
 * any()/all() dispatch (_lower_builtin_all_any) has always emitted
 * mojo_list_any/mojo_list_all instead, never a bare `any` call — grep
 * confirms no caller anywhere in this codebase ever referenced this bare
 * symbol. Worse, being unprefixed (unlike every other runtime export,
 * which uses the mojo_ prefix precisely to avoid this) it collided at the
 * C level with any genuinely compiled Mojo module that defines its OWN
 * top-level `any` function whose overload-mangled C symbol happens to
 * collapse to the literal bare name (e.g. a variadic `def any(*choices):`,
 * which gets no overload suffix — see _overload_suffix/`_func_csym`) —
 * "conflicting types for 'any'" (real repro: Lib/tokenize.py's own
 * `def any(*choices): return group(*choices) + '*'`). Removed rather than
 * re-guarded, since it was never called by anything in the first place. */

/* Python builtin exception classes and types */
/* Exception defined by generated code, not here */

/* ── Regex substitution with callback (for re.sub(pattern, fn, src)) ────── */
/* callback receives (env, matched_substring) and returns replacement string */
char *mojo_re_sub_fn(char *pattern, char *(*callback)(void *, char *), void *env, char *src);
/* re.sub(pattern, repl, src) where repl is a plain replacement string */
char *mojo_re_sub_str(char *pattern, char *repl, char *src);
/* re.escape(p) — backslash-escape regex metacharacters in p */
char *mojo_re_escape(char *s);


/* ── Small, bounded regex engine (see fire_runtime.c's own section comment
 * and regex_compile.py for the compile-time parser/emitter; BACKLOG-CODEGEN.md
 * §4f for why this exists) ─────────────────────────────────────────────── */
typedef struct {
    int op;   /* 0=CHAR 1=ANY 2=CLASS 3=CONCAT 4=ALT 5=GROUP 6=REPEAT */
    int a, b, c, d, e, f;
} ReNode;

typedef struct { int lo, hi; } ReRange;
typedef struct { int offset, count; } ReClassInfo;

int mojo_regex_search(const ReNode *prog, const ReRange *ranges, const ReClassInfo *classinfo,
                       int root, int ngroups, const char *text, int64_t text_len, int64_t from_pos,
                       int64_t *out_start, int64_t *out_end, int64_t *gstart, int64_t *gend);
char *mojo_regex_lastgroup(const char **names, int ngroups, const int64_t *gstart);
char *mojo_regex_substr(const char *text, int64_t start, int64_t end);
char *mojo_regex_sub_fn(const ReNode *prog, const ReRange *ranges, const ReClassInfo *classinfo,
                         int root, int ngroups,
                         char *(*callback)(void *, char *), void *env, char *src);
char *mojo_regex_sub_str(const ReNode *prog, const ReRange *ranges, const ReClassInfo *classinfo,
                          int root, int ngroups, char *repl, char *src);

#ifdef __cplusplus
}
#endif
