#!/usr/bin/env python3
"""A cross-module free-function CALL must name the symbol its DEFINITION emits.

Regression for the `stdlib-dylib` red (`bugs/gate-stdlib-dylib.md`): a
stdlib module compiled ALONE (as `build_stdlib_dylib.build` does, one worker
process per module) resolves an imported function's parameter ctypes from
`module_loader.py`'s export text scan, while the defining module emits them
from the codegen's own `_signature_ctypes`. The two disagreed for every
string-wrapper parameter, because the scan boxed `Span`/`StringSlice` to
`int64_t *` to avoid naming a `Span` typedef the importing TU "might not
have" — every generated TU now carries `typedef struct Span Span;`, and the
box hashed a DIFFERENT `overload_suffix_for` than the definition:

    string_span.mojo calls   std_collections_string__unicode_is_lowercase_55072c (int64_t * s)
    _unicode.mojo defines    std_collections_string__unicode_is_lowercase_fa3cf4 (Span * s)

so the dylib ships a reference no translation unit defines, and every client
aborts at load with dyld's "symbol not found". The bare spelling is the same
bug in its other shape: `_atof(x: StringSlice)` is emitted with `char *`
(`d719e0`) and was called with `int64_t *` (`55072c`).

What this test pins, in one place:

  1. the generated C: every `_unicode` function `string_span` calls is named
     with the SAME full symbol (including the 6-hex overload suffix) the
     defining module emits, for the four StringSlice[_] functions the red
     named; and
  2. the export record the importer reads: `is_lowercase`'s parameter is
     `Span *` (the fat pointer `_mojo_type` gives a bracketed StringSlice)
     and `_atof`'s is `char *` (a bare StringSlice parameter), never the
     `int64_t *` box.

Run:  python3 test_stdlib_import_suffix.py
It is RED before the fix (four suffix mismatches) and GREEN after. No
stdlib dylib build is involved: two single-module compiles, ~5 s total.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
sys.path.insert(0, ROOT)

from module_loader import STDLIB_PATH, load_module  # noqa: E402
import build_stdlib_dylib as b  # noqa: E402

# The four functions the gate red named, all `def f(s: StringSlice[_])`.
SLICE_FUNCS = ('is_lowercase', 'is_uppercase', 'to_lowercase', 'to_uppercase')


def _compile(rel):
    """The generated C of one stdlib module, compiled exactly as the dylib
    build compiles it (its own module identity, no entry points)."""
    path = os.path.join(STDLIB_PATH, rel)
    with open(path) as f:
        src = f.read()
    name = b._module_name_for(path)
    return b.compile_module_to_c(src, path, name, linkable=False)


def _base(sym):
    """A `_std_..._<6 hex>` symbol without its overload suffix."""
    return re.sub(r'_[0-9a-f]{6}$', '', sym)


def _defs(c, prefix):
    """`{base: full symbol}` for the definitions this module's C emits under
    `prefix`. A definition is the one occurrence followed by `(...)\n{`; its
    forward declaration ends in `;` and its call sites are not at column 0."""
    out = {}
    for m in re.finditer(r'\n[^\n;]*?\b(' + re.escape(prefix) + r'\w+)'
                         r'\s*\([^;]*\)\s*\n\{', c):
        sym = m.group(1)
        out.setdefault(_base(sym), sym)
    return out


def _refs(c, prefix):
    """Every occurrence of a `prefix...` symbol in `c`, full name."""
    return set(re.findall(r'\b(' + re.escape(prefix) + r'\w+)\b', c))


def main():
    failures = []

    def check(what, ok, detail=''):
        if not ok:
            failures.append('%s: %s' % (what, detail))

    defined = _defs(_compile('std/collections/string/_unicode.mojo'),
                    'std_collections_string__unicode_')
    importer_c = _compile('std/collections/string/string_span.mojo')
    referenced = _refs(importer_c, 'std_collections_string__unicode_')

    # 1. The generated call names must agree with the emitted definition, for
    #    every `_unicode` function this importer references. Guarded on the
    #    four measured functions so the assertion cannot pass vacuously if a
    #    later stdlib edit drops the calls.
    for fn in SLICE_FUNCS:
        base = 'std_collections_string__unicode_' + fn
        check('%s is defined by _unicode.mojo' % fn, base in defined)
        called = sorted(s for s in referenced if _base(s) == base)
        check('%s is called by string_span.mojo' % fn, bool(called),
              'no %s* reference in its C' % base)
        if called and base in defined:
            check('%s: call names the definition\'s symbol' % fn,
                  called == [defined[base]],
                  'call %r vs definition %r' % (called, defined[base]))

    # Every other referenced _unicode function must also name a definition
    # (`_unicode` is the only definer in the dylib), which is the same rule
    # stated generally rather than for the four names.
    for sym in sorted(referenced):
        if _base(sym) in defined:
            check('%s: reference matches a definition' % sym,
                  defined[_base(sym)] == sym,
                  'definition is %r' % defined[_base(sym)])

    # 2. The export record the importer reads. `Span *` for a bracketed
    #    StringSlice, `char *` for the bare one: the ctypes the defining
    #    module's `_signature_ctypes` uses, hence the same overload suffix.
    unicode_exports = load_module('std.collections.string._unicode')
    check('export record: is_lowercase takes Span *',
          (unicode_exports.get('is_lowercase') or {}).get('c_parameters')
          == ['Span * s'],
          str((unicode_exports.get('is_lowercase') or {}).get('c_parameters')))
    float_exports = load_module(
        'std.collections.string._parsing_numbers.parsing_floats')
    check('export record: _atof takes char *',
          (float_exports.get('_atof') or {}).get('c_parameters')
          == ['char * x'],
          str((float_exports.get('_atof') or {}).get('c_parameters')))

    if failures:
        for f in failures:
            print('FAIL ' + f)
        return 1
    print('PASS stdlib_import_suffix: string_span names the four _unicode '
          'StringSlice[_] definitions with their own symbols, and the export '
          'record resolves Span * / char * (not the int64_t * box)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
