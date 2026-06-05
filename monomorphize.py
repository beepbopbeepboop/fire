#!/usr/bin/env python3
"""Monomorphization engine — MODULE_CACHE_DESIGN.md stage 5.

A generic is not one symbol; each instantiation is. When a client uses
`Generic[ConcreteType]`, we compute a content key over (template identity,
concrete type args, comptime params), look it up in the shared CAS, and on a
miss instantiate → compile → publish. Instantiate once, ever: the next client or
build faults the instantiation in. This is the "compile cost = sum of *unique*
instantiations, not TU × instantiations" property — the thing C++ gets wrong.

The substitution here is intentionally simple (textual over a single-`fn`
template) — enough to prove the keying + cache mechanism end to end. The real
engine is AST-driven and hooks the existing whole-program analysis in
`DispatchSolver` (gimple_codegen.py); the *cache contract* it relies on is this
module's `instantiate()`.
"""
import os
import re
import tempfile
import subprocess

import cas
from build_config import find_gcc
from gimple_codegen import GimpleGen
from mojo_compiler import tokenize, Parser

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')
_OBJ_FLAGS = ('-fgimple', '-fPIC', f'-I{RUNTIME}')

_FN_HEAD = re.compile(r'\bfn\s+(\w+)\s*\[([^\]]*)\]')
# Generalized head: a `fn` or `struct` template with `[type params]`.
_HEAD = re.compile(r'\b(fn|struct)\s+(\w+)\s*\[([^\]]*)\]')


def safe_suffix(s: str) -> str:
    """Encode a type-arg string into a valid C identifier fragment: parametric
    args like `List[Int]` contain `[`/`]`/`,`/spaces, which are illegal in a C
    symbol, so map every non-[A-Za-z0-9_] char to `_` (review finding #4)."""
    return re.sub(r'[^A-Za-z0-9_]', '_', s)


def mangle(name: str, type_args: dict) -> str:
    """Stable monomorphized symbol name, e.g. box_id + {T:Int64} -> box_id_Int64.
    Suffixes are sanitized to valid C identifiers."""
    suffix = '_'.join(safe_suffix(str(type_args[k])) for k in sorted(type_args))
    return f"{name}_{suffix}" if suffix else name


def _check_no_value_shadow(src: str, type_params) -> None:
    """Raise if a type parameter is also used as a *binding name* (a `var`/`for`
    target or an assignment target). Textual substitution would then rewrite that
    value identifier to a type name — a silent miscompile (review finding #3). A
    type used as a constructor (`T()`) or in a type position is fine; only bindings
    are unsafe, and bindings shadowing a type parameter are pathological, so we
    fail loudly rather than emit wrong code."""
    for tp in type_params:
        e = re.escape(tp)
        if re.search(rf'\b(?:var|for)\s+{e}\b', src) or \
           re.search(rf'(?m)^\s*{e}\s*=(?!=)', src):
            raise ValueError(
                f"monomorphize: type parameter {tp!r} is used as a value/binding "
                f"name; cannot textually instantiate this template")


def monomorphize_source(template_src: str, type_args: dict) -> tuple:
    """Specialize a single `fn` OR `struct` generic template for concrete type
    args. Returns (mangled_name, concrete_source). Textual substitution: drop the
    `[params]` block, rename the definition, and replace each type-param
    identifier with its concrete type as a whole word."""
    m = _HEAD.search(template_src)
    if not m:
        raise ValueError("monomorphize: no generic `fn`/`struct name[...]` found")
    kind, name = m.group(1), m.group(2)
    mangled = mangle(name, type_args)

    # Guard against substituting a type param that's also used as a binding name
    # (silent miscompile otherwise — review finding #3).
    _check_no_value_shadow(template_src, list(type_args.keys()))

    # Drop the [type-params] block and rename the definition (fn or struct).
    src = template_src[:m.start()] + f"{kind} {mangled}" + template_src[m.end():]
    # Substitute each type parameter with its concrete type (whole-word).
    for tp, concrete in type_args.items():
        src = re.sub(rf'\b{re.escape(tp)}\b', str(concrete), src)
    return mangled, src


def compile_fn(fn_src: str, gcc: str = None) -> tuple:
    """Compile a concrete (non-generic) single-`fn` source to a CAS-cached object,
    keyed by its content. Used for overload instances (slice 4). Returns
    (object_path, hit)."""
    gcc = gcc or find_gcc()
    m = re.search(r'\bfn\s+(\w+)', fn_src)
    name = m.group(1) if m else 'fn'
    key = cas.instantiation_key(fn_src, {'__fn__': name}, None, gcc, _OBJ_FLAGS)

    def build():
        gen = GimpleGen(emit_entry_points=False, module_name=name)
        c = gen.gen_module(Parser(tokenize(fn_src)).parse_module())
        wd = tempfile.mkdtemp(prefix='mojo_ovl_')
        cf, of = os.path.join(wd, name + '.c'), os.path.join(wd, name + '.o')
        with open(cf, 'w') as f:
            f.write(c)
        subprocess.run([gcc, *_OBJ_FLAGS, '-c', '-o', of, cf], check=True)
        with open(of, 'rb') as f:
            return f.read()

    return cas.get_or_build(key, '.o', build)


def instantiate(template_src: str, type_args: dict, comptime_args: dict = None,
                gcc: str = None) -> tuple:
    """Instantiate template_src for type_args, via the shared CAS.
    Returns (mangled_name, object_path, hit)."""
    gcc = gcc or find_gcc()
    mangled, concrete = monomorphize_source(template_src, type_args)
    key = cas.instantiation_key(template_src, type_args, comptime_args, gcc, _OBJ_FLAGS)

    def build():
        gen = GimpleGen(emit_entry_points=False, module_name=mangled)
        c = gen.gen_module(Parser(tokenize(concrete)).parse_module())
        wd = tempfile.mkdtemp(prefix='mojo_inst_')
        cfile, ofile = os.path.join(wd, mangled + '.c'), os.path.join(wd, mangled + '.o')
        with open(cfile, 'w') as f:
            f.write(c)
        subprocess.run([gcc, *_OBJ_FLAGS, '-c', '-o', ofile, cfile], check=True)
        with open(ofile, 'rb') as f:
            return f.read()

    obj, hit = cas.get_or_build(key, '.o', build)
    return mangled, obj, hit
