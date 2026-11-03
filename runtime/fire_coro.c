/* mojo_coro.c -- Layer 2: the architecture-independent coroutine runtime
   that implements SEAM A (mojo_coro.h) on top of Layer 3's fcontext
   primitive (mojo_coro_ctx.h). doc/COROUTINE.html §5.3.

   Model: strictly one-at-a-time. Exactly one of {resumer, body} runs at
   any instant -- a baton pass, never concurrency. The body runs on its own
   mmap'd stack (guard page below); it is *parked*, not destroyed, while
   suspended, which is why the ordinary setjmp/longjmp exception machinery
   (and everything else the normal codegen emits) works verbatim inside a
   coroutine body with no special-casing.
*/
#include "fire_coro.h"
#include "fire_coro_ctx.h"

#include <setjmp.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>

/* The exception machinery we ride on. Declared locally (rather than
   #include "fire_runtime.h") so Layer 2 stays decoupled from that header's
   GNU-extension prototypes; the real build links the real fire_runtime.c,
   the unit test links test_mojo_coro_exc_stub.c -- both define these with
   identical semantics. */
#ifndef MOJO_EXC_STACK_MAX
#define MOJO_EXC_STACK_MAX 64
#endif
extern jmp_buf _mojo_exc_stack[MOJO_EXC_STACK_MAX];
extern int     _mojo_exc_top;
extern void    mojo_raise(void);
extern void    mojo_exc_type_set(int64_t);
extern int64_t mojo_exc_type_get(void);
extern void    mojo_exc_msg_set(char *);
extern char   *mojo_exc_msg_get(void);
extern void    mojo_exc_obj_set(void *);
extern void   *mojo_exc_obj_get(void);
extern void    mojo_exc_pending_set(int);
extern int     mojo_exc_pending_get(void);

/* Deterministic exception-class tags -- must match GimpleGen._exc_type_id
   ((zlib.crc32(b"Name") & 0x7fffffff) or 1). Same hardcoding pattern as
   fire_runtime.c's _MOJO_EXC_TAG_* block. */
#define MOJO_TAG_GENERATOREXIT  2146172193
#define MOJO_TAG_STOPITERATION   590612416

/* Max try/with nesting depth a body may hold open ACROSS a yield. Bodies
   that yield outside any try (the overwhelming common case) use 0 of
   these. Bump if a real generator legitimately exceeds it. */
#define MOJO_CORO_EXC_SLICE_MAX 16

#ifndef MOJO_CORO_DEFAULT_STACK
#define MOJO_CORO_DEFAULT_STACK (256 * 1024)
#endif

struct MojoCoro {
    mojo_fctx_t   resume_pt;    /* jump here to (re)enter the body        */
    mojo_fctx_t   caller_pt;    /* body jumps here to suspend             */
    void         *map_base;     /* mmap region (guard page + stack)       */
    size_t        map_size;
    void        (*body)(MojoCoro *, void *env);
    void         *env;

    int           status;       /* MOJO_CORO_{SUSPENDED,RUNNING,DONE}     */
    int           started;
    int           last_wd;      /* was the most recent yield a wait-descriptor
                                    (async generator only -- see mojo_coro.h) */
    int64_t       yield_box;    /* value handed OUT at a yield            */
    int64_t       send_box;     /* value handed IN at a resume            */
    int64_t       ret_box;      /* body's return value (status==DONE)     */

    int           raised;       /* body unwound with an uncaught exc      */
    int64_t       exc_type;
    char         *exc_msg;
    void         *exc_obj;

    int           inject;       /* 0 none; 1 throw; 2 close (GeneratorExit)*/
    int64_t       inj_type;
    char         *inj_msg;
    void         *inj_obj;

    /* exception-stack bookkeeping while this coroutine is parked */
    int           exc_base;
    int           exc_slice_n;
    int64_t       exc_type_save;
    char         *exc_msg_save;
    void         *exc_obj_save;
    int           exc_pending_save;
    jmp_buf       exc_slice[MOJO_CORO_EXC_SLICE_MAX];
};

/* The coroutine currently executing its body (NULL == a resumer context).
   Strictly serialized, so a plain global is safe -- and it lets
   __mojo_coro_yield be called without threading the handle through every
   frame if a future Layer-1 shape wants that. */
static MojoCoro *g_active;

/* ── entry trampoline (runs on the coroutine stack) ───────────────────── */

static void
coro_trampoline(mojo_xfer_t in)
{
    MojoCoro *c = (MojoCoro *)in.data;
    c->caller_pt = in.from;

    /* Top-level landing pad: an exception the body does not catch unwinds
       to here (its inner handlers pop _mojo_exc_top back down to this
       frame first -- standard). */
    _mojo_exc_top += 1;
    if (setjmp(_mojo_exc_stack[_mojo_exc_top]) == 0) {
        c->body(c, c->env);
        _mojo_exc_top -= 1;                 /* normal fall-off */
    } else {
        c->raised   = 1;
        c->exc_type = mojo_exc_type_get();
        c->exc_msg  = mojo_exc_msg_get();
        c->exc_obj  = mojo_exc_obj_get();
        _mojo_exc_top = c->exc_base;        /* discard the body's frames */
    }
    c->status = MOJO_CORO_DONE;
    g_active  = NULL;
    mojo_jump_fctx(c->caller_pt, c);        /* final hand-back -- no return */
    for (;;) { }                            /* unreachable */
}

/* ── stack allocation ────────────────────────────────────────────────── */

static int
coro_alloc_stack(MojoCoro *c, size_t want)
{
    long pg = sysconf(_SC_PAGESIZE);
    if (pg <= 0) pg = 4096;
    if (want == 0) {
        const char *e = getenv("MOJO_CORO_STACK");
        want = e ? (size_t)strtoull(e, 0, 0) : (size_t)MOJO_CORO_DEFAULT_STACK;
        if (want < 32 * 1024) want = 32 * 1024;
    }
    /* round the usable stack up to a page, add one guard page below it */
    size_t usable = (want + (size_t)pg - 1) & ~((size_t)pg - 1);
    size_t total  = usable + (size_t)pg;

    void *m = mmap(NULL, total, PROT_READ | PROT_WRITE,
                   MAP_PRIVATE | MAP_ANON, -1, 0);
    if (m == MAP_FAILED) return -1;
    /* guard page at the low address (stack grows down into it => SIGSEGV,
       not silent neighbour corruption) */
    if (mprotect(m, (size_t)pg, PROT_NONE) != 0) {
        munmap(m, total);
        return -1;
    }
    c->map_base = m;
    c->map_size = total;
    return 0;
}

/* ── SEAM A ─────────────────────────────────────────────────────────── */

MojoCoro *
__mojo_coro_new(void (*body)(MojoCoro *, void *env), void *env, size_t stack)
{
    MojoCoro *c = (MojoCoro *)calloc(1, sizeof *c);
    if (!c) return 0;
    c->body = body;
    c->env  = env;
    c->status = MOJO_CORO_SUSPENDED;
    if (coro_alloc_stack(c, stack) != 0) { free(c); return 0; }

    unsigned char *top = (unsigned char *)c->map_base + c->map_size;
    c->resume_pt = mojo_make_fctx(top, c->map_size - (size_t)sysconf(_SC_PAGESIZE),
                                  coro_trampoline);
    return c;
}

/* Switch into the body; shared by resume/throw/close. Returns 1 if the
   body yielded, 0 if it finished (or unwound). */
static int
coro_run(MojoCoro *c, int64_t send_box)
{
    c->send_box = send_box;
    c->exc_base = _mojo_exc_top;
    c->status   = MOJO_CORO_RUNNING;
    c->started  = 1;

    MojoCoro *prev = g_active;
    g_active = c;
    mojo_xfer_t r = mojo_jump_fctx(c->resume_pt, c);
    g_active = prev;
    c->resume_pt = r.from;

    return c->status != MOJO_CORO_DONE;
}

int
__mojo_coro_resume(MojoCoro *c, int64_t send_box, int64_t *out)
{
    if (c->status == MOJO_CORO_DONE) {
        if (c->raised) {
            c->raised = 0;
            mojo_exc_type_set(c->exc_type);
            mojo_exc_msg_set(c->exc_msg);
            mojo_exc_obj_set(c->exc_obj);
            mojo_raise();                  /* re-raise on the resumer's live stack */
        }
        if (out) *out = c->ret_box;
        return 0;
    }
    if (coro_run(c, send_box)) { if (out) *out = c->yield_box; return 1; }
    if (c->raised) {
        c->raised = 0;
        mojo_exc_type_set(c->exc_type);
        mojo_exc_msg_set(c->exc_msg);
        mojo_exc_obj_set(c->exc_obj);
        mojo_raise();
    }
    if (out) *out = c->ret_box;
    return 0;
}

int
__mojo_coro_throw(MojoCoro *c, int64_t exc_type, char *exc_msg,
                  void *exc_obj, int64_t *out)
{
    if (!c->started || c->status == MOJO_CORO_DONE) {
        /* throw before first resume / into a finished generator: raise here */
        mojo_exc_type_set(exc_type);
        mojo_exc_msg_set(exc_msg);
        mojo_exc_obj_set(exc_obj);
        mojo_raise();
        return 0;                          /* unreachable */
    }
    c->inject   = 1;
    c->inj_type = exc_type;
    c->inj_msg  = exc_msg;
    c->inj_obj  = exc_obj;
    if (coro_run(c, 0)) { if (out) *out = c->yield_box; return 1; }
    if (c->raised) {
        c->raised = 0;
        mojo_exc_type_set(c->exc_type);
        mojo_exc_msg_set(c->exc_msg);
        mojo_exc_obj_set(c->exc_obj);
        mojo_raise();
    }
    if (out) *out = c->ret_box;
    return 0;
}

int64_t
__mojo_coro_yield(MojoCoro *c, int64_t val_box)
{
    /* --- save this coroutine's exception state, hand control back --- */
    int n = _mojo_exc_top - c->exc_base;
    if (n < 0) n = 0;
    if (n > MOJO_CORO_EXC_SLICE_MAX) n = MOJO_CORO_EXC_SLICE_MAX;   /* clamp; see MAX note */
    if (n > 0)
        memcpy(c->exc_slice, &_mojo_exc_stack[c->exc_base + 1],
               (size_t)n * sizeof(jmp_buf));
    c->exc_slice_n       = n;
    c->exc_type_save     = mojo_exc_type_get();
    c->exc_msg_save      = mojo_exc_msg_get();
    c->exc_obj_save      = mojo_exc_obj_get();
    c->exc_pending_save  = mojo_exc_pending_get();
    _mojo_exc_top = c->exc_base;

    c->yield_box = val_box;
    c->status    = MOJO_CORO_SUSPENDED;

    mojo_xfer_t r = mojo_jump_fctx(c->caller_pt, c);
    c->caller_pt = r.from;

    /* --- resumed: restore our exception state --- */
    c->status = MOJO_CORO_RUNNING;
    if (c->exc_slice_n > 0)
        memcpy(&_mojo_exc_stack[c->exc_base + 1], c->exc_slice,
               (size_t)c->exc_slice_n * sizeof(jmp_buf));
    _mojo_exc_top = c->exc_base + c->exc_slice_n;
    mojo_exc_type_set(c->exc_type_save);
    mojo_exc_msg_set(c->exc_msg_save);
    mojo_exc_obj_set(c->exc_obj_save);
    mojo_exc_pending_set(c->exc_pending_save);

    if (c->inject) {
        int mode = c->inject;
        c->inject = 0;
        mojo_exc_type_set(mode == 2 ? (int64_t)MOJO_TAG_GENERATOREXIT : c->inj_type);
        mojo_exc_msg_set(mode == 2 ? 0 : c->inj_msg);
        mojo_exc_obj_set(mode == 2 ? 0 : c->inj_obj);
        mojo_raise();                       /* longjmp within the (current) body stack */
    }
    return c->send_box;
}

int64_t
__mojo_coro_return_value(MojoCoro *c)
{
    return c->ret_box;
}

int64_t
__mojo_coro_yield_tagged(MojoCoro *c, int64_t val_box, int is_wd)
{
    c->last_wd = is_wd;
    return __mojo_coro_yield(c, val_box);
}

int
__mojo_coro_last_yield_was_wd(MojoCoro *c)
{
    return c->last_wd;
}

/* The opaque env pointer passed to __mojo_coro_new -- Layer 1's shim
   (mojo_coro_gen.c) uses it to reach a body's stashed arguments. */
void *
__mojo_coro_env(MojoCoro *c)
{
    return c ? c->env : 0;
}

/* internal companion to the getter above -- the lowered `return e` calls
   this then falls off the body. Part of coro-abi/1. */
void
__mojo_coro_set_return(MojoCoro *c, int64_t box)
{
    c->ret_box = box;
}

static void
coro_free(MojoCoro *c)
{
    if (c->map_base) munmap(c->map_base, c->map_size);
    free(c);
}

void
__mojo_coro_destroy(MojoCoro *c)
{
    if (!c) return;
    if (c->started && c->status == MOJO_CORO_SUSPENDED) {
        c->inject = 2;                      /* close: GeneratorExit at the yield point */
        (void)coro_run(c, 0);
        if (c->status == MOJO_CORO_DONE && c->raised) {
            int64_t t = c->exc_type;
            c->raised = 0;
            if (t != MOJO_TAG_GENERATOREXIT && t != MOJO_TAG_STOPITERATION) {
                /* an error escaped the cleanup path -- surface it */
                mojo_exc_type_set(t);
                mojo_exc_msg_set(c->exc_msg);
                mojo_exc_obj_set(c->exc_obj);
                coro_free(c);
                mojo_raise();
                return;                     /* unreachable */
            }
        }
        /* if the body swallowed GeneratorExit and yielded again, CPython
           raises RuntimeError("generator ignored GeneratorExit"); we just
           drop it and free -- revisit if a real case needs the diagnostic */
    }
    coro_free(c);
}
