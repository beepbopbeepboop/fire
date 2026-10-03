#!/usr/bin/env python3
"""Census: stdlib modules whose generated C CALLS an imported name that is a
generic template — a symbol nothing defines.

Why this exists. `compile_stdlib.py` (the `stdlib-syntax` gate step) runs
`gcc -fgimple -fsyntax-only`, which cannot see a call to a function that is
declared but never defined. `reflect.export_exclusions` deliberately keeps
every GENERIC template out of a module's export table — a generic has no single
concrete symbol, so an importer is supposed to instantiate it on demand — and
when that on-demand elaboration does not happen, the codegen emits an `extern
int64_t f (...)` and calls it anyway. That is not a compile error; it is an
`undefined symbol` at LINK.

This tool names every such site. It is a CENSUS, not a gate step: turning it
into one is a separate decision (see the measurement in
bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md — the
count is large enough that it must not be sprung on the suite).

A name is reported when, for a `from M import name` binding in the module:
  * `name` is NOT in `module_loader.load_module(M)`'s export table, AND
  * `name` is defined in M's source as a `def`/`fn` that is NOT a class
    (module_loader emits no class exports at all, so a class is legitimately
    absent from the table and legitimately callable — see
    `module_shared._register_sym`'s own comment), AND
  * the module's generated C contains a CALL to it — as opposed to only the
    preamble's guarded forward declaration, which every import gets and which
    links fine. See `_bare_call`; getting that distinction wrong is what made
    this census report 424 sites when 108 are real.

Usage:
    python3 tools/undef_import_census.py           # the census
    python3 tools/undef_import_census.py --names   # distinct names only
"""
import argparse
import os
import re
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from module_loader import STDLIB_PATH, load_module, can_resolve_module_path
from fire_compiler import Parser, py_tokenize, FromImportStmt
from mojo.middle.types import _fi_name, _fi_alias

_EXPORT_CACHE: dict = {}
_SRC_CACHE: dict = {}

_UNESCAPED_QUOTE = re.compile(r'(?<!\\)"')


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
                    help='print only the distinct called names')
    args = ap.parse_args()

    import compile_stdlib as cs
    files = [str(p) for _, p in cs.find_mojo_files(STDLIB_PATH)]
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


if __name__ == '__main__':
    main()