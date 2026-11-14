#!/usr/bin/env python3
"""The runtime's word-kinded os.path entries, against CPython's posixpath.

`mojo_os_path_split_w` / `mojo_os_path_join_w` take a runtime WORD: a registered
bytes object is a bytes path and its parts are bytes; anything else is a str. And
`mojo_truthy_word` answers Python truthiness for a bytes word (length, not the
non-NULL test a pointer-shaped word would get). A small C harness is linked
against the real runtime/fire_runtime.c, and every line it prints must equal what
CPython's posixpath returns for the same inputs, with the kind of each part.

This is the infrastructure the compiled glob chain needs (see
bugs/CODEGEN_glob_bytes_pattern_returns_empty.md); it is not yet called by the
GIMPLE lowering of os.path.split/join.

Skipped (not failed) when no C compiler is available.
"""
import os
import posixpath
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

HARNESS = r'''
#include <stdio.h>
#include <string.h>
#include "fire_runtime.h"

static MojoBytes *B(const char *s) { return mojo_bytes_new_lit(s, (int64_t)strlen(s)); }

static void part(int64_t w) {
    if (mojo_is_registered_bytes(w)) {
        MojoBytes *b = (MojoBytes *)(intptr_t)w;
        printf("B'%.*s'", (int)b->len, (char *)b->data);
    } else {
        printf("S'%s'", (char *)(intptr_t)w);
    }
}

static void split_bytes(const char *in) {
    MojoList *l = mojo_os_path_split_w((int64_t)(intptr_t)B(in));
    printf("split B'%s' -> ", in);
    part(mojo_list_get_int(l, 0)); printf(" ");
    part(mojo_list_get_int(l, 1)); printf("\n");
}

static void split_str(const char *in) {
    MojoList *l = mojo_os_path_split_w((int64_t)(intptr_t)in);
    printf("split S'%s' -> ", in);
    part(mojo_list_get_int(l, 0)); printf(" ");
    part(mojo_list_get_int(l, 1)); printf("\n");
}

static void join_bytes(const char *a, const char *b) {
    int64_t r = mojo_os_path_join_w((int64_t)(intptr_t)B(a), (int64_t)(intptr_t)B(b));
    printf("join B'%s' B'%s' -> ", a, b);
    part(r); printf("\n");
}

static void join_str(const char *a, const char *b) {
    int64_t r = mojo_os_path_join_w((int64_t)(intptr_t)a, (int64_t)(intptr_t)b);
    printf("join S'%s' S'%s' -> ", a, b);
    part(r); printf("\n");
}

static void truth(const char *s) {
    printf("truthy B'%s' -> %d\n", s, mojo_truthy_word((int64_t)(intptr_t)B(s)));
}

int main(void) {
    static const char *splits[] = {"a/b.py", "*.py", "/x", "a//b", "a/", "//", ""};
    for (size_t i = 0; i < sizeof splits / sizeof splits[0]; i++) split_bytes(splits[i]);
    split_str("a/b.py");
    split_str("*.py");

    join_bytes("/tmp", "x");
    join_bytes("a", "b");
    join_bytes("a/", "b");
    join_bytes("", "x");
    join_bytes("a", "/abs");
    join_bytes("", "");
    join_str("a", "b");

    truth("");
    truth("x");
    return 0;
}
'''


def expected_lines():
    """The same lines, from CPython's posixpath (the reference for every case)."""
    def part(v):
        if isinstance(v, bytes):
            return "B'%s'" % v.decode()
        return "S'%s'" % v

    out = []
    for s in ("a/b.py", "*.py", "/x", "a//b", "a/", "//", ""):
        h, t = posixpath.split(s.encode())
        out.append("split B'%s' -> %s %s" % (s, part(h), part(t)))
    for s in ("a/b.py", "*.py"):
        h, t = posixpath.split(s)
        out.append("split S'%s' -> %s %s" % (s, part(h), part(t)))
    for a, b in (("/tmp", "x"), ("a", "b"), ("a/", "b"), ("", "x"), ("a", "/abs"), ("", "")):
        out.append("join B'%s' B'%s' -> %s" % (a, b, part(posixpath.join(a.encode(), b.encode()))))
    out.append("join S'a' S'b' -> %s" % part(posixpath.join("a", "b")))
    for s in ("", "x"):
        out.append("truthy B'%s' -> %d" % (s, 1 if s.encode() else 0))
    return out


def main():
    cc = shutil.which('cc') or shutil.which('gcc') or shutil.which('clang')
    if cc is None:
        print('SKIP path word runtime: no C compiler on PATH')
        return 0
    work = tempfile.mkdtemp(prefix='path_word_rt_')
    src = os.path.join(work, 'harness.c')
    with open(src, 'w') as fh:
        fh.write(HARNESS)
    exe = os.path.join(work, 'harness')
    build = subprocess.run(
        [cc, '-std=c11', '-O0', '-I', os.path.join(HERE, 'runtime'), src,
         os.path.join(HERE, 'runtime', 'fire_runtime.c'), '-lm', '-o', exe],
        capture_output=True, text=True)
    if build.returncode != 0 or not os.path.exists(exe):
        print('FAIL the harness does not build against runtime/fire_runtime.c\n' + build.stderr[-2000:])
        return 1
    run = subprocess.run([exe], capture_output=True, text=True)
    if run.returncode != 0:
        print('FAIL the harness exits %d\n%s' % (run.returncode, run.stderr[-800:]))
        return 1
    want = expected_lines()
    got = run.stdout.splitlines()
    if got != want:
        print('FAIL word-kinded os.path differs from CPython posixpath')
        for w, g in zip(want, got):
            mark = '  ' if w == g else '!!'
            print('%s want %s\n   %s got  %s' % (mark, w, mark, g))
        if len(want) != len(got):
            print('line counts differ: want %d got %d' % (len(want), len(got)))
        return 1
    print('PASS word-kinded os.path split/join and bytes truthiness match CPython posixpath (%d lines)' % len(got))
    return 0


if __name__ == '__main__':
    sys.exit(main())
