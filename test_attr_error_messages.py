#!/usr/bin/env python3
"""Regression: CPython 3.15's "improved error messages" (all four branches
of Lib/traceback.py's `_compute_suggestion_error`).

What's New in Python 3.15 (the subject of
bugs/PYTHON3.15_improved_error_messages.md): an UNCAUGHT exception of one of
four types is printed with a suggestion computed at PRINT time from fields
the exception carries, so a caught exception stays plain. This file pins both
halves of that contract for every branch:

  * AttributeError — from `name`/`obj`: the static cross-language/wrong-type
    table (`[1,2,3].push(4)` -> `Did you mean '.append'?`), Levenshtein close
    matches (`s.lwer()` -> `Did you mean '.lower' instead of '.lwer'?`), and
    one-level nested members (`container.area` -> `Did you mean '.inner.area'
    instead of '.area'?`).
  * NameError — from `name` + the failing frame's pool (CPython reads
    f_locals+f_globals+f_builtins off the traceback; this interpreter captures
    them at raise time): close matches (`os2` -> `Did you mean: 'os'?`), the
    `self.<name>` refinement, and the forgot-to-import hint (`math` -> `Did
    you forget to import 'math'?`).
  * ModuleNotFoundError — from `name`: the import machinery's discoverable
    modules (`import os2` -> `Did you mean: 'os'?`).
  * ImportError (a `from X import Y` miss, carrying `name_from`) — from
    X's dir() (`from os import path2` -> `Did you mean: 'path'?`).

The RAISE half (myinterpreter._tag_attribute_error / _tag_name_error) makes
every missing-attribute AttributeError carry `name`/`obj` and every NameError
carry `name`/`candidates`/`self_obj`; the PRINT half (myinterpreter's
`error_suggestion_suffix`, called from fire.py's top-level error printing)
appends the exact 3.15.2 suffixes. Before the fix, `python3 fire.py run` on
`x.push(4)` printed the bare `'list' object has no attribute 'push'` with no
suggestion, and none of the other three exception types suggested anything.
"""

import os
import json
import re
import subprocess
import sys
import tempfile

import fire_compiler as N
from myinterpreter import (
    Interpreter,
    MojoInstance,
    attribute_error_suggestion,
    error_suggestion_suffix,
    name_error_suggestion,
    module_not_found_suggestion,
    import_error_suggestion,
)

HERE = os.path.dirname(os.path.abspath(__file__))


def run_interp_exc(source: str):
    """Execute `source` in-process; return the uncaught Exception, or None
    if it ran to completion."""
    mod = N.Module(body=N.Parser(N.py_tokenize(source)).parse_module())
    interp = Interpreter()
    try:
        interp.execute(mod)
        return None
    except Exception as e:
        return e


def run_interp(source: str):
    """Execute `source` in-process; return the uncaught AttributeError, or
    None if it ran to completion."""
    e = run_interp_exc(source)
    return e if isinstance(e, AttributeError) else None


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


# ------------------------------------------------------------ the other
# branches of _compute_suggestion_error: NameError, ModuleNotFoundError,
# ImportError (a `from X import Y` miss, the one carrying name_from)

def line_suffix_after(stderr: str, marker: str):
    """The text after `marker` on the last stderr line containing it — the
    shape of the final `Error:` line, whatever its type. None when no line
    carries the marker, '' when it appends nothing after it."""
    lines = [l for l in stderr.splitlines() if marker in l]
    if not lines:
        return None
    m = lines[-1].find(marker)
    return lines[-1][m + len(marker):].strip()


# ------------------------------------------------ the NameError branch

def test_name_error_raise_half_carries_fields():
    # The RAISE half: the interpreter's NameError must carry `name` and the
    # failing frame's candidate pool (CPython's f_locals + f_globals +
    # f_builtins — here the frame's vars plus the module scope's vars, where
    # builtins are bound), and the message stays plain.
    e = run_interp_exc("a_val = 1\nb_val2")
    assert isinstance(e, NameError), f"got {type(e)}"
    assert getattr(e, 'name', None) == 'b_val2'
    cands = getattr(e, 'candidates', None)
    assert isinstance(cands, list) and 'a_val' in cands, \
        f"module-level pool must carry the defined names, got {cands!r}"
    assert 'print' in cands, \
        "builtins live in the module scope and must be in the pool"
    assert getattr(e, 'self_obj', 'unset') is None, \
        "no self in a module-level frame"
    assert "Did you mean" not in str(e), \
        f"caught/unprinted message must stay plain, got {e!s}"


def test_name_error_raise_half_function_frame():
    # The pool must be the FAILING frame's locals, not just module globals:
    # a local defined in the function body must be a candidate.
    e = run_interp_exc(
        "def f():\n"
        "    local_one = 1\n"
        "    return local_two\n"
        "f()")
    assert isinstance(e, NameError)
    assert getattr(e, 'name', None) == 'local_two'
    assert 'local_one' in getattr(e, 'candidates', []), \
        "the failing frame's locals must be in the pool"


def test_name_error_suggestion_suffixes():
    class C:
        area = 5
    c = C()
    s = name_error_suggestion
    # plain close match
    assert s('os2', ['os', 'x'], None) == ". Did you mean: 'os'?"
    # the self.<name> refinement (a bare name that is an instance attribute)
    assert s('area', [], c) == ". Did you mean: 'self.area'?"
    # the forgot-to-import refinement, alone and combined with a suggestion
    assert s('math', [], None) == ". Did you forget to import 'math'?"
    assert s('math', ['mat'], None) == \
        ". Did you mean: 'mat'? Or did you forget to import 'math'?"
    # the non-ASCII rendering (CPython 3.15.2 verbatim: !a parens on the
    # suggestion only)
    assert s('hello', ['héllo'], None) == \
        ". Did you mean: 'héllo' ('h\\xe9llo')?"
    # no match -> nothing; no frame carried (a NameError CPython itself
    # raised) -> nothing, no crash
    assert s('zzz', ['os'], None) == ""
    assert s('os2', None, None) == ""
    # unlike the attr branch, NameError candidates are NOT underscore-
    # filtered
    assert s('value', ['_value', 'other'], None) == ". Did you mean: '_value'?"


def test_name_error_parity_with_cpython_315():
    # Differential: the host subprocess runs the same failing reference,
    # hands back its frame's exact candidate pool and its own printed
    # suffix — same pool in, the suffix must come out byte-identical.
    if sys.version_info < (3, 15):
        print(f"  (skipped: host is {sys.version.split()[0]}, not 3.15+)")
        return
    cases = [
        ("os = 1", None, "os2"),               # plain close match
        (None, "area", "area"),                # self.<name> refinement
        ("", None, "math"),                    # forgot-to-import only
        ("mat = 1", None, "math"),             # suggestion + forgot-import
        ("héllo = 1", None, "hello"),          # non-ASCII rendering
        ("_value = 1", None, "value"),         # no underscore filter
        ("unrelated = 1", None, "zzz9"),       # no match -> plain
    ]
    for defs, selfattr, ref in cases:
        if selfattr is None:
            script = f"""
import sys, json, traceback
{defs}
try:
    {ref}
except NameError:
    import builtins as B
    d = list(vars()) + list(vars()) + list(vars(B))
    last = list(traceback.TracebackException(*sys.exc_info()).format())[-1]
    sys.stdout.write(json.dumps([d, last]))
"""
            self_obj = None
        else:
            script = f"""
import sys, json, traceback
class C:
    {selfattr} = 5
def f(self):
    return {ref}
c = C()
try:
    f(c)
except NameError:
    import builtins as B
    frame = sys.exc_info()[2].tb_frame
    d = (list(frame.f_locals) + list(frame.f_globals)
         + list(frame.f_builtins))
    last = list(traceback.TracebackException(*sys.exc_info()).format())[-1]
    sys.stdout.write(json.dumps([d, last]))
"""
            self_obj = type('C', (), {selfattr: 5})()
        r = subprocess.run([sys.executable, '-c', script],
                           capture_output=True, text=True, cwd=HERE)
        assert r.returncode == 0, f"{ref}: host script failed: {r.stderr}"
        pool, last_line = json.loads(r.stdout)
        m = last_line.find("is not defined")
        assert m >= 0, f"{ref}: host did not print the base message: {last_line!r}"
        theirs = last_line[m + len("is not defined"):].strip().rstrip('\n')
        ours = name_error_suggestion(ref, pool, self_obj)
        assert ours == theirs, \
            f"NameError {ref!r}: ours {ours!r} vs host {theirs!r}"


def test_name_error_caps_match_cpython():
    # CPython's caps on the shared distance engine: the C-module pass gives
    # up at 750+ candidates, the fallback at 751+ — so at exactly 750 the
    # fallback (not the C pass) still finds the match, at 751 nothing does.
    pool750 = ['os'] + ['zzname%05d' % i for i in range(749)]
    assert name_error_suggestion('os2', pool750, None) == \
        ". Did you mean: 'os'?"
    pool751 = pool750 + ['q']
    assert name_error_suggestion('os2', pool751, None) == ""


def test_end_to_end_name_error_suggestion():
    # The `Error:` line is what OUR printing computes (before the fix it was
    # plain — a 3.15 host's own traceback module decorates its own final
    # line, which is not our code); the final line must agree with it.
    out, err, rc = fire_run("a_val = 1\nb_val2")
    assert rc == 1, f"uncaught NameError must exit 1, got {rc}"
    marker = "name 'b_val2' is not defined"
    ours = line_suffix_after(err, marker)
    assert ours == ". Did you mean: 'a_val'?", \
        f"final NameError line must carry the 3.15 suggestion, got {ours!r}"
    err_lines = [l for l in err.splitlines() if l.startswith("Error:")]
    assert err_lines and marker in err_lines[0], \
        f"the Error: line must carry the message, got {err_lines!r}"
    assert err_lines[0].split(marker, 1)[1].strip() == ours, \
        f"the Error: line must agree with the final line, got {err_lines!r}"
    # the self.<name> refinement end to end
    out, err, rc = fire_run(
        "class C:\n"
        "    def __init__(self):\n"
        "        self.area = 5\n"
        "    def f(self):\n"
        "        return area\n"
        "C().f()")
    assert rc == 1
    assert line_suffix_after(err, "name 'area' is not defined") == \
        ". Did you mean: 'self.area'?"


# --------------------------------------------------- ModuleNotFoundError

def test_module_not_found_suggestion_suffixes():
    s = module_not_found_suggestion
    # the stdlib is discoverable on every host, so this is environment-stable
    assert s('os2') == ". Did you mean: 'os'?"
    # a dotted miss whose parent is not a package (frozen `os`) yields no
    # candidates at all — CPython's try/except-returns-None
    assert s('os.path2') == ""
    # nothing close -> nothing
    assert s('zzzqqq999') == ""
    # guards
    assert s(None) == ""


def test_end_to_end_module_not_found_parity_with_cpython_315():
    # Same machine, same sys.path: whatever suffix CPython 3.15.2 appends to
    # `import <name>`'s ModuleNotFoundError, ours must be byte-identical —
    # on the `Error:` line our own printing computes (before the fix it was
    # plain) and on the final traceback line (rewritten from the same text).
    if sys.version_info < (3, 15):
        print(f"  (skipped: host is {sys.version.split()[0]}, not 3.15+)")
        return
    for name in ['os2', 'json2', 'zzzqqq999', 'os.path2', 'collections.abc2']:
        _, our_err, rc = fire_run(f"import {name}")
        assert rc == 1, f"import {name} must exit 1, got {rc}"
        host_err = subprocess.run(
            [sys.executable, '-c', f"import {name}"],
            capture_output=True, text=True, cwd=HERE).stderr
        marker = f"No module named '{name}'"
        ours = line_suffix_after(our_err, marker)
        theirs = line_suffix_after(host_err, marker)
        assert ours is not None, f"import {name}: no final line in our output"
        assert ours == theirs, \
            (f"import {name}: suggestion diverges from CPython 3.15: "
             f"host {theirs!r} vs ours {ours!r}")
        err_lines = [l for l in our_err.splitlines() if l.startswith("Error:")]
        assert err_lines and marker in err_lines[0], \
            f"the Error: line must carry the message, got {err_lines!r}"
        assert err_lines[0].split(marker, 1)[1].strip() == ours, \
            f"the Error: line must agree with the final line, got {err_lines!r}"


def test_end_to_end_module_not_found_caught_stays_plain():
    # the caught-plain/uncaught-suggested split for MNE too: a caught
    # ModuleNotFoundError prints its plain message.
    out, err, rc = fire_run(
        "try:\n"
        "    import os2\n"
        "except ModuleNotFoundError as e:\n"
        "    print('caught:', e)")
    assert rc == 0, f"caught case must exit 0, got {rc}\n{err}"
    assert "caught: No module named 'os2'" in out, f"stdout: {out!r}"
    assert "Did you mean" not in out, f"caught message must stay plain: {out!r}"
    assert "Did you mean" not in err, f"no suggestion may leak: {err!r}"


# ------------------------------------------------------- ImportError

def test_import_error_suggestion_suffixes():
    s = import_error_suggestion
    # the from-miss engine: X's dir() is the pool, filtered to non-
    # underscored names for a non-underscored name_from
    assert s('os', 'path2') == ". Did you mean: 'path'?"
    assert s('sys', 'exit2') == ". Did you mean: 'exit'?"
    # a present name is "found" (skipped) — the next-closest candidate wins
    assert s('os', 'path') == ". Did you mean: 'fspath'?"
    assert s('os', 'zzz') == ""
    # an unimportable module means no pool, CPython's try/except-None
    assert s('no_such_module_xyz9', 'x') == ""
    assert s(None, 'path2') == ""
    assert s('os', None) == ""


def test_import_error_suggestion_underscore_pool():
    # `from X import _y2`: an underscored name_from does NOT filter the pool
    # (CPython re-filters, mirroring the attr branch); a non-underscored
    # miss against the same module excludes the underscored member.
    fd, path = tempfile.mkstemp(suffix='.py', dir=HERE)
    with os.fdopen(fd, 'w') as f:
        f.write("_secret = 1\nother = 2\n")
    modname = os.path.splitext(os.path.basename(path))[0]
    sys.path.insert(0, HERE)
    try:
        __import__(modname)
        assert import_error_suggestion(modname, '_secret2') == \
            ". Did you mean: '_secret'?"
        assert import_error_suggestion(modname, 'other2') == \
            ". Did you mean: 'other'?"
        assert import_error_suggestion(modname, 'xecret') == "", \
            "a non-underscored miss must not suggest the underscored member"
    finally:
        sys.path.remove(HERE)
        sys.modules.pop(modname, None)
        os.unlink(path)


def test_end_to_end_import_error_parity_with_cpython_315():
    # The only way a name_from ImportError reaches our top level: a REAL
    # module that fails its own `from X import Y` (the interpreter's own
    # from-imports bind an auto-stub instead of raising — documented in
    # bugs/PYTHON3.15_improved_error_messages.md). The suffix must agree
    # with CPython 3.15.2's own `from os import path2`.
    if sys.version_info < (3, 15):
        print(f"  (skipped: host is {sys.version.split()[0]}, not 3.15+)")
        return
    fd, mpath = tempfile.mkstemp(suffix='.py', dir=HERE)
    with os.fdopen(fd, 'w') as f:
        f.write("from os import path2\n")
    modname = os.path.splitext(os.path.basename(mpath))[0]
    try:
        _, our_err, rc = fire_run(f"import {modname}")
        assert rc == 1, f"import {modname} must exit 1, got {rc}"
        host_err = subprocess.run(
            [sys.executable, '-c', "from os import path2"],
            capture_output=True, text=True, cwd=HERE).stderr
        marker = "cannot import name 'path2' from 'os'"
        ours = line_suffix_after(our_err, marker)
        theirs = line_suffix_after(host_err, marker)
        # the suffix after the marker includes the `(/path/to/os.py)` tail of
        # the base message — the suggestion is what follows it
        assert ours is not None and ours.endswith(". Did you mean: 'path'?"), \
            f"final ImportError line must carry the 3.15 suggestion, got {ours!r}"
        assert ours == theirs, \
            f"ImportError suffix diverges: host {theirs!r} vs ours {ours!r}"
        err_lines = [l for l in our_err.splitlines() if l.startswith("Error:")]
        assert err_lines and marker in err_lines[0], \
            f"the Error: line must carry the message, got {err_lines!r}"
        assert err_lines[0].split(marker, 1)[1].strip() == ours, \
            f"the Error: line must agree with the final line, got {err_lines!r}"
    finally:
        os.unlink(mpath)


# ------------------------------------------------------- the dispatcher

def test_error_suggestion_suffix_dispatch():
    e = NameError("name 'os2' is not defined")
    e.name = 'os2'; e.candidates = ['os']; e.self_obj = None
    assert error_suggestion_suffix(e) == ". Did you mean: 'os'?"
    # ModuleNotFoundError is an ImportError subclass: the MNE branch must
    # win (a bare MNE has no name_from, so the IE branch would give nothing)
    e = ModuleNotFoundError("No module named 'os2'")
    e.name = 'os2'
    assert error_suggestion_suffix(e) == ". Did you mean: 'os'?"
    e = ImportError("cannot import name 'path2' from 'os'")
    e.name = 'os'; e.name_from = 'path2'
    assert error_suggestion_suffix(e) == ". Did you mean: 'path'?"
    # CPython's guards: no `name` field -> nothing; other types -> nothing
    assert error_suggestion_suffix(NameError("name 'x' is not defined")) == ""
    assert error_suggestion_suffix(ValueError("boom")) == ""
    e = ImportError("cannot import name 'path2' from 'os'")
    e.name = 'os'  # no name_from: not a from-miss, no suggestion
    assert error_suggestion_suffix(e) == ""


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
    test_name_error_raise_half_carries_fields()
    print("PASS test_name_error_raise_half_carries_fields")
    test_name_error_raise_half_function_frame()
    print("PASS test_name_error_raise_half_function_frame")
    test_name_error_suggestion_suffixes()
    print("PASS test_name_error_suggestion_suffixes")
    test_name_error_parity_with_cpython_315()
    print("PASS test_name_error_parity_with_cpython_315")
    test_name_error_caps_match_cpython()
    print("PASS test_name_error_caps_match_cpython")
    test_end_to_end_name_error_suggestion()
    print("PASS test_end_to_end_name_error_suggestion")
    test_module_not_found_suggestion_suffixes()
    print("PASS test_module_not_found_suggestion_suffixes")
    test_end_to_end_module_not_found_parity_with_cpython_315()
    print("PASS test_end_to_end_module_not_found_parity_with_cpython_315")
    test_end_to_end_module_not_found_caught_stays_plain()
    print("PASS test_end_to_end_module_not_found_caught_stays_plain")
    test_import_error_suggestion_suffixes()
    print("PASS test_import_error_suggestion_suffixes")
    test_import_error_suggestion_underscore_pool()
    print("PASS test_import_error_suggestion_underscore_pool")
    test_end_to_end_import_error_parity_with_cpython_315()
    print("PASS test_end_to_end_import_error_parity_with_cpython_315")
    test_error_suggestion_suffix_dispatch()
    print("PASS test_error_suggestion_suffix_dispatch")
    print("ALL PASS")
