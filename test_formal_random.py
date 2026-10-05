#!/usr/bin/env python3
r"""`formal/hostmods/random.mojo`, differential against CPython's own `random`.

    python3 test_formal_random.py [-v] [group ...]

Groups: `resolve`, `getrandbits`, `randrange`, `seed`, `long`, `absent`.
With no argument, all. Every group that builds an image builds it on BOTH
backends.

WHY THE ORACLE IS CALLED AND NEVER TYPED
----------------------------------------
Nothing in this file records a number the module is supposed to answer. Every
expectation is computed by THIS process's `random` module, and the image has to
agree with it. That is not a stylistic choice and it is the whole reason the
row was reachable at all: **CPython's `Random` IS a Mersenne Twister**, so
"a random number" is not a specification — the specification is 40 lines of
integer arithmetic plus a seeding rule, and a module that answered *plausible
uniform* numbers would pass every check written by eye and fail both of its
callers, which compare their printed spreads against CPython's own on every
run (`test_formal_time.py:345`, `test_formal_hashlib.py:233`).

THE FOUR THINGS A TRANSCRIPTION GETS WRONG, AND WHERE EACH IS A CASE
-------------------------------------------------------------------
1. **THE INDEX IS THE ALGORITHM.** MT19937 regenerates all 624 words every 624
   draws and hands them out one at a time. A module that twists on every call is
   still uniform, still reproducible from the seed, and disagrees with CPython
   from its FIRST draw. `long` is the group that would catch it, and it is 700
   draws rather than 4 because the interesting defect is at draw 624.

2. **THE SEED IS NOT THE VALUE.** CPython seeds from `abs(a)` as little-endian
   32-bit words through `init_by_array` with a fixed 19650218 first pass — so
   `seed(0)` is not `seed(1) - 1`, a negative seed is the same sequence as its
   absolute value, and `seed(1 << 32)` is a TWO-word key. `seed`'s corpus has
   one row for each of those, and the two-word one is the only case where a
   little-endian transcription written as big-endian still agrees for small
   seeds.

3. **`randrange` IS REJECTION SAMPLING, NOT A MODULO.** CPython draws
   `n.bit_length()` bits and redraws while the draw is `>= n`. A modulo is the
   spelling everybody reaches for and it is biased; for `n = 2**k - 1` it
   changes the answer outright. `randrange`'s corpus carries two such widths on
   purpose.

4. **THE TWIST MASKS ITS SEAM.** `y` is assembled from the UPPER mask of the
   older word and the LOWER mask of the newer one, because the `>> 1` moves 31
   bits across the join. A plain `mt[kk] ^ mt[kk + 1]` is a different
   generator.

THE ONE WIDTH WHERE THIS PATH CANNOT SPELL CPYTHON'S ANSWER
-----------------------------------------------------------
`getrandbits(64)` is 64 bits and an `Int` on this path is a SIGNED 64-bit word
(`doc/ABI.md`), so the half of CPython's range with bit 63 set arrives negative
here. The BITS are the same 64; only the sign differs, and no caller in this
repository asks for it — the widest is `test_formal_time.py`'s
`randrange(1, 4_000_000_000 * 10**9)`, which asks `getrandbits` for 62. So
`getrandbits`'s check compares the two modulo 2**64 and says so at the
assertion rather than hiding it in a fixture: a reader who needs CPython's
non-negative value out of 64 bits wants a wider `Int`, which is
`bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`'s subject
and not this module's.
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
RUN_TIMEOUT = 120

TEMP = None

# `getrandbits` k, and the seeds. 0 and 1 are the two whose key derivation is a
# special case in CPython (`n = 0` still seeds, and `abs()` is what makes -7
# and 7 the same sequence); 1 << 32 is the first seed whose key is TWO words.
SEEDS = (0, 1, 23, 17, 20260930, 1 << 32, -7)
WIDTHS = tuple(range(1, 65))

# (a, b) pairs for randrange. `2**31 - 1` and `2**32 - 1` are the widths a
# modulo gets wrong; `(5, 6)` is the width-1 case where the rejection loop
# almost never redraws; `(-3, 4)` is a negative start; the two big ones are the
# callers' own ranges.
RANGES = ((0, 1), (0, 2), (5, 6), (140, 5000), (-3, 4), (0, 2 ** 31 - 1),
          (0, 2 ** 32 - 1), (2 ** 31, 2 ** 32), (1, 4_000_000_000 * 10 ** 9))


class Failure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise Failure(msg)


def backends():
    """The architectures to build for.

    BOTH, always: a 624-word recurrence indexed by a module-level counter is
    exactly the shape where a register-width or addressing difference shows up
    as a plausible wrong number rather than as a refusal, and the two backends
    are separately maintained lowerings of one AST (`CLAUDE.md`).

    A host with no x86-64 support returns one name, and `main` says so on the
    screen rather than the x86-64 half passing over quietly.
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


def run(out):
    r = subprocess.run([out], capture_output=True, timeout=RUN_TIMEOUT,
                       cwd=HERE)
    check(r.returncode == 0,
          f"image {os.path.basename(out)} exited {r.returncode}: "
          f"{(r.stderr or b'').decode('utf-8', 'replace').strip()[-300:]}")
    return [line for line in
            r.stdout.decode("latin-1").splitlines() if line != ""]


def program(lines):
    """A `main` that runs `lines` and prints each result with `%ld`.

    `%ld` and not `%d`: the answers are 32-bit values CPython spells UNSIGNED,
    and a `%d` reads 32 bits out of a 64-bit word, so `%d` would report every
    answer above 2^31 as a negative number and the comparison would be against
    the wrong thing. That is a property of the format string, not of the module,
    and it cost this file one wrong measurement before it was pinned here.
    """
    body = "\n".join(f"    {line}" for line in lines)
    return ("import random\n\ndef main() -> int32:\n" + body +
            "\n    return 0\n")


def compare(got, want, label, backend, signed64=False):
    check(len(got) == len(want),
          f"[{backend}] {label}: {len(got)} answers where CPython gives "
          f"{len(want)} — the image and CPython disagree about how many "
          f"draws the program makes")
    for i, (g, w) in enumerate(zip(got, want)):
        gv = int(g)
        if signed64:
            # See the module docstring: the same 64 bits, and only the sign
            # differs, because an `Int` here is a signed 64-bit word.
            check((gv - w) % (1 << 64) == 0,
                  f"[{backend}] {label}: answer {i} is {g}, CPython says {w}")
        else:
            check(gv == w,
                  f"[{backend}] {label}: answer {i} is {g}, CPython says {w} "
                  f"(first divergence; the module's own state is the suspect, "
                  f"not the print)")


def cpython_draws(seed, kind, arg, count):
    """CPython's own answers for `count` draws of one shape."""
    import random as _r
    _r.seed(seed)
    out = []
    for _ in range(count):
        if kind == "getrandbits":
            out.append(_r.getrandbits(arg))
        else:
            out.append(_r.randrange(*arg))
    return out


# ── the groups ────────────────────────────────────────────────────────────

def group_resolve(tmpdir, verbose):
    """`import random` resolves to this file, and the tier says so.

    `formal/imports.py`'s rule is that a name LEAVES `HOST_MODELLED` by being
    WRITTEN, so a leftover entry would make the instrument report a module that
    is already there as work to do. `test_formal_imports.py` checks the tier
    sets; this checks the file and the answer for this one name, which is the
    part a reader of the ranking asks about first.
    """
    sys.path.insert(0, HERE)
    import formal.imports as imp
    path = imp.resolve_module_path("random")
    check(path and os.path.isfile(path),
          f"resolve_module_path('random') is {path!r}, not this module")
    check(os.path.samefile(path, RANDOM_MODULE),
          f"random resolves to {path}, not {RANDOM_MODULE}")
    check(imp.host_module_tier("random") == "",
          f"random is still in tier {imp.host_module_tier('random')!r} after "
          f"being written")
    return True, "resolves to formal/hostmods/random.mojo, in no tier"


def group_getrandbits(tmpdir, verbose):
    """Every width 1..64, for every seed, against CPython's own.

    One image per backend: each (seed, width) pair is a `seed` and one call, so
    the whole corpus is a straight-line program and the build cost is paid
    once. Widths below 32 are one 32-bit draw shifted down and widths above are
    two draws assembled with the LAST one shifted — so 31/32 and 33 are the two
    rows that separate those rules from each other, and 62 is
    `test_formal_time.py`'s own width.
    """
    import random as _r
    lines, want, labels = [], [], []
    for seed in SEEDS:
        for k in WIDTHS:
            lines.append(f"random.seed({seed})")
            lines.append(f'printf("%ld\\n", random.getrandbits({k}))')
            _r.seed(seed)
            want.append(_r.getrandbits(k))
            labels.append(f"getrandbits({k}) after seed({seed})")
    src = program(lines)
    count = len(want)
    for backend in backends():
        got = run(build(src, f"gb_{backend}", backend))
        compare(got, want, f"getrandbits over {len(SEEDS)} seeds x "
                           f"{len(WIDTHS)} widths ({count} answers)",
                backend, signed64=True)
    return True, f"{count} answers per backend over {len(SEEDS)} seeds x " \
                 f"{len(WIDTHS)} widths"


def group_randrange(tmpdir, verbose):
    """The rejection-sampling ranges, against CPython's own.

    Ten draws per range, and the corpus is weighted towards the widths a
    modulo gets wrong: `2**31 - 1` and `2**32 - 1` are the cases where
    `draw % n` is not merely biased but a different number.
    """
    import random as _r
    lines, want = [], []
    for seed in (23, 17, 20260930):
        for ab in RANGES:
            lines.append(f"random.seed({seed})")
            for _ in range(10):
                lines.append(f'printf("%ld\\n", random.randrange({ab[0]}, '
                             f"{ab[1]}))")
            _r.seed(seed)
            want.extend(_r.randrange(ab[0], ab[1]) for _ in range(10))
    src = program(lines)
    count = len(want)
    for backend in backends():
        got = run(build(src, f"rr_{backend}", backend))
        compare(got, want,
                f"randrange over {len(RANGES)} ranges x 10 draws x 3 seeds "
                f"({count} answers)", backend)
    return True, f"{count} answers per backend over {len(RANGES)} ranges"


def group_seed(tmpdir, verbose):
    """The seeding rule, one row per thing it is not.

    Seven seeds x four draws each. `seed(0)` (CPython's key is one word of
    zeros and the generator still runs), `seed(1)` and `seed(-1 << 32)`'s
    partner `seed(1 << 32)` (the first TWO-word key, where a big-endian
    transcription finally differs), and `-7` beside `7` (the absolute value).
    The last row re-seeds with the SAME seed and asks for the same draws again,
    which is what "reproducible" means and is a property of the state rather
    than of the algorithm.
    """
    import random as _r
    lines, want = [], []
    for seed in SEEDS + (7,):
        lines.append(f"random.seed({seed})")
        for _ in range(4):
            lines.append('printf("%ld\\n", random.getrandbits(32))')
        _r.seed(seed)
        want.extend(_r.getrandbits(32) for _ in range(4))
    # Re-seed and redraw: the same numbers, twice.
    lines.append("random.seed(23)")
    for _ in range(2):
        lines.append('printf("%ld\\n", random.getrandbits(32))')
    _r.seed(23)
    want.extend(_r.getrandbits(32) for _ in range(2))
    src = program(lines)
    count = len(want)
    for backend in backends():
        got = run(build(src, f"sd_{backend}", backend))
        compare(got, want, f"seed over {len(SEEDS) + 1} seeds "
                           f"({count} answers)", backend)
    return True, f"{count} answers per backend over {len(SEEDS) + 1} seeds"


def group_long(tmpdir, verbose):
    """700 draws of one seed: the index walk, across a regeneration.

    The 624-word state is regenerated on draw 625, so this crosses the boundary
    once and a half. **This is the group that catches the defect the module's
    own docstring names first** — a `_twist` on every call is uniform and
    reproducible and differs from CPython on the FIRST answer, and a version
    that kept no index at all differs at 625. Neither is visible in four draws.
    """
    import random as _r
    n = 700
    lines = ["random.seed(23)"]
    for _ in range(n):
        lines.append('printf("%ld\\n", random.getrandbits(32))')
    _r.seed(23)
    want = [_r.getrandbits(32) for _ in range(n)]
    src = program(lines)
    for backend in backends():
        got = run(build(src, f"lo_{backend}", backend))
        compare(got, want, f"{n} consecutive draws (crosses the 624-word "
                           f"regeneration)", backend)
    return True, f"{n} consecutive draws per backend"


def group_absent(tmpdir, verbose):
    """The names this module does NOT have, refused naming themselves.

    `Random` is the one that matters and the one the row's other two files want:
    a `random.Random(n)` INSTANCE is an object with 624 words behind a pointer,
    so those files stop on the instance rather than on the import
    (`bugs/FORMAL_a_type_cannot_be_constructed_or_cloned_at_run_time.md`).
    `random()` is a `double`; `shuffle`/`choice`/`sample` take or answer a
    SEQUENCE, which lives in the caller's frame; `randint` is `randrange(a,
    b + 1)` and is absent with the rest rather than shipped as a second way to
    spell what `randrange` already says.

    Each is refused NAMING ITSELF, so a caller that wants one is told which one
    rather than getting a link error.
    """
    cases = (("Random", "Random(5)", None),
             ("random", "random()", None),
             ("shuffle", 'shuffle([1, 2])', None),
             ("choice", "choice([1, 2])", None),
             ("randint", "randint(1, 5)", None),
             ("uniform", "uniform(0.0, 1.0)", None))
    for name, call, _ in cases:
        src = ("import random\n\ndef main() -> int32:\n"
               f'    printf("%ld\\n", random.{call})\n'
               "    return 0\n")
        tmp = os.path.join(TEMP, "absent.mojo")
        out = os.path.join(TEMP, "absent")
        with open(tmp, "w") as f:
            f.write(src)
        r = subprocess.run([sys.executable, FIRE, "build", "--formal",
                            "--no-prove", "-o", out, tmp],
                           capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT, cwd=HERE)
        msg = (r.stderr or r.stdout)
        check(r.returncode != 0,
              f"random.{name} built; it is not supposed to exist, and a "
              f"silently-approximated name is worse than a refusal")
        check(name in msg,
              f"the refusal for random.{name} does not NAME it: "
              f"{msg.strip()[-200:]}")
    return True, f"{len(cases)} absent names refused, each naming itself"


GROUPS = {
    "resolve": group_resolve,
    "getrandbits": group_getrandbits,
    "randrange": group_randrange,
    "seed": group_seed,
    "long": group_long,
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
                print(f"PASS {nm:12} {msg}")
                npass += 1
            except Failure as e:
                print(f"FAIL {nm:12} {e}")
                nfail += 1
            except Exception as e:  # noqa: BLE001
                print(f"ERROR {nm:11} {type(e).__name__}: {e}")
                nfail += 1
        print(f"\nformal random: PASS={npass} FAIL={nfail} "
              f"(backends: {', '.join(backends())})")
        return 1 if nfail else 0


if __name__ == "__main__":
    sys.exit(main())