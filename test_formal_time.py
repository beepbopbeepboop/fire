#!/usr/bin/env python3
"""Build `time` for the formal backend and RUN it, against CPython's own
clocks.

    python3 test_formal_time.py [-v] [group ...]

Why an oracle rather than a table of expected numbers. Every value this module
produces is a reading of a CLOCK, so a table would be a table of numbers that
were right when it was written: `time.time_ns()` is different on every run by
construction. So each case is asserted as a RELATION — the formal image's
`time_ns()` lies within a few milliseconds of this process's own
`time.time_ns()`, the monotonic clock does not go backwards, `sleep_ns` takes
at least the time it was asked for — and the only case with an exact expected
answer is the one thing about `time` that is not a clock reading: the
nanosecond-to-double conversion, which is pure arithmetic over a chosen input
and is checked against EXACT rational arithmetic rather than against
`ns / 1e9` in Python.

That last distinction is not pedantry and it is the reason this file's
conversion check is written the way it is. `ns / 1e9` in CPython converts `ns`
to a float FIRST and then divides, which for any `ns` above `2**53` discards
the low 11 bits before the division — a double rounding. The formal module
computes the correctly-rounded value of the exact rational `ns / 10**9`, and
the two disagree on roughly a quarter of realistic timestamps (measured:
129308 of 500000 random values in the range). Asserting against CPython's
`ns / 1e9` would therefore fail a CORRECT module and pass an incorrect one, so
the oracle here is `fractions.Fraction` with the IEEE-754 rounding rule
written out, and CPython's own `float()` is used only for the values small
enough that the two agree.

Building and RUNNING, not building. `test_formal.py` typechecks the generated
proof and never executes the image, and an entire class of Mach-O emission bug
can be green there; every case here exits with a status this file checks.

Groups: `clocks`, `sleep`, `convert`, `limits`, `structroute`. With no
argument, all of them. `limits` asserts the names this module does NOT answer,
and `structroute` measures WHICH HALF of the capability behind those refusals
exists, so the two cannot disagree about why they are absent.
"""
import argparse
import math
import os
import platform
import re
import struct
import subprocess
import sys
import tempfile
import time as hosttime
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 300
RUN_TIMEOUT = 60

# The record terminator. NOT a newline: `\n` inside a Mojo string literal is
# not unescaped on this path — a formal image prints the two characters `\` and
# `n` — so every program in this file emits its records back to back and this
# token is what separates them. Same convention, and the same reason, as
# `test_formal_os.py`.
REC = "@@"

# How far the formal image's wall clock may sit from this process's, and how
# far apart the two `time_ns()` readings inside ONE image may be. Both are
# generous on purpose: a tight bound would make this file a flaky test of the
# machine's load rather than a test of the module. Two seconds is far more than
# any build/run here takes between the two readings, and still five orders of
# magnitude tighter than "it is the right decade".
WALL_SKEW_NS = 2_000_000_000


class Failure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Failure(msg)


# ── the oracle for the conversion ───────────────────────────────────────────

def exact_double_bits(ns):
    """The IEEE-754 bits of the correctly-rounded double nearest `ns / 10**9`.

    Written out rather than taken from `float(ns / 1e9)` because that is the
    thing being tested. `Fraction` is exact, and the rounding rule below is
    IEEE-754 round-half-to-even, so this is the answer the module is supposed
    to be producing.
    """
    if ns <= 0:
        return 0
    v = Fraction(ns, 10**9)
    e = 0
    while Fraction(2) ** e > v:
        e -= 1
    while Fraction(2) ** (e + 1) <= v:
        e += 1
    scaled = v / (Fraction(2) ** (e - 52))
    m = scaled.numerator // scaled.denominator
    rem = scaled - m
    if rem > Fraction(1, 2) or (rem == Fraction(1, 2) and m % 2):
        m += 1
    if m >> 53:
        m >>= 1
        e += 1
    return ((e + 1023) << 52) | (m & ((1 << 52) - 1))


def build(src, name):
    tmp = os.path.join(TEMP, name + ".mojo")
    out = os.path.join(TEMP, name)
    with open(tmp, "w") as f:
        f.write(src)
    r = subprocess.run([sys.executable, FIRE, "build", "--formal", "--no-prove",
                        "-o", out, tmp],
                       capture_output=True, text=True, timeout=BUILD_TIMEOUT,
                       cwd=HERE)
    check(r.returncode == 0,
          f"build failed: {(r.stderr or r.stdout).strip()[-500:]}")
    check(os.path.isfile(out), f"no image at {out}")
    return out


def run(out):
    r = subprocess.run([out], capture_output=True, text=True,
                       timeout=RUN_TIMEOUT, cwd=HERE)
    check(r.returncode == 0, f"image exited {r.returncode}: "
                             f"{(r.stderr or r.stdout).strip()[-300:]}")
    got = {}
    for tag, val in re.findall(r"([A-Za-z0-9_]+)=([^@]*)" + REC, r.stdout):
        got[tag] = val
    return got


# ── group: the clocks ───────────────────────────────────────────────────────

CLOCKS_PROGRAM = """\
import time

def main() -> int:
  printf("wall_bits=%.6f@@", time.time_seconds_bits())
  printf("wall_ns=%lld@@", time.time_ns())
  printf("wall_sec=%lld@@", time.time_seconds())
  printf("mono_a=%lld@@", time.monotonic_ns())
  printf("mono_b=%lld@@", time.monotonic_ns())
  printf("perf_ns=%lld@@", time.perf_counter_ns())
  printf("proc_ns=%lld@@", time.process_time_ns())
  printf("thread_ns=%lld@@", time.thread_time_ns())
  printf("clk_rt=%lld@@", time.clock_gettime_ns(time.CLOCK_REALTIME()))
  printf("clk_mono=%lld@@", time.clock_gettime_ns(time.CLOCK_MONOTONIC()))
  printf("clk_raw=%lld@@", time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW()))
  printf("clk_proc=%lld@@", time.clock_gettime_ns(time.CLOCK_PROCESS_CPUTIME_ID()))
  printf("clk_thr=%lld@@", time.clock_gettime_ns(time.CLOCK_THREAD_CPUTIME_ID()))
  printf("const_rt=%d@@", time.CLOCK_REALTIME())
  printf("const_mono=%d@@", time.CLOCK_MONOTONIC())
  printf("const_raw=%d@@", time.CLOCK_MONOTONIC_RAW())
  printf("const_proc=%d@@", time.CLOCK_PROCESS_CPUTIME_ID())
  printf("const_thr=%d@@", time.CLOCK_THREAD_CPUTIME_ID())
  return 0
"""


def group_clocks(tmpdir, verbose):
    # The host's own reading, taken as close to the image's as this process
    # can manage, so the two are comparable to within the build/run latency.
    before = hosttime.time_ns()
    got = run(build(CLOCKS_PROGRAM, "clocks"))
    after = hosttime.time_ns()

    wall = int(got["wall_ns"])
    check(before - WALL_SKEW_NS <= wall <= after + WALL_SKEW_NS,
          f"wall clock outside the host's: image {wall}, host {before}..{after}")

    # `time.time()` rendered from the bit pattern must be the same reading as
    # `time_ns()`, to within the microseconds between the two calls. This is
    # the cross-check that matters most: it ties the two representations
    # together, so a `time_seconds_bits` wired to the wrong clock is caught
    # here. The conversion itself is checked exactly, with no clock involved,
    # in the `convert` group — this one is about which counter is read, and a
    # tolerance is the honest form of that question.
    #
    # `wall_bits` is printed BEFORE `wall_ns` in the program, so it is the
    # earlier reading and the assertion is directional.
    bits_ns = int(round(float(got["wall_bits"]) * 1e9))
    check(0 <= wall - bits_ns < 1_000_000,
          f"time_seconds_bits printed {got['wall_bits']!r} but the "
          f"time_ns() read after it says {wall} — {wall - bits_ns} ns apart")

    # And the truncated form must be that same value's whole seconds.
    check(int(got["wall_sec"]) == wall // 10**9,
          f"time_seconds() {got['wall_sec']} != time_ns()//1e9 {wall // 10**9}")

    # The monotonic clock must not go backwards between two readings inside
    # one image. This is the property that distinguishes it from the wall
    # clock, and it is the one assertion here that needs no host oracle at
    # all — a wall clock read twice would also be non-decreasing, but only
    # because the two reads are microseconds apart, whereas this one is a
    # claim about the counter itself.
    a, b = int(got["mono_a"]), int(got["mono_b"])
    check(b >= a, f"monotonic went backwards: {a} then {b}")

    # perf_counter is documented in the module as the same counter on this
    # target, so the two must be within a millisecond of each other.
    check(abs(int(got["perf_ns"]) - a) < 1_000_000,
          f"perf_counter_ns {got['perf_ns']} is not monotonic_ns {a}")

    # CPU clocks are a different counter from the monotonic one and must be
    # far smaller — a process that has existed for a second has used a small
    # fraction of a second of CPU.
    for tag in ("proc_ns", "thread_ns"):
        v = int(got[tag])
        check(0 <= v < 10 ** 12, f"{tag} = {v} is not a plausible CPU count")

    # `clock_gettime_ns` must agree with the dedicated function for the same
    # clock, to the microsecond — the two are the same hardware counter read
    # through two spellings, and a divergence would mean one of them is wired
    # to something else.
    check(abs(int(got["clk_rt"]) - wall) < 1_000_000,
          f"clock_gettime_ns(REALTIME) {got['clk_rt']} != time_ns() {wall}")
    check(abs(int(got["clk_mono"]) - a) < 1_000_000,
          f"clock_gettime_ns(MONOTONIC) {got['clk_mono']} != monotonic_ns {a}")

    # Darwin's clock ids, against the C library's own numbers. Not a table of
    # facts about time: a table of facts about the TARGET, which is what these
    # constants are, and which would silently stop being true if the module
    # ever passed a Linux id to a Darwin kernel.
    for tag, want in (("const_rt", 0), ("const_mono", 6), ("const_raw", 4),
                      ("const_proc", 12), ("const_thr", 16)):
        check(int(got[tag]) == want,
              f"{tag} = {got[tag]}, Darwin says {want}")

    if verbose:
        print(f"    image wall={wall} host {before}..{after} "
              f"mono={a} cpu={got['proc_ns']}")
    return True, f"wall {wall} (host {before}..{after})"


# ── group: sleep ────────────────────────────────────────────────────────────

SLEEP_PROGRAM = """\
import time

def main() -> int:
  var t0 = time.monotonic_ns()
  var r = time.sleep_ns(120000000)
  var t1 = time.monotonic_ns()
  printf("ret=%d@@", r)
  printf("asked_ns=120000000@@", 0)
  printf("slept_ns=%lld@@", t1 - t0)
  # A negative argument is CPython's ValueError. There is no exception on this
  # path, so it sleeps zero and returns 0; the test asserts THAT, which is the
  # documented behaviour rather than a crash.
  var t2 = time.monotonic_ns()
  printf("neg_ret=%d@@", time.sleep_ns(-5000000))
  printf("neg_elapsed=%lld@@", time.monotonic_ns() - t2)
  var t3 = time.monotonic_ns()
  printf("zero_ret=%d@@", time.sleep_ns(0))
  printf("zero_elapsed=%lld@@", time.monotonic_ns() - t3)
  var t4 = time.monotonic_ns()
  printf("sec_ret=%d@@", time.sleep_seconds(1))
  printf("sec_elapsed=%lld@@", time.monotonic_ns() - t4)
  return 0
"""


def group_sleep(tmpdir, verbose):
    got = run(build(SLEEP_PROGRAM, "sleep"))

    check(int(got["ret"]) == 0, f"sleep_ns returned {got['ret']}, CPython returns None")
    slept = int(got["slept_ns"])
    # usleep(2) is what this calls, and Darwin's usleep can return early by a
    # signal; the floor is what matters (it must not return before the time is
    # up) and the ceiling is generous (a loaded machine is allowed to be late).
    check(slept >= 120_000_000, f"sleep_ns(120ms) returned after {slept} ns")
    check(slept < 2_000_000_000, f"sleep_ns(120ms) took {slept} ns")

    check(int(got["neg_ret"]) == 0, "sleep_ns(-) did not return 0")
    check(int(got["neg_elapsed"]) < 50_000_000,
          f"sleep_ns(-) slept {got['neg_elapsed']} ns; it must not sleep at all")
    check(int(got["zero_ret"]) == 0, "sleep_ns(0) did not return 0")
    check(int(got["zero_elapsed"]) < 50_000_000,
          f"sleep_ns(0) slept {got['zero_elapsed']} ns")

    check(int(got["sec_ret"]) == 0, "sleep_seconds did not return 0")
    check(int(got["sec_elapsed"]) >= 1_000_000_000,
          f"sleep_seconds(1) returned after {got['sec_elapsed']} ns")

    if verbose:
        print(f"    slept {slept} ns for a 120 ms request")
    return True, f"120ms -> {slept}ns"


# ── group: the nanosecond-to-double conversion ──────────────────────────────

def conversion_cases():
    """The inputs `ns_to_double_bits` is checked on.

    Chosen for the SHAPES rather than the values, because the shapes are where
    this arithmetic goes wrong:

      * every count from 1 to 399, which covers the whole sub-second range
        (a negative exponent) and every rounding boundary in it;
      * `10**9` and `10**9 - 1`, the two sides of the integer-second split;
      * `2**30 * 10**9` and its neighbours, which is where `ns` first exceeds
        `2**53` — the boundary at which CPython's own `ns / 1e9` starts
        double-rounding, and where this function's chunked shift is most
        exercised;
      * `10**12`, `10**15`, `2**53`, `2**62` and the top of the range, for the
        same reason at four more magnitudes;
      * a deterministic spread of random values across the whole timestamp
        range, so the property is not only checked at boundaries.

    Seeded, so a failure is reproducible: `random.seed(17)` and the same 120
    values come out on every run and on every machine.
    """
    import random
    random.seed(17)
    vals = list(range(1, 400))
    vals += [10**9 - 1, 10**9, 10**9 + 1,
             2**30 * 10**9 - 1, 2**30 * 10**9, 2**30 * 10**9 + 1,
             2**31 * 10**9, 10**12, 10**15, 2**53, 2**53 + 1, 2**62,
             4_000_000_000 * 10**9 - 1, 12345, 999999999]
    vals += [random.randrange(1, 4_000_000_000 * 10**9) for _ in range(120)]
    return vals


def convert_program(vals):
    lines = ["import time", "", "def main() -> int:"]
    for i, v in enumerate(vals):
        lines.append(f'  printf("c{i}=%.9f@@", time.ns_to_double_bits({v}))')
    lines.append("  return 0")
    return "\n".join(lines) + "\n"


def group_convert(tmpdir, verbose):
    vals = conversion_cases()
    got = run(build(convert_program(vals), "convert"))
    check(len(got) == len(vals),
          f"got {len(got)} records for {len(vals)} cases")
    bad = []
    for i, v in enumerate(vals):
        want = struct.unpack("<d", struct.pack("<Q", exact_double_bits(v)))[0]
        have = float(got[f"c{i}"])
        if have != want:
            bad.append((v, have, want))
    check(not bad,
          f"{len(bad)}/{len(vals)} conversions differ from the exact rational"
          + (f"; first: ns={bad[0][0]} got {bad[0][1]!r} want {bad[0][2]!r}"
             if bad else ""))

    # And the same values against CPython's own `float(ns / 1e9)`, asserted
    # only where the two are the same question — `ns` below 2**53, where
    # CPython has not discarded any bits and is therefore not double-rounding.
    # This is the check that would fail if the module were right for the wrong
    # reason, and it is bounded precisely because above 2**53 CPython is
    # computing something else.
    agree = [v for v in vals if v < 2**53]
    mism = [v for v in agree
            if float(got[f"c{vals.index(v)}"]) != v / 1e9]
    check(not mism, f"{len(mism)} conversions below 2**53 differ from "
                    f"CPython's float(ns/1e9); first: ns={mism[0] if mism else ''}")

    # The double rounding is real and is why the oracle above is `Fraction`.
    # Asserted rather than assumed, so that a future reader who replaces the
    # exact oracle with CPython's finds out here instead of in a flaky test.
    above = [v for v in vals if v >= 2**53]
    if above:
        differ = sum(1 for v in above if v / 1e9 !=
                     struct.unpack("<d", struct.pack("<Q", exact_double_bits(v)))[0])
        check(differ > 0,
              "CPython's float(ns/1e9) agreed with the exact rational on every "
              "value above 2**53, so this file's justification for not using it "
              "as the oracle no longer holds")

    if verbose:
        print(f"    {len(vals)} conversions exact "
              f"({len(agree)} cross-checked against CPython directly)")
    return True, f"{len(vals)} conversions bit-exact"


# ── group: what this module cannot do ───────────────────────────────────────

def group_limits(tmpdir, verbose):
    """The absent names, asserted as refusals rather than left to discovery.

    Each of these is a CPython `time` name with no representation on this
    target, and the module docstring says which capability each one needs. A
    module that omits a name silently is indistinguishable from a module that
    has it, so each omission is pinned here as a build that fails with a
    message naming the missing thing.
    """
    absent = {
        "localtime": "struct tm",
        "gmtime": "struct tm",
        "mktime": "struct tm",
        "strftime": "struct tm",
        "get_clock_info": "namedtuple",
    }
    for name in absent:
        src = (f"import time\n\ndef main() -> int:\n"
               f"  time.{name}(0)\n  return 0\n")
        tmp = os.path.join(TEMP, f"absent_{name}.mojo")
        with open(tmp, "w") as f:
            f.write(src)
        r = subprocess.run(
            [sys.executable, FIRE, "build", "--formal", "--no-prove",
             "-o", os.path.join(TEMP, f"absent_{name}"), tmp],
            capture_output=True, text=True, timeout=BUILD_TIMEOUT, cwd=HERE)
        check(r.returncode != 0,
              f"time.{name}() built, but the module documents it as absent — "
              f"either the docstring is wrong or the module grew a name")
        msg = (r.stderr or r.stdout)
        check(name in msg,
              f"time.{name}() failed without naming itself: {msg.strip()[-300:]}")

    if verbose:
        print(f"    {len(absent)} absent names refused, each naming itself")
    return True, f"{len(absent)} absent names refused"


# ── group: the struct route, measured ───────────────────────────────────────

# The read happens INSIDE a module, which is where `localtime`'s would: a
# pointer that arrives as a callee ARGUMENT has no recorded pointee, so a
# program reading libc's bytes through another module's pointer is a different
# question with a different answer. `getenv` is the instrument because it hands
# back an address whose bytes the test chose, so a wrong width or a wrong offset
# shows up as a wrong number rather than a plausible one.
READ_MODULE = """\
def env_byte(name, k) -> int:
  var p: Pointer[UInt8] = external_call["getenv", Pointer[UInt8]](name)
  var q: Pointer[UInt8] = p + k
  return q.value()
"""

READ_PROGRAM = """\
import tmrow

def main() -> int:
  printf("b0=%d@@", tmrow.env_byte("MOJO_STRUCT_ROUTE", 0))
  printf("b1=%d@@", tmrow.env_byte("MOJO_STRUCT_ROUTE", 1))
  printf("b7=%d@@", tmrow.env_byte("MOJO_STRUCT_ROUTE", 7))
  return 0
"""

# The load-side refusal, in a module of its own because one refused function
# refuses its whole module — a module with both the read and the refusal in it
# would make the reading case fail for the refusal's reason. (There was a second
# refusal here, the store one, and it is gone: the store builds now, and the
# stores that must still be refused are `STORE_REFUSALS` below.)
WIDE_MODULE = """\
def env_byte_wide(name) -> int:
  var p: Pointer[Int32] = external_call["getenv", Pointer[Int32]](name)
  return p.value()
"""

# The store half, in a module of its own for the same reason the read is: a
# module is where `localtime`'s store would be, and a pointer that arrives as a
# callee ARGUMENT has no recorded pointee while one this module allocates has
# one — so which of the two a case uses is part of what it measures.
#
# One function per pointee width, because the four widths are four INSTRUCTIONS
# (`strb`/`strh`/`str w`/`str x`, and `movb`/`mov w16`/`mov w32`/`mov qword`)
# and a store at the wrong one is invisible to every other assertion available
# here: it writes the right ANSWER and corrupts the bytes AFTER the pointee,
# which nothing reads unless something reads them.  So each case reads them —
# the bytes at and after the pointee, immediately after its own store and before
# the next one, which is the only ordering in which "the store wrote 4 bytes"
# and "the store wrote 8 bytes" are different observations.
STORE_MODULE = """\
def poke8(p: Pointer[UInt8], v) -> int:
  p.value() = v
  return p.value()

def poke16(p: Pointer[UInt16], v) -> int:
  p.value() = v
  return p.value()

def poke32(p: Pointer[Int32], v) -> int:
  p.value() = v
  return p.value()

def poke64(p: Pointer[Int64], v) -> int:
  p.value() = v
  return p.value()

def clear(p: Pointer[UInt8], k) -> int:
  p[k] = 0
  return 0

def byteat(p: Pointer[UInt8], k) -> int:
  return p[k]
"""

# `(label, width in bytes, value)`.  The label is both the record's key and the
# name of the case, and every width appears TWICE:
#
#   * the `a` value fits in 32 bits, so its round trip through `p.value()` can be
#     PRINTED. `printf("%d")` reads 32 bits of the vararg — which is C's own
#     rule and not a defect of this path, measured: an image printing
#     `1234605616436508552` prints `1432778632`, the low half, on both
#     architectures — so a value that does not fit cannot be compared as a
#     number here.
#   * the `b` value does NOT fit, and every one of its bytes is distinct and
#     non-zero, so the records that read the bytes at and after the pointee are
#     the only way to see whether the store wrote 1, 2, 4 or 8 bytes. A store
#     one width too wide writes the value's higher bytes into a buffer that was
#     cleared, and the `b` value is chosen so those bytes are not zero.
#
# Both are needed and neither subsumes the other: the `a` value proves the load
# and the store AGREE at that width (the round trip closes), and the `b` value
# proves the store's FOOTPRINT is that width (the byte after the pointee is
# still 0). A store at 8 bytes passes every `a` case for widths 1, 2 and 4 when
# the value happens to fit, and fails the matching `b` case.
STORE_CASES = (
    ("w1a", 1, 0x56),
    ("w1b", 1, 0x1234ABCD56),
    ("w2a", 2, 0x3344),
    ("w2b", 2, 0x11223344),
    ("w4a", 4, 0x55667788),
    ("w4b", 4, 0x1122334455),
    ("w8a", 8, 0x55667788),
    ("w8b", 8, 0x1122334455667788),
)
STORE_BYTES = 16


def _store_program():
    body = ["import tmstore", "",
            "def main() -> int:",
            "  var b: Pointer[UInt8] = external_call[\"malloc\", "
            "Pointer[UInt8]](%d)" % STORE_BYTES,
            "  var i = 0",
            "  while i < %d:" % STORE_BYTES,
            "    tmstore.clear(b, i)",
            "    i = i + 1"]
    for label, width, value in STORE_CASES:
        # The store is ALWAYS emitted; only the round-trip READ of it is
        # conditional, and dropping the store along with the print is how this
        # program once measured nothing at all for the `b` cases — every byte
        # read then showed the PREVIOUS case's value and the assertion still
        # had something to say.
        call = f"tmstore.poke{width * 8}(b, {value})"
        if value < 2 ** 32:
            body.append(f'  printf("{label}=%d@@", {call})')
        else:
            body.append(f"  {call}")
        # The pointee's own bytes, then one byte PAST it.  The last case is
        # 8 bytes wide and the buffer is 16, so it still has a byte past it.
        for k in range(width + 1):
            body.append(f'  printf("{label}b{k}=%d@@", tmstore.byteat(b, {k}))')
    body.append("  return 0")
    return "\n".join(body) + "\n"


def _store_want():
    """What each record must read, computed from `STORE_CASES` by CPython.

    The store truncates to the pointee's width and the bytes are little-endian
    on both architectures (`str`/`mov` are little-endian by definition and the
    image is a Mach-O), so `int.to_bytes(width, "little")` is the answer for the
    footprint, and re-reading those bytes as one word is the answer for the round
    trip — which is why it is `int.from_bytes(packed)` and not `value`: storing
    0x11223344 through a `UInt16` is 0x3344, and a round trip that returned
    anything else would mean the store had not truncated.
    """
    want = {}
    for label, width, value in STORE_CASES:
        packed = value.to_bytes(8, "little")[:width]
        if value < 2 ** 32:
            want[label] = str(int.from_bytes(packed, "little"))
        for k in range(width + 1):
            want[f"{label}b{k}"] = str(packed[k] if k < width else 0)
    return want

# The stores this path must still REFUSE, and the needle each one's message has
# to contain.  Every one of these is a case where the store's WIDTH would be a
# choice rather than a fact, so they are the standing statement that the
# capability did not become a way to emit a store at any width: no pointee at
# all, a pointee whose width this model does not establish (a float, a blob), a
# struct (there is nothing at the address to store into), an unscaled offset on
# a wider-than-one-byte pointee (the address and the store would disagree about
# the element size), and a receiver whose bytes are the image's read-only text.
#
# The needles are the model's own sentences, so a needle that stops matching is
# a message that moved — and both backends are asked for the same one, which is
# the property that keeps a `strb` and a `movq` from becoming two answers.
STORE_REFUSALS = (
    ("nopointee", """\
def f(p) -> int:
  p.value() = 1
  return 0
""", "its pointee is not recorded here"),
    ("float", """\
def f(p: Pointer[Float64]) -> int:
  p.value() = 1
  return 0
""", "the pointee is Float64"),
    ("blob", """\
def f(p: Pointer[List[Int]]) -> int:
  p.value() = 1
  return 0
""", "the pointee is List"),
    ("struct", """\
struct P3:
  var a: Int64
  var b: Int64

def f(p: Pointer[P3]) -> int:
  p.value() = 1
  return 0
""", "a STRUCT"),
    ("unscaled", """\
def f(p: Pointer[Int64], k) -> int:
  var q: Pointer[Int64] = p + k
  q.value() = 1
  return 0
""", "WITHOUT scaling it by the pointee's"),
    ("readonly", """\
def f() -> int:
  var p: Pointer[UInt8] = "hello"
  p.value() = 72
  return 0
""", "READ-ONLY page"),
)


# ── the `struct tm` route, end to end ───────────────────────────────────────
#
# The capability's reason for existing, in the shape the five absent `time`
# names will use it: a MODULE writes the eight bytes of a `time_t` through a
# `Pointer[UInt8]`, hands the address to libc's `localtime`, and reads the
# `struct tm` it fills in field-wise. Nothing here is special-cased for `time` —
# it is `malloc`, `p.value() = v` and `p[k]` — and that is the assertion: the
# bytes libc READS are the bytes the module WROTE, which is the one thing a
# build-only test of a store cannot show.
#
# A function rather than a literal so the oracle is CPython's own `time`, not a
# constant written here beside the program that computes it.
TM_EPOCH = 1700000000


def _tm_route_program():
    # An f-string and NOT `%`-formatting: the program's own text is full of `%`
    # (the `v % 256` decomposition and the `printf("...%d@@")` records), and a
    # `%`-formatted program raises `unsupported format character` on its own
    # source. Only the epoch is interpolated.
    return f"""\
def put64(p: Pointer[UInt8], v) -> int:
  p[0] = v % 256
  p[1] = (v / 256) % 256
  p[2] = (v / 65536) % 256
  p[3] = (v / 16777216) % 256
  p[4] = (v / 4294967296) % 256
  p[5] = (v / 1099511627776) % 256
  p[6] = (v / 281474976710656) % 256
  p[7] = (v / 72057594037927936) % 256
  return 0

def le32(p: Pointer[UInt8], k) -> int:
  return p[k] + p[k + 1] * 256 + p[k + 2] * 65536 + p[k + 3] * 16777216

def local_fields(t) -> int:
  var buf: Pointer[UInt8] = external_call["malloc", Pointer[UInt8]](8)
  put64(buf, t)
  var tm: Pointer[UInt8] = external_call["localtime", Pointer[UInt8]](buf)
  printf("year=%d@@", le32(tm, 20) + 1900)
  printf("mon=%d@@", le32(tm, 16) + 1)
  printf("mday=%d@@", le32(tm, 12))
  return 0

def main() -> int:
  return local_fields({TM_EPOCH})
"""


def _tm_route_want():
    t = hosttime.localtime(TM_EPOCH)
    return {"year": str(t.tm_year), "mon": str(t.tm_mon),
            "mday": str(t.tm_mday)}


def _build(tmpdir, mod_name, src, tag, program=None, arch=None):
    """Write one module and a program that calls into it; build and return.

    `program` is the whole program when the caller has one (the reading and
    storing cases, which print records); otherwise a program that CALLS the
    module's one function and returns its value, which is enough to make a
    refusal the build reports. `arch` adds the backend flag, so a case can also
    assert that the measurement is the same one on both architectures.

    The generated program is `import <mod>\n\ndef main() -> int: return <mod>.<f>()`
    with NO arguments, and that is the whole of the generated form: a
    `p.value() = 1` store now BUILDS, so there is no call whose arguments a
    generated program would have to invent any more.
    """
    with open(os.path.join(TEMP, mod_name + ".mojo"), "w") as f:
        f.write(src)
    prog = os.path.join(TEMP, tag + ".mojo")
    if program is None:
        fn = re.search(r"def (\w+)\(", src).group(1)
        program = (f"import {mod_name}\n\ndef main() -> int:\n"
                   f"  return {mod_name}.{fn}()\n")
    with open(prog, "w") as f:
        f.write(program)
    out = os.path.join(TEMP, tag + (f".{arch}" if arch else ""))
    argv = [sys.executable, FIRE, "build", "--formal", "--no-prove"]
    if arch:
        argv.append(f"--backend={arch}")
    return prog, subprocess.run(argv + ["-o", out, prog], capture_output=True,
                                text=True, timeout=BUILD_TIMEOUT, cwd=HERE)


def _run(out, arch):
    """`(rc, stdout, stderr)` for one image, with the x86-64 one under Rosetta.

    `test_formal_os_backing.py`'s runner, copied rather than imported because
    these two files have no shared test module and a shared one would be a
    second thing to keep in step. The reason it is here and not a BUILD is the
    whole point of this group: an x86-64 image that stores eight bytes where the
    pointee is one is a program that BUILDS, and a build-only assertion could
    not tell it from a correct one. Measured on this backend: an `os`-importing
    formal image builds AND runs under `arch -x86_64`.
    """
    argv = [out]
    if arch == "x86_64" and sys.platform == "darwin":
        argv = ["arch", "-x86_64", out]
    try:
        p = subprocess.run(argv, capture_output=True, text=True,
                           timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired:
        return 124, "", f"the image did not finish within {RUN_TIMEOUT}s"
    return p.returncode, p.stdout, p.stderr


def _build_program(tmpdir, tag, src, arch):
    """Build ONE self-contained file, for a case that is not module + program.

    The `struct tm` route is one file: it declares the functions it calls and
    calls them from `main`, because the thing being measured is a single image
    that writes eight bytes and hands them to libc. `_build` writes a module and
    a program that imports it, which is the right shape for the read and store
    halves (a pointer that arrives as a callee argument is a different question)
    and the wrong one here.
    """
    prog = os.path.join(TEMP, tag + ".mojo")
    with open(prog, "w") as f:
        f.write(src)
    out = os.path.join(TEMP, f"{tag}.{arch}")
    argv = [sys.executable, FIRE, "build", "--formal", "--no-prove",
            f"--backend={arch}", "-o", out, prog]
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=BUILD_TIMEOUT, cwd=HERE)


def group_structroute(tmpdir, verbose):
    """The `struct tm` route, both halves of it, measured on both backends.

    `bugs/FORMAL_time_struct_shaped_answers.md` says the five absent names are
    absent because "a `struct tm` cannot cross a module boundary, and cannot be
    constructed by one". That is true and it is NOT the whole reason, and the
    difference decides what a fix looks like. This group is the measurement, and
    both halves of it now exist:

      * **reading** a C library's struct through a `Pointer[UInt8]` pointee WORKS
        — byte loads at `p + k`, which is what every field of a `struct tm` is
        made of (nine `int`s, read as four little-endian bytes each). The
        annotation has to be on the local holding the address AND on the one
        holding `p + k`;
      * **writing** through a pointee with a declared one WORKS, at the pointee's
        own width — `p.value() = v` is a store of the pointee's width (a
        truncating store, which is C's `*(UInt8 *)p = v`), so a module can build
        the `time_t` that `localtime`/`gmtime` take a POINTER to and the
        `struct tm` that `mktime`/`strftime` take;
      * a **wider** pointee on an address that came from a call is still refused
        **by name**, on the load side and now on the store side too (the load's
        width must be established, and a callee that returned `p + k` hides its
        scale).

    The store half is RUN on both backends and not merely built, because the
    failure it exists to catch is invisible to a build: a store at the wrong
    width writes the right answer and corrupts the bytes after it. So the
    program's own numbers pin the width twice over — the value stored through
    each of the four widths round-trips at that width (`300` into a `UInt8` is
    44, `70000` into a `UInt16` is 4464), and the bytes AFTER a 4-byte store
    still read 0 in a buffer that was cleared.

    What this group is NOT is the five absent names. Those are
    `bugs/FORMAL_time_struct_shaped_answers.md`'s work — the API shape against
    CPython's one struct is a judgement that doc owns — and the capability they
    were waiting for is what this group measures.
    """
    prog, r = _build(tmpdir, "tmrow", READ_MODULE, "structroute",
                     program=READ_PROGRAM)
    check(r.returncode == 0,
          f"reading a C library's bytes through a UInt8 pointee did not "
          f"build: {(r.stderr or r.stdout).strip()[-400:]}")
    # The same read on the other backend, as a BUILD: this group is the standing
    # statement that the read half of the `struct tm` route exists, and "on the
    # machine's own architecture" would be a weaker claim than the doc it backs.
    _p2, r2 = _build(tmpdir, "tmrow", READ_MODULE, "structroute_x86_64",
                     program=READ_PROGRAM, arch="x86_64")
    check(r2.returncode == 0,
          f"the UInt8-pointee read did not build for x86_64 either: "
          f"{(r2.stderr or r.stdout).strip()[-400:]}")
    ran = subprocess.run([os.path.join(TEMP, "structroute")],
                         capture_output=True, text=True, timeout=RUN_TIMEOUT,
                         cwd=HERE,
                         env=dict(os.environ, MOJO_STRUCT_ROUTE="Zq7!vB2x"))
    check(ran.returncode == 0,
          f"the image exited {ran.returncode}: "
          f"{(ran.stderr or '').strip()[-300:]}")
    got = dict(re.findall(r"(b[0-9]+)=([^@]*)" + REC, ran.stdout))
    want = {"b0": "90", "b1": "113", "b7": "120"}   # ord() of Z q 7 ! v B 2 x
    check(got == want,
          f"byte loads through a UInt8 pointee returned {got}, expected "
          f"{want} — the bytes of the value this process put in the "
          f"environment")

    # ── the store half, on BOTH backends and as a RUN ─────────────────────
    for arch in ("arm64", "x86_64"):
        _p, rs = _build(tmpdir, "tmstore", STORE_MODULE, f"store_{arch}",
                        program=_store_program(), arch=arch)
        check(rs.returncode == 0,
              f"[{arch}] storing through a declared pointee did not build: "
              f"{(rs.stderr or rs.stdout).strip()[-400:]}")
        rc, out, err = _run(os.path.join(TEMP, f"store_{arch}.{arch}"), arch)
        check(rc == 0, f"[{arch}] the store image exited {rc}: "
                       f"{err.strip()[-300:]}")
        got = dict(re.findall(r"(\w+)=([^@]*)" + REC, out))
        want = _store_want()
        check(got == want,
              f"[{arch}] the stores returned {got}, expected {want}. Each case "
              f"reads the bytes at and AFTER its own pointee, so a store at "
              f"the wrong width is visible twice over: the value round trip "
              f"truncates to the wrong width, and the byte past the pointee "
              f"reads as part of the value instead of 0")

    # The stores that must still be refused, on both backends, with the model's
    # own sentence as the needle: a store whose WIDTH would be a choice rather
    # than a fact is the outcome this path must never reach, and the sentence is
    # shared so one backend cannot drift from the other without a test failing.
    for mod_name, src, needle in STORE_REFUSALS:
        for arch in ("arm64", "x86_64"):
            _p, rr = _build(tmpdir, mod_name, src, f"refused_{mod_name}_{arch}",
                            arch=arch)
            check(rr.returncode != 0,
                  f"[{arch}] {mod_name} BUILT, so the store capability has "
                  f"widened past the point where the width is established")
            msg = rr.stderr or rr.stdout
            check(needle in msg,
                  f"[{arch}] {mod_name} was refused, but not with the words "
                  f"{needle!r}: {msg.strip()[-300:]}")

    # The one LOAD-side refusal that is still a refusal: a 4-byte pointee on an
    # address a call returned. It is here rather than in `STORE_REFUSALS`
    # because it is the load's sentence, and the store half's refusal of the
    # same construct is in that table with its own words — the pair is what says
    # the two spellings refuse the same program.
    for arch in ("arm64", "x86_64"):
        _p, rr = _build(tmpdir, "tmwide", WIDE_MODULE,
                        f"refused_wide_{arch}", arch=arch)
        check(rr.returncode != 0,
              f"[{arch}] a 4-byte load from an address a call returned BUILT, "
              f"so the width rule has moved")
        check("the load's width is the pointee's" in (rr.stderr or rr.stdout),
              f"[{arch}] the wide load was refused without the model's own "
              f"sentence: {(rr.stderr or rr.stdout).strip()[-300:]}")

    # The store the five absent `time` names need, measured the way they will
    # use it: a MODULE writes the `time_t` libc's `localtime` takes a POINTER to,
    # and the answer comes back as a `struct tm *` whose fields are read
    # byte-wise. This is the end-to-end statement that the capability is not
    # only internally consistent — the bytes libc reads are the bytes the module
    # wrote. CPython's `time.localtime` is the oracle for all three fields, and
    # the field OFFSETS are Darwin's (`struct tm` starts `tm_sec` and `tm_year`
    # is the sixth `int`), which is why this is 20 and not 0.
    tm = _tm_route_program()
    for arch in ("arm64", "x86_64"):
        rt = _build_program(tmpdir, f"tmroute_{arch}", tm, arch)
        check(rt.returncode == 0,
              f"[{arch}] the localtime route did not build: "
              f"{(rt.stderr or rt.stdout).strip()[-400:]}")
        rc, out, err = _run(os.path.join(TEMP, f"tmroute_{arch}.{arch}"), arch)
        check(rc == 0, f"[{arch}] the localtime image exited {rc}: "
                       f"{err.strip()[-300:]}")
        got = dict(re.findall(r"(\w+)=([^@]*)" + REC, out))
        want = _tm_route_want()
        check(got == want,
              f"[{arch}] the localtime route returned {got}, expected {want} "
              f"— the same three fields CPython's time.localtime reports for "
              f"1700000000")

    if verbose:
        print("    reads and stores both work at the pointee's width, on both "
              "backends")
    return True, "read yes / store yes"


GROUPS = {
    "clocks": group_clocks,
    "sleep": group_sleep,
    "convert": group_convert,
    "limits": group_limits,
    "structroute": group_structroute,
}

TEMP = None


def main():
    global TEMP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", help="subset: " + ", ".join(GROUPS))
    args = ap.parse_args()
    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is "
              f"{platform.machine()}")
        return 0
    names = args.groups or list(GROUPS)
    for n in names:
        if n not in GROUPS:
            print(f"ERROR: unknown group {n!r}; known: {sorted(GROUPS)}",
                  file=sys.stderr)
            return 2
    failed = []
    with tempfile.TemporaryDirectory() as tmpdir:
        TEMP = tmpdir
        for name in names:
            try:
                ok, detail = GROUPS[name](tmpdir, args.verbose)
            except Exception as e:
                import traceback
                if args.verbose:
                    traceback.print_exc()
                ok, detail = False, f"{type(e).__name__}: {e}"
            print(("PASS " if ok else "FAIL ") + name + (
                ("  " + detail) if detail else ""))
            if not ok:
                failed.append(name)
    print(f"\n{len(names) - len(failed)}/{len(names)} groups passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
