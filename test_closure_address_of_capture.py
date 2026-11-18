"""`Pointer(to=x)` of a name a nested def captures BY VALUE takes the address of the
closure's environment field, not of a C local that does not exist in the nested def.

Before: the nested def emitted `_t1 = &base;` with no `base` in scope, so gcc refused
the module (`'base' undeclared`). This is the shape of stdlib test_variadic's
`make_elem_ptr`, which reads `Pointer(to=buffer_ptr)` from inside a nested def.
"""
import os
import shutil
import subprocess
import sys
import tempfile

import build_stdlib_dylib as b

SRC = """
def outer() -> Int:
    var base = 5
    def inner(i: Int) -> Int:
        var p = Pointer(to=base).as_unsafe_any_origin()
        return i
    return inner(1)
"""


def _gcc():
    for cand in ('/opt/local/bin/gcc-mp-15', 'gcc-15', 'gcc'):
        if shutil.which(cand) or os.path.exists(cand):
            return cand
    return None


def test_closure_address_of_capture():
    gcc = _gcc()
    if gcc is None:
        print('SKIP: no gcc available')
        return True
    here = os.path.dirname(os.path.abspath(__file__))
    inc = os.path.join(here, 'runtime')
    tmp = tempfile.mkdtemp(prefix='closure_addr_')
    try:
        path = os.path.join(tmp, 'cap_addr.mojo')
        with open(path, 'w') as f:
            f.write(SRC)
        c_text = b.compile_module_to_c(SRC, path, 'cap_addr')
        # The address is the environment field, never a bare local of the nested def.
        assert '&_env->base' in c_text, 'capture address is not the env field'
        assert '&base;' not in c_text, 'nested def takes the address of an out-of-scope name'
        cp = os.path.join(tmp, 'cap_addr.c')
        with open(cp, 'w') as f:
            f.write(c_text)
        r = subprocess.run([gcc, '-w', '-fgimple', '-D__MOJO_STDLIB_MODE__', '-I' + inc,
                            '-fsyntax-only', cp], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[:800]
        return True
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    ok = test_closure_address_of_capture()
    print('PASS' if ok else 'FAIL')
    sys.exit(0 if ok else 1)
