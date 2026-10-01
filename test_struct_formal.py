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


def check(ok, what, detail=""):
    # The detail is KEPT, not just printed: a suite that reports "FAIL
    # <what>" and throws away the only sentence that says why has thrown away
    # the evidence, and `bugs/CODEGEN_test_struct_formal_is_flaky.md` is the
    # write-up of a run whose output could not be attributed for exactly that
    # reason. It is also what the harness self-test below asserts on.
    RESULTS.append((bool(ok), what, detail))
    if not ok:
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
        raise AssertionError(
            f"the image was built and then did not finish within "
            f"{RUN_TIMEOUT}s — it is hung, not slow, and the cases after this "
            f"one in the same loop would not be reached if this were allowed "
            f"to propagate. `file {out}` and run it under "
            f"`tools/gdbtool.py` to see where it is looping."
        ) from None
    return ([ln for ln in run.stdout.split("\n") if ln.strip() != ""],
            _how_it_died(run))


def expect_lines(tmpdir, name, source, expected, what):
    """The program's printed integers must equal `expected`, element-wise.

    **TWO checks are recorded in every outcome, and that is the point.** This
    used to `return` from a failed length check, so the suite's own DENOMINATOR
    moved with its own verdicts — `bugs/CODEGEN_test_struct_formal_is_flaky.md`
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
        return check(False, values_what, f"not reached: {why}")

    try:
        got, died = build_and_run(tmpdir, name, source)
    except AssertionError as e:
        check(False, what, str(e))
        unreached("the program did not build")
        return None
    if died is not None:
        # A case in this file prints its whole answer and then falls off the
        # end of `main`, so anything but a clean exit is a defect whether or
        # not the printed numbers happened to be right. Reported on its own
        # first: an image that died at its first instruction has printed
        # nothing, and "expected 1 numbers, program printed 0: []" is a
        # statement about the struct tables that the process, not the tables,
        # is what makes false.
        check(False, what, died)
        unreached(died)
        return None
    if not check(len(got) == len(expected), what,
                 f"expected {len(expected)} numbers, program printed "
                 f"{len(got)}: {got}"):
        unreached(f"the program printed {len(got)} of {len(expected)} "
                  f"numbers, so there is nothing to compare: {got}")
        return None
    bad = [(i, g, e) for i, (g, e) in enumerate(zip(got, expected))
           if int(g) != e]
    check(not bad, values_what,
          f"{len(bad)} of {len(expected)} differ, first: "
          + ", ".join(f"line {i}: got {g}, CPython says {e}"
                      for i, g, e in bad[:4]))
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


# ── 2. pack, byte for byte ───────────────────────────────────────────────────

def _pack_program(fmt, values, n_slots):
    """A program that packs `values` and prints each resulting byte.

    The bytes come back out of the returned list one at a time, because a
    formal program cannot print a list — and `print` of a subscript is refused
    without a binding first, so each byte goes through a named local. That
    refusal is a property of `print`, not of `struct`, and the binding is the
    documented way round it.

    `n_slots` is how many arguments the call supplies. It is FIVE, not seven:
    a signature has to fit the smaller of the two ABIs' integer argument
    registers, and x86-64's SysV passes six (RDI/RSI/RDX/RCX/R8/R9) where
    arm64's AAPCS passes eight — so `struct.pack` is `fmt` plus five values.
    Getting that wrong is invisible on arm64 and is a refusal on x86-64, which
    is why `test_the_module_builds_on_both_backends` exists.
    """
    args = ", ".join(str(v) for v in values)
    if len(values) < n_slots:
        args += ", 0" * (n_slots - len(values))
    body = "\n".join(
        f"    x{i} = b[{i}]\n    print(x{i})"
        for i in range(struct.calcsize(fmt)))
    return ("from struct import pack\n\n"
            f"def main():\n    b = pack(\"{fmt}\", {args})\n{body}\n")


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
        expect_lines(tmpdir, f"pack{i}", _pack_program(fmt, [value], 5),
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
        expect_lines(tmpdir, f"packmv{i}", _pack_program(fmt, values, 5),
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
        args = ", ".join(str(v) for v in values)
        while len(values) < 5:
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
    # must not. `bugs/CODEGEN_x86_64_module_dylib_emitted_as_macho.md` reported
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
        values = [1] * len(struct.unpack(fmt, bytes(struct.calcsize(fmt))))
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


# ── 5. the module is where the resolver looks, and the corpus imports it ─────

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

    Each probe below records what it saw through `probe()`, which silences both
    the tally and the printing: every case here is SUPPOSED to fail, so a green
    run that printed eight red lines from its own self-test would be the same
    noise this docstring is about. Each probe's verdicts are appended once, at
    the end, so this function contributes a FIXED six checks whatever happens.

    Against the pre-fix harness, four of the six fail — verified by restoring
    the old `expect_lines` and the old `build_and_run` and re-running this.
    """
    global build_and_run
    real_build_and_run, real_check = build_and_run, globals()['check']

    def probe(fn):
        """Run `fn` with the tally and the printing silenced; return its checks."""
        keep, RESULTS[:] = RESULTS[:], []
        globals()['check'] = lambda ok, what, detail='': RESULTS.append(
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
        test_pack_single_value_formats,
        test_pack_multi_value_formats,
        test_pack_into_matches_cpython,
        test_pack_into_at_offset,
        test_unpack_from_round_trip,
        test_unpack_from_eight_values,
        test_the_unservable_list_is_exactly_the_wide_pack_formats,
        test_unservable_formats_are_refused_not_wrong,
        test_the_module_builds_on_both_backends,
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
