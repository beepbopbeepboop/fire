#!/usr/bin/env python3
"""Runtime unit test for the two hot-path data structures the container
runtime is built on (doc/MEMORY.html sections 10 and 3.A):

  * `_PtrReg`, the pointer-membership table behind mojo_is_registered_list/
    dict/set, tuple and bound-method marking. Every container init/destroy
    pays one add and one discard, so it was rewritten from a general MojoSet
    into a dedicated open-addressing table with backward-shift deletion; this
    checks it against a reference model, including forced collisions and the
    LIFO add/remove of ONE address that a stack-homed container produces.
  * the per-slot element-KINDS side table (`_reg_kinds`), keyed the same way
    but carrying a payload, against the same kind of model. Its delete used
    to clear the slot instead of closing the probe gap, so one list's free
    silently stripped the kinds off every other LIVE list sharing its probe
    cluster — the same shape the container registries' own `_destroy`
    helpers avoid, and the one this table had too (2026-09-30).
  * integer dict keys: canonical-decimal detection, int/string equivalence in both directions, strings that only
    look numeric staying separate, bytes keys staying separate, the `_kw` entry points against a reference model;
  * the Int-key path's fast itoa + block pool and the dict's resize (moves keys, keeps
    insertion order), which the Int-keyed dict benchmark depends on;
  * the dict's and set's 8-slot inline first table and the integer key's lazy decimal string: a small stack
    dict/set allocates nothing, growth/pop/copy/iteration/keys stay correct across the boundary;
  * MojoList's 4-slot inline buffer: growth across the boundary, a stack
    struct that is init'd/destroyed repeatedly, and (under AddressSanitizer,
    when the toolchain has it) that destroy never frees the inline storage.

The harness `#include`s fire_runtime.c so it can reach the static `_pr_*`
functions; it is built and run at -O0 and -O2, because the runtime is shipped
at -O2 and an optimization-only bug is exactly what this must not miss.
"""
import os
import shutil
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
from build_config import find_gcc  # noqa: E402

HARNESS = r'''
#include "fire_runtime.c"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#define N 4096
static uint64_t model[N]; static int present[N];
static uint64_t addr(int i) { return 0x100000000ULL + (uint64_t)i * 16; }

static void test_ptrreg(void) {
    srand(12345);
    _PtrReg r; memset(&r, 0, sizeof r);
    uint64_t live = 0;
    for (int i = 0; i < N; i++) model[i] = addr(i);
    for (int round = 0; round < 1500000; round++) {
        int i = rand() % N; int op = rand() % 3;
        if (op == 0) { _pr_add(&r, model[i]); if (!present[i]) { present[i]=1; live++; } }
        else if (op == 1) { _pr_del(&r, model[i]); if (present[i]) { present[i]=0; live--; } }
        else { assert(_pr_has(&r, model[i]) == present[i]); }
        if (round % 100000 == 0) {
            for (int k = 0; k < N; k++) assert(_pr_has(&r, model[k]) == present[k]);
            assert(r.used == live);
        }
    }
    for (int k = 0; k < N; k++) assert(_pr_has(&r, model[k]) == present[k]);
    assert(r.used == live);
    _PtrReg c; memset(&c, 0, sizeof c);
    for (int i = 0; i < 2000; i++) _pr_add(&c, addr(i * 256));
    for (int i = 0; i < 2000; i += 2) _pr_del(&c, addr(i * 256));
    for (int i = 0; i < 2000; i++) assert(_pr_has(&c, addr(i * 256)) == (i % 2));
    _PtrReg l; memset(&l, 0, sizeof l);
    for (int i = 0; i < 2000000; i++) {
        _pr_add(&l, addr(7)); assert(_pr_has(&l, addr(7))); _pr_del(&l, addr(7));
    }
    assert(l.used == 0 && !_pr_has(&l, addr(7)));
    /* add is idempotent; deleting an absent key is a no-op; 0 is never stored */
    _PtrReg m; memset(&m, 0, sizeof m);
    _pr_add(&m, addr(1)); _pr_add(&m, addr(1)); assert(m.used == 1);
    _pr_del(&m, addr(2)); assert(m.used == 1);
    _pr_add(&m, 0); assert(m.used == 1 && !_pr_has(&m, 0));
}

/* The per-slot ELEMENT-KINDS side table (`_reg_kinds`), keyed by the live
 * MojoList address like the _PtrReg tables but with a payload. Two of its
 * own properties, both measured: its home function used to be a bare
 * `addr & mask`, and heap MojoLists are 64 bytes apart (sizeof is 56,
 * malloc's size class rounds up), so EVERY row shared one probe cluster;
 * and its delete cleared the slot instead of closing the probe gap, so one
 * list's free made every later member of the cluster unfindable — a live
 * list silently losing the element kinds that describe it. Checked here
 * against a reference model over forced collisions, plus the exact shape
 * that broke (two colliding lists, one destroyed, the survivor intact). */
static void test_kinds_table(void) {
    enum { M = 512 };
    static uint64_t live[M]; static int present[M];
    static char ktag[M][4];
    for (int i = 0; i < M; i++) { live[i] = addr(i) + (i * 64);   /* 64-byte stride */
                                  ktag[i][0] = "dipnsl"[i % 6]; ktag[i][1] = 0; }
    srand(4242);
    int nlive = 0;
    for (int round = 0; round < 400000; round++) {
        int i = rand() % M;
        if (rand() % 3 == 0) {
            _KindRow *r = _kinds_row(live[i]);
            assert((r != NULL) == present[i]);
            if (r) { assert(r->addr == live[i]); assert(r->kinds == ktag[i]); }
        } else if (present[i]) {
            _kinds_forget(live[i]); present[i] = 0; nlive--;
        } else {
            int fresh = 0;
            _KindRow *r = _kinds_row_for_write(live[i], &fresh);
            assert(fresh); assert(r->addr == live[i]); r->kinds = ktag[i];
            present[i] = 1; nlive++;
        }
        if (round % 50000 == 0) {
            for (int k = 0; k < M; k++) {
                _KindRow *r = _kinds_row(live[k]);
                assert((r != NULL) == present[k]);
                if (r) assert(r->kinds == ktag[k]);
            }
            assert((int)_reg_kinds.used == nlive);
        }
    }
    for (int k = 0; k < M; k++) if (present[k]) { _kinds_forget(live[k]); present[k] = 0; nlive--; }
    assert(_reg_kinds.used == 0 && nlive == 0);

    /* The delete, forced. The home function is a multiplicative hash, so two
     * real heap lists no longer collide by construction (that WAS the bug:
     * a bare `addr & mask` put every row in one cluster because malloc hands
     * out 64-byte blocks and sizeof(MojoList) is 56). So the deletion rule
     * cannot be pinned by hoping for a collision — find an address that
     * genuinely shares a home slot with a live row, and require that
     * deleting the FIRST leaves the second findable. With the clear-the-slot
     * delete this asserts and the process aborts; with backward-shift it
     * holds. That is the half of the fix the heap-pair shape above can no
     * longer reach, and it is the half that protects any future home
     * function. */
    /* The table is empty here, so a row sits exactly at its home slot and
     * the first address whose home matches lands immediately after it in the
     * same cluster — which is precisely the layout a clear-the-slot delete
     * strands. */
    assert(_reg_kinds.used == 0 && _reg_kinds.cap >= 64);
    MojoList *p1 = mojo_list_new();
    mojo_list_set_kinds(p1, "dp");
    uint64_t a1 = (uint64_t)(uintptr_t)p1;
    uint64_t a2 = 0;
    for (uint64_t cand = a1 + 8; cand < a1 + (1ULL << 20); cand += 8) {
        if (_kinds_home(cand) == _kinds_home(a1)) { a2 = cand; break; }
    }
    assert(a2 != 0);
    int fresh = 0;
    _kinds_row_for_write(a2, &fresh)->kinds = "nn";
    assert(_reg_kinds.rows[_kinds_home(a1)].addr == a1);
    assert(_reg_kinds.rows[(_kinds_home(a1) + 1) & (_reg_kinds.cap - 1)].addr == a2);
    _kinds_forget(a1);
    _KindRow *after = _kinds_row(a2);
    assert(after != NULL && after->kinds == "nn");
    _kinds_forget(a2);
    mojo_list_free(p1);

    /* The exact failing shape: two colliding lists with kinds, the first
     * destroyed, the second still live and still described. */
    MojoList *x = mojo_list_new(), *y = mojo_list_new();
    mojo_list_append_double(x, 1.5); mojo_list_append_str(x, "aa");
    mojo_list_append_double(y, 9.5); mojo_list_append_str(y, "zz");
    mojo_list_set_kinds(x, "dp"); mojo_list_set_kinds(y, "dp");
    mojo_list_free(x);
    assert(mojo_list_get_kinds(y) && strcmp(mojo_list_get_kinds(y), "dp") == 0);
    assert(mojo_list_slot_kind(y, 0) == 'd' && mojo_list_slot_kind(y, 1) == 'p');
    /* a boxed read of the survivor's float slot really does box */
    int64_t bx = mojo_list_get_boxed(y, 0);
    assert(mojo_is_boxed(bx) && mojo_box_double(bx) == 9.5);
    mojo_list_free(y);
    /* and the row is really gone afterwards, so a reused address starts clean */
    MojoList *z = mojo_list_new();
    assert(mojo_list_get_kinds(z) == NULL);
    mojo_list_set_kinds(z, "ii");
    assert(mojo_list_get_kinds(z) && strcmp(mojo_list_get_kinds(z), "ii") == 0);
    mojo_list_free(z);
}

static void test_list_inline(void) {
    for (int n = 0; n <= 40; n++) {
        MojoList st; mojo_list_init(&st);
        MojoList *hp = mojo_list_new();
        assert(st.data == st.inl && st.cap == MOJO_LIST_INLINE);
        assert(mojo_is_registered_list((int64_t)(intptr_t)&st));
        for (int i = 0; i < n; i++) { mojo_list_append_int(&st, i * 7); mojo_list_append_int(hp, i * 7); }
        assert(st.len == n && hp->len == n);
        assert((st.data == st.inl) == (n <= MOJO_LIST_INLINE));
        for (int i = 0; i < n; i++) { assert(st.data[i] == i * 7); assert(hp->data[i] == i * 7); }
        mojo_list_destroy(&st);
        assert(!mojo_is_registered_list((int64_t)(intptr_t)&st));
        mojo_list_free(hp);
        mojo_list_init(&st);              /* the same storage re-init'd, as a loop does */
        assert(st.len == 0 && st.data == st.inl);
        mojo_list_destroy(&st);
    }
}

static void test_dict_and_itoa(void) {
    /* itoa against snprintf at every boundary. A KEPT decimal (mojo_str_from_int)
     * is an ordinary malloc'd string; the TRANSIENT one (mojo_cstr_or_int_str)
     * is a pool block and is the only thing mojo_cstr_or_int_release accepts.
     *
     * The two halves are checked over DIFFERENT value sets, and that is not
     * bookkeeping. `mojo_cstr_or_int_str(v)` returns `v` ITSELF — the caller
     * hands it back unchanged and it is never pooled — for any `v` the
     * runtime's boxed-string test claims, which is the [2GiB, 2^47) window
     * (`_mojo_ptr_shaped`: a char* and an int64_t are the same width here, so
     * a value in that window is a pointer until proven otherwise). 2^32 and
     * INT64_MAX are in it, so `strcmp(t, "4294967296")` on the raw return
     * dereferences the integer 4294967296 as a `char *` and segfaults — the
     * correct behaviour being asserted, tested wrongly. `mojo_str_from_int`
     * has no such test and is checked over the full range, extremes
     * included; the transient one is checked over everything OUTSIDE the
     * window, and the in-window entries are asserted to come back
     * unchanged, which is the documented contract. (This harness ran with
     * `-DNDEBUG` for its whole life — see `_flags` — so these `strcmp`s were
     * never executed and the segfault below them was never reached.) */
    int64_t vals[] = {0,1,-1,9,10,-10,99,100,12345,-98765,2147483647LL,-2147483648LL,4294967296LL,
                      9223372036854775807LL, (int64_t)(-9223372036854775807LL-1)};
    for (unsigned i = 0; i < sizeof vals / sizeof *vals; i++) {
        char ref[32]; snprintf(ref, sizeof ref, "%lld", (long long)vals[i]);
        char *kept = mojo_str_from_int(vals[i]); assert(strcmp(kept, ref) == 0); free(kept);
        uint64_t u = (uint64_t)vals[i];
        int boxed = (u >= 0x80000000ULL && u < 0x0000800000000000ULL);
        char *t = mojo_cstr_or_int_str(vals[i]);
        if (boxed) assert(t == (char *)(intptr_t)vals[i]);
        else assert(strcmp(t, ref) == 0);
        mojo_cstr_or_int_release(vals[i], t);
    }
    /* below the window's floor, and outside it, both spell a decimal */
    for (int64_t v = 0; v < 65536; v += 4093) {
        char ref[32]; snprintf(ref, sizeof ref, "%lld", (long long)v);
        char *t = mojo_cstr_or_int_str(v); assert(strcmp(t, ref) == 0);
        mojo_cstr_or_int_release(v, t);
    }
    /* above its ceiling, likewise. Doubling UP from the boundary, because
     * walking down from it walks straight back into the window these values
     * are excluded from (2^45 is inside [2^31, 2^47)). */
    for (int64_t v = (int64_t)0x0000800000000000ULL; v > 0 && v <= (int64_t)0x4000000000000000LL; v *= 2) {
        char ref[32]; snprintf(ref, sizeof ref, "%lld", (long long)v);
        char *t = mojo_cstr_or_int_str(v); assert(strcmp(t, ref) == 0);
        mojo_cstr_or_int_release(v, t);
    }
    /* a released transient block is the next one handed out */
    char *a = mojo_cstr_or_int_str(42); mojo_cstr_or_int_release(42, a);
    char *b = mojo_cstr_or_int_str(-7); assert(b == a && strcmp(b, "-7") == 0); mojo_cstr_or_int_release(-7, b);
    /* a kept decimal never enters the pool: it is not the block just released */
    char *kept2 = mojo_str_from_int(5); assert(kept2 != a); assert(strcmp(kept2, "5") == 0); free(kept2);
    /* a borrowed boxed string is returned unchanged and never pooled */
    char lit[] = "abc";
    char *same = mojo_cstr_or_int_str((int64_t)(intptr_t)lit); assert(same == lit);
    mojo_cstr_or_int_release((int64_t)(intptr_t)lit, same);
    char *c = mojo_cstr_or_int_str(1); assert(c != lit); mojo_cstr_or_int_release(1, c);
    /* many keys across several resizes: all present, absent stays absent, insertion order kept */
    MojoDict *d = mojo_dict_new();
    for (int i = 0; i < 5000; i++) { char *k = mojo_cstr_or_int_str(i); mojo_dict_set_int(d, k, i * 3); mojo_cstr_or_int_release(i, k); }
    assert(d->used == 5000);
    for (int i = 0; i < 5000; i++) { char *k = mojo_cstr_or_int_str(i); assert(mojo_dict_contains(d, k)); assert(mojo_dict_get_int(d, k) == i * 3); mojo_cstr_or_int_release(i, k); }
    char *k = mojo_cstr_or_int_str(5001); assert(!mojo_dict_contains(d, k)); mojo_cstr_or_int_release(5001, k);
    MojoList *keys = mojo_dict_keys(d); assert(keys->len == 5000);
    for (int i = 0; i < 5000; i++) { char ref[16]; snprintf(ref, sizeof ref, "%d", i); assert(strcmp(mojo_list_get_str(keys, i), ref) == 0); }
    mojo_list_free(keys);
    mojo_dict_free(d);
}

static void test_dict_int_keys(void) {
    /* Which strings are canonical integers (and so live in integer slots). */
    struct { const char *s; int ok; long long v; } tab[] = {
        {"0",1,0},{"5",1,5},{"-12",1,-12},{"9223372036854775807",1,9223372036854775807LL},
        {"-9223372036854775808",1,(long long)(-9223372036854775807LL-1)},
        {"05",0,0},{"+5",0,0},{"-0",0,0},{"",0,0},{"-",0,0},{"5a",0,0},{" 5",0,0},{"5 ",0,0},
        {"9223372036854775808",0,0},{"-9223372036854775809",0,0},{"12345678901234567890",0,0},
        {"00",0,0},{"1.5",0,0},{"0x10",0,0},
    };
    for (unsigned i = 0; i < sizeof tab / sizeof *tab; i++) {
        int64_t v = 0; int ok = _canon_int(tab[i].s, &v);
        assert(ok == tab[i].ok);
        if (ok) assert(v == tab[i].v);
    }
    /* int and string spellings of a key are ONE entry, in both directions. */
    MojoDict *d = mojo_dict_new();
    mojo_dict_set_int_kw(d, 5, 50);
    assert(mojo_dict_get_int(d, "5") == 50 && mojo_dict_contains(d, "5"));
    mojo_dict_set_int(d, "7", 70);
    assert(mojo_dict_get_int_kw(d, 7) == 70 && mojo_dict_contains_kw(d, 7));
    mojo_dict_set_int(d, "5", 51);                       /* overwrites, does not add */
    assert(d->used == 2 && mojo_dict_get_int_kw(d, 5) == 51);
    /* strings that merely LOOK numeric are their own keys, distinct from the int */
    mojo_dict_set_int(d, "007", 1); mojo_dict_set_int(d, "+7", 2); mojo_dict_set_int(d, "-0", 3);
    assert(d->used == 5);
    assert(mojo_dict_get_int(d, "007") == 1 && mojo_dict_get_int(d, "+7") == 2 && mojo_dict_get_int(d, "-0") == 3);
    assert(mojo_dict_get_int_kw(d, 7) == 70 && !mojo_dict_contains_kw(d, 0) && !mojo_dict_contains_kw(d, 6));
    /* a boxed string word goes to the string path */
    static char abc[] = "abc";
    mojo_dict_set_int_kw(d, (int64_t)(intptr_t)abc, 99);
    assert(mojo_dict_get_int(d, "abc") == 99 && mojo_dict_get_int_kw(d, (int64_t)(intptr_t)abc) == 99);
    /* bytes keys stay their own domain even when their bytes spell an integer */
    MojoBytes *b5 = mojo_bytes_from_cstr("5");
    mojo_dict_set_bytes_int(d, b5, 555);
    assert(mojo_dict_get_bytes_int(d, b5) == 555 && mojo_dict_get_int_kw(d, 5) == 51);
    /* iteration: integer keys come back as their decimal strings, in insertion order */
    MojoList *keys = mojo_dict_keys(d);
    const char *want[] = {"5", "7", "007", "+7", "-0", "abc", "5"};
    assert(keys->len == 7);
    for (int i = 0; i < 7; i++) assert(strcmp(mojo_list_get_str(keys, i), want[i]) == 0);
    mojo_list_free(keys);
    /* pop by int and by string; the rest survive, order kept. Seven keys went
     * in (the int 5, the int 7, "007", "+7", "-0", "abc" and the BYTES key
     * b'5', which is its own domain), so five are left after the two pops —
     * the count here was written as 4 and, with every assert in this harness
     * compiled out by the `-DNDEBUG` in `python3-config --cflags` (see
     * `_flags`), that arithmetic was never executed. */
    assert(mojo_dict_pop_int_kw(d, 5) == 51 && !mojo_dict_contains(d, "5") && !mojo_dict_contains_kw(d, 5));
    assert(mojo_dict_pop_int(d, "7") == 70 && !mojo_dict_contains_kw(d, 7));
    assert(mojo_dict_pop_int_kw(d, 12345) == 0);           /* absent */
    assert(mojo_dict_get_int(d, "007") == 1 && mojo_dict_get_bytes_int(d, b5) == 555 && d->used == 5);
    mojo_dict_free(d);

    /* against a reference model: set/get/contains/pop/setdefault, negatives and extremes */
    enum { M = 3000 };
    static int64_t val[M]; static int present[M];
    int64_t keyv[M];
    for (int i = 0; i < M; i++) keyv[i] = (i % 7 == 0) ? -(int64_t)(i + 1) * 1000003
                                       : (i % 11 == 0) ? (int64_t)i * 4294967311LL : (int64_t)i;
    keyv[1] = INT64_MAX; keyv[2] = INT64_MIN + 1; keyv[3] = 0;
    /* the word test: keys that look like pointers would be read as strings, so keep them out of
     * the [2^31, 2^47) window the boxed-string test claims (a documented, pre-existing limit) */
    for (int i = 0; i < M; i++) {
        uint64_t u = (uint64_t)keyv[i];
        if (u >= 0x80000000ULL && u < 0x0000800000000000ULL) keyv[i] = -(int64_t)i - 1;
    }
    /* The model indexes its state by POSITION, so it is only a model of a dict
     * if every position holds a DISTINCT key — and it did not: `i % 7 == 0`
     * gave index 0 the key 0, which `keyv[3] = 0` also claims, so the two
     * positions shared one entry and the model reported a phantom key at
     * round 752 of 400,000 (`contains(0)` true where the model said absent).
     * Asserted here rather than fixed quietly, because a model with
     * duplicate keys is wrong in a way that reads as a runtime bug. */
    for (int i = 0; i < M; i++)
        for (int j = i + 1; j < M; j++)
            assert(keyv[i] != keyv[j]);
    srand(777);
    MojoDict *m = mojo_dict_new();
    for (int round = 0; round < 400000; round++) {
        int i = rand() % M; int op = rand() % 5;
        if (op == 0) { mojo_dict_set_int_kw(m, keyv[i], round); val[i] = round; present[i] = 1; }
        else if (op == 1) { int64_t r = mojo_dict_pop_int_kw(m, keyv[i]); assert(r == (present[i] ? val[i] : 0)); present[i] = 0; }
        else if (op == 2) { assert(mojo_dict_contains_kw(m, keyv[i]) == present[i]); }
        else if (op == 3) { int64_t r = mojo_dict_setdefault_int_kw(m, keyv[i], 42);
                            if (!present[i]) { val[i] = 42; present[i] = 1; assert(r == 42); } else assert(r == val[i]); }
        else { assert(mojo_dict_get_int_kw(m, keyv[i]) == (present[i] ? val[i] : 0)); }
    }
    int64_t live = 0;
    for (int i = 0; i < M; i++) { assert(mojo_dict_contains_kw(m, keyv[i]) == present[i]); live += present[i]; }
    assert(m->used == live);
    mojo_dict_free(m);
}

static void test_dict_set_inline(void) {
    /* A stack MojoDict keeps its first table inside the struct and, with integer keys, allocates
     * nothing: no table, no key strings (the decimal is built only when read). */
    MojoDict d; mojo_dict_init(&d);
    assert(d.slots == d.inl && d.cap == MOJO_DICT_INLINE);
    for (int i = 0; i < 4; i++) mojo_dict_set_int_kw(&d, 100 + i, i);
    assert(d.slots == d.inl && d.used == 4);
    for (int i = 0; i < MOJO_DICT_INLINE; i++) assert(d.slots[i].key == NULL || d.slots[i].key == _ikey_lazy);
    /* reading keys as text materializes them, once, and they are then owned by the slot */
    MojoList *ks = mojo_dict_keys(&d);
    assert(ks->len == 4 && strcmp(mojo_list_get_str(ks, 0), "100") == 0 && strcmp(mojo_list_get_str(ks, 3), "103") == 0);
    mojo_list_free(ks);
    char *k0 = mojo_dict_slot_key(&d, 0); (void)k0;
    /* pop inside the inline table keeps the survivors and their order, and stays inline */
    assert(mojo_dict_pop_int_kw(&d, 101) == 1 && d.used == 3 && d.slots == d.inl);
    assert(mojo_dict_get_int_kw(&d, 100) == 0 && mojo_dict_get_int_kw(&d, 102) == 2 && mojo_dict_get_int_kw(&d, 103) == 3);
    /* a copy and an update read integer slots without text */
    MojoDict *cp = mojo_dict_copy(&d);
    assert(cp->used == 3 && mojo_dict_get_int_kw(cp, 102) == 2 && mojo_dict_contains(cp, "103"));
    /* the fifth key crosses the half-full mark: the table moves to the heap, entries intact */
    for (int i = 0; i < 6; i++) mojo_dict_set_int_kw(&d, 200 + i, i);
    assert(d.slots != d.inl && d.used == 9);
    for (int i = 0; i < 6; i++) assert(mojo_dict_get_int_kw(&d, 200 + i) == i);
    assert(mojo_dict_get_int_kw(&d, 100) == 0 && mojo_dict_get_int_kw(&d, 103) == 3);
    /* iteration hands back integers and their pairs */
    MojoDictIter *it = mojo_dict_iter_new(&d); int64_t sum = 0;
    while (mojo_dict_iter_next(it)) sum += mojo_dict_iter_key_int(it);
    mojo_dict_iter_free(it);
    assert(sum == 100 + 102 + 103 + 200 + 201 + 202 + 203 + 204 + 205);
    MojoList *pairs = mojo_dict_items_int(&d); assert(pairs->len == 9);
    MojoList *p0 = (MojoList *)(intptr_t)mojo_list_get_int(pairs, 0);
    assert(mojo_list_get_int(p0, 0) == 100 && mojo_list_get_int(p0, 1) == 0);
    mojo_list_free(pairs);
    mojo_dict_destroy(&d);
    mojo_dict_free(cp);
    /* string keys in an inline table, cleared and reused; a heap dict cleared after growth */
    for (int round = 0; round < 3; round++) {
        MojoDict e; mojo_dict_init(&e);
        mojo_dict_set_int(&e, "a", 1); mojo_dict_set_int(&e, "b", 2); mojo_dict_set_int(&e, "7", 3);
        assert(e.slots == e.inl && mojo_dict_get_int(&e, "b") == 2 && mojo_dict_get_int_kw(&e, 7) == 3);
        assert(mojo_dict_pop_int(&e, "a") == 1 && mojo_dict_pop_int(&e, "7") == 3 && mojo_dict_get_int(&e, "b") == 2);
        mojo_dict_clear(&e); assert(e.used == 0 && !mojo_dict_contains(&e, "b"));
        mojo_dict_set_int(&e, "c", 4); assert(mojo_dict_get_int(&e, "c") == 4);
        mojo_dict_destroy(&e);
    }
    /* the same for a set: ints and strings across the inline boundary, popped, grown, destroyed */
    MojoSet st; mojo_set_init(&st);
    assert(st.slots == st.inl && st.cap == MOJO_SET_INLINE);
    for (int i = 0; i < 4; i++) mojo_set_add_int(&st, i * 10);
    assert(st.slots == st.inl && st.used == 4);
    mojo_set_add_str(&st, "x"); mojo_set_add_str(&st, "y");
    for (int i = 4; i < 40; i++) mojo_set_add_int(&st, i * 10);
    assert(st.slots != st.inl && st.used == 42);
    for (int i = 0; i < 40; i++) assert(mojo_set_contains_int(&st, i * 10));
    assert(mojo_set_contains_str(&st, "x") && mojo_set_contains_str(&st, "y") && !mojo_set_contains_int(&st, 5));
    mojo_set_destroy(&st);
    for (int round = 0; round < 3; round++) {
        MojoSet t; mojo_set_init(&t);
        mojo_set_add_int(&t, 1); mojo_set_add_int(&t, 2);
        assert(t.slots == t.inl && mojo_set_contains_int(&t, 2));
        mojo_set_destroy(&t);
    }
}

int main(void) {
    test_ptrreg();
    test_kinds_table();
    test_list_inline();
    test_dict_and_itoa();
    test_dict_int_keys();
    test_dict_set_inline();
    printf("ok\n");
    return 0;
}
'''


def _flags():
    """`python3-config`'s include/link flags, MINUS the two that silently
    disable this test.

    `python3-config --cflags` on a Homebrew CPython 3.14 emits
    `-fno-strict-overflow -Wsign-compare -Wunreachable-code -fno-common
     -dynamic -DNDEBUG -g -O3 -Wall`. Two of those are load-bearing bugs for
    a harness whose entire verification IS its asserts:

      - `-DNDEBUG` compiles every `assert(...)` in the harness out of
        existence. The test then passed for every build, including a
        deliberately broken `_kinds_forget` (measured: the assert fires and
        aborts without it, and the test reported `PASS 3 passed` with it).
      - `-O3` comes AFTER the variant's own `-O0`/`-O2` on the command line
        and so overrode it, making the two optimisation-level variants the
        same build — the point of having them.

    Both are dropped here rather than worked around, and this is asserted
    below (`test_asserts_are_live`) so a future flag change cannot quietly
    re-disable the harness.
    """
    def cfg(*a):
        return subprocess.run(["python3-config", *a], capture_output=True, text=True).stdout.split()
    drop = ("-DNDEBUG", "-O3", "-O2", "-O1", "-O0", "-g")
    cflags = [f for f in cfg("--cflags") if f not in drop]
    ldflags = [f for f in cfg("--ldflags", "--embed") if f not in drop]
    return cflags, ldflags


# A build where the compiler dropped `-DNDEBUG` still prints "ok" and exits 0,
# because nothing in the harness can fail. This is the tripwire for that: it
# compiles a one-line program whose ONLY effect is to assert, and requires it
# to abort. A harness built with -DNDEBUG passes it vacuously.
ASSERT_LIVE_PROBE = r'''
#include <assert.h>
int main(void) { assert(0 && "NDEBUG is defined: every assert in this harness is a no-op"); return 0; }
'''


def _build_and_run(tmp, cc, opt, extra=()):
    exe = os.path.join(tmp, "harness_" + os.path.basename(cc) + opt.replace("-", "") + str(len(extra)))
    cflags, ldflags = _flags()
    cmd = [cc, opt, "-w", "-I", os.path.join(REPO, "runtime"), *cflags, *extra,
           os.path.join(tmp, "harness.c"), "-o", exe, "-lm", *ldflags]
    b = subprocess.run(cmd, capture_output=True, text=True)
    if b.returncode != 0:
        return None, b.stderr[-1500:]
    r = subprocess.run([exe], capture_output=True, text=True, timeout=300)
    return r, ""


def main():
    gcc = find_gcc()
    clang = shutil.which("clang")
    # (compiler, opt, extra flags, required). The sanitizer build uses clang:
    # the MacPorts gcc this project builds with ships no ASan runtime, Apple's
    # clang does. It is what catches `free()` of the inline buffer and any
    # out-of-range registry slot, which -O0/-O2 asserts alone cannot see.
    variants = [(gcc, "-O0", (), True), (gcc, "-O2", (), True)]
    if clang:
        variants.append((clang, "-O1", ("-g", "-fsanitize=address", "-fno-omit-frame-pointer"), False))
    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "harness.c"), "w") as f:
            f.write(HARNESS)
        # The assert tripwire first: if the flags ever compile the harness's
        # asserts out again, every variant below would report PASS and this
        # is the one line that says so.
        with open(os.path.join(tmp, "assert_probe.c"), "w") as f:
            f.write(ASSERT_LIVE_PROBE)
        cflags, ldflags = _flags()
        probe_exe = os.path.join(tmp, "assert_probe")
        pb = subprocess.run([gcc, "-O0", "-w", *cflags,
                             os.path.join(tmp, "assert_probe.c"), "-o", probe_exe],
                            capture_output=True, text=True)
        if pb.returncode != 0:
            print(f"FAIL  asserts are not live: the tripwire did not compile\n{pb.stderr[-1500:]}")
            failed += 1
        else:
            pr = subprocess.run([probe_exe], capture_output=True, text=True, timeout=60)
            if pr.returncode == 0:
                print("FAIL  asserts are not live: the harness's assert() calls are no-ops "
                      "(-DNDEBUG reached the command line; see _flags)")
                failed += 1
            else:
                print("PASS  asserts are live")
                passed += 1
        for cc, opt, extra, required in variants:
            label = " ".join((os.path.basename(cc), opt, *extra))
            r, err = _build_and_run(tmp, cc, opt, extra)
            if r is None:
                if not required:
                    print(f"SKIP  {label}: toolchain cannot build it "
                          f"({err.strip().splitlines()[-1] if err.strip() else 'no message'})")
                    continue
                print(f"FAIL  {label}: harness did not compile\n{err}")
                failed += 1
            elif r.returncode == 0 and r.stdout.strip() == "ok":
                print(f"PASS  {label}")
                passed += 1
            else:
                print(f"FAIL  {label}: exit {r.returncode}\n{r.stdout[-500:]}\n{r.stderr[-1500:]}")
                failed += 1
    print(f"Results: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
