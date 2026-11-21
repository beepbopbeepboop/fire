#!/usr/bin/env python3
"""Pin: `--dump-full` reports the weak stubs in the `.ci` it just wrote.

the stdlib-closure gate red (GATE_red_recover-land 2026-11-02 part 5, part 1) requires the closure of
`fire.py` to carry no `unavailable in compiled mode` stub, and
`bootstrap-stage1-transitive` enforces exactly that through
`reject=CLOSURE_INCOMPLETE`. But that regex reads the CHILD'S OUTPUT, and
`--dump-full` wrote the stubs only into `fire.ci` and printed `✓ Generated
fire.ci`: the job could pass with every one of them present. That made the
doc's acceptance second half unobservable in the job that is supposed to
prove it, so the only way to count the stubs was a manual grep of a 120 MB
artifact nobody kept.

`--dump-full` now says so on its own output when the artifact it just wrote
carries one. This test is the pin: a fixture whose compiled form really does
emit the stub must produce the report (and the test asserts the artifact
contains the stub, so the case cannot pass vacuously), and a clean fixture
must stay quiet.

Run: python3 test_dump_full_reports_closure_stubs.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, 'fire.py')
PHASE = 'unavailable in compiled mode'

# `locals()` is one of the builtins the GIMPLE path cannot lower at all, so a
# function that calls it emits the weak stub in its own module (see
# test_selfhost_no_locals_pin.py, the same shape removed from the compiler's
# own closure).
STUBBY = (
    'def f():\n'
    '    x = 1\n'
    '    return locals().get("x", 0)\n'
    '\n'
    'print(f())\n'
)
CLEAN = (
    'def f(n):\n'
    '    return n + 1\n'
    '\n'
    'print(f(1))\n'
)


def _dump(root: str, src: str):
    """Run `--dump-full` on a one-file program; return (result, artifact, dir)."""
    td = tempfile.mkdtemp(prefix='dump_full_stub_', dir=root)
    path = os.path.join(td, 'prog.py')
    with open(path, 'w') as f:
        f.write(src)
    r = subprocess.run(
        [sys.executable, FIRE, '--dump-full', 'prog.py'],
        cwd=td, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, timeout=300)
    ci_path = os.path.join(td, 'prog.ci')
    ci = open(ci_path).read() if os.path.exists(ci_path) else ''
    return r, ci, td


def test_stub_in_artifact_is_reported():
    root = os.path.join(HERE, 'build', 'test_dump_full_reports_closure_stubs')
    os.makedirs(root, exist_ok=True)
    r, ci, td = _dump(root, STUBBY)
    try:
        assert r.returncode == 0, (
            f'--dump-full failed ({r.returncode}); output:\n{r.stdout}')
        assert PHASE in ci, (
            'the fixture did not emit the weak stub this test is about, so '
            'the case would pass vacuously; artifact:\n' + ci[-2000:])
        assert PHASE in r.stdout, (
            '--dump-full wrote a .ci carrying an unavailable stub and said '
            'nothing about it, so the job\'s reject=CLOSURE_INCOMPLETE cannot '
            'see it; output was:\n' + r.stdout)
        assert 'prog.ci' in r.stdout, (
            'the report does not name the artifact it is about; output was:\n'
            + r.stdout)
    finally:
        shutil.rmtree(td, ignore_errors=True)


def test_clean_artifact_is_quiet():
    root = os.path.join(HERE, 'build', 'test_dump_full_reports_closure_stubs')
    os.makedirs(root, exist_ok=True)
    r, ci, td = _dump(root, CLEAN)
    try:
        assert r.returncode == 0, (
            f'--dump-full failed ({r.returncode}); output:\n{r.stdout}')
        assert PHASE not in ci, (
            'the clean fixture emitted a stub, which would make the quiet run '
            'indistinguishable from the reported one; artifact:\n' + ci[-2000:])
        assert PHASE not in r.stdout, (
            '--dump-full reported a stub for a closure that has none; output '
            'was:\n' + r.stdout)
    finally:
        shutil.rmtree(td, ignore_errors=True)


if __name__ == '__main__':
    test_stub_in_artifact_is_reported()
    test_clean_artifact_is_quiet()
    print('PASS')
