#!/usr/bin/env python3
"""
Attempts to transpile all (or a specific) Mojo stdlib module(s) through gimple_codegen.

Usage:
  python compile_stdlib.py                 # attempt entire stdlib
  python compile_stdlib.py --module time   # attempt only the time module
"""

import os
import sys
import subprocess
import argparse
import tempfile
from pathlib import Path
from module_loader import STDLIB_PATH
from build_config import find_gcc
from build_stdlib_dylib import compile_module_to_c

_GCC = find_gcc()
_RUNTIME_INC = str(Path(__file__).parent / 'runtime')

# Subtrees of the stdlib to attempt, in the order we want maximal coverage:
# benchmarks first (smallest, exercises real client code), then the library
# proper, then the test corpus, then tools.
DEFAULT_ROOTS = ['_core', 'collections', 'io', 'math', 'os']

def get_stdlib_path():
    """Return the path to the stdlib root directory (parent of std/, test/, ...)."""
    return Path(STDLIB_PATH).resolve()

def find_mojo_files(base_path, roots=None, module=None):
    """
    Find all .mojo files in the stdlib subtrees named in `roots`.

    If `module` is specified, only search that module's subdirectory under std/.
    Paths are yielded relative to the stdlib root so display shows e.g.
    "benchmarks/...", "std/...", "test/...".
    Yields (relative_path, absolute_path) tuples.
    """
    base = Path(base_path)
    if not base.exists():
        print(f"Error: stdlib path not found: {base}", file=sys.stderr)
        return

    if module:
        module_path = base / "std" / module
        if not module_path.exists():
            print(f"Error: module path not found: {module_path}", file=sys.stderr)
            return
        for mojo_file in sorted(module_path.rglob("*.mojo")):
            yield (mojo_file.relative_to(base), mojo_file)
        return

    for root in (roots or DEFAULT_ROOTS):
        search_root = base / root
        if not search_root.exists():
            continue
        for mojo_file in sorted(search_root.rglob("*.mojo")):
            yield (mojo_file.relative_to(base), mojo_file)

def transpile_file(mojo_file):
    """Compile a .mojo file through codegen → GCC -fgimple -fsyntax-only.

    Uses compile_module_to_c (emit_entry_points=False, path-relative name) — the
    same codegen path as build_stdlib_dylib — so results agree with the dylib build.
    Returns (success, msg).
    """
    try:
        src = open(mojo_file).read()
        rel = os.path.relpath(mojo_file, STDLIB_PATH)
        name = os.path.splitext(rel)[0].replace(os.sep, '_').replace('-', '_')

        # Stage 1: Python codegen
        try:
            c_src = compile_module_to_c(src, str(mojo_file), name)
        except Exception as e:
            return False, f"codegen: {str(e)[:120]}"

        if not c_src.strip():
            return True, None  # nothing to compile (empty/comment-only file)

        # Stage 2: GCC syntax check
        with tempfile.NamedTemporaryFile(suffix='.c', mode='w', delete=False) as tf:
            tf.write(c_src)
            cpath = tf.name
        try:
            r = subprocess.run(
                [_GCC, '-fgimple', f'-I{_RUNTIME_INC}', '-fsyntax-only',
                 '-D__MOJO_STDLIB_MODE__', '-x', 'c', cpath],
                capture_output=True, text=True, timeout=10,
            )
        except subprocess.TimeoutExpired:
            return False, "timeout in gcc (>10s)"
        finally:
            os.unlink(cpath)

        if r.returncode != 0:
            first_err = next((l for l in r.stderr.splitlines()
                              if ': error:' in l), r.stderr.splitlines()[0] if r.stderr else '')
            return False, f"gcc: {first_err[:120]}"

        return True, None

    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:100]}"

def main():
    parser = argparse.ArgumentParser(description="Attempt to transpile Mojo stdlib")
    parser.add_argument('--module', default=None, help='Restrict to a specific module under std/ (e.g., time)')
    parser.add_argument('--roots', default=None,
                        help='Comma-separated subtrees to scan (default: %s)' % ','.join(DEFAULT_ROOTS))
    args = parser.parse_args()

    roots = [r.strip() for r in args.roots.split(',')] if args.roots else DEFAULT_ROOTS

    stdlib_root = get_stdlib_path()
    print(f"Stdlib path: {stdlib_root}")
    if not args.module:
        print(f"Scanning roots: {', '.join(roots)}")

    if not stdlib_root.exists():
        print(f"ERROR: stdlib path does not exist", file=sys.stderr)
        print(f"Expected: {stdlib_root}", file=sys.stderr)
        sys.exit(1)

    # Find .mojo files
    mojo_files = list(find_mojo_files(stdlib_root, roots=roots, module=args.module))
    if not mojo_files:
        print(f"No .mojo files found")
        if args.module:
            print(f"  (checked module: {args.module})")
        sys.exit(0)

    print(f"Found {len(mojo_files)} .mojo files\n")

    # Transpile each file
    passed = []
    failed = []

    for i, (rel_path, abs_path) in enumerate(mojo_files):
        success, error = transpile_file(abs_path)

        if success:
            passed.append(rel_path)
        else:
            print(f"  {rel_path}...FAIL")
            failed.append((rel_path, error))

        if (i + 1) % 50 == 0 or (i + 1) == len(mojo_files):
            print(f"\r  Progress: {len(passed)} passed, {len(failed)} failed", end="", flush=True)

    # Print summary
    print("\n" + "="*70)
    print(f"PASSED: {len(passed)}")
    print(f"FAILED: {len(failed)}")
    print("="*70)

    if failed:
        print("\nFailed files:")
        for rel_path, error in failed:
            print(f"  {rel_path}")
            if error:
                print(f"    → {error}")

    if passed and len(passed) <= 10:
        print(f"\nPassed files:")
        for rel_path in passed:
            print(f"  {rel_path}")

    sys.exit(0 if not failed else 1)

if __name__ == '__main__':
    main()
