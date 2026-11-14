#!/usr/bin/env python3
"""Regression: imported decorators (from X import deco; @deco) must be applied.

See bugs/hard/COMPILE_FAIL_decorator_application_dropped.md (imported arm)."""
import subprocess, tempfile, os, sys

def test_imported_decorator_applied():
    with tempfile.TemporaryDirectory() as td:
        with open(os.path.join(td, 'deco.py'), 'w') as f:
            f.write('def twice(f):\n    def wrap(x):\n        return f(x) * 2\n    return wrap\n')
        with open(os.path.join(td, 'main.py'), 'w') as f:
            f.write('from deco import twice\n\n@twice\ndef step(x):\n    return x + 1\n\nprint(step(7))\n')
        r = subprocess.run([sys.executable, os.path.join(os.getcwd(), 'fire.py'), 'build', '-o', 'main', 'main.py'],
                           cwd=td, capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, f'build failed: {r.stderr[-500:]}'
        run = subprocess.run([os.path.join(td, 'main')], capture_output=True, text=True, timeout=60)
        assert run.stdout.strip() == '16', f'expected 16, got {run.stdout!r} err={run.stderr!r}'
    print('PASS test_imported_decorator_applied')

if __name__ == '__main__':
    test_imported_decorator_applied()
    print('ALL PASS')
