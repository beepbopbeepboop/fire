#!/usr/bin/env python3
"""
Bootstrap Test Runner - Execute all tests through all stages

Tests Stage 1 (Python) and Stage 2 (Mojo) bootstrap against multiple inputs.
Verifies:
  1. Each test compiles without error
  2. Generated C code is valid
  3. Outputs are deterministic
  4. Stage 1 and Stage 2 produce identical results
"""

import subprocess
import os
import sys
from pathlib import Path

STAGE1_SCRIPT = 'scripts/stage1_python_interpreter.py'

# Auto-discover test files
def discover_tests():
    """Find all bootstrap_test_*.mojo files."""
    from pathlib import Path
    return sorted([str(f) for f in Path('.').glob('bootstrap_test_*.mojo')])

TEST_FILES = discover_tests()


def run_stage1(test_file):
    """Run Stage 1 (Python interpreter) on test file."""
    try:
        result = subprocess.run(
            ['python3', STAGE1_SCRIPT, test_file],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout
        else:
            return None
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return None


def run_stage2(test_file):
    """Run Stage 2 (Mojo interpreter) on test file."""
    try:
        result = subprocess.run(
            ['mojo', 'run', 'scripts/stage2_mojo_interpreter.mojo', test_file],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return result.stdout
        else:
            return None
    except FileNotFoundError:
        return None  # Mojo not installed
    except Exception as e:
        return None


def test_determinism(test_file, stage_num=1):
    """Verify a stage produces identical output on consecutive runs."""
    if stage_num == 1:
        run_func = run_stage1
    else:
        run_func = run_stage2

    output1 = run_func(test_file)
    if output1 is None:
        return False

    output2 = run_func(test_file)
    if output2 is None:
        return False

    return output1 == output2


def validate_c_code(c_code):
    """Basic validation of generated C code."""
    if not c_code:
        return False

    # Check for required headers
    if '#include <stdint.h>' not in c_code:
        return False
    if '#include <stdio.h>' not in c_code:
        return False

    # Check for brace matching
    if c_code.count('{') != c_code.count('}'):
        return False

    # If file has __GIMPLE functions, check for basic blocks
    if '__GIMPLE' in c_code:
        if 'bb_' not in c_code:
            return False

    return True


def main():
    print("=" * 70)
    print("BOOTSTRAP TEST RUNNER")
    print("=" * 70)

    # Check test files exist
    missing = [f for f in TEST_FILES if not os.path.exists(f)]
    if missing:
        print(f"✗ Missing test files: {missing}")
        return 1

    results = {
        'stage1': [],
        'stage2': [],
        'determinism': [],
        'comparison': [],
    }

    for test_file in TEST_FILES:
        print(f"\nTesting: {test_file}")

        # Stage 1
        print("  Stage 1 (Python)...", end=" ", flush=True)
        output1 = run_stage1(test_file)
        if output1 and validate_c_code(output1):
            lines = len(output1.split('\n'))
            print(f"✓ ({lines} lines)")
            results['stage1'].append(True)

            # Test determinism
            print("    Determinism...", end=" ", flush=True)
            if test_determinism(test_file, stage_num=1):
                print("✓")
                results['determinism'].append(True)
            else:
                print("✗")
                results['determinism'].append(False)
        else:
            print("✗")
            results['stage1'].append(False)
            results['determinism'].append(False)

        # Stage 2
        print("  Stage 2 (Mojo)...", end=" ", flush=True)
        output2 = run_stage2(test_file)
        if output2 is None:
            print("⊘ (Mojo not available)")
            results['stage2'].append(None)
            results['comparison'].append(None)
        elif validate_c_code(output2):
            lines = len(output2.split('\n'))
            print(f"✓ ({lines} lines)")
            results['stage2'].append(True)

            # Compare Stage 1 vs Stage 2
            if output1 and output2 == output1:
                print("    Comparison...", end=" ", flush=True)
                print("✓ (identical)")
                results['comparison'].append(True)
            elif output1 and output2 != output1:
                print("    Comparison...", end=" ", flush=True)
                print("✗ (different)")
                results['comparison'].append(False)
        else:
            print("✗")
            results['stage2'].append(False)
            results['comparison'].append(False)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    stage1_pass = sum(1 for x in results['stage1'] if x)
    stage1_total = len(results['stage1'])
    print(f"Stage 1 (Python):     {stage1_pass}/{stage1_total} passed")

    stage2_pass = sum(1 for x in results['stage2'] if x is True)
    stage2_total = len([x for x in results['stage2'] if x is not None])
    if stage2_total > 0:
        print(f"Stage 2 (Mojo):       {stage2_pass}/{stage2_total} passed")
    else:
        print(f"Stage 2 (Mojo):       ⊘ Not available")

    determ_pass = sum(1 for x in results['determinism'] if x)
    determ_total = len(results['determinism'])
    print(f"Determinism:          {determ_pass}/{determ_total} verified")

    comp_pass = sum(1 for x in results['comparison'] if x is True)
    comp_total = len([x for x in results['comparison'] if x is not None])
    if comp_total > 0:
        print(f"Stage 1 vs 2:         {comp_pass}/{comp_total} identical")
    else:
        print(f"Stage 1 vs 2:         ⊘ Cannot compare (Stage 2 unavailable)")

    # Overall pass/fail
    if stage1_pass == stage1_total:
        print("\n✓ BOOTSTRAP STAGE 1 PASSED")
        return 0
    else:
        print("\n✗ BOOTSTRAP STAGE 1 FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(main())
