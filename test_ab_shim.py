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


def run_python_dump(src_path: str, out_dir: str, flag: str = '--dump') -> str:
    """Run python3 fire.py <flag> on src_path, return path to .ci file.

    MUST run from the repo root (`cwd=HERE`), same as run_native_dump: the
    self-host AST-reflection injection is CWD-gated, so a run from a temp
    dir produces a different (shorter) .ci that is not comparable to the
    native one. Kept symmetric so the only variable is Python-path vs
    compiled backend. `flag` is '--dump' (do_imports=False, single-TU) or
    '--dump-full' (do_imports=True, transitive closure) — see
    test_dump_full_file's docstring for why the two need separate corpora.
    """
    src_path = os.path.abspath(src_path)
    cmd = [sys.executable, os.path.join(HERE, 'fire.py'), flag, src_path]
    subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=60)
    basename = os.path.splitext(os.path.basename(src_path))[0]
    here_ci = os.path.join(HERE, f'{basename}.ci')
    ci_path = os.path.join(out_dir, f'{basename}.ci')
    if os.path.exists(here_ci) and os.path.abspath(here_ci) != os.path.abspath(ci_path):
        shutil.move(here_ci, ci_path)
    return ci_path


def run_native_dump(src_path: str, out_dir: str, flag: str = '--dump') -> str:
    """Run MOJO_NO_SHIM=1 mojoc <flag> on src_path, return path to .ci file."""
    src_path = os.path.abspath(src_path)
    env = os.environ.copy()
    env['MOJO_NO_SHIM'] = '1'
    # The compiled binary's `__file__` is "<bootstrap>", so its self-host
    # detection (`_SELFHOST_DIR = dirname(abspath(__file__))`) resolves to the
    # process CWD. The self-host struct registration (AST nodes, interpreter
    # types) is gated on that, so mojoc MUST run from the repo root — from a
    # temp dir the gate is False and AST field access falls back to
    # mojo_obj_getattr -> segfault (Class D of the A/B divergence list).
    # MOJO_HOME is also set as a belt-and-suspenders (runtime project root).
    env['MOJO_HOME'] = HERE
    # File must come FIRST: the compiled binary's argv parser uses
    # sys.argv[1] as the input and strips '--dump'/'--dump-full' by
    # rebuilding the list (list.remove is broken in the compiled binary).
    cmd = [MOJOC, src_path, flag]
    result = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True,
                            timeout=120, env=env)
    if result.returncode != 0:
        print(f"  NATIVE STDERR: {result.stderr[:2000]}", file=sys.stderr)
    basename = os.path.splitext(os.path.basename(src_path))[0]
    ci_path = os.path.join(out_dir, f'{basename}.ci')
    # The binary writes the .ci to ITS cwd (HERE); move it to out_dir.
    here_ci = os.path.join(HERE, f'{basename}.ci')
    if os.path.exists(here_ci) and os.path.abspath(here_ci) != os.path.abspath(ci_path):
        import shutil
        shutil.move(here_ci, ci_path)
    return ci_path


def diff_ci_files(ci_a: str, ci_b: str) -> tuple:
    """Compare two .ci files. Return (match: bool, diff_summary: str)."""
    if not os.path.exists(ci_a):
        return False, f"Python .ci missing: {ci_a}"
    if not os.path.exists(ci_b):
        return False, f"Native .ci missing: {ci_b}"

    # Read as BYTES then decode latin-1: a native .ci can carry non-UTF-8
    # bytes (a miscompiled name), and a hard UnicodeDecodeError here would
    # mask the real, more useful "these two differ at line N" report.
    with open(ci_a, 'rb') as f:
        lines_a = f.read().decode('latin-1').splitlines(keepends=True)
    with open(ci_b, 'rb') as f:
        lines_b = f.read().decode('latin-1').splitlines(keepends=True)

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
    """Test an inline Mojo source snippet.

    The `.mojo` file is written INTO the repo root (not a temp dir): both
    dump paths' self-host/stdlib resolution is path-sensitive, and only a
    file that lives beside `fire.py` produces the full, comparable `.ci`.
    """
    src_file = os.path.join(HERE, f'_abt_{name}.mojo')
    with open(src_file, 'w') as f:
        f.write(source)
    try:
        with tempfile.TemporaryDirectory() as td:
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
    finally:
        for _p in (src_file, src_file[:-5] + '.ci'):
            if os.path.exists(_p):
                os.remove(_p)


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


def test_dump_full_multi(name: str, files: dict, driver: str):
    """Test a `--dump-full` (do_imports=True, transitive closure) sibling-
    import scenario: `files` maps {basename.mojo: source} for every sibling
    module, `driver` names the one to invoke mojo(c) on.

    Plain `--dump` (BUILTIN_TESTS above) is do_imports=False — a single
    translation unit that never calls `_compile_imported_module`, so it
    cannot exercise cross-module `from X import Y` resolution at all. A
    real regression (BUG: `from gimple_exprtypes import ...` inside
    gimple_gen_coro.py, and `from fire_compiler import (...)` inside
    gimple_gen_stmts.py, both reached only through the compiled backend's
    OWN `--dump-full` self-compile of fire.py) was invisible to the whole
    27-case `--dump` corpus for exactly this reason — see
    gimple_module_gen.py's `FromImportStmt` sibling-resolution loop (the
    `can_resolve_module_path` guard added alongside this test). These
    cases mirror that shape in miniature: a driver module importing a
    sibling that is itself not stdlib/test-resolvable, so `load_module`
    must fail cleanly (guarded) instead of raising uncaught on the
    compiled backend.

    Files are written INTO the repo root (not a temp dir), same
    path-sensitivity reason as test_inline_source.
    """
    written = []
    try:
        for basename, source in files.items():
            path = os.path.join(HERE, basename)
            with open(path, 'w') as f:
                f.write(source)
            written.append(path)
        driver_path = os.path.join(HERE, driver)
        with tempfile.TemporaryDirectory() as td:
            py_dir = os.path.join(td, 'py')
            nc_dir = os.path.join(td, 'nc')
            os.makedirs(py_dir)
            os.makedirs(nc_dir)

            ci_py = run_python_dump(driver_path, py_dir, flag='--dump-full')
            ci_nc = run_native_dump(driver_path, nc_dir, flag='--dump-full')

            match, summary = diff_ci_files(ci_py, ci_nc)
        status = "PASS" if match else "FAIL"
        print(f"  {status}  {name}: {summary.splitlines()[0]}")
        if not match:
            print(f"         {summary}")
        return match
    finally:
        for p in written:
            if os.path.exists(p):
                os.remove(p)
        driver_ci = os.path.join(HERE, os.path.splitext(driver)[0] + '.ci')
        if os.path.exists(driver_ci):
            os.remove(driver_ci)


# ── Built-in --dump-full sibling-import test cases ────────────────────────
# Each entry: name -> (files: {basename: source}, driver: basename).
DUMP_FULL_TESTS = {
    "sibling_from_import": (
        {
            "abfulltest_leaf.mojo": textwrap.dedent("""\
                def leaf_value() -> Int:
                    return 7
            """),
            "abfulltest_driver.mojo": textwrap.dedent("""\
                from abfulltest_leaf import leaf_value

                def main() -> Int:
                    return leaf_value() + 1
            """),
        },
        "abfulltest_driver.mojo",
    ),
    "sibling_from_import_multi_name": (
        {
            "abfulltest_leaf2.mojo": textwrap.dedent("""\
                def leaf_a() -> Int:
                    return 1

                def leaf_b() -> Int:
                    return 2
            """),
            "abfulltest_driver2.mojo": textwrap.dedent("""\
                from abfulltest_leaf2 import (leaf_a, leaf_b)

                def main() -> Int:
                    return leaf_a() + leaf_b()
            """),
        },
        "abfulltest_driver2.mojo",
    ),
    "transitive_sibling_from_import": (
        {
            "abfulltest_leaf3.mojo": textwrap.dedent("""\
                def leaf_value3() -> Int:
                    return 3
            """),
            "abfulltest_mid3.mojo": textwrap.dedent("""\
                from abfulltest_leaf3 import leaf_value3

                def mid_value() -> Int:
                    return leaf_value3() * 2
            """),
            "abfulltest_driver3.mojo": textwrap.dedent("""\
                from abfulltest_mid3 import mid_value

                def main() -> Int:
                    return mid_value() + 1
            """),
        },
        "abfulltest_driver3.mojo",
    ),
}


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
    "while_loop": textwrap.dedent("""\
        def main() -> Int:
            var i: Int = 0
            var total: Int = 0
            while i < 10:
                total = total + i
                i = i + 1
            return total
    """),
    "nested_func": textwrap.dedent("""\
        def outer(x: Int) -> Int:
            def inner(y: Int) -> Int:
                return y * 2
            return inner(x) + 1

        def main() -> Int:
            return outer(20)
    """),
    "struct_def": textwrap.dedent("""\
        struct Point:
            var x: Int
            var y: Int

        def main() -> Int:
            var p = Point(3, 4)
            return p.x + p.y
    """),
    "dict_ops": textwrap.dedent("""\
        def main() -> Int:
            var d = {"a": 1, "b": 2}
            return d["a"] + d["b"]
    """),
    "fstring": textwrap.dedent("""\
        def main():
            var x: Int = 42
            var s = f"value={x}"
            print(s)
    """),
    "aug_assign": textwrap.dedent("""\
        def main() -> Int:
            var x: Int = 5
            x += 3
            x *= 2
            return x
    """),
    "break_continue": textwrap.dedent("""\
        def main() -> Int:
            var total: Int = 0
            for i in range(10):
                if i == 2:
                    continue
                if i == 8:
                    break
                total = total + i
            return total
    """),
    "string_concat": textwrap.dedent("""\
        def main():
            var a: String = "foo"
            var b: String = "bar"
            print(a + b)
    """),
    "tuple_ops": textwrap.dedent("""\
        def main() -> Int:
            var t = (10, 20, 30)
            return t[0] + t[1] + t[2]
    """),
    "comprehension": textwrap.dedent("""\
        def main() -> Int:
            var items = [i * 2 for i in range(5)]
            var total = 0
            for x in items:
                total = total + x
            return total
    """),
    "class_methods": textwrap.dedent("""\
        class Counter:
            var count: Int

            fn __init__(inout self):
                self.count = 0

            fn inc(inout self):
                self.count += 1

            fn get(self) -> Int:
                return self.count

        def main() -> Int:
            var c = Counter()
            c.inc()
            c.inc()
            c.inc()
            return c.get()
    """),
    "try_except": textwrap.dedent("""\
        def main() -> Int:
            var x: Int = 0
            try:
                x = 5
            except:
                x = 0
            return x
    """),
    "match_stmt": textwrap.dedent("""\
        def main() -> Int:
            var x: Int = 2
            match x:
                case 1:
                    return 10
                case 2:
                    return 20
                case _:
                    return 0
    """),
    "global_var": textwrap.dedent("""\
        var counter: Int = 0

        def bump() -> Int:
            global counter
            counter += 1
            return counter

        def main() -> Int:
            bump()
            bump()
            return bump()
    """),
    "recursive": textwrap.dedent("""\
        def fib(n: Int) -> Int:
            if n <= 1:
                return n
            return fib(n - 1) + fib(n - 2)

        def main() -> Int:
            return fib(10)
    """),
    "closure": textwrap.dedent("""\
        def make_adder(n: Int):
            def add(x: Int) -> Int:
                return x + n
            return add

        def main() -> Int:
            var add5 = make_adder(5)
            return add5(37)
    """),
    "list_of_strings": textwrap.dedent("""\
        def main():
            var items = ["a", "b", "c"]
            for s in items:
                print(s)
    """),
    "string_methods": textwrap.dedent("""\
        def main():
            var s: String = "Hello World"
            print(s.lower())
            print(s.upper())
            print(s.replace("World", "Mojo"))
    """),
    "nested_loops": textwrap.dedent("""\
        def main() -> Int:
            var total: Int = 0
            for i in range(3):
                for j in range(3):
                    total = total + i * j
            return total
    """),
    "list_append": textwrap.dedent("""\
        def main() -> Int:
            var items = [1, 2, 3]
            items.append(4)
            items.append(5)
            var total = 0
            for x in items:
                total = total + x
            return total
    """),
    "dict_iterate": textwrap.dedent("""\
        def main() -> Int:
            var d = {"a": 1, "b": 2, "c": 3}
            var total = 0
            for v in d.values():
                total = total + v
            return total
    """),
}


def main():
    if not os.path.exists(MOJOC):
        print(f"ERROR: {MOJOC} not found. Build with: MOJO_NO_SHIM=1 python3 fire.py build fire.py -o mojoc", file=sys.stderr)
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

        # `--dump-full` (do_imports=True) sibling-import corpus — see
        # test_dump_full_multi's docstring for why this needs its own
        # section (plain `--dump` above never exercises cross-module
        # `from X import Y` resolution).
        print()
        for name, (files, driver) in DUMP_FULL_TESTS.items():
            if test_dump_full_multi(name, files, driver):
                passed += 1
            else:
                failed += 1

        # test_simple.mojo is a larger stretch program (nested def +
        # every collection literal + `raises` main); the native backend
        # still SEGVs on it. Reported for visibility but NOT counted as a
        # failure — the 27 BUILTIN_TESTS above are the byte-parity gate.
        test_simple = os.path.join(HERE, 'test_simple.mojo')
        if os.path.exists(test_simple):
            print()
            ok = test_file(test_simple)
            print(f"  (test_simple is an informational stretch case — "
                  f"{'matches' if ok else 'still diverges'}, not gated)")

    print()
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == '__main__':
    main()
