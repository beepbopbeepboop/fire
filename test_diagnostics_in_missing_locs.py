#!/usr/bin/env python3
"""Modular's test/mojo-integration/diagnostics_in_missing_locs.mojo, run the way
its RUN lines do: copy the package, precompile it, delete the source, then
compile the test and pipe the diagnostics through FileCheck against the test's
own CHECK lines (`--Werror`, as modular's lit substitution has it: the test
expects the deprecated-conversion diagnostic as an error). Skipped when the
modular checkout or FileCheck is not present."""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, 'fire.py')
MODULAR = '/Users/mrs/net/chatgpt/claude/modular/mojo/test/mojo-integration'
FILECHECK = '/opt/homebrew/opt/llvm/bin/FileCheck'


def main():
    test = os.path.join(MODULAR, 'diagnostics_in_missing_locs.mojo')
    if not (os.path.exists(test) and os.path.exists(FILECHECK)):
        print('skip: modular checkout or FileCheck not present')
        return
    with tempfile.TemporaryDirectory() as d:
        shutil.copytree(os.path.join(MODULAR, 'inputs', 'diags_package'),
                        os.path.join(d, 'diags_package'))
        shutil.copy(test, os.path.join(d, 'diagnostics_in_missing_locs.mojo'))
        r = subprocess.run([sys.executable, FIRE, 'precompile',
                            os.path.join(d, 'diags_package'), '-o',
                            os.path.join(d, 'diags_package.mojoc')],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        shutil.rmtree(os.path.join(d, 'diags_package'))
        p = subprocess.run([sys.executable, FIRE, '--Werror', 'run',
                            os.path.join(d, 'diagnostics_in_missing_locs.mojo')],
                           capture_output=True, text=True, timeout=600)
        assert p.returncode != 0, 'the test expects the compile to fail (not %mojo-build)'
        fc = subprocess.run([FILECHECK, test], input=p.stdout + p.stderr,
                            capture_output=True, text=True)
        assert fc.returncode == 0, fc.stderr[-3000:]
    print('ok diagnostics_in_missing_locs.mojo passes FileCheck')
    print('all tests passed')


if __name__ == '__main__':
    main()
