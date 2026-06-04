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

def get_stdlib_path():
    """Return the path to the stdlib std directory."""
    stdlib_std_path = Path(STDLIB_PATH) / "std"
    return stdlib_std_path.resolve()

def find_mojo_files(base_path, module=None):
    """
    Find all .mojo files in stdlib.

    If module is specified, only search that module's subdirectory.
    Yields (relative_path, absolute_path) tuples.
    """
    base = Path(base_path)
    if not base.exists():
        print(f"Error: stdlib path not found: {base}", file=sys.stderr)
        return

    if module:
        module_path = base / module
        if not module_path.exists():
            print(f"Error: module path not found: {module_path}", file=sys.stderr)
            return
        search_root = module_path
    else:
        search_root = base

    for mojo_file in sorted(search_root.rglob("*.mojo")):
        rel_path = mojo_file.relative_to(base)
        yield (rel_path, mojo_file)

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
                ['python', 'mojo_compiler.py'],
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
    parser.add_argument('--module', default=None, help='Restrict to a specific module (e.g., time)')
    args = parser.parse_args()

    stdlib_std_path = get_stdlib_path()
    print(f"Stdlib path: {stdlib_std_path}")

    if not stdlib_std_path.exists():
        print(f"ERROR: stdlib path does not exist", file=sys.stderr)
        print(f"Expected: {stdlib_std_path}", file=sys.stderr)
        sys.exit(1)

    # Find .mojo files
    mojo_files = list(find_mojo_files(stdlib_std_path, args.module))
    if not mojo_files:
        print(f"No .mojo files found")
        if args.module:
            print(f"  (checked module: {args.module})")
        sys.exit(0)

    print(f"Found {len(mojo_files)} .mojo files\n")

    # Transpile each file
    passed = []
    failed = []

    for rel_path, abs_path in mojo_files:
        print(f"  {rel_path}...", end=" ", flush=True)
        success, error = transpile_file(abs_path)

        if success:
            print("OK")
            passed.append(rel_path)
        else:
            print("FAIL")
            failed.append((rel_path, error))

    # Print summary
    print("\n" + "="*70)
    print(f"Results: {len(passed)} passed, {len(failed)} failed")
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
