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

/* Like __mojo_coro_yield, but also records whether this suspension is a
   real user value (is_wd=0) or a wait-descriptor being forwarded upward
   for the scheduler (is_wd=1) -- needed only by an ASYNC GENERATOR body,
   which mixes real `yield` values with `await`'s wait-descriptors on the
   same channel; __mojo_coro_last_yield_was_wd reads it back right after
   the matching _resume/_throw returns 1. A plain generator or plain
   async function never mixes the two, so they keep using
   __mojo_coro_yield and this flag is simply unread for them. */
int64_t  __mojo_coro_yield_tagged(MojoCoro *c, int64_t val_box, int is_wd);
int      __mojo_coro_last_yield_was_wd(MojoCoro *c);

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

/* ---- the TAGGED box: one word per element, and its kind beside it --------
   A `yield` whose tuple has a slot that is ITSELF a tuple of heterogeneous
   inner shape boxes that inner tuple as

       [ tag0, word0, tag1, word1, ... ]        (2*K int64 slots)

   carried in a MojoList and handed around as the single int64_t every box on
   this seam is. The ACCESSORS are here, next to the tag values, because a
   caller that cannot see the tags cannot read a tag back: `mojo_tagged_tag_dyn`
   answers one of the constants below and nothing else states what they mean.
   Definitions are in fire_coro_gen.c.

   Declared here rather than left to the definitions, and that is a fix rather
   than a formality: these six names carry the runtime's `mojo_` prefix and were
   EXPORTED by the runtime dylib while no header declared them, so
   `formal/model.py`'s `gimple_runtime_callable` refused every call to them for
   want of a signature — five word-shaped entry points that were already written,
   already compiled into the library and already linkable, refused for a reason
   that is about the DECLARATION and not about the target.  `mojo_tagged_double`
   and `mojo_double_bits` are declared here too and are still correctly refused:
   they cross the boundary as a `double`, which is one machine word but not one
   value on the formal path (`_WORD_SCALARS`). */
enum { MOJO_TAG_INT = 0, MOJO_TAG_STR = 1, MOJO_TAG_DOUBLE = 2,
       MOJO_TAG_LIST = 3, MOJO_TAG_NONE = 4 };

/* `box` is the tagged box as an int64_t, `p` the 0-based element index. The
   typed accessors answer 0 (or NULL) unless the tag at `p` is their own, which
   is what makes one unpack correct regardless of which yield site produced the
   value; the `_dyn` pair reads the raw word and the raw tag. An out-of-range `p`
   reads as tag MOJO_TAG_NONE and word 0 rather than trapping. */
int64_t  mojo_tagged_int(int64_t box, int64_t p);
int64_t  mojo_tagged_word_dyn(int64_t box, int64_t p);
int64_t  mojo_tagged_tag_dyn(int64_t box, int64_t p);
char    *mojo_tagged_str(int64_t box, int64_t p);
int64_t  mojo_tagged_list(int64_t box, int64_t p);
double   mojo_tagged_double(int64_t box, int64_t p);

/* The IEEE-754 bits of a double as a word, and nothing else — the float rule
   above is why a formal image cannot use either half of this pair. */
int64_t  mojo_double_bits(double d);

#ifdef __cplusplus
}
#endif

#endif /* MOJO_CORO_H */
