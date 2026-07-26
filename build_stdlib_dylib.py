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
import shutil
import platform
import argparse
import tempfile
import subprocess
from concurrent.futures import ProcessPoolExecutor

import cas
import reflect
from build_config import find_gcc
from gimple_codegen import GimpleGen, FromImportStmt
from mojo_compiler import py_tokenize, Parser
from module_loader import load_module, STDLIB_PATH, module_name_for_path

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
            box['c'] = gen.gen_module(Parser(py_tokenize(src)).parse_module())
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


_stdlib_compile_cache: dict = {}  # in-process L1 for compile_module_to_c_cached


def compile_module_to_c_cached(src: str, path: str, module_name: str) -> str:
    """Like compile_module_to_c but CAS-cached under stdlib-compile/<hash>.

    The key folds in the compiler fingerprint (a codegen change invalidates
    every cached .ci) and the stdlib fingerprint (a module's C depends on its
    stdlib imports' signatures/layouts, so any stdlib edit invalidates too)."""
    key = cas.stdlib_compile_key(src, path, module_name)
    return cas.get_or_build_text(
        key, '.ci', lambda: compile_module_to_c(src, path, module_name),
        _stdlib_compile_cache)


def _imported_sigs(src: str) -> list:
    """The signatures this module is compiled against — part of its CAS key, so a
    dependency's signature change invalidates this module's cached object."""
    sigs = []
    try:
        stmts = Parser(py_tokenize(src)).parse_module()
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


def _module_name_for(path: str) -> str:
    """Thin re-export — the real logic now lives in module_loader.py
    (module_name_for_path) so gimple_codegen.py's cross-module struct-method
    qualification can call the EXACT same function on the exact same
    resolved file path, guaranteeing both sides of a qualified symbol name
    agree by construction. Kept here under the old name for callers within
    this file / anyone else already importing it from build_stdlib_dylib."""
    return module_name_for_path(path)


def _compile_one_object(src: str, path: str, name: str, workdir: str, gcc: str) -> bytes:
    """Cold-path builder: Mojo → C → .o; returns the object's bytes."""
    cfile = os.path.join(workdir, name + '.c')
    ofile = os.path.join(workdir, name + '.o')
    with open(cfile, 'w') as f:
        f.write(compile_module_to_c(src, path, name))
    subprocess.run([gcc, *_OBJ_FLAGS, '-c', '-o', ofile, cfile], check=True)
    with open(ofile, 'rb') as f:
        return f.read()


def _compile_module_job(path: str, workdir: str, use_cache: bool):
    """Per-module independent work (source → object): read, collect exports,
    compile (cache-or-build). Each module is fully independent — no shared
    state — so this parallelizes across processes the same way
    compile_stdlib.py's transpile_file does. Returns (path, name, ofile,
    exports, error, hit) — error is None on success; the symbol-collision
    dedup afterward (order-sensitive, so kept sequential) reads ofile.

    `hit` reports this job's own CAS hit/miss so the parent can aggregate
    cas.stats: with -j>1 each job runs in its own worker process, so
    cas.get_or_build's in-process stats increment is invisible to the
    parent's cas.stats (a separate module-global per process) — the
    aggregate would otherwise silently under-report."""
    gcc = find_gcc()
    name = _module_name_for(path)
    src = open(path).read()
    try:
        # module_prefix=name: the SAME identity GimpleGen(module_name=name)
        # below uses when actually compiling this module, so the reflection
        # table's advertised method symbols match what codegen emits.
        exports = reflect.collect_exports_src(src, module_prefix=name)
    except Exception:
        exports = []
    hit = None
    try:
        if use_cache:
            key = cas.module_key(src, _imported_sigs(src), gcc, _OBJ_FLAGS)
            ofile, hit = cas.get_or_build(
                key, '.o', lambda: _compile_one_object(src, path, name, workdir, gcc))
        else:
            ofile = os.path.join(workdir, name + '.o')
            with open(ofile, 'wb') as f:
                f.write(_compile_one_object(src, path, name, workdir, gcc))
    except Exception as e:
        return path, name, None, exports, str(e), hit
    return path, name, ofile, exports, None, hit


def build(modules: list, out: str, use_cache: bool = True, link_runtime: bool = False,
          extra_exports: list = None, jobs: int = 1) -> str:
    gcc = find_gcc()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    workdir = tempfile.mkdtemp(prefix='mojostdlib_')
    objs = []

    # Compile every module's source → object first (fully independent per
    # module, so parallelizes cleanly across processes — same scheme as
    # compile_stdlib.py's ProcessPoolExecutor use). Order is preserved
    # (pool.map, not as_completed) because the symbol-collision dedup below
    # is order-sensitive ("first module wins") and must stay sequential.
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(
                _compile_module_job, modules,
                [workdir] * len(modules), [use_cache] * len(modules)))
        # Merge each job's own CAS hit/miss into this process's cas.stats —
        # see _compile_module_job's docstring on why worker-process stats
        # don't propagate on their own. Only needed here: the jobs<=1 path
        # below calls cas.get_or_build in-process, where it already
        # increments cas.stats directly — redoing it here would double-count.
        for r in results:
            hit = r[-1]
            if hit is True:
                cas.stats['hits'] += 1
            elif hit is False:
                cas.stats['misses'] += 1
    else:
        results = [_compile_module_job(path, workdir, use_cache) for path in modules]

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
    for path, name, ofile, exports, error, _hit in results:
        if error is not None:
            print(f"  skip {os.path.relpath(path)}: {error}", file=sys.stderr)
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

    # Safety net: an export entry (from reflect.collect_exports_src's source
    # scan, or from extra_exports/collect_runtime_exports_h's header scan)
    # can drift out of sync with what actually got a compiled body — e.g.
    # BUG-2026-036, where a same-file overloaded free function (`def
    # CUDA(...)` declared twice in std/gpu/host/_nvidia_cuda.mojo) was still
    # advertised as a normal export even though gen_module's own "overloaded
    # top-level functions ... can't be emitted as distinct C symbols, drop
    # them here" pass never compiled a body for it, or a stale prototype in
    # mojo_runtime.h (e.g. MojoList__write_to) was never actually defined in
    # mojo_runtime.c. Either way the reflection table would forward-declare
    # and take the address of a symbol with zero definitions anywhere in the
    # dylib — `extern void sym();` with nothing behind it — which links fine
    # (production dylibs use `-undefined dynamic_lookup`) but crashes EVERY
    # dlopen of the dylib at runtime with "symbol not found in flat
    # namespace", not just uses of the broken function. Cross-check every
    # non-TYPE export's expected C symbol against what `nm` says the actual
    # object set defines, and drop anything orphaned instead of shipping a
    # dylib that can't even be loaded.
    all_defs = set()
    for o in objs:
        all_defs |= _defined_symbols(gcc, o)
    _kept = []
    for e in all_exports:
        if e['kind'] == reflect.SYM_TYPE or ('_' + reflect.export_csym(e)) in all_defs:
            _kept.append(e)
        else:
            print(f"  drop stale export {e['name']!r}: "
                  f"{reflect.export_csym(e)} has no definition in the built objects",
                  file=sys.stderr)
    all_exports = _kept

    # Reflection table source — deterministic given all_exports, so it can
    # participate in the dylib link key before writing the file.
    reflect_src = reflect.emit_table_c(all_exports)

    # Compute dylib link key and check CAS.  The key folds in every .o on the
    # link line (module objects + runtime .o or runtime dylib digest), the
    # reflect table source, the toolchain, and the link mode — so changing any
    # object or configuration invalidates the cached dylib.
    extra_link_digest = cas.file_digest(rt_dylib) if link_runtime else ''
    link_key = cas.dylib_link_key(
        objs, reflect_src, gcc, undefined=not link_runtime,
        extra_digest=extra_link_digest)
    if use_cache:
        cached_dylib = cas.lookup(link_key, '.dylib')
        if cached_dylib:
            cas.stats['hits'] += 1
            shutil.copy(cached_dylib, out)
            return out
        cas.stats['misses'] += 1

    # Reflection table: one merged __mojo_reflect over all Mojo modules + runtime.
    reflect_c = os.path.join(workdir, '_mojo_reflect.c')
    reflect_o = os.path.join(workdir, '_mojo_reflect.o')
    with open(reflect_c, 'w') as f:
        f.write(reflect_src)
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
    # Publish the linked dylib to the shared CAS so future builds skip the link
    # (even on use_cache=False runs: the fresh link is the correct artifact).
    with open(out, 'rb') as f:
        cas.publish(link_key, '.dylib', f.read())
    return out


def _dylink(gcc, out, objs, undefined=False, rpath=None, extra_libs=None, link_driver=None):
    """Platform dylib link command. undefined=True allows unresolved symbols
    (resolved at load from other dylibs, via dyld dynamic lookup).

    link_driver: override the link-time driver binary (e.g. find_gxx()'s g++)
    used in place of `gcc` for just this final link invocation. Every
    individual module's .c -> .o compile step is unaffected — this only
    matters when `objs` includes at least one C++-derived object (the
    generator-coroutine codegen path, not yet wired into any real build —
    see build_config.find_gxx()'s docstring). Defaults to `gcc`, so ordinary
    all-C builds are unchanged."""
    driver = link_driver or gcc
    if platform.system() == 'Darwin':
        cmd = [driver, '-dynamiclib',
               '-install_name', '@rpath/' + os.path.basename(out), '-o', out]
        if rpath:
            cmd += ['-Wl,-rpath,' + rpath]
        if undefined:
            cmd += ['-undefined', 'dynamic_lookup']
    else:
        cmd = [driver, '-shared', '-fPIC', '-o', out]
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


def build_stdlib(out: str = DEFAULT_OUT, use_cache: bool = True, jobs: int = 1) -> str:
    """Build the monolithic stdlib dylib from all auto-discovered library modules."""
    rt_header = os.path.join(RUNTIME, 'mojo_runtime.h')
    rt_exports = reflect.collect_runtime_exports_h(rt_header)
    return build(stdlib_modules(), out, use_cache=use_cache, extra_exports=rt_exports, jobs=jobs)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('modules', nargs='*', help='library .mojo modules to bundle (default: all stdlib)')
    ap.add_argument('-o', '--output', default=DEFAULT_OUT, help='output dylib path')
    ap.add_argument('--no-cache', action='store_true', help='bypass the CAS')
    ap.add_argument('-j', '--jobs', type=int, default=os.cpu_count(),
                     help='Parallel workers for the per-module Mojo→C→.o compile '
                          '(each module is independent, same scheme as '
                          'compile_stdlib.py). Default: os.cpu_count(). Use -j1 '
                          'for sequential (deterministic ordering, easier to read '
                          'failures as they happen).')
    args = ap.parse_args()
    modules = stdlib_modules()
    if args.modules:
        modules = list(args.modules)
    cas.reset_stats()
    out = build(modules, args.output, use_cache=not args.no_cache, jobs=args.jobs)
    msg = f"built {out} from {len(modules)} module(s) + runtime"
    if not args.no_cache:
        msg += f"  [cas hits={cas.stats['hits']} misses={cas.stats['misses']}]"
    print(msg)


if __name__ == '__main__':
    main()
