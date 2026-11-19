#!/usr/bin/env python3
"""A cross-module free-function CALL must name the symbol its DEFINITION emits.

Regression for the `stdlib-dylib` red (`bugs/mid/gate-stdlib-dylib.md`): a
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

  1. the generated C: every function the importers below call is named with
     the SAME full symbol (including the 6-hex overload suffix) as the
     defining module's emitted definition — the four `StringSlice[_]`
     functions `_unicode` defines plus, for the rest of the part-6 acceptance,
     `_utf8._count_utf8_continuation_bytes` and
     `_amdgpu.printf_append_string_n` (a bracketed `Span` parameter); and
  2. the export record the importer reads: `is_lowercase`'s parameter is
     `Span *` (the fat pointer `_mojo_type` gives a bracketed StringSlice),
     `_atof`'s is `char *` (a bare StringSlice parameter), and the two extra
     span-parameter functions resolve to `Span *` too — never the
     `int64_t *` box; and
  3. the THIRD reader of the same rule, `reflect.py`'s per-parameter `_mt`
     used by `_func_export_csym`: a synthetic module's `StringSlice[_]` and
     bare `StringSlice` parameters must hash the symbol its own codegen
     emits (`Span *` -> same suffix; bare -> `char *`, not `int64_t`).

Run:  python3 test_stdlib_import_suffix.py
It is RED before the fix (the call/definition suffix pairs, the export-record
ctypes and the reflection pin) and GREEN after. No stdlib dylib build is
involved: one single-module compile per stdlib module plus two synthetic
compiles, ~5 s total.
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

# (importer, definer, symbol prefix, functions the importer is KNOWN to call).
# The required list guards each pair's assertions from passing vacuously if a
# later stdlib edit drops the calls.
PAIRS = (
    ('std/collections/string/string_span.mojo',
     'std/collections/string/_unicode.mojo',
     'std_collections_string__unicode_', SLICE_FUNCS),
    ('std/collections/string/string_span.mojo',
     'std/collections/string/_utf8.mojo',
     'std_collections_string__utf8_', ('_count_utf8_continuation_bytes',)),
    ('std/builtin/debug_assert.mojo',
     'std/sys/_amdgpu.mojo',
     'std_sys__amdgpu_', ('printf_append_string_n',)),
)


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
    `prefix`. A definition is the one occurrence followed by `(...)\\n{`; its
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


def _check_calls_agree(check, importer, definer, prefix, required):
    """Every reference the importer makes under `prefix` that has a definition
    must spell that definition's symbol exactly."""
    defined = _defs(_compile(definer), prefix)
    referenced = _refs(_compile(importer), prefix)

    for fn in required:
        base = prefix + fn
        check('%s is defined by %s' % (fn, definer), base in defined)
        called = sorted(s for s in referenced if _base(s) == base)
        check('%s is called by %s' % (fn, importer), bool(called),
              'no %s* reference in its C' % base)
        if called and base in defined:
            check('%s: call names the definition\'s symbol' % fn,
                  called == [defined[base]],
                  'call %r vs definition %r' % (called, defined[base]))

    # Every other referenced function must also name a definition (the
    # definer is the only one in the dylib), which is the same rule stated
    # generally rather than for the required names.
    for sym in sorted(referenced):
        if _base(sym) in defined:
            check('%s: reference matches a definition' % sym,
                  defined[_base(sym)] == sym,
                  'definition is %r' % defined[_base(sym)])


def _check_reflect_agrees(check, ann, fn):
    """The reflection table's advertised symbol for a `def fn(p: ann)` must be
    the one the module's own codegen emits. `reflect._func_export_csym` hashes
    its `_param_mt` answer, so this pins the third reader of the parameter
    rule."""
    from fire_compiler import Parser, py_tokenize
    from gimple_codegen import GimpleGen
    import reflect

    src = 'def %s(p: %s) -> Int:\n    return 0\n' % (fn, ann)
    gen = GimpleGen(emit_entry_points=False, module_name='param_rule_probe')
    emitted = set(re.findall(r'\b(\w*%s\w*)\s*\(' % re.escape(fn),
                             gen.gen_module(Parser(py_tokenize(src)).parse_module())))
    advertised = {reflect.export_csym(e).lstrip('_')
                  for e in reflect.collect_exports_src(
                      src, module_prefix='param_rule_probe')
                  if e['name'] == fn}
    check('reflect: %s(%s) advertises the emitted symbol' % (fn, ann),
          emitted == advertised,
          'codegen %r vs reflect %r' % (sorted(emitted), sorted(advertised)))


def main():
    failures = []

    def check(what, ok, detail=''):
        if not ok:
            failures.append('%s: %s' % (what, detail))

    for importer, definer, prefix, required in PAIRS:
        _check_calls_agree(check, importer, definer, prefix, required)

    # The reflection table's advertised symbol is hashed from reflect.py's own
    # parameter resolver; both spellings must agree with codegen.
    _check_reflect_agrees(check, 'StringSlice[_]', 'probe_slice')
    _check_reflect_agrees(check, 'StringSlice', 'probe_bare')

    # The export record the importer reads. `Span *` for a bracketed
    # StringSlice/Span parameter, `char *` for the bare string: the ctypes the
    # defining module's `_signature_ctypes` uses, hence the same overload
    # suffix.
    def params(module, fn):
        return (load_module(module).get(fn) or {}).get('c_parameters')

    check('export record: is_lowercase takes Span *',
          params('std.collections.string._unicode', 'is_lowercase')
          == ['Span * s'],
          str(params('std.collections.string._unicode', 'is_lowercase')))
    check('export record: _count_utf8_continuation_bytes takes Span *',
          params('std.collections.string._utf8',
                 '_count_utf8_continuation_bytes') == ['Span * span'],
          str(params('std.collections.string._utf8',
                     '_count_utf8_continuation_bytes')))
    check('export record: printf_append_string_n takes Span *',
          params('std.sys._amdgpu', 'printf_append_string_n')
          == ['uint64_t msg_desc', 'Span * data', '_Bool is_last'],
          str(params('std.sys._amdgpu', 'printf_append_string_n')))
    check('export record: _atof takes char *',
          params('std.collections.string._parsing_numbers.parsing_floats',
                 '_atof') == ['char * x'],
          str(params('std.collections.string._parsing_numbers.parsing_floats',
                     '_atof')))

    if failures:
        for f in failures:
            print('FAIL ' + f)
        return 1
    print('PASS stdlib_import_suffix: every call in the three pairs names its '
          'definition\'s symbol, and the export record resolves Span * / char * '
          '(not the int64_t * box) for the bracketed and bare spellings')
    return 0


if __name__ == '__main__':
    sys.exit(main())
