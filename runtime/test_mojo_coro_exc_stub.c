/* test_mojo_coro_exc_stub.c -- minimal standalone implementation of the
   handful of mojo_runtime exception symbols that runtime/mojo_coro.c uses,
   so the Layer 2 unit test (test_mojo_coro.c) links without dragging in
   mojo_runtime.c (which needs <Python.h>). The real build links the real
   mojo_runtime.c; this is test scaffolding only and mirrors that file's
   semantics for these symbols exactly. */
#include <setjmp.h>
#include <stdint.h>
#include <stdlib.h>

#define MOJO_EXC_STACK_MAX 64
jmp_buf _mojo_exc_stack[MOJO_EXC_STACK_MAX];
int     _mojo_exc_top = -1;

static int64_t s_type;
static char   *s_msg;
static void   *s_obj;
static int     s_pending;

void    mojo_exc_type_set(int64_t t) { s_type = t; }
int64_t mojo_exc_type_get(void)      { return s_type; }
void    mojo_exc_msg_set(char *m)    { s_msg = m; }
char   *mojo_exc_msg_get(void)       { return s_msg; }
void    mojo_exc_obj_set(void *o)    { s_obj = o; }
void   *mojo_exc_obj_get(void)       { return s_obj; }
void    mojo_exc_pending_set(int v)  { s_pending = v; }
int     mojo_exc_pending_get(void)   { return s_pending; }

void mojo_exc_pop(void) { --_mojo_exc_top; }

void mojo_raise(void)
{
    if (_mojo_exc_top < 0) { abort(); }
    longjmp(_mojo_exc_stack[_mojo_exc_top], 1);
}

/* minimal MojoList so mojo_coro_gen.c's __mojo_tuple_box_* link in the
   unit test (the real build links runtime/mojo_runtime.c) */
typedef struct { int64_t *d; int n, cap; } _TestList;
void *mojo_list_new(void)
{
    _TestList *l = calloc(1, sizeof *l);
    return l;
}
void mojo_list_append_int(void *lp, int64_t v)
{
    _TestList *l = lp;
    if (l->n == l->cap) {
        l->cap = l->cap ? l->cap * 2 : 4;
        l->d = realloc(l->d, l->cap * sizeof(int64_t));
    }
    l->d[l->n++] = v;
}
int64_t mojo_list_get_int(void *lp, int64_t i)
{
    _TestList *l = lp;
    return (i >= 0 && i < l->n) ? l->d[i] : 0;
}
