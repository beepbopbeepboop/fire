#!/usr/bin/env python3
"""Regression: a package that exists only as a precompiled `<pkg>.mojoc` (its
source deleted) is still checked, and the diagnostics that point into it show
the modular compiler's SYNTHETIC form: `file:line:1`, the declaration rendered
as a signature with `    # note - synthetic signature`, a `($0 > Int(0))` line
for a constraint, and the members of a trait as a bare name. No `Imported from`
lines. Call errors in function bodies come before struct errors even when the
struct is higher up the file. Expected text captured from `tools/mojo build -I`
after `tools/mojo precompile` and deleting the source (DIAGNOSTICS_formatting_
modular part 1, step 6)."""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, 'fire.py')

PACKAGE = 'def cf[n: Int]() where n > 0:\n    pass\n\n\ndef og(n: Int):\n    pass\n\n\ndef og(n: Float64, m: Float64):\n    pass\n\n\ntrait Need:\n    comptime K: Int\n\n    def go(self):\n        ...\n'

MAIN = 'import pk\n\n\nstruct Bad(pk.Need):\n    pass\n\n\ndef main():\n    pk.cf[0]()\n    pk.og()\n'

WANT = "M:9:7: error: invalid call to 'cf': violated constraint\n    pk.cf[0]()\n    ~~^~~\nP:1:1: note: constraint declared here evaluated to False, expected '(n > Int(0))'\n($0 > Int(0))\n^\nP:1:1: note: function declared here\ndef cf[n: Int]() where (n > Int(0))    # note - synthetic signature\n^\nM:10:10: error: no matching function in call to 'og'\n    pk.og()\n    ~~~~~^\nP:5:1: note: candidate not viable: missing required argument: 'n'\ndef og(n: Int)    # note - synthetic signature\n^\nP:9:1: note: candidate not viable: missing required argument: 'n'\ndef og(n: Float64, m: Float64)    # note - synthetic signature\n^\nM:4:8: error: 'Bad' does not implement all requirements for 'Need'\nstruct Bad(pk.Need):\n       ^\nP:14:1: note: required member 'K' is not specified\nK    # note - synthetic signature\n^\nP:16:1: note: required function 'go' is not implemented\ndef go(self)    # note - synthetic signature\n^\nP:13:1: note: trait 'Need' declared here\ntrait Need    # note - synthetic signature\n^\n"


def test_diagnostics_from_a_precompiled_package_use_synthetic_signatures():
    with tempfile.TemporaryDirectory() as d:
        pkg = os.path.join(d, 'pk')
        os.mkdir(pkg)
        open(os.path.join(pkg, '__init__.mojo'), 'w').write(PACKAGE)
        r = subprocess.run([sys.executable, FIRE, 'precompile', pkg, '-o',
                            os.path.join(d, 'pk.mojoc')], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        shutil.rmtree(pkg)
        m = os.path.join(d, 'm.mojo')
        open(m, 'w').write(MAIN)
        p = subprocess.run([sys.executable, FIRE, 'run', m],
                           capture_output=True, text=True, timeout=300)
        err = p.stderr.replace(os.path.join(d, 'pk', '__init__.mojo'), 'P').replace(m, 'M')
        assert p.returncode == 1 and err == WANT, err


if __name__ == '__main__':
    test_diagnostics_from_a_precompiled_package_use_synthetic_signatures()
    print('ok test_diagnostics_from_a_precompiled_package_use_synthetic_signatures')
    print('all tests passed')
