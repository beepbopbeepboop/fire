#pragma once
#include <stdint.h>
#include <stdio.h>
#include <setjmp.h>

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
void        mojo_exc_msg_set(const char *msg);
const char *mojo_exc_msg_get(void);

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
int mojo_list_contains_str(MojoList *l, const char *v);

/* Item mutation and extra accessors */
void     mojo_list_set_int(MojoList *l, int64_t i, int64_t v);
void     mojo_list_set_double(MojoList *l, int64_t i, double v);
void     mojo_list_set_str(MojoList *l, int64_t i, const char *v);
char    *mojo_list_get_str(MojoList *l, int64_t i);
MojoList*mojo_list_slice(MojoList *l, int64_t start, int64_t stop);
MojoList*mojo_list_concat(MojoList *a, MojoList *b);

void mojo_list_print(MojoList *l);

/* ── String ───────────────────────────────────────────────────────────────*/
typedef struct {
    char    *data;
    int64_t  len;
} MojoStr;

MojoStr    *mojo_str_new(const char *s);
void        mojo_str_free(MojoStr *s);
MojoStr    *mojo_str_concat(MojoStr *a, MojoStr *b);
int64_t     mojo_str_len(MojoStr *s);
const char *mojo_str_data(MojoStr *s);
int         mojo_str_eq(MojoStr *a, MojoStr *b);
int         mojo_str_contains(MojoStr *haystack, const char *needle);
char        mojo_str_char_at(MojoStr *s, int64_t i);
void        mojo_str_print(MojoStr *s);

/* New string operations */
MojoStr    *mojo_str_slice(MojoStr *s, int64_t start, int64_t stop);
MojoStr    *mojo_str_from_char(char c);
MojoStr    *mojo_str_repeat(MojoStr *s, int64_t n);
int64_t     mojo_str_to_int(MojoStr *s);
double      mojo_str_to_float(MojoStr *s);

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

void        mojo_dict_set_int(MojoDict *d, const char *key, int64_t v);
void        mojo_dict_set_double(MojoDict *d, const char *key, double v);
void        mojo_dict_set_str(MojoDict *d, const char *key, const char *v);

int64_t     mojo_dict_get_int(MojoDict *d, const char *key);
double      mojo_dict_get_double(MojoDict *d, const char *key);
const char *mojo_dict_get_str(MojoDict *d, const char *key);

int         mojo_dict_contains(MojoDict *d, const char *key);
void        mojo_dict_print(MojoDict *d);
int64_t     mojo_dict_len(MojoDict *d);

/* Dict iterator — advance, then read key/value via accessor calls */
typedef struct {
    MojoDict *dict;
    int64_t   pos;    /* current slot index (-1 = not yet started) */
} MojoDictIter;
MojoDictIter  *mojo_dict_iter_new(MojoDict *d);
int            mojo_dict_iter_next(MojoDictIter *it);     /* 1=has entry, 0=done */
const char    *mojo_dict_iter_key(MojoDictIter *it);
int64_t        mojo_dict_iter_val_int(MojoDictIter *it);
double         mojo_dict_iter_val_double(MojoDictIter *it);
const char    *mojo_dict_iter_val_str(MojoDictIter *it);
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
void     mojo_set_add_str(MojoSet *s, const char *v);

int      mojo_set_contains_int(MojoSet *s, int64_t v);
int      mojo_set_contains_str(MojoSet *s, const char *v);
int64_t  mojo_set_len(MojoSet *s);

/* Set iterator */
typedef struct {
    MojoSet *set;
    int64_t  pos;   /* current slot index */
} MojoSetIter;
MojoSetIter *mojo_set_iter_new(MojoSet *s);
int          mojo_set_iter_next(MojoSetIter *it);      /* 1=has entry, 0=done */
int64_t      mojo_set_iter_val_int(MojoSetIter *it);
const char  *mojo_set_iter_val_str(MojoSetIter *it);
void         mojo_set_iter_free(MojoSetIter *it);

void     mojo_set_print(MojoSet *s);

/* ── Python integration ─────────────────────────────────────────────────*/
void mojo_print(const char *str);
char *mojo_input(const char *prompt);

/* Python built-in functions for C strings */
int mojo_isinstance(int obj, int type_id);
char *mojo_str(void *obj);  /* Flexible signature for both int and char* */
char *mojo_repr(int obj);
int mojo_type(int obj);
int mojo_hasattr(int obj, const char *attr);
char *mojo_str_cat(const char *a, const char *b);
char *mojo_cstr_repeat(const char *s, int64_t n);

/* Method stubs for compatibility */
int MojoList_append(MojoList *l, char *v);
int char_join(const char *sep, MojoList *items);
int int_items(int obj);
int int_read(int fh);

/* Command-line arguments */
void mojo_set_argv(int argc, const char **argv);
MojoList *mojo_get_argv(void);

/* File I/O - opaque handle for Python file objects */
typedef void* MojoFileHandle;

MojoFileHandle mojo_open(const char *filename, const char *mode);
void mojo_close(MojoFileHandle fh);
int64_t mojo_write(MojoFileHandle fh, const char *data, int64_t len);
int64_t mojo_read(MojoFileHandle fh, char *buffer, int64_t len);
char *mojo_file_read_all(const char *filename);

/* Module function stubs */
MojoFileHandle mojo_python_open(const char *filename);
char *mojo_python_read(MojoFileHandle fh);
int int_read(int fh);
void *mojo_parse(const char *source);
MojoList *mojo_tokenize(const char *source);

/* Builtin file I/O - defined in runtime */
int open(int path);
