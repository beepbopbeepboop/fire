# Regression test for bug:CODEGEN_ctor_temp_field_read_loses_element_type.
#
# A container stored through a constructor argument and read back off the
# constructor TEMPORARY (`B4([...]).v`) must print its elements, not the
# repr walker's guesses. Before the per-list element repr landed, a `0`
# element of a comprehension printed as `None` (the generic walker's sentinel)
# and a float list segfaulted (its IEEE-754 bits were read as a char *).
#
# Measured: the pre-fix behaviour is `[None, 1, 2]` / `[None, 5]` and a
# SIGSEGV on the float case at 86d862fc1; `git bisect` pins the fix to
# 331ddc2f7 (the comprehension/list(range) `mojo_list_set_elem_repr` call).
#
# The oracle is CPython on the same text, so no expected output is hand-copied.

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gimple_codegen  # noqa: E402
from build_config import find_gcc  # noqa: E402
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S

RUNTIME = os.path.join(HERE, 'runtime')

# The doc's repro, plus every shape the doc's table measured: a comprehension
# whose first element is the `0` sentinel, a plain literal with a `0`, a float
# list, and the same field read through a local.
SRC = '''\
class B4:
    def __init__(self, v):
        self.v = v

def main():
    print(B4([i for i in range(3)]).v)
    print(B4([i for i in [0]]).v)
    print(B4([i for i in [0, 1]]).v)
    print(B4([0, 5]).v)
    print(B4([0.0, 5.0]).v)
    b = B4([i for i in range(3)])
    print(b.v)

main()
'''


def _cpython_stdout(tmp):
    p = os.path.join(tmp, 'oracle.mojo')
    with open(p, 'w') as f:
        f.write(SRC)
    r = subprocess.run([sys.executable, '-I', p], capture_output=True,
                       text=True, timeout=RUN_TIMEOUT_S)
    assert r.returncode == 0, f'CPython oracle failed: {r.stderr}'
    return r.stdout


def _compiled_stdout(tmp):
    """Emit C through the gimple backend, build it with the runtime, run it.

    Returns (returncode, stdout). A segfault shows as a negative returncode
    rather than an exception, so the assertion reports the signal."""
    c_src = gimple_codegen._run_pipeline(
        SRC, filename='ctor_temp_field.mojo', **{'do_imports': True})[0]
    c_path = os.path.join(tmp, 'ctor_temp_field.c')
    exe = os.path.join(tmp, 'ctor_temp_field')
    with open(c_path, 'w') as f:
        f.write(c_src)
    gcc = find_gcc()
    b = subprocess.run(
        [gcc, '-fgimple', '-fPIC', f'-I{RUNTIME}', '-O0', '-w', '-o', exe,
         c_path, os.path.join(RUNTIME, 'fire_runtime.c'), '-lm'],
        capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    assert b.returncode == 0, f'gcc -fgimple failed:\n{b.stderr[:2000]}'
    r = subprocess.run([exe], capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
    return r.returncode, r.stdout


def test_ctor_temp_field_read_matches_cpython():
    # TMPDIR is the worktree's git-ignored .tmp/ (see the project rules); the
    # scratch dir is removed with the test, so nothing is left behind.
    with tempfile.TemporaryDirectory() as tmp:
        want = _cpython_stdout(tmp)
        rc, got = _compiled_stdout(tmp)
    assert rc == 0, f'compiled program exited {rc} (negative = signal)'
    assert got == want, f'compiled output differs from CPython\n' \
                        f'want:\n{want}\ngot:\n{got}'


if __name__ == '__main__':
    test_ctor_temp_field_read_matches_cpython()
    print('PASS  ctor_temp_field_read_matches_cpython')
