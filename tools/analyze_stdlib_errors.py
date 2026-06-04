#!/usr/bin/env python3
"""Analyze stdlib compilation errors and group them by type.

Usage:
    python analyze_stdlib_errors.py

This tool attempts to compile all Mojo stdlib files and categorizes any
parsing or compilation errors by type, making it easy to identify which
issues are most impactful.
"""

import os
import subprocess
import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
from module_loader import STDLIB_PATH
STDLIB_PATH = Path(STDLIB_PATH) / "std"

def transpile_file(mojo_file):
    """Transpile a single .mojo file and return error message if it fails."""
    try:
        with open(mojo_file, 'r') as f:
            source_code = f.read()

        proc = subprocess.run(
            ['python', 'mojo_compiler.py'],
            input=source_code,
            capture_output=True,
            cwd=REPO_ROOT,
            text=True,
            timeout=3
        )

        if proc.returncode != 0:
            # Extract error message
            lines = proc.stderr.split('\n')
            for line in reversed(lines):
                if "Error" in line or "SyntaxError" in line or "TypeError" in line:
                    return line.strip()
            return "Unknown error"
        return None  # Success

    except subprocess.TimeoutExpired:
        return "Timeout"
    except Exception as e:
        return str(e)

def main():
    stdlib_std_path = STDLIB_PATH.resolve()

    if not stdlib_std_path.exists():
        print(f"ERROR: stdlib path does not exist: {stdlib_std_path}")
        return

    # Find all mojo files
    mojo_files = sorted(stdlib_std_path.rglob("*.mojo"))

    errors = defaultdict(list)
    passing = []
    failing = []

    print(f"Analyzing {len(mojo_files)} stdlib files...")

    for i, mojo_file in enumerate(mojo_files):
        if (i + 1) % 50 == 0:
            print(f"  Processed {i+1}/{len(mojo_files)}...", flush=True)

        rel_path = mojo_file.relative_to(stdlib_std_path)
        error = transpile_file(mojo_file)

        if error is None:
            passing.append(rel_path)
        else:
            failing.append(rel_path)
            # Simplify error message
            error_simplified = error.replace("SyntaxError: ", "").replace("TypeError: ", "").split(" (")[0] if error else "Unknown"
            errors[error_simplified].append(rel_path)

    print("\n" + "="*70)
    print(f"Summary: {len(passing)} passing, {len(failing)} failing")
    print("="*70)

    print("\nTop error types (sorted by frequency):")
    for error_msg in sorted(errors.keys(), key=lambda k: -len(errors[k]))[:15]:
        count = len(errors[error_msg])
        pct = 100 * count / len(failing)
        print(f"  {count:2d} files ({pct:4.1f}%): {error_msg[:80]}")
        # Show first 2 files with this error
        for f in sorted(errors[error_msg])[:2]:
            print(f"       - {f}")
        if len(errors[error_msg]) > 2:
            print(f"       - ... and {len(errors[error_msg]) - 2} more")

    print(f"\nPassing rate: {len(passing)}/{len(mojo_files)} ({100*len(passing)//len(mojo_files)}%)")

if __name__ == '__main__':
    main()
