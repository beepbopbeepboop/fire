#!/usr/bin/env python3
"""A/B test: compare .ci output from Python path vs compiled native backend.

Usage:
    python3 test_ab_shim.py [file.mojo ...]

If no files given, tests a built-in set of small Mojo programs.
"""
import os
import sys
import subprocess
import tempfile
import shutil
import textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
MOJOC = os.path.join(HERE, 'mojoc')


def run_python_dump(src_path: str, out_dir: str) -> str:
    """Run python3 mojo.py --dump on src_path, return path to .ci file."""
    cmd = [sys.executable, os.path.join(HERE, 'mojo.py'), '--dump', src_path]
    subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, timeout=60)
    basename = os.path.splitext(os.path.basename(src_path))[0]
    ci_path = os.path.join(out_dir, f'{basename}.ci')
    return ci_path


def run_native_dump(src_path: str, out_dir: str) -> str:
    """Run MOJO_NO_SHIM=1 mojoc --dump on src_path, return path to .ci file."""
    env = os.environ.copy()
    env['MOJO_NO_SHIM'] = '1'
    cmd = [MOJOC, '--dump', src_path]
    result = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True,
                            timeout=120, env=env)
    if result.returncode != 0:
        print(f"  NATIVE STDERR: {result.stderr[:2000]}", file=sys.stderr)
    basename = os.path.splitext(os.path.basename(src_path))[0]
    ci_path = os.path.join(out_dir, f'{basename}.ci')
    return ci_path


def diff_ci_files(ci_a: str, ci_b: str) -> tuple:
    """Compare two .ci files. Return (match: bool, diff_summary: str)."""
    if not os.path.exists(ci_a):
        return False, f"Python .ci missing: {ci_a}"
    if not os.path.exists(ci_b):
        return False, f"Native .ci missing: {ci_b}"

    with open(ci_a) as f:
        lines_a = f.readlines()
    with open(ci_b) as f:
        lines_b = f.readlines()

    if lines_a == lines_b:
        return True, "IDENTICAL"

    # Find first differing line
    for i, (la, lb) in enumerate(zip(lines_a, lines_b)):
        if la != lb:
            break
    else:
        # One is prefix of the other
        i = min(len(lines_a), len(lines_b))

    # Show context around first diff
    start = max(0, i - 3)
    end = min(max(len(lines_a), len(lines_b)), i + 5)
    snippet = []
    for j in range(start, end):
        a = lines_a[j] if j < len(lines_a) else "<EOF>"
        b = lines_b[j] if j < len(lines_b) else "<EOF>"
        marker = " " if j < i else "≠" if a != b else " "
        snippet.append(f"{marker} L{j+1}:")
        snippet.append(f"  py: {a.rstrip()}")
        snippet.append(f"  nc: {b.rstrip()}")

    summary = f"DIFF at line {i+1} (out of {len(lines_a)}/{len(lines_b)} lines)"
    return False, summary + "\n" + "\n".join(snippet)


def test_inline_source(name: str, source: str):
    """Test an inline Mojo source snippet."""
    with tempfile.TemporaryDirectory() as td:
        src_file = os.path.join(td, f'{name}.mojo')
        with open(src_file, 'w') as f:
            f.write(source)

        py_dir = os.path.join(td, 'py')
        nc_dir = os.path.join(td, 'nc')
        os.makedirs(py_dir)
        os.makedirs(nc_dir)

        ci_py = run_python_dump(src_file, py_dir)
        ci_nc = run_native_dump(src_file, nc_dir)

        match, summary = diff_ci_files(ci_py, ci_nc)
        status = "PASS" if match else "FAIL"
        print(f"  {status}  {name}: {summary.splitlines()[0]}")
        if not match:
            print(f"         {summary}")
        return match


def test_file(path: str):
    """Test a .mojo file from disk."""
    name = os.path.splitext(os.path.basename(path))[0]
    with tempfile.TemporaryDirectory() as td:
        py_dir = os.path.join(td, 'py')
        nc_dir = os.path.join(td, 'nc')
        os.makedirs(py_dir)
        os.makedirs(nc_dir)

        ci_py = run_python_dump(path, py_dir)
        ci_nc = run_native_dump(path, nc_dir)

        match, summary = diff_ci_files(ci_py, ci_nc)
        status = "PASS" if match else "FAIL"
        print(f"  {status}  {name}: {summary.splitlines()[0]}")
        if not match:
            print(f"         {summary}")
        return match


# ── Built-in test cases ──────────────────────────────────────────────────

BUILTIN_TESTS = {
    "minimal_main": textwrap.dedent("""\
        def main():
            print(42)
    """),
    "arithmetic": textwrap.dedent("""\
        def main() -> Int:
            var x: Int = 10
            var y: Int = 32
            return x + y
    """),
    "function_def": textwrap.dedent("""\
        def add(a: Int, b: Int) -> Int:
            return a + b

        def main() -> Int:
            return add(20, 22)
    """),
    "if_else": textwrap.dedent("""\
        def main() -> Int:
            var x: Int = 5
            if x > 0:
                return 42
            else:
                return 0
    """),
    "list_ops": textwrap.dedent("""\
        def main() -> Int:
            var items = [1, 2, 3, 4, 5]
            var total = 0
            for i in range(len(items)):
                total = total + items[i]
            return total
    """),
    "string_ops": textwrap.dedent("""\
        def main():
            var s: String = "hello world"
            print(len(s))
    """),
}


def main():
    if not os.path.exists(MOJOC):
        print(f"ERROR: {MOJOC} not found. Build with: MOJO_NO_SHIM=1 python3 mojo.py build mojo.py -o mojoc", file=sys.stderr)
        sys.exit(1)

    passed = 0
    failed = 0

    # Test inline sources
    print("=" * 60)
    print("A/B SHIM TEST — Python vs compiled native backend")
    print("=" * 60)
    print()

    if len(sys.argv) > 1:
        # Test files from command line
        for path in sys.argv[1:]:
            if test_file(path):
                passed += 1
            else:
                failed += 1
    else:
        # Test built-in snippets
        for name, source in BUILTIN_TESTS.items():
            if test_inline_source(name, source):
                passed += 1
            else:
                failed += 1

        # Also test test_simple.mojo if it exists
        test_simple = os.path.join(HERE, 'test_simple.mojo')
        if os.path.exists(test_simple):
            print()
            if test_file(test_simple):
                passed += 1
            else:
                failed += 1

    print()
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
