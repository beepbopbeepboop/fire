#!/usr/bin/env python3
"""driver.py — `fire build`/`run`, thin by design (MODULE_CACHE_DESIGN.md).

`import` does the work: as the codegen resolves each import it builds the module's
dylib (CAS), wires its `__mojo_reflect` ABI, and *records the dylib on the link
line*. The driver just:
  * compiles the client in link mode (extern decls), getting back the recorded
    dylib list;
  * links the client against the stdlib dylib (runtime folded in) + any per-import
    dylibs recorded by `import` (the OS loader binds the symbols — we don't
    reinvent dyld);
  * content-addresses the whole program in ~/.gmojo/cas (warm = an instant copy);
  * runs it.

If the link path can't produce a binary we return None so the caller can fall
back to the inline builder — we accept things break, but a program that can build
still does.
"""
import os
import shutil
import platform
import subprocess
import sys

import cas
import build_stdlib_dylib as bsd
import gimple_codegen
from gimple_codegen import compile_linked
from build_config import (find_gcc, find_gxx,
                          optional_unit_compile_failed, optional_unit_libs,
                          optional_unit_source,
                          referenced_optional_runtime_units)

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')
_CPP_FLAGS = ('-std=c++20', '-fPIC', f'-I{RUNTIME}')


def _prog_key(c_code, link_files, gcc, flags, link_driver):
    # Everything that shapes the linked binary is in the key: the client C
    # (which already encodes imported signatures), the toolchain, and the
    # *content* of every dylib/object on the link line.  Hashing contents —
    # not just basenames — means a rebuilt stdlib dylib invalidates cached
    # programs (a fixed name like libmojostdlib.dylib carries no version
    # information).  In production the dylibs never change, so the extra
    # read-and-hash per compile is a cheap price for exactness.
    # `link_driver` (gcc vs g++ — see compile_linked's `needs_cxx`) is
    # folded in too: the SAME c_code/objects linked with a different final
    # driver can plausibly produce a different binary (different libstdc++
    # linkage), so a program that flips between needing/not-needing C++
    # must not collide on a stale cache entry from the other shape.
    return 'prog/' + cas._hash(
        'mojo-prog-v2', cas.ABI_VERSION, cas.compiler_fingerprint(),
        cas.toolchain_fingerprint(gcc, flags), c_code, link_driver,
        '\0'.join(f'{os.path.basename(p)}={cas.file_digest(p)}'
                  for p in sorted(link_files)))


def _build(c_code, stdlib, dylibs, objects, target, gcc, objflags, link_driver,
           extra_libs=()):
    """Compile the client object (cached) and link it against the runtime dylib +
    the import dylibs `import` recorded + the objects elaboration produced
    (generic instantiations, possibly including a C++-compiled coroutine
    unit — see compile_linked's own docstring). Returns True on success.

    `link_driver`: the FINAL link step's driver (gcc or g++ — see
    compile_program's `needs_cxx` handling). Every individual .c/.ci
    compile step (the client itself, fire_runtime.c, ...) is completely
    unaffected — this only changes which driver performs the final link,
    mirroring fire.py's own build_executable's identical `cxx_link` split
    (a real C++ object, e.g. one with coroutine frames/exception tables,
    generally needs a C++-aware final link even though every OTHER object
    on the line is ordinary -fgimple C)."""
    import tempfile
    wd = tempfile.mkdtemp(prefix='mojo_drv_')

    ckey = cas.module_key(c_code, [], gcc, objflags)

    def _client():
        cf, of = os.path.join(wd, 'client.c'), os.path.join(wd, 'client.o')
        open(cf, 'w').write(c_code)
        subprocess.run([gcc, *objflags, '-c', '-o', of, cf], check=True,
                       capture_output=True)
        return open(of, 'rb').read()

    client_o = cas.get_or_build(ckey, '.o', _client)[0]

    link_dylibs = list(dict.fromkeys([stdlib] + list(dylibs)))
    rpaths = sorted({os.path.dirname(d) for d in link_dylibs})

    link = [link_driver, '-o', target, client_o] + list(objects) + link_dylibs
    link += list(extra_libs)
    for rp in rpaths:
        link += [f'-Wl,-rpath,{rp}']
    if platform.system() == 'Darwin':
        # 512MB main-thread stack (default is 8MB). The self-hosted compiler's
        # own regex engine (re_match_node/re_match_repeat) and its generic AST
        # walkers are deeply CPS-recursive — a `re.sub`/`findall` over a
        # 200KB module source, or a walk of a big AST, recurses per input
        # position and blows the 8MB stack. Enlarging it is the pragmatic fix
        # until those are made iterative.
        link += ['-Wl,-stack_size,0x20000000']
    else:
        link += ['-ldl', '-Wl,-z,stacksize=536870912']

    r = subprocess.run(link, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"link failed: {r.stderr}", flush=True)
        return False
    os.chmod(target, 0o755)
    return True


def _build_client_cpp_object(cpp_code: str, gcc: str, objflags) -> bytes:
    """Compile this module's OWN top-level companion .cpp (a real Mojo
    `async def`/generator directly in the client module, as opposed to one
    reached only via an elaborated generic — see compile_linked's own
    docstring for how the two differ) to a CAS-cached object with g++.
    Mirrors monomorphize.instantiate's identical per-instantiation cpp
    build, and fire.py's build_executable's own "Milestone B" companion-
    .cpp compile step for its separate (non-link-mode) pipeline — same
    idea, applied here to link-mode's own client-level .cpp instead of an
    elaborated fragment's."""
    gxx = find_gxx()
    key = cas.module_key(cpp_code, [], gxx, _CPP_FLAGS)

    def _build_fn():
        import tempfile
        wd = tempfile.mkdtemp(prefix='mojo_drv_cpp_')
        cf = os.path.join(wd, 'client_async.cpp')
        of = os.path.join(wd, 'client_async.o')
        open(cf, 'w').write(cpp_code)
        subprocess.run([gxx, *_CPP_FLAGS, '-c', '-o', of, cf], check=True,
                       capture_output=True)
        return open(of, 'rb').read()

    return cas.get_or_build(key, '.o', _build_fn)[0]


class _OptionalUnitFailed(Exception):
    """Internal: an optional runtime unit's own compile failed. Carries the
    diagnostic to print. Not raised out of compile_program -- it is caught and
    turned into the same `return None` every other build failure here uses."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _compile_optional_unit(unit, src, plain, gcc):
    """CAS-cached object for one optional runtime unit, or None with the
    diagnostic already printed if it does not compile.

    Split out of compile_program so the failure is a `return None` sitting
    next to its reason, rather than a bare CalledProcessError from three
    frames down inside a CAS callback -- that is what this path used to raise,
    on the path `fire.py build` normally takes, and its argv named a temp .o
    rather than the unit that failed.

    The build callback RAISES rather than returning None: cas.get_or_build
    publishes whatever build_fn returns, so a None here would enter the CAS as
    a zero-length artifact and every later build would "hit" it.
    """
    # The per-unit compiler and flags go into the key as well as the command:
    # the Metal unit is Objective-C and needs clang + ARC, so keying it on the
    # build-wide gcc alone would let a gcc-built .o satisfy a later
    # clang-built request (or vice versa) across two checkouts sharing a cas.
    cc = optional_unit_cc(unit) or gcc
    ccf = tuple(optional_unit_cc_flags(unit))
    key = cas.module_key(open(src).read(), [], gcc, plain + (unit, cc) + ccf)

    def _build_fn():
        import tempfile as _tf
        wd = _tf.mkdtemp(prefix='mojo_optrt_')
        obj = os.path.join(wd, 'x.o')
        r = subprocess.run([cc, *plain, *ccf, '-c', '-o', obj, src],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise _OptionalUnitFailed(
                optional_unit_compile_failed(unit, src, r.stderr))
        return open(obj, 'rb').read()

    try:
        return cas.get_or_build(key, '.o', _build_fn)[0]
    except _OptionalUnitFailed as e:
        print(e.message, file=sys.stderr)
        return None


def compile_program(input_file, src, output=None, run=True,
                    opt_flag=None, debug_flag=None, program_args=None,
                    auto_gpu=True):
    """Compile (and optionally run) a Mojo program through the module-cache system.
    Returns the program's exit code when run / 0 on a successful build, or None if
    the build failed (caller decides the fallback)."""
    gcc = find_gcc()
    flags = (opt_flag or '-O0', debug_flag or '-g3')
    objflags = ('-fgimple', '-fPIC', f'-I{RUNTIME}') + flags

    # `import` resolves dylibs and elaboration produces instantiation objects,
    # both recorded as a side effect of compiling. `cpp_code`/`needs_cxx`:
    # see compile_linked's own docstring — a real coroutine translation
    # unit either directly in this module or inside an elaborated generic
    # it calls.
    c_code, dylibs, objects, cpp_code, needs_cxx = compile_linked(
        src, filename=input_file, auto_gpu=auto_gpu)
    objects = list(objects)
    if cpp_code:
        objects.append(_build_client_cpp_object(cpp_code, gcc, objflags))

    # A3 stack-switch coroutine runtime (doc/COROUTINE.html): CAS-build and
    # link the small Layer 1 shim + Layer 2 + arch Layer 3 whenever the
    # generated client .c references them (gimple_gen_coro lowered a
    # generator this way). Plain C / asm — NOT -fgimple.
    if ('__mgco_' in c_code or '__mojo_coro_yield_i' in c_code
            or '__mojo_future_' in c_code or '__mojo_event_' in c_code):
        _plain = ('-fPIC', f'-I{RUNTIME}') + flags
        _arch = ('fire_coro_ctx_aarch64.S'
                 if platform.machine().lower() in ('arm64', 'aarch64')
                 else 'fire_coro_ctx_generic.c')
        for _cs in ('fire_coro_gen.c', 'fire_coro.c', 'fire_async_sched.c', _arch):
            _p = os.path.join(RUNTIME, _cs)
            _key = cas.module_key(open(_p).read(), [], gcc, _plain + (_cs,))

            def _mk(_p=_p):
                import tempfile as _tf
                _d = _tf.mkdtemp(prefix='mojo_coro_')
                _o = os.path.join(_d, 'x.o')
                subprocess.run([gcc, *_plain, '-c', '-o', _o, _p], check=True,
                               capture_output=True)
                return open(_o, 'rb').read()

            objects.append(cas.get_or_build(_key, '.o', _mk)[0])

    # Optional runtime units (build_config's registry -- see
    # build_config.py's own header, where the bug is described). runtime/
    # holds six C
    # units and only fire_runtime.c was in a build path, while the headers of
    # the other four are `#include`d into EVERY generated TU (module_gen.py's
    # preamble) and all their signatures sit in gimple_codegen._KNOWN_SIGS --
    # so a program calling mojo_sqlite3_open saw a prototype, compiled clean,
    # and died at link with `Undefined symbols ... _mojo_sqlite3_open`. Same
    # probe as the coroutine block just above (the generated client .c
    # references this unit's namespace?) and for the same reason: a program
    # that never mentions sqlite must not drag libsqlite3 onto its link line.
    # Plain C, NOT -fgimple, exactly like the coroutine units above.
    extra_libs = []
    _plain = ('-fPIC', f'-I{RUNTIME}') + flags
    for _unit in referenced_optional_runtime_units(c_code, RUNTIME):
        _up = optional_unit_source(_unit, RUNTIME)
        _ukey = cas.module_key(open(_up).read(), [], gcc, _plain + (_unit,))
        # A unit that does not compile is a hard error, not a link failure, so
        # this does NOT go through the `check=True` path: that raises a bare
        # CalledProcessError whose argv points at a temp .o and says nothing
        # about which unit failed or which system headers are missing -- and
        # this is the path `fire.py build` normally takes. Returns None instead
        # so fire.py falls back to build_executable, which prints the same
        # diagnostic; see build_config.optional_unit_compile_failed.
        _obj = _compile_optional_unit(_unit, _up, _plain, gcc)

        if _obj is None:
            return None
        objects.append(_obj)
        extra_libs += optional_unit_libs(_unit)
    # The stdlib dylib already has runtime/mojo_async_runtime.cpp's own
    # symbols folded in unconditionally (build_stdlib_dylib.py's own
    # production-dylib link step) — a downstream client needing async
    # support does NOT need to separately recompile/relink that file, only
    # (a) its OWN coroutine unit object(s), just added above/by elaboration,
    # and (b) a C++-aware final link driver so THOSE objects' own C++
    # runtime dependencies (operator new/delete, exception tables,
    # coroutine frame helpers) resolve — confirmed via a direct hand-
    # verified repro (g++ final link + client's own coroutine .o, linked
    # only against the existing stdlib dylib, no separately-recompiled
    # mojo_async_runtime.o, ran correctly).
    link_driver = find_gxx() if needs_cxx else gcc
    target = os.path.abspath(output or os.path.splitext(os.path.basename(input_file))[0])

    # Stdlib dylib: monolithic, CAS-built on first use; runtime folded in, so
    # programs need only one dylib on the link line.  Resolved *before* the
    # cache key so its content participates in invalidation.
    stdlib = bsd.build_stdlib()

    # Warm path: the whole program is content-addressed — a cache hit is a copy.
    link_files = list(dict.fromkeys([stdlib] + list(dylibs))) + list(objects)
    pkey = _prog_key(c_code, link_files, gcc, objflags, link_driver)
    hit = cas.lookup(pkey, '')
    if hit:
        shutil.copy(hit, target)
        os.chmod(target, 0o755)
    else:
        if not _build(c_code, stdlib, dylibs, objects, target, gcc, objflags,
                      link_driver, extra_libs):
            return None
        cas.publish(pkey, '', open(target, 'rb').read())

    if run:
        return subprocess.run([target] + list(program_args or [])).returncode
    print(f"Built: {target}")
    return 0


def _expand_dylib_modules(input_files):
    """A dylib's whole point is to expose its FULL api — unlike an executable,
    which only needs whatever its own call graph reaches, so per-module
    compilation (deliberately, elsewhere) never treats "imported but never
    called" as a reason to compile+export a definition. `from engine_world
    import *` into a pure re-export wrapper file, with nothing in the wrapper
    itself calling any of those names, compiled to a dylib with ZERO engine
    symbols — every name IS defined somewhere, just not reachable from a
    wrapper file with no call sites of its own to force it in.

    Since `bsd.build()` already treats every module explicitly PASSED to it
    as unconditionally exporting its own full top-level API (that's exactly
    how the real 664-file stdlib dylib works — no module in that list is
    "unused"), the fix is to make `fire dylib` walk each input file's own
    `from X import ...` statements (any form, not just `*` — a normal named
    import of a name nothing else calls has the identical problem) and add
    every LOCAL (non-stdlib) module it names to the build list too, so their
    own top-level defs get the same unconditional-export treatment as if
    the caller had listed them explicitly. Recurses (bounded) since a
    pulled-in module may itself only re-export a further sibling. Stdlib
    imports (`from std... import ...` et al) are deliberately left alone —
    those are either already reachable through real call sites (the common
    case) or are part of the separately-built, already-complete real stdlib
    dylib; auto-expanding into that huge tree here would be wasteful and
    risks re-exporting symbols that collide with it."""
    import fire_compiler as mc
    import imports as _imp
    gen = gimple_codegen.GimpleGen(emit_entry_points=False)
    seen = set()
    modules = []
    queue = [os.path.abspath(f) for f in input_files]
    while queue:
        path = queue.pop(0)
        if path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        modules.append(path)
        try:
            stmts = mc.Parser(mc.py_tokenize(open(path).read())).parse_module()
        except Exception:
            continue
        gen._current_filename = path
        for s in stmts:
            if not isinstance(s, mc.FromImportStmt) or s.module.startswith('std'):
                continue
            resolved = _imp.resolve_source(s.module) or gen._resolve_test_relative_module(s.module)
            if resolved:
                resolved = os.path.abspath(resolved)
                if resolved not in seen:
                    queue.append(resolved)
    return modules


def compile_dylib(input_files, output=None, jobs=1, opt_flag=None):
    """Compile one or more Mojo LIBRARY modules (no `main()`/top-level
    entry point required — same "library module" shape build_stdlib_dylib.py
    already compiles every stdlib file as) into a single, standalone,
    self-contained shared library (.dylib on macOS, .so elsewhere), callable
    directly from C/C++ via its plain C ABI (module-qualified symbol names,
    e.g. `world.mojo`'s `def create_world():` exports as C symbol
    `world_create_world`).

    This is exactly `build_stdlib_dylib.build()` — already a fully general
    "compile this LIST of .mojo modules into one dylib" function, with no
    stdlib-tree-specific assumptions (confirmed: `_module_name_for`/
    `_compile_module_job` derive the module name from the file's own path,
    same as compiling any other module) — just exposed as a first-class
    driver entry point instead of only being reachable by hand-importing
    build_stdlib_dylib.py. `link_runtime=False` (the same "production" mode
    the real stdlib dylib itself uses): fire_runtime.c/mojo_async_runtime.cpp
    are compiled and folded directly into the output dylib, so the result
    is fully self-contained — a C/C++ host links or dlopen()s ONE file, with
    no separate mojo runtime dylib to also manage.

    `input_files`: a single path or a list of paths — every module's own
    exported symbols land in the same output dylib (mirrors `fire dylib
    a.mojo b.mojo -o combined.dylib` bundling multiple library modules
    together, the same way `build_stdlib_dylib.py`'s own CLI already
    accepts multiple module args). Each input file's own `from X import ...`
    statements (local/sibling modules only) are auto-expanded into the
    build list too — see `_expand_dylib_modules` — so a module that's only
    referenced via a re-export ("import everything from X, ship it") still
    gets its full API compiled in and exported, not silently dropped for
    having no local call site.

    `opt_flag` defaults to '-O2': unlike the internal stdlib dylib (compiled
    once, at -O0, optimized for build time and CAS cache-friendliness — see
    build_stdlib_dylib.build()'s own docstring), a `fire dylib` artifact is
    meant to be linked into a real program and actually run — fire.py's CLI
    passes through an explicit -O0/-O1/-O3/-Os/-Oz/-Og if the caller gave
    one (via the same `_extract_codegen_flags` every other subcommand uses),
    so this default only applies when nothing was specified."""
    if isinstance(input_files, str):
        input_files = [input_files]
    ext = 'dylib' if platform.system() == 'Darwin' else 'so'
    if output is None:
        base = os.path.splitext(os.path.basename(input_files[0]))[0]
        output = f'{base}.{ext}'
    target = os.path.abspath(output)
    all_modules = _expand_dylib_modules(input_files)
    out = bsd.build(all_modules, target,
                    use_cache=True, link_runtime=False, jobs=jobs,
                    opt_flag=opt_flag or '-O2')
    print(f"Built: {out}")
    return 0
