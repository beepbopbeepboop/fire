#!/usr/bin/env python3
"""Runtime unit test for the two hot-path data structures the container
runtime is built on (doc/MEMORY.html sections 10 and 3.A):

  * `_PtrReg`, the pointer-membership table behind mojo_is_registered_list/
    dict/set, tuple and bound-method marking. Every container init/destroy
    pays one add and one discard, so it was rewritten from a general MojoSet
    into a dedicated open-addressing table with backward-shift deletion; this
    checks it against a reference model, including forced collisions and the
    LIFO add/remove of ONE address that a stack-homed container produces.
  * integer dict keys: canonical-decimal detection, int/string equivalence in both directions, strings that only
    look numeric staying separate, bytes keys staying separate, the `_kw` entry points against a reference model;
  * the Int-key path's fast itoa + block pool and the dict's resize (moves keys, keeps
    insertion order), which the Int-keyed dict benchmark depends on;
  * FLOAT dict keys: `mojo_str_from_double` is the second producer into that same block
    pool, so the rendered key must fit the block the pool hands out (the widest `%.17g`
    spelling is 24 chars, and an undersized block TRUNCATES rather than crashing, making
    such a float a key nothing else can find), whole numbers keep Python's ".0", signed
    zero stays a distinct key, a released key comes back out of the pool, and every float
    round-trips through a real dict;
  * the dict's and set's 8-slot inline first table and the integer key's lazy decimal string: a small stack
    dict/set allocates nothing, growth/pop/copy/iteration/keys stay correct across the boundary;
  * MojoList's 4-slot inline buffer: growth across the boundary, a stack
    struct that is init'd/destroyed repeatedly, and (under AddressSanitizer,
    when the toolchain has it) that destroy never frees the inline storage.

The harness `#include`s fire_runtime.c so it can reach the static `_pr_*`
functions; it is built and run at -O0 and -O2, because the runtime is shipped
at -O2 and an optimization-only bug is exactly what this must not miss.

Every case is written in `assert`, so the whole file is only a test if the
asserts are compiled in — and they were not. `python3-config --cflags` supplies
`-DNDEBUG`, which turned each `assert(...)` into `((void)0)`: every case body
vanished, nothing under test was ever CALLED, and the run printed "ok" and
exited 0. That held on every macOS checkout for as long as this file existed,
which is the failure mode no assertion inside the harness can catch, because
the thing missing is the assertions. `_flags` now strips the flag and
`_asserts_live` proves it at run time with a tripwire.

Turning the asserts on immediately found three things, all of which had been
sitting in this file unnoticed, plus one live runtime bug:

  * `d->used == 4` after popping 2 of 7 keys — the test's own constant was
    wrong; 5 survive.
  * the reference model's key set was not injective (`keyv[0] == keyv[3] == 0`),
    so the model tracked one dict key under two indices and desynchronised,
    presenting as a dict bug. Injectivity is now asserted.
  * 4294967296 in `test_dict_and_itoa`'s `vals[]` segfaulted: an int64 key in
    [2^31, 2^47) is misread as a `char *` and dereferenced. That is the runtime
    bug; it is not fixed, and it is its own group (`boxedstr`) so it is
    reported by name rather than taking the green groups down with it. See
    bugs/RUNTIME_int64_key_above_2gb_dereferenced_as_pointer.md.
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
#include <math.h>
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
     * 4294967296 was in this list and is NOT any more: it is the value that
     * exposed a live pre-existing crash, and it now lives in its own group
     * (`boxedstr`, see test_boxed_str_discrimination) so that this group stays
     * green and the crash is reported by name instead of taking the whole
     * harness down with it. `d[3000000000] = 1` segfaults. */
    int64_t vals[] = {0,1,-1,9,10,-10,99,100,12345,-98765,2147483647LL,-2147483648LL,
                      9223372036854775807LL, (int64_t)(-9223372036854775807LL-1)};
    for (unsigned i = 0; i < sizeof vals / sizeof *vals; i++) {
        char ref[32]; snprintf(ref, sizeof ref, "%lld", (long long)vals[i]);
        char *kept = mojo_str_from_int(vals[i]); assert(strcmp(kept, ref) == 0); free(kept);
        char *t = mojo_cstr_or_int_str(vals[i]); assert(strcmp(t, ref) == 0);
        mojo_cstr_or_int_release(vals[i], t);
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
    /* pop by int and by string; the rest survive, order kept.
     *
     * 7 keys went in -- "5", "7", "007", "+7", "-0", "abc", and the bytes key
     * "5" in its own domain -- so after popping "5" and "7" FIVE remain: "007",
     * "+7", "-0", "abc" and the bytes "5". This said 4, and the count was
     * never checked before 2026-09-30 because the whole harness's asserts were
     * compiled out by python3-config's -DNDEBUG (see _flags), so a stale
     * constant sat here unnoticed. */
    assert(mojo_dict_pop_int_kw(d, 5) == 51 && !mojo_dict_contains(d, "5") && !mojo_dict_contains_kw(d, 5));
    assert(mojo_dict_pop_int(d, "7") == 70 && !mojo_dict_contains_kw(d, 7));
    assert(mojo_dict_pop_int_kw(d, 12345) == 0);           /* absent */
    assert(mojo_dict_get_int(d, "007") == 1 && mojo_dict_get_bytes_int(d, b5) == 555 && d->used == 5);
    assert(mojo_dict_pop_int(d, "007") == 1 && d->used == 4);
    assert(mojo_dict_pop_int(d, "+7") == 2 && mojo_dict_pop_int(d, "-0") == 3 && d->used == 2);
    assert(mojo_dict_get_int(d, "abc") == 99 && mojo_dict_get_bytes_int(d, b5) == 555);
    mojo_dict_free(d);

    /* against a reference model: set/get/contains/pop/setdefault, negatives and extremes */
    enum { M = 3000 };
    static int64_t val[M]; static int present[M];
    int64_t keyv[M];
    /* `(i+1)`, not `i`: with `i` the i%7==0 arm computed -0*1000003 == 0 for
     * i==0, which is ALSO keyv[3] below, so two indices shared one dict key.
     * The model tracks presence per INDEX and the dict keys by VALUE, so the
     * two silently desynchronised and the comparison failed at round 752 with a
     * `contains(0)` disagreement that had nothing to do with the dict. Never
     * checked before 2026-09-30 (the asserts were compiled out; see _flags). */
    for (int i = 0; i < M; i++) keyv[i] = (i % 7 == 0) ? -((int64_t)i + 1) * 1000003
                                       : (i % 11 == 0) ? (int64_t)i * 4294967311LL : (int64_t)i;
    keyv[1] = INT64_MAX; keyv[2] = INT64_MIN + 1; keyv[3] = 0;
    /* the word test: keys that look like pointers would be read as strings, so keep them out of
     * the [2^31, 2^47) window the boxed-string test claims (a documented, pre-existing limit,
     * reported by name as the `boxedstr` group rather than worked around in silence) */
    for (int i = 0; i < M; i++) {
        uint64_t u = (uint64_t)keyv[i];
        if (u >= 0x80000000ULL && u < 0x0000800000000000ULL) keyv[i] = -(int64_t)i - 1;
    }
    /* The model indexes val[]/present[] by index and the dict keys by value, so
     * the key set MUST be injective. Check it rather than trusting the
     * generator: the duplicate this catches cost a full debugging round to
     * attribute, and it presented as a dict bug. */
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

static void test_dict_float_keys(void) {
    /* The OTHER producer into the transient pool. `mojo_str_from_double`
     * renders a float dict key and hands back a `_INT_STR_BLOCK`-sized block;
     * `mojo_cstr_or_int_release` is what returns it. The pool keeps its free
     * list link in a block's first 8 bytes and hands blocks out with no size of
     * its own, so these two MUST agree on one size -- which is the invariant
     * this exists to pin. It was broken for real: with `_INT_STR_BLOCK` at 24
     * the widest `%.17g` spelling ("-1.2345678901234567e-308", 24 chars + NUL)
     * did not fit, and because the render is a bounded `snprintf` it did not
     * crash -- it TRUNCATED, so such a float became a key no other spelling of
     * that float could find. */
    assert(_INT_STR_BLOCK >= 32);

    /* The spelling IS the key, so pin it: `%.17g`, plus the ".0" that
     * Python's str(float) keeps for a whole number. Every entry is chosen to
     * exercise one arm of that rule; `ref` is computed the same way, so this
     * checks the runtime's rule against itself at the widths, and the two
     * explicit strcmp()s below check the rule itself. */
    double vs[] = {0.0, -0.0, 1.0, -1.0, 0.5, 3.5, 1.0/3.0, 2.0/3.0,
                   123456.789, 123456789.0, 1234567890123456.0, 1e16, 1e17,
                   1e-4, 1e-5, 1e-300, 1e308,
                   -1.2345678901234567e-308,   /* 24 chars: the widest */
                   1.7976931348623157e308,      /* DBL_MAX, 23 chars */
                   2.2250738585072014e-308,     /* DBL_MIN, 23 chars */
                   4.9406564584124654e-324,     /* smallest subnormal */
                   9007199254740992.0};         /* 2^53: 16 chars, no dot */
    for (unsigned i = 0; i < sizeof vs / sizeof *vs; i++) {
        char ref[64];
        snprintf(ref, sizeof ref, "%.17g", vs[i]);
        size_t rn = strlen(ref);
        if (rn && !strpbrk(ref, ".eEnN")) { ref[rn] = '.'; ref[rn+1] = '0'; ref[rn+2] = 0; }
        char *k = mojo_str_from_double(vs[i]);
        assert(k != NULL);
        /* No truncation: the rendered text must be the FULL spelling. This is
         * the assertion that failed at 24 bytes. */
        assert(strcmp(k, ref) == 0);
        assert(strlen(k) + 1 <= _INT_STR_BLOCK);
        /* and it fits the block the pool will hand out, unwritten-past */
        memset(k + strlen(k) + 1, 0, _INT_STR_BLOCK - strlen(k) - 1);
        mojo_cstr_or_int_release(0, k);   /* orig=0: always released, as codegen records it */
    }
    /* the rule itself, spelled out */
    { char *k = mojo_str_from_double(1.0);   assert(strcmp(k, "1.0") == 0); mojo_cstr_or_int_release(0, k); }
    { char *k = mojo_str_from_double(0.5);   assert(strcmp(k, "0.5") == 0); mojo_cstr_or_int_release(0, k); }
    { char *k = mojo_str_from_double(1.0/3.0);
      assert(strcmp(k, "0.33333333333333331") == 0); mojo_cstr_or_int_release(0, k); }
    { char *k = mojo_str_from_double(-1.2345678901234567e-308);
      assert(strlen(k) == 24); assert(strcmp(k, "-1.2345678901234567e-308") == 0);
      mojo_cstr_or_int_release(0, k); }
    /* signed zero stays a DISTINCT key: numerically -0.0 == 0.0, so if the two
     * spellings collided, the two inserts would share a slot. */
    { char *z = mojo_str_from_double(0.0), *nz = mojo_str_from_double(-0.0);
      assert(strcmp(z, "0.0") == 0 && strcmp(nz, "-0.0") == 0 && strcmp(z, nz) != 0);
      mojo_cstr_or_int_release(0, z); mojo_cstr_or_int_release(0, nz); }

    /* The pool hands the released key back: a float-keyed access in a loop must
     * reuse one block, not malloc per access. This also pins that the block the
     * pool returns is still `_INT_STR_BLOCK` bytes -- under ASan a producer that
     * released a smaller block would be caught on the full-width write below. */
    char *first = mojo_str_from_double(0.5); mojo_cstr_or_int_release(0, first);
    for (int i = 0; i < 64; i++) {
        char *k = mojo_str_from_double(0.25 + (double)i);
        assert(k == first);
        memset(k, 'x', _INT_STR_BLOCK);          /* full-width: overrun if undersized */
        k[0] = '0'; k[1] = '.'; k[2] = '2'; k[3] = 0;
        mojo_cstr_or_int_release(0, k);
    }
    assert(_int_str_pool == first);

    /* End to end, through the dict the way the emitted code does: render the
     * key, use it once, release it. Every float must be findable by its own
     * spelling and must not be findable by any other's. */
    MojoDict *d = mojo_dict_new();
    double keys[] = {0.0, -0.0, 1.0, 0.5, 1.0/3.0, -1.2345678901234567e-308,
                     4.9406564584124654e-324, 1.7976931348623157e308};
    for (unsigned i = 0; i < sizeof keys / sizeof *keys; i++) {
        char *k = mojo_str_from_double(keys[i]);
        mojo_dict_set_int(d, k, (int64_t)i + 100);
        mojo_cstr_or_int_release(0, k);
    }
    for (unsigned i = 0; i < sizeof keys / sizeof *keys; i++) {
        char *k = mojo_str_from_double(keys[i]);
        assert(mojo_dict_get_int(d, k) == (int64_t)i + 100);
        mojo_cstr_or_int_release(0, k);
    }
    for (unsigned i = 0; i < sizeof keys / sizeof *keys; i++) {
        for (unsigned j = 0; j < sizeof keys / sizeof *keys; j++) {
            if (i == j) continue;
            char *k = mojo_str_from_double(keys[i]);
            assert(mojo_dict_get_int(d, k) != (int64_t)j + 100);
            mojo_cstr_or_int_release(0, k);
        }
    }
    /* an absent float is absent, and asking costs nothing but a pooled block */
    { char *k = mojo_str_from_double(12345.6789);
      assert(!mojo_dict_contains(d, k)); mojo_cstr_or_int_release(0, k); }
    mojo_dict_free(d);
    /* inf/nan spell like Python's and are not truncated either */
    { char *k = mojo_str_from_double(INFINITY);  assert(strcmp(k, "inf") == 0); mojo_cstr_or_int_release(0, k); }
    { char *k = mojo_str_from_double(-INFINITY); assert(strcmp(k, "-inf") == 0); mojo_cstr_or_int_release(0, k); }
    { char *k = mojo_str_from_double(NAN);       assert(strcmp(k, "nan") == 0); mojo_cstr_or_int_release(0, k); }
}

/* KNOWN FAILING -- run as `--group boxedstr`, registered as the
 * expect-marked `ptrreg-boxed-str` test. Asserts the behaviour that SHOULD
 * hold: an int64_t in the predicate's accepted range that is not a real
 * pointer must still be rendered as its decimal, not dereferenced. It does not
 * hold, and the failure is a SEGFAULT, not an assert: `_mojo_ptr_shaped`
 * accepts [2^31, 2^47) on shape alone, so 2^32 reads as a char* and
 * `mojo_cstr_or_int_str` hands it straight to strcmp. See
 * bugs/RUNTIME_int64_key_above_2gb_dereferenced_as_pointer.md.
 *
 * Kept as its own group rather than deleted: the case that finds a bug must
 * not be the case that gets removed, and a single group that is allowed to be
 * red is the only way to report this without either hiding it or marking the
 * eleven green groups expect= as well. */
static void test_boxed_str_discrimination(void) {
    /* every one of these is an ordinary integer a program may use as a key */
    int64_t big[] = {2147483648LL, 3000000000LL, 4294967296LL,
                     1099511627776LL, 70368744177664LL};
    for (unsigned i = 0; i < sizeof big / sizeof *big; i++) {
        char ref[32]; snprintf(ref, sizeof ref, "%lld", (long long)big[i]);
        /* NOT a string: must be its decimal, and must be pool-backed */
        assert(mojo_boxed_is_str(big[i]) == 0);
        char *t = mojo_cstr_or_int_str(big[i]);
        assert(strcmp(t, ref) == 0);
        mojo_cstr_or_int_release(big[i], t);
        /* and through a real dict, both directions */
        MojoDict *d = mojo_dict_new();
        char *k = mojo_cstr_or_int_str(big[i]);
        mojo_dict_set_int(d, k, 7);
        mojo_cstr_or_int_release(big[i], k);
        char *k2 = mojo_cstr_or_int_str(big[i]);
        assert(mojo_dict_get_int(d, k2) == 7);
        mojo_cstr_or_int_release(big[i], k2);
        mojo_dict_free(d);
    }
}

int main(int argc, char **argv) {
    const char *only = (argc > 1) ? argv[1] : NULL;
    int ran = 0;
#define GROUP(id, fn) if (!only || strcmp(only, id) == 0) { fn(); ran = 1; }
    GROUP("ptrreg", test_ptrreg)
    GROUP("list_inline", test_list_inline)
    GROUP("dict_and_itoa", test_dict_and_itoa)
    GROUP("dict_int_keys", test_dict_int_keys)
    GROUP("dict_set_inline", test_dict_set_inline)
    GROUP("dict_float_keys", test_dict_float_keys)
    GROUP("boxedstr", test_boxed_str_discrimination)
#undef GROUP
    if (!ran) { fprintf(stderr, "no such group: %s\n", only); return 2; }
    printf("ok\n");
    return 0;
}
'''


def _flags():
    def cfg(*a):
        return subprocess.run(["python3-config", *a], capture_output=True, text=True).stdout.split()
    cflags, ldflags = cfg("--cflags"), cfg("--ldflags", "--embed")
    # Drop -DNDEBUG. `python3-config --cflags` emits it, and this harness is
    # written entirely in `assert`, so on a stock macOS python the whole file
    # compiled to `((void)0)` per statement: every case body vanished, the
    # helpers under test were never CALLED, and the run printed "ok" and exited
    # 0. `ptrreg` had been reporting a green pass for a test that did not
    # execute, on every macOS checkout, for as long as it existed -- the
    # pointer-registry reference model, the Int-key itoa, the inline dict/set
    # and the block pool were all untested here. Nothing in the harness can
    # catch that on its own, because the failure mode is the ABSENCE of the
    # checks, so the fix is here: make sure they are compiled in, and assert it
    # by running the harness with a tripwire in `main` (see _asserts_live).
    assert_live = [f for f in cflags if f not in ("-DNDEBUG", "-O3")]
    return assert_live, ldflags


def _asserts_live(tmp, cc):
    """Prove the harness's `assert`s are actually compiled in.

    A test that silently compiles itself away is worse than no test: it reports
    PASS forever. Rather than trust the flag munging above, inject
    `assert(0 && ...)` into main and require a non-zero exit. If this ever
    returns "disabled" the whole harness is reporting nothing and `ptrreg`
    should fail loudly rather than pass.
    """
    src = os.path.join(tmp, "harness.c")
    with open(src) as f:
        body = f.read()
    trip = os.path.join(tmp, "tripwire.c")
    with open(trip, "w") as f:
        f.write(body.replace("int main(int argc, char **argv) {",
                             'int main(int argc, char **argv) { assert(0 && "tripwire");'))
    cflags, ldflags = _flags()
    exe = os.path.join(tmp, "tripwire")
    b = subprocess.run([cc, "-O0", "-w", "-I", os.path.join(REPO, "runtime"),
                        *cflags, trip, "-o", exe, "-lm", *ldflags],
                       capture_output=True, text=True)
    if b.returncode != 0:
        return "unbuildable: " + b.stderr[-300:]
    r = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    if r.returncode == 0:
        return ("disabled: the harness's asserts compiled out, so every case "
                "below is a no-op reporting PASS")
    return None


def _build_and_run(tmp, cc, opt, extra=(), group=None):
    tag = "trip" if group is None else group
    exe = os.path.join(tmp, f"harness_{tag}_" + os.path.basename(cc) + opt.replace("-", "") + str(len(extra)))
    cflags, ldflags = _flags()
    cmd = [cc, opt, "-w", "-I", os.path.join(REPO, "runtime"), *cflags, *extra,
           os.path.join(tmp, "harness.c"), "-o", exe, "-lm", *ldflags]
    b = subprocess.run(cmd, capture_output=True, text=True)
    if b.returncode != 0:
        return None, b.stderr[-1500:]
    argv = [exe] + ([group] if group else [])
    r = subprocess.run(argv, capture_output=True, text=True, timeout=300)
    return r, ""


# The harness's groups, and which of them the suite is allowed to see red.
# `boxedstr` is the only known-failing one and it is a SEPARATE registered test
# carrying an `expect=` with a reason and a bug-doc link, so a fix for it turns
# into a FAILURE of that marker (drop the marker) instead of a silent no-op.
GREEN_GROUPS = ("ptrreg", "list_inline", "dict_and_itoa", "dict_int_keys",
                "dict_set_inline", "dict_float_keys")
KNOWN_BAD_GROUPS = ("boxedstr",)


def main():
    # `--group NAME` runs exactly one group and is how the suite addresses a
    # single known-failing group, so the expect-marked test is a real
    # measurement of that group rather than of the whole harness.
    only = None
    if len(sys.argv) >= 3 and sys.argv[1] == "--group":
        only = sys.argv[2]
    if only is not None and only not in GREEN_GROUPS + KNOWN_BAD_GROUPS:
        print(f"FAIL  no such group: {only}\n  known: "
              f"{', '.join(GREEN_GROUPS + KNOWN_BAD_GROUPS)}")
        print("Results: 0 passed, 1 failed")
        return 1
    groups = (only,) if only else GREEN_GROUPS

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
        # First: are the asserts even in the binary? If not, every result below
        # is a lie and there is no point running them.
        bad = _asserts_live(tmp, gcc)
        if bad:
            print(f"FAIL  asserts: {bad}")
            print("Results: 0 passed, 1 failed")
            return 1
        print("PASS  asserts are compiled in (tripwire fired as required)")
        passed += 1
        for g in groups:
            for cc, opt, extra, required in variants:
                label = f"{g} [{' '.join((os.path.basename(cc), opt, *extra))}]"
                r, err = _build_and_run(tmp, cc, opt, extra, group=g)
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
