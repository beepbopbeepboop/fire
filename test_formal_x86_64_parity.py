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

`FAILING_CASES` are the third shape: a program every machine leaves through a
TRAP, so CPython raises too and its own stdout is the expectation.  Nothing
about a differential-against-CPython fuzzer can reach them (it records a
`generator-error` and never builds an image), and the property they pin is the
one that class cannot have: that an exit path leaves BEHIND what the program
printed.

The first construct here is the read-modify-write through a subscript
(`q[0] += 5`), which arm64 had as `_emit_subscript_aug` and x86-64 refused
outright — FORMAL_x86_64_augmented_assignment_through_a_subscript_is_refused.
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
    # `len` is on this list because the two architectures answered it the SAME
    # wrong way, which is the shape a one-backend fix would hide: `_emit_call`
    # special-cased `range` and treated every other callee as a known function
    # or an extern, and `len` matched neither, so it became a call to a libc
    # symbol that does not exist.  Both backends therefore returned whatever
    # the call left in the return register — measured, -6 for `len(range(10))`
    # on BOTH — and one architecture being right would have been as much a bug
    # as both being wrong.  (The 2026-09 x86-64 backend-gap survey named this
    # case; its doc is deleted with its fixes and this comment is the record.)
    #
    # Four operand shapes in one line, because the fix is not one rule and the
    # four are the four ways to be wrong about it:
    #
    #   * a `range` blob — the count field at offset 0;
    #   * a LIST literal and a list LOCAL — the same field, and the local is the
    #     one a fall-through reads through an unclassified word;
    #   * a string LOCAL — a bare `char *`, and its length is a COMPUTATION
    #     (`strlen`) rather than a field, because a NUL-terminated run has no
    #     count word.  Measured before the fix, on both architectures:
    #     1819043176 = 0x6C6C6568 = "hell" read little-endian;
    #   * a string that is a METHOD RESULT — `lstrip` yields an INTERIOR
    #     pointer, so this is the case that pins the scan to the NUL from
    #     wherever the pointer starts rather than from the original literal.
    #     Measured before the fix, on both: 536897896 = 0x20006869, "hi"
    #     followed by the two spaces that had just been trimmed.
    #
    # The empty string is here too, because a scan that forgets the terminator
    # walks off the end of the buffer, and 0 is the answer that says it did not.
    #
    # ONE printf of SEVEN values, which used to be two printfs of four and
    # three.  The split was this suite's own subject rather than taste — SysV
    # x86-64 passed six integer arguments in registers, so a seven-value
    # `printf` was refused on x86-64 and built on arm64, and a case that tripped
    # it would have reported that filing instead of this one
    # (`FORMAL_x86_64_argument_registers`, now deleted).  It is one call
    # again now that
    # both conventions have a stack area, and
    # `a_variadic_printf_with_an_argument_in_the_frame` below is the row that
    # says so.
    ("len_of_every_operand_shape",
     "def main():\n"
     "    m = \"hello\"\n"
     "    w = \"  hi\".lstrip()\n"
     "    e = \"\"\n"
     "    var xs = [1, 2, 3]\n"
     "    printf(\"%d %d %d %d %d %d %d\", len(m), len(w), len(e), len(xs),\n"
     "           len([1, 2, 3, 4]), len(range(10)), len([]))\n"
     "    return 0\n",
     "import sys\n\ndef main():\n"
     "    m = \"hello\"\n"
     "    w = \"  hi\".lstrip()\n"
     "    e = \"\"\n"
     "    xs = [1, 2, 3]\n"
     "    sys.stdout.write(\"%d %d %d %d %d %d %d\" % (\n"
     "        len(m), len(w), len(e), len(xs),\n"
     "        len([1, 2, 3, 4]), len(range(10)), len([])))\n"
     "    return 0\n"),
    # THE SAME TUPLE STORE INSIDE `__init__`, WHICH USED TO BE A REFUSAL AND IS
    # NOT ONE ANY MORE — it is in `CASES` because both backends now answer it
    # with CPython's answer, and this row was the reason the shared REFUSALS list
    # is shorter than it was.
    #
    # `h.x, h.y = p, q` outside a constructor reached a different pass from the
    # same SPELLING inside one, and the constructor-with-arguments inline needed
    # the body to BE a straight line of `self.<field> = …` stores.  A tuple
    # target is not, so it was refused — which was only correct while BOTH
    # machines said so, and x86-64 used to reach its own `_emit_tuple_assign` and
    # refuse with a different sentence ("tuple assignment targets must be plain
    # names on the formal x86-64 path").  Two architectures, two refusals, one
    # program.
    #
    # `_init_statement_field_stores` is what closed it: one table for the single
    # and the tuple target shape, so the inline performs the tuple store and
    # `CONSTRUCTION_INIT` carries it.  Measured after the merge:
    #
    #     CPython  't=7'
    #     arm64     exit=0 stdout='t=7'
    #     x86-64    exit=0 stdout='t=7'
    #
    # So the row is here rather than in REFUSALS, where it asserted a refusal
    # that no longer fires.  The construct it was filed for — the SPELLING being
    # two-architecture-specific — is still what this file is for; what changed is
    # that both machines now agree on the answer instead of on the refusal.
    ("tuple_target_in_a_constructor_body_answers_on_both",
     "class Tail:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x, self.y = p, q\n"
     "    def total(self):\n"
     "        return self.x + self.y\n"
     "def main(n):\n"
     "    var t = Tail(3, 4)\n"
     "    printf(\"t=%d\", t.total())\n"
     "    return 0\n",
     "import sys\n\nclass Tail:\n"
     "    def __init__(self, p, q):\n"
     "        self.x, self.y = p, q\n"
     "    def total(self):\n"
     "        return self.x + self.y\n\n"
     "def main():\n"
     "    t = Tail(3, 4)\n"
     "    sys.stdout.write(\"t=%d\" % t.total())\n"
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
     # A COMPUTED exponent, which is a different path and not a variation: the
     # case above is the unroll over a literal, and arm64's binary
     # exponentiation loop — the path every exponent that is not a literal in
     # `0..64` takes, and the one `**=` shares — answered 0 for every
     # non-negative exponent because both of its conditional branches tested a
     # CSET flag with the wrong sense (`CBZ` where the flag being ZERO is the
     # loop continuing), so every non-negative exponent took the negative exit
     # and every positive one left the loop on its first test.  The one defect
     # `test_formal_run.py`'s `run_case` could not see is that it builds the
     # HOST's architecture, which on this repository's CI is arm64 — the
     # architecture that was wrong.
     #
     # Exponents 1, 2 and 5 over two bases, because the loop halves the
     # exponent and 1 is the one value a `result = 1` seed that is never
     # multiplied cannot get right, and a base of 0 or 1 hides a wrong squaring
     # entirely.  `3 ** 5` is the one that needs two loop iterations, so a loop
     # that ran its body once and left would answer 3 where the source says 243.
     ("variable_exponent_power",
     "def main():\n"
     "    var n = 1\n"
     "    printf(\"%d \", 2 ** n)\n"
     "    n = 2\n"
     "    printf(\"%d \", 3 ** n)\n"
     "    n = 5\n"
     "    printf(\"%d %d \", 2 ** n, 3 ** n)\n"
     "    printf(\"%d\", 1 ** n)\n"
     "    return 0\n",
     "import sys\n\ndef main():\n"
     "    n = 1\n"
     "    out = \"%d \" % (2 ** n)\n"
     "    n = 2\n"
     "    out += \"%d \" % (3 ** n)\n"
     "    n = 5\n"
     "    out += \"%d %d \" % (2 ** n, 3 ** n)\n"
     "    out += \"%d\" % (1 ** n)\n"
     "    sys.stdout.write(out)\n"
     "    return 0\n"),
     # The exponent as a PARAMETER, which is the distinction this defect turns
     # on and a different route to the exponent than a local: a parameter is
     # read out of the caller's frame rather than out of a local's home, and a
     # `**=` writes the accumulator back through `_store_var` where the binary
     # form leaves it in a register.
("variable_exponent_through_a_parameter_and_an_augmented_power",
     "def power(k: Int) -> Int:\n"
     "    return 2 ** k\n"
     "def main():\n"
     "    var n = 4\n"
     "    var a = 2\n"
     "    a **= n\n"
     "    var b = 3\n"
     "    b **= n\n"
     "    printf(\"%d %d %d\", power(n), a, b)\n"
     "    return 0\n",
     "import sys\n\ndef main():\n"
     "    def power(k):\n"
     "        return 2 ** k\n"
     "    n = 4\n"
     "    a = 2\n"
     "    a **= n\n"
     "    b = 3\n"
     "    b **= n\n"
     "    sys.stdout.write(\"%d %d %d\" % (power(n), a, b))\n"
     "    return 0\n"),
    # A FLOATING CONVERSION, which is a whole ABI question and not a
    # rendering: SysV AMD64 hands a `double` to a variadic callee in XMM0..XMM7
    # and an integer in RDI..R9, out of two INDEPENDENT register files, so
    # `printf("%f", w)` read whatever XMM0 held — a denormal, and a different
    # one on each run of the same binary, because the register was never
    # written. arm64 needs nothing: AAPCS passes a double and an integer in
    # register number 0 both, which is why this was invisible from every suite
    # that builds one architecture.
    #
    # The values are the IEEE-754 BIT PATTERNS of doubles (`math.mojo`'s own
    # representation, and the module's docstring says why), and 17 digits is
    # the shortest round-tripping form, so CPython's `repr` and the C library's
    # `%.17g` produce the same text. The `1.0000000000000002` is deliberate: it
    # is the smallest double above 1.0 and its low 32 bits are 1, so a lowering
    # that truncated the word to 32 bits — which is what an unannotated integer
    # does on this path — would print `1.000000` and this row would still pass
    # on that conversion alone. The mixed rows are the other half and are the
    # reason this is not one `movq`: an SSE argument does not consume a GPR, so
    # `printf("%f %lld", d, n)` needs `n` in **RDI** rather than RSI, and a fix
    # that only moved the float would print `n` one register late.
    ("printf_float_operand_read_from_an_xmm_register",
     "def main():\n"
     "    var one = 4607182418800017409\n"
     "    var two = 4611686018427387904\n"
     "    var n = 12345\n"
     "    printf(\"%.17g %.17g\\n\", one, two)\n"
     "    printf(\"%f %d\\n\", one, n)\n"
     "    printf(\"%d %f %d %f\\n\", n, one, 99, two)\n"
     "    printf(\"%e %g\\n\", one, two)\n"
     "    printf(\"%d %d\\n\", n, 7)\n"
     "    return 0\n",
     "import sys\nimport struct\n\n"
     "def d(u):\n"
     "    return struct.unpack('<d', struct.pack('<Q', u))[0]\n\n"
     "def main():\n"
     "    one = 4607182418800017409\n"
     "    two = 4611686018427387904\n"
     "    n = 12345\n"
     "    sys.stdout.write(\"%.17g %.17g\\n\" % (d(one), d(two)))\n"
     "    sys.stdout.write(\"%f %d\\n\" % (d(one), n))\n"
     "    sys.stdout.write(\"%d %f %d %f\\n\" % (n, d(one), 99, d(two)))\n"
     "    sys.stdout.write(\"%e %g\\n\" % (d(one), d(two)))\n"
     "    sys.stdout.write(\"%d %d\\n\" % (n, 7))\n"
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
    # than a frame address (`model.struct_fits_one_word` says the same thing in
    # its own words), and on this backend a field stored by a zero-argument
    # `__init__` of a one-field struct reads back as 0
    # (`“FORMAL_one_field_struct_field_stored_in_a_zero_arg_init_reads_as_zero”`),
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
    # ── THE STACK-ARGUMENT CONVENTION ───────────────────────────────────────────
    #
    # AAPCS passes arguments 0..7 in registers and the rest in the caller's frame;
    # SysV AMD64 passes 0..5 and the rest in the caller's frame, so a SEVEN-
    # argument function travels in a register on one architecture and in MEMORY on
    # the other.  Both conventions are implemented now
    # (`formal/x86_64_codegen.py`'s `_load_home_from_stack`/`_emit_call` and
    # `_MAX_INCOMING_ARGS` on both backends), which is what
    # `FORMAL_x86_64_argument_registers` asked for, and which is deleted;
    # before that x86-64
    # REFUSED the program and arm64 answered it, which is the two-architecture
    # disagreement about one source file this file exists to end.
    #
    # THE LADDER ITSELF — 7, 9 and 16 arguments, a stack argument arriving from a
    # caller's parameter, and a nested call in argument position — is in
    # `test_formal_run.py`'s `BOTH_ARCH_CASES`, which is REGISTERED as
    # `formal-run` and so runs in every gate; these two rows are the shapes that
    # ladder does not have, and neither is duplicated there.
    #
    # A VARIADIC EXTERN CALL whose seventh argument is in the caller's frame,
    # and it is here because libc is the one caller of this convention whose
    # code this project does NOT own: `printf` reads that argument out of
    # `[rsp+8]` and AL has to say how many vector registers were used.  On arm64
    # the same seven values are all registers, so the row is a statement about
    # the frame and not about the count.
    #
    # SEVEN and not nine, and the boundary is arm64's rather than this one's:
    # a variadic callee with arguments past the register file is refused there
    # (`formal/arm64_codegen.py`'s `_emit_call`, because its `...` tail is laid
    # out in a separate stack area), so a nine-value printf cannot be a
    # two-backend case at all.  `len_of_every_operand_shape` above used to split
    # its seven-value printf in two for the same reason and does not any more.
    ("a_variadic_printf_with_an_argument_in_the_frame",
     "def main():\n"
     "    printf(\"%d %d %d %d %d %d %d\", 1, 2, 3, 4, 5, 6, 7)\n"
     "    return 0\n",
     "import sys\n\ndef main():\n"
     "    sys.stdout.write(\"%d %d %d %d %d %d %d\" % (1, 2, 3, 4, 5, 6, 7))\n"
     "    return 0\n"),
    # A STACK ARGUMENT ALONGSIDE A FRAME RECEIVER, in METHOD position.  A
    # parameter with no register home is loaded into R11 — the scratch
    # `_store_var` uses on the spill path — and then stored, so a load that
    # borrowed that scratch for the ADDRESS would overwrite the value before the
    # store; and a method's receiver is the parameter whose home assignment is
    # the most complicated thing in the prologue.  `self.a` is READ as well as
    # the arguments passed, so a frame read that landed on the outgoing area
    # shows up in the answer instead of passing quietly.
    #
    # The method is spelled INSIDE the struct, which is not a style choice: at
    # module level `self` is a name and `wide` is a free function, and the
    # receiver-position rules say so by name (measured — "not one of those
    # methods of those receivers").
    ("a_stack_argument_on_a_method_with_a_frame_receiver",
     "struct P:\n"
     "    var a: int\n"
     "    var b: int\n"
     "    def wide(self, a0: int, a1: int, a2: int, a3: int,\n"
     "             a4: int, a5: int, a6: int) -> int:\n"
     "        return a6 * 1000 + a0 + self.a\n\n"
     "def main() -> int:\n"
     "    var q = P()\n"
     "    q.a = 5\n"
     "    q.b = 6\n"
     "    printf(\"recv=%d\", q.wide(1, 2, 3, 4, 5, 6, 7))\n"
     "    return 0\n",
     "import sys\n\nclass P:\n"
     "    a = 0\n"
     "    b = 0\n\n"
     "    def wide(self, a0, a1, a2, a3, a4, a5, a6):\n"
     "        return a6 * 1000 + a0 + self.a\n\ndef main():\n"
     "    q = P()\n"
     "    q.a = 5\n"
     "    q.b = 6\n"
     "    sys.stdout.write(\"recv=%d\" % q.wide(1, 2, 3, 4, 5, 6, 7))\n"
     "    return 0\n"),
    # `x^` is Mojo's OWNERSHIP TRANSFER marker — a borrow-check annotation
    # naming no runtime operation — and it is the one unary operator the two
    # backends used to answer differently about.  arm64's `_emit_expr` had an
    # `is_ownership_transfer` branch; x86-64's `_emit_unary` did not, so it fell
    # through to `unsupported unary operator '^' on the formal x86-64 path`.
    # That is a codegen gap in x86-64 and not a wording difference: it refused
    # correct stdlib Mojo, `std/builtin/swap.mojo` (`var tmp = lhs^`), which
    # builds on arm64 and was carried as unstarted x86-64-side work in
    # `bugs/FORMAL_known_limits.md` §6.5.
    #
    # The case is the WHOLE of `swap.mojo`'s shape rather than the bare
    # operator, because a bare `var t = a^` and `swap(a, b)`'s three-operator
    # body differ in what they prove.  The bare one says the operator emits
    # something; this one says the emitted value is the operand's, on both
    # backends, with the operands printed afterwards to show the transfer
    # marked no MOVE — a lowering that consumed or zeroed the source would
    # satisfy the first and fail this.
    ("ownership_transfer_caret",
     "def main():\n"
     "    var a = 11\n"
     "    var b = 22\n"
     "    var c = 33\n"
     "    var x = a^\n"
     "    var y = b^\n"
     "    var z = c^\n"
     "    printf(\"%d %d %d\", x, y, z)\n"
     "    printf(\" %d %d %d\", a, b, c)\n"
     "    return 0\n",
     "import sys\n\n"
     "def main():\n"
     "    a = 11\n"
     "    b = 22\n"
     "    c = 33\n"
     "    x = a\n"
     "    y = b\n"
     "    z = c\n"
     "    sys.stdout.write(\"%d %d %d\" % (x, y, z))\n"
     "    sys.stdout.write(\" %d %d %d\" % (a, b, c))\n"
     "    return 0\n"),
    # The same operator over a NEGATIVE value, because the pass-through is
    # implemented by emitting the operand and a lowering that truncated or
    # sign-extended on the way through would agree with the case above on every
    # non-negative input and disagree here.  `-7` is the smallest value whose
    # sign bit and whose magnitude disagree under a 32-bit truncation.
    ("ownership_transfer_keeps_a_negative",
     "def main():\n"
     "    var n = -7\n"
     "    var m = n^\n"
     "    printf(\"%d %d\", m, n)\n"
     "    return 0\n",
     "import sys\n\n"
     "def main():\n"
     "    n = -7\n"
     "    m = n\n"
     "    sys.stdout.write(\"%d %d\" % (m, n))\n"
     "    return 0\n"),
    # A CALL's result under the marker, which is the shape inside a loop body in
    # `swap.mojo` (`unsafe_take_pointee()` is an extern call).  It is here for
    # the RAX handoff rather than the value: every case above reads a name, and
    # a lowering that emitted the marker by re-evaluating its operand — which
    # is the one implementation that gets the first three cases right and this
    # one wrong, by calling `bump()` twice — passes them all.
    ("ownership_transfer_of_a_call_result",
     "import sys\n\ndef bump():\n"
     "    print(\"bump\")\n"
     "    return 7\n"
     "\n"
     "def main():\n"
     "    var v = bump()^\n"
     "    printf(\"%d\", v)\n"
     "    return 0\n",
     "import sys\n\ndef bump():\n"
     "    print(\"bump\")\n"
     "    return 7\n"
     "\n"
     "def main():\n"
     "    v = bump()\n"
     "    sys.stdout.write(\"%d\" % v)\n"
     "    return 0\n"),
    # ── `del` ───────────────────────────────────────────────────────────────
    #
    # THE SILENT NO-OP, and the two halves of it.  arm64 had four `del`
    # lowering helpers and one `continue` in front of them, so `del lst[0]`
    # built, ran, exited 0 and removed nothing — and x86-64 had no `DelStmt` in
    # its statement dispatch at all, so the SAME source did not build there.
    # One architecture quietly wrong, the other declining: the shape this file
    # exists to end.
    #
    # Three shapes, one row each, because they are three different algorithms
    # (shift-one, memmove-the-tail, shift-over-the-pairs) and a fix that
    # repaired one of them and left the other two would pass a single row.
    # The index is a NAME in the first two rows and a negative one in the
    # third: the wrap is a separate branch in both backends from the element
    # address it feeds, so "the index is 0" does not cover it.
    ("del_list_index_computed",
     "def main():\n"
     "    var a = [10, 20, 30]\n"
     "    var i = 0\n"
     "    del a[i]\n"
     "    printf(\"%d %d %d\", len(a), a[0], a[1])\n"
     "    return 0\n",
     "import sys\n\ndef main():\n"
     "    a = [10, 20, 30]\n"
     "    i = 0\n"
     "    del a[i]\n"
     "    sys.stdout.write(\"%d %d %d\" % (len(a), a[0], a[1]))\n"
     "    return 0\n"),
    ("del_list_index_negative",
     "def main():\n"
     "    var a = [10, 20, 30, 40]\n"
     "    del a[-1]\n"
     "    printf(\"%d %d %d\", len(a), a[0], a[2])\n"
     "    return 0\n",
     "import sys\n\ndef main():\n"
     "    a = [10, 20, 30, 40]\n"
     "    del a[-1]\n"
     "    sys.stdout.write(\"%d %d %d\" % (len(a), a[0], a[2]))\n"
     "    return 0\n"),
    # `a[1]` is the tail element, which is the whole point of the row: a
    # memmove that only decremented the count would leave `a[1]` at 20 and
    # print `2 10 20`, and reading `a[3]` here would be an out-of-range exit on
    # both machines rather than a comparison.
    ("del_list_slice",
     "def main():\n"
     "    var a = [10, 20, 30, 40, 50]\n"
     "    del a[1:4]\n"
     "    printf(\"%d %d %d\", len(a), a[0], a[1])\n"
     "    return 0\n",
     "import sys\n\ndef main():\n"
     "    a = [10, 20, 30, 40, 50]\n"
     "    del a[1:4]\n"
     "    sys.stdout.write(\"%d %d %d\" % (len(a), a[0], a[1]))\n"
     "    return 0\n"),
    # A NEGATIVE lower bound and an OMITTED upper one, which between them are
    # the whole of Python's bound normalization: the lower bound gains the
    # count, the omitted upper bound IS the count, and the two clamps between
    # them are where a `cset` polarity error turns `del a[-2:]` into
    # `del a[-2:1]` — a list of the right length and the wrong contents.
    ("del_list_slice_negative_start_open_stop",
     "def main():\n"
     "    var a = [10, 20, 30, 40]\n"
     "    del a[-2:]\n"
     "    printf(\"%d %d %d\", len(a), a[0], a[1])\n"
     "    return 0\n",
     "import sys\n\ndef main():\n"
     "    a = [10, 20, 30, 40]\n"
     "    del a[-2:]\n"
     "    sys.stdout.write(\"%d %d %d\" % (len(a), a[0], a[1]))\n"
     "    return 0\n"),
    ("del_dict_key",
     "def main():\n"
     "    var d = {\"a\": 1, \"b\": 2, \"c\": 3}\n"
     "    del d[\"b\"]\n"
     "    printf(\"%d %d %d\", len(d), d[\"a\"], d[\"c\"])\n"
     "    return 0\n",
     "import sys\n\ndef main():\n"
     "    d = {\"a\": 1, \"b\": 2, \"c\": 3}\n"
     "    del d[\"b\"]\n"
     "    sys.stdout.write(\"%d %d %d\" % (len(d), d[\"a\"], d[\"c\"]))\n"
     "    return 0\n"),
    # THROUGH A FRAME SLOT, because the base is read by a different table than
    # a local's: `h.xs` is an SRA slot, and a lowering that loaded the blob the
    # way it loads a name would decrement the first word of the HOLDER.
    ("del_through_a_frame_slot",
     "struct Holder:\n"
     "    var xs: List[Int]\n"
     "def main():\n"
     "    var h = Holder()\n"
     "    h.xs = [1, 2, 3]\n"
     "    del h.xs[0]\n"
     "    printf(\"%d %d\", h.xs[0], h.xs[1])\n"
     "    return 0\n",
     "import sys\n\nclass Holder:\n"
     "    def __init__(self):\n"
     "        self.xs = []\n\n"
     "def main():\n"
     "    h = Holder()\n"
     "    h.xs = [1, 2, 3]\n"
     "    del h.xs[0]\n"
     "    sys.stdout.write(\"%d %d\" % (h.xs[0], h.xs[1]))\n"
     "    return 0\n"),
    # A chain of typed-nested FRAMES, which is the shape the block layout is
    # recursive for, and every level is given a DISTINCT value so a lowering
    # that put any two frames at the same address cannot pass by printing one
    # number twice.  The read is the half that used to be one hop deep whatever
    # the chain's length: `o.n.n.v` was computed as `o.n.v`, so the innermost
    # read either refused (`'n' is not a field of the holder's struct`, which
    # is true of the OUTER struct and false of the file) or read the wrong slot.
    # A METHOD CALL on a nested receiver -- `o.n.put(7)`, which
    # `formal/build.py`'s `_rewrite_nested_method_calls` turns into
    # `In_put(o.n, 7)` so the ordinary call path applies.  The frame design's
    # own "still not done" list named this as refused on both backends, which
    # this row measured FALSE: it builds and answers `77` on both.  So it is
    # here because a doc's open list is not a test, and the second half is the
    # shape that matters -- the write goes through `In_put`'s OWN frame
    # contract (`out self`, `FrameOk_except`), so a lowering that read the
    # receiver's slot without going through the method would print the right
    # `a` and the wrong `b`.
    #
    # `b` is 0 and that is the assertion: `Inner_put` writes slot 0 and must not
    # disturb slot 1, so a copy-through would show `b=7`.
    ("method_call_on_a_nested_frame_receiver",
     "struct In:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def put(out self, v: Int) -> Int:\n"
     "        self.a = v\n"
     "        return self.a\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.a\n"
     "\n"
     "struct Out:\n"
     "    var pad: Int\n"
     "    var n: In\n"
     "\n"
     "def main(k):\n"
     "    var o = Out()\n"
     "    o.n.put(7)\n"
     '    printf("%d %d %d", o.n.a, o.n.b, o.n.get() * 10 + o.n.a)\n'
     "    return 0\n",
     "class In:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "\n"
     "    def put(self, v):\n"
     "        self.a = v\n"
     "        return self.a\n"
     "\n"
     "    def get(self):\n"
     "        return self.a\n"
     "\n"
     "class Out:\n"
     "    def __init__(self):\n"
     "        self.pad = 0\n"
     "        self.n = In()\n"
     "\n"
     "import sys\n"
     "\n"
     "def main():\n"
     "    o = Out()\n"
     "    o.n.put(7)\n"
     '    sys.stdout.write("%d %d %d" % (o.n.a, o.n.b, o.n.get() * 10 + o.n.a))\n'
     "    return 0\n"),
    # The row above with `Out`'s `pad` DELETED, so `n` is the struct's ONLY
    # field — and with it the whole shape changes, because a struct of one
    # field has no frame of its own: its receiver IS that field, and
    # `model.struct_constructor_site_bytes` reserves the NESTED block alone
    # because "there is no object: the VALUE is the nested frame's address".
    # `o.n` is therefore `o`, and `o.n.a` is ONE load at `o + 8·slot(a)` — not
    # the two-hop read a "the first hop was thrown away" reading of the symptom
    # suggests, and not the field access of a plain word either.  Before the
    # fix BOTH backends refused the read by name with
    #
    #     main: 'o.a' is a field access through 'o', and this path has no way
    #     to say what 'o' holds … Bind the base from a constructor whose
    #     declaration THIS IMAGE can see (`x = S()`)
    #
    # about a constructor they had just compiled and could see perfectly well:
    # the holder analysis seeded the METHOD receiver of such a struct
    # (`_frame_receivers`) and had no case for the LOCAL, so the word the
    # constructor put an address in was still classified as a plain word.
    # commit 03e3b7b6.
    #
    # The `put(7)` is the METHOD-call half and the reads are the direct half,
    # so the two shapes that share the word are both here: with only the call
    # the program already built, which is why the row looked like a working
    # family rather than a broken one.
    ("one_field_struct_whose_only_field_is_a_nested_frame",
     "struct In:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def put(out self, v: Int) -> Int:\n"
     "        self.a = v\n"
     "        return self.a\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.a\n"
     "\n"
     "struct Out:\n"
     "    var n: In\n"
     "\n"
     "def main(k):\n"
     "    var o = Out()\n"
     "    o.n.put(7)\n"
     '    printf("%d %d %d", o.n.a, o.n.b, o.n.get() * 10 + o.n.a)\n'
     "    return 0\n",
     "class In:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "\n"
     "    def put(self, v):\n"
     "        self.a = v\n"
     "        return self.a\n"
     "\n"
     "    def get(self):\n"
     "        return self.a\n"
     "\n"
     "class Out:\n"
     "    def __init__(self):\n"
     "        self.n = In()\n"
     "\n"
     "import sys\n"
     "\n"
     "def main():\n"
     "    o = Out()\n"
     "    o.n.put(7)\n"
     '    sys.stdout.write("%d %d %d" % (o.n.a, o.n.b, o.n.get() * 10 + o.n.a))\n'
     "    return 0\n"),
    # The same shape TWO NESTED LEVELS DOWN, and it is its own row because it
    # fails a different way: the row above reads slots the nested frame already
    # had, while this one reads a frame the nested frame itself holds, and the
    # one-word construction used to bring that grandchild's DEFAULTS up and
    # never store its ADDRESS (`_emit_fresh_one_word` stopped after
    # `_emit_frame_nested` + `_emit_frame_defaults` on the reasoning that its
    # own address is the result, which says nothing about the frames inside
    # it).  The slot stayed at the zero those defaults wrote, so the first read
    # through it was a load at address 0: measured on both architectures,
    # `o.n.d.x = 5` built, ran and died of SIGSEGV, exit 139, while `o.n.a` and
    # `o.n.d.y` answered correctly in the same program.
    ("one_field_struct_whose_only_field_is_a_nested_frame_two_levels_down",
     "struct Deep:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "struct In:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var d: Deep\n"
     "\n"
     "struct Out:\n"
     "    var n: In\n"
     "\n"
     "def main(k):\n"
     "    var o = Out()\n"
     "    o.n.a = 7\n"
     "    o.n.d.x = 5\n"
     "    o.n.d.y = 6\n"
     '    printf("%d %d %d %d", o.n.a, o.n.b, o.n.d.x, o.n.d.y)\n'
     "    return 0\n",
     "class Deep:\n"
     "    def __init__(self):\n"
     "        self.x = 0\n"
     "        self.y = 0\n"
     "\n"
     "class In:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "        self.d = Deep()\n"
     "\n"
     "class Out:\n"
     "    def __init__(self):\n"
     "        self.n = In()\n"
     "\n"
     "import sys\n"
     "\n"
     "def main():\n"
     "    o = Out()\n"
     "    o.n.a = 7\n"
     "    o.n.d.x = 5\n"
     "    o.n.d.y = 6\n"
     '    sys.stdout.write("%d %d %d %d" % (o.n.a, o.n.b, o.n.d.x, o.n.d.y))\n'
     "    return 0\n"),
    ("nested_frame_chain_three_levels",
     "struct In:\n"
     "    var v: Int\n"
     "    var w: Int\n"
     "\n"
     "struct Mid:\n"
     "    var v: Int\n"
     "    var n: In\n"
     "\n"
     "struct Out:\n"
     "    var v: Int\n"
     "    var n: Mid\n"
     "\n"
     "def main():\n"
     "    var o = Out()\n"
     "    o.v = 1\n"
     "    o.n.v = 2\n"
     "    o.n.n.v = 3\n"
     "    o.n.n.w = 4\n"
     "    printf(\"%d %d %d %d\", o.v, o.n.v, o.n.n.v, o.n.n.w)\n"
     "    return 0\n",
     "class In:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.w = 0\n"
     "\n"
     "class Mid:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.n = In()\n"
     "\n"
     "class Out:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.n = Mid()\n"
     "\n"
     "import sys\n\n"
     "def main():\n"
     "    o = Out()\n"
     "    o.v = 1\n"
     "    o.n.v = 2\n"
     "    o.n.n.v = 3\n"
     "    o.n.n.w = 4\n"
     "    sys.stdout.write(\"%d %d %d %d\" % (o.v, o.n.v, o.n.n.v, o.n.n.w))\n"
     "    return 0\n"),
    # The chain at ONE FIELD, which is the row `nested_frame_chain_three_levels`
    # could not reach: `Out` above has `v` to spare, so `Out` is a frame and
    # `o.n.n.v` is three loads off a frame base. Drop `v` and `Out` is a ONE-WORD
    # struct, `_rewrite_self_fields` collapses `o.n` onto `o`, and the source's
    # `o.n.a` reaches the emitter as `o.a` — a field of `Inner` read through a
    # local whose only classification was "a word". It was REFUSED on both
    # machines with a message naming `o.a`, which the source never writes, and
    # the refusal's own repair ("bind the base from a constructor this image can
    # see") was satisfied by the line above it.
    #
    # The answer is the two-hop read and it needs no new table: `Outer`'s word
    # IS the address of the `Inner` frame the construction site reserved
    # (`struct_nested_frame_fields`), so once `o` is a holder of `Inner`,
    # `o.a` is one load at `[o + 8*slot(a)]` — the same two hops the source
    # wrote. A multi-field outer keeps `model._frame_nested_slots`' tuple,
    # because a slot there SURVIVES the collapse.
    ("one_word_outer_over_a_nested_frame",
     "struct In:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def put(out self, v: Int) -> Int:\n"
     "        self.a = v\n"
     "        return self.a\n"
     "    def get(self) -> Int:\n"
     "        return self.a\n"
     "\n"
     "struct Out:\n"
     "    var n: In\n"
     "\n"
     "def main():\n"
     "    var o = Out()\n"
     "    o.n.put(7)\n"
     # The value is PRINTED rather than returned: `run_case` requires the
     # oracle to exit 0, and a Mojo entry stub makes `main`'s return the exit
     # status while `cpython_answer`'s bare `main()` call discards it — so a
     # returned 77 here compares 77 against 0 and the case asserts nothing.
     "    printf(\"%d %d %d\", o.n.a, o.n.b, o.n.get() * 10 + o.n.a)\n"
     "    return 0\n",
     "class In:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "    def put(self, v):\n"
     "        self.a = v\n"
     "        return self.a\n"
     "    def get(self):\n"
     "        return self.a\n"
     "\n"
     "class Out:\n"
     "    def __init__(self):\n"
     "        self.n = In()\n"
     "\n"
     "import sys\n\n"
     "def main():\n"
     "    o = Out()\n"
     "    o.n.put(7)\n"
     "    sys.stdout.write(\"%d %d %d\" % (o.n.a, o.n.b,\n"
     "                                o.n.get() * 10 + o.n.a))\n"
     "    return 0\n"),
    # The same chain HANDED TO A CALLEE, which is the `_emit_frame_copy` half and
    # not the `_emit_frame_nested_addresses` half: the copy reserves its own
    # block and has to lay the nested frames out in it identically, so a fix
    # that stored each level's address against the OUTER base (as both backends
    # did) passes the case above — which never copies — and fails this one by
    # overwriting the outer frame's own first-level address with the inner one.
    ("nested_frame_chain_three_levels_survives_a_call",
     "struct In:\n"
     "    var v: Int\n"
     "    var w: Int\n"
     "\n"
     "struct Mid:\n"
     "    var v: Int\n"
     "    var n: In\n"
     "\n"
     "struct Out:\n"
     "    var v: Int\n"
     "    var n: Mid\n"
     "\n"
     "def take(x: Out) -> Int:\n"
     "    printf(\"%d %d %d\", x.v, x.n.v, x.n.n.v)\n"
     "    return x.n.n.w\n"
     "\n"
     "def main():\n"
     "    var o = Out()\n"
     "    o.v = 1\n"
     "    o.n.v = 2\n"
     "    o.n.n.v = 3\n"
     "    o.n.n.w = 9\n"
     "    printf(\" %d \", o.n.n.v)\n"
     "    printf(\"%d\", take(o))\n"
     "    return 0\n",
     "class In:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.w = 0\n"
     "\n"
     "class Mid:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.n = In()\n"
     "\n"
     "class Out:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.n = Mid()\n"
     "\n"
     "import sys\n\n"
     "def take(x):\n"
     "    sys.stdout.write(\"%d %d %d\" % (x.v, x.n.v, x.n.n.v))\n"
     "    return x.n.n.w\n"
     "\n"
     "def main():\n"
     "    o = Out()\n"
     "    o.v = 1\n"
     "    o.n.v = 2\n"
     "    o.n.n.v = 3\n"
     "    o.n.n.w = 9\n"
     "    sys.stdout.write(\" %d \" % o.n.n.v)\n"
     "    sys.stdout.write(\"%d\" % take(o))\n"
     "    return 0\n"),
    # FIVE nested levels, which is `MAX_NESTED_FRAME_DEPTH` and the deepest
    # chain the layout sizes.  It is here as the anti-rot for the bound: raise
    # the constant and this keeps passing while the REFUSAL below stops firing,
    # which is the pair that says the constant is the whole of the limit.
    ("nested_frame_chain_at_the_depth_bound",
     "struct S1:\n"
     "    var v: Int\n"
     "    var w: Int\n"
     "\n"
     "struct S2:\n"
     "    var v: Int\n"
     "    var n: S1\n"
     "\n"
     "struct S3:\n"
     "    var v: Int\n"
     "    var n: S2\n"
     "\n"
     "struct S4:\n"
     "    var v: Int\n"
     "    var n: S3\n"
     "\n"
     "struct S5:\n"
     "    var v: Int\n"
     "    var n: S4\n"
     "\n"
     "def main():\n"
     "    var o = S5()\n"
     "    o.v = 1\n"
     "    o.n.v = 2\n"
     "    o.n.n.v = 3\n"
     "    o.n.n.n.v = 4\n"
     "    o.n.n.n.n.v = 5\n"
     "    printf(\"%d %d %d %d %d\", o.v, o.n.v, o.n.n.v, o.n.n.n.v,\n"
     "           o.n.n.n.n.v)\n"
     "    return 0\n",
     "class S1:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.w = 0\n"
     "\n"
     "class S2:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.n = S1()\n"
     "\n"
     "class S3:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.n = S2()\n"
     "\n"
     "class S4:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.n = S3()\n"
     "\n"
     "class S5:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "        self.n = S4()\n"
     "\n"
     "import sys\n\n"
     "def main():\n"
     "    o = S5()\n"
     "    o.v = 1\n"
     "    o.n.v = 2\n"
     "    o.n.n.v = 3\n"
     "    o.n.n.n.v = 4\n"
     "    o.n.n.n.n.v = 5\n"
     "    sys.stdout.write(\"%d %d %d %d %d\" % (o.v, o.n.v, o.n.n.v,\n"
     "                                        o.n.n.n.v, o.n.n.n.n.v))\n"
     "    return 0\n"),
    # ── the lowering paths that exist on arm64's side ALONE ──────────────
    #
    # Added by the arm-vs-x86 parity audit (2026-10-03), which enumerated the
    # `_emit_*` methods that exist in `formal/arm64_codegen.py` and NOT in
    # `formal/x86_64_codegen.py` and then built and ran each construct on both
    # machines.  Five of the seven were already correct on both and had NO case
    # here, which is the coverage hole this file is for: a construct both
    # machines answer is not evidence they will keep answering it.
    #
    # The two that were not correct are the interesting half, and they are in
    # `test_formal_list_splat.py` (arm64 built `[*a]` as an EMPTY list) and in
    # FORMAL_arm64_set_union_result_blob_has_the_wrong_count.
    ("read_slice_of_a_list",
     "def main():\n"
     "    var a = [10, 20, 30, 40, 50]\n"
     "    var b = a[1:4]\n"
     "    printf(\"%d %d %d\", b[0], b[1], b[2])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a = [10, 20, 30, 40, 50]\n"
     "    b = a[1:4]\n"
     "    sys.stdout.write(\"%d %d %d\" % (b[0], b[1], b[2]))\n"
     "    return 0\n"),
    # The step is a RUN-TIME value on this path, so the four Python defaults
    # that depend on its sign are each a word and the loop picks between them.
    # `a[::2]` is the shape that needs all of them at once.
    ("read_slice_with_a_step",
     "def main():\n"
     "    var a = [10, 20, 30, 40, 50]\n"
     "    var b = a[::2]\n"
     "    printf(\"%d %d %d\", b[0], b[1], b[2])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a = [10, 20, 30, 40, 50]\n"
     "    b = a[::2]\n"
     "    sys.stdout.write(\"%d %d %d\" % (b[0], b[1], b[2]))\n"
     "    return 0\n"),
    # An open stop, which is `len(a)` and NOT a literal: the bound comes from
    # the blob's count field, so a slice that assumed the source's length was
    # written down would be short by one here.
    ("read_slice_with_an_open_stop",
     "def main():\n"
     "    var a = [10, 20, 30, 40, 50]\n"
     "    var b = a[2:]\n"
     "    printf(\"%d %d %d\", b[0], b[1], b[2])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a = [10, 20, 30, 40, 50]\n"
     "    b = a[2:]\n"
     "    sys.stdout.write(\"%d %d %d\" % (b[0], b[1], b[2]))\n"
     "    return 0\n"),
    # `del a[1:3]` COMPACTS the survivors, so the elements after the hole have
    # to MOVE — a different job from a read slice, and the one that reads
    # `a[2]` back to tell whether it happened.  `del_list_slice` above is the
    # single-bound form; this is the range.
    ("del_a_range_of_a_list",
     "def main():\n"
     "    var a = [10, 20, 30, 40, 50]\n"
     "    del a[1:3]\n"
     "    printf(\"%d %d %d\", a[0], a[1], a[2])\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a = [10, 20, 30, 40, 50]\n"
     "    del a[1:3]\n"
     "    sys.stdout.write(\"%d %d %d\" % (a[0], a[1], a[2]))\n"
     "    return 0\n"),
    # A tuple target NESTED inside another tuple target.  The outer unpack
    # only checks top-level arity, so the inner pair is a second emitter with
    # its own register discipline — and `tuple_target_in_a_constructor_body_
    # answers_on_both` above is the single-level spelling of this.
    ("nested_tuple_target_assignment",
     "def main():\n"
     "    var t = (1, (2, 3))\n"
     "    a, (b, c) = t\n"
     "    printf(\"%d %d %d\", a, b, c)\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    t = (1, (2, 3))\n"
     "    a, (b, c) = t\n"
     "    sys.stdout.write(\"%d %d %d\" % (a, b, c))\n"
     "    return 0\n"),
    # `x if c else y`, with the UNTAKEN arm made observable.  arm64 has a CSEL
    # for this, which reads two registers at once and so evaluates both arms;
    # a branchless lowering of a conditional whose arms have effects answers a
    # different program, and the difference is in what the program PRINTS, not
    # in the value it returns.  Measured on this tree: both machines branch, and
    # `bump()`'s output appears for neither — so the case is pinning that
    # answer rather than discovering it.
    ("conditional_expression_does_not_run_the_untaken_arm",
     "def bump():\n"
     "    printf(\"arm-ran \")\n"
     "    return 7\n"
     "\n"
     "def main():\n"
     "    var c = 0\n"
     "    printf(\"v=%d\", bump() if c else 99)\n"
     "    return 0\n",
     "import sys\n\n"
     "def bump():\n"
     "    sys.stdout.write(\"arm-ran \")\n"
     "    return 7\n"
     "\n"
     "def main():\n"
     "    c = 0\n"
     "    sys.stdout.write(\"v=%d\" % (bump() if c else 99))\n"
     "    return 0\n"),
    # A CHAINED COMPARISON whose first operand is EVEN — the one row of this
    # construct that a hand-written case gets wrong by accident, because the
    # corpus of small positive integers this file is made of is mostly ODD.
    #
    # x86-64's `_emit_compare_chain` seeded its running AND with the first
    # OPERAND'S VALUE instead of 1, so every chain answered
    # `operands[0] & link0 & link1 & …`: `n <= m <= w` with n = -20 printed 0
    # while arm64 printed 1, and `m <= w <= w` with m = 5 printed 1 — so a case
    # written with a first operand of 5 or 243 passes on both machines and
    # never sees the defect.  These rows are the parity ladder over the
    # LOW BIT of the first operand: 20 (even), 5 (odd), 0 (even), -20 (even,
    # and the sign is a second axis — a negative first operand is what the
    # fuzzer's generated programs hit first).
    #
    # Both spellings are here because they are different paths in the backend:
    # the chain in a CONDITION goes through the truthy-word lowering, and the
    # chain ASSIGNED to a name goes through the value path, and a fix that
    # only reached one of them would leave the other reading a stale slot.
    ("chain_first_operand_bits",
     "def main():\n"
     "    var n = -20\n"
     "    var m = 5\n"
     "    var w = 243\n"
     "    printf(\"%d %d %d %d\", 1 if n <= m <= w else 0,"
     " 1 if m <= w <= w else 0, 1 if 0 <= m <= w else 0,"
     " 1 if w >= m >= n else 0)\n"
     "    var r = n <= m <= w\n"
     "    printf(\" %d\", 1 if r else 0)\n"
     "    return 0\n",
     "import sys\n\n"
     "def main():\n"
     "    n = -20\n"
     "    m = 5\n"
     "    w = 243\n"
     "    sys.stdout.write(\"%d %d %d %d\" % (1 if n <= m <= w else 0,\n"
     "                                       1 if m <= w <= w else 0,\n"
     "                                       1 if 0 <= m <= w else 0,\n"
     "                                       1 if w >= m >= n else 0))\n"
     "    r = n <= m <= w\n"
     "    sys.stdout.write(\" %d\" % (1 if r else 0))\n"
     "    return 0\n"),
    # The SAME defect one link further out: a THREE-link chain, where the seed
    # is ANDed with three link results rather than two.  Every row here is a
    # chain whose answer is TRUE, so a seed of 0 shows up as a wrong 0 rather
    # than as a coincidence — `20 <= 5 <= 243 <= 9` would answer 0 either way
    # and assert nothing.
    ("chain_three_links_first_operand_bits",
     "def main():\n"
     "    var a = 4\n"
     "    var b = 5\n"
     "    var c = 243\n"
     "    var d = 250\n"
     "    var e = 6\n"
     "    var f = 7\n"
     "    var g = 7\n"
     "    printf(\"%d %d %d\", 1 if a <= b <= c <= d else 0,"
     " 1 if e <= f <= c <= d else 0, 1 if g <= f <= c <= d else 0)\n"
     "    return 0\n",
     "import sys\n\n"
     "def main():\n"
     "    a = 4\n"
     "    b = 5\n"
     "    c = 243\n"
     "    d = 250\n"
     "    e = 6\n"
     "    f = 7\n"
     "    g = 7\n"
     "    sys.stdout.write(\"%d %d %d\" % (1 if a <= b <= c <= d else 0,\n"
     "                                   1 if e <= f <= c <= d else 0,\n"
     "                                   1 if g <= f <= c <= d else 0))\n"
     "    return 0\n"),
    # A NEGATIVE VALUE SPELLED WITH AN OPERATOR — the one that made a literal
    # comparison decide UNSIGNED on BOTH machines, so it is here rather than in
    # an arm64-only file even though it is not an x86-64 gap.
    #
    # `-4` is a UnaryOp and `0 - 4` is a BinaryOp.  `infer_expr` reported the
    # first signed (the negated-literal arm, added with the arm64 signedness
    # work) and the second typeless, because both of its operands are literals;
    # `common_type(None, None)` is None, `cmp_signed(None)` is False, and the
    # compare was emitted with unsigned condition codes.  So the same value
    # answered 0 as `-4` and 1 as `0 - 4`:
    #
    #     0 < (51 - 55)    CPython 0    arm64 1    x86-64 1
    #     17 <= (0 - 4)     CPython 0    arm64 1    x86-64 1
    #     (0 - 4) < 0       CPython 1    arm64 0    x86-64 0
    #
    # Both spellings of each comparison are in the case, and the variable form
    # (`a - b < c` with a variable) is the control: that one was already
    # signed, which is why the defect needed arithmetic on LITERALS to show.
    # A COMPREHENSION inside an `elif` ARM, and this is a refusal rather than a
    # wrong answer — which is the shape this file exists for in its other
    # direction.  arm64 built and ran it; x86-64 refused with
    #
    #     main: '_cb0' has no home: the register allocator collected no home
    #     for it, so the emitter and the allocation walk disagree about this
    #     function's locals
    #
    # `_cb{d}` is a comprehension's per-generator temp, and the walk that
    # reserves them (`x86_64_codegen._collect_var_names`'s `walk_compr`) reached
    # an `if`/`else` body through the dataclass-field walk — which iterates a
    # LIST's items — but an `elif` body arrives as the second item of a TUPLE
    # in `IfStmt.elifs`, and the tuple branch handed that bare LIST to
    # `walk_compr`, which found no `__dataclass_fields__` and returned.  So the
    # comprehension reserved no temps at all.  arm64's `walk_compr_temps` has
    # had a `isinstance(node, list)` arm for exactly this reason since the
    # comprehension-temp bug it documents; this backend's copy did not.
    #
    # Found by `tools/formal_fuzz.py`'s `containers` mix, seeds 1000-1499.
    # Both arms are here because only the `elif` one failed, and a list
    # comprehension in the `if` arm is the control for "the walk reaches an
    # `if` body".
    ("comprehension_in_an_elif_arm_reserves_its_temps",
     "def main():\n"
     "    var n = 0\n"
     "    if 1 > 0:\n"
     "        var t = [10 + i for i in range(3)]\n"
     "        for x in t:\n"
     "            n = n + x\n"
     "    elif 2 > 3:\n"
     "        var t = [10 + i for i in range(3)]\n"
     "        for x in t:\n"
     "            n = n + x\n"
     "    else:\n"
     "        n = n + 1\n"
     "    printf(\"n=%d\", n)\n"
     "    return 0\n",
     "import sys\n\n"
     "def main():\n"
     "    n = 0\n"
     "    if 1 > 0:\n"
     "        t = [10 + i for i in range(3)]\n"
     "        for x in t:\n"
     "            n = n + x\n"
     "    elif 2 > 3:\n"
     "        t = [10 + i for i in range(3)]\n"
     "        for x in t:\n"
     "            n = n + x\n"
     "    else:\n"
     "        n = n + 1\n"
     "    sys.stdout.write(\"n=%d\" % n)\n"
     "    return 0\n"),
    # A DICT comprehension in the same position, because the two walk the same
    # way but lower through different emitters, and a fix that covered only the
    # list form would leave the dict one reserved-and-unused.  Its KEYS are
    # summed rather than its length read, for the reason the case above walks
    # the list instead of subscripting it: `len` and `t[0]` of a name a
    # comprehension bound are both refused on both architectures (\"len() of a
    # value classified as 'int'\" and \"print() cannot tell whether SubscriptExpr
    # is a string or a number\"), so an observation through either would be a
    # case that cannot run.
    ("dict_comprehension_in_an_elif_arm_reserves_its_temps",
     "def main():\n"
     "    var n = 0\n"
     "    if 1 > 0:\n"
     "        var d = {10 + i: 100 + i for i in range(3)}\n"
     "        for k in d:\n"
     "            n = n + k\n"
     "    elif 2 > 3:\n"
     "        var d = {10 + i: 100 + i for i in range(3)}\n"
     "        for k in d:\n"
     "            n = n + k\n"
     "    else:\n"
     "        n = n + 1\n"
     "    printf(\"n=%d\", n)\n"
     "    return 0\n",
     "import sys\n\n"
     "def main():\n"
     "    n = 0\n"
     "    if 1 > 0:\n"
     "        d = {10 + i: 100 + i for i in range(3)}\n"
     "        for k in d:\n"
     "            n = n + k\n"
     "    elif 2 > 3:\n"
     "        d = {10 + i: 100 + i for i in range(3)}\n"
     "        for k in d:\n"
     "            n = n + k\n"
     "    else:\n"
     "        n = n + 1\n"
     "    sys.stdout.write(\"n=%d\" % n)\n"
     "    return 0\n"),
    ("negative_literal_spelled_with_an_operator",
     "def main():\n"
     "    var a = 17\n"
     "    var b = 4\n"
     "    printf(\"%d %d %d %d %d %d\", 1 if 0 < (51 - 55) else 0,"
     " 1 if 17 <= (0 - 4) else 0, 1 if (0 - 4) < 0 else 0,"
     " 1 if 17 <= -4 else 0, 1 if -4 < 17 else 0, 1 if (a - b) < a else 0)\n"
     "    return 0\n",
     "import sys\n\n"
     "def main():\n"
     "    a = 17\n"
     "    b = 4\n"
     "    sys.stdout.write(\"%d %d %d %d %d %d\" % (\n"
     "        1 if 0 < (51 - 55) else 0,\n"
     "        1 if 17 <= (0 - 4) else 0,\n"
     "        1 if (0 - 4) < 0 else 0,\n"
     "        1 if 17 <= -4 else 0,\n"
     "        1 if -4 < 17 else 0,\n"
     "        1 if (a - b) < a else 0))\n"
     "    return 0\n"),
    # ── `int(s)` / `int(s, base)`: THE PARSE, ON BOTH MACHINES ──
    #
    # `test_formal_run.py`'s `INT_PARSE_CASES` pins the same five programs, and
    # it pins them through `run_case`, which builds THE HOST'S ARCHITECTURE for
    # an answered case — so on an arm64 host they were arm64 rows, and x86-64's
    # half of the parse was never checked by anything.  It was refused: the
    # lowering ended in two identical `self.asm.label(endl)` emits, and the
    # assembler's own duplicate-label check turned that into
    #
    #     build: internal: label 'main_ip1_end' is defined twice, at 0x… and at 0x…
    #
    # which `formal_fuzz.py` classified as a REFUSAL — a construct with no
    # representation — rather than as the internal error it is.  Measured on
    # `print(int("12"))`: arm64 printed 12, x86-64 refused, exit 0 on one side
    # and a build failure on the other, and nothing in the suite was red.
    #
    # So these five are HERE, where a case runs on both machines or not at all.
    # `int_parse_of_a_string_parameter` is the shape the label counter has to
    # survive: the parse is inside a CALLEE, so its end label is `parse_ip1_end`
    # and a counter that was per-program rather than per-function would collide
    # with the caller's own.
    ("int_parse_of_a_decimal_string",
     "def main():\n"
     "    printf(\"%d %d %d %d\", int(\"41\"), int(\"0\"), int(\"-7\"),"
     " int(\"  41  \"))\n"
     "    return 0\n",
     "import sys\n\n"
     "def main():\n"
     "    sys.stdout.write(\"%d %d %d %d\" % (int(\"41\"), int(\"0\"),"
     " int(\"-7\"), int(\"  41  \")))\n"
     "    return 0\n"),
    ("int_parse_with_a_stated_base",
     "def main():\n"
     "    printf(\"%d %d %d %d %d\", int(\"41\", 10), int(\"ff\", 16),"
     " int(\"101010\", 2), int(\"777\", 8), int(\"+7\", 10))\n"
     "    return 0\n",
     "import sys\n\n"
     "def main():\n"
     "    sys.stdout.write(\"%d %d %d %d %d\" % (int(\"41\", 10),"
     " int(\"ff\", 16), int(\"101010\", 2), int(\"777\", 8),"
     " int(\"+7\", 10)))\n"
     "    return 0\n"),
    # The `0x` PREFIX under an explicit 16, which `strtoll` reads and which a
    # lowering that applied the base twice would not.
    ("int_parse_in_base_sixteen_reads_the_0x_prefix",
     "def main():\n"
     "    printf(\"%d %d %d\", int(\"0x29\", 16), int(\"FF\", 16), int(\"0xff\", 16))\n"
     "    return 0\n",
     "import sys\n\n"
     "def main():\n"
     "    sys.stdout.write(\"%d %d %d\" % (int(\"0x29\", 16), int(\"FF\", 16),"
     " int(\"0xff\", 16)))\n"
     "    return 0\n"),
    # Through a PARAMETER, which is the shape a real caller has and the one the
    # evidence test turns on: an annotated `String` parameter is positively
    # text, and an undecided operand keeps the number conversion.
    ("int_parse_of_a_string_parameter",
     "def parse(s: String) -> Int:\n"
     "    return int(s)\n"
     "def main():\n"
     "    printf(\"%d %d\", parse(\"41\"), parse(\"-123\"))\n"
     "    return 0\n",
     "import sys\n\n"
     "def parse(s: str) -> int:\n"
     "    return int(s)\n"
     "def main():\n"
     "    sys.stdout.write(\"%d %d\" % (parse(\"41\"), parse(\"-123\")))\n"
     "    return 0\n"),
    # …and the CONTROL, on both machines: `int(n)` for a NUMBER is still the
    # number conversion, which is what `model.int_parse_lowering`'s permissive
    # `None` is for.  A parse applied to a number would turn every numeric
    # `int(x)` in the corpus into a parse of digits.
    ("int_parse_of_a_number_is_still_a_conversion",
     "def widen(n: Int) -> Int:\n"
     "    var v = int(n)\n"
     "    var w = Int32(n)\n"
     "    printf(\"%d %d\", v, w)\n"
     "    return 0\n"
     "def main():\n"
     "    widen(300)\n"
     "    return 0\n",
     "import sys\n\n"
     "def widen(n: int) -> int:\n"
     "    v = int(n)\n"
     "    w = int(n)\n"
     "    sys.stdout.write(\"%d %d\" % (v, w))\n"
     "    return 0\n"
     "def main():\n"
     "    widen(300)\n"
     "    return 0\n"),
     # `List.clear()` reached through a ONE-FIELD struct's sole field, which is

    # `std/collections/binary_heap.mojo`'s `clear` and the row that file's build
    # reaches next.  The identity is correct (`self._data` IS `self`), so what
    # the emitter sees is `self.clear()` with the receiver's KIND established
    # from the field's declared type — which is why this is a one-store lowering
    # and not a rewrite: the blob's COUNT is its first word, and emptying a list
    # is a store of zero there.
    #
    # The numbers are the assertion and they are not weak: `after 0` is only
    # reachable if the store landed in the blob the caller's local points at, and
    # `before 3` is only reachable if it did not already.
    #
    # `bugs/FORMAL_binary_heap_mojo_after_the_len_value.md` §3a row 1.
    ("list_clear_through_a_one_word_structs_sole_field",
     "struct Wrap:\n"
     "    var _data: List[Int]\n"
     "\n"
     "    def __init__(out self):\n"
     "        self._data = [5, 6, 7]\n"
     "\n"
     "    def clear(mut self):\n"
     "        self._data.clear()\n"
     "\n"
     "    def size(self) -> Int:\n"
     "        return len(self._data)\n"
     "\n"
     "def main(k):\n"
     "    var w = Wrap()\n"
     '    printf("before %d", w.size())\n'
     "    w.clear()\n"
     '    printf(" after %d", w.size())\n'
     "    return 0\n",
     "class Wrap:\n"
     "    def __init__(self):\n"
     "        self._data = [5, 6, 7]\n"
     "\n"
     "    def clear(self):\n"
     "        self._data.clear()\n"
     "\n"
     "    def size(self):\n"
     "        return len(self._data)\n"
     "\n"
     "import sys\n"
     "\n"
     "def main():\n"
     "    w = Wrap()\n"
     '    sys.stdout.write("before %d" % w.size())\n'
     "    w.clear()\n"
     '    sys.stdout.write(" after %d" % w.size())\n'
     "    return 0\n"),
# A BYTE BLOB is `[count][byte 0][byte 1]…` — one header word and ONE-BYTE
    # elements — and this case is the whole of that claim, on both machines.
    # Read `b[1]` and a word-stride blob answers 0 where CPython says 98, so
    # the expected output is a number only a one-byte-element lowering can
    # produce; and it is read off CPython by this file rather than written down,
    # which is what makes it an assertion about the layout rather than a
    # constant agreed with by hand. `test_formal_run.py`'s `constr_bytearray_*`
    # group is the rest of it (iteration, membership, append, and the `bytes`
    # refusal), and this row is what says the two machines build the SAME blob
    # from the same constructor — the property a one-sided assertion cannot see.
    ("bytearray_both_backends_build_it_identically",
     "def main():\n"
     "    var b = bytearray(4)\n"
     "    b[0] = 65\n"
     "    b[1] = 66\n"
     "    printf(\"%d %d %d %d %d\\n\", len(b), b[0], b[1], b[2], b[3])\n"
     "    return 0\n",
     "def main():\n"
     "    b = bytearray(4)\n"
     "    b[0] = 65\n"
     "    b[1] = 66\n"
     "    print(len(b), b[0], b[1], b[2], b[3])\n"
     "    return 0\n"),
    # THE CONTROL for the FRAME-slot refusal in `REFUSALS`
    # (`subscript_of_a_frame_slot_refused_identically`), and it is here rather
    # than there because it is ANSWERED, not refused: the gate is a KIND and a
    # field declared a CONTAINER is a container.  If the frame row had been
    # written as "a subscript of a field whose declared type is a struct of this
    # module, whatever it is", THIS is the row it would break — and it is the
    # same struct, the same frame and the same program with one field changed.
    # So the assertion is the number, and 22 is CPython's.
    ("subscript_of_a_list_slot_is_still_a_container_read",
     "struct Deep:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "struct Wrap:\n"
     "    var d: Deep\n"
     "    var xs: List[Int]\n"
     "\n"
     "def main():\n"
     "    var w = Wrap()\n"
     "    w.d.x = 3\n"
     "    w.d.y = 4\n"
     "    w.xs = [11, 22, 33]\n"
     '    printf("%d", w.xs[1])\n'
     "    return 0\n",
     "import sys\n"
     "\n"
     "class Deep:\n"
     "    def __init__(self):\n"
     "        self.x = 3\n"
     "        self.y = 4\n"
     "\n"
     "class Wrap:\n"
     "    def __init__(self):\n"
     "        self.d = Deep()\n"
     "        self.xs = [11, 22, 33]\n"
     "\n"
     "def main():\n"
     "    w = Wrap()\n"
     '    sys.stdout.write("%d" % w.xs[1])\n'
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
# …and the CONTROL for those three, which is a CASE rather than a refusal because
# nothing about its OUTPUT is wrong: an unclassified base keeps the container
# reading, and that is load-bearing. `INT_KIND` is this model's DEFAULT for a
# word, so a rule that read it as a claim would refuse every subscript over an
# unannotated parameter — 284 of them, measured, by the census
# `subscript_base_lowering`'s own docstring cites. This is the one program that
# says so, on both machines, with CPython's answer as the expectation.
CASES.append(
    ("a_subscript_on_an_unclassified_parameter_still_builds",
     "def at(xs, i):\n"
     "    return xs[i]\n"
     "\n"
     "def main():\n"
     "    print(at([4, 5, 6], 1))\n"
     "    return 0\n",
     "def at(xs, i):\n"
     "    return xs[i]\n"
     "\n"
     "def main():\n"
     "    print(at([4, 5, 6], 1))\n"
     "    return 0\n")
)

# A construct that leaves through a TRAP: every machine stops with a NONZERO
# status, and CPython raises.  That is a third shape, and it needs its own
# runner rather than a fourth flag on `run_case`, because `run_case` refuses an
# oracle that does not exit 0 — and this is precisely the class where the
# oracle cannot: every program here raises in CPython, so the traceback goes to
# stderr and CPython's own STDOUT is still exactly the expectation.  The
# assertion is therefore three things at once, and all three are needed:
#
#   * CPython exits nonzero, so the case is really about the exit path and not
#     about a construct one backend refuses to lower;
#   * both backends exit with CPython's status; and
#   * both backends' stdout is byte-identical to CPython's — which is the whole
#     assertion.  The two backends differ in HOW they leave (arm64's exit is a
#     raw Darwin trap, x86-64's is a call to the C library's `exit`, which
#     flushes), and stdout is block-buffered whenever it is not a terminal —
#     which is every case a test harness creates, `subprocess.run(
#     capture_output=True)` above all.  So a program that printed and then
#     trapped printed EVERYTHING on x86-64 and NOTHING on arm64: the output was
#     still in the buffer when the raw `SYS_exit` stopped the process.  Both
#     exited 1, both were "correct", and the two architectures disagreed about
#     what the program left on stdout.
#
# Why this is a COVERAGE statement and not a gap in either backend's coverage:
# `tools/formal_fuzz.py` compares against CPython, so every program that
# reaches one of these exits is recorded as a `generator-error` and never
# reaches an image.  A differential-against-CPython fuzzer structurally cannot
# see a bug the two backends do not SHARE — and only a parity file compares
# those two directly.  (Fixed on arm64 by `_emit_exit`, which flushes through
# the same `fflush(NULL)` the `flush=True` path already emits; x86-64 needed no
# change, because `exit` flushes and that asymmetry WAS the defect.)
FAILING_CASES = [
    # The subscript, which is the shape the doc that filed this measured.  The
    # OOB check is an emitter-side trap on this path (not CPython's own
    # IndexError in the image), which is why it is the case that shows the exit
    # flushing rather than the exception machinery.
    ("printed_output_survives_an_out_of_range_subscript",
     "def main() -> Int32:\n"
     "    print(\"before\")\n"
     "    xs = [1, 2, 3]\n"
     "    print(xs[7])\n"
     "    return 0\n",
     "def main() -> Int32:\n"
     "    print(\"before\")\n"
     "    xs = [1, 2, 3]\n"
     "    print(xs[7])\n"
     "    return 0\n"),
    # The same exit, reached by a different trap: a tuple unpack's runtime arity
    # check.  It is here because it rules out the alternative explanation.  If
    # the missing line were about the SUBSCRIPT — a lost diagnostic, a swallowed
    # print — this case would print `before` on both machines anyway, and one
    # case that agrees for a different reason is worth less than the two.
    # A BLOB right-hand side, not a literal: `a, b = (1,)` is refused at BUILD
    # time on arm64 ("tuple assignment length mismatch: 2 targets, 1 values"),
    # so the literal spelling never reaches the trap and would test the
    # build-time check rather than the exit.
    ("printed_output_survives_a_tuple_arity_check",
     "def main() -> Int32:\n"
     "    print(\"before\")\n"
     "    t = (1,)\n"
     "    a = 0\n"
     "    b = 0\n"
     "    a, b = t\n"
     "    return 0\n",
     "def main() -> Int32:\n"
     "    print(\"before\")\n"
     "    t = (1,)\n"
     "    a = 0\n"
     "    b = 0\n"
     "    a, b = t\n"
     "    return 0\n"),
]

REFUSALS = [
    # A SUBSCRIPT on a base the source proves to be a scalar. This is the
    # worst failure mode in the area — an image that SEGFAULTS with no
    # diagnostic — and it was not one shape but three, and the two machines did
    # not agree about any of them: x86-64 exited 139 on all three, arm64 refused
    # two of them with a message about the literal a one-field rewrite folded
    # the field to, and faulted on the third.
    #
    # The needle is the shared SENTENCE rather than the base, because the base is
    # what the two machines spelled differently (`5` against `s`) and what a
    # future rewrite of the one-field identity would move again. What has to be
    # pinned is that both say the base is not a container, in the same words.
    ("a_subscript_on_a_literal_field_faulted_identically",
     "struct S:\n"
     "    var n: Int = 5\n"
     "\n"
     "def main() -> Int:\n"
     "    var s = S()\n"
     "    printf(\"%d\", s.n[0])\n"
     "    return 0\n",
     "asks for a container element"),
    # The `DType` row, and the one that faulted on BOTH machines: the field is
    # established by the CONSTRUCTOR rather than by a class-level default, so
    # nothing folds to a literal and nothing refuses. A type's value is its tag
    # word, and a tag has no count and no elements.
    #
    # ONE field, and that is what this row is for rather than a shorter program:
    # a one-field struct's sole field is in `model.one_field_struct_names`, so
    # `_rewrite_self_fields` is entitled to collapse `self.d` onto `self` and
    # hand the emitter a bare `self` — which is the shape whose arm64 refusal
    # this file's first `REFUSALS` comment describes as "a message about the
    # literal a one-field rewrite folded the field to". The `__init__` is what
    # STOPS the fold here, because the slot's value is whatever the constructor
    # was handed, so `s.d` is still a `MemberExpr` when the gate sees it and the
    # FIELD arm of `scalar_container_base_evidence` is the one that answers.
    # Hence the needle, and hence why the sibling row below pins the SAME
    # sentence for the same construct: that one declares two fields, so it is not
    # in `one_field_struct_names` at all, and the two rows differ on the rewrite
    # rather than on the diagnostic.
    #
    # This row's needle was `is a TYPE value` — the NON-field arm's words, and an
    # arm this program does not reach. It is the row that is worth keeping a
    # non-field sibling for; that sibling is three rows down.
    ("a_subscript_on_a_type_value_faulted_identically",
     "struct S:\n"
     "    var d: DType = 5\n"
     "    def __init__(out self, v: DType):\n"
     "        self.d = v\n"
     "\n"
     "def main() -> Int:\n"
     "    var s = S(DType.int32)\n"
     "    printf(\"%d\", s.d[0])\n"
     "    return 0\n",
     "is a struct field declared to hold a TYPE TAG"),
    # … and the sibling that IS the non-field arm: a type VALUE rather than a
    # slot holding one. `scalar_container_base_evidence` has two `TYPE_KIND`
    # arms and they are different sentences — a field is "a struct field
    # declared to hold a TYPE TAG", anything else is "a TYPE value — the tag
    # word this path gives a type name" — so a needle taken from one of them
    # does not pin the other and a corpus that only builds fields leaves the
    # second arm unpinned.
    #
    # A LOCAL rather than a `DType`-annotated parameter on purpose: this is the
    # only spelling of a bare type value the gate classifies as `TYPE_KIND`. A
    # parameter declared `DType` is not classified as one and `t[0]` on it
    # BUILDS, which is a different defect with its own doc and is not what this
    # row is measuring.
    ("a_subscript_on_a_bare_type_value_faulted_identically",
     "def main() -> Int:\n"
     "    var t = DType.int32\n"
     "    printf(\"%d\", t[0])\n"
     "    return 0\n",
     "is a TYPE value"),
    # A CALLEE this backend does not lower, which used to stop at a link audit
    # that named a FILE and a SYMBOL and never the call — so a reader could not
    # tell whether to change the program or the link line, and the fuzz audit
    # filed every such refusal as `unnamed`. The needle is the sentence that
    # resolves it, not the symbol list, because the symbol list is the part both
    # machines already agreed on: what has to be pinned is the sentence that
    # says which of the two causes each name is.
    #
    # `sum` rather than `frobnicate` on purpose: the message must name a name
    # that IS a real construct, since a diagnostic quoted from a program that
    # spells nothing is exactly the shape the fuzz audit calls `unnamed`.
    ("an_unlowered_callee_names_the_call",
     "def main():\n"
     "    var xs = [1, 2, 3]\n"
     "    return sum(xs)\n",
     "is not lowered on this path"),
    ("aug_on_two_strings_refused_identically",
     "def main():\n"
     "    var a = [\"ab\", \"cd\"]\n"
     "    a[0] += \"x\"\n"
     "    printf(\"%d\\n\", len(a[0]))\n"
     "    return 0\n",
     "'+=' on two strings is refused"),
    # `@=` IS THE ONE AUGMENTED SPELLING NEITHER MACHINE LOWERS, and the needle
    # is the OPERATOR LIST rather than the words around it, because the two
    # messages necessarily differ in those: `formal/x86_64_codegen.py` says "on
    # the formal x86-64 path (supports …)" and its arm64 twin says "(formal
    # arm64 path supports …)".  Both build that list from `model.AUG_OPS`, so
    # this row is the anti-rot for that sharing: an edit that adds an operator to
    # one backend's own table instead of the shared constant makes the two
    # lists differ and this fails, which is the failure mode the shared
    # constant exists to prevent.
    #
    # It also says which spelling is left: `/=` `//=` `%=` `**=` were on this
    # list until the delegation that removed them, and `+= -= *= &= |= ^= <<=
    # >>=` never were.
    # THE `del` RESIDUE, and the reason it is a REFUSAL rather than a widening.
    # A `step` removes elements that are not adjacent (`del a[0:4:2]` removes
    # elements 0 and 2), so the contiguous shift-left the path would emit
    # produces a list of the right length and the wrong CONTENTS — which is the
    # same silent wrong answer as the no-op this group was written for, reached
    # by the other route. The needle is the word `step` and not the bounds,
    # because the two backends' bounds are the source's own text and the word
    # is the part a reader has to act on.
    ("del_stepped_slice_refused_identically",
     "def main():\n"
     "    var a = [1, 2, 3, 4]\n"
     "    del a[0:4:2]\n"
     "    return 0\n",
     "is not lowered on the formal path"),
    # A POINTER base, for the same reason and with a measurement in it:
    # `del p[0]` on a `malloc`'d buffer whose first word is 10 printed 9 on
    # arm64, because the first word was read as the COUNT and decremented
    # while the buffer's contents stayed put. There is no length to move
    # anything within, so this is refused rather than lowered.
    ("del_pointer_base_refused_identically",
     "def main():\n"
     "    var p: Pointer[Int] = malloc(64)\n"
     "    p[0] = 10\n"
     "    p[1] = 20\n"
     "    del p[0]\n"
     "    return 0\n",
     "the base is a POINTER"),
    ("aug_matmul_refused_with_the_same_operator_list",
     "def main():\n"
     "    var m = Mat()\n"
     "    m.v @= m.w\n"
     "    return m.v\n"
     "\n"
     "struct Mat:\n"
     "    var v: Int\n"
     "    var w: Int\n",
     "+ - * / // % & | ^ << >> **"),
    # A chain of typed-nested frames ONE LEVEL past what the layout sizes, and a
    # DECLARATION CYCLE, which is the case `MAX_NESTED_FRAME_DEPTH` is written
    # for.  Both used to build: the recursion's `depth <= 0` arm returned the
    # object's own bytes and DROPPED the frames below the cut, so the reserved
    # block came back short by exactly those frames, the blob cursor started
    # inside one, and the program took a SIGSEGV with no diagnostic naming the
    # file.  A bound that hangs is a bug; a bound that faults silently is
    # worse, and this row is the refusal both must now make instead.
    ("nested_frame_chain_past_the_depth_bound_refused",
     "struct S1:\n"
     "    var v: Int\n"
     "    var w: Int\n"
     "\n"
     "struct S2:\n"
     "    var v: Int\n"
     "    var n: S1\n"
     "\n"
     "struct S3:\n"
     "    var v: Int\n"
     "    var n: S2\n"
     "\n"
     "struct S4:\n"
     "    var v: Int\n"
     "    var n: S3\n"
     "\n"
     "struct S5:\n"
     "    var v: Int\n"
     "    var n: S4\n"
     "\n"
     "struct S6:\n"
     "    var v: Int\n"
     "    var n: S5\n"
     "\n"
     "def main():\n"
     "    var o = S6()\n"
     "    o.v = 1\n"
     "    printf(\"%d\", o.v)\n"
     "    return 0\n",
     "past the 4 levels this path lays out"),
    ("cyclic_nested_frames_refused",
     "struct A:\n"
     "    var x: Int\n"
     "    var b: B\n"
     "\n"
     "struct B:\n"
     "    var y: Int\n"
     "    var a: A\n"
     "\n"
     "def main():\n"
     "    var o = A()\n"
     "    o.x = 1\n"
     "    printf(\"%d\", o.x)\n"
     "    return 0\n",
     "past the 4 levels this path lays out"),
    # `bytes()` is the one byte-sequence constructor still refused, and the
    # refusal is the x86-64 half of a message arm64 prints too. The needle is
    # the clause naming what to write instead — `bytearray` IS the blob on this
    # path, and the two byte sequences being told apart by which blob they are
    # is the decision `bytearray_both_backends_build_it_identically` below
    # exercises.
    #
    # Before the element width was decided, all four spellings reached the bind
    # audit as a dangling extern named `bytearray`/`bytes`, so both machines
    # "built" them and the build failed about a SYMBOL — a fact about the link
    # line rather than about the type the reader wrote.
    ("bytes_constructor_refused_identically",
     "def main():\n"
     "    var b = bytes()\n"
     "    printf(\"%d\", 1)\n"
     "    return 0\n",
     "The MUTABLE byte blob is `bytearray`"),
    # `bytes_constructor_refused_identically` below is the refusal direction:
    # the two byte-sequence names are told apart by WHICH blob each builds, and
    # the row above is the construction that has to agree on both machines.
    # A SUBSCRIPT OF A FRAME SLOT, and this group is where the disagreement
    # lived: `s.n` on a field declared `Int` was REFUSED on arm64 and SIGSEGV'd
    # (exit 139) on x86-64, and with the field constructor-established BOTH
    # machines crashed.  CPython refuses all three (`TypeError: 'int' object is
    # not subscriptable`), so the correct answer is a refusal on both and one
    # machine was dereferencing a `5`.
    #
    # The needle is the BASE'S SPELLING and not the refusal's wording, because
    # the wording was the defect in the first half: arm64 refused at an emitter
    # gate that reports the node it was HANDED, and by then `s.n` had been
    # rewritten to the slot's materialized class-level default, so the message
    # said "got IntLiteral" about a source that says `s.n`.  A reader sent to
    # look for an `IntLiteral` in a file that has none is the C5 failure this
    # project's diagnostics exist to stop.
    # commit f0df70b2.
    ("subscript_of_a_slot_declared_an_int_refused_identically",
     "struct S:\n"
     "    var n: Int = 5\n"
     "    var t: Int = 6\n"
     "\n"
     "def main():\n"
     "    var s = S()\n"
     '    printf("%d", s.n[0])\n'
     "    return 0\n",
     "a subscript of `s.n` asks for a container element"),
    # The same shape with a `DType` field, which is a TYPE TAG rather than an
    # integer and therefore a different word in the message — so the needle here
    # is the KIND clause and it is a separate row for that reason rather than
    # for the shape.
    ("subscript_of_a_dtype_slot_refused_identically",
     "struct S:\n"
     "    var d: DType = 5\n"
     "    var t: Int = 6\n"
     "\n"
     "def main():\n"
     "    var s = S()\n"
     '    printf("%d", s.d[0])\n'
     "    return 0\n",
     "is a struct field declared to hold a TYPE TAG"),
    # ── the FRAME slot, which is the same family and the one whose wrong answer
    # is a NUMBER rather than a fault. `FRAME_KIND` was deliberately kept OUT of
    # `model.NON_CONTAINER_SLOT_KINDS` until 2026-10-04, on the reasoning that a
    # frame is a wrong ANSWER rather than a fault and therefore its own defect.
    # The reasoning was right and the exclusion was untenable: the answer was
    # measured, it is a number, and the two machines do not even agree on it.
    #
    #   struct Deep:  var x: Int;  var y: Int
    #   struct Wrap:  var d: Deep;  var t: Int
    #   w.d.x = 3 ; w.d.y = 4 ; printf("%d", w.d[0])
    #
    # | | arm64 | x86-64 |
    # |---|---|---|
    # | `w.d[0]` | 4, exit 0 | 4, exit 0 |
    #
    # and 4 is `Deep`'s SECOND field, which is the arithmetic rather than an
    # accident: `count = mem_read_u64(w + 0)` is the first field, so the walk
    # bound-checks the index against `x` and then reads `w + 8 + 8·x`.  The
    # needle is the base's SPELLING for the reason the two rows above give, and
    # the KIND clause differs from all three of theirs, so it is a separate row.
    ("subscript_of_a_frame_slot_refused_identically",
     "struct Deep:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "struct Wrap:\n"
     "    var d: Deep\n"
     "    var t: Int\n"
     "\n"
     "def main():\n"
     "    var w = Wrap()\n"
     "    w.d.x = 3\n"
     "    w.d.y = 4\n"
     '    printf("%d", w.d[0])\n'
     "    return 0\n",
     "a subscript of `w.d` asks for a container element"),
    # THE CONTROL, and it is the row that carries the decision: when the
    # declared struct declares `__getitem__` the subscript is a METHOD CALL and
    # not a slot load, so `w.d[i]` cannot be given the answer `w.d.x` already has
    # without one spelling meaning two things.  This program is the corpus's own
    # shape — `std/collections/dict.mojo`'s `StringDict.__getitem__` is
    # `return self._dict[key]` — and it is the ONLY row in the corrected
    # `scalar_container_base_evidence` census that reaches FRAME_KIND (2 of 537
    # `X.<field>[i]` sites, both this one).  Measured before the refusal, from a
    # GREEN build, exit 0 on both:
    #
    # | | arm64 | x86-64 |
    # |---|---|---|
    # | `h.d[1]` | 0 | **-1927469536** |
    #
    # Two architectures, two different wrong answers, neither of which is a slot
    # load — so a refusal is strictly better than either lowering, and the
    # alternative the doc weighed (`base + 8i`) is not one lowering but two.
    ("subscript_of_a_frame_slot_with_getitem_refused_identically",
     "struct Deep:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __getitem__(self, k: Int) -> Int:\n"
     "        return self.a + k\n"
     "\n"
     "struct Hold:\n"
     "    var d: Deep\n"
     "    var t: Int\n"
     "\n"
     "def main():\n"
     "    var h = Hold()\n"
     "    h.d.a = 3\n"
     "    h.d.b = 4\n"
     '    printf("%d", h.d[1])\n'
     "    return 0\n",
     "a subscript of `h.d` asks for a container element"),
    # …and the one that CRASHED ON BOTH, which is its own row because it is the
    # only one of the three whose kind is not established by a DECLARATION: the
    # slot holds a tag because the CONSTRUCTOR put one there, so
    # `struct_field_kind`'s third door has to be open for it.
    # `ValueKinds._constructed_field_kind` requires the constructor argument's
    # own kind to be evidence, and `DType.int32` classified as nothing — the
    # same "one value, two kinds, decided by where the name is written" the
    # `DTYPE_TYPE_NAMES` row records one level out, moved one level further in.
    # `_kind_of_simple` asks `type_value_tag` for it now.
    ("subscript_of_a_constructor_established_dtype_slot_refused_identically",
     "struct S:\n"
     "    var d: DType\n"
     "    var t: Int\n"
     "\n"
     "    def __init__(out self, v: DType):\n"
     "        self.d = v\n"
     "        self.t = 7\n"
     "\n"
     "def main():\n"
     "    var s = S(DType.int32)\n"
     '    printf("%d", s.d[0])\n'
     "    return 0\n",
     "is a struct field declared to hold a TYPE TAG"),
    # The other direction of the `clear` row above, and the one that says the
    # KIND guard is load-bearing rather than decorative: the same `clear()` on a
    # field whose value the constructor takes from a PARAMETER.  The store is
    # one word at offset 0 of the receiver, so on a word this image cannot
    # establish to be a list's header it writes zero into whatever address that
    # word holds — which is a silent wrong answer in a program that runs.
    #
    # The receiver's kind is `'int'` and not `None` because
    # `ValueKinds`'s default for an unannotated word is an integer, and the
    # message names that rather than shrugging: the reader is looking at a
    # `List[Int]` declaration two lines above and the sentence has to explain why
    # it is not being used.
    ("clear_of_a_receiver_this_image_cannot_call_a_list_refused_identically",
     "struct Wrap:\n"
     "    var _data: List[Int]\n"
     "\n"
     "    def __init__(out self, xs: List[Int]):\n"
     "        self._data = xs\n"
     "\n"
     "    def clear(mut self):\n"
     "        self._data.clear()\n"
     "\n"
     "def main(k):\n"
     "    var xs = [5, 6, 7]\n"
     "    var w = Wrap(xs)\n"
     "    w.clear()\n"
     "    return 0\n",
     "lowers to one store of zero at offset 0 of its receiver"),
    # A FRAME-valued FIELD read as a container.  `w.d` is `Deep`'s frame BASE,
    # so `w.d[0]` means `Deep`'s first field and the blob walk answered
    # something else: it read offset 0 of the base as the container's COUNT,
    # computed `base + 8 + 8*count` from it, and read THAT — with `x = 3` in
    # slot 0, `w + 32`, which is past `Deep`'s two slots.  Both machines printed
    # 4, out of the frame's scratch region, and the build was green.
    #
    # The needle names the FRAME rather than a slot or a count, because that is
    # the part the reader acts on: the declaration `var d: Deep` is two lines
    # above the use, and `w.d.x` is the same program with a name where the
    # index is.  A needle about the arithmetic would name a number the reader
    # never wrote.
    #
    # It is a REFUSAL rather than a lowering at `base + 8i` because the index is
    # not a field name: slot `i` is the struct's `i`-th declared field while
    # `i` is inside them and a spill slot past that, so the bound that would
    # make it an answer is one this path would have to invent for a program
    # CPython refuses outright.  `formal/model.py`'s `frame_slot_element_refusal`
    # has the argument and the corpus census; this row is the anti-rot for the
    # two emitters asking it at the same point, which is after the dict and
    # string readings and not beside the scalar-field gate.
    ("a_subscript_of_a_field_declared_a_framed_struct_refused_identically",
     "struct Deep:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "struct Wrap:\n"
     "    var d: Deep\n"
     "    var t: Int\n"
     "\n"
     "def main() -> Int:\n"
     "    var w = Wrap()\n"
     "    w.d.x = 3\n"
     "    w.d.y = 4\n"
     "    printf(\"%d\", w.d[0])\n"
     "    return 0\n",
     "offset 0 of a frame is that struct's FIRST FIELD"),
    # The same refusal from the OTHER three choke points, because
    # `_refuse_frame_slot_element` is asked at four of them and a gate that
    # covers the subscript alone leaves a for-in iteration to read the frame's
    # first field as a count.  One row per op is what keeps the four from
    # drifting apart; the needles differ by the leading words the message builds
    # from the op, so each names its own.
    ("a_for_in_iteration_of_a_frame_field_refused_identically",
     "struct Deep:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "struct Wrap:\n"
     "    var d: Deep\n"
     "    var t: Int\n"
     "\n"
     "def main() -> Int:\n"
     "    var w = Wrap()\n"
     "    var t = 0\n"
     "    for f in w.d:\n"
     "        t = t + f\n"
     "    printf(\"%d\", t)\n"
     "    return 0\n",
     "a for-in iteration of `w.d` asks for a container element"),
    ("a_membership_test_against_a_frame_field_refused_identically",
     "struct Deep:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "struct Wrap:\n"
     "    var d: Deep\n"
     "    var t: Int\n"
     "\n"
     "def main() -> Int:\n"
     "    var w = Wrap()\n"
     "    printf(\"%d\", 3 in w.d)\n"
     "    return 0\n",
     "a membership test of `w.d` asks for a container element"),
    ("a_slice_of_a_frame_field_refused_identically",
     "struct Deep:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "struct Wrap:\n"
     "    var d: Deep\n"
     "    var t: Int\n"
     "\n"
     "def main() -> Int:\n"
     "    var w = Wrap()\n"
     "    var s = w.d[0:1]\n"
     "    printf(\"%d\", len(s))\n"
     "    return 0\n",
     "a slice of `w.d` asks for a container element"),
]

# The other direction, and it is a PER-PLATFORM limit rather than a shared one,
# is where this file USED to end.  A nine-argument call was refused on x86-64
# and answered on arm64: AAPCS passes arguments 0..7 in registers and the rest in
# the caller's frame, SysV AMD64 passes 0..5 and the rest in the caller's frame,
# and only AAPCS's half was implemented here.  That limit was pinned in a group
# of its own (`X86_ONLY_REFUSALS`, built on x86-64 alone and required to refuse)
# so that it would read as a STATED LIMIT rather than an oversight — and it was:
# when the SysV stack area landed, that group started failing and said why.
#
# The group is gone and its subject is five `CASES` rows instead, because the
# interesting property is not "x86-64 refuses this" but "the two machines put the
# seventh argument in DIFFERENT PLACES and both deliver it".  A one-sided
# assertion stays green through the whole class of defect a stack-argument
# convention can have — the caller's `SUB`/`store`/`ADD`, or the callee's
# `[RBP + 16 + 8k]` load — because the machine not using the frame cannot see
# any of it.  `run_x86_refusal` went with it: it existed for that one limit, and
# a runner with no case is a runner to maintain.


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


def run_failing_case(name, mojo_src, cpython_src, tmpdir, verbose):
    """A program every machine exits NONZERO on: stdout must still be CPython's.

    The three assertions are in `FAILING_CASES`'s own comment.  The order
    matters: the oracle's exit status is checked before either image is built,
    so a case that stopped raising (the construct gained an in-band error
    report, say) fails as "the oracle now exits 0" rather than as two machines
    quietly agreeing on something CPython no longer does.
    """
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(mojo_src)
    want_exit, want_out = cpython_answer(cpython_src, tmpdir, name)
    if want_exit == 0:
        return False, ("CPython now exits 0 for this program, so it no longer "
                       "exercises an exit path and belongs in CASES, where a "
                       "successful run is compared instead")
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build(src, out, backend)
        if rc != 0:
            return False, (f"--backend={backend} did not build: "
                           f"{text.strip()[-300:]}")
        r = run(out, backend)
        if r.returncode != want_exit:
            return False, (f"--backend={backend} exited {r.returncode}, CPython "
                           f"exits {want_exit}; stderr: {r.stderr.strip()[:160]}")
        if r.stdout != want_out:
            return False, (
                f"--backend={backend} printed {r.stdout[:120]!r} where CPython "
                f"prints {want_out[:120]!r} — its exit does not flush what the "
                f"program printed, so the line is LOST rather than wrong")
        if verbose:
            print(f"      {backend}: {r.stdout[:60]!r} exit={r.returncode} "
                  f"(CPython agrees)")
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
        for name, _s, _c in FAILING_CASES:
            print(f"  case    {name}  (exits nonzero on every machine)")
        for name, _s, needle in REFUSALS:
            print(f"  refusal {name}  ({needle!r})")
        return 0

    known = ({c[0] for c in CASES} | {c[0] for c in REFUSALS}
             | {c[0] for c in FAILING_CASES})
    wanted = ([(c, "case") for c in CASES]
              + [(c, "failing") for c in FAILING_CASES]
              + [(c, "refusal") for c in REFUSALS])
    if args.cases:
        missing = set(args.cases) - known
        if missing:
            print(f"ERROR: unknown case(s): {sorted(missing)}", file=sys.stderr)
            return 2
        wanted = [c for c in wanted if c[0][0] in args.cases]

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for (name, mojo_src, third), kind in wanted:
            try:
                if kind == "refusal":
                    ok, detail = run_refusal(name, mojo_src, third, tmpdir,
                                             args.verbose)
                elif kind == "failing":
                    ok, detail = run_failing_case(name, mojo_src, third, tmpdir,
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
