#!/usr/bin/env python3
"""The interpreter runs the `constrained[cond, msg]()` builtin.

The compiled path rejects a provably-false `constrained` at compile time
(test_constrained_diagnostic.py). `python3 fire.py run` used to raise
`NameError: name 'constrained' is not defined` for every program that uses
the builtin, including valid ones. The interpreter now evaluates the condition
when the call runs: false raises `constraint failed: <msg>`, true is a no-op.

Runs real programs through `python3 fire.py run` in a temp dir and checks the
exit code and stderr. Run with: python3 test_interpreter_constrained_diagnostic.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MOJO = os.path.join(HERE, 'fire.py')


def run_program(source: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, 'prog.mojo')
        with open(path, 'w') as f:
            f.write(source)
        proc = subprocess.run(
            [sys.executable, MOJO, 'run', path],
            capture_output=True, text=True, timeout=120,
        )
        return proc.returncode, proc.stderr


FAILURES = []


def check(name, cond, detail=''):
    print(('PASS  ' if cond else 'FAIL  ') + name + ('' if cond else f'  [{detail}]'))
    if not cond:
        FAILURES.append(name)


def main():
    # False condition with a message.
    rc, err = run_program(
        'fn f():\n'
        '    constrained[1 == 2, "bad"]()\n'
        'fn main():\n'
        '    f()\n'
    )
    check('false constrained with message exits nonzero', rc != 0, f'rc={rc}')
    check('false constrained names the message',
          'constraint failed: bad' in err, err)
    check('false constrained is not a NameError',
          'NameError' not in err, err)

    # True condition is a no-op.
    rc, err = run_program(
        'fn main():\n'
        '    constrained[1 == 1, "ok"]()\n'
        '    print("after")\n'
    )
    check('true constrained exits 0', rc == 0, f'rc={rc} stderr={err}')
    check('true constrained prints no failure',
          'constraint failed' not in err, err)

    # False condition without a message.
    rc, err = run_program(
        'fn main():\n'
        '    constrained[False]()\n'
    )
    check('false constrained with no message exits nonzero', rc != 0, f'rc={rc}')
    check('false constrained with no message prints constraint failed',
          'constraint failed' in err, err)

    # False condition inside a helper called from main.
    rc, err = run_program(
        'fn helper():\n'
        '    constrained[False, "bad"]()\n'
        'fn main():\n'
        '    helper()\n'
    )
    check('helper constrained exits nonzero', rc != 0, f'rc={rc}')
    check('helper constrained names the message',
          'constraint failed: bad' in err, err)

    print()
    if FAILURES:
        print(f'{len(FAILURES)} failed: ' + ', '.join(FAILURES))
        return 1
    print('all constrained-diagnostic checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
