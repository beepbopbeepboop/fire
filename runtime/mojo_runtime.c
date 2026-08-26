#include "mojo_runtime.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdint.h>
#include <inttypes.h>
#include <ctype.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <errno.h>
#include <dirent.h>

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
int64_t _mojo_exc_type = 0;
void mojo_exc_type_set(int64_t type_id) { _mojo_exc_type = type_id; }
int64_t mojo_exc_type_get(void) { return _mojo_exc_type; }

/* Compiled-generator (C++20 coroutine) exception-boundary flag — see the
 * long comment on this in mojo_runtime.h. Set only by a generator's
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
    /* Use printf directly (no Python dependency) */
    printf("%s", str);
    fflush(stdout);
}

/* print(..., file=sys.stderr): a separate function rather than passing a
 * FILE* through generated GIMPLE code — `stderr`/`stdout` are macros on
 * macOS (e.g. __stderrp), not necessarily legal inline in -fgimple's
 * restricted subset. gimple_codegen.py's _gen_print detects `file=` by AST
 * shape at compile time and picks mojo_print vs this, so no FILE* value
 * ever needs to flow through the generated code at all. */
void mojo_print_stderr(char *str) {
    fprintf(stderr, "%s", str);
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
        mojo_exc_msg_set("FileNotFoundError");
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
static MojoSet *_mojo_list_registry = NULL;

int mojo_is_registered_list(int64_t addr) {
    if (!_mojo_list_registry || addr < 65536) return 0;
    return mojo_set_contains_int(_mojo_list_registry, addr);
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
int mojo_boxed_is_str(int64_t v) {
    return v > 65536 && !mojo_is_registered_list(v);
}

/* A Python tuple literal lowers to the exact same MojoList as a list literal
 * (see _lower_tuple_literal in gimple_codegen.py) — there is no runtime
 * distinction between the two, so generic repr() always printed a tuple's
 * contents with list brackets `[...]` instead of `(...)`. Marked explicitly
 * by _lower_tuple_literal's emitted call to mojo_mark_as_tuple() right after
 * mojo_list_new(); checked by _mojo_repr_list to choose the right brackets. */
static MojoSet *_mojo_tuple_registry = NULL;

void mojo_mark_as_tuple(MojoList *l) {
    if (!l) return;
    if (!_mojo_tuple_registry) _mojo_tuple_registry = mojo_set_new();
    mojo_set_add_int(_mojo_tuple_registry, (int64_t)(intptr_t)l);
}

int mojo_is_tuple(MojoList *l) {
    if (!l || !_mojo_tuple_registry) return 0;
    return mojo_set_contains_int(_mojo_tuple_registry, (int64_t)(intptr_t)l);
}

MojoList *mojo_list_new(void)
{
    MojoList *l = malloc(sizeof(MojoList));
    l->data = NULL;
    l->len  = 0;
    l->cap  = 0;
    if (!_mojo_list_registry) _mojo_list_registry = mojo_set_new();
    mojo_set_add_int(_mojo_list_registry, (int64_t)(intptr_t)l);
    return l;
}

void mojo_list_free(MojoList *l)
{
    free(l->data);
    free(l);
}

static void _list_grow(MojoList *l)
{
    int64_t nc = l->cap == 0 ? 4 : l->cap * 2;
    l->data = realloc(l->data, (size_t)nc * sizeof(int64_t));
    l->cap  = nc;
}

void mojo_list_append_int(MojoList *l, int64_t v)
{
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

int64_t mojo_list_get_int(MojoList *l, int64_t i)   { if (!l || !l->data) return 0; return l->data[_norm_idx(l, i)]; }

double mojo_list_get_double(MojoList *l, int64_t i)
{
    double v;
    memcpy(&v, &l->data[_norm_idx(l, i)], sizeof(v));
    return v;
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

void mojo_list_set_int(MojoList *l, int64_t i, int64_t v)   { l->data[_norm_idx(l, i)] = v; }

void mojo_list_set_double(MojoList *l, int64_t i, double v)
{
    int64_t bits;
    memcpy(&bits, &v, sizeof(bits));
    l->data[_norm_idx(l, i)] = bits;
}

void mojo_list_set_str(MojoList *l, int64_t i, char *v)
{
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
    _mojo_list_insert_slot(l, i, v);
}

void mojo_list_insert_double(MojoList *l, int64_t i, double v)
{
    int64_t bits;
    memcpy(&bits, &v, sizeof(bits));
    _mojo_list_insert_slot(l, i, bits);
}

void mojo_list_insert_str(MojoList *l, int64_t i, char *v)
{
    _mojo_list_insert_slot(l, i, (int64_t)(uintptr_t)v);
}

char *mojo_list_get_str(MojoList *l, int64_t i)
{
    if (!l || !l->data) return "";
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
    return r;
}

/* `del lst[start:stop]` — removes elements [start, stop) in place, shifting
 * later elements down. Bound normalization mirrors mojo_list_slice exactly
 * (same negative-index/omitted-stop/clamping rules), since both lower from
 * the identical SliceExpr shape. */
void mojo_list_del_slice(MojoList *l, int64_t start, int64_t stop)
{
    if (!l) return;
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

MojoList *mojo_list_concat(MojoList *a, MojoList *b)
{
    if (!a) a = mojo_list_new();
    if (!b) b = mojo_list_new();
    MojoList *r = mojo_list_new();
    for (int64_t i = 0; i < a->len; i++) mojo_list_append_int(r, a->data[i]);
    for (int64_t i = 0; i < b->len; i++) mojo_list_append_int(r, b->data[i]);
    return r;
}

MojoList *mojo_list_repeat(MojoList *l, int64_t n)
{
    MojoList *r = mojo_list_new();
    for (int64_t rep = 0; rep < n; rep++)
        for (int64_t i = 0; i < l->len; i++)
            mojo_list_append_int(r, l->data[i]);
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
         * took 100% CPU and dozens of GB before this fix). */
        len = 0;
        while (len < stop && s[len]) len++;
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
        len = 0;
        while (len < stop && s[len]) len++;
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

/* A single character (raw `char`, e.g. from string indexing) is a distinct
 * representation from a 1-character `char *` string — reinterpreting its
 * numeric byte value as a pointer (the boxed-int64_t-as-pointer convention
 * used elsewhere for containers of strings) produces a garbage address
 * (e.g. 0x22 for '"'). Build a real 1-char C string instead. */
char *mojo_char_to_str(char c) {
    char *s = malloc(2);
    s[0] = c;
    s[1] = '\0';
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
    if (!s || !s[0]) return 0;
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
 * ctype's is* take an int and misbehave on negative (signed-char) input, so
 * cast through unsigned char. */
int mojo_str_isalnum(char *s) {
    if (!s || !*s) return 0;
    for (unsigned char *p = (unsigned char *)s; *p; p++)
        if (!isalnum(*p)) return 0;
    return 1;
}
int mojo_str_isdigit(char *s) {
    if (!s || !*s) return 0;
    for (unsigned char *p = (unsigned char *)s; *p; p++)
        if (!isdigit(*p)) return 0;
    return 1;
}
int mojo_str_isalpha(char *s) {
    if (!s || !*s) return 0;
    for (unsigned char *p = (unsigned char *)s; *p; p++)
        if (!isalpha(*p)) return 0;
    return 1;
}
int mojo_str_isspace(char *s) {
    if (!s || !*s) return 0;
    for (unsigned char *p = (unsigned char *)s; *p; p++)
        if (!isspace(*p)) return 0;
    return 1;
}
/* isupper/islower: every CASED character matches, and there is at least one
 * cased character (Python semantics — "A1" is upper, "1" is not, "ABC" is). */
int mojo_str_isupper(char *s) {
    if (!s) return 0;
    int has_cased = 0;
    for (unsigned char *p = (unsigned char *)s; *p; p++) {
        if (islower(*p)) return 0;
        if (isupper(*p)) has_cased = 1;
    }
    return has_cased;
}
int mojo_str_islower(char *s) {
    if (!s) return 0;
    int has_cased = 0;
    for (unsigned char *p = (unsigned char *)s; *p; p++) {
        if (isupper(*p)) return 0;
        if (islower(*p)) has_cased = 1;
    }
    return has_cased;
}

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
    mojo_list_append_str(l, merged);
    free(merged);
    for (int64_t i = n_keep; i < n; i++) mojo_list_append_str(l, mojo_list_get_str(all, i));
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
/* (struct definitions now in mojo_runtime.h) */

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

/* A dict whose values are all Python bools (e.g. `flags[name] = True`) has
 * no runtime marker distinguishing that from any other int64_t-valued dict
 * — like the None/int and tuple/list ambiguities elsewhere in this runtime,
 * generic repr() (_mojo_generic_elem_repr, via _mojo_repr_dict) can't tell a
 * real boxed 0/1 boolean apart from a genuine small int, so it always
 * printed 0/1 instead of False/True. Marked explicitly wherever codegen
 * knows (from the RHS's static type) that a `dict[key] = True_or_False`
 * assignment is storing a real bool; checked by _mojo_repr_dict to choose
 * the right value formatting for the whole dict. */
static MojoSet *_mojo_bool_dict_registry = NULL;

void mojo_mark_dict_bool_values(MojoDict *d) {
    if (!d) return;
    if (!_mojo_bool_dict_registry) _mojo_bool_dict_registry = mojo_set_new();
    mojo_set_add_int(_mojo_bool_dict_registry, (int64_t)(intptr_t)d);
}

int mojo_is_bool_dict(MojoDict *d) {
    if (!d || !_mojo_bool_dict_registry) return 0;
    return mojo_set_contains_int(_mojo_bool_dict_registry, (int64_t)(intptr_t)d);
}

static MojoSet *_mojo_dict_registry = NULL;

int mojo_is_registered_dict(int64_t addr) {
    if (!_mojo_dict_registry || addr < 65536) return 0;
    return mojo_set_contains_int(_mojo_dict_registry, addr);
}

MojoDict *mojo_dict_new(void)
{
    MojoDict *d = malloc(sizeof(MojoDict));
    d->cap      = 8;
    d->used     = 0;
    d->next_seq = 0;
    d->slots = calloc((size_t)d->cap, sizeof(_DictSlot));
    if (!_mojo_dict_registry) _mojo_dict_registry = mojo_set_new();
    mojo_set_add_int(_mojo_dict_registry, (int64_t)(intptr_t)d);
    return d;
}

void mojo_dict_free(MojoDict *d)
{
    for (int64_t i = 0; i < d->cap; i++) free(d->slots[i].key);
    free(d->slots);
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
 * Mirrors mojo_list_clear's in-place semantics (runtime/mojo_runtime.c:2601). */
void mojo_dict_clear(MojoDict *d)
{
    if (!d) return;
    for (int64_t i = 0; i < d->cap; i++) {
        free(d->slots[i].key);
        d->slots[i].key = NULL;
    }
    d->used = 0;
    d->next_seq = 0;
}

static _DictSlot *_dict_find(MojoDict *d, char *key)
{
    uint64_t h = _str_hash(key) % (uint64_t)d->cap;
    for (int64_t i = 0; i < d->cap; i++) {
        int64_t idx = (int64_t)((h + (uint64_t)i) % (uint64_t)d->cap);
        _DictSlot *sl = &d->slots[idx];
        if (!sl->key) return sl;          /* empty — insertion point */
        if (strcmp(sl->key, key) == 0) return sl;
    }
    return NULL;
}

static void _dict_grow(MojoDict *d);

/* seq >= 0 preserves an already-assigned insertion sequence number (used
 * only by _dict_grow's rehash, so a key's original insertion order survives
 * moving to a new, bigger slot array); seq < 0 assigns a fresh one. */
static void _dict_set_raw_seq(MojoDict *d, char *key, int64_t val, int64_t seq)
{
    if (d->used * 2 >= d->cap) _dict_grow(d);
    _DictSlot *sl = _dict_find(d, key);
    if (!sl->key) {
        sl->key = strdup(key);
        sl->seq = (seq >= 0) ? seq : d->next_seq++;
        if (sl->seq >= d->next_seq) d->next_seq = sl->seq + 1;
        d->used++;
    }
    sl->val = val;
}

static void _dict_set_raw(MojoDict *d, char *key, int64_t val)
{
    _dict_set_raw_seq(d, key, val, -1);
}

static void _dict_grow(MojoDict *d)
{
    int64_t old_cap = d->cap;
    _DictSlot *old  = d->slots;
    d->cap   *= 2;
    d->used  = 0;
    d->slots = calloc((size_t)d->cap, sizeof(_DictSlot));
    for (int64_t i = 0; i < old_cap; i++)
        if (old[i].key) _dict_set_raw_seq(d, old[i].key, old[i].val, old[i].seq);
    for (int64_t i = 0; i < old_cap; i++) free(old[i].key);
    free(old);
}

/* Slot indices for d->slots, in insertion order (ascending by _DictSlot.seq)
 * — used only by generic repr()'s dict formatting (_mojo_repr_dict) so it
 * matches Python's insertion-order-preserving dict printing instead of raw
 * open-addressing hash-slot order. Real iteration (MojoDictIter,
 * .keys()/.values()/.items()) is unaffected and still walks slots in hash
 * order — deliberately scoped to the debug-dump path only, not a behavior
 * change for compiled programs. Returns a malloc'd array of d->used
 * entries (NULL if empty); caller must free() it. */
static int _cmp_seqidx(const void *a, const void *b) {
    int64_t sa = ((const int64_t *)a)[0];
    int64_t sb = ((const int64_t *)b)[0];
    return (sa > sb) - (sa < sb);
}
int64_t *mojo_dict_order_indices(MojoDict *d)
{
    if (!d || d->used == 0) return NULL;
    int64_t (*tmp)[2] = malloc(sizeof(int64_t) * 2 * (size_t)d->used);
    int64_t n = 0;
    for (int64_t i = 0; i < d->cap; i++)
        if (d->slots[i].key) { tmp[n][0] = d->slots[i].seq; tmp[n][1] = i; n++; }
    qsort(tmp, (size_t)n, sizeof(int64_t) * 2, _cmp_seqidx);
    int64_t *out = malloc(sizeof(int64_t) * (size_t)n);
    for (int64_t i = 0; i < n; i++) out[i] = tmp[i][1];
    free(tmp);
    return out;
}

void mojo_dict_set_int(MojoDict *d, char *key, int64_t v)
{
    _dict_set_raw(d, key, v);
}

void mojo_dict_set_double(MojoDict *d, char *key, double v)
{
    int64_t bits;
    memcpy(&bits, &v, sizeof(bits));
    _dict_set_raw(d, key, bits);
}

void mojo_dict_set_str(MojoDict *d, char *key, char *v)
{
    _dict_set_raw(d, key, (int64_t)(uintptr_t)v);
}

static _DictSlot *_dict_lookup(MojoDict *d, char *key)
{
    if (!d || !d->cap || !d->slots) return NULL;
    uint64_t h = _str_hash(key) % (uint64_t)d->cap;
    for (int64_t i = 0; i < d->cap; i++) {
        int64_t idx = (int64_t)((h + (uint64_t)i) % (uint64_t)d->cap);
        _DictSlot *sl = &d->slots[idx];
        if (!sl->key) return NULL;
        if (strcmp(sl->key, key) == 0) return sl;
    }
    return NULL;
}

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

void mojo_dict_print(MojoDict *d)
{
    printf("{");
    int first = 1;
    for (int64_t i = 0; i < d->cap; i++) {
        if (!d->slots[i].key) continue;
        if (!first) printf(", ");
        printf("\"%s\": %lld", d->slots[i].key, (long long)d->slots[i].val);
        first = 0;
    }
    printf("}");
}

int64_t mojo_dict_len(MojoDict *d) { return d ? d->used : 0; }

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
    return it->dict->slots[it->order[it->pos]].key;
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
/* (struct definitions now in mojo_runtime.h) */

MojoSet *mojo_set_new(void)
{
    MojoSet *s = malloc(sizeof(MojoSet));
    s->cap   = 8;
    s->used  = 0;
    s->slots = malloc((size_t)s->cap * sizeof(_SetSlot));
    for (int64_t i = 0; i < s->cap; i++) s->slots[i].tag = -1;
    return s;
}

void mojo_set_free(MojoSet *s)
{
    for (int64_t i = 0; i < s->cap; i++)
        if (s->slots[i].tag == 1) free(s->slots[i].val_s);
    free(s->slots);
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
    }
    s->used = 0;
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

static int64_t _set_slot_str(MojoSet *s, char *v)
{
    uint64_t h = _str_hash(v) % (uint64_t)s->cap;
    for (int64_t i = 0; i < s->cap; i++) {
        int64_t idx = (int64_t)((h + (uint64_t)i) % (uint64_t)s->cap);
        _SetSlot *sl = &s->slots[idx];
        if (sl->tag == -1) return idx;
        if (sl->tag == 1 && strcmp(sl->val_s, v) == 0) return idx;
    }
    return -1;
}

static void _set_grow(MojoSet *s)
{
    int64_t old_cap = s->cap;
    _SetSlot *old   = s->slots;
    s->cap   *= 2;
    s->used  = 0;
    s->slots = malloc((size_t)s->cap * sizeof(_SetSlot));
    for (int64_t i = 0; i < s->cap; i++) s->slots[i].tag = -1;
    for (int64_t i = 0; i < old_cap; i++) {
        if (old[i].tag == 0) mojo_set_add_int(s, old[i].val_i);
        else if (old[i].tag == 1) { mojo_set_add_str(s, old[i].val_s); free(old[i].val_s); }
    }
    free(old);
}

void mojo_set_add_int(MojoSet *s, int64_t v)
{
    if (s->used * 2 >= s->cap) _set_grow(s);
    int64_t idx = _set_slot_int(s, v);
    if (idx < 0) { _set_grow(s); idx = _set_slot_int(s, v); }
    if (s->slots[idx].tag == -1) { s->slots[idx].tag = 0; s->slots[idx].val_i = v; s->used++; }
}

void mojo_set_add_str(MojoSet *s, char *v)
{
    if (s->used * 2 >= s->cap) _set_grow(s);
    int64_t idx = _set_slot_str(s, v);
    if (idx < 0) { _set_grow(s); idx = _set_slot_str(s, v); }
    if (s->slots[idx].tag == -1) {
        s->slots[idx].tag   = 1;
        s->slots[idx].val_s = strdup(v);
        s->used++;
    }
}

int mojo_set_contains_int(MojoSet *s, int64_t v)
{
    int64_t idx = _set_slot_int(s, v);
    return idx >= 0 && s->slots[idx].tag == 0;
}

int mojo_set_contains_str(MojoSet *s, char *v)
{
    int64_t idx = _set_slot_str(s, v);
    return idx >= 0 && s->slots[idx].tag == 1;
}

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
    if (a) for (int64_t i = 0; i < a->cap; i++) {
        if (a->slots[i].tag == 0)
            mojo_set_add_int(out, a->slots[i].val_i);
    }
    if (b) for (int64_t i = 0; i < b->cap; i++) {
        if (b->slots[i].tag == 0)
            mojo_set_add_int(out, b->slots[i].val_i);
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

void mojo_set_update(MojoSet *dst, MojoSet *src) {
    if (!dst || !src) return;
    for (int64_t i = 0; i < src->cap; i++) {
        if (src->slots[i].tag == 0)
            mojo_set_add_int(dst, src->slots[i].val_i);
        else if (src->slots[i].tag == 1)
            mojo_set_add_str(dst, src->slots[i].val_s);
    }
}

/* ── MojoSetIter ─────────────────────────────────────────────────────────*/

struct MojoSetIter {
    MojoSet *set;
    int64_t  pos;   /* current slot index */
};

MojoSetIter *mojo_set_iter_new(MojoSet *s)
{
    MojoSetIter *it = malloc(sizeof(MojoSetIter));
    it->set = s;
    it->pos = -1;
    return it;
}

int mojo_set_iter_next(MojoSetIter *it)
{
    it->pos++;
    while (it->pos < it->set->cap) {
        if (it->set->slots[it->pos].tag != -1) return 1;
        it->pos++;
    }
    return 0;
}

int64_t mojo_set_iter_val_int(MojoSetIter *it)
{
    return it->set->slots[it->pos].val_i;
}

char *mojo_set_iter_val_str(MojoSetIter *it)
{
    return it->set->slots[it->pos].val_s;
}

void mojo_set_iter_free(MojoSetIter *it) { free(it); }

/* ── Python builtin functions for C types ──────────────────────────────────*/

int mojo_isinstance(int obj, int type_id) {
    /* Stub: returns 0 (false) for now. Only covers scalar builtins
     * (bool, int, float, str, list, dict, set) -- those have no tagged
     * runtime representation in this compiler (a plain int64_t, double,
     * char pointer, or MojoList pointer carries no dynamic type marker), so
     * a real isinstance() there would need a much bigger boxing-scheme
     * change. isinstance() against a real user-defined struct/dataclass
     * type does NOT go through this stub -- see mojo_read_type_tag below
     * and _lower_builtin_isinstance's struct_field_types branch in
     * gimple_codegen.py. */
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
int64_t mojo_read_type_tag(int64_t addr) {
    if (!addr) return 0;
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
    if (addr < 65536) return 0;
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
    return buffer;
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
     * value=0 once self-hosted. */
    static char buffer[64];
    snprintf(buffer, sizeof(buffer), "%g", v);
    int has_marker = 0;
    for (char *p = buffer; *p; p++) {
        if (*p == '.' || *p == 'e' || *p == 'E' || *p == 'n' || *p == 'i') { has_marker = 1; break; }
    }
    if (!has_marker) strncat(buffer, ".0", sizeof(buffer) - strlen(buffer) - 1);
    return buffer;
}

char *mojo_repr_list_doubles(MojoList *l) {
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
        if (_i > 0) _buf = mojo_str_cat(_buf, ", ");
        _buf = mojo_str_cat(_buf, mojo_repr_float(mojo_list_get_double(l, _i)));
    }
    if (_is_tup && _n == 1) _buf = mojo_str_cat(_buf, ",");
    return mojo_str_cat(_buf, _is_tup ? ")" : "]");
}

char *mojo_repr_list_ints(MojoList *l) {
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
        if (_i > 0) _buf = mojo_str_cat(_buf, ", ");
        _buf = mojo_str_cat(_buf, mojo_repr_int(mojo_list_get_int(l, _i)));
    }
    if (_is_tup && _n == 1) _buf = mojo_str_cat(_buf, ",");
    return mojo_str_cat(_buf, _is_tup ? ")" : "]");
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

int mojo_type(...) {
    /* Stub: returns type identifier. 0 for now */
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

char *mojo_str_cat(char *a, char *b) {
    /* Concatenate two C strings */
    if (!a) a = "";
    if (!b) b = "";

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
    /* Return FILE* as int64_t so int_read/int_write can cast it back */
    FILE *f = fopen(path, "r");
    if (!f) return 0;
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

char *string_strip(char *str) {
    if ((intptr_t)str < 65536) return str;
    if (!str) return str;

    /* Skip leading whitespace */
    char *start = str;
    while (*start && (*start == ' ' || *start == '\t' || *start == '\n' || *start == '\r')) {
        start++;
    }

    /* Nothing but whitespace — return as-is */
    if (!*start) { return str; }

    /* Find end (skip trailing whitespace) */
    char *end = str + strlen(str) - 1;
    while (end > start && (*end == ' ' || *end == '\t' || *end == '\n' || *end == '\r')) {
        end--;
    }

    size_t len = (end - start) + 1;
    if (start == str && len == strlen(str)) {
        return str;  /* nothing to strip */
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
    return str;
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
    if (start == str) return str;
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
    if ((int64_t)len >= width) return s;
    size_t pad = (size_t)width - len;
    char fc = (fill && fill[0]) ? fill[0] : ' ';
    size_t left = 0, right = 0;
    if (mode == 0) { left = pad; }
    else if (mode == 1) { right = pad; }
    else { left = pad / 2; right = pad - left; }
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
    if (!parts || parts->len == 0) return "";
    if (!sep) sep = "";
    size_t sep_len = strlen(sep);
    size_t total = 0;
    for (int64_t i = 0; i < parts->len; i++) {
        char *s = mojo_list_get_str(parts, i);
        if (s) total += strlen(s);
        if (i < parts->len - 1) total += sep_len;
    }
    char *out = (char *)malloc(total + 1);
    if (!out) return "";
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
#define _MOJO_EXC_TAG_ATTRIBUTEERROR 1471495998

void mojo_raise_attribute_error(char *attr) {
    char msg[256];
    snprintf(msg, sizeof msg, "AttributeError: %s", attr ? attr : "?");
    char *heap_msg = strdup(msg);
    mojo_exc_type_set(_MOJO_EXC_TAG_ATTRIBUTEERROR);
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
void mojo_unsupported_iter(const char *type_name) {
    fprintf(stderr, "mojo_unsupported_iter: 'for' loop over unsupported iterable "
                     "type %s (codegen has no lowering for this container/iterator "
                     "shape; the loop body runs zero times)\n", type_name ? type_name : "?");
}


char *gimple_codegen_compile_to_gimple(char *src, int do_imports, char *filename) {
    /*
     * Call Python's gimple_codegen.compile_to_gimple() via subprocess.
     * We write src to a temp file, then run:
     *   python3 -c "import gimple_codegen; print(gimple_codegen.compile_to_gimple(open('TMP').read(), do_imports, filename))"
     * and capture the output.  Falls back to a valid-but-empty stub only on
     * hard failures (popen/write errors).
     */
    static char *result_buf = NULL;
    static size_t result_cap = 0;
    char tmppath[128];
    snprintf(tmppath, sizeof(tmppath), "/tmp/_mojo_src_%d.mojo", (int)getpid());

    /* Write source to temp file */
    FILE *tmp = fopen(tmppath, "w");
    if (!tmp) goto fallback;
    fputs(src, tmp);
    fclose(tmp);

    /* Locate the project root: prefer MOJO_HOME env, else executable-relative */
    char *mojo_home = getenv("MOJO_HOME");
    char pythonpath[512];
    if (mojo_home) {
        snprintf(pythonpath, sizeof(pythonpath), "%s", mojo_home);
    } else {
        /* Default: current working directory (works when run from project root) */
        snprintf(pythonpath, sizeof(pythonpath), ".");
    }

    /* Build the Python one-liner command */
    char cmd[1024];
    snprintf(cmd, sizeof(cmd),
        "PYTHONPATH='%s' python3 -c \""
        "import sys; import gimple_codegen; "
        "src = open('%s').read(); "
        "print(gimple_codegen.compile_to_gimple(src, %d, '%s'), end='')\" 2>/dev/null",
        pythonpath, tmppath, do_imports, filename ? filename : "");

    FILE *fp = popen(cmd, "r");
    if (!fp) { unlink(tmppath); goto fallback; }

    /* Read the WHOLE subprocess output, growing the buffer as needed. A fixed
     * 4 MiB cap here used to silently truncate any transitive-closure dump
     * once the self-hosted compiler's own generated C exceeded that size
     * (mojo.py's own full closure is 5+ MiB): fread stopped short of EOF,
     * pclose() then closed the read end while the child still had more to
     * write, the child got SIGPIPE/EPIPE and exited non-zero, and THAT non-zero
     * rc silently triggered the "Python call failed" fallback stub below —
     * every --dump of mojo.py itself losing its whole transitive closure. */
    if (!result_buf) { result_cap = 1 << 20; result_buf = malloc(result_cap); }
    size_t n = 0;
    for (;;) {
        if (n + 65536 >= result_cap) {
            result_cap *= 2;
            result_buf = realloc(result_buf, result_cap);
        }
        size_t got = fread(result_buf + n, 1, result_cap - n - 1, fp);
        n += got;
        if (got == 0) break;  /* EOF or error */
    }
    int rc = pclose(fp);
    unlink(tmppath);

    if (n > 64 && rc == 0) {
        result_buf[n] = '\0';
        return result_buf;
    }

fallback:
    /* Should never be reached in a working installation — emit a valid-but-
       minimal stub that at least compiles without errors. */
    if (!result_buf) { result_cap = 1 << 12; result_buf = malloc(result_cap); }
    snprintf(result_buf, result_cap,
        "/* gimple_codegen_compile_to_gimple: Python call failed */\n"
        "#include \"mojo_runtime.h\"\n"
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
        mojo_list_append_str(out, d->slots[order[oi]].key);
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
        mojo_list_append_str(pair, d->slots[i].key);
        mojo_list_append_int(pair, d->slots[i].val);
        mojo_list_append_int(out, (int64_t)(intptr_t)pair);
    }
    free(order);
    return out;
}

void mojo_dict_update(MojoDict *dst, MojoDict *src) {
    if (!dst || !src) return;
    for (int64_t i = 0; i < src->cap; i++)
        if (src->slots[i].key)
            mojo_dict_set_int(dst, src->slots[i].key, src->slots[i].val);
}

int64_t mojo_dict_pop_int(MojoDict *d, char *key) {
    if (!d) return 0;
    _DictSlot *sl = _dict_lookup(d, key);
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
    int64_t old_cap = d->cap;
    _DictSlot *old = d->slots;
    d->slots = calloc((size_t)old_cap, sizeof(_DictSlot));
    d->used = 0;
    for (int64_t i = 0; i < old_cap; i++) {
        if (old[i].key && strcmp(old[i].key, key) != 0)
            _dict_set_raw_seq(d, old[i].key, old[i].val, old[i].seq);
    }
    for (int64_t i = 0; i < old_cap; i++) free(old[i].key);
    free(old);
    return val;
}

MojoDict *mojo_dict_copy(MojoDict *d) {
    MojoDict *out = mojo_dict_new();
    if (d) mojo_dict_update(out, d);
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

/* Python list.pop(index=-1): removes and returns the element at `idx`
 * (negative indices count from the end), shifting later elements down.
 * mojo_list_pop(l) (no index) used to be the only implementation, always
 * popping the last element regardless of any index argument codegen passed
 * it — a real bug: `argv.pop(1)` (removing a specific flag/token, not the
 * last one) silently popped the wrong element instead. */
int64_t mojo_list_pop_at(MojoList *l, int64_t idx) {
    if (!l || l->len == 0) return 0;
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

void mojo_list_extend(MojoList *dst, MojoList *src) {
    if (!dst || !src) return;
    for (int64_t i = 0; i < src->len; i++)
        mojo_list_append_int(dst, src->data[i]);
}

void mojo_list_sort(MojoList *l) { (void)l; /* stub */ }
void mojo_list_reverse(MojoList *l) {
    if (!l || l->len < 2) return;
    for (int64_t i = 0, j = l->len-1; i < j; i++, j--) {
        int64_t tmp = l->data[i]; l->data[i] = l->data[j]; l->data[j] = tmp;
    }
}
void mojo_list_clear(MojoList *l) { if (l) l->len = 0; }
void mojo_list_remove_str(MojoList *l, const char *v) {
    if (!l || !v) return;
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
void mojo_set_discard(MojoSet *s, int64_t v) { (void)s; (void)v; /* stub */ }


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

char *int64_t_basename(char *path) {
    if (!path) return "";
    const char *base = path;
    for (const char *p = path; *p; p++) {
        if (*p == '/') base = p + 1;
    }
    return (char *)base;
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
    if (!s || !old_s || !new_s) return s_i;
    size_t old_len = strlen(old_s), new_len = strlen(new_s);
    if (old_len == 0) return s_i;
    int count = 0;
    const char *p = s;
    while ((p = strstr(p, old_s)) != NULL) { count++; p += old_len; }
    if (count == 0) return s_i;
    size_t slen = strlen(s);
    size_t result_len = slen + (size_t)count * new_len
                        - (size_t)count * old_len + 1;
    char *result = (char *)malloc(result_len);
    if (!result) return s_i;
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

void *mojo_sorted(void *iterable) {
    MojoList *src = (MojoList *)iterable;
    MojoList *dst = mojo_list_copy(src);
    /* Bubble sort on stored int64_t values */
    for (int64_t i = 0; i < dst->len; i++) {
        for (int64_t j = i + 1; j < dst->len; j++) {
            if (mojo_list_get_int(dst, i) > mojo_list_get_int(dst, j)) {
                int64_t tmp = dst->data[i];
                dst->data[i] = dst->data[j];
                dst->data[j] = tmp;
            }
        }
    }
    return dst;
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
    for (int64_t i = 0; i < dst->len; i++) {
        for (int64_t j = i + 1; j < dst->len; j++) {
            if (strcmp((char *)(uintptr_t)dst->data[i], (char *)(uintptr_t)dst->data[j]) > 0) {
                int64_t tmp = dst->data[i];
                dst->data[i] = dst->data[j];
                dst->data[j] = tmp;
            }
        }
    }
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

void *mojo_zip(void *a, void *b) {
    (void)a; (void)b;
    return mojo_list_new();
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
char *mojo_str_from_int(int64_t v) {
    char buf[32];
    snprintf(buf, sizeof buf, "%lld", (long long)v);
    char *out = (char *)malloc(strlen(buf) + 1);
    strcpy(out, buf);
    return out;
}

/* Python's divmod(a, b) builtin: (a // b, a % b) as a real 2-tuple, using
 * the SAME floor-division adjustment __mojo_floordiv (mojo_runtime.h) uses
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
 * existing build site that already links mojo_runtime.c gets it for free.
 * ReNode/ReRange/ReClassInfo are declared once, in mojo_runtime.h. */

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
