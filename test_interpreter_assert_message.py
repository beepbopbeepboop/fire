#!/usr/bin/env python3
"""The interpreter's `assert` failure text matches the compiled path's.

Modular's `test/mojo-integration/assert_failure_message.mojo` requires
`Assert Error: x must be positive` on stderr when an `assert` with a message
fails. The compiled path prints that prefix (mojo/backend_gimple/emit_stmts.py);
`python3 fire.py run` used to print only `Error: <loc>: <msg>`.

Runs real programs through `python3 fire.py run` in a temp dir and checks the
exit code and stderr. Run with: python3 test_interpreter_assert_message.py
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
    # The modular snippet: a failing assert with a message.
    rc, err = run_program(
        'def main():\n'
        '    assert False, "x must be positive"\n'
    )
    check('failing assert with message exits nonzero', rc != 0, f'rc={rc}')
    check('failing assert prints Assert Error prefix with the message',
          'Assert Error: x must be positive' in err, err)

    # A failing assert with no message gets the default text, with the prefix.
    rc, err = run_program(
        'def main():\n'
        '    assert False\n'
    )
    check('bare failing assert exits nonzero', rc != 0, f'rc={rc}')
    check('bare failing assert prints Assert Error: assert failed',
          'Assert Error: assert failed' in err, err)

    # A passing assert is silent and exits 0.
    rc, err = run_program(
        'def main():\n'
        '    assert True, "unused"\n'
        '    print("ok")\n'
    )
    check('assert True exits 0', rc == 0, f'rc={rc} stderr={err}')
    check('assert True prints no Assert Error', 'Assert Error' not in err, err)

    print()
    if FAILURES:
        print(f'{len(FAILURES)} failed: ' + ', '.join(FAILURES))
        return 1
    print('all assert-message checks passed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
