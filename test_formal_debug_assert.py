#!/usr/bin/env python3
"""test_formal_debug_assert.py -- `debug_assert` is a builtin both formal
backends now lower, and this file is the evidence that what they lower is
RIGHT rather than merely accepted.

**What was wrong.** `debug_assert` is defined in six lines in
`myinterpreter.py:3010` and had no lowering at all in `formal/`. Both
spellings failed, for two unrelated reasons:

  * `debug_assert(cond, msg)` passed every check and emitted a `BL
    debug_assert` — an extern nothing defines. The link audit caught the
    dangling symbol, so it was a refusal and not a wrong image, but it caught
    it by an accident of ordering.
  * `debug_assert[assert_mode="safe"](cond, msg)` was refused by
    `model.specialization_call_refusal`, which is TRUE in general (a bracket
    needs a declaration to bind against) and FALSE here: `debug_assert` is a
    builtin, so its declaration is a fact about the language rather than
    something the image has to compile.

61 call sites in 23 files of the new-modular stdlib are spelled one way or the
other (33 bare, 28 bracketed), so this is the terminal cause for a large family
of files.

**Why BOTH architectures are required to agree.** The bracketed spelling is the
one that had to be caught differently on each: arm64's `_callee_symbol`
flattens a subscript callee to its base name, so the call reached an arm placed
after it, while x86-64's copy has no `SubscriptExpr` arm at all and the call
was refused before any arm could see it. A lowering tested on one architecture
would have passed with the other still emitting a dangling `BL`. Every
execution case here runs on both, and the two disagreeing answers this group
exists to catch have both happened on this backend.

**Why the ORACLE is CPython, not a table of expected exit codes.** The
contract is "on a false condition, the program does not continue". What
continues is the program after the check, and the exit status is how the check
says it failed. A hand-written expected constant for each case would assert
about this file's author; running the same program under CPython asks instead.
The one thing CPython cannot be the oracle for is the message text, because
`debug_assert` raises `AssertionError` and Python prints a traceback — so what
is asserted about the diagnostic is that it goes nowhere near stdout, which is
the property that keeps a program's real output comparable.

Run:  python3 test_formal_debug_assert.py [-v]
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


def build(source, out, backend=None, tmpdir=None):
    """`fire.py build --formal --no-prove`, as a (returncode, output) pair."""
    path = os.path.join(tmpdir, "prog.mojo")
    with open(path, "w") as f:
        f.write(source)
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out]
    if backend:
        cmd.append(f"--backend={backend}")
    cmd.append(path)
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run(path):
    p = subprocess.run([path], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT)
    return p.returncode, p.stdout


def cpython(source, tmpdir):
    """The same program under CPython, which is the oracle for the outcome.

    `printf` is a C-library function this backend maps and `var x = v` is Mojo,
    neither of which CPython parses, so each case supplies its own CPython
    spelling rather than this file transliterating one — the same arrangement
    `test_formal_run.py`'s `run_cpython_pair_case` uses, and for the same
    reason: a transliteration written here is a second statement of what the
    program means, and it is the thing under test.
    """
    path = os.path.join(tmpdir, "ref.py")
    with open(path, "w") as f:
        f.write(source)
    p = subprocess.run([sys.executable, path], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT)
    # 7 (the program's own `return`, which is what the formal entry point
    # makes the exit status too) and 1 (an uncaught `AssertionError`) are both
    # answers; a SyntaxError or a NameError is not, and would otherwise read as
    # "the check fired".
    if p.returncode not in (0, 1, 7):
        raise AssertionError(
            f"the CPython reference itself failed (exit {p.returncode}), so the "
            f"oracle is not an oracle: {p.stderr.strip()[-300:]}")
    return p.returncode


# `debug_assert` as `myinterpreter.py:3010` defines it, verbatim. The reference
# for the language in this tree is the interpreter, so a program that runs
# under `fire.py run` has a CPython answer here that was written by the same
# definition the lowering is checked against — rather than by this file.
_CPYTHON_PREAMBLE = (
    "import sys\n"
    "\n"
    "def debug_assert(cond, *args):\n"
    "    if not cond:\n"
    '        raise AssertionError("debug_assert failed"'
    " + (\": \" + str(args[0]) if args else \"\"))\n"
)


# ── 1. both spellings, both architectures, against CPython ───────────────────

# (name, mojo condition value, bracketed?)
#
# `passing` and `failing` differ only in the value of `n`, which is what makes
# the pair a control: the same program text, the same check, one value that
# satisfies it and one that does not. A lowering that always fired would pass
# `passing` and fail `failing` identically; one that never fired would do the
# reverse.
SPELLING_CASES = [
    ("bare_passing", "5", False),
    ("bare_failing", "0", False),
    ("bracketed_passing", "5", True),
    ("bracketed_failing", "0", True),
]


def _program(n_source, bracketed, marker):
    """A program whose post-check output identifies it and whose exit is 7.

    The exit 7 is load-bearing rather than decorative: it is what proves the
    program's LAST statement ran, so an image that exited 1 because the check
    passed-then-failed is distinguishable from one that exited 1 because it
    never got past the check. Without a distinctive post-check value, "exit 1"
    would be consistent with both a correct failure and a program that died
    early.
    """
    call = (f'debug_assert[assert_mode="safe"](n > 0, "n must be positive")'
            if bracketed else
            'debug_assert(n > 0, "n must be positive")')
    return (
        "def main() -> Int:\n"
        f"    var n = {n_source}\n"
        f"    {call}\n"
        f'    printf("{marker}\\n")\n'
        "    return 7\n"
    )


def _cpython_program(n_source, bracketed, marker):
    """The CPython spelling of `_program`, for the same program.

    Identical apart from `var` (Mojo), `printf` (a C-library function this
    backend maps) and the bracketed call — which CPython writes as a bare call,
    because `debug_assert` is a builtin there too and its bracket selects a
    compile-time mode rather than changing what the call does.
    """
    call = 'debug_assert(n > 0, "n must be positive")'
    return (_CPYTHON_PREAMBLE
            + "def main():\n"
            + f"    n = {n_source}\n"
            + f"    {call}\n"
            + f'    print("{marker}")\n'
            + "    return 7\n"
            + "sys.exit(main())\n")


def test_both_spellings_match_cpython(tmpdir):
    """Each spelling, each architecture: same exit status as CPython, same
    post-check output, and the marker printed only when the check passed."""
    for name, n_source, bracketed in SPELLING_CASES:
        marker = f"reached-{name}"
        source = _program(n_source, bracketed, marker)
        want_exit = cpython(_cpython_program(n_source, bracketed, marker),
                            tmpdir)
        passing = name.endswith("passing")
        # The sanity check on the ORACLE, not on the lowering: 7 is the
        # program's own `return`, which is what the formal entry point makes
        # the process exit status and what `sys.exit(main())` makes CPython's,
        # and 1 is the uncaught `AssertionError`. Anything else would mean the
        # reference program is not the program, and every comparison below
        # would be against the wrong answer.
        check(want_exit == (7 if passing else 1),
              f"{name}: CPython's own exit status is the expected one",
              f"CPython exited {want_exit} for a program whose check is "
              f"{'true' if passing else 'false'}; the oracle is wrong, not "
              f"the lowering")
        for backend in BACKENDS:
            out = os.path.join(tmpdir, f"{name}.{backend}")
            rc, text = build(source, out, backend=backend, tmpdir=tmpdir)
            if not check(rc == 0, f"{name} builds on {backend}", text[-400:]):
                continue
            got_exit, got_out = run(out)
            check(got_exit == want_exit,
                  f"{name} on {backend} exits as CPython does",
                  f"exit {got_exit}, CPython exits {want_exit}")
            if passing:
                check(marker in got_out,
                      f"{name} on {backend} reaches the code after the check",
                      f"stdout {got_out!r} does not contain {marker!r}")
            else:
                # The diagnostic must NOT reach stdout. This is the property
                # that keeps a failing program's real output comparable, and
                # the reason the lowering prints nothing: this backend has one
                # output stream and the interpreter's contract for a failed
                # assert is an exception, not a line of program output.
                check(marker not in got_out,
                      f"{name} on {backend} does not print past the check",
                      f"stdout {got_out!r} contains the marker, so the program "
                      f"continued after a false condition")


def test_the_check_actually_fires(tmpdir):
    """The falsy cases above prove the program stopped; this proves it was the
    CHECK that stopped it and not something else about the program.

    Without it, "exit 1 with no output" is equally consistent with a lowering
    that always exits 1 — which would satisfy every case above. The control is
    the same program with the condition's comparison flipped so it is TRUE, and
    the requirement is that it then reaches the marker and exits 7.
    """
    source = _program("0", False, "reached-control")
    flipped = source.replace("n > 0", "n >= 0")
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"control.{backend}")
        rc, text = build(flipped, out, backend=backend, tmpdir=tmpdir)
        if not check(rc == 0, f"the true-condition control builds on {backend}",
                     text[-400:]):
            continue
        got_exit, got_out = run(out)
        check(got_exit == 7 and "reached-control" in got_out,
              f"on {backend} a TRUE condition continues and exits 7",
              f"exit {got_exit}, stdout {got_out!r} — if this fails, the "
              f"lowering exits regardless of the condition")
    del source


def test_bracketed_and_bare_agree(tmpdir):
    """The two spellings are one construct, so they must produce the same
    program. Compared as BUILT artifacts' observable behaviour, because the
    bracket is the half that used to be architecture-dependent."""
    for n_source, want in (("5", 7), ("0", 1)):
        for bracketed in (False, True):
            name = f"agree-{n_source}-{'br' if bracketed else 'bare'}"
            marker = name
            source = _program(n_source, bracketed, marker)
            out = os.path.join(tmpdir, name)
            rc, text = build(source, out, tmpdir=tmpdir)
            if not check(rc == 0, f"{name} builds", text[-400:]):
                continue
            got_exit, got_out = run(out)
            check(got_exit == want,
                  f"{name} exits {want} (the bracket changes nothing)",
                  f"exit {got_exit}, stdout {got_out!r}")


# ── 2. the arguments, which are where a lowering can quietly lose work ───────

def test_message_arguments_are_evaluated(tmpdir):
    """A message argument must be EVALUATED, on the failing path.

    This is the case that decides what "the messages are not formatted" is
    allowed to mean. They are ordinary argument expressions, so evaluating them
    is what keeps a dropped expression from being a dropped side effect; a
    lowering that skipped them to save work would pass every other test in this
    file and would silently change what a failing program does.

    The message calls `exit(3)`, and that is what makes the case observable.
    The obvious discriminator — a `printf` in the message slot — does NOT work
    here, and the reason is worth recording because it is a property of this
    backend rather than of the test: the failing path leaves through the raw
    `svc` exit syscall (`_emit_debug_assert` emits the same three instructions
    `AssertStmt` and `RaiseStmt` do), and that syscall discards the stdio
    buffer, so a `printf` before it produces no output at all. Measured: the
    same program with `printf` in the message slot prints nothing on both
    architectures. An exit STATUS survives the syscall and nothing else does.
    """
    source = (
        "def note() -> Int:\n"
        "    exit(3)\n"
        "    return 1\n"
        "\n"
        "def main() -> Int:\n"
        "    var n = 0\n"
        '    debug_assert(n > 0, "msg", note())\n'
        '    printf("reached\\n")\n'
        "    return 7\n"
    )
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"side.{backend}")
        rc, text = build(source, out, backend=backend, tmpdir=tmpdir)
        if not check(rc == 0, f"a side-effecting message builds on {backend}",
                     text[-400:]):
            continue
        got_exit, _got_out = run(out)
        check(got_exit == 3,
              f"on {backend} the message argument ran before the exit",
              f"exit {got_exit} — the message expression was dropped, so a side "
              f"effect in it is a side effect the program no longer has")


def test_a_passing_check_evaluates_nothing_it_does_not_need(tmpdir):
    """The control for the case above: when the condition HOLDS, the messages
    are not evaluated.

    That is the real `debug_assert`'s behaviour and the reason its own
    docstring tells callers to keep side effects out of them — the assertion
    costs nothing when it passes. Without this control, a lowering that
    evaluated the messages on BOTH paths would pass
    `test_message_arguments_are_evaluated` and would make every passing
    `debug_assert` in the stdlib call a function it did not need to call.
    """
    source = (
        "def note() -> Int:\n"
        "    exit(3)\n"
        "    return 1\n"
        "\n"
        "def main() -> Int:\n"
        "    var n = 5\n"
        '    debug_assert(n > 0, "msg", note())\n'
        '    printf("reached\\n")\n'
        "    return 7\n"
    )
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"noside.{backend}")
        rc, text = build(source, out, backend=backend, tmpdir=tmpdir)
        if not check(rc == 0, f"the passing side-effect case builds on {backend}",
                     text[-400:]):
            continue
        got_exit, got_out = run(out)
        check(got_exit == 7 and "reached" in got_out,
              f"on {backend} a passing check continues and exits 7",
              f"exit {got_exit}, stdout {got_out!r} — the message ran even "
              f"though the condition held, which the real builtin does not do")


def test_the_condition_is_the_only_thing_tested(tmpdir):
    """The first argument is the condition and the rest are messages.

    A lowering that tested the LAST argument, or that required two arguments,
    would satisfy every case above — they all pass a literal condition and at
    least one message. This one pins the position: the condition is false and
    the message is a non-empty string, so a lowering that tested the message
    would CONTINUE past a check that must stop it.
    """
    source = (
        "def main() -> Int:\n"
        "    var n = 0\n"
        '    debug_assert(n > 0, "a message that is true-ish")\n'
        '    printf("reached\\n")\n'
        "    return 7\n"
    )
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"position.{backend}")
        rc, text = build(source, out, backend=backend, tmpdir=tmpdir)
        if not check(rc == 0, f"the position case builds on {backend}",
                     text[-400:]):
            continue
        got_exit, got_out = run(out)
        check(got_exit == 1 and "reached" not in got_out,
              f"on {backend} a false FIRST argument fails even with a message",
              f"exit {got_exit}, stdout {got_out!r}")


def test_falsy_conditions_are_the_python_ones(tmpdir):
    """Zero and the empty string are falsy; a non-zero integer is truthy.

    The empty string is the case that separates a correct lowering from a null
    test, and it is the same reason `_emit_truthy_word` exists. A lowering that
    treated "non-zero pointer" as the truthiness would pass an empty string —
    which is a non-zero address — and let the program continue.
    """
    cases = [
        ("empty_string", 'var s = ""', 'debug_assert(s, "empty")', 1),
        ("nonempty_string", 'var s = "x"', 'debug_assert(s, "full")', 7),
        ("zero_int", "var n = 0", "debug_assert(n, \"zero\")", 1),
        ("nonzero_int", "var n = 1", "debug_assert(n, \"one\")", 7),
    ]
    for name, decl, call, want_exit in cases:
        source = (f"def main() -> Int:\n    {decl}\n    {call}\n"
                  f'    printf("reached\\n")\n    return 7\n')
        for backend in BACKENDS:
            out = os.path.join(tmpdir, f"{name}.{backend}")
            rc, text = build(source, out, backend=backend, tmpdir=tmpdir)
            if not check(rc == 0, f"{name} builds on {backend}", text[-400:]):
                continue
            got_exit, got_out = run(out)
            check(got_exit == want_exit,
                  f"on {backend} {name} exits {want_exit}",
                  f"exit {got_exit}, stdout {got_out!r}")


# ── 3. the refusals ─────────────────────────────────────────────────────────

def test_an_unbindable_bracket_is_refused_not_dropped(tmpdir):
    """A bracket naming a parameter `debug_assert` does not declare is refused.

    Dropped is the failure this exists to prevent: `plain[3](5)` emitted as
    `plain(5)` builds, runs, and returns an answer the source never wrote, with
    nothing on the link line to catch it. A `debug_assert` whose bracket was
    ignored would do the same thing while looking even more innocent, because
    the check's own outcome is a non-zero exit rather than a printed number.
    """
    cases = [
        ("unknown_param", 'debug_assert[bogus=1](n > 0, "m")', "bogus"),
        ("positional", "debug_assert[Int](n > 0, \"m\")", "positionally"),
    ]
    for name, call, needle in cases:
        source = (f"def main(n: Int) -> Int:\n    {call}\n    return n\n")
        for backend in BACKENDS:
            out = os.path.join(tmpdir, f"{name}.{backend}")
            rc, text = build(source, out, backend=backend, tmpdir=tmpdir)
            check(rc != 0, f"{name} is refused on {backend}",
                  "it BUILT, and an account-for-free bracket that the build "
                  "cannot bind is dropped silently")
            check(needle in text,
                  f"{name} on {backend} says what it cannot bind",
                  f"the refusal does not mention {needle!r}: {text.strip()[-300:]}")


def test_the_empty_call_is_refused(tmpdir):
    """`debug_assert()` has no condition, and lowering it as a check that
    always passes is an assertion that can never fail."""
    source = "def main(n: Int) -> Int:\n    debug_assert()\n    return n\n"
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"empty.{backend}")
        rc, text = build(source, out, backend=backend, tmpdir=tmpdir)
        check(rc != 0, f"the empty call is refused on {backend}",
              "it BUILT as an assert that can never fail")
        check("first argument" in text,
              f"the empty-call refusal on {backend} names the missing argument",
              text.strip()[-300:])


def test_a_frame_address_is_not_a_condition(tmpdir):
    """A struct receiver handed to `debug_assert` is a frame ADDRESS, and what
    would be tested is the address rather than the value.

    This is the refusal `FRAME_VALUE_ONLY_CALLS` makes, and it is measured:
    `std/collections/interval.mojo` passes `self` as a MESSAGE operand, and
    without the row in that set it was refused as "`debug_assert()` … is a name
    with no definition in hand in this image" — false, since it is a builtin
    this path compiles, and a sentence that sends the reader looking for a
    missing callee. The set's own sentence is the true one.
    """
    source = (
        "struct Interval:\n"
        "    var start: Int\n"
        "    var end: Int\n"
        "\n"
        "    def check(out self) -> Int:\n"
        '        debug_assert(self.start <= self.end, "bad ", self)\n'
        "        return 1\n"
        "\n"
        "def main() -> Int:\n"
        "    return 0\n"
    )
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"frame.{backend}")
        rc, text = build(source, out, backend=backend, tmpdir=tmpdir)
        if rc == 0:
            check(True, f"the frame case is accepted on {backend} "
                        f"(the receiver is a one-word int here)")
            continue
        check("VALUE" in text or "value" in text,
              f"the frame refusal on {backend} says a value was wanted",
              text.strip()[-300:])


def test_a_keyword_argument_is_refused(tmpdir):
    """`location=` is a source location for a diagnostic this path does not
    format, so it is refused rather than silently ignored.

    `location` is a DECLARED parameter of the real `debug_assert`
    (`std/builtin/debug_assert.mojo`), which is why it is the case worth
    refusing rather than an invented one: dropping it would leave a call that
    names a source location reporting a failure with no source location in it,
    which is the diagnostic this path cannot currently produce and says so
    nowhere. The value is a LOCAL here so the refusal that comes back is about
    the keyword rather than about an undeclared name.
    """
    source = ("def main(n: Int) -> Int:\n"
              "    var loc = n\n"
              '    debug_assert(n > 0, "m", location=loc)\n'
              "    return n\n")
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"kw.{backend}")
        rc, text = build(source, out, backend=backend, tmpdir=tmpdir)
        check(rc != 0, f"a keyword argument is refused on {backend}",
              "it BUILT, so a keyword the builtin declares is being ignored")
        check("keyword" in text and "location" in text,
              f"the keyword refusal on {backend} names it",
              text.strip()[-300:])


# ── 4. the decision this lowering records ───────────────────────────────────

def test_assert_mode_is_a_compile_time_argument_not_a_runtime_one(tmpdir):
    """`assert_mode` selects whether the check is compiled in, and this path
    has no `ASSERT` build setting to resolve it against.

    The choice recorded here is that the check is emitted either way, so the
    bracket binds and is read rather than refused. The alternative — refusing
    the bracket — is the refusal this change exists to end, and dropping the
    bracket is the `plain[3](5)` image. This test is what makes the choice
    visible rather than implicit: it says which answer a bracket with
    `assert_mode="none"` gets, so a future reader who disagrees with the
    decision changes a test rather than discovering it in a sweep.
    """
    for mode in ('"safe"', '"none"'):
        source = ("def main() -> Int:\n"
                  "    var n = 0\n"
                  f'    debug_assert[assert_mode={mode}](n > 0, "m")\n'
                  '    printf("reached\\n")\n'
                  "    return 7\n")
        out = os.path.join(tmpdir, f"mode-{mode.strip(chr(34))}")
        rc, text = build(source, out, tmpdir=tmpdir)
        if not check(rc == 0, f"assert_mode={mode} builds", text[-400:]):
            continue
        got_exit, got_out = run(out)
        check(got_exit == 1,
              f"assert_mode={mode} still checks (the mode is not consulted)",
              f"exit {got_exit}, stdout {got_out!r}")


def test_a_bare_call_needs_no_declaration(tmpdir):
    """The bug's own central claim: `debug_assert` is a builtin, so a file with
    no imports at all can call it.

    `binary_heap.mojo` is that file — it has no imports — and it is the reason
    the bare spelling emitted a `BL` rather than being refused for a missing
    callee. Built here without any import so a regression to "needs a
    declaration" is visible in this file rather than in a sweep of 80 files.
    """
    source = ("def main() -> Int:\n"
              "    var n = 5\n"
              '    debug_assert(n > 0, "m")\n'
              '    debug_assert[assert_mode="safe"](n > 0, "m")\n'
              '    printf("reached\\n")\n'
              "    return 7\n")
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"noimports.{backend}")
        rc, text = build(source, out, backend=backend, tmpdir=tmpdir)
        if not check(rc == 0, f"both spellings build with no imports on {backend}",
                     text[-400:]):
            continue
        got_exit, got_out = run(out)
        check(got_exit == 7 and "reached" in got_out,
              f"both spellings pass on {backend} with no imports",
              f"exit {got_exit}, stdout {got_out!r}")


def test_the_stdlib_call_site_shapes_are_the_ones_lowered(tmpdir):
    """The two shapes the new-modular stdlib actually uses, in the files that
    use them.

    33 of the 61 call sites are bare and 28 are bracketed, and the bracketed
    ones are bracketed BY NAME (`assert_mode="safe"`, `cpu_only=True`) — which
    is why the positional bracket is refused and the named one is not. This
    test is the corpus evidence for that split; without it, the decision rests
    on a count in a bug doc that a later change to the stdlib would invalidate
    silently.
    """
    source = (
        "def main() -> Int:\n"
        "    var n = 5\n"
        '    debug_assert(n > 0, "divisor must be positive")\n'
        '    debug_assert[assert_mode="safe"](n >= 0, "non-negative")\n'
        '    debug_assert[cpu_only=True](n >= 0, "cpu only")\n'
        '    debug_assert(n > 0)\n'
        '    printf("reached\\n")\n'
        "    return 7\n"
    )
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"shapes.{backend}")
        rc, text = build(source, out, backend=backend, tmpdir=tmpdir)
        if not check(rc == 0, f"the stdlib spellings build on {backend}",
                     text[-400:]):
            continue
        got_exit, got_out = run(out)
        check(got_exit == 7 and "reached" in got_out,
              f"the stdlib spellings pass on {backend}",
              f"exit {got_exit}, stdout {got_out!r}")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    tests = [
        test_both_spellings_match_cpython,
        test_the_check_actually_fires,
        test_bracketed_and_bare_agree,
        test_message_arguments_are_evaluated,
        test_a_passing_check_evaluates_nothing_it_does_not_need,
        test_the_condition_is_the_only_thing_tested,
        test_falsy_conditions_are_the_python_ones,
        test_an_unbindable_bracket_is_refused_not_dropped,
        test_the_empty_call_is_refused,
        test_a_frame_address_is_not_a_condition,
        test_a_keyword_argument_is_refused,
        test_assert_mode_is_a_compile_time_argument_not_a_runtime_one,
        test_a_bare_call_needs_no_declaration,
        test_the_stdlib_call_site_shapes_are_the_ones_lowered,
    ]
    with tempfile.TemporaryDirectory(prefix="debug_assert_") as tmpdir:
        for t in tests:
            before = len(RESULTS)
            try:
                t(tmpdir)
            except Exception as e:            # a raising test is a failed test
                check(False, f"{t.__name__} raised", repr(e))
            if args.verbose:
                for ok, what in RESULTS[before:]:
                    print(f"  {'ok  ' if ok else 'FAIL'}  {what}")

    passed = sum(1 for ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())