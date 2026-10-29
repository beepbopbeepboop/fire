# Regression tests for bugs/CODEGEN_module_boundary_carries_no_value_types.md
#
# Each case is a two-module program compiled through the real import closure
# (`compile_to_gimple(..., do_imports=True)`), linked with `gcc -fgimple`, run,
# and compared with the stdout CPython prints for the same two files.
#
# Status of the cases (2026-10-29, measured on this tree):
#   module_qualified_str_param       PASSES -- `m.f('abcd')` types as char *
#                                    across the boundary; pinned so it stays so.
#   imported_generator_yields_str    FAILS  -- the importer's loop variable
#                                    over `m.gen(['p', 'q'])` is untyped, so the
#                                    yielded `char *` prints as its address.
#                                    This is the live wrong answer; see the doc.
#
# Scratch files go under TMPDIR (the worktree's .tmp/), never a fixed path.

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

# The coroutine runtime is linked whenever the generated C calls into it, the
# same textual test test_gimple_runner.py uses for the same reason.
CORO_SOURCES = ['fire_coro_gen.c', 'fire_coro.c', 'fire_async_sched.c']

CASES = [
    (
        'module_qualified_str_param',
        # m.py
        'def f(s):\n    return len(s)\n',
        # u.py
        'import m\n'
        'def main():\n'
        '    print(m.f("abcd"))\n'
        '    print(m.f("xy"))\n'
        'main()\n',
        '4\n2\n',
    ),
    (
        'imported_generator_yields_str',
        'def gen(xs):\n'
        '    for x in xs:\n'
        '        yield x\n',
        'import m\n'
        'def main():\n'
        '    for v in m.gen(["p", "q"]):\n'
        '        print(v)\n'
        'main()\n',
        'p\nq\n',
    ),
]


def build_and_run(name, m_src, u_src):
    """Compile u.py (importing m.py) to an executable and return its stdout."""
    work = tempfile.mkdtemp(prefix=f'modboundary_{name}_')
    try:
        with open(os.path.join(work, 'm.py'), 'w') as f:
            f.write(m_src)
        u_path = os.path.join(work, 'u.py')
        with open(u_path, 'w') as f:
            f.write(u_src)
        c_code = compile_to_gimple(u_src, do_imports=True, filename=u_path)
        c_file = os.path.join(work, 'u.c')
        exe = os.path.join(work, 'u.exe')
        with open(c_file, 'w') as f:
            f.write(c_code)
        sources = [c_file, os.path.join(RUNTIME, 'fire_runtime.c')]
        if '__mgco_' in c_code or '__mojo_coro_yield_i' in c_code:
            import platform
            arch = ('fire_coro_ctx_aarch64.S'
                    if platform.machine().lower() in ('arm64', 'aarch64')
                    else 'fire_coro_ctx_generic.c')
            sources += [os.path.join(RUNTIME, c)
                        for c in CORO_SOURCES + [arch]]
        link = subprocess.run(
            [find_gcc(), '-fgimple', f'-I{RUNTIME}', '-o', exe, *sources],
            capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
        if link.returncode != 0:
            return f'<gcc -fgimple failed: {link.stderr[-300:]}>'
        run = subprocess.run([exe], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT_S)
        return run.stdout
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    failed = []
    for name, m_src, u_src, expected in CASES:
        got = build_and_run(name, m_src, u_src)
        if got == expected:
            print(f'PASS {name}')
        else:
            print(f'FAIL {name}: expected {expected!r}, got {got!r}')
            failed.append(name)
    print(f'{len(CASES) - len(failed)}/{len(CASES)} passed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
