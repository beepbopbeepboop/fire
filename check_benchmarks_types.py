#!/usr/bin/env python3
"""
Check failing benchmarks with type system to catch type violations.
"""

import os
import sys
from pathlib import Path

# Add mojo-reference to path
sys.path.insert(0, '/Users/mrs/claude/mojo-reference')

from gimple_codegen import GimpleGen
from mojo_compiler import tokenize, Parser

BENCHMARK_DIR = '/Users/mrs/claude/pyperformance/b'

# Common benchmarks to test
BENCHMARKS = [
    'bfib.py',
    'bfloat.py',
    'bmandel.py',
    'bmatmul.py',
    'bnbody.py',
    'bnqueens.py',
]

def compile_with_type_check(filepath):
    """Compile a file and report type system findings."""
    try:
        with open(filepath, 'r') as f:
            code = f.read()

        tokens = tokenize(code)
        stmts = Parser(tokens).parse_module()

        gen = GimpleGen()
        gimple = gen.gen_module(stmts)

        errors = []
        if gen.type_checker and gen.type_checker.has_errors():
            for error in gen.type_checker.error_log:
                errors.append((error.invariant, str(error)))

        return gimple is not None, errors, gen.type_checker
    except Exception as e:
        return False, [], str(e)


def main():
    print("=" * 80)
    print("TYPE SYSTEM CHECK: Failing Benchmarks")
    print("=" * 80)

    for bench_name in BENCHMARKS:
        filepath = os.path.join(BENCHMARK_DIR, bench_name)
        if not os.path.exists(filepath):
            print(f"\n⊘ {bench_name:20} - File not found")
            continue

        print(f"\n{'─' * 80}")
        print(f"📋 {bench_name}")
        print(f"{'─' * 80}")

        success, errors, checker = compile_with_type_check(filepath)

        if not success:
            print(f"❌ Compilation failed")
            continue

        if not errors:
            print(f"✅ No type system violations detected")
            if checker and hasattr(checker, 'variable_types'):
                print(f"   Type checks performed:")
                print(f"   - {len(checker.variable_types)} variables tracked")
                if hasattr(checker, 'locked_types'):
                    print(f"   - {len(checker.locked_types)} types locked for INFERENCE_IDEMPOTENCE")
        else:
            print(f"⚠️  TYPE SYSTEM VIOLATIONS FOUND: {len(errors)}")
            for invariant, error_msg in errors:
                print(f"\n   {invariant}:")
                # Print first 200 chars of error
                lines = error_msg.split('\n')[:3]
                for line in lines:
                    if line.strip():
                        print(f"   {line}")

    print(f"\n{'=' * 80}")
    print("TYPE SYSTEM CHECK COMPLETE")
    print("=" * 80)


if __name__ == '__main__':
    main()
