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


def _excluded_platform(fname: str) -> bool:
    """True if a platform-specific module does not match the host OS. The stdlib
    ships per-OS variants (os/_macos.mojo vs os/_linux_x86.mojo, pwd/_linux.mojo
    vs pwd/_macos.mojo) that define the *same* symbols; linking all of them into
    one dylib is a duplicate-symbol error. Keep only the host's variant."""
    stem = fname[:-len('.mojo')] if fname.endswith('.mojo') else fname
    host = platform.system()
    tags = {'_linux': 'Linux', '_macos': 'Darwin', '_windows': 'Windows'}
    for tag, osname in tags.items():
        if (stem == tag or stem.endswith(tag) or (tag + '_') in stem) and host != osname:
            return True
    return False


def stdlib_modules() -> list:
    """All library .mojo files under STDLIB_PATH (no tests, no programs)."""
    modules = []
    std_root = os.path.join(STDLIB_PATH, 'std') if os.path.isdir(
        os.path.join(STDLIB_PATH, 'std')) else STDLIB_PATH
    for dirpath, dirnames, filenames in os.walk(std_root):
        # prune test subtrees in-place
        dirnames[:] = [d for d in dirnames if d not in ('test', 'tests', 'benchmarks')]
        for fname in filenames:
            if fname.endswith('.mojo') and not _excluded_platform(fname):
                modules.append(os.path.join(dirpath, fname))
    return sorted(modules)

# gcc flags that affect the object output — folded into the CAS key.
# __MOJO_STDLIB_MODE__ must be defined: stdlib modules provide their own
# definitions of symbols the runtime header would otherwise declare
# (write/open/close/...), and the header guards those under this macro.
_OBJ_FLAGS = ('-fgimple', '-fPIC', '-D__MOJO_STDLIB_MODE__', f'-I{RUNTIME}')


def compile_module_to_c(src: str, path: str, module_name: str) -> str:
    """Transpile one library module to GIMPLE C with no main/entry points.

    Deep-but-finite generic-instantiation chains (a module pulling in nested
    generics) can run many thousands of Python frames deep on a COLD cache before
    the CAS shortcuts them. Run codegen in a thread with a large stack and a high
    recursion limit so legitimate deep cascades complete instead of crashing the
    module into a source-fallback skip. (True non-convergence — instantiating with
    symbolic type args — is prevented at the call site, not papered over here.)"""
    import threading
    import monomorphize
    # Fresh elaborator state per module so a prior module's crash can't pollute
    # this one (cross-module domino).
    monomorphize._IN_PROGRESS.clear()
    monomorphize.ELAB_DEPTH[0] = 0
    box: dict = {}

    def _run():
        try:
            sys.setrecursionlimit(120000)
            gen = GimpleGen(emit_entry_points=False, module_name=module_name)
            gen._current_filename = path
            box['c'] = gen.gen_module(Parser(tokenize(src)).parse_module())
        except BaseException as e:   # propagate to the caller's thread
            box['err'] = e

    for _sz in (1024 * 1024 * 1024, 512 * 1024 * 1024, 256 * 1024 * 1024):
        try:
            threading.stack_size(_sz)   # room for ~100k frames
            break
        except Exception:
            continue
    t = threading.Thread(target=_run)
    t.start()
    t.join()
    if 'err' in box:
        raise box['err']
    return box['c']


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


def _defined_symbols(gcc: str, obj: str) -> set:
    """External symbols *defined* (not undefined) by an object file, via nm.
    Used to drop modules whose symbols collide with an already-included one."""
    nm = 'nm'  # llvm/bsd nm on the PATH; gcc toolchains ship a compatible one
    try:
        out = subprocess.run([nm, '-g', obj], capture_output=True, text=True).stdout
    except Exception:
        return set()
    syms = set()
    for line in out.splitlines():
        parts = line.split()
        # Defined external: "<addr> <TYPE> <name>"; undefined: "<TYPE=U> <name>".
        # Uppercase type letter (T/D/S/B/C/I/R) = external & defined.
        if len(parts) >= 3 and parts[1] in ('T', 'D', 'S', 'B', 'C', 'I', 'R'):
            syms.add(parts[2])
    return syms


def _localize_symbols(obj: str, syms: set, workdir: str, name: str) -> str:
    """Make `syms` file-local in a COPY of `obj` so it can join the link without a
    duplicate-definition clash, while the object's other globals stay exported.

    This is how two modules that each carry a copy of the same generic struct
    (e.g. DeviceBuffer in device_context.mojo and _device_context_hal.mojo, both
    emitting _DeviceBuffer___len__) can both be included: the first keeps the
    exported symbol, the later one's duplicate is demoted to a local definition.
    Returns the path to the edited copy, or '' if no symbol-editing tool is found
    (caller then falls back to excluding the whole module). Portable across the GNU
    (objcopy) and macOS (nmedit) toolchains."""
    edited = os.path.join(workdir, name + '.local.o')
    with open(obj, 'rb') as fi, open(edited, 'wb') as fo:
        fo.write(fi.read())
    import shutil
    objcopy = shutil.which('objcopy') or shutil.which('gobjcopy')
    if objcopy:
        cmd = [objcopy]
        for s in sorted(syms):
            cmd += ['--localize-symbol', s]
        cmd.append(edited)
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return edited
        except Exception:
            return ''
    nmedit = shutil.which('nmedit')
    if nmedit:
        # nmedit -s <keep> localizes every global NOT listed; keep = defs - syms.
        keep = _defined_symbols(find_gcc(), edited) - set(syms)
        keepfile = os.path.join(workdir, name + '.keep')
        with open(keepfile, 'w') as f:
            f.write('\n'.join(sorted(keep)) + '\n')
        try:
            subprocess.run([nmedit, '-s', keepfile, edited],
                           check=True, capture_output=True)
            return edited
        except Exception:
            return ''
    return ''


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

    # Greedy symbol-collision dedup: the dylib is a speed hack (a client uses a
    # symbol from it if present, else falls back to source), so it need not be
    # complete — it must only link. When two modules define the same external
    # symbol (e.g. an `abs` overload in both math and complex -> mojo_abs), keep
    # the first and drop the colliding module (and its reflection exports). This
    # is a stopgap; the real fix is overload-aware mangling of free functions
    # (STDLIB-BUGS.md SB-1). Written plainly so the self-host compiler handles it.
    all_exports = []
    seen_syms = set()
    skipped = 0
    excluded = 0
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
        defs = _defined_symbols(gcc, ofile)
        clash = defs & seen_syms
        if clash:
            # A duplicate definition (e.g. a generic struct copied into two modules).
            # Rather than drop the whole module — losing its UNIQUE symbols too —
            # demote just the clashing symbols to file-local in this object and keep
            # the rest. The first module's copy stays the exported definition.
            edited = _localize_symbols(ofile, clash, workdir, name)
            if edited:
                ofile = edited
                defs = defs - clash   # clashing syms no longer exported here
                print(f"  localize {len(clash)} dup symbol(s) in {name} "
                      f"(e.g. {sorted(clash)[0]})", file=sys.stderr)
            else:
                one = sorted(clash)[0]
                print(f"  exclude {name} from dylib: symbol already defined ({one})",
                      file=sys.stderr)
                excluded += 1
                continue
        seen_syms |= defs
        objs.append(ofile)
        all_exports.extend(exports)
    if skipped:
        print(f"  ({skipped} modules skipped)", file=sys.stderr)
    if excluded:
        print(f"  ({excluded} modules excluded for symbol collisions)", file=sys.stderr)

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
    # -fno-builtin: the table forward-declares every exported symbol as
    # `extern void sym();` purely to take its address. Some exported names
    # collide with C builtins (memcmp, nan, isnan, …); without -fno-builtin gcc
    # rejects the unprototyped redeclaration as a conflicting type.
    subprocess.run([gcc, '-fno-builtin', '-fPIC', f'-I{HERE}', '-c', '-o', reflect_o, reflect_c], check=True)
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
    modules = stdlib_modules()
    if args.modules:
        modules = list(args.modules)
    cas.reset_stats()
    out = build(modules, args.output, use_cache=not args.no_cache)
    msg = f"built {out} from {len(modules)} module(s) + runtime"
    if not args.no_cache:
        msg += f"  [cas hits={cas.stats['hits']} misses={cas.stats['misses']}]"
    print(msg)


if __name__ == '__main__':
    main()
