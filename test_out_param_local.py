"""A free function's `out` parameter reaches the caller, in the same module and
across an import.

`def make(out r: Box)` writes its result through a pointer the caller owns. A
caller that omits the argument (`var b = make()`) must get that result: the
callee copies into the caller's object, and the caller allocates the object and
passes it. Pinned here by compiling the modules to C and running them.
"""
import os
import shutil
import subprocess
import sys
import tempfile

import build_stdlib_dylib as b

SRC = """
struct Box(Copyable):
    var v: Int

def make(out r: Box):
    r = Box(7)

def use() -> Int:
    var b = make()
    return b.v
"""

MAIN = """#include <stdio.h>
int64_t outp_use(void);
int main(void) { printf("%lld\\n", (long long)outp_use()); return 0; }
"""


def _gcc():
    for cand in ('/opt/local/bin/gcc-mp-15', 'gcc-15', 'gcc'):
        if shutil.which(cand) or os.path.exists(cand):
            return cand
    return None


def test_out_param_round_trip():
    gcc = _gcc()
    if gcc is None:
        print('SKIP: no gcc available')
        return True
    here = os.path.dirname(os.path.abspath(__file__))
    tmp = tempfile.mkdtemp(prefix='out_param_')
    try:
        src_path = os.path.join(tmp, 'outp.mojo')
        with open(src_path, 'w') as f:
            f.write(SRC)
        c_src = b.compile_module_to_c(SRC, src_path, 'outp')
        c_path = os.path.join(tmp, 'outp.c')
        with open(c_path, 'w') as f:
            f.write(c_src)
        main_path = os.path.join(tmp, 'main.c')
        with open(main_path, 'w') as f:
            f.write(MAIN)
        inc = os.path.join(here, 'runtime')
        flags = ['-w', '-fgimple', '-D__MOJO_STDLIB_MODE__', '-I' + inc]
        objs = []
        for name, path in (('outp', c_path), ('rt', os.path.join(inc, 'fire_runtime.c'))):
            o = os.path.join(tmp, name + '.o')
            r = subprocess.run([gcc] + flags + ['-c', path, '-o', o],
                               capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[:800]
            objs.append(o)
        mo = os.path.join(tmp, 'main.o')
        r = subprocess.run([gcc, '-w', '-I' + inc, '-c', main_path, '-o', mo],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:800]
        exe = os.path.join(tmp, 'run')
        r = subprocess.run([gcc, '-o', exe, mo] + objs + ['-lm'],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:800]
        out = subprocess.run([exe], capture_output=True, text=True).stdout.strip()
        assert out == '7', f'out param result was {out!r}, expected 7'
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


A_SRC = """
struct Box(Copyable):
    var v: Int

def make(out r: Box):
    r = Box(7)
"""

B_SRC = """
from xmod_a import Box, make

def use() -> Int:
    var b = make()
    return b.v
"""

MAIN_X = """#include <stdio.h>
int64_t xmod_b_use(void);
int main(void) { printf("%lld\\n", (long long)xmod_b_use()); return 0; }
"""


def test_out_param_cross_module():
    gcc = _gcc()
    if gcc is None:
        print('SKIP: no gcc available')
        return True
    here = os.path.dirname(os.path.abspath(__file__))
    inc = os.path.join(here, 'runtime')
    tmp = tempfile.mkdtemp(prefix='out_param_x_')
    try:
        srcs = {}
        for name, text in (('xmod_a', A_SRC), ('xmod_b', B_SRC)):
            path = os.path.join(tmp, name + '.mojo')
            with open(path, 'w') as f:
                f.write(text)
            srcs[name] = (path, text)
        # xmod_b imports xmod_a; the loader resolves it from the directory of the source.
        sys.path.insert(0, tmp)
        try:
            c_out = {}
            for name, (path, text) in srcs.items():
                c_out[name] = b.compile_module_to_c(text, path, name)
        finally:
            sys.path.remove(tmp)
        objs = []
        for name, c_text in c_out.items():
            cp = os.path.join(tmp, name + '.c')
            with open(cp, 'w') as f:
                f.write(c_text)
            o = os.path.join(tmp, name + '.o')
            r = subprocess.run([gcc, '-w', '-fgimple', '-D__MOJO_STDLIB_MODE__', '-I' + inc,
                                '-c', cp, '-o', o], capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[:800]
            objs.append(o)
        rt = os.path.join(tmp, 'rt.o')
        r = subprocess.run([gcc, '-w', '-fgimple', '-D__MOJO_STDLIB_MODE__', '-I' + inc,
                            '-c', os.path.join(inc, 'fire_runtime.c'), '-o', rt],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:800]
        mp = os.path.join(tmp, 'main.c')
        with open(mp, 'w') as f:
            f.write(MAIN_X)
        mo = os.path.join(tmp, 'main.o')
        r = subprocess.run([gcc, '-w', '-I' + inc, '-c', mp, '-o', mo],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:800]
        exe = os.path.join(tmp, 'run')
        r = subprocess.run([gcc, '-o', exe, mo] + objs + [rt, '-lm'],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:800]
        out = subprocess.run([exe], capture_output=True, text=True).stdout.strip()
        assert out == '7', f'cross-module out result was {out!r}, expected 7'
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


PTR_A = """
struct Box(Copyable):
    var v: Int

def get_box(out result: UnsafePointer[Box]):
    var p = UnsafePointer[Box].alloc(1)
    p[].v = 9
    result = p
"""

PTR_B = """
from ptr_a import Box, get_box

def use() -> Int:
    return get_box()[].v
"""

PTR_MAIN = """#include <stdio.h>
int64_t ptr_b_use(void);
int main(void) { printf("%lld\\n", (long long)ptr_b_use()); return 0; }
"""


def test_pointer_result_cross_module():
    """`out result: UnsafePointer[T]` is a pointer result: the caller gets the
    pointer back and dereferences it, across an import (random's
    get_global_random_state is this shape). Expects 9."""
    gcc = _gcc()
    if gcc is None:
        print('SKIP: no gcc available')
        return True
    here = os.path.dirname(os.path.abspath(__file__))
    inc = os.path.join(here, 'runtime')
    tmp = tempfile.mkdtemp(prefix='ptr_result_')
    try:
        srcs = {'ptr_a': PTR_A, 'ptr_b': PTR_B}
        for name, text in srcs.items():
            with open(os.path.join(tmp, name + '.mojo'), 'w') as f:
                f.write(text)
        sys.path.insert(0, tmp)
        try:
            c_out = {name: b.compile_module_to_c(text, os.path.join(tmp, name + '.mojo'), name)
                     for name, text in srcs.items()}
        finally:
            sys.path.remove(tmp)
        objs = []
        for name, c_text in c_out.items():
            cp = os.path.join(tmp, name + '.c')
            with open(cp, 'w') as f:
                f.write(c_text)
            o = os.path.join(tmp, name + '.o')
            r = subprocess.run([gcc, '-w', '-fgimple', '-D__MOJO_STDLIB_MODE__', '-I' + inc,
                                '-c', cp, '-o', o], capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[:800]
            objs.append(o)
        rt = os.path.join(tmp, 'rt.o')
        r = subprocess.run([gcc, '-w', '-fgimple', '-D__MOJO_STDLIB_MODE__', '-I' + inc,
                            '-c', os.path.join(inc, 'fire_runtime.c'), '-o', rt],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:800]
        mp = os.path.join(tmp, 'main.c')
        with open(mp, 'w') as f:
            f.write(PTR_MAIN)
        mo = os.path.join(tmp, 'main.o')
        r = subprocess.run([gcc, '-w', '-I' + inc, '-c', mp, '-o', mo], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:800]
        exe = os.path.join(tmp, 'run')
        r = subprocess.run([gcc, '-o', exe, mo] + objs + [rt, '-lm'], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:800]
        out = subprocess.run([exe], capture_output=True, text=True).stdout.strip()
        assert out == '9', f'pointer result read back {out!r}, expected 9'
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    ok = test_out_param_round_trip() and test_out_param_cross_module() and test_pointer_result_cross_module()
    print('PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)
