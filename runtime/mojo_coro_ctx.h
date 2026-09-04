/* mojo_coro_ctx.h -- SEAM B: the entire architecture-specific surface of the
   Mojo stack-switch coroutine primitive (doc/COROUTINE.html, Layer 3).

   This is the boost.context / libaco "fcontext" shape: three functions that
   do nothing but shuffle callee-saved registers and the stack pointer. No
   heap, no libc, no OS calls. Everything above this header (Layer 2,
   runtime/mojo_coro.c) is portable C.

   Porting to a new architecture == adding ONE file that implements these
   three symbols (see mojo_coro_ctx_aarch64.S for the model, and
   mojo_coro_ctx_generic.c for the ucontext fallback used until an arch has
   its own .S).

   Contract
   --------
   A "context" is an opaque pointer to saved machine state sitting at the top
   of some stack. Switching to a context restores its callee-saved registers
   and stack pointer and resumes it exactly where it last called
   mojo_jump_fctx (or, for a fresh context, enters its entry function).

   Exactly one context runs at a time. There is no preemption, no
   concurrency, no shared mutable state crossing a switch -- only the single
   `void *data` word in mojo_xfer_t. This is what keeps the runtime's
   "single-threaded, no locks" invariant honest.
*/
#ifndef MOJO_CORO_CTX_H
#define MOJO_CORO_CTX_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Opaque handle to a saved context (in practice: the saved stack pointer,
   pointing at a block of spilled callee-saved registers). */
typedef void *mojo_fctx_t;

/* The result of a context switch: `from` is the context we just suspended
   (switch back to it to resume the other side), `data` is the word the
   switcher passed us. Returned in the first two integer registers on every
   supported ABI. */
typedef struct {
    mojo_fctx_t from;
    void       *data;
} mojo_xfer_t;

/* Build a context at the top of the stack region [stack_base, stack_base+size).
   `stack_top` must be the HIGH address (stack_base + size). On the first
   mojo_jump_fctx into the returned context, control enters `entry` with the
   mojo_xfer_t {from, data} of that jump as its argument. `entry` must never
   return (it should end by jumping to some other context). */
mojo_fctx_t mojo_make_fctx(void *stack_top, size_t size,
                           void (*entry)(mojo_xfer_t));

/* Suspend the current context, switch to `to`, delivering `data`. Returns
   when some other context switches back here, carrying that switch's
   {from, data}. */
mojo_xfer_t mojo_jump_fctx(mojo_fctx_t to, void *data);

/* Like mojo_jump_fctx, but before `to` resumes, run `fn` ON `to`'s STACK
   with the switch's {from, data}; `to` then resumes with fn's returned
   mojo_xfer_t. Used to raise an exception (GeneratorExit) at a coroutine's
   suspension point for a clean unwind on destroy. */
mojo_xfer_t mojo_ontop_fctx(mojo_fctx_t to, void *data,
                            mojo_xfer_t (*fn)(mojo_xfer_t));

#ifdef __cplusplus
}
#endif

#endif /* MOJO_CORO_CTX_H */
