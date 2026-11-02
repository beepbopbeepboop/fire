#!/usr/bin/env python3
"""test_runtime_cstr_region.py -- the C-string region helpers answer like
Python's slice, at every boundary the tokenizer's scans depend on.

`mojo_cstr_region_eq` (`s[start:stop] == needle` without the slice) and
`mojo_cstr_slice_n` / `mojo_cstr_region_eq_n` (the length-aware variants that
take the caller's known length) decide whether a region reaches the end of the
string, straddles the terminator, or is empty. The tokenizer's quote scans
(`fire_compiler.py::replace_multiline_strings`, `_scan_string_end`) are only
correct if those answers are right at exactly those edges, and nothing else
pinned them: the memchr rewrite of the scan (see the Status of
bugs/CODEGEN_selfhost_tokenize_region_eq_quadratic.md) changed how the length
is found, and this is the test that says the answers did not move.

The model is Python's own `e[start:stop] == needle`, where `e` is the string up
to its first NUL (a C string ends there). Only non-negative and small negative
bounds are generated: the omitted-stop sentinel is a separate convention and is
not what the scan uses.

Run with:  python3 test_runtime_cstr_region.py
"""

import itertools
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME_DIR = os.path.join(HERE, 'runtime')

HARNESS = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "fire_runtime.h"

/* One case per line: hex(s) hex(needle) start stop slen.  slen is the byte
 * length the caller would have passed to the _n variants; it is the C string's
 * own strlen, which is the only length the callers can know. */
static char *unhex(const char *h, size_t *n) {
    /* "-" is the empty string: an empty hex token cannot be read by %s. */
    if (h[0] == '-') { *n = 0; return calloc(1, 1); }
    size_t m = strlen(h) / 2;
    char *b = malloc(m + 1);
    for (size_t i = 0; i < m; i++) {
        unsigned v;
        sscanf(h + 2 * i, "%2x", &v);
        b[i] = (char)v;
    }
    b[m] = '\0';
    *n = m;
    return b;
}

int main(void) {
    char line[4096];
    while (fgets(line, sizeof line, stdin)) {
        char hs[2048], hn[2048];
        long long start, stop;
        if (sscanf(line, "%2047s %2047s %lld %lld", hs, hn, &start, &stop) != 4)
            return 2;
        size_t sn, nn;
        char *s = unhex(hs, &sn);
        char *needle = unhex(hn, &nn);
        int64_t slen = (int64_t)strlen(s);
        int a = mojo_cstr_region_eq(s, start, stop, needle);
        int b = mojo_cstr_region_eq_n(s, slen, start, stop, needle);
        char *sl = mojo_cstr_slice_n(s, slen, start, stop);
        /* slice_n's answer is the region's bytes; compare against needle the
         * way the region_eq contract does, so the three agree by construction. */
        int c = strcmp(sl, needle) == 0;
        printf("%d %d %d\n", a, b, c);
        free(sl);
        free(s);
        free(needle);
    }
    return 0;
}
'''


def _model(s: bytes, start: int, stop: int, needle: bytes) -> int:
    """Python's answer for `e[start:stop] == needle`, `e` = `s` up to its NUL."""
    e = s.split(b'\0', 1)[0]
    return int(e[start:stop] == needle)


def _cases(rng: random.Random):
    alphabet = b'ab\x00'
    strings = [b'', b'a', b'ab', b'abc', b'abcabc', b'a\x00bc', b'\x00']
    for _ in range(200):
        n = rng.randint(0, 9)
        strings.append(bytes(rng.choice(alphabet) for _ in range(n)))
    # A needle is a C string too, so it carries no NUL.
    needles = [b'', b'a', b'ab', b'abc', b'ba']
    bounds = range(-8, 13)
    for s in strings:
        for needle in needles:
            for start, stop in itertools.product(bounds, bounds):
                yield s, start, stop, needle


def main() -> int:
    rng = random.Random(0x2974)
    cases = list(_cases(rng))
    with tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR')) as td:
        harness_c = os.path.join(td, 'harness.c')
        harness_o = os.path.join(td, 'harness.o')
        runtime_o = os.path.join(td, 'fire_runtime.o')
        exe = os.path.join(td, 'harness')
        with open(harness_c, 'w') as f:
            f.write(HARNESS)
        subprocess.run(['cc', '-O0', '-c', os.path.join(RUNTIME_DIR, 'fire_runtime.c'),
                        '-I', RUNTIME_DIR, '-o', runtime_o], check=True,
                       stderr=subprocess.DEVNULL)
        subprocess.run(['cc', '-O0', '-c', harness_c, '-I', RUNTIME_DIR, '-o', harness_o],
                       check=True)
        subprocess.run(['cc', harness_o, runtime_o, '-o', exe], check=True)

        # An empty string or needle is spelled "-": the C side reads tokens with
        # %s, which cannot take an empty one.
        stdin = ''.join(
            f"{(s.hex() or '-')} {(needle.hex() or '-')} {start} {stop}\n"
            for s, start, stop, needle in cases)
        out = subprocess.run([exe], input=stdin, capture_output=True, text=True,
                             check=True).stdout.split('\n')
    failures = []
    for (s, start, stop, needle), line in zip(cases, out):
        a, b, c = (int(x) for x in line.split())
        want = _model(s, start, stop, needle)
        if (a, b, c) != (want, want, want):
            failures.append((s, start, stop, needle, (a, b, c), want))
    if failures:
        for s, start, stop, needle, got, want in failures[:10]:
            print(f"FAIL s={s!r} [{start}:{stop}] == {needle!r}: got {got}, want {want}")
        print(f"{len(failures)} of {len(cases)} cases disagree with Python's slice")
        return 1
    print(f"ok: {len(cases)} cases, region_eq / region_eq_n / slice_n agree with Python's slice")
    return 0


if __name__ == '__main__':
    sys.exit(main())
