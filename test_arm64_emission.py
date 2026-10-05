#!/usr/bin/env python3
"""Emission tests: the new arm64 instructions must actually be EMITTED.

`test_arm64_encoders.py` proves each encoder produces the bytes Apple's
assembler produces. That is necessary and not sufficient: an encoder nothing
calls is a decoder test with extra steps, and the codegen went on emitting
`cmp` + `cset` + `cbz` for years with a perfectly good encoder sitting unused.

So these build real programs and look at the disassembly, for two things the
value tests cannot see:

  1. that the instruction appears at all (the encoder is reachable), and
  2. that using it did not quietly change what the program computes.

The second is the one that matters. A CSEL that picks the wrong operand, or
an `and` compiled as an `or`, produces a program that builds, runs, and
answers with the wrong number — the same failure shape as the dict
comprehension, and the reason every case here checks a VALUE and not just a
mnemonic.

Usage:
    python3 test_arm64_emission.py [-v]
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


class TestFailure(Exception):
    pass


def check(cond, msg):
    if not cond:
        raise TestFailure(msg)


def build_and_run(source, tmpdir, name):
    """(exit_status, disassembly) for `source` built with `build --formal`."""
    src = os.path.join(tmpdir, name + ".mojo")
    exe = os.path.join(tmpdir, name)
    with open(src, "w") as f:
        f.write(source)
    b = subprocess.run([sys.executable, FIRE, "build", "--formal", "--no-prove",
                        "-o", exe, src], capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    check(b.returncode == 0,
          f"build failed: {(b.stderr or b.stdout).strip()[-300:]}")
    r = subprocess.run([exe], capture_output=True, text=True, timeout=120)
    dis = subprocess.run(["otool", "-tv", exe], capture_output=True,
                         text=True).stdout
    return r.returncode, dis, r.stdout


def mnemonics(dis):
    out = []
    for line in dis.splitlines():
        m = re.match(r"^[0-9a-f]{8,}\t+([a-z][a-z0-9.]*)", line)
        if m:
            out.append(m.group(1))
    return out


# ── CSEL: a conditional EXPRESSION should not be a branch ────────────────
CSEL_CASES = [
    ("csel_ternary_true", "def f(n):\n    c = 5\n    return 10 if c else 20\n",
     10, ("csel",)),
    ("csel_ternary_false", "def f(n):\n    c = 0\n    return 10 if c else 20\n",
     20, ("csel",)),
    # Python tests the condition for TRUTHINESS, so a negative non-zero must
    # still take the `then` arm. A `eq`-based CSEL gets this wrong.
    ("csel_truthiness", "def f(n):\n    c = 0 - 7\n    return 10 if c else 20\n",
     10, ("csel",)),
    ("csel_nested", "def f(n):\n    a = 1\n    return 5 if a else (7 if a else 9)\n",
     5, ("csel",)),
    ("csel_arith_arms", "def f(n):\n    c = n - 4\n    return n * 2 if c > 0 "
     "else n * 3\n", 20, ("csel",)),
    # Short-circuit as a value: `or` keeps a truthy left, `and` keeps a
    # truthy RIGHT. These two are one instruction apart and it is very easy to
    # swap them — `5 and 9` returning 5 compiles, runs and is wrong.
    ("csel_or_left", "def f(n):\n    a = 5\n    return a or 9\n", 5, ("csel",)),
    ("csel_or_right", "def f(n):\n    a = 0\n    return a or 9\n", 9, ("csel",)),
    ("csel_and_right", "def f(n):\n    a = 5\n    return a and 9\n", 9, ("csel",)),
    ("csel_and_left", "def f(n):\n    a = 0\n    return a and 9\n", 0, ("csel",)),
    ("csel_or_chained", "def f(n):\n    a = 0\n    b = 0\n    return a or 0 or 6\n",
     6, ("csel",)),
    ("csel_and_chained", "def f(n):\n    a = 3\n    b = 4\n    return a and b and 6\n",
     6, ("csel",)),
]

# Cases that MUST NOT take the branchless path, because CSEL evaluates both
# arms. Each one would print if the discarded arm ran.
KEEP_BRANCHING = [
    ("impure_else_not_run",
     'def f(n):\n    return 1 if n > 0 else boom()\n'
     'def boom():\n    printf("BOOM")\n    return 0\n', 1, "BOOM"),
    ("impure_or_not_run",
     'def f(n):\n    a = 1\n    return a or boom()\n'
     'def boom():\n    printf("BOOM")\n    return 0\n', 1, "BOOM"),
    ("impure_and_not_run",
     'def f(n):\n    a = 0\n    return a and boom()\n'
     'def boom():\n    printf("BOOM")\n    return 0\n', 0, "BOOM"),
]


# B.cond: a comparison should branch on the FLAGS, not materialise a boolean
# into a register for the very next instruction to read back.
BCOND_CASES = [
    ("bcond_if_true", "def f(n):\n    a = 3\n    b = 9\n    if a < b:\n"
     "        return 1\n    return 0\n", 1),
    # The case that hung: a FALSE comparison. Before the displacement was
    # patched, this spun on `b.ls <itself>` forever.
    ("bcond_if_false", "def f(n):\n    a = 3\n    b = 9\n    if a > b:\n"
     "        return 1\n    return 0\n", 0),
    ("bcond_elif", "def f(n):\n    a = 5\n    if a > 9:\n        return 1\n"
     "    elif a > 3:\n        return 2\n    return 0\n", 2),
    ("bcond_while", "def f(n):\n    a = 1\n    b = 5\n    c = 0\n"
     "    while a < b:\n        c = c + a\n        a = a + 1\n    return c\n", 10),
    ("bcond_for_range", "def f(n):\n    s = 0\n    for i in range(3, 9):\n"
     "        s = s + i\n    return s\n", 33),
    # An impure arm keeps the branch (CSEL would evaluate both).
    ("bcond_ternary", "def f(n):\n    a = 3\n    b = 9\n"
     "    return 1 if a < b else boom()\n"
     "def boom():\n    printf(\"BOOM\")\n    return 0\n", 1),
    ("bcond_compr", "def f(n):\n    a = 3\n    r = [x for x in range(5) if x > a]\n"
     "    return len(r)\n", 1),
    # A call condition genuinely needs a value, so it must NOT become a
    # B.cond off the flags -- there are no flags to read.
    ("bcond_call_still_cset", "def f(n):\n    if side(1):\n        return 5\n"
     "    return 0\ndef side(v):\n    return v\n", 5),
]


# TBZ / TBNZ: `if x & (1 << n):` is ONE instruction, and the two largest
# genuinely-uncovered entries in `tools/arm64_insn_audit.py`'s 200-binary
# instruction mix (49,645 TBNZ + 25,037 TBZ).
#
# The encoder existed and was byte-exact against `as` throughout, which is
# exactly why these are HERE and not in `test_arm64_encoders.py`: an encoder
# nothing calls is a decoder test with extra steps. And the first version of
# this wiring produced a program that BUILT, RAN and printed `0 0` where the
# source says `1 0`, because `Assembler.resolve()` had no TBZ/TBNZ arm and kept
# imm14 = 0 — and then the arm it got preserved the wrong bits and tested bit 0.
# Both are invisible to a byte comparison, which is the lesson in
# `bugs/FORMAL_arm64_instruction_coverage.md` §"Comparing instruction bytes is
# not comparing instructions"; the value assertion below is what caught them
# and the self-branch assertion is what would have caught the first.
TBZ_CASES = [
    # (name, source, expected exit, expected mnemonic, expected bit)
    #
    # The plain shape, and the bit number is the whole content of the
    # instruction: `40 & 8` sets bit 3.
    ("tbz_bit3_set", "def f(n):\n    x = 40\n    if x & 8:\n        return 1\n"
     "    return 0\n", 1, "tbz", 3),
    # The same bit clear, so the BRANCH is taken and the fallthrough is not —
    # the direction that has to be right for the other answer to be.
    ("tbz_bit3_clear", "def f(n):\n    x = 32\n    if x & 8:\n        return 1\n"
     "    return 0\n", 0, "tbz", 3),
    ("tbz_bit0", "def f(n):\n    x = 7\n    if x & 1:\n        return 1\n"
     "    return 0\n", 1, "tbz", 0),
    ("tbz_bit31", "def f(n):\n    x = 2147483648\n    if x & (1 << 31):\n"
     "        return 1\n    return 0\n", 1, "tbz", 31),
    # The `not` spelling is the OTHER instruction and not another way to
    # spell this one: the condition holds when the bit is clear, so the branch
    # that leaves it is taken when the bit is set. `40 & 8` is set, so `not`
    # is FALSE and this returns 0 — the answer a TBZ here would invert.
    ("tbnz_negated_bit_test", "def f(n):\n    x = 40\n    if not (x & 8):\n"
     "        return 1\n    return 0\n", 0, "tbnz", 3),
    ("tbnz_negated_bit_test_bit_clear",
     "def f(n):\n    x = 32\n    if not (x & 8):\n        return 1\n"
     "    return 0\n", 1, "tbnz", 3),
    # `&` is commutative in Python and a reader writes both orders.
    ("tbz_mask_on_the_left", "def f(n):\n    x = 40\n    if 8 & x:\n"
     "        return 1\n    return 0\n", 1, "tbz", 3),
    # A LOOP test, which is a different caller and a different block shape, and
    # it has to run MORE THAN ONCE: the branch is the loop's back edge and a
    # loop that leaves on its first iteration cannot tell a patched displacement
    # from an unpatched one at all. 8 is `255` counting down to `248`, which is
    # the first value with bit 3 clear — `x - 8` would clear the bit itself and
    # stop after one turn, so the decrement is by ONE on purpose.
    ("tbz_while_loop",
     "def f(n):\n    x = 255\n    k = 0\n    while x & 8:\n        x = x - 1\n"
     "        k = k + 1\n    return k\n", 8, "tbz", 3),
]

# The four shapes that must NOT become a bit test, each with the reason it is
# not one. Every case here prints the answer the general path gives, so a
# recogniser that reached for them would be caught by the VALUE even when the
# mnemonic check below passes.
KEEP_THE_MASK = [
    # NOT a single bit: `x & 255` asks whether ANY of eight bits is set, and a
    # TBZ would answer for one of them. `40 & 255` is 40, so the answer is 1.
    ("mask_is_not_a_power_of_two",
     "def f(n):\n    x = 40\n    if x & 255:\n        return 1\n"
     "    return 0\n", 1, 0),
    # Bit 40: the b40 form relocates imm14 and `encode_tbz_xn_bit` REFUSES a
    # bit >= 32 rather than encode it from memory of the spec. The general
    # path is a correct AND, which is the point of declining rather than
    # guessing.
    ("bit_above_31",
     "def f(n):\n    x = 40\n    if x & (1 << 40):\n        return 1\n"
     "    return 0\n", 0, 0),
    # The operand needs a CALL, so it is not a word this emitter can put in a
    # register on its own.
    ("operand_needs_a_call",
     "def f(n):\n    x = 0\n    if side(8) & x:\n        return 1\n"
     "    return 0\ndef side(v):\n    return v\n", 0, 0),
    # The comparison arm is not a comparison: `x == 8` must keep its CMP.
    ("not_a_bitwise_and",
     "def f(n):\n    x = 8\n    if x == 8:\n        return 1\n"
     "    return 0\n", 1, 0),
]


def self_branching(dis):
    """Addresses of branches whose displacement resolves to themselves.

    `otool -tv` prints `ADDR<TAB>MNEMONIC<TAB>TARGET` for anything with a
    branch target, so a self-branch is visible directly in the disassembly.
    """
    out = []
    for line in dis.splitlines():
        m = re.match(r"^([0-9a-f]{8,})\t+([a-z][a-z0-9.]*)\s+0x([0-9a-f]+)$",
                     line)
        if m and m.group(1) == m.group(3).lstrip("0").rjust(len(m.group(1)), "0"):
            out.append((m.group(1), m.group(2)))
        elif m and int(m.group(1), 16) == int(m.group(3), 16):
            out.append((m.group(1), m.group(2)))
    return out


def test_bcond_emitted_and_patched(tmpdir, verbose):
    for name, src, want_exit in BCOND_CASES:
        code, dis, out = build_and_run(src, tmpdir, name)
        check(code == want_exit,
              f"{name}: returned {code}, expected {want_exit}")
        ms = mnemonics(dis)
        if name != "bcond_call_still_cset":
            check(any(m.startswith("b.") and m != "b" for m in ms),
                  f"{name}: no B.cond in {ms}")
        # The check the encoder tests cannot make: they compare the four
        # instruction BYTES against `as`, which says nothing about the
        # displacement. `resolve()` had no B.cond case, so imm19 stayed 0 and
        # the branch pointed at itself -- a one-instruction infinite loop.
        bad = self_branching(dis)
        check(not bad,
              f"{name}: branch resolves to its own address: {bad}")


def test_csel_emitted_and_correct(tmpdir, verbose):
    for name, src, want_exit, want_mn in CSEL_CASES:
        code, dis, out = build_and_run(src, tmpdir, name)
        check(code == want_exit,
              f"{name}: returned {code}, expected {want_exit}")
        ms = mnemonics(dis)
        for want in want_mn:
            check(any(m == want or m.startswith(want) for m in ms),
                  f"{name}: expected {want} to be emitted, got {sorted(set(ms))}"
                  f" — the encoder is correct but nothing calls it, which is "
                  f"the whole failure this file exists to catch")
        if verbose:
            print(f"  ok   {name} (exit {code}, {len(ms)} instructions)")


def test_impure_arms_still_branch(tmpdir, verbose):
    """CSEL evaluates both arms, so an arm that can be OBSERVED must keep the
    branch. Each case has a discarded arm that prints; if the output contains
    the marker, the purity guard let it through and the program's observable
    behaviour changed."""
    for name, src, want_exit, marker in KEEP_BRANCHING:
        code, dis, out = build_and_run(src, tmpdir, name)
        check(code == want_exit,
              f"{name}: returned {code}, expected {want_exit}")
        check(marker not in out,
              f"{name}: the DISCARDED arm ran and printed {marker!r} — "
              f"stdout={out!r}. CSEL computes both arms, so anything "
              f"observable has to keep the short-circuiting branch.")
        check(not any(m == "csel" for m in mnemonics(dis)),
              f"{name}: took the branchless path despite an impure arm")
        if verbose:
            print(f"  ok   {name} (exit {code}, still branches)")


def test_spills_use_unscaled_access(tmpdir, verbose):
    """A spill slot is a fixed displacement from the frame pointer, which is
    precisely what LDUR/STUR are for: one instruction where the general path
    spent three (materialise the address in X17, subtract, then access [X17]).
    Only offsets the 9-bit unscaled field can hold take the short path, so a
    frame too large for it must still be correct rather than truncated."""
    body = "".join(f"    v{i} = {i}\n" for i in range(14))
    total = "+".join(f"v{i}" for i in range(14))
    src = f"def f(n):\n{body}    return {total}\n"
    code, dis, _ = build_and_run(src, tmpdir, "spill_ldur")
    check(code == sum(range(14)),
          f"spilled locals computed {code}, expected {sum(range(14))}")
    ms = mnemonics(dis)
    check(any(m.startswith("ldur") or m.startswith("stur") for m in ms),
          f"expected ldur/stur for frame-pointer-relative spills, got "
          f"{sorted(set(ms))}")
    if verbose:
        print(f"  ok   spill_ldur (exit {code}, ldur/stur present)")


def test_simple_operands_avoid_the_stack(tmpdir, verbose):
    """When the arms are plain locals, CSEL must not touch the stack.

    A load does not write the flags, so both arms can be materialised after
    the compare and nothing needs saving. The general form still spills,
    because evaluating an arm clobbers the flags — but for `x = a if c else b`
    with local arms, which is the common shape, that spill is pure overhead.

    This also pins WHICH registers hold what: an earlier version of the fast
    path read X0 as the "then" operand after X0 had already been overwritten
    with the else arm, which compiles, runs, and returns the other value.
    Asserting the absence of stp/ldp is what makes the fast path a path at
    all rather than an accident."""
    src = ("def f(n):\n    a = 3\n    b = 4\n"
           "    x = a if a > 0 else b\n"
           "    return x\n")
    code, dis, _ = build_and_run(src, tmpdir, "csel_nostack")
    check(code == 3, f"returned {code}, expected 3")
    ms = mnemonics(dis)
    check(any(m == "csel" for m in ms), f"no csel emitted: {sorted(set(ms))}")
    # No push/pop AROUND THE CSEL. Not "no stp anywhere": the prologue and
    # epilogue save the frame pointer and the callee-saved pairs, so those are
    # always present and have nothing to do with the conditional.
    idx = ms.index("csel")
    around = ms[max(0, idx - 5):idx]
    check(not any(m in ("stp", "ldp") for m in around),
          f"the CSEL still spills its operands: {around} immediately before "
          f"the csel")
    if verbose:
        print(f"  ok   csel_nostack (exit {code}, no stack)")


def test_tbz_emitted_and_correct(tmpdir, verbose):
    for name, src, want_exit, want_mn, want_bit in TBZ_CASES:
        code, dis, _ = build_and_run(src, tmpdir, name)
        check(code == want_exit,
              f"{name}: returned {code}, expected {want_exit}")
        ms = mnemonics(dis)
        check(any(m == want_mn for m in ms),
              f"{name}: expected {want_mn} to be emitted, got "
              f"{sorted(set(ms))} — the encoder is correct but nothing calls "
              f"it, which is the whole failure this file exists to catch")
        # The BIT, read out of the disassembly rather than the instruction
        # count. The first version of this wiring printed `0 0` where the
        # source says `1 0` because `Assembler.resolve()` preserved the wrong
        # bits and every test became `tbz w0, #0` — a program that builds, runs
        # and is wrong, with a TBZ in it.
        bits = set()
        for line in dis.splitlines():
            m = re.search(rf"\b{want_mn}\s+w\d+,\s+#(0x[0-9a-f]+|\d+)", line)
            if m:
                bits.add(int(m.group(1), 0))
        check(bits == {want_bit},
              f"{name}: the disassembly tests bits {sorted(bits)}, expected "
              f"{{{want_bit}}} — a {want_mn.upper()} that reads the wrong bit "
              f"is a wrong answer that still looks like one")
        # …and the displacement, which is the half no byte comparison sees.
        bad = self_branching(dis)
        check(not bad,
              f"{name}: branch resolves to its own address: {bad}")
        if verbose:
            print(f"  ok   {name} (exit {code}, {want_mn} bit {want_bit})")


def test_a_mask_that_is_not_one_bit_keeps_the_general_path(tmpdir, verbose):
    """`want_bit` is 0 for every row here, which means "no TBZ in the image".

    That is the direction that would REFUSE real programs if the recogniser
    were too eager: `x & 255` is eight bits, bit 40 is a form the encoder
    declines, and `side(8) & x` has no word to test. All four still have to
    print the right answer, which is what says the general path is intact
    rather than merely bypassed.
    """
    for name, src, want_exit, want_bit in KEEP_THE_MASK:
        code, dis, _ = build_and_run(src, tmpdir, name)
        check(code == want_exit,
              f"{name}: returned {code}, expected {want_exit} — the general "
              f"path has to keep answering this shape")
        ms = mnemonics(dis)
        check(not any(m.startswith(("tbz", "tbnz")) for m in ms),
              f"{name}: took the bit-test path for a shape that is not a "
              f"single-bit test: {sorted(set(ms))}")
        if verbose:
            print(f"  ok   {name} (exit {code}, no tbz)")


TESTS = [
    ("B.cond is emitted, correct, and its displacement is patched",
     test_bcond_emitted_and_patched),
    ("CSEL is emitted and computes the right value",
     test_csel_emitted_and_correct),
    ("TBZ is emitted, tests the right bit, and its displacement is patched",
     test_tbz_emitted_and_correct),
    ("a mask that is not one bit keeps the general path",
     test_a_mask_that_is_not_one_bit_keeps_the_general_path),
    ("simple CSEL operands avoid the stack",
     test_simple_operands_avoid_the_stack),
    ("spills use unscaled frame-relative access",
     test_spills_use_unscaled_access),
    ("an observable arm keeps the short-circuiting branch",
     test_impure_arms_still_branch),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal arm64 output needs an arm64 host, this is "
              f"{platform.machine()}")
        return 0

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, fn in TESTS:
            try:
                fn(tmpdir, args.verbose)
            except TestFailure as e:
                failed += 1
                print(f"  FAIL  {name}\n        {e}")
                continue
            except Exception as e:
                failed += 1
                print(f"  ERROR {name}\n        {type(e).__name__}: {e}")
                if args.verbose:
                    import traceback
                    traceback.print_exc()
                continue
            passed += 1
            print(f"  PASS  {name}")

    print(f"\narm64 emission: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
