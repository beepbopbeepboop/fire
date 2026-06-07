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
from pathlib import Path
from module_loader import STDLIB_PATH

# Subtrees of the stdlib to attempt, in the order we want maximal coverage:
# benchmarks first (smallest, exercises real client code), then the library
# proper, then the test corpus, then tools.
DEFAULT_ROOTS = ['benchmarks', 'std', 'test', 'tools']

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
    """
    Transpile a single .mojo file through mojo_compiler.py.

    Returns (success: bool, error_msg: str or None)
    """
    try:
        with open(mojo_file, 'r') as f:
            source_code = f.read()

        repo_root = Path(__file__).parent

        # Run mojo_compiler.py with timeout
        try:
            proc = subprocess.run(
                [sys.executable, 'mojo_compiler.py'],
                input=source_code,
                capture_output=True,
                cwd=repo_root,
                text=True,
                timeout=3
            )
            if proc.returncode != 0:
                # Find the actual error message (usually last line before traceback or the line with "Error:")
                lines = proc.stderr.split('\n')
                error_line = ""
                for line in reversed(lines):
                    if line.strip() and not line.startswith('  '):
                        error_line = line.strip()
                        break
                if not error_line:
                    error_line = lines[-2] if len(lines) > 1 else "unknown error"
                return False, f"{error_line[:120]}"

            # Check that compilation produced output (empty files are OK)
            if not proc.stdout.strip():
                # A file with no Mojo declarations (e.g. license-only __init__)
                # correctly produces no GIMPLE output — treat as success.
                import re
                stripped = re.sub(r'#[^\n]*', '', source_code).strip()
                if stripped:
                    return False, "mojo_compiler produced no output"

            return True, None

        except subprocess.TimeoutExpired:
            return False, "timeout (>3s)"

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

    if failed and len(failed) <= 20:
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
