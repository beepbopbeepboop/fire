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
    # `len` is on this list because the two architectures answered it the SAME
    # wrong way, which is the shape a one-backend fix would hide: `_emit_call`
    # special-cased `range` and treated every other callee as a known function
    # or an extern, and `len` matched neither, so it became a call to a libc
    # symbol that does not exist.  Both backends therefore returned whatever
    # the call left in the return register — measured, -6 for `len(range(10))`
    # on BOTH — and one architecture being right would have been as much a bug
    # as both being wrong.  (`bugs/FORMAL_x86_64_formal_backend_gaps.md`.)
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
    # (`bugs/FORMAL_x86_64_argument_registers.md`, now deleted).  It is one call
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
    # ── THE STACK-ARGUMENT CONVENTION ───────────────────────────────────────────
    #
    # AAPCS passes arguments 0..7 in registers and the rest in the caller's frame;
    # SysV AMD64 passes 0..5 and the rest in the caller's frame, so a SEVEN-
    # argument function travels in a register on one architecture and in MEMORY on
    # the other.  Both conventions are implemented now
    # (`formal/x86_64_codegen.py`'s `_load_home_from_stack`/`_emit_call` and
    # `_MAX_INCOMING_ARGS` on both backends), which is what
    # `bugs/FORMAL_x86_64_argument_registers.md` asked for, and which is deleted;
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
    # bugs/FORMAL_arm64_set_union_result_blob_has_the_wrong_count.md.
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
