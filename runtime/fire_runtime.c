#include "fire_runtime.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>
#include <stdint.h>
#include <inttypes.h>
#include <ctype.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <errno.h>
#include <dirent.h>
#if defined(__APPLE__)
#include <malloc/malloc.h>
#define MOJO_MALLOC_USABLE_SIZE(p) malloc_size(p)
#define MOJO_HAVE_MALLOC_USABLE_SIZE 1
#elif defined(__linux__)
#include <malloc.h>
#define MOJO_MALLOC_USABLE_SIZE(p) malloc_usable_size(p)
#define MOJO_HAVE_MALLOC_USABLE_SIZE 1
#else
#define MOJO_HAVE_MALLOC_USABLE_SIZE 0
#endif

#define USE_PYTHON 0

#if USE_PYTHON
#include <Python.h>
#endif

/* Exception stack */
jmp_buf _mojo_exc_stack[MOJO_EXC_STACK_MAX];
int     _mojo_exc_top = -1;

void mojo_exc_pop(void)
{
    --_mojo_exc_top;
}

/* Cleanup-thunk registry — see fire_runtime.h for the design rationale.
 * Kind-tagged rather than raw function pointers: every entry is one of
 * exactly three known container frees, so a switch in the unwind loop
 * below is simpler and avoids introducing function-pointer calls into a
 * hot path for no benefit.
 *
 * The three `_STACK` kinds (doc/OWNERSHIP_MODEL.md Phase 6) are for a
 * stack-allocated candidate (gimple_gen_infra.py's `maybe_stack_alloc_
 * owned_ctor`): the struct itself lives in the OWNING FUNCTION's own
 * stack frame, not the heap, so an exception unwinding PAST that frame
 * must tear down only its internal buffers (`mojo_*_destroy`) and never
 * call `free()` on the struct pointer itself (`mojo_*_free` would free a
 * stack address — undefined behavior, corrupting the heap allocator). */
typedef enum { MOJO_CLEANUP_DICT, MOJO_CLEANUP_LIST, MOJO_CLEANUP_SET,
               MOJO_CLEANUP_DICT_STACK, MOJO_CLEANUP_LIST_STACK, MOJO_CLEANUP_SET_STACK,
               MOJO_CLEANUP_PTR,   /* a plain malloc/calloc block: a struct instance */
               MOJO_CLEANUP_LIST_STRS, /* a list that owns its string elements */
               MOJO_CLEANUP_CLOSURE   /* a bound method plus the env it owns */
             } mojo_cleanup_kind_t;
#define MOJO_CLEANUP_STACK_MAX 8192
static mojo_cleanup_kind_t _mojo_cleanup_kind[MOJO_CLEANUP_STACK_MAX];
static void                *_mojo_cleanup_ptr[MOJO_CLEANUP_STACK_MAX];
int _mojo_cleanup_top = -1;
/* Indexed by _mojo_exc_top (the try/except LEVEL, not a stack of its own):
 * the cleanup-stack depth that level's own exception path should unwind
 * back down to. */
static int _mojo_cleanup_checkpoint[MOJO_EXC_STACK_MAX];

static void _mojo_cleanup_push(mojo_cleanup_kind_t kind, void *ptr)
{
    if (_mojo_cleanup_top + 1 >= MOJO_CLEANUP_STACK_MAX) {
        /* Degrade to today's pre-existing "leaks on an exception path"
         * behavior rather than crash a program that would otherwise run
         * fine — this registry is a memory-usage improvement, not a
         * correctness requirement for programs that never raise. */
        fprintf(stderr, "mojo_cleanup_push: cleanup stack overflow (>%d live owned locals)\n",
                MOJO_CLEANUP_STACK_MAX);
        return;
    }
    ++_mojo_cleanup_top;
    _mojo_cleanup_kind[_mojo_cleanup_top] = kind;
    _mojo_cleanup_ptr[_mojo_cleanup_top] = ptr;
}

void mojo_cleanup_push_dict(void *p) { _mojo_cleanup_push(MOJO_CLEANUP_DICT, p); }
void mojo_cleanup_push_list(void *p) { _mojo_cleanup_push(MOJO_CLEANUP_LIST, p); }
void mojo_cleanup_push_set(void *p)  { _mojo_cleanup_push(MOJO_CLEANUP_SET, p); }
void mojo_cleanup_push_dict_stack(void *p) { _mojo_cleanup_push(MOJO_CLEANUP_DICT_STACK, p); }
void mojo_cleanup_push_list_stack(void *p) { _mojo_cleanup_push(MOJO_CLEANUP_LIST_STACK, p); }
void mojo_cleanup_push_set_stack(void *p)  { _mojo_cleanup_push(MOJO_CLEANUP_SET_STACK, p); }
void mojo_cleanup_push_ptr(void *p)        { _mojo_cleanup_push(MOJO_CLEANUP_PTR, p); }
void mojo_cleanup_push_list_strs(void *p)  { _mojo_cleanup_push(MOJO_CLEANUP_LIST_STRS, p); }
void mojo_cleanup_push_closure(void *p)    { _mojo_cleanup_push(MOJO_CLEANUP_CLOSURE, p); }

void mojo_cleanup_cancel_n(int64_t n)
{
    _mojo_cleanup_top -= (int)n;
}

void mojo_cleanup_checkpoint_save(void)
{
    if (_mojo_exc_top >= 0 && _mojo_exc_top < MOJO_EXC_STACK_MAX)
        _mojo_cleanup_checkpoint[_mojo_exc_top] = _mojo_cleanup_top;
}

/* Run every cleanup thunk pushed since the checkpoint recorded for the
 * try/except level `mojo_raise` is about to longjmp into. Must run BEFORE
 * the longjmp: `longjmp` itself skips every C statement between the raise
 * site and the setjmp point, so this is the only place left that these
 * owned locals' frees can happen on an exception path (see
 * doc/OWNERSHIP_MODEL.md's exception-handling section). A thunk here is,
 * by construction, one this same call stack already pushed and never
 * cancelled — cancellation always happens at the exact free call the
 * normal path already emits, so a thunk surviving to this point means
 * that free call never ran, i.e. an exception genuinely reached or passed
 * this local's owning frame without it. */
static void _mojo_cleanup_unwind_to(int chk)
{
    while (_mojo_cleanup_top > chk) {
        mojo_cleanup_kind_t kind = _mojo_cleanup_kind[_mojo_cleanup_top];
        void *ptr = _mojo_cleanup_ptr[_mojo_cleanup_top];
        --_mojo_cleanup_top;
        switch (kind) {
            case MOJO_CLEANUP_DICT: mojo_dict_free((MojoDict *)ptr); break;
            case MOJO_CLEANUP_LIST: mojo_list_free((MojoList *)ptr); break;
            case MOJO_CLEANUP_SET:  mojo_set_free((MojoSet *)ptr);  break;
            case MOJO_CLEANUP_DICT_STACK: mojo_dict_destroy((MojoDict *)ptr); break;
            case MOJO_CLEANUP_LIST_STACK: mojo_list_destroy((MojoList *)ptr); break;
            case MOJO_CLEANUP_SET_STACK:  mojo_set_destroy((MojoSet *)ptr);  break;
            case MOJO_CLEANUP_PTR:        free(ptr);                         break;
            case MOJO_CLEANUP_LIST_STRS:  mojo_list_free_owned_strs((MojoList *)ptr); break;
            case MOJO_CLEANUP_CLOSURE:    mojo_closure_free(ptr);            break;
        }
    }
}

void mojo_raise(void)
{
    /* _mojo_exc_top < 0 means no enclosing try/with is active — either a
     * genuinely uncaught exception reaching the top of the program (real
     * Mojo would print a traceback and exit(1); this from-scratch runtime
     * has no such top-level handler), or a push/pop imbalance in the
     * generated code (a codegen bug, not a program bug). Either way,
     * longjmp-ing into _mojo_exc_stack[-1] is out-of-bounds and undefined —
     * previously a silent memory corruption that only crashed much later,
     * far from the real cause. Fail loudly and immediately instead. */
    if (_mojo_exc_top < 0) {
        fprintf(stderr, "Unhandled exception: %s\n", mojo_exc_msg_get());
        exit(1);
    }
    if (_mojo_exc_top >= MOJO_EXC_STACK_MAX) {
        fprintf(stderr, "mojo_raise: exception stack overflow (>%d nested try/with)\n",
                MOJO_EXC_STACK_MAX);
        exit(1);
    }
    _mojo_cleanup_unwind_to(_mojo_cleanup_checkpoint[_mojo_exc_top]);
    longjmp((void *)&_mojo_exc_stack[_mojo_exc_top], 1);
}

char *_mojo_exc_msg = NULL;
void mojo_exc_msg_set(char *msg) { _mojo_exc_msg = (char *)msg; }
char *mojo_exc_msg_get(void) { return _mojo_exc_msg ? _mojo_exc_msg : ""; }

/* Exception object slot (for typed exceptions) */
void *_mojo_exc_obj = NULL;
void mojo_exc_obj_set(void *obj) { _mojo_exc_obj = obj; }
void *mojo_exc_obj_get(void) { return _mojo_exc_obj; }

/* Exception type tag: a small int id (assigned per exception class name at
 * compile time, see GimpleGen._exc_type_id) that lets a multi-handler
 * try/except dispatch on which exception was actually raised instead of
 * always running the first handler. 0 means untyped/unknown (e.g. a bare
 * `raise` re-raising whatever is already live). */

/* Deterministic exception-class tags — the same values
 * GimpleGen._exc_type_id(name) computes (`(zlib.crc32(b"Name") &
 * 0x7fffffff) or 1`), computed once in Python and hardcoded here so the
 * runtime can raise REAL, typed, catchable exceptions (see
 * mojo_raise_file_not_found / mojo_open below). Defined up here rather
 * than next to their users: mojo_open (line ~319) needs them before the
 * AttributeError section further down. */
#define _MOJO_EXC_TAG_ATTRIBUTEERROR 1471495998
#define _MOJO_EXC_TAG_TYPEERROR 348628165
#define _MOJO_EXC_TAG_VALUEERROR 663468903
#define _MOJO_EXC_TAG_FILENOTFOUND 1834506930
#define _MOJO_EXC_TAG_OSERROR 2131477727

int64_t _mojo_exc_type = 0;
void mojo_exc_type_set(int64_t type_id) { _mojo_exc_type = type_id; }
int64_t mojo_exc_type_get(void) { return _mojo_exc_type; }

/* Compiled-generator (C++20 coroutine) exception-boundary flag — see the
 * long comment on this in fire_runtime.h. Set only by a generator's
 * extern "C" `<base>_resume()` (compiled .cpp side, gimple_codegen.py's
 * _gen_cpp_generator_unit) when an exception escaped that coroutine's own
 * body uncaught; consumed (checked, then cleared) by whichever ordinary,
 * never-suspended code called `_resume()` and observed it return false. */
int _mojo_exc_pending = 0;
void mojo_exc_pending_set(int v) { _mojo_exc_pending = v; }
int mojo_exc_pending_get(void) { return _mojo_exc_pending; }

/* ── Global state for argc/argv ───────────────────────────────────────────*/
static int _mojo_argc = 0;
static const char **_mojo_argv = NULL;
static MojoList *_mojo_argv_list = NULL;

void mojo_set_argv(int argc, const char **argv) {
    _mojo_argc = argc;
    _mojo_argv = argv;
    /* Build the argv list once */
    if (_mojo_argv_list) {
        mojo_list_free(_mojo_argv_list);
    }
    _mojo_argv_list = mojo_list_new();
    for (int i = 0; i < argc; i++) {
        mojo_list_append_str(_mojo_argv_list, argv[i]);
    }
}

MojoList *mojo_get_argv(void) {
    if (!_mojo_argv_list) {
        _mojo_argv_list = mojo_list_new();
    }
    return _mojo_argv_list;
}

/* `sys.argv = [...]` — a REBIND of the whole list, which real Python programs
 * genuinely do (mojo.py's own CLI strips its `--dump`/`--dump-full` flags this
 * way before reading `input_file = sys.argv[1]`). Reads lower to
 * mojo_get_argv() above; without a matching store the assignment was silently
 * dropped, so the compiled binary kept seeing the unstripped argv and treated
 * the flag itself as the input filename -- writing `--dump.ci` instead of
 * `<basename>.ci` for every bootstrap stage-2/3 dump.
 *
 * Takes ownership of `lst` (it is the caller's freshly-built list) but does NOT
 * free the previous list: elements of the old argv list are commonly still
 * referenced by the new one (the usual shape is a filtered copy), so freeing it
 * would leave those strings dangling. The old list is small, bounded by argc,
 * and leaked at most once per rebind. `_mojo_argc`/`_mojo_argv` deliberately
 * keep pointing at the real process argv -- they are the C-level view used by
 * anything that needs the original vector. */
void mojo_replace_argv(MojoList *lst) {
    if (!lst) return;
    _mojo_argv_list = lst;
}

/* ── Python integration ───────────────────────────────────────────────────
 * Print via Python's print() function using the C API.                    */
#if USE_PYTHON
static PyObject *_mojo_print_func = NULL;
static int _mojo_py_initialized = 0;

void mojo_print_init(void) {
    if (_mojo_print_func != NULL) {
        return;  /* Already initialized */
    }

    /* Get the builtins module */
    PyObject *builtins = PyImport_ImportModule("builtins");
    if (builtins == NULL) {
        fprintf(stderr, "mojo_print_init: Failed to import builtins\n");
        PyErr_Print();
        return;
    }

    /* Get the print function from builtins */
    _mojo_print_func = PyObject_GetAttrString(builtins, "print");
    Py_DECREF(builtins);

    if (_mojo_print_func == NULL) {
        fprintf(stderr, "mojo_print_init: Failed to get print function\n");
        PyErr_Print();
        return;
    }

    if (!PyCallable_Check(_mojo_print_func)) {
        fprintf(stderr, "mojo_print_init: print is not callable\n");
        Py_DECREF(_mojo_print_func);
        _mojo_print_func = NULL;
        return;
    }
}
#endif

void mojo_print(char *str) {
    /* Use printf directly (no Python dependency).
     *
     * A NULL `char *` prints "None", not whatever printf does with a NULL
     * `%s` (glibc and Darwin both print the parenthesised "(null)", which is
     * a string no source wrote). On this path a NULL string IS `None`: the
     * container misses return NULL — `mojo_dict_get_str` on an absent key is
     * what `d.get(k)` lowers to — so `print(d.get("MISSING"))` has to say
     * `None` the way CPython does. Printing "(null)" for it made the value
     * recognisable as wrong only if you already knew it was wrong. */
    printf("%s", str ? str : "None");
    fflush(stdout);
}

/* print(..., file=sys.stderr): a separate function rather than passing a
 * FILE* through generated GIMPLE code — `stderr`/`stdout` are macros on
 * macOS (e.g. __stderrp), not necessarily legal inline in -fgimple's
 * restricted subset. gimple_codegen.py's _gen_print detects `file=` by AST
 * shape at compile time and picks mojo_print vs this, so no FILE* value
 * ever needs to flow through the generated code at all. */
void mojo_print_stderr(char *str) {
    /* The same NULL-means-None rule as `mojo_print` above, for the same
     * reason: the two are the same statement with a different FILE*. */
    fprintf(stderr, "%s", str ? str : "None");
    fflush(stderr);
}

/* File I/O — via Python (if enabled) or via C stdio */
#if USE_PYTHON
MojoFileHandle mojo_open(char *filename, char *mode) {
    PyObject *open_func = PyObject_GetAttrString(
        PyImport_ImportModule("builtins"), "open");
    if (!open_func) {
        PyErr_Print();
        return NULL;
    }

    PyObject *fh = PyObject_CallFunction(open_func, "ss", filename, mode);
    Py_DECREF(open_func);

    if (!fh) {
        PyErr_Print();
        return NULL;
    }

    return (MojoFileHandle)fh;
}

void mojo_close(MojoFileHandle fh) {
    if (!fh) return;

    PyObject *file_obj = (PyObject *)fh;
    PyObject *close_result = PyObject_CallMethod(file_obj, "close", NULL);

    if (close_result) {
        Py_DECREF(close_result);
    } else {
        PyErr_Print();
    }

    Py_DECREF(file_obj);
}

int64_t mojo_write(MojoFileHandle fh, char *data, int64_t len) {
    if (!fh || !data) return -1;

    PyObject *file_obj = (PyObject *)fh;

    /* If len is -1, compute it from the string */
    if (len == -1) {
        len = (int64_t)strlen(data);
    }

    PyObject *write_result = PyObject_CallMethod(file_obj, "write", "s", data);

    if (!write_result) {
        PyErr_Print();
        return -1;
    }

    int64_t written = PyLong_AsLongLong(write_result);
    Py_DECREF(write_result);

    return written;
}

int64_t mojo_read(MojoFileHandle fh, char *buffer, int64_t len) {
    if (!fh) return -1;

    PyObject *file_obj = (PyObject *)fh;
    PyObject *read_result = PyObject_CallMethod(file_obj, "read", "L", (unsigned long)len);

    if (!read_result) {
        PyErr_Print();
        return -1;
    }

    Py_ssize_t result_len = 0;
    char *result_data = PyUnicode_AsUTF8AndSize(read_result, &result_len);

    if (!result_data) {
        Py_DECREF(read_result);
        PyErr_Print();
        return -1;
    }

    int64_t copy_len = (result_len < len) ? result_len : len;
    memcpy(buffer, result_data, copy_len);

    Py_DECREF(read_result);
    return copy_len;
}

char *mojo_file_read_all(char *filename) {
    /* Read entire file contents into allocated string */
    if (!filename) return NULL;

    PyObject *builtins = PyImport_ImportModule("builtins");
    if (!builtins) {
        PyErr_Clear();
        return NULL;
    }

    PyObject *open_func = PyObject_GetAttrString(builtins, "open");
    Py_DECREF(builtins);

    if (!open_func) {
        PyErr_Clear();
        return NULL;
    }

    PyObject *file_obj = PyObject_CallFunction(open_func, "s", filename);
    Py_DECREF(open_func);

    if (!file_obj) {
        PyErr_Clear();
        return NULL;
    }

    PyObject *read_result = PyObject_CallMethod(file_obj, "read", NULL);
    Py_DECREF(file_obj);

    if (!read_result) {
        PyErr_Clear();
        return NULL;
    }

    Py_ssize_t result_len = 0;
    char *result_data = PyUnicode_AsUTF8AndSize(read_result, &result_len);

    if (!result_data) {
        Py_DECREF(read_result);
        PyErr_Clear();
        return NULL;
    }

    char *buffer = malloc(result_len + 1);
    if (buffer) {
        memcpy(buffer, result_data, result_len);
        buffer[result_len] = '\0';
    }

    Py_DECREF(read_result);
    return buffer;
}
#else
/* Non-Python implementations using C stdio */
MojoFileHandle mojo_open(char *filename, char *mode) {
    FILE *f = fopen(filename, mode);
    if (!f) {
        /* Typed like real Python: a missing file is FileNotFoundError
         * (anything else OSError) — see mojo_raise_file_not_found. */
        FILE *probe = fopen(filename, "r");
        mojo_exc_type_set(probe ? _MOJO_EXC_TAG_OSERROR
                                : _MOJO_EXC_TAG_FILENOTFOUND);
        char msg[512];
        snprintf(msg, sizeof msg, "[Errno 2] cannot open '%s' (mode '%s')",
                 filename ? filename : "?", mode ? mode : "?");
        char *heap_msg = strdup(msg);
        mojo_exc_msg_set(heap_msg);
        mojo_exc_obj_set(heap_msg);
        mojo_raise();
    }
    return (MojoFileHandle)f;
}

void mojo_close(MojoFileHandle fh) {
    if (fh) fclose((FILE *)fh);
}

int64_t mojo_write(MojoFileHandle fh, char *data, int64_t len) {
    if (!fh || !data) return -1;
    if (len == -1) len = (int64_t)strlen(data);
    return (int64_t)fwrite(data, 1, (size_t)len, (FILE *)fh);
}

int64_t mojo_read(MojoFileHandle fh, char *buffer, int64_t len) {
    if (!fh || !buffer) return -1;
    return (int64_t)fread(buffer, 1, (size_t)len, (FILE *)fh);
}

char *mojo_file_read_all(char *filename) {
    if (!filename) return NULL;
    FILE *f = fopen(filename, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buffer = malloc(size + 1);
    if (buffer) {
        fread(buffer, 1, size, f);
        buffer[size] = '\0';
    }
    fclose(f);
    return buffer;
}
#endif

/* ═══════════════════════════════════════════════════════════════════════
 * MojoList
 * ═══════════════════════════════════════════════════════════════════════*/

struct MojoList {
    int64_t *data;
    int64_t  len;
    int64_t  cap;
};

/* Registry of every live MojoList* address, used only by generic repr()
 * dispatch (_mojo_generic_elem_repr in gimple_codegen.py) to tell a boxed
 * int64_t holding a nested list/tuple pointer apart from a boxed string
 * pointer or a real large int — MojoList carries no type tag of its own
 * (unlike a codegen-emitted struct's leading __mojo_type_id field), so
 * without this a list-of-tuples field (e.g. FunctionDef.params) printed
 * each tuple's raw pointer bytes reinterpreted as garbage text via
 * mojo_repr_str. Lazily allocated via mojo_set_new() itself (not tracked
 * in the registry — only MojoLists returned by mojo_list_new() are). */

/* _PtrReg: the membership table behind every "is this boxed int64_t a list /
 * dict / set / tuple / bound method" registry in this file. It answers ONE
 * question — "is this address registered?" — so it is nothing but a set of
 * non-zero addresses: open addressing, power-of-two capacity (an AND, not a
 * `%`), 8-byte slots, a one-multiply hash, and backward-shift deletion (no
 * tombstones). Every container init/destroy pays one add and one discard, so
 * this is the hottest code in a program that builds short-lived containers:
 * the MojoSet these registries used to be (32-byte slots, a `%` per probe, a
 * re-hash of the cluster on every erase) was measured at well over half the
 * runtime cost of a stack-homed list. Not thread-safe, exactly like what it
 * replaces. Its own storage is plain calloc/free, never a MojoSet/MojoList,
 * so registering can never recurse into registering.
 *
 * Invariants: slot value 0 = empty (0 is never registered); `cap` is a power
 * of two; used*2 <= cap (so a probe always reaches an empty slot). */
typedef struct {
    uint64_t *slots;
    uint64_t  cap;    /* power of two, 0 until first add */
    uint64_t  used;
    int       shift;  /* 64 - log2(cap) */
} _PtrReg;

static inline uint64_t _pr_home(const _PtrReg *r, uint64_t p) {
    /* >>3: heap/stack addresses are 8/16-byte aligned, the low bits carry no
     * information. The multiplicative hash's HIGH bits are the well-mixed
     * ones, hence the shift down rather than a mask of the product. */
    return ((p >> 3) * 0x9E3779B97F4A7C15ULL) >> r->shift;
}

static void _pr_grow(_PtrReg *r) {
    uint64_t ncap = r->cap ? r->cap * 2 : 256;
    uint64_t *old = r->slots;
    uint64_t ocap = r->cap;
    r->slots = (uint64_t *)calloc((size_t)ncap, sizeof(uint64_t));
    r->cap = ncap;
    r->shift = 64;
    for (uint64_t c = ncap; c > 1; c >>= 1) r->shift--;
    r->used = 0;
    for (uint64_t i = 0; i < ocap; i++) {
        if (old[i]) {
            uint64_t j = _pr_home(r, old[i]);
            while (r->slots[j]) j = (j + 1) & (ncap - 1);
            r->slots[j] = old[i];
            r->used++;
        }
    }
    free(old);
}

static void _pr_add(_PtrReg *r, uint64_t p) {
    if (!p) return;
    if ((r->used + 1) * 2 > r->cap) _pr_grow(r);
    uint64_t mask = r->cap - 1;
    uint64_t j = _pr_home(r, p);
    while (r->slots[j]) {
        if (r->slots[j] == p) return;
        j = (j + 1) & mask;
    }
    r->slots[j] = p;
    r->used++;
}

static int _pr_has(const _PtrReg *r, uint64_t p) {
    if (!r->used) return 0;
    uint64_t mask = r->cap - 1;
    uint64_t j = _pr_home(r, p);
    while (r->slots[j]) {
        if (r->slots[j] == p) return 1;
        j = (j + 1) & mask;
    }
    return 0;
}

static void _pr_del(_PtrReg *r, uint64_t p) {
    if (!r->used) return;
    uint64_t mask = r->cap - 1;
    uint64_t i = _pr_home(r, p);
    while (r->slots[i] != p) {
        if (!r->slots[i]) return;          /* not registered */
        i = (i + 1) & mask;
    }
    /* Backward-shift deletion: pull later members of the cluster into the
     * hole when their home is not strictly inside (i, j], so no tombstone is
     * ever left and lookups stay short however often the same address is
     * added and removed (the LIFO stack-homed pattern). */
    uint64_t j = i;
    for (;;) {
        j = (j + 1) & mask;
        if (!r->slots[j]) break;
        uint64_t k = _pr_home(r, r->slots[j]);
        int in_range = (i <= j) ? (i < k && k <= j) : (i < k || k <= j);
        if (!in_range) {
            r->slots[i] = r->slots[j];
            i = j;
        }
    }
    r->slots[i] = 0;
    r->used--;
}

static _PtrReg _reg_list;

int mojo_is_registered_list(int64_t addr) {
    if (addr < 65536) return 0;
    return _pr_has(&_reg_list, (uint64_t)addr);
}

/* ── Per-slot element kinds on a MojoList ────────────────────────────────
 *
 * A MojoList's `data` is a flat `int64_t` array with NO per-element type
 * tag: a double is stored as a bit-cast and a `MojoBytes *` as a pointer
 * cast, so a reader that does not already know what a slot holds has no way
 * to find out. That is why every uniform-list reader in this file (and the
 * codegen's own subscript/repr helpers) is chosen per LIST and not per SLOT.
 *
 * Where the kinds ARE known — a `struct` format string, or a heterogeneous
 * list literal — the right answer is per slot, and this table is how that
 * travels with the VALUE instead of dying with the one compile-time name the
 * codegen happened to see it under. One open-addressed map keyed by the live
 * MojoList address, holding one byte per slot from the alphabet below plus
 * the per-slot box cache (see `mojo_list_get_boxed`).
 *
 * Deliberately a SIDE TABLE and not a field on MojoList: changing that
 * struct's layout would move every stack-declared list in every generated
 * program, plus the C++ backend's own copy of the container
 * (mojo/backend_gimple/cpp_core.py) and the self-host's emitted structs.
 *
 * Only lists that are genuinely heterogeneous are ever added, so a program
 * that never builds one pays a single failed probe per heterogeneous read
 * and nothing at all anywhere else — the same "no cost until you need it"
 * shape _reg_tuple above already pays.
 *
 * Alphabet (mirrors the codegen's _STRUCT_KIND_BYTE, plus the two kinds a
 * heterogeneous list literal can hold and a struct format cannot):
 *   'i' int64_t          (all of b B h H i I l L q Q ? and 'c')
 *   'd' double           (f d)
 *   's' MojoBytes *      (s)
 *   'p' char *           (a str held in a list slot)
 *   'l' MojoList *       (a nested container held in a list slot)
 *   'n' None
 * An index past the end of the string reads as 'i', which is the same
 * answer mojo_repr_list_kinds already gave for an uncovered slot.
 *
 * The kinds string is NOT copied: both callers hand over a pointer that
 * outlives every list it reaches — a strdup'd `MojoStructFmt` field the
 * compiler never frees, and a codegen string-pool constant — so
 * `mojo_list_inherit_kinds` below really does share rather than alias a
 * temporary.
 */
typedef struct {
    uint64_t addr;    /* the MojoList address; 0 = empty slot */
    char    *kinds;   /* one byte per slot, or NULL */
    void   **boxes;   /* lazily allocated, one entry per list element */
    /* How to REPR one element of this list, or NULL. Same "the information
     * travels with the value" bargain as `kinds`, and for the same reason: the
     * codegen knows a literal's element type where it BUILDS the list and has
     * no way to tell a runtime walker later, because a struct-allocated value
     * carries no type tag for `_mojo_dispatch_repr` to find (that is the whole
     * of bugs/CODEGEN_user_defined_dunder_repr_not_consulted_by_str_and_
     * container_spellings.md). One pointer per row, and only for a list whose
     * elements are a registered struct. Not copied either: it is a function
     * address in this image. */
    char   *(*repr_fn)(int64_t);
} _KindRow;

static struct {
    _KindRow *rows;
    uint64_t  cap;    /* power of two, 0 until first add */
    uint64_t  used;
    int       shift;  /* 64 - log2(cap), as in _PtrReg */
} _reg_kinds;

/* Home slot for `addr`. The one-multiply hash and the high-bit shift are
 * `_PtrReg`'s (_pr_home) for the same reason: a BARE `addr & mask` — which
 * is what this table used — gives every pair of heap MojoLists the same home
 * slot, because `sizeof(MojoList)` is 56 and malloc hands out 64-byte
 * blocks, so consecutive allocations are 64 apart and congruent mod any
 * power-of-two table size. Every live kinds row therefore sat in one probe
 * cluster, which is both a linear-time probe and — the bug this fixes — a
 * table whose DELETION could strand its neighbours (see _kinds_forget). */
static inline uint64_t _kinds_home(uint64_t addr) {
    return ((addr >> 3) * 0x9E3779B97F4A7C15ULL) >> _reg_kinds.shift;
}

static void _kinds_grow(void)
{
    uint64_t ncap = _reg_kinds.cap ? _reg_kinds.cap * 2 : 64;
    _KindRow *old = _reg_kinds.rows;
    uint64_t ocap = _reg_kinds.cap;
    _reg_kinds.rows = (_KindRow *)calloc((size_t)ncap, sizeof(_KindRow));
    _reg_kinds.cap  = ncap;
    _reg_kinds.shift = 64;
    for (uint64_t c = ncap; c > 1; c >>= 1) _reg_kinds.shift--;
    _reg_kinds.used = 0;
    for (uint64_t i = 0; i < ocap; i++) {
        if (!old[i].addr) continue;
        uint64_t j = _kinds_home(old[i].addr);
        while (_reg_kinds.rows[j].addr) j = (j + 1) & (ncap - 1);
        _reg_kinds.rows[j] = old[i];
        _reg_kinds.used++;
    }
    free(old);
}

/* The row for `addr`, or NULL. Probe terminates: `used*2 <= cap` is kept. */
static _KindRow *_kinds_row(uint64_t addr)
{
    if (!_reg_kinds.cap || !addr) return NULL;
    uint64_t mask = _reg_kinds.cap - 1;
    uint64_t i = _kinds_home(addr);
    for (;;) {
        if (!_reg_kinds.rows[i].addr) return NULL;
        if (_reg_kinds.rows[i].addr == addr) return &_reg_kinds.rows[i];
        i = (i + 1) & mask;
    }
}

/* The row for `addr`, creating it if needed. `*fresh` reports whether it is
 * new, so a caller that has nothing to record can undo the creation. */
static _KindRow *_kinds_row_for_write(uint64_t addr, int *fresh)
{
    *fresh = 0;
    if (!_reg_kinds.cap) { _kinds_grow(); *fresh = 1; }
    if ((_reg_kinds.used + 1) * 2 > _reg_kinds.cap) {
        _kinds_grow();
        *fresh = 1;
    }
    uint64_t mask = _reg_kinds.cap - 1;
    uint64_t i = _kinds_home(addr);
    while (_reg_kinds.rows[i].addr) {
        if (_reg_kinds.rows[i].addr == addr) return &_reg_kinds.rows[i];
        i = (i + 1) & mask;
    }
    _reg_kinds.rows[i].addr = addr;
    _reg_kinds.used++;
    *fresh = 1;
    return &_reg_kinds.rows[i];
}

const char *mojo_list_get_kinds(MojoList *l)
{
    _KindRow *r = _kinds_row((uint64_t)(uintptr_t)l);
    return r ? r->kinds : NULL;
}

static void _kinds_forget(uint64_t addr);

void mojo_list_set_kinds(MojoList *l, const char *kinds)
{
    if (!l) return;
    uint64_t addr = (uint64_t)(uintptr_t)l;
    /* Clearing a list that never had a row is the overwhelmingly common
     * call, so it must not allocate one. */
    if ((!kinds || !*kinds) && !_kinds_row(addr)) return;
    int fresh = 0;
    _KindRow *r = _kinds_row_for_write(addr, &fresh);
    r->kinds = (char *)kinds;
    if (fresh && !kinds) _kinds_forget(addr);
}

/* The kind of one slot, 'i' for anything this table does not describe. */
char mojo_list_slot_kind(MojoList *l, int64_t i)
{
    const char *k = mojo_list_get_kinds(l);
    if (!k || i < 0 || !k[i]) return 'i';
    return k[i];
}

/* `dst` is a fresh list built slot-for-slot out of `src`: it holds the same
 * values, so it describes them the same way. Every list->list copy in this
 * file calls this; that is the whole reason `list(mixed_tuple)` and
 * `m[:]` are right rather than only the original.
 *
 * The ELEMENT REPR travels with it for the same reason and by the same route:
 * a copy holds the same values, so it reprs them the same way, and `list(t)`
 * printing a raw pointer decimal where `t` printed `R<a>` would be the same
 * bug one call away. */
void mojo_list_inherit_kinds(MojoList *dst, MojoList *src)
{
    if (!dst || !src) return;
    const char *k = mojo_list_get_kinds(src);
    if (k) mojo_list_set_kinds(dst, k);
    _KindRow *sr = _kinds_row((uint64_t)(uintptr_t)src);
    if (sr && sr->repr_fn) mojo_list_set_elem_repr(dst, (void *)sr->repr_fn);
}

/* ── The per-list ELEMENT REPR ────────────────────────────────────────────
   `mojo_list_set_elem_repr` records how to render one element of this list;
   `mojo_list_repr_elem` is what a repr walker asks per slot and gets NULL from
   when the list says nothing (so the walker's own generic reader still runs,
   and a list this was never called for is exactly as it was).

   Why a function pointer on the VALUE rather than a global type->repr table:
   the element's static type is known where the list is built and is thrown away
   by the time anything walks it, and the two ways to recover it both fail —
   `_mojo_dispatch_repr` needs a runtime type TAG, which a struct-allocated
   local does not carry (its first word is its first field), and a global
   address->type registry would go stale the moment a frame is reused, handing a
   later struct at the same address another struct's repr. Recording the
   function on the list has neither failure mode: it is set once, from the
   compile-time type, and it dies with the list.

   Emitted by the codegen beside the `mojo_list_set_kinds` call for the same
   literal (mojo/backend_gimple/emit_exprs.py's `_lower_list_literal`), for a
   homogeneous literal whose element type is a registered struct — the case the
   kinds table deliberately leaves alone, since one accessor is already exact
   for reading and says nothing about REPR.
*/
void mojo_list_set_elem_repr(MojoList *l, void *fn)
{
    if (!l) return;
    uint64_t addr = (uint64_t)(uintptr_t)l;
    int fresh = 0;
    _KindRow *r = _kinds_row_for_write(addr, &fresh);
    r->repr_fn = (char *(*)(int64_t))fn;
    if (fresh && !fn) _kinds_forget(addr);
}

/* The recorded element repr, or NULL. The walker decides what a NULL means —
   that is the point of returning NULL rather than a generic answer here. */
char *mojo_list_repr_elem(MojoList *l, int64_t v)
{
    _KindRow *r = _kinds_row((uint64_t)(uintptr_t)l);
    if (!r || !r->repr_fn) return NULL;
    return r->repr_fn(v);
}

static void _kinds_forget(uint64_t addr)
{
    if (!_reg_kinds.used) return;
    uint64_t mask = _reg_kinds.cap - 1;
    uint64_t i = _kinds_home(addr);
    while (_reg_kinds.rows[i].addr != addr) {
        if (!_reg_kinds.rows[i].addr) return;    /* not registered */
        i = (i + 1) & mask;
    }
    free(_reg_kinds.rows[i].boxes);
    /* Backward-shift deletion, the same algorithm (and the same reason) as
     * _pr_del: clearing the slot outright would leave a hole that every
     * LATER member of this probe cluster can no longer be found through, so
     * one list's free would silently strip the element kinds off every other
     * live list whose home slot it shared — and a heterogeneous list read
     * with no kinds reads a double's IEEE-754 bit pattern as an int64_t,
     * which the repr path then hands to strlen. Real, measured, and the
     * shape of the dangling-registry bug this table was written without. */
    uint64_t j = i;
    for (;;) {
        j = (j + 1) & mask;
        if (!_reg_kinds.rows[j].addr) break;
        uint64_t k = _kinds_home(_reg_kinds.rows[j].addr);
        int in_range = (i <= j) ? (i < k && k <= j) : (i < k || k <= j);
        if (!in_range) {
            _reg_kinds.rows[i] = _reg_kinds.rows[j];
            i = j;
        }
    }
    _reg_kinds.rows[i].addr = 0;
    _reg_kinds.rows[i].kinds = NULL;
    _reg_kinds.rows[i].boxes = NULL;
    _reg_kinds.used--;
}

/* ── Boxed reads: one C type for a slot whose kind is not known at compile
 * time ────────────────────────────────────────────────────────────────────
 *
 * `for x in struct.unpack('<if', buf)` and `struct.unpack('<if', buf)[i]`
 * have no compile-time slot index, so the value they produce has to land in
 * ONE static C type — and for a list that mixes ints and floats there is no
 * single right answer for an int64_t slot holding a double's bit pattern.
 * A box is how that kind travels out of the slot and next to the value: a
 * 16-byte cell whose first word is a magic no struct type tag can equal
 * (those are 31-bit CRCs of a class name, so the top 32 bits are always
 * clear) and whose second word is the raw slot.
 *
 * The int64_t a boxed read returns IS the box's address, so the consumer
 * needs one predicate to tell it from a real value: `mojo_is_boxed`, backed
 * by the same _PtrReg membership tables the other boxed-value predicates use
 * (mojo_is_registered_list, mojo_is_bound_method). `mojo_boxed_is_str` is
 * taught to exclude a box, because a box is pointer-shaped and would
 * otherwise be handed to strlen — turning a wrong number into a crash.
 *
 * Boxes are cached per (list, slot) rather than allocated per READ: a loop
 * over a 10k-element mixed list boxes each of its double slots once, not
 * once per iteration, and `mojo_list_destroy` releases the cache array. The
 * boxes themselves outlive the list, because a boxed value read out of a
 * list is a value the program may still hold — the same rule the existing
 * container code follows for a `MojoBytes *` slot.
 */
#define MOJO_BOX_MAGIC 0x4D4A424F58310001ULL   /* "MBOX1" */

typedef struct {
    uint64_t magic;
    int64_t  bits;
    /* The slot's own kind byte (mojo_list_set_kinds' alphabet), copied from
     * the list at BOX time. A box exists precisely because the raw word is
     * not self-describing — a double has no int64_t spelling, and a str
     * slot's word is a bare pointer with nothing to say it is one — so the
     * consumer has to be able to ASK rather than guess. Without this the box
     * only ever carried the float case and every other kind came back as the
     * bare word: `mojo_repr_boxed` could only answer "box ⇒ float", so a
     * STRING slot of the same heterogeneous list printed as its address
     * decimal. */
    char     kind;
} MojoBox;

static _PtrReg _reg_box;

int mojo_is_boxed(int64_t v)
{
    if (v < 65536) return 0;
    return _pr_has(&_reg_box, (uint64_t)v);
}

int64_t mojo_list_get_boxed(MojoList *l, int64_t i)
{
    if (!l || i < 0 || i >= l->len) return 0;
    char _k = mojo_list_slot_kind(l, i);
    /* An int slot is its own answer and stays the bare word: a box is a heap
     * cell per (list, slot), and taxing every int in a mixed list to serve the
     * uncommon kinds would be the wrong trade. Every OTHER kind is boxed —
     * not just 'd' — because for each of them the raw word is ambiguous: a
     * double has no int64_t spelling, and a `char *` slot's word is a bare
     * pointer a consumer cannot tell from an int. */
    if (_k == 'i')
        return l->data[i];
    uint64_t addr = (uint64_t)(uintptr_t)l;
    int fresh = 0;
    _KindRow *r = _kinds_row_for_write(addr, &fresh);
    if (fresh || !r->boxes) {
        void **nb = (void **)calloc((size_t)l->len, sizeof(void *));
        if (!nb) return l->data[i];
        if (r->boxes) free(r->boxes);
        r->boxes = nb;
    }
    if (i >= l->len) return l->data[i];
    if (!r->boxes[i]) {
        MojoBox *bx = (MojoBox *)malloc(sizeof(MojoBox));
        if (!bx) return l->data[i];
        bx->magic = MOJO_BOX_MAGIC;
        /* The slot's own word, bit for bit: a list stores a double that way
         * (see the MojoList comment in fire_runtime.h), and reinterpreting
         * it is what mojo_list_get_double does. Storing the double TRUNCATED
         * to an int64_t instead would read back 2.5 as 2.0. */
        bx->bits = l->data[i];
        bx->kind = _k;
        _pr_add(&_reg_box, (uint64_t)(uintptr_t)bx);
        r->boxes[i] = bx;
    }
    return (int64_t)(uintptr_t)r->boxes[i];
}

/* A double travels as its IEEE-754 BITS inside an int64_t — in a list slot
   (mojo_list_get_double), in a box (mojo_box_double below), and in the
   int64_t the homogenized `mojo_fnptr_call_N` helpers return for a callable
   value. This is the ONE definition of that conversion in each direction, so
   a consumer recovering a double from a word cannot get the direction wrong.
   `mojo_double_from_bits` must MEMCPY, never a C cast: `(double)bits` is the
   bits' NUMERIC value — 4611686018427387904.0 for the bit pattern of the
   literal 1.5 — which is exactly the wrong answer this exists to prevent. */
double mojo_double_from_bits(int64_t bits) {
    double v;
    memcpy(&v, &bits, sizeof(v));
    return v;
}

int64_t mojo_double_to_bits(double v) {
    int64_t bits;
    memcpy(&bits, &v, sizeof(bits));
    return bits;
}

/* The box read as a double. A value that is NOT a box — or a box of a kind
 * that is not a double's — comes back as its own numeric value, not 0: the
 * codegen marks a whole READ SITE as possibly boxed (the runtime decides per
 * slot), so a call here must be correct for the int slots of the same list
 * too — and promoting an int to a double is exactly what an operation with a
 * float operand already does to it. A non-double box unwraps to its raw word
 * first, which is what that same slot returned before it was boxed at all. */
double mojo_box_double(int64_t v)
{
    if (!mojo_is_boxed(v)) return (double)v;
    MojoBox *bx = (MojoBox *)(intptr_t)v;
    if (bx->kind != 'd') return (double)bx->bits;
    return mojo_double_from_bits(bx->bits);
}

/* The box read as an integer: Python's own conversion (truncation toward
 * zero) of a DOUBLE box, and the raw word for anything else — including a
 * non-double box, whose slot is not a number at all and whose word is what
 * the unboxed read returned. */
int64_t mojo_box_int(int64_t v)
{
    MojoBox *bx = (MojoBox *)(intptr_t)v;
    if (!bx || !mojo_is_boxed(v)) return v;
    if (bx->kind != 'd') return bx->bits;
    return (int64_t)mojo_box_double(v);
}

/* The repr of a possibly-boxed int64_t. A box is described by its OWN kind
 * byte (see MojoBox): 'd' the double it holds, 'p' a str, 's' bytes, 'l' a
 * nested container, 'n' None, anything else the plain integer. Not a box ->
 * the plain integer, which is what every other int64_t in this runtime
 * already is. One call so the consumer needs no branch.

 * The per-kind arms are `mojo_repr_list_kinds`' own, so a str slot and a str
 * element of a heterogeneous list cannot print differently — and the str arm
 * is why this cannot go on answering "box ⇒ float": a `char *` slot's word is
 * a bare pointer, so without asking the box a str element printed as its own
 * address decimal. */
char *mojo_repr_boxed(int64_t v)
{
    if (mojo_is_boxed(v)) {
        MojoBox *bx = (MojoBox *)(intptr_t)v;
        switch (bx->kind) {
            case 'd': return mojo_repr_float(mojo_double_from_bits(bx->bits));
            /* str() semantics, NOT repr(): every caller of this function is a
             * str() spelling (`print`, an f-string, `%s`, the `str` builtin),
             * where `str("yy")` is `yy` and only `repr` would quote it. The
             * float case could not tell the two apart, which is why the
             * name says "repr" and the behaviour was never checked; the str
             * slot can. strdup'd because the string belongs to the list, and
             * callers treat this result as their own (see
             * mojo_cstr_or_int_str's ownership comment). */
            case 'p': return strdup((char *)(intptr_t)bx->bits);
            case 's': return mojo_bytes_repr((MojoBytes *)(intptr_t)bx->bits);
            case 'l': return mojo_repr_list_kinds(
                (MojoList *)(intptr_t)bx->bits, NULL);
            case 'n': return strdup("None");
            default:  return mojo_repr_int(bx->bits);
        }
    }
    return mojo_str_from_int(v);
}


/* The ONE definition of "this int64_t is a real heap/static pointer", shared
 * by every predicate in this file that has to dereference one. Both
 * requirements below are what makes that safe, and both were found by
 * measurement, not by taste:
 *
 *   - at least 2 GiB: below that live None, small ints, bools, and the
 *     31-bit `zlib.crc32(name) & 0x7fffffff` struct type-tags a compiled
 *     `type(node)` yields in place of a class object. A `v > 65536` test
 *     classified every such tag as "definitely a pointer" and the
 *     dereference then segfaulted -- CRASH.md, the mojoc-on-any-input
 *     SIGSEGV. This is the arm the crash fix was actually about.
 *   - below 2^47, the top of the userspace half on every platform this
 *     runtime targets. A codegen-emitted recursive AST scan once walked
 *     into the sentinel 0x00007fffffffffff -- past this bound -- and the
 *     bare dereference segfaulted.
 *
 * NOT in this predicate, deliberately, because they are properties of what
 * a given CALLER intends to read, not of the address:
 *
 *   - 8-byte alignment, and
 *   - a live allocation of at least 8 bytes.
 * A `char *` string has no alignment requirement at all, and a C string
 * LITERAL is not malloc'd and not even 8-byte aligned: measured on the
 * literals `"bb"`, `"a"`, `"ccc"` in a real generated .c, the addresses
 * come out at ...644, ...647, ...649 (i.e. 8-alignment 4/7/1) with
 * malloc_size() == 0, because they live in a merged .rodata section, not on
 * the heap. Folding either requirement in here rejected every string
 * literal in the program. See _mojo_tagged_addr_ok below, which does need
 * both, and mojo_boxed_is_str above, which needs neither. */
static int _mojo_ptr_shaped(int64_t addr) {
    uint64_t u = (uint64_t)addr;
    if (u < 0x80000000ULL) return 0;
    if (u >= 0x0000800000000000ULL) return 0;
    return 1;
}

/* Runtime str-vs-container discriminator for an AMBIGUOUSLY-typed (boxed
 * int64_t) value — the `isinstance(x, str)` counterpart of
 * mojo_is_registered_list above, sharing its registry so the two verdicts
 * are mutually consistent by construction. In this compiler's scalar body
 * model a char* string and a MojoList* container are BOTH pointer-shaped
 * int64_t values with no header/tag on the string side, so a polymorphic
 * parameter (e.g. fsutil.py's iter_files `root`, which is a str at the
 * recursive call and a list of strs at the top call) cannot be resolved
 * statically. The model's own established convention (mojo_str()'s
 * "high address ⇒ string", and _mojo_repr_list's registered-list probe)
 * already discriminates these two shapes everywhere else at runtime:
 * pointer-shaped AND NOT a live registered MojoList ⇒ treat as string.
 * Small values (<65536: None/small ints/bools) are not strings. */

/* Is this boxed int64_t plausibly a `char *`?
 *
 * DELIBERATELY the RANGE-only predicate (`_mojo_ptr_shaped`, defined above),
 * not the fuller `_mojo_tagged_addr_ok` the struct-box readers use. That
 * fuller predicate answers a different question -- "may I read an
 * `int64_t __mojo_type_id` at offset 0 of this?" -- and two of its extra
 * checks are properties of THAT read rather than of pointers in general:
 *
 *   - `u & 7`, 8-byte alignment, because the tag is an int64_t at offset 0.
 *   - `MOJO_MALLOC_USABLE_SIZE(u) >= sizeof(int64_t)`, because that read
 *     must not run off the end of the allocation holding the address.
 *
 * A codegen-emitted string LITERAL is a `char[N]` in __TEXT/__rodata: it is
 * not a malloc allocation at all, so `malloc_size` returns 0 for it, and
 * 8-byte alignment is a property of the C compiler's section layout, not
 * something the emitted `static char * _slit_N = "bb";` (module_gen.py's
 * pool) can rely on. Measured on that exact declaration shape in a
 * standalone C file, at both -O0 and -O2: "a" at &7==7, "bb" at 1, "ccc" at
 * 4, "dddd" at 0, "x" at 3 -- i.e. mostly NOT 8-aligned, and differently per
 * build. The full pipeline's pool has so far come out aligned in every
 * variant tried (20+ first-key literals x pool padding, each probed at
 * runtime), so the alignment half is LATENT rather than firing today -- but
 * the malloc_usable_size half, which was briefly folded into this
 * predicate, was exactly this bug: it trips on EVERY literal, and
 * `sorted(["bb","a","ccc"], key=lambda s: s)` printed `['bb','a','ccc']`
 * (the comparator saw three EQUAL keys, so the sort was a no-op) and
 * `lambda k, d=d: d[k]` called as `f("a")` printed 0. Requiring either
 * property here demotes a string literal to "not a string", and that is a
 * SILENT wrong answer rather than a crash -- `mojo_cstr_or_int_str` falls
 * through to `mojo_str_from_int`, so a dict keyed by a literal is looked up
 * by the decimal of its own address and silently yields the not-found
 * default. Two checks that are half a coin flip per build are two checks
 * that should not be here at all.
 *
 * What IS shared with the struct predicate -- and is the reason this is a
 * range test at all -- is the 2 GiB floor, which rejects None, small ints,
 * bools and the 31-bit `zlib.crc32(name) & 0x7fffffff` struct type-tags a
 * compiled `type(node)` yields in place of a class object. A `v > 65536`
 * test here classified every such tag as "definitely a string pointer" and
 * handed it to strlen -- CRASH.md's segfault. The upper bound is the struct
 * predicate's canonical-userspace ceiling (2^47), so a garbage 64-bit word
 * is not handed to strlen either.
 *
 * Being looser here than the struct path is not a new laxity: it accepts
 * every value the struct path's range test accepts, and is the same
 * discriminator mojo_str() already applies (any value above 64 KiB is a
 * `char *`), just with the 2 GiB floor and 2^47 ceiling that the CRASH.md
 * analysis showed are required.
 *
 * Struct-valued boxes (mojo_read_type_tag / mojo_read_type_tag_safe,
 * isinstance) keep the strict predicate: they are the ones that dereference.
 */
int mojo_boxed_is_str(int64_t v) {
    /* A BOX is pointer-shaped and is not a list, so without this third test
     * a boxed float read out of a heterogeneous list (`for x in
     * struct.unpack('<if', buf): print(x)`) was classified as a string and
     * handed to strlen — a wrong number turned into a segfault. The
     * discriminator is a live membership probe, not a shape test, so a box
     * is excluded wherever it has actually been built.
     *
     * The DICT and SET registries are excluded for the same reason and were
     * missing: a registered `MojoDict *` is exactly as pointer-shaped as a
     * registered `MojoList *`, so `d[some_dict] = 1` classified its own key as
     * a string and `strdup`'d the first bytes of the struct — a garbage key
     * and no diagnostic, where CPython raises `unhashable type: 'dict'`. All
     * three are excluded TOGETHER on purpose: this predicate's job is "is this
     * a boxed string", and a container of any kind is a different answer, so
     * adding one kind now and the other two later is how the list-only version
     * shipped in the first place. */
    return _mojo_ptr_shaped(v) && !mojo_is_registered_list(v)
        && !mojo_is_registered_dict(v) && !mojo_is_registered_set(v)
        && !mojo_is_boxed(v);
}

/* A Python tuple literal lowers to the exact same MojoList as a list literal
 * (see _lower_tuple_literal in gimple_codegen.py) — there is no separate
 * container struct — so the tuple marker below is the ONLY thing that
 * distinguishes a tuple from a list at runtime. It is consulted by repr (to
 * choose `(...)` over `[...]`), by isinstance (mojo_isinstance type_id 8),
 * and — since 2026-09-29 — by every MUTATING list operation below, which
 * refuse a marked list the way CPython refuses to mutate a tuple. See
 * mojo_require_mutable_list's own comment for why that had to be added. */
static _PtrReg _reg_tuple;

void mojo_mark_as_tuple(MojoList *l) {
    if (!l) return;
    _pr_add(&_reg_tuple, (uint64_t)(uintptr_t)l);
}

int mojo_is_tuple(MojoList *l) {
    if (!l) return 0;
    return _pr_has(&_reg_tuple, (uint64_t)(uintptr_t)l);
}

/* Every mutating MojoList entry point calls this first, so a tuple-marked
 * list behaves like a tuple rather than like a list that merely PRINTS like
 * one.
 *
 * The marker used to be purely decorative: `b'a=b'.partition(b'=')` carried
 * it, so `print(p)` was `(b'a', b'=', b'b')` and `isinstance(p, tuple)` was
 * True — but `p.append(b'z')` silently succeeded and `p[0] = b'x'` silently
 * overwrote, because the marker was read by repr and nothing else. That is
 * the whole content of the bug doc's item 6a: the doc concluded the residue
 * was unfixable for want of a tuple TYPE, but the type was already there and
 * simply was not load-bearing. CPython's answers, which this reproduces:
 *
 *   t.append(x)   -> AttributeError: 'tuple' object has no attribute 'append'
 *   t[0] = x      -> TypeError: 'tuple' object does not support item assignment
 *   del t[0]      -> TypeError: 'tuple' object doesn't support item deletion
 *
 * The distinction between the two exception TYPES is not cosmetic: the
 * method forms are an attribute lookup that fails, while the two item forms
 * are a container refusing the operation, and CPython's own `except` clauses
 * distinguish them. `attr` is the METHOD name for the attribute case, or NULL
 * for the item cases, which the two item messages below spell out.
 *
 * Forward-declared because the raise helpers are defined ~5000 lines below
 * (next to the other typed-exception raisers); the header declares all three
 * for generated code, but a definition is still needed here. */
static void mojo_raise_tuple_no_attr(const char *attr);
static void mojo_raise_tuple_item_error(const char *verb);

static void mojo_require_mutable_list(MojoList *l, const char *attr) {
    if (!mojo_is_tuple(l)) return;
    if (attr) mojo_raise_tuple_no_attr(attr);
    mojo_raise_tuple_item_error(NULL);
}

/* Bound-method registry — the runtime counterpart of _reg_list
 * above. `mojo_bound_method_new` (previously a static-inline in the
 * header) records every MojoBoundMethod it allocates here so that a
 * dynamically-dispatched call site (mojo_maybe_bound_call_N) can tell a
 * bound-method value apart from a plain function pointer stored in the
 * same void*-typed local. */
static _PtrReg _reg_bound_method;

MojoBoundMethod *mojo_bound_method_new(void *fn, void *self) {
    MojoBoundMethod *bm = (MojoBoundMethod *)malloc(sizeof(MojoBoundMethod));
    bm->fn = fn;
    bm->self = self;
    _pr_add(&_reg_bound_method, (uint64_t)(uintptr_t)bm);
    return bm;
}

int mojo_is_bound_method(void *p) {
    int64_t v = (int64_t)(intptr_t)p;
    if (v < 65536) return 0;
    return _pr_has(&_reg_bound_method, (uint64_t)v);
}

/* ── Variadic callables ──────────────────────────────────────────────────
 * A sibling of the bound-method registry above, for the same reason and
 * with the same shape: a variadic callable's VALUE is not a bare function
 * pointer, so a dynamically-dispatched call site has to be able to tell
 * it apart from one. What the callee really wants is its arguments
 * PACKED — `*args` into a MojoList, `**kwargs` into a MojoDict — and the
 * packed form is built here rather than at the call site because the call
 * site is the only place that knows the arity, while this is the only
 * place that knows the callee's real parameter list.
 *
 * The `v < 65536` guard is _mojo_ptr_shaped's, for the reason spelled out
 * on mojo_is_bound_method above. */
static _PtrReg _reg_vararg_fn;

MojoVarargFn *mojo_vararg_fn_new(void *fn, void *self, int64_t n_fixed, int64_t kind,
                                 int64_t has_env) {
    MojoVarargFn *vf = (MojoVarargFn *)malloc(sizeof(MojoVarargFn));
    vf->fn = fn;
    vf->self = self;
    vf->n_fixed = n_fixed;
    vf->kind = kind;
    vf->has_env = has_env;
    _pr_add(&_reg_vararg_fn, (uint64_t)(uintptr_t)vf);
    return vf;
}

int mojo_is_vararg_fn(void *p) {
    int64_t v = (int64_t)(intptr_t)p;
    if (v < 65536) return 0;
    return _pr_has(&_reg_vararg_fn, (uint64_t)v);
}

/* One packing routine, five arity wrappers. `a`/`n` are the arguments the
 * call site wrote, `kw` its already-packed keyword dict (NULL when it
 * passed none).
 *
 * The first `n_fixed` of them are ORDINARY leading parameters — the callee
 * declares them before its `*args`, so they stay positional and are passed
 * straight through as scalars. Everything after them is what `*args`
 * collects, packed into a fresh MojoList.
 *
 * `n_fixed` is bounded to 4 by the wrappers below (the call site has at
 * most 4 arguments to give), so the leading-parameter count can never
 * exceed the arity, and a callee wanting more fixed parameters than the
 * call site supplied is a call with too few arguments — real Python raises
 * TypeError for that; the extra slots read as 0 here, matching how every
 * other too-few-arguments call in this runtime behaves rather than
 * dereferencing past the end of `a`.
 */
static int64_t _mojo_vararg_invoke(MojoVarargFn *vf, const int64_t *a, int64_t n, MojoDict *kw) {
    int64_t nf = vf->n_fixed;
    if (nf < 0) nf = 0;
    if (nf > n) nf = n;
    /* `*args` collects everything past the fixed leading parameters. */
    MojoList *packed = 0;
    if (vf->kind != 2) {
        packed = mojo_list_new();
        for (int64_t i = nf; i < n; i++)
            mojo_list_append_int(packed, a[i]);
    }
    /* A `**kwargs` callee must never see NULL: `k['x']` on a NULL dict is a
     * segfault, and `len(k)` is a legitimate spelling. An empty dict is
     * the correct answer for a call that passed no keywords. */
    MojoDict *k = kw;
    if (vf->kind >= 1 && !k) k = mojo_dict_new();
    if (vf->kind == 0) k = 0;
    if (!vf->has_env) {
        /* No captures: the lifted callee has NO leading `self` parameter,
         * so passing one would shift every real parameter a slot left. */
        switch (nf) {
        case 0:
            if (vf->kind == 0) return ((int64_t (*)(MojoList *))vf->fn)(packed);
            if (vf->kind == 1) return ((int64_t (*)(MojoList *, MojoDict *))vf->fn)(packed, k);
            return ((int64_t (*)(MojoDict *))vf->fn)(k);
        case 1:
            if (vf->kind == 0) return ((int64_t (*)(int64_t, MojoList *))vf->fn)(a[0], packed);
            if (vf->kind == 1) return ((int64_t (*)(int64_t, MojoList *, MojoDict *))vf->fn)(a[0], packed, k);
            return ((int64_t (*)(int64_t, MojoDict *))vf->fn)(a[0], k);
        case 2:
            if (vf->kind == 0) return ((int64_t (*)(int64_t, int64_t, MojoList *))vf->fn)(a[0], a[1], packed);
            if (vf->kind == 1) return ((int64_t (*)(int64_t, int64_t, MojoList *, MojoDict *))vf->fn)(a[0], a[1], packed, k);
            return ((int64_t (*)(int64_t, int64_t, MojoDict *))vf->fn)(a[0], a[1], k);
        case 3:
            if (vf->kind == 0) return ((int64_t (*)(int64_t, int64_t, int64_t, MojoList *))vf->fn)(a[0], a[1], a[2], packed);
            if (vf->kind == 1) return ((int64_t (*)(int64_t, int64_t, int64_t, MojoList *, MojoDict *))vf->fn)(a[0], a[1], a[2], packed, k);
            return ((int64_t (*)(int64_t, int64_t, int64_t, MojoDict *))vf->fn)(a[0], a[1], a[2], k);
        default:
            if (vf->kind == 0) return ((int64_t (*)(int64_t, int64_t, int64_t, int64_t, MojoList *))vf->fn)(a[0], a[1], a[2], a[3], packed);
            if (vf->kind == 1) return ((int64_t (*)(int64_t, int64_t, int64_t, int64_t, MojoList *, MojoDict *))vf->fn)(a[0], a[1], a[2], a[3], packed, k);
            return ((int64_t (*)(int64_t, int64_t, int64_t, int64_t, MojoDict *))vf->fn)(a[0], a[1], a[2], a[3], k);
        }
    }
    switch (nf) {
    case 0:
        if (vf->kind == 0) return ((int64_t (*)(void *, MojoList *))vf->fn)(vf->self, packed);
        if (vf->kind == 1) return ((int64_t (*)(void *, MojoList *, MojoDict *))vf->fn)(vf->self, packed, k);
        return ((int64_t (*)(void *, MojoDict *))vf->fn)(vf->self, k);
    case 1:
        if (vf->kind == 0) return ((int64_t (*)(void *, int64_t, MojoList *))vf->fn)(vf->self, a[0], packed);
        if (vf->kind == 1) return ((int64_t (*)(void *, int64_t, MojoList *, MojoDict *))vf->fn)(vf->self, a[0], packed, k);
        return ((int64_t (*)(void *, int64_t, MojoDict *))vf->fn)(vf->self, a[0], k);
    case 2:
        if (vf->kind == 0) return ((int64_t (*)(void *, int64_t, int64_t, MojoList *))vf->fn)(vf->self, a[0], a[1], packed);
        if (vf->kind == 1) return ((int64_t (*)(void *, int64_t, int64_t, MojoList *, MojoDict *))vf->fn)(vf->self, a[0], a[1], packed, k);
        return ((int64_t (*)(void *, int64_t, int64_t, MojoDict *))vf->fn)(vf->self, a[0], a[1], k);
    case 3:
        if (vf->kind == 0) return ((int64_t (*)(void *, int64_t, int64_t, int64_t, MojoList *))vf->fn)(vf->self, a[0], a[1], a[2], packed);
        if (vf->kind == 1) return ((int64_t (*)(void *, int64_t, int64_t, int64_t, MojoList *, MojoDict *))vf->fn)(vf->self, a[0], a[1], a[2], packed, k);
        return ((int64_t (*)(void *, int64_t, int64_t, int64_t, MojoDict *))vf->fn)(vf->self, a[0], a[1], a[2], k);
    default:
        if (vf->kind == 0) return ((int64_t (*)(void *, int64_t, int64_t, int64_t, int64_t, MojoList *))vf->fn)(vf->self, a[0], a[1], a[2], a[3], packed);
        if (vf->kind == 1) return ((int64_t (*)(void *, int64_t, int64_t, int64_t, int64_t, MojoList *, MojoDict *))vf->fn)(vf->self, a[0], a[1], a[2], a[3], packed, k);
        return ((int64_t (*)(void *, int64_t, int64_t, int64_t, int64_t, MojoDict *))vf->fn)(vf->self, a[0], a[1], a[2], a[3], k);
    }
}

int64_t mojo_vararg_call_0(void *fp, void *kw) {
    return _mojo_vararg_invoke((MojoVarargFn *)fp, 0, 0, (MojoDict *)kw);
}
int64_t mojo_vararg_call_1(void *fp, void *kw, int64_t a) {
    int64_t v[1]; v[0] = a;
    return _mojo_vararg_invoke((MojoVarargFn *)fp, v, 1, (MojoDict *)kw);
}
int64_t mojo_vararg_call_2(void *fp, void *kw, int64_t a, int64_t b) {
    int64_t v[2]; v[0] = a; v[1] = b;
    return _mojo_vararg_invoke((MojoVarargFn *)fp, v, 2, (MojoDict *)kw);
}
int64_t mojo_vararg_call_3(void *fp, void *kw, int64_t a, int64_t b, int64_t c) {
    int64_t v[3]; v[0] = a; v[1] = b; v[2] = c;
    return _mojo_vararg_invoke((MojoVarargFn *)fp, v, 3, (MojoDict *)kw);
}
int64_t mojo_vararg_call_4(void *fp, void *kw, int64_t a, int64_t b, int64_t c, int64_t d) {
    int64_t v[4]; v[0] = a; v[1] = b; v[2] = c; v[3] = d;
    return _mojo_vararg_invoke((MojoVarargFn *)fp, v, 4, (MojoDict *)kw);
}

int64_t mojo_vararg_call_5(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4) {
    int64_t v[5]; v[0] = _a0; v[1] = _a1; v[2] = _a2; v[3] = _a3; v[4] = _a4;
    return _mojo_vararg_invoke((MojoVarargFn *)fp, v, 5, (MojoDict *)kw);
}

int64_t mojo_vararg_call_6(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5) {
    int64_t v[6]; v[0] = _a0; v[1] = _a1; v[2] = _a2; v[3] = _a3; v[4] = _a4; v[5] = _a5;
    return _mojo_vararg_invoke((MojoVarargFn *)fp, v, 6, (MojoDict *)kw);
}

int64_t mojo_vararg_call_7(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5, int64_t _a6) {
    int64_t v[7]; v[0] = _a0; v[1] = _a1; v[2] = _a2; v[3] = _a3; v[4] = _a4; v[5] = _a5; v[6] = _a6;
    return _mojo_vararg_invoke((MojoVarargFn *)fp, v, 7, (MojoDict *)kw);
}

int64_t mojo_vararg_call_8(void *fp, void *kw, int64_t _a0, int64_t _a1, int64_t _a2, int64_t _a3, int64_t _a4, int64_t _a5, int64_t _a6, int64_t _a7) {
    int64_t v[8]; v[0] = _a0; v[1] = _a1; v[2] = _a2; v[3] = _a3; v[4] = _a4; v[5] = _a5; v[6] = _a6; v[7] = _a7;
    return _mojo_vararg_invoke((MojoVarargFn *)fp, v, 8, (MojoDict *)kw);
}






/* Two frees for the two things a `MojoBoundMethod` can be, because `self`
 * belongs to only one of them:
 *
 *  - `mojo_bound_method_free` — a METHOD taken as a value (`f = self.m`,
 *    `readline.set_completer(self.complete)`). `self` is the receiver object,
 *    owned by whoever holds it; only the wrapper is ours. Its REGISTRY entry is
 *    discarded here, which is the whole reason this function exists and is
 *    what the container registries already do in their `_destroy` helpers: an
 *    address left in `_reg_bound_method` outlives its object, `malloc` hands
 *    that address straight back out for something else, and
 *    `mojo_is_bound_method` then reports a plain function pointer as a
 *    bound method — so `mojo_fnptr_call_N` dispatches through a
 *    `((int64_t (*)(void *))bm->fn)(bm->self)` on two words of whatever the
 *    new object is. That is the dangling-registry shape of
 *    bugs/CODEGEN_container_free_registry_dangling_entries.md, and it is what
 *    makes freeing a bound method safe to do at all.
 *  - `mojo_closure_free` — a CAPTURING LAMBDA. There `self` is the
 *    `malloc(sizeof(env))` emit_calls' closure constructor allocated one
 *    instruction earlier and filled with the captured values, and nothing
 *    else holds either half, so the pair is one allocation unit.
 *
 * Neither is `mojo_bound_method_new`'s default free: a bound method that
 * escapes (handed to a callee that stores it, returned, appended) must stay
 * alive, and codegen only reaches these for a value it has proven cannot.
 */
void mojo_bound_method_free(MojoBoundMethod *bm)
{
    if (!bm) return;
    _pr_del(&_reg_bound_method, (uint64_t)(uintptr_t)bm);
    free(bm);
}

void mojo_closure_free(void *bmv)
{
    MojoBoundMethod *bm = (MojoBoundMethod *)bmv;
    if (!bm) return;
    free(bm->self);
    mojo_bound_method_free(bm);
}

/* mojo_list_init/mojo_list_destroy: see mojo_set_init/mojo_set_destroy's
 * comment just above (same Phase 6 rationale, same refactor shape). */
void mojo_list_init(MojoList *l)
{
    l->data = l->inl;
    l->len  = 0;
    l->cap  = MOJO_LIST_INLINE;
    _pr_add(&_reg_list, (uint64_t)(uintptr_t)l);
}

void mojo_list_destroy(MojoList *l)
{
    _pr_del(&_reg_list, (uint64_t)(uintptr_t)l);
    _pr_del(&_reg_tuple, (uint64_t)(uintptr_t)l);
    _kinds_forget((uint64_t)(uintptr_t)l);
    if (l->data != l->inl) free(l->data);
}

MojoList *mojo_list_new(void)
{
    MojoList *l = malloc(sizeof(MojoList));
    mojo_list_init(l);
    return l;
}

void mojo_list_free(MojoList *l)
{
    mojo_list_destroy(l);
    free(l);
}

/* A list of STRINGS that the list SOLELY owns — every element freshly
 * allocated by the function that built the list, and by nothing else.
 * `mojo_list_append_str` stores the pointer it is given and never copies it
 * (see its definition above), so a plain `mojo_list_free` on such a list
 * releases the container and leaves every element behind: that is the
 * ~48 B/iteration of `String("a b c").split(" ")` in
 * bugs/CODEGEN_call_result_container_never_freed.md, where the list itself
 * was already being freed and only the strings inside it were not.
 *
 * The counterpart rule is what makes this safe: a list of strings is USUALLY
 * borrowed (string literals, `d[k]` read back out of a dict, the elements of
 * a list built by `extend`), and freeing those is a crash. So this is never
 * the default free for a `MojoList *` — codegen picks it only for a value it
 * has matched to one of the runtime functions in `_OWNS_STR_ELEMS`
 * (mojo/backend_gimple/emit_infra.py), each of which was read to allocate
 * every element it appends and to append nothing it did not allocate.
 * `mojo_str_rsplit` is deliberately NOT in that set: it hands its result the
 * very same pointers its own intermediate list holds. */
void mojo_list_free_owned_strs(MojoList *l)
{
    if (!l) return;
    for (int64_t i = 0; i < l->len; i++) free((void *)(intptr_t)l->data[i]);
    mojo_list_free(l);
}

static void _list_grow(MojoList *l)
{
    int64_t nc = l->cap * 2;
    if (l->data == l->inl) {
        /* Leaving the inline buffer: the elements must be COPIED out — the
         * inline storage is not a malloc block, realloc() on it is UB. */
        int64_t *nd = malloc((size_t)nc * sizeof(int64_t));
        memcpy(nd, l->inl, (size_t)l->len * sizeof(int64_t));
        l->data = nd;
    } else {
        l->data = realloc(l->data, (size_t)nc * sizeof(int64_t));
    }
    l->cap  = nc;
}

void mojo_list_append_int(MojoList *l, int64_t v)
{
    mojo_require_mutable_list(l, "append");
    if (l->len == l->cap) _list_grow(l);
    l->data[l->len++] = v;
}

void mojo_list_append_double(MojoList *l, double v)
{
    int64_t bits;
    memcpy(&bits, &v, sizeof(bits));
    mojo_list_append_int(l, bits);
}

void mojo_list_append_str(MojoList *l, const char *v)
{
    mojo_list_append_int(l, (int64_t)(uintptr_t)v);
}

/* Python negative-index semantics (list[-1] == list[len-1]) — none of the
 * list/string accessors below normalized this before; a negative index was
 * passed straight through to `data[i]`, reading out of bounds. Found via a
 * real crash: `line_nums[-1] if line_nums else 0` in mojo_compiler.py's
 * tokenizer, compiled with a NULL line_nums (empty input) — but the bug
 * itself is general, not specific to that call site. */
static int64_t _norm_idx(MojoList *l, int64_t i) {
    return i < 0 ? i + l->len : i;
}

int64_t mojo_list_get_int(MojoList *l, int64_t i)   { if (!l || l->len == 0) return 0; return l->data[_norm_idx(l, i)]; }

double mojo_list_get_double(MojoList *l, int64_t i)
{
    return mojo_double_from_bits(l->data[_norm_idx(l, i)]);
}


int64_t mojo_list_len(MojoList *l) { return l ? l->len : 0; }

int mojo_list_contains_int(MojoList *l, int64_t v)
{
    for (int64_t i = 0; i < l->len; i++)
        if (l->data[i] == v) return 1;
    return 0;
}

int mojo_list_contains_double(MojoList *l, double v)
{
    int64_t bits;
    memcpy(&bits, &v, sizeof(bits));
    return mojo_list_contains_int(l, bits);
}

/* `x in <list of bytes>`: elements are stored as boxed `MojoBytes *`
 * pointers, so membership is a CONTENT comparison (Python defines list
 * membership in terms of `==`, which for bytes is bytewise) rather than
 * the pointer identity mojo_list_contains_int would give. */
int mojo_list_contains_bytes(MojoList *l, MojoBytes *v)
{
    for (int64_t i = 0; i < l->len; i++) {
        MojoBytes *e = (MojoBytes *)(uintptr_t)l->data[i];
        if (mojo_bytes_eq(e, v)) return 1;
    }
    return 0;
}

int mojo_list_contains_str(MojoList *l, char *v)
{
    for (int64_t i = 0; i < l->len; i++) {
        char *s = (char *)(uintptr_t)l->data[i];
        /* A NULL needle is a real `None`/NULL value, not an error: a tuple
         * literal like `(None, '<conflict>')` stores None as a NULL element,
         * and `rt_prov not in (None, '<conflict>')` (gimple_codegen.py's
         * generator-provenance pass) legitimately probes it. Previously only
         * `s` was guarded, so strcmp(s, NULL) segfaulted on the second
         * iteration. Match Python: None == None. */
        if (v == NULL)
            return s == NULL ? 1 : 0;
        if (s && strcmp(s, v) == 0) return 1;
    }
    return 0;
}

/* `l.count(x)` — how many SLOTS equal x, the counting sibling of the
 * `x in l` predicates above. Distinct because those answer a yes/no from the
 * first hit and stop; these must visit every slot. Each takes the needle in
 * the domain its slot is stored in, for the same reason the membership
 * predicates do (a bytes/str element is a boxed pointer, and comparing that
 * as a raw int64_t slot would compare addresses). */
int64_t mojo_list_count_int(MojoList *l, int64_t v)
{
    int64_t n = 0;
    for (int64_t i = 0; i < l->len; i++) if (l->data[i] == v) n++;
    return n;
}

int64_t mojo_list_count_str(MojoList *l, char *v)
{
    int64_t n = 0;
    for (int64_t i = 0; i < l->len; i++) {
        char *s = (char *)(uintptr_t)l->data[i];
        if (v == NULL) { if (s == NULL) n++; }
        else if (s && strcmp(s, v) == 0) n++;
    }
    return n;
}

int64_t mojo_list_count_bytes(MojoList *l, MojoBytes *v)
{
    int64_t n = 0;
    for (int64_t i = 0; i < l->len; i++)
        if (mojo_bytes_eq((MojoBytes *)(uintptr_t)l->data[i], v)) n++;
    return n;
}

void mojo_list_set_int(MojoList *l, int64_t i, int64_t v)
{
    mojo_require_mutable_list(l, NULL);
    l->data[_norm_idx(l, i)] = v;
}

void mojo_list_set_double(MojoList *l, int64_t i, double v)
{
    mojo_require_mutable_list(l, NULL);
    int64_t bits;
    memcpy(&bits, &v, sizeof(bits));
    l->data[_norm_idx(l, i)] = bits;
}

void mojo_list_set_str(MojoList *l, int64_t i, char *v)
{
    mojo_require_mutable_list(l, NULL);
    l->data[_norm_idx(l, i)] = (int64_t)(uintptr_t)v;
}

/* list.insert(i, v): shift slots up from the tail, then store. Python
 * negative-index + clamp semantics (i<0 counts from the end; i>len appends).
 * All three element kinds share one int64 slot representation (doubles as
 * raw bits, strings as pointers — same convention as append/set above), so
 * a single slot-shifting helper covers them. Found missing via box.3d/game's
 * FileSystem.current_dir_path (`path_parts.insert(0, name)` silently no-op'd
 * — the unknown-method fallback dropped the call entirely — leaving every
 * path "/"-rooted). */
static void _mojo_list_insert_slot(MojoList *l, int64_t i, int64_t v)
{
    if (!l) return;
    int64_t n = l->len;
    if (i < 0) i += n;
    if (i < 0) i = 0;
    if (i > n) i = n;
    mojo_list_append_int(l, 0);      /* grow by exactly one slot */
    for (int64_t k = n; k > i; --k)
        l->data[k] = l->data[k - 1];
    l->data[i] = v;
}

void mojo_list_insert_int(MojoList *l, int64_t i, int64_t v)
{
    mojo_require_mutable_list(l, "insert");
    _mojo_list_insert_slot(l, i, v);
}

void mojo_list_insert_double(MojoList *l, int64_t i, double v)
{
    mojo_require_mutable_list(l, "insert");
    int64_t bits;
    memcpy(&bits, &v, sizeof(bits));
    _mojo_list_insert_slot(l, i, bits);
}

void mojo_list_insert_str(MojoList *l, int64_t i, char *v)
{
    mojo_require_mutable_list(l, "insert");
    _mojo_list_insert_slot(l, i, (int64_t)(uintptr_t)v);
}

char *mojo_list_get_str(MojoList *l, int64_t i)
{
    if (!l || l->len == 0) return "";
    return (char *)(uintptr_t)l->data[_norm_idx(l, i)];
}

MojoList *mojo_list_slice(MojoList *l, int64_t start, int64_t stop)
{
    /* stop == MOJO_SLICE_STOP_OMITTED means "no stop given" (`lst[start:]`)
     * — without this check, that omitted bound fell into `stop < 0` below
     * and got treated as a literal `stop=-1` (`lst[start:-1]`), silently
     * dropping the list's last element from every plain `lst[start:]`
     * slice. Same class of bug as mojo_cstr_slice's own sentinel fix. */
    if (stop == MOJO_SLICE_STOP_OMITTED) stop = l->len;
    if (start < 0) start = l->len + start;
    if (stop  < 0) stop  = l->len + stop;
    if (start < 0) start = 0;
    if (stop > l->len) stop = l->len;
    MojoList *r = mojo_list_new();
    for (int64_t i = start; i < stop; i++)
        mojo_list_append_int(r, l->data[i]);
    /* A slot-for-slot copy of `l`, so the result describes its slots exactly
     * as `l` does (a `struct.unpack` of a mixed format, a heterogeneous
     * literal). The comprehension above appends as plain int64_t, which loses
     * that description. */
    mojo_list_inherit_kinds(r, l);
    /* `t[:]` is a tuple when `t` is: slicing does not change a container's
     * type in Python, and the marker is a per-address registry entry rather
     * than a distinct container type, so without this the slice printed
     * `[1, 2.5]` where CPython prints `(1, 2.5)`. Same rule as
     * mojo_list_concat's. */
    if (mojo_is_tuple(l)) mojo_mark_as_tuple(r);
    return r;
}

/* `del lst[start:stop]` — removes elements [start, stop) in place, shifting
 * later elements down. Bound normalization mirrors mojo_list_slice exactly
 * (same negative-index/omitted-stop/clamping rules), since both lower from
 * the identical SliceExpr shape. */
void mojo_list_del_slice(MojoList *l, int64_t start, int64_t stop)
{
    if (!l) return;
    mojo_require_mutable_list(l, NULL);
    if (stop == MOJO_SLICE_STOP_OMITTED) stop = l->len;
    if (start < 0) start = l->len + start;
    if (stop  < 0) stop  = l->len + stop;
    if (start < 0) start = 0;
    if (stop > l->len) stop = l->len;
    if (start >= stop) return;
    int64_t n = stop - start;
    for (int64_t i = start; i < l->len - n; i++)
        l->data[i] = l->data[i + n];
    l->len -= n;
}

/* `lst[start:stop] = repl` — replace the elements [start, stop) in place
 * with a copy of `repl`'s elements, shifting the tail and growing/shrinking
 * the list by (repl->len - (stop - start)). Bound normalization mirrors
 * mojo_list_slice / mojo_list_del_slice exactly (negative-index wrap,
 * MOJO_SLICE_STOP_OMITTED, clamping); after clamping `stop < start` is
 * treated as `stop = start`, i.e. a pure insertion at `start` (`lst[i:i]
 * = repl`). Element slots are raw int64_t, as with every other MojoList
 * op — interpretation (int/double-bits/pointer) is the caller's. `repl`
 * is snapshotted first so `lst[a:b] = lst` (self-aliasing) is safe. */
void mojo_list_splice(MojoList *l, int64_t start, int64_t stop, MojoList *repl)
{
    if (!l) return;
    mojo_require_mutable_list(l, NULL);
    int64_t rlen = repl ? repl->len : 0;
    if (stop == MOJO_SLICE_STOP_OMITTED) stop = l->len;
    if (start < 0) start = l->len + start;
    if (stop  < 0) stop  = l->len + stop;
    if (start < 0) start = 0;
    if (start > l->len) start = l->len;
    if (stop < start) stop = start;
    if (stop > l->len) stop = l->len;

    int64_t *snap = NULL;
    if (rlen > 0) {
        snap = malloc((size_t)rlen * sizeof(int64_t));
        memcpy(snap, repl->data, (size_t)rlen * sizeof(int64_t));
    }

    int64_t gap    = stop - start;      /* slots removed */
    int64_t tail   = l->len - stop;     /* slots after the removed region */
    int64_t newlen = l->len - gap + rlen;

    while (l->cap < newlen)
        _list_grow(l);

    if (rlen > gap) {
        /* growing: shift the tail right, back-to-front */
        for (int64_t i = tail - 1; i >= 0; --i)
            l->data[start + rlen + i] = l->data[stop + i];
    } else if (rlen < gap) {
        /* shrinking: shift the tail left, front-to-back */
        for (int64_t i = 0; i < tail; ++i)
            l->data[start + rlen + i] = l->data[stop + i];
    }

    for (int64_t i = 0; i < rlen; ++i)
        l->data[start + i] = snap[i];

    l->len = newlen;
    free(snap);
}

/* Python's slice.indices(length): normalize (start, stop) for the given
 * sign of `step` into the half-open-ish bounds an extended slice walks. */
static void _mojo_slice_indices(int64_t length, int64_t step,
                                int has_start, int64_t start,
                                int has_stop, int64_t stop,
                                int64_t *out_start, int64_t *out_stop)
{
    int64_t lower, upper;
    if (step < 0) { lower = -1;      upper = length - 1; }
    else          { lower = 0;       upper = length;     }
    if (!has_start) {
        start = (step < 0) ? upper : lower;
    } else {
        if (start < 0) { start += length; if (start < lower) start = lower; }
        else if (start > upper) start = upper;
    }
    if (!has_stop) {
        stop = (step < 0) ? lower : upper;
    } else {
        if (stop < 0) { stop += length; if (stop < lower) stop = lower; }
        else if (stop > upper) stop = upper;
    }
    *out_start = start;
    *out_stop  = stop;
}

/* Number of elements an extended slice [start:stop:step] selects, with
 * start/stop already normalized by _mojo_slice_indices. */
static int64_t _mojo_slice_len(int64_t start, int64_t stop, int64_t step)
{
    if (step > 0)
        return start < stop ? (stop - start - 1) / step + 1 : 0;
    return start > stop ? (start - stop - 1) / (-step) + 1 : 0;
}

/* `lst[start:stop:step] = repl` for step != 1 (an "extended slice"
 * assignment). Python requires len(repl) to equal the number of slots the
 * slice selects — there is no growing/shrinking, each selected slot is
 * overwritten in order. Returns 0 on success, -1 for step == 0, and the
 * (positive) required length when it does not match len(repl) so the
 * length does not match (Python raises ValueError; the compiled runtime
 * has no ValueError object, so it reports and exits — an honest failure,
 * not a silent wrong result). `has_*` flags distinguish an omitted bound
 * (`lst[::2]`) from an explicit 0. */
void mojo_list_assign_step(MojoList *l,
                           int has_start, int64_t start,
                           int has_stop,  int64_t stop,
                           int64_t step,  MojoList *repl)
{
    if (!l) return;
    mojo_require_mutable_list(l, NULL);
    if (step == 0) {
        fprintf(stderr, "ValueError: slice step cannot be zero\n");
        exit(1);
    }
    int64_t s, e;
    _mojo_slice_indices(l->len, step, has_start, start, has_stop, stop, &s, &e);
    int64_t slen = _mojo_slice_len(s, e, step);
    int64_t rlen = repl ? repl->len : 0;
    if (slen != rlen) {
        fprintf(stderr,
                "ValueError: attempt to assign sequence of size %lld "
                "to extended slice of size %lld\n",
                (long long)rlen, (long long)slen);
        exit(1);
    }
    int64_t *snap = NULL;
    if (rlen > 0) {
        snap = malloc((size_t)rlen * sizeof(int64_t));
        memcpy(snap, repl->data, (size_t)rlen * sizeof(int64_t));
    }
    int64_t idx = s;
    for (int64_t i = 0; i < slen; ++i) { l->data[idx] = snap[i]; idx += step; }
    free(snap);
}

MojoList *mojo_list_concat(MojoList *a, MojoList *b)
{
    if (!a) a = mojo_list_new();
    if (!b) b = mojo_list_new();
    MojoList *r = mojo_list_new();
    for (int64_t i = 0; i < a->len; i++) mojo_list_append_int(r, a->data[i]);
    for (int64_t i = 0; i < b->len; i++) mojo_list_append_int(r, b->data[i]);
    /* `a + b` is a TUPLE if EITHER operand is: CPython's tuple has no
     * __add__ with a list (so `t + []` is a TypeError there, which this
     * runtime does not model), but the repr of the result is a tuple's, and
     * the marker is the only thing that decides it here. Propagating it is
     * what makes `(1,2) + (3,)` print `(1, 2, 3)` instead of `[1, 2, 3]`.
     * The marker is a per-address registry entry rather than a distinct
     * container type, so the result has to be marked like every other
     * derivation of one. */
    if (mojo_is_tuple(a) || mojo_is_tuple(b)) mojo_mark_as_tuple(r);
    /* `t + t` and `t + []` are described by the source kinds, repeated to
     * cover the result's slots; anything else (two lists whose kinds differ)
     * has ONE slot array and no single correct answer, so nothing is
     * recorded rather than something wrong. The repeated string is a fresh
     * allocation because the source's is shared with every copy of it. */
    {
        const char *ka = mojo_list_get_kinds(a);
        const char *kb = mojo_list_get_kinds(b);
        int64_t na = a->len, nb = b->len;
        if (ka && nb == 0) {
            mojo_list_set_kinds(r, ka);
        } else if (ka && kb && na == nb && strcmp(ka, kb) == 0) {
            char *kk = (char *)malloc((size_t)(na + nb) + 1);
            memcpy(kk, ka, (size_t)na);
            memcpy(kk + na, kb, (size_t)nb);
            kk[na + nb] = '\0';
            mojo_list_set_kinds(r, kk);
        }
    }
    /* The element repr propagates on the same terms as the kinds string
     * above: recorded on ONE side and nothing on the other, or recorded on
     * both and the SAME function. Two lists of different struct types
     * concatenated record nothing, because one slot array cannot describe
     * both -- which leaves the generic reader, exactly as before. */
    {
        _KindRow *ra = _kinds_row((uint64_t)(intptr_t)a);
        _KindRow *rb = _kinds_row((uint64_t)(intptr_t)b);
        char *(*rfa)(int64_t) = ra ? ra->repr_fn : NULL;
        char *(*rfb)(int64_t) = rb ? rb->repr_fn : NULL;
        if (rfa && !rfb) mojo_list_set_elem_repr(r, (void *)rfa);
        else if (rfa && rfb && rfa == rfb) mojo_list_set_elem_repr(r, (void *)rfa);
    }
    return r;
}

MojoList *mojo_list_repeat(MojoList *l, int64_t n)
{
    MojoList *r = mojo_list_new();
    for (int64_t rep = 0; rep < n; rep++)
        for (int64_t i = 0; i < l->len; i++)
            mojo_list_append_int(r, l->data[i]);
    /* `(1,2) * 2` is a tuple, for the same reason as mojo_list_concat. */
    if (mojo_is_tuple(l)) mojo_mark_as_tuple(r);
    /* Same as mojo_list_concat: the source kinds, repeated n times to cover
     * the result (a fresh string, since the source's is shared). */
    {
        const char *k = mojo_list_get_kinds(l);
        if (k && n > 0) {
            char *kk = (char *)malloc((size_t)(l->len * n) + 1);
            for (int64_t rep = 0; rep < n; rep++)
                memcpy(kk + rep * l->len, k, (size_t)l->len);
            kk[l->len * n] = '\0';
            mojo_list_set_kinds(r, kk);
        }
    }
    return r;
}

void mojo_list_print(MojoList *l)
{
    printf("[");
    for (int64_t i = 0; i < l->len; i++) {
        if (i) printf(", ");
        printf("%lld", (long long)l->data[i]);
    }
    printf("]");
}

/* ═══════════════════════════════════════════════════════════════════════
 * MojoStr
 * ═══════════════════════════════════════════════════════════════════════*/

struct MojoStr {
    char    *data;
    int64_t  len;
};

MojoStr *mojo_str_new(char *s)
{
    MojoStr *ms = malloc(sizeof(MojoStr));
    ms->len  = (int64_t)strlen(s);
    ms->data = malloc((size_t)ms->len + 1);
    memcpy(ms->data, s, (size_t)ms->len + 1);
    return ms;
}

void mojo_str_free(MojoStr *s)
{
    free(s->data);
    free(s);
}

MojoStr *mojo_str_concat(MojoStr *a, MojoStr *b)
{
    MojoStr *ms = malloc(sizeof(MojoStr));
    ms->len  = a->len + b->len;
    ms->data = malloc((size_t)ms->len + 1);
    memcpy(ms->data,           a->data, (size_t)a->len);
    memcpy(ms->data + a->len,  b->data, (size_t)b->len + 1);
    return ms;
}

int64_t     mojo_str_len(MojoStr *s)  { return s->len; }
char *mojo_str_data(MojoStr *s) { return s->data; }

/* Slicing a plain NUL-terminated char* (the common case: gimple_codegen.py
 * boxes an ordinary Python `str` as char*, not the MojoStr* wrapper struct —
 * that has its own mojo_str_slice above) has no length field to bound the
 * copy against, unlike MojoStr's `->len`. _lower_slice's previous fallback
 * for a plain pointer just added `start` to the pointer and returned that —
 * correct for `s[start:]` (a NUL-terminated string with the tail intact
 * naturally reads correctly to its own end), but `s[:stop]`/`s[start:stop]`
 * silently returned everything from `start` to the ORIGINAL string's real
 * end, completely ignoring `stop` — no truncation ever happened, since nothing
 * ever copied a shorter buffer or wrote a new NUL terminator. Found via
 * mojo_compiler.py's own `_strip_inline_comment(s)` (`return s[:i]`) never
 * actually removing anything, letting a `#`-comment's text — including
 * `for`/`import`/etc keywords — flow straight into the token stream once
 * self-hosted.
 *
 * `stop == MOJO_SLICE_STOP_OMITTED` is _lower_slice's sentinel for "no stop
 * given" (`s[start:]`) — a plain -1 doesn't work as that sentinel: it's
 * indistinguishable from a real `s[:-1]` request, which silently returned
 * the whole string unsliced instead of dropping the last character (found
 * via mojo_compiler.py's own backslash-line-continuation joining, whose
 * `line.rstrip()[:-1]` — meant to drop the trailing `\` — left it in place,
 * shifting every subsequent token's column on that logical line by one).
 * mojo_str_slice/mojo_list_slice had the same collision in the opposite
 * direction: their omitted-stop case fell into the `stop < 0` branch below
 * and got treated as literal `stop=-1`, silently dropping the last
 * character/element from every plain `x[start:]`. */
char *mojo_cstr_slice(char *s, int64_t start, int64_t stop)
{
    if (!s) { char *e = malloc(1); e[0] = '\0'; return e; }
    int64_t len;
    if (start < 0 || stop < 0 || stop == MOJO_SLICE_STOP_OMITTED) {
        /* Negative indices / "no stop given" need the true length to
         * resolve against. */
        len = (int64_t)strlen(s);
    } else {
        /* Common case (e.g. a tight scanning loop doing
         * mojo_cstr_slice(s, j, j+3) once per position while searching a
         * large string): both bounds are already concrete non-negative
         * indices, so all we need to know is whether `s` reaches `stop`
         * bytes - a scan bounded by `stop`, not a full strlen(). Before
         * this fix every call re-scanned the ENTIRE string just to pull
         * out a few bytes near the front of it, turning any such loop
         * quadratic - confirmed as the actual cause of a stage2-bootstrap
         * runaway (mojo_compiler.py's own py_tokenize scanning for a
         * closing triple-quote across mojo.py's ~900KB source, self-hosted,
         * took 100% CPU and dozens of GB before this fix).
         *
         * The scan is `memchr` rather than the byte-at-a-time loop this
         * used to be, which is the SAME value by definition (the offset of
         * the first NUL within s[0..stop), or `stop` when there is none)
         * and is what every libc already vectorises. Measured on the exact
         * scanning shape above (see
         * bugs/CODEGEN_selfhost_tokenize_region_eq_quadratic.md): 14x on
         * the same inputs, with a byte-for-byte equality check over every
         * position confirming the two agree.
         *
         * It is a constant-factor win, NOT a complexity one, and the doc
         * says why it cannot be more: a bare `char *` carries no length, so
         * "is `start` inside this string?" cannot be answered without a
         * scan from byte 0, and every caller of this function has to ask
         * that question (a slice whose start is past the end has to be
         * reported as the empty string). Making the scan start-relative,
         * which would be linear, means reading s[start] before anything
         * has established that index is in bounds. */
        {
            const char *nul = (const char *)memchr(s, '\0', (size_t)stop);
            len = nul ? (int64_t)(nul - s) : stop;
        }
    }
    if (stop == MOJO_SLICE_STOP_OMITTED) stop = len;
    if (start < 0) start += len;
    if (stop  < 0) stop  += len;
    if (start < 0) start = 0;
    if (stop > len) stop = len;
    if (start >= stop) { char *e = malloc(1); e[0] = '\0'; return e; }
    int64_t n = stop - start;
    char *out = malloc((size_t)n + 1);
    memcpy(out, s + start, (size_t)n);
    out[n] = '\0';
    return out;
}

/* reversed(<str>) modeled as an eagerly reversed copy (see
 * _lower_builtin_reversed). */
char *mojo_cstr_reverse(char *s)
{
    if (!s) { char *e = malloc(1); e[0] = '\0'; return e; }
    size_t n = strlen(s);
    char *out = malloc(n + 1);
    for (size_t i = 0; i < n; i++) out[i] = s[n - 1 - i];
    out[n] = '\0';
    return out;
}

/* `s[start:stop] == needle` without ever calling mojo_cstr_slice - no
 * malloc, no memcpy of the slice, no separate strcmp call. Added after a
 * `sample`-based CPU profile (not guessed) showed ~90% of ALL runtime, in
 * the exact stage2-bootstrap performance case this file's other fixes
 * target, inside mojo_cstr_slice's malloc+memcpy, called from
 * mojo_compiler.py's own self-hosted tokenizer doing
 * `while ... src[j:j+3] != quote3:` once per character while scanning for
 * a closing triple-quote: materializing a 3-byte heap string just to
 * immediately strcmp-and-discard it, over and over. gimple_codegen.py's
 * `_lower_binary` special-cases the AST shape `<slice> == / != <string>`
 * to call this instead of the generic slice-then-compare lowering. */
int mojo_cstr_region_eq(char *s, int64_t start, int64_t stop, char *needle)
{
    if (!s || !needle) return s == needle;
    int64_t len;
    if (start < 0 || stop < 0 || stop == MOJO_SLICE_STOP_OMITTED) {
        len = (int64_t)strlen(s);
        if (stop == MOJO_SLICE_STOP_OMITTED) stop = len;
        if (start < 0) start += len;
        if (stop  < 0) stop  += len;
    } else {
        /* Same value as the byte-at-a-time scan this replaced, for the
         * same reason mojo_cstr_slice's does (see the note there): it is
         * the offset of the first NUL in s[0..stop), or `stop`. memchr
         * computes it ~14x faster on the tokenizers' scanning shape. */
        const char *nul = (const char *)memchr(s, '\0', (size_t)stop);
        len = nul ? (int64_t)(nul - s) : stop;
    }
    if (start < 0) start = 0;
    if (stop > len) stop = len;
    if (start >= stop) return needle[0] == '\0';
    int64_t region_len = stop - start;
    size_t needle_len = strlen(needle);
    if ((size_t)region_len != needle_len) return 0;
    return memcmp(s + start, needle, needle_len) == 0;
}

MojoStr *mojo_str_slice(MojoStr *s, int64_t start, int64_t stop)
{
    /* See mojo_list_slice's identical fix: MOJO_SLICE_STOP_OMITTED (not a
     * plain -1) means "no stop given" (`s[start:]`), distinct from a real
     * `s[start:-1]`. */
    if (stop == MOJO_SLICE_STOP_OMITTED) stop = s->len;
    if (start < 0) start = s->len + start;
    if (stop  < 0) stop  = s->len + stop;
    if (start < 0) start = 0;
    if (stop > s->len) stop = s->len;
    if (start >= stop) {
        MojoStr *ms = malloc(sizeof(MojoStr));
        ms->len = 0; ms->data = malloc(1); ms->data[0] = '\0';
        return ms;
    }
    int64_t len = stop - start;
    MojoStr *ms = malloc(sizeof(MojoStr));
    ms->len  = len;
    ms->data = malloc((size_t)len + 1);
    memcpy(ms->data, s->data + start, (size_t)len);
    ms->data[len] = '\0';
    return ms;
}

MojoStr *mojo_str_from_char(char c)
{
    MojoStr *ms = malloc(sizeof(MojoStr));
    ms->len  = 1;
    ms->data = malloc(2);
    ms->data[0] = c;
    ms->data[1] = '\0';
    return ms;
}

MojoStr *mojo_str_repeat(MojoStr *s, int64_t n)
{
    if (n <= 0) {
        MojoStr *ms = malloc(sizeof(MojoStr));
        ms->len = 0; ms->data = malloc(1); ms->data[0] = '\0';
        return ms;
    }
    int64_t total = s->len * n;
    MojoStr *ms = malloc(sizeof(MojoStr));
    ms->len  = total;
    ms->data = malloc((size_t)total + 1);
    for (int64_t i = 0; i < n; i++)
        memcpy(ms->data + i * s->len, s->data, (size_t)s->len);
    ms->data[total] = '\0';
    return ms;
}

int64_t mojo_str_to_int(MojoStr *s)   { return (int64_t)atoll(s->data); }
double  mojo_str_to_float(MojoStr *s) { return atof(s->data); }

int mojo_str_eq(MojoStr *a, MojoStr *b)
{
    return a->len == b->len && memcmp(a->data, b->data, (size_t)a->len) == 0;
}

/* Null-safe strcmp: mirrors Python's None-vs-str comparison semantics
   (never crashes; None == None, None != any real string). Needed because
   a `str = None` default parameter lowers to a genuine NULL char *, and
   raw strcmp() on NULL segfaults. */
int mojo_cstr_cmp(char *a, char *b)
{
    if ((intptr_t)a < 65536 || (intptr_t)b < 65536)
        return (intptr_t)a - (intptr_t)b;
    if (a == NULL || b == NULL)
        return a == b ? 0 : 1;
    return strcmp(a, b);
}

int mojo_str_contains(char *haystack, char *needle)
{
    if ((intptr_t)haystack < 65536 || (intptr_t)needle < 65536) return 0;
    return strstr(haystack, needle) != NULL;
}

char mojo_str_char_at(MojoStr *s, int64_t i) { return s->data[i < 0 ? i + s->len : i]; }
void mojo_str_print(MojoStr *s) { fwrite(s->data, 1, (size_t)s->len, stdout); }

/* ── bytes ──────────────────────────────────────────────────────────────*/
/* The single MojoBytes allocator, so `readonly` has exactly one default:
 * immutable. Only the bytearray constructors (mojo_bytearray_new /
 * mojo_bytearray_copy, plus the mojo_bytearray_mark wrapper the backend
 * puts around the SHARED bytes constructors) clear it — a value produced
 * by any bytes operation is immutable, which is what lets every reader
 * (notably memoryview `.readonly`) trust the flag without asking where
 * the object came from. */
static MojoBytes *mojo_bytes_alloc(int64_t len)
{
    MojoBytes *b = malloc(sizeof(MojoBytes));
    b->len  = len;
    b->data = malloc((size_t)(len < 0 ? 0 : len) + 1);
    b->data[len < 0 ? 0 : len] = 0;
    b->readonly = 1;
    return b;
}

MojoBytes *mojo_bytes_new_lit(const char *data, int64_t len)
{
    MojoBytes *b = mojo_bytes_alloc(len);
    if (len > 0) memcpy(b->data, data, (size_t)len);
    return b;
}

MojoBytes *mojo_bytes_empty(void) { return mojo_bytes_alloc(0); }

MojoBytes *mojo_bytes_zeros(int64_t n)
{
    if (n < 0) n = 0;
    MojoBytes *b = mojo_bytes_alloc(n);
    memset(b->data, 0, (size_t)n);
    return b;
}

MojoBytes *mojo_bytes_from_list(MojoList *l)
{
    int64_t n = mojo_list_len(l);
    MojoBytes *b = mojo_bytes_alloc(n);
    for (int64_t i = 0; i < n; i++)
        b->data[i] = (uint8_t)(mojo_list_get_int(l, i) & 0xFF);
    return b;
}

MojoBytes *mojo_bytes_from_str(char *s, char *encoding)
{
    (void)encoding; /* utf-8 / ascii: source is already a UTF-8 char* */
    int64_t n = (int64_t)strlen(s);
    return mojo_bytes_new_lit(s, n);
}

/* NUL-terminated C string -> MojoBytes (copies up to the terminator).
 * Used by the `b'...' % args` lowering to fold a formatted numeric/str
 * spec (always ASCII, never embedded NUL) into the byte accumulator. */
MojoBytes *mojo_bytes_from_cstr(const char *s)
{
    if (s == NULL) return mojo_bytes_alloc(0);
    return mojo_bytes_new_lit(s, (int64_t)strlen(s));
}

static void mojo_bytes_clamp_range(MojoBytes *b, int64_t *start, int64_t *stop)
{
    int64_t lo = *start, hi = *stop;
    if (lo == MOJO_SLICE_STOP_OMITTED) lo = 0;
    if (hi == MOJO_SLICE_STOP_OMITTED) hi = b->len;
    if (lo < 0) lo += b->len;
    if (hi < 0) hi += b->len;
    if (lo < 0) lo = 0;
    if (hi > b->len) hi = b->len;
    if (hi < lo) hi = lo;
    *start = lo; *stop = hi;
}

int64_t mojo_bytes_len(MojoBytes *b) { return b->len; }

int64_t mojo_bytes_get(MojoBytes *b, int64_t i)
{
    if (i < 0) i += b->len;
    if (i < 0 || i >= b->len) return 0;
    return (int64_t)b->data[i];
}

/* `b[i]` at an EXPLICIT subscript — the same read, but an out-of-range
 * index RAISES IndexError instead of answering 0. mojo_bytes_get above
 * keeps the lenient form on purpose, because the `for b in <bytes>` loop
 * lowering calls it with an index it has already bounds-checked against
 * mojo_bytes_len, and a raising helper there would be a raise the program
 * can never reach.
 *
 * Without the split, `b'abc'[10]` and `b''[0]` both printed 0 with exit 0,
 * where CPython raises IndexError. 0 is not a neutral answer here: it is
 * a real byte value, so `if b[i] == 0:` on a short buffer silently took
 * the true branch. */
int64_t mojo_bytes_get_checked(MojoBytes *b, int64_t i)
{
    int64_t n = b ? b->len : 0;
    int64_t j = i < 0 ? i + n : i;
    if (j < 0 || j >= n) {
        char detail[96];
        snprintf(detail, sizeof detail, "index out of range");
        mojo_raise_index_error(detail);
    }
    return (int64_t)b->data[j];
}

int mojo_bytes_eq(MojoBytes *a, MojoBytes *b)
{
    if (a == b) return 1;
    if (a == NULL || b == NULL) return 0;
    return a->len == b->len && memcmp(a->data, b->data, (size_t)a->len) == 0;
}

/* The three-way sibling of mojo_bytes_eq, for `b'a' < b'b'` and for a bytes
 * ELEMENT of an ordered container (`[b'a'] < [b'b']`, which is what _slot_cmp
 * asks). A prefix orders first, same as every other sequence here. Defined
 * next to mojo_bytes_eq rather than at the ordering block because it is a
 * primitive of the bytes type, not of the comparison operators. */
int mojo_bytes_cmp(MojoBytes *a, MojoBytes *b)
{
    if (a == b) return 0;
    if (a == NULL || b == NULL) return MOJO_CMP_UNORDERABLE;
    int64_t n = a->len < b->len ? a->len : b->len;
    if (n > 0) {
        int r = memcmp(a->data, b->data, (size_t)n);
        if (r) return r < 0 ? -1 : 1;
    }
    if (a->len == b->len) return 0;
    return a->len < b->len ? -1 : 1;
}

int mojo_bytes_truthy(MojoBytes *b) { return b != NULL && b->len != 0; }

/* The `index`/`rindex` half of the find family over a BYTES needle: the
 * search itself is mojo_bytes_find / _rfind (which answer -1), and only
 * the FAILURE differs — CPython raises ValueError("subsection not found")
 * there. Kept as a wrapper rather than a duplicate search so the two can
 * never drift on where the match is. */
int64_t _mojo_bytes_index_or_raise(int64_t at) {
    if (at >= 0) return at;
    char detail[96];
    snprintf(detail, sizeof detail, "subsection not found");
    mojo_raise_value_error(detail);
    return -1;  /* unreached */
}

char *mojo_bytes_repr(MojoBytes *b)
{
    if (b == NULL) { char *s = malloc(5); memcpy(s, "None", 5); return s; }
    /* worst case per byte: \xNN == 4 chars, plus b'' and NUL */
    char *out = malloc((size_t)b->len * 4 + 4);
    size_t p = 0;
    out[p++] = 'b'; out[p++] = '\'';
    for (int64_t i = 0; i < b->len; i++) {
        unsigned c = b->data[i];
        if (c == '\\' || c == '\'') { out[p++] = '\\'; out[p++] = (char)c; }
        else if (c == '\n') { out[p++] = '\\'; out[p++] = 'n'; }
        else if (c == '\t') { out[p++] = '\\'; out[p++] = 't'; }
        else if (c == '\r') { out[p++] = '\\'; out[p++] = 'r'; }
        else if (c >= 32 && c < 127) { out[p++] = (char)c; }
        else { p += (size_t)sprintf(out + p, "\\x%02x", c); }
    }
    out[p++] = '\'';
    out[p] = 0;
    return out;
}

void mojo_bytes_print(MojoBytes *b)
{
    char *s = mojo_bytes_repr(b);
    fputs(s, stdout);
    free(s);
}

MojoBytes *mojo_bytes_concat(MojoBytes *a, MojoBytes *b)
{
    int64_t an = a ? a->len : 0, bn = b ? b->len : 0;
    MojoBytes *r = mojo_bytes_alloc(an + bn);
    if (an) memcpy(r->data, a->data, (size_t)an);
    if (bn) memcpy(r->data + an, b->data, (size_t)bn);
    return r;
}

MojoBytes *mojo_bytes_repeat(MojoBytes *b, int64_t n)
{
    if (n < 0) n = 0;
    int64_t bn = b ? b->len : 0;
    MojoBytes *r = mojo_bytes_alloc(bn * n);
    for (int64_t i = 0; i < n; i++)
        if (bn) memcpy(r->data + i * bn, b->data, (size_t)bn);
    return r;
}

/* Read-slice with step. start/stop use the same MOJO_SLICE_STOP_OMITTED
 * sentinel convention as mojo_list_slice; step defaults to 1. */
MojoBytes *mojo_bytes_slice(MojoBytes *b, int64_t start, int64_t stop, int64_t step)
{
    int64_t n = b ? b->len : 0;
    if (step == 0) step = 1;
    int64_t lo, hi;
    if (step > 0) {
        lo = (start == MOJO_SLICE_STOP_OMITTED) ? 0 : start;
        hi = (stop == MOJO_SLICE_STOP_OMITTED) ? n : stop;
        if (lo < 0) lo += n;
        if (hi < 0) hi += n;
        if (lo < 0) lo = 0;
        if (hi > n) hi = n;
    } else {
        lo = (start == MOJO_SLICE_STOP_OMITTED) ? n - 1 : start;
        hi = (stop == MOJO_SLICE_STOP_OMITTED) ? -1 : stop;
        if (lo < 0 && start != MOJO_SLICE_STOP_OMITTED) lo += n;
        if (hi < 0 && stop != MOJO_SLICE_STOP_OMITTED) hi += n;
        if (lo > n - 1) lo = n - 1;
    }
    /* count elements */
    int64_t cnt = 0;
    for (int64_t i = lo; (step > 0) ? (i < hi) : (i > hi); i += step)
        if (i >= 0 && i < n) cnt++;
    MojoBytes *r = mojo_bytes_alloc(cnt);
    int64_t p = 0;
    for (int64_t i = lo; (step > 0) ? (i < hi) : (i > hi); i += step)
        if (i >= 0 && i < n) r->data[p++] = b->data[i];
    return r;
}

int mojo_bytes_contains(MojoBytes *hay, MojoBytes *needle)
{
    if (!needle || needle->len == 0) return 1;
    if (!hay || hay->len < needle->len) return 0;
    for (int64_t i = 0; i + needle->len <= hay->len; i++)
        if (memcmp(hay->data + i, needle->data, (size_t)needle->len) == 0) return 1;
    return 0;
}

int64_t mojo_bytes_find(MojoBytes *hay, MojoBytes *needle)
{
    if (!needle || needle->len == 0) return 0;
    if (!hay || hay->len < needle->len) return -1;
    for (int64_t i = 0; i + needle->len <= hay->len; i++)
        if (memcmp(hay->data + i, needle->data, (size_t)needle->len) == 0) return i;
    return -1;
}

int64_t mojo_bytes_count(MojoBytes *hay, MojoBytes *needle)
{
    /* An EMPTY needle is not "never found" — CPython counts len+1 non-
     * overlapping empty matches, one before every character and one after
     * the last: `b'abc'.count(b'')` is 4 and `b''.count(b'')` is 1. The
     * loop below cannot produce either (it advances by needle->len, which
     * is 0, so it spins), which is why it answered 0 for both. */
    if (!hay) return 0;
    if (!needle || needle->len == 0) return hay->len + 1;
    int64_t c = 0;
    for (int64_t i = 0; i + needle->len <= hay->len; ) {
        if (memcmp(hay->data + i, needle->data, (size_t)needle->len) == 0) { c++; i += needle->len; }
        else i++;
    }
    return c;
}

/* count within an explicit [start, stop) range — non-overlapping, as in
 * Python. Matches mojo_bytes_find_from's sentinel convention. */
int64_t mojo_bytes_count_from(MojoBytes *hay, MojoBytes *needle,
                              int64_t start, int64_t stop)
{
    if (!hay) return 0;
    if (!needle || needle->len == 0) {
        mojo_bytes_clamp_range(hay, &start, &stop);
        return stop - start + 1;
    }
    mojo_bytes_clamp_range(hay, &start, &stop);
    int64_t c = 0;
    for (int64_t i = start; i + needle->len <= stop; ) {
        if (memcmp(hay->data + i, needle->data, (size_t)needle->len) == 0) { c++; i += needle->len; }
        else i++;
    }
    return c;
}

/* startswith / endswith, WITH the optional [start[, end]] window both take.
 *
 * The two-argument spellings `b.startswith(p, 1, 2)` were silently IGNORED:
 * the call sites passed only (bytes, prefix), so the answer was computed
 * over the WHOLE string and the window never applied. `b'abc'.startswith(
 * b'a', 1, 2)` was True where CPython says False, and `b'abc'.endswith(b'c',
 * 0, 2)` likewise — both plausible, both wrong, exit 0. The window is
 * sliced out first and the prefix/suffix then compared against that, which
 * is exactly CPython's own spelling. */
int mojo_bytes_startswith_from(MojoBytes *b, MojoBytes *p, int64_t start, int64_t stop)
{
    if (!b) return p && p->len == 0;
    mojo_bytes_clamp_range(b, &start, &stop);
    int64_t n = stop - start;
    if (!p || p->len == 0) return 1;
    if (n < p->len) return 0;
    return memcmp(b->data + start, p->data, (size_t)p->len) == 0;
}

int mojo_bytes_endswith_from(MojoBytes *b, MojoBytes *p, int64_t start, int64_t stop)
{
    if (!b) return p && p->len == 0;
    mojo_bytes_clamp_range(b, &start, &stop);
    int64_t n = stop - start;
    if (!p || p->len == 0) return 1;
    if (n < p->len) return 0;
    return memcmp(b->data + stop - p->len, p->data, (size_t)p->len) == 0;
}

int mojo_bytes_startswith(MojoBytes *b, MojoBytes *p)
{
    return mojo_bytes_startswith_from(b, p, 0, MOJO_SLICE_STOP_OMITTED);
}

int mojo_bytes_endswith(MojoBytes *b, MojoBytes *p)
{
    return mojo_bytes_endswith_from(b, p, 0, MOJO_SLICE_STOP_OMITTED);
}

char *mojo_bytes_decode(MojoBytes *b, char *encoding)
{
    (void)encoding;
    int64_t n = b ? b->len : 0;
    char *s = malloc((size_t)n + 1);
    if (n) memcpy(s, b->data, (size_t)n);
    s[n] = 0;
    return s;
}

char *mojo_bytes_hex(MojoBytes *b)
{
    int64_t n = b ? b->len : 0;
    char *s = malloc((size_t)n * 2 + 1);
    for (int64_t i = 0; i < n; i++)
        sprintf(s + i * 2, "%02x", b->data[i]);
    s[n * 2] = 0;
    return s;
}

/* Real, deterministic (but NOT cryptographic, and NOT bit-compatible with
 * Python's hashlib) digest over accumulated bytes — backs the compiled
 * codegen's hashlib.blake2b/md5/sha256(...).update(...).hexdigest() support
 * (see gimple_gen_methods.py's MojoBytes* 'update'/'hexdigest' cases).
 * Callers of this codegen's own hashlib usage (cas.py, build_stdlib_dylib.py,
 * py314_cache.py) only ever run under CPython's real hashlib — the compiled
 * mojoc binary never drives that build tooling itself — so this only needs
 * to let hashlib-using Python source COMPILE under self-host, not reproduce
 * Python's real digest bytes. FNV-1a 64-bit, run twice with different seeds
 * to fill a 32-hex-char string (arbitrary but fixed length, wide enough that
 * a mistaken 16-hex-char truncation elsewhere would still surface a bug). */
char *mojo_bytes_hash_hexdigest(MojoBytes *b)
{
    uint64_t h1 = 0xcbf29ce484222325ULL, h2 = 0x9e3779b97f4a7c15ULL;
    int64_t n = b ? b->len : 0;
    for (int64_t i = 0; i < n; i++) {
        h1 = (h1 ^ b->data[i]) * 0x100000001b3ULL;
        h2 = (h2 ^ (b->data[i] + 1)) * 0x100000001b3ULL;
    }
    char *s = malloc(33);
    sprintf(s, "%016llx%016llx", (unsigned long long)h1, (unsigned long long)h2);
    return s;
}

MojoBytes *mojo_bytes_replace(MojoBytes *b, MojoBytes *from, MojoBytes *to)
{
    return mojo_bytes_replace_n(b, from, to, MOJO_SLICE_STOP_OMITTED);
}

/* `count` bounds the number of replacements (MOJO_SLICE_STOP_OMITTED =
 * unbounded); a negative count also means "all", per Python. */
MojoBytes *mojo_bytes_replace_n(MojoBytes *b, MojoBytes *from, MojoBytes *to,
                                int64_t count)
{
    if (!b) return mojo_bytes_empty();
    if (!from || from->len == 0) {
        /* An EMPTY pattern is a real CPython spelling, not a no-op: it
         * matches at every one of the len+1 BOUNDARY positions — before
         * each character and after the last. `b'aaa'.replace(b'', b'-')`
         * is `b'-a-a-a-'` and `b''.replace(b'', b'-')` is `b'-'`. This
         * answered the string UNCHANGED, because the loop below advances
         * by from->len (0) and so never matched.
         *
         * The model, which `count` then bounds: walk the len+1 boundary
         * positions; at the first `count` of them emit the replacement and
         * at every one of them emit the character that follows (there is
         * none after the last). So the loop is over boundaries, not over
         * characters, and the tail needs no special case — position len is
         * simply a boundary with no character. */
        if (count == 0) return mojo_bytes_new_lit((const char *)b->data, b->len);
        if (count < 0) count = MOJO_SLICE_STOP_OMITTED;
        int64_t slots = (count == MOJO_SLICE_STOP_OMITTED) ? b->len + 1 : count;
        if (slots > b->len + 1) slots = b->len + 1;
        int64_t tn = to ? to->len : 0;
        MojoBytes *r = mojo_bytes_alloc(b->len + slots * tn);
        int64_t p = 0;
        for (int64_t k = 0; k <= b->len; k++) {
            if (k < slots && tn) memcpy(r->data + p, to->data, (size_t)tn);
            if (k < slots) p += tn;
            if (k < b->len) r->data[p++] = b->data[k];
        }
        r->len = p;
        r->data[p] = 0;
        return r;
    }
    if (count < 0) count = MOJO_SLICE_STOP_OMITTED;
    if (count == 0) return mojo_bytes_new_lit((const char *)b->data, b->len);
    int64_t total = mojo_bytes_count(b, from);
    if (count != MOJO_SLICE_STOP_OMITTED && total > count) total = count;
    int64_t tn = to ? to->len : 0;
    MojoBytes *r = mojo_bytes_alloc(b->len + total * (tn - from->len));
    int64_t p = 0, done = 0;
    for (int64_t i = 0; i < b->len; ) {
        if (i + from->len <= b->len && memcmp(b->data + i, from->data, (size_t)from->len) == 0) {
            if (tn) memcpy(r->data + p, to->data, (size_t)tn);
            p += tn; i += from->len;
            if (count != MOJO_SLICE_STOP_OMITTED && ++done >= count) {
                int64_t rest = b->len - i;
                if (rest) memcpy(r->data + p, b->data + i, (size_t)rest);
                p += rest;
                break;
            }
        } else r->data[p++] = b->data[i++];
    }
    r->len = p;
    r->data[p] = 0;
    return r;
}

static int mojo_bytes_isspace_byte(uint8_t c)
{ return c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v'; }

MojoBytes *mojo_bytes_strip(MojoBytes *b, MojoBytes *chars, int do_left, int do_right)
{
    if (!b) return mojo_bytes_empty();
    int64_t lo = 0, hi = b->len;
    #define IN_STRIP(c) (chars ? (memchr(chars->data, (c), (size_t)chars->len) != NULL) : mojo_bytes_isspace_byte(c))
    if (do_left)  while (lo < hi && IN_STRIP(b->data[lo])) lo++;
    if (do_right) while (hi > lo && IN_STRIP(b->data[hi - 1])) hi--;
    #undef IN_STRIP
    return mojo_bytes_new_lit((const char *)(b->data + lo), hi - lo);
}

MojoBytes *mojo_bytes_upper(MojoBytes *b)
{
    if (!b) return mojo_bytes_empty();
    MojoBytes *r = mojo_bytes_new_lit((const char *)b->data, b->len);
    for (int64_t i = 0; i < r->len; i++)
        if (r->data[i] >= 'a' && r->data[i] <= 'z') r->data[i] -= 32;
    return r;
}

MojoBytes *mojo_bytes_lower(MojoBytes *b)
{
    if (!b) return mojo_bytes_empty();
    MojoBytes *r = mojo_bytes_new_lit((const char *)b->data, b->len);
    for (int64_t i = 0; i < r->len; i++)
        if (r->data[i] >= 'A' && r->data[i] <= 'Z') r->data[i] += 32;
    return r;
}

static void mojo_bytes_list_push(MojoList *l, const uint8_t *d, int64_t n)
{
    MojoBytes *piece = mojo_bytes_new_lit((const char *)d, n);
    mojo_list_append_int(l, (int64_t)(uintptr_t)piece);
}

MojoList *mojo_bytes_split(MojoBytes *b, MojoBytes *sep)
{
    MojoList *l = mojo_list_new();
    if (!b) return l;
    if (!sep || sep->len == 0) {
        /* whitespace split, no empty pieces */
        int64_t i = 0;
        while (i < b->len) {
            while (i < b->len && mojo_bytes_isspace_byte(b->data[i])) i++;
            if (i >= b->len) break;
            int64_t start = i;
            while (i < b->len && !mojo_bytes_isspace_byte(b->data[i])) i++;
            mojo_bytes_list_push(l, b->data + start, i - start);
        }
        return l;
    }
    int64_t start = 0;
    for (int64_t i = 0; i + sep->len <= b->len; ) {
        if (memcmp(b->data + i, sep->data, (size_t)sep->len) == 0) {
            mojo_bytes_list_push(l, b->data + start, i - start);
            i += sep->len; start = i;
        } else i++;
    }
    mojo_bytes_list_push(l, b->data + start, b->len - start);
    return l;
}

MojoList *mojo_bytes_rsplit(MojoBytes *b, MojoBytes *sep)
{
    /* no maxsplit support: same result set as split, just reuse it */
    return mojo_bytes_split(b, sep);
}

MojoList *mojo_bytes_splitlines(MojoBytes *b)
{
    MojoList *l = mojo_list_new();
    if (!b) return l;
    int64_t start = 0;
    for (int64_t i = 0; i < b->len; i++) {
        if (b->data[i] == '\n') {
            mojo_bytes_list_push(l, b->data + start, i - start);
            start = i + 1;
        }
    }
    if (start < b->len) mojo_bytes_list_push(l, b->data + start, b->len - start);
    return l;
}

MojoBytes *mojo_bytes_join(MojoBytes *sep, MojoList *parts)
{
    if (!parts) return mojo_bytes_empty();
    int64_t n = mojo_list_len(parts);
    int64_t total = 0;
    int64_t sn = sep ? sep->len : 0;
    for (int64_t i = 0; i < n; i++) {
        MojoBytes *p = (MojoBytes *)(uintptr_t)mojo_list_get_int(parts, i);
        total += (p ? p->len : 0);
        if (i) total += sn;
    }
    MojoBytes *r = mojo_bytes_alloc(total);
    int64_t off = 0;
    for (int64_t i = 0; i < n; i++) {
        if (i && sn) { memcpy(r->data + off, sep->data, (size_t)sn); off += sn; }
        MojoBytes *p = (MojoBytes *)(uintptr_t)mojo_list_get_int(parts, i);
        if (p && p->len) { memcpy(r->data + off, p->data, (size_t)p->len); off += p->len; }
    }
    return r;
}

/* ── bytes: search with explicit range, and the int-valued (bytearray)
 * flavours of index/count ─────────────────────────────────────────────────
 * Python's optional [start[, end]] argument clamps into the buffer, handles
 * negatives, and tolerates start > end (empty range). `start`/`stop` use the
 * MOJO_SLICE_STOP_OMITTED sentinel for "not given". */
int64_t mojo_bytes_find_from(MojoBytes *hay, MojoBytes *needle,
                             int64_t start, int64_t stop)
{
    if (!needle || needle->len == 0) return -1;
    if (!hay) return -1;
    mojo_bytes_clamp_range(hay, &start, &stop);
    for (int64_t i = start; i + needle->len <= stop; i++)
        if (memcmp(hay->data + i, needle->data, (size_t)needle->len) == 0) return i;
    return -1;
}

int64_t mojo_bytes_rfind_from(MojoBytes *hay, MojoBytes *needle,
                              int64_t start, int64_t stop)
{
    if (!needle || needle->len == 0) return -1;
    if (!hay) return -1;
    mojo_bytes_clamp_range(hay, &start, &stop);
    for (int64_t i = stop - needle->len; i >= start; i--)
        if (memcmp(hay->data + i, needle->data, (size_t)needle->len) == 0) return i;
    return -1;
}

int64_t mojo_bytes_rfind(MojoBytes *hay, MojoBytes *needle)
{
    return mojo_bytes_rfind_from(hay, needle, 0, MOJO_SLICE_STOP_OMITTED);
}

/* index/count over a single byte VALUE (bytearray.index(x) /
 * bytes.index(<int>) — Python accepts an int in 0-255 there). */
int64_t mojo_bytes_index_int(MojoBytes *b, int64_t v, int64_t start, int64_t stop)
{
    int64_t at = mojo_bytes_find_int(b, v, start, stop);
    if (at < 0) {
        char detail[96];
        snprintf(detail, sizeof detail, "subsection not found");
        mojo_raise_value_error(detail);
    }
    return at;
}

int64_t mojo_bytes_rindex_int(MojoBytes *b, int64_t v, int64_t start, int64_t stop)
{
    int64_t at = mojo_bytes_rfind_int(b, v, start, stop);
    if (at < 0) {
        char detail[96];
        snprintf(detail, sizeof detail, "subsection not found");
        mojo_raise_value_error(detail);
    }
    return at;
}

/* find / rfind / index / rindex over a single byte VALUE (the `b.index(0x2c)`
 * spelling). `mojo_bytes_index_int` is the FIND-shaped one: it answers -1
 * when absent, which is what `find`/`rfind` return. `index`/`rindex` are the
 * same search with a different failure — they RAISE ValueError — so they get
 * their own entry points below rather than sharing this one, which is what
 * made `b'abc'.index(b'z')` answer -1 with exit 0.
 *
 * A value outside 0-255 is a ValueError in CPython (`b'abc'.count(300)`), not
 * a silently wrapped one; `& 0xFF` below is what turned 300 into 44 and made
 * `count(300)` count the letter 'c'. */
static void mojo_bytes_check_byte_value(int64_t v) {
    if (v >= 0 && v <= 255) return;
    char detail[96];
    snprintf(detail, sizeof detail,
             "byte must be in range(0, 256)");
    mojo_raise_value_error(detail);
}

int64_t mojo_bytes_find_int(MojoBytes *b, int64_t v, int64_t start, int64_t stop)
{
    mojo_bytes_check_byte_value(v);
    if (!b) return -1;
    mojo_bytes_clamp_range(b, &start, &stop);
    for (int64_t i = start; i < stop; i++)
        if ((int64_t)b->data[i] == v) return i;
    return -1;
}

int64_t mojo_bytes_rfind_int(MojoBytes *b, int64_t v, int64_t start, int64_t stop)
{
    mojo_bytes_check_byte_value(v);
    if (!b) return -1;
    mojo_bytes_clamp_range(b, &start, &stop);
    for (int64_t i = stop - 1; i >= start; i--)
        if ((int64_t)b->data[i] == v) return i;
    return -1;
}

int64_t mojo_bytes_count_int(MojoBytes *b, int64_t v, int64_t start, int64_t stop)
{
    mojo_bytes_check_byte_value(v);
    if (!b) return 0;
    mojo_bytes_clamp_range(b, &start, &stop);
    int64_t c = 0;
    for (int64_t i = start; i < stop; i++) if ((int64_t)b->data[i] == v) c++;
    return c;
}

MojoBytes *mojo_bytes_removeprefix(MojoBytes *b, MojoBytes *p)
{
    if (!b) return mojo_bytes_empty();
    if (mojo_bytes_startswith(b, p)) return mojo_bytes_new_lit((const char *)(b->data + p->len),
                                                               b->len - p->len);
    return mojo_bytes_new_lit((const char *)b->data, b->len);
}

MojoBytes *mojo_bytes_removesuffix(MojoBytes *b, MojoBytes *p)
{
    if (!b) return mojo_bytes_empty();
    if (mojo_bytes_endswith(b, p)) return mojo_bytes_new_lit((const char *)b->data,
                                                            b->len - p->len);
    return mojo_bytes_new_lit((const char *)b->data, b->len);
}

MojoBytes *mojo_bytes_capitalize(MojoBytes *b)
{
    if (!b) return mojo_bytes_empty();
    MojoBytes *r = mojo_bytes_new_lit((const char *)b->data, b->len);
    for (int64_t i = 0; i < r->len; i++) {
        uint8_t c = r->data[i];
        if (c >= 'a' && c <= 'z') r->data[i] = (uint8_t)(c - 32);
        else if (i > 0 && mojo_bytes_isspace_byte(c)) continue; /* rest lowercased below */
    }
    /* everything after the first cased character is lowercase */
    int seen = 0;
    for (int64_t i = 0; i < r->len; i++) {
        uint8_t c = r->data[i];
        if (!seen) {
            if (c >= 'a' && c <= 'z') { r->data[i] = (uint8_t)(c - 32); seen = 1; }
            else if (c >= 'A' && c <= 'Z') seen = 1;
            continue;
        }
        if (c >= 'A' && c <= 'Z') r->data[i] = (uint8_t)(c + 32);
    }
    return r;
}

MojoBytes *mojo_bytes_swapcase(MojoBytes *b)
{
    if (!b) return mojo_bytes_empty();
    MojoBytes *r = mojo_bytes_new_lit((const char *)b->data, b->len);
    for (int64_t i = 0; i < r->len; i++) {
        uint8_t c = r->data[i];
        if (c >= 'a' && c <= 'z') r->data[i] = (uint8_t)(c - 32);
        else if (c >= 'A' && c <= 'Z') r->data[i] = (uint8_t)(c + 32);
    }
    return r;
}

/* ASCII title-casing: first cased char of each whitespace-delimited word
 * uppercased, the rest lowercased (bytes has no cased-ness beyond ASCII). */
MojoBytes *mojo_bytes_title(MojoBytes *b)
{
    if (!b) return mojo_bytes_empty();
    MojoBytes *r = mojo_bytes_new_lit((const char *)b->data, b->len);
    int prev_alpha = 0;
    for (int64_t i = 0; i < r->len; i++) {
        uint8_t c = r->data[i];
        int alpha = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
        if (prev_alpha) {
            if (c >= 'A' && c <= 'Z') r->data[i] = (uint8_t)(c + 32);
        } else if (c >= 'a' && c <= 'z') {
            r->data[i] = (uint8_t)(c - 32);
        }
        prev_alpha = alpha;
    }
    return r;
}

/* ljust/rjust/center/zfill. `mode`: 0 = ljust (pad on the right), 1 = rjust
 * (pad on the left), 2 = center. `signbit` is 1 for zfill (pad with '0',
 * keeping a leading sign in front of the zeros, matching Python). */
/* CPython's `center` split of the pad, shared by the str and bytes padders
 * below: `marg // 2` on the left, plus one MORE on the left when both
 * `marg` and `width` are odd — which is literally CPython's
 * `left = marg // 2 + (marg & width & 1)`. Plain `marg // 2` puts the odd
 * pad byte on the wrong side whenever it matters: `'ab'.center(5, '_')` is
 * `__ab_` in CPython, `_ab__` with the floor. */
static int64_t _center_left(int64_t marg, int64_t width)
{ return marg / 2 + (marg & width & 1); }

static MojoBytes *mojo_bytes_pad(MojoBytes *b, int64_t width, int fill,
                                 int mode, int signbit)
{
    int64_t n = b ? b->len : 0;
    if (width <= n) return mojo_bytes_new_lit(b ? (const char *)b->data : "", n);
    int has_sign = signbit && n > 0 && (b->data[0] == '+' || b->data[0] == '-');
    int64_t total = width - n;
    /* `before` = pad bytes placed BEFORE the content: 0 for ljust, all of
     * them for rjust/zfill, and CPython's center split for center. */
    int64_t before = mode == 0 ? 0 : (mode == 1 ? total : _center_left(total, width));
    if (has_sign) before++;
    MojoBytes *r = mojo_bytes_alloc(width);
    memset(r->data, fill, (size_t)width);
    if (has_sign) r->data[0] = b->data[0];
    if (n) memcpy(r->data + before, b->data + (has_sign ? 1 : 0), (size_t)(n - (has_sign ? 1 : 0)));
    return r;
}

MojoBytes *mojo_bytes_ljust(MojoBytes *b, int64_t width, int fill)
{ return mojo_bytes_pad(b, width, fill & 0xFF, 0, 0); }

MojoBytes *mojo_bytes_rjust(MojoBytes *b, int64_t width, int fill)
{ return mojo_bytes_pad(b, width, fill & 0xFF, 1, 0); }

MojoBytes *mojo_bytes_center(MojoBytes *b, int64_t width, int fill)
{ return mojo_bytes_pad(b, width, fill & 0xFF, 2, 0); }

MojoBytes *mojo_bytes_zfill(MojoBytes *b, int64_t width)
{ return mojo_bytes_pad(b, width, '0', 1, 1); }

/* ljust/rjust/center's `fillchar`, as the single byte it names.
 * CPython accepts ONLY a one-byte bytes here and raises TypeError on
 * anything else (`b'a'.ljust(4, b'..')`, `b'a'.ljust(4, 46)`), so the
 * length check has to happen where the value is known — the fill
 * expression is not a compile-time constant, and the backend used to
 * read it as a scalar, which for a MojoBytes * meant the LOW BYTE OF A
 * HEAP ADDRESS: `b'a'.ljust(4, b'.')` printed a different wrong value on
 * every run. Raising beats silently padding with the first byte, which
 * is what a length-tolerant version would do. */
int mojo_bytes_fill_byte(MojoBytes *fill)
{
    int64_t n = fill ? fill->len : 0;
    if (n != 1) {
        char detail[128];
        snprintf(detail, sizeof(detail),
                 "ljust() argument 2 must be a byte string of length 1, not %lld",
                 (long long)n);
        mojo_raise_type_error(detail);
        return ' ';
    }
    return (int)fill->data[0];
}

/* partition/rpartition -> a 3-element list (head, sep, tail). `from_right`
 * searches for the LAST occurrence instead of the first. */
/* partition/rpartition -> a 3-element TUPLE (head, sep, tail), which is a
 * MojoList * carrying the mojo_mark_as_tuple marker — the same shape a tuple
 * LITERAL lowers to (see mojo_mark_as_tuple's doc comment). It used to return
 * an unmarked list, so `print(b'a=b'.partition(b'='))` showed
 * `[b'a', b'=', b'b']` where CPython shows `(b'a', b'=', b'b')`. Only the
 * REPR was wrong: this representation has no separate tuple type, so
 * indexing, len() and iteration were already correct. The marker is what
 * _mojo_repr_list consults to pick the brackets. */
static MojoList *mojo_bytes_partition_go(MojoBytes *b, MojoBytes *sep, int from_right)
{
    MojoList *l = mojo_list_new();
    int64_t n = b ? b->len : 0;
    int64_t sn = (sep && sep->len) ? sep->len : 0;
    if (sn == 0) {
        /* An EMPTY separator is a ValueError in CPython, not a
         * never-found separator: `b'a=b'.partition(b'')` raises, where the
         * arms below answer `(b'', b'', b'a=b')`. Same distinction `split`
         * already draws (mojo_bytes_split_max's whitespace-split branch is
         * only for a genuinely absent sep). */
        {
            char detail[96];
            snprintf(detail, sizeof(detail), "empty separator");
            mojo_raise_value_error(detail);
        }
        mojo_bytes_list_push(l, (const uint8_t *)"", 0);
        mojo_bytes_list_push(l, (const uint8_t *)"", 0);
        mojo_bytes_list_push(l, b ? b->data : (const uint8_t *)"", n);
        mojo_mark_as_tuple(l);
        return l;
    }
    int64_t at = from_right ? mojo_bytes_rfind_from(b, sep, 0, n)
                            : mojo_bytes_find_from(b, sep, 0, n);
    if (at < 0) {
        /* No separator: CPython's answer is the WHOLE string in the piece
         * the method searches from, and two empty separators beside it —
         * `b'abc'.partition(b'=')` is `(b'abc', b'', b'')` and
         * `b'abc'.rpartition(b'=')` is `(b'', b'', b'abc')`. These two arms
         * were SWAPPED, so each method returned the other's answer on
         * exactly the input where they differ; a `sep` that is not present
         * is the common case, not an edge case. */
        if (from_right) {
            mojo_bytes_list_push(l, (const uint8_t *)"", 0);
            mojo_bytes_list_push(l, (const uint8_t *)"", 0);
            mojo_bytes_list_push(l, b ? b->data : (const uint8_t *)"", n);
        } else {
            mojo_bytes_list_push(l, b ? b->data : (const uint8_t *)"", n);
            mojo_bytes_list_push(l, (const uint8_t *)"", 0);
            mojo_bytes_list_push(l, (const uint8_t *)"", 0);
        }
        mojo_mark_as_tuple(l);
        return l;
    }
    mojo_bytes_list_push(l, b->data, at);
    mojo_bytes_list_push(l, sep->data, sn);
    mojo_bytes_list_push(l, b->data + at + sn, n - at - sn);
    mojo_mark_as_tuple(l);
    return l;
}

MojoList *mojo_bytes_partition(MojoBytes *b, MojoBytes *sep)
{ return mojo_bytes_partition_go(b, sep, 0); }

MojoList *mojo_bytes_rpartition(MojoBytes *b, MojoBytes *sep)
{ return mojo_bytes_partition_go(b, sep, 1); }

/* bytes.fromhex: pairs of hex digits, ASCII whitespace ignored. */
MojoBytes *mojo_bytes_fromhex(char *s)
{
    int64_t n = s ? (int64_t)strlen(s) : 0;
    MojoBytes *r = mojo_bytes_alloc(n / 2);
    r->len = 0;   /* whitespace is skipped below, so the real count is less */
    int hi = -1;
    for (int64_t i = 0; i < n; i++) {
        char c = s[i];
        if (mojo_bytes_isspace_byte((uint8_t)c)) continue;
        int v;
        if (c >= '0' && c <= '9') v = c - '0';
        else if (c >= 'a' && c <= 'f') v = c - 'a' + 10;
        else if (c >= 'A' && c <= 'F') v = c - 'A' + 10;
        else { fprintf(stderr, "ValueError: non-hexadecimal number found in fromhex() arg\n"); exit(1); }
        if (hi < 0) hi = v;
        else { r->data[r->len++] = (uint8_t)((hi << 4) | v); hi = -1; }
    }
    if (hi >= 0) { fprintf(stderr, "ValueError: non-hexadecimal number found in fromhex() arg\n"); exit(1); }
    return r;
}

/* bytes.maketrans(from, to) -> a 256-byte translation table. */
MojoBytes *mojo_bytes_maketrans(MojoBytes *from, MojoBytes *to)
{
    MojoBytes *t = mojo_bytes_zeros(256);
    int64_t fn = from ? from->len : 0;
    int64_t tn = to ? to->len : 0;
    for (int64_t i = 0; i < 256; i++) t->data[i] = (uint8_t)i;
    for (int64_t i = 0; i < fn && i < tn; i++) t->data[from->data[i]] = to->data[i];
    return t;
}

/* `b.translate(table, delete)` — the two-argument form. The `delete` SET was
 * silently dropped: the call site passed only the table, so
 * `b'hello'.translate(None, b'l')` came back as `b'hello'` where CPython
 * answers `b'heo'`. `delete` is applied FIRST (a byte in the set is removed
 * and never translated); `table` is a 256-entry lookup and may be NULL,
 * which means "keep every surviving byte as itself" — CPython spells that
 * `b'hello'.translate(None, b'l')`, and None is exactly the no-table case.
 * `table` of any other length is a ValueError in CPython ("translation
 * table must be 256 characters long"), and is one here rather than a
 * partially-applied table, which is what a short table silently produced. */
MojoBytes *mojo_bytes_translate_del(MojoBytes *b, MojoBytes *table, MojoBytes *delbytes)
{
    if (!b) return mojo_bytes_empty();
    if (table && table->len != 256) {
        char detail[96];
        snprintf(detail, sizeof detail,
                 "translation table must be 256 characters long");
        mojo_raise_value_error(detail);
    }
    MojoBytes *r = mojo_bytes_alloc(b->len);
    int64_t p = 0;
    for (int64_t i = 0; i < b->len; i++) {
        uint8_t c = b->data[i];
        if (delbytes && memchr(delbytes->data, c, (size_t)delbytes->len)) continue;
        r->data[p++] = table ? table->data[c] : c;
    }
    r->len = p;
    r->data[p] = 0;
    return r;
}

MojoBytes *mojo_bytes_translate(MojoBytes *b, MojoBytes *table)
{
    if (!b) return mojo_bytes_empty();
    if (!table) return mojo_bytes_new_lit((const char *)b->data, b->len);
    if (table->len != 256) {
        char detail[96];
        snprintf(detail, sizeof detail,
                 "translation table must be 256 characters long");
        mojo_raise_value_error(detail);
    }
    MojoBytes *r = mojo_bytes_new_lit((const char *)b->data, b->len);
    for (int64_t i = 0; i < r->len; i++) {
        uint8_t c = r->data[i];
        r->data[i] = table->data[c];
    }
    return r;
}

/* `bytes.expandtabs([tabsize])` — the bytes twin of mojo_str_expandtabs,
 * which already existed. This had NO bytes implementation at all, so the
 * call fell through to the generic unknown-method stub and answered a raw
 * int `0` (printed as `0`, not even a plausible-looking empty bytes) for
 * every spelling. `tabsize` defaults to 8, and a non-positive tabsize
 * REMOVES the tab rather than leaving it alone — CPython's
 * `b'a\tb\tc'.expandtabs(0)` is `b'abc'`, and this returned the input
 * unchanged. Column counting resets on `\n` and `\r` only (not on `\f` or
 * `\v`, which occupy a column), matching both this and mojo_str_expandtabs. */
MojoBytes *mojo_bytes_expandtabs(MojoBytes *b, int64_t tabsize)
{
    int64_t n = b ? b->len : 0;
    if (tabsize <= 0) {
        MojoBytes *r = mojo_bytes_alloc(n + 1);
        int64_t q = 0;
        for (int64_t i = 0; i < n; i++) if (b->data[i] != '\t') r->data[q++] = b->data[i];
        r->len = q;
        r->data[q] = 0;
        return r;
    }
    MojoBytes *r = mojo_bytes_alloc(n * (int64_t)tabsize + 1);
    int64_t p = 0, col = 0;
    for (int64_t i = 0; i < n; i++) {
        uint8_t c = b->data[i];
        if (c == '\t') {
            int64_t spaces = tabsize - (col % tabsize);
            for (int64_t k = 0; k < spaces; k++) r->data[p++] = ' ';
            col += spaces;
        } else {
            r->data[p++] = c;
            col = (c == '\n' || c == '\r') ? 0 : col + 1;
        }
    }
    r->len = p;
    r->data[p] = 0;
    return r;
}

/* NUL-terminated copy of the bytes' content, for the char*-keyed dict /
 * str-tagged set probe paths. Bytes containing an embedded NUL are
 * truncated at it — the same lossiness the char*-keyed dict has always had
 * for any non-str key; a container keyed on such bytes needs a typed-key
 * container, not this shim. */
char *mojo_bytes_cstr_key(MojoBytes *b)
{
    int64_t n = b ? b->len : 0;
    char *s = malloc((size_t)n + 1);
    if (n) memcpy(s, b->data, (size_t)n);
    s[n] = 0;
    return s;
}

/* ── the isX() character-class kernel ─────────────────────────────────────
 * ONE implementation of the ASCII character-class predicates, shared by
 * the `str` (char*) and `bytes` (MojoBytes *) families. It used to exist
 * twice — a hand-written `mojo_str_isX` per predicate and a separate
 * `mojo_bytes_is` switch — and the two drifted: the bytes copy answered
 * `b''.isalpha() == True`, `b'ab1'.islower() == False` and
 * `b'1'.istitle() == True`, all three wrong, while the str copy (which
 * mirrors CPython's own defs) was right. A silent-wrong-value divergence
 * between two copies of one rule is exactly what a shared kernel
 * prevents; every case below is transcribed from CPython's definitions.
 *
 * `kind` is a MOJO_IS_* code. The byte-level classes are the C-locale
 * ASCII ones CPython's `bytes` methods use (`Py_ISALPHA` etc.), so the
 * answer does not drift with the process locale the way ctype.h's
 * locale-sensitive `isalpha` would.
 *
 * Python's per-predicate rules, which the three "all-X" ones each encode
 * differently, are the whole content of this function:
 *   isalpha/isalnum/isdigit/isspace/isascii — every char is in the class
 *   islower  — at least one cased char, and NO cased char is uppercase
 *               (digits/underscore/punct are UNCASED: ignored, so
 *               `b'ab1'.islower()` is True)
 *   isupper  — the mirror image
 *   istitle  — at least one cased char, and every run of cased chars
 *               starts uppercase followed by lowercase (`b'A B'` True,
 *               `b'AB'` False, `b'1'` False)
 *   isprintable — every char is a printable char: 0x20..0x7e, plus any
 *               byte >= 0xa0. That excludes the C1 control block 0x80-0x9f,
 *               where UTF-8 puts U+0080..U+009F, exactly as CPython does.
 *               A byte-level test cannot see the Unicode categories, so a
 *               code point in a separator block (U+00A0, U+2028, ...) is
 *               answered True here and False by CPython; ASCII and the C1
 *               controls — every case reachable without a category table —
 *               are exact.
 *   isnumeric   — Unicode category N*; over an ASCII window that is
 *               exactly the digits, i.e. the same test as isdigit
 * Python's "every char is in C" is False over an EMPTY string — with two
 * vacuous-True exceptions that are definitional rather than accidental:
 * isascii ("no char has the high bit set") and isprintable ("no char is
 * unprintable"). So `''.isprintable()` is True and `b''.isascii()` is. */
#define MOJO_IS_ALPHA   0
#define MOJO_IS_ALNUM   1
#define MOJO_IS_DIGIT   2
#define MOJO_IS_SPACE   3
#define MOJO_IS_UPPER   4
#define MOJO_IS_LOWER   5
#define MOJO_IS_TITLE   6
#define MOJO_IS_PRINT   7
#define MOJO_IS_ASCII   8
#define MOJO_IS_NUMERIC 9

static int mojo_is_alpha(uint8_t c)
{ return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
static int mojo_is_digit(uint8_t c) { return c >= '0' && c <= '9'; }
static int mojo_is_upper(uint8_t c) { return c >= 'A' && c <= 'Z'; }
static int mojo_is_lower(uint8_t c) { return c >= 'a' && c <= 'z'; }

static int mojo_is_printable(uint8_t c)
{ return (c >= 0x20 && c <= 0x7e) || c >= 0xa0; }

static int mojo_is_kind(const uint8_t *d, int64_t len, int kind)
{
    if (len == 0) return kind == MOJO_IS_ASCII || kind == MOJO_IS_PRINT;
    if (kind == MOJO_IS_ASCII) {
        for (int64_t i = 0; i < len; i++) if (d[i] > 127) return 0;
        return 1;
    }
    int has_cased = 0, prev_cased = 0;
    for (int64_t i = 0; i < len; i++) {
        uint8_t c = d[i];
        int a = mojo_is_alpha(c), dg = mojo_is_digit(c);
        switch (kind) {
        case MOJO_IS_ALPHA:   if (!a) return 0; break;
        case MOJO_IS_ALNUM:   if (!a && !dg) return 0; break;
        case MOJO_IS_DIGIT:
        case MOJO_IS_NUMERIC: if (!dg) return 0; break;
        case MOJO_IS_SPACE:   if (!mojo_bytes_isspace_byte(c)) return 0; break;
        case MOJO_IS_PRINT:   if (!mojo_is_printable(c)) return 0; break;
        case MOJO_IS_UPPER:   if (mojo_is_lower(c)) return 0;
                              if (mojo_is_upper(c)) has_cased = 1; break;
        case MOJO_IS_LOWER:   if (mojo_is_upper(c)) return 0;
                              if (mojo_is_lower(c)) has_cased = 1; break;
        case MOJO_IS_TITLE:   /* an uncased char ends the current word, so the
                               * next cased one starts a fresh title run */
                              if (!a) { prev_cased = 0; break; }
                              if (prev_cased) { if (!mojo_is_lower(c)) return 0; }
                              else            { if (!mojo_is_upper(c)) return 0; }
                              prev_cased = has_cased = 1; break;
        }
    }
    if (kind == MOJO_IS_UPPER || kind == MOJO_IS_LOWER || kind == MOJO_IS_TITLE)
        return has_cased;
    return 1;
}

int mojo_bytes_is(MojoBytes *b, int kind)
{ return b ? mojo_is_kind(b->data, b->len, kind) : 0; }

/* The char*-typed half of the same question. A NUL-terminated string has
 * no embedded NULs, so its length is strlen — the same byte window
 * mojo_is_kind walks. A NULL string (an unset str field reaching a
 * predicate) answers False, as every one of these did before. */
static int mojo_cstr_is(char *s, int kind)
{ return s ? mojo_is_kind((const uint8_t *)s, (int64_t)strlen(s), kind) : 0; }


/* split/rsplit with a maxsplit bound (MOJO_SLICE_STOP_OMITTED = unbounded).
 * Python splits from the right for rsplit, and neither form drops a
 * trailing empty piece when the bound is not reached. */
MojoList *mojo_bytes_split_max(MojoBytes *b, MojoBytes *sep, int64_t maxsplit, int from_right)
{
    MojoList *l = mojo_list_new();
    if (!b) return l;
    int64_t n = b->len;
    /* An EMPTY separator is a ValueError in CPython — `b'ab'.split(b'')` and
     * `b'ab'.rsplit(b'')` both raise "empty separator". It was conflated
     * with the genuinely-absent one (`split()` with no argument, which IS a
     * whitespace split) because both arrive here as a NULL-or-empty `sep`,
     * so `split(b'')` silently whitespace-split instead. Only the SPELLING
     * distinguishes them: an explicit empty separator is a non-NULL,
     * zero-length value. mojo_bytes_partition already draws this exact
     * distinction (see mojo_bytes_partition_go's own comment). */
    if (sep && sep->len == 0) {
        char detail[96];
        snprintf(detail, sizeof detail, "empty separator");
        mojo_raise_value_error(detail);
    }
    int64_t sn = sep ? sep->len : 0;
    if (sn == 0) {
        /* whitespace split, no empty pieces, no leading/trailing padding */
        int64_t i = 0;
        while (i < n) {
            while (i < n && mojo_bytes_isspace_byte(b->data[i])) i++;
            if (i >= n) break;
            int64_t start = i;
            while (i < n && !mojo_bytes_isspace_byte(b->data[i])) i++;
            mojo_bytes_list_push(l, b->data + start, i - start);
            if (maxsplit != MOJO_SLICE_STOP_OMITTED && (int64_t)mojo_list_len(l) >= maxsplit) {
                /* The REST of the input is ONE more piece, verbatim. It
                 * was pushed as a single ZERO-length piece, so
                 * `b'a b c'.split(maxsplit=1)` came back
                 * [b'a', b'', b'', b''] — one real piece followed by
                 * three empty ones, where CPython answers
                 * [b'a', b' b c']. */
                int64_t rest = i;
                while (rest < n && mojo_bytes_isspace_byte(b->data[rest])) rest++;
                if (rest < n) mojo_bytes_list_push(l, b->data + rest, n - rest);
                i = n;
            }
        }
        return l;
    }
    if (!from_right) {
        int64_t start = 0, done = 0;
        /* An EMPTY subject splits to exactly one piece — the empty string —
         * not to none. `[].join`ing over an empty result and iterating it
         * are both wrong for `b''.split(b',')`, and the loop below never
         * ran at all (no separator to find), so the answer was []. */
        if (n == 0) {
            mojo_bytes_list_push(l, b->data, 0);
            return l;
        }
        for (int64_t i = 0; i + sn <= n; ) {
            if (memcmp(b->data + i, sep->data, (size_t)sn) == 0) {
                mojo_bytes_list_push(l, b->data + start, i - start);
                i += sn; start = i;
                if (maxsplit != MOJO_SLICE_STOP_OMITTED && ++done >= maxsplit) break;
            } else i++;
        }
        mojo_bytes_list_push(l, b->data + start, n - start);
        return l;
    }
    int64_t stop = n, done = 0;
    for (int64_t i = n - sn; i >= 0; ) {
        if (memcmp(b->data + i, sep->data, (size_t)sn) == 0) {
            mojo_bytes_list_push(l, b->data + i + sn, stop - i - sn);
            stop = i; i -= sn;
            if (maxsplit != MOJO_SLICE_STOP_OMITTED && ++done >= maxsplit) break;
        } else i--;
    }
    mojo_bytes_list_push(l, b->data, stop);
    /* pushed back-to-front; reverse into source order */
    int64_t m = mojo_list_len(l);
    for (int64_t i = 0; i < m / 2; i++) {
        int64_t x = mojo_list_get_int(l, i), y = mojo_list_get_int(l, m - 1 - i);
        mojo_list_set_int(l, i, y);
        mojo_list_set_int(l, m - 1 - i, x);
    }
    return l;
}

MojoList *mojo_bytes_splitlines_keep(MojoBytes *b, int keepends)
{
    MojoList *l = mojo_list_new();
    if (!b) return l;
    int64_t start = 0;
    for (int64_t i = 0; i < b->len; i++) {
        if (b->data[i] == '\n') {
            mojo_bytes_list_push(l, b->data + start, i - start + (keepends ? 1 : 0));
            start = i + 1;
        }
    }
    if (start < b->len) mojo_bytes_list_push(l, b->data + start, b->len - start);
    return l;
}

/* ── bytearray (mutable, shares the MojoBytes representation) ────────────
 * No capacity field on MojoBytes, so every size-changing op reallocs
 * data to exactly len+1. O(n) amortized append is acceptable for this
 * compiler's workloads and keeps the struct layout (and every codegen
 * struct-field table) untouched. */
static void mojo_bytearray_resize(MojoBytes *b, int64_t newlen)
{
    if (newlen < 0) newlen = 0;
    b->data = realloc(b->data, (size_t)newlen + 1);
    b->data[newlen] = 0;
    b->len = newlen;
}

MojoBytes *mojo_bytearray_new(void) { return mojo_bytearray_mark(mojo_bytes_alloc(0)); }

MojoBytes *mojo_bytearray_copy(MojoBytes *src)
{
    int64_t n = src ? src->len : 0;
    return mojo_bytearray_mark(mojo_bytes_new_lit(src ? (const char *)src->data : "", n));
}

/* `bytes(bytearray)` — the one copy that RE-IMMUTABILISES, so it must not
 * go through mojo_bytearray_copy (its own former body, which is why this
 * used to inherit a bytearray's mutability flag). */
MojoBytes *mojo_bytes_copy(MojoBytes *src) { return mojo_bytes_new_lit(src ? (const char *)src->data : "", src ? src->len : 0); }

MojoBytes *mojo_bytearray_mark(MojoBytes *b) { if (b) b->readonly = 0; return b; }

/* reversed(<bytes>) modeled as an eagerly reversed copy. */
MojoBytes *mojo_bytes_reverse(MojoBytes *src)
{
    int64_t n = src ? src->len : 0;
    MojoBytes *out = mojo_bytes_alloc(n);
    for (int64_t i = 0; i < n; i++) out->data[i] = src->data[n - 1 - i];
    out->len = n;
    return out;
}

void mojo_bytearray_setitem(MojoBytes *b, int64_t i, int64_t v)
{
    if (!b) return;
    if (i < 0) i += b->len;
    if (i < 0 || i >= b->len) { fprintf(stderr, "IndexError: bytearray index out of range\n"); exit(1); }
    b->data[i] = (uint8_t)(v & 0xFF);
}

void mojo_bytearray_append(MojoBytes *b, int64_t v)
{
    if (!b) return;
    mojo_bytearray_resize(b, b->len + 1);
    b->data[b->len - 1] = (uint8_t)(v & 0xFF);
}

void mojo_bytearray_extend(MojoBytes *b, MojoBytes *other)
{
    if (!b || !other || other->len == 0) return;
    int64_t old = b->len;
    /* snapshot in case other aliases b */
    int64_t on = other->len;
    uint8_t *tmp = malloc((size_t)on);
    memcpy(tmp, other->data, (size_t)on);
    mojo_bytearray_resize(b, old + on);
    memcpy(b->data + old, tmp, (size_t)on);
    free(tmp);
}

int64_t mojo_bytearray_pop(MojoBytes *b, int64_t i)
{
    if (!b || b->len == 0) { fprintf(stderr, "IndexError: pop from empty bytearray\n"); exit(1); }
    if (i == MOJO_SLICE_STOP_OMITTED) i = b->len - 1;
    if (i < 0) i += b->len;
    if (i < 0 || i >= b->len) { fprintf(stderr, "IndexError: pop index out of range\n"); exit(1); }
    int64_t out = b->data[i];
    memmove(b->data + i, b->data + i + 1, (size_t)(b->len - i - 1));
    mojo_bytearray_resize(b, b->len - 1);
    return out;
}

void mojo_bytearray_delitem(MojoBytes *b, int64_t i)
{
    (void)mojo_bytearray_pop(b, i);
}

/* ba[start:stop] = repl  — splice: delete [start,stop), insert repl's
 * bytes at start. Negative / omitted bounds already normalized by the
 * caller (same _lower_slice_bounds path as list splice). */
void mojo_bytearray_splice(MojoBytes *b, int64_t start, int64_t stop, MojoBytes *repl)
{
    if (!b) return;
    int64_t n = b->len;
    if (start == MOJO_SLICE_STOP_OMITTED) start = 0;
    if (stop == MOJO_SLICE_STOP_OMITTED) stop = n;
    if (start < 0) start += n;
    if (stop < 0) stop += n;
    if (start < 0) start = 0;
    if (start > n) start = n;
    if (stop < start) stop = start;
    if (stop > n) stop = n;
    int64_t rn = repl ? repl->len : 0;
    uint8_t *rtmp = malloc((size_t)(rn ? rn : 1));
    if (rn) memcpy(rtmp, repl->data, (size_t)rn);
    int64_t tail = n - stop;
    uint8_t *ttmp = malloc((size_t)(tail ? tail : 1));
    if (tail) memcpy(ttmp, b->data + stop, (size_t)tail);
    mojo_bytearray_resize(b, start + rn + tail);
    if (rn) memcpy(b->data + start, rtmp, (size_t)rn);
    if (tail) memcpy(b->data + start + rn, ttmp, (size_t)tail);
    free(rtmp); free(ttmp);
}

void mojo_bytearray_insert(MojoBytes *b, int64_t i, int64_t v)
{
    if (!b) return;
    int64_t n = b->len;
    if (i < 0) i += n;
    if (i < 0) i = 0;
    if (i > n) i = n;
    mojo_bytearray_resize(b, n + 1);
    memmove(b->data + i + 1, b->data + i, (size_t)(n - i));
    b->data[i] = (uint8_t)(v & 0xFF);
}

void mojo_bytearray_remove(MojoBytes *b, int64_t v)
{
    if (!b) { fprintf(stderr, "ValueError: bytearray.remove(x): x not in bytearray\n"); exit(1); }
    int64_t at = mojo_bytes_index_int(b, v, 0, MOJO_SLICE_STOP_OMITTED);
    if (at < 0) { fprintf(stderr, "ValueError: bytearray.remove(x): x not in bytearray\n"); exit(1); }
    mojo_bytearray_pop(b, at);
}

/* ── memoryview (non-copying 1-D byte view) ─────────────────────────────*/
/* `readonly` comes from the SOURCE object (see the field's comment in
 * fire_runtime.h); the raw-window entry point mojo_memoryview_new has no
 * source object to ask, so it starts at 0 and mojo_memoryview_from_bytes
 * — the only constructor the backend actually emits — sets the real value.
 * A derived view (slice) inherits it, which is what CPython does: a
 * sub-view of a read-only view is still read-only. */
MojoMemoryView *mojo_memoryview_new(uint8_t *data, int64_t len, int64_t itemsize)
{
    MojoMemoryView *m = malloc(sizeof(MojoMemoryView));
    m->data = data;
    m->len = len;
    m->itemsize = itemsize > 0 ? itemsize : 1;
    m->readonly = 0;
    return m;
}

MojoMemoryView *mojo_memoryview_from_bytes(MojoBytes *b)
{
    MojoMemoryView *m = mojo_memoryview_new(b ? b->data : NULL, b ? b->len : 0, 1);
    m->readonly = b ? b->readonly : 1;
    return m;
}

int mojo_memoryview_readonly(MojoMemoryView *m) { return m ? m->readonly : 0; }

int64_t mojo_memoryview_len(MojoMemoryView *m) { return m ? m->len : 0; }

int64_t mojo_memoryview_get(MojoMemoryView *m, int64_t i)
{
    if (!m) return 0;
    if (i < 0) i += m->len;
    if (i < 0 || i >= m->len) {
        /* A real, catchable IndexError, not a print-and-exit. The
         * print-and-exit could not be caught, so a program guarding an
         * optional read (`try: v = mv[n] except IndexError: v = None`)
         * died instead of taking the fallback — and the plain
         * `mv[n]` for n past the end still raises, just one that behaves
         * like every other raise in this runtime. */
        char detail[96];
        snprintf(detail, sizeof detail, "index out of bounds on memoryview");
        mojo_raise_index_error(detail);
    }
    return (int64_t)m->data[i];
}

/* mv[a:b] — a sub-view into the SAME buffer (no copy). start/stop use the
 * MOJO_SLICE_STOP_OMITTED sentinel convention; step is not supported for
 * a non-contiguous view and is treated as 1. */
MojoMemoryView *mojo_memoryview_slice(MojoMemoryView *m, int64_t start, int64_t stop, int64_t step)
{
    (void)step;
    int64_t n = m ? m->len : 0;
    int64_t lo = (start == MOJO_SLICE_STOP_OMITTED) ? 0 : start;
    int64_t hi = (stop == MOJO_SLICE_STOP_OMITTED) ? n : stop;
    if (lo < 0) lo += n;
    if (hi < 0) hi += n;
    if (lo < 0) lo = 0;
    if (hi > n) hi = n;
    if (hi < lo) hi = lo;
    MojoMemoryView *sub = mojo_memoryview_new(m ? m->data + lo : NULL, hi - lo, m ? m->itemsize : 1);
    sub->readonly = m ? m->readonly : 0;
    return sub;
}

MojoBytes *mojo_memoryview_tobytes(MojoMemoryView *m)
{
    return mojo_bytes_new_lit(m ? (const char *)m->data : "", m ? m->len : 0);
}

int mojo_memoryview_eq(MojoMemoryView *m, MojoBytes *b)
{
    if (!m || !b) return m == NULL && b == NULL;
    return m->len == b->len && memcmp(m->data, b->data, (size_t)m->len) == 0;
}

char *mojo_memoryview_hex(MojoMemoryView *m)
{
    MojoBytes *b = mojo_memoryview_tobytes(m);
    char *r = mojo_bytes_hex(b);
    return r;
}

/* .cast(fmt) for a 1-D byte view: only 'B'/'b'/'c' are meaningful and all
 * keep itemsize 1, so this is an identity return. */
MojoMemoryView *mojo_memoryview_cast(MojoMemoryView *m, char *fmt) { (void)fmt; return m; }

/* Read-only descriptive attributes. `nbytes` is len*itemsize; `itemsize` and
 * `format` describe the element type (always one byte here, so 'B' unless
 * .cast() named a signed/char variant). */
int64_t mojo_memoryview_itemsize(MojoMemoryView *m) { return m ? m->itemsize : 0; }

int64_t mojo_memoryview_nbytes(MojoMemoryView *m)
{ return m ? m->len * m->itemsize : 0; }

char *mojo_memoryview_format(MojoMemoryView *m, char *fmt)
{ (void)m; return fmt ? fmt : (char *)"B"; }

/* `.obj` is the object the view was taken from; this representation keeps
 * only a raw window, so a bytes-backed view re-wraps its own window. */
MojoBytes *mojo_memoryview_obj(MojoMemoryView *m)
{
    return mojo_bytes_new_lit(m ? (const char *)m->data : "", m ? m->len : 0);
}

/* The DESCRIPTIVE shape attributes. All four are exact for this
 * representation, which is always a 1-D, C-contiguous, non-strided view of
 * `len` elements — that is not an approximation of a general memoryview, it
 * is what a `MojoMemoryView` IS here. None of them existed, so each fell to
 * the generic unknown-member stub and printed its own heap address as a
 * decimal: `mv.shape` printed 4340423136, `mv.ndim` printed 4340426608, and
 * a program testing `mv.ndim == 1` silently took the false branch.
 *
 * The tuples are returned as STRINGS (the "(4,)" spelling) rather than as
 * MojoLists because there is no caller-side shape for a 1-tuple here and the
 * repr of a boxed list would be `[4]`, not `(4,)`. Printing the string
 * gives CPython's exact text. */
char *mojo_memoryview_shape_str(MojoMemoryView *m)
{
    char buf[32];
    snprintf(buf, sizeof buf, "(%lld,)", (long long)(m ? m->len : 0));
    return strdup(buf);
}

char *mojo_memoryview_strides_str(MojoMemoryView *m)
{
    /* Stride is the distance between consecutive elements, in BYTES. */
    char buf[32];
    snprintf(buf, sizeof buf, "(%lld,)", (long long)(m ? m->itemsize : 0));
    return strdup(buf);
}

char *mojo_memoryview_suboffsets_str(void) { return strdup("()"); }

int64_t mojo_memoryview_ndim(MojoMemoryView *m) { (void)m; return 1; }

/* Contiguity: a 1-D window over `len` bytes with no gaps is C-contiguous,
 * which for 1 dimension is also F-contiguous and simply "contiguous". */
int mojo_memoryview_c_contiguous(MojoMemoryView *m) { (void)m; return 1; }
int mojo_memoryview_f_contiguous(MojoMemoryView *m) { (void)m; return 1; }
int mojo_memoryview_contiguous(MojoMemoryView *m) { (void)m; return 1; }

/* `mv.tolist()` — the view's elements as a real list of ints. This
 * answered a raw int 0 from the unknown-member stub. */
MojoList *mojo_memoryview_tolist(MojoMemoryView *m)
{
    MojoList *out = mojo_list_new();
    if (!m) return out;
    for (int64_t i = 0; i < m->len; i++)
        mojo_list_append_int(out, (int64_t)m->data[i]);
    return out;
}

char *mojo_memoryview_repr(MojoMemoryView *m)
{
    char *s = malloc(48);
    snprintf(s, 48, "<memory at %p>", (void *)m);
    return s;
}

/* ── struct module: binary pack / unpack ──────────────────────────────
 * See fire_runtime.h for the format mini-language and calling convention.
 * A compiled format expands to one MojoStructOp per value ('x' padding is
 * folded into offsets and produces no op; 's'/'c' are a single op of
 * `nbytes` bytes). */
typedef struct {
    char    code;     /* b B h H i I l L q Q f d s ? c */
    int32_t nbytes;   /* wire size (for 's'/'c': the byte count) */
    int64_t offset;   /* byte offset within the packed buffer */
} MojoStructOp;

struct MojoStructFmt {
    int           big_endian;  /* 1 = big/network order, 0 = little (host assumed LE) */
    int           native;      /* 1 = '@' native size + alignment, 0 = standard sizes, no padding */
    int64_t       size;        /* calcsize() */
    int64_t       nops;
    MojoStructOp *ops;
    char         *format;      /* original format string (struct.Struct.format) */
    char         *kinds;       /* one per-slot kind byte for `ops`, or NULL
                                * when the format is uniform (the common case,
                                * and the one that needs no side table) */
};

void mojo_struct_raise_error(const char *msg)
{
    size_t n = strlen(msg) + 1;
    char *heap = (char *)malloc(n);
    memcpy(heap, msg, n);
    mojo_exc_type_set(MOJO_STRUCT_ERROR_TAG);
    mojo_exc_msg_set(heap);
    mojo_exc_obj_set(heap);
    mojo_raise();
}

static void _struct_type_info(char code, int native, int *sz, int *align)
{
    int s;
    switch (code) {
        case 'x': case 'b': case 'B': case 'c': case 's': case '?': s = 1; break;
        case 'h': case 'H': s = 2; break;
        case 'i': case 'I': s = 4; break;
        case 'l': case 'L': s = native ? (int)sizeof(long) : 4; break;
        case 'q': case 'Q': s = 8; break;
        case 'f': s = 4; break;
        case 'd': s = 8; break;
        default:  s = 0; break;   /* unknown code */
    }
    if (sz)    *sz = s;
    if (align) *align = native ? s : 1;
}

/* One slot of an unpack result, in the alphabet mojo_list_set_kinds
 * documents: 'd' for a float/double op, 's' for the bytes an 's'/'c' op
 * produces, 'i' for everything else (including '?', which packs as a
 * byte but is an int to every reader). The ONE definition, shared by the
 * format compiler below and by _struct_unpack_at, so a kinds string and
 * the value stored in the slot cannot drift apart. */
static char _struct_op_kind(char code)
{
    if (code == 'f' || code == 'd') return 'd';
    if (code == 's' || code == 'c') return 's';
    return 'i';
}

MojoStructFmt *mojo_struct_compile(const char *fmt)
{
    if (fmt == NULL) fmt = "";
    MojoStructFmt *f = (MojoStructFmt *)calloc(1, sizeof *f);
    f->big_endian = 0;
    f->native     = 1;
    const char *p = fmt;
    while (*p == ' ' || *p == '\t' || *p == '\n') p++;
    if (*p == '<' || *p == '>' || *p == '=' || *p == '!' || *p == '@') {
        switch (*p) {
            case '<': f->big_endian = 0; f->native = 0; break;
            case '=': f->big_endian = 0; f->native = 0; break;
            case '>': f->big_endian = 1; f->native = 0; break;
            case '!': f->big_endian = 1; f->native = 0; break;
            case '@': f->big_endian = 0; f->native = 1; break;
        }
        p++;
    }
    int64_t cap = 8;
    f->ops  = (MojoStructOp *)malloc((size_t)cap * sizeof(MojoStructOp));
    f->nops = 0;
    int64_t off = 0;
    while (*p) {
        char c = *p;
        if (c == ' ' || c == '\t' || c == '\n') { p++; continue; }
        long count = -1;
        if (c >= '0' && c <= '9') {
            count = 0;
            while (*p >= '0' && *p <= '9') { count = count * 10 + (*p - '0'); p++; }
            c = *p;
            if (!c) { mojo_struct_raise_error("repeat count given without format specifier"); return f; }
        }
        p++;
        int sz = 0, align = 1;
        _struct_type_info(c, f->native, &sz, &align);
        if (sz == 0) {
            char m[64];
            snprintf(m, sizeof m, "bad char in struct format: '%c'", c);
            mojo_struct_raise_error(m);
            return f;
        }
        if (c == 's' || c == 'c') {
            long n = (c == 'c') ? 1 : ((count < 0) ? 1 : count);
            if (f->native && align > 1) off = (off + align - 1) & ~(int64_t)(align - 1);
            if (f->nops >= cap) { cap *= 2; f->ops = (MojoStructOp *)realloc(f->ops, (size_t)cap * sizeof(MojoStructOp)); }
            f->ops[f->nops].code   = c;
            f->ops[f->nops].nbytes = (int32_t)n;
            f->ops[f->nops].offset = off;
            f->nops++;
            off += n;
        } else {
            long reps = (count < 0) ? 1 : count;
            for (long r = 0; r < reps; r++) {
                if (f->native && align > 1) off = (off + align - 1) & ~(int64_t)(align - 1);
                if (c != 'x') {
                    if (f->nops >= cap) { cap *= 2; f->ops = (MojoStructOp *)realloc(f->ops, (size_t)cap * sizeof(MojoStructOp)); }
                    f->ops[f->nops].code   = c;
                    f->ops[f->nops].nbytes = (int32_t)sz;
                    f->ops[f->nops].offset = off;
                    f->nops++;
                }
                off += sz;
            }
        }
    }
    f->size   = off;
    f->format = strdup(fmt);
    /* The per-slot kinds, derived from the ops just built rather than by
     * re-parsing the format: each op's `code` already says how its slot was
     * written in _struct_unpack_at, so this cannot disagree with it. A
     * UNIFORM format records nothing — its readers are all chosen from the
     * format at compile time and need no side table, and leaving it NULL
     * keeps every uniform `struct` use (the overwhelming majority) paying
     * exactly nothing for this. */
    {
        int mixed = 0;
        for (int64_t i = 0; i < f->nops; i++) {
            char k = _struct_op_kind(f->ops[i].code);
            if (i > 0 && k != _struct_op_kind(f->ops[0].code)) { mixed = 1; break; }
        }
        if (mixed) {
            char *ks = (char *)malloc((size_t)f->nops + 1);
            for (int64_t i = 0; i < f->nops; i++) ks[i] = _struct_op_kind(f->ops[i].code);
            ks[f->nops] = '\0';
            f->kinds = ks;
        }
    }
    return f;
}

static void _struct_wr_uint(uint8_t *dst, uint64_t v, int nbytes, int big)
{
    for (int i = 0; i < nbytes; i++) {
        int shift = big ? (nbytes - 1 - i) * 8 : i * 8;
        dst[i] = (uint8_t)((v >> shift) & 0xFF);
    }
}

static uint64_t _struct_rd_uint(const uint8_t *src, int nbytes, int big)
{
    uint64_t v = 0;
    for (int i = 0; i < nbytes; i++) {
        int shift = big ? (nbytes - 1 - i) * 8 : i * 8;
        v |= (uint64_t)src[i] << shift;
    }
    return v;
}

MojoBytes *mojo_struct_pack_h(MojoStructFmt *f, MojoList *vals)
{
    int64_t nv = mojo_list_len(vals);
    if (nv != f->nops) {
        char m[96];
        snprintf(m, sizeof m, "pack expected %lld items for packing (got %lld)",
                 (long long)f->nops, (long long)nv);
        mojo_struct_raise_error(m);
        return mojo_bytes_empty();
    }
    MojoBytes *b = mojo_bytes_zeros(f->size);
    for (int64_t i = 0; i < f->nops; i++) {
        MojoStructOp *op = &f->ops[i];
        uint8_t *dst = b->data + op->offset;
        switch (op->code) {
            case 's': case 'c': {
                MojoBytes *sv = (MojoBytes *)(uintptr_t)mojo_list_get_int(vals, i);
                int64_t n = sv ? sv->len : 0;
                if (n > op->nbytes) n = op->nbytes;
                if (n > 0) memcpy(dst, sv->data, (size_t)n);
                break;
            }
            case 'f': {
                float fv = (float)mojo_list_get_double(vals, i);
                uint32_t bits; memcpy(&bits, &fv, 4);
                _struct_wr_uint(dst, bits, 4, f->big_endian);
                break;
            }
            case 'd': {
                double dv = mojo_list_get_double(vals, i);
                uint64_t bits; memcpy(&bits, &dv, 8);
                _struct_wr_uint(dst, bits, 8, f->big_endian);
                break;
            }
            case '?': {
                dst[0] = mojo_list_get_int(vals, i) ? 1 : 0;
                break;
            }
            default: {
                int64_t v = mojo_list_get_int(vals, i);
                _struct_wr_uint(dst, (uint64_t)v, op->nbytes, f->big_endian);
                break;
            }
        }
    }
    return b;
}

static MojoList *_struct_unpack_at(MojoStructFmt *f, MojoBytes *buf, int64_t offset)
{
    int64_t buflen = buf ? buf->len : 0;
    if (offset < 0 || offset + f->size > buflen) {
        char m[96];
        snprintf(m, sizeof m, "unpack requires a buffer of %lld bytes", (long long)f->size);
        mojo_struct_raise_error(m);
        return mojo_list_new();
    }
    MojoList *out = mojo_list_new();
    for (int64_t i = 0; i < f->nops; i++) {
        MojoStructOp *op = &f->ops[i];
        const uint8_t *src = buf->data + offset + op->offset;
        switch (op->code) {
            case 's': case 'c': {
                MojoBytes *sv = mojo_bytes_new_lit((const char *)src, op->nbytes);
                mojo_list_append_int(out, (int64_t)(uintptr_t)sv);
                break;
            }
            case 'f': {
                uint32_t bits = (uint32_t)_struct_rd_uint(src, 4, f->big_endian);
                float fv; memcpy(&fv, &bits, 4);
                mojo_list_append_double(out, (double)fv);
                break;
            }
            case 'd': {
                uint64_t bits = _struct_rd_uint(src, 8, f->big_endian);
                double dv; memcpy(&dv, &bits, 8);
                mojo_list_append_double(out, dv);
                break;
            }
            case '?': {
                mojo_list_append_int(out, src[0] ? 1 : 0);
                break;
            }
            default: {
                uint64_t raw = _struct_rd_uint(src, op->nbytes, f->big_endian);
                int is_signed = (op->code == 'b' || op->code == 'h' ||
                                 op->code == 'i' || op->code == 'l' || op->code == 'q');
                int64_t v;
                if (is_signed && op->nbytes < 8 &&
                    (raw & ((uint64_t)1 << (op->nbytes * 8 - 1))))
                    v = (int64_t)(raw | (~(uint64_t)0 << (op->nbytes * 8)));
                else
                    v = (int64_t)raw;
                mojo_list_append_int(out, v);
                break;
            }
        }
    }
    mojo_mark_as_tuple(out);
    /* Hand the per-slot kinds to the VALUE, not to a compile-time name: the
     * result can now be copied, sliced, returned from a function or stored
     * in a container and still be read back correctly, which is the whole
     * point of the side table (see mojo_list_set_kinds). A uniform format
     * records nothing, so this is one call with a NULL argument for it. */
    mojo_list_set_kinds(out, f->kinds);
    return out;
}

int64_t   mojo_struct_calcsize(const char *fmt)                 { return mojo_struct_compile(fmt)->size; }
MojoBytes *mojo_struct_pack_list(const char *fmt, MojoList *v)  { return mojo_struct_pack_h(mojo_struct_compile(fmt), v); }
MojoList  *mojo_struct_unpack(const char *fmt, MojoBytes *buf)  { return _struct_unpack_at(mojo_struct_compile(fmt), buf, 0); }
MojoList  *mojo_struct_unpack_from(const char *fmt, MojoBytes *buf, int64_t off)
                                                               { return _struct_unpack_at(mojo_struct_compile(fmt), buf, off); }

MojoStructFmt *mojo_struct_new(const char *fmt)                 { return mojo_struct_compile(fmt); }
int64_t   mojo_struct_size(MojoStructFmt *f)                    { return f ? f->size : 0; }
char     *mojo_struct_format(MojoStructFmt *f)                  { return (f && f->format) ? f->format : (char *)""; }
MojoList  *mojo_struct_unpack_h(MojoStructFmt *f, MojoBytes *buf)   { return _struct_unpack_at(f, buf, 0); }
MojoList  *mojo_struct_unpack_from_h(MojoStructFmt *f, MojoBytes *buf, int64_t off)
                                                               { return _struct_unpack_at(f, buf, off); }

void mojo_struct_pack_into_h(MojoStructFmt *f, MojoBytes *buf, int64_t offset, MojoList *vals)
{
    int64_t buflen = buf ? buf->len : 0;
    if (!buf || offset < 0 || offset + f->size > buflen) {
        mojo_struct_raise_error("pack_into requires a buffer of sufficient size");
        return;
    }
    MojoBytes *packed = mojo_struct_pack_h(f, vals);
    memcpy(buf->data + offset, packed->data, (size_t)f->size);
}

void mojo_struct_pack_into(const char *fmt, MojoBytes *buf, int64_t offset, MojoList *vals)
{
    mojo_struct_pack_into_h(mojo_struct_compile(fmt), buf, offset, vals);
}

/* A single character (raw `char`, e.g. from string indexing) is a distinct
 * representation from a 1-character `char *` string — reinterpreting its
 * numeric byte value as a pointer (the boxed-int64_t-as-pointer convention
 * used elsewhere for containers of strings) produces a garbage address
 * (e.g. 0x22 for '"'). Build a real 1-char C string instead. */
char *mojo_char_to_str(char c) {
    /* The 256 possible one-character strings are IMMORTAL and shared: this is
     * called once per character by every scan over a string (`c = s[i]`,
     * `c == "\\"`, `buf.append(c)`, `c in ('(', '[')`), and a fresh malloc each
     * time is a leak with no owner (a list of str never frees its elements). The
     * result is therefore NOT the caller's to free -- it is deliberately absent
     * from the codegen's _FRESH_STRING_RETURNS -- and is never written to. The
     * store below is idempotent (a slot only ever holds its own character), so
     * there is no init step to race or forget. */
    static char tbl[256][2];
    char *s = tbl[(unsigned char)c];
    s[0] = c;
    return s;
}

/* Python's ord()/chr() builtins had NO real implementation at all — just a
 * declared-but-never-defined variadic stub (`int64_t ord(...);`), an
 * undefined symbol at link time for any program that actually calls either.
 * Byte-range only (this codebase's strings are plain bytes, not full
 * Unicode codepoints), matching mojo_char_to_str's own scope. Found via
 * regex_compile.py's own ord(c) calls (the first code in this self-hosted
 * codebase to actually call ord()). */
int64_t mojo_ord(char *s) {
    uintptr_t v = (uintptr_t)s;
    if (v == 0) return 0;
    /* Self-hosted path: a `str` field the compiled codegen erased to
     * int64_t can reach here holding a raw codepoint (e.g. regex_compile's
     * `ord(node.c)` where `Char.c` boxed to the int 0x5b) rather than a
     * pointer to a 1-char string. A value in the Unicode range is that
     * codepoint, never a valid userspace address (no real pointer is
     * < 0x110000 on any target this runs on). */
    if (v <= 0x10FFFFULL) return (int64_t)v;
    if (!s[0]) return 0;
    return (int64_t)(unsigned char)s[0];
}

char *mojo_chr(int64_t code) {
    return mojo_char_to_str((char)code);
}

int mojo_str_startswith(char *s, char *prefix) {
    if (!s || !prefix) return 0;
    while (*prefix) {
        if (!*s || *s != *prefix) return 0;
        s++; prefix++;
    }
    return 1;
}

/* Python str character-class predicates. All require at least one character
 * (empty string → False), and every character must satisfy the class. Used
 * to be codegen stubs hardcoded to 0 (always False) — e.g.
 * `raw[i].isdigit()` / `prev.isalnum()` in mojo_compiler.py's own tokenizer.
 * Now thin wrappers over the shared kernel (mojo_is_kind, see the bytes
 * section): these six and the bytes-side mojo_bytes_is are the SAME
 * Python rules, and while they were two hand-written copies they drifted —
 * the bytes copy answered `b'ab1'.islower()` False and `b'1'.istitle()`
 * True. One kernel, one set of answers, for both families.
 * istitle/isascii/isprintable/isnumeric are here rather than at the
 * mojo_bytes_is call site because CPython defines all ten on `str` and
 * only eight on `bytes`; isprintable/isnumeric did not exist on either
 * side in this backend and both used to answer a silent 0. */
int mojo_str_isalnum(char *s) { return mojo_cstr_is(s, MOJO_IS_ALNUM); }
int mojo_str_isdigit(char *s) { return mojo_cstr_is(s, MOJO_IS_DIGIT); }
int mojo_str_isalpha(char *s) { return mojo_cstr_is(s, MOJO_IS_ALPHA); }
int mojo_str_isspace(char *s) { return mojo_cstr_is(s, MOJO_IS_SPACE); }
int mojo_str_isupper(char *s) { return mojo_cstr_is(s, MOJO_IS_UPPER); }
int mojo_str_islower(char *s) { return mojo_cstr_is(s, MOJO_IS_LOWER); }
int mojo_str_istitle(char *s) { return mojo_cstr_is(s, MOJO_IS_TITLE); }
int mojo_str_isascii(char *s) { return mojo_cstr_is(s, MOJO_IS_ASCII); }
int mojo_str_isprintable(char *s) { return mojo_cstr_is(s, MOJO_IS_PRINT); }
/* ASCII-window approximation of Unicode category N* (see the kernel): a
 * non-ASCII char is not a digit here, so '²'.isnumeric() is False where
 * CPython says True — the same ASCII-only limit the pre-existing str
 * isalpha/isdigit have, and strictly better than the unconditional 0
 * this answered before. */
int mojo_str_isnumeric(char *s) { return mojo_cstr_is(s, MOJO_IS_NUMERIC); }

int mojo_str_endswith(char *s, char *suffix) {
    if (!s || !suffix) return 0;
    int slen = strlen(s);
    int suflen = strlen(suffix);
    if (suflen > slen) return 0;
    return strcmp(s + slen - suflen, suffix) == 0;
}

int mojo_str_startswith_char(char *s, char c) {
    if (!s) return 0;
    return s[0] == c;
}

int mojo_str_endswith_char(char *s, char c) {
    if (!s || !*s) return 0;
    int len = strlen(s);
    return s[len - 1] == c;
}

int64_t mojo_str_find(char *s, char *needle) {
    if ((intptr_t)s < 65536 || (intptr_t)needle < 65536) return -1;
    if (!s || !needle) return -1;
    char *found = strstr(s, needle);
    if (!found) return -1;
    return (int64_t)(found - s);
}

/* str.rfind(needle): index of the LAST occurrence of needle in s, or -1.
 * Empty needle matches at strlen(s) (CPython: "ab".rfind("") == 2). */
int64_t mojo_str_rfind(char *s, char *needle) {
    if ((intptr_t)s < 65536 || (intptr_t)needle < 65536) return -1;
    if (!s || !needle) return -1;
    int64_t nlen = (int64_t)strlen(needle);
    int64_t slen = (int64_t)strlen(s);
    if (nlen == 0) return slen;
    if (nlen > slen) return -1;
    for (int64_t i = slen - nlen; i >= 0; i--) {
        if (memcmp(s + i, needle, (size_t)nlen) == 0) return i;
    }
    return -1;
}

/* str.find(needle, start) with CPython semantics: negative start is relative
 * to the end (clamped to 0 after adjustment); start beyond the string length
 * is a guaranteed miss (-1); an empty needle matches at `start` itself, as
 * long as start <= len (e.g. "ab".find("", 2) == 2 but "ab".find("", 3) ==
 * -1). On a hit the returned index is absolute (relative to `s`, not to
 * `s + start`). */
int64_t mojo_str_find_from(char *s, char *needle, int64_t start) {
    if ((intptr_t)s < 65536 || (intptr_t)needle < 65536) return -1;
    if (!s || !needle) return -1;
    int64_t len = (int64_t)strlen(s);
    if (start < 0) {
        start += len;
        if (start < 0) start = 0;
    }
    if (start > len) return -1;
    if (!*needle) return start;
    char *found = strstr(s + start, needle);
    if (!found) return -1;
    return (int64_t)(found - s);
}

/* Deliberately NOT named mojo_getenv: `getenv` is in _FORCE_RENAME_RESERVED
 * in gimple_codegen.py, so the real Mojo stdlib's own `getenv` (std/os/
 * env.mojo, a genuine `def getenv(name, default="") -> String`) also
 * compiles to a C function literally called `mojo_getenv` — naming this
 * wrapper the same collided with that (conflicting-types build failure in
 * std/python/_cpython.mojo, which calls the stdlib's real getenv). ast_
 * rewriter.py's os.environ.* rules call this one directly by name instead
 * of relying on the reserved-name rewrite. */
char *mojo_c_getenv(char *name) {
    if (!name) return NULL;
    return getenv(name);
}

/* `os.environ` as a VALUE -- the bare mapping, not the per-key
 * `os.environ.get(k)` / `os.environ[k]` / `k in os.environ` idioms, which
 * ast_rewriter.py already lowers to `mojo_c_getenv`. Those rewrites are
 * what the overwhelming majority of real code uses, and they work with no
 * runtime object behind them at all; this exists for the value-position
 * read that has no such lowering: `env_defaults | os.environ | updates`
 * (Tools/wasm/wasi/__main__.py's `updated_env`) is a genuine `dict |`
 * union and previously typed `os.environ` as an opaque `int64_t`, so the
 * union call received an integer where it expected `MojoDict *` -- a hard
 * `-Wint-conversion` error, and an honest refusal rather than a silent
 * wrong answer.
 *
 * A PROCESS-WIDE SINGLETON, built once, mirroring `mojo_get_argv`: Python
 * guarantees `os.environ is os.environ`, and a per-read fresh dict would
 * break both that identity and any `os.environ['X'] = v` write-then-read
 * in the same program. The strings are the C runtime's own `environ`
 * slots (not copies) and the dict is never freed, both deliberate: a
 * compiled program here has no interpreter shutdown, and the same
 * "elements commonly still referenced" reasoning as
 * `mojo_replace_argv` applies.
 *
 * SCOPE, stated honestly: a `d[k] = v` / `del d[k]` through this dict
 * mutates the mapping but does NOT call `putenv`/`unsetenv`, so a later
 * `getenv()` in C, or a child process, does not see it. Only
 * `os.environ` reads are faithful. `environ` is declared `extern` here
 * rather than via `environ()` because this runtime targets POSIX
 * (see mojo_platform_system), and the NULL-vs-empty distinction does not
 * matter: an empty environment and an unset `environ` both yield an empty
 * mapping, which is what Python reports for `dict(os.environ)`. */
extern char **environ;
static MojoDict *_mojo_environ_dict = NULL;

MojoDict *mojo_environ_dict(void) {
    if (_mojo_environ_dict) return _mojo_environ_dict;
    _mojo_environ_dict = mojo_dict_new();
    if (environ) {
        for (char **e = environ; *e; e++) {
            char *eq = strchr(*e, '=');
            /* A malformed entry with no '=' has no key to split on; Python's
             * own os.environ decoding skips it too (posix puts it in
             * os.environb only as an undecodable-name entry). */
            if (!eq) continue;
            *eq = '\0';
            mojo_dict_set_str(_mojo_environ_dict, *e, eq + 1);
            *eq = '=';
        }
    }
    return _mojo_environ_dict;
}

/* Python str truthiness: "" is falsy, NULL is falsy, anything else truthy.
 * Used by _ensure_bool_cond so `if some_char_star:` matches Python semantics
 * (a pointer-nullity check alone treats a non-null empty string as truthy). */
int mojo_truthy_cstr(char *s) {
    /* A very small pointer (below typical page alignment) is almost certainly
       a bool/small-int value that was cast to char* by the codegen — treating
       it as a string would dereference address 0x1 (etc.) and SIGSEGV.
       Guards against BUG-2026-045's "bool-as-char*" JIT crash. */
    if ((int64_t)(intptr_t)s < 65536) return s != NULL;
    return s[0] != '\0';
}

/* len(a_plain_string): real libc strlen() returns size_t, not int64_t —
 * GIMPLE's strict typing rejects assigning that straight into an int64_t
 * temp ("invalid conversion in gimple call"), the same class of issue as
 * mojo_getenv/mojo_c_getenv. This wrapper gives it the guaranteed-correct
 * signature codegen expects. */
int64_t mojo_strlen(char *s) {
    return s ? (int64_t)strlen(s) : 0;
}

/* Regex match.start()/.end() need Unicode-codepoint offsets to match
 * Python's re.Match semantics (stage1, this codebase's documented ground
 * truth per bootstrap-validate.mojo) — but mojo_regex_search scans `s` as a
 * raw byte buffer, so its match positions are byte offsets. Convert by
 * counting non-continuation bytes (those not matching 10xxxxxx) up to
 * byte_offset. */
int64_t mojo_utf8_codepoint_index(char *s, int64_t byte_offset) {
    int64_t count = 0;
    for (int64_t i = 0; i < byte_offset; i++)
        if ((s[i] & 0xC0) != 0x80) count++;
    return count;
}

/* platform.system()/platform.machine(): resolved via preprocessor macros at
 * the C compiler's own build time (not Python's `platform` module — this
 * runtime is itself compiled by whatever gcc builds the self-hosted binary,
 * so baking the answer in via CPython's platform.system() from ast_rewriter.py
 * would recurse, since ast_rewriter.py is part of the self-hosted closure too). */
char *mojo_platform_system(void) {
#if defined(__APPLE__)
    return "Darwin";
#elif defined(__linux__)
    return "Linux";
#elif defined(_WIN32)
    return "Windows";
#else
    return "";
#endif
}

char *mojo_platform_machine(void) {
#if defined(__aarch64__) || defined(__arm64__)
    return "arm64";
#elif defined(__x86_64__) || defined(_M_X64)
    return "x86_64";
#else
    return "";
#endif
}

/* Read a pipe fd to EOF into a malloc'd, NUL-terminated buffer. */
static char *_read_all(int fd) {
    size_t cap = 4096, len = 0;
    char *buf = malloc(cap);
    for (;;) {
        if (len + 4096 > cap) { cap *= 2; buf = realloc(buf, cap); }
        ssize_t n = read(fd, buf + len, cap - len - 1);
        if (n < 0) { if (errno == EINTR) continue; break; }
        if (n == 0) break;
        len += (size_t)n;
    }
    buf[len] = '\0';
    return buf;
}

void mojo_stream_write(int64_t fd, char *s) {
    if (!s) return;
    /* Only the three standard streams: this handle is an fd, and a
     * handle that is not one must not become a wild write(). */
    if (fd < 0 || fd > 2) return;
    /* fwrite, not write(2): stdio may have buffered output already, and
     * mixing a raw write(2) with buffered stdio reorders the two. */
    fwrite(s, 1, strlen(s), fd == 0 ? stdin : (fd == 1 ? stdout : stderr));
    fflush(fd == 0 ? stdin : (fd == 1 ? stdout : stderr));
}

char *mojo_stdin_read(void) {
    return _read_all(STDIN_FILENO);
}

MojoCompletedProcess *mojo_subprocess_run(MojoList *argv, int64_t capture_output) {
    int64_t n = mojo_list_len(argv);
    char **cargv = malloc((size_t)(n + 1) * sizeof(char *));
    for (int64_t i = 0; i < n; i++) cargv[i] = mojo_list_get_str(argv, i);
    cargv[n] = NULL;

    int out_pipe[2] = {-1, -1}, err_pipe[2] = {-1, -1};
    if (capture_output) { pipe(out_pipe); pipe(err_pipe); }

    pid_t pid = fork();
    if (pid == 0) {
        if (capture_output) {
            dup2(out_pipe[1], STDOUT_FILENO);
            dup2(err_pipe[1], STDERR_FILENO);
            close(out_pipe[0]); close(out_pipe[1]);
            close(err_pipe[0]); close(err_pipe[1]);
        }
        execvp(cargv[0], cargv);
        _exit(127);  /* execvp failed (e.g. command not found) */
    }

    MojoCompletedProcess *p = malloc(sizeof(MojoCompletedProcess));
    p->out = strdup("");
    p->err = strdup("");
    if (capture_output) {
        close(out_pipe[1]); close(err_pipe[1]);
        free(p->out); free(p->err);
        p->out = _read_all(out_pipe[0]);
        p->err = _read_all(err_pipe[0]);
        close(out_pipe[0]); close(err_pipe[0]);
    }
    int status = 0;
    waitpid(pid, &status, 0);
    p->returncode = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    free(cargv);
    return p;
}

int64_t mojo_subprocess_returncode(MojoCompletedProcess *p) { return p->returncode; }
char   *mojo_subprocess_stdout(MojoCompletedProcess *p)     { return p->out; }
char   *mojo_subprocess_stderr(MojoCompletedProcess *p)     { return p->err; }

/* Shared by mojo_str_split/mojo_str_rsplit: split on runs of whitespace,
 * leading/trailing whitespace ignored — Python's str.split()/str.split(None)
 * semantics (as opposed to strtok's "sep" splitting on any one of a set of
 * literal delimiter characters).
 *
 * mojo_list_append_str stores the raw pointer it's given (MojoList never
 * copies or frees string contents — see mojo_list_free), so every token
 * appended here must be its own independent allocation, not a pointer into
 * `copy`: real bug found via list iteration printing empty strings, once
 * `copy` was freed after the loop, every stored pointer was already
 * dangling. */
static void _split_whitespace_into(MojoList *out, char *s) {
    char *copy = strdup(s);
    char *p = copy;
    while (*p) {
        while (*p && isspace((unsigned char)*p)) p++;
        if (!*p) break;
        char *start = p;
        while (*p && !isspace((unsigned char)*p)) p++;
        char saved = *p;
        *p = '\0';
        mojo_list_append_str(out, strdup(start));
        *p = saved;
    }
    free(copy);
}

/* Python str.split(sep): sep NULL (or "") means split on runs of whitespace
 * (leading/trailing ignored, unlike strtok's delimiter-set semantics) — the
 * common no-argument `s.split()` call. Found via a real corrupted-argv bug:
 * `subprocess.run(["gcc"] + ... + py_cflags + ...)` where
 * py_cflags = getenv_output.strip().split() silently produced an empty list
 * (this function used to just bail out on a NULL/empty sep) instead of the
 * real whitespace-split flags, breaking exec of the child process. */
MojoList *mojo_str_split(char *s, char *sep) {
    MojoList *l = mojo_list_new();
    if (!s) return l;
    if (!sep || !*sep) {
        _split_whitespace_into(l, s);
        return l;
    }
    /* Split on the literal `sep` substring, keeping empty fields between
     * consecutive occurrences (Python semantics) — strtok treats `sep` as a
     * set of delimiter characters and collapses runs of them, silently
     * dropping the empty string between two adjacent separators. Real bug
     * found via py_tokenize's own `src.splitlines()` (== split("\n")):
     * every blank line in the input vanished, shifting every subsequent
     * physical line number down by one. */
    size_t sep_len = strlen(sep);
    const char *p = s;
    const char *hit;
    while ((hit = strstr(p, sep)) != NULL) {
        size_t seg_len = (size_t)(hit - p);
        char *seg = (char *)malloc(seg_len + 1);
        memcpy(seg, p, seg_len);
        seg[seg_len] = '\0';
        mojo_list_append_str(l, seg);
        p = hit + sep_len;
    }
    mojo_list_append_str(l, strdup(p));
    return l;
}

/* Python str.count(sub): number of non-overlapping occurrences. `str.count`
 * had no lowering at all before (any call fell through to the generic
 * "unknown char* method" stub, always returning 0) — real bug found via
 * mojo_compiler.py's own multi-line-string handling, which counts '\n' in a
 * matched docstring to preserve line numbers after collapsing it to a
 * placeholder; every count silently came back 0, undoing that fix once
 * self-hosted. */
int64_t mojo_str_count(char *s, char *sub) {
    if (!s || !sub || !*sub) return 0;
    size_t sub_len = strlen(sub);
    int64_t n = 0;
    const char *p = s;
    while ((p = strstr(p, sub)) != NULL) { n++; p += sub_len; }
    return n;
}

/* Python str.splitlines(): splits on \n, \r\n or \r, but — unlike
 * split("\n") — a trailing line terminator does NOT produce a final empty
 * element (used by py_tokenize's `raw_lines = src.splitlines()`, where every
 * Mojo/Python source file ends in a trailing newline). */
MojoList *mojo_str_splitlines(char *s) {
    MojoList *l = mojo_list_new();
    if (!s) return l;
    const char *p = s;
    const char *start = p;
    while (*p) {
        if (*p == '\n' || *p == '\r') {
            size_t seg_len = (size_t)(p - start);
            char *seg = (char *)malloc(seg_len + 1);
            memcpy(seg, start, seg_len);
            seg[seg_len] = '\0';
            mojo_list_append_str(l, seg);
            if (*p == '\r' && *(p + 1) == '\n') p++;
            p++;
            start = p;
        } else {
            p++;
        }
    }
    if (p != start) mojo_list_append_str(l, strdup(start));
    return l;
}

/* Python str.rsplit(sep, maxsplit): sep NULL means split on runs of
 * whitespace (leading/trailing whitespace ignored); maxsplit < 0 means
 * unlimited. Splits are taken from the right, so with a positive maxsplit
 * the leftmost element absorbs any excess separators. */
MojoList *mojo_str_rsplit(char *s, char *sep, int64_t maxsplit) {
    MojoList *l = mojo_list_new();
    if (!s) return l;

    /* Collect tokens left-to-right first (unlimited), then merge from the
     * left once we know how many splits maxsplit allows. */
    MojoList *all = mojo_list_new();
    if (sep && *sep) {
        /* See mojo_str_split's comment: strtok collapses consecutive
         * separators, dropping empty fields that Python's rsplit(sep)
         * keeps. */
        size_t sep_len = strlen(sep);
        const char *p = s;
        const char *hit;
        while ((hit = strstr(p, sep)) != NULL) {
            size_t seg_len = (size_t)(hit - p);
            char *seg = (char *)malloc(seg_len + 1);
            memcpy(seg, p, seg_len);
            seg[seg_len] = '\0';
            mojo_list_append_str(all, seg);
            p = hit + sep_len;
        }
        mojo_list_append_str(all, strdup(p));
    } else {
        _split_whitespace_into(all, s);
    }

    int64_t n = mojo_list_len(all);
    if (maxsplit < 0 || maxsplit >= n - 1) {
        for (int64_t i = 0; i < n; i++) mojo_list_append_str(l, mojo_list_get_str(all, i));
        mojo_list_free(all);      /* the strings moved to `l`; the list did not */
        return l;
    }
    /* Merge the leftmost (n - maxsplit) tokens back together with sep
     * (or a single space, for whitespace splitting) as the join separator. */
    int64_t n_keep = n - maxsplit;
    const char *joiner = (sep && *sep) ? sep : " ";
    char *merged = strdup(mojo_list_get_str(all, 0));
    for (int64_t i = 1; i < n_keep; i++) {
        char *piece = mojo_list_get_str(all, i);
        size_t newlen = strlen(merged) + strlen(joiner) + strlen(piece) + 1;
        char *next = malloc(newlen);
        snprintf(next, newlen, "%s%s%s", merged, joiner, piece);
        free(merged);
        merged = next;
    }
    /* NO `free(merged)` here: `mojo_list_append_str` stores the pointer
     * verbatim (it never copies — every appended string in this file is
     * heap-allocated-and-leaked, or a string literal), so freeing it makes
     * `l[0]` a dangling pointer. This was a use-after-free: any
     * `x.rsplit(sep, k)` with 0 <= k < ntokens-1 returned an empty first
     * element (`"Counter * self".rsplit(" ", 1)` -> `["", "self"]`),
     * which in this compiler's own `_gen_struct_method` corrupted every
     * struct method's forward-declared parameter list. */
    mojo_list_append_str(l, merged);
    for (int64_t i = n_keep; i < n; i++) mojo_list_append_str(l, mojo_list_get_str(all, i));
    /* `all` is a scratch list whose ELEMENTS `l` now shares (the merge above
     * copies them into `merged`; the tail is moved by pointer), so only the
     * list's own struct and buffer are released here — the strings belong to
     * `l`, which is the returned value. */
    mojo_list_free(all);
    return l;
}

/* Python str.partition(sep): split at the FIRST occurrence of sep, always
 * returning a 3-element (head, sep, tail) result — (s, "", "") if sep isn't
 * found. Previously had NO codegen lowering at all (fell to the generic
 * "unknown char* method" stub, always returning a bare int64_t 0), so any
 * `a, b, c = s.partition(x)` unpacked garbage/zero into all three targets —
 * real bug found via importlib/metadata/__init__.py's PathDistribution.
 * _name_from_stem: `name, sep, rest = filename.partition('-')`. */
MojoList *mojo_str_partition(char *s, char *sep) {
    MojoList *l = mojo_list_new();
    if (!s) s = "";
    if (!sep || !*sep) {
        mojo_list_append_str(l, strdup(s));
        mojo_list_append_str(l, strdup(""));
        mojo_list_append_str(l, strdup(""));
        return l;
    }
    char *hit = strstr(s, sep);
    if (!hit) {
        mojo_list_append_str(l, strdup(s));
        mojo_list_append_str(l, strdup(""));
        mojo_list_append_str(l, strdup(""));
        return l;
    }
    size_t head_len = (size_t)(hit - s);
    char *head = (char *)malloc(head_len + 1);
    memcpy(head, s, head_len);
    head[head_len] = '\0';
    mojo_list_append_str(l, head);
    mojo_list_append_str(l, strdup(sep));
    mojo_list_append_str(l, strdup(hit + strlen(sep)));
    return l;
}

/* Python str.rpartition(sep): split at the LAST occurrence of sep, always
 * returning a 3-element (head, sep, tail) result — ("", "", s) if sep isn't
 * found (note: the empty-result placement mirrors before "" "" s, the
 * opposite of partition's s "" "" — real Python semantics). */
MojoList *mojo_str_rpartition(char *s, char *sep) {
    MojoList *l = mojo_list_new();
    if (!s) s = "";
    if (!sep || !*sep) {
        mojo_list_append_str(l, strdup(""));
        mojo_list_append_str(l, strdup(""));
        mojo_list_append_str(l, strdup(s));
        return l;
    }
    size_t sep_len = strlen(sep);
    char *last_hit = NULL;
    char *p = s;
    char *hit;
    while ((hit = strstr(p, sep)) != NULL) {
        last_hit = hit;
        p = hit + sep_len;
    }
    if (!last_hit) {
        mojo_list_append_str(l, strdup(""));
        mojo_list_append_str(l, strdup(""));
        mojo_list_append_str(l, strdup(s));
        return l;
    }
    size_t head_len = (size_t)(last_hit - s);
    char *head = (char *)malloc(head_len + 1);
    memcpy(head, s, head_len);
    head[head_len] = '\0';
    mojo_list_append_str(l, head);
    mojo_list_append_str(l, strdup(sep));
    mojo_list_append_str(l, strdup(last_hit + sep_len));
    return l;
}

/* ═══════════════════════════════════════════════════════════════════════
 * MojoDict — open-addressing hash map, string keys, int64_t slots
 * ═══════════════════════════════════════════════════════════════════════*/
/* (struct definitions now in fire_runtime.h) */

static uint64_t _str_hash(char *s)
{
    /* NULL keys (a missing-field sentinel from the A5 getattr fallback, or a
     * 0/NULL boxed key) hash as the empty string instead of crashing the
     * loop below. The codegen's boxed-int64 dict keys are char* pointers by
     * convention, but a NULL pointer can legitimately reach a dict lookup. */
    if (!s) s = "";
    uint64_t h = 14695981039346656037ULL;
    for (; *s; s++) h = (h ^ (uint8_t)*s) * 1099511628211ULL;
    return h;
}

static _PtrReg _reg_dict;

int mojo_is_registered_dict(int64_t addr) {
    if (addr < 65536) return 0;
    return _pr_has(&_reg_dict, (uint64_t)addr);
}

/* Decimal formatting for an int64_t. `tmp` is a scratch buffer of
 * _INT_STR_BLOCK bytes; the returned pointer is INSIDE it, so the string is
 * tmp + sizeof tmp - result bytes long including the NUL. A hand-rolled itoa:
 * snprintf("%lld") was half the cost of an Int-keyed dict access (vfprintf,
 * locale lookup, buffer setup) for what is a divide loop.
 *
 * 32, not the 20+1 an int needs. This is also the POOL BLOCK SIZE for every
 * transient decimal that `mojo_cstr_or_int_release` hands back (see
 * `_int_str_block`), and the pool also carries FLOAT keys rendered by
 * `mojo_str_from_double`.
 *
 * That second consumer is why the number is measured rather than reasoned. The
 * worst `%.17g` spelling of a double is 24 characters, not the ~21 a 16-digit
 * estimate suggests: 17 significant digits ("1.7976931348623157") plus a sign
 * ("-"), a point, an exponent marker and a THREE-digit exponent ("e-308"), and
 * the sign and the 3-digit exponent are independent, so
 * "-1.2345678901234567e-308" is 24. `%.17g` of `DBL_MAX` ("1.7976931348623157e+308")
 * and of the smallest subnormal ("4.9406564584124654e-324") are 23. A whole
 * number takes the other branch and gets the ".0" Python's str(float) keeps:
 * the widest is "10000000000000000" -> "10000000000000000.0", 19. So 24 + 1 NUL
 * = 25 is the true requirement and 32 has room.
 *
 * Getting this wrong does NOT crash, which is what made it worth measuring:
 * `snprintf(tmp, sizeof tmp, ...)` into an undersized `tmp` TRUNCATES, so a
 * 24-byte block silently rendered "-1.2345678901234567e-308" as a 23-character
 * prefix and every such float became a dict key that no other spelling of that
 * float could ever find. test_ptr_registry.py pins both the width and the
 * producer/pool agreement.
 *
 * The pool stores its free-list link in a block's first 8 bytes and hands
 * blocks out with no size of its own, so every producer into it must agree on
 * one size — a producer that malloc'd a different size and released through
 * this path would put a wrongly-sized block on the free list, and the next
 * `_fmt_int`/`%.17g` would write past it. `mojo_str_from_double` therefore
 * allocates from `_int_str_block()` rather than with a size-exact malloc. */
#define _INT_STR_BLOCK 32
static char *_fmt_int(int64_t v, char *tmp) {
    char *p = tmp + _INT_STR_BLOCK;
    uint64_t u = v < 0 ? (uint64_t)0 - (uint64_t)v : (uint64_t)v;
    *--p = '\0';
    do { *--p = (char)('0' + (u % 10)); u /= 10; } while (u);
    if (v < 0) *--p = '-';
    return p;
}

/* An integer dict key's decimal string is built only when something asks for
 * it. Until then the slot's `key` points at this shared, never-freed sentinel
 * (so `key != NULL` still means "occupied") and `ikey` holds the value; the
 * hash and every integer probe use `ikey` alone. `_slot_key` materializes the
 * string (owned by the slot from then on) for the readers that need text:
 * iteration, repr, `.keys()`/`.items()`. A dict that is only ever indexed by
 * integer therefore allocates no key strings at all. */
static char _ikey_lazy[1] = {0};

static char *_slot_key(_DictSlot *sl)
{
    if (sl->key == _ikey_lazy) {
        char tmp[_INT_STR_BLOCK];
        char *p = _fmt_int(sl->ikey, tmp);
        size_t n = (size_t)(tmp + sizeof tmp - p);
        sl->key = (char *)malloc(n);
        memcpy(sl->key, p, n);
    }
    return sl->key;
}

static void _slot_free_key(_DictSlot *sl)
{
    if (sl->key != _ikey_lazy) free(sl->key);
}

/* For generated code (the compiler's dict repr) that used to read
 * `d->slots[i].key` directly. */
char *mojo_dict_slot_key(MojoDict *d, int64_t i)
{
    return _slot_key(&d->slots[i]);
}

/* The DOUBLE twin of `mojo_dict_slot_key`, for the same caller and the same
 * reason: `_mojo_repr_dict` walks slots by INDEX (the order
 * `mojo_dict_order_indices` hands back), and `mojo_dict_get_double` takes a
 * KEY, so the emitted repr had no way to read a `kind == 1` slot back at its
 * own width. It went to `_mojo_generic_elem_repr` instead, which treats
 * `val > 65536` as a pointer and dereferences it through
 * `mojo_read_type_tag_safe` — and a double's IEEE-754 bits are exactly such a
 * word (3.5 is 0x400C000000000000), so `print({"c": 3.5})` was a SIGSEGV.
 *
 * `memcpy` rather than a `double *` cast: the slot is an `int64_t` in a
 * struct, and reading it through a `double *` is a strict-aliasing violation
 * (every other double accessor in this file copies for the same reason). */
double mojo_dict_slot_double(MojoDict *d, int64_t i)
{
    double v;
    memcpy(&v, &d->slots[i].val, sizeof(v));
    return v;
}

/* mojo_dict_init/mojo_dict_destroy: see mojo_set_init/mojo_set_destroy's
 * comment (same Phase 6 rationale, same refactor shape). */
void mojo_dict_init(MojoDict *d)
{
    d->cap      = MOJO_DICT_INLINE;
    d->used     = 0;
    d->next_seq = 0;
    d->slots    = d->inl;       /* the first table lives inside the struct */
    memset(d->inl, 0, sizeof d->inl);
    _pr_add(&_reg_dict, (uint64_t)(uintptr_t)d);
}

void mojo_dict_destroy(MojoDict *d)
{
    _pr_del(&_reg_dict, (uint64_t)(uintptr_t)d);
    for (int64_t i = 0; i < d->cap; i++) _slot_free_key(&d->slots[i]);
    if (d->slots != d->inl) free(d->slots);
}

MojoDict *mojo_dict_new(void)
{
    MojoDict *d = malloc(sizeof(MojoDict));
    mojo_dict_init(d);
    return d;
}

void mojo_dict_free(MojoDict *d)
{
    mojo_dict_destroy(d);
    free(d);
}

/* dict.clear(): empty the dict IN PLACE, keeping the MojoDict struct (and the
 * caller's pointer to it) valid — a `self.X.clear()` on a class/instance field
 * frees keys+slots but leaves the dict object itself alive so the field stays
 * a valid, reusable empty dict, exactly like Python. The previous lowering of
 * `.clear()` called mojo_dict_free (destroying the dict and leaving every
 * caller's field pointing at freed memory); the second `_reset_func()` on the
 * same GimpleGen instance (one per function during gen_module) then freed the
 * dangling pointer again — macOS libmalloc's "pointer being freed was not
 * allocated" abort, the intermittent SIGABRT (heap-layout dependent, ~40%).
 * Mirrors mojo_list_clear's in-place semantics (runtime/fire_runtime.c:2601). */
void mojo_dict_clear(MojoDict *d)
{
    if (!d) return;
    for (int64_t i = 0; i < d->cap; i++) {
        _slot_free_key(&d->slots[i]);
        d->slots[i].key = NULL;
    }
    d->used = 0;
    d->next_seq = 0;
}

/* `keykind` distinguishes key DOMAINS that share the char* key storage: 0
 * = a str key, 1 = a bytes key. Both store the key's own characters
 * (mojo_bytes_cstr_key for bytes), so strcmp still does the matching, but
 * the tag keeps `d[b'x']` and `d['x']` as the two distinct entries Python
 * says they are instead of silently aliasing one onto the other. */
/* Canonical decimal integer: "0", "5", "-12". Not "+5", not "05", not "-0", not
 * a value that overflows int64_t. A key like this is stored as an INTEGER slot
 * (keykind 2) however it arrived, so `d[5]` and `d["5"]` stay one entry (as they
 * always were) and an int lookup never formats a string. */
static int _canon_int(const char *s, int64_t *out)
{
    if (!s) return 0;
    const char *p = s;
    int neg = 0;
    if (*p == '-') { neg = 1; p++; }
    if (*p < '0' || *p > '9') return 0;
    if (*p == '0' && (p[1] != '\0' || neg)) return 0;
    uint64_t v = 0;
    int n = 0;
    for (; *p; p++, n++) {
        if (*p < '0' || *p > '9') return 0;
        if (n >= 19) return 0;
        v = v * 10 + (uint64_t)(*p - '0');
    }
    if (!neg && v > (uint64_t)INT64_MAX) return 0;
    if (neg && v > (uint64_t)INT64_MAX + 1) return 0;
    *out = neg ? (int64_t)((uint64_t)0 - v) : (int64_t)v;
    return 1;
}

static inline uint64_t _ik_hash(int64_t k)
{
    uint64_t x = (uint64_t)k;          /* the murmur3 64-bit finalizer */
    x ^= x >> 33; x *= 0xff51afd7ed558ccdULL;
    x ^= x >> 33; x *= 0xc4ceb9fe1a85ec53ULL;
    x ^= x >> 33;
    return x;
}

/* The slot for integer key `k`: the matching slot if present, else the empty
 * slot where it would go. (`_dict_find_k` is the string-key twin.) */
static _DictSlot *_dict_find_ik(MojoDict *d, int64_t k)
{
    uint64_t mask = (uint64_t)d->cap - 1;
    uint64_t h = _ik_hash(k) & mask;
    for (int64_t i = 0; i < d->cap; i++) {
        _DictSlot *sl = &d->slots[(h + (uint64_t)i) & mask];
        if (!sl->key) return sl;
        if (sl->keykind == 2 && sl->ikey == k) return sl;
    }
    return NULL;
}

static _DictSlot *_dict_lookup_ik(MojoDict *d, int64_t k)
{
    if (!d || !d->cap || !d->slots) return NULL;
    uint64_t mask = (uint64_t)d->cap - 1;
    uint64_t h = _ik_hash(k) & mask;
    for (int64_t i = 0; i < d->cap; i++) {
        _DictSlot *sl = &d->slots[(h + (uint64_t)i) & mask];
        if (!sl->key) return NULL;
        if (sl->keykind == 2 && sl->ikey == k) return sl;
    }
    return NULL;
}

static _DictSlot *_dict_find_k(MojoDict *d, char *key, int64_t keykind)
{
    int64_t iv;
    if (keykind == 0 && _canon_int(key, &iv)) return _dict_find_ik(d, iv);
    uint64_t mask = (uint64_t)d->cap - 1;      /* cap is a power of two */
    uint64_t h = _str_hash(key) & mask;
    for (int64_t i = 0; i < d->cap; i++) {
        int64_t idx = (int64_t)((h + (uint64_t)i) & mask);
        _DictSlot *sl = &d->slots[idx];
        if (!sl->key) return sl;          /* empty — insertion point */
        if (sl->keykind == keykind && strcmp(sl->key, key) == 0) return sl;
    }
    return NULL;
}

static _DictSlot *_dict_find(MojoDict *d, char *key)
{ return _dict_find_k(d, key, 0 /* str key */); }

static void _dict_grow(MojoDict *d);
static void _dict_set_ik(MojoDict *d, int64_t k, int64_t val, int64_t kind);

/* seq >= 0 preserves an already-assigned insertion sequence number (used
 * only by _dict_grow's rehash, so a key's original insertion order survives
 * moving to a new, bigger slot array); seq < 0 assigns a fresh one. */
static void _dict_set_raw_seq_kind_k(MojoDict *d, char *key, int64_t val,
                                     int64_t seq, int64_t kind, int64_t keykind)
{
    if (d->used * 2 >= d->cap) _dict_grow(d);
    if (keykind == 2) keykind = 0;   /* a re-insert of an integer slot: the string domain, re-normalised below */
    _DictSlot *sl = _dict_find_k(d, key, keykind);
    if (!sl->key) {
        int64_t iv;
        if (keykind == 0 && _canon_int(key, &iv)) {
            sl->key = _ikey_lazy;
            sl->keykind = 2;
            sl->ikey = iv;
        } else {
            sl->key = strdup(key);
            sl->keykind = keykind;
        }
        sl->seq = (seq >= 0) ? seq : d->next_seq++;
        if (sl->seq >= d->next_seq) d->next_seq = sl->seq + 1;
        d->used++;
    }
    sl->val = val;
    sl->kind = kind;   /* a value re-set under an existing key replaces the
                        * old value AND its type, like real Python's
                        * dict.__setitem__ */
}

static void _dict_set_raw_seq_kind(MojoDict *d, char *key, int64_t val, int64_t seq, int64_t kind)
{
    _dict_set_raw_seq_kind_k(d, key, val, seq, kind, 0 /* str key */);
}

static void _dict_set_raw_seq(MojoDict *d, char *key, int64_t val, int64_t seq)
{
    _dict_set_raw_seq_kind(d, key, val, seq, 0 /* int */);
}

static void _dict_set_raw(MojoDict *d, char *key, int64_t val, int64_t kind)
{
    _dict_set_raw_seq_kind(d, key, val, -1, kind);
}

static void _dict_grow(MojoDict *d)
{
    int64_t old_cap = d->cap;
    _DictSlot *old  = d->slots;
    d->cap   *= 2;
    d->slots = calloc((size_t)d->cap, sizeof(_DictSlot));
    uint64_t mask = (uint64_t)d->cap - 1;
    /* Move each occupied slot whole into the new array: the key string's
     * ownership moves with it, so a resize no longer strdup()s and free()s
     * every key. Keys are already unique (a bytes key and a str key with the
     * same characters are distinct entries), so the probe only needs an empty
     * slot, never a comparison; `used`, `seq` and `next_seq` are unchanged. */
    for (int64_t i = 0; i < old_cap; i++) {
        if (!old[i].key) continue;
        uint64_t j = (old[i].keykind == 2 ? _ik_hash(old[i].ikey)
                                          : _str_hash(old[i].key)) & mask;
        while (d->slots[j].key) j = (j + 1) & mask;
        d->slots[j] = old[i];
    }
    if (old != d->inl) free(old);
}

/* Slot indices for d->slots, in insertion order (ascending by _DictSlot.seq).
 * Backs BOTH generic repr()'s dict formatting (_mojo_repr_dict) and real
 * iteration (MojoDictIter, .keys()/.values()/.items()), so all of them walk
 * Python's insertion-order-preserving dict order, not raw open-addressing
 * hash-slot order. Returns a malloc'd array of d->used entries (NULL if
 * empty); caller must free() it. */
static int _cmp_seqidx(const void *a, const void *b) {
    int64_t sa = ((const int64_t *)a)[0];
    int64_t sb = ((const int64_t *)b)[0];
    return (sa > sb) - (sa < sb);
}
int64_t *mojo_dict_order_indices(MojoDict *d)
{
    if (!d || d->used == 0) return NULL;
    /* Size the scratch and result arrays from what is actually in the slot
     * table, not from `used` alone. A well-formed dict has exactly `used`
     * occupied slots, but a value the compiled backend typed as a dict that is
     * really another container (a list of pairs was iterated as a dict:
     * bugs/CODEGEN_list_of_pairs_iterated_as_dict.md) has no such guarantee,
     * and trusting `used` wrote past the end of the malloc block and corrupted
     * the allocator's free list, crashing much later inside malloc. The result
     * is padded to at least `used` entries because MojoDictIter walks
     * `pos < dict->used`. */
    int64_t occ = 0;
    for (int64_t i = 0; i < d->cap; i++)
        if (d->slots[i].key) occ++;
    int64_t (*tmp)[2] = malloc(sizeof(int64_t) * 2 * (size_t)(occ ? occ : 1));
    int64_t n = 0;
    for (int64_t i = 0; i < d->cap; i++)
        if (d->slots[i].key) { tmp[n][0] = d->slots[i].seq; tmp[n][1] = i; n++; }
    qsort(tmp, (size_t)n, sizeof(int64_t) * 2, _cmp_seqidx);
    int64_t total = n > d->used ? n : d->used;
    int64_t *out = calloc((size_t)total, sizeof(int64_t));
    for (int64_t i = 0; i < n; i++) out[i] = tmp[i][1];
    free(tmp);
    return out;
}

void mojo_dict_set_int(MojoDict *d, char *key, int64_t v)
{
    _dict_set_raw(d, key, v, 0);
}

void mojo_dict_set_double(MojoDict *d, char *key, double v)
{
    int64_t bits;
    memcpy(&bits, &v, sizeof(bits));
    _dict_set_raw(d, key, bits, 1);
}

void mojo_dict_set_str(MojoDict *d, char *key, char *v)
{
    _dict_set_raw(d, key, (int64_t)(uintptr_t)v, 2);
}

/* A Python bool is a 0/1 int64_t here (see _lower_BoolLiteral), so it needs
 * its own _DictSlot.kind to stay distinguishable from a genuine 0/1 int once
 * it is a slot — same reason `kind` exists for double and char * above. This
 * replaces a whole-DICT registry (`mojo_mark_dict_bool_values`, since deleted)
 * that answered for every value at once, so `{'name': p.name, 'ok': p.ok}`
 * rendered the int as True/False too. Per-slot is the shape the slot's `kind`
 * already had; only the one value stored through this setter changes. */
void mojo_dict_set_bool(MojoDict *d, char *key, int v)
{
    _dict_set_raw(d, key, v ? 1 : 0, 3);
}

static _DictSlot *_dict_lookup_k(MojoDict *d, char *key, int64_t keykind)
{
    if (!d || !d->cap || !d->slots) return NULL;
    int64_t iv;
    if (keykind == 0 && _canon_int(key, &iv)) return _dict_lookup_ik(d, iv);
    /* cap is always a power of two (mojo_dict_init: 8, _dict_grow: doubles). */
    uint64_t mask = (uint64_t)d->cap - 1;
    uint64_t h = _str_hash(key) & mask;
    for (int64_t i = 0; i < d->cap; i++) {
        int64_t idx = (int64_t)((h + (uint64_t)i) & mask);
        _DictSlot *sl = &d->slots[idx];
        if (!sl->key) return NULL;
        if (sl->keykind == keykind && strcmp(sl->key, key) == 0) return sl;
    }
    return NULL;
}

static _DictSlot *_dict_lookup(MojoDict *d, char *key)
{ return _dict_lookup_k(d, key, 0 /* str key */); }

int64_t mojo_dict_get_int(MojoDict *d, char *key)
{
    _DictSlot *sl = _dict_lookup(d, key);
    return sl ? sl->val : 0;
}

double mojo_dict_get_double(MojoDict *d, char *key)
{
    _DictSlot *sl = _dict_lookup(d, key);
    if (!sl) return 0.0;
    double v;
    memcpy(&v, &sl->val, sizeof(v));
    return v;
}

char *mojo_dict_get_str(MojoDict *d, char *key)
{
    _DictSlot *sl = _dict_lookup(d, key);
    return sl ? (char *)(uintptr_t)sl->val : NULL;
}

int mojo_dict_contains(MojoDict *d, char *key)
{
    return _dict_lookup(d, key) != NULL;
}

/* ── bytes-keyed dict access ─────────────────────────────────────────────
 * `d[b'k']` needs its own key domain (see _DictSlot.keykind) so a bytes key
 * and a str key of the same characters stay distinct entries, as in Python.
 * Every one of these takes the key's CONTENT as a NUL-terminated copy
 * (mojo_bytes_cstr_key), the same probe the str path uses. */

static void _dict_set_bytes_raw(MojoDict *d, MojoBytes *key, int64_t val, int64_t kind)
{
    if (!d) return;
    char *k = mojo_bytes_cstr_key(key);
    _dict_set_raw_seq_kind_k(d, k, val, -1, kind, 1 /* bytes key */);
    free(k);
}

void mojo_dict_set_bytes_int(MojoDict *d, MojoBytes *key, int64_t v)
{ _dict_set_bytes_raw(d, key, v, 0); }

void mojo_dict_set_bytes_double(MojoDict *d, MojoBytes *key, double v)
{
    int64_t bits;
    memcpy(&bits, &v, sizeof(bits));
    _dict_set_bytes_raw(d, key, bits, 1);
}

void mojo_dict_set_bytes_str(MojoDict *d, MojoBytes *key, char *v)
{ _dict_set_bytes_raw(d, key, (int64_t)(uintptr_t)v, 2); }

/* The bytes-key twin of mojo_dict_set_bool: same value, same slot kind, its
 * own key DOMAIN (see mojo_dict_set_bytes_int). */
void mojo_dict_set_bytes_bool(MojoDict *d, MojoBytes *key, int v)
{ _dict_set_bytes_raw(d, key, v ? 1 : 0, 3); }

static _DictSlot *_dict_lookup_bytes(MojoDict *d, MojoBytes *key)
{
    if (!d) return NULL;
    char *k = mojo_bytes_cstr_key(key);
    _DictSlot *sl = _dict_lookup_k(d, k, 1 /* bytes key */);
    free(k);
    return sl;
}

int64_t mojo_dict_get_bytes_int(MojoDict *d, MojoBytes *key)
{
    _DictSlot *sl = _dict_lookup_bytes(d, key);
    return sl ? sl->val : 0;
}

char *mojo_dict_get_bytes_str(MojoDict *d, MojoBytes *key)
{
    _DictSlot *sl = _dict_lookup_bytes(d, key);
    if (!sl) return NULL;
    return (char *)(uintptr_t)sl->val;
}

double mojo_dict_get_bytes_double(MojoDict *d, MojoBytes *key)
{
    _DictSlot *sl = _dict_lookup_bytes(d, key);
    if (!sl) return 0.0;
    double v;
    memcpy(&v, &sl->val, sizeof(v));
    return v;
}

int mojo_dict_contains_bytes(MojoDict *d, MojoBytes *key)
{
    return _dict_lookup_bytes(d, key) != NULL;
}

int64_t mojo_dict_setdefault_bytes_int(MojoDict *d, MojoBytes *key, int64_t dflt)
{
    if (!d) return dflt;
    if (mojo_dict_contains_bytes(d, key)) return mojo_dict_get_bytes_int(d, key);
    mojo_dict_set_bytes_int(d, key, dflt);
    return dflt;
}

static int64_t _dict_pop_k(MojoDict *d, char *key, int64_t keykind);

/* The value-domain siblings of mojo_dict_pop_bytes_int. All three share
 * this body: a dict slot is one int64_t of bits, so what differs is only
 * how the caller wants them READ BACK — a double through memcpy (never a
 * pointer/int punning cast, which strict-aliasing gcc may reorder), a
 * char* straight through, an int as-is. `pop` on a str-keyed dict only ever
 * had the int spelling, so a bytes-keyed dict with str values popped its
 * value as a raw pointer decimal. */
static int64_t _dict_pop_bytes_raw(MojoDict *d, MojoBytes *key, int64_t dflt)
{
    if (!d) return dflt;
    if (!mojo_dict_contains_bytes(d, key)) return dflt;
    char *k = mojo_bytes_cstr_key(key);
    int64_t v = _dict_pop_k(d, k, 1 /* bytes key */);
    free(k);
    return v;
}

int64_t mojo_dict_pop_bytes_int(MojoDict *d, MojoBytes *key, int64_t dflt)
{ return _dict_pop_bytes_raw(d, key, dflt); }

char *mojo_dict_pop_bytes_str(MojoDict *d, MojoBytes *key)
{ return (char *)(uintptr_t)_dict_pop_bytes_raw(d, key, 0); }

double mojo_dict_pop_bytes_double(MojoDict *d, MojoBytes *key)
{
    int64_t bits = _dict_pop_bytes_raw(d, key, 0);
    double v;
    memcpy(&v, &bits, sizeof(v));
    return v;
}

void mojo_dict_print(MojoDict *d)
{
    printf("{");
    int first = 1;
    for (int64_t i = 0; i < d->cap; i++) {
        if (!d->slots[i].key) continue;
        if (!first) printf(", ");
        printf("\"%s\": %lld", _slot_key(&d->slots[i]), (long long)d->slots[i].val);
        first = 0;
    }
    printf("}");
}

int64_t mojo_dict_len(MojoDict *d) { return d ? d->used : 0; }

/* ── Runtime dict-keyed %-formatting ────────────────────────────────────*/
/* A small growable output buffer for assembling the formatted result. */
typedef struct { char *buf; size_t len, cap; } _FmtBuf;

static void _fmtbuf_reserve(_FmtBuf *b, size_t extra)
{
    if (b->len + extra + 1 <= b->cap) return;
    size_t nc = b->cap ? b->cap * 2 : 128;
    while (nc < b->len + extra + 1) nc *= 2;
    b->buf = realloc(b->buf, nc);
    b->cap = nc;
}

static void _fmtbuf_putn(_FmtBuf *b, const char *s, size_t n)
{
    _fmtbuf_reserve(b, n);
    memcpy(b->buf + b->len, s, n);
    b->len += n;
    b->buf[b->len] = '\0';
}

static void _fmtbuf_puts(_FmtBuf *b, const char *s) { _fmtbuf_putn(b, s, strlen(s)); }

/* Materialize one %(key)... spec's value as display text for the s/r/a
 * conversions (Python's str()/repr() coercion), honoring the slot's kind
 * tag. Returns a pointer to a heap or static-ish string the caller must
 * treat as short-lived: int values use mojo_str_from_int's own heap
 * buffer (leaked, consistent with this runtime's no-free model); doubles
 * are formatted into a caller-provided buffer; strings pass through. */
static char *_fmt_dict_val_str(int64_t v, int64_t kind, char *dblbuf, size_t dblcap)
{
    if (kind == 2) return (char *)(uintptr_t)v;
    if (kind == 1) {
        double dv;
        memcpy(&dv, &v, sizeof(dv));
        snprintf(dblbuf, dblcap, "%.17g", dv);
        /* Trim like Python str(float): %.17g of 3.5 is "3.5" already;
         * nothing further needed for common values. */
        return dblbuf;
    }
    return mojo_str_from_int(v);
}

char *mojo_str_format_dict(char *fmt, MojoDict *vals)
{
    if (!fmt) return NULL;
    _FmtBuf out = {0};
    const char *p = fmt;
    while (*p) {
        if (*p != '%') {
            const char *start = p;
            while (*p && *p != '%') p++;
            _fmtbuf_putn(&out, start, (size_t)(p - start));
            continue;
        }
        /* At a '%'. */
        if (p[1] == '%') { _fmtbuf_putn(&out, "%", 1); p += 2; continue; }
        /* Dict-keyed form: %(key)[flags][width][.prec]conv */
        if (p[1] != '(') {
            /* Not a keyed spec — a stray '%' in a dynamic template. Real
             * Python would fail with "unsupported format character" /
             * ValueError only when a conversion follows; a lone trailing
             * '%' raises ValueError too. Copy verbatim and keep going:
             * matches _lower_percent_format's established lenient
             * degradation for templates that weren't really format
             * strings, and never crashes. */
            _fmtbuf_putn(&out, p, 1);
            p++;
            continue;
        }
        const char *key_start = p + 2;
        const char *key_end = key_start;
        while (*key_end && *key_end != ')') key_end++;
        if (!*key_end) { /* unterminated %( — copy rest verbatim */
            _fmtbuf_puts(&out, p);
            break;
        }
        size_t keylen = (size_t)(key_end - key_start);
        char key[256];
        if (keylen >= sizeof(key)) keylen = sizeof(key) - 1;
        memcpy(key, key_start, keylen);
        key[keylen] = '\0';

        /* Flags/width/precision run after the key. */
        const char *s = key_end + 1;
        char fwp[32];
        size_t fwplen = 0;
        while (*s && strchr("-+ #.0123456789", *s) && fwplen + 1 < sizeof(fwp)) {
            fwp[fwplen++] = *s;
            s++;
        }
        fwp[fwplen] = '\0';
        char conv = *s;
        if (conv) s++;

        _DictSlot *sl = vals ? _dict_lookup(vals, key) : NULL;
        if (!sl) {
            free(out.buf);
            mojo_raise_key_error(key);
            return NULL;  /* unreached */
        }
        int64_t v = sl->val, kind = sl->kind;

        if (conv == 's' || conv == 'r' || conv == 'a') {
            char dblbuf[40];
            char *sv = _fmt_dict_val_str(v, kind, dblbuf, sizeof dblbuf);
            if ((conv == 'r' || conv == 'a') && kind == 2) {
                /* repr() of a string value adds the quotes. */
                char *q = mojo_repr_str(sv);
                _fmtbuf_puts(&out, q);
            } else {
                /* Width/precision apply to the string too ("%10.3s"). */
                char pspec[48];
                snprintf(pspec, sizeof pspec, "%%%.*ss", (int)fwplen, fwp);
                char piece[512];
                snprintf(piece, sizeof piece, pspec, sv);
                _fmtbuf_puts(&out, piece);
            }
            p = s;
            continue;
        }

        /* Numeric / char conversions. */
        char cconv[4];
        int is_int_conv =
            (conv == 'd' || conv == 'i' || conv == 'u' ||
             conv == 'o' || conv == 'x' || conv == 'X');
        int is_flt_conv =
            (conv == 'e' || conv == 'E' || conv == 'f' || conv == 'F' ||
             conv == 'g' || conv == 'G');
        if (is_int_conv) {
            long long iv;
            if (kind == 2) goto lenient;      /* %d of a string: TypeError in Python */
            if (kind == 1) {
                double dv; memcpy(&dv, &v, sizeof dv);
                iv = (long long)dv;           /* real Python truncates %d of float */
            } else {
                iv = (long long)v;
            }
            cconv[0] = 'l'; cconv[1] = 'l';
            cconv[2] = (conv == 'i') ? 'd' : conv;   /* C has no %lli/%llu-as-i */
            cconv[3] = '\0';
            char pspec[48];
            snprintf(pspec, sizeof pspec, "%%%.*s%s", (int)fwplen, fwp, cconv);
            char piece[512];
            snprintf(piece, sizeof piece, pspec, iv);
            _fmtbuf_puts(&out, piece);
        } else if (is_flt_conv) {
            double dv;
            if (kind == 2) goto lenient;      /* %f of a string: TypeError in Python */
            if (kind == 1) memcpy(&dv, &v, sizeof dv);
            else dv = (double)v;              /* ints widen, like real Python */
            char pspec[48];
            snprintf(pspec, sizeof pspec, "%%%.*s%c", (int)fwplen, fwp, conv);
            char piece[512];
            snprintf(piece, sizeof piece, pspec, dv);
            _fmtbuf_puts(&out, piece);
        } else if (conv == 'c') {
            if (kind == 2) goto lenient;
            long long cv;
            if (kind == 1) { double tmp; memcpy(&tmp, &v, sizeof tmp); cv = (long long)tmp; }
            else cv = (long long)v;
            char piece[8];
            snprintf(piece, sizeof piece, "%c", (int)cv);
            _fmtbuf_puts(&out, piece);
        } else {
            goto lenient;
        }
        p = s;
        continue;
lenient:
        /* Unsupported/invalid combination: copy the whole original spec
         * text through unchanged (never crash, never silently misprint a
         * wrong-typed value). Mirrors _lower_percent_format's own
         * mismatched-arity degradation convention. */
        _fmtbuf_putn(&out, p, (size_t)(s - p));
        p = s;
        continue;
    }
    if (!out.buf) return strdup("");
    return out.buf;
}

/* ── MojoDictIter ─────────────────────────────────────────────────────────*/

struct MojoDictIter {
    MojoDict *dict;
    int64_t   pos;    /* current slot index (-1 = not yet started) */
};

MojoDictIter *mojo_dict_iter_new(MojoDict *d)
{
    MojoDictIter *it = malloc(sizeof(MojoDictIter));
    it->dict  = d;
    it->pos   = -1;
    it->order = mojo_dict_order_indices(d);
    return it;
}

int mojo_dict_iter_next(MojoDictIter *it)
{
    it->pos++;
    return (it->dict && it->pos < it->dict->used) ? 1 : 0;
}

char *mojo_dict_iter_key(MojoDictIter *it)
{
    return _slot_key(&it->dict->slots[it->order[it->pos]]);
}

/* The current key as an INTEGER, for a loop over a Dict[Int, V]. An integer
 * slot (keykind 2) holds it directly; any other slot is a key that was never
 * canonical decimal, so parse what it holds rather than invent a value. */
int64_t mojo_dict_iter_key_int(MojoDictIter *it)
{
    _DictSlot *s = &it->dict->slots[it->order[it->pos]];
    if (s->keykind == 2) return s->ikey;
    return s->key ? (int64_t)strtoll(s->key, NULL, 10) : 0;   /* not an integer slot: parse its text */
}

int64_t mojo_dict_iter_val_int(MojoDictIter *it)
{
    return it->dict->slots[it->order[it->pos]].val;
}

double mojo_dict_iter_val_double(MojoDictIter *it)
{
    double v;
    memcpy(&v, &it->dict->slots[it->order[it->pos]].val, sizeof(v));
    return v;
}

char *mojo_dict_iter_val_str(MojoDictIter *it)
{
    return (char *)(uintptr_t)it->dict->slots[it->order[it->pos]].val;
}

void mojo_dict_iter_free(MojoDictIter *it) { free(it->order); free(it); }

/* ═══════════════════════════════════════════════════════════════════════
 * MojoSet — hash set backed by the same open-addressing scheme
 * ═══════════════════════════════════════════════════════════════════════*/
/* (struct definitions now in fire_runtime.h) */

/* Registry of every MojoSet this runtime allocates — the set-shaped
 * sibling of _reg_list above, and for the same reason: a set
 * reaching codegen as a boxed `int64_t` (a cross-module module-global
 * accessor returns int64_t, so `gimple_ctypes._C_RESERVED_FUNCS` and
 * friends arrive type-erased) carries no tag of its own, and without a
 * registry `x in <that value>` had no way to discover it was a set. See
 * mojo_in_dispatch_str. */
static _PtrReg _reg_set;

int mojo_is_registered_set(int64_t addr) {
    if (addr < 65536) return 0;
    return _pr_has(&_reg_set, (uint64_t)addr);
}

/* mojo_set_init/mojo_set_destroy: the in-place halves of mojo_set_new/
 * mojo_set_free, factored out for doc/OWNERSHIP_MODEL.md's Phase 6
 * (stack allocation of Phase-3-owned locals, see gimple_gen_infra.py's
 * "Phase 6" section) — a stack-declared `MojoSet` has no `malloc`/`free`
 * for the struct itself, only for its `slots` buffer and registry
 * membership, which these two do exactly like `_new`/`_free` always did
 * (`_new`/`_free` are now thin wrappers around them, not a duplicate
 * implementation — this project's own "consolidate duplicates"
 * convention, not a special case for this feature). */
void mojo_set_init(MojoSet *s)
{
    s->cap   = MOJO_SET_INLINE;
    s->used  = 0;
    s->next_seq = 0;
    s->slots = s->inl;          /* the first table lives inside the struct */
    for (int64_t i = 0; i < s->cap; i++) { s->slots[i].tag = -1; s->slots[i].seq = 0; }
    _pr_add(&_reg_set, (uint64_t)(uintptr_t)s);
}

void mojo_set_destroy(MojoSet *s)
{
    _pr_del(&_reg_set, (uint64_t)(uintptr_t)s);
    for (int64_t i = 0; i < s->cap; i++)
        if (s->slots[i].tag == 1) free(s->slots[i].val_s);
    if (s->slots != s->inl) free(s->slots);
}

MojoSet *mojo_set_new(void)
{
    MojoSet *s = malloc(sizeof(MojoSet));
    mojo_set_init(s);
    return s;
}

void mojo_set_free(MojoSet *s)
{
    mojo_set_destroy(s);
    free(s);
}

/* set.clear(): empty the set IN PLACE, keeping the MojoSet struct (and the
 * caller's pointer to it) valid — same rationale as mojo_dict_clear above. */
void mojo_set_clear(MojoSet *s)
{
    if (!s) return;
    for (int64_t i = 0; i < s->cap; i++) {
        if (s->slots[i].tag == 1) free(s->slots[i].val_s);
        s->slots[i].tag = -1;
        s->slots[i].val_i = 0;
        s->slots[i].val_s = NULL;
        s->slots[i].seq = 0;
    }
    s->used = 0;
    s->next_seq = 0;
}

static void _set_grow(MojoSet *s);

static int64_t _set_slot_int(MojoSet *s, int64_t v)
{
    uint64_t h = (uint64_t)v * 2654435761ULL;
    /* `% s->cap` (always a power of two) keeps only h's LOW bits - the
     * weakest bits of a plain multiplicative hash. Values from
     * mojo_set_add_int(registry, (int64_t)(intptr_t)ptr) (this runtime's
     * only int-keyed-set use case: object-identity/type-tag registries
     * keyed by heap pointer) are typically 16-byte aligned, i.e. always
     * divisible by 16 - and since 2654435761 is odd, v's low 4 zero bits
     * survive the multiply into h, so every such key collides on the same
     * 1-in-16 slots instead of spreading across the table: a real
     * clustering pathology that degrades this from O(1) amortized toward
     * O(n) per insert as a registry accumulates many pointers, exactly the
     * "self-hosted compiler processing its own large source" scenario that
     * exposed it. Fold the high bits down before the modulo (matches the
     * mixing step in xxhash/murmur's finalizers) so pointer alignment
     * doesn't determine which slots ever get used as probe starts. */
    h ^= h >> 32;
    for (int64_t i = 0; i < s->cap; i++) {
        int64_t idx = (int64_t)((h + (uint64_t)i) % (uint64_t)s->cap);
        _SetSlot *sl = &s->slots[idx];
        if (sl->tag == -1) return idx;
        if (sl->tag == 0 && sl->val_i == v) return idx;
    }
    return -1;
}

/* Probe for `v` among slots of DOMAIN `tag` only (1 = str, 2 = bytes). Both
 * domains store the value's own characters in val_s, so the tag is what
 * keeps `{b'a'}` and `{'a'}` the two distinct sets Python says they are. */
static int64_t _set_slot_str_tag(MojoSet *s, char *v, int tag)
{
    /* A NULL needle is a real None value the codegen boxed as a null char*
     * (e.g. a `None` alias/name flowing into `{ ... for n in names }`).
     * Treat it as the empty string for slotting rather than dereferencing
     * NULL in _str_hash/strcmp — mirrors mojo_list_contains_str's guard. */
    if (!v) v = "";
    uint64_t h = _str_hash(v) % (uint64_t)s->cap;
    for (int64_t i = 0; i < s->cap; i++) {
        int64_t idx = (int64_t)((h + (uint64_t)i) % (uint64_t)s->cap);
        _SetSlot *sl = &s->slots[idx];
        if (sl->tag == -1) return idx;
        if (sl->tag == tag && sl->val_s && strcmp(sl->val_s, v) == 0) return idx;
    }
    return -1;
}

static int64_t _set_slot_str(MojoSet *s, char *v)
{ return _set_slot_str_tag(s, v, 1 /* str domain */); }

/* Place ONE already-owned entry into the freshly-resized table `s`, keeping
 * the caller's original insertion `seq` and taking a PRIVATE copy of any
 * string payload. `_set_grow`'s replay is the only caller.
 *
 * It exists because routing the replay through the public adders
 * (`mojo_set_add_int` / `mojo_set_add_str`) was wrong three separate ways,
 * and all three are silent:
 *
 *  1. BYTES ENTRIES WERE DROPPED. The old replay had a `tag == 0` branch
 *     and a `tag == 1` branch and NO `tag == 2` branch, so every bytes
 *     element (`mojo_set_add_bytes`, which stamps tag 2 precisely so
 *     `b'a'` and `'a'` stay distinct) was discarded by the rehash — and its
 *     `val_s` leaked, since the free lived in the tag-1 branch. Measured
 *     through the compiled path before this fix:
 *
 *         s = {b'a', b'b', b'c', b'd', b'e'}
 *         print(len(s))          ->  1        (expected 5)
 *
 *     `mojo_set_init` starts `cap` at 8 and grows when `used * 2 >= cap`,
 *     i.e. on the FIFTH insert, so any bytes set of 5+ elements lost all
 *     but the element that triggered the grow. Tag 1 and tag 2 have
 *     identical storage (a strdup'd/`cstr_key`'d `val_s` the slot owns) and
 *     now share one branch.
 *
 *  2. EVERY KEY WAS PROBED TWICE. The adders probe to find the slot and
 *     then the replay called `_set_slot_int` / `_set_slot_str_tag` a SECOND
 *     time on the same key just to recover the index it had already found.
 *     Each probe is an O(cap) linear scan under load, and this runs for
 *     every entry on every rehash.
 *
 *  3. EVERY STRING WAS COPIED AND THEN FREED. `mojo_set_add_str` strdups
 *     its argument; the replay then freed the ORIGINAL. Net effect: one
 *     malloc + one free per string entry per rehash, to end up with the
 *     same bytes.
 *
 * Plus a fourth, structural one that is not a miscompile but made the
 * replay need its `next_seq` save/restore at all: the adders re-check
 * `used * 2 >= cap` and can call `_set_grow` RECURSIVELY while the outer
 * replay is still walking the old table. It cannot happen — the new
 * capacity is `2 * old_cap` and the old table held at most `old_cap`
 * occupied slots, so there is provably room for every entry being
 * reinserted — which is why this function takes no capacity check and no
 * retry, and why the replay no longer touches `next_seq` at all (it stamps
 * `seq` directly instead of letting an adder stamp `next_seq++` and
 * saving the counter afterwards). `idx < 0` is therefore unreachable; the
 * guard is kept so a future change to the growth policy degrades to
 * "drop this one entry" rather than to a write past the end of `slots`. */
static void _set_replay_entry(MojoSet *s, int tag, int64_t val_i,
                              char *val_s, int64_t seq)
{
    int64_t idx;
    if (tag == 0) idx = _set_slot_int(s, val_i);
    else          idx = _set_slot_str_tag(s, val_s, tag);
    if (idx < 0) return;
    s->slots[idx].tag   = tag;
    s->slots[idx].val_i = (tag == 0) ? val_i : 0;
    s->slots[idx].val_s = (tag == 0) ? NULL : strdup(val_s ? val_s : "");
    s->slots[idx].seq   = seq;
    s->used++;
}

static void _set_grow(MojoSet *s)
{
    int64_t old_cap = s->cap;
    _SetSlot *old   = s->slots;
    s->cap   *= 2;
    s->used  = 0;
    s->slots = malloc((size_t)s->cap * sizeof(_SetSlot));
    for (int64_t i = 0; i < s->cap; i++) { s->slots[i].tag = -1; s->slots[i].seq = 0; }
    /* Re-insert carries each entry's ORIGINAL seq across the rehash, so a
     * grow never reorders iteration. `next_seq` is deliberately left alone
     * (the previous code saved and restored it around a replay that went
     * through the adders, which stamp `next_seq++`): `_set_replay_entry`
     * writes `seq` straight into the slot, so nothing here can perturb it. */
    for (int64_t i = 0; i < old_cap; i++) {
        if (old[i].tag == 0) {
            _set_replay_entry(s, 0, old[i].val_i, NULL, old[i].seq);
        } else if (old[i].tag == 1 || old[i].tag == 2) {
            _set_replay_entry(s, old[i].tag, 0, old[i].val_s, old[i].seq);
            free(old[i].val_s);
        }
    }
    if (old != s->inl) free(old);
}

void mojo_set_add_int(MojoSet *s, int64_t v)
{
    if (s->used * 2 >= s->cap) _set_grow(s);
    int64_t idx = _set_slot_int(s, v);
    if (idx < 0) { _set_grow(s); idx = _set_slot_int(s, v); }
    if (s->slots[idx].tag == -1) {
        s->slots[idx].tag = 0; s->slots[idx].val_i = v;
        s->slots[idx].seq = s->next_seq++; s->used++;
    }
}

void mojo_set_add_str(MojoSet *s, char *v)
{
    if (s->used * 2 >= s->cap) _set_grow(s);
    int64_t idx = _set_slot_str(s, v);
    if (idx < 0) { _set_grow(s); idx = _set_slot_str(s, v); }
    if (s->slots[idx].tag == -1) {
        s->slots[idx].tag   = 1;
        s->slots[idx].val_s = strdup(v ? v : "");
        s->slots[idx].seq   = s->next_seq++;
        s->used++;
    }
}

/* `s.add(b'..')` / a `{b'..', b'..'}` literal. The slot is keyed by CONTENT
 * (the same _set_slot_str probe a str element uses, so `b'a'` matches any
 * other `b'a'`), but carries its own tag 2 so it can never be confused with
 * a str element of the same characters — `b'a' in {b'a'}` and `'a' in {b'a'}`
 * give different answers, as in Python. The stored val_s is a NUL-terminated
 * copy of the bytes, so a bytes element containing an embedded NUL is
 * truncated here (the same lossiness the char*-keyed dict already has). */
void mojo_set_add_bytes(MojoSet *s, MojoBytes *b)
{
    char *k = mojo_bytes_cstr_key(b);
    if (s->used * 2 >= s->cap) _set_grow(s);
    int64_t idx = _set_slot_str_tag(s, k, 2 /* bytes domain */);
    if (idx < 0) { _set_grow(s); idx = _set_slot_str_tag(s, k, 2); }
    if (s->slots[idx].tag == -1) {
        s->slots[idx].tag   = 2;
        s->slots[idx].val_s = k;
        s->slots[idx].seq   = s->next_seq++;
        s->used++;
    } else {
        free(k);
    }
}

int mojo_set_contains_bytes(MojoSet *s, MojoBytes *b)
{
    if (!s) return 0;
    char *k = mojo_bytes_cstr_key(b);
    int64_t idx = _set_slot_str_tag(s, k, 2 /* bytes domain */);
    free(k);
    return idx >= 0;
}

/* Re-materialize a tag-2 (bytes) slot as a real MojoBytes value. */
MojoBytes *mojo_set_val_bytes(MojoSet *s, int64_t idx)
{
    if (!s || idx < 0 || idx >= s->cap || s->slots[idx].tag != 2) return NULL;
    char *v = s->slots[idx].val_s;
    return mojo_bytes_from_cstr(v ? v : "");
}

/* Home slot (the index its own hash probes from, before any collision
 * displacement) for whatever's currently in `s->slots[idx]` — needed by
 * the backward-shift deletion below to decide whether a later slot may
 * be moved back to fill a hole without breaking its own probe chain. */
static int64_t _set_home_slot(MojoSet *s, int64_t idx)
{
    _SetSlot *sl = &s->slots[idx];
    if (sl->tag == 0) {
        uint64_t h = (uint64_t)sl->val_i * 2654435761ULL;
        h ^= h >> 32;
        return (int64_t)(h % (uint64_t)s->cap);
    }
    return (int64_t)(_str_hash(sl->val_s ? sl->val_s : "") % (uint64_t)s->cap);
}

/* Standard backward-shift deletion for open addressing with linear
 * probing (Knuth vol. 3, algorithm R): removing a slot outright (just
 * marking it empty) would break the probe chain for any later-inserted
 * entry that collided into a slot past it — a lookup for that entry would
 * stop at the now-empty slot before reaching it. Instead, walk forward
 * from the freed slot and pull back any entry whose home slot lies at or
 * before the hole (cyclically), repeating until a genuinely empty slot is
 * hit. Shared by both int- and str-tagged slots since the check only
 * needs each slot's own home position, not its value's type. */
static void _set_erase_slot(MojoSet *s, int64_t i)
{
    if (s->slots[i].tag == 1) free(s->slots[i].val_s);
    s->slots[i].tag = -1;
    s->slots[i].val_s = NULL;
    s->used--;
    int64_t j = i;
    for (;;) {
        j = (j + 1) % s->cap;
        if (s->slots[j].tag == -1) break;
        int64_t k = _set_home_slot(s, j);
        int movable = (i <= j) ? (k <= i || k > j) : (k <= i && k > j);
        if (movable) {
            s->slots[i] = s->slots[j];
            s->slots[j].tag = -1;
            s->slots[j].val_s = NULL;
            i = j;
        }
    }
}

void mojo_set_discard_int(MojoSet *s, int64_t v)
{
    if (!s) return;
    int64_t idx = _set_slot_int(s, v);
    if (idx < 0 || s->slots[idx].tag != 0) return;
    _set_erase_slot(s, idx);
}

void mojo_set_discard_str(MojoSet *s, char *v)
{
    if (!s) return;
    int64_t idx = _set_slot_str(s, v);
    if (idx < 0 || s->slots[idx].tag != 1) return;
    _set_erase_slot(s, idx);
}

/* ── int/str view equivalence ──────────────────────────────────────────
 * MojoList and MojoDict each store one value word per entry, so their
 * `_get_int` / `_get_str` accessors are just two VIEWS of the same
 * storage and agree by construction. MojoSet is the odd one out: it
 * keeps `val_i` and `val_s` in separate fields, so an entry added
 * through one view was invisible through the other.
 *
 * That asymmetry is not a theoretical concern — it is precisely the
 * failure the self-hosted compiler keeps hitting. When the codegen
 * cannot infer a `set[str]`'s element type it erases the element to
 * int64_t, so `s.add(x)` emits `mojo_set_add_int(s, <char* as int>)`
 * while `x in s` emits `mojo_set_contains_str(...)` (or the reverse, or
 * an int-view ITERATION over str slots). Each such mismatch silently
 * behaved as "not present" / "empty", and each has previously been
 * chased down and patched one at a time in the Python sources.
 *
 * Fix it once, here, by making the two views agree the way List and Dict
 * already do: a str slot's int view is its pointer, an int slot's str
 * view is that pointer when it plausibly is one, and each `contains`
 * falls back to the other kind's slots. The fallbacks are gated on the
 * per-kind counters so a single-kind set (the normal case) stays O(1).
 */

int mojo_set_contains_int(MojoSet *s, int64_t v)
{
    if (!s) return 0;
    int64_t idx = _set_slot_int(s, v);
    return idx >= 0 && s->slots[idx].tag == 0;
}

int mojo_set_contains_str(MojoSet *s, char *v)
{
    if (!s) return 0;
    int64_t idx = _set_slot_str(s, v);
    return idx >= 0 && s->slots[idx].tag == 1;
}

/* NOTE on the `contains` pair: unlike the iterator accessors below, these
 * are deliberately NOT made cross-view. An int slot holds a bare 64-bit
 * value with no way to tell a boxed `char *` from a genuine integer (a
 * type tag, an id(), a heap pointer to a NON-string object — all of which
 * this runtime really does store in int-keyed sets), so answering a
 * `contains_str` query by strcmp-ing against int slots reads unbounded
 * memory through a pointer that was never a string. Tried, and it
 * segfaulted two translation units that previously compiled. An
 * `add_int` / `contains_str` mismatch is a codegen element-type inference
 * gap and has to be fixed there, where the static type is known. */

void mojo_set_print(MojoSet *s)
{
    printf("{");
    int first = 1;
    for (int64_t i = 0; i < s->cap; i++) {
        _SetSlot *sl = &s->slots[i];
        if (sl->tag == -1) continue;
        if (!first) printf(", ");
        if (sl->tag == 0) printf("%lld", (long long)sl->val_i);
        else              printf("\"%s\"", sl->val_s);
        first = 0;
    }
    printf("}");
}

int64_t mojo_set_len(MojoSet *s) { return s ? s->used : 0; }

MojoSet *mojo_set_union(MojoSet *a, MojoSet *b) {
    MojoSet *out = mojo_set_new();
    if (!a && !b) return out;
    /* Copy BOTH int slots (tag 0) and string slots (tag 1) — the
     * string branch was missing, so `set_of_str_a | set_of_str_b`
     * silently returned an empty set (mojo_set_intersection /
     * mojo_set_difference already handle both). This broke every
     * `used |= _used_idents_node(...)` in the compiler's own closure
     * capture scan: capturing closures lost their whole env struct. */
    if (a) for (int64_t i = 0; i < a->cap; i++) {
        if (a->slots[i].tag == 0)
            mojo_set_add_int(out, a->slots[i].val_i);
        else if (a->slots[i].tag == 1)
            mojo_set_add_str(out, a->slots[i].val_s);
    }
    if (b) for (int64_t i = 0; i < b->cap; i++) {
        if (b->slots[i].tag == 0)
            mojo_set_add_int(out, b->slots[i].val_i);
        else if (b->slots[i].tag == 1)
            mojo_set_add_str(out, b->slots[i].val_s);
    }
    return out;
}

MojoSet *mojo_set_intersection(MojoSet *a, MojoSet *b) {
    MojoSet *out = mojo_set_new();
    if (!a || !b) return out;
    for (int64_t i = 0; i < a->cap; i++) {
        if (a->slots[i].tag == 0 && mojo_set_contains_int(b, a->slots[i].val_i))
            mojo_set_add_int(out, a->slots[i].val_i);
        else if (a->slots[i].tag == 1 && mojo_set_contains_str(b, a->slots[i].val_s))
            mojo_set_add_str(out, a->slots[i].val_s);
    }
    return out;
}

MojoSet *mojo_set_difference(MojoSet *a, MojoSet *b) {
    MojoSet *out = mojo_set_new();
    if (!a) return out;
    for (int64_t i = 0; i < a->cap; i++) {
        if (a->slots[i].tag == 0 && !mojo_set_contains_int(b, a->slots[i].val_i))
            mojo_set_add_int(out, a->slots[i].val_i);
        else if (a->slots[i].tag == 1 && !mojo_set_contains_str(b, a->slots[i].val_s))
            mojo_set_add_str(out, a->slots[i].val_s);
    }
    return out;
}

MojoSet *mojo_set_copy(MojoSet *s) {
    MojoSet *out = mojo_set_new();
    if (!s) return out;
    for (int64_t i = 0; i < s->cap; i++) {
        if (s->slots[i].tag == 0)
            mojo_set_add_int(out, s->slots[i].val_i);
        else if (s->slots[i].tag == 1)
            mojo_set_add_str(out, s->slots[i].val_s);
    }
    return out;
}

/* `dst |= src`, and the merge behind a multi-clause set comprehension
   (`{i + j for i in range(3) for j in range(3)}`, lowered as one
   `mojo_set_update` per outer element). Walks the SOURCE in INSERTION order
   (mojo_set_order_indices), not raw hash-slot order: the destination's own
   order is what a set's iteration and repr report, so a slot-order walk made
   the merged result's order depend on where the heap put the source's
   elements. `s |= other` is a merge in the source's order for the same
   reason. */
void mojo_set_update(MojoSet *dst, MojoSet *src) {
    if (!dst || !src) return;
    int64_t *order = mojo_set_order_indices(src);
    int64_t n = order ? src->used : 0;
    for (int64_t oi = 0; oi < n; oi++) {
        _SetSlot *s = &src->slots[order[oi]];
        if (s->tag == 0)
            mojo_set_add_int(dst, s->val_i);
        else if (s->tag == 1)
            mojo_set_add_str(dst, s->val_s);
    }
    free(order);
}

/* ── MojoSetIter ─────────────────────────────────────────────────────────*/

struct MojoSetIter {
    MojoSet *set;
    int64_t  pos;   /* current slot index */
};

/* Live slot indices in insertion order — the set analogue of
 * mojo_dict_order_indices, and it exists for the same reason: iteration
 * order must not depend on where the heap happened to put things. */
int64_t *mojo_set_order_indices(MojoSet *s)
{
    if (!s || s->used == 0) return NULL;
    /* Sized from the slot table, padded to `used` (the iterator's bound): see
     * mojo_dict_order_indices for why `used` alone cannot be trusted. */
    int64_t occ = 0;
    for (int64_t i = 0; i < s->cap; i++)
        if (s->slots[i].tag != -1) occ++;
    int64_t (*tmp)[2] = malloc(sizeof(int64_t) * 2 * (size_t)(occ ? occ : 1));
    int64_t n = 0;
    for (int64_t i = 0; i < s->cap; i++)
        if (s->slots[i].tag != -1) { tmp[n][0] = s->slots[i].seq; tmp[n][1] = i; n++; }
    qsort(tmp, (size_t)n, sizeof(int64_t) * 2, _cmp_seqidx);
    int64_t total = n > s->used ? n : s->used;
    int64_t *out = calloc((size_t)total, sizeof(int64_t));
    for (int64_t i = 0; i < n; i++) out[i] = tmp[i][1];
    free(tmp);
    return out;
}

MojoSetIter *mojo_set_iter_new(MojoSet *s)
{
    MojoSetIter *it = malloc(sizeof(MojoSetIter));
    it->set   = s;
    it->pos   = -1;
    it->n     = s ? s->used : 0;
    it->order = s ? mojo_set_order_indices(s) : NULL;
    return it;
}

int mojo_set_iter_next(MojoSetIter *it)
{
    it->pos++;
    return (it->order && it->pos < it->n) ? 1 : 0;
}

/* The backing slot index for the CURRENT position — what mojo_set_val_bytes
 * needs, since a bytes element lives in the tag-2 domain and has to be
 * re-materialized from its stored content copy. */
int64_t mojo_set_iter_pos(MojoSetIter *it)
{
    if (!it || it->pos < 0 || it->pos >= it->n || !it->order) return -1;
    return it->order[it->pos];
}

/* Both accessors follow the int/str view-equivalence rule documented at
 * mojo_set_contains_int: a str slot's int64_t view is its pointer, an int
 * slot's str view is that pointer when it plausibly is one. Returning the
 * raw (always-zero) sibling field instead made `for x in <str set>` — which
 * the codegen lowers through the INT view whenever it cannot infer the
 * element type — hand back 0 for every element, so e.g. gen_module_impl's
 * `_ptr_helpers_needed` scan produced an empty list and the
 * `static char * _mojo_at_char (...)` helper was never emitted while its
 * call sites were. */
int64_t mojo_set_iter_val_int(MojoSetIter *it)
{
    _SetSlot *sl = &it->set->slots[it->order[it->pos]];
    if (sl->tag == 1) return (int64_t)(uintptr_t)sl->val_s;
    return sl->val_i;
}

/* The str view of an INT slot is deliberately NOT the raw value cast to
 * `char *` — see the note above mojo_set_contains_int: an int slot may
 * legitimately hold a non-string (a type tag, an id(), a pointer to a
 * non-string object), and handing that to the caller as a string reads
 * unbounded memory. Only the int-view-of-a-str-slot direction above is
 * unambiguous, because there the pointer IS the value. */
char *mojo_set_iter_val_str(MojoSetIter *it)
{
    _SetSlot *sl = &it->set->slots[it->order[it->pos]];
    return sl->val_s ? sl->val_s : "";
}

void mojo_set_iter_free(MojoSetIter *it) { free(it->order); free(it); }

/* ── Python builtin functions for C types ──────────────────────────────────*/

/* `x in <container>` where the container reached codegen as a boxed
 * `int64_t` and so has no static type. Previously codegen emitted
 * `/* TODO: 'in' for int64_t *\/ t = 0;` — a hardcoded FALSE. That is not
 * a missing optimisation, it silently inverts program logic: every
 * membership test against a cross-module container global answered "no".
 * `name in gimple_ctypes._C_RESERVED_FUNCS` (read through the
 * int64_t-returning `gimple_ctypes__mojo_global_get__C_RESERVED_FUNCS`
 * accessor) was dead, so the compiler stopped recognising libc names and
 * emitted a `__attribute__((weak)) int64_t abs (...)` stub that collides
 * with <stdlib.h>'s own `abs` — one "conflicting types" error that then
 * cascaded into 631 more in mojo_compiler.py alone.
 *
 * The three container kinds are all discoverable at runtime through the
 * registries, so answer the question instead of guessing. Order is
 * dict, list, set; a value that is none of them is not a container and
 * the answer really is 0. */
int mojo_in_dispatch_str(int64_t container, char *needle)
{
    if (container == 0) return 0;
    if (mojo_is_registered_dict(container)) {
        /* The needle can be a CONTAINER even on this "str" view: `k in d`
         * where `k` is a tuple leaves the dict ambiguous but types the needle
         * as `char *`, because the codegen's only evidence about it is the
         * pointer type it was cast to. Keying that by its address is the
         * bug this fixes (see mojo_dict_key_for), so the content key is
         * needed on BOTH views — the view is chosen from the CONTAINER, and
         * this one is a dict either way. */
        if (mojo_is_registered_list((int64_t)(uintptr_t)needle)) {
            char *ck = mojo_dict_key_for((int64_t)(uintptr_t)needle);
            int hit = mojo_dict_contains((MojoDict *)(uintptr_t)container, ck);
            mojo_dict_key_free(ck);
            return hit;
        }
        return mojo_dict_contains((MojoDict *)(uintptr_t)container, needle);
    }
    if (mojo_is_registered_list(container))
        return mojo_list_contains_str((MojoList *)(uintptr_t)container, needle);
    if (mojo_is_registered_set(container))
        return mojo_set_contains_str((MojoSet *)(uintptr_t)container, needle);
    return 0;
}

/* The int view asks the same question with BOTH operands erased to
 * int64_t, so the NEEDLE is as untyped as the container and needs the same
 * treatment, and the dict branch is `mojo_dict_contains_kw` rather than
 * `mojo_dict_contains` because of it: on the int view the needle is not known
 * to be an integer at all. An erased key can be a boxed `char *` (a str
 * subscripted dict read through an int64_t accessor), and `_kw` is the existing
 * helper that decides between the two key domains from `mojo_boxed_is_str` --
 * the same discriminator `mojo_cstr_or_int_str` and every `_kw` dict entry
 * point already use, so no new notion of "which words are strings" enters the
 * runtime here, and `d[k]` and `k in d` agree on the same erased key instead of
 * one of them answering for a key the other cannot see. Casting the needle to
 * `char *` unconditionally (what this used to be written as the moment a dict
 * branch existed) makes an int-keyed dict compare its integer bits as if they
 * were a string.
 *
 * Without that treatment this function asked the INT predicates about a boxed
 * `char *`:
 *
 *   - a dict fell off the end entirely (there was no dict branch at all), so
 *     `x in d` answered False for every erased dict -- bugs/
 *     CODEGEN_in_dispatch_int_has_no_dict_branch.md;
 *   - a set of strings answered False too, for a different reason: its
 *     elements live in tag-1 string slots and `_set_slot_int` probes the
 *     int domain, which cannot hold a pointer-shaped key at all.
 *
 * Both were silent: exit 0, no diagnostic, and the "no" inverts whatever
 * branch of the program the membership test was guarding. A container that
 * is none of the three kinds really is not a container, so the trailing 0
 * is the honest answer and not a fallback.
 *
 * The list and set branches stay on their int view deliberately: there is no
 * `_kw` twin for either, and inventing one means strcmp-ing slots that hold
 * bare integers, which is the segfault the `contains` pair's own note in this
 * file records having been tried. That is an element-type inference gap in the
 * codegen, where the static type is known, not something to guess at here. */
int mojo_in_dispatch_int(int64_t container, int64_t needle)
{
    if (container == 0) return 0;
    if (mojo_boxed_is_str(needle))
        return mojo_in_dispatch_str(container, (char *)(intptr_t)needle);
    if (mojo_is_registered_dict(container))
        return mojo_dict_contains_kw((MojoDict *)(intptr_t)container, needle);
    if (mojo_is_registered_list(container))
        return mojo_list_contains_int((MojoList *)(intptr_t)container, needle);
    if (mojo_is_registered_set(container))
        return mojo_set_contains_int((MojoSet *)(intptr_t)container, needle);
    return 0;
}

/* ── `==` / `!=` between values: Python value equality ──────────────────────
 *
 * The compiled path used to lower every comparison between two containers to
 * a raw POINTER comparison, because that is what falls out of C. It is wrong
 * for every value, not just for the aliasing case: `{1,2} == {1,2}` built from
 * two literals is two allocations, so the answer was always False. The visible
 * damage is a `while new != old:` fixed point over containers that can never
 * terminate (and, with no GC, leaks a fresh set/list per round) — measured at
 * 43 GB on a two-line program, see
 * bugs/CODEGEN_container_eq_is_pointer_identity.md.
 *
 * The three `mojo_*_eq` functions below are the per-kind answer; `elem` is the
 * ELEMENT code the codegen knows statically for the container it built (the
 * codegen has no element type at all for an erased operand, and passes
 * MOJO_EQ_UNKNOWN, which asks the value's own per-slot kinds first). One code
 * per comparison, not one per kind: `a == b` with `a` erased to int64_t is the
 * shape the compiler's own source is full of, and it still needs the other
 * side's static element type to compare a list of strings by CONTENT.
 *
 * Every one of these is allocation-free — a comparison must not change what
 * the heap looks like, and this one runs inside fixed points. The MOJO_EQ_*
 * element codes live in fire_runtime.h, next to the declarations.
 */

/* One slot word pair, by element code. `ka`/`kb` are the per-slot kinds
 * (mojo_list_slot_kind's alphabet), consulted only for the side whose code is
 * MOJO_EQ_UNKNOWN. Returns 1 when the two slots hold equal values.
 *
 * The codes are PER SIDE because `[1.0] == [1]` is a legitimate program: the
 * codegen knows the left list is float and the right one int, and a single
 * code cannot say so. Exactly one side being DOUBLE is therefore a normal
 * case, not an error -- and the integer side has to be CONVERTED, not
 * reinterpreted, or its 64 one-bits become a denormal. Plain `return 0` on a
 * mismatch is what made `[1.0] == [1]` and `{"a": 1.0} == {"a": 1}` False.
 *
 * A pointer-typed word against a float is unequal by inspection rather than by
 * dereference, and the two pointer-typed arms below range-check both words
 * before reading them: the erased-operand path below can guess STR for a
 * container whose real elements are not strings (a type-confused program), and
 * a strcmp on a small integer is a segfault, not a wrong answer. */
static double _eq_as_double(int64_t w)
{
    double d;
    __builtin_memcpy(&d, &w, 8);
    return d;
}

static int _kind_to_eq(char k)
{
    if (k == 'd') return MOJO_EQ_DOUBLE;
    if (k == 'p') return MOJO_EQ_STR;
    if (k == 's') return MOJO_EQ_BYTES;
    if (k == 'l') return MOJO_EQ_GENERIC;
    return MOJO_EQ_INT;                    /* 'i' and 'n' (None) */
}

/* The Python type name an MOJO_EQ_* code stands for, for the TypeError text
 * an unordered comparison raises. Derived from the SAME table `_kind_to_eq`
 * reads, so a new element code cannot produce a message naming a type this
 * runtime does not have. MOJO_EQ_UNKNOWN is an int as far as the caller knows
 * (nothing better was available), which is the right answer for the erased
 * operand in `an_erased_handle < ["a"]`. */
static const char *_eq_typename(int code)
{
    if (code == MOJO_EQ_DOUBLE) return "float";
    if (code == MOJO_EQ_STR) return "str";
    if (code == MOJO_EQ_BYTES) return "bytes";
    return "int";                          /* INT, GENERIC and UNKNOWN */
}

static int _slot_eq(int64_t x, int64_t y, int ea, int eb, char ka, char kb)
{
    /* `None` against a NUMBER, before the codes are resolved: `_kind_to_eq`
     * below folds 'n' into MOJO_EQ_INT (they are the same int64_t at the C
     * level, and a `None == 0` test is a real thing to answer), which is right
     * for ordering's purposes and wrong for equality's. `[None] == [0]` is
     * CPython's False and this answered True, because both slots are the word
     * 0 and `x == y` below cannot tell them apart. The per-slot kind is the
     * only evidence that can, which is why the codegen records it for a
     * homogeneous `[None]` too (see `_lower_list_literal`). One 'n' against a
     * number is unequal; TWO 'n's are the same value, and `x == y` still
     * answers that. */
    if ((ka == 'n') != (kb == 'n')) return 0;
    if (ea == MOJO_EQ_UNKNOWN) ea = _kind_to_eq(ka);
    if (eb == MOJO_EQ_UNKNOWN) eb = _kind_to_eq(kb);
    if ((ea == MOJO_EQ_DOUBLE) != (eb == MOJO_EQ_DOUBLE)) {
        if (ea == MOJO_EQ_INT)   return (double)x == _eq_as_double(y);
        if (eb == MOJO_EQ_INT)   return _eq_as_double(x) == (double)y;
        return 0;                  /* a pointer is equal to no float */
    }
    if (ea != eb) return 0;
    switch (ea) {
    case MOJO_EQ_INT:
        /* An int64_t slot the codegen could not TYPE can still be holding a
         * container: a dict literal whose value is a list is stored through
         * mojo_dict_set_int with no value-type record behind it, and that is
         * why `{"k": [1, 2]} == {"k": [1, 2]}` answered False. The registries
         * are this runtime's own answer to "what is this word", so ask them
         * before concluding unequal — mojo_value_eq is that answer, and it
         * returns 0 for two words that are not the same container kind. A
         * plain integer is never a registered container address, so the probe
         * cannot turn an unequal pair into an equal one. */
        if (x == y) return 1;
        return mojo_value_eq(x, y, MOJO_EQ_UNKNOWN);
    case MOJO_EQ_DOUBLE:  return _eq_as_double(x) == _eq_as_double(y);
    case MOJO_EQ_STR:
        return (_mojo_ptr_shaped(x) && _mojo_ptr_shaped(y)
                && strcmp((char *)(intptr_t)x, (char *)(intptr_t)y) == 0);
    case MOJO_EQ_BYTES:
        return (_mojo_ptr_shaped(x) && _mojo_ptr_shaped(y)
                && mojo_bytes_eq((MojoBytes *)(intptr_t)x,
                                 (MojoBytes *)(intptr_t)y));
    default:               /* MOJO_EQ_GENERIC: a nested container */
        return mojo_value_eq(x, y, MOJO_EQ_UNKNOWN);
    }
}

int mojo_list_eq(MojoList *a, MojoList *b, int ea, int eb)
{
    if (a == b) return 1;                    /* the same storage: equal */
    if (!a || !b) return 0;
    /* A tuple and a list are both MojoList at the C level and Python says
     * they are never equal, so the marker decides (see mojo_mark_as_tuple). */
    if (mojo_is_tuple(a) != mojo_is_tuple(b)) return 0;
    if (a->len != b->len) return 0;
    for (int64_t i = 0; i < a->len; i++) {
        if (!_slot_eq(a->data[i], b->data[i], ea, eb,
                      mojo_list_slot_kind(a, i), mojo_list_slot_kind(b, i)))
            return 0;
    }
    return 1;
}

/* A dict is order-INSENSITIVE: same entries, any insertion order. Keys are
 * compared with the same strcmp the table itself probes with (_dict_find_k),
 * so "the same key" means here exactly what it means to every other lookup —
 * including the integer-key domain, where `key` still holds the decimal text
 * and `ikey` the integer. */
int mojo_dict_eq(MojoDict *a, MojoDict *b, int va, int vb)
{
    if (a == b) return 1;
    if (!a || !b) return 0;
    if (a->used != b->used) return 0;
    for (int64_t i = 0; i < a->cap; i++) {
        _DictSlot *sa = &a->slots[i];
        if (!sa->key) continue;
        _DictSlot *sb = _dict_find_k(b, sa->key, sa->keykind);
        if (!sb || !sb->key) return 0;               /* key absent from b */
        /* The value is an untagged word: the codegen's static value type when
         * it has one, else this slot's own `kind` tag. */
        if (va == MOJO_EQ_UNKNOWN)
            va = (sa->kind == 1) ? MOJO_EQ_DOUBLE
              : (sa->kind == 2) ? MOJO_EQ_STR
              : MOJO_EQ_INT;
        if (vb == MOJO_EQ_UNKNOWN)
            vb = (sb->kind == 1) ? MOJO_EQ_DOUBLE
              : (sb->kind == 2) ? MOJO_EQ_STR
              : MOJO_EQ_INT;
        if (!_slot_eq(sa->val, sb->val, va, vb, 'i', 'i')) return 0;
    }
    return 1;
}

/* Does `s` hold this int-tagged entry, comparing as FLOATS? A set of floats
 * stores the IEEE-754 bits in an int slot, so `mojo_set_contains_int` would
 * look for the exact bits and miss `{1.0}` against `{1}` (which Python calls
 * equal). Sets are small and this arm only runs when the two sides' element
 * codes disagree about float-ness, so a linear scan is the right trade. */
static int _set_has_double(MojoSet *s, double want)
{
    for (int64_t i = 0; i < s->cap; i++) {
        if (s->slots[i].tag != 0) continue;
        if (_eq_as_double(s->slots[i].val_i) == want) return 1;
    }
    return 0;
}

/* Does `b` hold `a`'s i-th entry? ONE reading of a set slot, shared by
 * mojo_set_eq (membership in both directions) and the subset test
 * mojo_set_cmp needs — the two differ only in what they conclude from the
 * answer, and keeping the slot-kind dispatch in one place is what stops them
 * drifting on the `mixed` float case, where a set of floats stores its bits
 * in an int slot. */
static int _set_has_slot(MojoSet *b, MojoSet *a, int64_t i, int mixed)
{
    _SetSlot *sl = &a->slots[i];
    if (sl->tag == 1)
        return mojo_set_contains_str(b, sl->val_s);
    if (sl->tag == 2)
        return mojo_set_contains_bytes(b, (MojoBytes *)(intptr_t)sl->val_s);
    if (mixed)
        return _set_has_double(b, _eq_as_double(sl->val_i));
    return mojo_set_contains_int(b, sl->val_i);
}

int mojo_set_eq(MojoSet *a, MojoSet *b, int ea, int eb)
{
    if (a == b) return 1;
    if (!a || !b) return 0;
    if (a->used != b->used) return 0;
    int mixed = ((ea == MOJO_EQ_DOUBLE) != (eb == MOJO_EQ_DOUBLE));
    for (int64_t i = 0; i < a->cap; i++) {
        if (a->slots[i].tag < 0) continue;          /* empty slot */
        if (!_set_has_slot(b, a, i, mixed)) return 0;
    }
    return 1;
}

/* The kind of an ambiguous (boxed int64_t) value, from the same registries
 * mojo_in_dispatch_* above use. Only the three container kinds are
 * distinguishable: a `char *` string has no header of its own, and every
 * other value in this model is a bare word. */
#define MOJO_VK_NONE 0
#define MOJO_VK_LIST 1
#define MOJO_VK_DICT 2
#define MOJO_VK_SET  3

static int _value_kind(int64_t v)
{
    if (mojo_is_registered_dict(v)) return MOJO_VK_DICT;
    if (mojo_is_registered_list(v)) return MOJO_VK_LIST;
    if (mojo_is_registered_set(v))  return MOJO_VK_SET;
    return MOJO_VK_NONE;
}

/* `a == b` for two values whose static types the codegen could not both
 * resolve — the shape the compiler's own source is written in, where a
 * container handed to an unannotated parameter arrives as a bare int64_t.
 *
 * The word comparison first is not an optimization but the whole answer for
 * every pair that is not two containers of the same kind: it is CPython's
 * identity, and a registry address is never a small int or a bool, so
 * "equal words" can only mean equal values. Anything else falls out of the
 * kind pair, and only the same-kind pairs are ever equal. */
int mojo_value_eq(int64_t a, int64_t b, int elem)
{
    if (a == b) return 1;
    int ka = _value_kind(a), kb = _value_kind(b);
    if (ka != kb || ka == MOJO_VK_NONE) return 0;
    /* `elem` is the element code of the side the CODEGEN knew. The erased side
     * gets the same code: it has no static type by definition, and in the
     * shape that reaches here (`an_erased_handle == ["a", "b"]`) it really does
     * hold the same elements. When that guess is wrong the answer is unequal —
     * what the pointer comparison this replaced said too — and the STR/BYTES
     * arms of _slot_eq range-check before dereferencing, so a wrong guess
     * cannot be a crash. */
    if (ka == MOJO_VK_LIST) return mojo_list_eq((MojoList *)(intptr_t)a,
                                               (MojoList *)(intptr_t)b,
                                               elem, elem);
    if (ka == MOJO_VK_DICT) return mojo_dict_eq((MojoDict *)(intptr_t)a,
                                               (MojoDict *)(intptr_t)b,
                                               elem, elem);
    return mojo_set_eq((MojoSet *)(intptr_t)a, (MojoSet *)(intptr_t)b,
                       elem, elem);
}

/* A SECOND implementation of this same fix was written independently on
 * another branch: `MOJO_ORD_INCOMPARABLE`, `mojo_value_order`,
 * `mojo_list_order` / `mojo_set_order` / `mojo_dict_order` /
 * `mojo_value_order_op`, and a `mojo_list_cmp(a, b, ea, eb)` that took NO
 * operator. It is not here, and the reason is worth writing down rather than
 * leaving to the next reader who finds those names in a branch:
 *
 *   - ONE comparison, folded at the call site. The `*_order` family is a
 *     per-operator entry point, which is the shape the `==` family already had
 *     before it was consolidated into `mojo_*_eq`; re-introducing it for the
 *     four ordering operators would put two spellings of the same three-way
 *     comparison back in the file. `mojo_cmp_fold` is the fold.
 *   - `op` is threaded down rather than handed to a per-operator wrapper,
 *     because the TypeError text must name the operator the SOURCE wrote and a
 *     nested container (`[[1]] < [['a']]`) must keep naming the OUTERMOST one.
 *     With a per-operator wrapper that becomes the wrapper's problem at every
 *     level of the recursion.
 *   - `mojo_dict_order` (always raises) is redundant with the codegen's
 *     compile-time `_ord_pair_is_refused`, and on the erased route -- the only
 *     route it would still be reachable from -- the registry cannot say "dict"
 *     at all, so `mojo_value_cmp` refuses on the same MOJO_CMP_UNORDERABLE.
 *
 * Its one thing this block did NOT have is folded in below: the explicit
 * `ka == 'n' || kb == 'n'` refusal. `None` shares MOJO_EQ_INT with the integers
 * here, so the per-slot kind is the only thing that can say "None is in no
 * order with anything, itself included" -- `[None] < [None]` is a TypeError on
 * CPython, and without this check the word 0 is compared against the word 0 and
 * answers "equal", which for `<=` is False where CPython raises.
 */
/* ── `<` / `<=` / `>` / `>=` between containers: Python's ordering ────────
 *
 * The same lowering question `==` was, one level up: `a < b` between two
 * containers used to fall out of C as the same raw POINTER comparison `==`
 * used to, so the answer was decided by heap addresses — a stable, plausible
 * and wrong answer, exit 0, no diagnostic. Unlike `==` this is answerable
 * rather than a refusal: CPython implements ordering for lists (lexicographic,
 * a shorter prefix ordering FIRST) and for sets (proper subset), and this
 * project's CPython is the oracle the tests diff against.
 *
 * A dict is the one container kind with NO ordering — `{'a':1} < {'b':2}` is
 * a genuine TypeError even on 3.14 — so the dict arm raises rather than
 * inventing an answer, which is also what a pair of DIFFERENT kinds and a
 * container against a non-container must do.
 *
 * The element comparison is `_slot_cmp`, the three-way sibling of `_slot_eq`
 * above, and it reads the same evidence: a per-side MOJO_EQ_* code from the
 * codegen, falling back to the value's own per-slot kinds. Allocation-free,
 * for `_slot_eq`'s reason — this runs inside fixed points.
 */

/* The one place "these have no ordering" becomes a Python-level exception, so
 * every producer refuses identically instead of each spelling it. CPython's
 * text for `[1] < ['a']` is "'<' not supported between instances of 'int' and
 * 'str'"; the element type names are what the element codes carry, so this
 * spells them from the same MOJO_EQ_* table `_kind_to_eq` reads rather than
 * from a second list.
 *
 * `op` is the operator SPELLING the program used, not the internal code, so the
 * message says `'<= not supported…'` for `<=` rather than always saying `'<'`:
 * CPython names the operator the user wrote, and a diagnostic that misreports
 * which one failed is worse than none. */
/* The kind byte, when it is more specific than the MOJO_EQ_* code, wins the
 * type name — and `None` is the case that makes this necessary rather than
 * tidy. `_kind_to_eq` folds `'n'` into MOJO_EQ_INT because a `None` slot IS
 * the word 0 at the C level, which is the right answer for deciding the
 * comparison. It is the wrong answer for NAMING it: `[1] < [None]` raised
 * "'<' not supported between instances of 'int' and 'int'", while CPython
 * names `'NoneType'`, so the message blamed the wrong operand for a refusal
 * that was correct. `_slot_cmp`'s `ka == 'n' || kb == 'n'` arm is what
 * decided to refuse, so the kind is the same evidence that did the deciding
 * and the two must not disagree about what was refused.
 *
 * Only `'n'` overrides. Every other kind is faithfully represented by its
 * code, and a `'?'` / unknown kind means there was no per-slot evidence at
 * all, which is what MOJO_EQ_UNKNOWN already says. */
static const char *_cmp_side_typename(int code, char kind)
{
    if (kind == 'n') return "NoneType";
    return _eq_typename(code);
}

static void _raise_unorderable_ea_kinds(int ea, int eb, char ka, char kb,
                                        const char *op)
{
    char detail[128];
    snprintf(detail, sizeof detail,
             "'%s' not supported between instances of '%s' and '%s'",
             op, _cmp_side_typename(ea, ka), _cmp_side_typename(eb, kb));
    mojo_raise_type_error(detail);
}

static void _raise_unorderable_ea(int ea, int eb, const char *op)
{
    _raise_unorderable_ea_kinds(ea, eb, 0, 0, op);
}

/* The list/tuple half: a tuple and a list are the same C type with a marker to
 * tell them apart, and CPython's message names which one each side was — it
 * has the real Python types, this backend only has the markers. Same helper,
 * the two type names passed in, so there is one place that builds this text. */
static void _raise_unorderable(const char *ta, const char *tb, const char *op)
{
    char detail[128];
    snprintf(detail, sizeof detail,
             "'%s' not supported between instances of '%s' and '%s'",
             op, ta, tb);
    mojo_raise_type_error(detail);
}

/* Which operator is being evaluated, as the string the exception message needs.
 * Threaded down from the codegen (which knows the operator the source spelled)
 * rather than derived here, so the recursion through nested containers
 * (`[[1]] < [['a']]`) keeps naming the OUTERMOST operator — which is the one
 * CPython reports, and the only one the user wrote. */
static const char *_cmp_op_name(int op)
{
    switch (op) {
    case MOJO_CMP_OP_LE: return "<=";
    case MOJO_CMP_OP_GT: return ">";
    case MOJO_CMP_OP_GE: return ">=";
    default:             return "<";
    }
}

/* NaN is unordered against everything INCLUDING itself, which is not the same
 * as equal: `[nan] <= [nan]` is False in Python while `nan == nan` is also
 * False, so folding NaN into either verdict gets one of the two wrong. */
static int _cmp_double(double x, double y)
{
    if (x < y) return -1;
    if (x > y) return 1;
    if (x == y) return 0;
    return MOJO_CMP_UNORDERABLE;
}

/* One slot word pair, three-way: <0, 0, >0, or MOJO_CMP_UNORDERABLE.
 *
 * UNORDERABLE rather than a plain 0 because 0 means EQUAL, and the two
 * collapse into each other at the call site if this returns "equal" for a
 * pair Python refuses: `[1] < ['a']` must raise, not answer False, and
 * `mojo_list_cmp` has to be able to tell "these differ" from "these cannot
 * be compared". Every arm that dereferences ranges-checks its words first,
 * for `_slot_eq`'s reason — the erased-operand path can guess STR for a
 * container whose elements are not strings, and a strcmp on a small integer
 * is a segfault, not a wrong answer. */
static int _slot_cmp(int64_t x, int64_t y, int ea, int eb, char ka, char kb,
                     int op)
{
    if (ea == MOJO_EQ_UNKNOWN) ea = _kind_to_eq(ka);
    if (eb == MOJO_EQ_UNKNOWN) eb = _kind_to_eq(kb);
    /* `None` is in NO order with anything, itself included: CPython raises for
     * `[None] < [None]`. It shares MOJO_EQ_INT with the integers here (as it
     * does in `_slot_eq`), so the per-slot KIND is the only thing that can say
     * so, and that is what this test reads. Without it the two 0 words compare
     * equal, which for `<=` answers False where CPython raises -- a refusal
     * turned into a verdict, and the quietest possible version of it. */
    if (ka == 'n' || kb == 'n') return MOJO_CMP_UNORDERABLE;
    /* Exactly one side DOUBLE: a genuine int/float pair compares NUMERICALLY
     * ([1] < [1.5] is True), so the integer word is CONVERTED rather than
     * reinterpreted -- `_eq_as_double`, the same helper `_slot_eq` uses, for
     * the same reason. A pointer-typed side against a float is not a numeric
     * comparison at all and is unordered. */
    if ((ea == MOJO_EQ_DOUBLE) != (eb == MOJO_EQ_DOUBLE)) {
        if (ea == MOJO_EQ_INT)  return _cmp_double((double)x, _eq_as_double(y));
        if (eb == MOJO_EQ_INT)  return _cmp_double(_eq_as_double(x), (double)y);
        return MOJO_CMP_UNORDERABLE;
    }
    /* Two DIFFERENT non-numeric codes have no ordering between them, and this
     * is the arm `==` gets for free (`if (ea != eb) return 0`) while ordering
     * does not: `[1] < ['a']` is a TypeError, and falling through to the INT
     * arm below because the LEFT side is an int would compare the integer 1
     * against the string's ADDRESS and answer True — a refusal turned into a
     * verdict. Only two float-ish codes ever legitimately differ, and the arm
     * above has already handled those. */
    if (ea != eb) return MOJO_CMP_UNORDERABLE;
    /* Equal int codes: the word is either a number or, when the codegen could
     * not type it, a nested container handle (`[[1]] < [[2]]` recurses). */
    if (ea == MOJO_EQ_INT) {
        if (x == y) return 0;
        int nk = _value_kind(x), nl = _value_kind(y);
        if (nk != MOJO_VK_NONE || nl != MOJO_VK_NONE)
            return mojo_value_cmp(x, y, MOJO_EQ_UNKNOWN, op);
        return x < y ? -1 : 1;
    }
    if (ea == MOJO_EQ_DOUBLE) return _cmp_double(_eq_as_double(x), _eq_as_double(y));
    if (ea == MOJO_EQ_STR) {
        if (!_mojo_ptr_shaped(x) || !_mojo_ptr_shaped(y))
            return MOJO_CMP_UNORDERABLE;
        char *sx = (char *)(intptr_t)x, *sy = (char *)(intptr_t)y;
        if (!sx || !sy) return MOJO_CMP_UNORDERABLE;   /* a NULL slot is None */
        int r = strcmp(sx, sy);
        return r < 0 ? -1 : (r > 0 ? 1 : 0);
    }
    if (ea == MOJO_EQ_BYTES) {
        if (!_mojo_ptr_shaped(x) || !_mojo_ptr_shaped(y))
            return MOJO_CMP_UNORDERABLE;
        return mojo_bytes_cmp((MojoBytes *)(intptr_t)x,
                              (MojoBytes *)(intptr_t)y);
    }
    /* MOJO_EQ_GENERIC: a nested container, ordered by the same rules at the
     * next level down. */
    return mojo_value_cmp(x, y, MOJO_EQ_UNKNOWN, op);
}

/* CPython's list rule: lexicographic on the elements, and a SHORTER prefix
 * orders first (`[1] < [1, 2]`). A tuple and a list are the same C type, so
 * the marker decides — and when the markers DISAGREE there is no ordering at
 * all (`[1] < (1,)` is a TypeError), which is UNORDERABLE rather than an
 * invented answer. */
int mojo_list_cmp(MojoList *a, MojoList *b, int ea, int eb, int op)
{
    if (!a || !b) return MOJO_CMP_UNORDERABLE;
    if (mojo_is_tuple(a) != mojo_is_tuple(b)) {
        _raise_unorderable(mojo_is_tuple(a) ? "tuple" : "list",
                           mojo_is_tuple(b) ? "tuple" : "list",
                           _cmp_op_name(op));
        return MOJO_CMP_UNORDERABLE;
    }
    int64_t n = a->len < b->len ? a->len : b->len;
    for (int64_t i = 0; i < n; i++) {
        int c = _slot_cmp(a->data[i], b->data[i], ea, eb,
                          mojo_list_slot_kind(a, i), mojo_list_slot_kind(b, i),
                          op);
        if (c == MOJO_CMP_UNORDERABLE) {
            int ca = ea, cb = eb;
            char ska = mojo_list_slot_kind(a, i), skb = mojo_list_slot_kind(b, i);
            if (ca == MOJO_EQ_UNKNOWN) ca = _kind_to_eq(ska);
            if (cb == MOJO_EQ_UNKNOWN) cb = _kind_to_eq(skb);
            _raise_unorderable_ea_kinds(ca, cb, ska, skb, _cmp_op_name(op));
            return MOJO_CMP_UNORDERABLE;
        }
        if (c != 0) return c;
    }
    if (a->len == b->len) return 0;
    return a->len < b->len ? -1 : 1;
}

/* CPython's set rule, which is NOT the list rule: `s1 < s2` is "s1 is a
 * PROPER SUBSET of s2", not a lexicographic order — `{1,2} < {1,3}` is False,
 * and so is `{1,2} < {2,3}`. So the three-way answer is derived from
 * SUBSETNESS, in both directions, and a pair that is neither (the `{1,2}` /
 * `{1,3}` case) is UNORDERABLE in both directions — which is exactly what
 * CPython says, since all four of `<`, `<=`, `>`, `>=` are False for it.
 *
 * `mojo_set_difference`'s emptiness shortcut is NOT the test: it answers
 * "does s1 have something s2 lacks", which is what `s1 - s2` means, and it
 * says nothing about the other direction — `s1 > s2` is False for two
 * equal-size proper subsets of each other, which is the case that failed.
 * `_set_has_slot` (beside mojo_set_eq) is the per-slot read this and
 * mojo_set_eq share. */

/* Is every entry of `a` also in `b`? */
static int _set_subset(MojoSet *a, MojoSet *b, int mixed)
{
    if (!a || !b) return 0;
    if (a == b) return 1;
    if (a->used > b->used) return 0;
    for (int64_t i = 0; i < a->cap; i++) {
        if (a->slots[i].tag < 0) continue;          /* empty slot */
        if (!_set_has_slot(b, a, i, mixed)) return 0;
    }
    return 1;
}

int mojo_set_cmp(MojoSet *a, MojoSet *b, int ea, int eb, int op)
{
    if (!a || !b) return MOJO_CMP_UNORDERABLE;
    int mixed = ((ea == MOJO_EQ_DOUBLE) != (eb == MOJO_EQ_DOUBLE));
    int ab = _set_subset(a, b, mixed);       /* a proper-or-not subset of b */
    int ba = _set_subset(b, a, mixed);
    if (ab && ba) {
        /* Both subset tests pass, so the two hold the same elements -- a set
         * cannot be a proper subset of itself, whatever `used` says. */
        return 0;
    }
    if (ab) return -1;
    if (ba) return 1;
    /* Neither is a subset of the other: CPython answers False for all four of
     * `<`, `<=`, `>`, `>=` here and does NOT raise, because a set ordering
     * test is a subset question and "no" is a real answer to it. That is why
     * this one is UNORDERABLE-without-a-raise while mojo_list_cmp's is not:
     * MOJO_CMP_UNORDERABLE is the value the fold reads, not a synonym for
     * "TypeError", and only the producers that CPython actually refuses call
     * _raise_unorderable. */
    return MOJO_CMP_UNORDERABLE;
}

/* `a OP b` for two operands whose static types the codegen could not BOTH
 * resolve — the erased-handle shape, the twin of mojo_value_eq. The kind
 * pair decides everything, exactly as it does there: only same-kind operands
 * have an ordering, and a dict has none, so this raises. That raise is
 * CPython's own answer for every pair that reaches it, which is why a wrong
 * guess about an erased operand's kind is a loud failure rather than a wrong
 * verdict. */
int mojo_value_cmp(int64_t a, int64_t b, int elem, int op)
{
    if (a == b) return 0;
    int ka = _value_kind(a), kb = _value_kind(b);
    if (ka != kb || ka == MOJO_VK_NONE) {
        _raise_unorderable_ea(MOJO_EQ_UNKNOWN, MOJO_EQ_UNKNOWN,
                              _cmp_op_name(op));
        return MOJO_CMP_UNORDERABLE;
    }
    if (ka == MOJO_VK_LIST)
        return mojo_list_cmp((MojoList *)(intptr_t)a,
                             (MojoList *)(intptr_t)b, elem, elem, op);
    if (ka == MOJO_VK_SET)
        return mojo_set_cmp((MojoSet *)(intptr_t)a,
                            (MojoSet *)(intptr_t)b, elem, elem, op);
    _raise_unorderable("dict", "dict", _cmp_op_name(op));
    return MOJO_CMP_UNORDERABLE;
}

/* Fold a three-way answer to the `_Bool` the operator wants.
 *
 * MOJO_CMP_UNORDERABLE is refused explicitly rather than left to fall out of
 * `c < 0` / `c > 0`, because 2 satisfies BOTH of those: `[1] < ['a']` would
 * answer False from `c < 0` and True from `c > 0` off one and the same
 * unordered answer. It has already raised by the time it gets here -- both
 * `mojo_*_cmp` raise where they produce it -- so this is the never-taken
 * branch, and it is the False that a program which somehow got here would get
 * rather than a second wrong answer. */
int mojo_cmp_fold(int c, int op)
{
    if (c == MOJO_CMP_UNORDERABLE) return 0;
    switch (op) {
    case MOJO_CMP_OP_LT: return c < 0;
    case MOJO_CMP_OP_LE: return c <= 0;
    case MOJO_CMP_OP_GT: return c > 0;
    default:             return c >= 0;      /* MOJO_CMP_OP_GE */
    }
}

int mojo_isinstance(int64_t obj, int type_id) {
    /* type_id: 1 bool, 2 int, 3 float, 4 str, 5 list, 6 dict, 7 set
     * (see _TYPE_IDS in gimple_gen_calls.py). bool/int/float are raw
     * unboxed values with no runtime marker -- still unanswerable, stay 0.
     * list/dict CAN be answered: the runtime keeps a registry of every
     * MojoList / MojoDict it allocates (mojo_is_registered_list/_dict).
     * This is what makes `isinstance(node, list)` in the compiler's own
     * generic AST walkers (_walk_ast_into, _rewrite_node, ...) actually
     * work when self-hosted, instead of silently never recursing.
     *
     * `obj` MUST be int64_t. It used to be `int`, which truncated every
     * argument to 32 bits before the registry lookup. That was survivable
     * only while the process heap stayed under 4 GB; self-hosting a real
     * file pushes allocations well past it (observed handles around
     * 0xA_8EDC_E140 ~= 45 GB), and from that point `isinstance(x, list)`
     * answered NO for every genuine list. `_walk_ast_into` then treated
     * the statement LIST it was handed as an opaque leaf, appended it,
     * and recursed into nothing — so every generic AST scan built on it
     * (`_collect_self_assigns`, `_collect_self_reads`, ...) saw exactly
     * one node and found nothing. Downstream, every class whose fields
     * come only from `__init__` assignments emitted as an empty
     * `typedef struct X { int _dummy; }` stub.
     *
     * The full-width `mojo_isinstance_p` below already existed for the
     * pointer-typed call sites; widening this one fixes the boxed
     * (`int64_t`-typed) call sites, which are the overwhelming majority
     * (190 of 191 in the compiler's own generated output) — and does so
     * for already-generated .ci files too, since they take this
     * prototype from the header rather than declaring it themselves. */
    if (type_id == 5 || type_id == 7)  /* list / tuple-as-list */
        return mojo_is_registered_list(obj);
    if (type_id == 6)
        return mojo_is_registered_dict(obj);
    if (type_id == 8) {  /* tuple: a registered MojoList carrying the tuple marker */
        if (!mojo_is_registered_list(obj)) return 0;
        return mojo_is_tuple((MojoList *)(intptr_t)obj);
    }
    return 0;
}

int mojo_isinstance_p(int64_t obj, int type_id) {
    /* Full-width sibling of mojo_isinstance -- no pointer truncation. */
    if (type_id == 5 || type_id == 7)
        return mojo_is_registered_list(obj);
    if (type_id == 6)
        return mojo_is_registered_dict(obj);
    if (type_id == 8) {  /* tuple: a registered MojoList carrying the tuple marker */
        if (!mojo_is_registered_list(obj)) return 0;
        return mojo_is_tuple((MojoList *)(intptr_t)obj);
    }
    return 0;
}

/* Every codegen-emitted struct typedef (see gimple_codegen.py's struct-typedef
 * emission) carries an `int64_t __mojo_type_id;` as its FIRST field, set once
 * at allocation time (_alloc_<StructName>, the sole struct-construction choke
 * point). Because it's the first field, its address equals the struct's own
 * address (no padding precedes the first member in C), so reading it back
 * needs no struct-specific knowledge — just a plain int64_t* dereference.
 * isinstance(x, StructName) compares this tag against StructName's own
 * deterministic hash (_struct_type_id in gimple_codegen.py — computed
 * independently at both the allocation site and the isinstance call site, no
 * shared registry needed). Real bug this fixes: mojo_isinstance() above was a
 * hardcoded-false stub for EVERY non-scalar type, so isinstance(node, SomeASTType)
 * always took the "not this type" branch — found via find_imports() (used by
 * `mojo --dump`'s own do_imports resolution) never recognizing any import
 * statement inside a nested function/if/try block once self-hosted. */
/* Can `addr` be the address of a codegen-emitted struct (i.e. is it safe
 * to read an `int64_t __mojo_type_id` from it)? _mojo_ptr_shaped (defined
 * near the top of this file, where mojo_boxed_is_str's own docstring
 * explains why it is the shared half) answers "is this a real pointer at
 * all"; this predicate adds the two further requirements that are
 * specifically about reading an 8-BYTE TYPE TAG and are therefore NOT
 * imposed on the plain char* string readers:
 *
 *   - 8-byte aligned: `__mojo_type_id` is an int64_t at offset 0, and
 *     every allocator this runtime uses returns 16-byte-aligned blocks,
 *     so a misaligned value is definitionally not a struct pointer (this is
 *     also what let `_scan_yield_bearing`'s walk into the unaligned
 *     0x00007fffffffffff sentinel segfault before the range ceiling in
 *     _mojo_ptr_shaped existed);
 *   - a live allocation of at least 8 bytes (see the ASan-confirmed
 *     heap-buffer-overflow below).
 *
 * Both requirements are what a C string LITERAL fails and a struct pointer
 * never does, which is exactly why mojo_boxed_is_str must not call this. */
static int _mojo_tagged_addr_ok(int64_t addr)
{
    uint64_t u = (uint64_t)addr;
    if (!_mojo_ptr_shaped(addr)) return 0;
    if (u & 7ULL) return 0;
#if MOJO_HAVE_MALLOC_USABLE_SIZE
    /* The range/alignment checks above only rule out small-int/None/
     * struct-type-tag values — they do NOT guarantee `addr` points at an
     * allocation big enough to hold the 8-byte tag read below. A real,
     * ASan-confirmed heap-buffer-overflow: a generic dataclass-field
     * walker (e.g. fire_compiler.py's `_scan_yield_bearing`, called with
     * an unannotated/erased `node` parameter) recurses into every field
     * of an AST node, including plain `str`/`int` scalar fields, not
     * just child nodes — a short `char *` string (as little as 1 byte,
     * heap-allocated via `mojo_regex_substr`/`strdup`) is a perfectly
     * valid, 8-byte-aligned heap pointer that PASSES the checks above,
     * so `isinstance(<that string>, SomeStruct)` read 3+ bytes past its
     * allocation. `malloc_size`/`malloc_usable_size` answers "how big is
     * the allocation actually holding this pointer" in O(1) (no scan),
     * so reject anything too small for a genuine tagged-struct header
     * instead of trusting range/alignment alone. */
    if (MOJO_MALLOC_USABLE_SIZE((void *)(intptr_t)addr) < sizeof(int64_t)) return 0;
#endif
    return 1;
}

int64_t mojo_read_type_tag(int64_t addr) {
    /* Was: `if (!addr) return 0; return *(int64_t*)addr;` — but once the
     * compiler's own generic AST walkers actually recurse (mojo_isinstance
     * for containers now works), `isinstance(<leaf>, SomeStruct)` reaches
     * here with `addr` being a small int / None / a 31-bit struct
     * type-tag, and the bare deref segfaulted. Same guard as
     * mojo_read_type_tag_safe: nothing legitimate lives below 2GiB on any
     * platform this runtime targets. */
    if (!_mojo_tagged_addr_ok(addr)) return 0;
    return *(int64_t *)(intptr_t)addr;
}

/* Like mojo_read_type_tag, but for callers that don't statically know
 * whether `addr` is even a real pointer — e.g. the generic
 * getattr()/setattr()/dataclasses.fields()/dataclasses.is_dataclass()
 * dispatch (see gimple_codegen.py's emitted _mojo_dispatch_* functions),
 * which run on a value boxed as int64_t that could just as easily be a
 * small scalar (a line number, a boolean, 0/None) as a struct pointer.
 * Dereferencing a small int as a pointer is UB; the same small-vs-real-
 * pointer heuristic mojo_str() already uses (a real heap/stack address is
 * never this small) turns that into a safe "not a tagged struct" instead
 * of a crash. */
int64_t mojo_read_type_tag_safe(int64_t addr) {
    /* < 64KiB: None / small ints / bools. Also reject the whole 31-bit
     * range the struct type-tags themselves occupy (`zlib.crc32(name) &
     * 0x7fffffff`): a compiled `type(node)` yields such a tag rather than
     * a class object, and `dataclasses.fields(<that tag>)` used to reach
     * here and dereference the tag as a pointer. On every platform this
     * runtime targets a genuine heap/stack/static address is far above
     * 2GiB, so nothing legitimate is lost. */
    if (!_mojo_tagged_addr_ok(addr)) return 0;
    return *(int64_t *)(intptr_t)addr;
}

char *mojo_str(void *obj) {
    /* Flexible: handle both int (cast as pointer) and actual char* pointers */
    if (obj == NULL) {
        static char none[] = "None";
        return none;
    }
    /* If it looks like a valid string pointer (high address), return as-is */
    intptr_t val = (intptr_t)obj;
    if (val > 65536) {  /* Likely a heap/stack pointer */
        return (char *)obj;
    }
    /* Treat as small integer and convert */
    static char buffer[64];
    snprintf(buffer, sizeof(buffer), "%" PRIdPTR, val);
    return buffer;
}

char *mojo_repr_int(int64_t obj) {
    /* Was `mojo_repr(int obj)` -- a plain 32-bit `int` parameter silently
     * truncated any 64-bit value (Int is the 64-bit machine word per ABI.md),
     * and every OTHER call shape (repr() on a string, list, or struct
     * pointer) was ALSO routed through this same int-formatting function,
     * printing a plausible-looking-but-meaningless decimal number for a
     * pointer instead of the real content. gimple_codegen.py's
     * _lower_call now dispatches repr() by the argument's static type
     * instead of always calling one generic function -- see
     * mojo_repr_str/mojo_repr_obj below for the other cases. Found via
     * mojo.py's own `--dump`'s `repr(ast)` on a parsed AST list producing a
     * garbage number as the .ast file's entire content. */
    static char buffer[32];
    snprintf(buffer, sizeof(buffer), "%" PRId64, obj);
    /* Fresh heap copy, NOT the shared `static buffer`: callers routinely
     * hold two `repr()` results live at once (e.g. the compiler's
     * `_lower_ListExpr` lowers every element and only then emits the append
     * lines), and a static return made the second call overwrite the first —
     * `[2.0, 3.0]` emitted `3.0, 3.0`. */
    return strdup(buffer);
}

char *mojo_repr_str(char *s) {
    /* Python repr() of a string is quoted: repr("hi") == "'hi'", with
     * control characters shown as escapes (repr("a\nb") == "'a\\nb'") rather
     * than the raw byte -- needed for e.g. a compiled AST's StringLiteral
     * nodes whose value is itself a multi-line docstring. Minimal escaping
     * (backslash, single-quote/double-quote as needed, \n \r \t) -- good
     * enough for a debug dump, not a full Python string-literal round-trip.
     *
     * Quote-character choice mirrors Python's own repr() heuristic: prefer
     * single quotes, UNLESS the string contains a single quote and no
     * double quote, in which case use double quotes instead so the
     * apostrophe needs no escaping -- e.g. Python's repr("it's") is the
     * 6-character string `"it's"` (double-quote delimited, apostrophe
     * unescaped), not `'it\'s'`. Found via a docstring containing
     * `'foo/bar.mojo'`-style single-quoted examples: this always used
     * single-quote delimiters with the inner quotes backslash-escaped
     * instead -- value-preserving, but a real mismatch against CPython's
     * own repr() once self-hosted-compiled and diffed against the
     * interpreted stage1 dump. */
    if (!s) s = "";
    int has_squote = 0, has_dquote = 0;
    for (const char *c = s; *c; c++) {
        if (*c == '\'') has_squote = 1;
        else if (*c == '"') has_dquote = 1;
    }
    char quote = (has_squote && !has_dquote) ? '"' : '\'';
    size_t len = strlen(s);
    char *buf = malloc(len * 2 + 3);
    char *p = buf;
    *p++ = quote;
    for (const char *c = s; *c; c++) {
        if (*c == quote || *c == '\\') { *p++ = '\\'; *p++ = *c; }
        else if (*c == '\n') { *p++ = '\\'; *p++ = 'n'; }
        else if (*c == '\r') { *p++ = '\\'; *p++ = 'r'; }
        else if (*c == '\t') { *p++ = '\\'; *p++ = 't'; }
        else *p++ = *c;
    }
    *p++ = quote;
    *p = '\0';
    return buf;
}

/* Python str(True)/str(False) → "True"/"False", not "1"/"0". str()/f-string
 * lowering routes a statically-_Bool value here instead of the int path. */
char *mojo_bool_to_str(int b) {
    static char t[] = "True";
    static char f[] = "False";
    return b ? t : f;
}

char *mojo_repr_float(double v) {
    /* Python's repr()/str() of a float always shows it as a float — even a
     * whole-number value like 0.0 or 2.0 keeps a trailing ".0" — so it can
     * never be confused with an int at a glance. Plain "%g" doesn't do
     * this: %g for 0.0 is just "0", indistinguishable from an int repr.
     * Found via a compiled AST's FloatLiteral(value=0.0, ...) printing as
     * value=0 once self-hosted.
     *
     * Precision: Python's repr picks the SHORTEST decimal string that
     * round-trips back to the same double (repr(3.141592653589793) is
     * "3.141592653589793", not the 6-significant-digit "%g" default
     * "3.14159"). Reproduce that by widening precision from 1 to 17 and
     * stopping at the first value strtod() parses back exactly; 17
     * significant digits always round-trip for an IEEE-754 double, so the
     * loop is guaranteed to terminate with a correct representation. */
    static char buffer[64];
    /* Special values first: Python's repr is "nan"/"inf"/"-inf". */
    if (v != v) return "nan";
    if (v == (double)INFINITY) return "inf";
    if (v == (double)-INFINITY) return "-inf";
    /* Shortest significant precision that strtod() parses back exactly.
     * 17 digits always round-trip for an IEEE-754 double. */
    int _prec = 17;
    for (int _p = 1; _p <= 17; _p++) {
        snprintf(buffer, sizeof(buffer), "%.*g", _p, v);
        if (strtod(buffer, NULL) == v) { _prec = _p; break; }
    }
    /* Python switches to SCIENTIFIC form only outside 1e-4 <= |v| < 1e16
     * (repr(1e9) is "1000000000.0", not "1e+09"); plain "%g" switches as
     * soon as the exponent reaches the precision, so re-format explicitly
     * from the decimal exponent. */
    char _ebuf[64];
    snprintf(_ebuf, sizeof(_ebuf), "%.*e", _prec - 1, v);
    char *_ep = strchr(_ebuf, 'e');
    int _E = _ep ? atoi(_ep + 1) : 0;
    if (_E >= -4 && _E < 16) {
        int _fprec = _prec - 1 - _E;
        if (_fprec < 0) _fprec = 0;
        snprintf(buffer, sizeof(buffer), "%.*f", _fprec, v);
    } else {
        snprintf(buffer, sizeof(buffer), "%.*e", _prec - 1, v);
    }
    int has_marker = 0;
    for (char *p = buffer; *p; p++) {
        if (*p == '.' || *p == 'e' || *p == 'E' || *p == 'n' || *p == 'i') { has_marker = 1; break; }
    }
    if (!has_marker) strncat(buffer, ".0", sizeof(buffer) - strlen(buffer) - 1);
    /* Fresh heap copy — see mojo_repr_int's identical note: a shared static
     * return aliased two live results (`[2.0, 3.0]` came out `3.0, 3.0`). */
    return strdup(buffer);
}

/* `mojo_str_cat` with its LEFT operand released. `mojo_str_cat` allocates a
   new buffer and deliberately leaves both arguments alone, so a chain of N
   cats needs the caller to free N-1 buffers. Every repr walker below is such
   a chain and none of them did, which was only a slow leak on a debug print
   until these walkers became a dict KEY's renderer
   (`_container_key_str`), where they run once per key in whatever loop the key
   is used in: measured +78 B per lookup, the same per-access growth the
   Int-key side had just been fixed for
   (bugs/CODEGEN_tuple_dict_key_hashed_by_address.md). `a` must be a buffer the
   caller owns -- every use below is one this file just built -- and `b` is
   untouched, so passing a shared static (`mojo_repr_obj`'s buffer) is safe.

   PUBLIC, and declared in fire_runtime.h, because the repr walkers the
   CODEGEN emits into every generated program (`_mojo_repr_list`,
   `_mojo_repr_pair`, `_mojo_repr_dict`, `_mojo_repr_set`,
   `mojo/backend_gimple/module_gen.py`) are the same chain and were leaking
   the same N-1 buffers per printed container. Emitting a second copy of this
   helper into the preamble instead would have been two implementations of one
   rule in two languages, which is the thing the runtime's own note about
   `mojo_repr_obj`'s shared buffer exists to make impossible. */
char *mojo_str_cat_free(char *a, char *b) {
    char *r = mojo_str_cat(a, b);
    free(a);
    return r;
}

/* A list that records its OWN per-slot kinds (mojo_list_set_kinds) is
   described by them more precisely than any single-accessor reader chosen
   for the whole list can be, so every uniform list repr below defers to it
   first and returns NULL when there is nothing to defer to. The one caller
   that cannot see the kinds at all is the one that most needs this: the
   codegen picks a uniform helper from a compile-time element type, and a
   DERIVED value (`list(t)`, `t[:]`, a `t` returned from a function) is
   built by a runtime helper the codegen knows nothing about. Costs a load
   and a branch when no heterogeneous list has ever been built, and one
   open-addressed probe otherwise. */
static char *_mojo_repr_defers_to_kinds(MojoList *l) {
    return (l && mojo_list_get_kinds(l)) ? mojo_repr_list_kinds(l, NULL) : NULL;
}

char *mojo_repr_list_doubles(MojoList *l) {
    /* A list that brought its own per-slot kinds is described by them
       (see _mojo_repr_defers_to_kinds). */
    char *_dk = _mojo_repr_defers_to_kinds(l);
    if (_dk) return _dk;
    /* Double-aware repr for a MojoList * whose element type is statically
     * known (at codegen time, via gimple_codegen.py's _elem_types) to be
     * double. MojoList stores every element as a raw int64_t slot with no
     * per-element type tag, and the codegen-emitted generic
     * _mojo_repr_list/_mojo_generic_elem_repr pair reads each slot back via
     * mojo_list_get_int -- a double's IEEE-754 bit pattern then either
     * prints as a nonsense integer or, when it happens to look like a
     * plausible heap address, faults inside mojo_read_type_tag_safe. This
     * mirrors _mojo_repr_list's exact structure (tuple parens, single-element
     * trailing comma, [..] otherwise) but reads each slot via
     * mojo_list_get_double and formats it with mojo_repr_float. */
    int _is_tup = l && mojo_is_tuple(l);
    if (!l) return _is_tup ? "()" : "[]";
    int64_t _n = mojo_list_len(l);
    char *_buf = strdup(_is_tup ? "(" : "[");
    for (int64_t _i = 0; _i < _n; _i++) {
        if (_i > 0) _buf = mojo_str_cat_free(_buf, ", ");
        /* One owned `_s`, released after the cat, rather than a cat per
           expression: `mojo_repr_float` returns a fresh heap string and a
           chain of N cats that never frees its left operands leaked N+1
           buffers (sized to the text so far, so O(N^2) bytes) per printed
           container -- ~500 B per `print` of an 8-element list, which is a
           `--dump`, a logging line, or any other loop that prints.
           bugs/PERF_printed_container_repr_leaks_its_cat_buffers.md */
        char *_s = mojo_repr_float(mojo_list_get_double(l, _i));
        _buf = mojo_str_cat_free(_buf, _s);
        free(_s);
    }
    if (_is_tup && _n == 1) _buf = mojo_str_cat_free(_buf, ",");
    return mojo_str_cat_free(_buf, _is_tup ? ")" : "]");
}

char *mojo_repr_list_ints(MojoList *l) {
    /* A list that brought its own per-slot kinds is described by them
       (see _mojo_repr_defers_to_kinds). */
    char *_dk = _mojo_repr_defers_to_kinds(l);
    if (_dk) return _dk;
    /* Int-aware repr for a MojoList * whose element type is statically
     * known (at codegen time, via gimple_codegen.py's _elem_types) to be a
     * genuinely homogeneous int64_t (never a boxed pointer/None sentinel
     * mixed in) -- e.g. a `[a for a in range(n)]`-style comprehension or
     * list literal of plain ints. MojoList stores every element as a raw
     * int64_t slot with no per-element type tag, and the generic codegen-
     * emitted _mojo_repr_list/_mojo_generic_elem_repr pair treats a slot
     * holding the literal value 0 as the `None` sentinel (needed for
     * genuinely dynamic/heterogeneous lists, where 0 really can mean a
     * boxed null), which is wrong for a list statically known to hold only
     * real ints -- a real element value of 0 always printed as `None`
     * instead of `0`. Mirrors mojo_repr_list_doubles's exact structure
     * (tuple parens, single-element trailing comma, [..] otherwise) but
     * reads each slot via mojo_list_get_int and formats it with
     * mojo_repr_int unconditionally, with no None-sentinel check. */
    int _is_tup = l && mojo_is_tuple(l);
    if (!l) return _is_tup ? "()" : "[]";
    int64_t _n = mojo_list_len(l);
    char *_buf = strdup(_is_tup ? "(" : "[");
    for (int64_t _i = 0; _i < _n; _i++) {
        if (_i > 0) _buf = mojo_str_cat_free(_buf, ", ");
        /* `mojo_repr_int` owns its return -- see mojo_repr_list_doubles's
           identical note on why the chain releases its left operands. */
        char *_s = mojo_repr_int(mojo_list_get_int(l, _i));
        _buf = mojo_str_cat_free(_buf, _s);
        free(_s);
    }
    if (_is_tup && _n == 1) _buf = mojo_str_cat_free(_buf, ",");
    return mojo_str_cat_free(_buf, _is_tup ? ")" : "]");
}

char *mojo_repr_list_bools(MojoList *l) {
    /* A list that brought its own per-slot kinds is described by them
       (see _mojo_repr_defers_to_kinds). */
    char *_dk = _mojo_repr_defers_to_kinds(l);
    if (_dk) return _dk;
    /* Bool-aware repr for a MojoList * whose element type is statically
     * known (at codegen time, via gimple_codegen.py's _elem_types) to be
     * `_Bool` (e.g. a `[True, False]` literal). MojoList stores every
     * element as a raw int64_t slot with no per-element type tag, so the
     * generic codegen-emitted _mojo_repr_list/_mojo_generic_elem_repr pair
     * both formats a bool slot with mojo_repr_int (printing 1/0 instead of
     * True/False) AND treats a False (0) slot as the None sentinel, so
     * `[True, False]` printed `[1, None]`. Mirrors mojo_repr_list_ints'
     * exact structure but formats each slot with mojo_repr_bool
     * unconditionally, with no None-sentinel check. */
    int _is_tup = l && mojo_is_tuple(l);
    if (!l) return _is_tup ? "()" : "[]";
    int64_t _n = mojo_list_len(l);
    char *_buf = strdup(_is_tup ? "(" : "[");
    for (int64_t _i = 0; _i < _n; _i++) {
        if (_i > 0) _buf = mojo_str_cat_free(_buf, ", ");
        /* The chain releases its left operands; the per-slot string does NOT
           need releasing, because `mojo_repr_bool` is one of this file's two
           repr helpers that returns SHARED storage (the other is
           `mojo_repr_obj`, and see mojo_str_cat_free's own comment for why the
           right operand of a cat must be left alone). */
        _buf = mojo_str_cat_free(_buf, mojo_repr_bool((int)mojo_list_get_int(l, _i)));
    }
    if (_is_tup && _n == 1) _buf = mojo_str_cat_free(_buf, ",");
    return mojo_str_cat_free(_buf, _is_tup ? ")" : "]");
}

/* Pair-list reprs: a list whose ELEMENTS are 2-element lists — what
   `enumerate(x)` and `zip(a, b)` produce. The generic codegen-emitted
   `_mojo_repr_list` cannot render one: it reads each inner slot through the
   None-sentinel heuristic, so the index 0 of the first pair printed as
   `None` (`[[None, 7], [1, 8]]`), and a real Python `(0, 7)` is wanted
   anyway. `_kind` is the statically known type of the SECOND slot (0 int,
   1 str, 2 double) — passed in rather than sniffed, because a double and an
   int are indistinguishable in the raw slot. */
static char *_mojo_repr_pairlist(MojoList *l, int _kind) {
    if (!l) return "[]";
    int64_t _n = mojo_list_len(l);
    char *_buf = strdup("[");
    for (int64_t _i = 0; _i < _n; _i++) {
        if (_i > 0) _buf = mojo_str_cat_free(_buf, ", ");
        int64_t _p = mojo_list_get_int(l, _i);
        if (!mojo_is_registered_list(_p)) {
            /* NOT owned: `mojo_repr_obj` returns its shared static, which is
               why it stays on the RIGHT of the cat (mojo_str_cat_free's own
               comment). */
            _buf = mojo_str_cat_free(_buf, mojo_repr_obj(_p));
            continue;
        }
        MojoList *_pair = (MojoList *)(intptr_t)_p;
        _buf = mojo_str_cat_free(_buf, "(");
        char *_s = mojo_repr_int(mojo_list_get_int(_pair, 0));
        _buf = mojo_str_cat_free(_buf, _s);
        free(_s);
        _buf = mojo_str_cat_free(_buf, ", ");
        int64_t _v = mojo_list_get_int(_pair, 1);
        if (_kind == 1) {
            _s = mojo_repr_str((char *)(intptr_t)_v);
        } else if (_kind == 2) {
            _s = mojo_repr_float(mojo_list_get_double(_pair, 1));
        } else if (mojo_boxed_is_str(_v)) {
            _s = mojo_repr_str((char *)(intptr_t)_v);
        } else {
            _s = mojo_repr_int(_v);
        }
        _buf = mojo_str_cat_free(_buf, _s);
        free(_s);
        _buf = mojo_str_cat_free(_buf, ")");
    }
    return mojo_str_cat_free(_buf, "]");
}

/* A list whose elements are LISTS OF INTS (`[[0, 7], [1, 8]]`) — what a
   nested list literal produces. The generic `_mojo_repr_list` recurses into
   the inner lists through the None-sentinel heuristic, so an inner 0 printed
   as `None` (`[[None, 7], [1, 8]]`). The codegen knows statically that the
   inner lists hold plain ints (that is exactly what routes this helper), so
   read every inner slot as an int.

   The outer value and every inner value each pick their own brackets from
   `mojo_is_tuple`, the same way every other repr helper here does. That is not
   cosmetic: `[(5, j) for j in range(3)]` and `[[5, j] for j in range(3)]`
   are the same comprehension with a tuple or a list element, both route here
   (both elements are int lists, so both carry the same nested element type),
   and the tuple one printed as `[[5, 0], [5, 1], [5, 2]]`. Hardcoding `[`
   here also misreported a tuple of int lists. */
static char *_mojo_repr_intlists(MojoList *l) {
    int _is_tup = l && mojo_is_tuple(l);
    if (!l) return _is_tup ? "()" : "[]";
    int64_t _n = mojo_list_len(l);
    char *_buf = strdup(_is_tup ? "(" : "[");
    for (int64_t _i = 0; _i < _n; _i++) {
        if (_i > 0) _buf = mojo_str_cat_free(_buf, ", ");
        int64_t _p = mojo_list_get_int(l, _i);
        if (!mojo_is_registered_list(_p)) {
            /* NOT owned -- `mojo_repr_obj`'s shared static. */
            _buf = mojo_str_cat_free(_buf, mojo_repr_obj(_p));
            continue;
        }
        MojoList *_in = (MojoList *)(intptr_t)_p;
        int64_t _m = mojo_list_len(_in);
        /* Each INNER element is a tuple or a list in its own right, and
         * `mojo_repr_list_ints`/`_doubles`/`_bytes` all open on
         * `mojo_is_tuple(this)` for exactly that reason. This helper used
         * to hardcode "[" / "]" for the inner pair, which made a list of
         * TUPLES print as a list of lists: `[(5, 0), (5, 1)]` printed
         * `[[5, 0], [5, 1]]`, and so did `[(5, j) for j in range(2)]`.
         * The outer brackets stay "[" -- this helper is reached only for a
         * list whose elements are containers, and a LIST OF TUPLES is
         * itself a list. */
        int _in_tup = mojo_is_tuple(_in);
        _buf = mojo_str_cat_free(_buf, _in_tup ? "(" : "[");
        for (int64_t _j = 0; _j < _m; _j++) {
            if (_j > 0) _buf = mojo_str_cat_free(_buf, ", ");
            char *_s = mojo_repr_int(mojo_list_get_int(_in, _j));
            _buf = mojo_str_cat_free(_buf, _s);
            free(_s);
        }
        if (_in_tup && _m == 1) _buf = mojo_str_cat_free(_buf, ",");
        _buf = mojo_str_cat_free(_buf, _in_tup ? ")" : "]");
    }
    if (_is_tup && _n == 1) _buf = mojo_str_cat_free(_buf, ",");
    return mojo_str_cat_free(_buf, _is_tup ? ")" : "]");
}

char *mojo_repr_list_intlists(MojoList *l) { return _mojo_repr_intlists(l); }

char *mojo_repr_list_pairs(MojoList *l) { return _mojo_repr_pairlist(l, 0); }
char *mojo_repr_list_pairs_s(MojoList *l) { return _mojo_repr_pairlist(l, 1); }
char *mojo_repr_list_pairs_d(MojoList *l) { return _mojo_repr_pairlist(l, 2); }

/* A list whose elements are inner lists/tuples that ALL share one per-slot
   kind pattern — `[(1.5, 2)]`, `[('a', 0, 1) for i in range(2)]`,
   `[(cfg, model), (cfg, model)]`. `kinds` is that pattern, one byte per
   INNER slot, in mojo_repr_list_kinds' own alphabet; the inner brackets, the
   single-element trailing comma and the per-slot value reading are all that
   function's, so this is the same reader applied one level up — which is why
   it delegates rather than repeating the switch.

   Without it the generic walker read each inner slot through the
   None-sentinel heuristic, so every int 0 in a non-zero slot printed as
   `None` (`[('a', 0, 1)]` → `[('a', None, 1)]`) and a double read as an int
   printed its raw IEEE-754 bits — or, when those bits looked like a heap
   address, faulted inside mojo_read_type_tag_safe (`[(1.5, 2)]` SIGSEGV'd).
   The codegen has the pattern statically (`_tuple_slot_types`, recorded for
   every tuple literal whose slots are not all one type), which is what routes
   here. */
char *mojo_repr_list_slotkinds(MojoList *l, const char *kinds) {
    int _is_tup = l && mojo_is_tuple(l);
    if (!l) return _is_tup ? "()" : "[]";
    int64_t _n = mojo_list_len(l);
    char *_buf = strdup(_is_tup ? "(" : "[");
    for (int64_t _i = 0; _i < _n; _i++) {
        if (_i > 0) _buf = mojo_str_cat_free(_buf, ", ");
        int64_t _p = mojo_list_get_int(l, _i);
        if (!mojo_is_registered_list(_p)) {
            /* NOT owned -- `mojo_repr_obj`'s shared static. */
            _buf = mojo_str_cat_free(_buf, mojo_repr_obj(_p));
            continue;
        }
        /* `mojo_repr_list_kinds` owns its return (see its own comment), so the
           chain releases its left operand AND this one. */
        char *_s = mojo_repr_list_kinds((MojoList *)(intptr_t)_p, kinds);
        _buf = mojo_str_cat_free(_buf, _s);
        free(_s);
    }
    if (_is_tup && _n == 1) _buf = mojo_str_cat_free(_buf, ",");
    return mojo_str_cat_free(_buf, _is_tup ? ")" : "]");
}

char *mojo_repr_list_bytes(MojoList *l) {
    /* A list that brought its own per-slot kinds is described by them
       (see _mojo_repr_defers_to_kinds). */
    char *_dk = _mojo_repr_defers_to_kinds(l);
    if (_dk) return _dk;
    /* repr for a MojoList * whose element type is statically known to be
     * `MojoBytes *` (e.g. b.split(sep)). Each int64_t slot holds a
     * MojoBytes pointer; format each via mojo_bytes_repr. */
    int _is_tup = l && mojo_is_tuple(l);
    if (!l) return _is_tup ? "()" : "[]";
    int64_t _n = mojo_list_len(l);
    char *_buf = strdup(_is_tup ? "(" : "[");
    for (int64_t _i = 0; _i < _n; _i++) {
        if (_i > 0) _buf = mojo_str_cat_free(_buf, ", ");
        MojoBytes *_b = (MojoBytes *)(uintptr_t)mojo_list_get_int(l, _i);
        /* `mojo_bytes_repr` owns its return. */
        char *_s = mojo_bytes_repr(_b);
        _buf = mojo_str_cat_free(_buf, _s);
        free(_s);
    }
    if (_is_tup && _n == 1) _buf = mojo_str_cat_free(_buf, ",");
    return mojo_str_cat_free(_buf, _is_tup ? ")" : "]");
}

char *mojo_repr_list_kinds(MojoList *l, const char *kinds) {
    /* repr for a MojoList * whose per-slot element kinds are known but NOT
     * uniform. The uniform helpers above each read every slot through one
     * accessor, which is exact for them because the whole list really does
     * hold that one kind; for a mixed list that choice is wrong for the
     * other slots, and a float read as an int prints its raw IEEE-754 bit
     * pattern (`(1, 4607182418800017408)` for '<if', `[1.0, 2.5]` for the
     * literal `[1, 2.5]`).
     *
     * TWO sources for the kind string, in this order:
     *   - the `kinds` argument, which the CALLER passes when it knows them
     *     statically — a `struct` format string is a compile-time constant
     *     (mojo/backend_gimple/emit_methods.py's _struct_slot_kinds), so the
     *     direct `struct.unpack(...)` case still needs no runtime table;
     *   - otherwise the kinds recorded on the VALUE itself
     *     (mojo_list_set_kinds), which is what makes every DERIVED list
     *     right: `list(t)`, `t[:]`, `t + t`, and a `t` returned from a
     *     function all carry them because the runtime hands them along. The
     *     codegen used to lose them there and print raw IEEE-754 bits for a
     *     copy of a mixed tuple.
     *
     * A slot the string does not cover (a longer list than the kinds
     * describe, which no real call produces) falls back to the int accessor,
     * the same answer the uniform int helper gives. Mirrors
     * mojo_repr_list_doubles' exact structure (tuple parens, single-element
     * trailing comma, [..] otherwise). */
    if (!kinds) kinds = mojo_list_get_kinds(l);
    int _is_tup = l && mojo_is_tuple(l);
    if (!l) return _is_tup ? "()" : "[]";
    int64_t _n = mojo_list_len(l);
    char *_buf = strdup(_is_tup ? "(" : "[");
    for (int64_t _i = 0; _i < _n; _i++) {
        if (_i > 0) _buf = mojo_str_cat_free(_buf, ", ");
        /* A NULL kinds string is not "no kinds" but "no kinds to apply": every
           slot then falls back to the int accessor, which is the documented
           behaviour for a slot the string does not cover (see the comment
           above). It was `kinds && !kinds[_i]`, which reads `kinds[_i]` in the
           else arm anyway — so a NULL kinds string dereferenced NULL, and
           `mojo_repr_list_kinds(l, NULL)` was only ever safe because every
           caller happened to pass a non-NULL string first. Two callers did
           not: the nested-list recursion just below, and a dict key's content
           key (`_container_key_str`), whose tuple carries no kinds row when
           codegen appended to it slot by slot. */
        char _k = (!kinds || !kinds[_i]) ? 'i' : kinds[_i];
        /* One `_s`, released after the cat, rather than a cat per branch: every
           repr helper here returns a fresh heap string and none of them was
           freed, so a repr of a mixed N-slot list leaked N of them. That was
           only ever a slow leak on a debug print, but this function is now
           also a dict KEY's renderer (`_container_key_str`), where it runs once
           per lookup in whatever loop the key is used in — which is exactly the
           shape that turned a tuple-keyed miss into gigabytes of live memory
           (bugs/CODEGEN_tuple_dict_key_hashed_by_address.md). The one branch
           that does not own a heap string is 'n' (None), a literal. */
        char *_s;
        /* The list's own ELEMENT REPR wins over every kind byte below: it is
           the codegen saying what this list's elements actually ARE, which is
           strictly more information than a slot's storage kind ('i' for a
           struct pointer is as true as 'i' for a small int and as useless). */
        char *_re = mojo_list_repr_elem(l, mojo_list_get_int(l, _i));
        if (_re) {
            _buf = mojo_str_cat_free(_buf, _re);
            free(_re);
            continue;
        }
        if (_k == 'd') {
            _s = mojo_repr_float(mojo_list_get_double(l, _i));
        } else if (_k == 's') {
            MojoBytes *_b = (MojoBytes *)(uintptr_t)mojo_list_get_int(l, _i);
            _s = mojo_bytes_repr(_b);
        } else if (_k == 'p') {
            char *_p = (char *)(intptr_t)mojo_list_get_int(l, _i);
            _s = mojo_repr_str(_p);
        } else if (_k == 'l') {
            /* A nested list/tuple slot: recurse through the same kinds-aware
             * repr, so `[[1, 2.5], 3]` describes its inner list too. */
            MojoList *_in = (MojoList *)(intptr_t)mojo_list_get_int(l, _i);
            _s = mojo_repr_list_kinds(_in, NULL);
        } else if (_k == 'n') {
            _buf = mojo_str_cat_free(_buf, "None");
            continue;
        } else {
            _s = mojo_repr_int(mojo_list_get_int(l, _i));
        }
        _buf = mojo_str_cat_free(_buf, _s);
        free(_s);
    }
    if (_is_tup && _n == 1) _buf = mojo_str_cat_free(_buf, ",");
    return mojo_str_cat_free(_buf, _is_tup ? ")" : "]");
}

char *mojo_repr_obj(int64_t addr) {
    /* Fallback for anything that isn't a plain scalar or a string: a real
     * struct/list/dict/set pointer. A full Python-style field-by-field repr
     * would need a runtime struct-metadata table (field names + types per
     * struct) this compiler doesn't build -- only a type TAG, see
     * mojo_read_type_tag above, which is enough for isinstance() but not for
     * reconstructing field names. Format as an address instead of silently
     * printing a decimal number indistinguishable from real data. */
    static char buffer[40];
    if (!addr) return "None";
    snprintf(buffer, sizeof(buffer), "<object at 0x%" PRIx64 ">", addr);
    return buffer;
}

int mojo_type(int obj) {
    /* Stub, and deliberately still a stub: returns a type identifier, 0 for
     * now. Not dead code despite having no in-tree caller -- see
     * fire_runtime.h's own comment on the declaration, which explains that
     * gimple_codegen._RUNTIME_FUNCS resolves the Mojo builtin `type` to this
     * symbol, so generated C references it. `int obj` matches the header and
     * this file's other boxed-object convention (mojo_hasattr below); the
     * parameter is unused because the answer does not depend on it yet. */
    (void)obj;
    return 0;
}

int mojo_hasattr(int obj, char *attr) {
    /* Stub: returns 1 for any non-NULL object, since the typed dispatch
       is generated as a static function in each module and not available
       here in the runtime library. Real Mojo would check the type tag
       and field list. Used by hasattr() in tests. */
    (void)attr;
    return obj != 0 ? 1 : 0;
}

/* A genuine C-string pointer always lands in the userspace-heap/static
   window [0x1000, 2^47) on macOS and Linux. A value outside it is not a
   string address — most often a `str` AST field the self-hosted codegen
   erased to int64_t (barrier 2: `_known_field_type` gap) whose 8 raw bytes
   are the string CONTENT, not a pointer to it (e.g. a struct name reaching
   an f-string as `0x6547656c706d6940` == "\x40impleGe"). Treat it as empty
   rather than dereferencing garbage: on the shimless `--dump-full` this
   turns a chain of one-crash-per-rebuild boxed-name faults into a single
   completable run whose remaining defects surface as GCC errors. Inert on
   the shimmed/Python path, where every argument is a real pointer. */
static int _mojo_cstr_ptr_ok(char *p) {
    uintptr_t v = (uintptr_t)p;
    return v >= 0x1000ULL && v < 0x0000800000000000ULL;
}

char *mojo_str_cat(char *a, char *b) {
    /* Concatenate two C strings */
    if (!_mojo_cstr_ptr_ok(a)) a = "";
    if (!_mojo_cstr_ptr_ok(b)) b = "";

    size_t len_a = strlen(a);
    size_t len_b = strlen(b);
    char *result = malloc(len_a + len_b + 1);

    if (result) {
        strcpy(result, a);
        strcpy(result + len_a, b);
    }

    return result;
}

char *mojo_path_join(char *base, char *name) {
    if (!base || base[0] == '\0') return name ? name : "";
    if (!name || name[0] == '\0') return base;
    size_t blen = strlen(base);
    int need_sep = (base[blen - 1] != '/');
    size_t nlen = strlen(name);
    char *result = malloc(blen + need_sep + nlen + 1);
    if (!result) return NULL;
    strcpy(result, base);
    if (need_sep) result[blen++] = '/';
    strcpy(result + blen, name);
    return result;
}

char *mojo_cstr_repeat(char *s, int64_t n) {
    /* Repeat a string n times */
    if (!s || n <= 0) {
        char *result = malloc(1);
        if (result) result[0] = '\0';
        return result;
    }

    size_t len = strlen(s);
    char *result = malloc(len * n + 1);

    if (result) {
        for (int64_t i = 0; i < n; i++) {
            strcpy(result + i * len, s);
        }
        result[len * n] = '\0';
    }

    return result;
}

/* ── Method stubs for compatibility ────────────────────────────────────────*/

int MojoList_append(MojoList *l, char *v) {
    /* Stub: append string to list */
    if (l && v) {
        mojo_list_append_str(l, v);
    }
    return 0;
}

int char_join(char *sep, MojoList *items) {
    /* Stub: join list items with separator - returns 0 for now */
    return 0;
}

int int_items(int obj) {
    /* Stub: return 0 for dictionary items - not fully implemented */
    return 0;
}

/* ── Module function stubs ────────────────────────────────────────────────*/

void *mojo_parse(char *source) {
    /* Basic parse stub - just return a simple AST node representation */
    if (!source || !source[0]) {
        return NULL;
    }
    /* For now, allocate a marker that indicates successful parse */
    int *result = malloc(sizeof(int));
    if (result) *result = 1;  /* 1 = successfully parsed */
    return result;
}

MojoList *mojo_py_tokenize(char *source) {
    /* Basic tokenizer - splits on whitespace and punctuation */
    MojoList *tokens = mojo_list_new();
    if (!source || !source[0]) {
        return tokens;
    }

    char buffer[1024];
    int idx = 0;

    for (char *p = source; *p; p++) {
        if (*p == ' ' || *p == '\n' || *p == '\t' || *p == '\r') {
            if (idx > 0) {
                buffer[idx] = '\0';
                char *token = malloc(idx + 1);
                if (token) {
                    strcpy(token, buffer);
                    mojo_list_append_str(tokens, token);
                    free(token);
                }
                idx = 0;
            }
        } else if (*p == '(' || *p == ')' || *p == ',' || *p == ':' || *p == '=') {
            if (idx > 0) {
                buffer[idx] = '\0';
                char *token = malloc(idx + 1);
                if (token) {
                    strcpy(token, buffer);
                    mojo_list_append_str(tokens, token);
                    free(token);
                }
                idx = 0;
            }
            char punct[2] = {*p, '\0'};
            mojo_list_append_str(tokens, punct);
        } else {
            if (idx < sizeof(buffer) - 1) {
                buffer[idx++] = *p;
            }
        }
    }

    if (idx > 0) {
        buffer[idx] = '\0';
        char *token = malloc(idx + 1);
        if (token) {
            strcpy(token, buffer);
            mojo_list_append_str(tokens, token);
            free(token);
        }
    }

    return tokens;
}

/* ── Python integration ──────────────────────────────────────────────*/
#if USE_PYTHON
int open(int path) {
    if (path <= 1000) return 0;
    char *path_str = (char *)path;
    PyObject *builtins = PyImport_ImportModule("builtins");
    if (!builtins) {
        PyErr_Clear();
        return 0;
    }
    PyObject *open_func = PyObject_GetAttrString(builtins, "open");
    Py_DECREF(builtins);
    if (!open_func) {
        PyErr_Clear();
        return 0;
    }
    PyObject *fh = PyObject_CallFunction(open_func, "s", path_str);
    Py_DECREF(open_func);
    if (!fh) {
        PyErr_Clear();
        return 0;
    }
    return (int)(intptr_t)fh;
}
#endif

/* ── Non-Python file open (always available) ────────────────────────────*/
int64_t mojo_open_file(char *path) {
    /* Return FILE* as int64_t so int_read/int_write can cast it back.
     * A missing/unreadable file RAISES (FileNotFoundError), matching
     * real Python's builtin open() — see mojo_raise_file_not_found. */
    FILE *f = fopen(path, "r");
    if (!f) mojo_raise_file_not_found(path);
    return (int64_t)(intptr_t)f;
}

/* ── REPL and utility functions ──────────────────────────────────────*/

char *mojo_input(char *prompt) {
    if (prompt) fputs(prompt, stdout);
    fflush(stdout);

    size_t cap = 4096;
    char *buf = malloc(cap);
    if (!buf) return NULL;
    size_t len = 0;
    for (;;) {
        if (len + 64 > cap) { cap *= 2; buf = realloc(buf, cap); }
        int c = fgetc(stdin);
        if (c == EOF || c == '\n') break;
        buf[len++] = (char)c;
    }
    buf[len] = '\0';
    return buf;
}

/* input() — weak so the Mojo stdlib's own `input` (std/io/io.mojo) overrides it
   when both are linked into the stdlib dylib, while standalone binaries that link
   only the runtime (e.g. build/mojo) still get a working `input`. */
__attribute__((weak)) char *input(char *prompt) {
    return mojo_input(prompt);
}

/* String utilities — stdlib-equivalent implementations */

/* A fresh heap copy of `s`. Every string method below returns a string the
 * CALLER owns — never its receiver, an interior pointer into it, or a static
 * literal — so the caller can free the result without asking where it came
 * from (codegen lists these in emit_infra._FRESH_STRING_RETURNS and frees
 * bound results at scope exit). The price is one copy where Python would
 * return the same object for an unchanged string. */
static char *_str_fresh_copy(const char *s) {
    size_t n = strlen(s);
    char *out = (char *)malloc(n + 1);
    if (!out) abort();
    memcpy(out, s, n + 1);
    return out;
}

char *string_strip(char *str) {
    if ((intptr_t)str < 65536) return str;
    if (!str) return str;

    /* Skip leading whitespace */
    char *start = str;
    while (*start && (*start == ' ' || *start == '\t' || *start == '\n' || *start == '\r')) {
        start++;
    }

    /* Nothing but whitespace — an empty string (a fresh one, like every
     * other result of this function) */
    if (!*start) { return _str_fresh_copy(""); }

    /* Find end (skip trailing whitespace) */
    char *end = str + strlen(str) - 1;
    while (end > start && (*end == ' ' || *end == '\t' || *end == '\n' || *end == '\r')) {
        end--;
    }

    size_t len = (end - start) + 1;
    if (start == str && len == strlen(str)) {
        return _str_fresh_copy(str);  /* nothing to strip */
    }
    /* Return a fresh heap copy rather than stripping in place: the input may
       be a read-only string literal (the generated preamble's interned
       `static char * _slit_N` pointers), and the previous in-place
       memmove/NUL-terminate wrote into that read-only memory — a real SIGBUS
       whenever `.strip()` was called on a literal with leading/trailing
       whitespace (e.g. gimple_codegen.py's own `self._emit('  _mojo_classattr_
       init ();')` → `line.strip()` in `_emit`, which aborted the self-hosted
       gen_func the moment function bodies actually started compiling). */
    char *out = malloc(len + 1);
    memcpy(out, start, len);
    out[len] = '\0';
    return out;
}

char *mojo_str_lstrip(char *str) {
    if (!str) return str;
    while (*str && (*str == ' ' || *str == '\t' || *str == '\n' || *str == '\r')) str++;
    return _str_fresh_copy(str);
}

char *mojo_str_rstrip(char *str) {
    if (!str) return str;
    size_t len = strlen(str);
    char *out = (char *)malloc(len + 1);
    if (!out) return str;
    memcpy(out, str, len + 1);
    char *end = out + len;
    while (end > out && (end[-1] == ' ' || end[-1] == '\t' || end[-1] == '\n' || end[-1] == '\r'))
        end--;
    *end = '\0';
    return out;
}

/* `.rstrip(chars)` — strip any trailing chars from the `chars` set, matching
 * Python (the plain mojo_str_rstrip only strips whitespace and ignores a
 * chars argument entirely, so `("MojoFunction *").rstrip(' *')` kept the
 * asterisk — gimple_codegen.py's struct-typedef dependency check
 * (`base_type = field_type.rstrip(' *')`) compared "MojoFunction *" against
 * the struct-name keys and concluded no dependency existed, emitting structs
 * out of dependency order in the self-hosted binary). */
char *mojo_str_rstrip_chars(char *str, char *chars) {
    if (!str) return str;
    size_t len = strlen(str);
    char *out = (char *)malloc(len + 1);
    if (!out) return str;
    memcpy(out, str, len + 1);
    char *end = out + len;
    while (end > out && chars && strchr(chars, end[-1]))
        end--;
    *end = '\0';
    return out;
}

char *mojo_str_lstrip_chars(char *str, char *chars) {
    if (!str) return str;
    size_t len = strlen(str);
    char *start = str;
    while (*start && chars && strchr(chars, *start))
        start++;
    if (start == str) return _str_fresh_copy(str);
    char *out = (char *)malloc(len - (start - str) + 1);
    if (!out) return str;
    strcpy(out, start);
    return out;
}

static char *_str_pad(char *s, int64_t width, char *fill, int mode) {
    /* mode: 0=rjust(right), 1=ljust(left), 2=center */
    if (!s) s = (char *)"";
    if (width < 0) width = 0;
    size_t len = strlen(s);
    if ((int64_t)len >= width) return _str_fresh_copy(s);
    size_t pad = (size_t)width - len;
    char fc = (fill && fill[0]) ? fill[0] : ' ';
    size_t left = 0, right = 0;
    if (mode == 0) { left = pad; }
    else if (mode == 1) { right = pad; }
    else { left = (size_t)_center_left((int64_t)pad, width); right = pad - left; }
    char *out = (char *)malloc(width + 1);
    if (!out) return s;
    size_t p = 0;
    for (size_t i = 0; i < left; i++) out[p++] = fc;
    for (size_t i = 0; i < len; i++) out[p++] = s[i];
    for (size_t i = 0; i < right; i++) out[p++] = fc;
    out[p] = '\0';
    return out;
}

char *mojo_str_rjust(char *s, int64_t width, char *fill) {
    return _str_pad(s, width, fill, 0);
}

char *mojo_str_ljust(char *s, int64_t width, char *fill) {
    return _str_pad(s, width, fill, 1);
}

char *mojo_str_center(char *s, int64_t width, char *fill) {
    return _str_pad(s, width, fill, 2);
}

char *mojo_str_expandtabs(char *str, int tabsize) {
    if (!str) return str;
    if (tabsize <= 0) tabsize = 8;
    size_t out_cap = strlen(str) * tabsize + 64;
    char *out = (char *)malloc(out_cap);
    if (!out) return str;
    size_t col = 0, oi = 0;
    for (const char *p = str; *p; p++) {
        if (*p == '\t') {
            size_t spaces = (size_t)tabsize - (col % (size_t)tabsize);
            while (oi + spaces + 1 > out_cap) { out_cap *= 2; out = realloc(out, out_cap); }
            for (size_t k = 0; k < spaces; k++) out[oi++] = ' ';
            col += spaces;
        } else {
            if (oi + 2 > out_cap) { out_cap *= 2; out = realloc(out, out_cap); }
            out[oi++] = *p;
            col = (*p == '\n') ? 0 : col + 1;
        }
    }
    out[oi] = '\0';
    return out;
}

char *mojo_str_join(char *sep, MojoList *parts) {
    if (!parts || parts->len == 0) return _str_fresh_copy("");
    if (!sep) sep = "";
    size_t sep_len = strlen(sep);
    size_t total = 0;
    for (int64_t i = 0; i < parts->len; i++) {
        char *s = mojo_list_get_str(parts, i);
        if (s) total += strlen(s);
        if (i < parts->len - 1) total += sep_len;
    }
    char *out = (char *)malloc(total + 1);
    if (!out) abort();
    char *p = out;
    for (int64_t i = 0; i < parts->len; i++) {
        char *s = mojo_list_get_str(parts, i);
        if (s) { size_t n = strlen(s); memcpy(p, s, n); p += n; }
        if (i < parts->len - 1) { memcpy(p, sep, sep_len); p += sep_len; }
    }
    *p = '\0';
    return out;
}

/* Is `c` safe to leave unquoted in a shell word, per CPython shlex.quote's
 * _find_unsafe = re.compile(r'[^\w@%+=:,./-]', re.ASCII) ? */
static int _mojo_shlex_char_safe(char c) {
    if ((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9'))
        return 1;
    switch (c) {
        case '_': case '@': case '%': case '+': case '=':
        case ':': case ',': case '.': case '/': case '-':
            return 1;
        default:
            return 0;
    }
}

/* POSIX-quote one element like CPython's shlex.quote(): empty string -> '',
 * a string with only "safe" characters is returned unchanged, otherwise
 * wrapped in single quotes with any embedded "'" replaced by '"'"'. */
static char *_mojo_shlex_quote_one(const char *s) {
    if (!s || s[0] == '\0') return "''";
    int needs_quoting = 0;
    for (const char *p = s; *p; p++) {
        if (!_mojo_shlex_char_safe(*p)) { needs_quoting = 1; break; }
    }
    if (!needs_quoting) return (char *)s;
    size_t len = strlen(s);
    size_t cap = len * 4 + 3; /* worst case: every char is a quote */
    char *out = (char *)malloc(cap);
    if (!out) return (char *)s;
    char *p = out;
    *p++ = '\'';
    for (size_t i = 0; i < len; i++) {
        if (s[i] == '\'') {
            /* close quote, escaped literal quote, reopen quote */
            *p++ = '\''; *p++ = '"'; *p++ = '\''; *p++ = '"'; *p++ = '\'';
        } else {
            *p++ = s[i];
        }
    }
    *p++ = '\'';
    *p = '\0';
    return out;
}

/* shlex.join(iterable): CPython's shlex.join is `" ".join(quote(s) for s in
 * split_command)` — a fixed space separator plus per-element POSIX quoting,
 * unlike str.join(iterable)'s arbitrary caller-supplied separator. */
char *mojo_shlex_join(MojoList *parts) {
    if (!parts || parts->len == 0) return "";
    size_t total = 0;
    char **quoted = (char **)malloc(sizeof(char *) * (size_t)parts->len);
    if (!quoted) return "";
    for (int64_t i = 0; i < parts->len; i++) {
        char *s = mojo_list_get_str(parts, i);
        char *q = _mojo_shlex_quote_one(s);
        quoted[i] = q;
        total += strlen(q);
        if (i < parts->len - 1) total += 1; /* space separator */
    }
    char *out = (char *)malloc(total + 1);
    if (!out) { free(quoted); return ""; }
    char *p = out;
    for (int64_t i = 0; i < parts->len; i++) {
        size_t n = strlen(quoted[i]);
        memcpy(p, quoted[i], n);
        p += n;
        if (i < parts->len - 1) *p++ = ' ';
    }
    *p = '\0';
    free(quoted);
    return out;
}

char *string_lower(char *str) {
    if (!str) return str;
    size_t len = strlen(str);
    char *lower = malloc(len + 1);
    if (!lower) return str;
    for (size_t i = 0; i < len; i++) {
        lower[i] = (str[i] >= 'A' && str[i] <= 'Z') ? (str[i] + 32) : str[i];
    }
    lower[len] = '\0';
    return lower;
}

char *string_upper(char *str) {
    if (!str) return str;
    size_t len = strlen(str);
    char *upper = malloc(len + 1);
    if (!upper) return str;
    for (size_t i = 0; i < len; i++) {
        upper[i] = (str[i] >= 'a' && str[i] <= 'z') ? (str[i] - 32) : str[i];
    }
    upper[len] = '\0';
    return upper;
}

/* `str.casefold()` — the Unicode caseless-folding form of `lower()`. Over
 * ASCII, which is all this representation carries (a `str` is a bare
 * `char *`), it is exactly `lower()`: every ASCII letter maps to its
 * lowercase counterpart and nothing else changes. The non-ASCII cases
 * (e.g. 'ß' -> 'ss', 'İ' -> 'i̇') are outside the representation and are
 * recorded as such on the str-side predicate tests rather than guessed at.
 * This existed because the method had no lowering at all and fell to the
 * generic unknown-method stub, printing a raw int 0. */
char *mojo_str_casefold(char *str) { return string_lower(str); }

char *mojo_str_swapcase(char *str) {
    if (!str) return str;
    size_t len = strlen(str);
    char *out = malloc(len + 1);
    if (!out) return str;
    for (size_t i = 0; i < len; i++) {
        char c = str[i];
        if (c >= 'a' && c <= 'z')      out[i] = (char)(c - 32);
        else if (c >= 'A' && c <= 'Z') out[i] = (char)(c + 32);
        else out[i] = c;
    }
    out[len] = '\0';
    return out;
}

/* `str.title()` — first character of each WORD upper, the rest lower. A
 * word boundary is here what CPython means: any character that is not
 * cased. That makes 'a1b'.title() == 'A1B' and 'a b'.title() == 'A B',
 * which is the rule `str.istitle()` (already implemented, via the shared
 * mojo_is_kind kernel) checks in the other direction. */
char *mojo_str_title(char *str) {
    if (!str) return str;
    size_t len = strlen(str);
    char *out = malloc(len + 1);
    if (!out) return str;
    int prev_uncased = 1;   /* the start of the string is a word boundary */
    for (size_t i = 0; i < len; i++) {
        char c = str[i];
        int cased = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z');
        if (prev_uncased && c >= 'a' && c <= 'z')      out[i] = (char)(c - 32);
        else if (prev_uncased && c >= 'A' && c <= 'Z') out[i] = c;
        else if (c >= 'A' && c <= 'Z')                 out[i] = (char)(c + 32);
        else if (c >= 'a' && c <= 'z')                 out[i] = c;
        else out[i] = c;
        prev_uncased = !cased;
    }
    out[len] = '\0';
    return out;
}

/* `str.capitalize()` — first character upper, ALL THE REST lower. Distinct
 * from title() in exactly that: 'aBC'.capitalize() is 'Abc'. */
char *mojo_str_capitalize(char *str) {
    if (!str) return str;
    size_t len = strlen(str);
    char *out = malloc(len + 1);
    if (!out) return str;
    for (size_t i = 0; i < len; i++) {
        char c = str[i];
        if (i == 0 && c >= 'a' && c <= 'z') out[i] = (char)(c - 32);
        else if (i > 0 && c >= 'A' && c <= 'Z') out[i] = (char)(c + 32);
        else out[i] = c;
    }
    out[len] = '\0';
    return out;
}

/* Real `hash(x)` builtin. `hash` was previously only a bare, never-defined
 * forward declaration in gimple_codegen.py's preamble (`_util_pairs`) —
 * compiled fine but failed to LINK ("undefined symbols: _hash") the moment
 * anything actually called it; found via Modules/_decimal/tests/bignum.py's
 * `pow(10, exp, _PyHASH_MODULUS)` sibling code (`xhash`) and importlib/
 * metadata/_text.py. mojo_hash_str hashes string CONTENT (reusing the same
 * FNV-1a _str_hash already used by MojoDict/MojoSet's own hash table, for
 * consistency — not real CPython's randomized SipHash, but stable across
 * calls within one run, which is all any real use of hash() here needs).
 * mojo_hash is the generic fallback for a statically-opaque argument
 * (codegen dispatches to mojo_hash_str/returns the value directly for a
 * STATICALLY known char* or int argument instead — see gimple_codegen.py's
 * `fname_raw == 'hash'` case — this is only reached when the static type
 * is unknown): mirrors _mojo_generic_elem_repr's existing heuristic for
 * telling a boxed pointer apart from a small int with no type tag of its
 * own (a real MojoList/MojoDict pointer has no stable content-based hash without
 * walking every element, so those hash by identity/address instead,
 * matching Python's own default object.__hash__ for unhashable-by-content
 * types rather than raising).
 */
int64_t mojo_hash_str(char *s) {
    return (int64_t)_str_hash(s);
}

int64_t mojo_hash(int64_t val) {
    if (val == 0) return 0;
    if (val > 65536) {
        if (mojo_is_registered_list(val) || mojo_is_registered_dict(val))
            return val;
        if (mojo_read_type_tag_safe(val) != 0)
            return val;
        return mojo_hash_str((char *)(intptr_t)val);
    }
    return val;
}

/* ── Generic Python-object dynamic-attribute storage ───────────────────────
 * Reached whenever codegen couldn't statically resolve obj.attr to a real
 * struct field (see gimple_codegen.py's `_mojo_dispatch_getattr`/
 * `_mojo_dispatch_setattr`, which try every known struct's own tagged
 * accessor first and fall through to these two only when no tag matches —
 * a bare/opaque `cls`/`self`/third-party-object value, or a genuinely NEW
 * attribute this compiler has no struct layout for; see bugs/hard/CODEGEN_
 * dynamic_attribute_on_generic_object.md, Steps 1-3).
 *
 * Real per-object storage: obj-pointer -> its own dynamic-attribute
 * MojoDict, keyed by the pointer's hex text (reuses MojoDict's existing
 * string-keyed hash table rather than a second, pointer-keyed hash table
 * implementation from scratch for what is deliberately a RARE fallback
 * path, not a hot one — ordinary struct field access never reaches here).
 * Lazily allocated (a program that never hits this path never allocates
 * it). Intentionally never freed when `obj` itself is freed — this runtime
 * has no object-lifetime/refcounting/GC story anywhere else either
 * (no `free()` paired with any struct allocator in gimple_codegen.py's
 * `_alloc_*` emission), so a leaked per-object dict here is consistent
 * with the rest of this runtime's existing memory model, not a new
 * regression. */
static MojoDict *_mojo_dynattr_objects = NULL;

static void _mojo_dynattr_key(void *obj, char *buf, size_t buflen) {
    snprintf(buf, buflen, "%p", obj);
}

/* A real, catchable AttributeError — same runtime call sequence compiled
 * `raise AttributeError(...)` itself lowers to (see gimple_codegen.py's
 * _gen_stmt_RaiseStmt: mojo_exc_type_set + mojo_exc_msg_set +
 * mojo_exc_obj_set + mojo_raise), so a compiled `except AttributeError:`
 * around a missing dynamic attribute genuinely matches this, not just the
 * lenient untagged-exception fallback. The tag is `gimple_codegen.py`'s
 * own `GimpleGen._exc_type_id('AttributeError')` — `(zlib.crc32(b"Attrib
 * uteError") & 0x7fffffff) or 1` — computed once in Python and hardcoded
* here rather than reimplementing CRC32 in C, since _exc_type_id is a
  * pure, deterministic function of the class name string (documented on
  * its own definition: stable across processes so the CAS content-cache
  * doesn't see spurious id churn) and this runtime is compiled once,
  * separately from any particular program's own GimpleGen instance. */

void mojo_raise_file_not_found(char *path) {
    /* Real Python's `open(path)` on a missing file raises
     * FileNotFoundError (an OSError subclass), it does NOT return a
     * falsy handle — callers' `try: ... except Exception:` guards only
     * work if the failure actually raises. Previously this returned 0,
     * which int_read(0) silently turned into an empty read, so e.g.
     * mojo.py's own "Error reading {input_file}" guard never fired and
     * every downstream step ran on empty source. */
    char msg[512];
    snprintf(msg, sizeof msg, "[Errno 2] No such file or directory: '%s'",
             path ? path : "?");
    char *heap_msg = strdup(msg);
    mojo_exc_type_set(_MOJO_EXC_TAG_FILENOTFOUND);
    mojo_exc_msg_set(heap_msg);
    mojo_exc_obj_set(heap_msg);
    mojo_raise();
}

void mojo_raise_attribute_error(char *attr) {
    char msg[256];
    snprintf(msg, sizeof msg, "AttributeError: %s", attr ? attr : "?");
    char *heap_msg = strdup(msg);
    mojo_exc_type_set(_MOJO_EXC_TAG_ATTRIBUTEERROR);
    mojo_exc_msg_set(heap_msg);
    mojo_exc_obj_set(heap_msg);
    mojo_raise();
}

/* Real `KeyError: 'k'` — same typed-exception mechanism as
 * mojo_raise_attribute_error just above (the tag is `(zlib.crc32(b"KeyError")
 * & 0x7fffffff) or 1`, computed once in Python and hardcoded here for the
 * same documented stability reason). Raised by mojo_str_format_dict on a
 * missing key, matching real Python's dict-keyed %-formatting. */
#define _MOJO_EXC_TAG_KEYERROR 1044929265

void mojo_raise_key_error(char *key) {
    char msg[256];
    snprintf(msg, sizeof msg, "KeyError: %s", key ? key : "?");
    char *heap_msg = strdup(msg);
    mojo_exc_type_set(_MOJO_EXC_TAG_KEYERROR);
    mojo_exc_msg_set(heap_msg);
    mojo_exc_obj_set(heap_msg);
    mojo_raise();
}

/* Real `TypeError: <detail>` — the same typed-exception mechanism as
 * mojo_raise_attribute_error / mojo_raise_key_error above, with the same
 * hardcoded-tag rationale (the tag is `(zlib.crc32(b"TypeError") &
 * 0x7fffffff) or 1`).
 *
 * It exists for the one shape the codegen used to answer with a SILENT wrong
 * value: calling an attribute that is not callable, on a type whose attribute
 * namespace the codegen models as CLOSED. The canonical case is
 * `struct.Struct.format` — in real Python that is a getset descriptor holding
 * the format STRING (there is no `Struct.format` method for it to shadow; the
 * struct module has no formatting entry point at all), so `s.format` reads as
 * a `str` and `s.format(70)` is a TypeError. Before this existed, such a call
 * became mojo_obj_call1() — a hardcoded `return 0` — and returned 0 with exit
 * 0. `detail` is the tail CPython puts after "TypeError: ", e.g. "'str' object
 * is not callable". */
void mojo_raise_type_error(char *detail) {
    char msg[256];
    snprintf(msg, sizeof msg, "TypeError: %s", detail ? detail : "?");
    char *heap_msg = strdup(msg);
    mojo_exc_type_set(_MOJO_EXC_TAG_TYPEERROR);
    mojo_exc_msg_set(heap_msg);
    mojo_exc_obj_set(heap_msg);
    mojo_raise();
}

/* `ValueError: <detail>` — same sequence, same tag derivation, next to its
 * three siblings above. Needed because an operation that REJECTS ITS
 * ARGUMENT is not one of those three: mojo_bytes_partition on an empty
 * separator is the live caller. */
void mojo_raise_value_error(char *detail) {
    char msg[256];
    snprintf(msg, sizeof msg, "ValueError: %s", detail ? detail : "?");
    char *heap_msg = strdup(msg);
    mojo_exc_type_set(_MOJO_EXC_TAG_VALUEERROR);
    mojo_exc_msg_set(heap_msg);
    mojo_exc_obj_set(heap_msg);
    mojo_raise();
}

/* `IndexError: <detail>` — the fifth typed raiser, same mechanism and same
 * hardcoded-tag derivation as the four above. Needed because an
 * out-of-range read used to answer a VALUE: `b'abc'[10]` and `b''[0]`
 * printed 0 with exit 0, and 0 is a real byte value, so
 * `if b[i] == 0:` on a short buffer silently took the true branch. */
#define _MOJO_EXC_TAG_INDEXERROR 635713773

void mojo_raise_index_error(char *detail) {
    char msg[256];
    snprintf(msg, sizeof msg, "IndexError: %s", detail ? detail : "?");
    char *heap_msg = strdup(msg);
    mojo_exc_type_set(_MOJO_EXC_TAG_INDEXERROR);
    mojo_exc_msg_set(heap_msg);
    mojo_exc_obj_set(heap_msg);
    mojo_raise();
}

/* The two ways a tuple refuses to be mutated, as CPython words them. Both
 * share mojo_require_mutable_list's typed-exception mechanism and the same
 * hardcoded-tag derivation as the four raisers above; they live here rather
 * than next to that call because their TEXT is a property of the tuple
 * marker, and the marker is declared ~5000 lines earlier (its definition is
 * forward-declared there for exactly this reason).
 *
 * `attr` non-NULL is the method form — `'tuple' object has no attribute
 * 'append'`, an AttributeError, because in CPython the failure is the
 * attribute lookup itself. NULL is the item form, a TypeError, and the two
 * halves of it are disambiguated by `verb`: assignment and deletion are
 * separate messages in CPython and a `try/except` in real code can tell
 * them apart. */
static void mojo_raise_tuple_no_attr(const char *attr) {
    char msg[160];
    snprintf(msg, sizeof msg, "'tuple' object has no attribute '%s'",
             attr ? attr : "?");
    char *heap_msg = strdup(msg);
    mojo_exc_type_set(_MOJO_EXC_TAG_ATTRIBUTEERROR);
    mojo_exc_msg_set(heap_msg);
    mojo_exc_obj_set(heap_msg);
    mojo_raise();
}

static void mojo_raise_tuple_item_error(const char *verb) {
    char msg[160];
    if (verb)
        snprintf(msg, sizeof msg, "'tuple' object %s", verb);
    else
        snprintf(msg, sizeof msg, "'tuple' object does not support item assignment");
    char *heap_msg = strdup(msg);
    mojo_exc_type_set(_MOJO_EXC_TAG_TYPEERROR);
    mojo_exc_msg_set(heap_msg);
    mojo_exc_obj_set(heap_msg);
    mojo_raise();
}

/* Reads a dynamically-set attribute from `obj`'s own per-object dict (see
 * above). No matching struct-field tag AND no dynamic attribute of this
 * name ever set on this exact object -> a real AttributeError, matching
 * Python's own `obj.missing_attr` behavior (this is exactly the case the
 * bug doc's own minimal repro's `try: ... except AttributeError:` idiom
 * depends on). Previously: silently printed a warning and returned 0 —
 * that behavior is preserved nowhere now; a program relying on the old
 * "always returns 0" non-error needs updating (there was never a
 * legitimate reason to depend on it — it was an unimplemented stub, not
 * a documented feature). */
/* When non-zero, mojo_obj_getattr returns MOJO_ATTR_MISSING for an absent
 * attribute instead of raising — set by the compiled 3-arg getattr lowering
 * around its dispatch call so the caller's default can be substituted. Not
 * thread-shared state that needs a lock: the flag is set and cleared within
 * a single straight-line lowering with no call that could re-enter getattr
 * on another thread's behalf. */
int _mojo_getattr_nothrow = 0;
int _mojo_getattr_missed = 0;

int64_t mojo_obj_getattr(void *obj, char *attr) {
    if (_mojo_dynattr_objects) {
        char key[32];
        _mojo_dynattr_key(obj, key, sizeof key);
        int64_t handle = mojo_dict_get_int(_mojo_dynattr_objects, key);
        if (handle) {
            MojoDict *attrs = (MojoDict *)(intptr_t)handle;
            if (mojo_dict_contains(attrs, attr))
                return mojo_dict_get_int(attrs, attr);
        }
    }
    if (_mojo_getattr_nothrow) {
        _mojo_getattr_missed = 1;
        return 0;
    }
    if (getenv("MOJO_ATTR_DBG")) {
        int64_t tag = mojo_read_type_tag_safe((int64_t)(intptr_t)obj);
        fprintf(stderr, "MOJO_ATTR_DBG: getattr '%s' miss on obj=%p tag=%lld\n",
                attr ? attr : "?", obj, (long long)tag);
    }
    mojo_raise_attribute_error(attr);
    return 0;  /* unreached: mojo_raise_attribute_error always raises (mojo_raise
                  either longjmps into an enclosing try, or exit(1)s if none is
                  active — see mojo_raise's own doc comment) */
}

/* Reached whenever _gen_for_iter (gimple_codegen.py) couldn't statically
 * resolve `for x in y:`'s iterable to a known container/struct-iterator
 * shape. That fallback used to just emit a "TODO" comment and drop
 * the ENTIRE loop body silently -- zero iterations, no error, no crash --
 * which is how `for m in _TOKEN_RE.finditer(s):` in mojo_compiler.py's own
 * py_tokenize (a regex .finditer() call, which has no codegen lowering at
 * all -- see BACKLOG-CODEGEN.md) silently produced an EMPTY token stream
 * for every self-hosted `.tok`/`.ast` dump instead of a visible failure.
 *
 * Unlike mojo_obj_getattr's abort() (a "should never happen, this is an
 * internal compiler bug" case), this fires for a legitimate, cataloged
 * feature gap that real compiled programs can legitimately hit and
 * recover from (mojo.py's own `.tok`/`.ast` generation wraps the call in a
 * try/except specifically anticipating this). abort() raises SIGABRT,
 * which no Mojo-level try/except can catch, so it would take down the
 * WHOLE process instead of just failing the one diagnostic step -- a
 * worse regression than the silent-empty-loop it replaces. So: print
 * loudly (visible, greppable), but let execution continue with the same
 * zero-iterations behavior as before. */
/* A CALLABLE-VALUED parameter default naming an IMPORTED module's function
   (`def probe(x, *, g=os.walk): return g(x)`). `_callable_value_symbol`
   answers "what C symbol does a function used as a value mean" for a BARE
   NAME this compile lowered; it cannot answer for a `module.attr` reference,
   because whether `os.walk` was compiled into this translation unit at all is
   a property of the whole import closure, not of the expression. The old
   answer was the `('int', '0')` fallback in `_default_expr_to_pair`, so `g`
   arrived as address 0 and `mojo_fnptr_call_1((void *)0, ...)` called through
   a null pointer: SIGSEGV, exit 139, no output.

   This is that case's honest answer, and it follows
   `mojo_unsupported_iter`'s convention exactly: print loudly, and let
   execution continue with the same behaviour the null pointer would have
   produced had it survived — so a program that never CALLS the parameter is
   completely unaffected, and one that does gets a greppable diagnostic
   instead of a signal.

   ONE function, not a family per arity, because the call reaches it through
   `mojo_fnptr_call_N`'s `int64_t (*)(int64_t...)` cast: a callee that
   declares no parameters simply does not read the arguments the caller
   passes, on every ABI this runtime targets. So `int64_t
   mojo_unavailable_callable(void)` is a correct target for arities 0 through
   4 alike, and returns a real 0 for the boxed result.

   The name is armed by the call site immediately before the call, which is
   why it is a separate setter rather than an argument: a `void (*)(void)`
   target cannot be passed one, and the alternative — one weak stub per
   referenced name — is the machinery the existing
   `_unsupported_generator_names` weak stubs already provide, which this is
   deliberately not duplicating. */
static const char *_unavailable_callable_name = "?";
static int _unavailable_callable_reported = 0;

void mojo_set_unavailable_callable_name(const char *name) {
    _unavailable_callable_name = name ? name : "?";
    _unavailable_callable_reported = 0;
}

int64_t mojo_unavailable_callable(void) {
    if (!_unavailable_callable_reported) {
        _unavailable_callable_reported = 1;
        fprintf(stderr, "mojo_unavailable_callable: '%s' is a callable that is "
                         "not available in compiled mode (it names an imported "
                         "module's function, which this translation unit may "
                         "not contain); calling it returns 0\n",
                _unavailable_callable_name);
    }
    return 0;
}

void *mojo_unavailable_callable_ptr(void) { return (void *)mojo_unavailable_callable; }

void mojo_unsupported_iter(const char *type_name) {
    fprintf(stderr, "mojo_unsupported_iter: 'for' loop over unsupported iterable "
                     "type %s (codegen has no lowering for this container/iterator "
                     "shape; the loop body runs zero times)\n", type_name ? type_name : "?");
}


/* Weak fallback: overridden by the compiled gimple_codegen closure's own
 * strong `compile_to_gimple` in a self-hosted `mojoc`. Every compiled Mojo
 * program links `fire_runtime.c`, and `gimple_codegen_compile_to_gimple`
 * below unconditionally references `compile_to_gimple` — this weak stub is
 * the ONLY thing that keeps a standalone link of just this runtime (no
 * compiled gimple_codegen closure at all, e.g. test_module_cache.py's
 * stage1 extern-boundary check, test_runner.py, build_stdlib_dylib.py's
 * dylib builds) from failing with an undefined-symbol link error. None of
 * those actually CALL gimple_codegen_compile_to_gimple at runtime (only
 * fire.py's own --dump/--dump-full/build_executable driver code, and the
 * compiler's own bootstrap sources mojo.mojo/scripts/stage2_mojo_
 * interpreter.mojo, ever contain a literal `gimple_codegen.compile_to_
 * gimple(...)` call), so this weak stub returning NULL is never actually
 * exercised as "the real answer" by anything that ships — only as a link-
 * time placeholder. Keep this even though the python3 subprocess fallback
 * that used to sit below it is gone (see gimple_codegen_compile_to_gimple's
 * own comment). */
__attribute__((weak)) char *compile_to_gimple(char *src, int do_imports, char *filename) {
    (void)src; (void)do_imports; (void)filename;
    return (char *)0;
}

char *gimple_codegen_compile_to_gimple(char *src, int do_imports, char *filename) {
    /*
     * Always call the compiled `compile_to_gimple` closure directly — no
     * subprocess, ever, under any circumstance. This used to fall back to
     * spawning `python3 -c "import gimple_codegen; ..."` (gated by
     * MOJO_NO_SHIM, or when this binary had no compiled closure at all);
     * that subprocess path is deleted entirely now that check-native-
     * dumpfull (formerly check-noshim-dumpfull) has proven the self-hosted
     * binary's own native compile_to_gimple produces byte-identical output
     * to the python3-interpreted reference for fire.py's whole transitive
     * closure. The weak stub above returns NULL when this binary has no
     * compiled gimple_codegen closure at all (see its own comment) — in
     * that case, return a valid-but-minimal stub .ci instead of ever
     * touching python3.
     */
    char *native = compile_to_gimple(src, do_imports, filename);
    if (native) return native;

    static char *result_buf = NULL;
    static size_t result_cap = 0;
    if (!result_buf) { result_cap = 1 << 12; result_buf = malloc(result_cap); }
    snprintf(result_buf, result_cap,
        "/* gimple_codegen_compile_to_gimple: no compiled compile_to_gimple "
        "in this binary (not a self-hosted build) */\n"
        "#include \"fire_runtime.h\"\n"
        "int _gimple_main(void) { return 0; }\n"
        "int main(int argc, char **argv) {\n"
        "  mojo_set_argv(argc, argv);\n"
        "  return _gimple_main();\n"
        "}\n");
    return result_buf;
}

/* Flattened method calls */
char *int_read(int64_t fh) {
    /* Read all content from file handle (MojoFileHandle as int64_t) */
    if (fh == 0) return NULL;
    FILE *f = (FILE *)(intptr_t)fh;
    size_t cap = 4096, len = 0;
    char *buf = malloc(cap);
    if (!buf) return NULL;
    for (;;) {
        if (len + 4096 > cap) { cap *= 2; buf = realloc(buf, cap); }
        ssize_t n = fread(buf + len, 1, cap - len - 1, f);
        if (n == 0) break;
        len += (size_t)n;
    }
    buf[len] = '\0';
    return buf;
}

int64_t int_write(int64_t fh, char *data) {
    if (fh > 0 && data) {
        FILE *f = (FILE *)(intptr_t)fh;
        fputs(data, f);
    }
    return 0;
}

int64_t int_parse_module(int parser) {
    /* Return empty statement list — parse happens in gimple_codegen layer */
    return (intptr_t)mojo_list_new();
}


/* ── Additional dict/list/set runtime helpers ──────────────────────────── */

MojoList *mojo_dict_keys(MojoDict *d) {
    /* Walks in insertion order (mojo_dict_order_indices), matching Python's
     * dict.keys() guarantee — not raw hash-slot order. */
    MojoList *out = mojo_list_new();
    if (!d) return out;
    int64_t *order = mojo_dict_order_indices(d);
    for (int64_t oi = 0; oi < d->used; oi++)
        mojo_list_append_str(out, _slot_key(&d->slots[order[oi]]));
    free(order);
    return out;
}

MojoList *mojo_dict_values(MojoDict *d) {
    /* Insertion order — see mojo_dict_keys's identical note. */
    MojoList *out = mojo_list_new();
    if (!d) return out;
    int64_t *order = mojo_dict_order_indices(d);
    for (int64_t oi = 0; oi < d->used; oi++)
        mojo_list_append_int(out, d->slots[order[oi]].val);
    free(order);
    return out;
}

MojoList *mojo_dict_items(MojoDict *d) {
    /* A list of (key, value) 2-element sub-lists — NOT a flat alternating
     * key/value list (the previous shape here). gimple_codegen.py's
     * `for k, v in d.items():` tuple-target lowering (_gen_for_list's
     * is_tuple branch) already unconditionally expects each top-level
     * element to itself be a MojoList* it can index into for k/v — the
     * flat shape meant it read the KEY's own char* bytes as if they were a
     * MojoList struct's internal fields, corrupting memory (crash: reading
     * a struct-valued dict's value came out as garbage, since the "value"
     * offset landed inside the key string's data instead of a real value
     * slot — found via mojo_compiler.py's own `_parse_postfix`, whose
     * `keywords: dict = {}` stores parsed expression nodes as values).
     * Also walks in insertion order now (mojo_dict_order_indices) — a
     * literal `Foo(**{k1: v1, k2: v2})`-style keyword-argument dict built
     * via `[(k, v) for k, v in keywords.items()]` (mojo_compiler.py's own
     * _parse_postfix) needs its arguments back in the order they were
     * written, not raw hash-slot order, or a compiled AST dump reorders a
     * call's own keyword arguments. */
    MojoList *out = mojo_list_new();
    if (!d) return out;
    int64_t *order = mojo_dict_order_indices(d);
    for (int64_t oi = 0; oi < d->used; oi++) {
        int64_t i = order[oi];
        MojoList *pair = mojo_list_new();
        mojo_list_append_str(pair, _slot_key(&d->slots[i]));
        mojo_list_append_int(pair, d->slots[i].val);
        /* Same reason as mojo_zip's: `dict.items()` yields (key, value)
         * TUPLES, so mark them — `print({"a": 1}.items())` printed
         * `[['a', 1]]` without this. */
        mojo_mark_as_tuple(pair);
        mojo_list_append_int(out, (int64_t)(intptr_t)pair);
    }
    free(order);
    return out;
}

/* dict.items() of a Dict[Int, V]: the same [key, value] pairs, with the key
 * slot an INTEGER (read it with mojo_list_get_int). Only for consumers that
 * know the dict is integer-keyed — every other reader of an items pair
 * assumes a string in slot 0. */
MojoList *mojo_dict_items_int(MojoDict *d) {
    MojoList *out = mojo_list_new();
    if (!d) return out;
    int64_t *order = mojo_dict_order_indices(d);
    for (int64_t oi = 0; oi < d->used; oi++) {
        _DictSlot *s = &d->slots[order[oi]];
        MojoList *pair = mojo_list_new();
        mojo_list_append_int(pair, s->keykind == 2 ? s->ikey
                             : (s->key ? (int64_t)strtoll(s->key, NULL, 10) : 0));
        mojo_list_append_int(pair, s->val);
        mojo_mark_as_tuple(pair);
        mojo_list_append_int(out, (int64_t)(intptr_t)pair);
    }
    free(order);
    return out;
}

void mojo_dict_update(MojoDict *dst, MojoDict *src) {
    if (!dst || !src) return;
    /* Walks the SOURCE in INSERTION order (mojo_dict_order_indices), not raw
     * hash-slot order. A dict's iteration order and repr are insertion order,
     * and each re-inserted pair takes a FRESH sequence number in the
     * destination (seq = -1 below), so the destination's order became the
     * source's slot order: `{str(i) + str(j): i for i in range(2) for j in
     * range(2)}` printed `{'01': 1, '00': 1}` where CPython prints
     * `{'00': 1, '01': 1}`. `d.update(other)` merges in the source's order for
     * the same reason. Each pair keeps its own `keykind`/`kind`, so an
     * integer-keyed pair stays integer-keyed and a string value stays a
     * string. */
    int64_t *order = mojo_dict_order_indices(src);
    int64_t n = order ? src->used : 0;
    for (int64_t oi = 0; oi < n; oi++) {
        _DictSlot *s = &src->slots[order[oi]];
        if (!s->key) continue;
        if (s->keykind == 2)
            _dict_set_ik(dst, s->ikey, s->val, s->kind);
        else
            _dict_set_raw_seq_kind_k(dst, s->key, s->val, -1, s->kind, s->keykind);
    }
    free(order);
}

/* dict.setdefault(key, default): return the value for `key`, inserting
 * `default` first when `key` is absent. Matches CPython's setdefault
 * (mutates the dict, returns whatever the value now is). */
int64_t mojo_dict_setdefault_int(MojoDict *d, char *key, int64_t dflt) {
    if (!d) return dflt;
    if (mojo_dict_contains(d, key)) return mojo_dict_get_int(d, key);
    mojo_dict_set_int(d, key, dflt);
    return dflt;
}

char *mojo_dict_setdefault_str(MojoDict *d, char *key, char *dflt) {
    if (!d) return dflt;
    if (mojo_dict_contains(d, key)) return mojo_dict_get_str(d, key);
    mojo_dict_set_str(d, key, dflt);
    return dflt;
}

/* Remove the entry at slot `sl` (a pointer INTO d->slots) by rebuilding the
 * table without it. The slot is identified by address, not by comparing keys:
 * an integer slot and a string slot of the same characters cannot be told apart
 * by strcmp. */
static void _dict_remove_slot(MojoDict *d, _DictSlot *sl) {
    int64_t cap = d->cap;
    int64_t skip = (int64_t)(sl - d->slots);
    /* Move every entry out to a scratch copy, clear the table in place, and
     * move the survivors back: a slot moves WHOLE, so its key (a lazy integer
     * sentinel or an owned string) travels with it and nothing is re-hashed
     * from text. The table itself is unchanged, which is what lets the first,
     * inline table be rebuilt without a second one to put it in. */
    _DictSlot *tmp = (_DictSlot *)malloc((size_t)cap * sizeof(_DictSlot));
    memcpy(tmp, d->slots, (size_t)cap * sizeof(_DictSlot));
    memset(d->slots, 0, (size_t)cap * sizeof(_DictSlot));
    d->used = 0;
    uint64_t mask = (uint64_t)cap - 1;
    for (int64_t i = 0; i < cap; i++) {
        if (!tmp[i].key || i == skip) continue;
        uint64_t j = (tmp[i].keykind == 2 ? _ik_hash(tmp[i].ikey)
                                          : _str_hash(tmp[i].key)) & mask;
        while (d->slots[j].key) j = (j + 1) & mask;
        d->slots[j] = tmp[i];
        d->used++;
    }
    if (tmp[skip].key) _slot_free_key(&tmp[skip]);
    free(tmp);
}

/* Remove the entry for `key` in the given key DOMAIN (see _DictSlot.keykind)
 * and return its value (0 when absent). */
static int64_t _dict_pop_k(MojoDict *d, char *key, int64_t keykind) {
    if (!d) return 0;
    _DictSlot *sl = _dict_lookup_k(d, key, keykind);
    if (!sl) return 0;
    int64_t val = sl->val;
    /* This table is plain linear-probing open addressing with NO tombstones
     * (_dict_find/_dict_lookup stop scanning at the first empty slot), so
     * just clearing this one slot would break the probe chain for any OTHER
     * key that hashed to the same bucket and got pushed past it — a later
     * lookup for that key would stop at the now-empty slot and report "not
     * found" even though the key is still in the table. Correct in-place
     * deletion needs Knuth's backward-shift algorithm; rebuilding the whole
     * slot array from scratch (mirrors _dict_grow's own rehash loop, minus
     * the size doubling) is simpler to get right and this table is never
     * large enough for the O(cap) cost to matter. Preserves each surviving
     * key's original `seq` so insertion-order dump/iteration is unaffected. */
    _dict_remove_slot(d, sl);
    return val;
}

int64_t mojo_dict_pop_int(MojoDict *d, char *key) {
    return _dict_pop_k(d, key, 0 /* str key */);
}

MojoDict *mojo_dict_copy(MojoDict *d) {
    MojoDict *out = mojo_dict_new();
    if (d) mojo_dict_update(out, d);
    return out;
}

/* `a | b` dict union (Python/Mojo Dict.__or__): a new dict with a's
 * entries overridden by b's on key collision. `b`'s values win, matching
 * mojo_dict_update's "src overwrites dst" semantics. */
MojoDict *mojo_dict_union(MojoDict *a, MojoDict *b) {
    MojoDict *out = mojo_dict_copy(a);
    if (b) mojo_dict_update(out, b);
    return out;
}

MojoDict *mojo_dict_from_pairs(MojoList *pairs) {
    MojoDict *out = mojo_dict_new();
    if (!pairs) return out;
    for (int64_t i = 0; i < pairs->len; i++) {
        MojoList *pair = (MojoList *)pairs->data[i];
        if (!pair || pair->len < 2) continue;
        char *key = (char *)pair->data[0];
        int64_t val = pair->data[1];
        mojo_dict_set_int(out, key, val);
    }
    return out;
}

MojoList *mojo_list_copy(MojoList *l) {
    MojoList *out = mojo_list_new();
    if (!l) return out;
    for (int64_t i = 0; i < l->len; i++)
        mojo_list_append_int(out, l->data[i]);
    /* A slot-for-slot copy, so the result describes its slots exactly as
     * `l` does — see mojo_list_inherit_kinds. */
    mojo_list_inherit_kinds(out, l);
    /* The tuple marker is deliberately NOT propagated: `t.copy()` does not
     * exist on a Python tuple (it is an AttributeError there), and
     * `list.copy()` on a real list yields a list. This helper backs BOTH —
     * `list(t)` goes through _lower_builtin_list's copy branch — so
     * propagating would make `list((1,2))` print `(1, 2)`. The opposite of
     * mojo_list_slice / mojo_list_concat / mojo_list_repeat, which preserve
     * it. */
    return out;
}

int mojo_list_all(MojoList *l) {
    if (!l) return 1;
    for (int64_t i = 0; i < l->len; i++)
        if (!l->data[i]) return 0;
    return 1;
}

int mojo_list_any(MojoList *l) {
    if (!l) return 0;
    for (int64_t i = 0; i < l->len; i++)
        if (l->data[i]) return 1;
    return 0;
}

/* all()/any()/sum() over a `bytes` (or `bytearray`) object. Iterating bytes
 * yields its INTEGERS, not one-character strings and not the object itself,
 * so these cannot go through the list helpers above: a bytes value is a
 * `MojoBytes *` and its elements are `b->data[i]`.
 *
 * These existed because every such call fell to the codegen's constant stub
 * instead — `all(b'abc')` answered 0 (CPython: True) and `sum(b'abc')`
 * answered a heap-pointer decimal (CPython: 294), both with exit 0. A
 * wrong ANSWER, not an error, and a plausible-looking one: the 0 is what
 * `all` of an empty iterable is, and the decimal is what an int prints. */
int mojo_bytes_all(MojoBytes *b) {
    /* Every element of a bytes object is a non-empty one, so a bytes
     * object is truthy-valued throughout: all(b'') is True (the empty
     * iterable) and all(b'\x00...') is True (0 is not None/False here). */
    (void)b;
    return 1;
}

int mojo_bytes_any(MojoBytes *b) {
    /* any() asks whether ANY ELEMENT is truthy, and an element of a bytes
     * object is an int in 0-255 — where 0 IS falsy. So this is not
     * "is the container non-empty": `any(b'\x00')` is False in CPython and
     * answered True here. (b'' is a separate case and agrees either way:
     * an empty iterable has no truthy element.) */
    for (int64_t i = 0; i < b->len; i++) if (b->data[i]) return 1;
    return 0;
}

int64_t mojo_bytes_sum(MojoBytes *b) {
    int64_t s = 0;
    for (int64_t i = 0; i < b->len; i++) s += b->data[i];
    return s;
}

/* `reversed(b)` — the iterator's elements, as a list of ints, matching
 * `list(reversed(b'abc'))` == [99, 98, 97]. Was `[]`: the reversed() path
 * only knew MojoList, so a bytes argument produced an empty list. */
MojoList *mojo_bytes_reversed_list(MojoBytes *b) {
    MojoList *out = mojo_list_new();
    if (!b) return out;
    for (int64_t i = b->len - 1; i >= 0; i--)
        mojo_list_append_int(out, (int64_t)b->data[i]);
    return out;
}

/* `sorted(b)` — the bytes' values in ascending order (CPython returns a
 * list of ints). Was a crash for a bytes argument (the sort path read the
 * object as a MojoList header). */
MojoList *mojo_bytes_sorted_list(MojoBytes *b) {
    MojoList *out = mojo_bytes_reversed_list(b);
    /* An insertion sort over int64_t slots: a MojoList carries no per-slot
     * comparator, and the values here are plain bytes, so the simplest
     * correct ordering is also the cheapest to be right about. */
    for (int64_t i = 1; i < out->len; i++) {
        int64_t key = out->data[i];
        int64_t j = i - 1;
        while (j >= 0 && out->data[j] > key) { out->data[j + 1] = out->data[j]; j--; }
        out->data[j + 1] = key;
    }
    return out;
}

int mojo_bytes_max(MojoBytes *b) {
    if (!b || b->len == 0) {
        char detail[96];
        snprintf(detail, sizeof detail, "max() arg is an empty sequence");
        mojo_raise_value_error(detail);
    }
    uint8_t m = b->data[0];
    for (int64_t i = 1; i < b->len; i++) if (b->data[i] > m) m = b->data[i];
    return (int)m;
}

int mojo_bytes_min(MojoBytes *b) {
    if (!b || b->len == 0) {
        char detail[96];
        snprintf(detail, sizeof detail, "min() arg is an empty sequence");
        mojo_raise_value_error(detail);
    }
    uint8_t m = b->data[0];
    for (int64_t i = 1; i < b->len; i++) if (b->data[i] < m) m = b->data[i];
    return (int)m;
}

/* Python list.pop(index=-1): removes and returns the element at `idx`
 * (negative indices count from the end), shifting later elements down.
 * mojo_list_pop(l) (no index) used to be the only implementation, always
 * popping the last element regardless of any index argument codegen passed
 * it — a real bug: `argv.pop(1)` (removing a specific flag/token, not the
 * last one) silently popped the wrong element instead. */
int64_t mojo_list_pop_at(MojoList *l, int64_t idx) {
    if (!l || l->len == 0) return 0;
    mojo_require_mutable_list(l, "pop");
    idx = _norm_idx(l, idx);
    if (idx < 0 || idx >= l->len) return 0;
    int64_t val = l->data[idx];
    for (int64_t i = idx; i < l->len - 1; i++) l->data[i] = l->data[i + 1];
    l->len--;
    return val;
}

int64_t mojo_list_pop(MojoList *l) {
    return mojo_list_pop_at(l, -1);
}

/* `del lst[i]` — the ITEM DELETION spelling, distinct from `lst.pop(i)`
 * even though both remove an element. They are one C operation
 * (mojo_list_pop_at) but two different Python operations, and CPython's
 * answers differ in both exception TYPE and text:
 *
 *   del (1,2)[0]  -> TypeError: 'tuple' object doesn't support item deletion
 *   (1,2).pop(0)  -> AttributeError: 'tuple' object has no attribute 'pop'
 *
 * so the deletion guard cannot live in mojo_list_pop_at (whose 'pop' is
 * right for the method form and wrong here). This is the deletion entry
 * point the `del` lowering calls instead. */
int64_t mojo_list_delitem(MojoList *l, int64_t idx) {
    if (!l || l->len == 0) return 0;
    if (mojo_is_tuple(l)) mojo_raise_tuple_item_error("doesn't support item deletion");
    return mojo_list_pop_at(l, idx);
}

void mojo_list_extend(MojoList *dst, MojoList *src) {
    if (!dst || !src) return;
    /* Checked here rather than left to mojo_list_append_int below: an EMPTY
     * src would otherwise append nothing and return without ever reaching
     * the guard, so `t.extend([])` on a tuple would succeed. */
    mojo_require_mutable_list(dst, "extend");
    for (int64_t i = 0; i < src->len; i++)
        mojo_list_append_int(dst, src->data[i]);
    /* `dst` now holds every slot `src` held, so `src`'s element repr describes
     * it — the same argument as `mojo_list_inherit_kinds`, which extend does
     * not call because the destination is not fresh. Only when `dst` has none:
     * a destination that was built with its own is the better answer, and a
     * mixed result (extend a list of P with a list of Q) has no single one,
     * which is the pre-existing behaviour. */
    if (!mojo_list_repr_elem(dst, 0)) {
        _KindRow *sr = _kinds_row((uint64_t)(uintptr_t)src);
        if (sr && sr->repr_fn) mojo_list_set_elem_repr(dst, (void *)sr->repr_fn);
    }
}

/* ── list.sort() / sorted(): ONE ordering primitive ───────────────────────
 *
 * Everything that orders a list in this file goes through _mojo_permute_by
 * below — mojo_list_sort (`l.sort()`), mojo_sorted (`sorted(x)`), 
 * mojo_list_sorted_str (`sorted(<strings>)`) and mojo_sorted_by_keys
 * (`sorted(x, key=f)`).  They used to be four hand-written loops over the same
 * question, which is how `l.sort()` came to be the one that was a STUB:
 * void mojo_list_sort(MojoList *l) { (void)l; } returned the list in its
 * original order, exit 0, saying nothing.  A program that sorted and then read
 * the list back got silently wrong data.
 *
 * `kind` is one byte of the mojo_list_set_kinds alphabet (MOJO_KIND_* in
 * fire_runtime.h): what a slot HOLDS.  A MojoList slot is a raw int64_t, so
 * ordering the slots as integers orders a list of strings by ADDRESS — which
 * is both non-deterministic across runs and different from Python's
 * alphabetical order.  The kind is therefore passed in: the call site knows it
 * (see _lower_list_method's gen._elem_of), and where it does not, the side
 * table and then the runtime's own discriminator decide (see _mojo_sort_kind).
 */

/* Range-safe string compare: a `sorted(<list of char*>)` whose codegen
   source (a name set, dict keys, ...) contains a NULL / erased-to-0 element
   — or, on the self-hosted path, an int slot holding pure garbage that was
   never a real pointer (`0xb343c47860b33ba0` &c) — must not segfault the
   whole sort in `strcmp`. Only a value inside the plausible userspace
   pointer window [0x1000, 2^47) is dereferenced; anything else sorts first
   (deterministically), and callers' per-element `_ptr_slot_in_range` guards
   then skip it in the loop body. */
static int _mojo_sorted_str_ok(int64_t raw) {
    uint64_t v = (uint64_t)raw;
    return v >= 0x1000ULL && v < 0x0000800000000000ULL;
}
static int _mojo_sorted_str_cmp(int64_t a_raw, int64_t b_raw) {
    int a_ok = _mojo_sorted_str_ok(a_raw);
    int b_ok = _mojo_sorted_str_ok(b_raw);
    if (!a_ok && !b_ok) return 0;
    if (!a_ok) return -1;
    if (!b_ok) return 1;
    return strcmp((const char *)(uintptr_t)a_raw, (const char *)(uintptr_t)b_raw);
}

/* The ONE comparator. `kind` is a MOJO_KIND_* byte; the default arm is the
   int64_t compare, which is also right for MOJO_KIND_NONE (every such slot is
   the same value, so any order of them is correct) and for any kind this
   file's alphabet does not give a total order to. */
static int _mojo_sort_cmp(int64_t a, int64_t b, int kind);

/* How deep the nested-container compare below will go. Python compares
   elementwise to any depth; a compiled MojoList cannot, because a
   self-referential list (`a = []; a.append(a)`) has no finite elementwise
   order at all. Past the bound the two compare EQUAL, which is a total order
   (it never claims one element is less than another) and, with the stable
   ordering below, leaves such elements in their original relative order. */
#define MOJO_SORT_MAX_DEPTH 16

static int _mojo_sort_cmp_at(int64_t a, int64_t b, int kind, int depth)
{
    if (kind != MOJO_KIND_LIST || depth >= MOJO_SORT_MAX_DEPTH)
        return _mojo_sort_cmp(a, b, kind);
    /* Python's list ordering: shorter first, then elementwise. */
    MojoList *x = (MojoList *)(intptr_t)a;
    MojoList *y = (MojoList *)(intptr_t)b;
    if (x == y) return 0;
    if (!x) return -1;
    if (!y) return 1;
    if (x->len != y->len) return x->len < y->len ? -1 : 1;
    for (int64_t i = 0; i < x->len; i++) {
        /* The inner element's kind, by the same two sources _mojo_sort_kind
         * uses: the per-slot side table when the inner list recorded one,
         * else the runtime's own discriminator. */
        const char *kx = mojo_list_get_kinds(x);
        const char *ky = mojo_list_get_kinds(y);
        int k = MOJO_KIND_INT;
        if (kx && kx[i]) k = kx[i];
        else if (ky && ky[i]) k = ky[i];
        else k = mojo_boxed_is_str(x->data[i]) ? MOJO_KIND_STR : MOJO_KIND_INT;
        int c = _mojo_sort_cmp_at(x->data[i], y->data[i], k, depth + 1);
        if (c) return c;
    }
    return 0;
}

static int _mojo_sort_cmp(int64_t a, int64_t b, int kind)

{
    switch (kind) {
    case MOJO_KIND_DOUBLE: {
        /* A list stores a double as its IEEE-754 bits in the slot (see the
           MojoList comment in fire_runtime.h), so the compare is on the
           reinterpreted value — comparing the bit patterns as integers
           would order every positive double after every negative one. */
        double x, y;
        __builtin_memcpy(&x, &a, 8);
        __builtin_memcpy(&y, &b, 8);
        if (x < y) return -1;
        if (x > y) return 1;
        return 0;
    }
    case MOJO_KIND_STR:
        return _mojo_sorted_str_cmp(a, b);
    case MOJO_KIND_BYTES: {
        const MojoBytes *x = (const MojoBytes *)(intptr_t)a;
        const MojoBytes *y = (const MojoBytes *)(intptr_t)b;
        if (!x || !y) return x == y ? 0 : (x ? 1 : -1);
        int64_t n = x->len < y->len ? x->len : y->len;
        int c = n > 0 ? memcmp(x->data, y->data, (size_t)n) : 0;
        if (c) return c < 0 ? -1 : 1;
        if (x->len < y->len) return -1;
        if (x->len > y->len) return 1;
        return 0;
    }
    default:
        return a < b ? -1 : (a > b ? 1 : 0);
    }
}

/* The kind to order `l` by, or 0 for "this list has no order" — which is
   mojo_list_sort's TypeError, not a silent no-op.
 *
 * The per-slot side table comes FIRST, ahead of what codegen knew: it is one
 * byte PER SLOT, so it is strictly more informative than the call site's
 * single element type, and a heterogeneous list literal
 * (`[1, 'a', 2.5]`) is recorded as exactly that while `_elem_of` reports only
 * the first/lowered type.  Trusting the call site there would order the list
 * by raw slot — strings by ADDRESS — and leave the side table describing
 * slots that have since moved.
 *
 * Then the call site's answer (a real static fact, from gen._elem_of), and
 * finally the runtime's own discriminator mojo_boxed_is_str, decided ONCE for
 * the whole list.  That last one is a genuine guess, and it is the same
 * discriminator mojo_cstr_or_int_str and mojo_sorted_by_keys already use for
 * "an untracked int64_t that may be a boxed char *"; the residual ambiguity (a
 * list of integers large enough to be pointer-shaped) is shared with those,
 * not introduced here.
 *
 * Either way the answer must be UNIFORM.  Python's sort compares every pair of
 * elements and raises TypeError on a mixed-type list, so "the slots disagree"
 * is the one answer that must be reported rather than guessed at. */
static int _mojo_sort_kind(MojoList *l, int kind)
{
    const char *k = mojo_list_get_kinds(l);
    if (k && l->len > 0) {
        char first = k[0] ? k[0] : MOJO_KIND_INT;
        for (int64_t i = 1; i < l->len; i++) {
            char c = k[i] ? k[i] : MOJO_KIND_INT;
            if (c != first) return 0;
        }
        return first;
    }
    if (kind) return kind;
    if (l->len < 1) return MOJO_KIND_INT;
    int s0 = mojo_boxed_is_str(l->data[0]);
    for (int64_t i = 1; i < l->len; i++)
        if (mojo_boxed_is_str(l->data[i]) != s0) return 0;
    return s0 ? MOJO_KIND_STR : MOJO_KIND_INT;
}

/* The one ordering loop: selection sort, permuting `l` in place and — when
   `keys` is given — the parallel key list with it, so the two stay aligned
   (that is why mojo_sorted_by_keys has always permuted both).
 *
 * Keys MOVED the slots, so a recorded per-slot kind string no longer
 * describes them; drop it, which is exactly what mojo_sorted_by_keys did for
 * the `sorted(x, key=f)` copy.  A KEYLESS sort needs no such step: it reaches
 * the loop with a recorded kinds string only when every slot agreed on one
 * kind (_mojo_sort_kind), and permuting identical kinds leaves it correct. */
static void _mojo_permute_by(MojoList *l, MojoList *keys, int kind, int reverse)
{
    int64_t n = l->len;
    if (keys && keys->len < n) n = keys->len;
    if (n < 2) return;
    if (keys) mojo_list_set_kinds(l, NULL);
    for (int64_t i = 0; i < n; i++) {
        for (int64_t j = i + 1; j < n; j++) {
            int64_t ki = keys ? mojo_list_get_int(keys, i) : l->data[i];
            int64_t kj = keys ? mojo_list_get_int(keys, j) : l->data[j];
            int c = _mojo_sort_cmp_at(ki, kj, kind, 0);
            int swap = reverse ? (c < 0) : (c > 0);
            if (!swap) continue;
            int64_t t = l->data[i]; l->data[i] = l->data[j]; l->data[j] = t;
            if (keys) {
                int64_t tk = mojo_list_get_int(keys, i);
                mojo_list_set_int(keys, i, mojo_list_get_int(keys, j));
                mojo_list_set_int(keys, j, tk);
            }
        }
    }
}

/* `l.sort()`, in place.  `kind` is the ELEMENT kind codegen knew at the call
   site (a MOJO_KIND_* byte), 0 for "it did not know" — see _mojo_sort_kind.
   With a `key=`, `keys` is the parallel key list codegen built by calling the
   key once per element (the compiled path has no per-element callback in the
   runtime, so _lower_builtin_sorted_keyed's builder is shared with this call
   site too), and then `kind` describes the KEY rather than the element. */
void mojo_list_sort(MojoList *l, int kind, int reverse, MojoList *keys)
{
    /* A tuple is not sortable in Python either, and this runtime has no
     * distinct container type for it — only the marker — so the guard is the
     * same `mojo_require_mutable_list` every other mutating entry point
     * calls. `l.sort()` on a tuple-marked list therefore refuses as CPython
     * refuses instead of silently reordering a list that prints like a
     * tuple. */
    mojo_require_mutable_list(l, "sort");
    if (!l || l->len < 2) return;
    if (!keys) {
        kind = _mojo_sort_kind(l, kind);
        if (!kind) {
            fprintf(stderr,
                    "TypeError: list.sort() cannot order a list whose elements "
                    "are not all of one orderable type (Python raises here "
                    "too); the list is left unchanged\n");
            exit(1);
        }
    }
    _mojo_permute_by(l, keys, kind, reverse);
}
void mojo_list_reverse(MojoList *l) {
    mojo_require_mutable_list(l, "reverse");
    if (!l || l->len < 2) return;
    for (int64_t i = 0, j = l->len-1; i < j; i++, j--) {
        int64_t tmp = l->data[i]; l->data[i] = l->data[j]; l->data[j] = tmp;
    }
    /* The slots moved, so a recorded per-slot kind string now describes the
     * wrong ones — same fix mojo_list_reversed makes for `sorted(x,
     * reverse=True)`.  A fresh string rather than an in-place reversal: the
     * recorded one is SHARED with every copy and slice taken from this list
     * (mojo_list_inherit_kinds hands over the same pointer). */
    const char *k = mojo_list_get_kinds(l);
    if (k) {
        int64_t n = l->len;
        char *rk = (char *)malloc((size_t)n + 1);
        if (rk) {
            for (int64_t i = 0; i < n; i++) rk[i] = k[n - 1 - i];
            rk[n] = '\0';
            mojo_list_set_kinds(l, rk);
        }
    }
}
void mojo_list_clear(MojoList *l) {
    if (!l) return;
    mojo_require_mutable_list(l, "clear");
    l->len = 0;
}
void mojo_list_remove_str(MojoList *l, const char *v) {
    if (!l || !v) return;
    mojo_require_mutable_list(l, "remove");
    for (int64_t i = 0; i < l->len; i++) {
        char *s = (char *)l->data[i];
        if (s && strcmp(s, v) == 0) {
            for (int64_t j = i; j < l->len - 1; j++)
                l->data[j] = l->data[j+1];
            l->len--;
            return;
        }
    }
}
void mojo_list_remove_int(MojoList *l, int64_t v) {
    if (!l) return;
    mojo_require_mutable_list(l, "remove");
    for (int64_t i = 0; i < l->len; i++) {
        if (l->data[i] == v) {
            for (int64_t j = i; j < l->len - 1; j++)
                l->data[j] = l->data[j+1];
            l->len--;
            return;
        }
    }
}
int64_t MojoList_index(MojoList *l, int v) {
    return mojo_list_index_int(l, (int64_t)v);
}
int64_t mojo_list_index_str(MojoList *l, const char *v) {
    if (!l) return -1;
    for (int64_t i = 0; i < l->len; i++) {
        char *s = (char *)l->data[i];
        if (s && strcmp(s, v) == 0) return i;
    }
    return -1;
}
int64_t mojo_list_index_int(MojoList *l, int64_t v) {
    if (!l) return -1;
    for (int64_t i = 0; i < l->len; i++) {
        if (l->data[i] == v) return i;
    }
    return -1;
}
/* Missing stubs for imported modules */
/* tokenize is provided by compiled mojo_compiler code, not the runtime */

/* Parser is defined as a struct in generated code; no runtime stub needed */

/* eval() stub — Python's eval() cannot run in C bootstrap; returns first arg unchanged */
int mojo_eval(int expr, MojoDict *globals, MojoDict *locals) {
    (void)globals; (void)locals;
    return expr;  /* return the expression value unchanged */
}

/* os.path bridge functions (stubs - real impl uses POSIX) */
int int_isdir(int64_t marker, int64_t path) {
    (void)marker;
    char *p = (char *)path;
    if (!p) return 0;
    struct stat st;
    return (stat(p, &st) == 0 && S_ISDIR(st.st_mode));
}

int64_t int_abspath(int64_t marker, int64_t path) {
    (void)marker;
    char *p = (char *)path;
    if (!p) return (int64_t)"";
    static char buf[4096];
    if (*p == '/') return (int64_t)p;
    if (!getcwd(buf, sizeof(buf))) return (int64_t)p;
    size_t plen = strlen(p);
    size_t dlen = strlen(buf);
    char *result = malloc(dlen + 1 + plen + 1);
    if (!result) return (int64_t)p;
    memcpy(result, buf, dlen);
    result[dlen] = '/';
    memcpy(result + dlen + 1, p, plen + 1);
    return (int64_t)result;
}

int64_t int_dirname(int64_t marker, int64_t path) {
    (void)marker;
    char *p = (char *)path;
    if (!p || !*p) return (int64_t)".";
    char *copy = strdup(p);
    if (!copy) return (int64_t)".";
    char *last = NULL;
    for (char *cp = copy; *cp; cp++) {
        if (*cp == '/') last = cp;
    }
    if (!last) { free(copy); return (int64_t)"."; }
    *last = '\0';
    if (*copy == '\0') { free(copy); return (int64_t)"/"; }
    char *result = strdup(copy);
    free(copy);
    return (int64_t)result;
}

int int_exists(int64_t marker, int64_t path) {
    (void)marker;
    char *p = (char *)path;
    if (!p) return 0;
    struct stat st;
    return (stat(p, &st) == 0);
}

int64_t int_join_list(int64_t marker, int64_t path_list) {
    (void)marker;
    MojoList *lst = (MojoList *)path_list;
    if (!lst || lst->len == 0) return (int64_t)"";
    /* Start with first element */
    int64_t result = lst->data[0];
    /* Join with each subsequent element */
    for (int64_t i = 1; i < lst->len; i++) {
        result = int_join(marker, result, lst->data[i]);
    }
    return result;
}

int64_t int_join(int64_t marker, int64_t base, int64_t part) {
    (void)marker;
    char *b = (char *)base;
    char *p = (char *)part;
    if (!b || !*b) return part;
    if (!p || !*p) return base;
    /* If part is absolute, return it directly */
    if (*p == '/') return part;
    size_t blen = strlen(b);
    size_t plen = strlen(p);
    int need_sep = (b[blen - 1] != '/');
    char *result = malloc(blen + need_sep + plen + 1);
    if (!result) return part;
    memcpy(result, b, blen);
    if (need_sep) result[blen++] = '/';
    memcpy(result + blen, p, plen + 1);
    return (int64_t)result;
}

int64_t int_getcwd(int64_t marker) {
    (void)marker;
    size_t cap = 4096;
    char *buf = malloc(cap);
    if (!buf) return (int64_t)"";
    if (getcwd(buf, cap)) return (int64_t)buf;
    free(buf);
    return (int64_t)"";
}

MojoList *mojo_listdir(char *path) {
    /* os.listdir(path) -> list[str] of entry names. "." and ".." are
     * excluded per Python semantics; order is the OS's readdir order
     * (real Python makes no ordering guarantee either). A path that
     * cannot be opened yields an empty list — real Python raises
     * OSError, but this runtime has no raise-from-C bridge here, and
     * real call sites either gate on os.path.isdir/exists first or
     * iterate defensively. */
    MojoList *l = mojo_list_new();
    if (!path || !*path) return l;
    DIR *d = opendir(path);
    if (!d) return l;
    struct dirent *ent;
    while ((ent = readdir(d)) != NULL) {
        const char *name = ent->d_name;
        if (name[0] == '.' && name[1] == '\0') continue;          /* "."  */
        if (name[0] == '.' && name[1] == '.' && name[2] == '\0') continue; /* ".." */
        mojo_list_append_str(l, strdup(name));
    }
    closedir(d);
    return l;
}

int int_isfile(int64_t marker, int64_t path) {
    /* os.path.isfile(path) — S_ISREG twin of int_isdir above. The codegen
     * previously stubbed this call shape to a literal 0 ("not a file"),
     * which made `if not os.path.isfile(p): continue` unconditional: every
     * iteration of e.g. Tools/unicode/gencodec.py's convertdir() loop was
     * silently skipped even after os.listdir returned a real list. */
    (void)marker;
    char *p = (char *)path;
    if (!p) return 0;
    struct stat st;
    return (stat(p, &st) == 0 && S_ISREG(st.st_mode));
}

MojoList *int64_t_path_split(char *path) {
    /* os.path.split(path) -> [head, tail] as a 2-element string list.
     * Python returns a tuple; the codegen models materialized pairs as a
     * MojoList* of strings exactly like its os.path.splitext lowering
     * ([root, ext]). Semantics mirror cpython's posixpath.split verbatim:
     * split at the last '/', keep ONE trailing slash in head only when it
     * is the whole string ('/' -> ['/', '']), and strip any other run of
     * trailing slashes from head ('a/b//' -> ['a/b', '']). */
    MojoList *l = mojo_list_new();
    char *head, *tail;
    if (!path) path = "";
    size_t plen = strlen(path);
    /* i = p.rfind('/') + 1 */
    size_t i = 0;
    for (size_t k = 0; k < plen; k++) {
        if (path[k] == '/') i = k + 1;
    }
    head = (char *)malloc(i + 1);
    memcpy(head, path, i);
    head[i] = '\0';
    tail = strdup(path + i);
    /* if head and head != '/'*len(head): head = head.rstrip('/') */
    if (i > 0) {
        size_t hlen = i;
        size_t end = hlen;
        while (end > 0 && head[end - 1] == '/') end--;
        if (end == 0) {
            /* all slashes: leave as-is */
        } else if (end < hlen) {
            head[end] = '\0';
        }
    }
    mojo_list_append_str(l, head);
    mojo_list_append_str(l, tail);
    return l;
}

MojoList *int64_t_path_splitdrive(char *path) {
    /* os.path.splitdrive(path) -> [drive, tail] as a 2-element string list.
     * POSIX posixpath.splitdrive has no drive concept: it always returns
     * ('', p). This codegen targets darwin, so mirror posixpath verbatim. */
    MojoList *l = mojo_list_new();
    if (!path) path = "";
    mojo_list_append_str(l, "");
    mojo_list_append_str(l, strdup(path));
    return l;
}

MojoList *int64_t_path_splitroot(char *path) {
    /* os.path.splitroot(path) -> [drive, root, tail] as a 3-element string
     * list. Mirrors cpython posixpath.splitroot verbatim (POSIX):
     *   p[:1] != '/'                      -> ('', '', p)
     *   p[1:2] != '/' or p[2:3] == '/'    -> ('', '/', p[1:])   (1 or >=3 slashes)
     *   else                              -> ('', '//', p[2:])  (exactly 2) */
    MojoList *l = mojo_list_new();
    if (!path) path = "";
    size_t plen = strlen(path);
    if (plen < 1 || path[0] != '/') {
        mojo_list_append_str(l, "");
        mojo_list_append_str(l, "");
        mojo_list_append_str(l, strdup(path));
    } else if (plen < 2 || path[1] != '/' || (plen >= 3 && path[2] == '/')) {
        mojo_list_append_str(l, "");
        mojo_list_append_str(l, "/");
        mojo_list_append_str(l, strdup(path + 1));
    } else {
        mojo_list_append_str(l, "");
        mojo_list_append_str(l, "//");
        mojo_list_append_str(l, strdup(path + 2));
    }
    return l;
}

char *int64_t_basename(char *path) {
    if (!path) return "";
    const char *base = path;
    for (const char *p = path; *p; p++) {
        if (*p == '/') base = p + 1;
    }
    return (char *)base;
}

/* pathlib.Path.resolve() (strict=False default) / os.path.realpath: make
 * the path absolute AND resolve symlinks via POSIX realpath(3). Matches
 * Python's strict=False convention: when the path (or any leading tail of
 * it) doesn't exist, realpath(3) fails and we return the input unchanged
 * rather than raising — every caller of this helper is a Path-shaped value
 * this codegen represents as its char* string, and resolve() on a
 * not-yet-existing path is ordinary, non-exceptional Python. */
char *int64_t_realpath(char *path) {
    if (!path) return "";
    char resolved[4096];
    if (realpath(path, resolved)) return strdup(resolved);
    return strdup(path);
}

/* os.path.splitext(path) -> (root, ext). Codegen (see the os.path.splitext
 * call site in gimple_codegen.py) treats this function's return value as
 * the root and builds a [root, ""] list around it — but this returned
 * `dot` (everything from the last '.' onward, i.e. the *extension*), not
 * the root, unconditionally swapping the two. Real bug found via
 * mojo.py's own build_executable: `os.path.splitext(basename)[0]` (meant
 * to strip the .mojo extension) returned ".mojo" itself instead. */
char *int64_t_splitext(char *path) {
    if (!path) return "";
    const char *dot = NULL;
    for (const char *p = path; *p; p++) {
        if (*p == '.') dot = p;
    }
    if (!dot) return path;
    size_t root_len = (size_t)(dot - path);
    char *root = malloc(root_len + 1);
    memcpy(root, path, root_len);
    root[root_len] = '\0';
    return root;
}

char *int64_t_expanduser(char *path) {
    if (!path) return "";
    if (path[0] != '~') return path;
    const char *home = getenv("HOME");
    if (!home) return path;
    /* Only the bare-"~" / "~/..." form is supported (no "~user"). */
    if (path[1] != '\0' && path[1] != '/') return path;
    size_t hl = strlen(home), rl = strlen(path + 1);
    char *out = (char *)malloc(hl + rl + 1);
    if (!out) return path;
    memcpy(out, home, hl);
    memcpy(out + hl, path + 1, rl + 1);
    return out;
}

int64_t _char_replace_impl(int64_t s_i, int64_t old_i, int64_t new_i) {
    char *s = (char *)s_i, *old_s = (char *)old_i, *new_s = (char *)new_i;
    if (!s) return s_i;
    if (!old_s || !new_s) return (int64_t)_str_fresh_copy(s);
    size_t old_len = strlen(old_s), new_len = strlen(new_s);
    if (old_len == 0) return (int64_t)_str_fresh_copy(s);
    int count = 0;
    const char *p = s;
    while ((p = strstr(p, old_s)) != NULL) { count++; p += old_len; }
    if (count == 0) return (int64_t)_str_fresh_copy(s);
    size_t slen = strlen(s);
    size_t result_len = slen + (size_t)count * new_len
                        - (size_t)count * old_len + 1;
    char *result = (char *)malloc(result_len);
    if (!result) abort();
    char *r = result; const char *q = s;
    while (*q) {
        if (strncmp(q, old_s, old_len) == 0) {
            memcpy(r, new_s, new_len); r += new_len; q += old_len;
        } else { *r++ = *q++; }
    }
    *r = '\0';
    return (int64_t)result;
}

/* Forward declare ModuleLoader (defined in generated code) */
typedef struct ModuleLoader ModuleLoader;

/* Module loader bridge implementations */
int int_load_module(ModuleLoader *ml_ptr, char *module_name) {
    /* Stub: return 0 (empty dict encoded as int) */
    (void)ml_ptr;  /* unused parameter */
    (void)module_name;  /* unused parameter */
    return 0;
}

char *int_get_symbol_type(ModuleLoader *ml_ptr, char *module_name, char *symbol_name) {
    /* Stub: return "int" as default type */
    (void)ml_ptr;  /* unused parameter */
    (void)module_name;  /* unused parameter */
    (void)symbol_name;  /* unused parameter */
    return "int";
}

/* Parser bridge implementations */
int int__peek(int parser) {
    /* Stub: return 0 (no token) */
    (void)parser;  /* unused parameter */
    return 0;
}

int int__advance(int parser) {
    /* Stub: advance parser and return 0 */
    (void)parser;  /* unused parameter */
    return 0;
}

int int__is_kw(int parser, char *keyword) {
    /* Stub: return 0 (not a keyword) */
    (void)parser;  /* unused parameter */
    (void)keyword;  /* unused parameter */
    return 0;
}

int int__expect(int parser, char *kind) {
    /* Stub: expect a token and return 0 */
    (void)parser;  /* unused parameter */
    (void)kind;  /* unused parameter */
    return 0;
}

int int__skip_bracketed(int parser) {
    /* Stub: skip bracketed expression and return 0 */
    (void)parser;  /* unused parameter */
    return 0;
}

int int__parse_type_ann(int parser) {
    /* Stub: parse type annotation and return 0 */
    (void)parser;  /* unused parameter */
    return 0;
}

/* Type checking functions */
int int_is_pointer(int cls, void *type_id) {
    /* Check if type_id (as char* or int) indicates a pointer */
    (void)cls;  /* unused parameter */
    if (!type_id) return 0;
    /* If it looks like a string, check for * */
    char *type_str = (char *)type_id;
    if (type_str && type_str[0] != '\0') {
        return strstr(type_str, "*") != NULL ? 1 : 0;
    }
    /* Otherwise treat as int (type ID) */
    return 0;
}

int int_is_float(int cls, void *type_id) {
    /* Check if type_id (as char* or int) indicates a float */
    (void)cls;  /* unused parameter */
    if (!type_id) return 0;
    /* If it looks like a string, check for float/double */
    char *type_str = (char *)type_id;
    if (type_str && type_str[0] != '\0') {
        return (strcmp(type_str, "float") == 0 ||
                strcmp(type_str, "double") == 0) ? 1 : 0;
    }
    /* Otherwise treat as int (type ID) */
    return 0;
}

int int_is_int(int cls, void *type_id) {
    /* Check if type_id (as char* or int) indicates an int */
    (void)cls;  /* unused parameter */
    if (!type_id) return 0;
    /* If it looks like a string, check for int/int64_t */
    char *type_str = (char *)type_id;
    if (type_str && type_str[0] != '\0') {
        return (strcmp(type_str, "int") == 0 ||
                strcmp(type_str, "int64_t") == 0) ? 1 : 0;
    }
    /* Otherwise treat as int (type ID) */
    return 1;  /* Assume it's an int ID if not a string */
}

int int_analyze(int obj) {
    /* Stub: analyze object and return 0 */
    (void)obj;  /* unused parameter */
    return 0;
}

/* Import function stub */
int int_import_module(int importlib_obj, char *module_name) {
    /* Stub: import module and return 0 (empty module) */
    (void)importlib_obj;  /* unused parameter */
    (void)module_name;  /* unused parameter */
    return 0;
}

/* ── Regex substitution with callback ──────────────────────────────────── */
/* Implements re.sub(pattern, callback, src) for POSIX ERE.
 * callback(env, matched_str) → replacement string.
 * Each match is replaced with the callback's return value.
 * Uses POSIX regcomp/regexec for portability (no PCRE dependency).        */
#include <regex.h>
char *mojo_re_sub_fn(char *pattern, char *(*callback)(void *, char *), void *env, char *src) {
    if (!pattern || !src) return src ? src : "";
    regex_t re;
    /* Compile as extended regex (ERE); treat . as matching newlines via REG_NEWLINE off */
    if (regcomp(&re, pattern, REG_EXTENDED) != 0) return src;

    size_t src_len = strlen(src);
    /* Result buffer: start with 4× source capacity, grow as needed */
    size_t out_cap = src_len * 4 + 64;
    char *out = (char *)malloc(out_cap);
    if (!out) { regfree(&re); return src; }
    size_t out_len = 0;

    const char *pos = src;
    regmatch_t pmatch[1];
    while (*pos) {
        int rc = regexec(&re, pos, 1, pmatch, 0);
        if (rc != 0) {
            /* No more matches — copy the rest */
            size_t rest = strlen(pos);
            while (out_len + rest + 1 > out_cap) { out_cap *= 2; out = realloc(out, out_cap); }
            memcpy(out + out_len, pos, rest);
            out_len += rest;
            break;
        }
        /* Copy text before match */
        size_t pre = (size_t)pmatch[0].rm_so;
        while (out_len + pre + 1 > out_cap) { out_cap *= 2; out = realloc(out, out_cap); }
        memcpy(out + out_len, pos, pre);
        out_len += pre;

        /* Extract matched substring */
        size_t mlen = (size_t)(pmatch[0].rm_eo - pmatch[0].rm_so);
        char *matched = (char *)malloc(mlen + 1);
        memcpy(matched, pos + pmatch[0].rm_so, mlen);
        matched[mlen] = '\0';

        /* Call the replacement callback */
        char *repl = callback(env, matched);
        free(matched);
        if (repl) {
            size_t rlen = strlen(repl);
            while (out_len + rlen + 1 > out_cap) { out_cap *= 2; out = realloc(out, out_cap); }
            memcpy(out + out_len, repl, rlen);
            out_len += rlen;
        }

        /* Advance past the match (avoid infinite loop on zero-length match) */
        size_t adv = (size_t)pmatch[0].rm_eo;
        if (adv == 0) { if (*pos) { out[out_len++] = *pos++; } else break; }
        else pos += adv;
    }
    out[out_len] = '\0';
    regfree(&re);
    return out;
}

/* re.sub(pattern, repl, src) where repl is a plain replacement STRING, not a
 * callback — Python's `re.sub` accepts either, but this codegen's `re.sub`
 * lowering assumed every second argument was a callback and cast the
 * replacement string straight to a function pointer, then called it: a
 * SIGILL calling a string's bytes as machine code. Found via
 * monomorphize.py's own `re.sub(r'[^A-Za-z0-9_]', '_', s)` /
 * `re.sub(rf'\b{re.escape(tp)}\b', str(concrete), src)`. Same substitution
 * loop as mojo_re_sub_fn, minus the callback machinery — no backreference
 * support (`\1` etc in repl), since nothing in this codebase's actual usage
 * needs it. */
/* re.escape(p) — escape the regex metacharacters in `p` so it can be
 * embedded as a literal inside a larger pattern. Several compiler modules
 * build identifier-anchored patterns as `rf'\b{re.escape(name)}\b'` (see
 * gimple_gen_infra.py's qualified-symbol rename, gimple_gen_resolve.py's
 * struct/generic scans). Before this existed the compiled backend had NO
 * lowering for re.escape at all: the call fell to the generic
 * scalar-receiver stub and returned 0, so the escaped identifier silently
 * vanished from every pattern that used it (the shim, running CPython, was
 * unaffected — a shim-vs-self-host `--dump` divergence).
 *
 * Mirrors CPython's re.escape (3.7+): ASCII letters, digits and '_' are
 * left alone; every character with special meaning to the pattern grammar
 * is backslash-escaped. */
char *mojo_re_escape(char *s) {
    static const char *specials = "()[]{}?*+-|^$\\.&~# \t\n\r\v\f";
    if (!s) return strdup("");
    size_t n = strlen(s);
    char *out = (char *)malloc(n * 2 + 1);
    if (!out) return strdup("");
    size_t j = 0;
    for (size_t i = 0; i < n; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c && strchr(specials, (int)c)) out[j++] = '\\';
        out[j++] = (char)c;
    }
    out[j] = '\0';
    return out;
}

char *mojo_re_sub_str(char *pattern, char *repl, char *src) {
    if (!pattern || !src) return src ? src : "";
    if (!repl) repl = "";
    regex_t re;
    if (regcomp(&re, pattern, REG_EXTENDED) != 0) return src;

    size_t src_len = strlen(src);
    size_t out_cap = src_len * 4 + 64;
    char *out = (char *)malloc(out_cap);
    if (!out) { regfree(&re); return src; }
    size_t out_len = 0;
    size_t rlen = strlen(repl);

    const char *pos = src;
    regmatch_t pmatch[1];
    while (*pos) {
        int rc = regexec(&re, pos, 1, pmatch, 0);
        if (rc != 0) {
            size_t rest = strlen(pos);
            while (out_len + rest + 1 > out_cap) { out_cap *= 2; out = realloc(out, out_cap); }
            memcpy(out + out_len, pos, rest);
            out_len += rest;
            break;
        }
        size_t pre = (size_t)pmatch[0].rm_so;
        while (out_len + pre + 1 > out_cap) { out_cap *= 2; out = realloc(out, out_cap); }
        memcpy(out + out_len, pos, pre);
        out_len += pre;

        while (out_len + rlen + 1 > out_cap) { out_cap *= 2; out = realloc(out, out_cap); }
        memcpy(out + out_len, repl, rlen);
        out_len += rlen;

        size_t adv = (size_t)pmatch[0].rm_eo;
        if (adv == 0) { if (*pos) { out[out_len++] = *pos++; } else break; }
        else pos += adv;
    }
    out[out_len] = '\0';
    regfree(&re);
    return out;
}

int64_t mojo_obj_call1(int64_t obj, char *method, int64_t arg1) {
    /* Stub: dynamic method call on opaque Python object.
     * In the bootstrap, interpreter execute() calls are not needed
     * since we compile rather than interpret. Returns 0 (None). */
    (void)obj; (void)method; (void)arg1;
    return 0;
}

/* ── Additional Python builtins (stubs for bootstrap) ──────────────── */

/* Python's bool repr. Every `print` of a boolean used to fall through to the
   generic numeric path (printf_fmt('_Bool') -> "%d"), so `print(True)` printed
   `1` and `print(1 == 1)` printed `1` — wrong for every boolean in every
   compiled program, not just the builtin-returning ones.

   The parameter is `int`, not `_Bool`: this header is included from C++
   translation units (the C++20 companion backend) where `_Bool` does not
   exist, and a bool argument arrives as 0/1 anyway. */
char *mojo_repr_bool(int b) { return b ? "True" : "False"; }

/* The TRANSIENT decimal strings of `mojo_cstr_or_int_str` (an Int dict key or
 * compare operand) are blocks from this small free list: one per access,
 * released the moment the call that consumed it returns
 * (`mojo_cstr_or_int_release`), so a tight loop of Int-keyed lookups reuses the
 * same block instead of a malloc/free pair per access. The pool only ever holds
 * blocks that came from `_int_str_block`. Not thread-safe, like the rest. */
static char *_int_str_pool;   /* free list; the next pointer lives in a block's first 8 bytes */

static char *_int_str_block(void) {
    char *b = _int_str_pool;
    if (b) {
        _int_str_pool = *(char **)b;
        return b;
    }
    return (char *)malloc(_INT_STR_BLOCK);
}

static char *_int_str_transient(int64_t v) {
    char tmp[_INT_STR_BLOCK];
    char *p = _fmt_int(v, tmp);
    char *out = _int_str_block();
    memcpy(out, p, (size_t)(tmp + sizeof tmp - p));
    return out;
}

/* A registered container (a list, or a tuple -- the two are the same
   MojoList with a marker) used where a C string is needed, which in practice
   means as a DICT KEY. The string is the container's VALUE, so `(p, 1.0)` keys
   as "('p', 1.0)" and two separately-built equal tuples key identically.

   Before this, a container word fell to the decimal-of-the-address branch and
   keyed as "4372863864": equal keys never hit, and a REUSED address could hit
   a stale entry. That was not only a wrong answer -- the dict layer then grew
   one entry per lookup and never hit one, which is where the multi-GB growth
   on `mojoc --dump-full fire.py` came from (see
   bugs/CODEGEN_tuple_dict_key_hashed_by_address.md).

   This has to live in the runtime because the value arriving here is an
   untyped WORD: the key's static type is known where the key is written and
   thrown away by the `int64_t` the dict call takes. Two sources for the text,
   in this order:

     - a list that carries its own per-slot kinds (`mojo_list_get_kinds`, set
       for `struct.unpack` of a mixed format and for a heterogeneous list
       literal) is rendered by the kinds-aware walker, which is the only thing
       that can read a FLOAT slot correctly;
     - otherwise each slot is read by RUNTIME type below, which is what a
       hand-built tuple needs: codegen appends slot by slot through
       `mojo_list_append_int`, so there is no kinds row to consult, and the
       kinds walker with no row renders every slot as an integer -- a string
       slot as the decimal of its own address, so two tuples holding equal
       strings at different addresses keyed differently and the bug survived
       the first attempt at this fix (measured, see the doc).

   This mirrors the codegen-emitted `_mojo_repr_list` /
   `_mojo_generic_elem_repr` pair, which is the same two-source shape for the
   same reason: what a slot holds is only knowable at runtime. It is a
   separate copy rather than a shared one because those two are emitted PER
   TRANSLATION UNIT with this program's own struct-tag table baked in, which
   the runtime has no way to see.

   Ownership: an ordinary heap string (the walker's own `strdup` /
   `mojo_str_cat` blocks), so `mojo_cstr_or_int_release` frees it -- see its
   second branch. Every per-slot string is freed as it is consumed, and the
   slot walker always returns a heap string (a strdup of `mojo_repr_obj`'s
   shared buffer where that is the answer) so the caller can free
   unconditionally instead of tracking which repr helper returns what. */
static char *_container_key_str(int64_t v);

static char *_key_slot_str(int64_t v) {
    if (mojo_is_registered_list(v)) return _container_key_str(v);
    /* A dict slot is a Python TypeError as a key and unreachable in practice;
       what matters is that it must not reach `strlen` below, since
       `mojo_boxed_is_str` accepts a dict pointer (it excludes registered
       LISTS and boxes, not dicts). The address placeholder is this runtime's
       own honest answer for a value it cannot describe. */
    if (mojo_is_registered_dict(v)) return strdup(mojo_repr_obj(v));
    /* `mojo_boxed_is_str`, the model's own discriminator, rather than a shape
       test of our own: its 2GiB-floor/2^47-ceiling window is what keeps a word
       that is NOT a pointer out of strlen. A float slot stored raw is the case
       that makes the difference — `1.0` is the bit pattern 0x3FF0000000000000,
       pointer-shaped to any `v > 65536` test, and dereferencing it segfaulted
       (measured, first attempt at this fix). */
    if (mojo_boxed_is_str(v)) return mojo_repr_str((char *)(intptr_t)v);
    /* A zero slot is `0`, not `None`. The emitted `_mojo_generic_elem_repr`
       answers "None" for one, because in a genuinely DYNAMIC list a 0 can be a
       boxed null and printing it as 0 would then be a lie; a key cannot afford
       the guess, and cannot afford the disagreement either -- this walker's
       other branch, `mojo_repr_list_kinds`, reads the same slot as an int, so
       leaving None to that function's 'n' kind (and only there) is what makes
       a tuple key the same text whether or not the list happens to carry a
       kinds row. Measured: with a 0-is-None rule here, `(('x', 0), 'y')`
       keyed as `(('x', None), 'y')` and disagreed with itself between the two
       branches. */
    return mojo_repr_int(v);
}

static char *_container_key_str(int64_t v) {
    MojoList *l = (MojoList *)(intptr_t)v;
    const char *kinds = mojo_list_get_kinds(l);
    if (kinds) return mojo_repr_list_kinds(l, kinds);
    int _is_tup = l && mojo_is_tuple(l);
    if (!l) return strdup(_is_tup ? "()" : "[]");
    int64_t _n = mojo_list_len(l);
    char *_buf = strdup(_is_tup ? "(" : "[");
    for (int64_t _i = 0; _i < _n; _i++) {
        if (_i > 0) _buf = mojo_str_cat_free(_buf, ", ");
        char *_s = _key_slot_str(mojo_list_get_int(l, _i));
        _buf = mojo_str_cat_free(_buf, _s);
        free(_s);
    }
    if (_is_tup && _n == 1) _buf = mojo_str_cat_free(_buf, ",");
    return mojo_str_cat_free(_buf, _is_tup ? ")" : "]");
}

/* An int64_t being used where a C string is needed (a dict key, an f-string
   field, ...): return it AS itself when it is really a boxed `char *`, the
   container's VALUE when it is really a container, else its decimal string.

   The codegen's own test for "is this boxed pointer?" is `_actual_types`,
   which only knows about values it saw TYPE-ERASED at some earlier point.
   An untracked int64_t is overwhelmingly a real Int (so the codegen
   correctly stringifies it), but not always: a lambda parameter has no
   annotation and is typed `int64_t`, so a string passed to it arrives with
   its pointer bits in an int64_t with nothing recorded anywhere. Measured:
   `d = {"a": 1}; f = lambda k: d[k]; f("a")` looked up the key "97" (the
   decimal of the address) and returned 0. mojo_boxed_is_str is the model's
   own discriminator — pointer-shaped and not a live registered list — so
   ask it here rather than guessing a direction. */
char *mojo_cstr_or_int_str(int64_t v) {
    if (mojo_boxed_is_str(v)) return (char *)(intptr_t)v;
    if (mojo_is_registered_list(v)) return _container_key_str(v);
    return _int_str_transient(v);
}

/* `mojo_cstr_or_int_str` for the caller that already KNOWS the word is an
   integer, so the question does not have to be asked at all.

   That is not a hypothetical caller. `mojo_boxed_is_str` is a RANGE test (see
   its own docstring), so it cannot tell an integer from a `char *`: every
   positive int64 in [2^31, 2^47) is pointer-shaped to it, and
   `d[3000000000] = 1` was handed to `mojo_dict_set_int(d, (char *)3000000000, 1)`,
   which `strcmp`ed address 3000000000 and died — SIGSEGV on the runtime unit
   test, at -O0, -O2 and under AddressSanitizer alike. The ambiguity is
   information-theoretic in this compiler's scalar body model (a `char *` and
   an `int64_t` are the same 64 bits with no tag), so the answer has to come
   from the codegen, which does know it: the emitted call site hands this
   function the raw integer instead of a word for the runtime to classify.

   Same block, same ownership, same release protocol as
   `mojo_cstr_or_int_str`'s own int half -- it IS that half, published under
   a name that states the answer the caller already has. The distinction is
   that this one never guesses, so it is also right for the integers
   `mojo_boxed_is_str` cannot see (anything in the 2 GiB .. 2^47 window,
   which is where every large-but-plausible int -- a nanosecond-ish id, a
   millisecond timestamp, a 2**40 token count -- lands).

   The DECIMAL, not a pointer round-trip: the dict re-normalises it through
   `_canon_int`, so `d[5]` and `d["5"]` stay the one integer slot they have
   always been (see `_canon_int`'s comment), and `d[3000000000] = 1` then
   `d[3000000000]` finds what it stored. */
char *mojo_int_str_transient(int64_t v) {
    return _int_str_transient(v);
}

/* The other half of mojo_cstr_or_int_str's contract: the result is OWNED by
   the caller exactly when it is not `v` itself. A boxed string comes back as
   the very same address (borrowed -- someone else owns it, never free it);
   an Int comes back as a fresh heap decimal (owned -- the caller must free it
   once its last use is done). `orig` is the int64_t that was converted and
   `s` is what mojo_cstr_or_int_str returned for it; this frees `s` iff it is
   the heap copy. Emitted by the codegen right after the single runtime call
   that consumes a TRANSIENT key (dict get/set/contains/pop, string compare) --
   all of which copy or merely read the key. Never call it for a key that was
   stored by reference (a list element, a __missing__ argument): those keep
   the unreleased conversion. See doc/MEMORY.html, "Transient keys". */
void mojo_cstr_or_int_release(int64_t orig, char *s) {
    if ((int64_t)(intptr_t)s == orig) return;     /* a borrowed boxed string */
    /* A content key is an ordinary heap string from the repr walker, NOT a
     pool block, and pooling one would hand it out later as an Int key's
     scratch -- so it is freed outright. `orig` is the discriminator because
     it is the SAME predicate mojo_cstr_or_int_str chose the branch with: a
     registered list is the only value that produces this kind of string, so
     the two cannot disagree about which allocation `s` is. */
    if (mojo_is_registered_list(orig)) { free(s); return; }
    /* `s` is the decimal `mojo_cstr_or_int_str` made through mojo_str_from_int,
     * i.e. a block from `_int_str_block`: back to the pool it came from. */
    *(char **)s = _int_str_pool;
    _int_str_pool = s;
}

/* ── A CONTAINER used as a dict key: a CONTENT key, not its address ──────────
 *
 * `d[(p, mtime)]` used to be keyed by the tuple OBJECT'S ADDRESS: the codegen's
 * dict-key conversion (`_char_to_cstr`) falls through to `(char *)value` for any
 * pointer-typed operand, so the key was the tuple's own pointer bits, and every
 * equal tuple built at a different address missed. Not a slow path either — it
 * was ~16 of the 19 GB live on `mojoc --dump-full fire.py`, because each miss
 * re-inserts and the runtime has no GC to reclaim the tuple.
 *
 * The leak hunt fixed the call sites that mattered (string keys, the
 * `_pair_key` convention already in fire_compiler.py) and left the MECHANISM,
 * which is what every remaining tuple-keyed lookup goes through.
 *
 * A tuple is the one container Python lets you key a dict with, because it is
 * the one container it considers hashable — so this is a tuple-only domain, not
 * a general "any container" one. A list / dict / set key is a TypeError in
 * Python and `mojo_dict_key_for` raises rather than inventing a key.
 *
 * How the key is spelled: the tuple's elements, each rendered with its OWN
 * kind, in a length-delimited form so that `('ab', 'c')` and `('a', 'bc')` get
 * DIFFERENT keys. That is the whole requirement — the dict keys on the string,
 * so the string has to be injective in the tuple — and a repr with separators
 * is not (it is exactly the `_repr_pairlist` ambiguity). A leading marker byte
 * keeps the domain apart from an ordinary str key, so `d[('a',)]` and `d["\x01a"]`
 * stay the two distinct entries Python says they are, the same reason keykind 1
 * exists for bytes keys.
 *
 * Ownership: the returned string is MALLOC'd and the caller OWNS it. It is not a
 * `_int_str_block` pool block and must NOT be released through
 * `mojo_cstr_or_int_release` (which links every block onto that pool's free list
 * and would hand a wrongly-sized block to the next `_fmt_int`). The dict copies
 * it with `strdup`, so the caller frees it as soon as its one consuming call
 * returns. */

/* Keykind 3: a container key, `key` holding the rendered content. Distinct from
 * every other keykind so it can never collide with a str key that happens to
 * spell the same characters. */
#define MOJO_KEY_TUPLE 3

/* Append to the growable key buffer, HEX-ENCODED and length-delimited.
 *
 * Both halves are load-bearing and neither is decoration:
 *
 *  - LENGTH-delimited, because a bare concatenation is ambiguous --
 *    `('ab', 'c')` and `('a', 'bc')` would render identically and two
 *    DIFFERENT tuples would share one dict entry. The prefix is the element's
 *    own byte count, so the reader (which is `strcmp`, i.e. none) never has to
 *    parse it; it exists purely to keep distinct tuples distinct.
 *  - HEX, because a dict key is a NUL-TERMINATED C string: it is strdup'd,
 *    hashed with `_str_hash` and compared with `strcmp`, every one of which
 *    stops at the first NUL. A binary encoding therefore cannot go in this
 *    domain at all -- `('a', 'b')` and `('a\0b',)` and `('a',)` would all
 *    compare EQUAL because the comparison would stop inside the first element.
 *    Two hex digits per byte is the cheapest encoding with no NUL and no
 *    separator ambiguity.
 *
 * The cost is a 2x key, which is the right trade against a hash collision
 * between two different tuples: the dict would then report one entry for two
 * keys, and `d[(a,)] = 1; d[(b,)] = 2` would silently lose one. */
static const char _KHEX[] = "0123456789abcdef";

static void _kbuf_put(char **buf, size_t *len, size_t *cap, const char *s, size_t n)
{
    size_t need = *len + 8 + 2 * n + 1;
    if (need > *cap) {
        while (need > *cap) *cap = *cap ? *cap * 2 : 64;
        *buf = (char *)realloc(*buf, *cap);
    }
    char *p = *buf + *len;
    for (int i = 0; i < 4; i++) {
        *p++ = _KHEX[(n >> (8 * i)) & 0xf];
    }
    for (size_t i = 0; i < n; i++) {
        *p++ = _KHEX[(unsigned char)s[i] >> 4];
        *p++ = _KHEX[(unsigned char)s[i] & 0xf];
    }
    *len = (size_t)(p - *buf);
}

/* Raw bytes with no length prefix, for a fixed one-byte tag. */
static void _kbuf_put_word(char **buf, size_t *len, size_t *cap, const char *tag, size_t n)
{
    size_t need = *len + n + 1;
    if (need > *cap) {
        while (need > *cap) *cap = *cap ? *cap * 2 : 64;
        *buf = (char *)realloc(*buf, *cap);
    }
    memcpy(*buf + *len, tag, n);
    *len += n;
}

/* Render `w` as the bytes of one element, by the element's OWN kind. `k` is the
 * slot kind (mojo_list_slot_kind's alphabet) when the value carries per-slot
 * kinds, else 0 to mean "unknown, ask the codegen's code". `ecode` is the
 * MOJO_EQ_* code the codegen passed; it is what decides a slot the per-slot
 * record says nothing about.
 *
 * The tag byte is part of every arm, so an int 1 and the str "1" render
 * differently — the same reason `_slot_eq` takes an element code rather than
 * comparing raw words. */
static void _tuple_key_elem(char **buf, size_t *len, size_t *cap, int64_t w,
                            char k, int ecode)
{
    if (ecode == MOJO_EQ_UNKNOWN) ecode = _kind_to_eq(k);
    char tmp[_INT_STR_BLOCK];
    if (ecode == MOJO_EQ_DOUBLE) {
        double d = _eq_as_double(w);
        int n = snprintf(tmp, sizeof tmp, "%.17g", d);
        _kbuf_put(buf, len, cap, tmp, (size_t)(n < 0 ? 0 : n));
    } else if (ecode == MOJO_EQ_STR) {
        /* A NULL slot is a real `None` element and gets its own tag, so a
         * tuple containing None does not render like one containing the empty
         * string. A word that is not pointer-shaped cannot be a string at all
         * — the erased-operand path can guess STR for a container whose real
         * elements are not strings, and dereferencing a small integer here
         * would be a segfault rather than a wrong key. */
        if (w == 0) { _kbuf_put(buf, len, cap, "N", 1); return; }
        if (!_mojo_ptr_shaped(w)) { _kbuf_put(buf, len, cap, "?", 1); return; }
        _kbuf_put(buf, len, cap, (char *)(intptr_t)w,
                  strlen((char *)(intptr_t)w));
    } else if (ecode == MOJO_EQ_BYTES) {
        if (!_mojo_ptr_shaped(w)) { _kbuf_put(buf, len, cap, "?", 1); return; }
        MojoBytes *b = (MojoBytes *)(intptr_t)w;
        _kbuf_put(buf, len, cap, (const char *)(b ? b->data : NULL),
                  b && b->len > 0 ? (size_t)b->len : 0);
    } else if (ecode == MOJO_EQ_GENERIC) {
        /* A nested container: recurse, so `((1,2),)` and `(1,2)` are different
         * keys. Recursion is bounded by the nesting depth of the value, which
         * for a heap object is bounded by the heap. */
        int64_t nk = _value_kind(w);
        if (nk == MOJO_VK_LIST) {
            _kbuf_put_word(buf, len, cap, "L", 1);
            char *inner = mojo_dict_key_for(w);
            if (inner) {
                _kbuf_put(buf, len, cap, inner, strlen(inner));
                free(inner);
            }
        } else if (nk == MOJO_VK_SET) {
            _kbuf_put_word(buf, len, cap, "S", 1);
        } else {
            _kbuf_put_word(buf, len, cap, "?", 1);
        }
        return;
    } else {
        /* An int slot that may really be a nested container handle (the same
         * "an untyped int64_t can be anything" case `_slot_eq`'s INT arm
         * handles by asking the registries). */
        if (_value_kind(w) != MOJO_VK_NONE) {
            _tuple_key_elem(buf, len, cap, w, 'l', MOJO_EQ_GENERIC);
            return;
        }
        char *p = _fmt_int(w, tmp);
        /* `- 1`: `_fmt_int` leaves the NUL inside the block, so the span it
         * returns INCLUDES it (which is what `_slot_key` wants — it copies the
         * NUL as part of the string). A length PREFIX counts content bytes, so
         * counting the terminator here would render every integer one byte too
         * long and, worse, put a NUL in the middle of the key where a
         * `strcmp`-based dict probe stops reading. */
        _kbuf_put(buf, len, cap, p, (size_t)(tmp + sizeof tmp - p) - 1);
    }
}

/* The content key for a container used as a dict key. See the block comment
 * above for the encoding and the ownership contract. Returns NULL for a NULL
 * or non-container `v`, and RAISES for a container Python would refuse as
 * unhashable, which is the honest answer and not a key invented for it. */
char *mojo_dict_key_for(int64_t v)
{
    int k = _value_kind(v);
    if (k == MOJO_VK_DICT || k == MOJO_VK_SET) {
        /* CPython's own text, for the same reason the ordering refusal carries
         * CPython's: a program printing this message prints CPython's message.
         * Two literals rather than one concatenated one because string-literal
         * `+` is pointer arithmetic and would drop the prefix. */
        mojo_raise_type_error(k == MOJO_VK_DICT
                              ? (char *)"unhashable type: 'dict'"
                              : (char *)"unhashable type: 'set'");
        return NULL;
    }
    if (k != MOJO_VK_LIST) return NULL;
    MojoList *l = (MojoList *)(intptr_t)v;
    /* A LIST is a MojoList that is NOT marked as a tuple, and Python refuses
     * it as unhashable — `d[[1, 2]]` is a TypeError. Without this the two are
     * the same C type and the list would quietly get a tuple's content key:
     * not a wrong ANSWER (it is the right one for a genuinely hashable
     * container) but a program that CPython rejects running to completion
     * here, which is how the missing refusal would go unnoticed. */
    if (!mojo_is_tuple(l)) {
        mojo_raise_type_error((char *)"unhashable type: 'list'");
        return NULL;
    }
    char *buf = NULL;
    size_t len = 0, cap = 0;
    /* The domain marker, so this key can never equal a str key spelling the
     * same bytes. Printable rather than a control byte: the key is a C string
     * that flows through hashing, comparison AND (for `.keys()`, a repr, a
     * `print`) rendering, and a raw 0x01 in a dict key is a trap for whatever
     * downstream reads it as text. */
    _kbuf_put_word(&buf, &len, &cap, "T1", 2);
    /* A tuple's LENGTH, so `(1,)` and `(1, 1)` differ even before the
     * elements: with elements only, they would both render "1". */
    char tmp[_INT_STR_BLOCK];
    char *lp = _fmt_int(l->len, tmp);
    _kbuf_put(&buf, &len, &cap, lp, (size_t)(tmp + sizeof tmp - lp) - 1);
    for (int64_t i = 0; i < l->len; i++) {
        _tuple_key_elem(&buf, &len, &cap, l->data[i],
                        mojo_list_slot_kind(l, i), MOJO_EQ_UNKNOWN);
    }
    if (!buf) { buf = (char *)malloc(1); cap = 1; }
    buf[len] = '\0';
    return buf;
}

/* Free a key `mojo_dict_key_for` returned. A named free rather than leaving the
 * caller to guess: the ownership contract above is the opposite of every other
 * key's (borrowed for a boxed string, pooled for an Int), so "just free it" is
 * right here and wrong one function away, and the symmetry with
 * `mojo_cstr_or_int_release` is what makes the difference visible at the call
 * site. */
void mojo_dict_key_free(char *s) { if (s) free(s); }

/* Is this word a container that needs a content key rather than the address?
 * The one predicate every `_kw` twin below asks, so "a dict key that is a
 * tuple" cannot be handled at one call site and forgotten at the next — which is
 * exactly how the address-keying survived the leak hunt's call-site fixes. */
static int _kw_is_container_key(int64_t kw)
{
    /* All THREE container registries, not just the list one: a dict or a set
     * used as a key must reach `mojo_dict_key_for`, which raises Python's
     * `unhashable type` for it. Testing only lists let those through to the
     * INTEGER arm, where the key was the address and the answer was a silent
     * False rather than a refusal. */
    return mojo_is_registered_list(kw) || mojo_is_registered_dict(kw)
        || mojo_is_registered_set(kw);
}

/* ── Dict operations keyed by a raw machine WORD ───────────────────────────
 * The key is an untracked int64_t: a boxed string pointer or an integer. The
 * decision is exactly `mojo_cstr_or_int_str`'s (`mojo_boxed_is_str`), so nothing
 * changes about which words are strings; what changes is that an integer is
 * looked up as an integer. Before, it was formatted to a decimal string, hashed
 * as text, compared with strcmp, and the string released afterwards — over half
 * of an Int-keyed dict access. A string word takes the ordinary string path. */

/* Insert or overwrite the entry for integer key `k`. A NEW key allocates
 * nothing: its decimal string is built on first read (`_slot_key`). */
static void _dict_set_ik(MojoDict *d, int64_t k, int64_t val, int64_t kind)
{
    if (!d) return;
    if (d->used * 2 >= d->cap) _dict_grow(d);
    _DictSlot *sl = _dict_find_ik(d, k);
    if (!sl->key) {
        sl->key = _ikey_lazy;
        sl->keykind = 2;
        sl->ikey = k;
        sl->seq = d->next_seq++;
        d->used++;
    }
    sl->val = val;
    sl->kind = kind;
}

/* The three kinds a key WORD can be, and the ONE place that decides which.
 *
 * A word reaching a dict as a key is one of three things: a boxed `char *`, a
 * real integer, or a CONTAINER handle. The third is the one that used to be
 * missing: `_dict_lookup_ik` then looked the tuple's ADDRESS up as an integer,
 * so an equal tuple at a different address missed and re-inserted, and with no
 * GC that leaked the tuple per miss (the ~16 of 19 GB in
 * bugs/PERF_selfhost_memory_leak_hunt.md).
 *
 * One dispatch for all of them, in this order, because the order is not
 * arbitrary: `mojo_boxed_is_str` already excludes a live registered list (see
 * its own comment — a container is pointer-shaped and would otherwise be
 * strcmp'd), so the container test could go first, but putting it first would
 * mean a future change to that predicate silently re-classifying container keys
 * as strings. Boxed str, then container, then integer.
 *
 * `out` receives the CONTENT KEY when the word was a container, and the caller
 * must free it with `mojo_dict_key_free` once its one consuming call returns;
 * `*out` is NULL for the other two kinds, which need no key at all. Every `_kw`
 * twin below follows this same three-arm shape on purpose: the bug was a
 * MISSING arm at every site, so adding the arm at one and not the others is
 * precisely the failure mode this shape makes visible. */
#define _KW_STR 0
#define _KW_INT 1
#define _KW_CONT 2
static int _kw_kind(int64_t kw, char **out)
{
    *out = NULL;
    if (mojo_boxed_is_str(kw)) return _KW_STR;
    if (_kw_is_container_key(kw)) { *out = mojo_dict_key_for(kw); return _KW_CONT; }
    return _KW_INT;
}

int64_t mojo_dict_get_int_kw(MojoDict *d, int64_t kw)
{
    char *ck; int k = _kw_kind(kw, &ck);
    if (k == _KW_STR) { return mojo_dict_get_int(d, (char *)(intptr_t)kw); }
    if (k == _KW_CONT) {
        int64_t v = mojo_dict_get_int(d, ck);
        mojo_dict_key_free(ck);
        return v;
    }
    _DictSlot *sl = _dict_lookup_ik(d, kw);
    return sl ? sl->val : 0;
}

double mojo_dict_get_double_kw(MojoDict *d, int64_t kw)
{
    char *ck; int k = _kw_kind(kw, &ck);
    if (k == _KW_STR) { return mojo_dict_get_double(d, (char *)(intptr_t)kw); }
    if (k == _KW_CONT) {
        double v = mojo_dict_get_double(d, ck);
        mojo_dict_key_free(ck);
        return v;
    }
    _DictSlot *sl = _dict_lookup_ik(d, kw);
    if (!sl) return 0.0;
    double v;
    memcpy(&v, &sl->val, sizeof(v));
    return v;
}

char *mojo_dict_get_str_kw(MojoDict *d, int64_t kw)
{
    char *ck; int k = _kw_kind(kw, &ck);
    if (k == _KW_STR) { return mojo_dict_get_str(d, (char *)(intptr_t)kw); }
    if (k == _KW_CONT) {
        char *v = mojo_dict_get_str(d, ck);
        mojo_dict_key_free(ck);
        return v;
    }
    _DictSlot *sl = _dict_lookup_ik(d, kw);
    return sl ? (char *)(uintptr_t)sl->val : NULL;
}

void mojo_dict_set_int_kw(MojoDict *d, int64_t kw, int64_t v)
{
    char *ck; int k = _kw_kind(kw, &ck);
    if (k == _KW_STR) { mojo_dict_set_int(d, (char *)(intptr_t)kw, v); return; }
    if (k == _KW_CONT) {
        mojo_dict_set_int(d, ck, v);
        mojo_dict_key_free(ck);
        return;
    }
    _dict_set_ik(d, kw, v, 0);
}

void mojo_dict_set_double_kw(MojoDict *d, int64_t kw, double v)
{
    char *ck; int k = _kw_kind(kw, &ck);
    if (k == _KW_STR) { mojo_dict_set_double(d, (char *)(intptr_t)kw, v); return; }
    if (k == _KW_CONT) {
        mojo_dict_set_double(d, ck, v);
        mojo_dict_key_free(ck);
        return;
    }
    int64_t bits;
    memcpy(&bits, &v, sizeof(bits));
    _dict_set_ik(d, kw, bits, 1);
}

void mojo_dict_set_str_kw(MojoDict *d, int64_t kw, char *v)
{
    char *ck; int k = _kw_kind(kw, &ck);
    if (k == _KW_STR) { mojo_dict_set_str(d, (char *)(intptr_t)kw, v); return; }
    if (k == _KW_CONT) {
        mojo_dict_set_str(d, ck, v);
        mojo_dict_key_free(ck);
        return;
    }
    _dict_set_ik(d, kw, (int64_t)(uintptr_t)v, 2);
}

int mojo_dict_contains_kw(MojoDict *d, int64_t kw)
{
    char *ck; int k = _kw_kind(kw, &ck);
    if (k == _KW_STR) return mojo_dict_contains(d, (char *)(intptr_t)kw);
    if (k == _KW_CONT) {
        int hit = mojo_dict_contains(d, ck);
        mojo_dict_key_free(ck);
        return hit;
    }
    return _dict_lookup_ik(d, kw) != NULL;
}

int64_t mojo_dict_pop_int_kw(MojoDict *d, int64_t kw)
{
    char *ck; int k = _kw_kind(kw, &ck);
    if (k == _KW_STR) return mojo_dict_pop_int(d, (char *)(intptr_t)kw);
    if (k == _KW_CONT) {
        int64_t v = mojo_dict_pop_int(d, ck);
        mojo_dict_key_free(ck);
        return v;
    }
    _DictSlot *sl = _dict_lookup_ik(d, kw);
    if (!sl) return 0;
    int64_t val = sl->val;
    _dict_remove_slot(d, sl);
    return val;
}

/* `setdefault` is the one `_kw` twin that asks the dict TWICE (contains, then
 * get or set), and a content key is a fresh string each time — so it is built
 * ONCE and both queries use it. Building it twice would be correct but would
 * render the whole tuple twice for what is one logical key, on a path that runs
 * in a loop. The `d == NULL` early return comes first because `mojo_dict_key_for`
 * can raise, and a `setdefault` on no dict at all should answer the default
 * without raising about the key it was handed. */
int64_t mojo_dict_setdefault_int_kw(MojoDict *d, int64_t kw, int64_t dflt)
{
    if (!d) return dflt;
    char *ck; int k = _kw_kind(kw, &ck);
    if (k == _KW_STR) {
        if (mojo_dict_contains_kw(d, kw)) return mojo_dict_get_int_kw(d, kw);
        mojo_dict_set_int_kw(d, kw, dflt);
        return dflt;
    }
    if (k == _KW_CONT) {
        int64_t v = mojo_dict_contains(d, ck) ? mojo_dict_get_int(d, ck)
                                              : (mojo_dict_set_int(d, ck, dflt), dflt);
        mojo_dict_key_free(ck);
        return v;
    }
    if (mojo_dict_contains_kw(d, kw)) return mojo_dict_get_int_kw(d, kw);
    mojo_dict_set_int_kw(d, kw, dflt);
    return dflt;
}

char *mojo_dict_setdefault_str_kw(MojoDict *d, int64_t kw, char *dflt)
{
    if (!d) return dflt;
    char *ck; int k = _kw_kind(kw, &ck);
    if (k == _KW_STR) {
        if (mojo_dict_contains_kw(d, kw)) return mojo_dict_get_str_kw(d, kw);
        mojo_dict_set_str_kw(d, kw, dflt);
        return dflt;
    }
    if (k == _KW_CONT) {
        char *v;
        if (mojo_dict_contains(d, ck)) v = mojo_dict_get_str(d, ck);
        else { mojo_dict_set_str(d, ck, dflt); v = dflt; }
        mojo_dict_key_free(ck);
        return v;
    }
    if (mojo_dict_contains_kw(d, kw)) return mojo_dict_get_str_kw(d, kw);
    mojo_dict_set_str_kw(d, kw, dflt);
    return dflt;
}


void *mojo_range(int64_t start, int64_t stop) {
    MojoList *l = mojo_list_new();
    for (int64_t i = start; i < stop; i++)
        mojo_list_append_int(l, i);
    return l;
}

void *mojo_range3(int64_t start, int64_t stop, int64_t step) {
    MojoList *l = mojo_list_new();
    if (step > 0) {
        for (int64_t i = start; i < stop; i += step)
            mojo_list_append_int(l, i);
    } else if (step < 0) {
        for (int64_t i = start; i > stop; i += step)
            mojo_list_append_int(l, i);
    }
    return l;
}

void *mojo_reversed(void *iterable) {
    MojoList *src = (MojoList *)iterable;
    MojoList *dst = mojo_list_copy(src);
    mojo_list_reverse(dst);
    return dst;
}

/* Reverse a list in place and return it — `sorted(x, reverse=True)` with no
   key is the type-aware sort followed by this, NOT a reverse-then-sort in
   the caller: the element-wise sorts are type-dispatched (mojo_sorted for
   ints, mojo_list_sorted_str for strings, ...), so ordering by the raw
   int64_t slots here would sort strings by ADDRESS instead of
   lexicographically. */
MojoList *mojo_list_reversed(MojoList *l) {
    if (!l) return l;
    for (int64_t i = 0, j = l->len - 1; i < j; i++, j--) {
        int64_t t = l->data[i]; l->data[i] = l->data[j]; l->data[j] = t;
    }
    /* The slots moved, so the kinds have to move with them. A FRESH string
     * rather than an in-place reverse: the recorded one is shared with
     * every copy and slice taken from this list (mojo_list_inherit_kinds
     * hands over the same pointer), and reversing it in place would
     * re-describe all of those. */
    const char *k = mojo_list_get_kinds(l);
    if (k) {
        int64_t n = mojo_list_len(l);
        char *rk = (char *)malloc((size_t)n + 1);
        for (int64_t i = 0; i < n; i++) rk[i] = k[n - 1 - i];
        rk[n] = '\0';
        mojo_list_set_kinds(l, rk);
    }
    return l;
}

/* `sorted(x, key=f)`: order `items` by the key each element maps to.
   `keys` is a parallel list the caller built by calling `f` per element (the
   compiled path has no per-element callback in the runtime, so it lowers the
   key call itself — see _lower_builtin_sorted), and `reverse` selects
   descending order, matching `sorted(..., reverse=True)`.

   `keys` is never NULL: the keyless `sorted(x, reverse=True)` reverses the
   result of the ordinary type-aware sort instead (see _lower_builtin_sorted),
   which is what keeps `sorted(["b","a"], reverse=True)` lexicographic rather
   than ordered by the string addresses in its int64_t slots.

   String keys are compared with strcmp, not as int64_t slots. The key
   function's return type cannot settle that at compile time — a lambda's is
   declared int64_t whatever it returns — so the runtime uses the model's own
   discriminator (mojo_boxed_is_str: pointer-shaped and not a live registered
   list), decided ONCE for the whole sort so the ordering stays consistent. */
MojoList *mojo_sorted_by_keys(MojoList *items, MojoList *keys, int reverse) {
    MojoList *dst = mojo_list_copy(items);
    if (!keys) return dst;
    int kind = MOJO_KIND_INT;
    if (keys->len > 0) {
        if (mojo_boxed_is_str(mojo_list_get_int(keys, 0))) {
            kind = MOJO_KIND_STR;
        } else if (keys->len > 1
                   && mojo_boxed_is_str(mojo_list_get_int(keys, 1))) {
            kind = MOJO_KIND_STR;
        }
    }
    _mojo_permute_by(dst, keys, kind, reverse);
    return dst;
}

void *mojo_sorted(void *iterable) {
    MojoList *src = (MojoList *)iterable;
    /* The generic int64-payload sort. Correct for int lists, and wrong for a
     * list whose elements are char* — see mojo_list_sorted_str below for why
     * the codegen dispatches around this one. */
    MojoList *dst = mojo_list_copy(src);
    _mojo_permute_by(dst, NULL, MOJO_KIND_INT, 0);
    return (void *)dst;
}

/* String-aware `sorted()` variants. The generic mojo_sorted above compares
 * the stored int64_t payloads — correct for int lists, but for a list whose
 * elements are char* pointers (a dict's keys, a set of module names, ...) it
 * orders by pointer VALUE, which is both non-deterministic across runs and
 * different from Python's alphabetical `sorted(...)`. The codegen picks these
 * by its own knowledge of the element type (see _lower_builtin_sorted), so the
 * runtime never has to guess. */
MojoList *mojo_list_sorted_str(MojoList *src) {
    MojoList *dst = mojo_list_copy(src);
    /* Sorting PERMUTES the slots, so the per-slot kinds copied along no
     * longer describe them; drop them rather than let a reader trust a
     * string that is now attached to the wrong slots. (Python refuses to
     * sort a mixed-type sequence at all, so nothing that reaches here is a
     * case where a correct answer exists.) */
    mojo_list_set_kinds(dst, NULL);
    _mojo_permute_by(dst, NULL, MOJO_KIND_STR, 0);
    return dst;
}

MojoList *mojo_set_sorted(MojoSet *s) {
    MojoList *out = mojo_list_new();
    if (!s) return out;
    int is_str = 0;
    for (int64_t i = 0; i < s->cap; i++) {
        if (s->slots[i].tag == 0)
            mojo_list_append_int(out, s->slots[i].val_i);
        else if (s->slots[i].tag == 1) {
            mojo_list_append_str(out, s->slots[i].val_s);
            is_str = 1;
        }
    }
    return is_str ? mojo_list_sorted_str(out) : mojo_sorted(out);
}

/* Insertion-order materialization — the set analogue of mojo_dict_keys.
 * Unlike mojo_set_sorted (for Python's explicit sorted(some_set)), this
 * backs iterable-consuming ops (all()/any()/enumerate()/str.join()/...)
 * so they see the SAME order as a plain `for x in s:` loop, which itself
 * walks mojo_set_order_indices — see that function's docstring for why
 * insertion order (not hash-slot order) is this runtime's determinism
 * requirement for sets. */
MojoList *mojo_set_to_list(MojoSet *s) {
    MojoList *out = mojo_list_new();
    if (!s || s->used == 0) return out;
    int64_t *order = mojo_set_order_indices(s);
    for (int64_t oi = 0; oi < s->used; oi++) {
        int64_t i = order[oi];
        if (s->slots[i].tag == 0)
            mojo_list_append_int(out, s->slots[i].val_i);
        else
            mojo_list_append_str(out, s->slots[i].val_s);
    }
    free(order);
    return out;
}

MojoList *mojo_dict_sorted_keys(MojoDict *d) {
    return mojo_list_sorted_str(mojo_dict_keys(d));
}

/* `sorted(d.items())` — a list of (key, value) 2-element sub-lists, sorted by
 * KEY (string comparison on element 0), matching Python's lexicographic tuple
 * ordering (keys are distinct so the key comparison decides every pair).
 * `mojo_sorted`'s int64 payload sort would order the tuple POINTERS, a
 * non-deterministic order that diverges from `python3 mojo.py --dump`
 * (visible in generated struct-typedef field order, e.g.
 * `for field_name, field_type in sorted(fields.items()):`). */
MojoList *mojo_dict_items_sorted(MojoDict *d) {
    MojoList *items = mojo_dict_items(d);
    if (!items || items->len < 2) return items;
    for (int64_t i = 0; i < items->len; i++) {
        for (int64_t j = i + 1; j < items->len; j++) {
            MojoList *a = (MojoList *)(uintptr_t)items->data[i];
            MojoList *b = (MojoList *)(uintptr_t)items->data[j];
            if (strcmp((char *)(uintptr_t)a->data[0], (char *)(uintptr_t)b->data[0]) > 0) {
                int64_t tmp = items->data[i];
                items->data[i] = items->data[j];
                items->data[j] = tmp;
            }
        }
    }
    return items;
}

int64_t mojo_sum(void *args) {
    MojoList *l = (MojoList *)args;
    int64_t total = 0;
    for (int64_t i = 0; i < l->len; i++)
        total += mojo_list_get_int(l, i);
    return total;
}

/* sum() over a list this codegen tracks (via _elem_types) as holding
 * doubles -- mojo_sum's plain mojo_list_get_int reads each slot's raw
 * int64_t bit pattern, silently truncating/misreading every float
 * element (found via Tools/lockbench/lockbench.py's `sum(values)` on a
 * list of floats). */
double mojo_sum_double(void *args) {
    MojoList *l = (MojoList *)args;
    double total = 0.0;
    for (int64_t i = 0; i < l->len; i++)
        total += mojo_list_get_double(l, i);
    return total;
}

/* zip(a, b) -> list of 2-element pair lists, truncated to the SHORTER
 * input (real Python semantics). Was a stub that unconditionally returned
 * an EMPTY list, so every `zip()` reaching a runtime call site (>2-sequence
 * chains via _lower_builtin_zip_n, `list(zip(...))`, or a `for` shape the
 * dedicated _gen_for_zip lowering declines) silently iterated zero times
 * instead of failing loudly. Pairs box each slot with append_int, the same
 * convention mojo_dict_items uses for its [key, value] pairs, so the
 * existing tuple-unpack accessors read them unchanged. */
void *mojo_zip(void *a, void *b) {
    MojoList *la = (MojoList *)a;
    MojoList *lb = (MojoList *)b;
    MojoList *out = mojo_list_new();
    if (!la || !lb) return out;
    int64_t n = la->len < lb->len ? la->len : lb->len;
    for (int64_t i = 0; i < n; i++) {
        MojoList *pair = mojo_list_new();
        mojo_list_append_int(pair, mojo_list_get_int(la, i));
        mojo_list_append_int(pair, mojo_list_get_int(lb, i));
        /* zip() yields TUPLES in Python, and this model's tuple marker is
         * what the repr reads to choose `(...)` over `[...]` (see
         * mojo_mark_as_tuple). Unmarked, `print(zip([1,2],[3,4]))` printed
         * `[[1, 3], [2, 4]]` and `isinstance(pair, tuple)` was False. */
        mojo_mark_as_tuple(pair);
        mojo_list_append_int(out, (int64_t)(intptr_t)pair);
    }
    return out;
}

/* Sets a dynamic attribute on `obj`'s own per-object dict — see the
 * `_mojo_dynattr_objects` block (mojo_obj_getattr, above) for the storage
 * scheme this shares. Reached whenever codegen couldn't statically resolve
 * `obj.attr = val` to a real struct field (bugs/hard/CODEGEN_dynamic_
 * attribute_on_generic_object.md, Steps 1/3). Previously a silent no-op —
 * `cls.__slot_names__ = []`-shaped code compiled but the assignment never
 * actually stuck anywhere, so a later read saw nothing. */
void mojo_setattr(void *obj, char *attr, int64_t val) {
    if (!_mojo_dynattr_objects) _mojo_dynattr_objects = mojo_dict_new();
    char key[32];
    _mojo_dynattr_key(obj, key, sizeof key);
    int64_t handle = mojo_dict_get_int(_mojo_dynattr_objects, key);
    MojoDict *attrs;
    if (handle) {
        attrs = (MojoDict *)(intptr_t)handle;
    } else {
        attrs = mojo_dict_new();
        mojo_dict_set_int(_mojo_dynattr_objects, key, (int64_t)(intptr_t)attrs);
    }
    mojo_dict_set_int(attrs, attr, val);
}

void mojo_delattr(void *obj, char *attr) {
    (void)obj; (void)attr;  /* no dynamic attribute deletion in the compiled
                               runtime — attributes are struct fields */
}

void setattr(int obj, int attr, int value) {
    (void)obj; (void)attr; (void)value;
}

int64_t mojo_max(void *args) {
    MojoList *l = (MojoList *)args;
    if (!l || l->len == 0) return 0;
    int64_t m = mojo_list_get_int(l, 0);
    for (int64_t i = 1; i < l->len; i++) {
        int64_t v = mojo_list_get_int(l, i);
        if (v > m) m = v;
    }
    return m;
}

int64_t mojo_min(void *args) {
    MojoList *l = (MojoList *)args;
    if (!l || l->len == 0) return 0;
    int64_t m = mojo_list_get_int(l, 0);
    for (int64_t i = 1; i < l->len; i++) {
        int64_t v = mojo_list_get_int(l, i);
        if (v < m) m = v;
    }
    return m;
}

/* min()/max() over a list this codegen tracks (via _elem_types) as holding
 * doubles — the plain int64_t mojo_min/mojo_max above compare each slot's
 * raw bit pattern, misordering negatives and non-representable magnitudes.
 * Mirrors mojo_sum_double's identical "route through _elem_types" fix. */
double mojo_max_double(void *args) {
    MojoList *l = (MojoList *)args;
    if (!l || l->len == 0) return 0.0;
    double m = mojo_list_get_double(l, 0);
    for (int64_t i = 1; i < l->len; i++) {
        double v = mojo_list_get_double(l, i);
        if (v > m) m = v;
    }
    return m;
}

double mojo_min_double(void *args) {
    MojoList *l = (MojoList *)args;
    if (!l || l->len == 0) return 0.0;
    double m = mojo_list_get_double(l, 0);
    for (int64_t i = 1; i < l->len; i++) {
        double v = mojo_list_get_double(l, i);
        if (v < m) m = v;
    }
    return m;
}

/* ── String/Number conversion (used directly in compiled code) ─────── */
/* Backs both bare `int(s)` and `int(s, 0)` (gimple_codegen.py's _lower_call
 * drops the base argument entirely and always calls this) — so this must
 * replicate Python's int(s, 0) auto-base-detection (0x/0X hex, 0o/0O octal,
 * 0b/0B binary, else decimal) itself. The previous plain atoll() doesn't
 * understand any of those prefixes; atoll("0x2545F4914F6CDD1D") stops
 * parsing at 'x' and silently returns 0 — found via a source literal like
 * `0xFFFFFFFFFFFFFFFF` parsing as IntLiteral(value=0) instead of the real
 * value once self-hosted (mojo.py's own repr(ast) dump on test_simple.mojo's
 * xorshift64star, which hashes with exactly this kind of hex mask
 * constant). Uses strtoull (unsigned) then casts to int64_t: a hex literal
 * with the sign bit set (e.g. the all-ones 64-bit mask above) is stored as
 * the equivalent negative machine word, same as a real 64-bit register
 * would hold it — this runtime has no bignum type to hold the literal
 * value exactly the way Python's arbitrary-precision int does. */
int64_t mojo_make_int(char *s) {
    if ((intptr_t)s < 65536) return (int64_t)(intptr_t)s;
    if (s[0] == '0' && (s[1] == 'b' || s[1] == 'B'))
        return (int64_t)strtoull(s + 2, NULL, 2);
    if (s[0] == '0' && (s[1] == 'o' || s[1] == 'O'))
        return (int64_t)strtoull(s + 2, NULL, 8);
    if (s[0] == '0' && (s[1] == 'x' || s[1] == 'X'))
        return (int64_t)strtoull(s + 2, NULL, 16);
    return (int64_t)atoll(s);
}
double mojo_make_float(char *s) { return s ? atof(s) : 0.0; }
int mojo_make_bool(int val) { return val ? 1 : 0; }
void *mojo_make_list(void) { return mojo_list_new(); }
void *mojo_make_dict(void) { return mojo_dict_new(); }
void *mojo_make_set(void) { return mojo_set_new(); }
void *mojo_make_tuple(void) { return mojo_list_new(); }

/* ── Stubs for interpreter dispatch (only used as function-pointer targets) ── */
int MojoParser() { return 0; }
int64_t mojo_len(int obj) { (void)obj; return 0; }
int mojo_getattr(int obj, char *attr) { (void)obj; (void)attr; return 0; }
void *mojo_enumerate(void *iterable) { return iterable; }
void *mojo_filter(void *func, void *iterable) { (void)func; return iterable; }
void *mojo_map(void *func, void *iterable) { (void)func; return iterable; }

/* ── Floating-point division helper ──────────────────────────────────
   gcc -fgimple ICEs (expmed_mode_index, expmed.h:239) when a float/double
   division operation appears inside a __GIMPLE function body. We emit a call
   to these normal-C helpers instead; the division is expanded here, in a
   regularly-compiled translation unit, where it works correctly. */
double mojo_div_double(double a, double b) { return a / b; }
float  mojo_div_float(float a, float b)    { return a / b; }

/* Decimal string of an integer (heap-allocated). Used when a string is
   concatenated with a numeric operand (String + Int) so codegen never has
   to emit an invalid `char* + int` expression. */
/* Decimal string of a floating-point value, formatted the way Python's
 * str(float) is: `%.17g`, with the trailing ".0" re-added for a whole number so
 * `3.0` does not print as "3".
 *
 * Exists because a FLOAT dict key has to become a string to be looked up —
 * the runtime keys every dict by a `char *` — and the codegen had no way to
 * produce one: `_char_to_cstr` handles `char` and `int64_t` and otherwise fell
 * through to a raw `(char *)value` bit-cast, which for a `double` is not valid
 * C at all ("cannot convert to a pointer type") and would have been a garbage
 * pointer even if it compiled. Call sites: `d[Float64(0.0)] = v` in the
 * stdlib's test/collections/test_dict.mojo.
 *
 * Negative zero needs no special case and gets none: `%.17g` prints `-0.0` as
 * "-0", which is Python's own spelling and keeps it a distinct key from "0".
 * The stdlib test that needs this is precisely the signed-zero one, since
 * `-0.0 == 0.0` numerically is what makes two such inserts collide on one key
 * — so the two spellings must agree between themselves, which they do.
 *
 * A whole number is detected by the ABSENCE of `.`, `e`/`E` and the `nan`/`inf`
 * spellings in the formatted output.
 *
 * ALLOCATED FROM THE TRANSIENT POOL, not with malloc. The release half of this
 * contract is `mojo_cstr_or_int_release`, which does not free: it links the
 * block onto `_int_str_pool` for the next access to reuse. A malloc'd block put
 * through that path was a live bug — the pool hands out `_INT_STR_BLOCK`-sized
 * blocks with no size of its own, so a differently-sized block on the free list
 * is a buffer overrun on the next use, and the malloc is never reclaimed
 * (+16 B per dict access, measured on build/memprobes/float_dict_key.mojo).
 * `_INT_STR_BLOCK` is sized to fit this output for exactly that reason. */
char *mojo_str_from_double(double v) {
    char tmp[_INT_STR_BLOCK];
    snprintf(tmp, sizeof tmp, "%.17g", v);
    size_t n = strlen(tmp);
    if (n && !strpbrk(tmp, ".eEnN")) {
        if (n + 3 <= sizeof tmp) {   /* room for the ".0" and the NUL */
            tmp[n] = '.'; tmp[n + 1] = '0'; tmp[n + 2] = '\0'; n += 2;
        }
    }
    char *out = _int_str_block();
    memcpy(out, tmp, n + 1);
    return out;
}

char *mojo_str_from_int(int64_t v) {
    /* A string that is KEPT (concatenated into a result, stored as a dict
     * value, bound to a local) gets an exact-size allocation. The pooled
     * fixed-size blocks below are only for the transient Int dict-key path,
     * which releases them; giving kept strings 24-byte blocks made every such
     * leak ~4x larger. */
    char tmp[_INT_STR_BLOCK];
    char *p = _fmt_int(v, tmp);
    size_t n = (size_t)(tmp + sizeof tmp - p);
    char *out = (char *)malloc(n);
    memcpy(out, p, n);
    return out;
}

/* Python's divmod(a, b) builtin: (a // b, a % b) as a real 2-tuple, using
 * the SAME floor-division adjustment __mojo_floordiv (fire_runtime.h) uses
 * for `//`, so the remainder here is always consistent with that quotient
 * (same sign as b) -- not C's truncating a % b. */
MojoList *mojo_divmod(int64_t a, int64_t b) {
    int64_t q = a / b;
    q -= (a % b != 0 && (a ^ b) < 0);
    int64_t r = a - q * b;
    MojoList *out = mojo_list_new();
    mojo_mark_as_tuple(out);
    mojo_list_append_int(out, q);
    mojo_list_append_int(out, r);
    return out;
}

/* Python's 3-arg pow(base, exp, mod) builtin: modular exponentiation via
 * right-to-left binary exponentiation (square-and-multiply), all-integer --
 * distinct from the ordinary 2-arg pow(x, y), which stays real-valued
 * (libc's own pow(double, double)). `exp` is assumed non-negative (real
 * Python raises for a negative exponent here too; this codegen has no
 * exception path out of a runtime helper, so a negative exponent just
 * yields 0 rather than looping incorrectly). */
int64_t mojo_pow_mod(int64_t base, int64_t exp, int64_t mod) {
    if (mod == 0) return 0;
    int64_t neg = mod < 0;
    int64_t m = neg ? -mod : mod;
    int64_t result = 1 % m;
    int64_t b = ((base % m) + m) % m;
    while (exp > 0) {
        if (exp & 1) result = (result * b) % m;
        b = (b * b) % m;
        exp >>= 1;
    }
    return neg && result != 0 ? result - m : result;
}

/* Python's hex()/oct()/bin() builtins: a signed 0x/0o/0b-prefixed string,
 * sign BEFORE the prefix for negative values (hex(-26) == '-0x1a', not
 * two's-complement) -- matching real Python exactly, not C's %x/%o. */
char *mojo_hex(int64_t v) {
    char buf[32];
    if (v < 0) snprintf(buf, sizeof buf, "-0x%llx", (unsigned long long)(-v));
    else       snprintf(buf, sizeof buf, "0x%llx", (unsigned long long)v);
    char *out = (char *)malloc(strlen(buf) + 1);
    strcpy(out, buf);
    return out;
}

char *mojo_oct(int64_t v) {
    char buf[32];
    if (v < 0) snprintf(buf, sizeof buf, "-0o%llo", (unsigned long long)(-v));
    else       snprintf(buf, sizeof buf, "0o%llo", (unsigned long long)v);
    char *out = (char *)malloc(strlen(buf) + 1);
    strcpy(out, buf);
    return out;
}

char *mojo_bin(int64_t v) {
    char digits[70];
    int i = 69;
    digits[i--] = '\0';
    unsigned long long u = (v < 0) ? (unsigned long long)(-v) : (unsigned long long)v;
    if (u == 0) digits[i--] = '0';
    while (u > 0) { digits[i--] = '0' + (int)(u & 1ULL); u >>= 1; }
    char buf[80];
    snprintf(buf, sizeof buf, "%s0b%s", (v < 0) ? "-" : "", digits + i + 1);
    char *out = (char *)malloc(strlen(buf) + 1);
    strcpy(out, buf);
    return out;
}

/* Arbitrary-precision digit-string -> decimal-string conversion, via
 * schoolbook "multiply existing decimal digits by base, add next digit"
 * (no division needed). Used ONLY so a compiled AST dump can print an
 * IntLiteral's exact source value even when it doesn't fit in int64_t (e.g.
 * the all-ones 64-bit mask 0xFFFFFFFFFFFFFFFF, which as int64_t wraps to
 * -1) — matching Python's own arbitrary-precision int repr. Real compiled
 * arithmetic still correctly uses the wrapped int64_t `value` field; this
 * exists purely for dump-fidelity, not as general bignum support. 48
 * decimal digits covers over 128 bits, comfortably more than any literal
 * actually written in this codebase. */
static char *_bignum_digits_to_decimal(const char *digits_str, int base) {
    unsigned char digits[48] = {0};
    int ndigits = 1;
    for (const char *p = digits_str; *p; p++) {
        char c = *p;
        if (c == '_') continue;
        int dv;
        if (c >= '0' && c <= '9') dv = c - '0';
        else if (c >= 'a' && c <= 'z') dv = c - 'a' + 10;
        else if (c >= 'A' && c <= 'Z') dv = c - 'A' + 10;
        else continue;
        if (dv >= base) continue;
        int carry = dv;
        for (int i = 0; i < ndigits; i++) {
            int prod = digits[i] * base + carry;
            digits[i] = (unsigned char)(prod % 10);
            carry = prod / 10;
        }
        while (carry > 0 && ndigits < 48) {
            digits[ndigits++] = (unsigned char)(carry % 10);
            carry /= 10;
        }
    }
    char *out = malloc((size_t)ndigits + 1);
    for (int i = 0; i < ndigits; i++)
        out[i] = (char)('0' + digits[ndigits - 1 - i]);
    out[ndigits] = '\0';
    return out;
}

char *mojo_int_literal_decimal(char *raw) {
    if (!raw || !raw[0]) return strdup("0");
    const char *p = raw;
    int neg = 0;
    if (*p == '-') { neg = 1; p++; }
    else if (*p == '+') { p++; }
    int base = 10;
    if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) { base = 16; p += 2; }
    else if (p[0] == '0' && (p[1] == 'o' || p[1] == 'O')) { base = 8; p += 2; }
    else if (p[0] == '0' && (p[1] == 'b' || p[1] == 'B')) { base = 2; p += 2; }
    char *dec = _bignum_digits_to_decimal(p, base);
    if (!neg) return dec;
    char *out = malloc(strlen(dec) + 2);
    out[0] = '-';
    strcpy(out + 1, dec);
    free(dec);
    return out;
}

/* ── Small, bounded regex engine ─────────────────────────────────────────
 * See regex_compile.py (compile-time parser/emitter) and BACKLOG-CODEGEN.md
 * §4f for why this exists: re.Pattern.finditer() had no codegen lowering at
 * all, so the self-hosted tokenizer (mojo_compiler.py's py_tokenize, built
 * on _TOKEN_RE.finditer()) silently produced an empty token stream whenever
 * the compiled Parser ran in-process instead of via the interpreted-Python
 * subprocess fallback. Supports exactly the subset of Python regex syntax
 * _TOKEN_RE-shaped patterns use: literals, '.', character classes (ranges,
 * negation, \d \s \S \w \W), alternation, capturing/non-capturing/named
 * groups, and the quantifiers * + ? {m,n} greedy and non-greedy. No
 * lookaround, no backreferences, no \b, no flags — not a general `re`
 * implementation. Kept in this file (rather than its own object) so every
 * existing build site that already links fire_runtime.c gets it for free.
 * ReNode/ReRange/ReClassInfo are declared once, in fire_runtime.h. */

#define RE_OP_CHAR   0
#define RE_OP_ANY    1
#define RE_OP_CLASS  2
#define RE_OP_CONCAT 3
#define RE_OP_ALT    4
#define RE_OP_GROUP  5
#define RE_OP_REPEAT 6

/* Continuation list: "what to match next after the current node succeeds."
 * kind 0: match node `node_idx` next.
 * kind 1: this is the closing half of a GROUP -- record its end position,
 *         then continue with `next`.
 * kind 2: this is the "try one more repetition" step of a REPEAT -- see
 *         match_repeat below.
 * A NULL continuation means "nothing left to match -- this position is the
 * overall match end." Allocated on the C call stack (one frame per
 * GROUP/REPEAT/CONCAT step actually taken), never heap-allocated. */
typedef struct ReCont {
    int kind;
    int node_idx;                                     /* kind 0 */
    int group_idx;                                     /* kind 1 */
    int r_inner_idx, r_lo, r_hi, r_greedy, r_count;     /* kind 2 */
    int64_t r_start_pos;                                 /* kind 2 */
    const struct ReCont *next;
} ReCont;

static int64_t re_match_node(const ReNode *prog, const ReRange *ranges, const ReClassInfo *classinfo,
                              const char *text, int64_t text_len, int node_idx, int64_t pos,
                              const ReCont *cont, int64_t *gstart, int64_t *gend);

static int64_t re_match_cont(const ReNode *prog, const ReRange *ranges, const ReClassInfo *classinfo,
                              const char *text, int64_t text_len, int64_t pos,
                              const ReCont *cont, int64_t *gstart, int64_t *gend);

static int64_t re_match_repeat(const ReNode *prog, const ReRange *ranges, const ReClassInfo *classinfo,
                                const char *text, int64_t text_len,
                                int inner_idx, int lo, int hi, int greedy, int count, int64_t pos,
                                const ReCont *outer_cont, int64_t *gstart, int64_t *gend) {
    if (greedy) {
        if (hi < 0 || count < hi) {
            ReCont rep_cont = { 2, 0, 0, inner_idx, lo, hi, greedy, count, pos, outer_cont };
            int64_t r = re_match_node(prog, ranges, classinfo, text, text_len, inner_idx, pos, &rep_cont, gstart, gend);
            if (r >= 0) return r;
        }
        if (count >= lo) return re_match_cont(prog, ranges, classinfo, text, text_len, pos, outer_cont, gstart, gend);
        return -1;
    } else {
        if (count >= lo) {
            int64_t r = re_match_cont(prog, ranges, classinfo, text, text_len, pos, outer_cont, gstart, gend);
            if (r >= 0) return r;
        }
        if (hi < 0 || count < hi) {
            ReCont rep_cont = { 2, 0, 0, inner_idx, lo, hi, greedy, count, pos, outer_cont };
            return re_match_node(prog, ranges, classinfo, text, text_len, inner_idx, pos, &rep_cont, gstart, gend);
        }
        return -1;
    }
}

static int64_t re_match_cont(const ReNode *prog, const ReRange *ranges, const ReClassInfo *classinfo,
                              const char *text, int64_t text_len, int64_t pos,
                              const ReCont *cont, int64_t *gstart, int64_t *gend) {
    if (!cont) return pos;
    if (cont->kind == 0) {
        return re_match_node(prog, ranges, classinfo, text, text_len, cont->node_idx, pos, cont->next, gstart, gend);
    }
    if (cont->kind == 1) {
        int64_t old_end = gend[cont->group_idx];
        gend[cont->group_idx] = pos;
        int64_t r = re_match_cont(prog, ranges, classinfo, text, text_len, pos, cont->next, gstart, gend);
        if (r < 0) gend[cont->group_idx] = old_end;
        return r;
    }
    /* kind == 2: one more repetition, unless it would be a zero-width
     * repeat past the minimum (which would loop forever). */
    if (pos == cont->r_start_pos && cont->r_count >= cont->r_lo) return -1;
    return re_match_repeat(prog, ranges, classinfo, text, text_len,
                           cont->r_inner_idx, cont->r_lo, cont->r_hi, cont->r_greedy, cont->r_count + 1,
                           pos, cont->next, gstart, gend);
}

static int64_t re_match_node(const ReNode *prog, const ReRange *ranges, const ReClassInfo *classinfo,
                              const char *text, int64_t text_len, int node_idx, int64_t pos,
                              const ReCont *cont, int64_t *gstart, int64_t *gend) {
    const ReNode *n = &prog[node_idx];
    switch (n->op) {
    case RE_OP_CHAR:
        if (pos < text_len && (unsigned char)text[pos] == (unsigned char)n->a)
            return re_match_cont(prog, ranges, classinfo, text, text_len, pos + 1, cont, gstart, gend);
        return -1;
    case RE_OP_ANY:
        if (pos < text_len && text[pos] != '\n')
            return re_match_cont(prog, ranges, classinfo, text, text_len, pos + 1, cont, gstart, gend);
        return -1;
    case RE_OP_CLASS: {
        if (pos >= text_len) return -1;
        const ReClassInfo *info = &classinfo[n->a];
        unsigned char ch = (unsigned char)text[pos];
        int inside = 0;
        for (int i = 0; i < info->count; i++) {
            const ReRange *r = &ranges[info->offset + i];
            if (ch >= r->lo && ch <= r->hi) { inside = 1; break; }
        }
        if (inside != n->b) return re_match_cont(prog, ranges, classinfo, text, text_len, pos + 1, cont, gstart, gend);
        return -1;
    }
    case RE_OP_CONCAT: {
        if (n->a < 0) return re_match_cont(prog, ranges, classinfo, text, text_len, pos, cont, gstart, gend);
        ReCont cont2 = { 0, n->b, 0, 0, 0, 0, 0, 0, 0, cont };
        return re_match_node(prog, ranges, classinfo, text, text_len, n->a, pos, &cont2, gstart, gend);
    }
    case RE_OP_ALT: {
        int64_t r = re_match_node(prog, ranges, classinfo, text, text_len, n->a, pos, cont, gstart, gend);
        if (r >= 0) return r;
        return re_match_node(prog, ranges, classinfo, text, text_len, n->b, pos, cont, gstart, gend);
    }
    case RE_OP_GROUP: {
        int gi = n->c;
        if (gi == 0) {
            /* non-capturing group */
            return re_match_node(prog, ranges, classinfo, text, text_len, n->a, pos, cont, gstart, gend);
        }
        int64_t old_start = gstart[gi], old_end = gend[gi];
        gstart[gi] = pos;
        ReCont mark = { 1, 0, gi, 0, 0, 0, 0, 0, 0, cont };
        int64_t r = re_match_node(prog, ranges, classinfo, text, text_len, n->a, pos, &mark, gstart, gend);
        if (r < 0) { gstart[gi] = old_start; gend[gi] = old_end; }
        return r;
    }
    case RE_OP_REPEAT:
        return re_match_repeat(prog, ranges, classinfo, text, text_len, n->a, n->d, n->e, n->f, 0, pos, cont, gstart, gend);
    }
    return -1;
}

/* Searches for the pattern starting at or after from_pos (mirrors
 * re.Pattern.finditer's per-iteration scan, NOT re.match's anchored-at-start
 * semantics). On success, returns 1 and fills out_start/out_end with the
 * whole-match span, and gstart[1..ngroups]/gend[1..ngroups] with each
 * capturing group's span (-1/-1 if that group didn't participate in this
 * particular match). Returns 0 if no match exists anywhere in
 * [from_pos, text_len]. gstart/gend must have ngroups+1 elements (index 0
 * is unused; groups are 1-based, matching Python's re.Match.group(1) etc). */
int mojo_regex_search(const ReNode *prog, const ReRange *ranges, const ReClassInfo *classinfo,
                       int root, int ngroups, const char *text, int64_t text_len, int64_t from_pos,
                       int64_t *out_start, int64_t *out_end, int64_t *gstart, int64_t *gend) {
    for (int64_t start = from_pos; start <= text_len; start++) {
        for (int i = 0; i <= ngroups; i++) { gstart[i] = -1; gend[i] = -1; }
        int64_t end = re_match_node(prog, ranges, classinfo, text, text_len, root, start, (const ReCont *)0, gstart, gend);
        if (end >= 0) {
            *out_start = start;
            *out_end = end;
            return 1;
        }
    }
    return 0;
}

/* Python's Match.lastgroup: the name of the highest-index capturing group
 * that actually participated in the match, or NULL if none of the named
 * groups did (e.g. the match went through an unnamed/non-capturing
 * alternative). names[i] is the compile-time-known name for group i (index
 * 0 unused, NULL for unnamed groups) -- see regex_compile.py's compile_pattern. */
char *mojo_regex_lastgroup(const char **names, int ngroups, const int64_t *gstart) {
    for (int i = ngroups; i >= 1; i--) {
        if (gstart[i] >= 0 && names[i]) return (char *)names[i];
    }
    return (char *)0;
}

/* Substring [start, end) of text, as a freshly malloc'd NUL-terminated
 * string -- the char* representation Match.group() needs. */
char *mojo_regex_substr(const char *text, int64_t start, int64_t end) {
    int64_t len = end - start;
    if (len < 0) len = 0;
    char *out = (char *)malloc((size_t)len + 1);
    memcpy(out, text + start, (size_t)len);
    out[len] = '\0';
    return out;
}

/* re.sub(pattern, callback, src) backed by this file's own regex engine
 * instead of mojo_re_sub_fn's POSIX regcomp/regexec: POSIX ERE has neither
 * PCRE shorthand classes (\s, \S, \d, \w) nor non-greedy quantifiers (*?),
 * so any pattern using them (e.g. mojo_compiler.py's own
 * replace_multiline_strings, matching a triple-quoted docstring via
 * `"""[\s\S]*?"""`) made regcomp() fail outright — mojo_re_sub_fn's own
 * "compile failed, return src unchanged" fallback then silently no-opped
 * the whole substitution, leaving multi-line strings unreplaced for the
 * line-by-line tokenizer that runs after it. Same substitution loop as
 * mojo_re_sub_fn, but scanning via mojo_regex_search/re_match_node. */
char *mojo_regex_sub_fn(const ReNode *prog, const ReRange *ranges, const ReClassInfo *classinfo,
                         int root, int ngroups,
                         char *(*callback)(void *, char *), void *env, char *src) {
    if (!src) return "";
    int64_t src_len = (int64_t)strlen(src);
    size_t out_cap = (size_t)src_len * 4 + 64;
    char *out = (char *)malloc(out_cap);
    if (!out) return src;
    size_t out_len = 0;

    int64_t *gstart = (int64_t *)malloc(sizeof(int64_t) * (size_t)(ngroups + 1));
    int64_t *gend = (int64_t *)malloc(sizeof(int64_t) * (size_t)(ngroups + 1));

    int64_t pos = 0;
    while (pos <= src_len) {
        int64_t mstart, mend;
        int ok = mojo_regex_search(prog, ranges, classinfo, root, ngroups,
                                    src, src_len, pos, &mstart, &mend, gstart, gend);
        if (!ok) {
            size_t rest = (size_t)(src_len - pos);
            while (out_len + rest + 1 > out_cap) { out_cap *= 2; out = realloc(out, out_cap); }
            memcpy(out + out_len, src + pos, rest);
            out_len += rest;
            break;
        }
        /* Copy text before the match */
        size_t pre = (size_t)(mstart - pos);
        while (out_len + pre + 1 > out_cap) { out_cap *= 2; out = realloc(out, out_cap); }
        memcpy(out + out_len, src + pos, pre);
        out_len += pre;

        /* `matched` (the callback's `m.group(0)`) is NOT freed here: a
         * callback is free to retain it (e.g. store into a dict/list, as
         * Python's real re.sub callback allows), same as every other
         * MojoList/MojoDict string-ownership convention in this runtime
         * (see mojo_list_append_str's comment). Freeing it unconditionally
         * right after the call left any retained reference dangling — real
         * bug found via mojo_compiler.py's own replace_multiline_strings:
         * `string_cache[placeholder] = m.group(0)` inside its re.sub
         * callback stored a pointer that was freed moments later, so every
         * later read of that cache came back empty (a picture-perfect
         * use-after-free: glibc's free() commonly zeroes/reuses the first
         * bytes of a small allocation immediately). */
        char *matched = mojo_regex_substr(src, mstart, mend);
        char *repl = callback(env, matched);
        if (repl) {
            size_t rlen = strlen(repl);
            while (out_len + rlen + 1 > out_cap) { out_cap *= 2; out = realloc(out, out_cap); }
            memcpy(out + out_len, repl, rlen);
            out_len += rlen;
        }

        /* Advance past the match (avoid infinite loop on zero-length match) */
        if (mend == mstart) {
            if (mstart < src_len) {
                out[out_len++] = src[mstart];
                pos = mstart + 1;
            } else {
                break;
            }
        } else {
            pos = mend;
        }
    }
    out[out_len] = '\0';
    free(gstart);
    free(gend);
    return out;
}

/* Engine-backed counterpart to mojo_re_sub_str: re.sub(pattern, repl, src)
 * where repl is a plain replacement string, not a callback. See
 * mojo_re_sub_str's comment for the bug this fixes. No backreference
 * support in repl, same as mojo_re_sub_str. */
char *mojo_regex_sub_str(const ReNode *prog, const ReRange *ranges, const ReClassInfo *classinfo,
                          int root, int ngroups, char *repl, char *src) {
    if (!src) return "";
    if (!repl) repl = "";
    int64_t src_len = (int64_t)strlen(src);
    size_t out_cap = (size_t)src_len * 4 + 64;
    char *out = (char *)malloc(out_cap);
    if (!out) return src;
    size_t out_len = 0;
    size_t rlen = strlen(repl);

    int64_t *gstart = (int64_t *)malloc(sizeof(int64_t) * (size_t)(ngroups + 1));
    int64_t *gend = (int64_t *)malloc(sizeof(int64_t) * (size_t)(ngroups + 1));

    int64_t pos = 0;
    while (pos <= src_len) {
        int64_t mstart, mend;
        int ok = mojo_regex_search(prog, ranges, classinfo, root, ngroups,
                                    src, src_len, pos, &mstart, &mend, gstart, gend);
        if (!ok) {
            size_t rest = (size_t)(src_len - pos);
            while (out_len + rest + 1 > out_cap) { out_cap *= 2; out = realloc(out, out_cap); }
            memcpy(out + out_len, src + pos, rest);
            out_len += rest;
            break;
        }
        size_t pre = (size_t)(mstart - pos);
        while (out_len + pre + 1 > out_cap) { out_cap *= 2; out = realloc(out, out_cap); }
        memcpy(out + out_len, src + pos, pre);
        out_len += pre;

        while (out_len + rlen + 1 > out_cap) { out_cap *= 2; out = realloc(out, out_cap); }
        memcpy(out + out_len, repl, rlen);
        out_len += rlen;

        if (mend == mstart) {
            if (mstart < src_len) {
                out[out_len++] = src[mstart];
                pos = mstart + 1;
            } else {
                break;
            }
        } else {
            pos = mend;
        }
    }
    out[out_len] = '\0';
    free(gstart);
    free(gend);
    return out;
}

/* ── Closure-lifted function stubs ──────────────────────────────────────────
 * These are nested functions in gimple_codegen.py that get compiled as
 * separate C functions when the self-hosted binary is built.  They are
 * called from the compiled gen_module / _infer_param_types / _scan_container_elems.
 * The stubs return empty/zero — safe for the A/B .ci comparison since these
 * closures are only invoked for edge-case import / struct-registration
 * codepaths that a simple test file won't hit. */
int64_t note_list_literal(void *v, void *val) {
    (void)v; (void)val;
    return 0;
}
int64_t scan_expr(void *expr) {
    (void)expr;
    return 0;
}
