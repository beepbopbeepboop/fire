#!/usr/bin/env python3
"""x86-64 PARITY: constructs arm64 lowers that x86-64 refused, checked on BOTH.

Every case here is one the two architectures used to answer differently about:
arm64 built it and ran it, x86-64 refused the source, or the reverse.  That
divergence is the defect this file exists to keep closed, and it is why each
case is checked on both backends rather than on the host's: a one-sided
assertion stays green through the whole class, because the backend under test
is the one that changed.

Three properties per case, and the third is the one that makes the other two
worth anything:

  1. arm64 builds it and its output matches CPython's;
  2. x86-64 builds it and its output matches CPython's;
  3. the expected output is whatever CPython prints for the same computation,
     run here, at test time — not a constant written by the person who wrote
     the lowering.  A constant is an assertion about a lowering made against
     itself, and a program that computes the right number for the wrong reason
     passes it.

`REFUSALS` are the other direction: a construct neither machine may lower, and
both must say so with the SAME words.  A construct that is genuinely absent
from the value model is better refused than emitted, and "one architecture
crashes and the other declines" is the shape that must not survive.

The first construct here is the read-modify-write through a subscript
(`q[0] += 5`), which arm64 had as `_emit_subscript_aug` and x86-64 refused
outright — bugs/FORMAL_x86_64_augmented_assignment_through_a_subscript_is_refused.md.
The refusal beside it is the same construct over a list of strings, where both
backends used to reach the integer ALU with two `char *` operands.

    python3 test_formal_x86_64_parity.py [-v] [--list]
"""

import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 600
RUN_TIMEOUT = 120
BACKENDS = ("arm64", "x86_64")


# (name, mojo source, cpython source).  The two are the same program; the
# CPython one exists so the expectation is computed rather than asserted.
#
# `Pointer` is spelled and annotated because the pointee WIDTH is what the
# read-modify-write has to agree with: `q[0] += 5` on `Pointer[Int32]` is
# 8-byte-granular arithmetic on a 4-byte element, and a lowering that forgets
# the width writes three bytes of a neighbour.
CASES = [
    ("aug_through_int32_pointer",
     "def main():\n"
     "    var q: Pointer[Int32] = malloc(16)\n"
     "    q[0] = 10\n"
     "    q[0] += 5\n"
     "    q[1] = 3\n"
     "    q[1] *= 7\n"
     "    printf(\"a=%d b=%d\", q[0], q[1])\n"
     "    return 0\n",
     "import ctypes\nimport sys\n"
     "# `create_string_buffer`, not `CDLL('libc').malloc`: ctypes's\n"
     "# default restype is `c_int`, which TRUNCATES a 64-bit malloc\n"
     "# result, so the oracle itself segfaults before it computes\n"
     "# anything — a reference that cannot run asserts nothing.\n"
     "_buf = ctypes.create_string_buffer(64)\n"
     "def main():\n"
     "    q = ctypes.cast(_buf, ctypes.POINTER(ctypes.c_int32))\n"
     "    q[0] = 10\n"
     "    q[0] += 5\n"
     "    q[1] = 3\n"
     "    q[1] *= 7\n"
     "    sys.stdout.write(\"a=%d b=%d\" % (q[0], q[1]))\n"
     "    return 0\n"),
    # Every operator the shared table supports, on one buffer, so a table that
    # loses a row shows up as a refusal naming it rather than as a program that
    # quietly stops being lowered.  `-` is the one with a left operand that is
    # NOT the accumulator: for `p[0] -= 3` the old element is the LEFT operand
    # and 3 the right, and reversing them is a different answer.
    ("aug_every_operator",
     "def main():\n"
     "    var p: Pointer[Int] = malloc(64)\n"
     "    p[0] = 100\n"
     "    p[0] -= 30\n"
     "    p[1] = 6\n"
     "    p[1] *= 7\n"
     "    p[2] = 0xF0\n"
     "    p[2] &= 0x3C\n"
     "    p[3] = 0xF0\n"
     "    p[3] |= 0x0F\n"
     "    p[4] = 0xFF\n"
     "    p[4] ^= 0x0F\n"
     "    p[5] = 1\n"
     "    p[5] <<= 4\n"
     "    p[6] = 256\n"
     "    p[6] >>= 3\n"
     "    printf(\"%d %d %d\", p[0], p[1], p[2])\n"
     "    printf(\" %d %d %d\", p[3], p[4], p[5])\n"
     "    printf(\" %d\", p[6])\n"
     "    return 0\n",
     "import ctypes\nimport sys\n"
     "# `create_string_buffer`, not `CDLL('libc').malloc`: ctypes's\n"
     "# default restype is `c_int`, which TRUNCATES a 64-bit malloc\n"
     "# result, so the oracle itself segfaults before it computes\n"
     "# anything — a reference that cannot run asserts nothing.\n"
     "_buf = ctypes.create_string_buffer(64)\n"
     "def main():\n"
     "    p = ctypes.cast(_buf, ctypes.POINTER(ctypes.c_int64))\n"
     "    p[0] = 100; p[0] -= 30\n"
     "    p[1] = 6;   p[1] *= 7\n"
     "    p[2] = 0xF0; p[2] &= 0x3C\n"
     "    p[3] = 0xF0; p[3] |= 0x0F\n"
     "    p[4] = 0xFF; p[4] ^= 0x0F\n"
     "    p[5] = 1;   p[5] <<= 4\n"
     "    p[6] = 256; p[6] >>= 3\n"
     "    sys.stdout.write(\"%d %d %d %d %d %d %d\" % tuple(p[i] for i in range(7)))\n"
     "    return 0\n"),
    # The same seven values JOINED, read back through the pointer rather than
    # through the names above, because the case that found the real bug in the
    # first lowering of this construct read the element back and saw an
    # ADDRESS: `mov [rax], rax` stores the element's own pointer into the
    # element, which is invisible to a case that only checks the arithmetic
    # happened and shows up the moment anything reads the buffer afterwards.
    # The values are printed from a SECOND buffer walk, so the store's target
    # and the store's value are separately observable.
    # A ONE-BYTE element. `UInt8` is the case where the load and the store have
    # to agree on the width: a 64-bit store into a one-byte element overwrites
    # the seven bytes after it, which on a `malloc`'d buffer is a silent
    # corruption and not a fault, so the value of the NEXT element is the
    # evidence.
    ("aug_through_byte_pointer",
     "def main():\n"
     "    var p: Pointer[UInt8] = malloc(8)\n"
     "    p[0] = 200\n"
     "    p[0] += 55\n"
     "    p[1] = 9\n"
     "    printf(\"a=%d b=%d\", p[0], p[1])\n"
     "    return 0\n",
     "import ctypes\nimport sys\n"
     "# `create_string_buffer`, not `CDLL('libc').malloc`: ctypes's\n"
     "# default restype is `c_int`, which TRUNCATES a 64-bit malloc\n"
     "# result, so the oracle itself segfaults before it computes\n"
     "# anything — a reference that cannot run asserts nothing.\n"
     "_buf = ctypes.create_string_buffer(64)\n"
     "def main():\n"
     "    p = ctypes.cast(_buf, ctypes.POINTER(ctypes.c_uint8))\n"
     "    p[0] = 200; p[0] += 55\n"
     "    p[1] = 9\n"
     "    sys.stdout.write(\"a=%d b=%d\" % (p[0], p[1]))\n"
     "    return 0\n"),
    # A LIST element, so the address computation under test is the bounds-
    # checked blob walk rather than `base + i*width`, and so a negative index
    # (which wraps like Python before the bound is checked) is exercised
    # through the read-modify-write rather than only through a read.
    ("aug_through_list_element",
     "import sys\n\n"
     "def main():\n"
     "    var a = [10, 20, 30]\n"
     "    a[1] += 5\n"
     "    a[-1] *= 2\n"
     "    printf(\"%d %d %d\", a[0], a[1], a[2])\n"
     "    return 0\n",
     "import sys\n\n"
     "def main():\n"
     "    a = [10, 20, 30]\n"
     "    a[1] += 5\n"
     "    a[-1] *= 2\n"
     "    sys.stdout.write(\"%d %d %d\" % (a[0], a[1], a[2]))\n"
     "    return 0\n"),
    # The index is a CALL, so the address has to be computed ONCE. Re-evaluating
    # it for the write would read and write two different elements of a list the
    # call in between could have changed, which is the whole reason this shape is
    # a separate emitter rather than the plain-name one with a different store.
    ("aug_index_is_a_call",
     "import sys\n\ndef bump():\n"
     "    return 1\n"
     "\n"
     "def main():\n"
     "    var a = [10, 20, 30]\n"
     "    a[bump()] += 100\n"
     "    printf(\"%d %d %d\", a[0], a[1], a[2])\n"
     "    return 0\n",
     "import sys\n\ndef bump():\n"
     "    return 1\n"
     "\n"
     "def main():\n"
     "    a = [10, 20, 30]\n"
     "    a[bump()] += 100\n"
     "    sys.stdout.write(\"%d %d %d\" % (a[0], a[1], a[2]))\n"
     "    return 0\n"),
    # THE AUGMENTED FORM OF THE FOUR OPERATORS THE ALU TABLE CANNOT EXPRESS.
    # `/` `//` `%` are a ONE-operand instruction whose zero arm is a trap and
    # `**` is an unroller, so `_ALU_RR` holds none of them and neither does the
    # shift table. arm64's `_emit_aug_assign` has always routed all four to the
    # same two helpers its binary form uses (`_emit_div_shift_pow`); x86-64's
    # twin had no such route, so `x /= 2`, `x //= 2`, `x %= 2` and `x **= 2`
    # were REFUSED by name on this backend while arm64 built and ran them — four
    # spellings of one construct, and a two-architecture disagreement about
    # ordinary Python that nothing here could see, because every other case in
    # this file reached the operator through a pointer or a list element rather
    # than through a name.
    #
    # All four in one program, because a delegation that added `/=` and stopped
    # there would pass a program that used only `/=`.
    ("aug_division_and_power_on_a_name",
     "def main():\n"
     "    a = 20\n"
     "    a //= 3\n"
     "    b = 20\n"
     "    b %= 6\n"
     "    c = 3\n"
     "    c **= 3\n"
     "    d = 20\n"
     "    d /= 4\n"
     "    printf(\"%d %d %d %d\", a, b, c, d)\n"
     "    return 0\n",
     "import sys\n\ndef main():\n"
     "    a = 20; a //= 3\n"
     "    b = 20; b %= 6\n"
     "    c = 3;  c **= 3\n"
     "    d = 20; d /= 4\n"
     "    sys.stdout.write(\"%d %d %d %d\" % (a, b, c, d))\n"
     "    return 0\n"),
    # `**` WITH AN EXPONENT ABOVE TWO, in the BINARY form, because the fix above
    # is a delegation and a delegation can carry a wrong answer with it:
    # x86-64's `_emit_pow` unrolled a small literal exponent by copying the
    # accumulator into R11 and popping that same accumulator back into RAX, so
    # both registers held one word and every step computed `acc * acc`. The
    # answer was `base ** (2 ** (lit - 1))` — `3 ** 3` answered 81 where the
    # source says 27, and `3 ** 8` answered 3**128 — built, ran, and disagreed
    # with arm64, with the whole suite green throughout because exponent 2 is
    # the one value a squaring gets right and it was the only exponent anything
    # tested.
    #
    # Exponents 3, 4, 5, 8 and 8 over a second base, so a fix that repaired the
    # first iteration of the unroll and left the rest answers 81 where the source
    # says 27. The last two are the same exponent over two bases because the
    # squaring is wrong by a different factor in each, and a base of 1 or 0 hides
    # it entirely — so neither appears here.
    ("literal_power_above_two",
     "def main():\n"
     "    printf(\"%d %d %d %d %d\", 3 ** 3, 3 ** 4, 3 ** 5, 2 ** 8, 3 ** 8)\n"
     "    return 0\n",
     "import sys\n\ndef main():\n"
     "    sys.stdout.write(\"%d %d %d %d %d\" % (3 ** 3, 3 ** 4, 3 ** 5,\n"
     "                                            2 ** 8, 3 ** 8))\n"
     "    return 0\n"),
    # THE SAME DELEGATION THROUGH A FRAME SLOT, which is a different route and
    # not a variation: a plain name loads and stores a local, while `self.x`
    # goes through `_member_slot_key` into the frame's slot array, and
    # `_emit_div_mod`/`_emit_pow` reach the target through `_emit_expr` /
    # `_store_var` rather than through the local path.  A delegation that named
    # the target correctly but stored it as a local would compute 101 and keep
    # it in a register, and the case above — which reads a name — would still
    # pass.
    #
    # TWO fields on purpose.  A one-field struct's receiver IS its field rather
    # than a frame address (`bugs/FORMAL_method_param_field_access.md`), and on
    # this backend a field stored by a zero-argument `__init__` of a one-field
    # struct reads back as 0
    # (`bugs/FORMAL_one_field_struct_field_stored_in_a_zero_arg_init_reads_as_zero.md`),
    # so a one-field spelling of this case would be measuring that bug and not
    # this construct.
    ("aug_division_through_a_frame_slot",
     "class Pair:\n"
     "    def __init__(self):\n"
     "        self.n = 20\n"
     "        self.m = 3\n"
     "\n"
     "    def shrink(self):\n"
     "        self.n //= 2\n"
     "        self.m %= 2\n"
     "        return self.n * 10 + self.m\n"
     "\n"
     "def main():\n"
     "    var p = Pair()\n"
     "    printf(\"%d\", p.shrink())\n"
     "    return 0\n",
     "import sys\n\nclass Pair:\n"
     "    def __init__(self):\n"
     "        self.n = 20\n"
     "        self.m = 3\n"
     "\n"
     "    def shrink(self):\n"
     "        self.n //= 2\n"
     "        self.m %= 2\n"
     "        return self.n * 10 + self.m\n"
     "\n"
     "def main():\n"
     "    p = Pair()\n"
     "    sys.stdout.write(\"%d\" % p.shrink())\n"
     "    return 0\n"),
]


# A construct NEITHER machine may lower, and both must refuse it with the same
# words: a `+=` whose element and whose value are both `char *` is integer
# arithmetic on two addresses.  arm64's subscript-augmented path reached the
# ALU without asking, so `a[0] += "x"` over a list of strings BUILT there and
# printed the length of a pointer sum; x86-64 refused.  One architecture
# answering and the other declining is the shape this file exists to end, and
# the check is `refuse:`-shaped for the same reason `test_formal_run.py`'s are:
# nothing about the program's OUTPUT can carry the assertion, because the
# assertion is that it must not have one.
REFUSALS = [
    ("aug_on_two_strings_refused_identically",
     "def main():\n"
     "    var a = [\"ab\", \"cd\"]\n"
     "    a[0] += \"x\"\n"
     "    printf(\"%d\\n\", len(a[0]))\n"
     "    return 0\n",
     "'+=' on two strings is refused"),
]


def build(src, out, backend):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out, src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run(path, backend, timeout=RUN_TIMEOUT):
    """Execute a built image, under Rosetta 2 when it is an x86-64 one.

    The x86-64 backend's whole subject is an image that RUNS, so a case that
    quietly stopped running — because the host cannot execute it — would pass
    every assertion that only compared build output.  `arch -x86_64` is what
    makes that a failure rather than a skip.

    Selected by the BACKEND rather than applied to whatever was built: on an
    arm64 host `arch -x86_64 <an arm64 image>` is "Bad CPU type in executable",
    which is a failure that reads as the host's fault and is really the harness
    asking the wrong machine to run the program.
    """
    argv = [path]
    if (backend == "x86_64" and platform.machine() in ("arm64", "aarch64")
            and sys.platform == "darwin"):
        argv = ["arch", "-x86_64", path]
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def cpython_answer(source, tmpdir, name):
    """CPython's stdout and exit status for `source` + `main()`, run now."""
    py = os.path.join(tmpdir, name + ".ref.py")
    with open(py, "w") as f:
        f.write(source + "\nmain()\n")
    ref = subprocess.run([sys.executable, py], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    return ref.returncode, ref.stdout


def run_case(name, mojo_src, cpython_src, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(mojo_src)
    want_exit, want_out = cpython_answer(cpython_src, tmpdir, name)
    if want_exit != 0:
        return False, (f"the CPython reference itself failed (exit "
                       f"{want_exit}); a case whose oracle does not run asserts "
                       f"nothing")
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(src, out, backend)
        if rc != 0:
            return False, f"--backend={backend} did not build: {text.strip()[-300:]}"
        if not os.path.isfile(out):
            return False, f"--backend={backend} reported success, wrote no binary"
        r = run(out, backend)
        if r.returncode != want_exit:
            return False, (f"--backend={backend} exited {r.returncode}, CPython "
                           f"exits {want_exit}; stderr: {r.stderr.strip()[:160]}")
        if r.stdout != want_out:
            return False, (f"--backend={backend} printed {r.stdout[:120]!r}, "
                           f"CPython prints {want_out[:120]!r}")
        if verbose:
            print(f"      {backend}: {r.stdout[:60]!r} exit={r.returncode}")
    return True, ""


def run_refusal(name, mojo_src, needle, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(mojo_src)
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(src, out, backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a construct that has no "
                           f"representation (expected a refusal naming "
                           f"{needle!r}) — the binary is the real answer here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not with the "
                           f"expected words {needle!r}: {text.strip()[-300:]}")
    if verbose:
        print(f"      refused identically on arm64 and x86-64: {needle!r}")
    return True, ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--list", action="store_true", help="list the cases and exit")
    ap.add_argument("cases", nargs="*", help="run only these cases")
    args = ap.parse_args()

    if args.list:
        for name, _s, _c in CASES:
            print(f"  case    {name}")
        for name, _s, needle in REFUSALS:
            print(f"  refusal {name}  ({needle!r})")
        return 0

    known = {c[0] for c in CASES} | {c[0] for c in REFUSALS}
    wanted = [(c, False) for c in CASES] + [(c, True) for c in REFUSALS]
    if args.cases:
        missing = set(args.cases) - known
        if missing:
            print(f"ERROR: unknown case(s): {sorted(missing)}", file=sys.stderr)
            return 2
        wanted = [c for c in wanted if c[0][0] in args.cases]

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for (name, mojo_src, third), is_refusal in wanted:
            try:
                if is_refusal:
                    ok, detail = run_refusal(name, mojo_src, third, tmpdir,
                                             args.verbose)
                else:
                    ok, detail = run_case(name, mojo_src, third, tmpdir,
                                          args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:                       # report, do not mask
                ok, detail = False, f"{type(e).__name__}: {e}"
                if args.verbose:
                    import traceback
                    traceback.print_exc()
            if ok:
                passed += 1
                print(f"  PASS  {name}")
            else:
                failed += 1
                print(f"  FAIL  {name}: {detail}")

    total = passed + failed
    print(f"\nx86-64 formal parity: PASS={passed} FAIL={failed} "
          f"({total} case{'s' if total != 1 else ''})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
