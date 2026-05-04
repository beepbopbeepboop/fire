#include "mojo_runtime.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdint.h>

/* Exception stack */
jmp_buf _mojo_exc_stack[MOJO_EXC_STACK_MAX];
int     _mojo_exc_top = -1;

int mojo_try_push(void)
{
    ++_mojo_exc_top;
    return setjmp(_mojo_exc_stack[_mojo_exc_top]);
}

void mojo_exc_pop(void)
{
    --_mojo_exc_top;
}

void mojo_raise(void)
{
    longjmp(_mojo_exc_stack[_mojo_exc_top], 1);
}

char *_mojo_exc_msg = NULL;
void mojo_exc_msg_set(const char *msg) { _mojo_exc_msg = (char *)msg; }
const char *mojo_exc_msg_get(void) { return _mojo_exc_msg ? _mojo_exc_msg : ""; }

/* ═══════════════════════════════════════════════════════════════════════
 * MojoList
 * ═══════════════════════════════════════════════════════════════════════*/

struct MojoList {
    int64_t *data;
    int64_t  len;
    int64_t  cap;
};

MojoList *mojo_list_new(void)
{
    MojoList *l = malloc(sizeof(MojoList));
    l->data = NULL;
    l->len  = 0;
    l->cap  = 0;
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

int64_t mojo_list_get_int(MojoList *l, int64_t i)   { return l->data[i]; }

double mojo_list_get_double(MojoList *l, int64_t i)
{
    double v;
    memcpy(&v, &l->data[i], sizeof(v));
    return v;
}

int64_t mojo_list_len(MojoList *l) { return l->len; }

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

int mojo_list_contains_str(MojoList *l, const char *v)
{
    for (int64_t i = 0; i < l->len; i++) {
        const char *s = (const char *)(uintptr_t)l->data[i];
        if (s && strcmp(s, v) == 0) return 1;
    }
    return 0;
}

void mojo_list_set_int(MojoList *l, int64_t i, int64_t v)   { l->data[i] = v; }

void mojo_list_set_double(MojoList *l, int64_t i, double v)
{
    int64_t bits;
    memcpy(&bits, &v, sizeof(bits));
    l->data[i] = bits;
}

void mojo_list_set_str(MojoList *l, int64_t i, const char *v)
{
    l->data[i] = (int64_t)(uintptr_t)v;
}

char *mojo_list_get_str(MojoList *l, int64_t i)
{
    return (char *)(uintptr_t)l->data[i];
}

MojoList *mojo_list_slice(MojoList *l, int64_t start, int64_t stop)
{
    if (start < 0) start = l->len + start;
    if (stop  < 0) stop  = l->len + stop;
    if (start < 0) start = 0;
    if (stop > l->len) stop = l->len;
    MojoList *r = mojo_list_new();
    for (int64_t i = start; i < stop; i++)
        mojo_list_append_int(r, l->data[i]);
    return r;
}

MojoList *mojo_list_concat(MojoList *a, MojoList *b)
{
    MojoList *r = mojo_list_new();
    for (int64_t i = 0; i < a->len; i++) mojo_list_append_int(r, a->data[i]);
    for (int64_t i = 0; i < b->len; i++) mojo_list_append_int(r, b->data[i]);
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

MojoStr *mojo_str_new(const char *s)
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
const char *mojo_str_data(MojoStr *s) { return s->data; }

MojoStr *mojo_str_slice(MojoStr *s, int64_t start, int64_t stop)
{
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

int mojo_str_contains(MojoStr *haystack, const char *needle)
{
    return strstr(haystack->data, needle) != NULL;
}

char mojo_str_char_at(MojoStr *s, int64_t i) { return s->data[i]; }
void mojo_str_print(MojoStr *s) { fwrite(s->data, 1, (size_t)s->len, stdout); }

/* ═══════════════════════════════════════════════════════════════════════
 * MojoDict — open-addressing hash map, string keys, int64_t slots
 * ═══════════════════════════════════════════════════════════════════════*/

typedef struct {
    char    *key;   /* NULL = empty slot */
    int64_t  val;
} _DictSlot;

struct MojoDict {
    _DictSlot *slots;
    int64_t    used;
    int64_t    cap;
};

static uint64_t _str_hash(const char *s)
{
    uint64_t h = 14695981039346656037ULL;
    for (; *s; s++) h = (h ^ (uint8_t)*s) * 1099511628211ULL;
    return h;
}

MojoDict *mojo_dict_new(void)
{
    MojoDict *d = malloc(sizeof(MojoDict));
    d->cap   = 8;
    d->used  = 0;
    d->slots = calloc((size_t)d->cap, sizeof(_DictSlot));
    return d;
}

void mojo_dict_free(MojoDict *d)
{
    for (int64_t i = 0; i < d->cap; i++) free(d->slots[i].key);
    free(d->slots);
    free(d);
}

static _DictSlot *_dict_find(MojoDict *d, const char *key)
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

static void _dict_set_raw(MojoDict *d, const char *key, int64_t val)
{
    if (d->used * 2 >= d->cap) _dict_grow(d);
    _DictSlot *sl = _dict_find(d, key);
    if (!sl->key) {
        sl->key = strdup(key);
        d->used++;
    }
    sl->val = val;
}

static void _dict_grow(MojoDict *d)
{
    int64_t old_cap = d->cap;
    _DictSlot *old  = d->slots;
    d->cap   *= 2;
    d->used  = 0;
    d->slots = calloc((size_t)d->cap, sizeof(_DictSlot));
    for (int64_t i = 0; i < old_cap; i++)
        if (old[i].key) _dict_set_raw(d, old[i].key, old[i].val);
    for (int64_t i = 0; i < old_cap; i++) free(old[i].key);
    free(old);
}

void mojo_dict_set_int(MojoDict *d, const char *key, int64_t v)
{
    _dict_set_raw(d, key, v);
}

void mojo_dict_set_double(MojoDict *d, const char *key, double v)
{
    int64_t bits;
    memcpy(&bits, &v, sizeof(bits));
    _dict_set_raw(d, key, bits);
}

void mojo_dict_set_str(MojoDict *d, const char *key, const char *v)
{
    _dict_set_raw(d, key, (int64_t)(uintptr_t)v);
}

static _DictSlot *_dict_lookup(MojoDict *d, const char *key)
{
    uint64_t h = _str_hash(key) % (uint64_t)d->cap;
    for (int64_t i = 0; i < d->cap; i++) {
        int64_t idx = (int64_t)((h + (uint64_t)i) % (uint64_t)d->cap);
        _DictSlot *sl = &d->slots[idx];
        if (!sl->key) return NULL;
        if (strcmp(sl->key, key) == 0) return sl;
    }
    return NULL;
}

int64_t mojo_dict_get_int(MojoDict *d, const char *key)
{
    _DictSlot *sl = _dict_lookup(d, key);
    return sl ? sl->val : 0;
}

double mojo_dict_get_double(MojoDict *d, const char *key)
{
    _DictSlot *sl = _dict_lookup(d, key);
    if (!sl) return 0.0;
    double v;
    memcpy(&v, &sl->val, sizeof(v));
    return v;
}

const char *mojo_dict_get_str(MojoDict *d, const char *key)
{
    _DictSlot *sl = _dict_lookup(d, key);
    return sl ? (const char *)(uintptr_t)sl->val : NULL;
}

int mojo_dict_contains(MojoDict *d, const char *key)
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

int64_t mojo_dict_len(MojoDict *d) { return d->used; }

/* ── MojoDictIter ─────────────────────────────────────────────────────────*/

struct MojoDictIter {
    MojoDict *dict;
    int64_t   pos;    /* current slot index (-1 = not yet started) */
};

MojoDictIter *mojo_dict_iter_new(MojoDict *d)
{
    MojoDictIter *it = malloc(sizeof(MojoDictIter));
    it->dict = d;
    it->pos  = -1;
    return it;
}

int mojo_dict_iter_next(MojoDictIter *it)
{
    it->pos++;
    while (it->pos < it->dict->cap) {
        if (it->dict->slots[it->pos].key) return 1;
        it->pos++;
    }
    return 0;
}

const char *mojo_dict_iter_key(MojoDictIter *it)
{
    return it->dict->slots[it->pos].key;
}

int64_t mojo_dict_iter_val_int(MojoDictIter *it)
{
    return it->dict->slots[it->pos].val;
}

double mojo_dict_iter_val_double(MojoDictIter *it)
{
    double v;
    memcpy(&v, &it->dict->slots[it->pos].val, sizeof(v));
    return v;
}

const char *mojo_dict_iter_val_str(MojoDictIter *it)
{
    return (const char *)(uintptr_t)it->dict->slots[it->pos].val;
}

void mojo_dict_iter_free(MojoDictIter *it) { free(it); }

/* ═══════════════════════════════════════════════════════════════════════
 * MojoSet — hash set backed by the same open-addressing scheme
 * ═══════════════════════════════════════════════════════════════════════*/

typedef struct {
    int     tag;   /* -1 = empty, 0 = int, 1 = str */
    int64_t val_i;
    char   *val_s;
} _SetSlot;

struct MojoSet {
    _SetSlot *slots;
    int64_t   used;
    int64_t   cap;
};

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

static void _set_grow(MojoSet *s);

static int64_t _set_slot_int(MojoSet *s, int64_t v)
{
    uint64_t h = (uint64_t)v * 2654435761ULL;
    for (int64_t i = 0; i < s->cap; i++) {
        int64_t idx = (int64_t)((h + (uint64_t)i) % (uint64_t)s->cap);
        _SetSlot *sl = &s->slots[idx];
        if (sl->tag == -1) return idx;
        if (sl->tag == 0 && sl->val_i == v) return idx;
    }
    return -1;
}

static int64_t _set_slot_str(MojoSet *s, const char *v)
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

void mojo_set_add_str(MojoSet *s, const char *v)
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

int mojo_set_contains_str(MojoSet *s, const char *v)
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

int64_t mojo_set_len(MojoSet *s) { return s->used; }

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

const char *mojo_set_iter_val_str(MojoSetIter *it)
{
    return it->set->slots[it->pos].val_s;
}

void mojo_set_iter_free(MojoSetIter *it) { free(it); }
