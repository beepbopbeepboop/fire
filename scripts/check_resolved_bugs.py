#!/usr/bin/env python3
"""Scan remaining COMPILE_FAIL bug reports and remove those that now compile."""
import os, sys, glob, subprocess, shutil

BUGS_DIR = os.path.join(os.path.dirname(__file__) or '.', '..', 'bugs')
STDLIB_DIR = '/Users/mrs/net/Python-3.14.6'
sys.path.insert(0, os.path.join(os.path.dirname(__file__) or '.', '..'))

from gimple_codegen import compile_to_gimple

def module_path(name: str) -> str | None:
    """Map a bug-report module name to its source .py path."""
    # Direct Lib/ match
    for base in (STDLIB_DIR,):
        path = os.path.join(base, 'Lib', f'{name}.py')
        if os.path.exists(path): return path
        path = os.path.join(base, 'Lib', name.replace('_', '/'), '__init__.py')
        if os.path.exists(path): return path
    # All known directories under STDLIB
    for root, dirs, files in os.walk(STDLIB_DIR):
        for f in files:
            if f == f'{name}.py':
                return os.path.join(root, f)
            if f == '__init__.py' and os.path.basename(root) == name.split('_')[-1]:
                return os.path.join(root, f)
    return None

def ci_name(py_path: str) -> str:
    """Map a .py path to a unique .ci filename."""
    rel = os.path.relpath(py_path, STDLIB_DIR)
    return rel.replace('/', '_').replace('.py', '') + '.ci'

def try_compile(py_path: str) -> bool:
    """Try to compile a .py file to .ci and gcc-check it."""
    ci = ci_name(py_path)
    ci_path = os.path.join(os.path.dirname(BUGS_DIR), ci)
    try:
        src = open(py_path).read()
        c_code = compile_to_gimple(src, do_imports=False, filename=os.path.basename(py_path))
        open(ci_path, 'w').write(c_code)
    except Exception:
        return False
    # gcc -fsyntax-only check
    r = subprocess.run(
        ['/opt/local/bin/gcc-mp-15', '-fgimple', '-I', os.path.join(os.path.dirname(BUGS_DIR), 'runtime'),
         '-fsyntax-only', '-x', 'c', ci_path],
        capture_output=True, text=True, timeout=60)
    return r.returncode == 0

def main():
    os.chdir(os.path.dirname(BUGS_DIR))
    bug_files = sorted(glob.glob(os.path.join(BUGS_DIR, 'COMPILE_FAIL_*.md')))
    removed = 0
    for bf in bug_files:
        name = os.path.basename(bf)
        # Extract module name from bug filename
        # Format: COMPILE_FAIL_<module>.md or COMPILE_FAIL_Lib_<module>_<suffix>.md
        stem = name.replace('COMPILE_FAIL_', '').replace('.md', '')
        # Try to find the source file
        py_path = module_path(stem.split('_')[0])
        if py_path is None:
            # Try extracting first meaningful part
            parts = stem.split('_')
            for i in range(1, len(parts)+1):
                candidate = '_'.join(parts[:i])
                py_path = module_path(candidate)
                if py_path: break
        if py_path and try_compile(py_path):
            os.remove(bf)
            print(f'REMOVED {name}')
            removed += 1
        else:
            print(f'KEPT    {name}')
    # Cleanup .ci files
    for f in glob.glob('*.ci'):
        os.remove(f)
    print(f'\nRemoved {removed} bug files')

if __name__ == '__main__':
    main()
