#!/usr/bin/env python3
"""Regression: CPython 3.15's "improved error messages" for AttributeError.

What's New in Python 3.15 (the subject of
bugs/PYTHON3.15_improved_error_messages.md): an UNCAUGHT AttributeError is
printed with a suggestion — the static cross-language/wrong-type table
(`[1,2,3].push(4)` -> `Did you mean '.append'?`), Levenshtein close matches
(`s.lwer()` -> `Did you mean '.lower' instead of '.lwer'?`), and one-level
nested members (`container.area` -> `Did you mean '.inner.area' instead of
'.area'?`). CPython computes the suggestion at PRINT time from two fields
the exception carries — `name` and `obj` — so a caught AttributeError stays
plain. This file pins both halves of that contract in our compiler:

  * the RAISE half (myinterpreter._tag_attribute_error): every
    missing-attribute AttributeError carries `name`/`obj`;
  * the PRINT half (myinterpreter.attribute_error_suggestion, called from
    fire.py's top-level error printing): the exact 3.15.2 suffixes.

Before the fix, `python3 fire.py run` on `x.push(4)` printed the bare
`'list' object has no attribute 'push'` with no suggestion, and the raised
exception carried no `name`/`obj` at all.
"""

import os
import re
import subprocess
import sys
import tempfile

import fire_compiler as N
from myinterpreter import Interpreter, MojoInstance, attribute_error_suggestion

HERE = os.path.dirname(os.path.abspath(__file__))


def run_interp(source: str):
    """Execute `source` in-process; return the uncaught AttributeError, or
    None if it ran to completion."""
    mod = N.Module(body=N.Parser(N.py_tokenize(source)).parse_module())
    interp = Interpreter()
    try:
        interp.execute(mod)
        return None
    except AttributeError as e:
        return e


def fire_run(source: str):
    """Run `source` through the CLI (`fire.py run`), the top-level error
    printing this regression is about. Returns (stdout, stderr, exit)."""
    fd, path = tempfile.mkstemp(suffix='.mojo', dir=HERE)
    with os.fdopen(fd, 'w') as f:
        f.write("def main():\n")
        for line in source.strip().splitlines():
            f.write("    " + line + "\n")
    try:
        r = subprocess.run([sys.executable, os.path.join(HERE, "fire.py"),
                            "run", path],
                           capture_output=True, text=True, cwd=HERE)
    finally:
        os.unlink(path)
    return r.stdout, r.stderr, r.returncode


def suggestion_suffix_of(stderr: str, name: str):
    """The text CPython appends after `... has no attribute '<name>'` on the
    final `AttributeError:` line — '' when it appends nothing."""
    lines = [l for l in stderr.splitlines()
             if l.startswith("AttributeError:")]
    if not lines:
        return None
    last = lines[-1]
    m = re.search(r"no attribute '" + re.escape(name) + r"'", last)
    if not m:
        return None
    return last[m.end():].strip()


# ---------------------------------------------------------------- the RAISE
# half: the exception carries name/obj and its message stays plain

def test_raise_half_host_object():
    e = run_interp("x = [1, 2, 3]\nx.push(4)")
    assert e is not None, "x.push(4) must raise AttributeError"
    assert getattr(e, 'name', None) == 'push', \
        f"exception must carry name='push', got {getattr(e, 'name', None)!r}"
    assert isinstance(getattr(e, 'obj', None), list) \
        and getattr(e, 'obj', None) == [1, 2, 3], \
        "exception must carry the list it failed on"
    assert "Did you mean" not in str(e), \
        f"caught/unprinted message must stay plain, got {e!s}"


def test_raise_half_mojo_instance():
    e = run_interp(
        "class C:\n"
        "    def __init__(self):\n"
        "        self.k = 9\n"
        "c = C()\nc.nope_xyz")
    assert e is not None, "c.nope_xyz must raise AttributeError"
    assert getattr(e, 'name', None) == 'nope_xyz'
    obj = getattr(e, 'obj', None)
    assert isinstance(obj, MojoInstance), \
        f"exception must carry the MojoInstance it failed on, got {type(obj)}"
    assert "nope_xyz" in str(e)


def test_suggestion_suffixes():
    s = attribute_error_suggestion
    # cross-language table (CPython 3.15.2's exact renderings)
    assert s([1, 2, 3], 'push') == ". Did you mean '.append'?"
    assert s('hello', 'toUpperCase') == ". Did you mean '.upper'?"
    assert s({}, 'put') == ". Use d[k] = v."
    assert s((1, 2), 'append') == ". Did you mean to use a 'list' object?"
    assert s(frozenset([1]), 'discard') == ". Did you mean to use a 'set' object?"
    # Levenshtein close match
    assert s('HELLO', 'lwer') == ". Did you mean '.lower' instead of '.lwer'?"
    # no match -> nothing appended
    assert s({1, 2}, 'push') == ""
    assert s(range(3), 'push') == ""
    # None object (no context) -> nothing, no crash
    assert s(None, 'push') == ""


def test_suggestion_nested_member():
    # What's New in 3.15's example: the missing attribute lives on a MEMBER
    class Inner:
        area = 5
    class Outer:
        pass
    outer = Outer()
    outer.inner = Inner()
    assert attribute_error_suggestion(outer, 'area') == \
        ". Did you mean '.inner.area' instead of '.area'?"
    # and through the interpreter's own tag on a MojoInstance
    e = run_interp(
        "class Circle:\n"
        "    def __init__(self):\n"
        "        self.radius = 1.0\n"
        "    def area(self):\n"
        "        return 3.14\n"
        "class Container:\n"
        "    def __init__(self, inner):\n"
        "        self.inner = inner\n"
        "c = Container(Circle())\nc.area")
    assert e is not None
    assert attribute_error_suggestion(getattr(e, 'obj', None),
                                      getattr(e, 'name', None)) == \
        ". Did you mean '.inner.area' instead of '.area'?"


def test_suggestion_nonascii_close_match():
    # The non-ASCII halves of the 3.15.2 renderings: `!a` (ascii()) in
    # parentheses on both names when the SUGGESTION is non-ASCII, the plain
    # rendering when only the misspelling is. CPython's matcher is two-
    # passed (C byte pass, then code-point fallback) and the fallback is
    # what finds 'caf' -> 'café' (byte distance 4 misses the byte window 3,
    # code-point distance 2 passes the code-point window 3).
    class Holder:
        héllo = 1
        wörld = 2
        café = 3
        push = 4
    h = Holder()
    assert attribute_error_suggestion(h, 'caf') == \
        ". Did you mean '.café' ('caf\\xe9') instead of '.caf' ('caf')?"
    assert attribute_error_suggestion(h, 'hèllo') == \
        ". Did you mean '.héllo' ('h\\xe9llo') instead of '.hèllo' ('h\\xe8llo')?"
    # suggestion ASCII, name non-ASCII -> plain rendering, no parens
    assert attribute_error_suggestion(h, 'pγsh') == \
        ". Did you mean '.push' instead of '.pγsh'?"
    # no close match -> nothing (the non-ASCII name must not invent one)
    assert attribute_error_suggestion(h, 'zzz') == ""


def test_suggestion_nested_underscored_no_false_positive():
    # CPython's nested check only looks at NON-underscored outer members,
    # even when the failing name is underscored: on object(), the class
    # does carry `__static_attributes__`, but the underscored `__class__`
    # outer attribute is out of scope, so nothing is suggested.
    assert attribute_error_suggestion(object(), '__static_attributes__') == ""


# ------------------------------------------------------------- the PRINT
# half: `fire.py run`'s top-level error printing

def test_end_to_end_uncaught_shows_suggestion():
    out, err, rc = fire_run("x = [1, 2, 3]\nx.push(4)")
    assert rc == 1, f"uncaught AttributeError must exit 1, got {rc}"
    suffix = suggestion_suffix_of(err, 'push')
    assert suffix == ". Did you mean '.append'?", \
        f"final AttributeError line must carry the 3.15 suggestion, got {suffix!r}"
    err_lines = [l for l in err.splitlines() if l.startswith("Error:")]
    assert err_lines and ". Did you mean '.append'?" in err_lines[0], \
        f"`Error:` line must agree with the final line, got {err_lines}"


def test_end_to_end_nested_member():
    out, err, rc = fire_run(
        "class Circle:\n"
        "    def __init__(self):\n"
        "        self.radius = 1.0\n"
        "    def area(self):\n"
        "        return 3.14\n"
        "class Container:\n"
        "    def __init__(self, inner):\n"
        "        self.inner = inner\n"
        "c = Container(Circle())\nc.area")
    assert rc == 1
    assert suggestion_suffix_of(err, 'area') == \
        ". Did you mean '.inner.area' instead of '.area'?"


def test_end_to_end_no_false_suggestion():
    out, err, rc = fire_run("s = {1, 2}\ns.push(3)")
    assert rc == 1
    assert suggestion_suffix_of(err, 'push') == "", \
        "set.push has no 3.15 suggestion; nothing may be invented"


def test_end_to_end_caught_stays_plain():
    # CPython 3.15 measures the same split: the suggestion is a print-time
    # thing, so an AttributeError caught in user code prints plain.
    out, err, rc = fire_run(
        "x = [1, 2, 3]\n"
        "try:\n"
        "    x.push(4)\n"
        "except AttributeError as e:\n"
        "    print('caught:', e)")
    assert rc == 0, f"caught case must exit 0, got {rc}\n{err}"
    assert "has no attribute 'push'" in out, f"stdout: {out!r}"
    assert "Did you mean" not in out, f"caught message must stay plain: {out!r}"
    assert "Did you mean" not in err, f"no suggestion may leak: {err!r}"


def test_end_to_end_other_exceptions_unchanged():
    out, err, rc = fire_run("x = 1 // 0\nprint(x)")
    assert rc == 1
    assert "Error: division by zero" in err
    assert "Did you mean" not in err


# ------------------------------------------------- parity with CPython 3.15

def test_parity_with_cpython_315():
    if sys.version_info < (3, 15):
        print(f"  (skipped: host is {sys.version.split()[0]}, not 3.15+)")
        return
    for name, src in [
        ('list.push', "x = [1, 2, 3]\nx.push(4)"),
        ('dict.put', "d = {}\nd.put('a', 1)"),
        ('str.lwer', "s = 'HELLO'\ns.lwer()"),
        ('set.push', "s = {1, 2}\ns.push(3)"),
    ]:
        host_err = subprocess.run(
            [sys.executable, '-c', src],
            capture_output=True, text=True).stderr
        host_last = [l for l in host_err.splitlines()
                     if l.startswith("AttributeError:")][-1]
        host_m = re.search(r"no attribute '([^']*)'", host_last)
        host_suffix = host_last[host_m.end():].strip()
        _, our_err, _ = fire_run(src)
        ours_name = host_m.group(1)
        ours_suffix = suggestion_suffix_of(our_err, ours_name)
        assert ours_suffix is not None, \
            f"{name}: no final AttributeError line in our output"
        assert ours_suffix == host_suffix, \
            (f"{name}: suggestion diverges from CPython 3.15: "
             f"host {host_suffix!r} vs ours {ours_suffix!r}")


def test_parity_nonascii_with_cpython_315():
    # The non-ASCII suggestion path, differentially: whatever suffix CPython
    # 3.15.2 appends at print time, ours must be byte-identical.
    if sys.version_info < (3, 15):
        print(f"  (skipped: host is {sys.version.split()[0]}, not 3.15+)")
        return
    import traceback as _tb

    class Holder:
        héllo = 1
        café = 2
        αβγ = 3
        push = 4

    h = Holder()

    def host_suffix(obj, name):
        e = AttributeError(f"x has no attribute '{name}'")
        e.name = name
        e.obj = obj
        last = list(_tb.TracebackException(type(e), e, None).format())[-1]
        m = last.find(f"has no attribute '{name}'")
        assert m >= 0, f"host did not print the base message: {last!r}"
        return last[m + len(f"has no attribute '{name}'"):].strip().rstrip('\n')

    for name in ['caf', 'hèllo', 'pγsh', 'αβ', 'wörld', 'zzz', 'uppér', 'café']:
        ours = attribute_error_suggestion(h, name)
        theirs = host_suffix(h, name)
        assert ours == theirs, \
            f"non-ASCII {name!r}: ours {ours!r} vs host {theirs!r}"


if __name__ == '__main__':
    test_raise_half_host_object()
    print("PASS test_raise_half_host_object")
    test_raise_half_mojo_instance()
    print("PASS test_raise_half_mojo_instance")
    test_suggestion_suffixes()
    print("PASS test_suggestion_suffixes")
    test_suggestion_nested_member()
    print("PASS test_suggestion_nested_member")
    test_suggestion_nonascii_close_match()
    print("PASS test_suggestion_nonascii_close_match")
    test_suggestion_nested_underscored_no_false_positive()
    print("PASS test_suggestion_nested_underscored_no_false_positive")
    test_end_to_end_uncaught_shows_suggestion()
    print("PASS test_end_to_end_uncaught_shows_suggestion")
    test_end_to_end_nested_member()
    print("PASS test_end_to_end_nested_member")
    test_end_to_end_no_false_suggestion()
    print("PASS test_end_to_end_no_false_suggestion")
    test_end_to_end_caught_stays_plain()
    print("PASS test_end_to_end_caught_stays_plain")
    test_end_to_end_other_exceptions_unchanged()
    print("PASS test_end_to_end_other_exceptions_unchanged")
    test_parity_with_cpython_315()
    print("PASS test_parity_with_cpython_315")
    test_parity_nonascii_with_cpython_315()
    print("PASS test_parity_nonascii_with_cpython_315")
    print("ALL PASS")
