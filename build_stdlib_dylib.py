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
import contextlib
import fcntl
from concurrent.futures import ProcessPoolExecutor

import cas
import reflect
from build_config import find_gcc, find_gxx
from gimple_codegen import GimpleGen, FromImportStmt
from fire_compiler import py_tokenize, Parser
from module_loader import load_module, STDLIB_PATH, module_name_for_path

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')
DEFAULT_OUT = os.path.join(HERE, 'build', 'libmojostdlib.dylib')

# ── Target architecture ─────────────────────────────────────────────────────
#
# An artifact is built for a TARGET; `platform.machine()` reports the HOST, and
# the two come apart the moment anything builds for the other member of the
# pair — which `tools/formal_sweep.py --arch` does, on every run, for both.
# Until now nothing here had a notion of a target at all: `runtime_dylib()`'s
# CAS key folded in the *host* (through `toolchain_fingerprint`) and its output
# name had no architecture in it, so the two were the same cache entry wearing
# the same file name.
#
# Four things have to carry the arch, and the fourth is the one that catches a
# mistake rather than preventing one:
#
#   1. the CAS key, or a hit serves one architecture's bytes for the other;
#   2. the OUTPUT NAME, or the two overwrite each other on disk even when the
#      keys are right (a caller may pass any directory it likes — see
#      `formal/imports.py`'s own note on why a name collision one level up
#      reintroduces exactly this);
#   3. the compile and link flags;
#   4. the VERIFICATION of what came out.
#
# (4) is load-bearing because a flag being ACCEPTED is not a flag being
# obeyed. Measured on this tree: `/opt/local/bin/gcc-mp-15 -arch x86_64 -c`
# prints "warning: this compiler does not support x86 ('-arch' option
# ignored)" and emits an **arm64** object, exit 0. A build rule that trusted the
# flag would produce a dylib named `.x86_64.dylib` containing arm64 code, and
# the failure would surface at `dlopen` — "mach-o file, but is an incompatible
# architecture" — in a completely different program, later. So `toolchain_for`
# MEASURES what each candidate driver can target and `object_arch` reads the
# arch back out of the emitted Mach-O.

_ARCH_ALIASES = {
    'aarch64': 'arm64', 'arm64e': 'arm64', 'armv8': 'arm64', 'arm': 'arm64',
    'amd64': 'x86_64', 'x86-64': 'x86_64', 'x64': 'x86_64', 'x86': 'i386',
    'i686': 'i386',
}
_HOST_ARCH = platform.machine().lower()


def normalize_arch(arch: str = None) -> str:
    """`arch` in one canonical spelling; the host's when `arch` is None or ''.

    Every arch that reaches an artifact's identity passes through here, so
    'aarch64' and 'arm64' — which `uname -m` and Apple's `-arch` respectively
    report, and which therefore both occur in this tree — name ONE cache
    entry rather than two identical builds, and cannot be mistaken for two
    architectures by a caller that only ever used one spelling.
    """
    if not arch:
        arch = _HOST_ARCH
    return _ARCH_ALIASES.get(arch.lower(), arch.lower())


def arch_flags(arch: str) -> tuple:
    """The per-target flags for a driver that HONOURS them (see above).

    Empty off Darwin on purpose: the artifact here is a Mach-O dylib (install
    name, `-dynamiclib`, `@rpath`), so a cross-architecture build of it is a
    Darwin question, and mapping a foreign arch onto `-m32`/`-m64` would be a
    different artifact pretending to be the same one.
    """
    if platform.system() != 'Darwin':
        return ()
    return ('-arch', normalize_arch(arch))


def arches_of(path: str) -> frozenset:
    """The architectures a Mach-O file really contains, read back from the file.

    This is the check that makes the arch in a cache key an assertion rather
    than a hope, and it deliberately asks the SYSTEM TOOL rather than
    re-parsing the header: `lipo -archs` is dyld's own view of the thing, so
    there is no second Mach-O reader in this file to disagree with the loader
    that will eventually have to load it. `file` is the fallback for a
    toolchain without `lipo`; if neither exists the answer is UNKNOWN, which
    callers must treat as "do not claim this artifact is for `arch`" rather
    than as a pass.
    """
    lipo = shutil.which('lipo')
    if lipo:
        try:
            out = subprocess.run([lipo, '-archs', path], capture_output=True,
                                 text=True).stdout.strip()
            if out:
                return frozenset(out.split())
        except Exception:
            pass
    filecmd = shutil.which('file')
    if filecmd:
        try:
            out = subprocess.run([filecmd, '-b', path], capture_output=True,
                                 text=True).stdout
        except Exception:
            out = ''
        found = set()
        for name in ('arm64', 'x86_64', 'i386', 'ppc64', 'ppc'):
            # "Mach-O 64-bit object arm64" / "... universal binary with 2
            # architectures: [x86_64:...] [arm64:...]"
            if name in out:
                found.add(name)
        if found:
            return frozenset(found)
    return frozenset()


class ArchError(RuntimeError):
    """No available toolchain can target the requested architecture, or an
    artifact came out for a different one than the one that was asked for."""


def _arch_or_die(path: str, arch: str, what: str) -> None:
    """Fail loudly when an artifact is not for the architecture it was built for.

    A silent mismatch is the whole failure this exists to prevent (see the
    warning at the top): the artifact links, the program builds, and the error
    appears at `dlopen` in an unrelated program with no thread back to here.
    """
    found = arches_of(path)
    if found and arch in found:
        return
    raise ArchError(
        f"{what} is {'/'.join(sorted(found)) or 'of unknown architecture'}, "
        f"not {arch}: {path}")


# A trivial translation unit, compiled by `toolchain_for` to MEASURE what a
# driver can target. `int`/nothing/return, so no header, no libc, no language
# feature — a driver that cannot compile this cannot compile the runtime.
_PROBE_SRC = 'int mojo_probe(void) { return 0; }\n'

# (driver, arch) -> (works, measured reason). Per-process; the probe is two
# forks and the answer cannot change while the process lives.
_driver_probe: dict = {}


def _driver_targets(driver: str, arch: str) -> tuple:
    """(works, why) — can `driver` emit an object FOR `arch`? Measured, not assumed."""
    key = (driver, arch)
    if key in _driver_probe:
        return _driver_probe[key]
    result = (False, 'not probed')
    try:
        wd = tempfile.mkdtemp(prefix='mojo_archprobe_')
        src = os.path.join(wd, 'probe.c')
        out = os.path.join(wd, 'probe.o')
        with open(src, 'w') as f:
            f.write(_PROBE_SRC)
        proc = subprocess.run([driver, *arch_flags(arch), '-c', '-o', out, src],
                              capture_output=True, text=True)
        if proc.returncode == 0 and os.path.exists(out):
            made = arches_of(out)
            if arch in made:
                result = (True, '')
            else:
                result = (False, f"emits {'/'.join(sorted(made)) or 'an object of unknown arch'}"
                                 f" for -arch {arch}")
        else:
            detail = (proc.stderr or proc.stdout or '').strip().splitlines()
            result = (False, detail[-1] if detail else f'exit {proc.returncode}')
    except Exception as e:
        result = (False, str(e))
    _driver_probe[key] = result
    return result


def toolchain_for(arch: str, gcc: str = None, gxx: str = None) -> tuple:
    """(cc, cxx) — drivers that can actually TARGET `arch`, or ArchError.

    The configured `build_config.find_gcc()`/`find_gxx()` come first, so for
    the host architecture this returns exactly what every caller got before
    and nothing about an ordinary build changes. Only when the preferred driver
    cannot target the requested architecture does this look further, and then
    the error it raises names what it measured for each candidate rather than
    saying "unsupported" — "this compiler does not support x86 ('-arch'
    option ignored)" is the difference between a bug report that is actionable
    and one that is not.
    """
    arch = normalize_arch(arch)
    cands_cc = [gcc] if gcc else []
    cands_cc += ['gcc', 'cc', 'clang']
    cands_cxx = [gxx] if gxx else []
    cands_cxx += ['g++', 'c++', 'clang++']
    cc = ''
    tried = []
    for c in cands_cc:
        if not c:
            continue
        # Resolved to a path before it is used or reported: on this machine
        # `gcc` on PATH is Apple clang, and a log that says "gcc: cannot
        # target x86_64" when it means /usr/bin/gcc is a message that sends
        # the next reader to install a gcc that is already installed and
        # already works.
        path = shutil.which(c) or (c if os.path.isabs(c) and os.path.exists(c) else '')
        if not path:
            continue
        ok, why = _driver_targets(path, arch)
        if ok:
            cc = path
            break
        tried.append(f"{path}: {why}")
    if not cc:
        raise ArchError(
            f"no C compiler on this machine can target {arch}"
            + (" (" + "; ".join(tried) + ")" if tried else " (none found)"))
    cxx = ''
    for c in cands_cxx:
        path = shutil.which(c) or ''
        if not path:
            continue
        ok, _why = _driver_targets(path, arch)
        if ok:
            cxx = path
            break
    if not cxx:
        # A C++ driver is only needed for the one .cpp unit. Falling back to
        # the C driver would fail later with a less useful message, so say so
        # here and let the caller decide.
        raise ArchError(
            f"no C++ compiler on this machine can target {arch}, and the "
            f"runtime dylib links {_CPP_UNIT}")
    return cc, cxx


# ── The runtime's translation units: ONE table, two callers ─────────────────
#
# `build()`'s production path and `runtime_dylib()` used to carry two
# hand-maintained copies of this list, which is how they came to disagree in
# every field except the filenames: `runtime_dylib()` took a `flags` argument,
# put it in its CAS key, and then never passed it to a single compile — so two
# callers passing different flags got two cache entries holding byte-identical
# artifacts, and a caller who believed the flag had been honoured was wrong.
# One table, one flag computation, used by both.
#
# (source, language, arch predicate or None for "every architecture").
# The aarch64 context-switch file is hand-written assembly and has no x86-64
# counterpart, which is why the pair below is selected on the TARGET and not
# on the host: selecting on the host is how an x86-64 build ends up assembling
# aarch64 instructions and getting an assembler error naming a register that
# does not exist on that architecture.
_C_UNIT = 'c'
_CPP_UNIT = 'fire_async_runtime.cpp'
_ASM_UNIT = 'asm'

_RUNTIME_UNITS = (
    ('fire_runtime.c', _C_UNIT, None),
    (_CPP_UNIT, 'c++', None),
    ('fire_coro.c', _C_UNIT, None),
    ('fire_coro_gen.c', _C_UNIT, None),
    ('fire_async_sched.c', _C_UNIT, None),
    ('fire_coro_ctx_aarch64.S', _ASM_UNIT, 'arm64'),
    ('fire_coro_ctx_generic.c', _C_UNIT, 'x86_64'),
)

# Per-language base flags. `fire_async_runtime.cpp` is a real C++20 translation
# unit (coroutines, exceptions) and is the reason the final link goes through a
# C++ driver at all — see `_dylink`'s `link_driver`.
_UNIT_FLAGS = {
    _C_UNIT: ('-fPIC',),
    'c++': ('-std=c++20', '-fPIC'),
    _ASM_UNIT: (),
}


# The runtime is hand-written C that every compiled program calls in its hot
# loops (list/dict/set operations, the container registries, the cleanup
# stack), so unlike the generated stdlib modules — which stay at gcc's
# implicit -O0 for compile time and cache-friendliness — it is always built
# optimized. Measured: at -O0 the runtime's own `_pr_home` was not even
# inlined, and a create/push/drop loop spent most of its time in it. The
# `mojoc` build has always compiled it at -O2, so this is the level the
# runtime is already exercised at; an explicit `opt_flag`/`extra_flags` still
# wins (a debugging `-O0` build stays -O0).
_RUNTIME_DEFAULT_OPT = '-O2'


def runtime_units(arch: str, opt_flag: str = None, extra_flags: tuple = ()) -> list:
    """`(source, language, base_flags)` for every unit of `arch`'s runtime.

    The flags are the per-language base, the runtime's own `-I`, the target
    flags, the optimization level (`opt_flag`, else `_RUNTIME_DEFAULT_OPT` for
    the C/C++ units), and the caller's `extra_flags` — in that order, so a
    caller's flag is the last word and an optimization level applies to every
    unit rather than to whichever one a caller remembered.
    """
    arch = normalize_arch(arch)
    out = []
    for src, lang, only in _RUNTIME_UNITS:
        if only is not None and normalize_arch(only) != arch:
            continue
        flags = tuple(_UNIT_FLAGS[lang]) + (f'-I{RUNTIME}',) + arch_flags(arch)
        if opt_flag:
            flags += (opt_flag,)
        elif lang != _ASM_UNIT:
            flags += (_RUNTIME_DEFAULT_OPT,)
        flags += tuple(extra_flags)
        out.append((os.path.join(RUNTIME, src), lang, flags))
    if not out:
        raise ArchError(f"no runtime units are defined for {arch}")
    return out


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


def _local_dep_fingerprint(path: str, dep_src_by_key: dict) -> str:
    """Content fingerprint of every LOCAL module reachable from `path` by
    following `from X import ...` (transitively), for folding into this
    module's CAS key.

    `_imported_sigs` above only captures a *direct* dependency's fn/def
    *signatures* — it never sees a `comptime` constant's value (which
    gimple_codegen constant-folds directly into every importer's generated C),
    and it never chases a re-export hop's own transitive imports. So a content
    change to a module imported only *transitively* (import graph
    game_engine -> recipes -> block_registry) left every importer's cached
    object stale: `mojo dylib` reported a fresh build yet the dylib kept the
    previous `block_registry.NUM_CPP_BLOCKS` (BUG-2026-032, box.3d/game).

    `dep_src_by_key` maps every candidate import spelling (full module name,
    its last dotted segment, and the bare file basename) of the modules in
    this build to `(path, source)`. Only modules IN this build participate —
    stdlib imports are covered by `cas.stdlib_fingerprint()` elsewhere and are
    deliberately not walked here."""
    import hashlib
    seen: dict = {}                 # dep module key -> sha256 of its source
    visited_paths = {path}
    stack = [path]
    while stack:
        p = stack.pop()
        try:
            s = open(p).read()
        except Exception:
            continue
        try:
            stmts = Parser(py_tokenize(s)).parse_module()
        except Exception:
            continue
        for st in stmts:
            if not isinstance(st, FromImportStmt):
                continue
            mod = (st.module or '').lstrip('.')
            # Stdlib imports are covered wholesale by cas.stdlib_fingerprint()
            # (folded into every stdlib module's key elsewhere); walking them
            # here would give every stdlib module a non-empty dep fingerprint
            # and force a full cold rebuild of the stdlib cache on no real
            # change. Mirrors driver._expand_dylib_modules' own `std` skip.
            if not mod or mod.startswith('std'):
                continue
            entry = (dep_src_by_key.get(mod)
                     or dep_src_by_key.get(mod.split('.')[-1]))
            if entry is None:
                continue
            dep_path, dep_src = entry
            if dep_path in visited_paths:
                continue
            visited_paths.add(dep_path)
            seen[dep_path] = hashlib.sha256(dep_src.encode('utf-8', 'replace')).hexdigest()
            stack.append(dep_path)
    if not seen:
        return ''
    return '\n'.join(f"{k}={seen[k]}" for k in sorted(seen))


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


def _compile_one_object(src: str, path: str, name: str, workdir: str, gcc: str,
                         objflags: tuple = _OBJ_FLAGS) -> bytes:
    """Cold-path builder: Mojo → C → .o; returns the object's bytes."""
    cfile = os.path.join(workdir, name + '.c')
    ofile = os.path.join(workdir, name + '.o')
    with open(cfile, 'w') as f:
        f.write(compile_module_to_c(src, path, name))
    subprocess.run([gcc, *objflags, '-c', '-o', ofile, cfile], check=True)
    with open(ofile, 'rb') as f:
        return f.read()


def _compile_module_job(path: str, workdir: str, use_cache: bool, objflags: tuple = _OBJ_FLAGS,
                         known_structs: frozenset = frozenset(), dep_fingerprint: str = ''):
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
    aggregate would otherwise silently under-report.

    `known_structs` (BUG-2026-029 cross-file follow-up): the bare names of
    every concrete struct defined ANYWHERE across the whole `modules` list
    this job is one of (computed once by `build()` before dispatching any
    job — see its own pre-pass), passed straight through to
    `reflect.collect_exports_src` so a module-level global whose struct type
    is defined in a SIBLING file (not this module's own file) still gets a
    SYM_GLOBAL reflection export instead of being silently un-advertised.
    Must be picklable for ProcessPoolExecutor — a frozenset of str is."""
    gcc = find_gcc()
    name = _module_name_for(path)
    src = open(path).read()
    try:
        # module_prefix=name: the SAME identity GimpleGen(module_name=name)
        # below uses when actually compiling this module, so the reflection
        # table's advertised method symbols match what codegen emits.
        exports = reflect.collect_exports_src(src, module_prefix=name,
                                               known_structs=known_structs)
    except Exception:
        exports = []
    hit = None
    try:
        if use_cache:
            key = cas.module_key(src, _imported_sigs(src), gcc, objflags,
                                 dep_fingerprint=dep_fingerprint)
            ofile, hit = cas.get_or_build(
                key, '.o', lambda: _compile_one_object(src, path, name, workdir, gcc, objflags))
        else:
            ofile = os.path.join(workdir, name + '.o')
            with open(ofile, 'wb') as f:
                f.write(_compile_one_object(src, path, name, workdir, gcc, objflags))
    except Exception as e:
        return path, name, None, exports, str(e), hit
    return path, name, ofile, exports, None, hit


@contextlib.contextmanager
def _output_lock(out: str):
    """Exclusive, cross-process, released on exit: an flock on a side file
    next to `out`, held across `build`'s whole publish.

    A side file and not the library itself, because `build` REPLACES the
    `.dylib` and a lock on the library would let a second process in the
    instant the first created it. `flock` is advisory and per-open-file-
    description, so the kernel releases it when the process dies and a
    killed build cannot wedge the tree (the same shape, and the same
    reasoning, as `formal/imports.py::_dylib_lock`).

    Why it is needed at all: `out` is a FIXED path
    (`build_stdlib_dylib.build_stdlib`'s default is
    `build/libmojostdlib.<arch>.dylib`), and every `fire.py build` reaches it
    through `driver.compile_program`'s `bsd.build_stdlib()`. So N gate jobs
    running in parallel each asked for the same library, and the losers of
    the CAS race did not queue — they raced the WINNER onto the same output
    file. Measured, two `linkmode`/`nonlocal` jobs in one `-j4` run, twice on
    this tree:

        ld: open() failed, errno=17 (File exists) for
            '<checkout>/build/libmojostdlib.arm64.dylib'

    which surfaced as a failing `test_link_mode` case
    (`test_bare_submodule_import_value_read raised: Command '[...,
    -dynamiclib, ..., -o, <checkout>/build/libmojostdlib.arm64.dylib, ...]'
    returned non-zero exit status 1`) and as a failing `test_nonlocal` case
    wanting `'7\\n'` — i.e. the dylib was never wrong, it was never finished.
    A second, quieter version of the same race needs no error at all: the
    cache-hit path `shutil.copy`s onto `out` in place, so a client linking
    against `out` at that moment can read a half-written Mach-O.

    The lock makes latecomers QUEUE rather than collide, and `build` re-checks
    the CAS inside it, so the queue collapses to one build and N-1 no-ops —
    the mechanism CLAUDE.md's "Shared expensive dependencies" section
    describes, and the same one `formal/lean.py`'s `ensure_library` uses.

    Local to this module, not shared: this file is in `mojoc`'s own compile
    closure, and `_is_selfhost_source_dir`'s docstring in
    `mojo/backend_gimple/module_gen.py` records a measured self-host failure
    for exactly the cross-module function reference that sharing one would
    have meant."""
    fd = os.open(out + '.lock', os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _publish_bytes(src_path: str, out: str) -> None:
    """Put `src_path`'s bytes at `out` with a single atomic rename.

    `os.replace` within a directory is atomic, so a concurrent reader of
    `out` — another job linking a program against the stdlib dylib — sees
    either the whole previous library or the whole new one, never a partial
    file. `shutil.copy` onto `out` in place gives it a window in which
    `out` is a truncated Mach-O."""
    staged = out + '.incoming.' + str(os.getpid())
    shutil.copy(src_path, staged)
    os.replace(staged, out)


def build(modules: list, out: str, use_cache: bool = True, link_runtime: bool = False,
          extra_exports: list = None, jobs: int = 1, opt_flag: str = None,
          track_local_deps: bool = True, arch: str = None) -> str:
    """`opt_flag` (e.g. '-O2'): folded into every module's AND the runtime's
    own object-compile flags, and into their CAS keys (so an -O2 build never
    serves a stale -O0-compiled object, or vice versa) — `_OBJ_FLAGS`/plain
    `toolchain_fingerprint(gcc, ())` on their own carry NO optimization flag
    (gcc's implicit -O0), appropriate for the STDLIB dylib (compiled once,
    used everywhere, optimized for compile time / cache-friendliness) but not
    for a `mojo dylib`-built artifact meant to be linked into a real program
    and actually run at speed.

    `arch` is the architecture the dylib is FOR (default: the host's) and
    reaches every module compile, every runtime object, the runtime dylib this
    links against, the final link, the CAS keys and the artifact's own
    verification — see the architecture section at the top of this file for why
    each of those is separately necessary and why the verification is not
    optional."""
    gcc = find_gcc()
    gxx = find_gxx()
    arch = normalize_arch(arch)
    objflags = _OBJ_FLAGS + arch_flags(arch) + ((opt_flag,) if opt_flag else ())
    os.makedirs(os.path.dirname(out), exist_ok=True)
    workdir = tempfile.mkdtemp(prefix='mojostdlib_')
    objs = []

    # BUG-2026-029 cross-file follow-up: a cheap, source-text-only pre-pass
    # over EVERY module in this build (before any per-module job runs) to
    # index which bare names are concrete structs ANYWHERE in the compile
    # unit — not just in the one file that happens to reference them. This
    # is what lets reflect.collect_exports_src (called per-module, in
    # parallel, with no visibility into sibling files on its own) recognize
    # a module-level global whose struct type is defined in a DIFFERENT
    # file (e.g. box.3d/game's `g_world: World` in game_ffi.mojo, with
    # `struct World` defined in engine_world.mojo) as struct-typed, and so
    # advertise a SYM_GLOBAL reflection export for it — see
    # reflect.collect_exports's `known_structs` param docstring for exactly
    # why this is safe (the accessor is always consumed as generic `void *`
    # regardless of which file the struct's real layout lives in). A parse
    # failure on one file here just contributes no names from that file —
    # the exact same file will fail again (and get reported) in its own
    # real `_compile_module_job` below, so silently skipping it here isn't
    # hiding anything.
    known_structs = set()
    for _path in modules:
        try:
            known_structs |= reflect.collect_local_struct_names_src(open(_path).read())
        except Exception:
            pass
    known_structs = frozenset(known_structs)

    # Per-module transitive local-dependency fingerprint (BUG-2026-032): index
    # every module in this build under each spelling it might be imported as,
    # then fold the content hash of each module's reachable local-import
    # closure into its CAS key. Cheap text pre-pass; a parse failure on one
    # file just contributes nothing (it fails again, reported, in its own job).
    _dep_src_by_key: dict = {}
    for _path in (modules if track_local_deps else ()):
        try:
            _src = open(_path).read()
        except Exception:
            continue
        _nm = _module_name_for(_path)
        _base = os.path.splitext(os.path.basename(_path))[0]
        for _k in {_nm, _nm.split('.')[-1], _base}:
            _dep_src_by_key.setdefault(_k, (_path, _src))
    dep_fps = {}
    for _path in modules:
        if not _dep_src_by_key:
            dep_fps[_path] = ''
            continue
        try:
            dep_fps[_path] = _local_dep_fingerprint(_path, _dep_src_by_key)
        except Exception:
            dep_fps[_path] = ''

    # Compile every module's source → object first (fully independent per
    # module, so parallelizes cleanly across processes — same scheme as
    # compile_stdlib.py's ProcessPoolExecutor use). Order is preserved
    # (pool.map, not as_completed) because the symbol-collision dedup below
    # is order-sensitive ("first module wins") and must stay sequential.
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            results = list(pool.map(
                _compile_module_job, modules,
                [workdir] * len(modules), [use_cache] * len(modules),
                [objflags] * len(modules), [known_structs] * len(modules),
                [dep_fps[p] for p in modules]))
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
        results = [_compile_module_job(path, workdir, use_cache, objflags, known_structs,
                                       dep_fps[path])
                   for path in modules]

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
    # - For production (link_runtime=False): compile each unit of the runtime
    #   and fold it into the dylib (no separate runtime dylib needed)
    # - For testing (link_runtime=True): build the standalone runtime dylib and
    #   link against it
    #
    # The unit list is `_RUNTIME_UNITS`, the SAME one `runtime_dylib()` uses.
    # It used to be written out twice, and the two copies had already drifted
    # in the way that matters: the copy here picked the context-switch source
    # from `platform.machine()` (the HOST) while the key for the object it was
    # about to compile folded in the same host — so a build FOR another
    # architecture compiled aarch64 assembly under a name that claimed
    # otherwise. One table, selected on the target, is the fix; the reasoning
    # for folding each unit in unconditionally is the hand-verified crashes
    # recorded below and in runtime_dylib()'s own docstring.
    rt_units = runtime_units(arch, opt_flag)
    cc, cxx = toolchain_for(arch, gcc, gxx)

    if link_runtime:
        # For test modules: link against standalone runtime dylib (which
        # itself now also folds in mojo_async_runtime.o — see
        # runtime_dylib()'s own docstring). Per-arch, for the same reason as
        # everything else here: a test module built for one architecture and a
        # runtime dylib built for the other is a link that succeeds and a
        # dlopen that does not.
        rt_dylib = runtime_dylib(gcc, arch=arch)
        rt_path = rt_dylib
    else:
        # For production: include every runtime object directly. The keys are
        # per unit (source + flags + toolchain + arch), and the arch is
        # spelled out in each because `toolchain_fingerprint` folds the FLAGS
        # — and a driver that ignores its target flag produces identical bytes
        # under a different name, which is the whole failure this per-arch work
        # is about.
        for _src, _lang, _uflags in rt_units:
            _stem = os.path.splitext(os.path.basename(_src))[0]
            _driver = cxx if _lang == 'c++' else cc
            _key = 'rtobj/' + cas._hash(
                'mojo-rtobj-v2', cas.ABI_VERSION, cas.compiler_fingerprint(),
                cas.toolchain_fingerprint(_driver, _uflags), arch, _stem,
                open(_src).read())

            def _build_rt_obj(_src=_src, _uflags=_uflags, _driver=_driver,
                              _stem=_stem):
                o = os.path.join(workdir, _stem + '.o')
                subprocess.run([_driver, *_uflags, '-c', '-o', o, _src], check=True)
                return open(o, 'rb').read()
            _o, _ = cas.get_or_build(_key, '.o', _build_rt_obj)
            objs.append(_o)
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
    # fire_runtime.h (e.g. MojoList__write_to) was never actually defined in
    # fire_runtime.c. Either way the reflection table would forward-declare
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
    _misresolved, _undefined = [], []
    for e in all_exports:
        if e['kind'] == reflect.SYM_TYPE:
            _kept.append(e)
            continue
        sym = reflect.export_csym(e)
        if ('_' + sym) in all_defs:
            _kept.append(e)
        elif ('_' + e['name']) in all_defs:
            # The entry names a symbol the dylib really defines, but the
            # export-csym rule resolved it to a different one — see
            # runtime_export_entries' report on why that is measured at 433 of
            # fire_runtime.h's 459 entry points today, and why the fix is in
            # reflect.export_csym rather than here. A separate class from the
            # genuinely-orphaned entry below because nothing is missing here:
            # the definition is present and the table just is not naming it.
            _misresolved.append(f"{e['name']} -> {sym}")
        else:
            _undefined.append(e['name'])
    all_exports = _kept
    for line in format_export_report(len(_kept) + len(_misresolved) + len(_undefined),
                                     _misresolved, _undefined):
        print(f"  {line}", file=sys.stderr)

    # Reflection table source — deterministic given all_exports, so it can
    # participate in the dylib link key before writing the file.
    reflect_src = reflect.emit_table_c(all_exports)

    # Compute dylib link key and check CAS.  The key folds in every .o on the
    # link line (module objects + runtime .o or runtime dylib digest), the
    # reflect table source, the toolchain, the target architecture, and the
    # link mode — so changing any object or configuration invalidates the
    # cached dylib. The arch is a separate key input rather than only arriving
    # inside the per-object flags, because the LINK step carries its own
    # `-arch` and a link that silently ignored it would otherwise be
    # indistinguishable from a correct one.
    extra_link_digest = cas.file_digest(rt_dylib) if link_runtime else ''
    link_key = cas.dylib_link_key(
        objs, reflect_src, cc, undefined=not link_runtime,
        extra_digest=extra_link_digest, arch=arch)

    # One exclusive section from here to the return, covering the currency
    # check, the link and the publish — see `_output_lock` for the measured
    # failure this replaces. The CAS is deliberately consulted INSIDE the
    # lock and not before it: a check-then-act on a shared filesystem is the
    # stampede, and `out` is the most-shared path in the tree (every parallel
    # `fire.py build` in the gate wants this one library). Everything above
    # the lock — the per-module compiles, all of them individually
    # content-addressed — still runs in parallel across callers, so the
    # serialised section is only the table compile and the link.
    with _output_lock(out):
        if use_cache:
            # Re-checked under the lock: a caller that queued behind another
            # one's fresh link finds the artifact published and returns,
            # which is what turns N racing builds into one build.
            cached_dylib = cas.lookup(link_key, '.dylib')
            if cached_dylib:
                cas.stats['hits'] += 1
                _publish_bytes(cached_dylib, out)
                _arch_or_die(out, arch, 'cached dylib')
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
        subprocess.run([cc, '-fno-builtin', '-fPIC', f'-I{HERE}', *arch_flags(arch),
                        '-c', '-o', reflect_o, reflect_c], check=True)
        objs.append(reflect_o)

        # Link into the WORK DIRECTORY and rename into place, because `out` is
        # a fixed path every other job links against: a dylib linked straight
        # to `out` is a partially-written Mach-O at every path a concurrent
        # reader can reach it, which is the silent half of the race
        # `_output_lock` names. `_dylink` is given the final install name
        # explicitly for the reason `runtime_dylib`'s own staged link gives
        # it — the install name is baked into the load command of everything
        # that links this library, so deriving it from a staging path and
        # renaming afterwards produces an artifact that disagrees with its own
        # name.
        staged = os.path.join(workdir, os.path.basename(out))
        # Linking depends on whether runtime is included or linked separately.
        # link_driver=cxx: the production dylib now always folds in mojo_
        # async_runtime.o (a real C++20 translation unit, not plain -fgimple C)
        # — g++ as the final link driver pulls in libstdc++ correctly, mirroring
        # fire.py's own link_executable(cxx=True) convention exactly.
        if link_runtime:
            # For test modules: link against runtime dylib, all symbols must resolve
            link = _dylink(cc, staged, objs, undefined=False, extra_libs=[rt_path],
                           rpath=os.path.dirname(rt_path), link_driver=cxx,
                           install_name='@rpath/' + os.path.basename(out),
                           arch=arch)
        else:
            # For production: cross-module references resolve at load time
            link = _dylink(cc, staged, objs, undefined=True, link_driver=cxx,
                           install_name='@rpath/' + os.path.basename(out),
                           arch=arch)
        subprocess.run(link, check=True)
        _arch_or_die(staged, arch, 'linked dylib')
        os.replace(staged, out)
        # Publish the linked dylib to the shared CAS so future builds skip the
        # link (even on use_cache=False runs: the fresh link is the correct
        # artifact). Inside the lock, so the latecomer above finds it.
        with open(out, 'rb') as f:
            cas.publish(link_key, '.dylib', f.read())
        return out


def _dylink(gcc, out, objs, undefined=False, rpath=None, extra_libs=None,
            link_driver=None, install_name=None, arch=None):
    """Platform dylib link command. undefined=True allows unresolved symbols
    (resolved at load from other dylibs, via dyld dynamic lookup).

    link_driver: override the link-time driver binary (e.g. find_gxx()'s g++)
    used in place of `gcc` for just this final link invocation. Every
    individual module's .c -> .o compile step is unaffected — this only
    matters when `objs` includes at least one C++-derived object (the
    generator-coroutine codegen path, not yet wired into any real build —
    see build_config.find_gxx()'s docstring). Defaults to `gcc`, so ordinary
    all-C builds are unchanged.

    install_name: override the `@rpath/<name>` install name, which otherwise
    comes from `out`'s basename. It is a parameter rather than a convention
    because the runtime dylib links into a work directory and is then MOVED
    into the CAS under its final name (see runtime_dylib): a dylib's install
    name is baked into the load command of everything that links it, so
    deriving it from a staging path and renaming afterwards produces an
    artifact that disagrees with its own name. Passing the final name makes
    the two the same statement by construction.

    arch: the target architecture for the LINK step. Distinct from every
    object's own compile flags, and independently necessary — a driver that
    cannot target an architecture ignores the flag at link time exactly as it
    ignores it at compile time, and produces a dylib of the wrong
    architecture out of correctly-built objects. Defaults to the host, so an
    ordinary build is unchanged."""
    driver = link_driver or gcc
    if platform.system() == 'Darwin':
        cmd = [driver, '-dynamiclib',
               '-install_name', install_name or ('@rpath/' + os.path.basename(out)),
               '-o', out]
        if arch:
            cmd += ['-arch', normalize_arch(arch)]
        if rpath:
            cmd += ['-Wl,-rpath,' + rpath]
        if undefined:
            cmd += ['-undefined', 'dynamic_lookup']
    else:
        cmd = [driver, '-shared', '-fPIC', '-o', out]
        if rpath:
            cmd += ['-Wl,-rpath,' + rpath]
        if undefined:
            cmd += ['-Wl,--allow-shlib-undefined']
    # Objects first, then extra libs (dependencies must come after the objects that use them)
    result = cmd + objs
    if extra_libs:
        result.extend(extra_libs)
    return result



def runtime_dylib(gcc: str = None, flags: tuple = (), arch: str = None) -> str:
    """Build (or find in the CAS) the runtime dylib that exports mojo_* symbols.

    The stdlib dylib now includes the runtime, but test modules and external
    clients need a separate runtime dylib to link against and resolve symbols.
    Built with all symbols resolved (undefined=False).

    Also folds in runtime/mojo_async_runtime.o (mojo_coro_resume_generic/
    mojo_coro_destroy_generic/AsyncRT_DeviceContext_enqueueHostFunction(Range))
    for the same reason build()'s production dylib path does — a compiled
    stdlib module (test or production) can reference these via
    `_coro_resume_fn`/`_coro_destroy_fn` used as bare values, or define a
    compiled async function/closure, independent of link_runtime mode. Since
    §5.5 (doc/COROUTINE.html) made the A3 stack-switch backend the default,
    also folds in the stack-switch runtime (fire_coro.c/fire_coro_gen.c/
    fire_async_sched.c + the arch context-switch file) for the identical
    reason — see build()'s own matching comment for the hand-verified crash
    this fixes. The unit list is `_RUNTIME_UNITS`, shared with build().

    `arch` names the architecture the dylib is FOR, defaulting to the host's.
    It is in the CAS key, in the file name, in every compile and link flag, and
    — the part that is not a promise — it is checked against the Mach-O that
    actually came out (`_arch_or_die`), because the driver this tree is
    configured with ACCEPTS `-arch x86_64`, warns that it is ignoring it, and
    emits an arm64 object. Without that check the foreign-architecture build
    this function exists to provide would be a host-architecture library with a
    foreign-architecture name, and the failure would be dyld's, in a different
    program, later.

    `flags` is applied to every unit's compile, which it previously was not:
    it went into the cache key and from there into nowhere, so two callers
    passing different flags got two entries holding identical bytes and neither
    got what it asked for.

    The result carries a `__mojo_reflect` table, derived from the runtime
    headers by `reflect.collect_runtime_exports_h` and then filtered against
    what `nm` says the linked objects DEFINE. Both halves matter and they fail
    in opposite directions: the header alone advertises prototypes nothing
    implements (a link failure for the first client that calls one, and a
    dlopen failure for every client, since the table forward-declares and takes
    the address of all of them), and the object set alone advertises C++
    template instantiations and libc re-exports that are not an ABI. The
    intersection is the set that is both promised and real, and the residue is
    REPORTED rather than dropped silently — see `runtime_export_entries`.
    """
    arch = normalize_arch(arch)
    cc, cxx = toolchain_for(arch, gcc or find_gcc(), find_gxx())
    units = runtime_units(arch, None, tuple(flags))
    digest = cas._hash(
        'mojo-rtdylib-v4', cas.ABI_VERSION, cas.compiler_fingerprint(),
        cas.toolchain_fingerprint(cc, arch_flags(arch) + tuple(flags)),
        arch, *[os.path.basename(s) for s, _l, _f in units],
        *[open(s).read() for s, _l, _f in units])
    # The arch is in the NAME as well as in the key, and the key alone is not
    # enough: `formal/imports.py`'s own note on `build_module_dylib` records
    # that a content-addressed name still collides when a caller passes a
    # directory of its own choosing, and the failure that causes is one
    # architecture's library replacing the other's on disk. Here the basename
    # is also the dylib's install name, so it has to say what it is either way.
    # `digest` stays content-addressed, so two builds that agree write the same
    # path and `os.replace` onto it below is idempotent.
    name = f'libmojostdlib.{arch}.{digest}.dylib'
    out = cas.path_for(f'rtdylib/libmojostdlib.{arch}.{digest}', '.dylib')
    if os.path.exists(out):
        # A cache hit still gets verified. The key is a claim about the
        # artifact; this is the artifact. A stale entry from before the arch
        # was in the key at all, or from a driver that lied, must not be
        # served just because its name is right.
        _arch_or_die(out, arch, 'cached runtime dylib')
        return out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    wd = tempfile.mkdtemp(prefix='mojo_rt_')
    objs = []
    for src, lang, unit_flags in units:
        stem = os.path.splitext(os.path.basename(src))[0]
        o = os.path.join(wd, stem + '.o')
        driver = cxx if lang == 'c++' else cc
        subprocess.run([driver, *unit_flags, '-c', '-o', o, src], check=True)
        _arch_or_die(o, arch, f'object for {os.path.basename(src)}')
        objs.append(o)
    # The reflection table over the runtime's own public surface, filtered to
    # the symbols this dylib really defines (see runtime_export_entries).
    # The report is PRINTED inside runtime_export_entries, not here: iterating
    # a local that a tuple-unpack bound is a shape the self-hosted backend
    # mis-types, and this module is in mojoc's own compile closure. See that
    # function's `for line in report:` for the measurement.
    entries, report = runtime_export_entries(cc, objs)
    reflect_src = reflect.emit_table_c(entries)
    rc = os.path.join(wd, '_mojo_reflect.c')
    ro = os.path.join(wd, '_mojo_reflect.o')
    with open(rc, 'w') as f:
        f.write(reflect_src)
    # -fno-builtin for the same reason build()'s own table compile needs it:
    # the table redeclares every advertised symbol unprototyped to take its
    # address, and some of those names are C builtins.
    subprocess.run([cc, '-fno-builtin', '-fPIC', f'-I{HERE}', *arch_flags(arch),
                    '-c', '-o', ro, rc], check=True)
    objs.append(ro)
    # Linked into the work directory and moved into place, because a dylib's
    # install name is derived from its output path: linking straight to `out`
    # and renaming would leave the artifact disagreeing with the load command
    # baked into everything that links it. `_dylink` is given the final
    # install name explicitly, so the two cannot drift, and the name is
    # content-addressed, so `os.replace` onto it is atomic and idempotent.
    # `arch` on the LINK is not redundant with it on every object, and this is
    # not a hypothetical: with it omitted, `ld` took the host architecture,
    # printed "warning: ignoring file ...: found architecture 'x86_64',
    # required architecture 'arm64'" for EVERY object, exited 0, and wrote an
    # empty arm64 dylib. A link driver that cannot target an architecture
    # ignores its flag exactly as quietly as a compiler does.
    staged = os.path.join(wd, name)
    subprocess.run(_dylink(cc, staged, objs, undefined=False, link_driver=cxx,
                           install_name='@rpath/' + name, arch=arch), check=True)
    _arch_or_die(staged, arch, 'linked runtime dylib')
    os.replace(staged, out)
    return out


# The headers that declare the runtime's public C surface, in the order they
# are scanned. `fire_runtime.h` is the whole of it for an ordinary client; the
# coroutine and async headers are here because their objects are in this dylib
# and a bind audit that does not know about `mojo_box_*`/`mojo_future_*` reports
# them as symbols nothing provides, which is the same false claim in the other
# direction.
_RUNTIME_HEADERS = ('fire_runtime.h', 'fire_async_runtime.h', 'fire_coro_ctx.h')


def runtime_export_entries(gcc: str, objs: list) -> tuple:
    """(entries, report) — the runtime's real export surface: the headers'
    entry points intersected with what the objects DEFINE.

    Both halves are load-bearing and they fail in opposite directions, which
    is why the answer is an intersection and not either side alone:

      * header alone advertises prototypes nothing implements. The table
        forward-declares and takes the address of every entry, so one orphan
        is a dlopen failure for EVERY client of the dylib, not only for a
        client that calls it (build()'s own comment records the real crash).
      * object set alone advertises C++ template instantiations, coroutine
        internals and libc re-exports, which are not an ABI and are not what
        `collect_runtime_exports_h` describes.

    `report` is a list of human-readable lines, and it distinguishes the two
    ways an entry can be dropped, because they are not equally interesting:

      * MISRESOLVED — the header names it `X`, `nm` says the objects define
        `_X`, and `reflect.export_csym` resolved the entry to some OTHER
        symbol. Nothing is missing; the shared export-csym rule is computing
        a Mojo overload-mangled name for a C prototype. This is a real,
        currently-live defect measured on this tree: with
        `fire_runtime.h`'s 459 entry points, only 26 survive
        `build_stdlib()`'s `nm` cross-check, and 433 are dropped for exactly
        this reason. So the stdlib dylib has never advertised 433 runtime
        entry points it defines — including all of `mojo_str_*` and every
        function whose parameters are not word-shaped. The fix belongs in
        `reflect.export_csym` (agent [3]'s file; see the INTERFACE REQUEST),
        and nothing here has to change when it lands: an entry that resolves
        correctly passes this same check and is advertised.
      * UNDEFINED — the header declares it and no object in the dylib defines
        it. Either a dead declaration (fire_runtime.h has six) or a prototype
        satisfied by whoever links against the dylib (`py_tokenize` is
        defined by the self-hosted compiler image, not by the runtime).

    Reporting rather than silently dropping is the point: a number sends
    nobody anywhere, and a named symbol sends the next reader to the one line
    that is wrong.
    """
    exports = []
    seen = set()
    for hdr in _RUNTIME_HEADERS:
        for e in reflect.collect_runtime_exports_h(os.path.join(RUNTIME, hdr)):
            if e['name'] in seen:
                continue
            seen.add(e['name'])
            exports.append(e)
    defined = set()
    for o in objs:
        defined |= _defined_symbols(gcc, o)
    kept = []
    misresolved, undefined = [], []
    for e in exports:
        sym = reflect.export_csym(e)
        if ('_' + sym) in defined:
            kept.append(e)
        elif ('_' + e['name']) in defined:
            misresolved.append(f"{e['name']} -> {sym}")
        else:
            undefined.append(e['name'])
    report = format_export_report(len(exports), misresolved, undefined)
    # Printed HERE, and that placement is load-bearing for the self-hosted
    # build rather than a matter of taste. This module is compiled into `mojoc`,
    # and the self-hosted backend mis-types `for x in <local>` when the local
    # was bound by TUPLE-UNPACKING a call's return: it has no element type for
    # it, so the loop's bounds are computed as `mojo_strlen(local)` and its
    # element access as `_mojo_at_char(local, i)` — string indexing applied to
    # a boxed LIST. That is not a wrong value, it is a hard gcc error, and it
    # took `fire.py build fire.py` out:
    #
    #   build_stdlib_dylib.py: error: passing argument 1 of 'mojo_strlen'
    #       makes pointer from integer without a cast [-Wint-conversion]
    #   build_stdlib_dylib.py: error: passing argument 1 of '_mojo_at_char'
    #       makes pointer from integer without a cast [-Wint-conversion]
    #
    # (`-Wint-conversion` is an ERROR by default in GCC 14+, not a warning, so
    # there is no flag that makes this survivable.)
    #
    # Iterating a list this function builds by `append` lowers correctly --
    # `mojo_list_get_str`, with `line` typed `char *` -- so the loop lives
    # where the list is built. The real fix is in the codegen, not here; see
    # bugs/FORMAL_known_limits.md.
    #
    # A caller that wants the lines as a VALUE still gets them: the tuple is
    # returned unchanged, and test_runtime_dylib.py reads report[0].
    for line in report:
        print(f"  runtime dylib: {line}", file=sys.stderr)
    return kept, report


def format_export_report(total: int, misresolved: list, undefined: list) -> list:
    """Human-readable lines for `runtime_export_entries`' two drop classes.

    Capped per class, because a report nobody can read is the same as no
    report: the counts and the first names are always there, and the tail is
    reachable by asking. The misresolved class is listed first and in full up
    to the cap because it is the actionable one — every name in it is a real
    definition the dylib is not advertising."""
    lines = [f"export table: {total - len(misresolved) - len(undefined)} of {total} "
             f"runtime entry points advertised "
             f"({len(misresolved)} misresolved, {len(undefined)} undefined)"]
    for label, names in (("defined but not advertised (export_csym resolved them to "
                          "a different symbol)", misresolved),
                         ("declared with no definition in this dylib", undefined)):
        if not names:
            continue
        shown = names[:_REPORT_CAP]
        lines.append(f"  {label}: {', '.join(shown)}"
                     + (f", +{len(names) - len(shown)} more" if len(names) > len(shown)
                        else ""))
    return lines


_REPORT_CAP = 24


def build_stdlib(out: str = DEFAULT_OUT, use_cache: bool = True, jobs: int = 1,
                 arch: str = None) -> str:
    """Build the monolithic stdlib dylib from all auto-discovered library modules.

    `arch` names the architecture the dylib is for; the default output NAME
    gains it as well, because `build/libmojostdlib.dylib` is a fixed path and
    two architectures writing to it would make the second build's success
    depend on which ran last. The name is only defaulted when the caller did
    not ask for a specific `out`."""
    arch = normalize_arch(arch)
    if out == DEFAULT_OUT:
        out = os.path.join(HERE, 'build', f'libmojostdlib.{arch}.dylib')
    rt_exports = []
    seen = set()
    for hdr in _RUNTIME_HEADERS:
        for e in reflect.collect_runtime_exports_h(os.path.join(RUNTIME, hdr)):
            if e['name'] not in seen:
                seen.add(e['name'])
                rt_exports.append(e)
    # track_local_deps=False: every module here IS a stdlib module, and the
    # whole stdlib closure is already folded into each one's key via
    # cas.stdlib_fingerprint(). Per-module local-dep tracking would only
    # re-hash that same closure under a new key and force a needless full
    # cold rebuild. It exists for `mojo dylib` on a PROJECT's own file set
    # (BUG-2026-032), reached via driver.compile_dylib -> build(...).
    return build(stdlib_modules(), out, use_cache=use_cache, extra_exports=rt_exports,
                 jobs=jobs, track_local_deps=False, arch=arch)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('modules', nargs='*', help='library .mojo modules to bundle (default: all stdlib)')
    ap.add_argument('-o', '--output', default=None,
                     help='output dylib path (default: build/libmojostdlib.<arch>.dylib)')
    ap.add_argument('--arch', default=None,
                     help='target architecture (default: this host\'s). The '
                          'architecture is part of the artifact\'s cache key, '
                          'its file name, every compile and link flag, and a '
                          'check on the Mach-O that actually came out — see '
                          'build_stdlib_dylib\'s module docstring.')
    ap.add_argument('--no-cache', action='store_true', help='bypass the CAS')
    ap.add_argument('-j', '--jobs', type=int, default=os.cpu_count(),
                     help='Parallel workers for the per-module Mojo→C→.o compile '
                          '(each module is independent, same scheme as '
                          'compile_stdlib.py). Default: os.cpu_count(). Use -j1 '
                          'for sequential (deterministic ordering, easier to read '
                          'failures as they happen).')
    args = ap.parse_args()
    arch = normalize_arch(args.arch)
    out = args.output or os.path.join(HERE, 'build', f'libmojostdlib.{arch}.dylib')
    modules = stdlib_modules()
    if args.modules:
        modules = list(args.modules)
    cas.reset_stats()
    built = build(modules, out, use_cache=not args.no_cache, jobs=args.jobs, arch=arch)
    msg = f"built {built} for {arch} from {len(modules)} module(s) + runtime"
    if not args.no_cache:
        msg += f"  [cas hits={cas.stats['hits']} misses={cas.stats['misses']}]"
    print(msg)


if __name__ == '__main__':
    main()
