#!/usr/bin/env python3
"""Build a stdlib dylib — MODULE_CACHE_DESIGN.md stage 2.

Compiles all stdlib library `.mojo` modules (files with no entry point) into one
self-contained shared library (`build/libmojostdlib.dylib`).  Clients compile in
*link mode* (extern decls only, see `ABI.md`) and link `-lmojostdlib`; the bodies
are demand-paged from the dylib.

The dylib is monolithic — every importable stdlib symbol is present — so the
runtime reflection table (`__mojo_reflect`) is authoritative for symbol resolution.
Build is driven on-demand by the driver, never by `make`.

Usage (manual):
  python build_stdlib_dylib.py [-o build/libmojostdlib.dylib]
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
from module_loader import load_module, STDLIB_PATH

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')
DEFAULT_OUT = os.path.join(HERE, 'build', 'libmojostdlib.dylib')


def stdlib_modules() -> list:
    """All library .mojo files under STDLIB_PATH (no tests, no programs)."""
    modules = []
    std_root = os.path.join(STDLIB_PATH, 'std') if os.path.isdir(
        os.path.join(STDLIB_PATH, 'std')) else STDLIB_PATH
    for dirpath, dirnames, filenames in os.walk(std_root):
        # prune test subtrees in-place
        dirnames[:] = [d for d in dirnames if d not in ('test', 'tests', 'benchmarks')]
        for fname in filenames:
            if fname.endswith('.mojo'):
                modules.append(os.path.join(dirpath, fname))
    return sorted(modules)

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
            try:
                exports = load_module(s.module)
            except Exception:
                continue
            for name, _alias in s.names:
                info = exports.get(name)
                if info and info.get('signature'):
                    sigs.append(info['signature'])
    return sigs


def build(modules: list, out: str, use_cache: bool = True, link_runtime: bool = False,
          extra_exports: list = None) -> str:
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
    skipped = 0
    for path in modules:
        # Use path-relative module name so __init__.mojo files from different
        # packages get unique symbol prefixes (std_os___init__ vs std___init__).
        # Fall back to basename for modules outside STDLIB_PATH (e.g. test modules)
        # — os.path.relpath would produce '../../../...' paths with dots that are
        # invalid in C identifiers and cause GCC to reject the generated .c file.
        rel = os.path.relpath(path, STDLIB_PATH)
        if rel.startswith('..'):
            name = os.path.splitext(os.path.basename(path))[0].replace('-', '_')
        else:
            name = os.path.splitext(rel)[0].replace(os.sep, '_').replace('-', '_')
        src = open(path).read()
        try:
            exports = reflect.collect_exports_src(src)
        except Exception:
            exports = []
        try:
            if use_cache:
                key = cas.module_key(src, _imported_sigs(src), gcc, _OBJ_FLAGS)
                ofile, hit = cas.get_or_build(
                    key, '.o', lambda s=src, p=path, n=name: compile_one_object(s, p, n))
            else:
                ofile = os.path.join(workdir, name + '.o')
                with open(ofile, 'wb') as f:
                    f.write(compile_one_object(src, path, name))
        except Exception as e:
            print(f"  skip {os.path.relpath(path)}: {e}", file=sys.stderr)
            skipped += 1
            continue
        all_exports.extend(exports)
        objs.append(ofile)
    if skipped:
        print(f"  ({skipped} modules skipped)", file=sys.stderr)

    # Runtime handling:
    # - For production (link_runtime=False): compile mojo_runtime.c into an object
    #   and fold it into the dylib (no separate runtime dylib needed)
    # - For testing (link_runtime=True): build separate runtime dylib and link against it
    rt_src = os.path.join(RUNTIME, 'mojo_runtime.c')
    rt_key = 'rtobj/' + cas._hash(
        'mojo-rtobj-v1', cas.ABI_VERSION, cas.compiler_fingerprint(),
        cas.toolchain_fingerprint(gcc, ()), open(rt_src).read())

    if link_runtime:
        # For test modules: link against standalone runtime dylib
        rt_dylib = runtime_dylib(gcc)
        rt_path = rt_dylib
    else:
        # For production: include runtime object directly
        def _build_rt_obj():
            o = os.path.join(workdir, 'mojo_runtime.o')
            subprocess.run([gcc, '-fPIC', f'-I{RUNTIME}', '-c', '-o', o, rt_src], check=True)
            return open(o, 'rb').read()
        rt_o, _ = cas.get_or_build(rt_key, '.o', _build_rt_obj)
        objs.append(rt_o)
        rt_path = None

    if extra_exports:
        all_exports.extend(extra_exports)

    # Reflection table: one merged __mojo_reflect over all Mojo modules + runtime.
    reflect_c = os.path.join(workdir, '_mojo_reflect.c')
    reflect_o = os.path.join(workdir, '_mojo_reflect.o')
    with open(reflect_c, 'w') as f:
        f.write(reflect.emit_table_c(all_exports))
    subprocess.run([gcc, '-fPIC', f'-I{HERE}', '-c', '-o', reflect_o, reflect_c], check=True)
    objs.append(reflect_o)

    # Linking depends on whether runtime is included or linked separately
    if link_runtime:
        # For test modules: link against runtime dylib, all symbols must resolve
        link = _dylink(gcc, out, objs, undefined=False, extra_libs=[rt_path],
                      rpath=os.path.dirname(rt_path))
    else:
        # For production: cross-module references resolve at load time
        link = _dylink(gcc, out, objs, undefined=True)
    subprocess.run(link, check=True)
    return out


def _dylink(gcc, out, objs, undefined=False, rpath=None, extra_libs=None):
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
    # Objects first, then extra libs (dependencies must come after the objects that use them)
    result = cmd + objs
    if extra_libs:
        result.extend(extra_libs)
    return result



def runtime_dylib(gcc: str = None, flags: tuple = ()) -> str:
    """Build (or find in the CAS) the runtime dylib that exports mojo_* symbols.

    The stdlib dylib now includes the runtime, but test modules and external
    clients need a separate runtime dylib to link against and resolve symbols.
    Built with all symbols resolved (undefined=False).
    """
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


def build_stdlib(out: str = DEFAULT_OUT, use_cache: bool = True) -> str:
    """Build the monolithic stdlib dylib from all auto-discovered library modules."""
    rt_header = os.path.join(RUNTIME, 'mojo_runtime.h')
    rt_exports = reflect.collect_runtime_exports_h(rt_header)
    return build(stdlib_modules(), out, use_cache=use_cache, extra_exports=rt_exports)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('modules', nargs='*', help='library .mojo modules to bundle (default: all stdlib)')
    ap.add_argument('-o', '--output', default=DEFAULT_OUT, help='output dylib path')
    ap.add_argument('--no-cache', action='store_true', help='bypass the CAS')
    args = ap.parse_args()
    modules = args.modules or stdlib_modules()
    cas.reset_stats()
    out = build(modules, args.output, use_cache=not args.no_cache)
    msg = f"built {out} from {len(modules)} module(s) + runtime"
    if not args.no_cache:
        msg += f"  [cas hits={cas.stats['hits']} misses={cas.stats['misses']}]"
    print(msg)


if __name__ == '__main__':
    main()
