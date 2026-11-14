#!/usr/bin/env python3
"""Per-part Done-when probes of the STILL-OPEN parts of
CODEGEN_stdlib_dylib_lazy_undefined_refs.

Each `test_<prefix>_*` here is the Done-when test of an open part doc under
bugs/ and is RED until its part lands. This file is deliberately NOT a
registered gate job: a red probe belongs to its bug doc's command, not to the
green regression bucket.

Run one probe:  python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p1_reexport
                python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p2_imported
                python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p3_same_arity
A bare run executes every open probe and is red until they all land.

p1_reexport / p2_suffix compile the real stdlib modules that carry the measured
mismatches (the same per-module `compile_module_to_c` path
`build_stdlib_dylib.py` uses) and assert on the emitted C; they depend on the
shared stdlib tree but never link against it and never run it. p3_dunder is
fully synthetic.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from module_loader import STDLIB_PATH, module_name_for_path
import build_stdlib_dylib as b


def _compile_stdlib(rel):
    path = os.path.join(STDLIB_PATH, *rel.split('/'))
    src = open(path).read()
    return b.compile_module_to_c(src, path, module_name_for_path(path),
                                 linkable=False)


# part 1 (bugs/CODEGEN_stdlib_dylib_lazy_undefined_refs-part1.md):
# a free function re-exported through a package `__init__.mojo` is referenced
# by the defining unit's qualifier (`std_memory_memory__...`), never by the
# re-exporting package's (`std_memory___init__...`).
def test_p1_reexport_home_module_is_the_defining_module():
    c = _compile_stdlib('std/memory/maybe_uninit.mojo')
    refs = [l for l in c.splitlines() if 'unsafe_memset_zero' in l]
    assert refs, 'maybe_uninit.mojo emits no unsafe_memset_zero reference; probe is stale'
    assert 'std_memory___init___unsafe_memset_zero' not in c, (
        'caller still qualifies the reference with the re-exporting '
        'package __init__:\n' + '\n'.join(refs))
    assert re.search(r'std_memory_memory__unsafe_memset_zero', c), (
        'caller does not reference the defining module '
        '(std/memory/memory.mojo):\n' + '\n'.join(refs))


# part 2 (bugs/CODEGEN_stdlib_dylib_lazy_undefined_refs-part2.md):
# the overload suffix a reference to an IMPORTED free function carries is the
# suffix of the DEFINING unit's signature. `std.collections.string.string`
# calls `parsing_floats._atof`; measured today the call emits
# `...__atof_55072c` (param `int64_t *`) while the defining unit emits
# `...__atof_d719e0` (param `char *`) — an undefined reference at link time.
_ATOF_FAMILY = (
    r'(?<![A-Za-z0-9_])'
    r'std_collections_string__parsing_numbers_parsing_floats__atof_[0-9a-f]+'
)


def _atof_symbols(c):
    return [m for l in c.splitlines() if '__atof_' in l
            for m in re.findall(_ATOF_FAMILY, l)]


def test_p2_imported_suffix_matches_the_defining_unit():
    def_c = _compile_stdlib('std/collections/string/_parsing_numbers/parsing_floats.mojo')
    call_c = _compile_stdlib('std/collections/string/string.mojo')
    # The definition is the one symbol occurrence not spelled with a trailing
    # forward-declaration `;`.
    def_lines = [l for l in def_c.splitlines() if '__atof_' in l]
    def_defs = [l for l in def_lines if not l.rstrip().endswith(';')]
    def_syms = {s for l in def_defs for s in re.findall(_ATOF_FAMILY, l)}
    assert len(def_syms) == 1, (
        'parsing_floats.mojo emits an unexpected set of _atof definitions: '
        + repr(def_lines))
    call_syms = set(_atof_symbols(call_c))
    assert call_syms, (
        'string.mojo emits no _atof reference; probe is stale')
    assert call_syms == def_syms, (
        'string.mojo references %s but the defining unit emits %s'
        % (sorted(call_syms), sorted(def_syms)))


# part 3 (bugs/CODEGEN_stdlib_dylib_lazy_undefined_refs-part3.md):
# a struct method dunder with two same-arity overloads is never referenced
# bare (no overload id); the call site names one concrete overload — for
# `p[0]`, the Int one.
P3_PAIR_SRC = (
    'struct Pair:\n'
    '    var a: Int\n'
    '    var b: Int\n'
    '    def __getitem__(self, i: Int) -> Int:\n'
    '        return i + 100\n'
    '    def __getitem__(self, s: String) -> Int:\n'
    '        return s.length + 100\n'
    '\n'
    'def f(p: Pair) -> Int:\n'
    '    return p[0]\n'
)


def test_p3_same_arity_dunder_names_one_overload():
    c = b.compile_module_to_c(P3_PAIR_SRC, 'p3_pair.mojo', 'p3_pair',
                              linkable=False)
    assert not re.search(r'pair_Pair___getitem__ \(', c), (
        'call site or extern still names the bare (un-suffixed) dunder:\n'
        + '\n'.join(l for l in c.splitlines() if 'getitem' in l))
    m_int = re.search(
        r'(\w*pair_Pair___getitem___[0-9a-f]+) \(Pair \* self, int64_t i\)', c)
    assert m_int is not None, (
        'no Int-overload definition of Pair.__getitem__:\n'
        + '\n'.join(l for l in c.splitlines() if 'getitem' in l))
    int_overload = m_int.group(1)
    m_call = re.search(r'= (\w*pair_Pair___getitem___[0-9a-f]+) \(', c)
    assert m_call is not None, (
        'no __getitem__ call site:\n'
        + '\n'.join(l for l in c.splitlines() if 'getitem' in l))
    assert m_call.group(1) == int_overload, (
        'p[0] dispatched to %s, but the Int overload is %s'
        % (m_call.group(1), int_overload))


if __name__ == '__main__':
    part = sys.argv[1] if len(sys.argv) > 1 else ''
    prefix = 'test_%s_' % part if part else 'test_'
    names = sorted(n for n, f in list(globals().items())
                   if n.startswith(prefix) and callable(f))
    if not names:
        sys.exit('no test named with prefix %r' % prefix)
    for name in names:
        globals()[name]()
        print('ok', name)
    print('all tests passed')
