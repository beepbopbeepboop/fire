#!/usr/bin/env python3
"""Regression test for compile-time `constrained(cond, msg)` (paren form).

The paren spelling of Mojo's builtin `constrained` must be enforced in
statement position in both the compiled (gimple) path and the interpreter,
matching the bracket form `constrained[cond, msg]()`:
- a provably-false condition fails with `constraint failed: <msg>`
- a true or unknown condition is a no-op
- a user-defined `constrained` shadows the builtin
"""

import os
import subprocess
import sys
import tempfile

from gimple_codegen import compile_to_gimple

HERE = os.path.dirname(os.path.abspath(__file__))
MOJO = os.path.join(HERE, "fire.py")


def _compile(src, filename="t.mojo"):
    return compile_to_gimple(src, do_imports=False, filename=filename)


def run_program(source: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "prog.mojo")
        with open(path, "w") as f:
            f.write(source)
        proc = subprocess.run(
            [sys.executable, MOJO, "run", path],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc.returncode, proc.stderr


def build_program(source: str):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "prog.mojo")
        out = os.path.join(tmp, "prog")
        with open(path, "w") as f:
            f.write(source)
        proc = subprocess.run(
            [sys.executable, MOJO, "build", path, "-o", out],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc.returncode, proc.stderr + proc.stdout


# --- gimple / compiled path ---

def test_paren_false_statement_gimple():
    try:
        _compile('fn f():\n    constrained(False, "nope")\n')
    except RuntimeError as e:
        s = str(e)
        assert "constraint failed" in s, s
        assert "nope" in s, s
        return
    raise AssertionError("provably-false paren constrained statement compiled without error")


def test_paren_false_statement_build():
    rc, out = build_program(
        'fn f():\n    constrained(False, "nope")\nfn main():\n    f()\n'
    )
    assert rc != 0, f"fire.py build accepted false paren constrained (rc={rc}): {out}"
    assert "constraint failed: nope" in out, out


def test_paren_true_statement_gimple():
    _compile('fn f():\n    constrained(True, "ok")\n')


def test_paren_unknown_statement_gimple():
    _compile('fn f[x: Int]():\n    constrained(x > 0, "ok")\n')


def test_paren_shadowing_gimple():
    # A module-defined constrained must keep its own function (no interception).
    src = (
        "fn constrained(cond: Bool, msg: String):\n"
        "    pass\n"
        "fn f():\n"
        '    constrained(False, "nope")\n'
    )
    _compile(src)


# --- interpreter path ---

def test_paren_false_interpreter():
    rc, err = run_program(
        'fn main():\n'
        '    constrained(False, "nope")\n'
    )
    assert rc != 0, f"interpreter accepted false paren constrained (rc={rc})"
    assert "constraint failed: nope" in err, err
    assert "NameError" not in err, err


def test_paren_false_no_msg_interpreter():
    rc, err = run_program(
        'fn main():\n'
        '    constrained(False)\n'
    )
    assert rc != 0, f"interpreter accepted false paren constrained with no msg (rc={rc})"
    assert "constraint failed" in err, err


def test_paren_true_interpreter():
    rc, err = run_program(
        'fn main():\n'
        '    constrained(True, "ok")\n'
        '    print("after")\n'
    )
    assert rc == 0, f"interpreter rejected true paren constrained (rc={rc} stderr={err})"
    assert "constraint failed" not in err, err


def test_paren_shadowing_interpreter():
    rc, err = run_program(
        'fn constrained(cond: Bool, msg: String):\n'
        '    print("user")\n'
        'fn main():\n'
        '    constrained(False, "nope")\n'
    )
    assert rc == 0, f"user-defined constrained was intercepted (rc={rc} stderr={err})"
    assert "constraint failed" not in err, err


# --- existing forms unchanged ---

def test_bracket_form_unchanged():
    try:
        _compile('fn f():\n    constrained[False, "nope"]()\n')
    except RuntimeError as e:
        assert "constraint failed" in str(e), e
        assert "nope" in str(e), e
    else:
        raise AssertionError("bracket constrained[False] changed behaviour")

    rc, err = run_program('fn main():\n    constrained[False, "nope"]()\n')
    assert rc != 0, f"interpreter bracket constrained changed behaviour (rc={rc})"
    assert "constraint failed: nope" in err, err


def test_comptime_assert_unchanged():
    try:
        _compile('fn f():\n    comptime assert False, "nope"\n')
    except RuntimeError as e:
        assert "nope" in str(e) or "assert" in str(e).lower(), e
    else:
        raise AssertionError("comptime assert changed behaviour")


def test_value_position_paren_unchanged():
    try:
        _compile('fn f():\n    var x = constrained(False, "nope")\n')
    except RuntimeError as e:
        assert "constraint failed" in str(e), e
        assert "nope" in str(e), e
    else:
        raise AssertionError("value-position paren constrained changed behaviour")


if __name__ == "__main__":
    test_paren_false_statement_gimple()
    test_paren_false_statement_build()
    test_paren_true_statement_gimple()
    test_paren_unknown_statement_gimple()
    test_paren_shadowing_gimple()
    test_paren_false_interpreter()
    test_paren_false_no_msg_interpreter()
    test_paren_true_interpreter()
    test_paren_shadowing_interpreter()
    test_bracket_form_unchanged()
    test_comptime_assert_unchanged()
    test_value_position_paren_unchanged()
    print("ok")
