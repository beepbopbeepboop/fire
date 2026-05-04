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
typedef struct MojoList MojoList;

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
typedef struct MojoStr MojoStr;

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
typedef struct MojoDict MojoDict;

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
typedef struct MojoDictIter MojoDictIter;
MojoDictIter  *mojo_dict_iter_new(MojoDict *d);
int            mojo_dict_iter_next(MojoDictIter *it);     /* 1=has entry, 0=done */
const char    *mojo_dict_iter_key(MojoDictIter *it);
int64_t        mojo_dict_iter_val_int(MojoDictIter *it);
double         mojo_dict_iter_val_double(MojoDictIter *it);
const char    *mojo_dict_iter_val_str(MojoDictIter *it);
void           mojo_dict_iter_free(MojoDictIter *it);

/* ── Set ──────────────────────────────────────────────────────────────────
 * Hash set over int64_t or string values.                                 */
typedef struct MojoSet MojoSet;

MojoSet *mojo_set_new(void);
void     mojo_set_free(MojoSet *s);

void     mojo_set_add_int(MojoSet *s, int64_t v);
void     mojo_set_add_str(MojoSet *s, const char *v);

int      mojo_set_contains_int(MojoSet *s, int64_t v);
int      mojo_set_contains_str(MojoSet *s, const char *v);
int64_t  mojo_set_len(MojoSet *s);

/* Set iterator */
typedef struct MojoSetIter MojoSetIter;
MojoSetIter *mojo_set_iter_new(MojoSet *s);
int          mojo_set_iter_next(MojoSetIter *it);      /* 1=has entry, 0=done */
int64_t      mojo_set_iter_val_int(MojoSetIter *it);
const char  *mojo_set_iter_val_str(MojoSetIter *it);
void         mojo_set_iter_free(MojoSetIter *it);

void     mojo_set_print(MojoSet *s);
