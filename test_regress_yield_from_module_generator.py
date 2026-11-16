#!/usr/bin/env python3
"""Regression: yield-from a compiled generator defined in an imported module.

`yield from mod.gen(...)` inside a compiled generator body must delegate to
the module-qualified generator's C++ coroutine wrappers (the same way
`for x in mod.gen(...)` already does), not fall through to the plain-collection
path or be refused as an unresolved delegate.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, 'fire.py')


def main() -> int:
    with tempfile.TemporaryDirectory(dir=os.path.join(HERE, '.tmp')) as tmp:
        mod_a = os.path.join(tmp, 'mod_yf_a.py')
        mod_b = os.path.join(tmp, 'mod_yf_b.py')
        out = os.path.join(tmp, 'out_mod_yf_b')
        with open(mod_a, 'w', encoding='utf-8') as f:
            f.write(
                'def gen():\n'
                '    yield 1\n'
                '    yield 2\n'
                '    yield 3\n'
            )
        with open(mod_b, 'w', encoding='utf-8') as f:
            f.write(
                'import mod_yf_a\n'
                '\n'
                'def outer():\n'
                '    yield from mod_yf_a.gen()\n'
                '\n'
                'def main():\n'
                '    for x in outer():\n'
                '        print(x)\n'
                'main()\n'
            )
        env = os.environ.copy()
        env['PYTHONPATH'] = tmp + (os.pathsep + env['PYTHONPATH'] if env.get('PYTHONPATH') else '')
        r = subprocess.run(
            [sys.executable, FIRE, 'build', '-o', out, mod_b],
            cwd=HERE, env=env, capture_output=True, text=True, timeout=180,
        )
        if r.returncode != 0:
            print('FAIL: build failed (yield-from module generator not supported?)')
            print('stdout:', (r.stdout or '')[-400:])
            print('stderr:', (r.stderr or '')[-800:])
            return 1
        run = subprocess.run([out], capture_output=True, text=True, timeout=30)
        if run.returncode != 0:
            print('FAIL: built binary failed')
            print('stdout:', (run.stdout or '')[-400:])
            print('stderr:', (run.stderr or '')[-400:])
            return 1
        got = (run.stdout or '').strip().splitlines()
        want = ['1', '2', '3']
        if got != want:
            print('FAIL: wrong output', got, 'want', want)
            return 1
        print('PASS: yield-from module generator works')
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
