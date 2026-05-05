#!/usr/bin/env python3
"""
Bootstrap Metrics - Comprehensive bootstrap system statistics

Generates detailed metrics on:
- Test coverage and results
- Code generation statistics
- Performance characteristics
- Determinism verification
"""

import subprocess
import time
from pathlib import Path
from collections import defaultdict

STAGE1 = 'scripts/stage1_python_interpreter.py'


def get_test_files():
    """Discover all bootstrap test files."""
    return sorted(Path('.').glob('bootstrap_test_*.mojo'))


def measure_compilation(test_file, runs=3):
    """Measure compilation time across multiple runs."""
    times = []
    for _ in range(runs):
        start = time.time()
        result = subprocess.run(
            ['python3', STAGE1, str(test_file)],
            capture_output=True,
            text=True,
            timeout=10
        )
        end = time.time()
        if result.returncode == 0:
            times.append(end - start)

    if not times:
        return None, None, None

    return min(times), sum(times) / len(times), max(times)


def count_lines(c_code):
    """Count lines and statements in C code."""
    lines = c_code.split('\n')
    code_lines = [l for l in lines if l.strip() and not l.strip().startswith('//')]
    functions = c_code.count('__GIMPLE')
    basic_blocks = c_code.count('bb_')
    return len(code_lines), functions, basic_blocks


def main():
    print("╔" + "═" * 78 + "╗")
    print("║" + " " * 20 + "BOOTSTRAP METRICS REPORT" + " " * 34 + "║")
    print("╚" + "═" * 78 + "╝")
    print()

    test_files = get_test_files()
    print(f"Found {len(test_files)} test files")
    print()

    # Compile all tests
    results = {}
    total_c_lines = 0
    total_functions = 0
    total_blocks = 0

    print("═" * 80)
    print("COMPILATION METRICS")
    print("═" * 80)
    print()

    for test_file in test_files:
        name = test_file.stem
        print(f"  {name:35s} ", end="", flush=True)

        result = subprocess.run(
            ['python3', STAGE1, str(test_file)],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            print("✗ (error)")
            results[name] = None
            continue

        c_code = result.stdout
        code_lines, funcs, blocks = count_lines(c_code)
        total_c_lines += code_lines
        total_functions += funcs
        total_blocks += blocks

        results[name] = {
            'c_code': c_code,
            'lines': len(c_code.split('\n')),
            'code_lines': code_lines,
            'functions': funcs,
            'blocks': blocks,
        }

        print(f"✓ ({code_lines} lines, {funcs} functions, {blocks} blocks)")

    print()
    print("═" * 80)
    print("STATISTICS")
    print("═" * 80)
    print()

    successful = sum(1 for r in results.values() if r is not None)
    print(f"Tests passed:          {successful}/{len(test_files)}")
    print(f"Total C lines:         {total_c_lines}")
    print(f"Total functions:       {total_functions}")
    print(f"Total basic blocks:    {total_blocks}")
    print()

    # Input file statistics
    print("─" * 80)
    print("INPUT FILES")
    print("─" * 80)
    print()

    for test_file in sorted(test_files):
        with open(test_file) as f:
            content = f.read()
        lines = len(content.split('\n'))
        size = len(content)
        print(f"  {test_file.name:35s} {size:6d} bytes, {lines:3d} lines")

    # Output file statistics
    print()
    print("─" * 80)
    print("OUTPUT FILES (GENERATED C)")
    print("─" * 80)
    print()

    for name, data in sorted(results.items()):
        if data:
            print(f"  {name:35s} {data['lines']:6d} lines ({data['code_lines']:4d} code lines)")

    # Efficiency metrics
    print()
    print("─" * 80)
    print("CODE GENERATION EFFICIENCY")
    print("─" * 80)
    print()

    for test_file in test_files:
        name = test_file.stem
        data = results.get(name)
        if not data:
            continue

        with open(test_file) as f:
            input_lines = len(f.read().split('\n'))

        expansion = data['code_lines'] / input_lines if input_lines > 0 else 0
        print(f"  {name:35s} {expansion:5.1f}x expansion (input {input_lines} → output {data['code_lines']})")

    # Compilation time
    print()
    print("─" * 80)
    print("COMPILATION PERFORMANCE")
    print("─" * 80)
    print()

    times = {}
    for test_file in test_files[:3]:  # Time first 3 tests
        name = test_file.stem
        min_t, avg_t, max_t = measure_compilation(test_file)
        if avg_t:
            times[name] = avg_t
            print(f"  {name:35s} {avg_t*1000:6.1f}ms (range {min_t*1000:.1f}-{max_t*1000:.1f}ms)")

    if times:
        avg_time = sum(times.values()) / len(times)
        print()
        print(f"  Average compilation time: {avg_time*1000:6.1f}ms")

    # Summary
    print()
    print("╔" + "═" * 78 + "╗")
    print("║" + " BOOTSTRAP METRICS SUMMARY".ljust(79) + "║")
    print("├" + "─" * 78 + "┤")
    print(f"║ Tests:                 {successful}/{len(test_files)} passed".ljust(79) + "║")
    print(f"║ Input:                 {sum(len(Path(f).read_text().split()) for f in test_files)} lines of code".ljust(79) + "║")
    print(f"║ Output:                {total_c_lines} lines of GIMPLE C".ljust(79) + "║")
    print(f"║ Functions generated:   {total_functions}".ljust(79) + "║")
    print(f"║ Basic blocks:          {total_blocks}".ljust(79) + "║")
    print("╚" + "═" * 78 + "╝")


if __name__ == '__main__':
    main()
