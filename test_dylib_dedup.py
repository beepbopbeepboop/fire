#!/usr/bin/env python3
"""The dylib's symbol-clash check (build_stdlib_dylib._defined_symbols) must count STRONG definitions and must not count
WEAK ones: a weak definition is merged by the linker, so every stdlib module carrying the same empty-GPU-sidecar stub
used to be reported as a clash and localized (noise on the screen, and a needless edit of each object).

Measured 2026-10-29: Apple clang's `nm -g` reports a Mach-O weak definition as a plain `T`; `nm -m` says `weak external`."""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_stdlib_dylib as B

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name)


with tempfile.TemporaryDirectory() as td:
    weak = os.path.join(td, 'weak.c'); strong = os.path.join(td, 'strong.c')
    open(weak, 'w').write('#include <stdint.h>\n__attribute__((weak)) int64_t gpu_stub(void) { return 0; }\n')
    open(strong, 'w').write('#include <stdint.h>\nint64_t strong_fn(void) { return 1; }\n')
    for src in (weak, strong):
        subprocess.run(['cc', '-c', src, '-o', src[:-2] + '.o'], check=True)
    w = B._defined_symbols('gcc', weak[:-2] + '.o')
    s = B._defined_symbols('gcc', strong[:-2] + '.o')
    check('a weak definition is not a clash', '_gpu_stub' not in w and '__gpu_stub' not in w)
    check('a strong definition is counted', any('strong_fn' in x for x in s))
    # The surface questions (export table, header-orphan check) need the weak
    # definition too: it is callable from the dylib whether or not it clashes.
    wa = B._defined_symbols('gcc', weak[:-2] + '.o', include_weak=True)
    check('include_weak counts a weak definition', any('gpu_stub' in x for x in wa))

print("%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
