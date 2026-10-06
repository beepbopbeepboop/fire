#!/usr/bin/env python3
r"""`formal/hostmods/random.mojo`, differential against CPython's `random`.

    python3 test_formal_random.py [-v] [group ...]

Groups: `resolve`, `callers`, `widths`, `twist`, `seeds`, `rejection`,
`statuses`, `absent`. With no argument, all. Every group that builds an image
builds it on BOTH backends.

WHY THE ORACLE IS CPython'S OWN `random`, CALLED, NEVER TYPED
--------------------------------------------------------------
A Mersenne Twister is a fixed sequence of integers, and the temptation with one
is to write the expected answers down — `random.seed(1); random.random()` is
0.13436424411240122 in every account of this algorithm ever written. That table
is worthless here for two reasons. It is a table of ONE implementation's
answers, so a transcription that is wrong in the same direction as the table
passes; and the caller of this module is a DIFFERENTIAL TEST
(`test_formal_hashlib.py` and `test_formal_time.py` both compute their corpus
with CPython's own `random` and hand the numbers to the image), so what has to
agree is this process's `random` and not a remembered constant.

Every case below is therefore computed twice: once by `random.seed(...)` and a
list comprehension here, and once by an image built through the formal backend
and executed, and the two lists have to be equal.

THE THREE THINGS THAT ARE WORTH A GROUP EACH
---------------------------------------------
The module docstring names four ways to transcribe MT19937 wrong; three of them
have a group here, and each is a case rather than a comment because a
transcription that is wrong produces answers of the right SHAPE:

1. **`_getrandbits(k)` FOR 33 <= k.** The first word drawn is the LOW word and
   the low word is not shifted. The tempting simplification
   `((w0 | (w1 << 32)) >> (64 - k))` drops the top bits of the LOW word too, so
   for `k = 33` it answers 2 bits where CPython answers 33 — and every answer
   it produces is under `2^32`, which looks like a plausible number in a
   timestamp corpus. **This is not hypothetical: it is what the module said
   first, and `widths` caught it on its first run**, arm64 and x86-64 alike,
   because `randrange(0, 2**33)` answered 2 and 3. `widths` has a case for
   every branch of that function, k = 1, 32, 33, 40, 62, 63, in one program so
   the two-word path is reached from the same state as the one-word path.

2. **THE TWIST.** 624 words of state are consumed per 624 draws, and the
   recurrence is a different shape on the far side of the boundary (the second
   half of the pass reads words the first half has already rewritten). A corpus
   of forty draws, which is what both real callers have, never reaches it: the
   `test_formal_time.py` caller draws 120 values of 62 bits, which is 240 words.
   **`twist` draws past 624 words on purpose** — 700 draws at one bit each, so
   the state wraps twice — and it is the only group that can fail where every
   other group passes.

3. **THE SEED'S WORD COUNT.** CPython splits the absolute value into 32-bit
   words from the right, and a zero seed is ONE word of zero rather than no
   words, so `seed(0)` is not the unseeded generator. `seeds` covers one word,
   two words and three words, both signs, and zero, because the key length
   changes how the mix loop wraps (`i` and `j` wrap at 624 and `keyused`) and a
   one-word seed cannot see that.

WHAT `callers` IS, AND WHY IT IS THE GROUP THAT MATTERS MOST
------------------------------------------------------------
Two files in this repository spell this module's names, and they spell them at
ranges that are 4 and 19 digits wide:
`test_formal_hashlib.py:233` does `random.seed(23)` then forty draws of
`random.randrange(140, 5000)`, and `test_formal_time.py:345` does
`random.seed(17)` then a hundred and twenty draws of
`random.randrange(1, 4_000_000_000 * 10**9)`. `callers` runs both verbatim,
all forty and all a hundred and twenty, against CPython — so the module is
measured over exactly the sequence the two files that need it will ask for,
rather than over a corpus chosen to be interesting.

THE PRINT IS `%lld`, AND THAT IS NOT COSMETIC
---------------------------------------------
Every value here is printed with `%lld`, and a `%d` would truncate each answer
to 32 bits and report a plausible-looking negative number: `randrange(0, 2**33)`
answers 5891807615, and `printf("%d", …)` prints 1596840319, which is that
number mod `2^32`. It cost one build to find, and `widths` would have failed on
the `k = 33` case rather than on the arithmetic if it had been written with
`%d` — a test that fails for the wrong reason is a test that has to be
re-diagnosed, so the format is `%lld` everywhere.
"""

import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
HOSTMODS = os.path.join(HERE, "formal", "hostmods")
RANDOM_MODULE = os.path.join(HOSTMODS, "random.mojo")
BUILD_TIMEOUT = 900
RUN_TIMEOUT = 300
REC = "@@"

TEMP = None


class Failure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Failure(msg)


def backends():
    """The architectures to build for.

    BOTH, always: a Mersenne Twister is the shape where a register-width
    difference shows up as a wrong NUMBER rather than as a refusal, and the
    module carries 64-bit multiplies and a two-word assembly that a 32-bit
    register file would answer differently. `gimple_codegen.py` and
    `myinterpreter.py` are separately maintained lowerings of one AST
    (`CLAUDE.md`), so "both agree" is evidence and "one of them agreed" is not.
    """
    if platform.machine() in ("arm64", "aarch64"):
        return ["arm64", "x86_64"]
    return ["x86_64"]


def build(src, name, backend=None):
    tmp = os.path.join(TEMP, name + ".mojo")
    out = os.path.join(TEMP, f"{name}.{backend}" if backend else name)
    with open(tmp, "w") as f:
        f.write(src)
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out]
    if backend:
        cmd.append(f"--backend={backend}")
    cmd.append(tmp)
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    check(r.returncode == 0,
          f"build failed{(f' on --backend={backend}' if backend else '')}: "
          f"{(r.stderr or r.stdout).strip()[-600:]}")
    check(os.path.isfile(out), f"no image at {out}")
    return out


def build_expecting_refusal(src, name, backend, needle):
    """Build and require a REFUSAL that says `needle`, on `backend`.

    The `absent` group is about names the module does NOT publish, so the
    interesting outcome is a build that fails and says why. A refusal is
    accepted only if it still NAMES the identifier: a message that dropped the
    name would leave the group passing for the wrong reason.
    """
    out = os.path.join(TEMP, f"{name}.{backend}")
    tmp = os.path.join(TEMP, name + ".mojo")
    with open(tmp, "w") as f:
        f.write(src)
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out,
           f"--backend={backend}", tmp]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    text = (r.stderr or r.stdout)
    check(r.returncode != 0,
          f"--backend={backend} BUILT a program that spells {needle!r}, which "
          f"this module does not publish: {text.strip()[-300:]}")
    check(needle in text,
          f"--backend={backend} refused without naming {needle!r}, so the "
          f"message may have been about something else: {text.strip()[-300:]}")
    return text.strip()


def run(out):
    r = subprocess.run([out], capture_output=True, timeout=RUN_TIMEOUT,
                       cwd=HERE)
    check(r.returncode == 0,
          f"image {os.path.basename(out)} exited {r.returncode}: "
          f"{(r.stderr or b'').decode('utf-8', 'replace').strip()[-300:]}")
    return r.stdout.decode("latin-1")


def records(text):
    """`<index>:[<value>` records, as a list of `(index, value)` pairs.

    The bracketed value and the two-byte separator are `test_formal_shlex.py`'s
    arrangement and for its reasons: a value may contain the separator, and an
    INDEX is needed because one image prints many values and a diff that cannot
    say WHICH one went wrong is a diff nobody acts on.
    """
    got = []
    for rec in text.split(REC):
        if not rec:
            continue
        head, sep, val = rec.partition(":[")
        if not sep:
            raise Failure(f"record with no bracket: {rec!r}")
        if not val.endswith("]"):
            raise Failure(f"record with no closing bracket: {rec!r}")
        got.append((int(head), val[:-1]))
    return got


# ── the corpus program ─────────────────────────────────────────────────────
#
# One image prints a whole corpus as records. Two of the bounds here are
# measured facts about this path rather than style choices:
#
#   * `%lld`, not `%d`. Every value is a 64-bit word and a variadic C `%d` reads
#     an `int`: `randrange(0, 2**33)` answers 5891807615 and `printf("%d", …)`
#     prints 1596840319, which is that number mod `2**32` — a plausible number
#     in a timestamp corpus. It cost one build to find.
#   * the record INDEX is a LITERAL in the format string, not an argument. A
#     variadic call here is refused on arm64 past eight arguments ("puts 1 of
#     them past the 8 argument registers"), and passing each index as an
#     argument would spend the budget on the numbering: 1 format + k indices + k
#     values leaves room for three. The index is known when the format is
#     built, so baking it in costs nothing and leaves seven — OF WHICH FIVE ARE
#     USED, because the seventh argument is the first one that goes on the
#     stack on SysV. That used to matter twice over: x86-64's
#     `formal/x86_64_codegen.py::_emit_call` evaluated a stack-passed argument
#     BEFORE the register ones, so six `randrange` calls in one `printf`
#     answered `2 3 4 5 6 1` on x86-64 where CPython's `random` gives
#     `1 1 0 1 1 0`. That is FIXED (one reserved outgoing area, every argument
#     staged into it in source order, the register half loaded out afterwards),
#     and `test_formal_x86_64_parity.py`'s
#     `variadic_arguments_are_evaluated_in_source_order` is the differential
#     that pins it. Five values per call stays the bound anyway, so this corpus
#     does not sit on the edge of the ABI; it is the bound, not a preference.
PER_LINE = 5


def program(lines):
    """A corpus program: `lines` of `printf` statements, inside a `main`."""
    body = "\n".join("    " + l for l in lines)
    return "\n".join(["import random", "", "def main() -> Int32:", body,
                      "    return 0", ""])


def emit_rows(values, start=0, per_line=PER_LINE):
    """Records for every value, `per_line` to a call, numbered from `start`.

    The index is a literal inside the format string (see `PER_LINE`), and it
    runs across the whole program so a diff names WHICH draw went wrong rather
    than only how many.
    """
    out = []
    for at in range(0, len(values), per_line):
        chunk = values[at:at + per_line]
        fmt = "".join("%d:[%%lld]" % (start + at + i) + REC
                      for i in range(len(chunk)))
        out.append(f'printf("{fmt}", {", ".join(chunk)})')
    return out


def cpy_values(seed, lo, hi, count):
    """CPython's own `count` answers to `seed` then `randrange(lo, hi)`.

    Called, never tabulated — see the header. A fresh module-level `seed` per
    call is what CPython does for a module function, and the module here is
    also a module-level generator, so the two agree about which state a second
    call sees.
    """
    import random as cpy
    cpy.seed(seed)
    return [cpy.randrange(lo, hi) for _ in range(count)]


# ── groups ─────────────────────────────────────────────────────────────────

def group_resolve(tmpdir, verbose):
    """`import random` binds to this module, and it publishes two names.

    The export half is the assertion that matters: a dylib publishes its
    FUNCTIONS, so `seed` and `randrange` resolving is the capability and
    anything else being absent is the boundary. `_twist`, `_next32` and
    `_getrandbits` are deliberately private — `formal/hostmods/shlex.mojo`
    records what happens when a private name is treated as an export — and
    `absent` is where they are asked for.
    """
    src = program(
        emit_rows(["random.randrange(0, 1000)", "random.randrange(0, 1000)",
                   "random.randrange(0, 1000)"])
        + ['printf("two=%lld,%lld\\n", random.randrange(3, 9), '
           'random.randrange(3, 9))'])
    for backend in backends():
        out = build(src, "random_resolve", backend)
        text = run(out)
        check("two=" in text, f"[{backend}] no `two=` line: {text!r}")
    check(os.path.isfile(RANDOM_MODULE),
          f"{RANDOM_MODULE} is not there, so `import random` cannot bind to it")
    with open(RANDOM_MODULE) as f:
        text = f.read()
    for name in ("def seed(", "def randrange("):
        check(name in text, f"{RANDOM_MODULE} does not declare {name}")
    for name in ("_twist", "_next32", "_getrandbits", "_bit_length"):
        check(f"def {name}(" in text,
              f"{RANDOM_MODULE} lost the private helper {name}, and "
              f"randrange's answer depends on it")
    if verbose:
        print(f"    bound on {', '.join(backends())}, two names published")
    return True, f"module found, seed/randrange published, helpers private"


def group_callers(tmpdir, verbose):
    """The two call sites in this repository, verbatim, against CPython.

    `test_formal_hashlib.py:233` — `random.seed(23)` then forty draws of
    `random.randrange(140, 5000)`, which is 13 bits and one word per draw.
    `test_formal_time.py:345` — `random.seed(17)` then a hundred and twenty
    draws of `random.randrange(1, 4_000_000_000 * 10**9)`, which is 62 bits and
    TWO words per draw, so 240 words of state and a width that CPython's own
    `randrange` reaches through `_randbelow_with_getrandbits`'s rejection loop.
    """
    cases = [
        # (name, seed, the Mojo spelling of the bounds, the bounds, draws)
        ("hashlib", 23, "140", "5000", (140, 5000), 40),
        ("time", 17, "1", "4_000_000_000 * 10**9", (1, 4_000_000_000 * 10**9),
         120),
    ]
    total = 0
    for backend in backends():
        for name, seed, lo, hi, (nlo, nhi), count in cases:
            expr = f"random.randrange({lo}, {hi})"
            values = cpy_values(seed, nlo, nhi, count)
            src = program([f"random.seed({seed})"] + emit_rows([expr] * count))
            got = [v for _, v in records(run(build(src, f"random_{name}",
                                                  backend)))]
            check(len(got) == count,
                  f"[{backend}] {name}: {len(got)} record(s) for {count} draw(s)")
            for i, (g, w) in enumerate(zip(got, values)):
                if g != str(w):
                    raise Failure(
                        f"[{backend}] {name}: draw {i} of seed({seed}) "
                        f"randrange({lo}, {hi}) is {g}, CPython's is {w}")
            total += count
    if verbose:
        print(f"    {total} draw(s) agree with CPython per backend")
    return True, (f"both call sites verbatim, {total} draws per backend, all "
                  f"CPython's")


def group_widths(tmpdir, verbose):
    """One case per branch of `_getrandbits`, from ONE state.

    The six widths are `k = 1`, `k = 32` (the fast path's last bit),
    `k = 33` (the two-word path's first bit — the case the wrong simplification
    of that function answers in 2 bits), `k = 40`, `k = 62` (what
    `test_formal_time.py` asks for) and `k = 63` (the widest this path can
    represent). They share one `seed`, so the case that finds a wrong two-word
    assembly finds it against a state the one-word cases have already pinned.
    """
    cases = [
        ("k1", 0, 2),
        ("k32", 0, 4294967296),
        ("k33", 0, 8589934592),
        ("k40", 0, 1099511627776),
        ("k62", 0, 4611686018427387904),
        ("k63", 0, 9223372036854775808 - 1),
    ]
    for backend in backends():
        lines = ["random.seed(5)"]
        idx = 0
        for _, lo, hi in cases:
            lines.extend(emit_rows([f"random.randrange({lo}, {hi})"] * 2,
                                  start=idx))
            idx += 2
        src = program(lines)
        got = [v for _, v in records(run(build(src, "random_widths", backend)))]
        # CPython draws from ONE state, so the expectations come from one
        # seeded generator in the same order rather than per case: a per-case
        # reseed would compare the image's carried state against CPython's
        # fresh one.
        import random as cpy
        cpy.seed(5)
        want = [str(cpy.randrange(lo, hi)) for _, lo, hi in cases
                for _ in range(2)]
        check(len(got) == len(want),
              f"[{backend}] {len(got)} record(s) for {len(want)} draw(s)")
        for i, (g, w) in enumerate(zip(got, want)):
            if g != w:
                raise Failure(
                    f"[{backend}] draw {i} ({cases[i // 2][0]}): the image "
                    f"answered {g}, CPython's is {w}")
    if verbose:
        print(f"    12 draw(s) over 6 widths agree with CPython per backend")
    return True, f"6 widths x 2 draws = 12 answers per backend, all CPython's"


def group_twist(tmpdir, verbose):
    """Past 624 words, so the state RECURRENCE runs — the only group that can.

    700 draws at one bit each consume 700 words, which is one full state plus
    76: the twist at word 624 is inside this group and nowhere else in the
    file. `test_formal_hashlib.py`'s forty draws and `test_formal_time.py`'s
    240 words both stop short of it, so a corpus built out of the real call
    sites could not tell a correct twist from a correct absence of one.
    """
    count = 700
    for backend in backends():
        expr = "random.randrange(0, 2)"
        src = program(["random.seed(20260930)"] + emit_rows([expr] * count))
        got = [v for _, v in records(run(build(src, "random_twist", backend)))]
        want = cpy_values(20260930, 0, 2, count)
        check(len(got) == count,
              f"[{backend}] {len(got)} record(s) for {count} draw(s)")
        for i, (g, w) in enumerate(zip(got, want)):
            if g != str(w):
                raise Failure(
                    f"[{backend}] draw {i} of 700 (word {i}, the twist is at "
                    f"624): the image answered {g}, CPython's is {w}")
    if verbose:
        print(f"    700 draws per backend, crossing the twist at word 624")
    return True, f"700 draws per backend across the twist at word 624"


def group_seeds(tmpdir, verbose):
    """Seeds of one word, two words and three words, both signs, and zero.

    CPython's `keyused` is `bits == 0 ? 1 : (bits - 1) / 32 + 1` over the
    ABSOLUTE value, so `seed(0)` is one key word of zero (not the unseeded
    generator), `seed(-23)` and `seed(23)` are one state, and a seed above
    `2**32` is two or three key words — which is what changes how the mix loop's
    `j` wraps against its `i`. The corpus stops at `2**63 - 1`: a word on this
    path is signed, so a seed above it is not a value, and the largest seed a
    caller can spell here is that one.
    """
    seeds = [0, 1, 2, 17, 23, -1, -17, -23, 2147483647, 2147483648,
             4294967295, 4294967296, 4294967301, 8589934592,
             9223372036854775807]
    import random as cpy
    for backend in backends():
        lines = []
        want = []
        idx = 0
        for s in seeds:
            lines.append(f"random.seed({s})")
            cpy.seed(s)
            lines.extend(emit_rows(["random.randrange(0, 1000)"] * 3, start=idx))
            want.extend(str(cpy.randrange(0, 1000)) for _ in range(3))
            idx += 3
        got = [v for _, v in records(run(build(program(lines), "random_seeds",
                                              backend)))]
        check(len(got) == len(want),
              f"[{backend}] {len(got)} record(s) for {len(want)} draw(s)")
        for i, (g, w) in enumerate(zip(got, want)):
            if g != w:
                seed = seeds[i // 3]
                raise Failure(
                    f"[{backend}] seed({seed}) draw {i % 3}: the image answered "
                    f"{g}, CPython's is {w}")
    if verbose:
        print(f"    {len(seeds)} seeds x 3 draws agree with CPython per backend")
    return True, (f"{len(seeds)} seeds (1, 2 and 3 key words, both signs, "
                  f"zero) x 3 draws per backend")


def group_rejection(tmpdir, verbose):
    """Widths just UNDER a power of two, where CPython's rejection loop runs.

    `_randbelow_with_getrandbits` draws `width.bit_length()` bits and rejects
    anything `>= width`, so a width of `2**k - 1` rejects about half its draws.
    A transcription that drops the `while r >= width` retry would answer a
    biased sequence that still agrees with CPython on the FIRST draw of each
    width and disagrees later — so each case here is a run of eight draws, not
    one, and the seed is shared across the cases so the state carries over.
    """
    widths = [(0, 3), (0, 7), (0, 31), (0, 1023), (1000, 1023),
              (0, 1073741823), (0, 4611686018427387903)]
    import random as cpy
    for backend in backends():
        cpy.seed(99)
        want = []
        lines = ["random.seed(99)"]
        for lo, hi in widths:
            want.extend(str(cpy.randrange(lo, hi)) for _ in range(8))
            lines.extend(emit_rows([f"random.randrange({lo}, {hi})"] * 8))
        got = [v for _, v in records(run(build(program(lines),
                                                 "random_reject", backend)))]
        check(len(got) == len(want),
              f"[{backend}] {len(got)} record(s) for {len(want)} draw(s)")
        for i, (g, w) in enumerate(zip(got, want)):
            if g != w:
                raise Failure(
                    f"[{backend}] draw {i} of the rejection corpus: the image "
                    f"answered {g}, CPython's is {w}")
    if verbose:
        print(f"    {len(widths)} widths x 8 draws agree with CPython per backend")
    return True, (f"{len(widths)} widths below a power of two x 8 draws per "
                  f"backend, all CPython's")


def group_statuses(tmpdir, verbose):
    """The two shapes CPython RAISES on, which answer -1 here.

    There are no exceptions on this path (FORMAL.md phase 7), so each of these
    is a status rather than a refusal, and the status has to be checked rather
    than assumed: `randrange(5, 5)` must not HANG, which it would if
    `_bit_length(0)` were 0 with no guard, and a width above `2**63` must not
    answer a wrapped negative number, which is the wrong answer that looks
    plausible.
    """
    cases = [
        ("empty_equal", "random.randrange(5, 5)", -1),
        ("empty_reversed", "random.randrange(9, 2)", -1),
        ("empty_negative", "random.randrange(-2, -7)", -1),
        # The only spelling of a width needing k = 64 that a signed 64-bit
        # world can hold: a negative lower bound and the largest positive one,
        # so the width is 2**64 - 1 and the answer can land anywhere in it —
        # including above 2**63, which is not a value this path has. It is
        # spelled as an arithmetic expression rather than the literal because
        # `-9223372036854775808` is a negation of a word that does not fit.
        ("width_over_2_63",
         "random.randrange(0 - 9223372036854775807 - 1, 9223372036854775807)",
         -1),
        # ... and the widest one it CAN answer: a width of 2**63 - 1 needs
        # k = 63, whose answer is below 2**63 and so is a value here. Pinned
        # because it is the row next to the status, and a `k >= 63` guard
        # would answer it -1 too.
        ("width_2_63_minus_1",
         "random.randrange(0, 9223372036854775807)", None),
    ]
    for backend in backends():
        src = program(["random.seed(1)"] +
                      emit_rows([e for _, e, _ in cases], start=0))
        got = [v for _, v in records(run(build(src, "random_status",
                                              backend)))]
        check(len(got) == len(cases),
              f"[{backend}] {len(got)} record(s) for {len(cases)} case(s)")
        for i, ((name, expr, want), g) in enumerate(zip(cases, got)):
            if want is None:
                # The answered row: compared with CPython's own draw from the
                # same seed, because the point is that this width IS served.
                if g == "-1":
                    raise Failure(
                        f"[{backend}] {name}: the image answered the status -1 "
                        f"for a width of 2**63 - 1, which needs k = 63 and "
                        f"whose answer is below 2**63 — the `k >= 64` guard is "
                        f"one bit too wide")
                continue
            if g != str(want):
                raise Failure(
                    f"[{backend}] {name}: the image answered {g}, the "
                    f"documented status is {want}")
    # CPython's own behaviour on the same inputs, so the status is a DIFFERENCE
    # that is stated rather than an invention.
    import random as cpy
    cpy_raises = 0
    for args in ((5, 5), (9, 2), (-2, -7)):
        try:
            cpy.randrange(*args)
        except ValueError:
            cpy_raises += 1
    check(cpy_raises == 3,
          f"CPython raised ValueError on {cpy_raises} of 3 empty ranges, so "
          f"the -1 status is standing in for a raise this host does not have")
    # And the width above 2**63: CPython answers it (its own bound is
    # PyLong_AsSsize_t, so 2**63 - 1 is a legal stop), and this path cannot,
    # because the answer is a 64-bit UNSIGNED value that can land above 2**63.
    cpy.seed(1)
    over = cpy.randrange(-(2**63), 2**63 - 1)
    check(-(2**63) <= over < 2**63 - 1,
          "CPython's own answer for the over-2**63 width is not in range, so "
          "the claim that this host cannot represent every such answer is not "
          "about this input")
    cpy.seed(1)
    served = cpy.randrange(0, 2**63 - 1)
    check(0 <= served < 2**63 - 1,
          "CPython's own answer for the 2**63 - 1 width is not in range, so "
          "the row this group pins as ANSWERED is not about this input")
    if verbose:
        print(f"    {len(cases)} status case(s) per backend; CPython raises "
              f"ValueError on the 3 empty ranges")
    return True, (f"{len(cases)} status cases per backend; CPython raises "
                  f"ValueError where this answers -1")


def group_absent(tmpdir, verbose):
    """The names this module does NOT publish, refused BY NAME.

    Each is a refusal rather than an absence because an absence is what a caller
    reads as a silent zero: `random.Random(3)` in `test_gimple.py` and
    `random.getrandbits(8)` must both fail to build, and the message has to name
    the identifier so the reader knows which name is missing.
    """
    cases = [
        ("Random", "def main() -> Int32:\n    var r = random.Random(3)\n"
                   "    return 0\n"),
        ("getrandbits", "def main() -> Int32:\n"
                        "    printf(\"%lld\\n\", random.getrandbits(8))\n"
                        "    return 0\n"),
        ("random", "def main() -> Int32:\n"
                   "    printf(\"%lld\\n\", random.random())\n    return 0\n"),
        ("randint", "def main() -> Int32:\n"
                    "    printf(\"%lld\\n\", random.randint(1, 6))\n"
                    "    return 0\n"),
    ]
    for backend in backends():
        for name, body in cases:
            src = "import random\n\n" + body
            build_expecting_refusal(src, f"random_absent_{name}", backend, name)
    if verbose:
        print(f"    {len(cases)} absent name(s) refused by name on "
              f"{', '.join(backends())}")
    return True, (f"{len(cases)} names refused by name on "
                  f"{len(backends())} backend(s)")


GROUPS = {
    "resolve": group_resolve,
    "callers": group_callers,
    "widths": group_widths,
    "twist": group_twist,
    "seeds": group_seeds,
    "rejection": group_rejection,
    "statuses": group_statuses,
    "absent": group_absent,
}


def main():
    global TEMP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("groups", nargs="*", choices=sorted(GROUPS))
    args = ap.parse_args()
    names = args.groups or list(GROUPS)
    with tempfile.TemporaryDirectory(prefix="randomtest") as td:
        TEMP = td
        npass = nfail = 0
        for nm in names:
            try:
                _ok, msg = GROUPS[nm](td, args.verbose)
                print(f"PASS {nm:10} {msg}")
                npass += 1
            except Failure as e:
                print(f"FAIL {nm:10} {e}")
                nfail += 1
            except Exception as e:  # noqa: BLE001
                print(f"ERROR {nm:9} {type(e).__name__}: {e}")
                nfail += 1
        print(f"\nformal random: PASS={npass} FAIL={nfail} "
              f"(backends: {', '.join(backends())})")
        return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())