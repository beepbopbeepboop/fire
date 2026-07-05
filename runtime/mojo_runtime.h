#pragma once
#include <stdint.h>
#include <stdio.h>
#include <setjmp.h>

/* Mojo type aliases */
typedef int mojo_int;
typedef float mojo_float;
typedef char* mojo_string;
typedef void* mojo_any;

/* Generic function pointer type (for storing any function as void*) */
typedef void* (*mojo_func_ptr)(void);
typedef void* mojo_generic_func;

/* ── Higher-order function dispatch helpers ──────────────────────────────
 * __GIMPLE functions cannot cast-and-call in a single expression, so
 * we call through these small non-GIMPLE helpers that do the cast.
 * All args/returns are widened to int64_t; callers cast as needed.
 * Declared static inline so they generate no external symbol.           */
static inline int64_t mojo_fnptr_call_0(void *fp) {
    return ((int64_t (*)(void))fp)();
}
static inline int64_t mojo_fnptr_call_1(void *fp, int64_t a) {
    return ((int64_t (*)(int64_t))fp)(a);
}
static inline int64_t mojo_fnptr_call_2(void *fp, int64_t a, int64_t b) {
    return ((int64_t (*)(int64_t, int64_t))fp)(a, b);
}
static inline int64_t mojo_fnptr_call_3(void *fp, int64_t a, int64_t b, int64_t c) {
    return ((int64_t (*)(int64_t, int64_t, int64_t))fp)(a, b, c);
}
static inline int64_t mojo_fnptr_call_4(void *fp, int64_t a, int64_t b, int64_t c, int64_t d) {
    return ((int64_t (*)(int64_t, int64_t, int64_t, int64_t))fp)(a, b, c, d);
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

/* ── List ─────────────────────────────────────────────────────────────────
 * Flat dynamic array of int64_t slots.  Doubles are stored as bit-casts;
 * string pointers are stored as uintptr_t casts (64-bit only).           */
typedef struct {
    int64_t *data;
    int64_t  len;
    int64_t  cap;
} MojoList;

MojoList *mojo_list_new(void);
void      mojo_list_free(MojoList *l);

void    mojo_list_append_int(MojoList *l, int64_t v);
void    mojo_list_append_double(MojoList *l, double v);
void    mojo_list_append_str(MojoList *l, const char *v);

int64_t mojo_list_get_int(MojoList *l, int64_t i);
double  mojo_list_get_double(MojoList *l, int64_t i);

int64_t mojo_list_len(MojoList *l);

int mojo_list_contains_int(MojoList *l, int64_t v);
int mojo_list_contains_double(MojoList *l, double v);
int mojo_list_contains_str(MojoList *l, char *v);

/* Item mutation and extra accessors */
void     mojo_list_set_int(MojoList *l, int64_t i, int64_t v);
void     mojo_list_set_double(MojoList *l, int64_t i, double v);
void     mojo_list_set_str(MojoList *l, int64_t i, char *v);
char    *mojo_list_get_str(MojoList *l, int64_t i);
MojoList*mojo_list_slice(MojoList *l, int64_t start, int64_t stop);
MojoList*mojo_list_concat(MojoList *a, MojoList *b);
MojoList*mojo_list_repeat(MojoList *l, int64_t n);

void mojo_list_print(MojoList *l);
int64_t MojoList__write_to(MojoList *l, ...);

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

/* New string operations */
MojoStr    *mojo_str_slice(MojoStr *s, int64_t start, int64_t stop);
MojoStr    *mojo_str_from_char(char c);
MojoStr    *mojo_str_repeat(MojoStr *s, int64_t n);
int64_t     mojo_str_to_int(MojoStr *s);
double      mojo_str_to_float(MojoStr *s);

/* String method operations on char* */
int mojo_str_startswith(char *s, char *prefix);
int mojo_str_endswith(char *s, char *suffix);
int mojo_str_startswith_char(char *s, char c);
int mojo_str_endswith_char(char *s, char c);
int mojo_str_contains(char *haystack, char *needle);
int64_t mojo_str_find(char *s, char *needle);
MojoList *mojo_str_split(char *s, char *sep);
MojoList *mojo_str_rsplit(char *s, char *sep, int64_t maxsplit);
char *mojo_c_getenv(char *name);
int mojo_truthy_cstr(char *s);
int64_t mojo_strlen(char *s);
char *mojo_platform_system(void);
char *mojo_platform_machine(void);
char *mojo_stdin_read(void);

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
} _DictSlot;

typedef struct {
    _DictSlot *slots;
    int64_t    used;
    int64_t    cap;
} MojoDict;

MojoDict   *mojo_dict_new(void);
void        mojo_dict_free(MojoDict *d);

void        mojo_dict_set_int(MojoDict *d, char *key, int64_t v);
void        mojo_dict_set_double(MojoDict *d, char *key, double v);
void        mojo_dict_set_str(MojoDict *d, char *key, char *v);

int64_t     mojo_dict_get_int(MojoDict *d, char *key);
double      mojo_dict_get_double(MojoDict *d, char *key);
char *mojo_dict_get_str(MojoDict *d, char *key);
MojoList   *mojo_dict_keys(MojoDict *d);
MojoList   *mojo_dict_values(MojoDict *d);
MojoList   *mojo_dict_items(MojoDict *d);
void        mojo_dict_update(MojoDict *dst, MojoDict *src);
int64_t     mojo_dict_pop_int(MojoDict *d, char *key);
MojoDict   *mojo_dict_copy(MojoDict *d);
MojoDict   *mojo_dict_from_pairs(MojoList *pairs);  /* dict(list_of_pairs) */
MojoList   *mojo_list_copy(MojoList *l);
int         mojo_list_all(MojoList *l);
int         mojo_list_any(MojoList *l);
int64_t     mojo_list_pop(MojoList *l);
int64_t     mojo_list_pop_at(MojoList *l, int64_t idx);
void        mojo_list_extend(MojoList *dst, MojoList *src);
void        mojo_list_sort(MojoList *l);
void        mojo_list_reverse(MojoList *l);
void        mojo_list_clear(MojoList *l);
void        mojo_list_remove_str(MojoList *l, const char *v);
void        mojo_list_remove_int(MojoList *l, int64_t v);
int64_t     mojo_list_index_str(MojoList *l, const char *v);
int64_t     mojo_list_index_int(MojoList *l, int64_t v);
int64_t     MojoList_index(MojoList *l, int v);

/* Generic Python-object attribute accessor (used by GIMPLE codegen for opaque int nodes) */
int64_t     mojo_obj_getattr(void *obj, char *attr);

int         mojo_dict_contains(MojoDict *d, char *key);
void        mojo_dict_print(MojoDict *d);
int64_t     mojo_dict_len(MojoDict *d);

/* Dict iterator — advance, then read key/value via accessor calls */
typedef struct {
    MojoDict *dict;
    int64_t   pos;    /* current slot index (-1 = not yet started) */
} MojoDictIter;
MojoDictIter  *mojo_dict_iter_new(MojoDict *d);
int            mojo_dict_iter_next(MojoDictIter *it);     /* 1=has entry, 0=done */
char *mojo_dict_iter_key(MojoDictIter *it);
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
} _SetSlot;

typedef struct {
    _SetSlot *slots;
    int64_t   used;
    int64_t   cap;
} MojoSet;

MojoSet *mojo_set_new(void);
void     mojo_set_free(MojoSet *s);

void     mojo_set_add_int(MojoSet *s, int64_t v);
void     mojo_set_add_str(MojoSet *s, char *v);

int      mojo_set_contains_int(MojoSet *s, int64_t v);
int      mojo_set_contains_str(MojoSet *s, char *v);
int64_t  mojo_set_len(MojoSet *s);
MojoSet *mojo_set_union(MojoSet *a, MojoSet *b);
MojoSet *mojo_set_intersection(MojoSet *a, MojoSet *b);
MojoSet *mojo_set_difference(MojoSet *a, MojoSet *b);
MojoSet *mojo_set_copy(MojoSet *s);
void     mojo_set_update(MojoSet *dst, MojoSet *src);
void     mojo_set_discard(MojoSet *s, int64_t v);

/* Set iterator */
typedef struct {
    MojoSet *set;
    int64_t  pos;   /* current slot index */
} MojoSetIter;
MojoSetIter *mojo_set_iter_new(MojoSet *s);
int          mojo_set_iter_next(MojoSetIter *it);      /* 1=has entry, 0=done */
int64_t      mojo_set_iter_val_int(MojoSetIter *it);
char *mojo_set_iter_val_str(MojoSetIter *it);
void         mojo_set_iter_free(MojoSetIter *it);

void     mojo_set_print(MojoSet *s);

/* ── Python integration ─────────────────────────────────────────────────*/
void mojo_print(char *str);
void mojo_print_stderr(char *str);
char *mojo_input(char *prompt);

/* Python built-in functions for C strings */
int mojo_isinstance(int obj, int type_id);
char *mojo_str(void *obj);  /* Flexible signature for both int and char* */
char *mojo_repr(int obj);
int mojo_type(int obj);
int mojo_hasattr(int obj, char *attr);
int mojo_getattr(int obj, char *attr);
void mojo_setattr(void *obj, char *attr, int64_t val);
char *mojo_str_cat(char *a, char *b);
char *mojo_str_from_int(int64_t v);
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
void *mojo_sorted(void *iterable);
void *mojo_reversed(void *iterable);

/* Context manager protocol */
int mojo_obj_enter(int obj);
int mojo_obj_exit(int obj, int exc_type, int exc_val, int exc_tb);

/* Call a method by name on an opaque object */
int64_t mojo_obj_call1(int64_t obj, char *method, int64_t arg1);

/* Method stubs for compatibility */
int MojoList_append(MojoList *l, char *v);
int char_join(char *sep, MojoList *items);
int int_items(int obj);

/* Command-line arguments */
void mojo_set_argv(int argc, const char **argv);
MojoList *mojo_get_argv(void);

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
char *mojo_str_lstrip(char *str);
char *mojo_str_rstrip(char *str);
char *mojo_str_expandtabs(char *str, int tabsize);
char *mojo_str_join(char *sep, MojoList *parts);

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

/* ── Missing function stubs for interpreter ──────────────────────────────
 * These are called by generated interpreter code and need stub declarations */

/* Python builtins that appear as function calls */
void setattr(int obj, int attr, int value);  /* setattr builtin */
int tuple(int *args);                         /* tuple constructor */

/* Magic methods for context managers */
int int___enter__(int obj);   /* __enter__ magic method */
int int___exit__(int obj, int exc_type, int exc_val, int exc_tb);  /* __exit__ */

/* String utility functions for method access */
char *int64_t_basename(char *path);    /* basename() from os.path */
char *int64_t_splitext(char *path);    /* splitext() from os.path */
char *int64_t_expanduser(char *path);  /* expanduser() from os.path */
int64_t _char_replace_impl(int64_t s, int64_t old_s, int64_t new_s);
/* str.replace() — macro to suppress implicit int/pointer conversion warnings */
#define char_replace(s, old, new) _char_replace_impl((int64_t)(s), (int64_t)(old), (int64_t)(new))

/* eval() stub — Python's eval() cannot run in C bootstrap; returns first arg unchanged */
int mojo_eval(int expr, MojoDict *globals, MojoDict *locals);

/* Module functions that are imported */
MojoList *py_tokenize(char *source);                /* lexer.tokenize -> list[Token] */
/* Parser is defined as a struct in generated code; no function stub needed */
char *gimple_codegen_compile_to_gimple(char *source, int do_imports, char *filename);  /* compile_to_gimple function */

/* os.path bridge functions (called from compiled module_loader code) */
int int_isdir(int64_t marker, int64_t path);           /* os.path.isdir */
int64_t int_abspath(int64_t marker, int64_t path);     /* os.path.abspath */
int64_t int_dirname(int64_t marker, int64_t path);     /* os.path.dirname */
int int_exists(int64_t marker, int64_t path);          /* os.path.exists */
int64_t int_join(int64_t marker, int64_t base, int64_t part);  /* os.path.join(a, b) */
int64_t int_join_list(int64_t marker, int64_t path_list);      /* os.path.join(*list) */
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

/* Python builtin any() function — suppressed in stdlib mode */
#ifndef __MOJO_STDLIB_MODE__
int any(void *iterable);                        /* Python any() builtin */
#endif

/* Python builtin exception classes and types */
/* Exception defined by generated code, not here */

/* ── Regex substitution with callback (for re.sub(pattern, fn, src)) ────── */
/* callback receives (env, matched_substring) and returns replacement string */
char *mojo_re_sub_fn(char *pattern, char *(*callback)(void *, char *), void *env, char *src);

