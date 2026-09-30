#!/usr/bin/env python3
"""A `comptime` binding whose value is TEXT, read as text and EXECUTED.

What is under test. `formal/model.py`'s kind rules decide, before anything is
emitted, whether a read holds a `char *` or a number — that decision is what
`print` turns into `%s` against `%lld`, and it is asked by truthiness, by `len`
and by a string `==` as well. A `comptime NAME = …` statement was never in
that analysis: `ValueKinds._scan` walks assignments, `var`s and control flow,
and a `comptime` binding is none of those, so a folded STRING binding arrived
at every one of those questions unclassified. The consequence was not a
refusal. `_emit_comptime_read` materializes the interned literal for the text —
so the word in the register really is a `char *` — and the classification then
printed it as a NUMBER:

    $ cat b7.mojo
    def main():
        comptime OS = "darwin"
        var t = OS
        print("t=", t)

    $ ./b7                      # arm64
    t= 4376183704
    $ ./b7                      # x86-64, same source
    t= 4307186585

Two numbers, one source, neither of them the text. The identical program with
an ordinary `var` printed `darwin` on both, which is what made it a bug rather
than a limit, and `print(OS)` with no `var` in between was REFUSED (correctly,
as a guard) while `print(t)` was answered wrongly — the guard could see the AST
and one local was enough to put the value out of its reach.

Only the kind-deciding paths were wrong. `t == "ab"` was already right, because
both sides are interned and compared as pointers.

THE ORACLE. `comptime` is a keyword CPython cannot parse, so the oracle for
each case is the same program with the keyword and its compile-time-only
framing removed — a module-level binding the build FOLDS, and a local the
program copies it into:

    OS = "darwin"
    t = OS
    print("t=", t)

CPython's output for that is the expected value below, computed here at run
time by `python3` rather than written down, so the two architectures have to
agree with a third implementation rather than with a literal in this file.
That is also the honest statement of what the construct is: a `comptime`
binding is a compile-time constant whose every read yields that constant
(`mojo/middle/comptime.py` rule 3), and a constant's value does not depend on
how it was spelled.

REFUSED below is the half that keeps the first half honest. The fix narrows
"unclassified" to "text" and nothing else: a `comptime` LIST binding is not
text, and the subscript of one is still refused, because a subscript of a
blob is an element index and only the ELEMENT's kind would say what to print —
and nothing here knows it. A widening that answered that would be exactly the
guess the refusal exists to prevent, and it would print an address as text.

Run:  python3 test_formal_comptime_string.py [-v] [case ...]
"""
import argparse
import os
import platform
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 600
RUN_TIMEOUT = 60


def cpython(source: str) -> tuple:
    """Run the SAME program under CPython; return `(stdout, exit status)`.

    Two substitutions, both of them keywords CPython's parser does not have and
    both of which are pure DECLARATION syntax: `comptime ` and `var ` at the
    start of a statement become nothing, so

        def main():
            comptime OS = "darwin"
            var t = OS
            print("t=", t)

    becomes a module-level `OS` and a local `t` holding it. The value flow —
    what every read of `t` yields — is unchanged, which is the whole of the
    claim under test (`mojo/middle/comptime.py` rule 3: every read of a bound
    name yields the constant).

    `main()` is RAISED out of rather than merely called, and that is the second
    half of the same substitution: a formal entry point's RETURN VALUE is the
    process exit status, while CPython's `main` is an ordinary function whose
    return value nothing turns into one. `raise SystemExit(main())` is the one
    driver on which the two agree, and without it a case asserting the exit
    status would compare the image's status against CPython's 0 — which passes
    for every `return 0` and is precisely the wrong answer for the `return 1` a
    comparison case is written to produce.

    A line-anchored substitution rather than a parse on purpose: it cannot
    reformat the program, so the two runs differ by the keywords and by the
    entry-point convention and by nothing else. `print` is the one name whose
    CPython meaning differs from Mojo's, and every case here uses it with the
    default `sep`/`end`; none asserts a printed BOOLEAN, because this backend
    has no `Bool` — it is 0/1, where CPython prints `True`/`False`.
    """
    p = subprocess.run(
        [sys.executable, "-c",
         re.sub(r"(?m)^(\s*)(comptime |var )+", r"\1", source)
         + "\nraise SystemExit(main())\n"],
        capture_output=True, text=True, timeout=RUN_TIMEOUT)
    return p.stdout, p.returncode


# (name, mojo source, expected stdout, expected exit status).
#
# The stdout is not written down from the implementation: `cpython()` runs the
# same program under CPython and the case compares against THAT, with the
# stated literal kept alongside so that a disagreement between this file and
# CPython is reported as a bug in this file's expectation rather than as a
# failure of the code under test. `expected stdout` of None means the exit
# status is the whole assertion — the comparison case, where CPython is asked
# what the status is rather than this file stating it.
EXECUTED = [
    # The bug itself, in its smallest form: one `var` between the binding and
    # the print, which is all it takes to put the value out of the AST guard's
    # reach. Before, this printed a different number on each architecture.
    ("a_comptime_string_through_one_var_prints_as_text",
     "def main():\n"
     "    comptime OS = \"darwin\"\n"
     "    var t = OS\n"
     "    print(\"t=\", t)\n",
     "t= darwin\n", 0),
    # …and with NO `var`, which used to be REFUSED. The refusal was correct as a
    # guard and wrong as a verdict: the binding's value is a compile-time
    # constant the emission already holds, so this was answerable.
    ("a_comptime_string_read_directly_prints_as_text",
     "def main():\n"
     "    comptime OS = \"darwin\"\n"
     "    print(\"os=\", OS)\n",
     "os= darwin\n", 0),
    # Two copies, so the marking propagates rather than being re-derived: the
    # kind of `t` is what `u`'s own classification asks about, and a fix that
    # answered the read and not the store would leave this one a number.
    ("a_comptime_string_through_two_vars_prints_as_text",
     "def main():\n"
     "    comptime OS = \"darwin\"\n"
     "    var t = OS\n"
     "    var u = t\n"
     "    print(t, u)\n",
     "darwin darwin\n", 0),
    # A NUMBER, through the same `var`. The fix narrows "unclassified" to the
    # folded value's own kind and must not move anything else: `comptime N = 5`
    # is a word, and printing a word as text is the same defect with the signs
    # swapped.
    ("a_comptime_number_through_one_var_still_prints_as_a_number",
     "def main():\n"
     "    comptime N = 5\n"
     "    var t = N\n"
     "    print(\"n=\", t)\n",
     "n= 5\n", 0),
    # …and read DIRECTLY, which used to be refused. The two routes to one value
    # gave two verdicts: a module-level `comptime` is substituted at its read as
    # a literal AST node and so always classified, while a function-local one is
    # not — so `print(N)` was a refusal and `var t = N; print(t)` was a number.
    # Whichever verdict is right, both routes have to give it.
    ("a_comptime_number_read_directly_prints_as_a_number",
     "def main():\n"
     "    comptime N = 5\n"
     "    print(\"n=\", N)\n",
     "n= 5\n", 0),
    # The same value COMPARED, which was already right and is here to say so:
    # a fix that made `print` answer from the interned pointer without the
    # comparison agreeing would be two half-fixes. The exit status is the
    # comparison, and CPython is asked what that status is.
    ("a_comptime_string_through_one_var_compares_equal",
     "def main():\n"
     "    comptime OS = \"darwin\"\n"
     "    var t = OS\n"
     "    return 1 if t == \"darwin\" else 0\n",
     None, 1),
    # …and TRUTHY, which is the third consumer of the same answer and the one
    # that decides whether the string is tested for emptiness rather than
    # compared against a null pointer.
    ("a_comptime_string_through_one_var_is_truthy",
     "def main():\n"
     "    comptime OS = \"darwin\"\n"
     "    var t = OS\n"
     "    if t:\n"
     "        print(\"yes\")\n"
     "    return 0\n",
     "yes\n", 0),
    # An EMPTY comptime string, because "" is the one value where "text" and
    # "true" disagree, and a fix that keyed on the pointer being non-null
    # rather than on the text would get this one backwards.
    ("an_empty_comptime_string_is_falsy",
     "def main():\n"
     "    comptime OS = \"\"\n"
     "    var t = OS\n"
     "    if t:\n"
     "        print(\"yes\")\n"
     "    else:\n"
     "        print(\"no\")\n"
     "    return 0\n",
     "no\n", 0),
]

# (name, source, needle). A `comptime` LIST is compile-time state too, and its
# read is a SUBSCRIPT — the element's kind, not the binding's, is what would
# say how to print it, and nothing here knows it. Answering it would mean
# printing an element address as text, which is the failure the print refusal
# was written for.
REFUSED = [
    ("a_comptime_list_subscript_is_still_unclassifiable",
     "def main():\n"
     "    comptime L = [1, 2, 3]\n"
     "    print(\"t=\", L[1])\n",
     "print() cannot tell whether SubscriptExpr is a string or a number"),
]


def build(src, out, backend=None):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out]
    if backend:
        cmd.append(f"--backend={backend}")
    cmd.append(src)
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run_executed(name, source, want_stdout, want_exit, tmpdir, verbose):
    """Build the arm64 image, EXECUTE it, and compare against CPython.

    arm64 only, for the reason `test_formal_run.py` is arm64-only: a formal
    x86-64 Mach-O needs Rosetta to launch on an arm64 Mac. That the x86-64
    backend reaches the SAME answers is checked by the refusal half below,
    which builds for both architectures, and by `test_formal_run.py`'s own
    x86-64 cases.
    """
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    out = os.path.join(tmpdir, name)
    rc, text = build(src, out)
    if rc != 0:
        return False, text.strip()[-300:]
    if not os.path.isfile(out):
        return False, "build reported success but wrote no binary"
    run = subprocess.run([out], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    ref_out, ref_exit = cpython(source)
    if ref_exit != want_exit:
        # Same reasoning as below, and it is the one that matters most: a
        # disagreement about the EXIT STATUS is a disagreement about what the
        # program computes, so this file's expectation is what is wrong.
        return False, (f"CPython exits {ref_exit} where this file expects "
                       f"{want_exit}: the expectation, not the code under "
                       f"test, is what disagrees")
    if run.returncode != want_exit:
        return False, (f"exit status {run.returncode}, expected {want_exit} "
                       f"(which is what CPython gives the same program)")
    if want_stdout is not None:
        if ref_out != want_stdout:
            # A mismatch here is a bug in this FILE's stated expectation, not in
            # the code under test, and must not be reported as the latter.
            return False, (f"CPython disagrees with the expectation this file "
                           f"states: {ref_out!r} != {want_stdout!r}")
        if run.stdout != ref_out:
            return False, (f"stdout {run.stdout!r} != CPython's {ref_out!r} — "
                           f"a wrong value is the worse outcome, not a refusal")
    if verbose:
        print(f"      stdout={run.stdout.strip()!r} exit={run.returncode}")
    return True, ""


def run_refused(name, source, needle, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ("arm64", "x86_64"):
        rc, text = build(src, os.path.join(tmpdir, f"{name}.{backend}"),
                         backend=backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a construct with no "
                           f"answer (expected a refusal naming {needle!r}); "
                           f"the binary is the real answer here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not with the "
                           f"expected words {needle!r}: {text.strip()[-220:]}")
    if verbose:
        print(f"      refused identically on arm64 and x86-64: {needle!r}")
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0

    known = {c[0] for c in EXECUTED} | {c[0] for c in REFUSED}
    if args.cases:
        missing = set(args.cases) - known
        if missing:
            print(f"ERROR: unknown case(s): {sorted(missing)}", file=sys.stderr)
            return 2

    checks = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, source, want_out, want_exit in EXECUTED:
            if args.cases and name not in args.cases:
                continue
            try:
                ok, detail = run_executed(name, source, want_out, want_exit,
                                          tmpdir, args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            checks.append((name, ok, detail))
        for name, source, needle in REFUSED:
            if args.cases and name not in args.cases:
                continue
            try:
                ok, detail = run_refused(name, source, needle, tmpdir,
                                         args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            checks.append((name, ok, detail))

    passed = failed = 0
    for name, ok, detail in checks:
        if ok:
            passed += 1
            print(f"  PASS  {name}")
        else:
            failed += 1
            print(f"  FAIL  {name}: {detail}")

    print(f"\ncomptime strings: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
