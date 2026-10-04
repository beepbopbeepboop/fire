#!/usr/bin/env python3
"""End-to-end tests for the module cache (MODULE_CACHE_DESIGN.md stages 1-6).

Each stage's mechanism is exercised for real: compile, link, run, and check the
cache behaves (cold miss / warm hit / invalidation). Run via `make check` or
directly: `python3 test_module_cache.py`.
"""
import os
import re
import sys
import shutil
import tempfile
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')
sys.path.insert(0, HERE)

from build_config import find_gcc
import cas
import reflect
import monomorphize as mm
import comptime
import build_stdlib_dylib as bsd
from gimple_codegen import compile_to_gimple_linked
from exec_budget import (COMPILE_TIMEOUT_S, RUN_TIMEOUT_S,
                           SWEEP_TIMEOUT_S)

GCC = find_gcc()
_PASS = 0
_FAIL = 0


def check(name, cond, detail=""):
    global _PASS, _FAIL
    if cond:
        print(f"PASS  {name}")
        _PASS += 1
    else:
        print(f"FAIL  {name}  {detail}")
        _FAIL += 1


# Was 20 s, which failed this suite in a full gate at -j18 -- as an UNCAUGHT
# TimeoutExpired, so every check before it was lost and every check after it never
# ran. See exec_budget.py for the shared value and the layering rationale.
#
# …and the nine OTHER budgets in this file were still literals when this was
# written: `timeout=20` five times, `timeout=120` three times and `timeout=180`
# once, all of them the same defect on the same kinds of child (a produced
# executable, a `fire.py build`, a `--dump-full` of the closure). Converting one
# call site in a file is not converting the file, which is why `test_suite.py`'s
# "no stale per-child budget is left as a literal" now reads the tree instead of
# trusting a comment that says the work was done.
EXE_TIMEOUT_S = RUN_TIMEOUT_S
_TIMED_OUT_PREFIX = '<<timed out'


def _run(exe):
    """Run a built executable and return a CompletedProcess-alike.

    A timeout here used to propagate as an uncaught TimeoutExpired, which
    aborted the whole suite with a traceback: every check before it was lost,
    every check after it never ran, and the gate could not tell what had been
    covered at all. Returning a synthetic result whose stdout says so instead
    makes every existing `check(..., _run(exe).stdout...)` call site fail
    honestly and legibly -- the check's own name is right there in the report --
    and lets the rest of the suite run.
    """
    try:
        return subprocess.run([exe], capture_output=True, text=True,
                              timeout=EXE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            [exe], returncode=-1,
            stdout=f'{_TIMED_OUT_PREFIX} after {EXE_TIMEOUT_S}s (see '
                   f'subprocess.TimeoutExpired; the job timeout is the real '
                   f'hang detector)>',
            stderr='')


def _write_runtime_module(name, src):
    """Place a library module where module_loader resolves single-name imports."""
    path = os.path.join(RUNTIME, name + '.mojo')
    with open(path, 'w') as f:
        f.write(src)
    return path


# ── Stage 1: extern-decl import boundary ──────────────────────────────────
def test_stage1_extern_boundary(wd):
    libsrc = "fn s1_add(a: Int64, b: Int64) -> Int64:\n    return a + b\n"
    _write_runtime_module('s1lib', libsrc)
    try:
        client = ("from s1lib import s1_add\n"
                  "fn main():\n"
                  "    var x = s1_add(40, 2)\n"
                  "    if x == 42:\n"
                  "        var ok = \"s1\\n\"\n"
                  "        var n = external_call[\"write\", Int64](1, ok, 3)\n")
        cC = compile_to_gimple_linked(client, filename='client.mojo')
        # SB-1 fix: an imported free function's extern/call-site symbol is now
        # module-qualified with its home module's name (s1lib_s1_add_<hash>,
        # not bare s1_add_<hash>) — see gimple_codegen._func_qualifier. Match
        # any qualifier/suffix rather than the exact old unqualified name.
        check("stage1: extern decl emitted, no inlined body",
              bool(re.search(r'extern int64_t \w*s1_add\w*\s*\(int64_t, int64_t\);', cC))
              and 's1_add (int64_t a, int64_t b)\n{' not in cC)
        # build library artifact separately, link, run
        from gimple_codegen import GimpleGen
        from fire_compiler import py_tokenize, Parser
        lib_c = GimpleGen(emit_entry_points=False, module_name='s1lib').gen_module(
            Parser(py_tokenize(libsrc)).parse_module())
        cc, lc = os.path.join(wd, 'c1.c'), os.path.join(wd, 'l1.c')
        open(cc, 'w').write(cC); open(lc, 'w').write(lib_c)
        co, lo = os.path.join(wd, 'c1.o'), os.path.join(wd, 'l1.o')
        subprocess.run([GCC, '-fgimple', f'-I{RUNTIME}', '-c', '-o', co, cc], check=True)
        subprocess.run([GCC, '-fgimple', f'-I{RUNTIME}', '-c', '-o', lo, lc], check=True)
        exe = os.path.join(wd, 'c1')
        subprocess.run([GCC, '-o', exe, co, lo, os.path.join(RUNTIME, 'fire_runtime.c')], check=True)
        check("stage1: linked client+artifact runs (cross-boundary call)",
              _run(exe).stdout.startswith('s1'))
    finally:
        os.remove(os.path.join(RUNTIME, 's1lib.mojo'))


# ── Stage 2/3: stdlib dylib + content-addressed cache ─────────────────────
def test_stage2_3_dylib_and_cas(wd):
    libsrc = ("fn s2_add(a: Int64, b: Int64) -> Int64:\n    return a + b\n"
              "fn s2_mul(a: Int64, b: Int64) -> Int64:\n    return a * b\n")
    libpath = os.path.join(wd, 's2lib.mojo')
    open(libpath, 'w').write(libsrc)
    _write_runtime_module('s2lib', libsrc)
    dylib = os.path.join(wd, 'libs2.dylib')
    try:
        cas.reset_stats()
        bsd.build([libpath], dylib, link_runtime=True)                      # cold
        cold = dict(cas.stats)
        cas.reset_stats()
        bsd.build([libpath], dylib, link_runtime=True)                      # warm
        warm = dict(cas.stats)
        # Two cached stages per build: the module object AND the final dylib
        # link (dylib-link/<hash>), so a cold build is exactly 2 misses and a
        # warm one exactly 2 hits (no codegen, no link).
        check("stage3: cold build is a miss", cold['misses'] == 2 and cold['hits'] == 0,
              str(cold))
        check("stage3: warm build is a hit (no codegen)", warm['hits'] == 2 and warm['misses'] == 0,
              str(warm))
        # edit source → must miss again (new object content ⇒ new link key too)
        cas.reset_stats()
        open(libpath, 'w').write(libsrc + "\nfn s2_extra() -> Int64:\n    return 0\n")
        bsd.build([libpath], dylib, link_runtime=True)
        check("stage3: source edit invalidates (miss)", cas.stats['misses'] == 2, str(cas.stats))
        # link a client against the dylib and run
        client = ("from s2lib import s2_add, s2_mul\n"
                  "fn main():\n"
                  "    var y = s2_mul(s2_add(40, 2), 2)\n"
                  "    if y == 84:\n"
                  "        var ok = \"s2\\n\"\n"
                  "        var n = external_call[\"write\", Int64](1, ok, 3)\n")
        cC = compile_to_gimple_linked(client)
        cc = os.path.join(wd, 'c2.c'); open(cc, 'w').write(cC)
        co = os.path.join(wd, 'c2.o')
        subprocess.run([GCC, '-fgimple', f'-I{RUNTIME}', '-c', '-o', co, cc], check=True)
        exe = os.path.join(wd, 'c2')
        # The stdlib dylib now includes the runtime (folded in during build).
        # Programs link only the module dylib, with rpath so dyld finds it at load.
        rt = bsd.runtime_dylib()
        link_cmd = [GCC, '-o', exe, co]
        if rt:  # If there's a separate runtime dylib, link it
            link_cmd.extend([rt, f'-Wl,-rpath,{os.path.dirname(rt)}'])
        link_cmd.extend([dylib, f'-Wl,-rpath,{os.path.dirname(dylib)}'])
        subprocess.run(link_cmd, check=True)
        check("stage2: client links the stdlib dylib and runs", _run(exe).stdout.startswith('s2'))
        sz = os.path.getsize(co)
        # 8192 -> 9216 (2026-10-03): the generic-repr family grew by 120 bytes
        # per module again — `_mojo_repr_list`'s element-repr probe
        # (`mojo_list_repr_elem` + its NULL branch), which is what makes a
        # struct stored in a container print through the struct's OWN `__repr__`
        # instead of as a raw pointer decimal. Measured 8144 -> 8264 on this
        # exact client. Same 1024 increment as the two bumps below so the guard
        # keeps its teeth; what it is guarding is unchanged, because the growth
        # is a CALL into the runtime registry and not a body in the client.
        #
        # The real fix for this budget is not another bump: all five
        # always-emitted generic-repr helpers are `static` and never
        # address-registered, and deleting them from this client by hand
        # compiled and linked with no undefined reference at 5208 bytes — 3552
        # of pure per-module dead weight. Gating the cluster on "this module can
        # reach it" is measured and filed as
        # bugs/PERF_generic_repr_helpers_emitted_into_every_module.md.
        #
        # 9216 -> 10240 (2026-10-03, merging the ten bugs4 branches): 9216 ->
        # 9416 on this exact client, +200. The growth is the dict repr's own
        # per-module material, from `bugs4-6`'s one-store-of-every-value-kind
        # work, and it is the same KIND of thing the three entries above record
        # rather than bodies landing in the client: two new `static` helpers in
        # the always-emitted preamble (`_mojo_dict_val_repr`, which asks the
        # dict's recorded repr for a struct slot, and `_mojo_repr_none`), plus
        # three rows in `_mojo_repr_dict`'s value-kind chain (the `kind == 4`
        # None row, the untagged-zero row, and the `kind == 5` struct row, which
        # `_mojo_cat_dict_val` became). Read off the generated C by diffing the
        # emitted `static` set against master's: exactly those two names are
        # new. Bumped by two 1024 increments rather than one, because the rule
        # this ladder follows is "clear the number and keep the teeth": 9416
        # would clear 10240 with 824 to spare, which is the same margin the
        # 11264 entry above was written for.
        check("stage2: client object is tiny (<9KB)", sz < 10240, f"{sz} bytes")
    finally:
        os.remove(os.path.join(RUNTIME, 's2lib.mojo'))


# ── Stage 4: reflection (polyglot C-ABI table) ────────────────────────────
def test_stage4_reflection(wd):
    libsrc = "fn s4_id(a: Int64) -> Int64:\n    return a\n"
    libpath = os.path.join(wd, 's4lib.mojo')
    open(libpath, 'w').write(libsrc)
    dylib = os.path.join(wd, 'libs4.dylib')
    bsd.build([libpath], dylib, link_runtime=True)
    # For testing: the test dylib is now linked against the runtime dylib
    rt = bsd.runtime_dylib()
    from module_loader import read_reflection
    exports = read_reflection(dylib, runtime_dylib=rt)
    check("stage4: __mojo_reflect readable; signature present",
          's4_id' in exports and 'int64_t s4_id (int64_t)' == exports['s4_id']['signature'],
          str(exports.get('s4_id')))
    # a pure-C consumer dlopens, reads the table, and calls by address
    cprog = os.path.join(wd, 'poly.c')
    open(cprog, 'w').write(
        '#include <stdio.h>\n#include <string.h>\n#include <dlfcn.h>\n#include "reflect.h"\n'
        'typedef int64_t (*fn1)(int64_t);\n'
        'int main(void){\n'
        f'  void *h=dlopen("{dylib}",RTLD_NOW); if(!h){{return 2;}}\n'
        '  const MojoReflectTable*t=(const MojoReflectTable*)dlsym(h,"__mojo_reflect");\n'
        '  if(!t||t->magic!=MOJO_REFLECT_MAGIC) return 3;\n'
        '  for(uint32_t i=0;i<t->n_syms;i++) if(!strcmp(t->syms[i].name,"s4_id")){\n'
        '    fn1 f=(fn1)t->syms[i].addr; printf("%lld\\n",(long long)f(99)); return 0; }\n'
        '  return 4; }\n')
    exe = os.path.join(wd, 'poly')
    r = subprocess.run([GCC, f'-I{HERE}', '-o', exe, cprog], capture_output=True, text=True)
    if r.returncode != 0:
        check("stage4: polyglot C consumer builds", False, r.stderr[:200]); return
    check("stage4: pure-C consumer reads table + calls by addr → 99",
          _run(exe).stdout.strip() == '99')


# ── Stage 5: monomorphization (instantiate once, ever) ────────────────────
def test_stage5_monomorphization(wd):
    cas.reset_stats()
    tmpl = "fn s5_id[T](x: T) -> T:\n    return x\n"
    n1, o1, h1, _cpp1 = mm.instantiate(tmpl, {'T': 'Int64'})
    n2, o2, h2, _cpp2 = mm.instantiate(tmpl, {'T': 'Float64'})
    n3, o3, h3, _cpp3 = mm.instantiate(tmpl, {'T': 'Int64'})
    check("stage5: distinct type args → distinct artifacts (2 misses)",
          (not h1) and (not h2) and o1 != o2)
    check("stage5: re-instantiation is a hit (same object)", h3 and o3 == o1)
    # the cached instantiation links + runs
    cmain = os.path.join(wd, 'um.c')
    open(cmain, 'w').write('#include <stdint.h>\n#include <stdio.h>\n'
                           'extern int64_t s5_id_1_T_5_Int64(int64_t);\n'
                           'int main(void){printf("%lld\\n",(long long)s5_id_1_T_5_Int64(7));return 0;}\n')
    exe = os.path.join(wd, 'um')
    subprocess.run([GCC, '-o', exe, cmain, o1, os.path.join(RUNTIME, 'fire_runtime.c')], check=True)
    check("stage5: cached instantiation links + runs", _run(exe).stdout.strip() == '7')


# ── Stage 6: comptime as cached machine code ──────────────────────────────
def test_stage6_comptime(wd):
    cas.reset_stats()
    fact = ("fn s6_fact(n: Int64) -> Int64:\n"
            "    var r: Int64 = 1\n    var i: Int64 = 1\n"
            "    while i <= n:\n        r = r * i\n        i = i + 1\n    return r\n")
    fib = ("fn s6_fib(n: Int64) -> Int64:\n"
           "    if n < 2:\n        return n\n    return s6_fib(n - 1) + s6_fib(n - 2)\n")

    def rfact(n):
        r = 1
        for i in range(1, n + 1):
            r *= i
        return r

    def rfib(n):
        return n if n < 2 else rfib(n - 1) + rfib(n - 2)

    ok_fact = all(comptime.evaluate(fact, 's6_fact', [n]) == rfact(n) for n in (5, 10, 20))
    ok_fib = all(comptime.evaluate(fib, 's6_fib', [n]) == rfib(n) for n in (10, 20))
    check("stage6: comptime loop (fact) as machine code matches reference", ok_fact)
    check("stage6: comptime recursion (fib) as machine code matches reference", ok_fib)
    # compiled once per fn, reused across calls
    check("stage6: compiled once, reused (2 misses, repeats hit)",
          cas.stats['misses'] == 2 and cas.stats['hits'] >= 1, str(cas.stats))


# ── Module-resolution authority: one module per name (our sys.modules) ────
def test_resolution_authority(wd):
    import imports
    a, b = os.path.join(wd, 'pa'), os.path.join(wd, 'pb')
    os.makedirs(a, exist_ok=True); os.makedirs(b, exist_ok=True)
    open(os.path.join(a, 'ridmod.mojo'), 'w').write("fn ridmod_v() -> Int64:\n    return 1\n")
    open(os.path.join(b, 'ridmod.mojo'), 'w').write("fn ridmod_v() -> Int64:\n    return 2\n")
    r = imports.Resolver(path=[a, b])
    e1 = r.resolve('ridmod')
    e2 = r.resolve('ridmod')
    check("authority: one module per name (cached identity)", e1 is e2)
    check("authority: first on path wins (shadow ignored)",
          e1.source == os.path.join(a, 'ridmod.mojo'))
    check("authority: fully-qualified-name symbol prefix",
          imports.ModuleEntry('std.io', None, None, {}).symbol_prefix == 'std_io')
    old = dict(os.environ)
    try:
        os.environ['MOJO_PATH'] = '/_m'; os.environ['PYTHONPATH'] = '/_p'
        p = imports.default_mojo_path()
        check("authority: MOJO_PATH preferred over PYTHONPATH",
              '/_m' in p and '/_p' in p and p.index('/_m') < p.index('/_p'))
    finally:
        os.environ.clear(); os.environ.update(old)

    # “The compiler has no way to see CPython's `Lib/` from an entry file outside it”: `_find` probed
    # only the two `.mojo` spellings, so `$PYTHONPATH` — which the search path
    # DOES honour — was silently useless for pointing at a CPython `Lib/`:
    # `$PYTHONPATH=<checkout>/Lib` left `resolve_source('argparse')` at None.
    # Mojo is a superset of Python, so a `.py` file on the search path is a
    # provider. Asserted through `_find` rather than `resolve()` because
    # `resolve()` also BUILDS a dylib for whatever it finds, which is a
    # different mechanism and not what this is about.
    open(os.path.join(a, 'ridpy.py'), 'w').write("def ridpy_v():\n    return 1\n")
    found, _sh = imports.Resolver(path=[a])._find('ridpy')
    check("authority: a .py file on the search path is a provider",
          found == os.path.join(a, 'ridpy.py'), str(found))
    # Extension is the INNER priority, LOCATION the outer one — the same rule
    # `emit_resolve._module_candidate_paths` applies, and the one that makes
    # `$PYTHONPATH` able to SHADOW rather than merely append.
    open(os.path.join(b, 'ridboth.mojo'), 'w').write("fn ridboth() -> Int64:\n    return 1\n")
    open(os.path.join(b, 'ridboth.py'), 'w').write("def ridboth():\n    return 2\n")
    found, _sh = imports.Resolver(path=[b])._find('ridboth')
    check("authority: a .mojo sibling wins over a .py in the SAME directory",
          found == os.path.join(b, 'ridboth.mojo'), str(found))
    open(os.path.join(a, 'ridboth.py'), 'w').write("def ridboth():\n    return 3\n")
    found, _sh = imports.Resolver(path=[a, b])._find('ridboth')
    check("authority: a closer directory's .py still wins over a further .mojo",
          found == os.path.join(a, 'ridboth.py'), str(found))
    # And the CPython checkout itself: `$PYTHONPATH=<checkout>/Lib` is the case
    # the bug doc names, so the detection is exercised on a real layout.
    cpy = os.path.join(wd, 'cpy')
    os.makedirs(os.path.join(cpy, 'Lib'), exist_ok=True)
    open(os.path.join(cpy, 'Lib', 'os.py'), 'w').write("# marker\n")
    open(os.path.join(cpy, 'Lib', 'ridcargparse.py'), 'w').write("def v():\n    return 1\n")
    os.makedirs(os.path.join(cpy, 'Tools', 'probe'), exist_ok=True)
    import imports as _imp
    detected = _imp.cpython_lib_root(os.path.join(cpy, 'Tools', 'probe'))
    check("authority: a CPython checkout is detected from an entry file in Tools/",
          detected == os.path.realpath(os.path.join(cpy, 'Lib')), str(detected))
    check("authority: the detected Lib is where the resolver then finds its .py",
          imports.Resolver(path=[detected])._find('ridcargparse')[0]
          == os.path.join(detected, 'ridcargparse.py'))
    check("authority: a directory with no checkout above it detects nothing",
          _imp.cpython_lib_root(a) is None, str(_imp.cpython_lib_root(a)))


# ── Elaboration slice 1: generic call → CAS-cached instantiation ──────────
def test_elaboration_generic_call(wd):
    import elaborate
    from gimple_codegen import compile_linked
    tmpl_mod = "fn box[T](x: T) -> T:\n    return x\n"
    el = elaborate.Elaborator()
    i64 = el.elaborate_generic_call(tmpl_mod, 'box', ['Int64'])
    i32 = el.elaborate_generic_call(tmpl_mod, 'box', ['Int32'])
    again = el.elaborate_generic_call(tmpl_mod, 'box', ['Int64'])
    check("elaborate: generic instantiated to a concrete symbol",
          bool(i64) and i64['symbol'] == 'box_1_T_5_Int64' and i64['ret'] == 'int64_t')
    check("elaborate: distinct type args → distinct instantiations",
          i64['object'] != i32['object'] and i32['symbol'] == 'box_1_T_5_Int32')
    check("elaborate: re-instantiation is a CAS hit (same object)",
          again['object'] == i64['object'])
    # codegen wiring: a generic call site emits an extern + concrete call and
    # records the instantiation object on the link line.
    gl = os.path.join(RUNTIME, 'el_genlib.mojo')
    open(gl, 'w').write("fn box[T](x: T) -> T:\n    return x\n")
    try:
        client = "from el_genlib import box\nfn main():\n    var y = box[Int64](42)\n"
        code, dylibs, objects, _cpp, _cxx = compile_linked(client)
        # `len(objects) == 1` and the call names a concrete instantiation.
        # NOTE (2026-10-02): an in-TU instantiation route was built and
        # measured for this shape — see
        # bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md
        # — which would make `objects` 0 and the definition in-TU. It is NOT
        # landed: it regressed five currently-compiling files, because
        # `monomorphize.mangle` keys only on the sorted bracket-parameter
        # values, so two templates selected for the same call can mangle two
        # DIFFERENT functions to one name and gcc reports `conflicting types`.
        # Until that is resolved the `.o` route stays, and this assertion is
        # the contract it has to keep.
        check("elaborate: client emits extern + concrete call + records object",
              'extern int64_t box_1_T_5_Int64' in code and 'box_1_T_5_Int64 (' in code
              and len(objects) == 1)
    finally:
        os.remove(gl)


# ── Elaboration slices 2 & 3: inferred generics + comptime evaluation ─────
def test_elaboration_inference_and_comptime(wd):
    import elaborate
    from gimple_codegen import compile_linked
    # slice 2: infer type args from argument C types
    tmpl = "fn box[T](x: T) -> T:\n    return x\n"
    check("slice2: infer arg C type -> Mojo type arg",
          elaborate.infer_type_args(tmpl, ['int64_t']) == ['Int64'])
    box_mod = os.path.join(RUNTIME, 'el_box.mojo')
    ct_mod = os.path.join(RUNTIME, 'el_ct.mojo')
    open(box_mod, 'w').write(tmpl)
    open(ct_mod, 'w').write("fn fib(n: Int64) -> Int64:\n    if n < 2:\n"
                            "        return n\n    return fib(n - 1) + fib(n - 2)\n")
    try:
        # slice 2 wiring: box(42) with no explicit [..] elaborates
        code, _d, objs, _cpp, _cxx = compile_linked("from el_box import box\n"
                                        "fn main():\n    var y = box(42)\n")
        check("slice2: inferred generic call elaborates (no explicit [..])",
              ('box_1_T_5_Int64' in code or 'box_1_T_3_Int' in code) and len(objs) == 1)
        # slice 3: comptime call to an imported fn resolved at compile time
        src = ("from el_ct import fib\n"
               "fn main():\n"
               "    comptime if fib(10) == 55:\n"
               "        external_call[\"exit\", NoneType](55)\n"
               "    else:\n"
               "        external_call[\"exit\", NoneType](1)\n")
        code2, _d2, _o2, _cpp, _cxx = compile_linked(src)
        check("slice3: comptime call evaluated as machine code; live branch only",
              ('exit (55)' in code2 or '= 55;' in code2) and 'exit (1)' not in code2)
    finally:
        os.remove(box_mod); os.remove(ct_mod)


# ── Elaboration slice 5: generic structs ─────────────────────────────────
def test_elaboration_generic_struct(wd):
    import elaborate
    from gimple_codegen import compile_linked
    mod = ("struct Box[T]:\n    var value: T\n"
           "    fn unbox(self) -> T:\n        return self.value\n")
    info = elaborate.Elaborator().elaborate_generic_struct(mod, 'Box', ['Int64'])
    check("slice5: generic struct instantiated to a concrete type",
          bool(info) and info['name'] == 'Box_1_T_5_Int64'
          and ('value', 'int64_t') in info['fields'])
    check("slice5: struct methods monomorphized",
          ('unbox', 'int64_t', []) in info['methods'])
    bl = os.path.join(RUNTIME, 'el_boxlib.mojo')
    open(bl, 'w').write(mod)
    try:
        code, _d, objs, _cpp, _cxx = compile_linked(
            "from el_boxlib import Box\n"
            "fn main():\n    var b = Box[Int64](42)\n    var y = b.unbox()\n")
        check("slice5: client materializes struct + calls method + records object",
              'typedef struct Box_1_T_5_Int64' in code and 'Box_1_T_5_Int64_unbox' in code
              and len(objs) == 1)
    finally:
        os.remove(bl)


# ── a failed elaboration compiles, but is NOT cached ──────────────────────
def test_elaboration_failure_is_not_cached(wd):
    """What `_ensure_generic_struct` does when the elaborator raises, and what
    `compile_module_to_c_cached` then does with the result.

    The codegen falls back to lowering the construction against the struct's
    UN-ELABORATED template, whose type parameters are unbound and therefore
    typed `int64_t` — so the C is a different program from the one the source
    says. That fallback is load-bearing and stays: turning it into a refusal
    was measured on the stdlib's own `std/` subtree (252 files) and took six
    currently-compiling files to a hard failure, `List[String]` in
    std/os/os.mojo among them.

    What must not happen is that such a module reaches the content-addressed
    store. One swallowed failure published a wrong `.ci` under the current
    compiler fingerprint, and `test/iter/test_ref_iteration.mojo` then reached
    a gate as an UNEXPECTED `stdlib-syntax` failure — gcc's `request for
    member 'value' in something not a structure or union`, on a line about
    iterators — an hour after the transient that caused it had ended. The
    condition had ended; the artifact had not.

    So: forced failure here, and the two properties are that the compile still
    succeeds (no new refusal) and that a second `compile_module_to_c_cached`
    of the same inputs REBUILDS rather than replaying a published artifact.
    """
    import elaborate
    from gimple_codegen import compile_linked
    mod = ("struct Box[T]:\n    var value: T\n"
           "fn unbox(self) -> T:\n        return self.value\n")
    bl = os.path.join(RUNTIME, 'el_boxfail.mojo')
    open(bl, 'w').write(mod)
    client = ("from el_boxfail import Box\n"
              "fn main():\n    var b = Box[Int64](42)\n"
              "    var y = b.unbox()\n    print(y)\n")
    real_instantiate = mm.instantiate
    reason = 'forced: the instantiation could not be built'

    def _boom(*a, **k):
        raise RuntimeError(reason)

    try:
        mm.instantiate = _boom
        try:
            code, _d, objs, _cpp, _cxx = compile_linked(client)
            check("elaborate: a failed struct elaboration still compiles "
                  "(the template fallback is load-bearing)", True)
            check("elaborate: ... and the fallback is the un-elaborated one",
                  'Box_1_T_5_Int64' not in code,
                  "the instantiation went through despite the failure")
        except Exception as e:
            check("elaborate: a failed struct elaboration still compiles "
                  "(the template fallback is load-bearing)", False,
                  f"{type(e).__name__}: {str(e)[:200]}")
        # Now the cache contract, on the entry point where the publish
        # decision is made. It has to be a MISS, because that is the only
        # path that builds: start from no artifact at all, build through the
        # forced failure, and look at what the store holds afterwards.
        path = os.path.join(RUNTIME, 'el_boxfail_client.mojo')
        open(path, 'w').write(client)
        csrc = open(path).read()
        bsd._stdlib_compile_cache.clear()
        key = cas.stdlib_compile_key(csrc, path, 'el_boxfail_client')
        stale = cas.lookup(key, '.ci')
        if stale:
            os.unlink(stale)          # a MISS is the whole point; see above
        try:
            t1 = bsd.compile_module_to_c_cached(csrc, path, 'el_boxfail_client')
            check("elaborate: a module built through a failed elaboration is "
                  "NOT published",
                  cas.lookup(key, '.ci') is None,
                  "the degraded artifact reached the content-addressed store")
            check("elaborate: ... and the reason for the degradation is "
                  "reported rather than swallowed",
                  any('could not be built' in d
                      for d in bsd.last_degradations()),
                  f"last_degradations() = {bsd.last_degradations()[:2]}")
            check("elaborate: ... and the degradation names the struct, its "
                  "type args and its source",
                  any('Box[Int64]' in d and 'el_boxfail.mojo' in d
                      for d in bsd.last_degradations()),
                  f"last_degradations() = {bsd.last_degradations()[:2]}")
            bsd._stdlib_compile_cache.clear()
            misses = cas.stats['misses']
            t2 = bsd.compile_module_to_c_cached(csrc, path, 'el_boxfail_client')
            check("elaborate: ... so the next run REBUILDS it rather than "
                  "replaying a wrong artifact",
                  cas.stats['misses'] == misses + 1 and t1 == t2,
                  f"misses did not advance: {cas.stats['misses']} vs {misses}")
        finally:
            stale = cas.lookup(key, '.ci')
            if stale:
                os.unlink(stale)
            os.remove(path)
    finally:
        mm.instantiate = real_instantiate
        os.remove(bl)


# ── Elaboration slice 4: overload resolution ─────────────────────────────
def test_elaboration_overload(wd):
    import elaborate
    from gimple_codegen import compile_linked
    mod = ("fn pick(x: Int64) -> Int64:\n    return x + 100\n\n"
           "fn pick(x: Int32) -> Int64:\n    return 7\n")
    check("slice4: all overloads extracted", len(elaborate.extract_overloads(mod, 'pick')) == 2)
    el = elaborate.Elaborator()
    i64 = el.elaborate_overload_call(mod, 'pick', ['int64_t'])
    i32 = el.elaborate_overload_call(mod, 'pick', ['int32_t'])
    check("slice4: overload selected by argument type",
          i64['symbol'] == 'pick__1_0_5_Int64'
          and i32['symbol'] == 'pick__1_0_5_Int32'
          and i64['object'] != i32['object'])
    ol = os.path.join(RUNTIME, 'el_ovlib.mojo')
    open(ol, 'w').write(mod)
    try:
        code, _d, objs, _cpp, _cxx = compile_linked(
            "from el_ovlib import pick\n"
            "fn main():\n    var a: Int64 = 5\n    var y = pick(a)\n")
        check("slice4: client calls the signature-mangled overload",
              'pick__1_0_5_Int64' in code and len(objs) == 1)
    finally:
        os.remove(ol)


# ── Elaboration slice 6: traits / conformance bound-checking ─────────────
def test_elaboration_trait_conformance(wd):
    import elaborate
    # A trait with one required method, a conforming type, a non-conforming
    # type, and generics (fn + struct) bounded by the trait.
    mod = (
        "trait Doubler:\n"
        "    fn double(self) -> Int64:\n"
        "        ...\n\n"
        "struct Num:\n"
        "    var v: Int64\n"
        "    fn double(self) -> Int64:\n"
        "        return self.v + self.v\n\n"
        "struct Bad:\n"
        "    var v: Int64\n"
        "    fn nope(self) -> Int64:\n"
        "        return self.v\n\n"
        "fn run[T: Doubler](x: T) -> Int64:\n"
        "    return x.double()\n\n"
        "struct Box[T: Doubler]:\n"
        "    var item: T\n"
        "    fn run(self) -> Int64:\n"
        "        return self.item.double()\n")
    # Primitives: bound parsing, trait extraction, conformance verdicts.
    check("slice6: trait bound parsed from generic head",
          elaborate.parse_bounds("fn run[T: Doubler](x: T) -> Int64:") == {'T': 'Doubler'})
    check("slice6: trait required methods extracted",
          elaborate.extract_trait(mod, 'Doubler') == [('double', [], 'Int64')])
    ok_num, miss_num = elaborate.check_conformance(mod, 'Num', 'Doubler')
    ok_bad, miss_bad = elaborate.check_conformance(mod, 'Bad', 'Doubler')
    check("slice6: conforming type satisfies the trait", ok_num and not miss_num)
    check("slice6: non-conforming type is rejected with a reason",
          (not ok_bad) and any('double' in m for m in miss_bad))

    el = elaborate.Elaborator()
    # Conforming: bounded generic fn + struct instantiate end-to-end (CAS).
    fi = el.elaborate_generic_call(mod, 'run', ['Num'])
    si = el.elaborate_generic_struct(mod, 'Box', ['Num'])
    check("slice6: bounded generic fn instantiates for a conforming type",
          bool(fi) and fi['symbol'] == 'run_1_T_3_Num')
    check("slice6: bounded generic struct instantiates for a conforming type",
          bool(si) and si['name'] == 'Box_1_T_3_Num'
          and ('run', 'int64_t', []) in si['methods'])
    # Non-conforming: a clear ConformanceError, for both fn and struct.
    raised_fn = raised_struct = False
    try:
        el.elaborate_generic_call(mod, 'run', ['Bad'])
    except elaborate.ConformanceError:
        raised_fn = True
    try:
        el.elaborate_generic_struct(mod, 'Box', ['Bad'])
    except elaborate.ConformanceError:
        raised_struct = True
    check("slice6: bounded generic fn rejects a non-conforming type", raised_fn)
    check("slice6: bounded generic struct rejects a non-conforming type", raised_struct)
    # Unknown/unbounded bounds never block (additive, best-effort).
    nb = el.elaborate_generic_call("fn id[T](x: T) -> T:\n    return x\n", 'id', ['Bad'])
    check("slice6: unbounded type parameter is not blocked", bool(nb))


# ── Reflected concrete struct type import (the real-stdlib distribution path) ─
def test_reflected_struct_import(wd):
    """A client imports a *concrete, already-compiled* struct type from a module
    dylib. The type's layout + methods cross the boundary via the reflection
    table (MOJO_SYM_TYPE kind 3 + MOJO_SYM_METHOD kind 1) — NOT inlined source.
    The client materializes the layout from reflection, constructs the type, and
    calls its methods linked from the dylib. This is the real-stdlib path (type +
    method bodies live in the dylib); it complements slice 5, which materializes a
    *generic* struct from source at the call site."""
    import imports
    from gimple_codegen import compile_linked
    mod = ("struct Counter:\n"
           "    var n: Int64\n"
           "    fn __init__(out self, start: Int64):\n"
           "        self.n = start\n"
           "    fn increment(self) -> Int64:\n"
           "        return self.n + 1\n"
           "    fn value(self) -> Int64:\n"
           "        return self.n\n")
    # Reflection emitter: a concrete struct → one TYPE entry (layout) + one
    # METHOD entry per method, with the `Struct_method` C symbol.
    exps = {e['name']: e for e in reflect.collect_exports_src(mod)}
    check("reflect: concrete struct emits a TYPE (kind 3) layout entry",
          exps.get('Counter', {}).get('kind') == reflect.SYM_TYPE
          and 'int64_t n;' in exps['Counter']['signature'])
    check("reflect: each method emits a METHOD (kind 1) entry with self pointer",
          exps.get('Counter.increment', {}).get('kind') == reflect.SYM_METHOD
          and exps['Counter.increment']['signature']
              == 'int64_t Counter_increment (Counter *)')

    libpath = os.path.join(RUNTIME, 'rs_cnt.mojo')
    open(libpath, 'w').write(mod)
    try:
        imports.reset_resolver()
        # The resolver builds the dylib and reads its reflection table. The struct
        # type is materialized from kind 3 — never from inlined source.
        entry = imports.resolve('rs_cnt')
        check("reflect: importer reads the struct type from the dylib reflection",
              bool(entry.dylib) and entry.exports.get('Counter', {}).get('kind') == 3)

        client = ("from rs_cnt import Counter\n"
                  "fn main():\n"
                  "    var c = Counter(41)\n"
                  "    var v = c.increment()\n"
                  "    var w = c.value()\n"
                  "    if v == 42:\n"
                  "        if w == 41:\n"
                  "            var ok = \"rs\\n\"\n"
                  "            var n = external_call[\"write\", Int64](1, ok, 3)\n")
        code, dylibs, _objs, _cpp, _cxx = compile_linked(client)
        # The dylib compiled this module with a real module_name
        # (module_loader.module_name_for_path on runtime/rs_cnt.mojo ->
        # 'rs_cnt'), so its methods are module-qualified C symbols — the
        # client's extern decl must reference that exact qualified name
        # (see GimpleGen._struct_method_qualifier/_struct_method_csym and
        # _register_reflected_struct, which reads the qualifier straight out
        # of the dylib's own advertised reflection signature).
        check("reflect: client materializes the layout + method externs (no body)",
              'typedef struct Counter' in code
              and 'extern int64_t rs_cnt_Counter_increment (Counter *);' in code
              and 'rs_cnt_Counter_increment (Counter *self)' not in code
              and len(dylibs) == 1)

        cc = os.path.join(wd, 'rs.c'); open(cc, 'w').write(code)
        co = os.path.join(wd, 'rs.o')
        subprocess.run([GCC, '-fgimple', f'-I{RUNTIME}', '-c', '-o', co, cc], check=True)
        exe = os.path.join(wd, 'rs')
        # The stdlib dylib includes the runtime, so only link the module dylibs
        rt = bsd.runtime_dylib()
        link_cmd = [GCC, '-o', exe, co]
        if rt:  # If there's a separate runtime dylib, link it
            link_cmd.extend([rt, f'-Wl,-rpath,{os.path.dirname(rt)}'])
        link_cmd.extend(dylibs)
        link_cmd.extend([f'-Wl,-rpath,{os.path.dirname(d)}' for d in dylibs])
        subprocess.run(link_cmd, check=True)
        check("reflect: client links the dylib's struct methods and runs",
              _run(exe).stdout.startswith('rs'))
        sz = os.path.getsize(co)
        # Budget covers the always-emitted-per-module generic-repr helpers
        # (_mojo_repr_list/_dict/_set, _mojo_dispatch_repr, etc.) — bumped
        # from 8192 when _mojo_repr_set was added alongside the existing
        # list/dict repr helpers.
        # 9216 -> 10240 (2026-09-26): the same family grew again, by two
        # unconditional per-module forward decls plus their definitions —
        # `_mojo_generic_elem_repr` and `_mojo_repr_pair`
        # (module_gen.py:459-460, emitted for EVERY module regardless of
        # whether it needs them). The client object measured 9320 bytes,
        # 104 over the old line. This is the assertion doing its job: a
        # client that is NOT tiny means bodies are landing in the client
        # instead of the dylib, which is the real bug this guards. Raised
        # by the same 1024 increment as the previous bump rather than to
        # just clear 9320, so the guard still has teeth; if a future
        # change pushes this past 10240, that is a genuine finding about
        # what is being emitted per module and wants a real look, not
        # another bump.
        #
        # 10240 -> 11264 (2026-10-03): that real look, done. Measured 10120 ->
        # 10432 on this exact client, +120 of it the same
        # `_mojo_repr_list` element-repr probe as stage2's, and +192 the
        # per-struct `_mojo_elem_repr_<Sn>` shim plus its forward decls, which
        # is emitted once per struct in `reflect_emitted`. Both are CALLS into
        # the runtime (`mojo_list_repr_elem`, the struct's own `__repr__`) and
        # not bodies in the client, so the invariant this guards — a client
        # that is not tiny means bodies are landing in it instead of the
        # dylib — is intact with ~7 KB to spare against a client whose own
        # code is a few hundred bytes.
        #
        # The look also found the actual fix for the budget, and it is not a
        # bump: all five always-emitted helpers are `static`, mutually
        # referenced and never address-registered, and hand-deleting them from
        # this client compiled and linked with no undefined reference at 5208
        # bytes. Filed as bugs/PERF_generic_repr_helpers_emitted_into_every_
        # module.md; not landed with the merge because its failure mode is a
        # link error on the self-host closure, which only `make bootstrap` can
        # clear.
        #
        # 11264 -> 12288 (2026-10-03, merging the ten bugs4 branches), for
        # stage2's reason and by the same two increments: this client carries
        # the dict-repr additions too plus the per-struct
        # `_mojo_elem_repr_<Sn>` shims `reflect_emitted` names, and 11600 needs
        # a ceiling above it that still has teeth (11264 would not clear it at
        # all). The invariant is unchanged: what grew is the always-emitted
        # generic-repr preamble, which is CALLS into the runtime plus the small
        # walkers above it, not bodies belonging to this client.
        check("reflect: client object is tiny — bodies live in the dylib",
              sz < 12288, f"{sz} bytes")
    finally:
        os.remove(libpath)


# ── ABI: module-qualified struct method symbols (cross-module collision) ──
def test_module_qualified_struct_symbols(wd):
    """Two DIFFERENT modules define a same-named struct with a same-named
    method (the real bug: std/utils/_ansi.mojo's `struct Color` and
    std/gpu/host/_tracing.mojo's `struct Color`, both compiled into one
    libmojostdlib.dylib — see STDLIB-BUGS.md and ABI.md's module-qualifier
    section). Compiled together into ONE shared dylib via build_stdlib_dylib's
    own build() (mirroring the real stdlib build, not imports.py's
    one-dylib-per-module resolver, which never puts two modules in the same
    dylib and so never exercises this collision), both structs' methods must
    get DISTINCT, module-qualified C symbols — no _localize_symbols demotion,
    and each struct's exported symbol independently callable with its own
    correct behavior (not silently resolving to the other module's copy, the
    confirmed-wrong reflection-table bug this whole change fixes)."""
    src_a = ("struct Shape:\n"
             "    var n: Int64\n"
             "    fn __init__(out self, n: Int64):\n"
             "        self.n = n\n"
             "    fn area(self) -> Int64:\n"
             "        return self.n * 10\n")
    src_b = ("struct Shape:\n"
             "    var n: Int64\n"
             "    fn __init__(out self, n: Int64):\n"
             "        self.n = n\n"
             "    fn area(self) -> Int64:\n"
             "        return self.n * 100\n")
    path_a = os.path.join(wd, 'coll_a.mojo'); open(path_a, 'w').write(src_a)
    path_b = os.path.join(wd, 'coll_b.mojo'); open(path_b, 'w').write(src_b)
    dylib = os.path.join(wd, 'libcoll.dylib')
    gcc = GCC
    bsd.build([path_a, path_b], dylib, link_runtime=True, use_cache=False)
    # nm reports raw linker symbols, which carry macOS's own leading
    # underscore convention (e.g. '_coll_a_Shape_area') — strip it so the
    # assertions read as plain C identifiers, matching what
    # GimpleGen._struct_method_csym itself computes.
    syms = {s.lstrip('_') if s.startswith('_') and not s.startswith('__') else s
            for s in bsd._defined_symbols(gcc, dylib)}
    check("abi: both modules' Shape.area get distinct qualified symbols",
          'coll_a_Shape_area' in syms and 'coll_b_Shape_area' in syms
          and 'Shape_area' not in syms,
          str(sorted(s for s in syms if 'Shape' in s)))
    check("abi: both modules' Shape.__init__ get distinct qualified symbols",
          'coll_a_Shape___init__' in syms and 'coll_b_Shape___init__' in syms,
          str(sorted(s for s in syms if 'Shape' in s)))

    # Reflection table: each module's own METHOD entry must advertise ITS
    # OWN qualified symbol, not silently point at the other module's (the
    # confirmed-wrong bug emit_table_c's string-only dedup used to hide).
    exps_a = {e['name']: e for e in reflect.collect_exports_src(src_a, module_prefix='coll_a')}
    exps_b = {e['name']: e for e in reflect.collect_exports_src(src_b, module_prefix='coll_b')}
    check("abi: reflection entries are independently qualified per module",
          'coll_a_Shape_area' in exps_a['Shape.area']['signature']
          and 'coll_b_Shape_area' in exps_b['Shape.area']['signature'])

    # End-to-end: a client importing EACH module's Shape independently (no
    # `as` alias — aliasing an imported struct is a separate, pre-existing
    # gap where the client's call sites mangle against the ALIAS instead of
    # the struct's real defining name, unrelated to this qualification fix)
    # gets that module's own, correct, distinct behavior.
    import imports
    from gimple_codegen import compile_linked
    for modname, expected in (('coll_a', 30), ('coll_b', 300)):
        imports.reset_resolver(path=[wd])
        client = (f"from {modname} import Shape\n"
                  "fn main():\n"
                  "    var s = Shape(3)\n"
                  "    var r = s.area()\n"
                  f"    if r == {expected}:\n"
                  "        var ok = \"qc\\n\"\n"
                  "        var n = external_call[\"write\", Int64](1, ok, 3)\n")
        code, dylibs, _objs, _cpp, _cxx = compile_linked(client)
        cc = os.path.join(wd, f'qc_{modname}.c'); open(cc, 'w').write(code)
        co = os.path.join(wd, f'qc_{modname}.o')
        subprocess.run([GCC, '-fgimple', f'-I{RUNTIME}', '-c', '-o', co, cc], check=True)
        exe = os.path.join(wd, f'qc_{modname}')
        rt = bsd.runtime_dylib()
        link_cmd = [GCC, '-o', exe, co]
        if rt:
            link_cmd.extend([rt, f'-Wl,-rpath,{os.path.dirname(rt)}'])
        link_cmd.extend(dylibs)
        link_cmd.extend([f'-Wl,-rpath,{os.path.dirname(d)}' for d in dylibs])
        subprocess.run(link_cmd, check=True)
        check(f"abi: client calling {modname}'s Shape.area() gets its own correct value",
              _run(exe).stdout.startswith('qc'))


def test_def_overload_not_dangling_export(wd):
    """BUG-2026-036: a same-file overloaded free function declared with `def`
    (not `fn`) used to still get advertised as a normal reflection export,
    even though gen_module's own "overloaded top-level functions ... can't be
    emitted as distinct C symbols, drop them here" pass (gimple_codegen.py's
    gen_module) never compiles a body for it. reflect.collect_exports_src's
    own mirror of that same drop condition only matched `fn`, not `def` — so
    the two forms disagreed, and the reflection table forward-declared +
    took the address of a symbol with zero definitions anywhere in the dylib
    (`extern void CUDA_0c85c9();` with nothing behind it). That's harmless at
    static link time (production dylibs use `-undefined dynamic_lookup`) but
    crashes EVERY dlopen of the dylib at runtime — real repro was
    std/gpu/host/_nvidia_cuda.mojo's two `def CUDA(...)` overloads, which made
    every single `fire.py` interpreter/compiler invocation crash at startup
    (dyld: symbol not found in flat namespace), regardless of the input file."""
    src = ("def CUDA(x: Int64) -> Int64:\n"
           "    return x + 1\n"
           "def CUDA(x: Float64) -> Float64:\n"
           "    return x + 2.0\n"
           "def CUDA_single(x: Int64) -> Int64:\n"
           "    return x + 3\n")
    exports = {e['name'] for e in reflect.collect_exports_src(src)}
    check("def-overload: both CUDA overloads are excluded from exports",
          'CUDA' not in exports, str(exports))
    check("def-overload: the non-overloaded sibling function still exports",
          'CUDA_single' in exports, str(exports))

    path = os.path.join(wd, 'cuda_like.mojo'); open(path, 'w').write(src)
    dylib = os.path.join(wd, 'libcudalike.dylib')
    bsd.build([path], dylib, link_runtime=True, use_cache=False)
    syms = bsd._defined_symbols(GCC, dylib)
    check("def-overload: no CUDA_<hash> extern/address survives into the dylib",
          not any(s.lstrip('_').startswith('CUDA_0') or s.lstrip('_') == 'CUDA'
                  for s in syms if 'CUDA_single' not in s),
          str(sorted(s for s in syms if 'CUDA' in s)))
    # Loadable — the actual regression: a stale export used to abort dlopen
    # for every user of the dylib, not just callers of the broken function.
    import ctypes
    ctypes.CDLL(dylib)
    check("def-overload: dylib with a dropped def-overload still dlopen()s", True)


def test_cross_module_free_func_mangling_agrees(wd):
    """BUG-2026-036's deeper blocker: a leading-underscore free function
    (never a reflect.py export — `collect_exports_src` excludes any
    underscore-prefixed name) taking a parameter of a type neither the
    definer's own file nor a same-batch sibling can resolve to anything
    concrete used to get TWO DIFFERENT overload-mangled C symbols depending
    on which file's codegen computed it.

    build_stdlib_dylib.build() compiles every module "fully independent —
    no shared state" (its own docstring): the DEFINING module resolves the
    unresolved parameter type through gimple_codegen's own canonical
    `_mojo_type` (unknown-type default: 'int64_t'), while an IMPORTING
    module can't reflect off a dylib for a leading-underscore symbol (none
    was ever exported) and falls back to module_loader.py's `load_module` —
    which used to carry its OWN separate, independently-wrong type-to-C
    converter (unknown-type default: 'int', a 32-bit C int) instead of
    reusing the codegen's. Two different default C types for the exact same
    unresolved parameter ⇒ two different md5 hashes ⇒ two different mangled
    symbols for what is, at the C level, one single function.

    Confirmed real repro: std/builtin/coroutine.mojo's
    `_coro_destroy_fn(handle: AnyCoroutine)` compiled standalone to
    `_coro_destroy_fn_0c85c9` (int64_t default), while
    std/gpu/host/device_context.mojo's import of it (passed as a bare
    function-pointer value, never called — exercising gimple_codegen.py's
    Name-lowering "C function name used as a value" path, ~line 5151, which
    calls `_func_csym`/`_overload_suffix`) expected `_coro_destroy_fn_fa7153`
    instead — an orphaned reference that crashed `dlopen` on EVERY fire.py
    invocation, not just ones that use coroutines.

    This is the minimal shape of that same bug: `corolike.mojo` (placed
    under runtime/ so module_loader resolves the bare module name, matching
    how a leading-underscore symbol with no dylib yet actually gets looked
    up) defines a leading-underscore function taking a never-declared type
    name (`Widget` — nothing anywhere makes it a real struct, mirroring how
    `AnyCoroutine` never resolves to a concrete C type either); a sibling
    module imports it and merely references it as a value. Both are compiled
    in the SAME build() batch (so neither has a dylib to reflect off of yet,
    same as the real stdlib build), then linked into one dylib. Asserts the
    two files agree on exactly one mangled symbol and the dylib dlopen()s."""
    def_src = ("def _touch(h: Widget):\n"
               "    pass\n"
               "def _touch_sibling(x: Int64) -> Int64:\n"
               "    return x + 1\n")
    def_path = _write_runtime_module('corolike', def_src)
    use_src = ("from corolike import _touch\n\n"
               "def call_it() -> Int64:\n"
               "    external_call[\"puts\", Int64](_touch)\n"
               "    return 0\n")
    use_path = os.path.join(wd, 'use_corolike.mojo')
    open(use_path, 'w').write(use_src)
    try:
        dylib = os.path.join(wd, 'libcorolike.dylib')
        bsd.build([def_path, use_path], dylib, link_runtime=True, use_cache=False)
        syms = bsd._defined_symbols(GCC, dylib)
        touch_syms = sorted(s for s in syms if 'touch' in s and 'sibling' not in s)
        check("cross-module mangling: exactly one _touch symbol is defined",
              len(touch_syms) == 1, str(touch_syms))
        import ctypes
        ctypes.CDLL(dylib)
        check("cross-module mangling: dylib with a cross-file reference to "
              "an underscore-prefixed free function still dlopen()s", True)
    finally:
        os.remove(def_path)


def test_sb1_cross_module_same_c_param_overload_mangling(wd):
    """STDLIB-BUGS.md SB-1: two modules' same-named free-function overloads that
    box down to the exact same C parameter TYPE (not just an unresolved one, as
    test_cross_module_free_func_mangling_agrees above covers) used to collide at
    link, because overload_suffix_for hashes only the collapsed C parameter-type
    list — 'int64_t' hashes the same no matter which Mojo-level function produced
    it. The historically-discovered instance was math.abs(SIMD) vs
    complex.abs(Complex), both boxing to a lone int64_t; math.abs is generic
    (`def abs[T: Absable](...)`) in the current stdlib snapshot and no longer
    reproduces the collision on its own (generics are never reflection-exported
    free functions), so this test reproduces the underlying shape directly and
    durably: two sibling modules each define `def sb1_scale(x: Int64) -> Int64`
    (Int64 always boxes to plain int64_t — no exotic/unresolved type needed) with
    DIFFERENT, independently-checkable bodies. Fixed by module-qualifying every
    free function's mangled C symbol with its owning module's name
    (gimple_codegen._func_qualifier / reflect._func_export_csym's module_prefix)
    — the same mechanism struct methods already used (_struct_method_qualifier),
    now extended to free functions."""
    import re
    import imports
    src_a = ("def sb1_scale(x: Int64) -> Int64:\n"
             "    if x < 0:\n"
             "        return -x\n"
             "    return x + 1000\n")
    src_b = ("def sb1_scale(x: Int64) -> Int64:\n"
             "    if x < 0:\n"
             "        return -x - 2000\n"
             "    return x + 2000\n")
    path_a = os.path.join(wd, 'sb1_mod_a.mojo'); open(path_a, 'w').write(src_a)
    path_b = os.path.join(wd, 'sb1_mod_b.mojo'); open(path_b, 'w').write(src_b)

    # reflect.py and gimple_codegen.py must independently compute the SAME
    # qualified symbol for each module's own definition (the whole point of
    # this mangling scheme: codegen and the reflection-table emitter agree).
    from gimple_codegen import GimpleGen
    from fire_compiler import py_tokenize, Parser
    for path, name, src in ((path_a, 'sb1_mod_a', src_a), (path_b, 'sb1_mod_b', src_b)):
        gen = GimpleGen(emit_entry_points=False, module_name=name)
        gen._current_filename = path
        c = gen.gen_module(Parser(py_tokenize(src)).parse_module())
        codegen_syms = set(re.findall(r'\b(\w*sb1_scale\w*)\s*\(', c))
        refl_syms = {reflect.export_csym(e).lstrip('_')
                     for e in reflect.collect_exports_src(src, module_prefix=name)
                     if e['name'] == 'sb1_scale'}
        check(f"SB-1: {name} codegen and reflect.py agree on the qualified symbol",
              codegen_syms == refl_syms, f"{codegen_syms} vs {refl_syms}")

    dylib = os.path.join(wd, 'libsb1.dylib')
    bsd.build([path_a, path_b], dylib, link_runtime=True, use_cache=False)
    syms = bsd._defined_symbols(GCC, dylib)
    scale_syms = sorted(s for s in syms if 'scale' in s)
    check("SB-1: both modules' sb1_scale get DISTINCT defined symbols",
          len(scale_syms) == 2, str(scale_syms))

    # Real compile+link+run: a client importing EACH module's sb1_scale
    # independently gets that module's own, correct, DIFFERENT behavior — not
    # one silently overwriting/aliasing the other.
    from gimple_codegen import compile_linked
    for modname, x, expected in (('sb1_mod_a', -5, 5), ('sb1_mod_b', -5, -1995)):
        imports.reset_resolver(path=[wd])
        client = (f"from {modname} import sb1_scale\n"
                  "fn main():\n"
                  f"    var r = sb1_scale({x})\n"
                  f"    if r == {expected}:\n"
                  "        var ok = \"qc\\n\"\n"
                  "        var n = external_call[\"write\", Int64](1, ok, 3)\n")
        code, dylibs, _objs, _cpp, _cxx = compile_linked(client)
        cc = os.path.join(wd, f'sb1c_{modname}.c'); open(cc, 'w').write(code)
        co = os.path.join(wd, f'sb1c_{modname}.o')
        subprocess.run([GCC, '-fgimple', f'-I{RUNTIME}', '-c', '-o', co, cc], check=True)
        exe = os.path.join(wd, f'sb1c_{modname}')
        rt = bsd.runtime_dylib()
        link_cmd = [GCC, '-o', exe, co]
        if rt:
            link_cmd.extend([rt, f'-Wl,-rpath,{os.path.dirname(rt)}'])
        link_cmd.extend(dylibs)
        link_cmd.extend([f'-Wl,-rpath,{os.path.dirname(d)}' for d in dylibs])
        subprocess.run(link_cmd, check=True)
        check(f"SB-1: client calling {modname}'s sb1_scale() gets its own correct value",
              _run(exe).stdout.startswith('qc'))


def test_sb1_mojo_build_cli_wrapper_modules(wd):
    """SB-1 follow-up (independent verification found a real bug in the first
    fix, bf96f55): `fire.py build`'s actual CLI path (do_imports=True inline
    compilation, gimple_codegen.compile_to_gimple / build_executable in
    fire.py) is a COMPLETELY DIFFERENT code path from build_stdlib_dylib.py's
    per-module-standalone-compile pipeline the first SB-1 test above
    exercises — its GimpleGen instances are nested and share state
    (_compile_imported_module), which the standalone pipeline never does.
    That sharing hid two real, independently-discovered miscompiles the
    first fix's own test suite could not have caught:

    1. `_imported_func_home` was a single dict SHARED across every nested
       temp_gen, keyed by bare function name via setdefault: two sibling
       modules each defining the SAME bare free-function name (exactly what
       SB-1 is about) — here `alpha_module.sb1_probe_t` / `beta_module.
       sb1_probe_t` — caused the SECOND module's own local definition to be
       silently emitted under the FIRST module's qualifier, a hard
       redefinition compile error (`redefinition of
       'alpha_module_sb1_probe_t_...'`). Fixed by checking
       _local_top_level_func_names (this exact compile's own top-level
       FunctionDefs) BEFORE consulting the shared dict in _func_qualifier.
    2. Even with (1) fixed, a SEPARATE bug remained for CALL SITES: two
       sibling WRAPPER modules (alpha_wrapper.mojo doing `from alpha_module
       import sb1_probe_t`, beta_wrapper.mojo doing `from beta_module import
       sb1_probe_t`, both transitively imported into one program) each
       correctly know their OWN function's true home from their OWN
       FromImportStmt — but the shared dict's first-registered-wins
       semantics meant beta_wrapper's call site silently CALLED
       alpha_module's sb1_probe_t instead of beta_module's: a real, silent,
       WRONG-RESULT miscompile with no build error at all (worse than (1)).
       Fixed by giving each GimpleGen instance its OWN private
       _own_imported_func_home dict (never shared across nested temp_gens),
       checked ahead of the shared fallback.

    This test reproduces (2) — the wrapper-module shape, chosen because it
    is fully achievable end-to-end through fire.py build's REAL CLI (unlike
    the coordinator's original top-level-ALIASED-import repro, which hits a
    SEPARATE, independently-confirmed-pre-existing bug in aliased free-
    function-value call sites — present on vanilla master before ANY SB-1
    work, unrelated to overload-mangling qualification, and explicitly out
    of scope here) — and asserts a REAL compile+link+run through the actual
    `python3 fire.py build <file>` subprocess gets each sibling module's own,
    distinct, correct result."""
    src_alpha_module = "def sb1_probe_t(x: Int64) -> Int64:\n    return x + 111\n"
    src_beta_module = "def sb1_probe_t(x: Int64) -> Int64:\n    return x + 222\n"
    src_alpha_wrapper = ("from alpha_module import sb1_probe_t\n\n"
                          "def call_alpha(x: Int64) -> Int64:\n"
                          "    return sb1_probe_t(x)\n")
    src_beta_wrapper = ("from beta_module import sb1_probe_t\n\n"
                         "def call_beta(x: Int64) -> Int64:\n"
                         "    return sb1_probe_t(x)\n")
    src_main = ("from alpha_wrapper import call_alpha\n"
                "from beta_wrapper import call_beta\n\n"
                "def main() raises:\n"
                "    print(call_alpha(1))\n"
                "    print(call_beta(1))\n")

    proj = os.path.join(wd, 'sb1_cli_wrappers')
    os.makedirs(proj, exist_ok=True)
    for fname, src in (('alpha_module.mojo', src_alpha_module),
                        ('beta_module.mojo', src_beta_module),
                        ('alpha_wrapper.mojo', src_alpha_wrapper),
                        ('beta_wrapper.mojo', src_beta_wrapper),
                        ('main.mojo', src_main)):
        with open(os.path.join(proj, fname), 'w') as f:
            f.write(src)

    exe = os.path.join(proj, 'main')
    # A BUILD, not a run, and the timeout is the file's own exec budget rather
    # than a bare literal: this call escaped as an uncaught TimeoutExpired and
    # took the whole file with it, so every check after this one was silently
    # not run — which is what happened in a `modcache` run alongside four other
    # suites at -j18 (2026-10-02, 429 s of wall clock, this build at 120.0 s).
    # A timeout here is LOAD, not a wrong answer, and it has to read as a
    # failed check rather than as the end of the file — the same reasoning, and
    # the same `_TIMED_OUT_PREFIX`, as `_run` above.
    try:
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, 'fire.py'), 'build', 'main.mojo'],
            cwd=proj, capture_output=True, text=True,
            timeout=EXE_TIMEOUT_S * 2)
    except subprocess.TimeoutExpired as e:
        r = subprocess.CompletedProcess(
            e.cmd, -1, stdout='', stderr=f'{_TIMED_OUT_PREFIX} after '
            f'{EXE_TIMEOUT_S * 2}s building main.mojo')
    check("SB-1 (fire.py build CLI): two sibling modules' same-named free "
          "function build without a redefinition error",
          'redefinition of' not in r.stderr and 'redefinition of' not in r.stdout,
          r.stdout + r.stderr)
    check("SB-1 (fire.py build CLI): build succeeds and produces an executable",
          r.returncode == 0 and os.path.exists(exe), r.stdout + r.stderr)
    if os.path.exists(exe):
        run = subprocess.run([exe], capture_output=True, text=True,
                             timeout=EXE_TIMEOUT_S)
        check("SB-1 (fire.py build CLI): each wrapper's call gets its own "
              "sibling module's distinct, correct result (112 / 223, not "
              "112 / 112)",
              run.stdout.strip().splitlines() == ['112', '223'],
              repr(run.stdout))


def test_sb1_per_scope_import_distinct_modules(wd):
    """SB-1 follow-up: ONE file with two different NESTED (function-body-local)
    scopes each importing a same-named free function from two DIFFERENT
    sibling modules (`def call_alpha(): from alpha_module import f; ...` /
    `def call_beta(): from beta_module import f; ...` in the SAME main.mojo).
    Real Mojo/Python scoping makes this genuinely UNAMBIGUOUS at the source
    level — each `from X import f` binds `f` only within its own function
    body (myinterpreter.py's Scope.define gives each function its own scope),
    so `call_alpha`'s reference means alpha_module's `f` and `call_beta`'s
    means beta_module's `f`.

    Originally (commit that introduced `_note_own_func_home`'s
    `_AMBIGUOUS_FUNC_HOME` marker) this codegen had NO per-lexical-scope
    import tracking (`_own_imported_func_home` is per-GimpleGen-INSTANCE, not
    per-scope — both nested imports live in the same root instance), so the
    ambiguity was silently resolved by picking whichever sibling module's
    registration happened first (module_stmts processed in sorted() order) —
    a real silent-wrong-answer miscompile (confirmed: printed the SAME value
    twice instead of two distinct ones), and the build was hardened to refuse
    with a clear RuntimeError rather than silently miscompile.

    FIXED FOR REAL: GimpleGen now tracks imports per lexical scope
    (`_import_scope_stack` + `_collect_body_import_bindings` + the
    `_gen_stmt_FromImportStmt` per-scope binding), so each function-body call
    site resolves to the module its own `from X import f` bound `f` to —
    exactly the shadowing the interpreter applies. The build now COMPILES
    this shape correctly and the binary prints both distinct, correct values
    (112 / 223), matching the interpreter path exactly."""
    src_alpha_module = "def sb1_probe_amb(x: Int64) -> Int64:\n    return x + 111\n"
    src_beta_module = "def sb1_probe_amb(x: Int64) -> Int64:\n    return x + 222\n"
    src_main = ("def call_alpha() raises -> Int64:\n"
                "    from alpha_module import sb1_probe_amb\n"
                "    return sb1_probe_amb(1)\n\n"
                "def call_beta() raises -> Int64:\n"
                "    from beta_module import sb1_probe_amb\n"
                "    return sb1_probe_amb(1)\n\n"
                "def main() raises:\n"
                "    print(call_alpha())\n"
                "    print(call_beta())\n")

    proj = os.path.join(wd, 'sb1_cli_ambiguous')
    os.makedirs(proj, exist_ok=True)
    for fname, src in (('alpha_module.mojo', src_alpha_module),
                        ('beta_module.mojo', src_beta_module),
                        ('main.mojo', src_main)):
        with open(os.path.join(proj, fname), 'w') as f:
            f.write(src)

    exe = os.path.join(proj, 'main')
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, 'fire.py'), 'build', 'main.mojo'],
        cwd=proj, capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    check("SB-1 per-scope-import: fire.py build succeeds (per-lexical-scope "
          "tracking now resolves each function's own local import), doesn't "
          "silently pick one module for both call sites",
          r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}")
    check("SB-1 per-scope-import: an executable is produced",
          os.path.exists(exe), 'no executable produced')
    rr = subprocess.run([exe], capture_output=True, text=True, timeout=EXE_TIMEOUT_S)
    check("SB-1 per-scope-import: the compiled binary gets BOTH distinct, "
          "correct values (call_alpha -> alpha_module's f, call_beta -> "
          "beta_module's f) — the shape that used to silently miscompile",
          rr.stdout.strip().splitlines() == ['112', '223'], repr(rr.stdout))
    # The interpreter path (myinterpreter.py) is a completely separate
    # implementation; it must agree on the same two distinct, correct values.
    ri = subprocess.run(
        [sys.executable, os.path.join(HERE, 'fire.py'), 'run', 'main.mojo'],
        cwd=proj, capture_output=True, text=True, timeout=EXE_TIMEOUT_S)
    check("SB-1 per-scope-import: the INTERPRETER path (separate "
          "implementation) agrees, getting both distinct, correct values",
          ri.stdout.strip().splitlines() == ['112', '223'], repr(ri.stdout))


# ── A class reached through a MODULE ALIAS assigned to a name (not a
#    `from M import C as A` statement) ──
def test_module_attr_class_alias_constructs_that_class(wd):
    """`Alias = h.Thing` binds the CLASS OBJECT under a new bare name — the
    spelling this compiler's own source uses to reach an AST node
    (`mojo/middle/offload.py`'s `I = gctypes.IdentExpr`,
    `emit_stmts.py`'s `_IL = gimple_ctypes.IntLiteral`). Python has no
    distinct "class value": every later `Alias(...)` constructs
    `h.Thing`.

    The compiled path did not model a class as a value (the assignment
    itself lowers to a stubbed 0, with a comment saying so) and resolved
    the CONSTRUCTED NAME by bare-name lookup against every struct in the
    whole-program closure — a different question. Two ways that went
    wrong, both real:

      * a same-named struct in another module won. `helper_module.Alias`
        here, so `Alias(value=7)` built the wrong class; and because the
        local and the struct type were then ONE C identifier, the local
        shadowed the type and gcc refused the function outright
        (`'_t2' undeclared`, `'node' undeclared`) — a hard build failure
        with no relation to its cause. In the self-host closure this was
        `mojo/middle/offload.py`'s `Lit = gctypes.IntLiteral` building
        `ast_rewriter.py`'s own unrelated `class Lit`.
      * where no struct matched, the call fell through to the
        opaque-constructor path and the class value it called was the
        stubbed 0 — `emit_stmts.py`'s `_IL(1)`, i.e. the self-hosted
        compiler building `UnaryOp.operand` for a negative-step `range`
        by calling a null function pointer.

    Fixed by recording the alias (`_note_struct_attr_alias`), which both
    the constructor dispatch and the return-type estimator already
    consult for the `from M import C as A` spelling. Asserted through both
    pipelines: the compiled binary and the interpreter, which are
    separate implementations."""
    src_helper = ("struct Thing:\n"
                  "    var value: Int64\n"
                  "\n"
                  "    fn __init__(out self, value: Int64):\n"
                  "        self.value = value\n"
                  "\n"
                  "\n"
                  "struct Alias:\n"
                  "    var value: Int64\n"
                  "\n"
                  "    fn __init__(out self, value: Int64):\n"
                  "        self.value = -1\n")
    src_main = ("import helper_module as h\n"
                "\n"
                "\n"
                "fn build(n: Int64):\n"
                "    Alias = h.Thing\n"
                "    node = Alias(value=n)\n"
                "    print(node.value)\n"
                "\n"
                "\n"
                "fn main():\n"
                "    build(Int64(7))\n")

    proj = os.path.join(wd, 'class_alias_proj')
    os.makedirs(proj, exist_ok=True)
    for fname, src in (('helper_module.mojo', src_helper),
                       ('main.mojo', src_main)):
        with open(os.path.join(proj, fname), 'w') as f:
            f.write(src)

    exe = os.path.join(proj, 'main')
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, 'fire.py'), 'build', 'main.mojo'],
        cwd=proj, capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    check("class alias: fire.py build succeeds (`Alias = h.Thing` then "
          "`Alias(value=...)` must build h.Thing, not the same-named "
          "helper_module.Alias — which also shadowed the local and made "
          "gcc reject the function)",
          r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}")
    if r.returncode == 0:
        rr = subprocess.run([exe], capture_output=True, text=True, timeout=EXE_TIMEOUT_S)
        check("class alias: the compiled binary constructs h.Thing -> 7",
              rr.stdout.strip().splitlines() == ['7'], repr(rr.stdout))
    ri = subprocess.run(
        [sys.executable, os.path.join(HERE, 'fire.py'), 'run', 'main.mojo'],
        cwd=proj, capture_output=True, text=True, timeout=EXE_TIMEOUT_S)
    check("class alias: the INTERPRETER path (separate implementation) "
          "agrees -> 7",
          ri.stdout.strip().splitlines() == ['7'], repr(ri.stdout))


def test_root_module_circular_import_symbol(wd):
    """A sibling module that imports a function FROM the root entry module
    (`from root import f`, while root itself imports the sibling) must call
    the root module's actual emitted symbol — the root compiles its own
    top-level defs under its BARE name (module_name '' -> no qualifier), so
    the importer's call site must resolve the root's module name (or any
    dotted/raw spelling of it) to that same bare symbol. The tier lookup
    used to sanitize the raw module string ('root') and emit a phantom
    `root_root_val_<hash>` the definition never provides: undefined symbol
    at link. Verified through BOTH pipelines: driver.compile_program's
    link mode (check-linkmode's own shape) and fire.build_executable's
    do_imports=True inline mode (the shape self-host compiles fire.py
    itself through, where the real undefined `_fire_build_executable_…`
    surfaced)."""
    import fire
    proj = os.path.join(wd, 'root_circ')
    os.makedirs(proj, exist_ok=True)
    with open(os.path.join(proj, 'helper.mojo'), 'w') as f:
        f.write("from root import root_val\n\n"
                "fn helper() raises -> Int64:\n"
                "    return root_val() + 1\n")
    with open(os.path.join(proj, 'root.mojo'), 'w') as f:
        f.write("from helper import helper\n\n"
                "fn root_val() raises -> Int64:\n"
                "    return 41\n\n"
                "def main() raises:\n"
                "    print(helper())\n")
    exe = os.path.join(proj, 'root')
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, 'fire.py'), 'build', 'root.mojo'],
        cwd=proj, capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    check("root-circular-import: fire.py build succeeds", r.returncode == 0,
          f"rc={r.returncode}\n{r.stdout}\n{r.stderr}")
    check("root-circular-import: executable produced", os.path.exists(exe))
    if os.path.exists(exe):
        rr = _run(exe)
        check("root-circular-import: binary prints correct value (42)",
              rr.returncode == 0 and rr.stdout.strip() == '42',
              repr(rr.stdout) + repr(rr.stderr))
    root_path = os.path.join(proj, 'root.mojo')
    with open(root_path) as f:
        source = f.read()
    inline_exe = os.path.join(proj, 'root_inline')
    ok = fire.build_executable(root_path, source, output=inline_exe,
                               work_dir=proj, quiet=True)
    check("root-circular-import: inline build links", ok)
    if ok:
        rr = _run(inline_exe)
        check("root-circular-import: inline binary prints 42",
              rr.returncode == 0 and rr.stdout.strip() == '42',
              repr(rr.stdout) + repr(rr.stderr))


def test_underscore_prefixed_sibling_import_symbol(wd):
    """`from ._helper import only` — a RELATIVE import whose module BASENAME
    starts with an underscore — through `fire.py build`'s real
    do_imports=True inline pipeline, the exact shape CPython's
    `Lib/importlib/resources/readers.py:15` uses
    (`from ._itertools import only`).

    The module-string mangler that builds a cross-module C symbol prefix
    disagreed with itself about such a module. A relative import's leading
    depth dot is not part of the module's NAME, but `_register_sym` in
    `mojo/middle/module_shared.py` turned that dot into an underscore like
    any other dot, while the DEFINING side — and the other four sites that
    mangle a module string (funcs_shared.py:376, :602, :830, and
    `_compile_imported_module`'s `_module_key`) — dropped it. With
    `._helper` the call site's prefix became `__helper` against a
    definition emitted as `_helper`, so the call referenced
    `__helper_only_<hash>` while the definition was
    `_helper_only_<hash>`:

        error: implicit declaration of function '__helper_only_37bd8e';
                               did you mean '_helper_only_37bd8e'?

    The module's OWN leading underscore is what made the two spellings
    differ by exactly one character, which is why a sibling named `helper`
    (or `base3`, as `test_root_module_circular_import_symbol` uses) was
    always fine and `_helper` never was — so no pre-existing test could
    have caught it.

    Asserted on the generated C of the whole closure, not on a link result,
    and that distinction is load-bearing rather than stylistic. A link
    assertion is UNRELIABLE here in both directions: in this minimal shape
    the sibling also gets compiled to its own translation unit, whose
    separately-derived symbol happens to satisfy the mismatched call, so
    the binary links and prints the right answer even while the unit's own
    call site points at a name that unit does not define. The real failure
    needs a closure where NO other unit supplies that name — which is
    exactly CPython's `Lib/importlib/resources/readers.py`, one 10 MB
    `.ci` for the whole closure, where it became `implicit declaration of
    function '__itertools_only_37bd8e'`. So the assertion is the invariant
    itself: within one generated unit, the cross-module function must have
    exactly ONE identifier spelling across its definition and its call
    site. `_MOJO_STUB_` guard names are excluded — they are a separate
    namespace and legitimately spell the mangled name verbatim.
    """
    import re
    import fire
    proj = os.path.join(wd, 'uscore_sibling')
    os.makedirs(proj, exist_ok=True)
    with open(os.path.join(proj, '_helper.py'), 'w') as f:
        f.write("def only(x, too_long):\n    return x\n")
    with open(os.path.join(proj, 'main.py'), 'w') as f:
        f.write("from ._helper import only\n\n"
                "class C:\n"
                "    def pick(self, children):\n"
                "        one_dir = 7\n"
                "        return only(one_dir, 1)\n\n"
                "def main():\n"
                "    print(C().pick(1))\n\n"
                "main()\n")
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, 'fire.py'), '--dump-full',
         'main.py'],
        cwd=proj, capture_output=True, text=True, timeout=SWEEP_TIMEOUT_S)
    check("underscore-sibling: --dump-full of the closure succeeds",
          r.returncode == 0, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}")
    ci = os.path.join(proj, 'main.ci')
    if not os.path.exists(ci):
        check("underscore-sibling: closure .ci produced", False, 'no main.ci')
        return
    with open(ci) as f:
        text = f.read()
    # Every spelling of the imported symbol. Two exclusions, both required:
    #   - lines naming `_MOJO_STUB_...` are dropped: that guard macro spells
    #     the mangled name verbatim as its own macro name, in a namespace of
    #     its own, and would otherwise register as a second spelling;
    #   - the leading-underscore run is matched as a WHOLE (`(?<![\w])_+...`)
    #     rather than with a bare `_helper_only_` pattern, which would match
    #     happily INSIDE `__helper_only_` and so report one spelling either
    #     way — which is exactly the bug this test has to see.
    body = '\n'.join(ln for ln in text.split('\n') if '_MOJO_STUB' not in ln)
    spellings = set(re.findall(r'(?<![\w])_+helper_only_[0-9a-f]+', body))
    check("underscore-sibling: the imported `from ._helper import only` has "
          "exactly ONE C identifier spelling across its declaration, its "
          "definition and its call site — a second spelling is the "
          "call-site/definition qualifier disagreement this test exists to "
          "catch (a leading-dot relative import whose module basename starts "
          "with `_`)",
          len(spellings) == 1,
          f"got {sorted(spellings)} (expected exactly 1)")


# ── Codegen-review fixes #3 (monomorphize shadow) and #4 (overload) ───────
def test_review_fixes_monomorphize_overload(wd):
    import monomorphize as mm
    import elaborate
    # #3: a type parameter used as a binding name raises instead of silently
    # rewriting that value identifier to a type (was a silent miscompile).
    raised = False
    try:
        mm.monomorphize_source(
            "fn bad[T](y: Int) -> Int:\n    var T = y\n    return T\n", {'T': 'Int64'})
    except ValueError:
        raised = True
    check("review#3: type-param-as-binding raises (no silent miscompile)", raised)
    check("review#3: a normal generic still instantiates",
          mm.monomorphize_source("fn box[T](x: T) -> T:\n    return x\n",
                                 {'T': 'Int64'})[0] == 'box_1_T_5_Int64')
    # #4.2: parametric type args mangle to a valid C identifier (no []/, etc.)
    check("review#4: parametric mangle is a valid C identifier",
          mm.mangle('box', {'T': 'List[Int]'})
          == 'box_1_T_19_List_x005BInt_x005D'
          and '[' not in mm.safe_suffix('List[Int]'))
    # #4.1: no matching overload returns None rather than silently picking the first
    mod = ("fn pick(x: Int64) -> Int64:\n    return x\n"
           "fn pick(x: Float64) -> Int64:\n    return 7\n")
    check("review#4: no-match overload returns None (no silent first-pick)",
          elaborate.Elaborator().elaborate_overload_call(mod, 'pick', ['char *']) is None)
    # #6: a comptime fn with an unmarshalable (container) param raises a clear
    # ValueError (so the caller falls back to the constant-folder), not KeyError.
    import comptime
    raised6 = False
    try:
        comptime.evaluate("fn f(xs: List) -> Int64:\n    return 0\n", 'f', [0])
    except ValueError:
        raised6 = True
    except Exception:
        pass
    check("review#6: unmarshalable comptime param raises ValueError", raised6)
    # #7: the no-annotation default is consistent (int64_t) across both type paths.
    # _TYPE_MAP itself has no `None` key (a literal None key crashes building
    # this dict once self-hosted — MojoDict is string-keyed only; see
    # BACKLOG-CODEGEN.md §1); _mojo_type's own `if not ann: return 'int64_t'`
    # short-circuit is the real (and only) code path, so .get(None, ...)
    # checks the same fallback value without requiring the key to exist.
    from gimple_codegen import _mojo_type, _TYPE_MAP
    check("review#7: None default consistent (int64_t)",
          _mojo_type(None) == 'int64_t' and _TYPE_MAP.get(None, 'int64_t') == 'int64_t')


def test_self_qualified_type_param_substitution(wd):
    """`Self.<param>` inside a generic struct substitutes to the CONCRETE type,
    `Self.` and all — not to `Self.<concrete>`.

    The bare-word substitution pass can only rewrite the `T` in `Self.T`, which
    leaves `Self.int64_t`: a member name that means nothing, which `_mojo_type`
    then answers as `int64_t`. That silence is what boxed stdlib's
    `_PeekableIterator[InnerIterator]`'s `var _inner: Self.InnerIterator` (and
    every other generic iterator's `_inner`), leaving `next(self._inner)` with
    no receiver type to dispatch the iterator protocol through — the declared
    red in bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_unlowered.md.
    See monomorphize_source's own docstring."""
    import monomorphize as mm

    _name, concrete = mm.monomorphize_source(
        "struct Wrap[T]:\n"
        "    var _inner: Self.T\n"
        "    var _raw: T\n"
        "    var _opt: Optional[Self.T]\n"
        "    var _ptr: Pointer[Self.T]\n"
        "    var _other: Self.NotAParam\n",
        {'T': 'int64_t'})
    check("self#1: mangled name is the injective spelling of the same key",
          _name == 'Wrap_1_T_12_int64_x005Ft')
    check("self#2: `Self.T` substitutes to the concrete type, not `Self.int64_t`",
          'var _inner: int64_t' in concrete and 'Self.int64_t' not in concrete)
    check("self#3: a bare `T` still substitutes (unchanged behaviour)",
          'var _raw: int64_t' in concrete)
    check("self#4: `Self.T` inside a container type argument substitutes too",
          'var _opt: Optional[int64_t]' in concrete
          and 'var _ptr: Pointer[int64_t]' in concrete)
    check("self#5: `Self.<non-param member>` is NOT substituted",
          'var _other: Self.NotAParam' in concrete)

    # A struct-typed argument must survive as the mangled name of that struct,
    # so the layout the caller registers and the layout the instantiated
    # object carries are computed from the SAME text.
    _name2, concrete2 = mm.monomorphize_source(
        "struct Wrap2[T]:\n"
        "    var _inner: Self.T\n",
        {'T': 'Inner_int64_t'})
    check("self#6: a struct-typed argument substitutes verbatim",
          'var _inner: Inner_int64_t' in concrete2
          and 'Self.Inner_int64_t' not in concrete2)

    # A nested function that re-declares the same name as its own bracket
    # parameter still shadows it — the qualified pass must respect the same
    # spans the bare one does, not rewrite a nested declaration.
    _name3, concrete3 = mm.monomorphize_source(
        "fn outer[T](x: Self.T) -> T:\n"
        "    def inner[T](y: T) -> T:\n"
        "        return y\n"
        "    return inner[T](x)\n",
        {'T': 'int64_t'})
    check("self#7: `Self.T` still respects a nested shadowing bracket param",
          'def inner[T](y: T) -> T:' in concrete3)
    check("self#8: the outer `Self.T` still substitutes",
          'fn outer_1_T_12_int64_x005Ft(x: int64_t) -> int64_t:' in concrete3)


def test_type_param_markers_and_simd_unification(wd):
    """`type_param_names` must not report a positional-only/keyword-only
    separator as a type parameter, and `infer_type_args` must bind a type
    parameter that appears NESTED in a parameter's annotation.

    Both were one-line defects with a large blast radius, and both are silent:
    the elaborator declines, the call site falls through to a bare
    `extern int64_t f (...)`, and `gcc -fsyntax-only` cannot see that nothing
    defines it. Measured over the stdlib sweep, the `//` marker alone accounted
    for 383 of 1254 elaborator declines — every template in the numeric library
    is written with it (`def ceildiv[T: CeilDivable, //](...)`). See
    bugs/CODEGEN_imported_generic_never_elaborated_calls_nothing_defines.md."""
    import elaborate as el

    check("marker#1: `//` is a separator, not a type param",
          el.type_param_names(
              'def ceildiv[T: CeilDivable, //](n: T, d: T) -> T:\n'
              '    return n\n') == ['T'])
    check("marker#2: a bare `**` is a separator; `**kw` is a parameter",
          el.type_param_names('def f[T, **](x: T) -> T:\n    return x\n')
          == ['T']
          and el.type_param_names('def g[T, **kw](x: T) -> T:\n    return x\n')
          == ['T', '**kw'])
    check("marker#3: the legacy `/` and `*` still work",
          el.type_param_names('def f[T, /](x: T) -> T:\n    return x\n')
          == ['T']
          and el.type_param_names('def g[T, *](x: T) -> T:\n    return x\n')
          == ['T'])
    check("marker#4: real params are untouched",
          el.type_param_names('struct Box[T, U]:\n    pass\n') == ['T', 'U'])
    check("marker#5: a bounds parse skips the marker too",
          el.parse_bounds('def ceildiv[T: CeilDivable, //](n: T) -> T:\n'
                          '    return n\n') == {'T': 'CeilDivable'})
    check("marker#6: an origin param is still reported (it is not a marker)",
          el.type_param_names(
              'def black_box[T: AnyType, origin: Origin, //]'
              '(ref[origin] value: T) -> ref[origin] T:\n'
              '    return value\n') == ['T', 'origin'])

    _simd = ('def copysign[\n    dtype: DType, width: Int, //\n'
             '](magnitude: SIMD[dtype,width], sign: SIMD[dtype,width])'
             ' -> SIMD[dtype,width]:\n    return magnitude\n')
    check("unify#1: a type param nested in `SIMD[dtype, width]` binds",
          el.infer_type_args(_simd, ['double', 'double'])
          == ['Float64', '1'])
    check("unify#2: `x: T` still binds as before",
          el.infer_type_args('def f[T](x: T) -> T:\n    return x\n',
                             ['char *']) == ['String'])
    check("unify#3: an un-understood shape still declines (no partial bind)",
          el.infer_type_args(
              'def f[T, U](a: Pointer[T], b: U) -> U:\n    return b\n',
              ['int64_t *', 'double']) is None)
    check("unify#4: a non-SIMD wrapper still declines",
          el.infer_type_args(
              'def f[T](a: Some[T]) -> T:\n    return a\n',
              ['int64_t']) is None)
    check("unify#5: too few arguments still declines",
          el.infer_type_args('def f[T, U](a: T, b: U) -> T:\n    return a\n',
                             ['int64_t']) is None)


def test_generic_instantiation_symbol_agreement(wd):
    """The instantiation TU's symbols and the caller's declarations must be the
    SAME strings — and the only way to find out is to LINK, because
    `compile_stdlib.py` runs `gcc -fsyntax-only` and cannot see a symbol that is
    declared and never defined.

    `monomorphize.instantiate` used to build the monomorphized TU with
    `module_name=mangled`, and a struct method's C symbol is
    `{home-module}_{Struct}_{method}{overload_suffix}`, so it emitted

        MoveOnly_Int64_MoveOnly_Int64___eq__      <- what the TU defined
        MoveOnly_Int64___eq__                    <- what the caller declared

    The caller has no module identity for a materialized generic struct (no
    `_imported_struct_home` entry), so it has no qualifier. Verified by linking
    `test/collections/test_array.mojo`'s generated C against its own CAS
    instantiation object: `ld: undefined _MoveOnly_Int___eq__` — i.e. EVERY
    generic struct this compiler had ever materialized produced an artifact
    that could not link, and no gate step can see it.

    The second half is `_struct_name_of` being used as an "is this a struct?"
    test. It is a pure spelling operation (`_struct_name_of('int64_t')` is
    `'int64_t'`), so the `next(<struct>)` struct-protocol branch's
    `if _struct_name_of(ret):` guard was true for the scalar `int64_t` too, and
    it dispatched `__next__` on `int64_t` — a symbol nothing defines. That is
    the family `bugs/CODEGEN_next_on_a_user_defined_iterator_struct_is_
    unlowered.md` is about, and the guard has to consult the registry."""
    import elaborate as el
    from module_loader import STDLIB_PATH
    import os as _os

    iter_src_path = _os.path.join(STDLIB_PATH, 'std', 'iter', '__init__.mojo')
    if not _os.path.exists(iter_src_path):
        check("symbols#0: std/iter is reachable", False)
        return
    iter_src = open(iter_src_path).read()

    # 1. The TU names its methods the way the caller's registry declares them.
    info = el.Elaborator().elaborate_generic_struct(iter_src, '_Empty', ['Int'])
    check("symbols#1: `_Empty[Int]` elaborates", bool(info and info['name']))
    if not info:
        return
    # The mangled STRUCT name is derived, not spelled out: this test's subject
    # is that the TU and the caller agree on ONE string, and hardcoding the
    # spelling here would make every change to `monomorphize.mangle` look like
    # a change to that agreement. `mangle`'s own spelling is pinned separately,
    # by `test_mangle_is_injective`.
    import monomorphize as _mm
    _m = _mm.mangle('_Empty', {'T': 'Int'})
    check("symbols#1b: `_Empty[Int]` mangles injectively", _m == '_Empty_1_T_3_Int')
    # `nm` on Mach-O prints the object format's leading underscore; strip
    # exactly one, so a C name that itself starts with one survives.
    names = {s[1:] if s.startswith('_') else s for s in (info.get('symbols') or ())}
    check("symbols#2: the object defines the UNQUALIFIED method name the caller "
          "declares (`_Empty_Int___next__`, not "
          "`_Empty_Int__Empty_Int___next__`)",
          f'{_m}___next__' in names)
    check("symbols#3: no symbol carries the mangled name as a module prefix",
          not any(n.startswith(_m + _m) for n in names))
    check("symbols#4: an overloaded method is reported under its real suffixed "
          "name and NOT under a bare name — the elaborator's view of two "
          "overloads of `__iter__` is identical, so it cannot invent one, and "
          "`_register_generic_struct` refuses such a struct rather than "
          "declaring a symbol nothing defines",
          any(n.startswith(f'{_m}___iter___') for n in names)
          and f'{_m}___iter__' not in names)
    _finfo = el.Elaborator().elaborate_generic_call(iter_src, 'empty', ['Int'])
    check("symbols#5: `empty[Int]` elaborates to the bare symbol `empty_1_T_3_Int` "
          "(the TU's module name does not reach the top-level function)",
          bool(_finfo) and _finfo['symbol'] == _mm.mangle('empty', {'T': 'Int'}))

    # 2. `_struct_name_of` is not a "is this a struct" predicate; the guard that
    #    needs one must ask the registry.
    import mojo.backend_gimple.emit_calls as ggc

    class _G:
        struct_field_types = {'It': {}}

    check("symbols#6: a scalar return is not read as a struct",
          ggc._struct_ptr_name(_G(), 'int64_t') == ''
          and ggc._struct_ptr_name(_G(), 'char *') == '')
    check("symbols#7: a registered struct pointer IS read as a struct",
          ggc._struct_ptr_name(_G(), 'It *') == 'It')
    check("symbols#8: an unregistered name is not either",
          ggc._struct_ptr_name(_G(), 'Nope *') == '')
    import mojo.middle.types as _t
    _G.struct_field_types = {'Int': {}}
    check("symbols#9: a scalar newtype that IS a real stdlib struct is still "
          "erased to its C scalar (this codegen's `_TYPE_MAP` convention wins)",
          ggc._struct_ptr_name(_G(), 'Int *') == '')


def test_mangle_is_injective(wd):
    """`monomorphize.mangle` must be a FUNCTION of the instantiation.

    It used to be `'_'.join(safe_suffix(v) for v in sorted(type_args.values()))`:
    no key names, and a LOSSY escape that mapped every non-alphanumeric
    character (including `_` itself) to `_`. Two independent collisions, both
    measured before the fix over the same generated corpus this test builds:

        mangle('Box', {'T': 'A_B'})        == 'Box_A_B'
        mangle('Box', {'T': 'A', 'o': 'B'}) == 'Box_A_B'   # ambiguous segmentation
        mangle('Box', {'T': 'List[Int]'})   == 'Box_List_Int_'
        mangle('Box', {'T': 'List_Int'})    == 'Box_List_Int'  # lossy escape
        mangle('Box', {'T': '_'}) == mangle('Box', {'T': ' '}) == mangle('Box', {'T': '.'})

    1512 of 1752 pairs collided. A non-injective name is not a naming
    inconvenience: two genuinely different instantiations shared one C symbol,
    which is `error: conflicting types for '<name>'` when both are defined in
    one TU and `ld: duplicate symbol` when they are not.

    The corpus is generated, not hand-listed, so it covers the separator
    characters the old scheme collapsed on (`_`, space, `.`, `[`, `]`, `,`)
    plus a digit that a length prefix has to be told apart from."""
    import itertools as _it
    _alpha = ['A', 'B', '_', ' ', '.', '[', ']', ',', '1']
    _vals = [''.join(p) for n in range(0, 4)
             for p in _it.product(_alpha, repeat=n)]
    _targs = []
    for v in _vals:
        _targs += [{'T': v}, {'T': 'A', 'o': v}, {'T': v, 'o': 'B'},
                   {'T': v, 'o': 'C'}, {'x': v, 'y': 'B', 'z': 'C'},
                   {'T': v, 'ArgC': '3'}]
    _seen: dict = {}
    _coll: list = []
    for t in _targs:
        for nm in ('Box', '_Empty', 'T', 'A_1'):
            m = mm.mangle(nm, t)
            if m in _seen and _seen[m] != (nm, t):
                _coll.append((_seen[m], (nm, t), m))
            _seen[m] = (nm, t)
    check(f"mangle#1: no two distinct (name, type_args) share a symbol "
          f"({len(_seen)} generated instantiations)", not _coll)

    _ident = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
    check("mangle#2: every mangled name is a legal C identifier",
          all(_ident.match(m) for m in _seen))
    # `mojo/middle/types.py::demangle_overload` recognises `___<6 lowercase
    # hex>$` as an overload-hash tail. The escapes are UPPERCASE hex for
    # exactly this reason, so a mangled type argument can never grow one.
    check("mangle#3: a mangled name cannot be mistaken for an overload-suffixed "
          "one (no `___` at all)",
          not any('___' in m for m in _seen))

    # The specific collisions the fix is about, named individually so a
    # regression reports WHICH one came back.
    check("mangle#4: {'T':'A_B'} and {'T':'A','o':'B'} are distinct",
          mm.mangle('Box', {'T': 'A_B'}) != mm.mangle('Box', {'T': 'A', 'o': 'B'}))
    check("mangle#5: {'T':'List[Int]'} and {'T':'List_Int'} are distinct",
          mm.mangle('Box', {'T': 'List[Int]'}) != mm.mangle('Box', {'T': 'List_Int'}))
    check("mangle#6: the escaped chars the old scheme collapsed are distinct",
          len({mm.mangle('Box', {'T': c}) for c in ('_', ' ', '.', '[', ',')}) == 5)
    check("mangle#7: the parameter NAME is part of the key (two templates that "
          "differ only in what they call their parameter do not collide)",
          mm.mangle('Foo', {'T': 'Int64'}) != mm.mangle('Foo', {'U': 'Int64'}))
    check("mangle#8: a zero-parameter instantiation keeps the bare name",
          mm.mangle('empty', {}) == 'empty')

    # `elaborate_overload_call` had the same defect on a different spelling:
    # `safe_suffix('_'.join(ptypes))` is ambiguous segmentation AND lossy.
    check("mangle#9: the overload signature mangling is injective too",
          mm.mangle_signature('pick', ['A_B']) != mm.mangle_signature('pick', ['A', 'B'])
          and mm.mangle_signature('pick', ['A_B']) != mm.mangle_signature('pick', ['A.B'])
          and mm.mangle_signature('pick', []) != mm.mangle_signature('pick', ['void']))

    # Round-trip: the length-prefixed components are DECODABLE, which is the
    # direct evidence that the count — not a guess about which `_` is
    # structural — is what disambiguates. The decoder lives here, not in
    # monomorphize.py, because nothing in the compiler needs it: injectivity is
    # the property everything depends on and it is property #1 above.
    def _unescape(t: str) -> str:
        out, i = [], 0
        while i < len(t):
            if t[i] != '_':
                out.append(t[i]); i += 1; continue
            w = 4 if t[i + 1] == 'x' else 8
            out.append(chr(int(t[i + 2:i + 2 + w], 16))); i += 2 + w
        return ''.join(out)

    def _decode(suffix: str):
        pairs, i = [], 0
        while i < len(suffix):
            j = suffix.index('_', i)
            klen = int(suffix[i:j]); k = suffix[j + 1:j + 1 + klen]
            i = j + 1 + klen + 1
            j = suffix.index('_', i)
            vlen = int(suffix[i:j]); v = suffix[j + 1:j + 1 + vlen]
            pairs.append((_unescape(k), _unescape(v)))
            i = j + 1 + vlen + 1
        return pairs

    _rt_bad = []
    for t in _targs:
        nm = 'Box'
        suffix = mm.mangle(nm, t)[len(nm) + 1:]
        try:
            if sorted(_decode(suffix)) != sorted((str(k), str(v)) for k, v in t.items()):
                _rt_bad.append(t)
        except Exception as e:
            _rt_bad.append((t, e))
    check(f"mangle#10: every mangled suffix decodes back to its (key, value) "
          f"pairs ({len(_targs)} round-trips)", not _rt_bad)


def test_in_tu_instantiation(wd):
    """An imported generic whose methods OVERLOAD is materialized in this
    translation unit, not declared `extern` beside a CAS object.

    The `.o` route cannot serve this shape, and the reason is measured rather
    than argued: `_register_generic_struct` reads the object's symbols with
    `nm`, sees two `__iter__` definitions (`..._0120be` and `..._0120be_2`),
    knows the caller can only compose the UNSUFFIXED name, and refuses the
    struct — so the caller's receiver types as a boxed `int64_t` and `next(obj)`
    has nothing to dispatch on. Every iterator in `std/iter` is in this class
    (`__iter__` on `var self` and on `ref self`, both erasing to
    `(Struct *)`), which is what `bugs/CODEGEN_next_on_a_user_defined_iterator_
    struct_is_unlowered.md` is about.

    Driven through `build_stdlib_dylib.compile_module_to_c` — the SAME entry
    point `compile_stdlib.py` uses — on two real stdlib test files, because the
    properties below are only meaningful against the real generic and `gcc
    -fsyntax-only` (the gate step) structurally cannot see any of them.

    Pinned per property:
      - the instantiation's methods are DEFINED in the module's own C, under the
        names this codegen gave them;
      - no `extern` claims them and no CAS object is contributed, i.e. exactly
        one route took the instantiation;
      - both `__iter__` overloads are DEFINED and the bare name is never
        CALLED — two overloads define neither, so nothing may dispatch on it;
      - `next(<struct>)` lowered for real, to the instantiation's own
        `__next__`, not to the always-declared variadic `next`;
      - the boundary predicate itself, on the real stdlib templates: an
        iterator whose only overloads are protocol ones is carried, and one
        whose overloads are NOT is refused (the `.o` route keeps it).
    """
    import os as _os
    import threading as _th
    from module_loader import STDLIB_PATH
    import build_stdlib_dylib as bsd
    import mojo.backend_gimple.elab_intu as EI

    def _compile(rel):
        path = _os.path.join(STDLIB_PATH, rel)
        if not _os.path.exists(path):
            return None
        src = open(path).read()
        mod = rel.replace('/', '.').replace('.mojo', '')
        box = {}
        _th.stack_size(1 << 30)
        t = _th.Thread(target=lambda: box.update(
            c=bsd.compile_module_to_c(src, path, mod)))
        t.start(); t.join()
        return box.get('c')

    once_src = _os.path.join(STDLIB_PATH, 'std', 'iter', '__init__.mojo')
    iter_src = open(once_src).read() if _os.path.exists(once_src) else ''

    # The boundary predicate, on the real templates. This is the line the
    # feature is drawn on, and it is a measurement rather than a whitelist:
    # in-TU carries a struct whose ONLY duplicated method names are iteration
    # protocol ones, because the two consumers resolve `__iter__` by the bare
    # name and correctly keep the receiver's own type when it is absent, while
    # every other overloaded method is dispatched through its signature hash and
    # this codegen cannot yet pick an overload at a call site from real C
    # parameter types. Measured counter-examples, all refused:
    #   MoveCounter/ArcPointer/BitSet/StaticTuple  dup ['__init__']
    #   Optional   ['__eq__', '__init__', '__iter__']
    #   List       ['__getitem__', '__init__', '__iter__', 'extend', 'pop',
    #               'resize']
    #   Coord      ['__init__', '__len__', 'product']
    class _G:
        _imported_generic_structs = {
            '_Empty': once_src, '_Once': once_src,
            '_RepeatIterator': _os.path.join(STDLIB_PATH, 'std', 'itertools',
                                             'itertools.mojo'),
            'Optional': _os.path.join(STDLIB_PATH, 'std', 'collections',
                                      'optional.mojo'),
            'List': _os.path.join(STDLIB_PATH, 'std', 'collections',
                                  'list.mojo'),
        }
        struct_field_types: dict = {}
    check("intu#1: an iterator whose only overload is `__iter__` is carried "
          "(`_Empty`, `_Once`, `_RepeatIterator`)",
          all(EI._protocol_only_overloads(_G(), n)
              for n in ('_Empty', '_Once', '_RepeatIterator')))
    check("intu#2: an overload OUTSIDE the iteration protocol is REFUSED "
          "(`Optional`, `List`) — the `.o` route keeps it",
          not any(EI._protocol_only_overloads(_G(), n)
                  for n in ('Optional', 'List')))

    for rel, base, targs in (('test/iter/test_once.mojo', '_Once', {'T': 'Int64'}),
                             ('test/iter/test_empty.mojo', '_Empty', {'T': 'Int'}),
                             ('test/itertools/test_repeat.mojo',
                              '_RepeatIterator', {'ElementType': 'Int64'})):
        code = _compile(rel)
        if code is None:
            check(f"intu#3: {rel} is reachable in the stdlib tree", False)
            continue
        m = mm.mangle(base, targs)
        check(f"intu#3: `{rel}` DEFINES `{m}` in its own C (in-TU, not extern)",
              f'typedef struct {m} ' in code
              and f'extern int64_t {m}___next__' not in code)
        check(f"intu#4: `{rel}` defines `__next__` and both `__iter__` "
              f"overloads, and CALLS no bare `__iter__`",
              f'{m}___next__ (' in code
              and code.count(f'{m}___iter___') >= 2
              and f'= {m}___iter__ (' not in code)
        check(f"intu#5: `{rel}` lowered `next(...)` to the instantiation's own "
              f"`__next__`, not the variadic `next`",
              f'= {m}___next__ (' in code and ' _next (' not in code)


def test_ambiguous_overload_is_refused_not_first_picked(wd):
    """An overload set this resolver cannot rank must RAISE, not return the
    first candidate.

    `myinterpreter.MojoOverloadSet` dispatches on argument count and keyword
    names only — the interpreter is untyped, so parameter types are not
    available to it. Two candidates that agree on both are therefore genuinely
    unrankable, and returning the first in source order is a silent wrong
    answer whenever they differ in parameter type, parameter convention
    (`ref`/`var`/`mut`) or return type.

    The stdlib's own shape is `peekable` (`std/iter/__init__.mojo`):
    `def peekable(ref iterable: Some[Iterable]) -> _PeekableIterator[...]`
    versus `def peekable(var iterable: Some[IterableOwned]) -> ...`. Same
    arity, no keywords, differing only in a trait bound and a convention.

    Pinned per property, because each is a distinct way this could rot back
    into a first-pick:
      - an unrankable tie RAISES, and the message names the tie;
      - the candidates are still enumerated in the message, so the caller can
        see WHICH overloads collided;
      - a tie that IS rankable (differing arity) still DISPATCHES — refusing
        every overload set would be a different regression, and this is what
        keeps the refusal from over-reaching;
      - the pre-existing no-match error still fires, unchanged, with its own
        message.

    The candidates are REAL `MojoFunction`s, built by parsing and executing
    source, not stubs: the overload set is reached through the same path a call
    site reaches it, and a stub cannot drift out of step with the invocation
    protocol `MojoOverloadSet.__call__` actually uses without this test failing
    for the wrong reason (which is exactly what happened when this test was
    merged into a tree whose `MojoFunction.__call__` had grown `_invoke`).
    """
    import myinterpreter as MI
    from fire_compiler import py_tokenize, Parser

    src = '''
def peekable(ref iterable: Some[Iterable]) -> _PeekableIterator:
    return 1


def peekable(var iterable: Some[IterableOwned]) -> _PeekableIterator:
    return 2


def f(a):
    return 10


def f(a, b):
    return 20
'''
    interp = MI.Interpreter(filename='ovl.mojo')
    for stmt in Parser(py_tokenize(src)).parse_module():
        interp.execute(stmt)

    # The stdlib `peekable` shape: same arity, same parameter name, no
    # keywords, differing only in what `_matches` cannot see.
    tie = interp.scope.vars['peekable']
    check("ovl#0: the parsed source really does produce a 2-candidate tie",
          len(tie.candidates) == 2, f'{len(tie.candidates)} candidates')
    try:
        got = tie([1, 2, 3])
        check("ovl#1: an unrankable tie RAISES rather than returning the first "
              "candidate", False, f'returned {got!r}')
    except MI._NoOverloadMatch as e:
        msg = str(e)
        check("ovl#1: an unrankable tie RAISES rather than returning the first "
              "candidate", 'AMBIGUOUS' in msg, msg[:120])
        check("ovl#2: the refusal names the tie — 'peekable', the candidate "
              "count, and the call shape",
              'peekable' in msg and '2 of 2' in msg and '1 positional' in msg,
              msg[:120])

    # Rankable: arity differs, so this MUST still dispatch. A refusal here
    # would be over-reaching, and `test_runtime_diff.py` is the backstop for
    # that; this pins it at the unit.
    ranked = interp.scope.vars['f']
    check("ovl#3: a RANKABLE overload set (differing arity) still dispatches",
          ranked(1) == 10 and ranked(1, 2) == 20,
          f'{ranked(1)!r} / {ranked(1, 2)!r}')

    # The pre-existing no-match error, unchanged.
    try:
        ranked(1, 2, 3)
        check("ovl#4: no-match still raises the original error", False,
              'returned instead of raising')
    except MI._NoOverloadMatch as e:
        check("ovl#4: no-match still raises the original error",
              'AMBIGUOUS' not in str(e) and 'no overload' in str(e),
              str(e)[:120])


def main():
    wd = tempfile.mkdtemp(prefix='mojo_modcache_test_')
    # Isolate the CAS so cold/warm/invalidation assertions are deterministic and
    # we never touch the user's real ~/.gmojo.
    cas.CAS_DIR = os.path.join(wd, 'gmojo')
    try:
        test_stage1_extern_boundary(wd)
        test_stage2_3_dylib_and_cas(wd)
        test_stage4_reflection(wd)
        test_stage5_monomorphization(wd)
        test_stage6_comptime(wd)
        test_resolution_authority(wd)
        test_elaboration_generic_call(wd)
        test_elaboration_inference_and_comptime(wd)
        test_elaboration_generic_struct(wd)
        test_elaboration_failure_is_not_cached(wd)
        test_elaboration_overload(wd)
        test_elaboration_trait_conformance(wd)
        test_reflected_struct_import(wd)
        test_module_qualified_struct_symbols(wd)
        test_mangle_is_injective(wd)
        test_in_tu_instantiation(wd)
        test_review_fixes_monomorphize_overload(wd)
        test_self_qualified_type_param_substitution(wd)
        test_type_param_markers_and_simd_unification(wd)
        test_generic_instantiation_symbol_agreement(wd)
        test_def_overload_not_dangling_export(wd)
        test_cross_module_free_func_mangling_agrees(wd)
        test_sb1_cross_module_same_c_param_overload_mangling(wd)
        test_sb1_mojo_build_cli_wrapper_modules(wd)
        test_sb1_per_scope_import_distinct_modules(wd)
        test_module_attr_class_alias_constructs_that_class(wd)
        test_root_module_circular_import_symbol(wd)
        test_underscore_prefixed_sibling_import_symbol(wd)
        test_ambiguous_overload_is_refused_not_first_picked(wd)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    print()
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    return _FAIL == 0


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
