"""Regression pin: an importer compiled before its definer, inside an import
cycle, still links.

`a.h(x, y)` has parameters only its call sites refine (`x` is a `char *`
because `b` calls it with a string). `b` is compiled while `a` is in progress,
so it hashes `h`'s parameters as `(int64_t, int64_t)` and names the symbol
`a_h_2dbb98`; `a` then emits `a_h_e253d6 (char *, int64_t)`. Before the
forwarder the link failed with `Undefined symbols: _a_h_2dbb98` -- the
`annotated_return_ctype` / `_pack_kwargs_dict` ... family of the `mojoc` and
`selfhost` gate failures. The definer now also defines each suffix an earlier
call site hashed, as a forwarder that casts the word to the refined pointer.
Builds through the real link-mode driver and runs the program.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

FILES = {
    'a.py': 'from b import f\n\n'
            'def h(x, y):\n    return len(x) + y\n\n'
            'def run() -> int:\n    return f(3)\n',
    'b.py': 'from a import h\n\n'
            'def f(n):\n    return h("abc", n)\n',
    'main.py': 'from a import run\nprint(run())\n',
}


def main() -> int:
    d = tempfile.mkdtemp(prefix='param_forwarder_')
    for name, text in FILES.items():
        with open(os.path.join(d, name), 'w') as f:
            f.write(text)
    out = os.path.join(d, 'm.out')
    r = subprocess.run([sys.executable, os.path.join(HERE, 'fire.py'), 'build',
                        'main.py', '-o', out], cwd=d, capture_output=True, text=True)
    text = r.stdout + r.stderr
    if 'link failed' in text.lower() or 'Linking failed' in text or not os.path.exists(out):
        print('FAIL: an importer that hashed the definer early did not link')
        print(text[-1500:])
        return 1
    run = subprocess.run([out], capture_output=True, text=True)
    if run.stdout.strip() != '6':
        print('FAIL: program printed %r, CPython prints %r' % (run.stdout, '6'))
        return 1
    print('PASS')
    return 0


if __name__ == '__main__':
    sys.exit(main())
