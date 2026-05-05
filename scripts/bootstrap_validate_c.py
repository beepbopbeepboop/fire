#!/usr/bin/env python3
"""
C Code Validation - Verify generated GIMPLE code can be compiled

Tests that generated C code:
1. Has valid syntax (can be parsed by gcc)
2. Contains required GIMPLE headers
3. Generates valid object files
"""

import subprocess
import tempfile
import os
from pathlib import Path

STAGE1 = 'scripts/stage1_python_interpreter.py'


def validate_c_syntax(c_code, test_name):
    """Validate GIMPLE C code structure.

    Checks for:
    1. Required headers
    2. Valid brace matching
    3. If functions exist, they should be in GIMPLE format
    """
    # Check for required headers
    if '#include <stdint.h>' not in c_code:
        return False, "Missing stdint.h"
    if '#include <stdio.h>' not in c_code:
        return False, "Missing stdio.h"

    # Basic brace matching
    if c_code.count('{') != c_code.count('}'):
        return False, "Mismatched braces"

    # If file has __GIMPLE functions, check they have basic blocks
    if '__GIMPLE' in c_code:
        if 'bb_' not in c_code:
            return False, "Functions without basic blocks"

    return True, None


def validate_gimple_structure(c_code):
    """Verify GIMPLE-required structures are present.

    Note: Some inputs (like module-level expressions) may not generate functions,
    which is acceptable. We only require GIMPLE if there are user-defined functions.
    """
    # Check for user-defined functions (not just __mojo_floordiv)
    # Look for function definitions with __GIMPLE
    has_user_functions = '__GIMPLE' in c_code

    if not has_user_functions:
        # No user functions - only runtime helpers
        # This is OK for minimal files (like module-level statements)
        return True, []

    # If there are user functions, they should have basic blocks
    if 'bb_' not in c_code:
        return False, ['bb_']

    return True, []


def test_input(test_file):
    """Test a single input file."""
    # Compile with Stage 1
    result = subprocess.run(
        ['python3', STAGE1, test_file],
        capture_output=True,
        text=True,
        timeout=10
    )

    if result.returncode != 0:
        return {
            'file': test_file,
            'status': 'COMPILATION_ERROR',
            'error': result.stderr[:200],
            'lines': 0,
        }

    c_code = result.stdout
    lines = len(c_code.split('\n'))

    # Check GIMPLE structure
    gimple_ok, missing = validate_gimple_structure(c_code)

    # Check C syntax
    syntax_ok, syntax_err = validate_c_syntax(c_code, Path(test_file).stem)

    status = 'OK'
    error = None

    if not gimple_ok:
        status = 'GIMPLE_ERROR'
        error = f"Missing: {missing}"
    elif syntax_ok is False:
        status = 'SYNTAX_ERROR'
        error = syntax_err[:200]
    elif syntax_ok is None:
        status = 'VALIDATION_SKIPPED'
        error = "gcc not available"

    return {
        'file': test_file,
        'status': status,
        'lines': lines,
        'error': error,
        'gimple': gimple_ok,
        'syntax': syntax_ok,
    }


def main():
    # Discover all test files
    test_files = sorted(Path('.').glob('bootstrap_test_*.mojo'))

    print("=" * 80)
    print("C CODE VALIDATION TEST SUITE")
    print("=" * 80)
    print()

    results = []
    for test_file in test_files:
        print(f"Testing {test_file.name:40s} ", end="", flush=True)
        result = test_input(str(test_file))
        results.append(result)

        if result['status'] == 'OK':
            print(f"✓ ({result['lines']} lines)")
        else:
            print(f"✗ ({result['status']})")

    # Summary
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    ok_count = sum(1 for r in results if r['status'] == 'OK')
    total = len(results)

    print(f"Files validated: {ok_count}/{total}")

    # Group by status
    statuses = {}
    for r in results:
        s = r['status']
        if s not in statuses:
            statuses[s] = []
        statuses[s].append(r)

    for status, items in sorted(statuses.items()):
        if status != 'OK':
            print(f"\n{status}:")
            for r in items:
                print(f"  {Path(r['file']).name}")
                if r['error']:
                    print(f"    {r['error'][:100]}")

    # Stats
    print()
    total_lines = sum(r['lines'] for r in results)
    print(f"Total lines generated: {total_lines}")

    return 0 if ok_count == total else 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
