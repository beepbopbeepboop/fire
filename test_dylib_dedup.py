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
    ref = os.path.join(td, 'ref.c'); ref2 = os.path.join(td, 'ref2.c')
    open(weak, 'w').write('#include <stdint.h>\n__attribute__((weak)) int64_t gpu_stub(void) { return 0; }\n')
    open(strong, 'w').write('#include <stdint.h>\nint64_t strong_fn(void) { return 1; }\n')
    # An object that only REFERENCES a symbol outside it. This is the shape
    # every stdlib module has for the runtime and its imports; counting those
    # references as definitions made almost every pair of modules "clash"
    # (the 150-module symbol-collision exclusion).
    open(ref, 'w').write('#include <stdint.h>\n'
                         'extern int64_t undefined_ref(void);\n'
                         'int64_t shared_fn(void) { return 3; }\n'
                         'int64_t unique_fn(void) { return 4; }\n'
                         'int64_t caller(void) { return undefined_ref(); }\n')
    # A second module with its own definitions that merely imports the SAME
    # name: this is the real shape of the 150-module report, where every module
    # "defined" the libc/runtime symbols it imports and so clashed with every
    # other module that imported them.
    open(ref2, 'w').write('#include <stdint.h>\n'
                          'extern int64_t undefined_ref(void);\n'
                          'int64_t other_fn(void) { return undefined_ref(); }\n')
    for src in (weak, strong, ref, ref2):
        subprocess.run(['cc', '-c', src, '-o', src[:-2] + '.o'], check=True)
    w = B._defined_symbols('gcc', weak[:-2] + '.o')
    s = B._defined_symbols('gcc', strong[:-2] + '.o')
    r = B._defined_symbols('gcc', ref[:-2] + '.o')
    r2 = B._defined_symbols('gcc', ref2[:-2] + '.o')
    check('modules that share only an imported symbol do not clash', not (r & r2))
    check('a weak definition is not a clash', '_gpu_stub' not in w and '__gpu_stub' not in w)
    check('a strong definition is counted', any('strong_fn' in x for x in s))
    check('an undefined reference is not a definition', not any('undefined_ref' in x for x in r))
    # include_weak=True asks the SURFACE question (does this object define the
    # symbol it advertises?); an undefined reference is not a definition there
    # either, or the export table claims symbols nobody in the dylib defines.
    rw = B._defined_symbols('gcc', ref[:-2] + '.o', include_weak=True)
    check('an undefined reference is not a definition (include_weak)',
          not any('undefined_ref' in x for x in rw))
    # ... and localizing a real clash in an object that also has undefined
    # references must still succeed: the keep list nmedit sees is built from
    # the same function, so an undefined name in it is a tool error and the
    # caller silently drops the module.
    clash = {x for x in r if 'shared_fn' in x}
    edited = B._localize_symbols(ref[:-2] + '.o', clash, td, 'ref')
    check('a clash is localizable beside undefined references', bool(edited))
    if edited:
        check('localizing keeps the other definitions',
              any('unique_fn' in x for x in B._defined_symbols('gcc', edited)))
    # The surface questions (export table, header-orphan check) need the weak
    # definition too: it is callable from the dylib whether or not it clashes.
    wa = B._defined_symbols('gcc', weak[:-2] + '.o', include_weak=True)
    check('include_weak counts a weak definition', any('gpu_stub' in x for x in wa))

print("%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
