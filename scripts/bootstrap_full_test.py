#!/usr/bin/env python3
"""
Full Bootstrap Test - Complete end-to-end testing and reporting

Executes all stages of bootstrap verification:
1. Determinism: Verify Stage 1 produces identical outputs
2. Validation: Verify generated C code is structurally valid
3. Metrics: Generate comprehensive statistics
4. Report: Create detailed test report
"""

import subprocess
import sys
from pathlib import Path
from time import time

def run_command(cmd, description):
    """Run a command and return success/failure."""
    print(f"Running: {description}...", end=" ", flush=True)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            print("✓")
            return True
        else:
            print(f"✗ ({result.stderr[:50]})")
            return False
    except Exception as e:
        print(f"✗ ({str(e)[:50]})")
        return False


def main():
    print("╔" + "═" * 78 + "╗")
    print("║" + " " * 16 + "MOJO BOOTSTRAP - FULL INTEGRATION TEST" + " " * 24 + "║")
    print("╚" + "═" * 78 + "╝")
    print()
    # `time.time()` and not `datetime.now().isoformat()`: this line is a
    # report header that identifies a run, and `datetime` was a
    # `HOST_MODELLED` row this file was ALONE in and cannot answer -- a
    # `datetime` is a six-field record and `.isoformat()` is a formatted one
    # (`bugs/FORMAL_time_struct_shaped_answers.md`). `time` is a module this
    # tree HAS. `run_stdlib_tests.py` says the same thing about the same
    # substitution, and `fault_tolerance.py:254` is the third site.
    print(f"Timestamp: {time()}")
    print()

    tests = [
        (['python3', 'scripts/bootstrap_verify.py'], "Phase verification (verify all tests pass)"),
        (['python3', 'scripts/bootstrap_test_runner.py'], "Test runner (auto-discover and test)"),
        (['python3', 'scripts/bootstrap_validate_c.py'], "C validation (verify GIMPLE structure)"),
        (['python3', 'scripts/bootstrap_metrics.py'], "Metrics (generate statistics)"),
    ]

    print("=" * 80)
    print("TEST EXECUTION")
    print("=" * 80)
    print()

    results = []
    for cmd, desc in tests:
        success = run_command(cmd, desc)
        results.append((desc, success))

    # Summary
    print()
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print()

    passed = sum(1 for _, s in results if s)
    total = len(results)

    for desc, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"  {desc:60s} {status}")

    print()
    print(f"Result: {passed}/{total} test suites passed")

    # Final status
    print()
    print("=" * 80)
    if passed == total:
        print("✓ BOOTSTRAP FULLY VERIFIED")
        print("=" * 80)
        print()
        print("All stages of bootstrap testing completed successfully:")
        print("  ✓ Phase verification passed")
        print("  ✓ Test execution passed")
        print("  ✓ C code validation passed")
        print("  ✓ Metrics generated")
        print()
        print("Bootstrap is ready for deployment on Mojo system.")
        return 0
    else:
        print("✗ BOOTSTRAP VERIFICATION FAILED")
        print("=" * 80)
        return 1


if __name__ == '__main__':
    sys.exit(main())
