#!/usr/bin/env python3
"""Census: stdlib modules whose generated C CALLS a symbol nothing defines.

TWO sections, because the first one is a lower bound and was being read as a
total.

SECTION 1 — "imported generic, bare name". A `from M import name` binding
where `name` is NOT in `module_loader.load_module(M)`'s export table, IS
defined in M's source as a `def`/`fn` that is not a class, and the module's
generated C contains a CALL to it — as opposed to only the preamble's guarded
forward declaration, which every import gets and which links fine. See
`_bare_call`; getting that distinction wrong is what made this census report
424 sites when 108 are real.

Section 1 has a measured blind spot, and it is not small. Its own `check()`
credits ANY call to a MANGLED symbol (`copysign_Float64_1`,
`size_of_6_target_17_CompilationTarget_4_type_3_Int`) on the grounds that a
mangled call names a CAS object the caller links. That is true for the ones
that have one and FALSE for the ones that do not, and nothing here can tell
the difference, because the check never links. Measured hole: `Set` is
reported (1 site) but `size_of` is not reported AT ALL, while
`test/collections/test_list.mojo` calls
`size_of_6_target_17_CompilationTarget_4_type_3_Int` and
`nm -g --defined-only build/libmojostdlib.arm64.dylib` has **0** such symbols.
So "96 / 51 / 60" counts the calls the elaborator never got to, and silently
excludes the ones it got to and could not link.

SECTION 2 — "called, defined nowhere". The total, measured the way the linker
would see it: for every file that COMPILES, compile its generated C to an
object with `gcc -c` (the same `-fgimple -D__MOJO_STDLIB_MODE__` the sweep
uses), read `nm -u`, and subtract every symbol the C runtime, the stdlib dylib
or the platform's own libraries define. What is left is called by this module
and defined by nothing on this machine. No parsing of the generated C is
involved, so this section cannot inherit `_bare_call`'s judgement calls — it is
`nm` against `nm`.

Both sections are CENSUS, not gate steps: turning either into one is a separate
decision (see the measurement in
bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md — the
count is large enough that it must not be sprung on the suite).

Usage:
    python3 tools/undef_import_census.py           # both sections
    python3 tools/undef_import_census.py --names   # section 1's distinct names
    python3 tools/undef_import_census.py --section 2
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_loader import STDLIB_PATH, load_module, can_resolve_module_path
from fire_compiler import Parser, py_tokenize, FromImportStmt
from mojo.middle.types import _fi_name, _fi_alias
from build_config import find_gcc

_EXPORT_CACHE: dict = {}
_SRC_CACHE: dict = {}

_UNESCAPED_QUOTE = re.compile(r'(?<!\\)"')

# Objects the linker line a real `fire.py build` uses always contributes, and
# the stdlib dylib itself. Section 2 subtracts their DEFINED symbols; a name in
# here is not part of the population even though `nm -u` on a single object
# cannot see that it is satisfiable.
_RUNTIME_OBJS = ('build/mojo_runtime.o', 'build/mojo_coro.o',
                 'build/mojo_coro_ctx.o', 'build/mojo_coro_gen.o',
                 'build/mojo_async_sched.o')
_DYLIB = 'build/libmojostdlib.arm64.dylib'

# nm's undefined-symbol spelling is `_foo`; every table below is compared in
# that spelling too, so nothing has to strip and re-add a prefix.
_DEFINED_CACHE: dict = {}


def _nm_defined(path: str) -> set:
    """`nm -g --defined-only` on one binary, as `_sym` strings. Empty on any
    failure — reported by the caller, never silently treated as "defines
    nothing", because that would inflate the population."""
    try:
        r = subprocess.run(['nm', '-g', '--defined-only', path],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return set()
    return {ln.split()[-1] for ln in r.stdout.splitlines() if ln.split()}


def _system_symbols() -> set:
    """Every symbol the platform's own libraries export, read out of the SDK's
    text-based stubs. They are the residue every `nm -u` has and none of it is
    this compiler's problem; without this subtraction section 2 would report
    `malloc`/`printf`/`pow` 610 times over."""
    out = set()
    try:
        sdk = subprocess.run(['xcrun', '--show-sdk-path'], capture_output=True,
                             text=True, timeout=60).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return out
    if not sdk:
        return out
    tbd_dir = os.path.join(sdk, 'usr', 'lib')
    for name in sorted(os.listdir(tbd_dir)) if os.path.isdir(tbd_dir) else ():
        if not name.endswith('.tbd'):
            continue
        try:
            text = open(os.path.join(tbd_dir, name), errors='replace').read()
        except OSError:
            continue
        # Every entry in a `symbols: [...]` list is `_name`; the leading
        # underscore is exactly nm's spelling, so no normalisation is needed.
        out.update(re.findall(r'(?m)(?<=[\s\'\[,])(_[A-Za-z_]\w*)', text))
    return out


def _defined_universe() -> set:
    """Symbols a real link of one generated module can satisfy without any
    further instantiation: the runtime objects, the stdlib dylib, and the
    platform libraries."""
    if 'set' not in _DEFINED_CACHE:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        s = _system_symbols()
        for rel in _RUNTIME_OBJS + (_DYLIB,):
            p = os.path.join(root, rel)
            if os.path.exists(p):
                s |= _nm_defined(p)
        _DEFINED_CACHE['set'] = s
    return _DEFINED_CACHE['set']


def _exports(mod):
    if mod not in _EXPORT_CACHE:
        try:
            _EXPORT_CACHE[mod] = (load_module(mod)
                                  if can_resolve_module_path(mod) else {})
        except Exception:
            _EXPORT_CACHE[mod] = {}
    return _EXPORT_CACHE[mod]


def _module_src(mod):
    if mod not in _SRC_CACHE:
        try:
            import gimple_codegen as GC
            paths = GC.GimpleGen(emit_entry_points=False,
                                 module_name='census')._module_candidate_paths(mod)
            p = next((q for q in paths if os.path.exists(q)), None)
            _SRC_CACHE[mod] = open(p).read() if p else ''
        except Exception:
            _SRC_CACHE[mod] = ''
    return _SRC_CACHE[mod]


def _is_generic_template(mod, orig):
    """True when `orig` is defined in `mod` as a GENERIC template — the one
    shape deliberately kept out of the export table, and therefore the one a
    call site must ELABORATE rather than import."""
    if orig in _exports(mod):
        return False
    src = _module_src(mod)
    if not src:
        return False
    if not re.search(rf'(?m)^\s*(?:async\s+)?(?:fn|def|struct)\s+{re.escape(orig)}\b',
                     src):
        return False
    if re.search(rf'(?m)^\s*struct\s+{re.escape(orig)}\b(?!\s*\[)', src):
        return False   # a class: not exported, but legitimately callable
    return True


def check(path):
    """(rel, local_name, source_module) per undefined-imported-generic call
    site, or None when the module does not compile at all."""
    import build_stdlib_dylib as b
    rel = os.path.relpath(path, STDLIB_PATH)
    src = open(path).read()
    name = os.path.splitext(rel)[0].replace(os.sep, '_').replace('-', '_')
    try:
        c = b.compile_module_to_c_cached(src, path, name)
    except Exception:
        return None
    imported = {}
    try:
        for s in Parser(py_tokenize(src)).parse_module():
            if isinstance(s, FromImportStmt) and not getattr(s, 'wildcard', False):
                for fip in (getattr(s, 'name_alias_strs', None) or []):
                    nm = _fi_name(fip)
                    al = _fi_alias(fip)
                    imported[al or nm] = (s.module, nm)
    except Exception:
        pass
    bad = []
    for local, (mod, orig) in imported.items():
        if not _is_generic_template(mod, orig):
            continue
        # A call to the BARE name is the hole. Once the elaborator has run,
        # the call site references a mangled instantiation (`copysign_Float64_1`)
        # whose definition lives in a CAS object the caller links — and
        # `_link_objects` is not reachable from here, and this check never links
        # anyway, so a mangled call is credited. Measured: std/math/math.mojo
        # emits `copysign_Float32_1`/`copysign_Int64_1` and contributes 8 link
        # objects, with no bare `copysign` extern left.
        if _bare_call(c, local):
            bad.append((rel, local, mod))
    return bad


def check_undefined(path):
    """(rel, [symbols]) for every symbol this module's object needs and
    nothing on this machine defines; None when the module does not compile.

    `gcc -c` + `nm -u`, so the measurement is the linker's own and cannot
    inherit `_bare_call`'s judgement calls. A file that does not compile is
    skipped for the same reason section 1 skips it: there is no artifact, and
    that population is `compile_stdlib.py`'s 19 `EXPECTED_FAILURES`."""
    import build_stdlib_dylib as b
    rel = os.path.relpath(path, STDLIB_PATH)
    src = open(path).read()
    name = os.path.splitext(rel)[0].replace(os.sep, '_').replace('-', '_')
    try:
        c = b.compile_module_to_c_cached(src, path, name)
    except Exception:
        return None
    if not c.strip():
        return (rel, [])
    defined = _defined_universe()
    with tempfile.TemporaryDirectory(prefix='undef_census_') as wd:
        cfile = os.path.join(wd, name + '.c')
        ofile = os.path.join(wd, name + '.o')
        with open(cfile, 'w') as f:
            f.write(c)
        cc = subprocess.run(
            [find_gcc(), '-fgimple', '-I' + os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'runtime'), '-D__MOJO_STDLIB_MODE__', '-c', '-o', ofile, cfile],
            capture_output=True, text=True, timeout=120)
        if cc.returncode != 0:
            return None
        nm = subprocess.run(['nm', '-u', ofile], capture_output=True, text=True,
                            timeout=60)
    undef = {ln.split()[-1] for ln in nm.stdout.splitlines() if ln.split()}
    return (rel, sorted(sym for sym in undef if sym not in defined))


def _bare_call(c: str, name: str) -> bool:
    """Does the generated C actually CALL `name`, as opposed to only DECLARING
    it?

    This distinction is the whole measurement, and getting it wrong inflated the
    census by 4x. The codegen emits, for EVERY name a module imports — used or
    not — a guarded forward declaration in the preamble:

        #ifndef size_of
        #define size_of
        extern int64_t size_of (...);  /* from std.sys.info */
        #endif

    and the previous test was `re.search(rf'\\b{name}\\s*\\(', c)` over the WHOLE
    file, which that line matches. So a module that imports `size_of` and never
    calls it was reported as an undefined call site. A forward declaration is
    harmless — it links fine, because nothing references it — so the reported
    population was mostly declarations.

    Measured on the same sweep: 424 (file, name) pairs by the old test, 108 by
    this one, over 60 files and 56 distinct names instead of 194 and 157. The
    residue — `FormatStruct` 15, `alloc` 10, `ThinAllocation` 8 — is real.

    Two shapes are excluded, and only because they are the codegen's own
    generated declaration forms, both machine-marked:
      * the `#ifndef NAME` / `#define NAME` / `#endif` guard lines, and
      * any line carrying this codegen's own `/* from <module> */` or
        `/* stub from <module> */` marker, which every preamble prototype and
        every unresolved-import weak stub carries and no call site can.

    Nothing else is filtered: a bare statement call (`Index (x);`), a `return
    foo (...)`, and an assignment (`_t3 = foo (...)`) all count. Guessing
    "does this line look like a declarator" instead would have silently dropped
    real calls, which is the one failure mode a census must not have.

    An occurrence inside a STRING LITERAL is not a call at all, and this
    codegen emits every docstring as one: `std/utils/coord.mojo`'s docstring
    contains the text `Coord(Coord(2, 3), Coord(4, 5))`, which is a sentence
    about the type, not a call to it. An odd number of unescaped `"` before the
    match means the match is inside a literal.
    """
    for line in c.splitlines():
        s = line.strip()
        if re.match(rf'^#\s*(?:ifndef|define|endif)\s+{re.escape(name)}\b', s):
            continue
        if '/* from ' in s or '/* stub from ' in s:
            continue
        for m in re.finditer(rf'\b{re.escape(name)}\b\s*\(', s):
            # Quotes before the match that are not escaped: an odd count means
            # the match is inside a string literal.
            if len(_UNESCAPED_QUOTE.findall(s[:m.start()])) % 2 == 0:
                return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--names', action='store_true',
                    help='print only section 1\'s distinct called names')
    ap.add_argument('--section', type=int, choices=(1, 2), default=0,
                    help='run only that section (default: both)')
    args = ap.parse_args()

    import compile_stdlib as cs
    files = [str(p) for _, p in cs.find_mojo_files(STDLIB_PATH)]

    if args.section in (0, 1):
        sites = []
        with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
            futs = {pool.submit(check, p): p for p in files}
            for f in as_completed(futs):
                r = f.result()
                if r:
                    sites.extend(r)
        names = sorted(set(s[1] for s in sites))
        if args.names:
            for n in names:
                print(n)
            return
        print(f"undefined-imported-generic call sites: {len(sites)}")
        print(f"distinct names: {len(names)}")
        print(f"files affected: {len(set(s[0] for s in sites))}")
        print("\nby name:")
        for n, k in Counter(s[1] for s in sites).most_common():
            print(f"  {k:4d}  {n}")
        print("\nby file:")
        for f, k in sorted(Counter(s[0] for s in sites).items()):
            print(f"  {k:4d}  {f}")
        print()

    if args.section in (0, 2):
        rows = []
        with ProcessPoolExecutor(max_workers=os.cpu_count()) as pool:
            futs = {pool.submit(check_undefined, p): p for p in files}
            for f in as_completed(futs):
                r = f.result()
                if r:
                    rows.append(r)
        by_name = Counter(s for _rel, syms in rows for s in syms)
        by_file = {rel: syms for rel, syms in rows if syms}
        print("called-but-defined-nowhere (gcc -c + nm -u, minus runtime + "
              "stdlib dylib + platform libs):")
        print(f"  sites: {sum(by_name.values())}")
        print(f"  distinct names: {len(by_name)}")
        print(f"  files affected: {len(by_file)}")
        print("\nby name:")
        for n, k in by_name.most_common():
            print(f"  {k:4d}  {n}")
        print("\nby file:")
        for rel, syms in sorted(by_file.items()):
            print(f"  {len(syms):4d}  {rel}")


if __name__ == '__main__':
    main()