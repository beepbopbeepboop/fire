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
                python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p4_target
                python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p5_unlowered
                python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p6_bracketed
                python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p7_struct
                python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p8_overload
                python3 test_stdlib_dylib_lazy_undefined_refs_probes.py p9_generic
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
from functools import lru_cache

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from module_loader import STDLIB_PATH, module_name_for_path
import build_stdlib_dylib as b


@lru_cache(maxsize=None)
def _compile_stdlib(rel):
    path = os.path.join(STDLIB_PATH, *rel.split('/'))
    src = open(path).read()
    return b.compile_module_to_c(src, path, module_name_for_path(path),
                                 linkable=False)


def _defs(c):
    """The C symbols that have a BODY in one module's generated C.

    A declaration ends with `;`; a definition's signature line does not. Weak
    one-line stubs (`__attribute__((weak)) int64_t name (...) { ... }`) count:
    they ARE definitions, under whatever name they spell, which is exactly what
    p5 is about.
    """
    out = set()
    for line in c.splitlines():
        s = line.strip()
        if not s or s.startswith(('#', '/*', '//')) or ' (' not in s:
            continue
        if s.endswith(';'):
            continue
        s = re.sub(r'^__attribute__\(\(.*?\)\)\s*', '', s)
        m = re.match(r'[^=]*?\b([A-Za-z_]\w*)\s*\(', s)
        if m:
            out.add(m.group(1))
    return out


def _ref_symbols(c, family):
    """Every occurrence of `family` (a regex with capturing groups intended as
    a whole-symbol pattern) in module C `c`."""
    return set(re.findall(family, c))


def _require_resolved(caller_c, caller_rel, family, definer_c, definer_rel):
    """Every symbol `caller_c` names from `family` must be defined by the
    defining unit — the dylib's contract (CLAUDE.md, `stdlib-dylib`)."""
    refs = _ref_symbols(caller_c, family)
    assert refs, ('probe is stale: %s no longer names %s'
                  % (caller_rel, family))
    defs = {s for s in _defs(definer_c) if re.fullmatch(family, s)}
    missing = sorted(refs - defs)
    assert not missing, (
        '%s references %s but %s defines only %s'
        % (caller_rel, ', '.join(sorted(refs)), definer_rel,
           ', '.join(sorted(defs)) or 'nothing'))


def _unresolved_family(definer_rel, caller_rel, family, workdir, tag):
    """`_std_` references matching `family` that a two-module dylib leaves
    undefined. Empty means the caller resolves the name — either the defining
    unit emits it or the call was inlined away. This is the authoritative
    instrument: it is the same `nm -u` vs `nm -gU` pair the bug was measured
    with, over the same per-module objects `build_stdlib_dylib.build` links."""
    from tools.stdlib_dylib_ratchet import unresolved_stdlib_refs
    mods = [os.path.join(STDLIB_PATH, *r.split('/'))
            for r in (definer_rel, caller_rel)]
    dylib = os.path.join(workdir, tag + '.dylib')
    b.build(mods, dylib, jobs=1)
    return [s for s in unresolved_stdlib_refs(dylib)
            if re.fullmatch(family, s)]




# part 1 (FIXED by `_reexported_defining_qualifier`): a free function
# re-exported through a package `__init__.mojo` is referenced by the defining
# unit's qualifier (`std_memory_memory_...`), never by the re-exporting
# package's (`std_memory___init___...`).
def test_p1_reexport_home_module_is_the_defining_module():
    c = _compile_stdlib('std/memory/maybe_uninit.mojo')
    refs = [l for l in c.splitlines() if 'unsafe_memset_zero' in l]
    assert refs, 'maybe_uninit.mojo emits no unsafe_memset_zero reference; probe is stale'
    assert 'std_memory___init___unsafe_memset_zero' not in c, (
        'caller still qualifies the reference with the re-exporting '
        'package __init__:\n' + '\n'.join(refs))
    # `<qualifier>_<bare-name>`, ONE separator: the defining file's own
    # compile emits `std_memory_memory_unsafe_memset_37bd8e` for its
    # sibling, and a double underscore appears only where the NAME itself
    # starts with one (`..._memory__memcmp_impl_...`). The part-1 doc
    # first spelled this with a second underscore; the compiler has never
    # emitted that spelling, and `nm` on a production dylib agrees
    # (`_std_memory_memory_unsafe_memset_37bd8e`, single).
    assert re.search(r'std_memory_memory_unsafe_memset_zero', c), (
        'caller does not reference the defining module '
        '(std/memory/memory.mojo):\n' + '\n'.join(refs))


# The rest of the part-1 acceptance list, measured through the real
# package-`__init__` re-export shape: one caller module per name from the
# parent doc's qualifier group. Each reference must carry the DEFINING
# module's qualifier, never the re-exporting package `__init__`'s.
_P1_REEXPORT_GROUP = (
    ('std/testing/assert_aborts.mojo', 'sleep',
     'std/time/time.mojo', 'std_time'),
    ('std/testing/prop/random.mojo', 'seed',
     'std/random/random.mojo', 'std_random'),
    ('std/itertools/itertools.mojo', 'forget_deinit',
     'std/memory/memory.mojo', 'std_memory'),
    ('std/pathlib/path.mojo', 'listdir',
     'std/os/os.mojo', 'std_os'),
    ('std/os/path/path.mojo', 'getpwnam',
     'std/pwd/pwd.mojo', 'std_pwd'),
    ('std/os/path/path.mojo', 'getpwuid',
     'std/pwd/pwd.mojo', 'std_pwd'),
)


def test_p1_reexport_direct_import_and_unknown_name_unchanged():
    # A DIRECT import already names the defining module: the re-export walk
    # must leave its qualifier exactly as it was (`_home == module`).
    direct = b.compile_module_to_c(
        'from std.memory.memory import unsafe_memset_zero\n'
        '\n'
        'def f(p: Int) -> Int:\n'
        '    unsafe_memset_zero(p, 1)\n'
        '    return 0\n',
        'p1_direct_import.mojo', 'p1_direct_import', linkable=False)
    assert 'std_memory_memory_unsafe_memset_zero' in direct, (
        'a direct import lost its defining-module qualifier:\n'
        + '\n'.join(l for l in direct.splitlines()
                    if 'unsafe_memset_zero' in l))

    # A name NO reachable module defines: `_find_symbol_home_module`'s
    # honest None keeps today's behaviour — the importing module's own
    # qualifier (here it is not even mangleable) and NO invented home.
    unknown = b.compile_module_to_c(
        'from std.memory import not_a_real_symbol_zz9\n'
        '\n'
        'def f() -> Int:\n'
        '    return not_a_real_symbol_zz9()\n',
        'p1_unknown_symbol.mojo', 'p1_unknown_symbol', linkable=False)
    assert 'std_memory_memory_not_a_real_symbol_zz9' not in unknown, (
        'the re-export walk invented a defining home for a name nothing '
        'defines:\n' + '\n'.join(
            l for l in unknown.splitlines()
            if 'not_a_real_symbol_zz9' in l))


def test_p1_reexport_group_callers_name_the_defining_module():
    for caller_rel, name, definer_rel, package in _P1_REEXPORT_GROUP:
        c = _compile_stdlib(caller_rel)
        refs = [l for l in c.splitlines() if name in l]
        assert refs, '%s emits no %s reference; probe is stale' % (
            caller_rel, name)
        # The package `__init__`'s qualifier, whatever `module_name_for_path`
        # derives for it: the package path is `<package>/__init__.mojo`, so
        # its qualifier is `<package>___init__`.
        bad = package + '___init___' + name
        assert bad not in c, (
            '%s still qualifies %s with the re-exporting package: %s'
            % (caller_rel, name, bad))
        definer = module_name_for_path(
            os.path.join(STDLIB_PATH, *definer_rel.split('/')))
        good = definer + '_' + name
        assert re.search(re.escape(good), c), (
            '%s does not reference the defining module %s (%s):\n%s'
            % (caller_rel, definer_rel, good, '\n'.join(refs)))


# part 2 (fixed): the overload suffix a reference to an IMPORTED free function
# carries is the suffix of the DEFINING unit's signature. `std.collections.string.string`
# calls `parsing_floats._atof`; before the fix the call emitted
# `...__atof_55072c` (param `int64_t *`) while the defining unit emitted
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


# part 3 (the bare-dunder group, landed 2026-11-14):
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


# part 4 (open): a macOS compile of `std/os/path/path.mojo` references all
# three platforms' `_lstat`/`_stat` bodies. Only `std/os/_macos.mojo` is built
# on macOS (`build_stdlib_dylib._excluded_platform`), so the four linux
# references can never be defined in a macOS dylib.
def test_p4_target_conditional_bodies_are_the_host_only():
    c = _compile_stdlib('std/os/path/path.mojo')
    others = sorted(set(re.findall(
        r'std_os__(?:linux_aarch64|linux_x86)__\w+', c)))
    assert not others, (
        'a macOS compile of std/os/path/path.mojo still references another '
        "target's bodies (not built into a macOS dylib):\n  "
        + '\n  '.join(others))
    defs = _defs(_compile_stdlib('std/os/_macos.mojo'))
    for want in ('std_os__macos__lstat_d719e0', 'std_os__macos__stat_d719e0'):
        assert want in defs, (
            'the host branch is missing: std/os/_macos.mojo does not define '
            + want)


# part 5 (open): a function whose body this compiler cannot lower is dropped,
# and the call site then emits a BARE weak stub; every caller elsewhere uses
# `std_<module>_<name>`. `is_*_gpu` (sys/info.mojo) and `CPython.as_imm`
# (python/_cpython.mojo) are the measured cases.
def test_p5_unlowered_bodies_are_defined_under_the_caller_name():
    info = _defs(_compile_stdlib('std/sys/info.mojo'))
    want = ('std_sys_info_is_apple_gpu', 'std_sys_info_is_nvidia_gpu',
            'std_sys_info_is_amd_gpu')
    missing = [n for n in want if n not in info]
    assert not missing, (
        'std/sys/info.mojo has no definition for %s; its own calls emit a '
        'bare-name stub that no cross-module caller can resolve'
        % ', '.join(missing))
    cpython = _defs(_compile_stdlib('std/python/_cpython.mojo'))
    assert 'std_python__cpython_CPython_as_imm' in cpython, (
        'std/python/_cpython.mojo only DECLARES '
        'std_python__cpython_CPython_as_imm (no body); every caller of it is '
        'undefined at link time')


# part 6 (open): a BRACKETED `StringSlice[...]`/`Span[...]` parameter lowers to
# `Span *` in the defining unit, but the text-scan import signature maps every
# `Span`/`StringSlice` to `char *` (module_loader.py, `_imported_type_ctype`).
# The suffixes disagree, so the caller names a symbol nothing emits.
def test_p6_bracketed_slice_params_use_the_definers_suffix():
    span = _compile_stdlib('std/collections/string/string_span.mojo')
    unicode_ = _compile_stdlib('std/collections/string/_unicode.mojo')
    utf8 = _compile_stdlib('std/collections/string/_utf8.mojo')
    amdgpu = _compile_stdlib('std/sys/_amdgpu.mojo')
    debug = _compile_stdlib('std/builtin/debug_assert.mojo')
    for name in ('is_lowercase', 'is_uppercase', 'to_lowercase',
                 'to_uppercase'):
        _require_resolved(
            span, 'std/collections/string/string_span.mojo',
            r'std_collections_string__unicode_%s_[0-9a-f]{6}\b' % name,
            unicode_, 'std/collections/string/_unicode.mojo')
    _require_resolved(
        span, 'std/collections/string/string_span.mojo',
        r'std_collections_string__utf8__count_utf8_continuation_bytes_[0-9a-f]{6}\b',
        utf8, 'std/collections/string/_utf8.mojo')
    _require_resolved(
        debug, 'std/builtin/debug_assert.mojo',
        r'std_sys__amdgpu_printf_append_string_n_[0-9a-f]{6}\b',
        amdgpu, 'std/sys/_amdgpu.mojo')


# part 7 (open): a parameter or return type that is a struct private to the
# defining module is seen by the text scan as `int64_t`, while the defining
# unit emits `_RunOptions *` / `Report *`. `benchmark._run_impl` is the measured
# case (bencher.mojo calls it).
def test_p7_struct_param_and_return_use_the_definers_suffix():
    _require_resolved(
        _compile_stdlib('std/benchmark/bencher.mojo'),
        'std/benchmark/bencher.mojo',
        r'std_benchmark_benchmark__run_impl_[0-9a-f]{6}\b',
        _compile_stdlib('std/benchmark/benchmark.mojo'),
        'std/benchmark/benchmark.mojo')


# part 8 (open): two same-name free functions in one module are not registered
# as overloads of each other: neither gets a definition, and the call becomes a
# bare `(void)` weak stub named without its module qualifier or suffix.
# Measured callers: bit/mask.splat, memory._free, memory.unsafe_memset_zero,
# string/_parsing_numbers/parsing_integers.to_integer.
def test_p8_overload_same_name_free_functions_get_their_own_symbols():
    src = ('def pick(x: Int) -> Int:\n'
           '    return x + 1\n'
           '\n'
           '\n'
           'def pick(x: Bool) -> Int:\n'
           '    return 1 if x else 0\n'
           '\n'
           '\n'
           'def use(x: Int) -> Int:\n'
           '    return pick(x)\n')
    c = b.compile_module_to_c(src, 'p8_pick.mojo', 'p8_pick',
                              linkable=False)
    defs = {s for s in _defs(c) if re.fullmatch(r'p8_pick_pick_[0-9a-f]{6}\b', s)}
    assert len(defs) == 2, (
        'a module with two same-name free functions must define both '
        'overloads; got %s' % (sorted(defs) or 'no definition at all'))
    calls = set(re.findall(r'= (p8_pick_pick_[0-9a-f]{6}) \(', c))
    assert calls and calls <= defs, (
        'the call site must name one of the two definitions (%s), not the bare '
        'stub; got %s' % (sorted(defs), sorted(calls) or 'no resolved call'))
    # The real callers: each two-module dylib must leave no `_std_` reference
    # in its family undefined. A fix that inlines the call at the call site is
    # equally acceptable, and also leaves nothing undefined.
    import tempfile
    cases = (
        ('std/bit/mask.mojo', 'std/collections/string/string_span.mojo',
         r'_std_bit_mask_splat(?:_[0-9a-f]{6})?'),
        ('std/memory/memory.mojo', 'std/memory/pointer.mojo',
         r'_std_memory_memory__free(?:_[0-9a-f]{6})?'),
        ('std/memory/memory.mojo', 'std/memory/maybe_uninit.mojo',
         r'_std_memory_memory_unsafe_memset_zero(?:_[0-9a-f]{6})?'),
        ('std/collections/string/_parsing_numbers/parsing_integers.mojo',
         'std/collections/string/_parsing_numbers/parsing_floats.mojo',
         r'_std_collections_string__parsing_numbers_parsing_integers_to_integer_[0-9a-f]{6}'),
    )
    with tempfile.TemporaryDirectory(prefix='p8_overload_') as wd:
        for i, (definer, caller, family) in enumerate(cases):
            still = _unresolved_family(definer, caller, family, wd, 'p8_%d' % i)
            assert not still, (
                '%s leaves %s undefined; %s defines no symbol the caller can '
                'resolve' % (caller, ', '.join(still), definer))


# part 9 (open): a generic free function instantiated only by a DIFFERENT
# module is never emitted by its defining module (a module is compiled alone,
# so nothing there asks for the concrete instance). Measured: memory.forget_deinit
# and memory.unsafe_destroy_n (array.mojo), memory.alloc.dealloc (list.mojo),
# time.time_function (benchmark.mojo).
def test_p9_generic_cross_module_instantiations_are_emitted():
    import tempfile
    from tools.stdlib_dylib_ratchet import unresolved_stdlib_refs

    cases = [
        ('std/memory/memory.mojo', 'std/collections/array.mojo',
         ('_std_memory_memory_forget_deinit_9f63a2',
          '_std_memory_memory_unsafe_destroy_n_2dbb98')),
        ('std/memory/alloc.mojo', 'std/collections/list.mojo',
         ('_std_memory_alloc_dealloc_9f63a2',)),
        ('std/time/time.mojo', 'std/benchmark/benchmark.mojo',
         ('_std_time_time_time_function',)),
    ]
    with tempfile.TemporaryDirectory(prefix='p9_generic_') as wd:
        for i, (definer, caller, want) in enumerate(cases):
            mods = [os.path.join(STDLIB_PATH, *r.split('/'))
                    for r in (definer, caller)]
            dylib = os.path.join(wd, 'p9_%d.dylib' % i)
            b.build(mods, dylib, jobs=1)
            unresolved = set(unresolved_stdlib_refs(dylib))
            still = [s for s in want if s in unresolved]
            assert not still, (
                '%s instantiates %s but %s emits no such definition; the '
                'two-module dylib leaves them undefined'
                % (caller, ', '.join(want), definer))


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
