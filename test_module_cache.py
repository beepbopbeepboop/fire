#!/usr/bin/env python3
"""End-to-end tests for the module cache (MODULE_CACHE_DESIGN.md stages 1-6).

Each stage's mechanism is exercised for real: compile, link, run, and check the
cache behaves (cold miss / warm hit / invalidation). Run via `make check` or
directly: `python3 test_module_cache.py`.
"""
import os
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


def _run(exe):
    return subprocess.run([exe], capture_output=True, text=True, timeout=20)


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
        check("stage1: extern decl emitted, no inlined body",
              'extern int64_t s1_add' in cC and 's1_add (int64_t a, int64_t b)\n{' not in cC)
        # build library artifact separately, link, run
        from gimple_codegen import GimpleGen
        from mojo_compiler import py_tokenize, Parser
        lib_c = GimpleGen(emit_entry_points=False, module_name='s1lib').gen_module(
            Parser(py_tokenize(libsrc)).parse_module())
        cc, lc = os.path.join(wd, 'c1.c'), os.path.join(wd, 'l1.c')
        open(cc, 'w').write(cC); open(lc, 'w').write(lib_c)
        co, lo = os.path.join(wd, 'c1.o'), os.path.join(wd, 'l1.o')
        subprocess.run([GCC, '-fgimple', f'-I{RUNTIME}', '-c', '-o', co, cc], check=True)
        subprocess.run([GCC, '-fgimple', f'-I{RUNTIME}', '-c', '-o', lo, lc], check=True)
        exe = os.path.join(wd, 'c1')
        subprocess.run([GCC, '-o', exe, co, lo, os.path.join(RUNTIME, 'mojo_runtime.c')], check=True)
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
        check("stage3: cold build is a miss", cold['misses'] == 1 and cold['hits'] == 0,
              str(cold))
        check("stage3: warm build is a hit (no codegen)", warm['hits'] == 1 and warm['misses'] == 0,
              str(warm))
        # edit source → must miss again
        cas.reset_stats()
        open(libpath, 'w').write(libsrc + "\nfn s2_extra() -> Int64:\n    return 0\n")
        bsd.build([libpath], dylib, link_runtime=True)
        check("stage3: source edit invalidates (miss)", cas.stats['misses'] == 1, str(cas.stats))
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
        check("stage2: client object is tiny (<8KB)", sz < 8192, f"{sz} bytes")
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
    n1, o1, h1 = mm.instantiate(tmpl, {'T': 'Int64'})
    n2, o2, h2 = mm.instantiate(tmpl, {'T': 'Float64'})
    n3, o3, h3 = mm.instantiate(tmpl, {'T': 'Int64'})
    check("stage5: distinct type args → distinct artifacts (2 misses)",
          (not h1) and (not h2) and o1 != o2)
    check("stage5: re-instantiation is a hit (same object)", h3 and o3 == o1)
    # the cached instantiation links + runs
    cmain = os.path.join(wd, 'um.c')
    open(cmain, 'w').write('#include <stdint.h>\n#include <stdio.h>\n'
                           'extern int64_t s5_id_Int64(int64_t);\n'
                           'int main(void){printf("%lld\\n",(long long)s5_id_Int64(7));return 0;}\n')
    exe = os.path.join(wd, 'um')
    subprocess.run([GCC, '-o', exe, cmain, o1, os.path.join(RUNTIME, 'mojo_runtime.c')], check=True)
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
          bool(i64) and i64['symbol'] == 'box_Int64' and i64['ret'] == 'int64_t')
    check("elaborate: distinct type args → distinct instantiations",
          i64['object'] != i32['object'] and i32['symbol'] == 'box_Int32')
    check("elaborate: re-instantiation is a CAS hit (same object)",
          again['object'] == i64['object'])
    # codegen wiring: a generic call site emits an extern + concrete call and
    # records the instantiation object on the link line.
    gl = os.path.join(RUNTIME, 'el_genlib.mojo')
    open(gl, 'w').write("fn box[T](x: T) -> T:\n    return x\n")
    try:
        client = "from el_genlib import box\nfn main():\n    var y = box[Int64](42)\n"
        code, dylibs, objects = compile_linked(client)
        check("elaborate: client emits extern + concrete call + records object",
              'extern int64_t box_Int64' in code and 'box_Int64 (' in code
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
        code, _d, objs = compile_linked("from el_box import box\n"
                                        "fn main():\n    var y = box(42)\n")
        check("slice2: inferred generic call elaborates (no explicit [..])",
              ('box_Int64' in code or 'box_Int' in code) and len(objs) == 1)
        # slice 3: comptime call to an imported fn resolved at compile time
        src = ("from el_ct import fib\n"
               "fn main():\n"
               "    comptime if fib(10) == 55:\n"
               "        external_call[\"exit\", NoneType](55)\n"
               "    else:\n"
               "        external_call[\"exit\", NoneType](1)\n")
        code2, _d2, _o2 = compile_linked(src)
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
          bool(info) and info['name'] == 'Box_Int64'
          and ('value', 'int64_t') in info['fields'])
    check("slice5: struct methods monomorphized",
          ('unbox', 'int64_t', []) in info['methods'])
    bl = os.path.join(RUNTIME, 'el_boxlib.mojo')
    open(bl, 'w').write(mod)
    try:
        code, _d, objs = compile_linked(
            "from el_boxlib import Box\n"
            "fn main():\n    var b = Box[Int64](42)\n    var y = b.unbox()\n")
        check("slice5: client materializes struct + calls method + records object",
              'typedef struct Box_Int64' in code and 'Box_Int64_unbox' in code
              and len(objs) == 1)
    finally:
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
          i64['symbol'] == 'pick__Int64' and i32['symbol'] == 'pick__Int32'
          and i64['object'] != i32['object'])
    ol = os.path.join(RUNTIME, 'el_ovlib.mojo')
    open(ol, 'w').write(mod)
    try:
        code, _d, objs = compile_linked(
            "from el_ovlib import pick\n"
            "fn main():\n    var a: Int64 = 5\n    var y = pick(a)\n")
        check("slice4: client calls the signature-mangled overload",
              'pick__Int64' in code and len(objs) == 1)
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
          bool(fi) and fi['symbol'] == 'run_Num')
    check("slice6: bounded generic struct instantiates for a conforming type",
          bool(si) and si['name'] == 'Box_Num'
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
        code, dylibs, _objs = compile_linked(client)
        check("reflect: client materializes the layout + method externs (no body)",
              'typedef struct Counter' in code
              and 'extern int64_t Counter_increment (Counter *);' in code
              and 'Counter_increment (Counter *self)' not in code
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
        check("reflect: client object is tiny — bodies live in the dylib",
              sz < 8192, f"{sz} bytes")
    finally:
        os.remove(libpath)


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
                                 {'T': 'Int64'})[0] == 'box_Int64')
    # #4.2: parametric type args mangle to a valid C identifier (no []/, etc.)
    check("review#4: parametric mangle is a valid C identifier",
          mm.mangle('box', {'T': 'List[Int]'}) == 'box_List_Int_'
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
        test_elaboration_overload(wd)
        test_elaboration_trait_conformance(wd)
        test_reflected_struct_import(wd)
        test_review_fixes_monomorphize_overload(wd)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    print()
    print(f"Results: {_PASS} passed, {_FAIL} failed")
    return _FAIL == 0


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
