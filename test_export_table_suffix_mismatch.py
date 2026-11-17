#!/usr/bin/env python3
"""Regression: the stdlib dylib's export-table cross-check reported 4 functions
as "declared with no definition in this dylib" although their bodies ARE in the
dylib — under a differently-hashed overload suffix.

The stdlib dylib build cross-checks every export entry's expected C symbol
against `nm` on the objects it just linked (build_stdlib_dylib.build,
runtime_export_entries, and the optional-unit builds). The source scan hashes
the signature's param types as parsed from source; codegen hashes the LIVE
inferred types at emission. For `std/collections/string/string.mojo`'s
`ord`/`ascii`/`atol` and `_parsing_numbers/parsing_integers.mojo`'s
`standardize_string_slice` the two disagree — the body exists as
`_std_collections_string_string_ord_d719e0` while the entry names
`..._ord_9f63a2` — and the old check, finding neither the expected symbol nor
the raw name, classified the entry as UNDEFINED: "declared with no definition
in this dylib". That false claim sent the analyzer's part-2 doc (bugs/
COMPILE_FAIL_Tools_cases_generator_analyzer-part3-part2.md) hunting for four
missing bodies that were present.

The fix is `build_stdlib_dylib.classify_export_entries` (the ONE classifier
behind the three call sites, which used to carry three copies of the check):
an entry whose expected symbol is absent but whose name has a DEFINITION under
a different 6-hex overload suffix is misresolved — and the report names the
definition that exists. Only `py_tokenize` (a runtime-header declaration
satisfied by the self-hosted compiler image, not the runtime) is genuinely
undefined.

This test pins the INVARIANT, in both states (the style test_runtime_dylib.py
uses for the same reason a count would rot):
  1. none of the four functions is classified "undefined" while a same-named
     definition exists under a different overload suffix;
  2. every entry classified "undefined" really has no definition under ANY
     spelling (the exact false claim this regression kills);
  3. every "defined as <sym>" the report cites is really defined in the dylib;
  4. end-to-end: the report the build actually prints to stderr no longer lists
     the four functions under "declared with no definition".
State 1+2 hold today (the four are misresolved-with-definition) and keep
holding if the codegen suffix disagreement is fixed (the four become kept);
they catch a regression of the classification itself in either state.

Run: `python3 test_export_table_suffix_mismatch.py`   (warm: ~30 s, < 1 GB;
a COLD stdlib dylib build costs what the stdlib bucket costs — the suite's
gate builds it first, and this test reuses the CAS)
SKIP (exit 0) when the stdlib source tree or a C toolchain is absent.
"""
import contextlib
import io
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import build_stdlib_dylib as bsd            # noqa: E402
import reflect                              # noqa: E402

# The four functions the old check misclassified, and the modules that define
# them (located from the build's own module list, so the test follows the tree
# instead of hard-coding a checkout path).
NAMES = ('ord', 'ascii', 'atol', 'standardize_string_slice')
OVERLOAD_SUFFIX = re.compile(r'_[0-9a-f]{6}$')


def stdlib_source_files():
    """The defining modules' paths, from the build's own module discovery."""
    mods = bsd.stdlib_modules()
    want = ('std/collections/string/string.mojo',
            'std/collections/string/_parsing_numbers/parsing_integers.mojo')
    out = []
    for w in want:
        for m in mods:
            if m.replace(os.sep, '/').endswith(w):
                out.append(m)
                break
        else:
            return None
    return out


def defined_symbols(dylib):
    """The dylib's external defined symbols, the way the cross-check reads them
    (macOS nm; arch-prefixed names)."""
    out = subprocess.run(['nm', '-g', '-m', dylib], capture_output=True, text=True).stdout
    syms = set()
    for line in out.splitlines():
        parts = line.split()
        if 'external' in parts and len(parts) >= 3 and parts[0] != '(undefined)':
            syms.add(parts[-1])
        elif len(parts) >= 3 and parts[1] in ('T', 'D', 'S', 'B', 'C', 'I', 'R'):
            syms.add(parts[2])
    return syms


def test_classifier(dylib, defined):
    files = stdlib_source_files()
    if files is None:
        print('SKIP  test_export_table_suffix_mismatch: stdlib string modules '
              'not in the build module list')
        return 0
    entries = []
    for path in files:
        prefix = bsd._module_name_for(path)
        entries += reflect.collect_exports_src(open(path).read(), module_prefix=prefix)
    # The fifth reported entry: a runtime-header declaration with no runtime
    # definition (csym = the raw header name).
    for e in reflect.collect_runtime_exports_h(os.path.join(HERE, 'runtime', 'fire_runtime.h')):
        if e['name'] == 'py_tokenize':
            entries.append(e)

    kept, misresolved, undefined = bsd.classify_export_entries(entries, defined)
    rc = 0
    by_name = {}
    for e in entries:
        by_name.setdefault(e['name'], []).append(e)

    # 1+2: the four are never "undefined" while a same-named definition exists
    # under a different overload suffix, and EVERY undefined entry is truly
    # definition-less under any spelling.
    suffix_by_stem = {}
    for d in defined:
        m = OVERLOAD_SUFFIX.search(d)
        if m:
            suffix_by_stem.setdefault(d[:m.start()], set()).add(d)
    for name in NAMES:
        for e in by_name.get(name, ()):
            if e['name'] in undefined:
                print(f'FAIL  {name} is reported "declared with no definition" '
                      f'but a definition exists or the check is blind to it')
                rc = 1
    for e in entries:
        if e['name'] not in undefined or e['kind'] == reflect.SYM_TYPE:
            continue
        sym = reflect.export_csym(e)
        expect = '_' + sym
        if expect in defined:
            print(f'FAIL  {e["name"]} reported undefined but its expected '
                  f'symbol {expect} IS defined')
            rc = 1
            continue
        m = OVERLOAD_SUFFIX.search(expect)
        if m and any(d != expect for d in suffix_by_stem.get(expect[:m.start()], ())):
            print(f'FAIL  {e["name"]} reported undefined though a same-named '
                  f'definition exists under a different overload suffix')
            rc = 1

    # 3: every "defined as <sym>" the classifier cites is really defined.
    for line in misresolved:
        m = re.search(r'\(defined as ([^)]+)\)$', line)
        if not m:
            continue
        for cited in m.group(1).split(', '):
            if ('_' + cited) not in defined:
                print(f'FAIL  misresolved line cites {cited!r} as defined, but '
                      f'nm says otherwise')
                rc = 1

    # 4: py_tokenize is the one genuinely undefined entry in this set — and if
    # a definition ever appears, the classifier must move it, which 1+2 above
    # would catch as the moment of truth.
    if 'py_tokenize' in undefined:
        if any(s.startswith('_py_tokenize') for s in defined):
            print('FAIL  py_tokenize reported undefined but the dylib defines '
                  'a _py_tokenize* symbol')
            rc = 1
    return rc


def test_report(text):
    """The report the BUILD prints must no longer list the four under
    "declared with no definition". `text` is the build's captured stderr."""
    report = [ln.strip() for ln in text.splitlines() if 'export table' in ln
              or 'no definition in this dylib' in ln
              or 'defined but not advertised' in ln]
    if not report:
        print('FAIL  no export-table report in the build output')
        return 1
    undefined_line = next((ln for ln in report
                           if 'no definition in this dylib' in ln), '')
    tail = undefined_line.split(': ', 1)[-1] if undefined_line else ''
    bad = [n for n in NAMES if re.search(rf'\b{n}\b', tail)]
    if bad:
        print(f'FAIL  the build report still names {bad} under "declared with '
              f'no definition in this dylib":\n  {undefined_line}')
        return 1
    print('PASS  export table: suffix-mismatched definitions are reported as '
          'defined (not "no definition in this dylib")')
    return 0


def main() -> int:
    if shutil.which('nm') is None:
        print('SKIP  test_export_table_suffix_mismatch: nm not found')
        return 0
    if stdlib_source_files() is None:
        print('SKIP  test_export_table_suffix_mismatch: stdlib sources absent')
        return 0
    # One build, its stderr captured: the classifier half reads the dylib's
    # symbols, the report half reads the lines build() printed.
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        dylib = bsd.build_stdlib()
    defined = defined_symbols(dylib)
    rc = test_classifier(dylib, defined)
    rc |= test_report(buf.getvalue())
    return rc


if __name__ == '__main__':
    sys.exit(main())
