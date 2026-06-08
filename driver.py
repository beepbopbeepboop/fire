#!/usr/bin/env python3
"""driver.py — `mojo build`/`run`, thin by design (MODULE_CACHE_DESIGN.md).

`import` does the work: as the codegen resolves each import it builds the module's
dylib (CAS), wires its `__mojo_reflect` ABI, and *records the dylib on the link
line*. The driver just:
  * compiles the client in link mode (extern decls), getting back the recorded
    dylib list;
  * links the client against the first-class runtime dylib + those import dylibs
    (the OS loader binds the symbols — we don't reinvent dyld);
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
from build_config import find_gcc

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')
RUNTIME_SRC = os.path.join(RUNTIME, 'mojo_runtime.c')


def _prog_key(c_code, dylibs, gcc, flags):
    # c_code already encodes the client + imported signatures; the dylib basenames
    # are content hashes, so they capture each dependency's implementation.
    return 'prog/' + cas._hash(
        'mojo-prog-v1', cas.ABI_VERSION, cas.compiler_fingerprint(),
        cas.toolchain_fingerprint(gcc, flags), c_code,
        '\0'.join(sorted(os.path.basename(d) for d in dylibs)))


def _build(c_code, dylibs, objects, target, gcc, objflags):
    """Compile the client object (cached) and link it against the runtime dylib +
    the import dylibs `import` recorded + the objects elaboration produced
    (generic instantiations). Returns True on success."""
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

    # Runtime is a first-class dylib, linked into every program; module dylibs
    # depend on it (their mojo_* symbols resolve from it at load).
    rt = bsd.runtime_dylib(gcc)
    link_dylibs = list(dict.fromkeys([rt] + list(dylibs)))
    rpaths = sorted({os.path.dirname(d) for d in link_dylibs})

    link = [gcc, '-o', target, client_o] + list(objects) + link_dylibs
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


def compile_program(input_file, src, output=None, run=True,
                    opt_flag=None, debug_flag=None):
    """Compile (and optionally run) a Mojo program through the module-cache system.
    Returns the program's exit code when run / 0 on a successful build, or None if
    the build failed (caller decides the fallback)."""
    gcc = find_gcc()
    flags = (opt_flag or '-O0', debug_flag or '-g3')
    objflags = ('-fgimple', '-fPIC', f'-I{RUNTIME}') + flags

    # `import` resolves dylibs and elaboration produces instantiation objects,
    # both recorded as a side effect of compiling.
    c_code, dylibs, objects = compile_linked(src, filename=input_file)
    target = os.path.abspath(output or os.path.splitext(os.path.basename(input_file))[0])

    # Warm path: the whole program is content-addressed — a cache hit is a copy.
    pkey = _prog_key(c_code, list(dylibs) + list(objects), gcc, objflags)
    hit = cas.lookup(pkey, '')
    if hit:
        shutil.copy(hit, target)
        os.chmod(target, 0o755)
    else:
        if not _build(c_code, dylibs, objects, target, gcc, objflags):
            return None
        cas.publish(pkey, '', open(target, 'rb').read())

    if run:
        return subprocess.run([target]).returncode
    print(f"Built: {target}")
    return 0
