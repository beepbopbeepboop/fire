#!/usr/bin/env python3
"""Runtime unit test for the two hot-path data structures the container
runtime is built on (doc/MEMORY.html sections 10 and 3.A):

  * `_PtrReg`, the pointer-membership table behind mojo_is_registered_list/
    dict/set, tuple and bound-method marking. Every container init/destroy
    pays one add and one discard, so it was rewritten from a general MojoSet
    into a dedicated open-addressing table with backward-shift deletion; this
    checks it against a reference model, including forced collisions and the
    LIFO add/remove of ONE address that a stack-homed container produces.
  * the Int-key path's fast itoa + block pool and the dict's resize (moves keys, keeps
    insertion order), which the Int-keyed dict benchmark depends on;
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
     * is a pool block and is the only thing mojo_cstr_or_int_release accepts. */
    int64_t vals[] = {0,1,-1,9,10,-10,99,100,12345,-98765,2147483647LL,-2147483648LL,4294967296LL,
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

int main(void) {
    test_ptrreg();
    test_list_inline();
    test_dict_and_itoa();
    printf("ok\n");
    return 0;
}
'''


def _flags():
    def cfg(*a):
        return subprocess.run(["python3-config", *a], capture_output=True, text=True).stdout.split()
    return cfg("--cflags"), cfg("--ldflags", "--embed")


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
