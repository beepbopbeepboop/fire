#!/usr/bin/env python3
"""Build a stdlib dylib — MODULE_CACHE_DESIGN.md stage 2.

Compiles library `.mojo` modules (with NO entry points — they are libraries, not
programs) plus the runtime into one self-contained shared library
(`build/libmojostdlib.dylib`). Clients compile in *link mode* (extern decls only,
see `ABI.md`) and link `-lmojostdlib`; the bodies are demand-paged from the dylib.

This is the prebuilt "warm bundle" form of the content-addressed cache: present →
dlopen/mmap and fault in; absent → recompile the transitive closure.

Usage:
  python build_stdlib_dylib.py MOD.mojo [MOD2.mojo ...] [-o build/libmojostdlib.dylib]
"""
import os
import sys
import platform
import argparse
import tempfile
import subprocess

import cas
import reflect
from build_config import find_gcc
from gimple_codegen import GimpleGen, FromImportStmt
from mojo_compiler import tokenize, Parser
from module_loader import load_module

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')
DEFAULT_OUT = os.path.join(HERE, 'build', 'libmojostdlib.dylib')

# gcc flags that affect the object output — folded into the CAS key.
_OBJ_FLAGS = ('-fgimple', '-fPIC', f'-I{RUNTIME}')


def compile_module_to_c(src: str, path: str, module_name: str) -> str:
    """Transpile one library module to GIMPLE C with no main/entry points."""
    gen = GimpleGen(emit_entry_points=False, module_name=module_name)
    gen._current_filename = path
    return gen.gen_module(Parser(tokenize(src)).parse_module())


def _imported_sigs(src: str) -> list:
    """The signatures this module is compiled against — part of its CAS key, so a
    dependency's signature change invalidates this module's cached object."""
    sigs = []
    try:
        stmts = Parser(tokenize(src)).parse_module()
    except Exception:
        return sigs
    for s in stmts:
        if isinstance(s, FromImportStmt):
            exports = load_module(s.module)
            for name, _alias in s.names:
                info = exports.get(name)
                if info and info.get('signature'):
                    sigs.append(info['signature'])
    return sigs


def build(modules: list, out: str, use_cache: bool = True) -> str:
    gcc = find_gcc()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    workdir = tempfile.mkdtemp(prefix='mojostdlib_')
    objs = []

    def compile_one_object(src, path, name):
        """Cold-path builder: Mojo → C → .o; returns the object's bytes."""
        cfile = os.path.join(workdir, name + '.c')
        ofile = os.path.join(workdir, name + '.o')
        with open(cfile, 'w') as f:
            f.write(compile_module_to_c(src, path, name))
        subprocess.run([gcc, *_OBJ_FLAGS, '-c', '-o', ofile, cfile], check=True)
        with open(ofile, 'rb') as f:
            return f.read()

    all_exports = []
    for path in modules:
        name = os.path.splitext(os.path.basename(path))[0]
        src = open(path).read()
        all_exports.extend(reflect.collect_exports_src(src))
        if use_cache:
            key = cas.module_key(src, _imported_sigs(src), gcc, _OBJ_FLAGS)
            ofile, hit = cas.get_or_build(
                key, '.o', lambda s=src, p=path, n=name: compile_one_object(s, p, n))
        else:
            ofile = os.path.join(workdir, name + '.o')
            with open(ofile, 'wb') as f:
                f.write(compile_one_object(src, path, name))
        objs.append(ofile)

    # Reflection table (reflect.h / reflect.py): one merged __mojo_reflect over
    # all bundled modules, so the dylib is self-describing for any C-ABI consumer.
    reflect_c = os.path.join(workdir, '_mojo_reflect.c')
    reflect_o = os.path.join(workdir, '_mojo_reflect.o')
    with open(reflect_c, 'w') as f:
        f.write(reflect.emit_table_c(all_exports))
    subprocess.run([gcc, '-fPIC', f'-I{HERE}', '-c', '-o', reflect_o, reflect_c], check=True)
    objs.append(reflect_o)

    # Runtime is a FIRST-CLASS dylib (see runtime_dylib). Link it explicitly
    # so the module dylib's runtime symbol dependencies are resolved.
    rt = runtime_dylib(gcc)
    rt_dir = os.path.dirname(rt)
    link = _dylink(gcc, out, objs, undefined=False, rpath=rt_dir)
    # Link with the runtime dylib explicitly
    link.insert(len(link) - len(objs), rt)
    subprocess.run(link, check=True)
    return out


def _dylink(gcc, out, objs, undefined=False, rpath=None):
    """Platform dylib link command. undefined=True allows unresolved symbols
    (resolved at load from other dylibs, via dyld dynamic lookup)."""
    if platform.system() == 'Darwin':
        cmd = [gcc, '-dynamiclib',
               '-install_name', '@rpath/' + os.path.basename(out), '-o', out]
        if rpath:
            cmd += ['-Wl,-rpath,' + rpath]
        if undefined:
            cmd += ['-undefined', 'dynamic_lookup']
    else:
        cmd = [gcc, '-shared', '-fPIC', '-o', out]
        if undefined:
            cmd += ['-Wl,--allow-shlib-undefined']
        if rpath:
            cmd += ['-Wl,-rpath,' + rpath]
    return cmd + objs


def runtime_dylib(gcc: str = None, flags: tuple = ()) -> str:
    """Build (or find in the CAS) the first-class runtime dylib that exports the
    mojo_* runtime symbols. Every program links it; module dylibs depend on it."""
    gcc = gcc or find_gcc()
    src = open(os.path.join(RUNTIME, 'mojo_runtime.c')).read()
    key = 'rtdylib/' + cas._hash(
        'mojo-rtdylib-v1', cas.ABI_VERSION, cas.compiler_fingerprint(),
        cas.toolchain_fingerprint(gcc, flags), src)
    out = cas.path_for(key, '.dylib')
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        wd = tempfile.mkdtemp(prefix='mojo_rt_')
        o = os.path.join(wd, 'mojo_runtime.o')
        subprocess.run([gcc, '-fPIC', f'-I{RUNTIME}', '-c', '-o', o,
                        os.path.join(RUNTIME, 'mojo_runtime.c')], check=True)
        subprocess.run(_dylink(gcc, out, [o], undefined=False), check=True)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('modules', nargs='+', help='library .mojo modules to bundle')
    ap.add_argument('-o', '--output', default=DEFAULT_OUT, help='output dylib path')
    ap.add_argument('--no-cache', action='store_true', help='bypass the CAS')
    args = ap.parse_args()
    cas.reset_stats()
    out = build(args.modules, args.output, use_cache=not args.no_cache)
    msg = f"built {out} from {len(args.modules)} module(s) + runtime"
    if not args.no_cache:
        msg += f"  [cas hits={cas.stats['hits']} misses={cas.stats['misses']}]"
    print(msg)


if __name__ == '__main__':
    main()
