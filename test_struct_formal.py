#!/usr/bin/env python3
"""test_struct_formal.py -- `formal/hostmods/struct.mojo` is byte-for-byte
CPython's `struct`.

The formal backends refused seven files in this repository because they
`import struct` and `struct` was in `formal/imports.py`'s HOST_MODELLED
("reachable in principle, not implemented"). The module implements it, and
this file is the evidence that the implementation is RIGHT rather than merely
present.

**Why byte-for-byte and not "it built".** A byte packer that is subtly wrong is
the worst thing in this tree to get wrong quietly: every caller here writes
Mach-O and ELF headers, so a wrong byte is a malformed binary that still links.
The oracle is CPython's own `struct` — this process's — so every case computes
the expected bytes with `struct.pack` and requires the formal-built program's
output to match them exactly.

**What is compared.** A formal program cannot print a list, so each case emits
one integer per assertion and this file compares them element-wise against the
CPython answer. The three axes that matter:

  * `calcsize` — every format string in the corpus, all thirteen.
  * `pack` — the bytes themselves, read back out of the returned list and
    reassembled, for every format `pack` can serve.
  * `pack_into` / `unpack_from` — the round trip through a CALLER-owned
    buffer, which is the form the corpus's patching call sites use and the
    only one whose lifetime is sound (a list built inside a function lives in
    that function's frame; see `struct.mojo`'s limit 4).

**What is deliberately not here.** `<IIQQQQQQ` and `<4sBBBBBBB5x` are two
corpus formats `pack` cannot serve — eight values do not fit the eight
argument registers once the format takes one. `struct.mojo` returns an empty
list for them rather than a wrong answer, and `test_unservable_formats_are_refused_not_wrong`
pins that it does so.

Run:  python3 test_struct_formal.py [-v]
"""
import argparse
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
# The module source, at the ONE place the formal resolver finds it. Derived
# from `formal/imports.py` rather than spelled out here, so a move of the
# search root cannot leave this file pointing at nothing.
sys.path.insert(0, HERE)
import formal.imports as _FI
HOSTMODS = _FI._HOSTMODS_ROOT
STRUCT_MODULE = os.path.join(HOSTMODS, "struct.mojo")
import fire_compiler as F
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60
#: Where a run that never finishes leaves the image, so that the one question
#: about it can be asked.  `build/` is git-ignored and is already where
#: `build/suite.log` goes, so this is the tree's own scratch area rather than a
#: new one — see `_preserve_a_hung_image`.
HANG_ARTIFACTS = os.path.join(HERE, "build", "hang-artifacts")

# Values chosen to exercise the parts that are easy to get wrong, not to be
# round numbers: every one has a non-zero byte in every position of its width,
# so a byte that is dropped, duplicated, or emitted at the wrong shift shows
# up as a difference rather than cancelling out in a sum.
V_I1 = 0xd65f03c0        # a real `ret` instruction, and the corpus's own
V_I2 = 0x11223344
V_I3 = 0xffffffff        # all bits set: catches a mask that is too narrow
V_Q1 = 0x1122334455667788
V_Q2 = 0x99aabbccddeeff00
V_Q3 = 0xffffffffffffffff
V_NEG = 0 - 5            # signed: the arithmetic-shift case

RESULTS = []

# "The values were not compared", distinct from `None` ("no differences") and
# from `[]`. `expect_lines` uses it so a wrong COUNT fails the values check
# rather than passing it on a comparison it never made.
_NOT_COMPARED = object()

def check(ok, what, detail="", tally=None, announce=True):
    """Record one verdict, and print it when it is a failure.

    The detail is KEPT in the record, not just printed: a suite that reports
    "FAIL <what>" and throws away the only sentence that says why has thrown
    away the evidence, and `“CODEGEN_test_struct_formal: the struct suite is FLAKY”` is the
    write-up of a run whose output could not be attributed for exactly that
    reason. It is also what the harness self-test below asserts on, so a record
    that dropped it would make that check pass for the wrong reason.

    `tally` redirects the record somewhere other than `RESULTS`, which is for a
    caller measuring THIS harness rather than `struct`: the probes in
    `test_the_check_count_is_fixed_whatever_the_verdicts` are supposed to fail,
    and a failure that reached the suite's own tally would make it red for a
    reason that has nothing to do with `struct`. It is the same code path
    either way, so what the probe measures is real. `announce=False` suppresses
    the FAIL line, which is the other half of that: a probe's expected failure
    printed among the suite's real ones is noise. Both halves of a probe's
    tuple are still there — a probe measuring the COUNT must not be measuring a
    different record shape than the suite's own.
    """
    (RESULTS if tally is None else tally).append((bool(ok), what, detail))
    if not ok and announce:
        print(f"FAIL  {what}" + (f": {detail}" if detail else ""), flush=True)
    return bool(ok)


def _how_it_died(run):
    """A description of a non-clean exit, or None when the image was fine.

    A program that builds, links, and then dies — SIGSEGV, SIGBUS, an illegal
    instruction, a `dyld` kill — has an EMPTY stdout, which is exactly what a
    program that legitimately printed nothing also has. Without this the one
    piece of evidence that distinguishes "crashed" from "answered wrongly" is
    discarded at the point where it still exists, and the reported failure
    points at the struct tables when the real answer is a dead process.

    `run.returncode` is negative when the child was killed by a signal, and
    that negative number is the ONLY record of which signal, so it is
    translated by name here rather than printed as `-11`.
    """
    if run.returncode == 0:
        return None
    if run.returncode < 0:
        try:
            signame = signal.Signals(-run.returncode).name
        except ValueError:
            signame = f"signal {-run.returncode}"
        how = f"the image was killed by {signame} (wait status {run.returncode})"
    else:
        how = f"the image exited {run.returncode}"
    err = (run.stderr or "").strip()
    return how + (f", stderr: {err[-300:]}" if err else ", with no stderr")


def _preserve_a_hung_image(name, out, path):
    """Copy the image and the source that produced it somewhere they survive.

    Returns the directory they are in, or None if they could not be copied.

    **Why this exists.**  The image used to live in a `TemporaryDirectory` and
    the timeout message named a path that no longer existed by the time anybody
    read the message, so the one question the timeout raises — "did this process
    never get scheduled, or is it spinning inside the image?" — could only be
    answered with the image in hand and the image was already gone.  The
    `SIGKILL` sibling of that report needs no image: `-9` cannot be sent by a
    process from inside, so it is a fact about the machine, and it is the
    reading that was already taken (`bugs/FORMAL_a_calcsize_image_hangs_once_in_
    several.md` §"Step 1").  **A hang is the one outcome where the harness holds
    no evidence at all beyond "it did not finish",** which is why it is this one
    that is preserved and why the copy is the whole of the fix.

    `build/hang-artifacts/` rather than a new directory: `build/` is already the
    tree's git-ignored scratch area (`build/suite.log`), so a directory beside
    it needs no ignore rule and is where a reader looks.  A copy failure is
    reported as None rather than raised, because losing a diagnostic must not
    turn a reported hang into an IOError.
    """
    dest = os.path.join(HANG_ARTIFACTS, name)
    try:
        os.makedirs(dest, exist_ok=True)
        for src in (out, path):
            if os.path.isfile(src):
                shutil.copy2(src, os.path.join(dest, os.path.basename(src)))
    except OSError:
        return None
    return dest if os.path.isfile(os.path.join(dest, os.path.basename(out))) \
        else None


def build_and_run(tmpdir, name, source):
    """Compile `source` through the formal arm64 backend and run it.

    Returns `(stdout_lines, how_it_died)`, or raises AssertionError with the
    build output — a build failure is a test failure here, never a skip:
    `struct.mojo` is in this repository and a program that imports it must
    build.

    The exit status is RETURNED rather than raised because one caller
    (`test_unservable_formats_are_refused_not_wrong`) requires a nonzero exit
    to be the passing outcome: reading `b[i]` for i past the end of an empty
    list is supposed to stop the program. Turning that into an exception would
    turn a correct observation into a failure.

    A run that never finishes is raised, and that is a separate decision from
    the exit status. `subprocess.TimeoutExpired` is an `OSError`, not an
    `AssertionError`, so it used to sail straight through `expect_lines`'s
    `except AssertionError` and out of the `for fmt in CORPUS_FORMATS` loop it
    was called from — abandoning every case after it. Measured: one run in two
    hit a 60 s timeout on `calcsize("<HHIQQQI")` and finished **122/127**
    instead of 148, because 21 checks were never reached and the report could
    not say so. A case that does not finish is a failed case, which is exactly
    what a build failure already was, and the fix is to make it one.

    **And the image is KEPT** (`_preserve_a_hung_image`), because the message
    names a path and a path that is gone by the time the message is read is not
    one.  The message states both branches the hang could be — starved, or
    spinning — because which one it is is a fact about the machine and about the
    image respectively, and only one of them is the image's fault.
    """
    path = os.path.join(tmpdir, f"{name}.py")
    with open(path, "w") as f:
        f.write(source)
    out = os.path.join(tmpdir, f"{name}.bin")
    result = subprocess.run(
        [sys.executable, FIRE, "build", "--formal", "--no-prove",
         "-o", out, path],
        capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
    if result.returncode != 0:
        raise AssertionError(
            f"build failed: {(result.stderr or result.stdout).strip()[-600:]}")
    try:
        run = subprocess.run([out], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        kept = _preserve_a_hung_image(name, out, path)
        where = (f"the image and its source are kept in {kept}: `file "
                 f"{os.path.join(kept, os.path.basename(out))}`, and "
                 f"`tools/gdbtool.py` on the live process answers in seconds "
                 f"whether it is looping" if kept else
                 f"the image COULD NOT be copied out of {tmpdir}, so it is "
                 f"gone and the only evidence is this message")
        raise AssertionError(
            f"the image was built and then did not finish within "
            f"{RUN_TIMEOUT}s — it is hung, not slow, and the cases after this "
            f"one in the same loop would not be reached if this were allowed "
            f"to propagate.  Two readings, and they are not the same fault: a "
            f"process that never got SCHEDULED is the machine (look at "
            f"`build/suite.log`'s measured peak and at how many jobs ran at "
            f"once), while a process SPINNING is the image — and {where}."
        ) from None
    return ([ln for ln in run.stdout.split("\n") if ln.strip() != ""],
            _how_it_died(run))


def expect_lines(tmpdir, name, source, expected, what, tally=None,
                announce=True):
    """The program's printed integers must equal `expected`, element-wise.

    **TWO checks are recorded in every outcome, and that is the point.** This
    used to `return` from a failed length check, so the suite's own DENOMINATOR
    moved with its own verdicts — `“CODEGEN_test_struct_formal: the struct suite is FLAKY”`
    recorded 144, 145, 147 and 148 checks on an unchanged tree, and read that
    as "some checks did not run", which is a claim about the tree and not about
    the tally. It is about the tally: a case that fails on length used to cost
    one check and a case that passed cost two, so the total was a function of
    the failures. A denominator that depends on the verdicts is not a
    denominator, and a suite whose total moves is a suite whose reader learns
    to re-run it — and a re-run that comes back green is not evidence.

    So the second check is always recorded, and when it cannot be evaluated it
    says so rather than being skipped. Each carries its own `what`, because
    "which of the two failed" is only answerable if they are distinguishable.
    """
    values_what = f"{what} [each printed value]"

    def unreached(why):
        return check(False, values_what, f"not reached: {why}",
                     tally=tally, announce=announce)

    try:
        got, died = build_and_run(tmpdir, name, source)
    except AssertionError as e:
        check(False, what, str(e), tally=tally, announce=announce)
        # "the program did not build" was the only wording here, and it is
        # false for the outcome `build_and_run` raises besides a build failure:
        # an image that never finishes BUILDS.  The second check says which, by
        # reading the first one's message, so a report cannot claim the compiler
        # refused a program the compiler built.
        why = str(e)
        unreached("the program did not build" if why.startswith("build failed")
                  else "the program did not finish (see the message above)")
        return None
    if died is not None:
        # A case in this file prints its whole answer and then falls off the
        # end of `main`, so anything but a clean exit is a defect whether or
        # not the printed numbers happened to be right. Reported on its own
        # first: an image that died at its first instruction has printed
        # nothing, and "expected 1 numbers, program printed 0: []" is a
        # statement about the struct tables that the process, not the tables,
        # is what makes false.
        check(False, what, died, tally=tally, announce=announce)
        unreached(died)
        return None
    if not check(len(got) == len(expected), what,
                 f"expected {len(expected)} numbers, program printed "
                 f"{len(got)}: {got}", tally=tally, announce=announce):
        unreached(f"the program printed {len(got)} of {len(expected)} "
                  f"numbers, so there is nothing to compare: {got}")
        return None
    bad = [(i, g, e) for i, (g, e) in enumerate(zip(got, expected))
           if int(g) != e]
    check(not bad, values_what,
          f"{len(bad)} of {len(expected)} differ, first: "
          + ", ".join(f"line {i}: got {g}, CPython says {e}"
                      for i, g, e in bad[:4]),
          tally=tally, announce=announce)
    return got


# ── 1. the corpus, DISCOVERED from the tree rather than listed ───────────────

def discover_corpus_formats():
    """Every format-shaped string literal in the files that import `struct`.

    Discovered, not listed, and that is the point. An earlier version of this
    file listed the thirteen formats the SWEEP reported — the seven files it
    blocks — and a byte-for-byte comparison against all thirteen passed while
    `formal/build.py` used two more (`<II`, `<8I`) that no list mentioned.
    `build.py` was not in the sweep's seven because it is not itself blocked on
    `import struct`; it is blocked on `json`, further down. A hand-kept list is
    a list of what somebody remembered, and this is the test that would have
    caught its own blind spot if it had been reading the tree.
    """
    import glob
    import re
    pat = re.compile(r'"(<[bBhHiIlLqQfdspcx?0-9]{1,14})"')
    out = set()
    for path in sorted(glob.glob(os.path.join(HERE, "formal", "*.py"))) + \
            [os.path.join(HERE, "test_x86_64_decode.py")]:
        with open(path) as f:
            text = f.read()
        if "import struct" not in text:
            continue
        for m in pat.finditer(text):
            fmt = m.group(1)
            try:
                struct.calcsize(fmt)
            except struct.error:
                continue          # not a format after all (e.g. "<8I" typo)
            out.add(fmt)
    return sorted(out)


CORPUS_FORMATS = discover_corpus_formats()


def test_the_corpus_was_discovered_and_is_not_empty(_tmpdir=None):
    """The discovery found something, and found more than the sweep's seven.

    A discovery that silently returned nothing would make every other test in
    this file vacuous — which is exactly how a test stops testing anything
    without going red. The floor is the seven formats the sweep's blocked files
    use; the ceiling is asserted by `test_every_corpus_format_is_implemented`
    below, which is the check that would fail if a format were missed.
    """
    check(len(CORPUS_FORMATS) >= 13,
          f"the corpus was walked and yielded {len(CORPUS_FORMATS)} formats, "
          f"expected at least 13: {CORPUS_FORMATS}")
    for f in ("<I", "<i", "<Q", "<q", "<QQ", "<II", "<8I"):
        check(f in CORPUS_FORMATS,
              f"{f} is one of the discovered corpus formats")


def test_every_corpus_format_is_implemented(tmpdir):
    """`calcsize` answers for every format the corpus uses — the gap check.

    The test that would have caught `<II` being missing: a format the table does
    not know returns 0, and 0 is a plausible-looking answer rather than an
    error, so a missing format is invisible unless something compares against
    CPython for every discovered format.
    """
    for fmt in CORPUS_FORMATS:
        src = (f'from struct import calcsize\n\ndef main():\n'
               f'    print(calcsize("{fmt}"))\n')
        expect_lines(tmpdir, f"corpus_{fmt.strip('<>')}", src,
                     [struct.calcsize(fmt)],
                     f'calcsize("{fmt}") == {struct.calcsize(fmt)} '
                     f'(every corpus format is implemented)')


def test_calcsize_each_format(tmpdir):
    """Each format's own size, not just the sum.

    A summed case cannot say WHICH format was wrong, and a dispatcher that
    produced the right total for the wrong reasons is exactly what passes one.
    """
    for fmt in CORPUS_FORMATS:
        src = (f'from struct import calcsize\n\ndef main():\n'
               f'    print(calcsize("{fmt}"))\n')
        expect_lines(tmpdir, f"calcsize_{fmt.strip('<>')}", src,
                     [struct.calcsize(fmt)],
                     f'calcsize("{fmt}") == {struct.calcsize(fmt)}')


# The whole GRAMMAR, walked rather than sampled, because `calcsize` used to be
# a table of the corpus's thirteen formats and every other format was 0.
#
# Generated, not listed, for the reason the corpus list is discovered rather
# than written: a hand-written list of formats is a list of the ones somebody
# thought of, and the question "is `calcsize` right" is about the grammar. The
# cross product is six byte orders (including ABSENT, which is `@` — CPython's
# `calcsize('l')` is 8 and `calcsize('<l')` is 4) times every code and several
# shapes, and a format CPython itself refuses is left out of the walk rather
# than compared against the module's status: `'<P'` raises `struct.error` in
# CPython and 0 here, and the two are different questions.
CALCSIZE_GRAMMAR = [
    order + item
    for order in ("", "<", ">", "=", "!", "@")
    for item in ("x", "c", "b", "B", "h", "H", "i", "I", "l", "L", "q", "Q",
                 "n", "N", "P", "s", "p", "?", "3x", "5s", "0s", "1p",
                 "2i3h", "12i", "i3i", "8I", "4q", "8s", "IIHH", "qq")
]

# Alignment is the one thing `@` does that `<` does not, so it gets its own
# rows rather than being left to the cross product to happen to produce.
CALCSIZE_ALIGNED = ["@xq", "@xi", "@xb", "@xh", "@hx", "@hxx", "@x", "@si",
                    "@i3l", "@7h", "@l", "@L", "@2n", "@ll", "@nP"]


def test_calcsize_the_whole_grammar(tmpdir):
    """Every code, every byte order, and `@`'s alignment, against CPython.

    ONE program for the whole walk, because a program per format is a build per
    format and this file's time is spent on builds: the suite's own note records
    a run losing 21 checks to a per-case 60 s timeout. The printed integers are
    compared element-wise by `expect_lines`, so a wrong answer names its index
    and the rest of the walk still runs.
    """
    wanted = [f for f in CALCSIZE_GRAMMAR + CALCSIZE_ALIGNED
              if _cpython_sizes(f)]
    lines = ["from struct import calcsize", "", "def main():"]
    for fmt in wanted:
        lines.append(f'    print(calcsize("{fmt}"))')
    src = "\n".join(lines) + "\n"
    expect_lines(tmpdir, "calcsize_grammar", src,
                 [struct.calcsize(f) for f in wanted],
                 f"calcsize over {len(wanted)} formats of the whole grammar")


def _cpython_sizes(fmt):
    """CPython's size for `fmt`, or None when CPython refuses the format.

    None rather than 0: this module's documented status for a format it will
    not answer is 0 (`formal/hostmods/struct.mojo`'s ERRORS section), and 0 is
    also CPython's answer for `''`, `'<'` and `'0s'`. Comparing the two would
    be a test that passes for the wrong reason.
    """
    try:
        struct.calcsize(fmt)
    except struct.error:
        return None
    return struct.calcsize(fmt)


def test_calcsize_absent_prefix_is_native_not_standard(tmpdir):
    """`calcsize('l')` is 8 and `calcsize('<l')` is 4, and both are asserted.

    Not a subsumption of the grammar walk: it is the single default in the
    parser that a reader is most likely to get wrong, because every format in
    this repository's own corpus carries an explicit `<`, so nothing else in
    the tree would notice the difference. CPython's `test_struct.py` does, at
    `calcsize('l')`, which is how this was found.
    """
    src = ('from struct import calcsize\n\ndef main():\n'
           '    print(calcsize("l"))\n'
           '    print(calcsize("<l"))\n'
           '    print(calcsize("si"))\n'
           '    print(calcsize("<si"))\n')
    expect_lines(tmpdir, "calcsize_native_default", src,
                 [struct.calcsize(f) for f in ("l", "<l", "si", "<si")],
                 "calcsize: an absent byte-order prefix is `@`")


# ── 2. pack, byte for byte ───────────────────────────────────────────────────

def _pack_program(fmt, values, n_slots=None):
    """A program that packs `values` and prints each resulting byte.

    The bytes come back out of the returned list one at a time, because a
    formal program cannot print a list — and `print` of a subscript is refused
    without a binding first, so each byte goes through a named local. That
    refusal is a property of `print`, not of `struct`, and the binding is the
    documented way round it.

    `n_slots`, when given, is how many arguments the call SUPPLIES, padding
    with zeros. It is None by default and used to be 5, because `pack`'s five
    value slots were REQUIRED: the call had to write all five or the arity
    check refused it at the CALL SITE, so every case here spelled
    `pack("<I", 7, 0, 0, 0, 0)` for a format that names one value. That is not
    a shape any caller writes — `formal/x86_64.py` has fifteen
    `struct.pack("<i", x)` sites — and the padding hid the gap rather than
    pinning it. The slots are DEFAULTED now (the same reason `pack_into`'s
    are), so the default here is the natural `pack("<I", 7)`.

    The signature is still six arguments WIDE, which is the part the width
    matters for: a module compiled for BOTH backends has to fit the smaller of
    their integer argument registers (x86-64's six, where arm64's AAPCS passes
    eight). Getting that wrong is invisible on arm64 and is a refusal on
    x86-64, which is why `test_the_module_builds_on_both_backends` exists.
    `n_slots` remains available so a case can still pin the padded spelling.
    """
    args = ", ".join(str(v) for v in values)
    if n_slots is not None and len(values) < n_slots:
        args += ", 0" * (n_slots - len(values))
    body = "\n".join(
        f"    x{i} = b[{i}]\n    print(x{i})"
        for i in range(struct.calcsize(fmt)))
    return ("from struct import pack\n\n"
            f"def main():\n    b = pack(\"{fmt}\", {args})\n{body}\n")


def test_pack_omitted_value_slots_are_filled(tmpdir):
    """A call that leaves value slots off is CPython's bytes, not a refusal.

    The one shape `struct.pack` is actually called with, and the one this
    module could not answer at all while the five slots were required: the
    arity check runs at the CALL SITE, so `pack("<I", 7)` was refused with
    "missing required argument 'v1'" before this body ever ran — and
    `formal/x86_64.py`, `formal/macho.py` and `formal/arm64.py` are written
    entirely in that shape, which is what put the whole of `formal/` behind a
    single declaration.

    Each case is one format and one value compared against CPython at the
    natural arity and at two wider ones, so "a default fills the slot" and "the
    value is not disturbed by the slots after it" are both assertions in the
    same run rather than one of them being assumed.
    """
    cases = [
        ("<I", [V_I1], 1),
        ("<I", [V_I1], 2),
        ("<I", [V_I1], 5),
        ("<HH", [0x1111, 0x2222], 2),
        ("<HH", [0x1111, 0x2222], 3),
        ("<HH", [0x1111, 0x2222], 5),
        ("<III", [V_I1, V_I2, V_I3], 3),
        ("<III", [V_I1, V_I2, V_I3], 5),
        ("<QQ", [V_Q1, V_Q2], 2),
        ("<QQ", [V_Q1, V_Q2], 5),
    ]
    for i, (fmt, values, n_slots) in enumerate(cases):
        expect_lines(tmpdir, f"packslots{i}",
                     _pack_program(fmt, values, n_slots),
                     list(struct.pack(fmt, *values)),
                     f'pack("{fmt}", {values}) with {n_slots} argument(s) is '
                     f"CPython's bytes")


def test_pack_single_value_formats(tmpdir):
    """`<I`, `<i`, `<Q`, `<q`: the 122 of 130 call sites that pack one value.

    Each byte is printed, so the comparison is against `struct.pack`'s exact
    output and not a summary of it. The all-ones and negative cases are the
    ones that catch a mask that is too narrow or a shift that is not
    arithmetic.

    CPython RANGE-CHECKS the signed codes (`struct.pack('<i', 0xd65f03c0)`
    raises), so a signed case only ever carries a value in range — the point
    of the check is that a negative value's bytes are two's complement, and an
    out-of-range one is an error CPython raises and this path has no way to.
    """
    cases = [
        ("<I", V_I1), ("<I", V_I2), ("<I", V_I3),
        ("<i", 0x7ffffff), ("<i", V_NEG),
        ("<Q", V_Q1), ("<Q", V_Q3),
        ("<q", V_Q1), ("<q", V_NEG),
    ]
    for i, (fmt, value) in enumerate(cases):
        expect_lines(tmpdir, f"pack{i}", _pack_program(fmt, [value]),
                     list(struct.pack(fmt, value)),
                     f'pack("{fmt}", {value}) is CPython\'s bytes')


def test_pack_multi_value_formats(tmpdir):
    """The multi-value formats `pack` can serve, each byte compared.

    `<QQ` and `<QQq` and `<III` and `<HH` and `<II` — every corpus format
    naming at most five values, which is what a signature can carry: `pack`
    is `fmt` plus five value slots because a module compiled for BOTH
    backends has to fit the smaller of their integer argument registers
    (x86-64's six). `unpack_from` is not limited this way — it reads its
    values out of the caller's buffer rather than receiving them, so `<8I`
    and the other wide formats are served there and tested by
    `test_unpack_from_eight_values`.
    """
    cases = [
        ("<QQ", [V_Q1, V_Q2]),
        ("<QQ", [V_Q3, 0]),
        ("<QQq", [V_Q1, V_Q2, V_NEG]),
        ("<III", [V_I1, V_I2, V_I3]),
        ("<II", [V_I1, V_I2]),
        ("<HH", [0x1111, 0x2222]),
    ]
    for i, (fmt, values) in enumerate(cases):
        expect_lines(tmpdir, f"packmv{i}", _pack_program(fmt, values),
                     list(struct.pack(fmt, *values)),
                     f'pack("{fmt}", {values}) is CPython\'s bytes')


# ── 3. pack_into / unpack_from: the round trip through a caller's buffer ────

def test_pack_into_matches_cpython(tmpdir):
    """`pack_into` writes CPython's bytes into the caller's buffer.

    This is the form the twelve `pack_into` call sites use, and the only one
    whose result is lifetime-sound: the buffer is the CALLER's list, so
    nothing built inside `struct.mojo` has to outlive the call.
    """
    cases = [
        ("<I", [V_I1]),
        ("<I", [V_I3]),
        ("<Q", [V_Q1]),
        ("<Q", [V_Q2]),
        ("<q", [V_NEG]),
        ("<III", [V_I1, V_I2, V_I3]),
        ("<QQ", [V_Q1, V_Q2]),
        ("<II", [V_I1, V_I2]),
    ]
    for i, (fmt, values) in enumerate(cases):
        size = struct.calcsize(fmt)
        expect_lines(tmpdir, f"packinto{i}", _pack_into_program(fmt, values,
                                                                size),
                     list(struct.pack(fmt, *values)),
                     f'pack_into("{fmt}", {values}) is CPython\'s bytes')


def _pack_into_program(fmt, values, size):
    args = ", ".join(str(v) for v in values)
    while len(values) < 3:
        args += ", 0"
        values = list(values) + [0]
    zeros = ", ".join(["0"] * size)
    body = "\n".join(f"    x{j} = buf[{j}]\n    print(x{j})"
                     for j in range(size))
    return ("from struct import pack_into\n\n"
            "def main():\n"
            f"    buf = [{zeros}]\n"
            f'    pack_into("{fmt}", buf, 0, {args})\n{body}\n')


def test_pack_into_at_offset(tmpdir):
    """A non-zero offset, which is what the patching call sites use.

    `formal/arm64.py` patches at `idx` and `idx + 4` into a section that is
    already built, so an implementation that only ever wrote at offset 0 would
    pass everything above and corrupt every Mach-O this compiler emits.
    """
    size = 12
    fmt = "<II"
    src = ("from struct import pack_into\n\n"
           "def main():\n"
           f"    buf = [{', '.join(['0'] * size)}]\n"
           f'    pack_into("{fmt}", buf, 4, {V_I1}, {V_I2})\n'
           + "\n".join(f"    x{j} = buf[{j}]\n    print(x{j})"
                       for j in range(size))
           + "\n")
    expected = [0] * 4 + list(struct.pack(fmt, V_I1, V_I2))
    expect_lines(tmpdir, "packinto_off", src, expected,
                 "pack_into at a non-zero offset writes CPython's bytes there")


def test_unpack_from_round_trip(tmpdir):
    """What `pack_into` wrote, `unpack_from` reads back as the same numbers.

    The round trip is the property the corpus actually depends on:
    `formal/arm64.py` packs an instruction, patches it in place, and later
    reads the same word back out to mask fields out of it.
    """
    cases = [
        ("<I", [V_I1]),
        ("<I", [V_I3]),
        ("<Q", [V_Q1]),
        ("<III", [V_I1, V_I2, V_I3]),
        ("<II", [V_I1, V_I2]),
    ]
    for i, (fmt, values) in enumerate(cases):
        size = struct.calcsize(fmt)
        # THREE value slots, because that is `pack_into`'s signature — padded
        # with 0s rather than left off, and never past the third. Padding to
        # five used to build here only because a call across a dylib boundary
        # silently DROPPED the arguments past the callee's arity; it is a
        # refusal now, which is the language's answer and the right one.
        values = list(values[:3])
        args = ", ".join(str(v) for v in values)
        while len(values) < 3:
            args += ", 0"
            values = list(values) + [0]
        zeros = ", ".join(["0"] * size)
        n = len(struct.unpack(fmt, bytes(size)))
        body = "\n".join(f"    y{j} = v[{j}]\n    print(y{j})"
                         for j in range(n))
        src = ("from struct import pack_into, unpack_from\n\n"
               "def main():\n"
               f"    buf = [{zeros}]\n"
               f'    pack_into("{fmt}", buf, 0, {args})\n'
               f'    v = unpack_from("{fmt}", buf, 0)\n{body}\n')
        expect_lines(tmpdir, f"roundtrip{i}", src,
                     list(struct.unpack(fmt,
                                        struct.pack(fmt, *values[:n]))),
                     f'pack_into/unpack_from round trip for "{fmt}"')


def test_unpack_from_eight_values(tmpdir):
    """`<8I`: eight values read out of one buffer, which `build.py` does.

    `formal/build.py` reads a dylib's 32-byte header with
    `struct.unpack_from("<8I", data, 0)` and a load command with
    `struct.unpack_from("<II", data, pos)`. Eight is the widest `unpack_from`
    has to serve and it is the one shape with no `pack` counterpart, so a
    buffer is filled directly and every one of the eight words is compared —
    the all-ones word is in the middle rather than first, so a reader that
    stopped early would be caught.
    """
    words = [0x01020304, 0x11223344, 0xffffffff, 0, 0, 0, 0, 0xdeadbeef]
    buf = []
    for w in words:
        b = struct.pack("<I", w)
        buf += list(b)
    literals = ", ".join(str(x) for x in buf)
    body = "\n".join(f"    y{j} = v[{j}]\n    print(y{j})"
                     for j in range(len(words)))
    src = ("from struct import unpack_from\n\n"
           "def main():\n"
           f"    buf = [{literals}]\n"
           '    v = unpack_from("<8I", buf, 0)\n' + body + "\n")
    expect_lines(tmpdir, "unpack8", src, words,
                 'unpack_from("<8I") reads all eight words CPython would')


# ── 4. the formats pack cannot serve, refused rather than wrong ──────────────

# Every corpus format naming MORE than five values. `pack` receives its
# values in argument registers and the format takes one of them, and the
# ceiling is the smaller of the two backends' — so these have nowhere to
# arrive on either.
#
# `<8I` is NOT here, and the distinction is the point: it names eight values
# but it is an UNPACK format (`formal/build.py` reads a dylib header with
# `struct.unpack_from("<8I", data, 0)`), and `unpack_from` reads its values
# out of the caller's buffer rather than receiving them, so no register limit
# applies to it. The list below is checked against the corpus by
# `test_the_unservable_list_is_exactly_the_wide_formats`, which filters on the
# formats `pack` is actually asked about.
UNSERVABLE = ["<HHHHHH", "<IBBHQQ", "<HHIQQQI", "<IIQQQQQQ",
              "<4sBBBBBBB5x"]

# The formats `struct.pack` is actually called with, as opposed to every
# format-shaped literal in a file that imports struct. A format that only
# `unpack_from` is used with is not a `pack` case, and conflating the two put
# `<8I` in a list it does not belong in.
PACK_FORMATS = ["<I", "<i", "<Q", "<q", "<QQ", "<QQq", "<III", "<II",
                "<IIQQQQQQ", "<HHHHHH", "<IBBHQQ", "<HHIQQQI",
                "<4sBBBBBBB5x"]


def test_the_unservable_list_is_exactly_the_wide_pack_formats(tmpdir):
    """The refusal list is derived from the corpus, not asserted about it.

    If a format later moved under the arity ceiling, or a new wide one
    appeared, this list would be stale and the test below would be testing a
    format that works — which is how a list of exceptions rots. Deriving it is
    cheap and makes the two impossible to disagree.

    Filtered to `PACK_FORMATS` because `unpack_from` is not register-limited
    (it reads the caller's buffer), so a wide UNPACK format is served and must
    not appear in a list of what `pack` cannot do.
    """
    wide = [f for f in PACK_FORMATS
            if len(struct.unpack(f, bytes(struct.calcsize(f)))) > 5]
    check(sorted(wide) == sorted(UNSERVABLE),
          f"the formats `pack` cannot serve are exactly the corpus PACK "
          f"formats naming more than five values: {sorted(wide)} vs the list "
          f"{sorted(UNSERVABLE)}")
    wide_all = [f for f in CORPUS_FORMATS
                if len(struct.unpack(f, bytes(struct.calcsize(f)))) > 5]
    check(set(wide_all) - set(wide) == {"<8I"},
          f"`<8I` is the only wide format that is unpack-only, and it is "
          f"served by unpack_from: {sorted(set(wide_all) - set(wide))}")


def test_the_module_builds_on_both_backends(_tmpdir=None):
    """`struct.mojo` compiles for arm64 AND x86-64.

    The test that would have caught the arity bug this module really had. Its
    signatures were first written to arm64's ceiling (eight integer argument
    registers, AAPCS X0-X7), every arm64 test passed, and the x86-64 build was
    refused outright:

        struct.mojo: pack_into: 8 parameters exceeds the 6 the formal x86-64
        ABI passes in registers

    x86-64's SysV passes integer arguments in six (RDI/RSI/RDX/RCX/R8/R9,
    `formal/x86_64.py`'s `ARG_REGS`), so a module both backends compile has to
    fit six — and that is not discoverable from either backend alone, which is
    why it is asserted here rather than discovered.

    **Both halves build now, on both architectures.** The arity half of the finding
    was settled first — the module's own functions compile for x86-64, which is
    what the 8-vs-6 refusal was about — and what held the x86-64 dylib back was
    a container defect, not a codegen gap: `build_macho_dylib` wrote its stubs
    with no `arch`, so the arm64 12-byte stub was `bytearray`-inserted into the
    x86-64 6-byte slots and left the image longer than `__LINKEDIT` declared,
    which `codesign` refuses outright. `struct.mojo` calls the C library, so it
    has stubs, so it was caught by that. Both are now fixed and the x86-64 half
    asserts the dylib is produced with the right container.
    """
    sys.path.insert(0, HERE)
    import tempfile as _tf
    try:
        import formal.build as B
        from formal.imports import build_module_dylib
    finally:
        sys.path.pop(0)
    src = STRUCT_MODULE

    # arm64: the whole module, as a dylib, which compiles every public
    # function rather than only the ones a program happens to call.
    with _tf.TemporaryDirectory() as d:
        try:
            out = build_module_dylib("struct", src, d, "arm64",
                                     project_root=src)
        except Exception as e:
            check(False, "struct.mojo compiles for arm64", str(e)[:300])
        else:
            check(bool(out) and os.path.isfile(out),
                  "struct.mojo produces a module dylib for arm64")

    # x86-64: the CODEGEN, which is what the arity question is about. Every
    # public function is compiled, in a function that links nothing.
    try:
        with open(src) as f:
            stmts = F.Parser(F.py_tokenize(f.read())).parse_module()
        B._formal_module_functions(src)          # parse + _prepare_functions
        check(True, "struct.mojo parses and its functions prepare on x86-64")
    except Exception as e:
        check(False, "struct.mojo's functions prepare for the x86-64 codegen",
              str(e)[:300])

# …and the dylib, which is now produced on both architectures. The
    # container is asserted against `default_format(arch)`, not hardcoded: on a
    # macOS host that is Mach-O for x86-64 too, because an x86-64 image that
    # runs here has to be one Rosetta 2 will load, and `fire.py`'s
    # `_formal_run_argv` is what runs them. Asserting ELF would be asserting
    # the wrong container for this host and would fail against a library that
    # is correct.
    #
    # This check used to require a Mach-O-to-ELF fix that could not have been
    # the right one: it failed on "the x86-64 module dylib is an ELF object"
    # while the x86-64 EXECUTABLE beside it was a Mach-O, so the dylib and the
    # thing linking it had to agree on the container and the test said they
    # must not. `“An x86-64 module dylib is a Mach-O, so no x86-64 program can import anything”` reported
    # the same wrong premise, and its real content — that `fmt` was accepted
    # and ignored, and that an x86-64 module dylib with an extern call could
    # not be signed — was two separate real defects, now fixed.
    with _tf.TemporaryDirectory() as d:
        try:
            out = build_module_dylib("struct", src, d, "x86_64",
                                     project_root=src)
            produced = bool(out) and os.path.isfile(out)
            if produced:
                with open(out, "rb") as f:
                    magic = f.read(4)
                want = (b"\xcf\xfa\xed\xfe" if B.default_format("x86_64")
                        == "macho" else b"\x7fELF")
                check(magic == want,
                      f"the x86-64 module dylib's container is {magic!r}, "
                      f"expected {want!r} — the format this host builds "
                      f"x86-64 in. A module library and the image linking it "
                      f"must agree on the container.")
            else:
                check(False, "struct.mojo produces a module dylib for x86_64")
        except Exception as e:
            check(False,
                  "struct.mojo produces a module dylib for x86-64; it was "
                  f"refused or mis-containered: {str(e)[:300]}")
def test_unservable_formats_are_refused_not_wrong(tmpdir):
    """A format needing more values than registers returns nothing.

    A wrong answer here would be the worst failure this module could have:
    these formats are ELF and Mach-O headers, so a caller would splice eight
    plausible bytes into a header and the image would be malformed rather than
    obviously broken. `struct.mojo` returns an empty list instead, and this
    pins that it does.
    """
    for fmt in UNSERVABLE:
        # `pack` has FIVE value slots, and this case supplies FIVE. That is the
        # in-band decline the module implements and it is a real behaviour, but
        # it is NOT the arity case: the eight-value call that reaches the
        # ceiling is a separate check, in
        # `test_the_eight_value_pack_is_refused_by_arity` below, because the
        # two fail in different places and only one of them is the compiler.
        # The module answers the format it is asked about from `_nvalues(fmt)`,
        # not from how many arguments arrived, so five supplied and more wanted
        # says exactly the intended thing.
        values = [1] * len(struct.unpack(fmt, bytes(struct.calcsize(fmt))))
        values = list(values[:5])
        args = ", ".join(str(v) for v in values)
        while len(values) < 5:
            args += ", 0"
            values = list(values) + [0]
        # A refused pack yields an empty list, and a list literal is the only
        # shape this path can print a length for — so the program counts the
        # bytes itself and prints the count. A WRONG answer would print the
        # format's real size and the check below would see it.
        size = struct.calcsize(fmt)
        src = ("from struct import pack\n\n"
               "def main():\n"
               f'    b = pack("{fmt}", {args})\n'
               "    n = 0\n"
               f"    i = 0\n    while i < {size}:\n"
               "        if b[i] == b[i]:\n"
               "            n = n + 1\n"
               "        i = i + 1\n"
               "    print(n)\n")
        try:
            got, died = build_and_run(tmpdir, f"refuse_{fmt.strip('<>')}", src)
        except AssertionError as e:
            check(False, f'pack("{fmt}") is refused, not wrong', str(e))
            continue
        # Reading b[i] for i in 0..size-1 of an EMPTY list exits(1) rather
        # than printing, so a refusal shows up as a nonzero exit; a wrong
        # answer would print `size`. Accept either "printed 0" or "the read
        # of the empty list stopped the program".
        #
        # The exit status comes from the run `build_and_run` already did. It
        # used to be a SECOND `subprocess.run` of the same image, which cost a
        # process spawn per format to learn something the first run had
        # already observed — and, on a machine where the image is
        # intermittently not runnable at all, gave the two runs a chance to
        # disagree with each other and report a refusal that was an artefact
        # of which of the two was unlucky.
        refused = (got == ["0"]) or (died is not None)
        check(refused,
              f'pack("{fmt}") must produce nothing (it needs 8 values and '
              f"only 8 argument registers exist, one of which is the format); "
              f"the program instead read {size - len(got)} of {size} bytes "
              f"and {died or 'exited 0 after printing them'}")


def test_the_eight_value_pack_is_refused_by_arity(tmpdir):
    """`pack` handed EIGHT values is refused AT THE CALL, by name.

    The case above supplies five, so the module's own in-band decline is what
    it sees. That was the whole of this suite's arity coverage until
    2026-10-02, and it is worth saying why that is a hole rather than a
    detail: a fixture that truncates its own arguments never builds the
    nine-argument call, so `pack`'s six-parameter signature — the ceiling the
    module's whole design rests on (see its docstring, point 2: six is the
    SMALLER of the two ABIs' integer argument registers, and a module sized to
    arm64's eight was refused on x86-64) — was enforced by nothing. If the
    signature check stopped firing, every one of these programs would still
    build and still print nothing, and the suite would be green.

    So the wide call is built here, with every value the format names, and the
    REFUSAL is the assertion — by name, and with the parameter list, because a
    refusal that named nothing could be satisfied by any refusal at all.

        build: call pack(): too many positional arguments (9 for 6
        parameter(s); the parameters are ['fmt', 'v0', 'v1', 'v2', 'v3', 'v4']

    Two facts are pinned by that one string and both are load-bearing. The
    `9 for 6` is the format plus eight values against five value slots, so the
    count is the CALL's and not a cap the module imposed on itself. And the
    parameter LIST is what says the ceiling is the signature rather than a
    number someone typed: widening `pack` to eight value slots would have to
    change that list, which is where a reader looks.

    This is a BUILD refusal, so `build_and_run` raises; catching the
    AssertionError is the passing outcome here, which is the mirror of the case
    above and is why the two are separate functions rather than one loop with a
    branch: the `except AssertionError` in the other one means a broken build,
    and folding them together would make that indistinguishable.

    Recorded here because it used to be in the fixture and was lost with it:
    a bug doc since deleted with the fix that closed it — which also recorded
    that the `expect=` marker this file's suite row had been carrying for these
    two checks was already gone by then, so only the coverage hole was left."""
    fmt = "<IIQQQQQQ"
    nvals = len(struct.unpack(fmt, bytes(struct.calcsize(fmt))))
    params = ["fmt"] + [f"v{i}" for i in range(5)]
    src = ("from struct import pack\n\n"
           "def main():\n"
           f'    b = pack("{fmt}", {", ".join(str(v + 1) for v in range(nvals))})\n'
           "    print(len(b))\n")
    try:
        got, died = build_and_run(tmpdir, f"arity_{fmt.strip('<>')}", src)
    except AssertionError as e:
        text = str(e)
        # The three parts, separately, so a reworded message that stopped
        # saying one of them is a FAIL rather than a pass with a new string.
        check("too many positional arguments" in text,
              f"pack(\"{fmt}\") with {nvals} values is refused as too many "
              f"arguments, and the refusal says so: {text[-300:]}")
        check(f"9 for {len(params)}" in text,
              f"the refusal counts 9 arguments against the callee's "
              f"{len(params)} parameters — the call's own arity, not a cap "
              f"the module imposed: {text[-300:]}")
        check(all(p in text for p in params),
              f"the refusal names the callee's parameters {params}, which is "
              f"what says the ceiling is the SIGNATURE: {text[-300:]}")
        return
    check(False,
          f"pack(\"{fmt}\") with all {nvals} values BUILT and ran "
          f"(stdout {got!r}, {died or 'exited 0'}) — the six-parameter "
          f"signature is no longer enforced, so the module's whole design "
          f"ceiling (its docstring, point 2) is unbacked and every five-value "
          f"case above is passing for the wrong reason")


# ── 5. the module is where the resolver looks, and the corpus imports it ─────

def test_the_check_count_is_fixed_whatever_the_verdicts(tmpdir):
    """A failing case records the SAME number of checks as a passing one.

    This suite's total used to be a function of how many cases failed —
    `expect_lines` returned early after the length mismatch, so a red run
    reported fewer checks than a green one (`144` / `145` / `147` / `148` on an
    unchanged tree). That is not cosmetic: a moving total means the denominator
    moves, so a reader cannot tell a check that was not reached from one that
    was reached and failed, and the total is useless as evidence.

    Both halves are measured here rather than asserted: a case whose program
    prints the right number of wrong values, and one whose program prints
    nothing at all. The second is the shape the real flake took.

    `tally=reached`, because two of the three probes are SUPPOSED to fail — a
    probe recorded in the suite's own tally would be indistinguishable from the
    bug it exists to detect. The count is read off a second tally the same
    `expect_lines` populates, so what is measured is the real code path.
    """
    cases = [
        # (name, source, expected, shape, checks reached, checks failed)
        # `want_failed` is 2 for the count mismatch because a program that
        # printed the wrong NUMBER of lines cannot have its values compared —
        # so the second check fails too, on the attribution rather than on a
        # comparison. That is the whole point of the shape: an early return
        # used to make it 1.
        ("checkcount_wrong_values",
         "from struct import calcsize\n\ndef main():\n    print(0)\n",
         [struct.calcsize("<I")], "values differ, count matches", 2, 1),
        ("checkcount_prints_nothing",
         "from struct import calcsize\n\ndef main():\n    pass\n",
         [struct.calcsize("<I")], "prints nothing", 2, 2),
        ("checkcount_correct",
         "from struct import calcsize\n\ndef main():\n"
         f'    print(calcsize("<I"))\n',
         [struct.calcsize("<I")], "everything agrees", 2, 0),
    ]
    for name, src, expected, shape, want_checks, want_failed in cases:
        reached = []
        expect_lines(tmpdir, name, src, expected, f"count probe: {shape}",
                     tally=reached, announce=False)
        check(len(reached) == want_checks,
              f"a `{shape}` case reaches exactly {want_checks} checks; got "
              f"{len(reached)}")
        check(sum(1 for ok, _w, _d in reached if not ok) == want_failed,
              f"a `{shape}` case fails {want_failed} of its {want_checks} "
              f"checks; got "
              f"{sum(1 for ok, _w, _d in reached if not ok)} failures")


def test_module_resolves_and_is_exported(tmpdir):
    """`struct` resolves to the module source and exports the four entry points.

    Without this the byte tests above would pass against a module the
    importer cannot reach, which is the shape of bug the HOST_MODELLED entry
    was: the file existed as far as `import struct` was concerned only if
    something answered it.

    The resolved PATH is compared to the file this suite reads, not to a
    basename: a `struct.mojo` that had drifted back to the repository root
    would still answer here — that is exactly what the module used to be — and
    `test_hostmods_are_invisible_to_every_other_resolver` in
    `test_formal_link_accounting.py` is what says why that is no longer
    allowed.
    """
    sys.path.insert(0, HERE)
    try:
        import formal.imports as I
    finally:
        sys.path.pop(0)
    path = I.resolve_module_path("struct", relative_to=os.path.join(
        HERE, "formal", "arm64.py"), project_root=os.path.join(
        HERE, "formal", "arm64.py"))
    check(path == STRUCT_MODULE,
          f"`import struct` resolves to {STRUCT_MODULE} for a "
          f"formal/arm64.py importer; got {path!r}")
    check("struct" not in I.HOST_MODELLED,
          "`struct` is no longer in HOST_MODELLED — the entry claimed the "
          "module was reachable but unimplemented, and it is implemented")
    if path and os.path.isfile(path):
        with open(path) as f:
            text = f.read()
        for fn in ("def pack(", "def pack_into(", "def unpack_from(",
                   "def calcsize("):
            check(fn in text, f"struct.mojo exports {fn[:-1]}()")


def test_struct_is_a_builtin_name_not_a_host_module(tmpdir):
    """The build refuses a file that imports an UNIMPLEMENTED host module.

    The negative control for the test above: if `struct` had merely been
    renamed rather than implemented, `import struct` would resolve to nothing
    and this is the message that would come back instead.
    """
    with tempfile.TemporaryDirectory() as d:
        prog = os.path.join(d, "p.py")
        with open(prog, "w") as f:
            f.write("import struct\n\ndef main():\n    return 0\n")
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove", prog],
            capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
        text = r.stderr + r.stdout
        check("host module" not in text,
              "`import struct` is no longer refused as a host module; got: "
              f"{text.strip()[-300:]}")


# ── 6. the seven files that import struct ───────────────────────────────────

IMPORTERS = ["formal/arm64.py", "formal/elf.py", "formal/macho.py",
             "formal/macho_linker.py", "formal/x86_64.py",
             "formal/x86_64_decode.py", "test_x86_64_decode.py"]


def test_the_seven_importers_no_longer_refuse_on_the_import(tmpdir):
    """None of the seven is refused for `struct` any more.

    The measurement this whole change exists for. Each file is BUILT, and the
    verdict checked is specifically that `struct` is no longer what stops it.
    Four of them still fail — on `typing`, `enum`, `dataclasses` and `sys`,
    which are OTHER unimplemented host modules and are other workers' claims —
    and a file that has moved from "blocked on struct" to "blocked on enum" is
    exactly the progress this is meant to make. What must NOT happen is the
    `struct` message coming back, which is why the check looks for the module
    NAME in the refusal rather than for success.
    """
    for rel in IMPORTERS:
        path = os.path.join(HERE, rel)
        if not os.path.isfile(path):
            check(False, f"{rel} exists")
            continue
        try:
            r = subprocess.run(
                [sys.executable, FIRE, "build", "--formal", "--no-prove",
                 "-o", os.path.join(tmpdir, os.path.basename(rel) + ".bin"),
                 path],
                capture_output=True, text=True, timeout=600, cwd=HERE)
        except subprocess.TimeoutExpired:
            check(False, f"{rel} builds (timed out at 600s)")
            continue
        text = r.stderr + r.stdout
        check("imports 'struct'" not in text,
              f"{rel} is no longer refused for importing `struct`",
              text.strip()[-300:])


# ── 7. the harness itself, which is what made the flake unattributable ──────

def test_the_harness_records_a_case_even_when_it_cannot_pass(tmpdir):
    """Every case costs the same number of checks, whatever happened to it.

    A suite whose TOTAL moves on an unchanged tree is a suite whose reader
    learns to re-run it, and a re-run that comes back green is not evidence.
    Three things moved this file's total, and each is a real defect rather
    than a reporting quirk:

      * `expect_lines` returned early from a failed length check, so a case
        that failed cost ONE check and a case that passed cost two;
      * a run that never finished raised `subprocess.TimeoutExpired`, which is
        an `OSError` and so sailed straight through `except AssertionError` and
        out of the `for fmt in CORPUS_FORMATS` loop — abandoning every case
        after it. Measured: 122/127 instead of 148, with nothing in the output
        saying that 21 checks had been skipped;
      * `build_and_run` returned only stdout and threw `run.returncode` away,
        so an image that built, linked, printed the right answer and then died
        was reported as a PASS. That is not a denominator problem, it is a
        correctness one, and no amount of counting finds it.

    A fourth is not about the TOTAL but about what a failure leaves behind: the
    timeout message named a path inside a `TemporaryDirectory`, so the image a
    hang needs in order to be diagnosable was deleted by the time the message
    was read (`_preserve_a_hung_image`).

    Each probe below records what it saw through `probe()`, which silences both
    the tally and the printing: every case here is SUPPOSED to fail, so a green
    run that printed eight red lines from its own self-test would be the same
    noise this docstring is about. Each probe's verdicts are appended once, at
    the end, so this function contributes a FIXED nine checks whatever happens.

    Against the pre-fix harness, four of the six that predate the hang case fail
    — verified by restoring the old `expect_lines` and the old `build_and_run`
    and re-running this — and the three that came with `_preserve_a_hung_image`
    are pinned by the same mechanism, against the function that preserves
    nothing.
    """
    global build_and_run
    real_build_and_run, real_check = build_and_run, globals()['check']

    def probe(fn):
        """Run `fn` with the tally and the printing silenced; return its checks."""
        keep, RESULTS[:] = RESULTS[:], []
        globals()['check'] = lambda ok, what, detail='', **_kw: RESULTS.append(
            (bool(ok), what, detail))
        try:
            fn()
            return RESULTS[:]
        finally:
            globals()['check'] = real_check
            RESULTS[:] = keep

    verdicts = []

    # (label, what build_and_run returns, the two verdicts the case must have).
    # Every one of the three is a FAILING case, which is the point: a
    # denominator has to be a function of the cases and not of their verdicts,
    # so the failing outcomes are the ones worth pinning.
    for label, canned, want in (
            ("the image exited nonzero after printing the right answer",
             (["36"], "the image exited 3, with no stderr"), (False, False)),
            ("the image printed the wrong NUMBER of answers",
             (["36", "37"], None), (False, False)),
            ("the image printed the right NUMBER and the wrong VALUE",
             (["35"], None), (True, False))):
        build_and_run = lambda *a, **k: canned
        added = probe(lambda: expect_lines(tmpdir, "stub", "stub source",
                                           [36], label))
        got = tuple(o for o, _w, _d in added)
        verdicts.append((
            got == want and len(added) == 2,
            f'harness: "{label}" is reported, and costs exactly two checks',
            f'{len(added)} check(s), verdicts {got}, wanted {want}: '
            f'{[w for _o, w, _d in added]}. One check means the case was '
            f'abandoned half way, which is what makes the total a function of '
            f'the verdicts.'))
        if canned[1] is not None:
            verdicts.append((
                bool(added) and added[0][2] == canned[1],
                f'harness: "{label}" says the image EXITED, not that it '
                f'answered wrongly',
                f'the recorded detail was '
                f'{added[0][2] if added else None!r}, and a program that '
                f'printed the right answer and then died has to say so'))
    build_and_run = real_build_and_run

    class _Ran:
        def __init__(self, rc, err=''):
            self.returncode, self.stderr = rc, err
    notes = {rc: (_how_it_died(_Ran(rc)) or '') for rc in (0, 3, -11, -9)}
    verdicts.append((
        'SIGSEGV' in notes[-11] and 'SIGKILL' in notes[-9]
        and notes[0] == '' and 'exited 3' in notes[3],
        'harness: a signal is reported BY NAME, not as a negative wait status',
        f'{notes}: a `-11` reaching a report names neither the signal nor the '
        f'process, and a clean exit must produce no note at all'))

    # ONE REAL BUILD, and it is the case no stub can reach. The three stubbed
    # outcomes above all go through a `build_and_run` this test supplies, so
    # they cannot see whether the REAL one reads `run.returncode` — and reading
    # it is the defect. This builds a three-line formal program that prints the
    # expected answer and then exits 3. Before the fix, `build_and_run`
    # returned only stdout, so this compared `['36']` against `['36']` and
    # reported a PASS for a process that had already failed; measured, not
    # argued, by re-running this probe against the old function.
    added = probe(lambda: expect_lines(
        tmpdir, "harness_dies_after_printing",
        'def main():\n    print("36")\n    return 3\n', [36],
        "a real image that exits 3 after printing 36"))
    verdicts.append((
        len(added) == 2 and not added[0][0] and 'exited 3' in added[0][2],
        'harness: a REAL image that exits nonzero after printing the right '
        'answer is reported as dead, not as correct',
        f'{len(added)} check(s): {added}. A pass here is the defect: stdout '
        f'matched and the process had already exited nonzero.'))

    # ONE REAL BUILD THAT DOES NOT FINISH, which is the fourth outcome no stub
    # above can reach, and the one whose evidence used to be thrown away: the
    # message named a path inside a `TemporaryDirectory`, so by the time anybody
    # read it the image was gone and the two readings it offers — starved by
    # the machine, or spinning inside the image — could not be told apart.  The
    # probe lowers `RUN_TIMEOUT` rather than waiting 60 s for the real one, and
    # then asks the two questions that matter: is the path in the message a
    # file that EXISTS, and does the preserved copy actually hold the image.
    real_timeout = RUN_TIMEOUT
    globals()['RUN_TIMEOUT'] = 3
    try:
        added = probe(lambda: expect_lines(
            tmpdir, "harness_hangs",
            'def main():\n    i = 0\n    while True:\n        i = i + 1\n'
            '    return 0\n', [0],
            "a real image that never finishes"))
    finally:
        globals()['RUN_TIMEOUT'] = real_timeout
    detail = added[0][2] if added else ''
    kept = None
    if HANG_ARTIFACTS in detail:
        # The message names the directory by absolute path, so the tail after
        # the prefix is appended to it: `os.path.join` would DISCARD the prefix
        # for an absolute tail, which is how the first version of this test
        # asked `os.path.isdir('/harness_hangs')` and reported a directory that
        # exists as one that does not.
        tail = re.split(r"[:`\s]", detail.split(HANG_ARTIFACTS, 1)[1],
                        maxsplit=1)[0].lstrip("/")
        if tail:
            kept = HANG_ARTIFACTS.rstrip("/") + "/" + tail
    verdicts.append((
        len(added) == 2 and not added[0][0] and 'did not finish' in detail
        and kept is not None and os.path.isdir(kept)
        and os.path.isfile(os.path.join(kept, "harness_hangs.bin")),
        'harness: an image that never finishes is KEPT, and the message names '
        'a path that exists',
        f'{len(added)} check(s): {added}. The message must name a directory '
        f'under {HANG_ARTIFACTS} holding the image; it named '
        f'{kept!r}, which '
        + ('exists' if kept and os.path.isdir(kept) else 'DOES NOT EXIST')
        + '. A message naming a path inside a TemporaryDirectory is the '
          'defect: the image is gone by the time it is read.'))
    verdicts.append((
        'SCHEDULED' in detail and 'SPINNING' in detail,
        'harness: a hang reports the two readings it has, because only one of '
        'them is the image fault',
        f'{detail!r}: a starved process and a spinning one are different '
        f'faults in different places, and a message that offers only one sends '
        f'the reader to the wrong one.'))

    for ok, what, detail in verdicts:
        RESULTS.append((ok, what, detail))
        if not ok:
            print(f"FAIL  {what}: {detail}", flush=True)


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    tests = [
        test_the_corpus_was_discovered_and_is_not_empty,
        test_the_harness_records_a_case_even_when_it_cannot_pass,
        test_every_corpus_format_is_implemented,
        test_calcsize_each_format,
        test_calcsize_the_whole_grammar,
        test_calcsize_absent_prefix_is_native_not_standard,
        test_pack_single_value_formats,
        test_pack_multi_value_formats,
        test_pack_omitted_value_slots_are_filled,
        test_pack_into_matches_cpython,
        test_pack_into_at_offset,
        test_unpack_from_round_trip,
        test_unpack_from_eight_values,
        test_the_unservable_list_is_exactly_the_wide_pack_formats,
        test_unservable_formats_are_refused_not_wrong,
        test_the_eight_value_pack_is_refused_by_arity,
        test_the_module_builds_on_both_backends,
        test_the_check_count_is_fixed_whatever_the_verdicts,
        test_module_resolves_and_is_exported,
        test_struct_is_a_builtin_name_not_a_host_module,
        test_the_seven_importers_no_longer_refuse_on_the_import,
    ]
    with tempfile.TemporaryDirectory(prefix="struct_formal_") as tmpdir:
        for t in tests:
            before = len(RESULTS)
            try:
                t(tmpdir)
            except Exception as e:            # a raising test is a failed test
                check(False, f"{t.__name__} raised", repr(e))
            if args.verbose:
                for ok, what, detail in RESULTS[before:]:
                    print(f"  {'ok  ' if ok else 'FAIL'}  {what}")
                    if not ok and detail:
                        print(f"          {detail}")

    passed = sum(1 for ok, _w, _d in RESULTS if ok)
    total = len(RESULTS)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
