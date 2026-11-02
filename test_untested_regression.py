#!/usr/bin/env python3
"""Regressions for bug:UNTESTED (bugs/UNTESTED.md)."""
import sys, importlib.util


# --- §3a: the mojo->fire rename fallout in test_mixed_cpp_link.py
def test_link_executable_default_still_gcc():
    # Before the fix this raised NameError: name 'mojo' is not defined
    # inside test_link_executable_default_still_gcc because it referenced mojo._GCC_BIN
    spec = importlib.util.spec_from_file_location("t", "test_mixed_cpp_link.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.test_link_executable_default_still_gcc()


# --- §3.3: test_coro_bugs.py, a diagnostic whose exit code was its only verdict
def test_coro_bugs_source_line_accepts_backticked_path():
    # Bug docs write `Source file: `/abs/path.py`` in backticks. The old pattern
    # kept the backtick, so os.path.exists() was false for every such doc and the
    # diagnostic silently diagnosed nothing.
    import test_coro_bugs
    m = test_coro_bugs.SRC_RE.search("Source file: `/x/y/analyzer.py`\n")
    assert m and m.group(1) == "/x/y/analyzer.py", m and m.group(1)


def test_coro_bugs_exit_code_is_the_verdict():
    import test_coro_bugs as t
    assert t.exit_code([]) == 2                       # nothing diagnosed: not green
    assert t.exit_code([("LOWERED", "a", "")]) == 0
    assert t.exit_code([("COMPILE", "a", ""), ("RAISE", "b", "")]) == 0
    assert t.exit_code([("LOWERED", "a", ""), ("CFAIL", "b", "")]) == 1


TESTS = [test_link_executable_default_still_gcc,
         test_coro_bugs_source_line_accepts_backticked_path,
         test_coro_bugs_exit_code_is_the_verdict]

if __name__ == '__main__':
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:
            failed += 1
            print(f"FAIL {fn.__name__}: {type(e).__name__}: {e}")
    print("PASS regression: fire references resolved, no NameError"
          if not failed else f"{failed} regression(s) failed")
    sys.exit(1 if failed else 0)
