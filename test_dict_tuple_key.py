#!/usr/bin/env python3
"""A tuple used as a dict key is keyed by its CONTENT on the compiled path.

`d[(p, mtime)]` used to be keyed by the tuple OBJECT'S ADDRESS: the codegen's
one dict-key-to-string conversion (`_char_to_cstr`) falls through to a raw
`(char *)value` for any pointer-typed operand, so the key was the tuple's own
pointer bits. Two consequences, both silent (exit 0, no diagnostic):

  * an equal tuple built at a different address never hit, so `k in d` was
    always False and every `d[k] = v` re-inserted;
  * with no GC to reclaim the tuple, each miss leaked one — this was about 16 of
    the 19 GB live on `mojoc --dump-full fire.py`
    (bugs/PERF_selfhost_memory_leak_hunt.md).

The leak hunt fixed the call sites that mattered (string keys, the `_pair_key`
convention already in fire_compiler.py) and left the MECHANISM, which is what
every remaining tuple-keyed lookup goes through. This is the mechanism's test.

A tuple is the one container Python lets you key a dict with, because it is the
one it considers hashable, so the domain is tuple-only: a list / dict / set key
is a TypeError in CPython and is one here too, with CPython's text.

Two properties are tested separately because they are separate requirements and
a fix that has only one of them looks correct:

  * SAME tuples hit (the bug), and
  * DIFFERENT tuples do not collide (the requirement that makes the first one
    safe). A key encoding that merely made the first case pass — say the first
    element, or the length, or the address of the first slot — would pass a
    hit-only test while `d[(1, 2)] = 1; d[(2, 1)] = 2` silently kept one entry.

Every case is a whole PROGRAM run TWICE — once compiled to an executable
through the GIMPLE backend, once by CPython on the same text with the Mojo
spellings stripped — and stdout AND exit status must agree. The unhashable
cases have no stdout to compare (CPython raises), so their TypeError TEXT is
diffed instead. Diffing against CPython throughout is the point: the expected
values are Python's, so a divergence is the compiler's, not the test's.

Run:  python3 test_dict_tuple_key.py [-v] [--keep]
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

RUNTIME = os.path.join(HERE, 'runtime')


def _p(*lines: str) -> str:
    return "\n".join(lines) + "\n"


# Every program is written ONCE and used for both engines (see `_py_source`).
# Each prints one line per assertion, so a divergence is a line-by-line diff
# rather than one opaque exit status.
CASES = [
    # ── the bug itself: the repro from the bug doc, verbatim ───────────────
    # `_C` is a MODULE GLOBAL, which is the self-hosted shape that cost the
    # memory: a module global reached through an int64_t accessor, so the key
    # is a raw word and nothing about the tuple's type survives to the call.
    ("doc-repro-global", _p(
        "_C: dict = {}",
        "",
        "def look(p: str) -> Int:",
        "    var k = (p, len(p))",
        "    if k in _C:",
        "        return 1",
        "    _C[k] = 2",
        "    return 0",
        "",
        "def main() raises:",
        '    print(look("x.py"), look("x.py"), look("x.py"))',
        "    print(len(_C))")),

    # The same question with the dict local, which is the shape a reader of the
    # bug doc will try first. `0 1 1` and `1` are the answers that were wrong:
    # `0 0 0` and `3` is what address-keying produced.
    ("doc-repro-local", _p(
        "def look(p: str) -> Int:",
        "    var d = {}",
        "    var k = (p, len(p))",
        "    if k in d:",
        "        return 1",
        "    d[k] = 2",
        "    return 0",
        "",
        "def main() raises:",
        '    print(look("x.py"), look("x.py"), look("x.py"))',
        "    var d2 = {}",
        '    var k2 = ("y.py", 2)',
        '    d2[k2] = 9',
        # `.get`, not a bare subscript: a MISSING bare subscript raises KeyError
        # in CPython, which would make this a refusal case and test nothing
        # about keying.
        '    print(d2.get(("y.py", 2), -1))',
        '    print(d2.get(("y.py", 3), -1))',
        "    print(len(d2))")),

    # ── every dict-key ENTRY POINT, not just `in` and `[]=` ────────────────
    # One per case, because a key that works in `d[k] = v` and misses in
    # `d.get(k)` is a bug in one entry point and not in the mechanism — and the
    # bug's history is exactly that: the leak hunt's call-site fixes covered
    # the lookups that mattered on the self-host path and nothing else.
    ("key-get", _p(
        "def put(a) -> Int:",
        "    var k = (a, 1)",
        "    _C[k] = 42",
        "    return 0",
        "",
        "_C: dict = {}",
        "",
        "def get(a) -> Int:",
        "    var k = (a, 1)",
        "    return _C.get(k, -1)",
        "",
        "def main() raises:",
        '    put("a")',
        '    print(get("a"))',
        '    print(get("b"))')),
    # `pop` WITHOUT a default, for two reasons. A default argument is ignored
    # for a missing key on the compiled path whatever the key's type — see
    # bugs/CODEGEN_dict_pop_default_ignored_on_a_miss.md, which this deliberately
    # does not depend on, so a fix there cannot be mistaken for a change here.
    # And a bare `pop` on a MISSING key raises in CPython, which is a refusal,
    # not a value.
    ("key-pop", _p(
        "_C: dict = {}",
        "",
        "def put(a) -> Int:",
        "    var k = (a, 1)",
        "    _C[k] = 7",
        "    return 0",
        "",
        "def take(a) -> Int:",
        "    var k = (a, 1)",
        "    return _C.pop(k)",
        "",
        "def main() raises:",
        '    put("a")',
        '    put("b")',
        '    print(take("a"))',
        "    print(len(_C))")),
    ("key-setdefault", _p(
        "_C: dict = {}",
        "",
        "def ask(a) -> Int:",
        "    var k = (a, 1)",
        "    return _C.setdefault(k, 5)",
        "",
        "def main() raises:",
        '    print(ask("a"))',
        '    print(ask("a"))',
        '    print(ask("b"))',
        "    print(len(_C))")),
    ("key-in", _p(
        "_C: dict = {}",
        "",
        "def has(a) -> Int:",
        "    var k = (a, 1)",
        "    if k in _C:",
        "        return 1",
        "    return 0",
        "",
        "def main() raises:",
        '    var k1 = ("a", 1)',
        '    _C[k1] = 1',
        '    print(has("a"))',
        '    print(has("b"))')),

    # ── the other half: DIFFERENT tuples must not share one entry ───────────
    # Each pair below differs in exactly one way, so a key that collapses any of
    # them loses an entry. `put` returns `len(_C)` after storing, so a collision
    # shows up as a count that does not grow.
    ("distinct-tuples", _p(
        "_C: dict = {}",
        "",
        "def put(a, b, c) -> Int:",
        "    var k = (a, b, c)",
        "    _C[k] = len(k)",
        "    return len(_C)",
        "",
        "def main() raises:",
        # same elements, different order
        '    print(put("a", "b", "c"))',
        '    print(put("c", "b", "a"))',
        # an int and a str that spell the same text are DIFFERENT elements,
        # and CPython agrees: (1,) != ("1",)
        "    print(put(1, 2, 3))",
        '    print(put(\"1\", \"2\", \"3\"))',
        # a concatenation split differently: the shape a repr-based key gets
        # wrong, because ("ab","c") and ("a","bc") both print like a,b,c
        '    print(put("ab", "c", 1))',
        '    print(put("a", "bc", 1))',
        # a length that differs only in the tail
        '    print(put("x", "", ""))',
        '    print(put("x", "y", ""))',
        "    print(len(_C))")),
    ("nested-tuple-key", _p(
        "_C: dict = {}",
        "",
        "def put1(a) -> Int:",
        "    var k = (a, 1)",
        "    _C[k] = 1",
        "    return len(_C)",
        "",
        "def put2(a) -> Int:",
        "    var inner = (a, 1)",
        "    var k = (inner, 2)",
        "    _C[k] = 2",
        "    return len(_C)",
        "",
        "def main() raises:",
        '    print(put1("a"))',
        '    print(put2("a"))',
        '    print(put2("b"))',
        "    print(len(_C))")),
    # `None` is a real element and is not the empty string. This is the
    # `_kbuf_put("N", ...)` tag's reason to exist.
    ("none-element", _p(
        "_C: dict = {}",
        "",
        "def put(a) -> Int:",
        "    var k = (a, None)",
        "    _C[k] = 1",
        "    return len(_C)",
        "",
        "def main() raises:",
        '    print(put(""))',
        '    print(put("x"))',
        "    print(len(_C))")),

    # ── what must NOT change ───────────────────────────────────────────────
    # A string key is still a string key: the content-key domain is marked so
    # it can never equal an ordinary str key that happens to spell the same
    # bytes, and these are the keys that were ALREADY correct.
("str-keys-unchanged", _p(
        "def main() raises:",
        "    var d = {}",
        '    d["a"] = 1',
        '    d["b"] = 2',
        '    print(d["a"])',
        '    print(d["b"])',
        '    print(d.get("zz", -1))',
        '    print("a" in d)',
        '    print("zz" in d)',
        "    print(len(d))")),
    # An int-keyed dict keeps its own integer domain — a tuple key must not
    # have dragged the ordinary `_kw` path onto the content-key path.
    ("int-keys-unchanged", _p(
        "def ask(d, k) -> Int:",
        "    if k in d:",
        "        return 1",
        "    return 0",
        "",
        "def main() raises:",
        "    var d = {}",
        "    d[10] = 1",
        "    d[20] = 1",
        "    print(ask(d, 10))",
        "    print(ask(d, 20))",
        "    print(ask(d, 30))")),
]

# The UNHASHABLE cases: CPython raises, so what has to match is the exit status
# and the TypeError TEXT. A container that Python refuses as a dict key must not
# quietly get a key here either — the compiled path used to `strdup` the first
# bytes of the container struct as the key, which is a silent garbage entry.
REFUSALS = [
    ("unhashable-dict", _p(
        "def main() raises:",
        "    var d = {}",
        '    d[{"a": 1}] = 1',
        '    print(len(d))')),
    ("unhashable-set", _p(
        "def main() raises:",
        "    var d = {}",
        "    d[{1, 2}] = 1",
        '    print(len(d))')),
    ("unhashable-list", _p(
        "def main() raises:",
        "    var d = {}",
        "    d[[1, 2]] = 1",
        "    print(len(d))")),
    # ...including through `in`, which is a different entry point with its own
    # dispatcher (mojo_in_dispatch_str/int rather than the `_kw` twins).
    ("unhashable-dict-in", _p(
        "def has(d, k) -> Int:",
        "    if k in d:",
        "        return 1",
        "    return 0",
        "",
        "def main() raises:",
        "    var d = {}",
        '    print(has(d, {"a": 1}))')),
    ("unhashable-list-in", _p(
        "def has(d, k) -> Int:",
        "    if k in d:",
        "        return 1",
        "    return 0",
        "",
        "def main() raises:",
        "    var d = {}",
        "    print(has(d, [1, 2]))")),
    # An unhashable element NESTED inside a tuple is refused too, not just a
    # top-level one. (`((1, 2), 3)` is hashable — a tuple of hashables is —
    # so the nesting that matters is a list inside the tuple.)
    ("unhashable-nested", _p(
        "def main() raises:",
        "    var d = {}",
        "    var k = ((1, 2), [3])",
        "    d[k] = 1",
        "    print(len(d))")),
]


def _py_source(src: str) -> str:
    """The same program as CPython sees it: drop the Mojo annotations."""
    out = []
    for line in src.splitlines():
        line = re.sub(r"\bvar\s+", "", line)
        line = re.sub(r"->\s*Int(?!\w)", "", line)
        line = re.sub(r"\braises\b", "", line)
        out.append(line)
    return "\n".join(out) + "\n\nmain()\n"


def run_cpython(src: str, tmp: str, tag: str):
    path = os.path.join(tmp, tag + "_ref.py")
    with open(path, "w") as f:
        f.write(_py_source(src))
    p = subprocess.run([sys.executable, path], capture_output=True, text=True,
                       timeout=60)
    return p.stdout, p.returncode, p.stderr


def run_compiled(src: str, tmp: str, name: str):
    """(stdout, exitcode, stderr) of the compiled program, or raises."""
    from build_config import find_gcc
    from gimple_codegen import compile_to_gimple

    c = compile_to_gimple(src)
    c_file = os.path.join(tmp, name + ".c")
    exe = os.path.join(tmp, name)
    with open(c_file, "w") as f:
        f.write(c)
    sources = [c_file, os.path.join(RUNTIME, "fire_runtime.c")]
    if "__mgco_" in c or "__mojo_coro_yield_i" in c:
        import platform
        arch = ("fire_coro_ctx_aarch64.S"
                if platform.machine().lower() in ("arm64", "aarch64")
                else "fire_coro_ctx_generic.c")
        sources += [os.path.join(RUNTIME, x) for x in
                    ("fire_coro_gen.c", "fire_coro.c", "fire_async_sched.c",
                     arch)]
    r = subprocess.run([find_gcc(), "-fgimple", "-I" + RUNTIME, "-o", exe,
                        *sources], capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError("generated C rejected by gcc -fgimple:\n"
                           + r.stderr[-3000:])
    p = subprocess.run([exe], capture_output=True, text=True, timeout=60)
    return p.stdout, p.returncode, p.stderr


def _type_error_line(stderr: str) -> str:
    """The identifying tail of a `TypeError`, or '' if there is none.

    The compiled runtime prints `Unhandled exception: TypeError: ...` on one
    line and CPython prints the same text inside a traceback, so this matches
    the part both spell identically.

    For an unhashable dict key the two word it differently around the same
    core: CPython's SUBSCRIPT is "cannot use 'dict' as a dict key (unhashable
    type: 'dict')" while the compiled raise site says "unhashable type:
    'dict'", and only the core identifies the program. So this returns the
    core when there is one, which is also what makes the comparison a test of
    the refusal rather than of either engine's prose around it."""
    for line in stderr.splitlines():
        if "TypeError:" in line:
            t = line[line.index("TypeError:") + len("TypeError:"):].strip()
            m = re.search(r"unhashable type: *'[^']*'", t)
            return m.group(0) if m else t
    return ""


def _diff(want: str, got: str) -> str:
    wl, gl = want.splitlines(), got.splitlines()
    lines = []
    for i in range(max(len(wl), len(gl))):
        w = wl[i] if i < len(wl) else "<missing>"
        g = gl[i] if i < len(gl) else "<missing>"
        if w != g:
            lines.append("      line %d: cpython %s, compiled %s"
                         % (i + 1, w, g))
    return "\n".join(lines[:12])


def _run_value_case(name: str, src: str, tmp: str):
    py_out, py_rc, py_err = run_cpython(src, tmp, name)
    if py_rc != 0 or py_err.strip():
        # A reference program that cannot run makes the case meaningless. This
        # is also the check that keeps a case out of CASES by mistake when
        # CPython REFUSES it — a refusal belongs in REFUSALS, where the
        # TypeError is the answer being diffed rather than a broken reference.
        return False, ("BROKEN: the reference program does not run under "
                       "CPython:\n" + py_err[-800:])
    try:
        c_out, c_rc, c_err = run_compiled(src, tmp, name)
    except Exception as e:                                   # noqa: BLE001
        return False, str(e)
    if (c_out, c_rc) == (py_out, py_rc):
        return True, "%d line(s)" % len(py_out.splitlines())
    note = "compiled answer differs from CPython's"
    if c_rc != py_rc:
        note += " (exit %d vs %d)" % (c_rc, py_rc)
    te = _type_error_line(c_err)
    if te:
        note += "\n      compiled raised: %s" % te
    return False, note + "\n" + _diff(py_out, c_out)


def _run_refusal_case(name: str, src: str, tmp: str):
    py_out, py_rc, py_err = run_cpython(src, tmp, name)
    py_te = _type_error_line(py_err)
    if py_rc == 0 or not py_te:
        return False, ("BROKEN: CPython does not refuse this program "
                       "(rc=%d, stderr=%r) — it is not a refusal case"
                       % (py_rc, py_err[-300:]))
    try:
        c_out, c_rc, c_err = run_compiled(src, tmp, name)
    except Exception as e:                                   # noqa: BLE001
        return False, str(e)
    c_te = _type_error_line(c_err)
    if not c_te:
        return False, ("the compiled program did NOT raise; it answered "
                       "rc=%d stdout=%r — a refusal became an entry"
                       % (c_rc, c_out.strip()[:200]))
    if c_rc == 0:
        return False, ("the compiled program raised but exited 0 (CPython "
                       "exits %d)" % py_rc)
    if c_te == py_te:
        return True, c_te
    return False, ("the TypeError text differs\n      cpython:   %s\n"
                   "      compiled: %s" % (py_te, c_te))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print every case, not just failures")
    ap.add_argument("--keep", action="store_true",
                    help="keep the generated C and binaries")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="tkdict-", dir=HERE)
    passed = failed = 0
    try:
        for name, src in CASES:
            ok, note = _run_value_case(name, src, tmp)
            passed += ok
            failed += not ok
            if not ok or args.verbose:
                print("%-6s %-24s %s" % ("PASS" if ok else "FAIL", name, note))
        for name, src in REFUSALS:
            ok, note = _run_refusal_case(name, src, tmp)
            passed += ok
            failed += not ok
            if not ok or args.verbose:
                print("%-6s %-24s %s" % ("PASS" if ok else "FAIL", name, note))
        total = len(CASES) + len(REFUSALS)
        if args.keep:
            print("kept: %s" % tmp)
            tmp = None
    finally:
        if tmp is not None:
            for f in os.listdir(tmp):
                os.unlink(os.path.join(tmp, f))
            os.rmdir(tmp)

    print("PASS=%d FAIL=%d of %d" % (passed, failed, total))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())