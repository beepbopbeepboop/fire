#!/usr/bin/env python3
"""An import-cycle back-edge gets the solver's return type (bugs/GIR_type_solver.md, S1).

`main` imports `a`, `a` imports `b` at the top, and `b` calls `a`'s functions
through the module attribute. Compiled in order, `b` is generated inside `a`'s
import step, before `a`'s own return-type passes have run: an importer reading a
definer that is still in progress. Before the solver's early decision this was
`conflicting types` in gcc, and the binary was wrong or did not build.

Checks: the binary prints what `python3 main.py` prints, and the solver's ledger
(FIRE_TSOLVE_LEDGER) has an `early` decision for `a.make` and `a.name_of` with
no `conflict` and no `undecided` line.

Run directly: python3 test_import_cycle_sigs.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = {
    'main.py': 'import a\nprint(a.run())\n',
    'a.py': ('import b\n'
             'def make(n):\n    return [n, n + 1]\n'
             'def name_of(x):\n    if x:\n        return "yes"\n    return None\n'
             'def label(x) -> str:\n    return "L" + str(x)\n'
             'def pair(n) -> tuple[str, str]:\n    return (str(n), "x")\n'
             'def run():\n    return b.use()\n'),
    'b.py': ('import a\n'
             'def use():\n    xs = a.make(3)\n    p = a.pair(2)\n'
             '    return str(len(xs)) + " " + a.name_of(1) + " " + a.label(4) + " " + p[0]\n'),
}
PY = sys.executable


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as d:
        for name in FILES:
            with open(os.path.join(d, name), 'w') as f:
                f.write(FILES[name])
        expected = subprocess.run([PY, 'main.py'], cwd=d, capture_output=True, text=True)
        ledger = os.path.join(d, 'ledger.txt')
        env = dict(os.environ, FIRE_TSOLVE_LEDGER=ledger)
        build = subprocess.run([PY, os.path.join(HERE, 'fire.py'), 'build', '-o', 'prog', 'main.py'],
                               cwd=d, capture_output=True, text=True, env=env)
        if build.returncode != 0:
            failures.append('build failed: ' + build.stderr[-800:])
        else:
            got = subprocess.run([os.path.join(d, 'prog')], capture_output=True, text=True)
            if got.stdout != expected.stdout:
                failures.append('output %r, python gives %r' % (got.stdout, expected.stdout))
        lines = []
        if os.path.exists(ledger):
            with open(ledger) as f:
                lines = f.read().splitlines()
        # Annotated definers are decided by the backend's own routine (4.4).
        for want in ('early a.make ', 'early a.name_of ', 'early a.label ', 'early a.pair '):
            if not any(ln.startswith(want) for ln in lines):
                failures.append('ledger has no `%s` line: %r' % (want.strip(), lines))
        for bad in ('conflict', 'weak', 'undecided'):
            hits = [ln for ln in lines if ln.startswith(bad)]
            if hits:
                failures.append('ledger has `%s` lines: %r' % (bad, hits))
    for f in failures:
        print('FAIL', f)
    if not failures:
        print('PASS import-cycle back-edge: output matches python, early decisions made, no conflicts')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
