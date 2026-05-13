#pragma once
#include <stdint.h>
#include <stdio.h>
#include <setjmp.h>

/* Mojo type aliases */
typedef int mojo_int;
typedef float mojo_float;
typedef char* mojo_string;
typedef void* mojo_any;

/* ── Exception stack (for try/except/raise) ──────────────────────────────
 * Generated __GIMPLE code calls mojo_try_push/mojo_exc_pop/mojo_raise so
 * that jmp_buf pointer arithmetic stays out of GIMPLE functions.          */
#define MOJO_EXC_STACK_MAX 64
extern jmp_buf _mojo_exc_stack[MOJO_EXC_STACK_MAX];
extern int     _mojo_exc_top;

/* Push a new exception frame and call setjmp.
 * Returns 0 on first entry, non-zero after longjmp (exception). */
int  mojo_try_push(void);
/* Pop the topmost exception frame. */
void mojo_exc_pop(void);
/* Raise (longjmp to current frame). */
void mojo_raise(void);
/* Exception message slot (optional string payload for raise). */
extern char *_mojo_exc_msg;
void        mojo_exc_msg_set(char *msg);
char *mojo_exc_msg_get(void);

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
void    mojo_list_append_str(MojoList *l, char *v);

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

/* New string operations */
MojoStr    *mojo_str_slice(MojoStr *s, int64_t start, int64_t stop);
MojoStr    *mojo_str_from_char(char c);
MojoStr    *mojo_str_repeat(MojoStr *s, int64_t n);
int64_t     mojo_str_to_int(MojoStr *s);
double      mojo_str_to_float(MojoStr *s);

/* String method operations on char* */
int mojo_str_startswith(char *s, char *prefix);
int mojo_str_endswith(char *s, char *suffix);
int mojo_str_contains(char *haystack, char *needle);
int64_t mojo_str_find(char *s, char *needle);
MojoList *mojo_str_split(char *s, char *sep);

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
MojoList   *mojo_list_copy(MojoList *l);
int64_t     mojo_list_pop(MojoList *l);
void        mojo_list_extend(MojoList *dst, MojoList *src);
void        mojo_list_sort(MojoList *l);
void        mojo_list_reverse(MojoList *l);
void        mojo_list_clear(MojoList *l);

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
char *mojo_input(char *prompt);

/* Python built-in functions for C strings */
int mojo_isinstance(int obj, int type_id);
char *mojo_str(void *obj);  /* Flexible signature for both int and char* */
char *mojo_repr(int obj);
int mojo_type(int obj);
int mojo_hasattr(int obj, char *attr);
int mojo_getattr(int obj, char *attr);
void mojo_setattr(int obj, char *attr, int val);
char *mojo_str_cat(char *a, char *b);
char *mojo_cstr_repeat(char *s, int64_t n);

/* Additional Python builtins */
int64_t mojo_len(int obj);
void *mojo_range(int64_t start, int64_t stop);
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
int64_t mojo_max(void *args);
int64_t mojo_min(void *args);
int64_t mojo_sum(void *args);
void *mojo_sorted(void *iterable);
void *mojo_reversed(void *iterable);

/* Context manager protocol */
int mojo_obj_enter(int obj);
int mojo_obj_exit(int obj, int exc_type, int exc_val, int exc_tb);

/* Method stubs for compatibility */
int MojoList_append(MojoList *l, char *v);
int char_join(char *sep, MojoList *items);
int int_items(int obj);

/* Command-line arguments */
void mojo_set_argv(int argc, char **argv);
MojoList *mojo_get_argv(void);

/* File I/O - opaque handle for Python file objects */
typedef void* MojoFileHandle;

MojoFileHandle mojo_open(char *filename, char *mode);
void mojo_close(MojoFileHandle fh);
int64_t mojo_write(MojoFileHandle fh, char *data, int64_t len);
int64_t mojo_read(MojoFileHandle fh, char *buffer, int64_t len);
char *mojo_file_read_all(char *filename);

/* Module function stubs */
void *mojo_parse(char *source);
MojoList *mojo_tokenize(char *source);

/* Builtin file I/O - defined in runtime */
int64_t mojo_open_file(char *path);  /* opens a file, returns handle as int64_t */

/* Flattened method stubs for generated GIMPLE code */
char *int_read(int64_t f);
int64_t int_write(int64_t f, char *data);
int64_t int_parse_module(int parser);

/* REPL and string utilities — stdlib-equivalent C implementations */
char *mojo_input(char *prompt);  /* Read line from stdin */
char *input(char *prompt);       /* Alias for mojo_input */

char *string_strip(char *str);         /* Strip whitespace */
char *string_lower(char *str);         /* Convert to lowercase */
char *string_upper(char *str);         /* Convert to uppercase */

/* ── Integer arithmetic helpers ──────────────────────────────────────────
 * Lowered floor-division for use in __GIMPLE code.                      */
static inline int __mojo_floordiv(int a, int b) {
    int q = a / b;
    return q - (a % b != 0 && (a ^ b) < 0);
}
