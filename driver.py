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
from build_config import find_gcc

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, 'runtime')


def _file_sha(path):
    """Content hash of a linked artifact (dylib or object)."""
    with open(path, 'rb') as f:
        return cas._hash(f.read())


def _prog_key(c_code, link_files, gcc, flags):
    # Everything that shapes the linked binary is in the key: the client C
    # (which already encodes imported signatures), the toolchain, and the
    # *content* of every dylib/object on the link line.  Hashing contents —
    # not just basenames — means a rebuilt stdlib dylib invalidates cached
    # programs (a fixed name like libmojostdlib.dylib carries no version
    # information).  In production the dylibs never change, so the extra
    # read-and-hash per compile is a cheap price for exactness.
    return 'prog/' + cas._hash(
        'mojo-prog-v2', cas.ABI_VERSION, cas.compiler_fingerprint(),
        cas.toolchain_fingerprint(gcc, flags), c_code,
        '\0'.join(f'{os.path.basename(p)}={_file_sha(p)}'
                  for p in sorted(link_files)))


def _build(c_code, stdlib, dylibs, objects, target, gcc, objflags):
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

    link_dylibs = list(dict.fromkeys([stdlib] + list(dylibs)))
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

    # Stdlib dylib: monolithic, CAS-built on first use; runtime folded in, so
    # programs need only one dylib on the link line.  Resolved *before* the
    # cache key so its content participates in invalidation.
    stdlib = bsd.build_stdlib()

    # Warm path: the whole program is content-addressed — a cache hit is a copy.
    link_files = list(dict.fromkeys([stdlib] + list(dylibs))) + list(objects)
    pkey = _prog_key(c_code, link_files, gcc, objflags)
    hit = cas.lookup(pkey, '')
    if hit:
        shutil.copy(hit, target)
        os.chmod(target, 0o755)
    else:
        if not _build(c_code, stdlib, dylibs, objects, target, gcc, objflags):
            return None
        cas.publish(pkey, '', open(target, 'rb').read())

    if run:
        return subprocess.run([target]).returncode
    print(f"Built: {target}")
    return 0
