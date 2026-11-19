#!/usr/bin/env python3
"""An OVERLOADED imported stdlib function is never declared `(void)`, and its
importer calls the overload the call site chose.

Pinning test for the `stdlib-dylib` unexpected-skip class (the from-scratch
stdlib dylib job). `module_loader`'s export scan cannot represent several
same-name signatures in its single-signature model, so it publishes an
overloaded function as variadic (`int64_t sleep (...)`, `c_parameters: []`).
An importer that rebuilt its extern from that empty list would emit
`(void)`, and `sleep(x)` in `std/testing/assert_aborts.mojo` would then fail
to compile, silently falling back to source: a NEW dylib skip.

The importer now resolves the overload at the call site: `sleep(x)` with an
`Int` names the `Int` overload's own symbol (the overload-suffixed name), and
declares it with that overload's concrete parameter. What this pins:

  1. the export record: `std.time.sleep` (overloaded: `Float64` and `Int`) is
     published `variadic` with a `(...)` signature, while
     `_unicode.is_lowercase` (one definition) is not, so the check cannot pass
     by making every import variadic;
  2. a synthetic importer's generated C declares the `Int` overload with a
     concrete `int64_t` parameter, never `(void)`, and calls that same name;
  3. the real module the skip was reported for,
     `std/testing/assert_aborts.mojo`, compiles and declares the same
     overload the same way.

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

# The bare name `sleep` is overloaded in std/time/time.mojo (`sleep(sec:
# Float64)` and `sleep(sec: Int)`). The importer emits each overload under its
# own overload-suffixed symbol, so the pin matches on the stable prefix.
SLEEP_PREFIX = 'std_time_time_sleep_'


def _compile(src, path, name):
    return b.compile_module_to_c(src, path, name, linkable=False)


def _extern_decls(c, prefix):
    """The `extern` declaration lines naming an overload of `prefix` (not its
    call sites)."""
    pat = re.compile(r'\b' + re.escape(prefix) + r'[0-9a-f]+\s*\(')
    return [l for l in c.splitlines() if 'extern' in l and pat.search(l)]


def _is_void(decl):
    return re.search(r'\(\s*void\s*\)', decl) is not None


def _is_int_overload(decl):
    """The `Int` overload takes one `int64_t` and nothing else."""
    return re.search(r'\(\s*int64_t\s*\)\s*;', decl) is not None


def _called_name(c, prefix):
    """The overload-suffixed name the body calls (the declared symbol)."""
    m = re.search(r'\b(' + re.escape(prefix) + r'[0-9a-f]+)\s*\(', c)
    return m.group(1) if m else None


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
          '(that is why the call site, not the record, picks the overload)',
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

    # 2. A synthetic importer calling the `Int` overload.
    synthetic = _compile(
        'from std.time import sleep\n'
        '\n'
        'def f(x: Int) -> Int:\n'
        '    sleep(x)\n'
        '    return 0\n',
        os.path.join(HERE, 'stdlib_variadic_probe.mojo'),
        'stdlib_variadic_probe')
    decls = _extern_decls(synthetic, SLEEP_PREFIX)
    check('synthetic importer declares a %s overload' % SLEEP_PREFIX,
          bool(decls), 'no extern declaration in its C')
    check('synthetic importer: no (void) prototype',
          not any(_is_void(d) for d in decls), '\n'.join(decls))
    check('synthetic importer: the Int overload is declared (int64_t)',
          any(_is_int_overload(d) for d in decls), '\n'.join(decls))
    called = _called_name(synthetic, SLEEP_PREFIX)
    declared = {re.search(r'\b(' + re.escape(SLEEP_PREFIX) + r'[0-9a-f]+)\s*\(',
                          d).group(1) for d in decls if re.search(
                              r'\b' + re.escape(SLEEP_PREFIX) + r'[0-9a-f]+\s*\(', d)}
    check('synthetic importer: the call names a declared overload',
          called is not None and called in declared,
          'called=%r declared=%r' % (called, sorted(declared)))

    # 3. The real module the unexpected skip named.
    rel = 'std/testing/assert_aborts.mojo'
    path = os.path.join(STDLIB_PATH, rel)
    with open(path) as f:
        src = f.read()
    real = _compile(src, path, b._module_name_for(path))
    decls = _extern_decls(real, SLEEP_PREFIX)
    check('%s declares a %s overload' % (rel, SLEEP_PREFIX), bool(decls),
          'module compiled but emits no sleep extern')
    check('%s: no (void) prototype' % rel,
          not any(_is_void(d) for d in decls), '\n'.join(decls))
    check('%s: the Int overload is declared (int64_t)' % rel,
          any(_is_int_overload(d) for d in decls), '\n'.join(decls))

    if failures:
        for f in failures:
            print('FAIL ' + f)
        return 1
    print('PASS stdlib_import_extern_variadic: the overloaded std.time.sleep '
          'keeps its (...) export record, its importers declare the Int '
          'overload concretely (never (void)) and call that same symbol, '
          'including in std/testing/assert_aborts.mojo, while the '
          'single-definition _unicode.is_lowercase stays non-variadic')
    return 0


if __name__ == '__main__':
    sys.exit(main())
