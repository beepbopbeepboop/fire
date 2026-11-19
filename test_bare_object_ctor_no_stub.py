#!/usr/bin/env python3
"""Pin: a bare `object()` constructor leaves no weak stub in the emitted C.

`bugs/GATE_red_recover-land_2026-11-02-part5-part1.md`'s `object` row: the
self-host closure carries `NOT_SET = object()` (`funcs_shared._PARSE_FAILED`,
and real stdlib code's `c_common/__init__.py` has the same idiom), and the
compiled path has no Python object representation, so the constructor is
lowered to the quiet null placeholder the coroutine emitter already used.

The lowering existed, but it ran too late: `_is_unknown` was true for `object`
(no definition, no import entry), so `_lnc_unknown` first emitted a weak
`int64_t object (...)` "unavailable in compiled mode" DEFINITION. The call
site then took the placeholder branch, making that definition dead — but it
still sat in the dumped `.ci`, which is the half of the job's acceptance the
`reject=` regex cannot see (it reads the child's output, not `fire.ci`).

The fixture requires zero unavailable-in-compiled-mode text, then builds the
emitted C and requires the binary's stdout to equal CPython's.

The fixture MUST live inside a checkout (under `build/`, git-ignored): the
probe resolves sibling modules against the importing file's own directory, and
a `$TMPDIR` outside the tree takes the generic branch instead.

Run: python3 test_bare_object_ctor_no_stub.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_config import find_gcc
from exec_budget import COMPILE_TIMEOUT_S, RUN_TIMEOUT_S

RUNTIME_DIR = os.path.join(HERE, 'runtime')
RUNTIME_C = os.path.join(RUNTIME_DIR, 'fire_runtime.c')

PROGRAM_SRC = """\
NOT_SET = object()


def same(x):
    return x is NOT_SET


def main():
    print(same(NOT_SET))
    print(same(3))


main()
"""


def _cpython_stdout(root: str, td: str) -> str:
    env = dict(os.environ)
    env['PYTHONPATH'] = td + (os.pathsep + env['PYTHONPATH']
                              if env.get('PYTHONPATH') else '')
    r = subprocess.run([sys.executable, root], capture_output=True, text=True,
                       cwd=td, env=env, timeout=RUN_TIMEOUT_S)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    return r.stdout


def _build_and_run(ci: str, td: str) -> str:
    gcc = find_gcc()
    c_path = os.path.join(td, 'consumer.ci')
    with open(c_path, 'w') as f:
        f.write(ci)
    c_o = os.path.join(td, 'consumer.o')
    rt_o = os.path.join(td, 'fire_runtime.o')
    exe = os.path.join(td, 'consumer.exe')
    r = subprocess.run([gcc, '-O0', '-fgimple', '-x', 'c',
                        f'-I{RUNTIME_DIR}', '-c', '-o', c_o, c_path],
                       capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    assert r.returncode == 0, r.stderr + '\n---\n' + ci
    r = subprocess.run([gcc, '-O0', f'-I{RUNTIME_DIR}', '-c', '-o', rt_o,
                        RUNTIME_C],
                       capture_output=True, text=True, timeout=COMPILE_TIMEOUT_S)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([gcc, '-o', exe, c_o, rt_o], capture_output=True,
                       text=True, timeout=COMPILE_TIMEOUT_S)
    assert r.returncode == 0, r.stderr + '\n---\n' + ci
    r = subprocess.run([exe], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT_S)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    return r.stdout


def test_bare_object_ctor_leaves_no_stub():
    import gimple_codegen
    root = os.path.join(HERE, 'build', 'test_bare_object_ctor_no_stub')
    os.makedirs(root, exist_ok=True)
    td = tempfile.mkdtemp(prefix='probe_', dir=root)
    try:
        probe = os.path.join(td, 'probe.py')
        with open(probe, 'w') as f:
            f.write(PROGRAM_SRC)
        expected = _cpython_stdout(probe, td)
        assert expected == 'True\nFalse\n', expected
        ci = gimple_codegen.compile_to_gimple(
            PROGRAM_SRC, do_imports=True, filename=probe)
        bad = [ln for ln in ci.splitlines()
               if 'unavailable in compiled mode' in ln]
        assert not bad, (
            'a bare `object()` emitted a dead weak stub; the placeholder '
            'lowering must run before `_lnc_unknown`:\n  ' + '\n  '.join(bad))
        # The placeholder arm is what must have replaced the stub; a call to
        # the symbol itself would mean the constructor went back to dynamic
        # dispatch.
        assert not any('object (' in ln and 'weak' in ln for ln in ci.splitlines())
        assert _build_and_run(ci, td) == expected
    finally:
        import shutil
        shutil.rmtree(td, ignore_errors=True)


if __name__ == '__main__':
    test_bare_object_ctor_leaves_no_stub()
    print('PASS')
