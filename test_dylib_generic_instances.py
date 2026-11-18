#!/usr/bin/env python3
"""A generic FREE FUNCTION instantiated only by another module must get a
definition in the dylib, under the exact symbol the caller references.

Every module in the dylib is compiled ALONE, so a generic a module merely
declares has no concrete signature there and is never emitted. A caller in
another module whose call the elaborator cannot bind (its argument's C type is
an erased word, not a type it can name) falls back to the text-scan ERASED
signature — `p9_gena_poke_2dbb98` for `def poke[T](p: MutPointer[T, _], ...)` —
and nothing defined that symbol. The dylib then left it undefined and every
client silently fell back to source for it (the "generic free function
instantiated only by another module" class of
CODEGEN_stdlib_dylib_lazy_undefined_refs; this file pins its fix).

`build_stdlib_dylib._generic_instance_requests` closes it: it reads each
caller OBJECT's references (`nm -u`) and recompiles the DEFINING module once
with the requested instances appended, emitted under the caller's own symbol in
the defining module's own translation unit.

Also pins the two safety rules: a module that only DECLARES a generic (nobody
asks for an instance) still emits nothing for it and the dylib loads, and an
AMBIGUOUS same-name request is declined rather than resolved by source order.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_stdlib_dylib as B
from gimple_codegen import GimpleGen

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name)


def _nm(argv):
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("%s failed: %s" % (' '.join(argv), r.stderr))
    out = set()
    for line in r.stdout.splitlines():
        line = line.rstrip()
        if line and not line.endswith(':'):
            out.add(line.split()[-1])
    return out


# The definer declares `poke[T]` with its type parameter inside a pointer, so a
# call argument's C type (`int64_t` — MutPointer is erased) cannot bind T. The
# caller therefore names the erased signature.
GENA = (
    'def poke[T: AnyType](p: MutPointer[T, _], n: Int) -> Int:\n'
    '    return n\n'
)
GENB = (
    'from .p9_gena import poke\n'
    '\n'
    '\n'
    'def use(p: MutPointer[Int, _]) -> Int:\n'
    '    return poke(p, 3)\n'
)
SYMBOL = 'p9_gena_poke_2dbb98'


def _write(td):
    a = os.path.join(td, 'p9_gena.mojo')
    c = os.path.join(td, 'p9_genb.mojo')
    with open(a, 'w') as f:
        f.write(GENA)
    with open(c, 'w') as f:
        f.write(GENB)
    return a, c


with tempfile.TemporaryDirectory(prefix='p9_generic_instances_') as td:
    gena, genb = _write(td)

    # 1. The PRE-PASS sees the request. This is the mechanism itself: the
    #    caller's object references the erased symbol and the definer's generic
    #    is indexed as its home, so the request comes back with an instance.
    ra = B._compile_module_job(gena, td, True)
    rb = B._compile_module_job(genb, td, True)
    req = B._generic_instance_requests([gena, genb], [ra, rb])
    got = req.get(gena, {})
    check('the caller\'s erased reference is a recognized generic-instance request',
          SYMBOL in got)
    if SYMBOL in got:
        check('the instance is a concrete definition of the template',
              ('def %s(' % SYMBOL) in got[SYMBOL]
              and 'poke[' not in got[SYMBOL].splitlines()[0])

    # 2. The dylib DEFINES it. This is the bug: before the pre-pass the symbol
    #    was in `nm -u` and nothing defined it.
    both = os.path.join(td, 'both.dylib')
    B.build([gena, genb], both, jobs=1)
    check('the two-module dylib defines the requested instance',
          ('_' + SYMBOL) in _nm(['nm', '-g', '-U', both]))
    check('the two-module dylib no longer references it undefined',
          ('_' + SYMBOL) not in _nm(['nm', '-u', both]))

    # 3. A module that only DECLARES the generic, with no caller in the link,
    #    still emits nothing for it — and the dylib still links and loads.
    only = os.path.join(td, 'definer_only.dylib')
    B.build([gena], only, jobs=1)
    check('a template nobody instantiates is not emitted',
          ('_' + SYMBOL) not in _nm(['nm', '-g', '-U', only]))
    from tools.stdlib_dylib_ratchet import unresolved_stdlib_refs, dylib_load_error
    check('the definer-only dylib loads', dylib_load_error(only) is None)
    check('the definer-only dylib references no undefined stdlib symbol',
          not unresolved_stdlib_refs(only))

# 4. Overload selection is PROVABLE, and an ambiguous request is declined: two
#    same-name generic templates whose erased signatures differ must never be
#    resolved by source order (a wrong body under the caller's symbol is a
#    silent miscompile; no definition is the documented source-fallback state).
PAIR = (
    'def pick[T: AnyType](x: T) -> Int:\n'
    '    return 1\n'
    '\n'
    '\n'
    'def pick[T: AnyType](x: Span[T]) -> Int:\n'
    '    return 2\n'
)
SUF_INT = GimpleGen.overload_suffix_for(['int64_t'])
SUF_CHAR = GimpleGen.overload_suffix_for(['char *'])
sel_int = B._select_generic_template(PAIR, 'pick', SUF_INT)
sel_char = B._select_generic_template(PAIR, 'pick', SUF_CHAR)
check('a typed request selects the template with that erased signature',
      bool(sel_int) and '(x: T)' in sel_int
      and bool(sel_char) and 'Span[T]' in sel_char)
check('a suffix-less (variadic) request with differing candidates is declined',
      B._select_generic_template(PAIR, 'pick', '') is None)
check('an unmatched suffix is declined',
      B._select_generic_template(PAIR, 'pick', '_abcdef') is None)
check('a name nothing declares is declined',
      B._select_generic_template(PAIR, 'absent', SUF_INT) is None)

print("%d passed, %d failed" % (len(PASS), len(FAIL)))
sys.exit(1 if FAIL else 0)
