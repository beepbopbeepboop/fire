#!/usr/bin/env python3
"""An OVERLOADED imported stdlib function keeps the variadic signature its
export record publishes; a non-overloaded one keeps its concrete parameters.

Pinning test for the `stdlib-dylib` unexpected-skip class (the from-scratch
stdlib dylib job). `module_loader`'s export scan cannot represent
several same-name signatures in its single-signature model, so it publishes an
overloaded function as a variadic extern (`ret name (...)` with
`c_parameters: []`). One importer rebuild instead reconstructed every extern
from `c_parameters` alone, turning that into `(void)`; `sleep(x)` in
`std/testing/assert_aborts.mojo` then failed to compile and the module
silently fell back to source — a NEW dylib skip. The fix is that the export
record's `signature` text is what the importer emits, never a rebuild from an
empty `c_parameters` list.

What this pins:

  1. the export record: `std.time.sleep` (overloaded — `Float64` and `Int`)
     is published as `variadic` with a `(...)` signature, while
     `_unicode.is_lowercase` (one definition) is not, so this test cannot
     pass by having the scan call everything variadic;
  2. a synthetic importer's generated C declares the imported symbol `(...)`
     and never `(void)`, and calls it through that name; and
  3. the real module the skip was reported for,
     `std/testing/assert_aborts.mojo`, compiles and carries the same
     variadic extern.

Run:  python3 test_stdlib_import_extern_variadic.py
No dylib is built and nothing is linked: three single-module compiles.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from module_loader import STDLIB_PATH, load_module  # noqa: E402
import build_stdlib_dylib as b  # noqa: E402

# The symbol the importer emits for `from std.time import sleep`. The bare
# name is overloaded in std/time/time.mojo (`sleep(sec: Float64)` at line 291
# and `sleep(sec: Int)` at 369), so the scan marks it variadic.
SLEEP_SYM = 'std_time___init___sleep'


def _compile(src, path, name):
    return b.compile_module_to_c(src, path, name, linkable=False)


def _extern_decls(c, sym):
    """The `extern` declaration lines naming `sym` (not its call sites)."""
    pat = re.compile(r'\b' + re.escape(sym) + r'\s*\(')
    return [l for l in c.splitlines() if 'extern' in l and pat.search(l)]


def _is_variadic(decl, sym):
    return re.search(r'\b' + re.escape(sym) + r'\s*\(\s*\.\.\.\s*\)', decl) is not None


def _is_void(decl, sym):
    return re.search(r'\b' + re.escape(sym) + r'\s*\(\s*void\s*\)', decl) is not None


def main():
    failures = []

    def check(what, ok, detail=''):
        if not ok:
            failures.append('%s: %s' % (what, detail))

    # 1. The export record is the evidence the importer reads.
    sleep = (load_module('std.time') or {}).get('sleep') or {}
    check('export record: std.time.sleep is published variadic',
          bool(sleep.get('variadic')), repr(sleep))
    check('export record: std.time.sleep publishes a (...) signature',
          re.search(r'\bsleep\s*\(\s*\.\.\.\s*\)\s*$',
                    str(sleep.get('signature') or '').strip()) is not None,
          repr(sleep.get('signature')))
    check('export record: std.time.sleep has no concrete c_parameters '
          '(that is why the signature text is the only source)',
          sleep.get('c_parameters') == [], repr(sleep.get('c_parameters')))

    # Negative control: a single-definition function is NOT variadic, so the
    # assertions above cannot pass by making every import variadic.
    concrete = (load_module('std.collections.string._unicode') or {}).get(
        'is_lowercase') or {}
    check('control: _unicode.is_lowercase is not variadic',
          not concrete.get('variadic'), repr(concrete))
    check('control: _unicode.is_lowercase keeps its concrete parameter',
          concrete.get('c_parameters') == ['Span * s'],
          repr(concrete.get('c_parameters')))

    # 2. A synthetic importer of the overloaded function.
    synthetic = _compile(
        'from std.time import sleep\n'
        '\n'
        'def f(x: Int) -> Int:\n'
        '    sleep(x)\n'
        '    return 0\n',
        os.path.join(HERE, 'stdlib_variadic_probe.mojo'),
        'stdlib_variadic_probe')
    decls = _extern_decls(synthetic, SLEEP_SYM)
    check('synthetic importer declares %s' % SLEEP_SYM, bool(decls),
          'no extern declaration in its C')
    check('synthetic importer: every extern is variadic',
          bool(decls) and all(_is_variadic(d, SLEEP_SYM) for d in decls),
          '\n'.join(decls))
    check('synthetic importer: no (void) prototype',
          not any(_is_void(d, SLEEP_SYM) for d in decls),
          '\n'.join(decls))

    # 3. The real module the unexpected skip named.
    rel = 'std/testing/assert_aborts.mojo'
    path = os.path.join(STDLIB_PATH, rel)
    with open(path) as f:
        src = f.read()
    real = _compile(src, path, b._module_name_for(path))
    decls = _extern_decls(real, SLEEP_SYM)
    check('%s declares %s' % (rel, SLEEP_SYM), bool(decls),
          'module compiled but emits no sleep extern')
    check('%s: every extern is variadic' % rel,
          bool(decls) and all(_is_variadic(d, SLEEP_SYM) for d in decls),
          '\n'.join(decls))
    check('%s: no (void) prototype' % rel,
          not any(_is_void(d, SLEEP_SYM) for d in decls),
          '\n'.join(decls))

    if failures:
        for f in failures:
            print('FAIL ' + f)
        return 1
    print('PASS stdlib_import_extern_variadic: the overloaded std.time.sleep '
          'keeps its (...) export signature in the synthetic importer and in '
          'std/testing/assert_aborts.mojo (never (void)), while the '
          'single-definition _unicode.is_lowercase stays non-variadic')
    return 0


if __name__ == '__main__':
    sys.exit(main())
