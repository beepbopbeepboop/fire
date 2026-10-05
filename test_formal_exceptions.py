#!/usr/bin/env python3
"""test_formal_exceptions.py -- the formal backends against CPython on
EXCEPTIONS, and the table that says which of them are answered, which are
refused, and what each refusal is allowed to say.

**Why this file exists rather than more rows in `test_formal_run.py`.**  That
file's CPython-pair runner requires the reference program to exit 0
(`run_cpython_pair_case` treats a nonzero reference exit as "the oracle is not
an oracle"), which is exactly the exit status every program in THIS file leaves
behind.  A whole class of observable — "what does the program leave behind when
it fails" — was therefore inexpressible there, and the exception contract is
almost entirely that class.  `run_pair` below compares stdout AND exit status
and accepts any reference status, which is what makes "CPython exits 1 here"
an assertion rather than an impossibility.

**CPython is the oracle, everywhere the construct runs.**  A hand-written
expected constant per row would assert about this file's author; running the
same program under `python3` asks instead.  The two exceptions, both stated
where they apply:

  * the exit status of an UNCAUGHT exception is part of the oracle, but the
    TRACEBACK on stderr is not, and cannot be: `print` on this path is the C
    library's, an exception message is not something the image formats, and the
    property that is asserted instead is that nothing about the diagnostic
    reaches **stdout** — which is what keeps a failing program's real output
    comparable.  This is the arrangement `test_formal_debug_assert.py` uses for
    the same reason.
  * a `try`/`except` arm with a body is REFUSED on both backends, by name, and
    the needle is the checked claim.  Those rows are here so the refusal stays
    honest and specific rather than because the construct works.

**Both architectures, always.**  The two disagreeing answers this group exists to
catch have both happened on this backend: arm64 refused a bracketed callee as a
name with no home while x86-64 refused it as an unsupported call target, from
two private copies of one rule.  A one-sided assertion would have been green
throughout.

Run:  python3 test_formal_exceptions.py [-v] [case ...]
"""
import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60
BACKENDS = ("arm64", "x86_64")

RESULTS = []


def check(ok, what, detail=""):
    RESULTS.append((bool(ok), what))
    if not ok:
        print(f"FAIL  {what}" + (f": {detail}" if detail else ""), flush=True)
    return bool(ok)


def build(source, out, backend=None, tmpdir=None, arg=3):
    """`fire.py build --formal --no-prove -n <arg>`, as (rc, output).

    `-n` is the formal backend's entry-argument flag and the CPython half is
    called with the SAME value, so a row whose whole subject is "this condition
    is true at 3 and false at 0" is decidable. Omitting it here is not a
    cosmetic default: the entry argument would silently be 10, and every row
    with an argument in it would be measuring a different program from the one
    CPython ran — which is the failure this file's oracle exists to prevent.
    """
    path = os.path.join(tmpdir, "prog.mojo")
    with open(path, "w") as f:
        f.write(source)
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out]
    if backend:
        cmd.append(f"--backend={backend}")
    cmd += ["-n", str(arg), path]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run(path):
    p = subprocess.run([path], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT)
    return p.returncode, p.stdout, p.stderr


def cpython(source, tmpdir):
    """CPython's (exit status, stdout) for a program, run here at test time."""
    path = os.path.join(tmpdir, "ref.py")
    with open(path, "w") as f:
        f.write(source)
    p = subprocess.run([sys.executable, path], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT)
    return p.returncode, p.stdout


# ── the ANSWERED table ──────────────────────────────────────────────────────
#
# (name, mojo source, cpython source, entry argument)
#
# Both halves are the SAME program; the runner appends `sys.exit(main(N))` to
# the CPython one and the build driver calls `main(N)` for the Mojo one, so the
# argument and the call are facts about the harness rather than about either
# program.  `var x = v` is Mojo and `printf` is a C-library function this
# backend maps, so the two halves cannot be one text — which is why each row
# supplies its own rather than this file transliterating one.  A transliteration
# written here would be a second statement of what the program means, and it is
# the thing under test.
#
# The entry argument is a third column rather than a constant because it is
# what makes several of these rows decidable: `uncaught_zd` divides by `n - 1`
# and is a `ZeroDivisionError` at 1 and an ordinary answer at 3, so one row
# pins both halves of the guard.
CASES = [
    # ── a `raise` of a builtin exception CLASS, called and bare ─────────────
    # This is the spelling that used to be refused twice over, each refusal
    # naming a SYMBOL instead of the construct: `raise ValueError("boom")`
    # emitted `BL ValueError` and was caught by the link audit ("the image
    # would bind 1 symbol(s) that nothing provides: ValueError"), and a bare
    # `raise ValueError` reached the name reader and was refused as "'ValueError'
    # has no home".  CPython's contract for an uncaught one is stdout flushed,
    # status 1, and the argument expressions already run — which is what the
    # `print` above `raise` and the marker after it are here to pin.
    ("raise_builtin_exception_with_a_message",
     "def main(n):\n"
     "    print('before')\n"
     "    raise ValueError('boom')\n"
     "    print('after')\n"
     "    return 0\n",
     "def main(n):\n"
     "    print('before')\n"
     "    raise ValueError('boom')\n"
     "    print('after')\n"
     "    return 0\n", 3),
    ("raise_builtin_exception_bare",
     "def main(n):\n"
     "    print('before')\n"
     "    raise ValueError\n"
     "    print('after')\n"
     "    return 0\n",
     "def main(n):\n"
     "    print('before')\n"
     "    raise ValueError\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # Several arguments, because a call's arguments are evaluated left to
    # right and a lowering that drops them all is indistinguishable from one
    # that keeps only the first.
    ("raise_builtin_exception_with_several_arguments",
     "def main(n):\n"
     "    print('before')\n"
     "    raise OSError('e', 2)\n"
     "    return 0\n",
     "def main(n):\n"
     "    print('before')\n"
     "    raise OSError('e', 2)\n"
     "    return 0\n", 3),
    # **The row that says the ARGUMENT EXPRESSIONS RUN.** `raise ValueError(g())`
    # is where "evaluate the expression for its side effects" is observable: a
    # lowering that dropped the call would exit 1 with the right status and
    # nothing printed, which is the wrong program.
    ("raise_a_builtin_exception_runs_its_argument_expressions",
     "def g():\n"
     "    print('arg')\n"
     "    return 1\n"
     "\n"
     "def main(n):\n"
     "    raise ValueError(g())\n"
     "    return 0\n",
     "def g():\n"
     "    print('arg')\n"
     "    return 1\n"
     "\n"
     "def main(n):\n"
     "    raise ValueError(g())\n"
     "    return 0\n", 3),
    # A class THIS image declares, called and bare.  The bare spelling is a
    # different program in CPython and had to become one here: `raise MyErr`
    # instantiates the class, so it is `raise MyErr()` and the constructor runs.
    ("raise_a_declared_class_called",
     "class MyErr:\n"
     "    pass\n"
     "\n"
     "def main(n):\n"
     "    print('before')\n"
     "    raise MyErr()\n"
     "    return 0\n",
     "class MyErr(Exception):\n"
     "    pass\n"
     "\n"
     "def main(n):\n"
     "    print('before')\n"
     "    raise MyErr()\n"
     "    return 0\n", 3),
    ("raise_a_declared_class_bare",
     "class MyErr:\n"
     "    pass\n"
     "\n"
     "def main(n):\n"
     "    print('before')\n"
     "    raise MyErr\n"
     "    return 0\n",
     "class MyErr(Exception):\n"
     "    pass\n"
     "\n"
     "def main(n):\n"
     "    print('before')\n"
     "    raise MyErr\n"
     "    return 0\n", 3),
    # A subclass of a builtin base — the spelling a user writes when they want
    # their own exception type, and the one
    # `bugs/FORMAL_an_exception_subclass_of_a_builtin_base_builds_and_then_
    # dies.md` measured (it built and then died; it is still refused for the
    # CATCHING half, which is a different question and is pinned below).
    ("raise_a_subclass_of_a_builtin_base",
     "class MyErr(ValueError):\n"
     "    pass\n"
     "\n"
     "def main(n):\n"
     "    print('before')\n"
     "    raise MyErr('m')\n"
     "    return 0\n",
     "class MyErr(ValueError):\n"
     "    pass\n"
     "\n"
     "def main(n):\n"
     "    print('before')\n"
     "    raise MyErr('m')\n"
     "    return 0\n", 3),
    # A `raise` whose value is an INSTANCE, and one whose value is a call's
    # RESULT: neither names a class, so both keep the "emit the expression as
    # written" path.  These are the rows that would notice a `raise` lowering
    # that dropped the value on the floor for everything.
    ("raise_an_exception_instance_held_in_a_local",
     "class MyErr:\n"
     "    pass\n"
     "\n"
     "def main(n):\n"
     "    e = MyErr()\n"
     "    print('before')\n"
     "    raise e\n"
     "    return 0\n",
     "class MyErr(Exception):\n"
     "    pass\n"
     "\n"
     "def main(n):\n"
     "    e = MyErr()\n"
     "    print('before')\n"
     "    raise e\n"
     "    return 0\n", 3),
    # CPython prints a traceback and exits 1 for a `raise` of something that is
    # not an exception, and so must this — the value is emitted, not checked.
    ("raise_of_a_non_exception",
     "def main(n):\n"
     "    print('before')\n"
     "    raise 'a plain string'\n"
     "    return 0\n",
     "def main(n):\n"
     "    print('before')\n"
     "    raise 'a plain string'\n"
     "    return 0\n", 3),
    # ── `SystemExit`, the one class whose status is not 1 ───────────────────
    # It is not a failure: it is how a program says "stop with this status", so
    # CPython never prints a traceback for it and the status is its ARGUMENT.
    # Five rows, because the five are different rules and a single one would
    # pass with the others wrong: no argument, an explicit 0, a literal 3, a
    # negative one (truncated to a byte by the C library) and a non-integer one
    # (which CPython prints and turns into status 1).
    ("systemexit_bare_exits_zero",
     "def main(n):\n"
     "    print('before')\n"
     "    raise SystemExit\n",
     "def main(n):\n"
     "    print('before')\n"
     "    raise SystemExit\n", 3),
    ("systemexit_with_a_zero_status",
     "def main(n):\n"
     "    print('before')\n"
     "    raise SystemExit(0)\n",
     "def main(n):\n"
     "    print('before')\n"
     "    raise SystemExit(0)\n", 3),
    ("systemexit_with_a_literal_status",
     "def main(n):\n"
     "    print('before')\n"
     "    raise SystemExit(3)\n",
     "def main(n):\n"
     "    print('before')\n"
     "    raise SystemExit(3)\n", 3),
    ("systemexit_with_a_negative_status_is_truncated_to_a_byte",
     "def main(n):\n"
     "    print('before')\n"
     "    raise SystemExit(-1)\n",
     "def main(n):\n"
     "    print('before')\n"
     "    raise SystemExit(-1)\n", 3),
    ("systemexit_with_a_non_integer_argument_is_status_one",
     "def main(n):\n"
     "    print('before')\n"
     "    raise SystemExit('a message')\n",
     "def main(n):\n"
     "    print('before')\n"
     "    raise SystemExit('a message')\n", 3),
    # ── ZeroDivisionError from a builtin operation ───────────────────────────
    # The INTEGER divide already guarded itself; these pin it against CPython
    # rather than against a constant, and `uncaught_zd_*` is the pair that says
    # the guard is on the DIVISOR AT RUN TIME rather than on a literal: the same
    # text answers differently at 1 and at 3.
    ("uncaught_integer_division_by_zero",
     "def main(n):\n"
     "    print('before')\n"
     "    x = 1 // (n - 1)\n"
     "    print('after')\n"
     "    return 0\n",
     "def main(n):\n"
     "    print('before')\n"
     "    x = 1 // (n - 1)\n"
     "    print('after')\n"
     "    return 0\n", 1),
    ("the_same_text_divides_when_the_divisor_is_not_zero",
     "def main(n):\n"
     "    print('before')\n"
     "    x = 1 // (n - 1)\n"
     "    print('after')\n"
     "    return 0\n",
     "def main(n):\n"
     "    print('before')\n"
     "    x = 1 // (n - 1)\n"
     "    print('after')\n"
     "    return 0\n", 3),
    ("uncaught_modulo_by_zero",
     "def main(n):\n"
     "    print('before')\n"
     "    x = n % 0\n"
     "    print('after')\n"
     "    return 0\n",
     "def main(n):\n"
     "    print('before')\n"
     "    x = n % 0\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # **The float divide, which used to compute `+inf` and carry on.**  IEEE-754
    # does not trap, so an emitted `FDIV` answers a NUMBER for a program CPython
    # refuses; measured before the guard, this printed `after` and exited 0.
    # `bugs/FORMAL_float_zero_division.md` recorded that divergence and is gone
    # with its fix — and it is fixed by an EMITTED GUARD, not by asking the
    # compiler to fold the divisor, which is why the variable row below is here
    # too.
    ("float_divide_by_a_zero_divisor_leaves",
     "def main(n):\n"
     "    print('before')\n"
     "    x = 1.0 / 0.0\n"
     "    print('after')\n"
     "    return 0\n",
     "def main(n):\n"
     "    print('before')\n"
     "    x = 1.0 / 0.0\n"
     "    print('after')\n"
     "    return 0\n", 3),
    ("float_divide_by_a_zero_divisor_held_in_a_variable_leaves",
     "def main(n):\n"
     "    z = 0.0\n"
     "    print('before')\n"
     "    x = 1.0 / z\n"
     "    print('after')\n"
     "    return 0\n",
     "def main(n):\n"
     "    z = 0.0\n"
     "    print('before')\n"
     "    x = 1.0 / z\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # `-0.0` is the other zero and a `CMP` against `+0.0` would miss it: the
    # guard tests the PATTERN with the sign bit dropped, so this row is the one
    # that would notice a repair that went back to comparing against a literal.
    ("float_divide_by_negative_zero_leaves",
     "def main(n):\n"
     "    z = 0.0 - 0.0\n"
     "    print('before')\n"
     "    x = 1.0 / z\n"
     "    print('after')\n"
     "    return 0\n",
     "def main(n):\n"
     "    z = 0.0 - 0.0\n"
     "    print('before')\n"
     "    x = 1.0 / z\n"
     "    print('after')\n"
     "    return 0\n", 3),
    # ── the other builtin-raised ones ───────────────────────────────────────
    ("uncaught_index_error",
     "def main(n):\n"
     "    xs = [1, 2, 3]\n"
     "    print('before')\n"
     "    print(xs[5])\n"
     "    return 0\n",
     "def main(n):\n"
     "    xs = [1, 2, 3]\n"
     "    print('before')\n"
     "    print(xs[5])\n"
     "    return 0\n", 3),
    ("uncaught_key_error",
     "def main(n):\n"
     "    d = {'a': 1}\n"
     "    print('before')\n"
     "    print(d['b'])\n"
     "    return 0\n",
     "def main(n):\n"
     "    d = {'a': 1}\n"
     "    print('before')\n"
     "    print(d['b'])\n"
     "    return 0\n", 3),
    # ── `assert` ────────────────────────────────────────────────────────────
    # The pair is the control: same text, one value that satisfies the condition
    # and one that does not.  A lowering that always fired, or never fired,
    # would satisfy one row of the pair and fail the other.
    ("assert_that_holds_reaches_the_code_after_it",
     "def main(n):\n"
     "    assert n > 0\n"
     "    print('after')\n"
     "    return 0\n",
     "def main(n):\n"
     "    assert n > 0\n"
     "    print('after')\n"
     "    return 0\n", 3),
    ("assert_that_fails_leaves",
     "def main(n):\n"
     "    print('before')\n"
     "    assert n > 0\n"
     "    print('after')\n"
     "    return 0\n",
     "def main(n):\n"
     "    print('before')\n"
     "    assert n > 0\n"
     "    print('after')\n"
     "    return 0\n", 0),
    # The MESSAGE is evaluated for its effects on the failing path and nowhere
    # else, so a `print` inside it is the observable — and the pair with the
    # row above says a passing assert pays nothing for its message.
    ("assert_message_runs_only_when_the_assert_fails",
     "def why():\n"
     "    print('why')\n"
     "    return 'nope'\n"
     "\n"
     "def main(n):\n"
     "    assert n > 0, why()\n"
     "    print('after')\n"
     "    return 0\n",
     "def why():\n"
     "    print('why')\n"
     "    return 'nope'\n"
     "\n"
     "def main(n):\n"
     "    assert n > 0, why()\n"
     "    print('after')\n"
     "    return 0\n", 0),
    # ── `finally`, which DOES run on the way out ────────────────────────────
    # This is the part of the exception contract that was already right and that
    # every row above depends on: a `raise` inside a `try` still runs the
    # `finally`.  It is here because a fix to the `raise` lowering that lost the
    # flush would keep every row above green (they have no `finally`) and break
    # only this one.
    ("a_finally_runs_on_the_way_out_of_a_raise",
     "def main(n):\n"
     "    try:\n"
     "        print('body')\n"
     "        raise ValueError('m')\n"
     "    finally:\n"
     "        print('fin')\n"
     "    return 0\n",
     "def main(n):\n"
     "    try:\n"
     "        print('body')\n"
     "        raise ValueError('m')\n"
     "    finally:\n"
     "        print('fin')\n"
     "    return 0\n", 3),
    ("a_finally_runs_on_the_way_out_of_a_failing_assert",
     "def main(n):\n"
     "    try:\n"
     "        print('body')\n"
     "        assert n > 0\n"
     "    finally:\n"
     "        print('fin')\n"
     "    return 0\n",
     "def main(n):\n"
     "    try:\n"
     "        print('body')\n"
     "        assert n > 0\n"
     "    finally:\n"
     "        print('fin')\n"
     "    return 0\n", 0),
    ("a_finally_runs_before_a_return",
     "def main(n):\n"
     "    try:\n"
     "        return 5\n"
     "    finally:\n"
     "        print('fin')\n"
     "    return 0\n",
     "def main(n):\n"
     "    try:\n"
     "        return 5\n"
     "    finally:\n"
     "        print('fin')\n"
     "    return 0\n", 3),
    ("nested_finallys_run_inside_out",
     "def main(n):\n"
     "    try:\n"
     "        try:\n"
     "            print('inner')\n"
     "        finally:\n"
     "            print('innerfin')\n"
     "    finally:\n"
     "        print('outerfin')\n"
     "    return 0\n",
     "def main(n):\n"
     "    try:\n"
     "        try:\n"
     "            print('inner')\n"
     "        finally:\n"
     "            print('innerfin')\n"
     "    finally:\n"
     "        print('outerfin')\n"
     "    return 0\n", 3),
    # ── a `try` with no raising body ────────────────────────────────────────
    # The `except: pass` shape, which is the commonest in the corpus and must
    # keep building: the arm has no effect to drop, so nothing is lost by
    # leaving it out, and this row is what would notice a repair that started
    # refusing it.
    ("an_except_pass_arm_still_builds",
     "def main(n):\n"
     "    try:\n"
     "        print('body')\n"
     "    except ValueError:\n"
     "        pass\n"
     "    return 0\n",
     "def main(n):\n"
     "    try:\n"
     "        print('body')\n"
     "    except ValueError:\n"
     "        pass\n"
     "    return 0\n", 3),
    ("else_runs_when_the_body_completed",
     "def main(n):\n"
     "    try:\n"
     "        print('body')\n"
     "    finally:\n"
     "        print('fin')\n"
     "    else_marker = 1\n"
     "    print('done')\n"
     "    return 0\n",
     "def main(n):\n"
     "    try:\n"
     "        print('body')\n"
     "    finally:\n"
     "        print('fin')\n"
     "    print('done')\n"
     "    return 0\n", 3),
]

# ── the REFUSED table ───────────────────────────────────────────────────────
#
# (name, mojo source, needle)
#
# A handler arm with a body is refused, and the refusal has to NAME the
# construct — that is the whole assertion here, and it is a real one: the
# alternative was a program that built, ran, printed nothing and exited 0, with
# no diagnostic anywhere.  The needles are checked exactly, on BOTH
# architectures, because "the two architectures refuse identically" is itself
# the property.
#
# `test_formal_run.py` also carries rows for this subject; these are here
# because that file's runner cannot express a case whose CPython half exits
# nonzero, and because the three spellings below differ in which refusal answers
# them and that difference is the point.
REFUSALS = [
    ("an_except_arm_with_a_print_is_refused_by_name",
     "def main(n):\n"
     "    try:\n"
     "        raise ValueError('m')\n"
     "    except ValueError:\n"
     "        print('HANDLER RAN')\n"
     "    return 0\n",
     "is a handler arm with a body this path cannot put in the image"),
    ("an_except_as_binding_is_refused_by_name",
     "def main(n):\n"
     "    try:\n"
     "        raise ValueError('m')\n"
     "    except ValueError as e:\n"
     "        print('caught')\n"
     "    return 0\n",
     "`ValueError` as e is a handler arm with a body this path cannot "
     "put in the image"),
    ("a_bare_except_with_a_body_is_refused_by_name",
     "def main(n):\n"
     "    try:\n"
     "        raise ValueError('m')\n"
     "    except:\n"
     "        print('caught')\n"
     "    return 0\n",
     "a bare `except:` is a handler arm with a body this path cannot put in "
     "the image"),
]


def run_pair(name, source, cpython_source, arg, tmpdir, verbose):
    """Both backends against CPython, comparing stdout AND exit status."""
    ref_source = cpython_source + f"\nimport sys\nsys.exit(main({arg}))\n"
    want_exit, want_out = cpython(ref_source, tmpdir)
    if verbose:
        print(f"      CPython: exit={want_exit} out={want_out!r}")
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(source, out, backend=backend, tmpdir=tmpdir,
                         arg=arg)
        if not check(rc == 0, f"{name} builds on {backend}", text[-400:]):
            continue
        got_exit, got_out, _err = run(out)
        if not check(got_out == want_out,
                     f"{name} on {backend} prints what CPython prints",
                     f"printed {got_out!r}, CPython printed {want_out!r}"):
            continue
        check(got_exit == want_exit,
              f"{name} on {backend} exits as CPython does",
              f"exit {got_exit}, CPython exits {want_exit}")


def run_refusal(name, source, needle, tmpdir, verbose):
    """Both backends must REFUSE, with the needle in the message."""
    seen = {}
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(source, out, backend=backend, tmpdir=tmpdir)
        if not check(rc != 0, f"{name} is refused on {backend}",
                     "it BUILT and ran, so a program the source says has an "
                     "arm this path cannot place is in the image as a program "
                     "whose arm never runs"):
            continue
        seen[backend] = text
        check(needle in text,
              f"{name} on {backend} names the construct",
              f"the message does not contain {needle!r}: {text.strip()[-300:]}")
    if len(seen) == 2 and verbose:
        print(f"      arm64 and x86-64 agree: {needle!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmpdir:
        for name, source, cpython_source, arg in CASES:
            if args.cases and name not in args.cases:
                continue
            run_pair(name, source, cpython_source, arg, tmpdir, args.verbose)
        for name, source, needle in REFUSALS:
            if args.cases and name not in args.cases:
                continue
            run_refusal(name, source, needle, tmpdir, args.verbose)

    total = len(RESULTS)
    passed = sum(1 for ok, _ in RESULTS if ok)
    print(f"\nexceptions: PASS={passed} FAIL={total - passed} "
          f"({total} checks)")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())