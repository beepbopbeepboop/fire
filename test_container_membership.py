#!/usr/bin/env python3
"""`x in <container>` when the container's static type is ERASED is answered.

`x in c` for a container that reached codegen without a static type -- a
container handed across a call boundary, read through a module-global
accessor, returned from a call -- lowers to one of two generic runtime
dispatchers, `mojo_in_dispatch_str` / `mojo_in_dispatch_int`
(`_lower_in` in `mojo/backend_gimple/emit_exprs.py`), because there is nothing
static left to pick `mojo_dict_contains` / `mojo_list_contains_int` /
`mojo_set_contains_str` from. The dispatchers' job is to recover the type from
the runtime's allocation registries, and the int view did not: it had no dict
branch at all, so `x in <boxed dict>` answered False for every key
(bugs/CODEGEN_in_dispatch_int_has_no_dict_branch.md), and it asked the INT
predicates about a needle that was really a boxed `char *`, so `x in <boxed
set of str>` answered False too -- a set's strings live in tag-1 slots, which
the int-domain probe cannot address at all. Every one of those was a False
rather than a crash: exit 0, no diagnostic, and a "no" that inverts whichever
branch of the program the membership test was guarding.

The same source compiled with the container kept LOCAL lowers to the typed
predicate and is correct, which is what made this so easy to miss in review --
and is why every case below passes the container in as an argument.

Every case is a whole PROGRAM run TWICE, once compiled to an executable
through the GIMPLE backend and once by CPython on the same text with the Mojo
spellings stripped; stdout AND exit status must agree. Diffing against CPython
is the point: the expected answers are Python's, so a divergence is the
compiler's, not the test's.

Run:  python3 test_container_membership.py [-v] [--keep]
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
# Each prints one line per assertion and returns 0, so a divergence is a
# line-by-line diff rather than one opaque exit status.
CASES = [
    # ── the bug: a dict behind an unannotated parameter ─────────────────────
    # Verbatim the shape in
    # bugs/CODEGEN_in_dispatch_int_has_no_dict_branch.md: the needle is read
    # out of a list of strings with `mojo_list_get_int`, so it arrives as an
    # int64_t holding a `char *`, and the whole question lowers to the INT
    # view. Note ONE call site per helper: a second call site passing a list
    # LITERAL changes the codegen's element inference for the loop variable and
    # the needle comes out as `char *` instead, which takes the str view and
    # would no longer exercise the int dispatcher at all.
    ("dict-erased-int-view", _p(
        "def look(names, d):",
        "    var n = 0",
        "    for name in names:",
        "        if name in d:",
        "            n = n + 1",
        "    return n",
        "",
        "def main() -> Int:",
        '    var names = ["f0", "f1", "nope"]',
        "    var d = {}",
        '    d["f0"] = 1',
        '    d["f1"] = 1',
        "    print(look(names, d))",
        "    return 0")),
    # The str view of the same question: it already had a dict branch, so this
    # is the "must not change" half of the pair, and the difference in emitted
    # C between the two cases is the whole point.
    ("dict-erased-str-view", _p(
        "def look(names, d):",
        "    var n = 0",
        "    for name in names:",
        "        if name in d:",
        "            n = n + 1",
        "    return n",
        "",
        "def main() -> Int:",
        '    var names = ["f0", "f1", "nope"]',
        "    var d = {}",
        '    d["f0"] = 1',
        '    d["f1"] = 1',
        "    print(look(names, d))",
        '    print(look(["f1"], d))',
        '    print(look(["nope"], d))',
        "    return 0")),
    # ...and the same question asked directly rather than in a loop, so a
    # failure names the shape rather than the count.
    ("dict-erased-direct", _p(
        "def has(d, k):",
        "    if k in d:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    var d = {}",
        '    d["a"] = 1',
        '    print(has(d, "a"))',
        '    print(has(d, "b"))',
        "    print(has({}, \"a\"))",
        "    return 0")),
    # An Int-keyed dict behind the same erased parameter: the `_kw` path, so
    # an integer needle is looked up as an integer rather than stringified.
    ("dict-erased-int-keys", _p(
        "def has(d, k):",
        "    if k in d:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    var d = {}",
        "    d[10] = 1",
        "    d[20] = 1",
        "    print(has(d, 10))",
        "    print(has(d, 20))",
        "    print(has(d, 30))",
        "    return 0")),
    # Mixed key domains in ONE dict, which is what makes the needle
    # discrimination load-bearing rather than incidental: `7` and `"7"` are
    # two different keys, and each must find only itself.
    #
    # TWO helpers, not one, because a single `has(d, k)` called with both a str
    # and an int argument hits an unrelated and separately documented defect
    # (bugs/CODEGEN_polymorphic_unannotated_param_vacuous_unanimity.md): the
    # unannotated parameter is typed `char *` by vacuous unanimity and the int
    # call site SIGSEGVs. Each helper here has a unanimous call-site set, so
    # this case exercises the dispatcher and nothing else. (That crash was
    # measured on this file's shape before it was written down; it is not what
    # this case is for.)
    ("dict-erased-mixed-keys", _p(
        "def has_str(d, k):",
        "    if k in d:",
        "        return 1",
        "    return 0",
        "",
        "def has_int(d, k):",
        "    if k in d:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    var d = {}",
        '    d["7"] = 1',
        "    d[7] = 2",
        '    print(has_str(d, "7"))',
        '    print(has_str(d, "8"))',
        "    print(has_int(d, 7))",
        "    print(has_int(d, 8))",
        "    return 0")),

    # ── a set of STRINGS behind an erased parameter, INT view ──────────────
    # The other half of the same defect: the needle is a boxed `char *` and
    # the int-domain probe cannot address a tag-1 slot at all. The needle comes
    # from a call so it is an int64_t, which is what selects the int view.
    ("set-erased-strs-int-view", _p(
        "def key():",
        '    return "a"',
        "",
        "def other():",
        '    return "c"',
        "",
        # Two helpers, one call site each: adding a string-LITERAL call site to
        # either one would make the codegen infer `char *` for the parameter
        # and take the str view, which is a different (already-working) path.
        "def has1(s, k):",
        "    if k in s:",
        "        return 1",
        "    return 0",
        "",
        "def has2(s, k):",
        "    if k in s:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        '    var s = {"a", "b"}',
        "    print(has1(s, key()))",
        "    print(has2(s, other()))",
        "    return 0")),
    ("set-erased-strs", _p(
        "def has(s, k):",
        "    if k in s:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        '    var s = {"a", "b"}',
        '    print(has(s, "a"))',
        '    print(has(s, "b"))',
        '    print(has(s, "c"))',
        "    return 0")),
    ("set-erased-ints", _p(
        "def has(s, k):",
        "    if k in s:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    var s = {1, 2, 3}",
        "    print(has(s, 1))",
        "    print(has(s, 3))",
        "    print(has(s, 4))",
        "    return 0")),

    # ── a LIST of strings behind an erased parameter ────────────────────────
    ("list-erased-strs", _p(
        "def has(xs, k):",
        "    if k in xs:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        '    var xs = ["a", "b", "c"]',
        '    print(has(xs, "a"))',
        '    print(has(xs, "c"))',
        '    print(has(xs, "d"))',
        "    return 0")),
    # ...including the `None` element, which is a real NULL slot: a str probe
    # that dereferenced it would segfault, so this case is also the guard on
    # mojo_in_dispatch_str's NULL handling being reachable from the int view.
    ("list-erased-with-none", _p(
        "def has(xs, k):",
        "    if k in xs:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        '    var xs = ["a", None]',
        "    print(has(xs, \"a\"))",
        "    print(has(xs, \"b\"))",
        "    return 0")),

    # ── containers arriving some other erased way ──────────────────────────
    # A dict returned from a call and a dict read out of a list of containers:
    # neither has a static type at the `in`.
    ("erased-via-return-and-list", _p(
        "def mk():",
        "    var d = {}",
        '    d["k"] = 1',
        "    return d",
        "",
        "def has(d, k):",
        "    if k in d:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    var d = mk()",
        '    print(has(d, "k"))',
        '    print(has(d, "nope"))',
        "    var ds = [mk()]",
        "    print(has(ds[0], \"k\"))",
        "    return 0")),
    # The needle is itself the result of a call, so it is not a variable the
    # codegen could have typed from its assignment, and the whole question goes
    # through the int dispatcher with a `char *` in hand.
    ("erased-both-args", _p(
        "def key():",
        '    return "k"',
        "",
        "def has(d, k):",
        "    if k in d:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    var d = {}",
        '    d["k"] = 1',
        "    print(has(d, key()))",
        '    print(has(d, "zz"))',
        "    return 0")),

    # ── what must NOT change ───────────────────────────────────────────────
    # The same programs with the container kept LOCAL lower to the typed
    # predicate before this change and must keep answering exactly as before.
    ("dict-typed-local", _p(
        "def main() -> Int:",
        "    var d = {}",
        '    d["a"] = 1',
        '    d["b"] = 2',
        '    print("a" in d)',
        '    print("z" in d)',
        '    print(10 in d)',
        "    return 0")),
    ("set-typed-local", _p(
        "def main() -> Int:",
        '    var s = {"a", "b"}',
        '    print("a" in s)',
        '    print("z" in s)',
        "    var t = {1, 2}",
        "    print(1 in t)",
        "    print(9 in t)",
        "    return 0")),
    ("list-typed-local", _p(
        "def main() -> Int:",
        '    var xs = ["a", "b"]',
        '    print("a" in xs)',
        '    print("z" in xs)',
        "    var ys = [1, 2]",
        "    print(1 in ys)",
        "    print(9 in ys)",
        "    return 0")),
    # An erased operand that is a str is still answerable: `in` on a string is
    # substring membership, and the compiled path has a dedicated predicate for
    # it. (A non-container like an int is NOT in this file: CPython raises
    # TypeError for `1 in 42`, so there is no reference answer to diff against,
    # and a case whose reference program cannot run is not evidence of
    # anything.)
    ("erased-str-operand", _p(
        "def has(x, k):",
        "    if k in x:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        '    print(has("abc", "a"))',
        '    print(has("abc", "z"))',
        "    return 0")),
    # `not in` routes through the same predicates with the answer negated.
    ("erased-not-in", _p(
        "def lacks(d, k):",
        "    if k not in d:",
        "        return 1",
        "    return 0",
        "",
        "def main() -> Int:",
        "    var d = {}",
        '    d["a"] = 1',
        '    print(lacks(d, "a"))',
        '    print(lacks(d, "z"))',
        "    return 0")),
]


def _py_source(src: str) -> str:
    """The same program as CPython sees it: drop the Mojo annotations."""
    out = []
    for line in src.splitlines():
        line = re.sub(r"\bvar\s+", "", line)
        line = re.sub(r"->\s*Int(?!\w)", "", line)
        out.append(line)
    return "\n".join(out) + "\n\nmain()\n"


def run_cpython(src: str, tmp: str):
    path = os.path.join(tmp, "ref.py")
    with open(path, "w") as f:
        f.write(_py_source(src))
    p = subprocess.run([sys.executable, path], capture_output=True, text=True,
                       timeout=60)
    return p.stdout, p.returncode, p.stderr


def run_compiled(src: str, tmp: str, name: str):
    """(stdout, exitcode) of the compiled program, or raises RuntimeError."""
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
    return p.stdout, p.returncode


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print every case, not just failures")
    ap.add_argument("--keep", action="store_true",
                    help="keep the generated C and binaries")
    args = ap.parse_args()

    tmp = tempfile.mkdtemp(prefix="intest-", dir=HERE)
    passed = failed = 0
    try:
        for name, src in CASES:
            py_out, py_rc, py_err = run_cpython(src, tmp)
            if py_rc != 0 or py_err.strip():
                # A reference program that cannot run makes the case
                # meaningless; say so instead of reporting a phantom failure.
                status = "BROKEN"
                note = "the reference program does not run under CPython:\n" \
                    + py_err[-1500:]
                failed += 1
            else:
                try:
                    c_out, c_rc = run_compiled(src, tmp, name)
                except Exception as e:                       # noqa: BLE001
                    status, note = "FAIL", str(e)
                    failed += 1
                else:
                    if (c_out, c_rc) == (py_out, py_rc):
                        status, note = "PASS", "%d line(s)" % len(
                            py_out.splitlines())
                        passed += 1
                    else:
                        status = "FAIL"
                        note = "compiled answer differs from CPython's"
                        if c_rc != py_rc:
                            note += " (exit %d vs %d)" % (c_rc, py_rc)
                        note += "\n" + _diff(py_out, c_out)
                        failed += 1
            if status != "PASS" or args.verbose:
                print("%-6s %-28s %s" % (status, name, note))
        if args.keep:
            print("kept: %s" % tmp)
            tmp = None
    finally:
        if tmp is not None:
            for f in os.listdir(tmp):
                os.unlink(os.path.join(tmp, f))
            os.rmdir(tmp)

    print("PASS=%d FAIL=%d of %d" % (passed, failed, len(CASES)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())