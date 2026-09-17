/* mojo_coro_ctx_generic.c -- portable Layer 3 (SEAM B) fallback built on
   POSIX <ucontext.h>. Correct everywhere ucontext exists; slower than a
   hand-written .S (a full sigprocmask syscall per switch on some libcs).

   Used for any architecture that does not yet have its own
   mojo_coro_ctx_<arch>.S. It is also the differential oracle the arch .S
   files are validated against (runtime/test_mojo_coro_ctx.c builds both).

   Selection is by the build (a single -D or file choice); this file and an
   arch .S are mutually exclusive in a link. */
#define _XOPEN_SOURCE 700
#include "fire_coro_ctx.h"

/* <ucontext.h> is deprecated on macOS (still present and functional on
   arm64); this file is the portability fallback, not the primary path. */
#if defined(__GNUC__)
# pragma GCC diagnostic ignored "-Wdeprecated-declarations"
#endif

#include <ucontext.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>

/* One of these sits at the top of each coroutine stack (and one bootstrap
   instance represents whatever native context first calls into here). */
typedef struct mojo_uc {
    ucontext_t                uc;
    void                    (*entry)(mojo_xfer_t);
    mojo_xfer_t               in;        /* xfer being delivered INTO us   */
    mojo_xfer_t             (*ontop_fn)(mojo_xfer_t);  /* run on resume, once */
} mojo_uc;

/* The context currently executing. NULL until the first jump, at which
   point a bootstrap mojo_uc is minted for the native caller so it can be
   switched back to. Strictly serialized => a plain global is safe. */
static mojo_uc *g_cur;

static void
uc_start(void)
{
    /* The jumping side set g_cur to us before swapcontext'ing in. */
    mojo_uc *me = g_cur;
    me->entry(me->in);
    /* entry() must not return. */
    abort();
}

static mojo_uc *
uc_bootstrap_self(void)
{
    if (!g_cur) {
        mojo_uc *b = (mojo_uc *)calloc(1, sizeof *b);
        assert(b);
        g_cur = b;
    }
    return g_cur;
}

mojo_fctx_t
mojo_make_fctx(void *stack_top, size_t size, void (*entry)(mojo_xfer_t))
{
    /* Carve the mojo_uc out of the caller-provided stack region so Layer 2
       owns exactly one allocation (the stack) per coroutine. */
    unsigned char *top  = (unsigned char *)stack_top;
    unsigned char *base = top - size;

    /* mojo_uc at the very top, 16-byte aligned; ucontext gets the rest. */
    uintptr_t slot = ((uintptr_t)top - sizeof(mojo_uc)) & ~(uintptr_t)0xF;
    mojo_uc  *m    = (mojo_uc *)slot;
    memset(m, 0, sizeof *m);
    m->entry = entry;

    getcontext(&m->uc);
    m->uc.uc_stack.ss_sp   = base;
    m->uc.uc_stack.ss_size = (size_t)((unsigned char *)slot - base);
    m->uc.uc_link          = NULL;
    makecontext(&m->uc, uc_start, 0);
    return m;
}

static mojo_xfer_t
uc_switch(mojo_fctx_t to_, void *data,
          mojo_xfer_t (*ontop_fn)(mojo_xfer_t))
{
    mojo_uc *to   = (mojo_uc *)to_;
    mojo_uc *self = uc_bootstrap_self();

    to->in.from   = self;
    to->in.data   = data;
    to->ontop_fn  = ontop_fn;

    g_cur = to;
    swapcontext(&self->uc, &to->uc);
    /* --- resumed: someone switched back into `self` --- */

    if (self->ontop_fn) {
        mojo_xfer_t (*f)(mojo_xfer_t) = self->ontop_fn;
        self->ontop_fn = NULL;
        return f(self->in);
    }
    return self->in;
}

mojo_xfer_t
mojo_jump_fctx(mojo_fctx_t to, void *data)
{
    return uc_switch(to, data, NULL);
}

mojo_xfer_t
mojo_ontop_fctx(mojo_fctx_t to, void *data, mojo_xfer_t (*fn)(mojo_xfer_t))
{
    return uc_switch(to, data, fn);
}
