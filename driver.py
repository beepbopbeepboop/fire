#!/usr/bin/env python3
"""driver.py — `mojo build`/`run`, thin by design (MODULE_CACHE_DESIGN.md).

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

import cas
import build_stdlib_dylib as bsd
import gimple_codegen
from gimple_codegen import compile_linked
from build_config import find_gcc, find_gxx

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


def _build(c_code, stdlib, dylibs, objects, target, gcc, objflags, link_driver):
    """Compile the client object (cached) and link it against the runtime dylib +
    the import dylibs `import` recorded + the objects elaboration produced
    (generic instantiations, possibly including a C++-compiled coroutine
    unit — see compile_linked's own docstring). Returns True on success.

    `link_driver`: the FINAL link step's driver (gcc or g++ — see
    compile_program's `needs_cxx` handling). Every individual .c/.ci
    compile step (the client itself, mojo_runtime.c, ...) is completely
    unaffected — this only changes which driver performs the final link,
    mirroring mojo.py's own build_executable's identical `cxx_link` split
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
    for rp in rpaths:
        link += [f'-Wl,-rpath,{rp}']
    if platform.system() != 'Darwin':
        link += ['-ldl']

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
    build, and mojo.py's build_executable's own "Milestone B" companion-
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


def compile_program(input_file, src, output=None, run=True,
                    opt_flag=None, debug_flag=None, program_args=None):
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
    c_code, dylibs, objects, cpp_code, needs_cxx = compile_linked(src, filename=input_file)
    objects = list(objects)
    if cpp_code:
        objects.append(_build_client_cpp_object(cpp_code, gcc, objflags))
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
        if not _build(c_code, stdlib, dylibs, objects, target, gcc, objflags, link_driver):
            return None
        cas.publish(pkey, '', open(target, 'rb').read())

    if run:
        return subprocess.run([target] + list(program_args or [])).returncode
    print(f"Built: {target}")
    return 0
