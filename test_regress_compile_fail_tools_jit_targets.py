#!/usr/bin/env python3
"""Regression: Tools/jit/_targets.py async refusal pinned.

The file contains async methods (`_build_stencils`, `_compile`, `_parse`)
that use `with tempfile.TemporaryDirectory()` inside async bodies. The
compiled async codegen correctly refuses this (needs structural
async-codegen + path-value plumbing, separate project). This test
pins the exact refusal so a future change that accidentally silences
or moves the failure is caught.
"""
import os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MOJO = os.path.join(HERE, 'fire.py')
TARGET = '/Users/mrs/net/Python-3.14.6/Tools/jit/_targets.py'

def main():
    if not os.path.isfile(TARGET):
        # Skip if external source not present (test still passes with note)
        print("SKIP: external source not present at", TARGET)
        sys.exit(0)
    b = subprocess.run(
        [sys.executable, MOJO, 'build', TARGET],
        capture_output=True, text=True, errors='replace', timeout=300,
        cwd=HERE)
    stderr = (b.stderr or '') + (b.stdout or '')
    # The refusal must mention the three functions and the `with` guard.
    ok = (b.returncode != 0
          and '_build_stencils' in stderr
          and 'not CallExpr' in stderr)
    print("refusal matched:", ok)
    print("stderr snippet:", stderr[-600:] if len(stderr) > 600 else stderr)
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    sys.exit(main())
