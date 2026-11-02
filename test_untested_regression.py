#!/usr/bin/env python3
"""Regressions for bug:UNTESTED (bug:UNTESTED)."""
import sys, importlib.util


# --- §3a: the mojo->fire rename fallout in test_mixed_cpp_link.py
def test_link_executable_default_still_gcc():
    # Before the fix this raised NameError: name 'mojo' is not defined
    # inside test_link_executable_default_still_gcc because it referenced mojo._GCC_BIN
    spec = importlib.util.spec_from_file_location("t", "test_mixed_cpp_link.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.test_link_executable_default_still_gcc()


# --- §3a: all eight files the rename hit must spell fire. (not stale mojo.)
def test_no_file_calls_stale_mojo_link_executable():
    # bugs/UNTESTED.md §3a: nine files still spelled `mojo.link_executable`
    # after the mojo→fire rename, eight of them hidden behind an `expect=`
    # marker that reported a false failure count. The fix is one word per
    # site; this pins that none of them regresses.
    import glob, re
    # Match an actual call/attribute access, not a comment or a docstring
    # mentioning the old name. A use is `mojo.<attr>` followed by `(` or
    # `.`; a citation in prose is followed by a space or punctuation.
    stale = re.compile(
        r"mojo\.(?:link_executable|_GCC_BIN|_GXX_BIN)(?:\(|\.|['\"])"
        r"|mock\.patch\('mojo\.subprocess\.run'\)"
    )
    bad = []
    for f in sorted(glob.glob("test_*.py")):
        src = open(f, encoding="utf-8").read()
        for lineno, line in enumerate(src.splitlines(), 1):
            code = line.split("#", 1)[0]  # strip trailing comments
            if stale.search(code):
                bad.append(f"{f}:{lineno}")
    assert not bad, f"files still calling the renamed module by its old name: {bad}"


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


# --- §3.3, general form: no test_*.py may print its failure and exit 0.
# A non-zero exit is the only verdict the gate reads, so a file that prints
# "FAIL" and then has no way to exit non-zero is a test that cannot fail.
import glob, re

_VERDICT_PRINT = re.compile(r"""print\(.*(?:\bFAIL|\bCFAIL\b|\bFailed\b|✗)""")
_EXIT_MECHANISM = re.compile(
    r"sys\.exit|\bexit\(|SystemExit|os\._exit|\braise\b|\bassert\b|"
    r"\bunittest\b|\bpytest\b|\.fail\(")


def silent_verdict_files(paths, source_of=lambda p: open(p, encoding="utf-8").read()):
    """Paths that print a failure verdict but have no exit mechanism at all."""
    bad = []
    for p in paths:
        src = source_of(p)
        if _VERDICT_PRINT.search(src) and not _EXIT_MECHANISM.search(src):
            bad.append(p)
    return bad


def test_silent_verdict_detector_flags_a_print_only_failure():
    # The detector must fire on the shape §3.3 describes, or the sweep below
    # proves nothing.
    shape = 'if x != y:\n    print("FAIL", x, y)\n'
    assert silent_verdict_files(["p.py"], source_of=lambda p: shape) == ["p.py"]
    # ...and must not fire when the failure also raises or exits.
    assert silent_verdict_files(["p.py"], source_of=lambda p: shape + "raise SystemExit(1)\n") == []
    assert silent_verdict_files(["p.py"], source_of=lambda p: shape + "sys.exit(1)\n") == []


def test_no_test_file_prints_a_failure_and_exits_zero():
    bad = silent_verdict_files(sorted(glob.glob("test_*.py")))
    assert not bad, f"print a failure verdict but have no exit mechanism: {bad}"


TESTS = [test_link_executable_default_still_gcc,
         test_no_file_calls_stale_mojo_link_executable,
         test_coro_bugs_source_line_accepts_backticked_path,
         test_coro_bugs_exit_code_is_the_verdict,
         test_silent_verdict_detector_flags_a_print_only_failure,
         test_no_test_file_prints_a_failure_and_exits_zero]

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
