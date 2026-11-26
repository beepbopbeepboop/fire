"""Regression pin: a tagged `= None` parameter forwarded to another tagged
parameter keeps its box, through a plain call, a method call and a module
attribute call (`mod.f(x)`).

`_emit_call` unboxes a may-box argument for a user function (`mojo_unbox_plain`:
None -> 0), because most parameters have no None word. A parameter declared
`= None` IS the tagged word and reads None with `mojo_word_is_none`, so passing
`x` straight through (`def outer(x=None): return inner(x)`) turned an omitted
argument into the integer 0: `outer()` printed `got 0`. The self-hosted compiler
crashed on it (`infer_return_type(gen, body, func_def=None)` forwarding
`func_def` to `infer_return_type_with_locals`, which dereferenced 0).
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = '''def inner(x=None):
    if x is not None:
        return "got " + str(x)
    return "none"
'''
SRC = '''import tagged_lib

def via_module(x=None):
    return tagged_lib.inner(x)

def inner(x=None):
    if x is not None:
        return "got " + str(x)
    return "none"

def outer(x=None):
    return inner(x)

class K:
    def inner(self, x=None):
        if x is not None:
            return "got " + str(x)
        return "none"

    def outer(self, x=None):
        return self.inner(x)

print(outer(), outer(0), outer(5))
print(via_module(), via_module(0), via_module(5))
k = K()
print(k.outer(), k.outer(0), k.outer(5))
'''
WANT = 'none got 0 got 5\nnone got 0 got 5\nnone got 0 got 5\n'


def main() -> int:
    d = tempfile.mkdtemp(prefix='tagged_fwd_')
    with open(os.path.join(d, 'tagged_lib.py'), 'w') as f:
        f.write(LIB)
    with open(os.path.join(d, 'm.py'), 'w') as f:
        f.write(SRC)
    out = os.path.join(d, 'm.out')
    r = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build',
                        'm.py', '-o', out], cwd=d, capture_output=True, text=True)
    if not os.path.exists(out):
        print('FAIL: did not build\n' + (r.stdout + r.stderr)[-1500:])
        return 1
    run = subprocess.run([out], capture_output=True, text=True)
    if run.stdout != WANT:
        print('FAIL: printed %r, CPython prints %r' % (run.stdout, WANT))
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
