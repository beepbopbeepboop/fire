"""Regression pin: a METHOD call passes a `= None` parameter as the None box.

A free function's `x=None` parameter is the tagged word, and its calls box the
argument by kind (`_box_param_call_args`). A method call did not: the omitted
argument was padded with the bare 0, which the callee (`mojo_word_is_none`) reads
as the integer 0, so `if tag is not None` was true and `b.label()` printed
`tag=0`. In the self-hosted compiler it was a crash: `self._infer_return_type(
body)` handed `func_def=None` to its callee as 0 and the callee dereferenced it.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = '''class Box:
    def __init__(self, n):
        self.n = n

    def label(self, tag=None):
        if tag is not None:
            return "tag=" + str(tag)
        return "no tag"

    def size(self, inner=None):
        if inner is not None:
            return inner.n
        return 0

b = Box(3)
print(b.label())
print(b.label(None))
print(b.label(0))
print(b.label("x"))
print(b.size(), b.size(Box(9)))
'''
WANT = 'no tag\nno tag\ntag=0\ntag=x\n0 9\n'


def main() -> int:
    d = tempfile.mkdtemp(prefix='method_none_')
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
