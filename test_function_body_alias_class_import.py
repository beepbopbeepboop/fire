#!/usr/bin/env python3
"""Regression: a FUNCTION-BODY `from M import Class as Alias` must bind
`Alias` to the class, not to a weak `unavailable in compiled mode` stub.

The constructor spelling (`Alias(3)`) was already resolving through the
constructor dispatch, so the stub it emitted was dead — but it still matched
the gate's "unavailable in compiled mode" reject. The value spelling
(`g = Alias`) was worse: `g` became the stub function itself, and the
compiled program printed `<function Alias at 0x...>` where CPython prints
`<class 'm.Thing'>`.

Fix: `_gen_stmt_FromImportStmt` (mojo/backend_gimple/emit_funcs.py) stops
the bare no-signature import registration when the shared
`_note_struct_import_alias` writer confirms the imported name is a class —
the module-scope path never puts a class binding in `imported_symbols`
either — and `_lower_IdentExpr`
(mojo/backend_gimple/emit_exprs.py) resolves the alias to the defining
name before the class-as-value branches, so `g = Alias` lowers exactly
like the direct spelling `g = Thing` does today.

Pinned behaviour (class-as-value in general is a separate, documented
feature gap, NOT this test's job):
  * constructor probe: zero `unavailable in compiled mode`, stdout ==
    CPython's (`3`), exit 0;
  * value probe: zero stubs, and `print(g)` prints the SAME class-value
    text the direct name `Thing` prints in the same program (CPython
    prints `<class 'm.Thing'>` for both; the compiled class-value model
    prints a type id — both spellings must agree, which is what this
    pins);
  * the existing function-alias shape (`from m import helper as alias;
    alias(1)`) stays green;
  * `from m import Thing, Thing as Alias` binds BOTH names in one body.

Run:  python3 test_function_body_alias_class_import.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_config import find_gcc                       # noqa: E402
from gimple_codegen import compile_to_gimple            # noqa: E402

RUNTIME = os.path.join(HERE, 'runtime')
COMPILE_TIMEOUT_S = 120
RUN_TIMEOUT_S = 10

M_SRC = (
    'class Thing:\n'
    '    def __init__(self, v):\n'
    '        self.v = v\n'
    '\n'
    'def helper(x):\n'
    '    return x * 2\n'
)

# (name, u.py source, CPython stdout)
CASES = [
    # The constructor probe: the aliased class constructs.
    (
        'constructor',
        'def f():\n'
        '    from m import Thing as Alias\n'
        '    t = Alias(3)\n'
        '    print(t.v)\n'
        'f()\n',
        '3\n',
    ),
    # The value probe: the alias READ as a value must be the same
    # class-value the direct spelling produces in the same program.
    (
        'value',
        'def f():\n'
        '    from m import Thing\n'
        '    from m import Thing as Alias\n'
        '    g = Alias\n'
        '    print(g)\n'
        '    print(Thing)\n'
        'f()\n',
        '<class \'m.Thing\'>\n<class \'m.Thing\'>\n',
    ),
    # No regression: the function-alias shape stays green.
    (
        'function_alias',
        'def f():\n'
        '    from m import helper as alias\n'
        '    print(alias(21))\n'
        'f()\n',
        '42\n',
    ),
    # Both names from one statement, both usable in the body.
    (
        'both_names_one_body',
        'def f():\n'
        '    from m import Thing, Thing as Alias\n'
        '    a = Thing(1)\n'
        '    b = Alias(2)\n'
        '    print(a.v)\n'
        '    print(b.v)\n'
        'f()\n',
        '1\n2\n',
    ),
]


def build_and_run(name, u_src, work):
    """Compile u.py (importing m.py) to an executable and return its
    stdout; the generated C is also returned for the stub assertions."""
    with open(os.path.join(work, 'm.py'), 'w') as f:
        f.write(M_SRC)
    u_path = os.path.join(work, 'u.py')
    with open(u_path, 'w') as f:
        f.write(u_src)
    c_src = compile_to_gimple(u_src, do_imports=True, filename=u_path)
    c_file = os.path.join(work, 'u.c')
    with open(c_file, 'w') as f:
        f.write(c_src)
    exe = os.path.join(work, 'u.exe')
    link = subprocess.run(
        [find_gcc(), '-fgimple', f'-I{RUNTIME}', '-o', exe, c_file,
         os.path.join(RUNTIME, 'fire_runtime.c')],
        capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    if link.returncode != 0:
        return c_src, f'<gcc failed: {link.stderr[-400:]}>'
    run = subprocess.run([exe], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT_S)
    return c_src, run.stdout


def main():
    failures = []
    scratch = os.path.join(HERE, '.tmp',
                           'test_function_body_alias_class_import')
    os.makedirs(scratch, exist_ok=True)
    work = tempfile.mkdtemp(prefix='fbalias_', dir=scratch)
    try:
        for name, u_src, expected in CASES:
            case_dir = os.path.join(work, name)
            os.makedirs(case_dir, exist_ok=True)
            c_src, got = build_and_run(name, u_src, case_dir)
            if 'unavailable in compiled mode' in c_src:
                failures.append(f'{name}: generated C still contains '
                                f'"unavailable in compiled mode" stub(s)')
            if name == 'value':
                # The alias and the direct spelling must print the SAME
                # class-value text in one program (CPython's own text is
                # a pre-existing class-as-value gap, not this part).
                lines = [ln for ln in got.splitlines() if ln.strip()]
                if len(lines) != 2:
                    failures.append(f'value: expected 2 printed lines, '
                                    f'got {got!r}')
                elif lines[0] != lines[1]:
                    failures.append('value: print(Alias) disagrees with '
                                    f'print(Thing): {lines!r}')
                if lines and '<function Alias' in lines[0]:
                    failures.append(f'value: alias is a function value: '
                                    f'{lines[0]!r}')
                continue
            if got != expected:
                failures.append(f'{name}: expected {expected!r}, got {got!r}')
        # CPython reference for the value spelling (documents the gap;
        # the compiled side only has to agree with itself).
        cpython_value = subprocess.run(
            [sys.executable, os.path.join(work, 'value', 'u.py')],
            capture_output=True, text=True, timeout=RUN_TIMEOUT_S,
            cwd=work + os.sep + 'value')
        if cpython_value.stdout != CASES[1][2]:
            failures.append(f'value: CPython reference drifted: '
                            f'{cpython_value.stdout!r}')
    finally:
        shutil.rmtree(work, ignore_errors=True)

    if failures:
        for f in failures:
            print(f'FAIL  function_body_alias_class_import: {f}')
        return 1
    print('PASS  function_body_alias_class_import')
    return 0


if __name__ == '__main__':
    sys.exit(main())
