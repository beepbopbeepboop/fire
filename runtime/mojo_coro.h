/* mojo_coro.h -- SEAM A: the coroutine-backend ABI (doc/COROUTINE.html §7,
   version coro-abi/1). Layer 1 (gimple_gen_coro.py) emits calls to exactly
   these six primitives and nothing else coroutine-specific.

   The in-tree backend is runtime/mojo_coro.c (stack-switch, on Layer 3's
   fcontext primitive). A conforming __builtin_coro_* lowering of the same
   six is a drop-in replacement (the deferred GCC Mojo-frontend backend).

   A generator/async body is lowered to an ordinary C function
       void <base>_body(MojoCoro *c, void *env)
   by the normal codegen, with only these rewrites: `yield e` ->
   __mojo_coro_yield; `return e` -> set c's return box + fall off;
   `await e` -> drive + suspend to the scheduler. Everything else (nested
   loops, try/finally, with, comprehensions, match) is unchanged because
   the body runs on a real stack.
*/
#ifndef MOJO_CORO_H
#define MOJO_CORO_H

#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct MojoCoro MojoCoro;

/* status values reported via *out sign / the return code of _resume */
enum { MOJO_CORO_SUSPENDED = 0, MOJO_CORO_RUNNING = 1, MOJO_CORO_DONE = 2 };

/* Create a suspended coroutine. `body` runs on its own stack on the first
   _resume. `env` is an opaque heap pointer the caller owns until _destroy.
   `stack` 0 = backend default (MOJO_CORO_STACK env, else 256 KiB). */
MojoCoro *__mojo_coro_new(void (*body)(MojoCoro *, void *env),
                          void *env, size_t stack);

/* Run `c` from its suspension point.
     returns 1  -> hit __mojo_coro_yield ; *out = yielded box
     returns 0  -> body returned          ; *out = return box
   If the body unwound with an uncaught exception, this re-raises it in the
   caller's context (via mojo_raise) instead of returning.
   Precondition: c is suspended (not running, not done). */
int      __mojo_coro_resume(MojoCoro *c, int64_t send_box, int64_t *out);

/* Callable only lexically within `body`. Suspends, hands `val_box` to the
   matching _resume/_throw, returns the next send box. May instead raise
   (a pending _throw / _destroy exception) in the body's context. */
int64_t  __mojo_coro_yield(MojoCoro *c, int64_t val_box);

/* The return box. Valid only after _resume/_throw returned 0. */
int64_t  __mojo_coro_return_value(MojoCoro *c);

/* Internal companion to the getter: the lowered `return e` calls this then
   falls off the body. Part of coro-abi/1 (Layer 1 emits it, not user
   code). */
void     __mojo_coro_set_return(MojoCoro *c, int64_t box);

/* Like _resume, but the suspended __mojo_coro_yield raises `exc` (a typed
   exception: type tag + optional message/obj) rather than returning a
   send value. Same return contract as _resume. */
int      __mojo_coro_throw(MojoCoro *c, int64_t exc_type, char *exc_msg,
                           void *exc_obj, int64_t *out);

/* If `c` is suspended, resume it once with GeneratorExit raised at the
   suspension point so with/finally run; swallow GeneratorExit and
   StopIteration escaping that unwind, propagate anything else. Then free
   all backend resources (NOT env -- the caller owns that). Idempotent on a
   done coroutine. */
void     __mojo_coro_destroy(MojoCoro *c);

/* ---- optional concrete generator handle -------------------------------
   Layer 1 may use this as the `MojoGenerator *` the language-level
   consumers pass around; it is opaque to them (never dereferenced). The
   per-generator <base>_start/_resume/_value/_destroy trampolines Layer 1
   emits fill it in. Kept here so the shape is one documented thing. */
typedef struct MojoGenerator {
    MojoCoro *coro;
    void     *env;         /* freed by <base>_destroy */
    int64_t   value;       /* last yielded box   (<base>_value reads this) */
    int64_t   send;        /* next send box      (set before <base>_resume) */
    int64_t   retval;      /* return box once done */
    int       done;
} MojoGenerator;

#ifdef __cplusplus
}
#endif

#endif /* MOJO_CORO_H */
