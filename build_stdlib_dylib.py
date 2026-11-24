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
import re
import sys
import shutil
import platform
import argparse
import tempfile
import subprocess
import fcntl
import contextlib
from concurrent.futures import ProcessPoolExecutor

import cas
import reflect
import build_config
from build_config import find_gcc, find_gxx
from gimple_codegen import GimpleGen, FromImportStmt, _safe_name
from fire_compiler import py_tokenize, Parser, FunctionDef
from module_loader import (load_module, STDLIB_PATH, module_name_for_path,
                           ModuleLoader)

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


class _StagingDir:
    """A `tempfile.mkdtemp` directory removed on the way out, success or raise.

    `ignore_errors=True` is deliberate: the failure worth raising is the
    caller's, and a cleanup error must not mask it. The three sites that stage
    objects into a directory — `_driver_targets` (a driver probe), `build` (the
    stdlib objects and the linked dylib) and `runtime_dylib` (the runtime
    objects) — each used to spell this shape out, and `build`'s copy was
    missing, which leaked a `mojostdlib_*` directory. One reader of the shape
    is what keeps the next staging site from being the one that forgets.
    `formal/build.py::_publish_signed_image` is the same shape."""

    def __init__(self, prefix: str) -> None:
        self.d = tempfile.mkdtemp(prefix=prefix)

    def __enter__(self) -> str:
        return self.d

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        shutil.rmtree(self.d, ignore_errors=True)
        return False


def _driver_targets(driver: str, arch: str) -> tuple:
    """(works, why) — can `driver` emit an object FOR `arch`? Measured, not assumed."""
    key = (driver, arch)
    if key in _driver_probe:
        return _driver_probe[key]
    result = (False, 'not probed')
    try:
        # The probe directory holds a one-line C file and its object; the object
        # is read and then nothing needs the directory, so it is removed here or
        # it leaks one dir per probed (driver, arch) — the same class of leak
        # `runtime_dylib` had, in the same file.
        with _StagingDir('mojo_archprobe_') as wd:
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


class _DylibGeneratedCppError(RuntimeError):
    """`compile_module_to_c` produced a C++20 coroutine translation unit it has
    no way to hand to the dylib link. Named so a caller that DOES know how to
    link one (`compile_module_to_c_given_gen`, used by the executable path) can
    tell it apart from a genuine compile failure. The refusal is the fix for
    the silent drop of `generated_cpp` by `compile_module_to_c` (dylib module
    path); the root cause is that the C++20 definitions had no link line."""


def compile_module_to_c(src: str, path: str, module_name: str,
                        linkable: bool = True, no_mangle: tuple = ()) -> str:
    """Compile one library module to GIMPLE C with no main/entry points.

    `no_mangle`: free-function names whose C symbol is emitted EXACTLY as
    written instead of being module-qualified and overload-suffixed. The
    cross-module generic-instance pre-pass (`_generic_instance_requests`) uses
    it for the definitions it appends, because their names are already the
    exact symbols callers in OTHER modules reference — the caller's own
    `_func_csym` spelling, which this side must not re-derive. Empty for every
    ordinary module compile, so their symbols are unchanged.

    Deep-but-finite generic-instantiation chains (a module pulling in nested
    generics) can run many thousands of Python frames deep on a COLD cache before
    the CAS shortcuts them. Run codegen in a thread with a large stack and a high
    recursion limit so legitimate deep cascades complete instead of crashing the
    module into a source-fallback skip. (True non-convergence — instantiating with
    symbolic type args — is prevented at the call site, not papered over here.)

    Records the generic-struct elaborations that FAILED, in
    `_LAST_DEGRADED` — cleared on entry, so it describes this call and only
    this call. `compile_module_to_c_cached` reads it to decide whether the
    result may be published; see there for why a module built that way must
    not be."""
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
            gen = GimpleGen(emit_entry_points=False, module_name=module_name,
                            no_mangle=no_mangle)
            gen._current_filename = path
            # Stash the text the parser consumes, exactly as gimple_codegen's
            # pipeline does (`gen._source_text = mojo_src`). `module_gen`'s
            # text-only generic discovery reads `_source_text` and falls back
            # to re-reading `path` from disk; with neither, a module-local
            # generic such as `absorb[T]` is not seen as generic at all and is
            # lowered with T erased to int64_t (bug:CODEGEN_local_generic_
            # float_literal_arg_erases_to_int64).
            gen._source_text = src
            box['c'] = gen.gen_module(Parser(py_tokenize(src)).parse_module())
            box['degraded'] = list(gen._generic_struct_elaboration_failures)
            box['csyms'] = {k: sorted(v) for k, v in (getattr(gen, '_func_csym_record', None) or {}).items()}
            box['cpp'] = getattr(gen, 'generated_cpp', '')
            # A generator / `async def` the C++20 emitter accepted leaves its
            # DEFINITIONS in a second artifact, `gen.generated_cpp`, and this
            # function can only return `box['c']`. Nothing downstream reads it:
            # not the return value, not the CAS key, not `_compile_one_object`'s
            # object bytes. The module's `.c` still carries the `extern`
            # declarations and the calls, so the object references
            # `_mojogen_<module>_<fn>_start/_resume/_value/_destroy` with nothing
            # defining them anywhere on the link line.
            #
            # It is silent in a dylib and FATAL in an executable, which is why
            # it went unnoticed: `build()` links a production dylib with
            # `undefined=True` (`-undefined dynamic_lookup`), so a module with
            # dangling coroutine symbols still loads, and both of CLAUDE.md's
            # silent-verdict steps are blind to it by construction — the
            # `stdlib-dylib` skip count does not move and `stdlib-syntax` only
            # checks that the `.c` parses. `fire.py build fire.py` links
            # `mojoc` against that dylib with every symbol resolved, and the
            # undefined entry points land in the program's undefined set
            # straight away.
            #
            # So this REFUSES instead: `build()`'s existing per-module error
            # path prints `skip <module>: ...` and the client falls back to
            # source, which is the same honest degradation the dylib already
            # uses for a module it cannot compile. It does not compile the
            # generator — that is candidate 1 in the doc, and it changes what
            # every dylib module's link line looks like — but it converts a
            # silent hole into a visible one, and the skip count it adds is
            # exactly the measurement candidate 1 has to not increase.
            #
            # Measured exposure on this tree is ZERO for both module lists
            # that ship (249 production stdlib modules and the 61-module
            # self-host closure: 0 real generator/async defs before lowering,
            # 0 after — `test_selfhost.py::closure_coroutines_are_lowerable`
            # pins the second), so this costs no `skip` line today. It is
            # `fire.py dylib` over a project's own Python-family modules where
            # it bites, which is a tree whose `.py` files are in neither list.
            # the refusal that stops `generated_cpp` being dropped silently.
            #
            # `linkable=False` for a caller that has NO link line — which is
            # `compile_stdlib.py`'s syntax sweep, the one instrument that reads
            # this function's return value and checks that the emitted C PARSES.
            # Every word of the argument above is about the link: a dangling
            # `_mojogen_*` reference is a link-line fact, and a sweep that never
            # links cannot observe it. Refusing there turned three REAL modules
            # into `stdlib-syntax` failures for a property they do not have:
            #
            #   test/runtime/test_asyncrt.mojo
            #   test/runtime/test_locks.mojo
            #   test/runtime/test_raising_asyncrt.mojo
            #
            # `FAILED: 18 (18 expected, 0 unexpected)` on master became
            # `21 (18 expected, 3 unexpected)` — three UNEXPECTED, which is the
            # direction CLAUDE.md's `stdlib-syntax` rule names as a regression.
            # bugs4-2's own measurement missed it because it looked at the two
            # module lists that SHIP and this sweep walks `test/runtime/` too.
            # So the switch is the honest shape: the emitter reports what it
            # produced, and the LINKER decides whether it can use it.
            if box.get('cpp') and linkable:
                raise _DylibGeneratedCppError(
                    f"{module_name}: {len(box['cpp'])} bytes of C++20 coroutine "
                    f"definitions (gen.generated_cpp) that this path cannot "
                    f"link; a dylib module's generator would ship as a dangling "
                    f"_mojogen_* reference. Compile this module as an executable "
                    f"(fire.py build), or fall back to source.")
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
    _LAST_DEGRADED[:] = box.get('degraded') or []
    _LAST_CSYMS.clear()
    _LAST_CSYMS.update(box.get('csyms') or {})
    return box['c']


# Why the LAST module compiled produced a different program from the one its
# source says: one entry per generic struct that could not be elaborated, as
# `Struct[Args] from <source>: <exception>`. Empty means the compile was clean.
# Module-level because the codegen runs in a thread (`compile_module_to_c`) and
# because the consumer (`compile_module_to_c_cached`, and the stdlib sweep's
# verdict through `last_degradations()`) is a different function from the
# producer. It describes EXACTLY ONE module — the last one compiled or served
# from the in-process L1 — never an accumulation, so a degraded module followed
# by a clean cache hit does not label the clean one.
_LAST_DEGRADED: list = []

# The free-function C symbols the LAST module compiled named, `{bare name: [symbol]}`,
# as codegen itself produced them (see emit_funcs._func_csym). The export table takes
# its symbol names from this, so it can never disagree with the definitions it lists.
_LAST_CSYMS: dict = {}
# The symbol record of the object `_compile_one_object` last built in this process.
_OBJECT_CSYMS: dict = {}


def _apply_codegen_csyms(exports: list, csyms: dict, defined: set) -> list:
    """Give each free-function export the symbol codegen named it for a definition
    this object actually contains.

    Codegen's record for a name holds every symbol it produced for that name in this
    module: the definition, and also call sites that resolve to another symbol (a
    call to the runtime's `atol` is spelled `mojo_atol`). The definition is the one
    the object defines, so the candidates are intersected with `defined` (the
    object's own symbols, arch-prefixed as `nm` spells them). Exactly one survivor
    is the function's symbol. Anything else keeps its signature-derived spelling and
    the classifier checks it as before."""
    for e in exports:
        if e['kind'] != reflect.SYM_FUNCTION or e.get('csym'):
            continue
        names = [n for n in (csyms.get(e['name']) or []) if ('_' + n) in defined]
        if len(names) == 1:
            e['csym'] = names[0]
    return exports


def _read_csyms(side_key: str):
    """The symbol record CAS-published beside an object, or None when there is none."""
    import json
    p = cas.lookup(side_key, '.json')
    if p is None:
        return None
    with open(p) as f:
        return json.load(f)

# Every generic-struct elaboration refusal this process has seen, as
# `(module_path, [reason, ...])`, accumulated by `compile_module_to_c_cached`.
# The un-elaborated-template fallback that produces the reason is load-bearing
# (kept compiling; see `test_elaboration_failure_is_not_cached`), but the
# refusal is NOT a cacheable artifact and NOT console noise: a driver that
# wants the detail (the stdlib sweep) reads it from its own call frame via
# `last_degradations()` — that list is per-call, which is what threads it back
# to the caller — and this log keeps it visible for anything that only has the
# module-level state. Read with `refusal_log()`; never printed here, so a
# reader of the sweep's console is not asked to guess which red lines are
# actionable (bug:CODEGEN_stdlib_run_prints_elaboration_refusals).
_REFUSAL_LOG: list = []


def last_degradations() -> list:
    """The degradation list for the most recent `compile_module_to_c_cached` (or
    `compile_module_to_c`) call in this process, as a copy.

    A cache hit restores the entry's own list: a published artifact is only
    ever a clean compile, but the in-process L1 also holds modules that were
    NOT published (see `compile_module_to_c_cached`), so "the last thing I
    read from a cache" is not the same claim as "never degraded". Read this,
    do not clear it."""
    return list(_LAST_DEGRADED)


def refusal_log() -> list:
    """Every recorded `(module_path, [reason, ...])` refusal, as a copy."""
    return list(_REFUSAL_LOG)


def _record_refusal(path: str, degraded: list) -> None:
    """Keep the refusal off the console and on the books.

    The detail still has to reach whoever runs the sweep, so it is appended
    to `_REFUSAL_LOG` (read back with `refusal_log()`) and echoed to the
    console only under MOJO_DEBUG, like every other deliberately-degraded
    path in this compiler. Nothing is swallowed: the module's `.ci` is
    refused publication here, and the caller that wants a count reads it
    from its own frame via `last_degradations()`."""
    _REFUSAL_LOG.append((path, list(degraded)))
    if os.environ.get('MOJO_DEBUG'):
        sys.stderr.write(
            f"[compile_module_to_c_cached] {path}: {len(degraded)} generic "
            f"struct elaboration(s) failed, so this module's C is NOT the "
            f"program its source describes and it is NOT being cached:\n"
            + ''.join(f'    {d}\n' for d in degraded))


# In-process L1 for compile_module_to_c_cached. Values are
# `(c_text, degraded)` — the degradation list is stored WITH the artifact so a
# hit can answer for itself rather than inheriting the previous module's state
# (a degraded compile is not published to the CAS, but it is kept here).
_stdlib_compile_cache: dict = {}


def stdlib_codegen_key(src: str, path: str, module_name: str,
                       linkable: bool = True) -> str:
    """The CAS key `compile_module_to_c_cached` stores a module's C under.

    One definition, because a caller that wants to know "would this be a hit?"
    (compile_stdlib.py's hit/miss counters) has to build the SAME key. It built
    the linkable one while compiling with `linkable=False`, whose key carries
    the `|nolink` suffix, so its pre-check never matched and the report said
    `Codegen CAS: 0/679 hits` for a sweep that was 100% cached."""
    return cas.stdlib_compile_key(src, path, module_name,
                                  extra='' if linkable else '|nolink')


def compile_module_to_c_cached(src: str, path: str, module_name: str,
                              linkable: bool = True) -> str:
    """Like compile_module_to_c but CAS-cached under stdlib-compile/<hash>.

    The key folds in the compiler fingerprint (a codegen change invalidates
    every cached .ci) and the stdlib fingerprint (a module's C depends on its
    stdlib imports' signatures/layouts, so any stdlib edit invalidates too).

    **A module built through a FAILED generic-struct elaboration is not
    published.** That compile is not this module: the struct was lowered
    against its un-elaborated template, so every one of its type parameters is
    typed `int64_t` where the source says otherwise. Publishing it puts a
    wrong artifact in a content-addressed store under the CURRENT compiler
    fingerprint, which means every later run — a `make gate` on another
    machine's checkout of the same commit, an hour later — replays the wrong
    artifact instead of recompiling and getting it right. That is how
    `test/iter/test_ref_iteration.mojo` reached a gate as an UNEXPECTED
    `stdlib-syntax` failure (`request for member 'value' in something not a
    structure or union`, at a line about iterators) an hour after the
    transient that caused it was gone: the condition had ended and the
    artifact had not.

    So the miss path is spelled out here rather than delegated to
    `cas.get_or_build_text`, whose contract is "build, then publish" with no
    room for a build that must not be published. It is those six lines
    duplicated, not a second cache: the same key, the same L1, the same
    `cas.stats` accounting, in the same order.

    **The degradation is part of the RESULT, not just a warning.** On return,
    `last_degradations()` describes THIS module and nothing else — empty for a
    CAS hit, the build's list for a miss, and the stored list for an L1 hit
    (which may be a degraded compile, since those are not published but are
    kept for the rest of the process). compile_stdlib.py's per-file verdict
    reads it and reports the file FAILED: a module the compiler says is not
    the program its source describes must not count as a pass.
    """
    # The `‘linkable’ half is part of the KEY, not of the cache: a `.ci`
    # published by a `linkable=False` call has had no link-line check made on
    # it, and handing it to `build()` would republish the very hole the refusal
    # exists to refuse. One extra character in the key, and the two artifacts
    # can never be confused for each other.
    # `last_degradations()` must describe THIS call and only this call. The
    # compile path clears/refreshes it, and each L1 entry carries its own
    # degradation list, so a hit answers for the module it replays rather than
    # inheriting whichever module this worker compiled last. (A CAS hit can
    # only be clean: a degraded compile is never published.)
    key = stdlib_codegen_key(src, path, module_name, linkable)
    if key in _stdlib_compile_cache:
        text, degraded = _stdlib_compile_cache[key]
        _LAST_DEGRADED[:] = degraded
        return text
    cached = cas.lookup(key, '.ci')
    if cached is not None:
        cas.stats['hits'] += 1
        with open(cached) as f:
            text = f.read()
        # Only a CLEAN compile is ever published (the branch below), so a hit
        # in the shared store cannot be degraded. Say so explicitly rather
        # than leaving `_LAST_DEGRADED` holding whatever the previous module
        # in this worker left there: compile_stdlib.py reads it as THIS
        # module's verdict.
        degraded = []
    else:
        cas.stats['misses'] += 1
        text = compile_module_to_c(src, path, module_name, linkable=linkable)
        degraded = last_degradations()
        if degraded:
            _record_refusal(path, degraded)
        else:
            cas.publish(key, '.ci', text.encode('utf-8'))
    _LAST_DEGRADED[:] = degraded
    _stdlib_compile_cache[key] = (text, list(degraded))
    return text


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
    object stale: `fire dylib` reported a fresh build yet the dylib kept the
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


def _defined_symbols(gcc: str, obj: str, *, include_weak: bool = False) -> set:
    """External symbols *defined* (not undefined) by an object file, via nm.

    By default a WEAK definition is left out: it is the clash check's question
    ("which names would collide if this module joined the dylib?"), and a weak
    definition is merged by the linker rather than colliding. Questions about
    what the object SURFACES — the runtime's export table, or whether a header
    declaration has a definition — pass `include_weak=True`, because a weak
    definition is a real, callable, exported symbol (`input` in fire_runtime.c
    is one: the stdlib's own `input` overrides it, but the runtime still defines
    it for everyone who does not)."""
    nm = 'nm'  # llvm/bsd nm on the PATH; gcc toolchains ship a compatible one
    try:
        # -m names a Mach-O weak definition as "weak external"; plain nm reports it as an ordinary `T`.
        out = subprocess.run([nm, '-g', '-m', obj], capture_output=True, text=True).stdout
    except Exception:
        return set()
    syms = set()
    for line in out.splitlines():
        if 'weak' in line and not include_weak:
            # A WEAK definition is merged by the linker, not a clash: every module that carries the same weak
            # copy (the empty GPU sidecar's introspection stubs, in ~every stdlib module) links fine.
            continue
        parts = line.split()
        # -m lines: "<addr> (<section>) external <name>", while an UNDEFINED
        # reference has no address at all: "(undefined) external <name>".
        # Both spellings contain "external", so the address is what separates
        # a definition from a reference. Counting a reference as a definition
        # makes every module "clash" on the runtime symbols it imports, and
        # then makes `_localize_symbols`'s keep list name undefined symbols,
        # which nmedit rejects — the whole module is dropped for a collision
        # that never existed (the 150-module exclusion).
        if 'external' in parts and len(parts) >= 3:
            if parts[0] != '(undefined)':
                syms.add(parts[-1])
            continue
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


def _nm_all(objs: list, args: tuple) -> set:
    """Every symbol ONE `nm` run over ALL of `objs` names — the union, because
    the caller only ever asks "is this symbol referenced anywhere in the
    link / defined anywhere in it", never which object carried it.

    One invocation per question, not one per object: `build()` runs the
    generic-instance pre-pass on every dylib it links, including the full
    664-module stdlib build whose pass-1 objects are usually all CAS hits, so
    a subprocess per object per question would put seconds of `nm` on the warm
    path for nothing. `nm` prints a `file:` header before each object's
    symbols (and a fat file's header ends in ':' too); those are skipped, and
    the symbol is the line's last token in both `-u` (`_foo`) and `-g -U`
    (`0000000000000123 T _foo`) spellings — the same rule
    `tools/stdlib_dylib_ratchet._nm_symbols` uses.

    A failing `nm` RAISES: an empty set would read as "nothing is referenced"
    or "nothing is defined", which are silent-green and false-red readings of
    exactly the state this pre-pass exists to measure."""
    argv = ['nm']
    argv = argv + list(args) + list(objs)
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("nm %s failed (exit %d): %s"
                           % (' '.join(args), r.returncode,
                              (r.stderr or '').strip()))
    syms = set()
    for line in r.stdout.splitlines():
        line = line.rstrip()
        if not line or line.endswith(':'):
            continue
        syms.add(line.split()[-1])
    return syms


def _bare_symbol(s: str) -> str:
    """`s` without the single leading underscore Mach-O gives every C symbol,
    so symbol sets from `nm` can be compared on ELF too."""
    if s.startswith('_'):
        return s[1:]
    return s


# The type argument a cross-module generic instance is built with.
#
# Every generic free function a caller in ANOTHER module names by an erased
# signature has its type parameters erased to `int64_t` on the caller's side:
# `module_loader`'s text scan resolves the annotation `T` (and every container
# wrapped around it, e.g. `MutPointer[T, _]`) to `int64_t`, which is why the
# reference carries the suffix of `int64_t` / `int64_t, int64_t` rather than of
# any concrete type. `Int` is the Mojo spelling whose C lowering is exactly
# that word, so the definition the module emits has the parameter types the
# caller's own declaration has. The body is compiled by the defining module's
# codegen (not in an isolated TU), so it is the same program the same template
# lowers to everywhere else in this backend — including this backend's normal
# erasure of the parts that need the concrete type.
_INSTANCE_TYPE_ARG = 'Int'

_HEX_DIGITS = '0123456789abcdef'


def _split_overload_suffix(sym: str) -> tuple:
    """`(base, suffix)` where `suffix` is '' or the `_` plus six lowercase hex
    digits `GimpleGen.overload_suffix_for` appends.

    Bounded slices plus `find`, never `sym[-7]`/`sym[i]` or a loop over the
    string's characters: this file is compiled by the self-hosted compiler,
    whose char* subscription yields the BYTE's integer value rather than a
    1-char string, and whose run-time regex engine is deliberately absent (see
    `overload_suffix_for`'s own note and `gimple_ctypes.source_decl_ends`)."""
    if len(sym) > 6 and sym[-7:].startswith('_'):
        tail = sym[-6:]
        ok = True
        for k in range(0, 6):
            if _HEX_DIGITS.find(tail[k:k + 1]) < 0:
                ok = False
                break
        if ok:
            return sym[:-7], sym[-7:]
    return sym, ''


def _top_level_generic_names(src: str) -> list:
    """Names of the TOP-LEVEL generic free functions a module's text declares,
    in source order.

    Text-only, no parse: this runs over every module in the link before any
    codegen, and `def <name>[` in column 0 is exactly a top-level generic free
    function. An indented `def` is a method, and `def <name>(` is concrete, so
    neither is a candidate. Bounded slices, not `rest[i]` — see
    `_split_overload_suffix` on why this file cannot index a string."""
    out = []
    _word = ('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
             '0123456789_')
    for line in src.split('\n'):
        kw = 0
        if line.startswith('def '):
            kw = 4
        elif line.startswith('fn '):
            kw = 3
        else:
            continue
        rest = line[kw:]
        i = 0
        while i < len(rest) and _word.find(rest[i:i + 1]) >= 0:
            i += 1
        if i == 0:
            continue
        j = i
        while j < len(rest) and (' \t').find(rest[j:j + 1]) >= 0:
            j += 1
        if j < len(rest) and rest[j:j + 1] == '[' and rest[:i] not in out:
            out.append(rest[:i])
    return out


def _template_shape(template_src: str, name: str):
    """`(arity, c_parameter_types, return_annotation)` for the parsed template,
    or None.

    The C types come from `ModuleLoader._mojo_type_to_c`, the ONE resolver the
    text-scan import signature (`module_loader.load_module`) uses to spell an
    imported function's parameters — so the suffix computed from them with
    `GimpleGen.overload_suffix_for` is the suffix the CALLER put on its
    reference, not a second naming scheme."""
    try:
        stmts = Parser(py_tokenize(template_src)).parse_module()
    except Exception:
        return None
    for s in stmts:
        if not (isinstance(s, FunctionDef) and s.name == name):
            continue
        c_params = []
        for pname, ptype in (getattr(s, 'params', None) or []):
            if pname == 'self':
                continue
            if pname.startswith('*'):
                # `*args` makes the scan's signature variadic, i.e. suffix-less
                # (`overload_suffix_for` refuses a `...` parameter list).
                c_params.append('...')
                break
            bare = ptype.split('=')[0].strip()
            try:
                ct = ModuleLoader._mojo_type_to_c(bare, param=True)
            except Exception:
                ct = 'int64_t'
            c_params.append('int64_t' if ct == 'void' else ct)
        ret = getattr(s, 'return_type', None) or ''
        return (len(c_params), tuple(c_params), ret)
    return None


def _select_generic_template(module_src: str, name: str, suffix: str):
    """The template of `name` that the requested `suffix` names, or None.

    A name may have several same-named generic definitions (Mojo separates
    them by arity and parameter types; the C symbol separates them by
    `overload_suffix_for`). Two provable selections, and nothing else:

    * `suffix` is non-empty — the candidates whose PREDICTED suffix is exactly
      it. Several such candidates are indistinguishable at the C level when
      their erased parameter and return types agree, so any of them is right.
    * `suffix` is empty — the caller's scan spells an OVERLOADED name `(...)`,
      so the symbol states no types. Accept only when every candidate has one
      and the same erased signature; then any of them is callable.

    Anything else is ambiguous, and an ambiguous request is DECLINED rather
    than resolved by source order: a definition with the wrong body under the
    caller's symbol is a silent miscompile, while no definition is the
    documented "client falls back to source" state this pass must not worsen."""
    import elaborate
    shapes = []
    for t in elaborate.extract_fn_sources(module_src, name):
        # A concrete same-name definition (`def name(`) has no type parameters
        # and an indented one is a METHOD whose block cannot be parsed as a
        # module; neither is a generic free-function template.
        if not elaborate.type_param_names(t):
            continue
        shape = _template_shape(t, name)
        if shape is not None:
            shapes.append((t, shape))
    if not shapes:
        return None
    if suffix:
        matches = []
        for _t, sh in shapes:
            if GimpleGen.overload_suffix_for(list(sh[1])) == suffix:
                matches.append((_t, sh))
    else:
        matches = shapes
    if not matches:
        return None
    pick = matches[0]
    first = pick[1]
    for _t, sh in matches[1:]:
        if sh != first:
            return None
    return pick[0]


def _rename_instance_head(concrete: str, mangled: str, symbol: str) -> str:
    """The monomorphized definition with its own mangled name replaced by the
    exact `symbol` the caller references.

    Anchored on a line-initial `def`/`fn`, so a mention of the template name
    inside the body or a docstring is untouched. `monomorphize_source` puts
    the definition head first, and this REFUSES rather than return a text it
    did not rename — an unrenamed instance is a different symbol. Bounded
    slices, not `concrete[q]` — see `_split_overload_suffix` on why this file
    cannot index a string."""
    _after = '([: \t\n'
    for kw in ('def ', 'fn '):
        head = kw + mangled
        if concrete.startswith(head):
            rest = concrete[len(head):]
            if not rest or _after.find(rest[:1]) >= 0:
                return kw + symbol + rest
    for kw in ('def ', 'fn '):
        head = '\n' + kw + mangled
        p = concrete.find(head)
        if p < 0:
            continue
        q = p + len(head)
        if q >= len(concrete) or _after.find(concrete[q:q + 1]) >= 0:
            return concrete[:p] + '\n' + kw + symbol + concrete[q:]
    raise RuntimeError("could not rename the monomorphized head %r" % mangled)


def _generic_instance_source(template_src: str, symbol: str) -> str:
    """The concrete definition of `template_src` that `symbol` asks for.

    One monomorphization, then the head renamed to the caller's exact symbol.
    The caller's own `_func_csym` produced that name; reusing it verbatim is
    what makes the definition and the reference the SAME symbol (the bug
    doc's "one naming function, not a second spelling").

    The bracket arguments are the ones the caller's erased signature PROVES,
    and nothing else:

    * a TYPE parameter is instantiated with `_INSTANCE_TYPE_ARG` — the type
      whose C lowering is the erased word the caller passes;
    * a parameter `elaborate.erased_only_params` proves is discarded by
      `_mojo_type` (the origin / receiver-convention group) takes the SAME
      stand-in the elaborator's own `.o` route uses for it
      (`elaborate.ERASED_TYPE_ARG`);
    * a comptime VALUE parameter (`k: Int`, `mut: Bool`) has no provable
      argument here — the caller's erased signature does not carry it — so the
      request is REFUSED rather than substituting a type into a value's place.

    Refusing is deliberate and is the doc's own rule: a wrong-erased template
    under the caller's symbol is a silent miscompile, while no definition is
    the documented "client falls back to source" state this pass must not
    worsen."""
    import monomorphize
    import elaborate
    params = elaborate.type_param_names(template_src)
    if not params:
        return None
    kinds = elaborate.type_param_kinds(template_src)
    kind_of = {}
    for i in range(len(params)):
        kind_of[params[i]] = kinds[i] if i < len(kinds) else 'type'
    erased = elaborate.erased_only_params(template_src, params)
    type_args = {}
    for p in params:
        if p in erased:
            type_args[p] = elaborate.ERASED_TYPE_ARG
        elif kind_of[p] == 'type':
            type_args[p] = _INSTANCE_TYPE_ARG
        else:
            return None
    mangled, concrete = monomorphize.monomorphize_source(template_src, type_args)
    return _rename_instance_head(concrete, mangled, symbol)


def _generic_instance_requests(modules: list, results: list) -> dict:
    """`{defining module path: {caller symbol: instance source}}` for every
    generic free-function instance a module in THIS link references and
    nothing in it defines.

    A module is compiled ALONE, so a generic it merely declares has no
    concrete signature there and is never emitted — while a caller in another
    module that cannot elaborate the call names it by the text-scan erased
    signature (`..._forget_deinit_9f63a2`). Nothing defined that symbol, so
    the dylib left it lazy/undefined and every client fell back to source.
    This pre-pass answers exactly those references: it reads the reference set
    from the caller OBJECTS (`nm -u`, so it works on a CAS hit too, unlike the
    generated C, which only exists after a miss) and hands each defining
    module the instances its callers ask for, to emit in its OWN translation
    unit where its own types and functions resolve.

    Only symbols whose home module is in this link are considered, and only
    when a top-level `def <name>[` in that module names them — this is the
    generic-free-function class, not a place to invent definitions for
    ordinary missing symbols (parts 5 and 8 of the same bug are their own)."""
    index = {}
    src_by_path = {}
    for path in modules:
        try:
            src = open(path).read()
        except OSError:
            continue
        src_by_path[path] = src
        qualifier = _module_name_for(path)
        for name in _top_level_generic_names(src):
            index[qualifier + '_' + _safe_name(name)] = (path, name)
    if not index:
        return {}

    defined = set()
    undefined = set()
    _objs = []
    for _path, _name, ofile, _exports, error, _hit in results:
        if error is None and ofile:
            _objs.append(ofile)
    if _objs:
        try:
            for s in _nm_all(_objs, ('-g', '-U')):
                defined.add(_bare_symbol(s))
            for s in _nm_all(_objs, ('-u',)):
                undefined.add(_bare_symbol(s))
        except Exception as e:
            print("  instance scan: %s" % e, file=sys.stderr)
            return {}

    requested = {}
    for sym in sorted(undefined):
        if sym in defined:
            continue
        base, suffix = _split_overload_suffix(sym)
        home = index.get(base)
        if home is None:
            continue
        definer, gname = home
        if sym in requested.get(definer, {}):
            continue
        module_src = src_by_path.get(definer)
        if module_src is None:
            continue
        try:
            template = _select_generic_template(module_src, gname, suffix)
            if template is None:
                raise RuntimeError(
                    "no %s template matches the erased signature" % gname)
            source = _generic_instance_source(template, sym)
            if source is None:
                raise RuntimeError(
                    "%s has a comptime value parameter the erased "
                    "signature does not carry" % gname)
        except Exception as e:
            # Visible, and NOT a `skip <module>:` line: the module still
            # builds and the dylib still links. The reference stays lazy,
            # the documented state this pass must not worsen.
            print("  instance %s: not emitted in %s: %s"
                  % (sym, os.path.basename(definer), e), file=sys.stderr)
            continue
        if definer not in requested:
            requested[definer] = {}
        requested[definer][sym] = source
    return requested


def _compile_one_object(src: str, path: str, name: str, workdir: str, gcc: str,
                         objflags: tuple = _OBJ_FLAGS, no_mangle: tuple = ()) -> bytes:
    """Cold-path builder: Mojo → C → .o; returns the object's bytes.

    `src` may already carry the cross-module generic instances a caller in
    another module asked for, appended by `_compile_module_job`; `no_mangle`
    names them, so each is emitted under exactly the symbol that caller
    references.

    A module whose generic-struct elaboration failed is compiled against its
    un-elaborated template (every type parameter `int64_t`), so its C is not the
    program its source describes. Refuse it here — before the object is written
    into the shared CAS and before it can be linked into the dylib — so the
    caller's per-module skip path handles it the same way the sweep does."""
    cfile = os.path.join(workdir, name + '.c')
    ofile = os.path.join(workdir, name + '.o')
    c_text = compile_module_to_c(src, path, name, no_mangle=no_mangle)
    _OBJECT_CSYMS.clear()
    _OBJECT_CSYMS.update(_LAST_CSYMS)
    refusals = last_degradations()
    if refusals:
        raise RuntimeError(
            f"elaboration: {len(refusals)} generic struct elaboration(s) failed, "
            f"so the C is not the program its source describes: {refusals[0]}")
    with open(cfile, 'w') as f:
        f.write(c_text)
    subprocess.run([gcc, *objflags, '-c', '-o', ofile, cfile], check=True)
    with open(ofile, 'rb') as f:
        return f.read()


def _compile_module_job(path: str, workdir: str, use_cache: bool, objflags: tuple = _OBJ_FLAGS,
                         known_structs: frozenset = frozenset(), dep_fingerprint: str = '',
                         instances: dict = None):
    """Per-module independent work (source → object): read, collect exports,
    compile (cache-or-build). Each module is fully independent — no shared
    state — so this parallelizes across processes the same way
    compile_stdlib.py's compile_file does. Returns (path, name, ofile,
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
    Must be picklable for ProcessPoolExecutor — a frozenset of str is.

    `instances` (`{symbol: source}`, second pass only): concrete generic
    instances a caller in another module references, appended to this module's
    source and emitted HERE, so the template body is compiled against its own
    module's types and functions. They are part of the source, hence of the
    CAS key, and their names go to `no_mangle` so each is emitted under the
    caller's own symbol rather than qualified and re-suffixed here. Their
    exports are deliberately not advertised: the reflection table describes
    the module's declarations, and these exist only to satisfy references."""
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
    no_mangle = ()
    if instances:
        # Sorted, so the appended text (and therefore the CAS key and the
        # emitted C) is the same byte for byte on every build.
        _parts = []
        for _sym in sorted(instances):
            _parts.append(instances[_sym])
        src = src + '\n\n\n' + '\n\n\n'.join(_parts)
        no_mangle = tuple(sorted(instances))
    hit = None
    try:
        if use_cache:
            key = cas.module_key(src, _imported_sigs(src), gcc, objflags,
                                 dep_fingerprint=dep_fingerprint)
            ofile, hit = cas.get_or_build(
                key, '.o', lambda: _compile_one_object(src, path, name, workdir, gcc,
                                                       objflags, no_mangle))
            # The codegen symbol record is published beside the object. A hit whose
            # entry predates the record is rebuilt once, so the record exists.
            side_key = key + '.csyms'
            csyms = _read_csyms(side_key) if hit else None
            if csyms is None:
                if hit:
                    ofile = cas.publish(key, '.o', _compile_one_object(
                        src, path, name, workdir, gcc, objflags, no_mangle))
                csyms = dict(_OBJECT_CSYMS)
                import json
                cas.publish(side_key, '.json', json.dumps(csyms, sort_keys=True).encode())
        else:
            ofile = os.path.join(workdir, name + '.o')
            with open(ofile, 'wb') as f:
                f.write(_compile_one_object(src, path, name, workdir, gcc,
                                            objflags, no_mangle))
            csyms = dict(_OBJECT_CSYMS)
        exports = _apply_codegen_csyms(exports, csyms, _defined_symbols(gcc, ofile, include_weak=True))
        # A degraded compile must never reach the dylib. The cached path only
        # serves objects published by a clean build (_compile_one_object refuses
        # to produce a degraded one), but a fresh in-process compile records its
        # degradations in this worker; treat them as the job's error so the
        # caller prints `skip <module>: ...` instead of linking the module.
        refusals = last_degradations() if hit is False else []
        if refusals:
            return (path, name, None, exports,
                    f"elaboration: {len(refusals)} generic struct elaboration(s) failed, "
                    f"so the C is not the program its source describes: {refusals[0]}",
                    hit)
    except Exception as e:
        return path, name, None, exports, str(e), hit
    return path, name, ofile, exports, None, hit


class _OutputLock:
    """Exclusive, cross-process, released on exit: an `flock` on a side file
    next to `out`, held across `build`'s whole publish. A SIDE file, because
    `build` replaces the `.dylib` and a lock on the library itself would admit
    a second process the instant the first created it.

    **What this buys, and what it does not.** It buys LATENCY, not safety: with
    the currency check moved inside it, N concurrent callers collapse to one
    link and N-1 no-ops instead of N identical links. Safety comes entirely
    from the atomic publish — the link stages into the work directory and
    `os.replace`s into `out`, and the cache-hit copy renames rather than
    truncating in place — and that half deliberately depends on nothing but
    `os.replace` / `shutil.copy` / `os.path`, all of which this file already
    relies on (`runtime_dylib`'s own staged link is the same shape).

    The split is not tidiness, it is measured. `fcntl.flock` does NOT survive
    the compiled path: compiled through this compiler's own link-mode
    pipeline, a module whose body is `fcntl.flock(fd, 2)` emits

        _t4 = _t2;  /* int64_t.flock() stubbed */

    — the extern preamble's weak stub, which returns 0 and takes no lock. So
    in a self-hosted build this lock is a no-op, and it must be: a
    correctness argument that rested on it would be an argument that holds on
    `python3 fire.py build` and silently does not hold in `mojoc`. Staging +
    `os.replace` is the half that is equally true in both.

    Why the lock is here at all, then: `out` is a FIXED path
    (`build_stdlib`'s default is `build/libmojostdlib.<arch>.dylib`) and every
    `fire.py build` reaches it through `driver.compile_program`, so every
    parallel job in the gate asks for the same library at once. Measured on
    this tree, twice, `python3 tools/suite.py -j4 linkmode nonlocal ...`:

        ld: open() failed, errno=17 (File exists) for
            '<checkout>/build/libmojostdlib.arm64.dylib'

    which reached two of this batch's own jobs as a failing `test_link_mode`
    case (`test_bare_submodule_import_value_read raised: ... -o,
    .../libmojostdlib.arm64.dylib ... returned non-zero exit status 1`) and a
    failing `test_nonlocal` case wanting `'7\n'`. That error is the link
    colliding on the shared output path; on the python3 path the lock is what
    removes it, and the staged link is what makes it harmless if it recurs.

    `flock` is advisory and per-open-file-description, so the kernel releases
    it when the process dies and a killed build cannot wedge the tree — the
    same shape and the same reasoning as `formal/imports.py::_dylib_lock` (and
    the reason this helper is LOCAL to this module rather than shared with it:
    this file is in `mojoc`'s own compile closure — `cas.selfhost_inputs()`
    lists it — and BLOW.md's root-cause record for the ~15.8 GB fixed
    # compile-time blowup measured a self-host failure for exactly the
    # cross-module function reference sharing one would mean).

    **Why a CLASS and not a `@contextlib.contextmanager` generator.** This was
    one, and it broke the self-host build at LINK time, so the shape is load-
    bearing rather than stylistic. Measured, in order:

      * `mojo/middle/coro.py::_eligible` REFUSES a decorated generator
        outright — this exact function returned `(False, 'decorated')` — so it
        never reached the A3 stack-switch lowering (the one that emits a
        generator's `_start`/`_resume`/`_value`/`_destroy` bodies straight
        into the module's own `.c`, which is why every OTHER generator in the
        self-host closure is fine).
      * It therefore fell through to the C++20 coroutine emitter, whose
        definitions live in a SEPARATE companion translation unit,
        `GimpleGen.generated_cpp`.
      * `compile_module_to_c` — this file's own per-module compile, the one
        every dylib build and therefore every self-host build goes through —
        returns the `.c` and DISCARDS `generated_cpp`. So the object referenced
        `_mojogen_build_stdlib_dylib__output_lock_start/_resume` with nothing
        anywhere defining them, and `mojoc`, `selfhost` and
        `bootstrap-stage2-cc` all died with

            Undefined symbols for architecture arm64:
              "__mojogen_build_stdlib_dylib__output_lock_start",
              "__mojogen_build_stdlib_dylib__output_lock_resume"

        `test_selfhost.py`'s `closure_coroutines_are_lowerable` is the guard
        that keeps it out; the root cause is the silent drop of `generated_cpp`
        by the dylib module path, now refused.

    A plain function pair (`_acquire`/`_release` around an explicit
    `try`/`finally`) is the other generator-free shape and lowers correctly
    too (measured: the release is emitted on the normal, the caught and the
    re-raise paths). The class is preferred because it keeps acquire and
    release in ONE place, so no future edit can release an fd it never took.

    The `as` binding in `build`'s `with` is load-bearing too, and not for
    Python's sake: in the compiled path a `with` item with NO `as` target
    contributes nothing to the teardown list, so `__exit__` is never called at
    all (measured; filed as
    that bug's doc, deleted with its fix)."""

    fd: int

    def __init__(self, out: str) -> None:
        # `flock` inside the guarded region, exactly as the generator's
        # `try: flock; yield; finally: close` had it: a failing `flock` must
        # still close the descriptor it opened. `with`-block teardown cannot
        # do that job — `__exit__` is not reached when `__enter__` raises, and
        # here the raise happens before `__enter__` even runs.
        _fd = os.open(out + '.lock', os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(_fd, fcntl.LOCK_EX)
        except BaseException:
            os.close(_fd)
            raise
        self.fd = _fd

    def __enter__(self) -> int:
        return self.fd

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        # Always False, never a conditional True: the compiled path calls
        # `__exit__` and then re-raises unconditionally, so a "swallow"
        # return would hold on `python3 fire.py build` and not in `mojoc`.
        os.close(self.fd)
        return False


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
          track_local_deps: bool = True, arch: str = None,
          stamp_key: str = None) -> str:
    """`opt_flag` (e.g. '-O2'): folded into every module's AND the runtime's
    own object-compile flags, and into their CAS keys (so an -O2 build never
    serves a stale -O0-compiled object, or vice versa) — `_OBJ_FLAGS`/plain
    `toolchain_fingerprint(gcc, ())` on their own carry NO optimization flag
    (gcc's implicit -O0), appropriate for the STDLIB dylib (compiled once,
    used everywhere, optimized for compile time / cache-friendliness) but not
    for a `fire dylib`-built artifact meant to be linked into a real program
    and actually run at speed.

    `arch` is the architecture the dylib is FOR (default: the host's) and
    reaches every module compile, every runtime object, the runtime dylib this
    links against, the final link, the CAS keys and the artifact's own
    verification — see the architecture section at the top of this file for why
    each of those is separately necessary and why the verification is not
    optional.

    `stamp_key`: when given, the installed artifact's digest is recorded beside
    `out` under that key, INSIDE the publish lock, so the stamp and the bytes it
    describes cannot come from two different builds. `build_stdlib()` passes
    `stdlib_dylib_currency_key(arch)`; nothing else does, so `fire dylib`
    builds write no stamp."""
    gcc = find_gcc()
    gxx = find_gxx()
    arch = normalize_arch(arch)
    objflags = _OBJ_FLAGS + arch_flags(arch) + ((opt_flag,) if opt_flag else ())
    os.makedirs(os.path.dirname(out), exist_ok=True)
    # Every object, the generated reflection C and its object, and the staged
    # dylib live under this work directory, and `os.replace` moves only the
    # finished dylib out — so nothing removes it unless `_staging_dir` does.
    # Measured at ~324 kB for a ONE-module cold build (a full stdlib build is
    # 664 modules plus the runtime and the reflection table, so tens to hundreds
    # of MB), created unconditionally even on a cache hit, and leaked per cold
    # CAS before this.
    with _StagingDir('mojostdlib_') as workdir:
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

        # Cross-module generic FREE FUNCTION instances (bug:CODEGEN_stdlib_
        # dylib_lazy_undefined_refs, the "generic free function instantiated
        # only by another module" class). A module is compiled ALONE, so a
        # generic it declares has no concrete signature there and is never
        # emitted; a caller in another module that cannot elaborate the call
        # references the text-scan ERASED signature instead, which nothing
        # defined — so the dylib left it lazy and clients silently fell back
        # to source. `_generic_instance_requests` reads the caller objects'
        # references and recompiles each DEFINING module once with the
        # requested instances appended, so its own codegen emits them under
        # the caller's exact symbols. A defining module whose second compile
        # fails keeps its first-pass object: the reference stays lazy (the
        # documented contract) instead of the module being skipped, and the
        # reason is printed by name on stderr.
        #
        # BEFORE the collision dedup below, because the dedup is what turns
        # `results` into the link line; a replaced object after it would never
        # be linked.
        instance_jobs = _generic_instance_requests(modules, results)
        if instance_jobs:
            _idx_by_path = {}
            for _i in range(len(results)):
                _row = results[_i]
                _idx_by_path[_row[0]] = _i
            for _ipath in sorted(instance_jobs):
                _inst = instance_jobs[_ipath]
                _ires = _compile_module_job(
                    _ipath, workdir, use_cache, objflags, known_structs,
                    dep_fps[_ipath], _inst)
                if _ires[4] is not None:
                    print("  instances for %s: not emitted (%s)"
                          % (os.path.basename(_ipath), _ires[4]), file=sys.stderr)
                    continue
                results[_idx_by_path[_ipath]] = _ires

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
                    # routine (not an error): the dedup log, not the screen
                    with open(os.environ.get('MOJO_DEDUP_LOG') or os.path.join(workdir, 'dedup.log'), 'a') as _dl:
                        _dl.write(f"localize {len(clash)} dup symbol(s) in {name} (e.g. {sorted(clash)[0]})\n")
                else:
                    one = sorted(clash)[0]
                    with open(os.environ.get('MOJO_DEDUP_LOG') or os.path.join(workdir, 'dedup.log'), 'a') as _dl:
                        _dl.write(f"exclude {name} from dylib: symbol already defined ({one})\n")
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
            all_defs |= _defined_symbols(gcc, o, include_weak=True)
        # One shared classifier for the three-way kept/misresolved/undefined
        # split (see classify_export_entries): an entry whose body exists under
        # a differently-hashed overload suffix is misresolved — and the report
        # names the definition — not "declared with no definition".
        _kept, _misresolved, _undefined = classify_export_entries(all_exports, all_defs)
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
        # check, the link and the publish. The CAS is consulted INSIDE the lock
        # and not before it: a check-then-act on a shared filesystem is the
        # stampede, and `out` is the most-shared path in the tree (every parallel
        # `fire.py build` in the gate wants this one library). Everything above
        # the lock — the per-module compiles, all individually content-addressed —
        # still runs in parallel across callers, so the serialised section is only
        # the table compile and the link.
        #
        # Correctness does NOT rest on that lock; `_OutputLock`'s own docstring
        # gives the measurement (a compiled `fcntl.flock` is the extern preamble's
        # weak stub), and the guarantee is the staged link plus `os.replace` below,
        # which hold whether or not the lock did anything.
        #
        # `as _lock_fd` is not decoration: it is what makes the compiled path emit
        # the `__exit__` call at all (see `_OutputLock`'s own note, and
        # the doc for that, deleted with its fix).
        with _OutputLock(out) as _lock_fd:
            if use_cache:
                # Re-checked under the lock: a caller that queued behind another
                # one's fresh link finds the artifact published and returns,
                # which is what turns N racing builds into one build.
                cached_dylib = cas.lookup(link_key, '.dylib')
                if cached_dylib:
                    cas.stats['hits'] += 1
                    _publish_bytes(cached_dylib, out)
                    _arch_or_die(out, arch, 'cached dylib')
                    if stamp_key:
                        _write_stamp(out, stamp_key)
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
            # `_OutputLock` names. `_dylink` is given the final install name
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
            if stamp_key:
                _write_stamp(out, stamp_key)
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
    # Everything below happens inside a staging DIRECTORY that is removed on the
    # way out, whether the build succeeded or raised. Only the finished dylib
    # leaves (`os.replace(staged, out)`), and without `_staging_dir` the eight
    # runtime objects, the reflection table's generated C and its object, and
    # the linked dylib itself sit in `$TMPDIR` for the life of the machine —
    # ~520 kB per COLD build, which per-test CAS homes make routine. The
    # `ignore_errors=True` is deliberate: the failure that matters is the
    # build's, and a stale directory is worth less than a cleanup error masking
    # it. `formal/build.py::_publish_signed_image` is the same shape.
    # The work directory holds the runtime objects, the generated reflection C
    # and its object, and the staged dylib — and `os.replace` below moves only
    # the dylib out, so nothing else removes `wd` unless this does. It is per
    # COLD CAS (a cache hit returned above), and this tree has many callers with
    # a fresh `GMOJO_HOME` per test, so the leak measured ~500 kB per cold build
    # (34 leaked dirs, ~17 MB, in twelve minutes of one corpus run).
    # `_staging_dir` is the model `formal/build.py::_publish_signed_image` uses:
    # stage, publish, and remove the staging DIRECTORY so a killed build leaves
    # no debris for a later glob to mistake for a library.
    with _StagingDir('mojo_rt_') as wd:
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
        # -fno-builtin: the table redeclares every advertised symbol unprototyped
        # to take its address, and some of those names are C builtins.
        objs.append(_compile_reflect_table(cc, arch, wd, entries))
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


def _compile_reflect_table(cc: str, arch: str, wd: str, entries: list) -> str:
    """Emit and compile a `__mojo_reflect` table for `entries`; return the .o path."""
    reflect_src = reflect.emit_table_c(entries)
    rc = os.path.join(wd, '_mojo_reflect.c')
    ro = os.path.join(wd, '_mojo_reflect.o')
    with open(rc, 'w') as f:
        f.write(reflect_src)
    subprocess.run([cc, '-fno-builtin', '-fPIC', f'-I{HERE}', *arch_flags(arch),
                    '-c', '-o', ro, rc], check=True)
    return ro


def optional_runtime_dylib(unit: str, arch: str = None) -> str:
    """Build (or find in the CAS) an optional runtime unit as a loadable Mach-O dylib.

    The unit is compiled from `build_config.optional_unit_source(unit)` for `arch`
    with `optional_unit_cc(unit)` / `optional_unit_cc_flags(unit)`, defaulting to
    the same compiler/flags `runtime_units` uses for a plain C unit. It links with
    `optional_unit_libs(unit)` (e.g. `-lsqlite3`) and carries a `__mojo_reflect`
    table filtered to the unit's own namespace. CAS-cached by unit, arch, source,
    flags and libs. A missing unit, missing dev library, or missing toolchain is a
    clear error, never a silent skip.
    """
    arch = normalize_arch(arch)
    if unit not in build_config.optional_unit_names():
        raise RuntimeError(
            f"unknown optional runtime unit {unit!r}; known: "
            f"{build_config.optional_unit_names()}")
    cc_default, cxx = toolchain_for(arch, find_gcc(), find_gxx())
    unit_cc = build_config.optional_unit_cc(unit)
    cc = unit_cc if unit_cc else cc_default
    src = build_config.optional_unit_source(unit)
    hdr = build_config.optional_unit_header(unit)
    unit_flags = tuple(build_config.optional_unit_cc_flags(unit))
    unit_libs = tuple(build_config.optional_unit_libs(unit))
    namespace = build_config.optional_unit_namespace(unit)

    if not os.path.isfile(src):
        raise RuntimeError(
            f"optional runtime unit {unit!r} source not found: {src}")
    if not os.path.isfile(hdr):
        raise RuntimeError(
            f"optional runtime unit {unit!r} header not found: {hdr}")

    # Effective compile flags: default like `runtime_units` uses for a C unit.
    if src.endswith(('.cpp', '.cc', '.cxx')):
        eff_cc = cxx
        eff_lang_flags = list(_UNIT_FLAGS.get('c++', ()))
    elif src.endswith('.m'):
        eff_cc = cc
        eff_lang_flags = list(_UNIT_FLAGS.get(_C_UNIT, ('-fPIC',)))
    else:
        eff_cc = cc
        eff_lang_flags = list(_UNIT_FLAGS.get(_C_UNIT, ('-fPIC',)))
    eff_opt = [_RUNTIME_DEFAULT_OPT] + list(unit_flags)
    eff_compile_flags = tuple(eff_lang_flags + eff_opt)

    digest = cas._hash(
        'mojo-optrtdylib-v2', cas.ABI_VERSION, cas.compiler_fingerprint(),
        cas.toolchain_fingerprint(eff_cc, arch_flags(arch) + eff_compile_flags + unit_libs),
        arch, unit, os.path.basename(src), open(src).read(),
        *eff_compile_flags, *unit_libs)
    name = f'libmojo{unit}.{arch}.{digest}.dylib'
    out = cas.path_for(f'oprtdylib/libmojo{unit}.{arch}.{digest}', '.dylib')
    if os.path.exists(out):
        _arch_or_die(out, arch, 'cached optional runtime dylib')
        return out
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with _StagingDir('mojo_optrt_') as wd:
        objs = []
        stem = os.path.splitext(os.path.basename(src))[0]
        o = os.path.join(wd, stem + '.o')
        compile_cmd = ([eff_cc] + list(eff_lang_flags) + [f'-I{RUNTIME}'] +
                       list(arch_flags(arch)) + list(eff_opt) +
                       ['-c', '-o', o, src])
        try:
            subprocess.run(compile_cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            msg = (e.stderr or e.stdout or '').strip()
            raise RuntimeError(
                f"optional runtime unit {unit!r} compile failed ({src}): {msg}") from e
        _arch_or_die(o, arch, f'object for {os.path.basename(src)}')
        objs.append(o)

        # Reflect table: this unit's header, filtered to its namespace and to
        # symbols the objects actually define.
        entries = []
        seen = set()
        try:
            for e in reflect.collect_runtime_exports_h(hdr):
                if namespace and not e['name'].startswith(namespace):
                    continue
                if e['name'] in seen:
                    continue
                seen.add(e['name'])
                entries.append(e)
        except Exception:
            entries = []
        defined = set()
        for obj in objs:
            defined |= _defined_symbols(cc, obj, include_weak=True)
        kept, misresolved, undefined = classify_export_entries(entries, defined)
        report = format_export_report(len(entries), misresolved, undefined)
        for line in report:
            print(f"  optional runtime {unit}: {line}", file=sys.stderr)
        objs.append(_compile_reflect_table(cc, arch, wd, kept))

        staged = os.path.join(wd, name)
        # Link against core runtime to resolve symbols the unit may call.
        try:
            core = runtime_dylib(arch=arch)
        except Exception:
            core = None
        link_cmd = _dylink(cc, staged, objs, undefined=False if core else True,
                           link_driver=cc, install_name='@rpath/' + name, arch=arch)
        link_cmd = link_cmd + list(unit_libs)
        if core:
            link_cmd = link_cmd + [core]
        try:
            subprocess.run(link_cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            msg = (e.stderr or e.stdout or '').strip()
            dev = build_config.optional_unit_dev_package(unit)
            hint = f" (install {dev})" if dev else ""
            raise RuntimeError(
                f"optional runtime unit {unit!r} link failed{hint}: {msg}") from e
        _arch_or_die(staged, arch, 'linked optional runtime dylib')
        os.replace(staged, out)
        try:
            import formal.build as _FB
            if not os.path.exists(_FB.dylib_manifest_path(out)):
                _FB.runtime_manifest(out)
        except Exception:
            pass
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
        currently-live defect measured on this tree: of `fire_runtime.h`'s 892
        entry points, only a handful survive `build_stdlib()`'s `nm`
        cross-check, and the rest are dropped for exactly this reason. So the
        stdlib dylib has never advertised most of the runtime entry points it
        defines — including all of `mojo_str_*` and every function whose
        parameters are not word-shaped. The figure is deliberately NOT written
        down here: `format_export_report` prints the kept / misresolved /
        undefined split on every build, so the number to read is the one the
        build reports and this paragraph cannot go stale against it. (It did,
        once: it said "only 26 of 459" for months after both counts had
        moved.) The fix belongs in `reflect.export_csym` (agent [3]'s file;
        see the INTERFACE REQUEST), and nothing here has to change when it
        lands: an entry that resolves correctly passes this same check and is
        advertised.
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
        defined |= _defined_symbols(gcc, o, include_weak=True)
    kept, misresolved, undefined = classify_export_entries(exports, defined)
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


# A Mojo overload suffix: `overload_suffix_for` (mojo/backend_gimple/emit_funcs)
# emits `_` + 6 hex digits (a 24-bit polynomial hash over the joined C
# param-type list), or nothing at all for a zero/variadic param list. The
# cross-check below must recognise that tail to tell a SUFFIX disagreement
# (the body exists, hashed a different way) from a genuinely missing body.
_OVERLOAD_SUFFIX_RE = re.compile(r'_[0-9a-f]{6}$')


def classify_export_entries(entries: list, defined: set) -> tuple:
    """Split export entries into (kept, misresolved, undefined) against
    `defined`, the arch-prefixed C symbols the object set really defines (as
    `_defined_symbols` returns them).

    This is the ONE three-way check behind the export table's `nm` cross-check.
    It used to be copy-pasted three times (build()'s all_exports,
    runtime_export_entries' header exports, and the optional-unit builds), and
    the copies had already drifted from the truth in the way that matters:

    * kept — the entry's expected symbol is defined: the table can name it.
    * misresolved — the dylib defines the function, but under a DIFFERENT symbol
      than the entry computed. Two shapes, both "defined but not advertised":
      (a) the RAW name is defined but the entry's mangling rule resolved to a
      different spelling, and (b) the SAME name is defined with a DIFFERENT
      overload suffix — the entry's source-scan param types hash to a different
      24-bit suffix than codegen's live-inferred ones (the `ord`/`ascii`/
      `atol`/`standardize_string_slice` case: the body exists as
      `..._ord_d719e0` while the entry names `..._ord_9f63a2`). For shape (b)
      the report NAMES the definition that exists, because a bare "declared
      with no definition" sends the next reader hunting for a missing body
      that is in fact present.
    * undefined — no definition under any spelling: genuinely absent from the
      dylib (a header declaration satisfied by whoever links against it, e.g.
      `py_tokenize`, which the self-hosted compiler image defines, not the
      runtime).

    A suffix sibling is only accepted when the EXPECTED symbol itself carries a
    suffix: a C-prototype entry (whose `csym` is the raw header name) has none,
    and matching one against a coincidental `_deadbeef` tail would invent a
    definition that is not there. SYM_TYPE entries are layout descriptors with
    no runtime symbol, so they are always kept (the table stores a NULL for
    them and never forward-declares them — see reflect.emit_table_c)."""
    kept, misresolved, undefined = [], [], []
    # defined-symbol -> its stem (everything before the overload suffix), so a
    # miss on the exact symbol can be re-checked against the same function's
    # other overload hashes in O(1) instead of scanning `defined` per entry.
    suffix_by_stem = {}
    for d in defined:
        m = _OVERLOAD_SUFFIX_RE.search(d)
        if m:
            suffix_by_stem.setdefault(d[:m.start()], set()).add(d)
    for e in entries:
        if e['kind'] == reflect.SYM_TYPE:
            kept.append(e)
            continue
        sym = reflect.export_csym(e)
        expect = '_' + sym
        if expect in defined:
            kept.append(e)
            continue
        m = _OVERLOAD_SUFFIX_RE.search(expect)
        if m:
            siblings = sorted(d for d in suffix_by_stem.get(expect[:m.start()], ())
                              if d != expect)
            if siblings:
                # `sym` is spelled without the arch's leading underscore;
                # `defined` carries it — strip it so both halves of the line
                # read as the same kind of name.
                spelled = [s[1:] if s.startswith('_') else s for s in siblings]
                # Pre-joined, not nested inside the f-string: this module
                # compiles into mojoc, and the self-hosted backend's f-string
                # lowering does not take nested same-quote f-expression parts.
                joined = ', '.join(spelled)
                misresolved.append(f"{e['name']} -> {sym} (defined as {joined})")
                continue
        if ('_' + e['name']) in defined:
            misresolved.append(f"{e['name']} -> {sym}")
        else:
            undefined.append(e['name'])
    return kept, misresolved, undefined


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


def _runtime_header_entries() -> list:
    """Every entry point the runtime headers advertise, one per name."""
    rt_exports = []
    seen = set()
    for hdr in _RUNTIME_HEADERS:
        for e in reflect.collect_runtime_exports_h(os.path.join(RUNTIME, hdr)):
            if e['name'] not in seen:
                seen.add(e['name'])
                rt_exports.append(e)
    return rt_exports


def _runtime_tree_digest() -> str:
    """Content digest of every file under `runtime/`.

    `cas.compiler_fingerprint()` folds in `fire_runtime.c`/`.h` and the two
    Metal files, but `build()` also compiles `runtime_units()` (the coroutine
    and async units, `fire_re_engine.inc`, ...) and reads the optional-unit
    headers. A currency key that trusted only the fingerprint would serve a
    dylib after one of those changed, so the whole directory is hashed. It is
    1.3 MB, ~0.02 s."""
    parts = ['mojo-runtime-tree-v1']
    for dirpath, dirnames, filenames in os.walk(RUNTIME):
        dirnames.sort()
        for name in sorted(filenames):
            p = os.path.join(dirpath, name)
            rel = os.path.relpath(p, RUNTIME).replace(os.sep, '/')
            try:
                parts.append(rel + '\x1f' + cas.file_digest(p))
            except OSError:
                parts.append(rel + '\x1f' + 'unreadable')
    return cas._hash(*parts)


def stdlib_dylib_currency_key(arch: str) -> str:
    """The digest of every input the stdlib dylib's bytes are derived from.

    Everything `build()` reads is represented here: the compiler sources and
    the runtime files (`compiler_fingerprint`), the whole `runtime/` tree, the
    stdlib sources (`stdlib_fingerprint`), the toolchain and object flags, the
    target architecture, and the header entries the link key folds in. The
    whole point is that this is CHEAP compared with `build()`: it hashes
    sources, while `build()` computes 664 module keys and runs `nm` over every
    object, which is what made a `fire.py build` of a three-line program take
    the same time as a stdlib build (and made `silentnoop`'s first case
    exhaust its 300 s budget)."""
    gcc = find_gcc()
    objflags = _OBJ_FLAGS + arch_flags(arch)
    # The link key folds `extra_exports` in, so the currency key must too. A
    # plain loop rather than a nested comprehension: this file is in `mojoc`'s
    # own compile closure (`cas.selfhost_inputs()`).
    export_rows = []
    for e in _runtime_header_entries():
        pairs = []
        for k in sorted(e.keys()):
            pairs.append(k + '=' + str(e[k]))
        export_rows.append('\x1e'.join(pairs))
    exports = '\x1d'.join(sorted(export_rows))
    return cas._hash(
        'mojo-stdlib-dylib-current-v1', cas.ABI_VERSION,
        cas.compiler_fingerprint(), cas.stdlib_fingerprint(),
        _runtime_tree_digest(), cas.toolchain_fingerprint(gcc, objflags),
        normalize_arch(arch), exports)


def _stamp_path(out: str) -> str:
    return out + '.current'


def _stamp_is_current(out: str, key: str) -> bool:
    """Whether `out` is the artifact `key` names, by its own bytes.

    The digest half is not decoration: the stamp and the dylib are two files,
    and a concurrent build from a different key can replace one between the
    two reads. A mismatch rebuilds, which is always safe."""
    try:
        with open(_stamp_path(out)) as f:
            lines = f.read().split()
    except OSError:
        return False
    if len(lines) != 2 or lines[0] != key:
        return False
    try:
        return lines[1] == cas.file_digest(out)
    except OSError:
        return False


def _write_stamp(out: str, key: str) -> None:
    """Record `key` and the artifact's digest beside `out`, atomically.

    Callers hold `_OutputLock(out)`: the stamp describes the bytes at `out`,
    so writing it outside the install lock could pair one build's key with a
    racing build's artifact."""
    row = key + '\n' + cas.file_digest(out) + '\n'
    p = _stamp_path(out)
    tmp = p + '.tmp.%d' % os.getpid()
    with open(tmp, 'w') as f:
        f.write(row)
    os.replace(tmp, p)


def stdlib_dylib(out: str = None, arch: str = None, jobs: int = 1) -> str:
    """The stdlib dylib `fire.py build` LINKS AGAINST, built on first use.

    This is `build_stdlib()` plus a currency stamp, and the difference is
    measured rather than cosmetic. `driver.compile_program` asks for this
    library on EVERY build, and `build_stdlib()` answers by re-deriving all
    664 module keys and running `nm` on every object even when every one of
    them is a CAS hit — ~3 minutes on a loaded gate box for a program that
    itself compiles in a second. That cost is invisible when a checkout has a
    warm artifact, which is why it went unnoticed: the job that DID notice,
    `silentnoop`, builds 26 programs with a 300 s budget each, and in a fresh
    tree (the integrator's `masterred_` snapshot) the first one was charged
    for the whole stdlib and timed out.

    The stamp names the inputs (`stdlib_dylib_currency_key`) and the
    artifact's own digest. A matching stamp means the artifact at `out` is
    already the one those inputs produce, so there is nothing to derive. Any
    input change, a missing stamp, or an artifact whose bytes disagree sends
    it through `build_stdlib()`.  `tools/stdlib_dylib_ratchet.py` calls
    `build_stdlib()` and not this function, so the `skip <module>:` lines it
    reads are still produced by a real build every time it runs.

    `out` is defaulted exactly as `build_stdlib()`'s is, per arch."""
    arch = normalize_arch(arch)
    if out is None:
        out = os.path.join(HERE, 'build', f'libmojostdlib.{arch}.dylib')
    key = stdlib_dylib_currency_key(arch)
    if _stamp_is_current(out, key):
        return out
    built = build_stdlib(out=out, use_cache=True, jobs=jobs, arch=arch,
                          stamp_key=key)
    return built


def build_stdlib(out: str = DEFAULT_OUT, use_cache: bool = True, jobs: int = 1,
                 arch: str = None, stamp_key: str = None) -> str:
    """Build the monolithic stdlib dylib from all auto-discovered library modules.

    `arch` names the architecture the dylib is for; the default output NAME
    gains it as well, because `build/libmojostdlib.dylib` is a fixed path and
    two architectures writing to it would make the second build's success
    depend on which ran last. The name is only defaulted when the caller did
    not ask for a specific `out`.

    `stamp_key` is passed through to `build()` and written beside `out` with
    the artifact's digest inside the install lock; see `stdlib_dylib()`."""
    arch = normalize_arch(arch)
    if out == DEFAULT_OUT:
        out = os.path.join(HERE, 'build', f'libmojostdlib.{arch}.dylib')
    rt_exports = _runtime_header_entries()
    # track_local_deps=False: every module here IS a stdlib module, and the
    # whole stdlib closure is already folded into each one's key via
    # cas.stdlib_fingerprint(). Per-module local-dep tracking would only
    # re-hash that same closure under a new key and force a needless full
    # cold rebuild. It exists for `fire dylib` on a PROJECT's own file set
    # (BUG-2026-032), reached via driver.compile_dylib -> build(...).
    return build(stdlib_modules(), out, use_cache=use_cache, extra_exports=rt_exports,
                 jobs=jobs, track_local_deps=False, arch=arch,
                 stamp_key=stamp_key)


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
