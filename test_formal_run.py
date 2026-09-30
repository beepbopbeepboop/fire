#!/usr/bin/env python3
"""Build formal-backend executables and RUN them, checking the answers.

test_formal.py only ever typechecks the generated proof; it never executes the
binary, which is why an entire class of Mach-O emission bugs could sit there
green: images dyld refused to load (SIGKILL at exec), an LC_CODE_SIGNATURE that
landed on the first instructions, a GOT slot nothing ever bound so the call stub
branched through zero. Every one of those produced a *correct proof* about code
that could not run.

This suite executes instead. Each case names the exit status (and stdout) the
program must produce, so "it linked" and "it computed the right answer" are
separate assertions. Grounded in what clang/ld emits: a working image and a
broken one differ in load-command details, and this is the test that notices.

    python3 test_formal_run.py [-v] [case ...]
"""
import argparse
import os
import platform
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 120
RUN_TIMEOUT = 60

# (name, source, expected exit status, expected stdout substring)
#
# The first two are the "does anything run at all" cases: before the Mach-O
# layout fixes in formal/macho_linker.py, every executable this suite builds was
# killed by the kernel at exec with no output at all. `printf` is the case that
# covers the whole extern path — stubs, __DATA_CONST,__got, and the classic dyld
# bind opcodes that fill the GOT slot the stub branches through.
CASES = [
    ("ret42", "def ret42():\n    return 42\n", 42, None),
    # Comparisons involving a NEGATIVE value. A bare literal takes its type
    # from context, and with both operands typeless the comparison came out
    # unsigned -- so `-3` was 0xFFFF...FD and `-3 < 2` was false. Two places
    # had to change: `infer_expr` reports a negated literal signed, and a
    # range's counter is no longer seeded with the (unsigned) default, which
    # made EVERY range unsigned regardless of its bounds.
    # The third case guards the other direction: an all-positive comparison
    # must still be unchanged.
    ("neg_cmp_true", "def f(n):\n    a = -3\n    if a < 2:\n        return 1\n"
     "    return 0\n", 1, None),
    ("neg_cmp_zero", "def f(n):\n    a = -3\n    if a < 0:\n        return 1\n"
     "    return 0\n", 1, None),
    ("pos_cmp_still_false", "def f(n):\n    a = 3\n    if a < 2:\n"
     "        return 1\n    return 0\n", 0, None),
    # ── the SIGNEDNESS matrix (bugs/CODEGEN_arm64_cmp_flags_and_loop_signedness) ──
    #
    # Unannotated `int` used to be modelled as UInt64 and `common_type`
    # resolved a mixed signed/unsigned pair to unsigned, so any comparison
    # involving a negative value and a VARIABLE read the negative as a huge
    # positive number.  The two cases the previous fix (negated literal vs
    # literal) did not reach are the two that mattered: a negative produced by
    # arithmetic (`0 - 3`, a BinaryOp, so typeless) and a negative against an
    # unannotated local.  Every row below is a real build + run; the exit status
    # is the program's answer and must be 1.
    #
    # The unsigned control cases are here on purpose: a signed default must not
    # quietly turn an `UInt32` comparison into a signed one, so `pos_still_works`
    # and `uint_still_unsigned` are the rows that would catch an over-correction.
    ("binop_neg_vs_lit",
     "def main(n):\n    a = 0 - 3\n    if a < 2:\n        return 1\n    return 0\n", 1, None),
    ("neg_lit_vs_var",
     "def main(n):\n    a = -3\n    b = 2\n    if a < b:\n        return 1\n    return 0\n", 1, None),
    # The INVERSION: the same pair the other way round. A fix that made `<`
    # signed without touching `>` would pass the row above and fail this one.
    ("neg_lit_vs_var_gt",
     "def main(n):\n    a = -3\n    b = 2\n    if a > b:\n        return 1\n    return 0\n", 0, None),
    ("var_vs_neg_lit",
     "def main(n):\n    b = 2\n    if b > -3:\n        return 1\n    return 0\n", 1, None),
    ("neg_vs_neg",
     "def main(n):\n    a = -7\n    b = -9\n    if a > b:\n        return 1\n    return 0\n", 1, None),
    # Narrow signed types, against an unannotated local: the width is not the
    # issue, the signedness is, and a per-width annotation must not fall back to
    # the (formerly unsigned) default.
    ("int8_neg_vs_var",
     "def main(n):\n    a: Int8 = -3\n    b = 2\n    if a < b:\n        return 1\n    return 0\n", 1, None),
    ("int16_neg_vs_var",
     "def main(n):\n    a: Int16 = -3\n    b = 2\n    if a < b:\n        return 1\n    return 0\n", 1, None),
    ("int32_neg_vs_var",
     "def main(n):\n    a: Int32 = -3\n    b = 2\n    if a < b:\n        return 1\n    return 0\n", 1, None),
    # The three other signedness-sensitive operations, not just the comparison:
    # an arithmetic shift, a truncating division/remainder pair, and the format
    # a negative value prints with. Each of these read the value through the
    # signedness decision too, and each was unsigned before.
    ("arith_shift_negative",
     "def main(n):\n    a = -8\n    b = a >> 2\n    if b == 0 - 2:\n        return 1\n    return 0\n", 1, None),
    ("print_negative",
     "def main(n):\n    a = -7\n    printf(\"%d\\n\", a)\n    return 3\n", 3, "-7"),
    ("neg_div_rem",
     "def main(n):\n    a = 0 - 7\n    if a / 2 == 0 - 3 and a % 2 == 0 - 1:\n        return 1\n    return 0\n", 1, None),
    ("neg_mod",
     "def main(n):\n    a = 0 - 7\n    b = a % 3\n    if b == 0 - 1:\n        return 1\n    return 0\n", 1, None),
    # Controls.
    ("pos_still_works",
     "def main(n):\n    a = 3\n    b = 2\n    if a > b:\n        return 1\n    return 0\n", 1, None),
    ("uint_still_unsigned",
     "def main(n):\n    a: UInt32 = 7\n    b: UInt32 = 2\n    if a > b:\n        return 1\n    return 0\n", 1, None),
    # Counted, not summed: the sum is -5, and every expected value in this
    # suite must fit in a byte (see the retraction in BUG.md).
    ("range_neg_bounds", "def f(n):\n    s = 0\n    c = 0\n"
     "    for i in range(-3, 2):\n        s = s + i\n        c = c + 1\n"
     "    return c\n", 5, None),
    # Spilling, not just register allocation. `_spill_off` is the distance DOWN
    # to a slot, and the LDUR/STUR fast path was passing it as a POSITIVE
    # displacement: `stur x0, [x29, #+0x58]` stores ABOVE the frame pointer,
    # inside the CALLER's frame. Every function with more locals than the ten
    # callee-saved registers silently corrupted its caller and returned a
    # wrong number -- 15 locals summed to 237 instead of 120.
    ("spills_15_locals",
     "def f(n):\n" + "".join(f"    v{i} = {i + 1}\n" for i in range(15))
     + "    return " + " + ".join(f"v{i}" for i in range(15)) + "\n",
     120, None),
    ("spills_22_locals",
     "def f(n):\n" + "".join(f"    v{i} = {i + 1}\n" for i in range(22))
     + "    return " + " + ".join(f"v{i}" for i in range(22)) + "\n",
     253, None),
    # One spilled variable on its own: the smallest case that reaches the
    # spill path at all, so a regression in the offset sign cannot hide behind
    # a function that never spills.
    ("spills_one_local",
     "def f(n):\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    e = 5\n"
     "    g = 6\n    h = 7\n    i = 8\n    j = 9\n    k = 10\n    l = 11\n"
     "    return l + k + j\n", 30, None),
    # for-range loops. The exit test is the whole loop: before it, the
    # lowering computed a CSET and never branched on it, so EVERY one of these
    # hung rather than returning a wrong number -- which is why they need to be
    # here and not left to the range tests that only existed inside
    # comprehensions.
    ("for_range_sum", "def f(n):\n    s = 0\n    for i in range(3, 9):\n"
                      "        s = s + i\n    return s\n", 33, None),
    ("for_range_empty", "def f(n):\n    s = 0\n    for i in range(5, 5):\n"
                        "        s = s + 1\n    return s\n", 0, None),
    ("for_range_desc", "def f(n):\n    s = 0\n    for i in range(4, 0, -1):\n"
                       "        s = s + i\n    return s\n", 10, None),
    ("for_range_step2", "def f(n):\n    s = 0\n    for i in range(7, 1, -2):\n"
                        "        s = s + i\n    return s\n", 15, None),
    ("for_range_one_arg", "def f(n):\n    s = 0\n    for i in range(4):\n"
                          "        s = s + i\n    return s\n", 6, None),
    ("for_range_nested", "def f(n):\n    s = 0\n    for i in range(2):\n"
                         "        for j in range(3):\n            s = s + 1\n"
                         "    return s\n", 6, None),
    ("for_range_break", "def f(n):\n    for i in range(0, 100):\n"
                        "        if i > 3:\n            break\n"
                        "    return i\n", 4, None),
    ("seven", "def seven():\n    return 7\n", 7, None),
    ("absval", "def absval(n):\n    if n > 0:\n        return n\n"
               "    else:\n        return 0 - n\n", 10, None),
    ("fib", "def fib(n):\n    if n <= 1:\n        return n\n"
            "    else:\n        return fib(n - 1) + fib(n - 2)\n", 55, None),
    ("hello", 'def hello(n):\n    printf("hello from mojo")\n    return 0\n',
     0, "hello from mojo"),
    ("two_calls", 'def two(n):\n    printf("one")\n    printf("two")\n'
                 '    return 5\n', 5, "onetwo"),
    # `comptime f(...)` is resolved by COMPILING f with this same backend and
    # calling it at compile time (formal/comptime_runner.py), so a folded
    # constant and the code emitted for the same expression cannot come from
    # two different implementations. The callee here has a loop and a nested
    # call, and the second binding is fed by the first, so this covers the
    # whole path: run the callee, fold its result, fold arithmetic over that
    # result, and emit the branch the folded condition selects.
    # The entry function is the FIRST one in the file, so it comes first here
    # and the comptime callees it folds follow.
    # `len` is a builtin and has to be intercepted in the call path, the same
    # way `range` is. It had no coverage at all: left to the extern path it
    # became a BL against a symbol `len` that libSystem does not define, so
    # the image built and then aborted in the loader with "Symbol not found:
    # _len". A list is a `[count][elements]` blob, so the answer is one load
    # from offset 0 — and the tuple and range cases check it is the COUNT and
    # not, say, the last element or the address.
    ("len_list", "def len_list(n):\n    return len([1, 2, 3, 4])\n",
     4, None),
    ("len_range", "def len_range(n):\n    return len(range(10))\n",
     10, None),
    ("len_empty", "def len_empty(n):\n    return len([])\n", 0, None),
    ("len_nested", "def len_nested(n):\n"
                   "    return len([[1, 2], [3, 4, 5]])\n", 2, None),
    ("len_sum", "def len_sum(n):\n"
                "    xs = [1, 2, 3]\n    return len(xs) + len(range(4))\n",
     7, None),
    # Comprehensions. These were all SIGSEGV, and the cause was not the
    # nesting BUG.md suspected: the walk that allocates a comprehension's
    # control temps was handed the statement LIST and only recursed through
    # __dataclass_fields__, which a list does not have — so it returned
    # immediately and no temp was ever allocated. Both temps then fell through
    # _store_var/_load_var's unknown-name path, which uses X19, so the loop's
    # blob base and its index shared one register and the index store
    # destroyed the base. Every comprehension then read `ldr xN, [x0]`.
    #
    # The single-generator cases are here because the bug was NOT
    # nesting-specific — one generator failed exactly as hard as two.
    ("compr_single", "def compr_single(n):\n"
                     "    xs = [i for i in range(3)]\n"
                     "    t = 0\n"
                     "    for x in xs:\n        t = t + x\n"
                     "    return t\n", 3, None),
    ("compr_nested", "def compr_nested(n):\n"
                     "    xs = [i + j for i in range(2) for j in range(2)]\n"
                     "    t = 0\n"
                     "    for x in xs:\n        t = t + x\n"
                     "    return t\n", 4, None),
    ("compr_nested3", "def compr_nested3(n):\n"
                      "    return len([i * 10 + j for i in range(3) "
                      "for j in range(2)])\n", 6, None),
    # Bound to a local first: subscripting a comprehension DIRECTLY
    # (`[i for i in ...][2]`) is a separate, still-open gap — the subscript
    # path wants a list/tuple name or literal as its base. Tracked in BUG.md.
    ("compr_over_literal", "def compr_over_literal(n):\n"
                           "    xs = [i * 2 for i in [1, 2, 3]]\n"
                           "    return xs[2]\n", 6, None),
    ("compr_condition", "def compr_condition(n):\n"
                        "    return len([i for i in range(6) if i > 3])\n",
     2, None),
    # A comprehension nested inside a for-loop, so the comprehension temps and
    # the for-list temps have to coexist without aliasing each other.
    ("compr_in_for", "def compr_in_for(n):\n"
                     "    t = 0\n"
                     "    for k in [1, 2]:\n"
                     "        xs = [j for j in range(2)]\n"
                     "        t = t + xs[1]\n"
                     "    return t\n", 2, None),
    # `range(n)` with a RUNTIME bound, as a value. Its epilogue used to drop
    # the loop's start/stop/step with `ldp_sp_post` — which writes X0 — after
    # the blob address had been put there, so the function returned `start`
    # (0) instead of its result.
    ("len_runtime_range", "def len_runtime_range(n):\n"
                          "    return len(range(n))\n", 10, None),
    # A one-field struct whose field is written as a CLASS-LEVEL ASSIGNMENT,
    # which the parser keeps in `StructDef.fields` as an `AssignStmt` rather
    # than the `VarDecl` an annotation produces. Both spellings are one field,
    # so both must collapse to the same one word: the field name is read out of
    # the node to decide that, and reading `.name` off the `AssignStmt` shape
    # aborted the whole build with a Python traceback (the field-name lookup
    # now goes through formal.model.struct_field_name, which knows both
    # shapes). Run rather than merely built, because the collapse is an
    # identity the answer depends on: `c.count = n` then `c.get()` has to come
    # back as n, which it only does if `self.count` really became `self`.
    ("struct_field_assign_default", "struct Counter:\n"
                                    "    count = 0\n\n"
                                    "    def get(self):\n"
                                    "        return self.count\n\n"
                                    "def main(n):\n"
                                    "    c = Counter()\n"
                                    "    c.count = n\n"
                                    "    return c.get()\n", 10, None),
    # The same field declared with an annotation AND a default, which is the
    # other node shape (an `AssignStmt` carrying `type_ann`) and the shape
    # every dataclass-style field in this repo's own source takes.
    ("struct_field_ann_default", "struct Counter:\n"
                                 "    count: Int = 0\n\n"
                                 "    def get(self):\n"
                                 "        return self.count\n\n"
                                 "def main(n):\n"
                                 "    c = Counter()\n"
                                 "    c.count = n\n"
                                 "    return c.get()\n", 10, None),
    # A PYTHON-STYLE class: it declares nothing, and its one field is whatever
    # `__init__` assigns. The width has to be DERIVED from the methods for this
    # to be the one-word case it plainly is. It was not: reading only
    # `StructDef.fields` measured zero fields, so the struct looked like a
    # marker, `c.n` and `self.n` became two unrelated words that merely shared
    # a spelling, and every accessor returned an uninitialised register. This
    # program returned 0.
    #
    # TWO instances, deliberately: it is the stronger half of the claim. The
    # receiver IS the field, so the collapse has to keep them distinct — a
    # lowering that got this right by making the field a single global would
    # pass a one-instance version of this test.
    ("pyclass_field_from_init", "class Counter:\n"
                                "    def __init__(self):\n"
                                "        self.n = 0\n\n"
                                "    def get(self):\n"
                                "        return self.n\n\n"
                                "def main(n):\n"
                                "    a = Counter()\n"
                                "    a.n = n\n"
                                "    b = Counter()\n"
                                "    b.n = n + 1\n"
                                "    return a.get() * 100 + b.get()\n", 243, None),
    # The other half of the Python spelling: a class that only ever READS its
    # field, because the CALLER writes it. Reading `self.n` declares a field
    # exactly as much as assigning it does, and a census taken from the
    # assignments alone called this a zero-field marker — after which the
    # method read a slot nothing had ever written. This returned 0.
    ("pyclass_field_read_only", "class Cell:\n"
                                "    def get(self):\n"
                                "        return self.n\n\n"
                                "def main(n):\n"
                                "    c = Cell()\n"
                                "    c.n = n\n"
                                "    return c.get()\n", 10, None),
    # …and the same spelling with `__slots__`, which is a class-level
    # assignment that NAMES fields rather than storing one. Counted as a field
    # in its own right it made this class look two fields wide and the build
    # was refused; counted for what it says it is, it is one field and one
    # word. The refusal this replaces was at least honest, so this case is
    # here to stop the honest limit from being wider than the truth.
    ("pyclass_slots_field", "class Cell:\n"
                            "    __slots__ = (\"n\",)\n\n"
                            "    def get(self):\n"
                            "        return self.n\n\n"
                            "def main(n):\n"
                            "    c = Cell()\n"
                            "    c.n = n\n"
                            "    return c.get()\n", 10, None),
    # The other side of the same line, and it used to be a REFUSAL: a class
    # with two fields had nothing to be as a one-word value, so `c.a` and
    # `c.b` could not both exist. It is now a frame of two 8-byte slots with
    # the receiver holding its ADDRESS, which is still one word, so the value
    # model is untouched and this builds and RUNS. Both directions matter:
    # a write at the call site (`p.a = 1`) and a write through the receiver
    # (`p.b = 2`, inside a method) land in the same frame and the accessor
    # reads back the sum, so the answer 3 is the sum of the two writes and not
    # of anything else. The same source with the receiver switch OFF is
    # `wide_off_pair_two_fields`, which still refuses by name.
    ("pyclass_two_fields",
     "class Pair:\n"
     "    def __init__(self):\n"
     "        self.a = 1\n"
     "        self.b = 2\n\n"
     "    def set_b(self, v):\n"
     "        self.b = v\n\n"
     "    def total(self):\n"
     "        return self.a + self.b\n\n"
     "def main(n):\n"
     "    p = Pair()\n"
     "    p.a = 1\n"
     "    p.set_b(2)\n"
     "    return p.total()\n", 3, None),
    # The refusal above has to be the SAME refusal on both backends. They used
    # to disagree about struct construction outright: arm64 refused a two-field
    # `Point()` while x86-64 emitted a `call _Point` against a symbol nothing
    # defines, built the image, and let dyld kill it at launch ("Symbol not
    # found: _Point"). One source, two architectures, and only one of them said
    # no — so the check is that both now refuse, with the same words.
    # A direct field write at the call site AND a write through a method, then
    # two reads back: the method's write wins (9), and all three reads are the
    # same frame, so 9 + 9 + 9 = 27 and not 5 + 9 + 9. The old expectation of
    # 23 was the arithmetic of a program where the two spellings were two
    # different words.
    ("struct_ctor_both_backends",
     "struct Point:\n"
     "    x: Int\n"
     "    y: Int\n\n"
     "    fn get_x(self) -> Int:\n"
     "        return self.x\n\n"
     "    fn set_x(self, v: Int):\n"
     "        self.x = v\n\n"
     "def main(n):\n"
     "    p = Point()\n"
     "    p.x = 5\n"
     "    p.set_x(9)\n"
     "    return p.x + p.get_x() + p.get_x()\n", 27, None),
    # A construction whose argument count is not the struct's field list. This
    # case used to expect `refuse:takes no arguments on this path`, which was
    # one of the three construction messages that were STALE FOR THE WRONG
    # REASON: it said "a struct is default-initialized and its fields assigned",
    # which was true before the by-reference receiver gave a multi-field struct
    # a block to fill and stopped being the reason the moment that block
    # landed. It is still a refusal — the arity genuinely does not match — and
    # it is now refused for the arity, with the field list spelled, which is
    # what the reader needs: `Resolver` derives NO fields at all (a Python class
    # whose only member is a method), so three arguments have nowhere to go.
    ("struct_ctor_args_both_backends",
     "class Resolver:\n"
     "    def resolve(self, name):\n"
     "        return len(name)\n\n"
     "def main(n):\n"
     "    r = Resolver(n, n, n)\n"
     "    return r.resolve(\"a\")\n",
     "refuse:does not match its fields (no fields at all)", None),
    # `S()` is not a call — it brings every field up at its default — so for a
    # one-field struct the default IS the whole value, and a constructor that
    # always emitted 0 threw it away. Nothing in these two programs ever writes
    # the field, so nothing else could supply it: `count = 7` read back as 0.
    # Built and ran and was wrong, which is the one outcome this backend may
    # not produce. Run rather than merely built, because the bug WAS a value.
    ("struct_default_word_int", "struct Counter:\n"
                                "    count = 7\n\n"
                                "    def get(self):\n"
                                "        return self.count\n\n"
                                "def main(n):\n"
                                "    c = Counter()\n"
                                "    return c.get()\n", 7, None),
    # The same default as a STRING, which is one word on this path (a bare
    # `char *`), so the constructor materializes the literal's own address. The
    # comparison is what proves the pointer is the RIGHT pointer and not merely
    # some word: it has to be the bytes `hi`.
    ("struct_default_word_string", "struct Name:\n"
                                  "    text = \"hi\"\n\n"
                                  "    def get(self):\n"
                                  "        return self.text\n\n"
                                  "def main(n):\n"
                                  "    c = Name()\n"
                                  "    if c.get() == \"hi\":\n"
                                  "        return 1\n"
                                  "    return 0\n", 1, None),
    # …and a default this path genuinely cannot bring up: a container is not
    # something a constructor can evaluate here, and the honest answer to that
    # is to say so rather than hand back a zero the source never mentioned.
    # Checked on both backends, because the failure it replaces was a wrong
    # ANSWER on arm64 and a call to a symbol nothing defines on x86-64.
    ("struct_default_word_opaque",
     "struct Names:\n"
     "    items = [1, 2, 3]\n\n"
     "    def get(self):\n"
     "        return self.items\n\n"
     "def main(n):\n"
     "    c = Names()\n"
     "    return c.get()\n", "refuse:cannot bring its field 'items' up at its default", None),
    ("comptime_call", "def comptime_call(n):\n"
                      "    comptime var a = square(6)\n"
                      "    comptime var b = add(a, 1)\n"
                      "    comptime var c = fact(5)\n"
                      "    comptime var flag = a > 30\n"
                      "    if flag:\n        return b + c\n"
                      "    return 0\n"
                      "def square(x):\n    return x * x\n"
                      "def add(a, b):\n    return a + b\n"
                      "def fact(n):\n    var acc = 1\n    var i = 1\n"
                      "    while i <= n:\n        acc = acc * i\n"
                      "        i = i + 1\n    return acc\n", 157, None),

    # ── len() and element access on a LIST BLOB ───────────────────────────
    #
    # `len` of a list is not an interception this suite had to add — both
    # backends already read the blob's count word — so the first two of these
    # are guards rather than fixes, and they pass on both trees by design.
    # They are here because the interesting cases below them are all about
    # what a list blob IS, and a guard is the only thing that says the fix did
    # not quietly change the size of the thing being measured.
    ("list_len_empty", "def main():\n"
                       "    var a = []\n"
                       "    return len(a)\n", 0, None),
    ("list_len_singleton", "def main():\n"
                           "    var a = [7]\n"
                           "    return len(a)\n", 1, None),
    # The APPEND path, as a guard. It was already correct — `_emit_list_append`
    # pushes the value and reads it back out of the frame rather than trusting
    # a register across the store — so this passes on both trees, and it is
    # here because the two cases below it turned out to be broken in exactly
    # the way this one is not, and the difference between the two store paths
    # is the thing a reader is meant to take away. `len` alone would pass with
    # the elements holding whatever the store happened to leave there, so the
    # elements are read back too, and compared as equalities rather than a sum
    # because two addresses added together and truncated to a byte can land on
    # the right answer by chance.
    ("list_append_then_read", "def main():\n"
                              "    var a = []\n"
                              "    a.append(10)\n"
                              "    a.append(20)\n"
                              "    if len(a) == 2:\n"
                              "        if a[0] == 10:\n"
                              "            if a[1] == 20:\n"
                              "                return 1\n"
                              "    return 0\n", 1, None),
    # The SUBSCRIPT-ASSIGN path, which is the one that was broken, and it was
    # broken SILENTLY and only on arm64. `a[2] = 9` emitted the value into X0
    # and then computed the element address — which builds its answer in X0
    # out of X0..X4 — so what was written was the ADDRESS, and `a[2]` read
    # back a frame pointer. It built, it ran, it disagreed with x86-64 (which
    # spills the value for exactly this reason), and the wrong value was a
    # plausible 64-bit word: the outcome this backend is not allowed to
    # produce. `a = [0, 0, 0]` is deliberate — zeros already read back 0, so
    # a literal of zeros cannot tell a stored value from an absent one.
    ("list_subscript_store_then_read", "def main():\n"
                                       "    var a = [0, 0, 0]\n"
                                       "    a[2] = 9\n"
                                       "    if a[2] == 9:\n"
                                       "        return 1\n"
                                       "    return 0\n", 1, None),
    # …and the same defect with a COMPUTED index in a loop, which is where it
    # produced a frame address rather than a stale zero. Non-zero literals, so
    # the read is distinguishable from "never written".
    ("list_subscript_store_loop", "def main():\n"
                                  "    var a = [10, 20, 30, 40, 50]\n"
                                  "    var i = 0\n"
                                  "    while i < 5:\n"
                                  "        a[i] = i * 2\n"
                                  "        i = i + 1\n"
                                  "    if a[3] == 6:\n"
                                  "        return 1\n"
                                  "    return 0\n", 1, None),
    # An append INSIDE A LOOP, at the only trip count the capacity bargain
    # allows. The capacity is `literal length + number of append SITES`
    # (_scan_list_caps), so a loop may append at most as many times as there
    # are append sites in its body: one site, one iteration. The store is
    # bounds-checked against that number and exits(1) rather than growing the
    # blob, which is the documented bargain and is loud rather than wrong —
    # so this case pins the trip count deliberately, and the comment is the
    # reason it is 1 and not 5. A capacity derived from a literal `range()`
    # bound would lift it; nothing derives one yet.
    ("list_append_in_loop", "def main():\n"
                            "    var a = [1, 2]\n"
                            "    var i = 0\n"
                            "    while i < 1:\n"
                            "        a.append(i + 3)\n"
                            "        i = i + 1\n"
                            "    if len(a) == 3:\n"
                            "        if a[2] == 3:\n"
                            "            return 1\n"
                            "    return 0\n", 1, None),

    # ── the gimple backend's C runtime, refused by name ───────────────────
    #
    # `mojo_*` is the ABI of the OTHER backend's C runtime (runtime/
    # fire_runtime.h, runtime/fire_sqlite3.h), and a program written against it
    # spells those entry points in the source. A formal image used to link
    # libSystem and nothing else, so each of these emitted a BL against a symbol
    # nothing defines: the build reported success and the program died in the
    # loader. A formal build now puts the per-architecture `mojo_*` library on
    # the link line when the program names a word-shaped entry point of it
    # (`formal/build.py`'s `_runtime_library_for`), so a `mojo_*` call splits
    # three ways: linked, refused for its TYPES, and refused because this
    # library does not export the name. The two `refuse:` cases below are the
    # second and the third; a numeric case is the first, and the assertion there
    # is that BOTH architectures AGREE — which `refuse:` also asserts, for the
    # other two.
    ("gimple_runtime_sqlite_refused",
     "def main():\n"
     "    var db = mojo_sqlite3_open(\":memory:\")\n"
     "    mojo_sqlite3_close(db)\n"
     "    return 0\n",
     "refuse:is an entry point of the gimple backend's C runtime", None),
    # `mojo_print` rather than `print`, for the file that spells the runtime's
    # own name. Same namespace, OPPOSITE answer, and this is the case the whole
    # phase-2 payoff turns on: every type crossing this call is one 64-bit word
    # — a `char *` is a value on this path, because a string is an interned
    # `char *` with no header — and the per-arch runtime library is on the link
    # line, so this is no longer a refusal but an image that RUNS. Verified:
    # exit 0 and "hi" on stdout, arm64 and x86_64.
    ("gimple_runtime_print_runs",
     "def main():\n"
     "    mojo_print(\"hi\")\n"
     "    return 0\n",
     0, None),
    # The one that is NOT answerable by linking the library, which is why the
    # refusal says more than "no library here". `mojo_list_len` takes a
    # `MojoList *` — a heap box the gimple runtime owns — where a list on this
    # path is a frame blob whose first word IS its count, so the operand and
    # the answer are of different types. The argument here is a REAL list
    # literal, which is the whole point: even a program with nothing wrong
    # with its list cannot be answered, because the call is not asking this
    # path's question. The extra sentence in the diagnostic is what a reader
    # would otherwise have to discover by reading fire_runtime.h.
    ("gimple_list_len_refused",
     "def main():\n"
     "    var xs = [1, 2, 3]\n"
     "    var n = mojo_list_len(xs)\n"
     "    return n\n",
     "refuse:It could not be answered by linking that library either", None),
    # …and the other side of the same prefix rule: a `mojo_`-named function
    # DEFINED IN THIS MODULE is not a runtime entry point, and refusing it
    # would be a self-inflicted wound of exactly the kind the other cases
    # exist to remove. The repository has real ones —
    # scripts/stage2_mojo_interpreter.mojo defines `mojo_to_python` — so this
    # is a live shape and not a hypothetical. Passes on both trees: it is the
    # guard that says the refusal is a decision about a NAME'S BINDING and not
    # about its spelling.
    ("mojo_prefixed_local_function_ok",
     "def mojo_triple(x):\n"
     "    return x * 3\n\n"
     "def main():\n"
     "    return mojo_triple(5)\n", 15, None),
    # ── class-level CONSTANT vs per-instance state ─────────────────────────
    # A class-level constant is not a field. `Regs.A = 1` is one value for
    # every instance, so there is nothing for a receiver word to hold, and
    # counting it used to make this class FOUR fields wide. With the
    # by-reference receiver the count no longer decides whether the program
    # builds, so what this case has to assert instead is that the two names
    # that are NOT storage still do not become slots: `A` and `B` are read as
    # their own literals, and the answer is the two field writes plus `A`.
    # 40 + 90 + 1 = 131, and it would be 39 more if `A` had quietly become a
    # third slot with a zero in it.
    ("pyclass_constant_table_with_two_fields",
     "class Regs:\n"
     "    A = 1\n"
     "    B = 2\n"
     "\n"
     "    def __init__(self):\n"
     "        self.lo = 4\n"
     "        self.hi = 9\n"
     "\n"
     "    def total(self):\n"
     "        return self.lo + self.hi + self.A\n"
     "\n"
     "def main(n):\n"
     "    r = Regs()\n"
     "    r.lo = 40\n"
     "    r.hi = 90\n"
     "    return r.total()\n", 131, None),
    # …and the same class with NO instance state at all, which is the case the
    # rule exists for: it is one word (in fact none), it builds, and it RUNS.
    # The exit value is the assertion — the constants are materialized where
    # they are read (formal/build.py `_rewrite_class_constants`), so `Regs.A` is
    # the 1 the source wrote. Left to the field path it read the local slot
    # spelled `Regs.A`, which nothing ever writes, and this program returned
    # 31 off an uninitialised register. Both spellings of the call are here:
    # through an instance and through the class name, because a method on a
    # receiver that carries nothing is a free function that ignores `self` and
    # both have to work.
    ("pyclass_constant_table_only",
     "class Regs:\n"
     "    A = 3\n"
     "    B = 4\n"
     "\n"
     "    def span(self):\n"
     "        return Regs.B - Regs.A\n"
     "\n"
     "    def first():\n"
     "        return Regs.A + 1\n"
     "\n"
     "def main(n):\n"
     "    r = Regs()\n"
     "    return r.span() * 10 + Regs.first()\n", 14, None),
    # The tie-break, and the only case here that is about a name being BOTH: a
    # class-level name that the program also writes through a receiver is
    # storage, whatever its initializer looks like, because the write is what
    # makes it per-instance. `Cell.N = 7` is a constant until `self.N = 4` and
    # `c.N = 9` say otherwise. Drop the write clause from the rule and this
    # program returns 0 — the receiver word is never written and the field
    # aliases into a slot nothing fills, which is the one error the rule is
    # arranged to be unable to make. `Cell.M` is in the class to keep the case
    # honest about the other half: it IS only ever read, so it is a constant,
    # and this tree measures one field where the pre-rule tree measured two
    # and refused.
    ("pyclass_name_read_bare_and_written",
     "class Cell:\n"
     "    N = 7\n"
     "    M = 3\n"
     "\n"
     "    def __init__(self):\n"
     "        self.N = 4\n"
     "\n"
     "    def get(self):\n"
     "        return self.N\n"
     "\n"
     "def main(n):\n"
     "    c = Cell()\n"
     "    c.N = 9\n"
     "    return c.get() + Cell.M\n", 12, None),
    # A name written through a receiver AT A CALL SITE is storage too, and this
    # is the case that says so: no method of `Pair2` mentions `B`, so only the
    # unit-wide write census can see that `p.B = 5` makes it per-instance.
    # `B` and `a` are two fields with two slots, and a write at the call site
    # has to reach a method that reads it: 3*10 + 5 = 35. The one-field
    # lowering this replaced would have turned `p.B = 5` into an assignment to
    # the receiver itself, which is the aliasing bug the width rule existed to
    # prevent — and the frame is what makes the two slots two slots again.
    ("pyclass_field_written_only_at_call_site",
     "class Pair2:\n"
     "    B = 0\n"
     "\n"
     "    def __init__(self):\n"
     "        self.a = 1\n"
     "\n"
     "    def get(self):\n"
     "        return self.a\n"
     "\n"
     "    def get_b(self):\n"
     "        return self.B\n"
     "\n"
     "def main(n):\n"
     "    p = Pair2()\n"
     "    p.B = 5\n"
     "    p.a = 3\n"
     "    return p.get() * 10 + p.get_b()\n", 35, None),
    # A constant whose value is not a literal has nowhere to live on this path:
    # there is no module-global storage, so a read can only be answered by the
    # value it is written with. A container is not that. The honest answer is to
    # refuse by name rather than hand back the zero an unwritten slot gives.
    # Checked on both backends, because the failure it replaces was a wrong
    # ANSWER (0, from an uninitialised slot) rather than a diagnostic.
    ("pyclass_nonliteral_constant_refused",
     "class Table:\n"
     "    NAMES = [\"a\", \"b\"]\n"
     "\n"
     "    def first():\n"
     "        return Table.NAMES[0]\n"
     "\n"
     "def main(n):\n"
     "    return Table.first()\n",
     "refuse:Table.NAMES is a class-level constant", None),

    # ── methods on a string ──────────────────────────────────────────────
    #
    # A string here is a bare `char *`: no header, no length, just bytes to a
    # NUL. That splits the string methods in two (formal/model.py,
    # POINTER_BOUNDED_METHODS), and the five lowered here are the pointer-
    # bounded half — their answer is a function of the bytes to the NUL, which
    # libSystem already computes. The length-dependent half is refused by name
    # and there are `refuse:` cases for it below.
    #
    # `lstrip` is checked through `print` and not through `==`, and the reason
    # is worth stating because it looks like an odd choice: `==` between two
    # strings on this path is POINTER equality of interned literals, so it is
    # right whenever both sides are literals and WRONG for a derived interior
    # pointer — which is exactly what `lstrip` returns. That is a pre-existing
    # property of `==` here (string `+` is already broken the same way), not
    # something these methods introduce, and it is not this file's business to
    # fix. What these cases check is the VALUE, via printf.

    # The basic left-strip, with the leading run being all three of tab/space
    # and the result observed on stdout. `\t` here is a literal BACKSLASH and a
    # `t` — string literals on this path are not unescaped — so it must NOT be
    # treated as a tab, and this case is what pins that down.
    ("str_lstrip_prints",
     "def main(n):\n"
     "    printf(\"[%s][%s][%s]\\n\", \"   hi\".lstrip(), \"hi\".lstrip(),\n"
     "           \"\".lstrip())\n"
     "    return 0\n", 0, "[hi][hi][]"),
    # The all-whitespace and empty cases, which are where a scan that forgets
    # to stop at the terminator walks off the end of the buffer. An all-space
    # string strips to the empty string, and so does the empty one.
    #
    # The second operand is the unescaping boundary, and it is here because it
    # is surprising: `"\t"` in a Mojo literal on this path is a BACKSLASH and a
    # `t`, two characters, not a tab — string literals are stored unescaped
    # (see the module docstring of fire_compiler) — and a backslash is not
    # whitespace, so `lstrip` leaves it alone. Python would return "". Asserting
    # the unstripped result is what stops a later "fix" that unescapes literals
    # in the string methods from quietly changing what the program computes.
    ("str_lstrip_all_whitespace",
     "def main(n):\n"
     "    printf(\"[%s][%s]\\n\", \"   \".lstrip(), \"\\t\".lstrip())\n"
     "    return 0\n", 0, "[][\\t]"),
    # A local receiver as well as a literal: the two lower differently (a
    # literal is ADRP+ADD, a local is a load), and only exercising the literal
    # would leave the local path untested.
    ("str_lstrip_local_receiver",
     "def main(n):\n"
     "    s = \"  padded\"\n"
     "    m = s.lstrip()\n"
     "    printf(\"[%s]\\n\", m)\n"
     "    if m.startswith(\"pad\"):\n"
     "        return 3\n"
     "    return 0\n", 3, "[padded]"),
    # `startswith`: a hit, a miss, and the empty affix — which is a
    # zero-length compare, so it compares equal, which is the "yes" Python
    # gives. And a prefix LONGER than the receiver, which must be a miss
    # rather than a compare that runs off the front.
    ("str_startswith",
     "def main(n):\n"
     "    s = \"abcabc\"\n"
     "    r = 0\n"
     "    if s.startswith(\"abc\"): r = r + 1\n"
     "    if not s.startswith(\"zz\"): r = r + 2\n"
     "    if s.startswith(\"\"): r = r + 4\n"
     "    if not s.startswith(\"abcd\"): r = r + 8\n"
     "    return r\n", 15, None),
    # `endswith`: the same four, and the longer-suffix case is the one that
    # needs the length guard — `s + len(s) - len(p)` underflows without it, and
    # the compare then reads before the start of the buffer.
    ("str_endswith",
     "def main(n):\n"
     "    s = \"abcabc\"\n"
     "    r = 0\n"
     "    if s.endswith(\"abc\"): r = r + 1\n"
     "    if not s.endswith(\"zz\"): r = r + 2\n"
     "    if s.endswith(\"\"): r = r + 4\n"
     "    if not s.endswith(\"zabc\"): r = r + 8\n"
     "    return r\n", 15, None),
    # `find`: a hit in the middle, a hit at offset 0, a miss (-1, which is a
    # NULL from strstr and has to be turned into Python's -1 rather than
    # returned as the NULL's own bits), and the empty needle (0, because
    # strstr returns the receiver itself).
    ("str_find",
     "def main(n):\n"
     "    s = \"abcabc\"\n"
     "    r = 0\n"
     "    if s.find(\"ca\") == 2: r = r + 1\n"
     "    if s.find(\"abc\") == 0: r = r + 2\n"
     "    if s.find(\"zz\") == 0 - 1: r = r + 4\n"
     "    if s.find(\"\") == 0: r = r + 8\n"
     "    return r\n", 15, None),
    # `count`, and the two places it is easy to be wrong. NON-overlapping:
    # \"aaa\".count(\"aa\") is 1, and advancing the cursor by one byte instead of
    # by the needle's length would make it 2. And the EMPTY needle, which
    # matches at each of the L+1 positions in a string of length L — so
    # \"abc\".count(\"\") is 4, not 3, and \"\".count(\"\") is 1, not 0.
    ("str_count",
     "def main(n):\n"
     "    s = \"abcabc\"\n"
     "    r = 0\n"
     "    if s.count(\"abc\") == 2: r = r + 1\n"
     "    if \"aaa\".count(\"aa\") == 1: r = r + 2\n"
     "    if s.count(\"\") == 7: r = r + 4\n"
     "    if \"\".count(\"\") == 1: r = r + 8\n"
     "    if s.count(\"zz\") == 0: r = r + 16\n"
     "    return r\n", 31, None),
    # Two of them on one receiver, and the result of the first feeding the
    # second. `m = s.lstrip()` binds a STRING, and a classifier that did not
    # learn that would format m as a number — the case here is that
    # `m.count("a")` is asked of a name the classifier has to have called a
    # string, which it only does because the method's result kind is recorded.
    ("str_method_result_is_string",
     "def main(n):\n"
     "    s = \"  aaa\"\n"
     "    m = s.lstrip()\n"
     "    r = 0\n"
     "    if m.count(\"a\") == 3: r = r + 1\n"
     "    if m.endswith(\"a\"): r = r + 2\n"
     "    if m.find(\"aaa\") == 0: r = r + 4\n"
     "    return r\n", 7, None),
    # ── the refusals, which are the other half of the answer ─────────────
    #
    # `strip` is one instruction from `lstrip` and is still refused, and the
    # reason is a WRITE rather than a computation: a shorter string has to be
    # terminated one byte earlier, and on a bare `char *` the only byte there is
    # the receiver's own. A string literal is interned into __TEXT,__text,
    # which is mapped read+execute, so writing it faults. Checked on both
    # backends because the failure it replaces was a plausible-looking WRONG
    # STRING: an earlier version returned the new end pointer without writing
    # anything, and "   hi   ".strip() printed as "   ".
    ("str_strip_refused",
     "def main(n):\n"
     "    s = \"  hi  \"\n"
     "    t = s.strip()\n"
     "    return 0\n",
     "refuse:strip() is a real method of String", None),
    ("str_rstrip_refused",
     "def main(n):\n"
     "    s = \"  hi  \"\n"
     "    t = s.rstrip()\n"
     "    return 0\n",
     "refuse:see strip", None),
    # The length-dependent half: each of these needs a buffer of a size
    # nothing knows at compile time. The needle is the reason, so the
    # diagnostic is checked for the part that tells a reader which half of the
    # argument is missing.
    ("str_split_refused",
     "def main(n):\n"
     "    s = \"a b\"\n"
     "    parts = s.split(\" \")\n"
     "    return 0\n",
     "refuse:split() is a real method of String", None),
    ("str_join_refused",
     "def main(n):\n"
     "    parts = [\"a\", \"b\"]\n"
     "    t = parts.join(\"-\")\n"
     "    return 0\n",
     "refuse:join() is a real method of String", None),
    ("str_replace_refused",
     "def main(n):\n"
     "    s = \"aa\"\n"
     "    t = s.replace(\"a\", \"b\")\n"
     "    return 0\n",
     "refuse:replace() is a real method of String", None),
    # `upper` is refused for the same class of reason as `strip` and gets its
    # own case because it is the one a reader is most likely to assume works.
    ("str_upper_refused",
     "def main(n):\n"
     "    s = \"ab\"\n"
     "    t = s.upper()\n"
     "    return 0\n",
     "refuse:upper() is a real method of String", None),
    # The KIND GUARD, and this is the most important refusal in the group.
    # `value` is 359 of the method calls in the stdlib, on MLIR value objects
    # and not on strings; lowered as a string operation it would walk whatever
    # 64-bit word the receiver holds as if it were an address to bytes. The
    # receiver here is an unannotated parameter, so the source does not say
    # what it holds, and the honest answer is to say so rather than to guess.
    #
    # The needle is the DEREFERENCE half, and it is a needle rather than the old
    # "is a method call on a value" because that blanket text told a reader of
    # this case to add the method to the string table — the exact
    # mis-implementation the guard exists to prevent.
    #
    # The expectation was CHANGED in wave 6 and the change is the point of the
    # case.  It used to be "is a DEREFERENCE on this path, not an identity",
    # which is FALSE about 527 of the 528 `value` sites in the stdlib: an enum's
    # `value()` is its integral, an iterator's is the item it holds, and a
    # `SIMD`'s is its scalar, and none of those three is a load from an address.
    # The pointer value model made the pointer case answerable, which left the
    # refusal describing only the one receiver it was about while claiming all
    # of them.  It now names the four questions behind the one spelling, which
    # is true of every receiver and tells a reader that the fix is a DECLARATION
    # rather than another method to add to a table.  The history sentence about
    # the loader is kept, so the two facts are not separated.
    ("str_method_unknown_receiver",
     "def main(n):\n"
     "    h = n\n"
     "    return h.value()\n",
     "refuse:is spelled the same for four different questions", None),
    # A string method on a receiver the classifier positively knows is NOT a
    # string. Same refusal family, different wording, and the wording is the
    # point: \"the source does not say\" and \"it is an int\" are different
    # problems with different fixes.
    # The same guard reached through a STRING method, which is where the new
    # wording is load-bearing. `h` comes from an unannotated parameter, so the
    # source does not say what it holds; pre-change this refused as "a method
    # call on a value" (wave 1's blanket refusal) and it refuses now as a string
    # method whose receiver is unclassified, which tells the reader that
    # ANNOTATING THE RECEIVER is the fix. Without the guard, `lstrip` on such a
    # receiver lowers and walks whatever 64-bit word arrived as if it were an
    # address to bytes.
    ("str_method_unknown_receiver_str",
     "def main(n):\n"
     "    h = n\n"
     "    t = h.lstrip()\n"
     "    return 0\n",
     "refuse:classified as 'int' rather than a string", None),
    # …and the OTHER undecided case, which is not the same thing. An
    # unannotated parameter is a WORD, and a word on this path is an integer
    # (see the note on kinds in formal/model.py), so it classifies as `int` and
    # gets the message above. A name bound two ways in one function classifies
    # as NOTHING, because picking either answer would make the result depend on
    # which use site asked — and that gets its own message, which is the one
    # that says the fix is to make the source say.
    ("str_method_conflicted_receiver",
     "def main(n):\n"
     "    h = \"abc\"\n"
     "    if n > 0:\n"
     "        h = 5\n"
     "    t = h.lstrip()\n"
     "    return 0\n",
     "refuse:the source does not say what its receiver holds", None),
    ("str_method_int_receiver",
     "def main(n):\n"
     "    k = 7\n"
     "    c = k.count(\"a\")\n"
     "    return 0\n",
     "refuse:is a method on a string", None),

    # ── the string VALUE: len, ==, and + ──────────────────────────────────
    #
    # A string on this path is a bare `char *` to NUL-terminated bytes interned
    # into `__TEXT,__text` (measured: that segment is mapped `initprot 0x5`,
    # read+execute, no write). Three things follow, and each of them used to be
    # a plausible-looking WRONG ANSWER rather than a diagnostic:
    #
    #   NO LENGTH FIELD. There is no count at offset 0 to read. `len()` of a
    #       string is a `strlen` over the bytes — a computation, not a field
    #       load, which is why the representation does not have to widen.
    #   POINTER EQUALITY, not content equality, for `==`. Right for two interned
    #       literals (interning is by content) and wrong for every derived
    #       interior pointer, which is what `lstrip` returns.
    #   READ-ONLY BYTES. Nothing may write them, so nothing may return a
    #       shorter string, and nothing may build a new one — which is why `+`
    #       cannot be lowered at all and is refused instead.
    #
    # Every case in this group FAILED on the pre-change tree. The `len` ones
    # failed by returning the first eight CHARACTERS of the string as a number
    # (1819043176 = 0x6C6C6568 = "hell" for `m = "hello"`, on both backends),
    # the `==` one failed by taking the wrong branch on a correct program, and
    # the `+` one failed by printing `[]` on arm64 and SEGFAULTING on x86-64.

    # `len` of a string, on a LITERAL. Pre-change this was REFUSED — the old
    # check fired on a syntactic literal and on an identity type-constructor
    # and nothing else — so it changed from a diagnostic to a number. It is the
    # smallest case that shows the refusal was the wrong answer even where it
    # fired: the length of a NUL-terminated `char *` is a `strlen`, and the
    # representation does not have to widen to have one.
    ("str_len_literal",
     "def main(n):\n"
     "    printf(\"%d\\n\", len(\"hello\"))\n"
     "    return 0\n", 0, "5"),
    # `len` of a LOCAL. This is the case that was wrong: the refusal only fired
    # on a literal, so a name fell through to the count-field load and read the
    # first eight bytes of the CHARACTER data. Observed on the pre-change tree,
    # on BOTH backends: 1819043176.
    ("str_len_local",
     "def main(n):\n"
     "    m = \"hello\"\n"
     "    printf(\"%d\\n\", len(m))\n"
     "    return 0\n", 0, "5"),
    # `len` of a METHOD RESULT — the third shape, and the one that is neither a
    # literal nor a name. `lstrip` yields an INTERIOR pointer, so this is also
    # the case that pins down that the lowering reads to the NUL from wherever
    # the pointer starts and not from the original literal. Pre-change it
    # returned 536897896 = 0x20006869, which is "hi" followed by the two spaces
    # that had just been trimmed.
    ("str_len_method_result",
     "def main(n):\n"
     "    m = \"  hi\".lstrip()\n"
     "    printf(\"%d\\n\", len(m))\n"
     "    return 0\n", 0, "2"),
    # The empty string and a string that is entirely whitespace, which is where
    # a scan that forgets the terminator walks off the end of the buffer. Both
    # are 0.
    ("str_len_empty",
     "def main(n):\n"
     "    e = \"\"\n"
     "    w = \"   \".lstrip()\n"
     "    printf(\"%d %d\\n\", len(e), len(w))\n"
     "    return 0\n", 0, "0 0"),
    # `len` where the answer is used as a NUMBER rather than printed, because a
    # printf of the wrong value and an arithmetic result of the wrong value are
    # different symptoms of the same bug and only one of them is a "return
    # status" a suite can check.
    ("str_len_in_arithmetic",
     "def main(n):\n"
     "    a = \"abc\"\n"
     "    b = \"de\"\n"
     "    return len(a) * 10 + len(b)\n", 32, None),
    # The blob half, as a guard: `len` of a list, a range and a local list all
    # still read the count field at offset 0. `len(range(10))` is in here for a
    # second reason — `range(...)` lowers to a `[count][elements]` blob but the
    # kind table calls a `range(...)` call an `int`, so the `len` decision
    # recognises it by the shape that decides the answer rather than by the
    # kind. Without that, the new kind-driven refusal broke a case that has
    # always worked.
    ("len_blob_shapes_still_work",
     "def main(n):\n"
     "    xs = [1, 2, 3]\n"
     "    return len([1, 2, 3, 4]) + len(range(10)) + len([]) + len(xs)\n",
     17, None),
    # `len` of something the source does not say the type of. This one is a
    # refusal and it is a refusal on purpose: the old lowering read eight bytes
    # at offset 0 of an unclassified word and called the result a length, and
    # for a `char *` that is the first eight CHARACTERS. An unannotated
    # parameter is a word, and a word here is an `int` (see the note on kinds in
    # formal/model.py), so this is the INT row of `model.len_operand_lowering`
    # rather than the unknown row — the int message says an integer has no
    # length and names the two things that do.
    ("str_len_of_unannotated_param_refused",
     "def main(n):\n"
     "    printf(\"%d\\n\", len(n))\n"
     "    return 0\n",
     "refuse:an integer has no length", None),
    # And the unknown row, which is a different refusal for a different reason:
    # this operand is bound both ways in one function, so the classifier says
    # nothing rather than saying `int`.
    ("str_len_of_conflicted_name_refused",
     "def main(n):\n"
     "    h = \"abc\"\n"
     "    if n > 0:\n"
     "        h = 5\n"
     "    return len(h)\n",
     "refuse:the source does not say what this operand holds", None),

    # `==` on two literals: right before, right after, and the pair that must
    # NOT be equal. The pre-change pointer compare got all three of these right
    # (interning is by content), so this case is a GUARD — it is here to catch
    # a content compare that is subtly wrong, not to catch the old bug.
    ("str_eq_two_literals",
     "def main(n):\n"
     "    r = 0\n"
     "    if \"abc\" == \"abc\": r = r + 1\n"
     "    if \"abc\" == \"xyz\": r = r + 2\n"
     "    if \"abc\" != \"xyz\": r = r + 4\n"
     "    printf(\"%d\\n\", r)\n"
     "    return 0\n", 0, "5"),
    # `==` on a DERIVED INTERIOR POINTER against a literal. This is the case
    # that was wrong, and it is the worst shape a wrong answer can have: a
    # correct program taking the WRONG BRANCH, with nothing downstream able to
    # tell. Observed on the pre-change tree, on BOTH backends: `r` came out 9,
    # i.e. the `m == "abc"` arm did not fire.
    ("str_eq_interior_pointer",
     "def main(n):\n"
     "    m = \"  abc\".lstrip()\n"
     "    r = 0\n"
     "    if m == \"abc\": r = r + 1\n"
     "    if m == \"xyz\": r = r + 2\n"
     "    if m != \"abc\": r = r + 4\n"
     "    printf(\"%d\\n\", r)\n"
     "    return 0\n", 0, "1"),
    # `==` where the interior pointer is on the LEFT of one comparison and the
    # RIGHT of another, and where the two operands are the same name. The
    # lowering puts the operands in the stack across two libc calls, so a
    # register clobbered by the first call shows up here and nowhere else.
    ("str_eq_operand_positions",
     "def main(n):\n"
     "    s = \"  xy\".lstrip()\n"
     "    t = \"xy\"\n"
     "    r = 0\n"
     "    if s == t: r = r + 1\n"
     "    if t == s: r = r + 2\n"
     "    if s == s: r = r + 4\n"
     "    printf(\"%d\\n\", r)\n"
     "    return 0\n", 0, "7"),
    # `is` and `is not` must stay POINTER comparisons. They are the one string
    # comparison for which the pointer is the answer rather than an
    # approximation of it — `a is b` asks whether two names hold one object, and
    # with interning by content two equal literals already are one object.
    # Routing them through the content compare would make `x is y` true whenever
    # the CONTENTS match, which is a different question spelled the same way.
    # The observable consequence on this path: two equal literals ARE the same
    # interned object, so `is` is true, and an interior pointer is NOT that
    # object, so `is` is false even though the content compare says equal.
    ("str_is_stays_identity",
     "def main(n):\n"
     "    m = \"  abc\".lstrip()\n"
     "    a = \"abc\"\n"
     "    b = \"abc\"\n"
     "    r = 0\n"
     "    if a is b: r = r + 1\n"
     "    if m is a: r = r + 2\n"
     "    printf(\"%d\\n\", r)\n"
     "    return 0\n", 0, "1"),
    # `+` on two strings. It is a refusal and the pre-change behaviour was the
    # worst of anything in this group: `[]` on arm64 and a SEGFAULT on x86-64,
    # from one line, so the two backends did not even agree on whether the
    # program worked. Asserted as a refusal on both, which is also the assertion
    # that they now agree.
    ("str_concat_refused",
     "def main(n):\n"
     "    s = \"ab\" + \"cd\"\n"
     "    printf(\"[%s]\\n\", s)\n"
     "    return 0\n",
     "refuse:on two strings is refused on this path", None),
    # `+` where ONE side is a string is not string concatenation and must not be
    # refused: the mixed case is the pointer/offset arithmetic a caller may have
    # meant, and refusing it would turn a working program into a diagnostic over
    # a case the model cannot see. This is a guard.
    ("str_plus_int_still_arithmetic",
     "def main(n):\n"
     "    k = 3\n"
     "    s = \"ab\"\n"
     "    return k + 4\n", 7, None),

    # ── wave 4 (D5): the limits, pinned so they cannot be lost ──────────────
    #
    # Four `refuse:` cases, one per verified-true limit in the sweep residue
    # that no other list already covers. A `refuse:` case asserts the build
    # FAILS with these words on BOTH backends, so each of these goes RED if
    # the limit is closed — which is the point. A limit nobody can detect the
    # disappearance of is indistinguishable from a limit nobody re-checked.
    #
    # What closes each one, and what it costs, is in
    # bugs/FORMAL_known_limits.md §2 and §3. The short version: the MLIR one
    # cannot be closed on this path at all (there is no MLIR in a freestanding
    # image for the template to become); the other three are shape and
    # comptime-folding rules that a fuller value model would replace.
    #
    # NOT pinned here, deliberately, because pinning them would cement a
    # fabricated answer as intended behaviour — see the same document §2.2-2.4
    # and §3.1-3.2 for the four constructs that DO build and lie:
    # `__mlir_attr.`…`` (a dotted template, single element) builds and reads an
    # undefined name, so it prints whatever word is in the register — 10 on
    # arm64, 0 on x86-64, for the same source; a module-level
    # `comptime X = __mlir_type[…]` is never walked at all, which is why
    # std/builtin/type_aliases.mojo is a false PASS in the sweep baseline;
    # `__mlir_op.`…`[n]` builds and segfaults; and `String()` (zero operands)
    # is refused as if it were a two-operand conversion.

    # An MLIR attribute template is not a subscript. The elements are
    # backtick-quoted literal fragments interleaved with compile-time
    # sub-expressions and the whole thing denotes a dialect attribute, so
    # there is nothing here for a subscript to index. Materializing it as a
    # container would put a pointer to a frame blob where an attribute belongs
    # and disagree with the compiler that does have MLIR. This is the refusal
    # behind 36 of the 578 swept stdlib files — and it is arch-free text on
    # purpose, so `refuse:` (not `refuse_either:`) is the right assertion.
    ("limit_mlir_multi_element_template",
     "def main(n: Int) -> Int:\n"
     "    var t = __mlir_attr[`#kgen.param.expr<`, n, `> : !kgen.string`]\n"
     "    return n\n",
     "refuse:assembles an MLIR attribute from a template", None),
    # NOT HERE: a struct's positional-argument construction. That limit is
    # already pinned by `struct_ctor_args_both_backends` (same needle, both
    # backends, same refusal) and a second case asserting the same thing is a
    # parallel implementation of a pin that exists, not extra coverage. It is
    # listed in bugs/FORMAL_known_limits.md §3 with that case's name.
    # A `comptime` binding whose right-hand side mentions a RUNTIME parameter
    # cannot be folded, and this path has no comptime evaluator that could
    # resolve it. Guessing a value would be a fabricated answer.
    #
    # `refuse_either:`, and the reason is worth reading: the two backends
    # refuse at DIFFERENT depths and name DIFFERENT limits for one construct.
    # arm64 reaches the fold and says so; x86-64 has no `comptime` statement
    # lowering at all and says "unsupported statement ComptimeVarStmt". Both
    # are honest, and the shared-text rule that `refuse:` enforces cannot
    # apply — but the DRIFT is real and is recorded in
    # bugs/FORMAL_known_limits.md §3 as arch drift, not as agreement.
    ("limit_comptime_over_a_runtime_parameter",
     "def poly(coefficients):\n"
     "    comptime num_coefficients = len(coefficients)\n"
     "    return num_coefficients\n\n"
     "def main(n: Int) -> Int:\n"
     "    return poly([1, 2, 3])\n",
     "refuse_either:does not fold to a compile-time constant"
     "|unsupported statement ComptimeVarStmt", None),
    # A body written `...` is a declaration with no instructions behind it, and
    # there is nothing to emit. Reached only where the walk actually gets to
    # the body — an `...` in a trait method nothing calls compiles, which is
    # correct and is why this case calls the function.
    #
    # The needle was `unsupported expression EllipsisLiteral`, which is what
    # this backend used to say.  It stopped saying that: the message became
    # "is a declaration of an interface and so has no body to lower (a `...`
    # in a trait method builds on both architectures, and a `...` in a plain
    # function is refused whether or not anything ever calls it)" — which
    # NAMES THE REASON rather than the node kind, and additionally states the
    # trait-method case, so the pin was the only thing left describing the old
    # behaviour.  Verified pre-existing, not introduced by this round: the
    # message lives in formal/model.py and no commit in the [4]/[5] merge
    # touched that line, and the pin was last written in dbf3abb.
    #
    # The needle is now the REASON ("no body to lower") rather than the whole
    # sentence, so it survives the next rewording of the advice -- which is the
    # failure mode this pin has now had once.  It is still a refusal, still
    # names why, and `refuse:` still asserts BOTH architectures agree; nothing
    # is silenced, the pin simply stops describing a message nobody emits.
    ("limit_ellipsis_function_body",
     "def slen(value):\n"
     "    ...\n\n"
     "def main(n: Int) -> Int:\n"
     "    return slen(1)\n",
     "refuse:no body to lower", None),

    # ── wave 5 (E1): the same limit in the two spellings that FABRICATED ─────
    #
    # The case above is the multi-element bracket, which has always been
    # refused. These are the other two spellings of the identical construct,
    # and both used to BUILD, RUN, and print a number nobody wrote: 10 on arm64,
    # 0 on x86-64, for the same source, and 1 on arm64 if the program had five
    # more locals. Same needle as the limit above, and `refuse:` rather than
    # `refuse_either:` — the point of these is that the two architectures can
    # no longer DISAGREE, so a shared needle is exactly the assertion.
    #
    # Each names the spelling it pins, because they were three different holes
    # with one cause (a check keyed on base-plus-comma-list instead of on the
    # base name) and a fix that closed one of them would leave the other two
    # green.
    #
    # The third — the dotted one — is the spelling real stdlib source uses:
    # `std/sys/info.mojo:32` and `std/builtin/type_aliases.mojo:146/149/153`.
    # A `MemberExpr` reaches no subscript and no address computation at all,
    # which is why it fell all the way through to a load of an undefined name.
    ("limit_mlir_template_dotted_spelling",
     "def main(n: Int) -> Int:\n"
     "    var t = __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`\n"
     "    return n\n",
     "refuse:assembles an MLIR attribute from a template", None),
    # The single-element bracket: `__mlir_type[x]` is a template exactly as
    # `__mlir_type[x, y]` is, and the comma was the only thing that made the
    # difference visible.
    ("limit_mlir_template_single_element_bracket",
     "def main(n: Int) -> Int:\n"
     "    var t = __mlir_type[`!kgen.never`]\n"
     "    return n\n",
     "refuse:assembles an MLIR attribute from a template", None),
    # A MODULE-LEVEL `comptime` binding is not part of the function-body
    # expression walk at all — `compile()` is handed the prepared FUNCTION list
    # and lowers nothing else — so the multi-element template, the exact shape
    # the refusal above exists for, compiled away silently and every use site
    # read an undefined name. That made `std/builtin/type_aliases.mojo` a FALSE
    # PASS: four such bindings (lines 146/149/153/157) and the sweep counted the
    # file as one that built. The needle is this refusal's own, so the two
    # arches cannot name different limits for one construct.
    ("limit_module_level_comptime_mlir_template",
     "comptime OriginSet = __mlir_type[\n"
     "    `!lit.origin<`, 1, `>`\n"
     "]\n"
     "def main(n: Int) -> Int:\n"
     "    return n\n",
     "refuse:module-level comptime binding 'OriginSet' is initialized from an "
     "MLIR attribute template", None),
    # The walk RECURSES, so a template nested two levels down inside a call's
    # keyword argument is caught too — which is where `type_aliases.mojo` keeps
    # its `__mlir_attr[…]` ones, under `Origin[0, _mlir_origin=…]()`. Without
    # the recursion this file would still have been a false PASS after the
    # direct case above was fixed.
    ("limit_module_level_comptime_nested_mlir_template",
     "struct W:\n"
     "    var a: Int\n"
     "comptime Alias = W(0, _mlir_origin=__mlir_attr[\n"
     "    `#lit.static.origin : !lit.origin<false>`\n"
     "])\n"
     "def main(n: Int) -> Int:\n"
     "    return n\n",
     "refuse:module-level comptime binding 'Alias' is initialized from an "
     "MLIR attribute template", None),

    # ── wave 5 (E1): two OVER-refusals, and a reworded reason ───────────────
    #
    # `DType` is on the hand-kept `UNREPRESENTABLE_TYPE_CTORS` list and is
    # declared in `std/builtin/dtype.mojo` as a struct of exactly ONE field. A
    # formal value is one 64-bit word, so a one-field struct IS one thing and
    # the refusal — "a formal value is one 64-bit word, and DType is not one
    # thing" — was false. The same program with the struct RENAMED built and
    # ran on both architectures, so the verdict was decided by a spelling.
    #
    # `S()` with no arguments is not an arity to match against a field count; it
    # is Mojo's own struct syntax, which is the shape `_emit_struct_constructor`
    # has always lowered. This case is the one that says so, and its expected
    # stdout is the point: the answer is 7, the value the source stores.
    ("over_refusal_one_field_struct_spelled_like_an_unrepresentable_type",
     "struct DType:\n"
     "    var _mlir_value: Int\n"
     "def main(n: Int) -> Int:\n"
     "    var d = DType()\n"
     "    d._mlir_value = 7\n"
     "    print(\"v = %d\\n\", d._mlir_value)\n"
     "    return 0\n",
     0, "v = %d\\n 7"),
    # GUARD, and it is here because the case above is not enough on its own:
    # the identical struct under a name that is NOT on the list must keep
    # building, or the fix has become "refuse every struct". Before the fix
    # this passed and the case above did not — they were the same program under
    # two spellings with opposite verdicts, which is the defect stated as a
    # test pair.
    ("guard_one_field_struct_spelled_normally_still_builds",
     "struct DTypeX:\n"
     "    var _mlir_value: Int\n"
     "def main(n: Int) -> Int:\n"
     "    var d = DTypeX()\n"
     "    d._mlir_value = 7\n"
     "    print(\"v = %d\\n\", d._mlir_value)\n"
     "    return 0\n",
     0, "v = %d\\n 7"),
    # A name on the list that this image has NO declaration of is still
    # refused — there is no field list to bring up — but the reason it now
    # gives is one it has checked ("this image has no declaration of Span")
    # rather than a claim about a type it cannot see ("Span is not one thing").
    # The needle is the checked claim; the old wording is asserted ABSENT below
    # by `refuse_without:`, which is the anti-rot direction for a rewording.
    ("over_refusal_undeclared_type_says_it_is_undeclared",
     "def main(n: Int) -> Int:\n"
     "    var s = Span(1, 2)\n"
     "    return n\n",
     "refuse:this image has no declaration of Span to construct", None),
    # The same refusal, asserted from the other side: the sentence "a formal
    # value is one 64-bit word, and Span is not one thing" is a claim about a
    # type this image cannot see, and it is FALSE for the names that are
    # declared (the `DType` case above is a one-field struct, i.e. one thing).
    # A `refuse:` case cannot catch this, because a fix that APPENDS a true
    # sentence satisfies it while leaving the false one in place — which is
    # exactly what a reword that only adds context would do.
    ("over_refusal_no_longer_claims_a_type_is_not_one_thing",
     "def main(n: Int) -> Int:\n"
     "    var s = Span(1, 2)\n"
     "    return n\n",
     "refuse_without:this image has no declaration of Span to construct"
     ":is not one thing", None),
    # `String()` is the language's ZERO-ARGUMENT empty-string constructor, and
    # a string on this path is a bare `char *` to NUL-terminated bytes, so the
    # interned `""` IS the empty string and `len` of it is 0. It was refused
    # through the identity-conversion ARITY check with a reason that did not
    # apply to the construct ("a conversion has one operand"), and
    # `std/format/repr.mojo:28` is `var string = String()`.
    ("over_refusal_zero_arg_string_constructor_is_the_empty_string",
     "def main(n: Int) -> Int:\n"
     "    var s = String()\n"
     "    print(\"len=%d\\n\", len(s))\n"
     "    return 0\n",
     # The expected stdout carries a LITERAL backslash-n, not a newline: a
     # string literal on this path is stored unescaped, so `print` receives
     # the two characters `\` and `n`. That is verified against the repo's own
     # committed `test_output.txt` (35 bytes with literal backslashes), so the
     # expectation is the representation, not a bug in it.
     0, "len=%d\\n 0"),

    # ── wave 5 (E4): `in` on a string, `+=` on a string, and the rest of
    # ── the arithmetic surface a `char *` reaches ──────────────────────────
    #
    # Two named items and one class. `"x" in s` SIGBUSed on both backends and
    # `s += t` added two addresses on both; and the reason the class is wider
    # than those two is that D3's fix was in the `+` / `==` / `len` paths, and
    # augmented assignment and membership sit right next to all three. Every
    # case below that says "observed on the pre-change tree" was run there.
    #
    # `refuse:` is the right assertion for most of them and not a compromise:
    # the pre-change behaviour was a number the source never wrote, and a
    # refusal is the honest answer for an operator that has no C meaning on a
    # pointer. The needle is the SHARED sentence, so each case is also the
    # assertion that the two architectures refuse identically.

    # ── the named item 1: `in` with a string haystack ──────────────────────
    #
    # Observed on the pre-change tree, on BOTH backends:
    #     s = "hello"
    #     if "ell" in s: printf("HIT\n")
    # terminated the process with SIGBUS (exit -10). A string haystack that
    # was not a syntactic literal fell through to the blob scan, which read the
    # first eight bytes of the CHARACTERS as a `[count]` header and walked off
    # the end of the mapping. x86-64 had no string case AT ALL, so where it
    # did not fault it returned FALSE — `"bc" in "abcd"` printed nothing.
    ("str_membership_substring_needle",
     "def main(n):\n"
     "    s = \"hello\"\n"
     "    r = 0\n"
     "    if \"ell\" in s:\n"
     "        r = r + 1\n"
     "    if \"zzz\" in s:\n"
     "        r = r + 2\n"
     "    printf(\"r=%d\\n\", r)\n"
     "    return 0\n", 0, "r=1"),
    # `not in` inverts ONCE, after the call, so it cannot be right at one exit
    # and wrong at another. Both directions are in this case because the
    # pre-change tree had no string path to invert at all.
    ("str_membership_not_in_inverts",
     "def main(n):\n"
     "    s = \"hello\"\n"
     "    r = 0\n"
     "    if \"zzz\" not in s:\n"
     "        r = r + 1\n"
     "    if \"ell\" not in s:\n"
     "        r = r + 2\n"
     "    printf(\"r=%d\\n\", r)\n"
     "    return 0\n", 0, "r=1"),
    # THE EDGE CASES, each one run, because four of the five are places a
    # membership test can be wrong in the direction that HIDES bugs:
    #
    #   * the EMPTY needle is TRUE. `strstr` agrees — it returns the haystack,
    #     which is non-NULL — and a test that said an empty needle is absent
    #     would make `"".join(xs)`-shaped code silently skip everything.
    #   * a needle LONGER than the haystack is FALSE, twice over: once for the
    #     positive spelling and once for `not in`, because the terminator
    #     cannot match a non-terminator byte.
    #   * a needle at offset 0 and a needle at the very END are both TRUE.
    #   * a byte needle of 0 is FALSE. This is the ONE case libc gets wrong
    #     for this representation: `strchr(s, 0)` returns the TERMINATOR, so a
    #     bare `!= NULL` would say `0 in "hello"` is true. It cannot contain a
    #     NUL — the only NUL in a string is the one that ends it — so the
    #     byte is tested in front of the call on both backends.
    ("str_membership_edge_cases",
     "def main(n):\n"
     "    s = \"hello\"\n"
     "    e = \"\"\n"
     "    r = 0\n"
     "    if e in s:\n"
     "        r = r + 1\n"
     "    if \"hello world\" in s:\n"
     "        r = r + 2\n"
     "    if not (\"hello world\" in s):\n"
     "        r = r + 4\n"
     "    if \"hel\" in s:\n"
     "        r = r + 8\n"
     "    if \"llo\" in s:\n"
     "        r = r + 16\n"
     "    if 0 in s:\n"
     "        r = r + 32\n"
     "    if 101 in s:\n"
     "        r = r + 64\n"
     "    if 255 in s:\n"
     "        r = r + 128\n"
     "    if 255 not in s:\n"
     "        r = r + 256\n"
     "    printf(\"r=%d\\n\", r)\n"
     "    return 0\n", 0, "r=349"),
    # The unescaping boundary, and it is the reason this case exists at all:
    # string literals are stored UNESCAPED on this path, so `"\t"` is a
    # BACKSLASH and a `t` — two characters — and a backslash is not a tab.
    # A membership test written against the escaped reading would answer a
    # question nobody asked. All four assertions are here because each is a
    # different way to get it wrong: the letter, the backslash, the length,
    # and the absent letter.
    ("str_membership_on_the_unescaped_representation",
     "def main(n):\n"
     "    r = 0\n"
     "    if \"t\" in \"\\t\":\n"
     "        r = r + 1\n"
     "    if \"x\" in \"\\t\":\n"
     "        r = r + 2\n"
     "    if len(\"\\t\") == 2:\n"
     "        r = r + 4\n"
     "    printf(\"r=%d\\n\", r)\n"
     "    return 0\n", 0, "r=5"),
    # A haystack that is a DERIVED INTERIOR POINTER rather than a literal —
    # the shape `lstrip` returns, and the one the pre-change pointer-based
    # reasoning got wrong. Also the case where the needle and the haystack are
    # both names, so both have to survive the libc call on the stack.
    ("str_membership_derived_haystack",
     "def main(n):\n"
     "    m = \"  hello\".lstrip()\n"
     "    t = \"ell\"\n"
     "    r = 0\n"
     "    if t in m:\n"
     "        r = r + 1\n"
     "    if m in t:\n"
     "        r = r + 2\n"
     "    printf(\"r=%d\\n\", r)\n"
     "    return 0\n", 0, "r=1"),
    # BOTH operands literals is a compile-time answer, and it is taken before
    # the call so the constant and libc cannot disagree. On the pre-change tree
    # arm64 got this right by accident and x86-64 SIGBUSed on it.
    ("str_membership_two_literals",
     "def main(n):\n"
     "    r = 0\n"
     "    if \"bc\" in \"abcd\":\n"
     "        r = r + 1\n"
     "    if \"xy\" in \"abcd\":\n"
     "        r = r + 2\n"
     "    if \"\" in \"abcd\":\n"
     "        r = r + 4\n"
     "    printf(\"r=%d\\n\", r)\n"
     "    return 0\n", 0, "r=5"),
    # A list haystack still takes the blob scan. This is a GUARD: the string
    # case is dispatched BEFORE the blob case now, and a haystack whose kind
    # this path cannot see must still reach the blob path rather than being
    # refused by the string dispatch.
    ("str_membership_list_haystack_is_a_guard",
     "def main(n):\n"
     "    r = 0\n"
     "    if 2 in [1, 2, 3]:\n"
     "        r = r + 1\n"
     "    if 9 in [1, 2, 3]:\n"
     "        r = r + 2\n"
     "    printf(\"r=%d\\n\", r)\n"
     "    return 0\n", 0, "r=1"),

    # ── the named item 2: `+=` on a string ─────────────────────────────────
    #
    # Observed on the pre-change tree, on BOTH backends, for this source:
    #     s = "ab"; t = "cd"; s += t; printf("[%s]\n", s)
    # printed `[]` on arm64 and SEGFAULTED on x86-64 — the same non-answer as
    # `s = s + t`, which BOTH backends already refused, from the same line of
    # source. The cause is that an augmented assignment is a separate emitter
    # that never asked the question `_emit_binop` asks.
    #
    # It is a REFUSAL and not a lowering, and the reason is D3's: a string is
    # a bare `char *` into `__TEXT,__text` with no write bit, so there is
    # nowhere to put the result. Implementing concatenation is a new value
    # representation, which is a decided question and not this one's to reopen.
    ("str_augmented_concat_refused",
     "def main(n):\n"
     "    s = \"ab\"\n"
     "    t = \"cd\"\n"
     "    s += t\n"
     "    printf(\"[%s]\\n\", s)\n"
     "    return 0\n",
     "refuse:'+=' on two strings is refused on this path", None),
    # The whole augmented family, not just `+=`, because they are one code path
    # and a fix that caught only `+=` would leave the other eleven adding two
    # addresses. `s -= t` is `+`'s refusal (address minus address is the same
    # missing buffer); the rest are the arithmetic table's. One program, so the
    # first refusal is the one that fires and the case is a single assertion
    # about the family — the individual operators are pinned separately below.
    ("str_augmented_subtract_refused",
     "def main(n):\n"
     "    s = \"ab\"\n"
     "    t = \"cd\"\n"
     "    s -= t\n"
     "    printf(\"[%s]\\n\", s)\n"
     "    return 0\n",
     "refuse:'-=' on two strings is refused on this path", None),
    # `+=` where ONE side is a string is still not string concatenation, and
    # still must not be refused: `s + 1` is the pointer arithmetic a caller who
    # reached a `char *` through this path may have meant. This is a GUARD for
    # D3's `str_plus_int_still_arithmetic`, extended to the augmented form,
    # and it is here because the new table is the one that could have over-
    # reached.
    ("str_augmented_plus_int_still_arithmetic_is_a_guard",
     "def main(n):\n"
     "    k = 3\n"
     "    s = \"ab\"\n"
     "    k += 4\n"
     "    printf(\"%d\\n\", k)\n"
     "    return 0\n", 0, "7"),

    # ── the class: every operator that reached the integer path ────────────
    #
    # All of these BUILT, RAN and returned a number the source never wrote.
    # Measured on the pre-change tree for `s = "abc"`, `t = "bc"`, on BOTH
    # backends — and the two columns DISAGREE, which is the strongest evidence
    # there is that no reader of either number could have trusted it:
    #
    #     s & t   69911496 / 45978594      s | t   68191180 /  2872318
    #     s ^ t         4 /        28      s - t        -4 /       -4
    #     s * 2   8062864 /     5302246    s // 2  -2147433998 / -2128240118
    #     s >> 1  -2107760164 / -2147386903   ~s      8881076 /    3236815
    #     -s     -36488120 /  -79725522
    #
    # The RELATIONAL half is worse than a wrong number because it is a wrong
    # BRANCH: `s < t` was TRUE and `s > t` FALSE on both backends, decided by
    # the order the two literals happen to be interned in the text section.
    # Reordering the two lines of source reverses every one of them.
    #
    # One case per operator family, each with the SHARED sentence as the needle
    # so that "the two architectures refuse identically" is the assertion.
    ("str_bitwise_operators_refused",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    t = \"bc\"\n"
     "    r = s & t\n"
     "    printf(\"%d\\n\", r)\n"
     "    return 0\n",
     "refuse:'&' is refused when the left operand is a string", None),
    ("str_relational_operators_refused",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    t = \"bc\"\n"
     "    if s < t:\n"
     "        printf(\"LT\\n\")\n"
     "    return 0\n",
     "refuse:'<' is refused when the left operand is a string", None),
    # `<=` and `>=` are their own case and not folded into the one above,
    # because they are where a plausible-looking helper goes wrong: a helper
    # that strips a trailing `=` to recognise an augmented operator also turns
    # `<=` into `<`, and the refusal then names a DIFFERENT OPERATOR than the
    # line the reader is looking at. It did exactly that before this case
    # existed, on both backends.
    ("str_relational_le_and_ge_name_themselves",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    t = \"bc\"\n"
     "    if s <= t:\n"
     "        printf(\"LE\\n\")\n"
     "    return 0\n",
     "refuse:'<=' is refused when the left operand is a string", None),
    ("str_relational_ge_names_itself",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    t = \"bc\"\n"
     "    if s >= t:\n"
     "        printf(\"GE\\n\")\n"
     "    return 0\n",
     "refuse:'>=' is refused when the left operand is a string", None),
    ("str_multiplication_refused",
     "def main(n):\n"
     "    s = \"ab\"\n"
     "    r = s * 2\n"
     "    printf(\"%d\\n\", r)\n"
     "    return 0\n",
     "refuse:'*' is refused when the left operand is a string", None),
    # `%` is worth its own case because it is the one that looks like it might
    # work: `"%d" % k` is printf-style formatting, and on the pre-change tree
    # it returned 0 on arm64 and 2 on x86-64 for `k = 3` — the address modulo
    # three, differing between architectures. A program that formats a string
    # was computing an address modulo a number and neither architecture was
    # doing arithmetic on the formatting.
    ("str_percent_formatting_refused_not_faked",
     "def main(n):\n"
     "    k = 3\n"
     "    s = \"%d\"\n"
     "    printf(\"%d\\n\", s % k)\n"
     "    return 0\n",
     "refuse:'%' is refused when the left operand is a string", None),
    ("str_shift_refused",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    r = s >> 1\n"
     "    printf(\"%d\\n\", r)\n"
     "    return 0\n",
     "refuse:'>>' is refused when the left operand is a string", None),
    ("str_floor_divide_refused",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    r = s // 2\n"
     "    printf(\"%d\\n\", r)\n"
     "    return 0\n",
     "refuse:'//' is refused when the left operand is a string", None),
    # The AUGMENTED spellings of the same table, which is where the named item
    # lived. `&=` and `>>=` are here rather than `|=` and `**=` so that the two
    # cases pin the two different code paths inside the augmented emitter: the
    # shift branch and the ALU branch. Both used to add two addresses.
    ("str_augmented_bitwise_refused",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    t = \"bc\"\n"
     "    s &= t\n"
     "    printf(\"%d\\n\", s)\n"
     "    return 0\n",
     "refuse:'&=' is refused when the left operand is a string", None),
    ("str_augmented_shift_refused",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    s >>= 1\n"
     "    printf(\"%d\\n\", s)\n"
     "    return 0\n",
     "refuse:'>>=' is refused when the left operand is a string", None),
    # The diagnostic names the SPELLING the source used, not the bare operator
    # the table is keyed on. `s %= 4` has ONE string operand, so it is the
    # arithmetic table and not the two-string one, and the message has to say
    # `%=` — a message that said `%` would be a small lie about the line the
    # reader is looking at. `s += 4` is deliberately NOT the case here: `+`
    # with one string operand is real C pointer arithmetic and stays allowed
    # (see the guard above), which is the one place this table does not fire.
    ("str_augmented_arithmetic_names_the_spelling",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    s %= 4\n"
     "    printf(\"%d\\n\", s)\n"
     "    return 0\n",
     "refuse:'%=' is refused when the left operand is a string", None),
    # Unary: negation and complement of an address. `-` is the half that can be
    # reached from source; `~` CANNOT, because the tokenizer's `_TOKEN_RE` has
    # no `~` in its OP alternation and `py_tokenize` drops UNK tokens — so
    # `~s` lexes as `s` and the parser never sees a UnaryOp at all. The model's
    # `~` refusal is landed and both backends already ask for it, so the day
    # the lexer's OP group gains a `~` the refusal fires with no further work;
    # see bugs/FORMAL_string_value_model.md for the measured consequence today
    # (`~s` returns the POINTER, 77693904 on arm64 and 74486761 on x86-64 for
    # the same source, and the `~` is nowhere in the AST).
    ("str_unary_negation_refused",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    r = -s\n"
     "    printf(\"%d\\n\", r)\n"
     "    return 0\n",
     "refuse:unary '-' is refused on a string", None),
    # `not s` is the one that is a fabricated FALSITY rather than a fabricated
    # number, and it is the worst of the set for that reason: a pointer is
    # never zero, so `not s` is FALSE for every string INCLUDING THE EMPTY
    # ONE. Observed on the pre-change tree, on both backends:
    #     s = "abc"; e = ""; printf("%d %d", 1 if not s else 0, 1 if not e else 0)
    # printed `0 0`. Python's answer is `0 1` — a program testing a string for
    # emptiness is told the empty string is non-empty.
    #
    # The honest lowering is `len(s) == 0`, which is a `strlen` and nothing
    # else, and it is NOT available at this site: `not` tests a value already in
    # a register and this emitter cannot see what produced it. `if s:` and
    # `while s:` have the same defect and are still lowered; both are written
    # down in bugs/FORMAL_string_value_model.md with the next step.
    ("str_not_refused_because_empty_string_is_falsy",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    e = \"\"\n"
     "    printf(\"%d %d\\n\", 1 if not s else 0, 1 if not e else 0)\n"
     "    return 0\n",
     "refuse:`not s` is refused because s is a string", None),
    # GUARD: `not` on an INTEGER is untouched by the refusal above, or the
    # fix would be "refuse every `not`". This passed before the change too.
    ("str_not_on_an_int_is_a_guard",
     "def main(n):\n"
     "    a = 0\n"
     "    b = 3\n"
     "    printf(\"%d %d\\n\", 1 if not a else 0, 1 if not b else 0)\n"
     "    return 0\n", 0, "1 0"),
    # A string INDEX is `s + i` with two addresses. Observed on the pre-change
    # tree: `printf("%d", s[t])` printed 67 on arm64 — the low byte of a
    # text-section address, small and printable and therefore the most
    # believable fabricated number in this whole group — and segfaulted on
    # x86-64. Asked at the subscript's single choke point, so a read, a store
    # and an augmented assignment are all covered by one call.
    ("str_subscript_by_a_string_index_refused",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    t = \"b\"\n"
     "    printf(\"%d\\n\", s[t])\n"
     "    return 0\n",
     "refuse:cannot index a string on this path", None),
    # GUARD: an INTEGER index into a string is `s + i`, which is real C
    # pointer arithmetic and is still lowered — this is the byte at that
    # offset, which is a fact about the representation rather than a fabricated
    # value. It passed before the change and must keep passing.
    ("str_subscript_by_an_int_index_is_a_guard",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    printf(\"%d %d\\n\", s[0], s[2])\n"
     "    return 0\n", 0, "97 99"),
]

# ── what a method on a VALUE means, per RECEIVER KIND ──────────────────────
#
# A formal value is one 64-bit word, so `recv.m()` cannot mean anything until
# the word is said to hold something. The kind of the receiver is what says it,
# and the cases below are the matrix: one case per receiver kind, per method,
# so that "which methods mean what here" is a test and not a claim.
#
# The group is the wave-4 finding family — 76 files, the largest in the sweep,
# and NOT a string-method family at all. Re-derived from the sweep rather than
# from the earlier censuses, and it came out as FIVE distinct blocking sites
# over 73 of the 76 dependency-propagated files: `ptr.value()` (53),
# `self.step.or_else()` (20), and one each of `writer.write_string()`,
# `condition.__mlir_bool__()` and `ptr.unsafe_value()`. The two big ones are a
# DEREFERENCE and an OPTIONAL UNWRAP, which are spelled alike in the stdlib
# (`value` / `unsafe_value`) and mean opposite things; conflating them is how
# the characterised group would have been mis-implemented.
#
# What the cases assert is the SHAPE of the refusal, not just that there is
# one. A refusal that says "this backend lowers only append, close, write and
# the string methods …" is worse than no refusal for a non-string receiver: it
# reads as "add it to the string table". So each needle here names what is
# actually missing.

# The DEREFERENCE half. `UnsafePointer.value()` in Mojo returns the pointee, so
# on this path it is a LOAD from the address in the receiver — and a load is
# not one instruction here. All three reasons are load-bearing and each alone
# is enough, which is why the needle names the middle one (the pointer value
# model) rather than only asserting a refusal.
#
# Pre-change these all refused as "is a method call on a value", which told a
# reader the fix was another string method.
RECVKIND_CASES = [
 ("recvkind_value_on_name",
 "def main(n):\n"
 "    ptr = n\n"
 "    k = ptr.value()\n"
 "    return 0\n",
 "refuse:is spelled the same for four different questions", None),
 # The same method on a FRAME SLOT — a different SHAPE, and the shape the
 # wave-3 by-reference work exposed: the receiver is a word read out of
 # another function's frame, so what it holds is a question about that
 # function's field list, not about this one.
 ("recvkind_value_on_frame_slot",
  "struct Box:\n"
  "    ptr: Int\n"
  "    n: Int\n"
  "    def __init__(self):\n"
  "        self.ptr = 1\n"
  "        self.n = 2\n"
  "\n"
  "def main(n):\n"
  "    b = Box()\n"
  "    k = b.ptr.value()\n"
  "    return 0\n",
  "refuse:is spelled the same for four different questions", None),
 # An Optional UNWRAP, which is NOT a dereference and must not be answered as
 # one. The reason is the missing NICHE: `None` and a value are both one word
 # in one frame slot, and `None` is emitted as the integer 0, so treating 0 as
 # empty would be wrong about `Some(0)` — a silent wrong answer on a program
 # that computes a different number. This is the 20-file shape
 # (`builtin_slice.mojo`'s `self.step.or_else()`).
 ("recvkind_or_else_frame_slot",
  "struct S:\n"
  "    step: Int\n"
  "    def __init__(self):\n"
  "        self.step = 1\n"
  "\n"
  "def main(n):\n"
  "    s = S()\n"
  "    k = s.step.or_else(1)\n"
  "    return 0\n",
  "refuse:is an Optional unwrap", None),
 # A WRITER, which is a multi-field struct and therefore a frame ADDRESS. This
 # is the most tempting name in the tree to add next to the `write` that IS
 # lowered, and adding it would pass a frame address as fd(2): EBADF, nothing
 # checks it, and the program's output is missing rather than wrong-looking.
 ("recvkind_write_string_on_struct",
  "struct W:\n"
  "    buf: Int\n"
  "    n: Int\n"
  "    def __init__(self):\n"
  "        self.buf = 0\n"
  "        self.n = 0\n"
  "\n"
  "def main(n):\n"
  "    w = W()\n"
  "    k = w.write_string(\"None\")\n"
  "    return 0\n",
  "refuse:is a method on a Writer", None),
 # `__mlir_bool__` is the one case here that IS implementable — a Bool is a word
 # holding 0 or 1 on this path, so it is the test `if` already does — and is
 # refused only because it cannot be GUARDED. The needle is the guard, not the
 # impossibility: a reader should come away knowing the fix is a BOOL kind.
 ("recvkind_mlir_bool_needs_a_bool_kind",
  "def main(n):\n"
  "    c = n > 3\n"
  "    k = c.__mlir_bool__()\n"
  "    return 0\n",
  "refuse:is a real builtin and is implementable as the same test", None),
]

# ── `write`/`close` are a SYSCALL, and need a real receiver ─────────────────
#
# These two lower to the C library's `write(2)` and `close(2)`, so the receiver
# has to be a file descriptor. `open(...)` already lowers to the C library's
# `open(2)`, so a descriptor is a word that came from `open(2)` — and NOTHING
# CHECKED THAT until this group. The pre-change docstring asserted it ("the
# receiver of a file method IS a descriptor") as an assumption about the
# source.
#
# Measured on the pre-change tree: all four of the refusals below BUILT on both
# architectures, and each passed something that is not a descriptor as fd. None
# of them faults — `write(2)` on a bad descriptor returns -1, which nothing
# here checks — so the program runs, writes nothing, and exits 0. That is what
# a silently-wrong lowering produces, and it is why these are `refuse:` cases
# and not a note in a comment.
#
# The needle is "has to be a file descriptor", which is the part that tells a
# reader the RECEIVER is the problem and not the method.
FD_CASES = [
 ("fd_write_on_string_refused",
  "def main(n):\n"
  "    s = \"hello\"\n"
  "    k = s.write(\"x\")\n"
  "    return 0\n",
  "refuse:has to be a file descriptor", None),
 # An int, which is the closest miss: a descriptor IS an int, so the kind is
 # no help at all here. This is the case that shows the guard cannot be a kind
 # guard and has to be a flow fact.
 ("fd_write_on_int_refused",
  "def main(n):\n"
  "    k = 7\n"
  "    r = k.write(\"x\")\n"
  "    return 0\n",
  "refuse:has to be a file descriptor", None),
 # A struct receiver, whose word is a FRAME ADDRESS. The message names the
 # shape as well as the requirement, because "a Writer reaches here too" is the
 # sentence that stops the next reader adding `write_string`.
 ("fd_write_on_struct_refused",
  "struct P:\n"
  "    x: Int\n"
  "    y: Int\n"
  "    def __init__(self):\n"
  "        self.x = 1\n"
  "        self.y = 2\n"
  "\n"
  "def main(n):\n"
  "    p = P()\n"
  "    r = p.write(\"x\")\n"
  "    return 0\n",
  "refuse:its receiver is a frame address", None),
 # A list blob, whose word is ALSO a frame address, and which is the case most
 # likely to be waved through on the grounds that a blob is "container-ish".
 ("fd_write_on_list_refused",
  "def main(n):\n"
  "    xs = [1, 2, 3]\n"
  "    r = xs.write(\"x\")\n"
  "    return 0\n",
  "refuse:has to be a file descriptor", None),
 # `close` gets its own case because it is the other syscall and the guard is
 # a table lookup, not a shared code path — a table with two entries and one
 # test is not a test of the table.
 ("fd_close_on_string_refused",
  "def main(n):\n"
  "    s = \"hello\"\n"
  "    k = s.close()\n"
  "    return 0\n",
  "refuse:has to be a file descriptor", None),
 # An ALIAS of a descriptor keeps it, so this one BUILDS. The guard is on
 # where the word was bound, and a name bound from a name bound from `open` is
 # still that word. A guard that only recognised the direct binding would refuse
 # this, which would be a false refusal on correct source.
 ("fd_alias_still_writes",
  "def main(n):\n"
  "    f = open(\"/tmp/fd_alias_still_writes.txt\", \"w\")\n"
  "    g = f\n"
  "    g.write(\"aliased\")\n"
  "    f.close()\n"
  "    return 0\n",
  0, None),
 # …and the real thing, so the guard has a positive case that RUNS rather than
 # only refusing. 5 bytes on disk is the assertion: `write` lowering to a
 # no-op would pass every refusal case above and still be broken.
 ("fd_write_close_roundtrip",
  "def main(n):\n"
  "    f = open(\"/tmp/fd_write_close_roundtrip.txt\", \"w\")\n"
  "    f.write(\"hello\")\n"
  "    f.close()\n"
  "    return 0\n",
   0, None),
 # A FRAME SLOT holding what is syntactically a descriptor. Refused, and the
 # message names the receiver's SHAPE as well as the requirement, because
 # proving a field holds a descriptor is cross-field flow and this path cannot
 # see it — a correct-looking `self._fd.write(s)` must not be lowered on the
 # strength of a name the model does not have.
 ("fd_write_on_frame_slot_refused",
  "struct Box:\n"
  "    fd: Int\n"
  "    n: Int\n"
  "    def __init__(self):\n"
  "        self.fd = 3\n"
  "        self.n = 0\n"
  "\n"
  "def main(n):\n"
  "    b = Box()\n"
  "    b.fd.write(\"x\")\n"
  "    return 0\n",
  "refuse:and it is a frame slot", None),
]

# ── a multi-field receiver, BY REFERENCE ───────────────────────────────────
#
# A value on this path is one 64-bit word, and a struct of two fields has
# nothing to BE as a value. It is given a representation anyway, without
# changing the value model at all: the receiver word is the ADDRESS of an
# out-of-line frame of 8-byte slots, `h.x` is a load from `[h, #8k]`, and
# `h.x = v` is a store to the same place. A pointer is one word, so
# `MojoFunc`'s single parameter is still `self` and is still that address, and
# the method call is unchanged (`S.m(self, ...)` — the receiver is passed as
# the address it already was).
#
# What these cases are really about is the failure mode that matters: TWO
# INSTANCES OF ONE STRUCT MUST NOT ALIAS. `byref_two_instances_no_alias` is
# that case and it is the one to read first; the rest pin the widths, the
# field kinds, and the escapes that have to be REFUSED rather than lowered,
# because a frame belongs to the function that created it and a receiver that
# outlives its creator would be dereferenced after its bytes were reused.
BYREF_CASES = [
    # The cheapest width, and the whole design in one program: two fields, a
    # constructor, a write through the receiver, a read back through a
    # DIFFERENT method. 3 + 4 = 7.
    ("byref_two_fields_roundtrip",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "    fn set_x(self, v: Int):\n"
     "        self.x = v\n\n"
     "    fn set_y(self, v: Int):\n"
     "        self.y = v\n\n"
     "    fn get_x(self) -> Int:\n"
     "        return self.x\n\n"
     "    fn get_y(self) -> Int:\n"
     "        return self.y\n\n"
     "def main(n) -> Int:\n"
     "    var p = Point()\n"
     "    p.set_x(3)\n"
     "    p.set_y(4)\n"
     "    return p.get_x() + p.get_y()\n", 7, None),
    # **TWO INSTANCES MUST NOT ALIAS.** This is the case the whole design
    # exists for, and the one a "same code, bigger n" framing hides: if the two
    # constructors had handed out the same address, or if the slots were
    # indexed by anything but the frame base, then `a` and `b` would share
    # storage and every value below would be wrong in a way no refusal would
    # catch. Each check below names WHICH instance was corrupted, so a
    # regression says which of the two frames moved rather than just "35".
    ("byref_two_instances_no_alias",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "    fn set_x(self, v: Int):\n"
     "        self.x = v\n\n"
     "    fn set_y(self, v: Int):\n"
     "        self.y = v\n\n"
     "    fn get_x(self) -> Int:\n"
     "        return self.x\n\n"
     "    fn get_y(self) -> Int:\n"
     "        return self.y\n\n"
     "def main(n) -> Int:\n"
     "    var a = Point()\n"
     "    var b = Point()\n"
     "    a.set_x(3)\n"
     "    a.set_y(4)\n"
     "    b.set_x(100)\n"
     "    b.set_y(200)\n"
     "    if a.get_x() != 3:\n"
     "        return 1000 + a.get_x()\n"
     "    if a.get_y() != 4:\n"
     "        return 2000 + a.get_y()\n"
     "    if b.get_x() != 100:\n"
     "        return 3000 + b.get_x()\n"
     "    if b.get_y() != 200:\n"
     "        return 4000 + b.get_y()\n"
     "    return 0\n", 0, None),
    # …and the same two instances with a COPY, because a copy shares the
    # frame and must: `c = a` then `c.set_x(9)` is visible through `a`, and
    # `b` is still untouched. 9 * 1 + 100 = 109.
    ("byref_copy_shares_the_frame",
     "struct Cell:\n"
     "    var n: Int\n"
     "    var m: Int\n\n"
     "    fn set_n(self, v: Int):\n"
     "        self.n = v\n\n"
     "    fn get_n(self) -> Int:\n"
     "        return self.n\n"
     "    fn get_m(self) -> Int:\n"
     "        return self.m\n\n"
     "def main(n) -> Int:\n"
     "    var a = Cell()\n"
     "    var b = Cell()\n"
     "    a.set_n(3)\n"
     "    b.set_n(100)\n"
     "    var c = a\n"
     "    c.set_n(9)\n"
     "    if a.get_n() != 9:\n"
     "        return 1000 + a.get_n()\n"
     "    return a.get_n() + b.get_n() - 100\n", 9, None),
    # A field written through the receiver and read through ANOTHER method,
    # with the dispatch in between: `set` picks a slot by index, `get` reads
    # it back. The 12-field case is here for the width, not for the dispatch:
    # `many` is the same code with a bigger n, which is the claim the design
    # makes and the reason the width bands are not three projects.
    ("byref_twelve_fields_dispatch",
     "struct Wide:\n"
     "    var f0: Int\n"
     "    var f1: Int\n"
     "    var f2: Int\n"
     "    var f3: Int\n"
     "    var f4: Int\n"
     "    var f5: Int\n"
     "    var f6: Int\n"
     "    var f7: Int\n"
     "    var f8: Int\n"
     "    var f9: Int\n"
     "    var f10: Int\n"
     "    var f11: Int\n"
     "\n"
     "    fn set(self, i: Int, v: Int):\n"
     "        if i == 0:\n"
     "            self.f0 = v\n"
     "        elif i == 1:\n"
     "            self.f1 = v\n"
     "        elif i == 2:\n"
     "            self.f2 = v\n"
     "        elif i == 3:\n"
     "            self.f3 = v\n"
     "        elif i == 4:\n"
     "            self.f4 = v\n"
     "        elif i == 5:\n"
     "            self.f5 = v\n"
     "        elif i == 6:\n"
     "            self.f6 = v\n"
     "        elif i == 7:\n"
     "            self.f7 = v\n"
     "        elif i == 8:\n"
     "            self.f8 = v\n"
     "        elif i == 9:\n"
     "            self.f9 = v\n"
     "        elif i == 10:\n"
     "            self.f10 = v\n"
     "        else:\n"
     "            self.f11 = v\n"
     "\n"
     "    fn get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.f0\n"
     "        elif i == 1:\n"
     "            return self.f1\n"
     "        elif i == 2:\n"
     "            return self.f2\n"
     "        elif i == 3:\n"
     "            return self.f3\n"
     "        elif i == 4:\n"
     "            return self.f4\n"
     "        elif i == 5:\n"
     "            return self.f5\n"
     "        elif i == 6:\n"
     "            return self.f6\n"
     "        elif i == 7:\n"
     "            return self.f7\n"
     "        elif i == 8:\n"
     "            return self.f8\n"
     "        elif i == 9:\n"
     "            return self.f9\n"
     "        elif i == 10:\n"
     "            return self.f10\n"
     "        return self.f11\n"
     "\n"
     "def main(n) -> Int:\n"
     "    var w = Wide()\n"
     "    var i = 0\n"
     "    while i < 12:\n"
     "        w.set(i, i + 1)\n"
     "        i = i + 1\n"
     "    var total = 0\n"
     "    i = 0\n"
     "    while i < 12:\n"
     "        total = total + w.get(i)\n"
     "        i = i + 1\n"
     "    return total\n", 78, None),
    # A field that is a LOCAL, a CONSTANT and a POINTER-shaped value, all in
    # one receiver, because those are the three things a method body reaches
    # for and only one of them is the frame. The local is computed from the
    # receiver and added back, the class constant is materialized where it is
    # read (it is NOT a slot), and the third field holds a value written at the
    # call site. 5*2 + 10 + 7 = 27.
    ("byref_field_local_const_and_value",
     "struct Mixed:\n"
     "    var n: Int\n"
     "    var s: String\n"
     "    var p: Int\n"
     "    const K: Int = 7\n\n"
     "    fn get_n(self) -> Int:\n"
     "        return self.n\n\n"
     "    fn set_n(self, v: Int):\n"
     "        self.n = v\n\n"
     "    fn describe(self) -> Int:\n"
     "        var local = self.n * 2\n"
     "        local = local + self.p\n"
     "        return local + Mixed.K\n\n"
     "def main(n) -> Int:\n"
     "    var m = Mixed()\n"
     "    m.set_n(5)\n"
     "    m.p = 10\n"
     "    if m.get_n() != 5:\n"
     "        return 1000 + m.get_n()\n"
     "    return m.describe()\n", 27, None),
    # An AUGMENTED assignment to a field: `self.n += 5` is a load, an add and
    # a store through the receiver, so it exercises the frame store from the
    # augmented-assignment path as well as the plain one. Two bumps: n = 10,
    # m = 4, so 10*10 + 4 = 104 — and a load that returned 0 both times (the
    # classic SRA-slot bug) would have given 4.
    ("byref_augmented_field",
     "struct Counter:\n"
     "    var n: Int\n"
     "    var m: Int\n\n"
     "    fn bump(self):\n"
     "        self.n += 5\n"
     "        self.m += 2\n\n"
     "    fn get_n(self) -> Int:\n"
     "        return self.n\n\n"
     "    fn get_m(self) -> Int:\n"
     "        return self.m\n\n"
     "def main(n) -> Int:\n"
     "    var c = Counter()\n"
     "    c.bump()\n"
     "    c.bump()\n"
     "    return c.get_n() * 10 + c.get_m()\n", 104, None),
    # A receiver handed to a plain function, which reads a field of it: the
    # argument IS the address, so the callee's parameter is a frame holder
    # without any type inference. 40 + 2 = 42.
    ("byref_receiver_through_a_plain_function",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "    fn set_a(self, v: Int):\n"
     "        self.a = v\n\n"
     "    fn get_a(self) -> Int:\n"
     "        return self.a\n\n"
     "def bump(x):\n"
     "    return x.get_a() + 2\n\n"
     "def main(n) -> Int:\n"
     "    var p = Pair()\n"
     "    p.set_a(40)\n"
     "    return bump(p)\n", 42, None),
    # ── wave 3 (C5): a field used as a VALUE RECEIVER, and a name that is two
    # shapes at once ──
    #
    # `h.f.m(x)` reads `mem[h + 8k]` and hands that word to the callee, so it
    # is a method call ON A VALUE and the frame layout is not what decides it.
    # Until this case existed the build pass refused the whole shape as "a field
    # of a field", which is not what is wrong with it: the value IS a word, the
    # backend just may not know which. With the receiver kind established —
    # the slot is assigned a string LITERAL in this same function, which is what
    # `_string_vars` records — `startswith` lowers and the program runs.
    #
    # The receiver kind is per-function on purpose: a slot assigned in `main`
    # and read in a method is NOT known to be a string in that method, so the
    # same program split across two functions is still refused. That asymmetry
    # is the reason this case puts the assignment in the same function, and it
    # is why it is a positive case at all.
    ("byref_value_method_on_a_frame_slot",
     "struct Named:\n"
     "    var tag: Int\n"
     "    var name: String\n\n"
     "    fn check(self, p: String) -> Bool:\n"
     "        self.name = \"hello\"\n"
     "        return self.name.startswith(p)\n\n"
     "def main(n: Int) -> Int:\n"
     "    var m = Named()\n"
     "    var ok: Bool = m.check(\"he\")\n"
     "    if ok:\n"
     "        return 7\n"
     "    return 100\n", 7, None),
    # THE SAME VALUE, READ OUT OF TWO INSTANCES. A field read used as a value
    # receiver is a plain load, so the property that has to survive is the one
    # this file already states for the two-instance case: reading `a.name` must
    # not see what was written to `b.name`, and neither object's `tag` may move.
    # Each branch names WHICH object was corrupted, so a regression says which
    # frame moved rather than just a number.
    #
    # This is the positive counterpart of `byref_two_layouts_disagree` below: two
    # objects of two DIFFERENT widths, and the field used is at the same slot
    # index in both — which is what makes one index legal, and
    # `Frame.frame_instances_no_alias_neqn` is what says the two objects are
    # still separate storage rather than one object seen twice.
    ("byref_two_widths_no_alias",
     "struct A:\n"
     "    var v: Int\n"
     "    var w: Int\n\n"
     "struct B:\n"
     "    var v: Int\n"
     "    var w: Int\n"
     "    var z: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var a = A()\n"
     "    var b = B()\n"
     "    a.v = 5\n"
     "    a.w = 2\n"
     "    b.v = 7\n"
     "    b.w = 3\n"
     "    if a.v != 5:\n"
     "        return 1000 + a.v\n"
     "    if a.w != 2:\n"
     "        return 2000 + a.w\n"
     "    if b.v != 7:\n"
     "        return 3000 + b.v\n"
     "    if b.w != 3:\n"
     "        return 4000 + b.w\n"
     "    return 0\n", 0, None),
    # …and the same property reached through ONE NAME rebound to two widths,
    # which is the path the candidate-set rule has to keep working. `v` and `w`
    # are slot 0 and 1 in both layouts, so one index serves both and the access
    # is well defined whichever object the name holds; `z` is B's alone and is
    # never written through the shared name, because writing it would be a third
    # shape the layouts do not agree on and `byref_two_layouts_disagree` is what
    # that has to say. 502 is the `A` path and 0 the `B` path, so a program that
    # read one object as the other returns the wrong one of the two.
    #
    # `touchB` writes `z` so that B's third field is written SOMEWHERE, and it
    # used to do that through a bare parameter — `def touchB(b): b.z = 1`, which
    # has no field layout to write into.  Wave 6 (F1) found that store was
    # silent on BOTH architectures in opposite ways: x86-64's `AssignStmt` for a
    # MemberExpr target evaluated both sides and returned, DISCARDING it, and
    # arm64's `_store_var` had no slot and fell through to `mov x19, src`, so the
    # write landed in the register the NEXT function reads as its first
    # parameter.  Neither is a wrong value; one is a dropped store and one is a
    # wrong store, and a case that only checks a return value never notices.
    # `touchB` now builds its own B, so the write is a real write to a field
    # this compiler placed, and it still says what it was here to say.
    ("byref_one_name_two_widths_agree",
     "struct A:\n"
     "    var v: Int\n"
     "    var w: Int\n\n"
     "struct B:\n"
     "    var v: Int\n"
     "    var w: Int\n"
     "    var z: Int\n\n"
     "def touchB() -> Int:\n"
     "    var q = B()\n"
     "    q.z = 1\n"
     "    return q.z\n\n"
     "def pick(c: Int) -> Int:\n"
     "    var x = A()\n"
     "    x.v = 5\n"
     "    x.w = 2\n"
     "    if c > 0:\n"
     "        x = B()\n"
     "    return x.v * 100 + x.w\n\n"
     "def main(n: Int) -> Int:\n"
     "    var a: Int = pick(0)\n"
     "    var b: Int = pick(1)\n"
     "    if a != 502:\n"
     "        return 1000 + a\n"
     "    if b != 0:\n"
     "        return 2000 + b\n"
     "    return 0\n", 0, None),
    # The frame contract's SLIDE, and the reason it is a case here rather than
    # only in the proof generator: the proof generator READS the field's slot
    # off the emitted `STR`'s offset (`formal/arm64_proof_gen.py`'s
    # `_frame_slot_accesses`, which also constant-propagates the receiver
    # through the method's own `ADD`s so an access through some other base is
    # refused rather than guessed).  So a program that writes `self.y` must
    # produce a contract about slot 1, and a program whose method reads a field
    # the emitter places elsewhere must not be given one at all.  The two cases
    # below differ from `byref_two_fields_roundtrip` in exactly one character
    # of the method body, and the answers are 41 and 40 -- a generator that
    # hardcoded slot 0 would return the same number for both.
    ("byref_slot_follows_the_field_written",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "    fn set_x(self, v: Int):\n"
     "        self.x = v\n\n"
     "    fn set_y(self, v: Int):\n"
     "        self.y = v\n\n"
     "    fn get_x(self) -> Int:\n"
     "        return self.x\n\n"
     "    fn get_y(self) -> Int:\n"
     "        return self.y\n\n"
     "def main(n) -> Int:\n"
     "    var p = Point()\n"
     "    p.set_x(40)\n"
     "    p.set_y(1)\n"
     "    return p.get_x() + p.get_y()\n", 41, None),
    # A method that WRITES the SECOND field and reads the first back: the
    # other direction of the same slide, and 1 rather than 41, so a generator
    # that wrote slot 0 for both would get this one wrong.
    ("byref_second_field_write_leaves_first",
     "struct Point:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "    fn set_y(self, v: Int):\n"
     "        self.y = v\n\n"
     "    fn get_x(self) -> Int:\n"
     "        return self.x\n\n"
     "    fn get_y(self) -> Int:\n"
     "        return self.y\n\n"
     "def main(n) -> Int:\n"
     "    var p = Point()\n"
     "    p.set_y(1)\n"
     "    return p.get_x() + p.get_y()\n", 1, None),
]

# Constructs a frame ADDRESS may not take part in. Each is a `refuse:` case
# because the alternative is a program that builds, runs, and reads a frame
# after the function that created it has returned — the one outcome this
# backend may not produce. They are here so that a future change which
# "helpfully" lowers them is caught.
BYREF_REFUSALS = [
    # Returned: the frame dies with the function that made it.
    ("byref_refuse_returned",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def mk():\n"
     "    var p = P()\n"
     "    return p\n\n"
     "def main(n) -> Int:\n"
     "    var q = mk()\n"
     "    return 0\n",
     "refuse:is returned from the function that created it", None),
    # Into a container: a list blob has no layout for a frame address.
    ("byref_refuse_stored_in_a_list",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n) -> Int:\n"
     "    var p = P()\n"
     "    var xs = [p]\n"
     "    return 0\n",
     "refuse:is stored in a container", None),
    # A field OF a field: a slot holds one 64-bit word, and that word is a
    # value, not a struct.
    ("byref_refuse_field_of_field",
     "struct Q:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "struct P:\n"
     "    var q: Int\n"
     "    var r: Int\n\n"
     "    fn get(self) -> Int:\n"
     "        return self.q.a\n\n"
     "def main(n) -> Int:\n"
     "    var p = P()\n"
     "    return 0\n",
     "refuse:reads a field of a field", None),
    # A callee this module does not compile cannot know the frame's layout.
    ("byref_refuse_invisible_callee",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n) -> Int:\n"
     "    var p = P()\n"
     "    return mojo_print(p)\n",
     "refuse:no definition in hand", None),
    # ── wave 3 (C5) ──
    #
    # A frame address PARKED IN A FIELD. `o.inner = i` looks like an ordinary
    # assignment and is the one channel out of a function that was not checked:
    # the slot belongs to the frame of whatever function built `o`, while the
    # value written into it names a frame belonging to whatever function built
    # `i`, and the two lifetimes are independent. Return and container were
    # already refused; this is the same hole one level down, which is the
    # direction this whole design leaks in.
    #
    # It BUILT before this case existed, and read the reclaimed bytes.
    ("byref_refuse_frame_address_in_a_field",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "struct Outer:\n"
     "    var inner: Int\n"
     "    var tag: Int\n\n"
     "def stash(o) -> Int:\n"
     "    var i = Inner()\n"
     "    o.inner = i\n"
     "    return o.tag\n\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    o.tag = 4\n"
     "    return stash(o)\n",
     "refuse:outlives the frame it names", None),
    # TWO LAYOUTS THAT DISAGREE. `x = A()` on one path and `x = B()` on another
    # is one name and two frame layouts, and `A` puts `v` in slot 0 where `B`
    # puts it in slot 1. An analysis that settles on one of them reads the
    # other's storage: this exact program built, ran, and printed `61 99` where
    # the source says `50 99`, which is the outcome this backend exists to make
    # impossible. The needle is the sentence that says which candidate wanted
    # which slot, because a regression that re-introduces the miscompile would
    # otherwise pass a vaguer assertion.
    ("byref_two_layouts_disagree",
     "struct A:\n"
     "    var v: Int = 11\n"
     "    var pad: Int = 0\n\n"
     "struct B:\n"
     "    var pad: Int = 99\n"
     "    var v: Int = 0\n\n"
     "def touchA(a) -> Int:\n"
     "    a.pad = 7\n"
     "    return 0\n\n"
     "def pick(c: Int) -> Int:\n"
     "    var x = A()\n"
     "    x.v = 5\n"
     "    if c > 0:\n"
     "        x = B()\n"
     "    return x.v * 10 + x.pad\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r0: Int = pick(0)\n"
     "    var r1: Int = pick(1)\n"
     "    print(r0, r1)\n"
     "    return 0\n",
     "refuse:the shapes do not agree on where 'v' lives", None),
    # A METHOD DISPATCHED BY NAME ONTO THE WRONG RECEIVER. `_rewrite_method_calls`
    # turns `self.go(5)` into `Helper_go(self, 5)` from the method name alone,
    # because `recv.m(x)` carries no type — which is fine until the receiver is a
    # frame, at which point `Helper_go`'s `self.a = v` writes slot 0 of an
    # `Owner`'s frame, i.e. its `h`. Measured: `o.run(); o.h` printed `5, 5`
    # where the source says `5, 0`, because both structs' first fields are
    # integers and the write lands somewhere perfectly legal.
    ("byref_refuse_method_on_another_struct",
     "struct Helper:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "    fn go(self, v: Int) -> Int:\n"
     "        self.a = v\n"
     "        return self.a\n\n"
     "struct Owner:\n"
     "    var h: Int\n"
     "    var t: Int\n\n"
     "    fn run(self) -> Int:\n"
     "        return self.go(5)\n\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Owner()\n"
     "    o.t = 3\n"
     "    var r: Int = o.run()\n"
     "    return r * 10 + o.h\n",
     "refuse:is dispatched to Helper.go() by method NAME", None),
    # A receiver handed to a BUILTIN, which is a different reason from the
    # invisible-callee case above and was being reported as the same one.
    # `len` is compiled; it is compiled as an operation on a VALUE, so what
    # arrives is a pointer where it wants the object. The old text said "the
    # callee cannot know the frame's layout", which is not what is wrong and
    # sends the reader to look at the wrong thing.
    #
    # RE-POINTED at the `__len__` wording, and the reason is a change in what
    # this backend can do rather than a rewording for its own sake: `len` on a
    # frame address is now `x.__len__()` — a method of the receiver's own
    # struct, the one hand-off a frame address makes — so `P` declaring no
    # `__len__` is the whole of what is wrong, and a message that only said
    # "wrong category of argument" would be telling a reader who is about to
    # add the `__len__` that they have to change the program instead.
    # `len_frame_address_calls_the_struct_dunder_len` is the case that now
    # BUILDS; this is the one that still refuses, and it refuses for the
    # opposite reason.
    ("byref_refuse_receiver_to_a_builtin",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "    fn n(self) -> Int:\n"
     "        return len(self)\n\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    return p.n()\n",
     "refuse:declares no `__len__`", None),
    # A field of a field that is NOT a call: the value-position shape, which is
    # the one that stays a layout refusal. The needle is the CHAIN, because the
    # old message printed `self.<last member>` and so described a field the
    # source never mentions — `h.sub.g` read as though it said `h.g`.
    ("byref_refuse_field_of_field_names_the_chain",
     "struct Q:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "struct P:\n"
     "    var q: Int\n"
     "    var r: Int\n\n"
     "    fn get(self) -> Int:\n"
     "        return self.q.a\n\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    return p.get()\n",
     "refuse:self.q.a reads a field of a field", None),
]

# ── wave 4 (D4): the CALL hand-off, split by what the callee actually is ─────
#
# `_check_frame_escapes` used to answer every one of these with one sentence per
# shape, and for two of the shapes the sentence named a cause that was not
# operating. The cases below are the split, one per answer, and each says what
# the reader would otherwise have to go and check.
#
# (a) an ADDRESS constructor is NOT a refusal. `Pointer` is an identity type
#     constructor on this path, so `Pointer(to=s)` yields the word it was
#     handed — and for a multi-field struct that word is the frame's base
#     address, which is what a pointer to the object means. It was in
#     FRAME_VALUE_ONLY_CALLS, whose text says the callee "wants the object
#     itself … so what would arrive is the address Pointer() would then
#     dereference as one", which for `Pointer` is the reasoning upside down.
#
# The positive case is written so a wrong answer cannot hide in it: the two
# addresses are printed AND subtracted, and the difference has to be the frame
# size. Two unrelated leftover registers 16 bytes apart is not what a no-op
# would produce by accident, and if `Pointer(to=s)` stopped being the identity
# the difference would be whatever the registers happened to hold.
BYREF_HANDOFF_CASES = [
    ("byref_pointer_to_a_frame_is_the_address",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var s1 = S()\n"
     "    s1.a = 11\n"
     "    s1.b = 22\n"
     "    var s2 = S()\n"
     "    s2.a = 33\n"
     "    s2.b = 44\n"
     "    var p1 = Pointer(to=s1)\n"
     "    var p2 = Pointer(to=s2)\n"
     "    print(p1)\n"
     "    print(p2)\n"
     "    return p2 - p1\n", 16, None),
    # The same hand-off on a plain VALUE, as a guard: `Pointer(to=l)` on a list
    # has always been the identity and must keep being it. This case passes
    # before and after and is here for the side where the rule has to hold, not
    # as a demonstration of anything.
    ("byref_pointer_to_a_list_is_still_the_identity",
     "def main(n: Int) -> Int:\n"
     "    var l = [7, 8, 9]\n"
     "    var p = Pointer(to=l)\n"
     "    return p - Pointer(to=l) + l[0]\n", 7, None),
    # (b) THE FRAME AND THE STRUCT'S C LAYOUT COINCIDE — measured, not argued,
    # and this case is the measurement. `memset` writes sixteen bytes through a
    # pointer taken from the frame, and both slots read back as the sixteen
    # bytes it wrote. That is only true if the frame block IS the struct's
    # storage: contiguous from `base`, field `k` at `base + 8k`, in declaration
    # order — which is exactly the C layout of a struct whose every field is 8
    # bytes wide and 8-aligned. So the old refusal's premise ("the frame holds
    # the fields at `base + 8k`, which is not the struct's own layout") is
    # false for that shape, and this is the program that says so.
    #
    # It is also the case that needed a one-line fix in the x86-64 emitter,
    # which is why it is here rather than only in the report: `Pointer(to=x)`
    # is spelled with a keyword, arm64's `_emit_type_constructor` has always
    # accepted a keyword-named operand and x86-64's read `e.args` alone, so the
    # two backends disagreed about this source file — a divergence that had
    # been masked because the frame analysis refused both before either
    # emitter was reached.
    ("byref_frame_bytes_are_the_structs_c_layout",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S()\n"
     "    s.a = 0\n"
     "    s.b = 0\n"
     "    memset(Pointer(to=s), 65, 16)\n"
     "    return (s.a == 4702111234474983745) * 100 \\\n"
     "        + (s.b == 4702111234474983745)\n", 101, None),
]

BYREF_HANDOFF_REFUSALS = [
    # (b) A struct CONSTRUCTOR called with a frame address. This case USED to
    # be here, expecting `refuse:is a COPY CONSTRUCTION`, and it is now a
    # positive case in CONSTRUCTION_CASES — the copy lowers. The old text was
    # false twice over: `R` is declared in this very file, which is the only
    # reason the argument is a frame address at all, and a struct has no body
    # to compile. Its real content was one level down, and the level down now
    # has a lowering.
    #
    # A NON-FIRST argument position. "A position whose meaning this path cannot
    # see" was a statement about the analysis in a message a reader takes to be a
    # statement about the program, and it was standing in for three different
    # things. Wave 5 split them, and this case is the one that MOVED: the
    # position is now followed (see `byref_nonfirst_holder_reads_correctly` in
    # the wave-5 block), so what is left to refuse in this program is the
    # RETURN — `take()` hands back a frame address it did not create, which is
    # the return family and says so.
    ("byref_refuse_nonfirst_position_names_it",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def take(x: Int, y: Int) -> Int:\n"
     "    return y\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return take(1, r).a",
     "refuse:returned from a function that did not create it", None),
    # …and the C half of it, which is a wrong CATEGORY of argument and not a
    # position question at all. `printf` was falling through to "no definition
    # in hand", which is false — it is libSystem's and it binds — and the
    # program it produced printed the frame's ADDRESS as the integer the format
    # asked for, and exited 0.
    #
    # The needle no longer mentions the position, and that is the point of the
    # split: the position is not what makes this wrong, so a message that
    # mentions it sends the reader looking for a position problem that is not
    # there. The variadic conversion is the reason and the reason is now what
    # the message says.
    ("byref_refuse_c_entry_point_in_a_position",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    printf(\"val=%d\\n\", r)\n"
     "    return 0",
     "refuse:the argument is VARIADIC, so whatever conversion the format "
     "string names", None),
    # A frame address RETURNED by a function that did not create it. The holder
    # fixpoint makes a callee's first parameter a holder, so this is the larger
    # half of the return family, and the old sentence named THIS function as the
    # creator — sending the reader to `fwd` for a construction that is in
    # `main`. The refusal is right; the creator is the caller and nothing here
    # establishes the caller is still on the stack.
    ("byref_refuse_returned_from_a_receiver",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def fwd(r: Int) -> Int:\n"
     "    return r\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return fwd(r).a\n",
     "refuse:returned from a function that did not create it", None),
    # …and the method half, where the sentence is the same lie with a struct's
    # name attached.
    ("byref_refuse_returned_from_a_method_receiver",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    fn give(self) -> Int:\n"
     "        return self\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    return r.give().a\n",
     "refuse:returned from a method of R", None),
    # A name the model KNOWS and cannot represent. `Error` is a real type, so
    # "which this module does not compile" was false a third time over: it is
    # neither a function this module compiles nor a function at all, and the
    # fact that stops the program is that one formal value is one 64-bit word.
    ("byref_refuse_unrepresentable_type_constructor",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    var e = Error(r)\n"
     "    return r.a\n",
     "refuse:is a real type this path has no representation", None),
]

# ── wave 4 (D4): a frame address handed to a method in an IMPORTED module ───
#
# The binding half of case (c), and it is the change with a program behind it.
#
# `_method_exports` filtered out every method whose struct was not one word,
# with the comment "refused at lift time, never compiled". That was true when a
# multi-field struct had no representation, and stopped being true the moment
# the by-reference receiver landed: a wide struct's method IS compiled and its
# receiver word IS the frame address. So the filter was dropping the export of
# code that was in the library, and the importer's call had no symbol to bind
# to — while the refusal said the callee "is not compiled", which is the
# opposite of what was happening.
#
# Two cases, and the second is a GUARD: a one-field struct's method has always
# crossed this boundary, so the one-field case passes before and after. It is
# here because the rule has to hold on the side where it already worked, and it
# is reported as passing pre-change rather than dressed up as a demonstration.
#
    # The mutating case is the one that would catch a wrong lowering. `S_set_a`
    # writes `self.a`, which on the caller's side is the caller's `s1.a`: if the
    # address handed over were anything other than the caller's frame base, the
    # write would land somewhere else and `s1.a` would still read 2. The answer
    # is `s1.a == 5`, `s1.b == 9` and `r == 9` read back on the CALLER's side,
    # so a wrong address gives 38 rather than 68. (68 rather than 959 because
    # the formal entry's return value becomes the process exit status, so a
    # three-digit answer is truncated to a byte and would stop distinguishing
    # anything.)
CROSS_MODULE_CASES = [
    ("byref_cross_module_wide_receiver_reads",
     {"mod": "struct S:\n"
             "    var a: Int\n"
             "    var b: Int\n"
             "\n"
             "    fn get(self) -> Int:\n"
             "        return self.a * 10 + self.b\n"
             "\n"
             "def bump(v: Int) -> Int:\n"
             "    return v + 1\n",
      "main": "from byref_xmod import S, bump\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var s = S()\n"
              "    s.a = 3\n"
              "    s.b = 4\n"
              "    return s.get() + bump(1)\n"}, 36, None),
    ("byref_cross_module_wide_receiver_writes",
     {"mod": "struct S:\n"
             "    var a: Int\n"
             "    var b: Int\n"
             "\n"
             "    fn set_a(self, v: Int) -> Int:\n"
             "        self.a = v\n"
             "        return self.b\n",
      "main": "from byref_xmod import S\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var s1 = S()\n"
              "    s1.a = 2\n"
              "    s1.b = 9\n"
              "    var r = s1.set_a(5)\n"
              "    return s1.a * 10 + s1.b + r\n"}, 68, None),
    # The GUARD: the same two files with a ONE-field struct, which has always
    # bound across the module boundary. Before this change: passes. After:
    # passes. It is here so that a change which "fixed" the wide case by
    # breaking the export table for both would fail here.
    ("byref_cross_module_one_field_receiver",
     {"mod": "struct T:\n"
             "    var a: Int\n"
             "\n"
             "    fn get(self) -> Int:\n"
             "        return self.a * 10\n",
      "main": "from byref_xmod import T\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var t = T()\n"
              "    t.a = 7\n"
              "    return t.get()\n"}, 70, None),
]

# ── wave 5 (E3): a frame address in a NON-FIRST parameter position ──────────
#
# Three things wore one sentence, and this is the split. The headline is the
# first two POSITIVE cases: a frame address in a parameter that is not the
# first one now computes the right answer, on both machines, including with the
# creator one frame deeper — which is the case that would catch a lifetime
# error in the fixpoint rather than a missing slot table.
#
# Refusals here are the other two cases and they are refused with the reason
# that is actually operating: a VARIADIC position for being variadic, and an
# OPAQUE one for having no declaration in hand.
WAVE5_POSITION_CASES = [
    #
    # "A position whose meaning this path cannot see" was one sentence standing
    # in for three different things, and all three were wrong answers without
    # the check. This block is the split: the position is now FOLLOWED (case 1),
    # a variadic position is refused for being variadic (case 2), and only the
    # genuinely unreadable position is refused as unreadable (case 3).
    #
    # The lifetime argument the first two rest on, in one sentence, because it
    # is the thing that makes the extension safe rather than hopeful: a frame
    # belongs to the function that created it, an address only ever travels DOWN
    # an active call chain, so the creator of a holder that arrived as an
    # argument is an ANCESTOR of the callee and its bytes are live for every
    # instant of the callee's activation. The callee may read and write through
    # it. What it may not do is let the word leave — and `return`, a container,
    # a field, a subscript are each refused by name, which is what the
    # use-after-free guard below is measuring.
    ("byref_nonfirst_holder_reads_correctly",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def take(x: Int, y: Int) -> Int:\n"
     "    return y.a * 10 + y.b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return take(1, r)\n", 78, None),
    # THE SAME SHAPE WITH THE CREATOR ONE FRAME DEEPER, and this is the case
    # that matters: it is the one that would catch a lifetime error in the
    # fixpoint. `main` holds no frame at all here — `mid` builds the object and
    # `main` only calls `mid` — so if the fixpoint reasoned "the frame belongs
    # to the function that made it and this one did not, so it must be gone",
    # the read through `y` would be a read of reclaimed stack and the answer
    # would be whatever those bytes hold now.
    #
    # Before this change the program was refused with "a position whose meaning
    # this path cannot see"; with only that check lifted it returned 10 on
    # arm64 and 0 on x86-64, where the source says 7. A two-backend
    # disagreement about what the reused bytes held is the signature of exactly
    # this mistake, which is why the case is here and not folded into the one
    # above.
    ("byref_nonfirst_holder_reads_with_creator_one_frame_deeper",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def take(x: Int, y: Int) -> Int:\n"
     "    return y.a * 10 + y.b\n"
     "\n"
     "def mid(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return take(1, r)\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return mid(1)\n", 78, None),
    # A WRITE through the non-first parameter, which is the other half of the
    # licence and the stronger half: a read would still come out right if the
    # address were a COPY of the frame rather than the frame itself, but a
    # write through a copy lands in the copy and `r.a` would still read 1.
    # 5*10 + 2 = 52, and 12 is what a copied address gives.
    ("byref_nonfirst_holder_writes_through_to_the_caller",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def put(x: Int, y: Int, v: Int) -> Int:\n"
     "    y.a = v\n"
     "    return y.a\n"
     "\n"
     "def mid(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 1\n"
     "    r.b = 2\n"
     "    put(0, r, 5)\n"
     "    return r.a * 10 + r.b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return mid(1)\n", 52, None),
    # THE USE-AFTER-FREE GUARD, and the one the brief asks not to be dropped
    # because it is awkward. Same fixpoint, same non-first position, but the
    # callee RETURNS the word: `stash` did not create the frame, so handing the
    # address back means the caller dereferences a pointer whose creator may be
    # gone. With the creator one frame deeper that is not a maybe.
    #
    # Before this change: with the position check lifted, this built and
    # returned 10 on arm64 and 0 on x86-64 where the source says 7 — a
    # use-after-free, and the two architectures disagreeing about the reused
    # bytes. Now it is refused, and the refusal names the RETURN rather than
    # the position, which is the whole of the split.
    ("byref_refuse_a_received_frame_address_returned",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def stash(x: Int, y: Int) -> Int:\n"
     "    return y\n"
     "\n"
     "def outer(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return stash(1, r)\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = outer(1)\n"
     "    return p.a\n",
     "refuse:returned from a function that did not create it", None),
    # The same word parked in a CONTAINER by the callee that received it. The
    # fixpoint is what makes this visible at all: before it, `y` was not a
    # holder in `stash`, so the container check had nothing to fire on and the
    # address went into a list and was read back after its frame was gone.
    ("byref_refuse_a_received_frame_address_stored",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def stash(x: Int, y: Int) -> Int:\n"
     "    var box = [y]\n"
     "    return 1\n"
     "\n"
     "def outer(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    stash(1, r)\n"
     "    return 0\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return outer(1)\n",
     "refuse:is stored in a container", None),
    # CASE 2: a VARIADIC position, refused for being variadic. The needle
    # deliberately does NOT mention the position, because the position is not
    # what is wrong: `printf` reads the word by the format's conversion, in
    # every position, and a message that names a position sends the reader
    # looking for a position problem that is not there.
    #
    # Before this change this program was refused as "a position whose meaning
    # this path cannot see"; with only that check lifted it built, printed the
    # frame's ADDRESS as the decimal the format asked for, and exited 0.
    ("byref_refuse_a_variadic_position_as_variadic",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def show(fmt: Int, v: Int) -> Int:\n"
     "    return 0\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    printf(\"val=%d\\n\", r)\n"
     "    return 0\n",
     "refuse:the argument is VARIADIC, so whatever conversion the format "
     "string names", None),
    # CASE 3: a genuinely OPAQUE position — a method call on a value receiver,
    # which is dispatched by NAME and so carries no type and no parameter list
    # for this walk to read. Marked as a limit of the analysis rather than
    # asserted as a fact about the program, which is the sentence the whole
    # family was written to stop saying.
    #
    # GUARD in one direction: this program was refused before the change too,
    # with the same words. It is here because the split has to keep the narrow
    # case narrow, and a case that only ever fired on new shapes would not show
    # that.
    ("byref_refuse_an_opaque_position_as_opaque",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "class Box:\n"
     "    var v: Int\n"
     "\n"
     "    fn take(self, o: Int) -> Int:\n"
     "        return 0\n"
     "\n"
     "def mk() -> Box:\n"
     "    var bx = Box()\n"
     "    bx.v = 1\n"
     "    return bx\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    return mk().take(r)\n",
     "refuse:a METHOD call on a value receiver", None),
    # ONE PARAMETER, TWO KINDS OF VALUE — the wrong answer that was in the
    # shipped tree at the FIRST position, before any of this, and the reason
    # the agreement rule exists. `f` is compiled with `x` a frame holder, so
    # `x.a` is a load at `base + 0`, and `f(2, 3)` arrives with `x = 2`.
    #
    # Before this change: built, ran, and died with SIGSEGV (exit 139) on BOTH
    # architectures. The `refuse:` convention cannot express "must not build"
    # for a program that used to build, so this is a `refuse:` case and the
    # measurement is in the comment above and in
    # `model.frame_holder_disagreement_refusal`.
    ("byref_refuse_two_call_sites_that_disagree",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def f(x: Int, y: Int) -> Int:\n"
     "    return x.a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return f(r, 1) + f(2, 3)\n",
     "refuse:One parameter, two kinds of value", None),
    # …and the same disagreement where the DISAGREEING call site is in a
    # function that holds no frame of its own, which is the shape that made the
    # check a whole-image pass rather than another branch: `main` never mentions
    # `r`, so every per-function channel in `_check_frame_escapes` skips it.
    # Built and died with SIGSEGV (139) on both architectures before.
    ("byref_refuse_a_disagreement_in_a_frame_free_caller",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def take(x: Int, y: Int) -> Int:\n"
     "    return y.a\n"
     "\n"
     "def mid(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    return take(1, r)\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return take(2, mid(1))\n",
     "refuse:One parameter, two kinds of value", None),
    # A GUARD, and it is a guard against a message that was entirely false.
    # `Pointer` is an ADDRESS constructor — handing one a frame address is the
    # answer, not the mistake — and it is also an `identity` type constructor,
    # so a predicate that asks "does this callee want a value?" from
    # `type_constructor_kind` alone says YES about it.  With the exclusion
    # missing, `Pointer(0, r)` was refused with
    #
    #   a R receiver is passed to Pointer(), a C library entry point, in
    #   argument position 1 of 2. This is not a question about the position:
    #   Pointer() is variadic and takes its arguments as values …
    #
    # and every clause of that is false: `Pointer` is not a C entry point, it
    # is not variadic, and the thing that actually refuses it is an arity
    # check.  A sentence whose whole mechanism is not operating is worse than
    # the vague one it replaced, so this case pins the arity refusal.
    #
    # GUARD in the second direction as well, and the reason it is here rather
    # than in the positive list: `Pointer(to=s)` in a non-first position of an
    # ordinary function has to keep being the identity.  That is
    # `byref_pointer_to_a_list_is_still_the_identity` one level up; this one is
    # the same rule reached through the new position path, and it passed before
    # the change only because the position rule refused the file first.
    ("byref_address_ctor_is_not_called_variadic",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    var p = Pointer(0, r)\n"
     "    return r.a * 10 + r.b\n",
     "refuse:takes exactly one value to convert", None),
    ("byref_address_ctor_stays_the_identity_in_a_nonfirst_position",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def keep(x: Int, p: Int) -> Int:\n"
     "    return 1\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    var s = R()\n"
     "    s.a = 1\n"
     "    s.b = 2\n"
     "    return r.a * 10 + r.b + keep(0, Pointer(to=s))\n", 79, None),
    # A SUBSCRIPT store, which was a hole rather than a refusal: `q[0] = r`
    # reads as an ordinary assignment and the list's element is a heap cell, so
    # the frame address outlives the frame. Measured before the branch existed,
    # on both architectures: it built, ran, and returned 0 where the source
    # says 7 — silently, with the program exiting 0.
    ("byref_refuse_a_frame_address_stored_through_a_subscript",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    var q = [1, 2, 3]\n"
     "    q[0] = r\n"
     "    return q[0].a\n",
     "refuse:is stored through 'q[0]'", None),]



def run_module_case(name, files, want_exit, want_stdout, tmpdir, verbose):
    """A case that needs TWO files: a module and a program that imports it.

    The cross-module hand-off is the only shape in this suite that a single
    source file cannot express, and it is the shape this change is about: a
    frame address handed to a method that is compiled into another image. The
    module is written next to the program in the same temporary directory, which
    is what `resolve_module_path` looks in for a sibling, so the import resolves
    the way it does in the repository.

    The `refuse:` and `refuse_either:` conventions are the same as
    `run_case`'s and mean the same thing: both architectures must refuse, with
    the same words. A divergence here would be the worst kind, because the two
    sides of the boundary are separate compilations and a disagreement about
    what a frame address means is exactly what would not show up in a
    single-file case.
    """
    mod = os.path.join(tmpdir, "byref_xmod.mojo")
    with open(mod, "w") as f:
        f.write(files["mod"])
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(files["main"])

    if isinstance(want_exit, str) and (
            want_exit.startswith("refuse:")
            or want_exit.startswith("refuse_either:")):
        either = want_exit.startswith("refuse_either:")
        needles = (want_exit[len("refuse_either:"):].split("|") if either
                   else [want_exit[len("refuse:"):]])
        for backend in ("arm64", "x86_64"):
            rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.{backend}"),
                                    backend=backend)
            if rc == 0:
                return False, (f"--backend={backend} BUILT a cross-module "
                               f"hand-off that has no representation (expected "
                               f"a refusal naming one of {needles!r})")
            if not any(n in text for n in needles):
                return False, (f"--backend={backend} refused, but not with any "
                               f"of {needles!r}: {text.strip()[-200:]}")
        if verbose:
            print(f"      refused identically on both architectures: {needles!r}")
        return True, ""

    out = os.path.join(tmpdir, name)
    rc, text = build_formal(src, out)
    if rc != 0:
        return False, text.strip()[-300:]
    if not os.path.isfile(out):
        return False, "build reported success but wrote no binary"
    run = subprocess.run([out], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    if run.returncode != want_exit:
        return False, (f"exit status {run.returncode}, expected {want_exit}"
                       + (f"; stderr: {run.stderr.strip()[:120]}"
                          if run.stderr.strip() else ""))
    if want_stdout is not None and want_stdout not in run.stdout:
        return False, f"stdout {run.stdout[:120]!r} does not contain {want_stdout!r}"
    if verbose:
        print(f"      stdout={run.stdout[:60]!r} exit={run.returncode}")
    return True, ""

# ── wave 4 (D2): a field's DECLARED type, used only when every binding agrees ──
#
# C5's named next step. The rule is the one C5 handed over verbatim — a declared
# type is used only when EVERY binding of the name agrees with it, the same
# agree-or-refuse discipline as `model.struct_frame_slot_candidates` — and the
# two ways it can end are both here, because the interesting one is the way it
# ends BADLY:
#
#   * agreed, and the type names a framed struct of this module → the slot holds
#     a NESTED FRAME, which the constructor PLACES in the outer object's own
#     block (`model.struct_nested_frame_fields` / `struct_constructor_sites`).
#     The lifetime is then the outer object's, which is strictly more than the
#     refusal it replaces could offer: that refusal's whole complaint was that
#     the frame belongs to whichever function built the object.
#   * agreed, and it does NOT → the word in the slot is provably a plain value,
#     and the frame layout is not what is in question, so the frame diagnostic
#     must NOT fire and the value-method one must.
#   * NOT agreed — no annotation, two candidates naming different types, one
#     candidate not declaring the field → untyped, and the case stays refused
#     with the disagreement spelled out.
#
# `byref_declared_type_contradicted_by_a_rebinding` is the one that makes the
# approach sound and the one most likely to be quietly dropped: it is the case
# where a single counter-example has to take the whole capability back out.
DECLARED_TYPE_CASES = [
    # The positive case: `inner: Inner` names a struct of this module whose
    # receiver is a frame, every binding agrees (there is one), and so the
    # nested frame is placed and `self.in1.total()` is a call on a placed
    # address. The method writes nothing and reads two fields, so 123 is the
    # source's answer and a build that computed 0 or 5 would be the silently-
    # wrong outcome this whole shape is arranged to avoid.
    ("byref_nested_frame_method_call",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "    fn total(self) -> Int:\n"
     "        return self.a * 100 + self.b * 10 + self.c\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    var in1: Inner\n"
     "\n"
     "    fn go(self) -> Int:\n"
     "        return self.in1.total() + self.tag\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    o.tag = 5\n"
     "    o.in1.a = 1\n"
     "    o.in1.b = 2\n"
     "    o.in1.c = 3\n"
     "    return o.go()\n", 128, None),
    # TWO OBJECTS, EACH HOLDING ITS OWN NESTED FRAME. `Frame.nested_frames_no_
    # alias` written as a program, and written the way C5 wrote its two-instance
    # cases: each read is guarded by a DIFFERENT return code, so a regression
    # says WHICH frame moved rather than only that a number is wrong.
    #
    # `o1` and `o2` are two constructor SITES, so two blocks, so two nested
    # Inner frames at different addresses. Writing `o2.in1.a = 4` must not be
    # visible in `o1`, and the 3000/5000 guards are the reads that would catch
    # it. This is the case a "the code is the same for every width" argument
    # cannot establish on its own.
    ("byref_nested_frame_two_objects_no_alias",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "    fn total(self) -> Int:\n"
     "        return self.a * 100 + self.b * 10 + self.c\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    var in1: Inner\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o1 = Outer()\n"
     "    var o2 = Outer()\n"
     "    o1.in1.a = 1\n"
     "    o1.in1.b = 2\n"
     "    o1.in1.c = 3\n"
     "    o2.in1.a = 7\n"
     "    o2.in1.b = 8\n"
     "    o2.in1.c = 9\n"
     "    if o1.in1.total() != 123:\n"
     "        return 1000 + o1.in1.total()\n"
     "    if o2.in1.total() != 789:\n"
     "        return 2000 + o2.in1.total()\n"
     "    o2.in1.a = 4\n"
     "    if o1.in1.total() != 123:\n"
     "        return 3000 + o1.in1.total()\n"
     "    if o2.in1.total() != 489:\n"
     "        return 4000 + o2.in1.total()\n"
     "    o1.in1.c = 5\n"
     "    if o2.in1.total() != 489:\n"
     "        return 5000 + o2.in1.total()\n"
     "    return 0\n", 0, None),
    # A nested frame the nested struct's OWN method writes to. The slot belongs
    # to the nested frame, so this is the ordinary frame store and not the
    # write-once rule — which is exactly the distinction `_check_nested_frame_
    # writes` draws by refusing writes to the field from the OWNER's methods and
    # not from the nested struct's. 4 + 5 is the nested method's own answer.
    ("byref_nested_frame_is_mutable_by_its_own_method",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "    fn bump(self) -> Int:\n"
     "        self.c = self.c + 1\n"
     "        return self.a + self.b + self.c\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    var in1: Inner\n"
     "\n"
     "    fn go(self) -> Int:\n"
     "        return self.in1.bump()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    o.in1.a = 2\n"
     "    o.in1.b = 3\n"
     "    o.in1.c = 4\n"
     "    return o.go()\n", 10, None),
]

DECLARED_TYPE_REFUSALS = [
    # ── THE CASE THAT MAKES THE APPROACH SOUND ──
    #
    # One local rebound to two structs, and the two DISAGREE about the field's
    # declared type: `A.in1` is an `Inner` (a frame) and `B.in1` is an `Int` (a
    # word). One counter-example, and the name is not typed, so no nested frame
    # is placed and the case is refused — with BOTH candidates spelled, because
    # a refusal that does not say which candidate wanted what is a refusal the
    # reader has to re-derive, and this is the refusal where being vague would
    # be most tempting.
    #
    # The direction that matters: reading the `A` candidate's type on the `B`
    # path would place a frame where a word lives and hand the method a frame
    # address read out of an integer. That program builds, runs, and returns a
    # number nobody wrote.
    ("byref_declared_type_contradicted_by_a_rebinding",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "    fn total(self) -> Int:\n"
     "        return self.a * 100 + self.b * 10 + self.c\n"
     "\n"
     "struct A:\n"
     "    var in1: Inner\n"
     "    var w: Int\n"
     "\n"
     "struct B:\n"
     "    var in1: Int\n"
     "    var w: Int\n"
     "\n"
     "def pick(c: Int) -> Int:\n"
     "    var x = A()\n"
     "    x.in1.a = 1\n"
     "    if c > 0:\n"
     "        x = B()\n"
     "    return x.in1.total()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return pick(0)\n",
     "refuse:A declares 'in1' as 'Inner'", None),
    # No annotation at all: `in1 = 0` is a class-level ASSIGNMENT, so nothing
    # here says what the slot holds, and the untyped case must stay refused
    # rather than being treated as a value on the strength of `= 0`. The
    # message has to say WHICH shape of untyped it is, because a class that
    # assigns its fields in `__init__` and one that assigns a literal are both
    # "no declared type" and only one of them is `= 0`.
    ("byref_declared_type_absent_stays_refused",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "    fn total(self) -> Int:\n"
     "        return self.a * 100 + self.b * 10 + self.c\n"
     "\n"
     "struct P:\n"
     "    var in1 = 0\n"
     "    var z: Int\n"
     "\n"
     "    fn go(self) -> Int:\n"
     "        return self.in1.total()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    return p.go()\n",
     "refuse:does not declare 'in1'", None),
    # A field that IS written. `in1: Inner` agrees on a framed struct, so the
    # slot does hold a frame address — but `P.go` ASSIGNS the field, so what is
    # in the slot is a frame belonging to whichever function ran the assignment,
    # not the frame the constructor placed. Those two lifetimes are independent,
    # which is the whole reason the placed frame is preferred, so the case is
    # refused with that said rather than silently treated as the placed one.
    #
    # This is the fourth answer of the declared-type rule and the one an early
    # version got wrong: it placed the frame anyway and then refused every
    # write to it, which is sound about the frame and useless about the program
    # — it moved 164 stdlib files' verdicts to refuse ordinary code like
    # `self._bytes = remaining`. The needle is the REASSIGNMENT, because that is
    # the fact a reader needs and the one a regression would drop.
    ("byref_refuse_write_over_a_nested_frame",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "    fn total(self) -> Int:\n"
     "        return self.a * 100 + self.b * 10 + self.c\n"
     "\n"
     "struct P:\n"
     "    var in1: Inner\n"
     "    var z: Int\n"
     "\n"
     "    fn go(self) -> Int:\n"
     "        var t = Inner()\n"
     "        self.in1 = t\n"
     "        return self.in1.total()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    return p.go()\n",
     "refuse:ASSIGNS that field, so what is in the slot is a frame belonging to", None),
    # The BLOB-IN-A-FIELD PREMISE, as a refusal. C5 recorded that a slot can
    # never hold a list today only because no field can take a non-literal
    # default AND `S()` does not run `__init__` — neither of which is a property
    # of the frame layout. This is the check that stops that being an accident
    # of two other decisions: a `reset()` that builds a list into a field is a
    # blob with the ASSIGNING function's lifetime sitting in a slot whose
    # lifetime is the object's, and `self.items.append(x)` afterwards appends
    # into reclaimed stack.
    #
    # It is the case the value-method work depends on, so it is a test and not
    # a comment: the day (B1) is lifted for any reason, this goes red.
    ("byref_refuse_container_written_into_a_field",
     "struct Bag:\n"
     "    var items: Int\n"
     "    var n: Int\n"
     "\n"
     "    fn reset(self) -> Int:\n"
     "        self.items = [1, 2, 3]\n"
     "        return self.n\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Bag()\n"
     "    return b.reset()\n",
     "refuse:breaks the premise that makes a frame field safe", None),
    # The NEGATIVE use of the declared type, and the reason this is not only a
    # nesting feature. `n: Int` says the slot is NOT a frame address of this
    # unit, so the word handed to `bump` is a plain value — which is the value-
    # method question, not the frame's. The needle is the VALUE-METHOD refusal
    # and it is the assertion: the frame refusal must be GONE for this source,
    # because a diagnostic about the frame layout is a diagnostic about the
    # wrong thing. (`bump` is deliberately not in any lowered table, so the
    # value path refuses it loudly instead of computing something.)
    ("byref_declared_scalar_receiver_is_not_a_frame_question",
     "struct Helper:\n"
     "    var q: Int\n"
     "    var r: Int\n"
     "\n"
     "    fn bump(self) -> Int:\n"
     "        return self.q + 1\n"
     "\n"
     "struct P:\n"
     "    var n: Int\n"
     "    var m: Int\n"
     "\n"
     "    fn go(self) -> Int:\n"
     "        return self.n.bump()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    return p.go()\n",
     "refuse:is a method call on a value", None),
]

# ── wave 5 (E2): the three CONSTRUCTION shapes ─────────────────────────────
#
# `S()`, `S(a, b, …)` and `S(x)` are three lowerings, and until now only the
# first existed. The two others are here, and what makes them representable is
# not a new instruction and not a new addressing mode — it is that a block
# built at a construction SITE belongs to the function the site is in, and
# `_check_frame_escapes` refuses every channel by which it could leave that
# activation. So the object is read only while its creator is on the stack, and
# a word parked in one of its slots came from a live local of that function or
# of an ancestor of it.
#
# That last sentence is also what makes a construction DIFFERENT from the
# assignment `o.inner = i`, which is refused: there `o` may be an object an
# ANCESTOR built, so the slot outlives `i`'s creator and the next use of `o`
# reads reclaimed stack. The two look identical in the source and the
# difference is entirely "is the object new here".
#
# The four things these cases have to establish, in the order they matter:
#
#   1. `S()` still works and still refuses a non-literal default by name — the
#      GUARD. It passed before this change and must pass after; it is here so
#      that a regression in the shape the other two were built next to is
#      caught here rather than in the sweep.
#   2. `S(a, b)` fills fields in DECLARATION ORDER and the values read back.
#   3. `S(x)` is a SHALLOW COPY and NOT A SHARED FRAME. This is the one that
#      matters: a copy implemented as "hand back the same address" builds, runs,
#      and returns numbers, and the only way to see it is to MUTATE THE COPY
#      AND READ THE ORIGINAL. `constr_copy_does_not_alias` is written to detect
#      exactly that, with a different return code per field so a regression
#      says which slot moved.
#   4. A copy of a struct with a PLACED NESTED FRAME shares the nested frame,
#      which is the language's semantics and not a bug — so this case asserts
#      the sharing, because the failure mode is a copy that "helpfully" deep
#      copied it.
CONSTRUCTION_CASES = [
    # (1) THE GUARD. `S()` on a multi-field struct, with a class-level literal
    # default on one field so the case also pins that the default is
    # MATERIALIZED and not zeroed. 3 + 40 + 0 = 43.
    ("constr_default_still_works",
     "struct Cfg:\n"
     "    var a: Int\n"
     "    var b: Int = 40\n"
     "    var c: Int\n"
     "\n"
     "    fn get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.a\n"
     "        if i == 1:\n"
     "            return self.b\n"
     "        return self.c\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var s = Cfg()\n"
     "    s.a = 3\n"
     "    if s.get(0) != 3:\n"
     "        return 90 + s.get(0)\n"
     "    if s.get(1) != 40:\n"
     "        return 80 + s.get(1)\n"
     "    if s.get(2) != 0:\n"
     "        return 70 + s.get(2)\n"
     "    return 43\n", 43, None),
    # (2) POSITIONAL, declaration order, read back through METHODS rather than
    # through `s.x` so the answer goes through the slot table and not through
    # whatever a field read happens to do. 314 == 15 * 100 + 7 * 10 + 4 is
    # written as `1500 + 70 + 4` to stay inside a byte.
    ("constr_positional_fills_in_order",
     "struct Triple:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "    fn get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.a\n"
     "        if i == 1:\n"
     "            return self.b\n"
     "        return self.c\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var t = Triple(15, 7, 4)\n"
     "    if t.get(0) != 15:\n"
     "        return 10 + t.get(0)\n"
     "    if t.get(1) != 7:\n"
     "        return 20 + t.get(1)\n"
     "    if t.get(2) != 4:\n"
     "        return 30 + t.get(2)\n"
     "    return 41\n", 41, None),
    # (2b) Positional arguments that are EXPRESSIONS, and a mixture of literals,
    # locals and a call result. The store is one per argument at `base + 8k` in
    # order, so an argument that is a call is the case where recomputing the
    # base matters: a call clobbers the scratch register the base lives in on
    # this path, and hoisting the base would store every argument into slot 0.
    # `2 + 3` and `scale(4)` are the two shapes, and the expected value 5, 10,
    # 12 names which slot moved if one of them did.
    ("constr_positional_expression_arguments",
     "struct Triple2:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "    fn get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.a\n"
     "        if i == 1:\n"
     "            return self.b\n"
     "        return self.c\n"
     "\n"
     "def scale(v: Int) -> Int:\n"
     "    return v * 3\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var t = Triple2(2 + 3, scale(2) + 4, scale(4))\n"
     "    if t.get(0) != 5:\n"
     "        return 10 + t.get(0)\n"
     "    if t.get(1) != 10:\n"
     "        return 20 + t.get(1)\n"
     "    if t.get(2) != 12:\n"
     "        return 30 + t.get(2)\n"
     "    return 7\n", 7, None),
    # (3) THE COPY THAT MUST NOT ALIAS. This is the most important case in the
    # group and the only one that detects the failure it is about.
    #
    # A copy implemented as "return the source's address" — which is the reading
    # a frame design invites, since `c = a` on a frame IS exactly that — makes
    # every write to the copy a write to the original. The program would build,
    # would run, and would return a number; the only symptom would be that the
    # ORIGINAL's fields moved. So each field is checked through the ORIGINAL
    # after the copy was mutated, with a distinct return code per field, and
    # then the copy is checked too, so a copy that shares nothing (a fresh zero
    # block) is caught as loudly as one that shares everything.
    ("constr_copy_does_not_alias",
     "struct Cell:\n"
     "    var n: Int\n"
     "    var m: Int\n"
     "    var p: Int\n"
     "\n"
     "    fn set(self, i: Int, v: Int) -> Int:\n"
     "        if i == 0:\n"
     "            self.n = v\n"
     "        elif i == 1:\n"
     "            self.m = v\n"
     "        else:\n"
     "            self.p = v\n"
     "        return v\n"
     "\n"
     "    fn get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.n\n"
     "        if i == 1:\n"
     "            return self.m\n"
     "        return self.p\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Cell()\n"
     "    a.set(0, 3)\n"
     "    a.set(1, 4)\n"
     "    a.set(2, 5)\n"
     "    var b = Cell(a)\n"
     "    b.set(0, 90)\n"
     "    b.set(1, 91)\n"
     "    b.set(2, 92)\n"
     "    if a.get(0) != 3:\n"
     "        return 10 + a.get(0)\n"
     "    if a.get(1) != 4:\n"
     "        return 20 + a.get(1)\n"
     "    if a.get(2) != 5:\n"
     "        return 30 + a.get(2)\n"
     "    if b.get(0) != 90:\n"
     "        return 40 + b.get(0)\n"
     "    if b.get(1) != 91:\n"
     "        return 50 + b.get(1)\n"
     "    if b.get(2) != 92:\n"
     "        return 60 + b.get(2)\n"
     "    return 7\n", 7, None),
    # (3b) A copy whose value is checked through a plain assignment afterwards,
    # so the copy is not only "not the same address" but "an independent block
    # that reads back what the source read". The guard codes are the two
    # instances' values, so a swap is caught as well as a share.
    ("constr_copy_reads_back_what_the_source_read",
     "struct Pair3:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "    fn set_x(self, v: Int) -> Int:\n"
     "        self.x = v\n"
     "        return self.x\n"
     "\n"
     "    fn set_y(self, v: Int) -> Int:\n"
     "        self.y = v\n"
     "        return self.y\n"
     "\n"
     "    fn get_x(self) -> Int:\n"
     "        return self.x\n"
     "\n"
     "    fn get_y(self) -> Int:\n"
     "        return self.y\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Pair3()\n"
     "    a.set_x(11)\n"
     "    a.set_y(22)\n"
     "    var b = Pair3(a)\n"
     "    if b.get_x() != 11:\n"
     "        return 10 + b.get_x()\n"
     "    if b.get_y() != 22:\n"
     "        return 20 + b.get_y()\n"
     "    # `b` is now assigned away, so the copy's block is dead and every\n"
     "    # subsequent read must come from `a` alone\n"
     "    b.set_x(99)\n"
     "    var d = Pair3()\n"
     "    if d.get_x() != 0:\n"
     "        return 30 + d.get_x()\n"
     "    if a.get_x() != 11:\n"
     "        return 40 + a.get_x()\n"
     "    return 7\n", 7, None),
    # (4) A COPY OF A STRUCT WITH A PLACED NESTED FRAME. The nested frame's
    # address is one of the slots, so a shallow copy copies the ADDRESS — and
    # the two objects then share the nested object, which is what the language
    # does and what a "helpful" deep copy would get wrong. Written so the
    # sharing is the ASSERTION: `b.bump()` has to be visible through `a`, and a
    # deep copy would make `a`'s nested frame read 23 still.
    ("constr_copy_of_a_nested_frame_shares_it",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    fn bump(self) -> Int:\n"
     "        self.a = self.a + 1\n"
     "        return self.a\n"
     "\n"
     "    fn inner_total(self) -> Int:\n"
     "        return self.a * 10 + self.b\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var in1: Inner\n"
     "\n"
     "    fn bump_inner(self) -> Int:\n"
     "        return self.in1.bump()\n"
     "\n"
     "    fn whole(self) -> Int:\n"
     "        return self.in1.inner_total() * 10 + self.tag\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Outer()\n"
     "    a.tag = 1\n"
     "    a.in1.a = 2\n"
     "    a.in1.b = 3\n"
     "    var b = Outer(a)\n"
     "    if b.whole() != 231:\n"
     "        return 10 + b.whole()\n"
     "    b.bump_inner()\n"
     "    if a.whole() != 331:\n"
     "        return 20 + a.whole()\n"
     "    if b.whole() != 331:\n"
     "        return 30 + b.whole()\n"
     "    return 7\n", 7, None),
    # (5) A COPY WHOSE SOURCE ARRIVED AS THE CALLEE'S FIRST PARAMETER. The
    # source frame then belongs to the CALLER, which is the case that decides
    # whether the copy is a lifetime problem: it is not, because the caller is
    # on the stack for the whole of the call and the copy's block dies with the
    # callee. If the copy were a shared frame, `p.tag = 7` would write the
    # caller's field and the two guards after the call would see it.
    ("constr_copy_of_a_parameter_frame",
     "struct Pt:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "    fn set_x(self, v: Int) -> Int:\n"
     "        self.x = v\n"
     "        return self.x\n"
     "\n"
     "    fn set_y(self, v: Int) -> Int:\n"
     "        self.y = v\n"
     "        return self.y\n"
     "\n"
     "    fn get_x(self) -> Int:\n"
     "        return self.x\n"
     "\n"
     "    fn get_y(self) -> Int:\n"
     "        return self.y\n"
     "\n"
     "def twice(o) -> Int:\n"
     "    var p = Pt(o)\n"
     "    if p.get_x() != o.get_x():\n"
     "        return 90\n"
     "    if p.get_y() != o.get_y():\n"
     "        return 91\n"
     "    p.set_x(70)\n"
     "    if o.get_x() == 70:\n"
     "        return 92\n"
     "    if p.get_x() != 70:\n"
     "        return 93\n"
     "    return 0\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Pt()\n"
     "    a.set_x(3)\n"
     "    a.set_y(4)\n"
     "    if twice(a) != 0:\n"
     "        return 80\n"
     "    if a.get_x() != 3:\n"
     "        return 81\n"
     "    if a.get_y() != 4:\n"
     "        return 82\n"
     "    return 7\n", 7, None),
    # (6) A copy INSIDE A LOOP. The block belongs to the SITE, so the second
    # iteration reuses it — the same reuse a C local gets, and the reason a
    # constructor in a loop cannot grow the stack. The value checked is the
    # SECOND iteration's, and each iteration copies a freshly-mutated source,
    # so a copy that accidentally aliased the PREVIOUS iteration's block would
    # read 100 on the third pass and be caught.
    ("constr_copy_in_a_loop_reuses_the_site",
     "struct Cell2:\n"
     "    var v: Int\n"
     "    var w: Int\n"
     "\n"
     "    fn set_v(self, x: Int) -> Int:\n"
     "        self.v = x\n"
     "        return self.v\n"
     "\n"
     "    fn get_v(self) -> Int:\n"
     "        return self.v\n"
     "\n"
     "    fn get_w(self) -> Int:\n"
     "        return self.w\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var src = Cell2()\n"
     "    var last = 0\n"
     "    for i in range(1, 5):\n"
     "        src.set_v(i * 10)\n"
     "        var c = Cell2(src)\n"
     "        if c.get_v() != i * 10:\n"
     "            return 20 + c.get_v()\n"
     "        if c.get_w() != 0:\n"
     "            return 30 + c.get_w()\n"
     "        c.set_v(99)\n"
     "        if src.get_v() == 99:\n"
     "            return 40 + i\n"
     "        last = c.get_v()\n"
     "    if last != 99:\n"
     "        return 50 + last\n"
     "    if src.get_v() != 40:\n"
     "        return 60 + src.get_v()\n"
     "    return 7\n", 7, None),
    # (7) A ONE-FIELD STRUCT with an argument — the value collapse, and the case
    # that shows `S(x)` on a value is not a copy at all: there is no block, the
    # receiver IS the field, so the argument is not stored, it IS the result.
    # This is the shape wave 2's collapse created and the one an "n-slot copy"
    # framing would get wrong by inventing a frame for it.
    ("constr_one_field_positional_is_the_value",
     "struct Counter:\n"
     "    count: Int\n\n"
     "    def get(self):\n"
     "        return self.count\n\n"
     "def main(n: Int) -> Int:\n"
     "    var c = Counter(37)\n"
     "    if c.get() != 37:\n"
     "        return 20 + c.get()\n"
     "    c.count = 5\n"
     "    var d = Counter(c.count + 1)\n"
     "    if d.get() != 6:\n"
     "        return 30 + d.get()\n"
     "    if c.get() != 5:\n"
     "        return 40 + c.get()\n"
     "    return 7\n", 7, None),
    # (8) `String()` — a zero-operand CONVERSION, which used to be refused for
    # being zero-operand. The reason it is answerable is a property of strings
    # and of nothing else on this path: a literal is interned and
    # NUL-terminated, so the address of `""` IS the empty string, `strlen` of
    # it is 0 and `%s` of it prints nothing. `String("")` already built and
    # already had `len` 0, so this is the same word by another spelling.
    # `std/format/repr.mojo`'s `var string = String()` is the site in the
    # corpus.
    ("constr_empty_string_is_the_empty_string",
     "def main(n: Int) -> Int:\n"
     "    var s = String()\n"
     "    if len(s) != 0:\n"
     "        return 20 + len(s)\n"
     "    var t = String(\"\")\n"
     "    if len(t) != 0:\n"
     "        return 30 + len(t)\n"
     "    printf(\"[%s]\", s)\n"
     "    return 7\n", 7, "[]"),
    # (9) A LOCAL STRUCT whose NAME is in `UNREPRESENTABLE_TYPE_CTORS`. The
    # hand-kept list of unrepresentable type NAMES used to refuse `DType(...)`
    # outright without asking what the file being compiled declares — and a
    # struct of ONE field is a plain word, the most representable thing there
    # is. The rule that was masked is the ordinary one and arity applies it: the
    # call's argument count matches the local declaration's field count, so it
    # is a construction of that struct. The needle for "this is still refused"
    # is in CONSTRUCTION_REFUSALS, where the arity does NOT match.
    ("constr_local_declaration_beats_the_name_list",
     "struct DType:\n"
     "    var width: Int\n\n"
     "    def get(self):\n"
     "        return self.width\n\n"
     "def main(n: Int) -> Int:\n"
     "    var d = DType(9)\n"
     "    if d.get() != 9:\n"
     "        return 20 + d.get()\n"
     "    return 7\n", 7, None),
    # (10) A POSITIONAL CONSTRUCTION INSIDE A LOOP, and a copy out of it. The
    # block is the site's, so both reuse it; the point is that a per-ITERATION
    # expectation is what a per-site block satisfies, and this asserts the
    # second and third iteration's values rather than the first's.
    ("constr_positional_in_a_loop",
     "struct Acc:\n"
     "    var k: Int\n"
     "    var v: Int\n\n"
     "    def get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.k\n"
     "        return self.v\n\n"
     "def main(n: Int) -> Int:\n"
     "    var last_k = 0\n"
     "    var last_v = 0\n"
     "    for i in range(1, 4):\n"
     "        var a = Acc(i, i * i)\n"
     "        if a.get(0) != i:\n"
     "            return 20 + a.get(0)\n"
     "        if a.get(1) != i * i:\n"
     "            return 30 + a.get(1)\n"
     "        last_k = a.get(0)\n"
     "        last_v = a.get(1)\n"
     "    if last_k != 3:\n"
     "        return 40 + last_k\n"
     "    if last_v != 9:\n"
     "        return 50 + last_v\n"
     "    return 7\n", 7, None),

    # ── a DECLARED `__init__`: `S(a, b)` is a CALL, and the call is INLINED ──
    #
    # This whole block is `bugs/FORMAL_struct_construction_shapes.md`'s one
    # remaining refusal, closed.  `Slice` — the case that found it — declares
    # TWO `__init__` overloads against three fields and the corpus writes all
    # three counts, so `Slice(a, b)` is a call to the two-parameter constructor
    # and NOT a two-field construction of a three-field struct.  What used to
    # be a blanket refusal is now the language's own rule: the argument COUNT
    # selects the overload, and the selected overload's body becomes the stores
    # at the construction site.
    #
    # The expected value of every case below is what CPython returns for the
    # same program written as a class with the same two `__init__` overloads —
    # the translation is one-to-one (`struct S:` → `class S:`, `out self` →
    # `self`, `var` dropped), and `python3` has run each of them, so the answer
    # is the language's and not the emitter's.
    #
    # The four rows together are what makes the block a test of the SELECTION
    # rather than of the stores: a program that filled `step` with the third
    # argument on every call, or with a constant, or that ignored the count
    # entirely, would pass one row and fail another.
    ("constr_init_arity_selects_the_overload",
     "struct Slice3:\n"
     "    var start: Int\n"
     "    var end: Int\n"
     "    var step: Int\n"
     "\n"
     "    def __init__(out self, start: Int, end: Int):\n"
     "        self.start = start\n"
     "        self.end = end\n"
     "        self.step = 1\n"
     "\n"
     "    def __init__(out self, start: Int, end: Int, step: Int):\n"
     "        self.start = start\n"
     "        self.end = end\n"
     "        self.step = step\n"
     "\n"
     "    def get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.start\n"
     "        if i == 1:\n"
     "            return self.end\n"
     "        return self.step\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Slice3(1, 9)\n"
     "    var b = Slice3(2, 8, 5)\n"
     "    if a.get(0) != 1:\n"
     "        return 10 + a.get(0)\n"
     "    if a.get(1) != 9:\n"
     "        return 20 + a.get(1)\n"
     "    if a.get(2) != 1:\n"
     "        return 30 + a.get(2)\n"
     "    if b.get(0) != 2:\n"
     "        return 40 + b.get(0)\n"
     "    if b.get(1) != 8:\n"
     "        return 50 + b.get(1)\n"
     "    if b.get(2) != 5:\n"
     "        return 60 + b.get(2)\n"
     "    return 7\n", 7, None),
    # The corpus's own spelling, verbatim: `Slice`'s two-parameter constructor
    # ends in `self.step = None`, and `None` is a NAME, not a parameter and not
    # a local of the body.  Without the singleton case the inline refuses here,
    # and with a wrong answer for `None` the field would read as a random word
    # — so the assertion is that `step` is 0, twice, for both constructions.
    #
    # The second half is the fourth-parameter marker: `__slice_literal__` is
    # DEFAULTED and never read, and a defaulted parameter the caller omits and
    # the body ignores must not cost anything.  If the selection counted
    # parameters rather than required ones, the three-argument call below would
    # not match anything and would be refused.
    ("constr_init_none_and_a_defaulted_unread_parameter",
     "struct Sl:\n"
     "    var start: Int\n"
     "    var end: Int\n"
     "    var step: Int\n"
     "\n"
     "    def __init__(out self, start: Int, end: Int):\n"
     "        self.start = start\n"
     "        self.end = end\n"
     "        self.step = None\n"
     "\n"
     "    def __init__(out self, start: Int, end: Int, step: Int, lit: Int = 0):\n"
     "        self.start = start\n"
     "        self.end = end\n"
     "        self.step = step\n"
     "\n"
     "    def get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.start\n"
     "        if i == 1:\n"
     "            return self.end\n"
     "        return self.step\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Sl(0, 4)\n"
     "    var b = Sl(1, 5, 2)\n"
     "    if a.get(0) != 0:\n"
     "        return 10 + a.get(0)\n"
     "    if a.get(1) != 4:\n"
     "        return 20 + a.get(1)\n"
     "    if a.get(2) != 0:\n"
     "        return 30 + a.get(2)\n"
     "    if b.get(2) != 2:\n"
     "        return 40 + b.get(2)\n"
     "    return 5\n", 5, None),
    # A DEFAULTED parameter the body DOES store, called both with and without
    # it.  10 is the default's whole job here: a program that always read the
    # caller's third argument would pass the second check and fail the first,
    # and one that always stored the default would do the reverse.
    ("constr_init_a_defaulted_parameter_the_body_stores",
     "struct Dflt:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __init__(out self, a: Int, b: Int = 7):\n"
     "        self.a = a\n"
     "        self.b = b\n"
     "\n"
     "    def get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.a\n"
     "        return self.b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = Dflt(1)\n"
     "    var y = Dflt(2, 5)\n"
     "    if x.get(0) != 1:\n"
     "        return 10 + x.get(0)\n"
     "    if x.get(1) != 7:\n"
     "        return 20 + x.get(1)\n"
     "    if y.get(1) != 5:\n"
     "        return 30 + y.get(1)\n"
     "    return 3\n", 3, None),
    # A field the constructor does NOT assign.  The language default-
    # initializes the object BEFORE the constructor runs, so `b` keeps its
    # class-level 11 — and that is only true if the bring-up still happens
    # underneath the inlined stores.  A lowering that emitted the constructor's
    # stores alone would leave `b` at whatever the block held, which is a
    # plausible-looking number nobody wrote: the case is here for that.
    ("constr_init_an_unassigned_field_keeps_its_class_default",
     "struct Part:\n"
     "    var a: Int\n"
     "    var b: Int = 11\n"
     "    var c: Int\n"
     "\n"
     "    def __init__(out self, a: Int, c: Int):\n"
     "        self.a = a\n"
     "        self.c = c\n"
     "\n"
     "    def get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.a\n"
     "        if i == 1:\n"
     "            return self.b\n"
     "        return self.c\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = Part(1, 3)\n"
     "    if p.get(0) != 1:\n"
     "        return 10 + p.get(0)\n"
     "    if p.get(1) != 11:\n"
     "        return 20 + p.get(1)\n"
     "    if p.get(2) != 3:\n"
     "        return 30 + p.get(2)\n"
     "    return 4\n", 4, None),
    # A ONE-FIELD struct, where the receiver IS the field and there is nothing
    # to store into.  The constructor's body is still what decides the value, so
    # the LAST store is the whole result — the same word, for the same reason
    # a positional argument on a one-field struct is the result.
    ("constr_init_a_one_field_struct_is_the_last_store",
     "struct One1:\n"
     "    var n: Int\n"
     "\n"
     "    def __init__(out self, n: Int):\n"
     "        self.n = n\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.n\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var w = One1(42)\n"
     "    if w.get() != 42:\n"
     "        return 20 + w.get()\n"
     "    return 6\n", 6, None),
    # A constructor inside a LOOP, which is the per-SITE block discipline with
    # stores in it.  The values checked are the THIRD iteration's, so a
    # per-iteration block and a per-site one both pass and only a store that
    # survived from iteration one — the failure mode of a bring-up that ran once
    # — would not.
    ("constr_init_in_a_loop_reuses_its_site_block",
     "struct Acc2:\n"
     "    var k: Int\n"
     "    var v: Int\n"
     "\n"
     "    def __init__(out self, k: Int, v: Int):\n"
     "        self.k = k\n"
     "        self.v = v\n"
     "\n"
     "    def get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.k\n"
     "        return self.v\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var last_k = 0\n"
     "    var last_v = 0\n"
     "    for i in range(1, 4):\n"
     "        var a = Acc2(i, i * i)\n"
     "        if a.get(0) != i:\n"
     "            return 20 + a.get(0)\n"
     "        if a.get(1) != i * i:\n"
     "            return 30 + a.get(1)\n"
     "        last_k = a.get(0)\n"
     "        last_v = a.get(1)\n"
     "    if last_k != 3:\n"
     "        return 40 + last_k\n"
     "    if last_v != 9:\n"
     "        return 50 + last_v\n"
     "    return 7\n", 7, None),
    # THE LANGUAGE'S ANSWER, and the test that was missing while this was
    # pinned the other way: `S()` on a struct whose `__init__` takes no
    # REQUIRED parameter RUNS the constructor, so `Z()` is `a == 8, b == 9`.
    #
    # This used to assert the opposite (both fields zero), and pinning a
    # known-wrong answer is how it stayed wrong: nothing else in the corpus
    # distinguishes a correct zero-argument lowering from the zeros, so a green
    # suite said nothing either way.  `init_overload_for_arity` is what makes
    # it decidable rather than a guess — it admits a count of 0 exactly when
    # some declared overload takes no required parameter, and answers
    # `ambiguous` (a refusal) when two of them would, so `S()` is selected by
    # exactly the rule every other count is.  The exit status is 1 because
    # `main` returns 1 when both fields carry the defaults, and 0 otherwise, so
    # the zeros and CPython's answer are different exit codes and this test
    # cannot pass for either by accident.
    ("constr_a_zero_argument_construction_runs_a_zero_required_init",
     "struct Z:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __init__(out self, a: Int = 8, b: Int = 9):\n"
     "        self.a = a\n"
     "        self.b = b\n"
     "\n"
     "    def get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.a\n"
     "        return self.b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var z = Z()\n"
     "    if z.get(0) == 8 and z.get(1) == 9:\n"
     "        return 1\n"
     "    return 0\n", 1, None),
    # …and the GUARD that says the change did not OVERREACH: a struct that
    # declares NO constructor is still brought up at its class-level defaults,
    # because there is no body to run.  Same shape as the case above with the
    # `__init__` removed, so it is the only thing separating "zero-argument
    # constructions run a constructor" from "every construction runs one".
    ("constr_a_zero_argument_construction_of_a_constructor_less_struct",
     "struct P9:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.a\n"
     "        return self.b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P9()\n"
     "    if p.get(0) != 0 or p.get(1) != 0:\n"
     "        return 20 + p.get(0)\n"
     "    return 7\n", 7, None),
]

CONSTRUCTION_REFUSALS = [
    # ── a declared `__init__`, which makes `S(...)` a CALL ──
    #
    # This used to be ONE refusal for every construction of a struct that
    # declares a constructor, and the reason it existed was a good one: with a
    # declared `__init__`, `S(a, b)` is a CALL to it, so the arity message's
    # claim — "a struct's fields are filled in DECLARATION ORDER and there is
    # no other form" — is FALSE for such a struct, and a message that is false
    # about the program in front of the reader is worse than no message.
    # `Slice` is what made it concrete and it was twenty stdlib files' first
    # blocking fact.
    #
    # What is left here is the part of that refusal which is still true, split
    # by what is actually wrong.  A call does not have to be EMITTED to be RUN:
    # a constructor body that is a straight line of `self.<field> = <expr>`
    # stores is the same program as the construction followed by those stores,
    # and that is a shape this path already emits — so the argument count now
    # selects the overload and the selected body becomes the stores
    # (`CASES`, "a DECLARED `__init__`").  What the inline cannot supply is an
    # overload the count does not pick out of one, and a body that is not only
    # those stores.  Each of the five cases below is one of those, and each
    # names its own cause.
    #
    # (1) No declared arity admits the count.  `Slice` admits 2, 3 and 4
    # positionals, and `A(1)` is not one of them — an error the language reports
    # at the call, and the fix is on the caller's side, so the message spells
    # the declared shapes.  The needle is the SHAPES, because a count alone
    # leaves the reader to work out which arity was wrong.
    ("constr_refuse_an_init_count_no_overload_takes",
     "struct A1:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __init__(out self, a: Int, b: Int):\n"
     "        self.a = a\n"
     "        self.b = b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = A1(1)\n"
     "    return x.a\n",
     "refuse:and none of them takes that count: A1 declares 1 `__init__` overload (2 required (a, b))",
     None),
    # (2) TWO overloads admit the count.  This path resolves nothing by type —
    # a call site carries the argument count and the arguments, never their
    # types — so it cannot say which constructor the source named, and picking
    # either would be running a constructor the program did not choose.  The
    # needle is the AMBIGUITY, because "it is refused" and "it is refused
    # because two would have done" have different fixes and a reader who is sent
    # to the class body can only find that out by reading both.
    ("constr_refuse_two_inits_admitting_the_same_count",
     "struct A2:\n"
     "    var a: Int\n"
     "\n"
     "    def __init__(out self, a: Int):\n"
     "        self.a = a\n"
     "\n"
     "    def __init__(out self, a: Int, b: Int = 2):\n"
     "        self.a = a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = A2(1)\n"
     "    return x.a\n",
     "refuse:and TWO of them admit that count", None),
    # (3) A BRANCH in the body.  The body is not a sequence of stores, and a
    # branch means the value in a field depends on a condition this path would
    # have to reproduce at the construction site rather than copy.  The needle
    # is the STATEMENT, because "this constructor is not lowered" without it
    # sends the reader back to the class body to work out which of its lines
    # mattered.
    ("constr_refuse_an_init_body_with_a_branch",
     "struct A3:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __init__(out self, a: Int, b: Int):\n"
     "        self.a = a\n"
     "        if b > 0:\n"
     "            self.b = b\n"
     "        else:\n"
     "            self.b = 0 - b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = A3(1, 2)\n"
     "    return x.a\n",
     "refuse:whose body this path does not inline: a `if` statement", None),
    # (4) A LOCAL of the body.  This is the asymmetry with running the body in
    # place, and it is why the accepted set is a set: the body is INLINED into
    # the calling function, where a name it binds does not exist.  The needle is
    # the ASSIGNMENT, so the reader is told which line rather than which class.
    ("constr_refuse_an_init_body_that_binds_a_local",
     "struct A4:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __init__(out self, a: Int, b: Int):\n"
     "        t = a + b\n"
     "        self.a = t\n"
     "        self.b = b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = A4(1, 2)\n"
     "    return x.a\n",
     "refuse:whose body this path does not inline: a local assignment (`t = …`)",
     None),
    # (5) A READ OF THE RECEIVER, which is the case a bare-parameter check
    # misses and the one that would be a wrong ANSWER rather than a refusal:
    # `self.a = a` is fine because `a` is the caller's own expression, and
    # `self.a = 1 + a` is not, because the arithmetic names a word the calling
    # function does not have.  The needle is the READ, and the parameter row
    # below is its twin from the other side.
    ("constr_refuse_an_init_body_that_reads_the_receiver",
     "struct A5:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __init__(out self, a: Int, b: Int):\n"
     "        self.a = a\n"
     "        self.b = self.a + b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = A5(1, 2)\n"
     "    return x.b\n",
     "refuse:whose body this path does not inline: a read of 'self' in the right-hand side",
     None),
    # (6) The same refusal for a PARAMETER, which is the one that is easy to
    # get wrong in the accepting direction: a program that inlined this would
    # read a word out of whatever register the CALLING function left in it, and
    # the caller is `main`, whose first argument is the test input.
    ("constr_refuse_an_init_body_that_reads_a_parameter_in_an_expression",
     "struct A6:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __init__(out self, a: Int, b: Int):\n"
     "        self.a = a + 1\n"
     "        self.b = b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = A6(1, 2)\n"
     "    return x.a\n",
     "refuse:whose body this path does not inline: a read of 'a' in the right-hand side",
     None),
    # (6b) An AUGMENTED assignment.  It is a read AND a write, so the value it
    # stores depends on what is already in the slot — and the slot holds the
    # CLASS-LEVEL default at the point the constructor's stores run, not
    # whatever an earlier statement stored.  Refused rather than answered with
    # the class default, because that is a different program from the language's
    # for every statement after the first.  Its own case because the statement
    # SPELLING is the only thing distinguishing it from a local assignment, and
    # a reader who saw "a local assignment" for `self.b += b` would go looking
    # in the wrong place.
    ("constr_refuse_an_init_body_with_an_augmented_assignment",
     "struct A6b:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __init__(out self, a: Int, b: Int):\n"
     "        self.a = a\n"
     "        self.b += b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = A6b(1, 2)\n"
     "    return x.a\n",
     "refuse:whose body this path does not inline: an augmented assignment to `self.b`",
     None),
    # (7) A CONSTRUCTION OF A FRAMED STRUCT inside the body.  Its receiver
    # block is reserved per call SITE, in the prologue of the function whose
    # body names the call; a body inlined into a construction elsewhere has no
    # such site, and emitting the construction anyway would write into a block
    # nothing reserved.  `StridedSlice.__init__` in `builtin_slice.mojo` is
    # this shape, which is why the message names the reason rather than the
    # node class.
    #
    # The construction is NESTED in a container literal, and that is the point
    # rather than decoration: a check on the top-level node alone would let this
    # through to the emitter, which looks the call up in this function's
    # reserved sites, does not find it, and refuses with "the frame layout and
    # the body disagree … which is a compiler bug" — a diagnostic about the
    # compiler, printed for a program that is merely a shape this path cannot
    # lower.  The needle is the CONSTRUCTOR, so a reader who lands here knows
    # which call the inline cannot host.
    ("constr_refuse_an_init_body_that_constructs_a_framed_struct",
     "struct In1:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct In2:\n"
     "    var items: List[Int]\n"
     "    var g: Int\n"
     "\n"
     "    def __init__(out self, g: Int):\n"
     "        self.items = [In1(1, 2)]\n"
     "        self.g = g\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = In2(3)\n"
     "    return x.g\n",
     "refuse:whose body this path does not inline: `In1(…)`, a construction of a struct whose receiver is a frame",
     None),
    # (8) The SAME construction into a field DECLARED with that struct's type,
    # and the message is a different one — the placement's.  `f` is a field this
    # constructor brings a nested frame up in, so storing a word over it is what
    # `construction_nested_slot_refusal` is for, and that is the more useful of
    # the two: it names the slot and what a read through it would compute.  It
    # is a separate case because two refusals for one family is exactly what
    # "the needle is the fact that is wrong" is for, and because the ORDER
    # matters: the placement check runs after the walk, so a bare-parameter
    # store into a placed slot is answered by the placement and a computed one
    # by the walk.
    ("constr_refuse_an_init_store_over_a_placed_nested_frame",
     "struct In3:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct In4:\n"
     "    var f: In3\n"
     "    var g: Int\n"
     "\n"
     "    def __init__(out self, f: In3, g: Int):\n"
     "        self.f = f\n"
     "        self.g = g\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = In4(In3(1, 2), 3)\n"
     "    return x.g\n",
     "refuse:as field 'f' is refused on this path: 'f' is declared as a In3",
     None),
    # The other side of the same line, and the one the change made a REFUSAL:
    # a zero-argument `S()` on a struct whose `__init__` REQUIRES a parameter.
    # `Bag4()` is a `TypeError` in the language — the constructor needs `n` and
    # `m` — and it used to build, run and return 7 by bringing both fields up
    # at zero.  A silently wrong value is the outcome this backend treats as
    # worst available, and the count is not ambiguous here: `init_overload_
    # for_arity` says no declared overload takes 0 and the message spells the
    # overloads it does declare, so the fix is on the caller's side.
    ("constr_refuse_a_zero_arg_construction_when_init_requires_parameters",
     "struct Bag4:\n"
     "    var n: Int\n"
     "    var m: Int\n"
     "\n"
     "    def __init__(out self, n: Int, m: Int):\n"
     "        self.n = n\n"
     "        self.m = m\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.n * 10 + self.m\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Bag4()\n"
     "    return b.get()\n",
     "refuse:none of them takes that count", None),
    # ── ARITY: too few, too many, and a zero-field struct ──
    # Too FEW. `S(1)` on a two-field `S` is not a one-field construction, it is
    # a two-field construction missing an argument, and the message has to say
    # so rather than leaving the reader to infer it from a count. The needle is
    # the FIELD LIST, because the field list is the answer to "which argument
    # is missing" and a bare count is not.
    ("constr_refuse_too_few_arguments",
     "struct P1:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "    def get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.x\n"
     "        return self.y\n\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P1(1)\n"
     "    return p.get(0)\n",
     "refuse:does not match its fields (2 field(s): x, y)", None),
    # Too MANY, and the mirror image: the count is not a field list, so the
    # message spells both sides. `P2` is a FOUR-field struct, so this also
    # covers a width past the cheapest case.
    ("constr_refuse_too_many_arguments",
     "struct P2:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "    var z: Int\n"
     "    var w: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P2(1, 2, 3, 4, 5)\n"
     "    return p.x\n",
     "refuse:with 5 argument(s) does not match its fields (4 field(s): x, y, z, w)",
     None),
    # A struct with NO fields at all and three arguments. This is the case the
    # pre-existing `struct_ctor_args_both_backends` covers, re-spelled: the old
    # text was "a struct is default-initialized and its fields assigned", which
    # was stale for the wrong reason, and the honest content here is that
    # `Resolver` derives no fields so there is nowhere to put an argument.
    ("constr_refuse_a_struct_with_no_fields",
     "class Resolver2:\n"
     "    def resolve(self, name):\n"
     "        return len(name)\n\n"
     "def main(n):\n"
     "    r = Resolver2(n, n, n)\n"
     "    return r.resolve(\"a\")\n",
     "refuse:does not match its fields (no fields at all)", None),
    # ── A KEYWORD construction, which the language does not have ──
    # `P3(x=1, y=2)` is not a shape a struct construction has. The tempting
    # wrong answer is to read the keywords as positionals in dict order, which
    # makes a program's meaning depend on an iteration order nobody wrote.
    ("constr_refuse_keyword_arguments",
     "struct P3:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P3(x=1, y=2)\n"
     "    return p.x\n",
     "refuse:keyword argument(s) 'x', 'y' is not a shape this path lowers",
     None),
    # ── a COPY of the wrong thing ──
    # A copy of a DIFFERENT struct. A copy here is a slot-for-slot copy, so it
    # is only defined between two objects of the SAME layout, and `B` is a
    # different layout by definition. The tempting wrong answer is to copy
    # anyway: the two structs in this program have the same field NAMES, so a
    # slot-for-slot copy would produce a plausible object — and it would be a
    # different program from the one written.
    ("constr_refuse_copy_of_another_struct",
     "struct A1:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "struct B1:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = A1()\n"
     "    x.a = 7\n"
     "    x.b = 8\n"
     "    var y = B1(x)\n"
     "    return y.a\n",
     "refuse:is a COPY CONSTRUCTION and the argument is a A1 frame, not a B1 one",
     None),
    # A copy of a name NOTHING can recognise as a frame. This is the refusal
    # whose absence would be the worst outcome available, because it is the one
    # that is not a missing feature: `q` is a plain `Int` local, and copying
    # slot 0 out of the word `7` would copy seven bytes of a stack frame and a
    # count field. The program would build, run, and return a number nobody
    # wrote. So an absent answer IS the answer, the same tie-break
    # `frame_field_type_candidates` uses.
    ("constr_refuse_copy_of_an_unrecognised_word",
     "struct P4:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var q = 7\n"
     "    var p = P4(q)\n"
     "    return p.x\n",
     "refuse:is a COPY CONSTRUCTION and nothing here can say that argument is a P4 frame",
     None),
    # A copy of a name that may be EITHER of two structs. `struct_frame_slot_
    # candidates`'s question one level in, with the same answer: two candidate
    # layouts and no path sensitivity, so there is no one layout to copy.
    ("constr_refuse_copy_from_an_ambiguous_name",
     "struct A2:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "struct B2:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "def pick(c: Int) -> Int:\n"
     "    var x = A2()\n"
     "    if c > 0:\n"
     "        x = B2()\n"
     "    var y = A2(x)\n"
     "    return y.a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return pick(0)\n",
     "refuse:is a COPY CONSTRUCTION and the argument is a A2, B2 frame", None),
    # ── a FRAME ADDRESS as a ONE-WORD struct's whole value ──
    # `One(fr)` where `fr` is a two-field frame. A framed object has a BLOCK and
    # a block is confined to the function that built it; a one-field struct has
    # no block, its receiver IS the field, and a plain word is passed around
    # without any frame-lifetime check seeing it. Same reason
    # `byref_refuse_frame_address_in_a_field` exists, one level out.
    ("constr_refuse_frame_address_as_a_one_field_value",
     "struct Two3:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "struct One3:\n"
     "    var only: Int\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var t = Two3()\n"
     "    t.a = 4\n"
     "    var o = One3(t)\n"
     "    return o.only\n",
     "refuse:its whole value IS that word", None),
    # ── an argument landing on a PLACED NESTED FRAME's slot ──
    # `in1` is declared `Inner`, so the constructor PLACED an Inner frame in
    # that slot and in the object's own block. Storing `2` over it would leave
    # a value where `self.in1.a` computes a frame base from it. The
    # construction is refused by name, and the needle is the PLACEMENT, because
    # that is the fact a reader needs and the one a regression would drop.
    ("constr_refuse_argument_on_a_placed_nested_slot",
     "struct Inner3:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "struct Outer3:\n"
     "    var tag: Int\n"
     "    var in1: Inner3\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer3(1, 2)\n"
     "    return o.tag\n",
     "refuse:the constructor PLACED a Inner3 frame in that slot", None),
    # ── a container from a CALLEE, which is a blob in reclaimed stack ──
    # `mklist()` is DECLARED to return a list, so the constructor knows the
    # word it is about to store is a bump-allocated region of the callee's own
    # reserved scratch, and that scratch is gone by the time the store happens.
    # The declaration is the whole of the evidence, and the two cases either
    # side of it are the point: a container LITERAL is allowed (built by the
    # function whose block is being filled, so it outlives every read of the
    # slot) and a call declared `-> Int` is allowed (an integer is a word).
    # Which is why `constr_positional_expression_arguments` passes
    # `scale(4)` and this one does not.
    ("constr_refuse_container_returned_by_a_callee",
     "struct Bag2:\n"
     "    var items: Int\n"
     "    var n: Int\n"
     "\n"
     "def mklist() -> List[Int]:\n"
     "    var xs = [1, 2, 3]\n"
     "    return xs\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Bag2(mklist(), 5)\n"
     "    return b.n\n",
     "refuse:is declared to return a container, and a container on this path is a "
     "bump-allocated region of the CALLEE's own reserved scratch",
     None),
    # The REACHABLE CONSEQUENCE of the hazard the case above refuses, checked
    # separately and for a different reason. `append` through a frame slot is
    # refused on its own terms — the room an append needs has to be known where
    # the list is built, and a slot is not a list literal — which is what makes
    # the permissive tie-break in `_construction_arg_is_dead_blob` safe rather
    # than merely arguable: a container LITERAL in a field, and a call with no
    # declared return type, are both allowed, and neither can be reached
    # through a method on this path. This case is here so that the day the
    # append IS lowered, the argument above is visibly false rather than
    # quietly stale.
    ("constr_append_through_a_field_is_still_refused",
     "struct Bag3:\n"
     "    var items: Int\n"
     "    var n: Int\n"
     "\n"
     "    fn add(self, v: Int) -> Int:\n"
     "        self.items.append(v)\n"
     "        return self.n\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Bag3([1, 2, 3], 5)\n"
     "    return b.add(4)\n",
     "refuse:list.append() is not lowered on the formal", None),
    # The `String` name is a struct some files declare, and `Pointer` is a
    # struct some files declare AND an identity conversion. Neither the
    # construction table nor the type-constructor table may reach across, so
    # this case pins the boundary: `String()` is a zero-operand CONVERSION
    # (answered, above) while `String(1, 2)` is a genuine arity error on the
    # conversion, not a construction.
    ("constr_refuse_two_operand_conversion",
     "def main(n: Int) -> Int:\n"
     "    var s = String(1, 2)\n"
     "    return 0\n",
     "refuse:takes exactly one value to convert", None),
    # And the other side of the same boundary: a name in the unrepresentable
    # list that this module does NOT declare, called with an argument count
    # that does not match any local declaration, keeps its refusal. This is the
    # negative guard for
    # `model.type_constructor_prefers_local_struct`: arity decides, and an
    # unmatched call is left exactly as it was.
    ("constr_refuse_undeclared_name_in_the_unrepresentable_list",
     "def main(n: Int) -> Int:\n"
     "    var e = DType(1, 2)\n"
     "    return 0\n",
     "refuse:constructing DType has no representation on this path", None),
]


# ── wave 3 (C4): the subscript, and a subscript with more than one index ──
#
# `x[a, b]` is a SubscriptExpr whose index is a TUPLE. What it means is
# settled by the corpus rather than by the spelling: across the 294 stdlib
# files and every source in this repository there is not one multi-element
# subscript whose base is a value. They are all compile-time explicit-
# parameter lists on a generic (`size_of[type, target]`,
# `external_call["sysctlbyname", Int32]`, `UnsafePointer[NoneType,
# MutAnyOrigin]`) or `__mlir_attr[...]` templates — a construct that selects
# an instantiation and hands it types, of which no runtime word exists here.
# So none of them is a 2-D index, and a stride would have to be invented.
#
# The refusals live in `_emit_subscript_addr` on both backends, which is the
# one place a read, a store and an augmented assignment all pass through, and
# the TEXT comes from formal/model.py so the two architectures cannot drift.
# The `refuse:` cases below run on both, which is the assertion.
SUBSCRIPT_CASES = [
    # ── the three that must keep working ──
    # A single-index read, with the index in a VARIABLE rather than a literal
    # because that is the shape nothing in formal/examples covers: all 65 of
    # them index with a literal, which is why an arm64 proof gap on
    # `a[i]` (see bugs/FORMAL_arm64_known_proof_gaps.md) went unregistered.
    # The exit status is the assertion: 20, not a frame address.
    ("sub_single_index_var",
     "def main(n):\n"
     "    a = [10, 20, 30]\n"
     "    i = 1\n"
     "    return a[i]\n", 20, None),
    # Out of range must still be LOUD. This is the bargain the blob
    # bounds-check buys: a 3-element list indexed at 7 exits(1) rather than
    # reading past the end of the frame. It is here because the multi-index
    # refusal was added at the same place this check lives, and a check added
    # next to a bounds check is a check that can be lost.
    ("sub_out_of_range_exits",
     "def main(n):\n"
     "    a = [10, 20, 30]\n"
     "    i = 7\n"
     "    return a[i]\n", 1, None),
    # The store path, for the same reason and for wave 1's B3: `_emit_sub-
    # script_store_reg` used to build the ADDRESS in X0 and then store X0, so
    # `a[i] = 9` wrote a pointer. 9 + 1 = 10, and a pointer is not 9.
    ("sub_single_index_store",
     "def main(n):\n"
     "    a = [1, 2, 3]\n"
     "    i = 2\n"
     "    a[i] = 9\n"
     "    return a[i] + a[0]\n", 10, None),
    # ── the multi-index forms, all of which must be refused identically ──
    # `a[i, j]` on a LIST. The one that motivated the group. Pre-change this
    # was refused on arm64 and SILENTLY LOWERED on x86-64: the index tuple
    # became a frame blob and that blob's own ADDRESS was used as the element
    # index, so `a[i, j]` returned an element nobody asked for.
    ("sub_multi_index_list_read",
     "def main(n):\n"
     "    a = [10, 20, 30]\n"
     "    i = 1\n"
     "    j = 2\n"
     "    return a[i, j]\n",
     "refuse:is a subscript whose index is a tuple", None),
    # A static tuple index, which pre-change took a different wrong road: the
    # old rule let any statically-known container key through to the DICT
    # path, so a list base was scanned as if it held pair keys.
    ("sub_multi_index_list_static_key",
     "def main(n):\n"
     "    a = [10, 20, 30]\n"
     "    return a[1, 2]\n",
     "refuse:is a subscript whose index is a tuple", None),
    # On a STRING, where there is no bounds check to catch a bad index at all
    # (a string is a bare `char *` with no header). Pre-change this SEGFAULTED
    # on x86-64 while arm64 refused: base + (address of the tuple blob).
    ("sub_multi_index_string_read",
     "def main(n):\n"
     "    s = \"hello\"\n"
     "    i = 1\n"
     "    j = 2\n"
     "    c = s[i, j]\n"
     "    return 0\n",
     "refuse:is a subscript whose index is a tuple", None),
    # THE STORE, and the reason the check moved to the address computation:
    # both refusals used to sit in the READ path, so `a[i, j] = v` reached the
    # emitter. On arm64 that made the PROOF GENERATOR livelock (it was killed
    # at 50s and again at 45s; the sweep's own 300s timeout is what eventually
    # catches it), and on x86-64 it built and ran.
    ("sub_multi_index_list_store",
     "def main(n):\n"
     "    a = [1, 2, 3]\n"
     "    i = 1\n"
     "    j = 2\n"
     "    a[i, j] = 9\n"
     "    return a[0]\n",
     "refuse:is a subscript whose index is a tuple", None),
    # On a FRAME-BACKED STRUCT FIELD. This is C2's territory and the
    # interaction is the point: the field is a frame slot, so the refusal must
    # be about the SUBSCRIPT and must not be attributed to the receiver — a
    # message here would send the reader to the frame rules for something the
    # frame rules are fine with. Same needle as the plain list case, which is
    # what says the two produced the same answer.
    ("sub_multi_index_frame_field",
     "struct Point:\n"
     "    x: Int\n"
     "    y: Int\n\n"
     "    fn get_x(self) -> Int:\n"
     "        return self.x\n\n"
     "def main(n):\n"
     "    p = Point()\n"
     "    p.x = 5\n"
     "    i = 0\n"
     "    j = 1\n"
     "    return p.x[i, j]\n",
     "refuse:is a subscript whose index is a tuple", None),
    # A generic's explicit-parameter list used AS A VALUE, which is the shape
    # `size_of[type, target]` and `is_triple["…", target]` have when they are
    # not the callee of a call. `pick[1, 2]()` — the call form — is a
    # different route through `_emit_call` and is deliberately not here.
    ("sub_multi_index_comptime_params",
     "def pick[type: Int, target: Int]() -> Int:\n"
     "    return type + target\n\n"
     "def main(n):\n"
     "    v = pick[1, 2]\n"
     "    return 0\n",
     "refuse:is a compile-time explicit-parameter list on a generic", None),
    # The construct that actually blocks 36 stdlib files, named for what it
    # is. `std/sys/info.mojo` has 27 of these and nothing else the backend
    # reaches first; the old text called it a "multi-index subscript", which
    # is a misdiagnosis — it is not a subscript and no index is involved.
    ("sub_multi_index_mlir_template",
     "def main(n):\n"
     "    x = __mlir_attr[`#kgen.param.expr<eq,`, 1, `, 2> : i1`]\n"
     "    return 0\n",
     "refuse:assembles an MLIR attribute from a template", None),
    # `del a[i, j]`. arm64 reaches the subscript here and refuses with the
    # shared message; x86-64 has no `del` at all and refuses the STATEMENT
    # first, which is correct and complete but names a different thing. Both
    # refusing is the assertion, and the two reasons are genuinely different,
    # which `refuse:` cannot express — hence `refuse_either:`.
    #
    # This case exists because the shape used to be a silent NO-OP: the
    # SubscriptExpr branch of arm64's `_emit_del` sits after the SliceExpr
    # branch's `continue`, so `del a[i, j]` fell off the end of the loop,
    # built, ran, and left all three elements in place.
    ("sub_multi_index_del",
     "def main(n):\n"
     "    a = [1, 2, 3]\n"
     "    i = 0\n"
     "    j = 1\n"
     "    del a[i, j]\n"
     "    return a[0]\n",
     "refuse_either:is a subscript whose index is a tuple|"
     "unsupported statement DelStmt", None),
    # A multi-index inside a function whose frame is already well filled. The
    # refusal must be the SUBSCRIPT's, not the frame-capacity one, and it must
    # be the same on both arches: a construct that needs more slots than the
    # frame has has to fail loudly and say which of the two it was.
    ("sub_multi_index_near_frame_capacity",
     "def main(n):\n"
     "    a = [1, 2, 3]\n"
     "    b = [4, 5, 6]\n"
     "    c = [7, 8, 9]\n"
     "    d = [10, 11, 12]\n"
     "    e = [13, 14, 15]\n"
     "    f = [16, 17, 18]\n"
     "    g = [19, 20, 21]\n"
     "    h = [22, 23, 24]\n"
     "    i = 1\n"
     "    j = 2\n"
     "    v = a[i, j] + b[i, j] + c[i, j] + d[i, j]\n"
     "    return v + e[i, j] + f[i, j] + g[i, j] + h[i, j]\n",
     "refuse:is a subscript whose index is a tuple", None),
]


# ── wave 6: `~`, the truthiness conversion, and a slice of a string ────────
#
# Three separate defects, all found by RUNNING programs and all in the same
# family: a value on this path is one 64-bit word, and three constructs reached
# the integer path without asking what the word held. `~s` did not even reach
# the compiler — `fire_compiler.py`'s tokenizer had no `~` in its OP
# alternation, so `~` was dropped as UNK and `r = ~s` built an AST containing
# `r = s`. That is the worst shape a wrong answer has: not a crash, not a
# refusal, a program that runs and computes what the source did not say, from a
# construct that does not parse.
WAVE6_TRUTHY_CASES = [
    # `~` ON AN INTEGER — the overwhelmingly common use, and the one that was
    # ALSO wrong before the lexer fix, for the same reason. `~5` returned 5: the
    # token was gone, so the expression was just `5`. Every value here is what
    # Python says for a two's-complement 64-bit word, and the case is worth
    # having for the arm64 MVN and the x86-64 NOT separately, since they are two
    # instructions in two files that had to be added independently.
    ("tilde_int_is_minus_one_less",
     "def main(n):\n"
     "    return ~5 + 6\n", 0, None),
    ("tilde_int_edges",
     "def main(n):\n"
     "    printf(\"%d %d %d %d\", ~0, ~1, ~-1, ~~7)\n"
     "    return 0\n", 0, "-1 -2 0 7"),
    ("tilde_int_through_a_variable",
     "def main(n):\n"
     "    k = 5\n"
     "    r = ~k\n"
     "    printf(\"%d\", r)\n"
     "    return 0\n", 0, "-6"),
    ("tilde_int32_is_truncated_to_its_width",
     "def main(n):\n"
     "    var k: Int32 = 5\n"
     "    printf(\"%d\", ~k)\n"
     "    return 0\n", 0, "-6"),

    # `~` ON A STRING. Before the lexer fix this was `r = s` and printed the
    # ADDRESS of the string (46007208 on arm64, 38761401 on x86-64 — two
    # architectures, two numbers, neither computed). Now it is a refusal, and
    # identically worded on both, which is the assertion.
    ("tilde_string_refused",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    r = ~s\n"
     "    printf(\"%d\", r)\n"
     "    return 0\n",
     "refuse:unary '~' is refused on a string", None),

    # ── truthiness, and the empty string is the case that matters ──────────
    #
    # `if s:` is a CONVERSION, not a special case of `if x:`, and the conversion
    # depends on what the operand holds. On this path a string is a bare
    # `char *`, so the identity test this replaces says TRUE for every string
    # INCLUDING THE EMPTY ONE. Before this, `if e:` where `e = ""` printed
    # `E-truthy` on both backends: a program testing a string for emptiness was
    # told the empty string is non-empty, and nothing downstream could tell.
    ("truthy_empty_string_is_false",
     "def main(n):\n"
     "    e = \"\"\n"
     "    if e:\n"
     "        printf(\"E-truthy\")\n"
     "    else:\n"
     "        printf(\"E-falsy\")\n"
     "    return 0\n", 0, "E-falsy"),
    ("truthy_nonempty_string_is_true",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    if s:\n"
     "        printf(\"S-truthy\")\n"
     "    else:\n"
     "        printf(\"S-falsy\")\n"
     "    return 0\n", 0, "S-truthy"),
    # A string that is not a literal and not an int: the interned bytes of a
    # method result. `strlen` has to be reached through a NAME here, which is
    # the shape a compile-time special case would miss.
    ("truthy_lstrip_result_is_true",
     "def main(n):\n"
     "    s = \"  hi\".lstrip()\n"
     "    if s:\n"
     "        printf(\"S-truthy\")\n"
     "    else:\n"
     "        printf(\"S-falsy\")\n"
     "    return 0\n", 0, "S-truthy"),
    # A `String`-ANNOTATED parameter, which is what the kind table is for: the
    # truthiness has to follow the annotation across a call boundary, and it
    # cannot be told from the literal case — the callee sees a name.
    ("truthy_annotated_parameter",
     "def f(s: String):\n"
     "    if s:\n"
     "        return 1\n"
     "    return 0\n"
     "def main(n):\n"
     "    printf(\"%d %d\", f(\"\"), f(\"x\"))\n"
     "    return 0\n", 0, "0 1"),

    # A list blob's truthiness is its COUNT, which is at offset 0. `if []:`
    # was TRUE before this — a fabricated truthiness in the same family, found
    # while checking the string one and not named in wave 5's list at all.
    ("truthy_empty_list_is_false",
     "def main(n):\n"
     "    a = []\n"
     "    if a:\n"
     "        printf(\"L-truthy\")\n"
     "    else:\n"
     "        printf(\"L-falsy\")\n"
     "    return 0\n", 0, "L-falsy"),
    ("truthy_nonempty_list_is_true",
     "def main(n):\n"
     "    a = [1, 2]\n"
     "    if a:\n"
     "        printf(\"L-truthy\")\n"
     "    else:\n"
     "        printf(\"L-falsy\")\n"
     "    return 0\n", 0, "L-truthy"),
    ("truthy_empty_tuple_is_false",
     "def main(n):\n"
     "    e = ()\n"
     "    f = (1,)\n"
     "    printf(\"%d %d\", 1 if e else 0, 1 if f else 0)\n"
     "    return 0\n", 0, "0 1"),

    # An int and a FRAME ADDRESS. The int is the identity test and is unchanged
    # by any of this — it is here to catch a truthiness helper that "fixed"
    # strings by breaking integers. The frame address is the third kind with an
    # answer: its truthiness is POINTER truthiness, and a frame is never mapped
    # at 0, so the identity test is right for it too. D1 established there is no
    # BOOL kind distinct from INT on this path, so "0/1" and "a bool" are the
    # same thing and nothing here needed a new representation to say so.
    ("truthy_int_zero_and_nonzero",
     "def main(n):\n"
     "    printf(\"%d %d\", 1 if 0 else 0, 1 if 7 else 0)\n"
     "    return 0\n", 0, "0 1"),
    ("truthy_frame_address_is_a_pointer_test",
     "struct P2:\n"
     "    x: Int\n"
     "    y: Int\n"
     "    def total(self):\n"
     "        return self.x + self.y\n"
     "def main(n):\n"
     "    p = P2()\n"
     "    p.x = 1\n"
     "    p.y = 2\n"
     "    if p:\n"
     "        printf(\"F-truthy %d\", p.total())\n"
     "    else:\n"
     "        printf(\"F-falsy\")\n"
     "    return 0\n", 0, "F-truthy 3"),

    # ── the OTHER truthiness sites, one case each ──────────────────────────
    #
    # `if` is the site everyone checks, and it is the one wave 5 already had
    # half of (a comparison in a condition bypasses `_emit_binop`, so `if s < t:`
    # branched on the interning order while `r = s < t` was refused). Every
    # remaining site is here, because a conversion that is right in one of them
    # and missing from the next four is the same bug five times over.

    # `while s:` on the empty string DID NOT TERMINATE before this: the loop
    # condition was the address, the address is never zero, and the body was
    # never even reachable to change it. So this case is a timeout, not a wrong
    # answer, and RUN_TIMEOUT is what it used to run into. `i=0` is the whole
    # assertion: the body never runs, which is what an empty string means.
    ("truthy_while_empty_string_terminates",
     "def main(n):\n"
     "    e = \"\"\n"
     "    i = 0\n"
     "    while e:\n"
     "        i = i + 1\n"
     "        e = \"\"\n"
     "    printf(\"i=%d\", i)\n"
     "    return 0\n", 0, "i=0"),
    # The other direction, and the one that needs the CONVERSION rather than
    # just the exit: a non-empty string enters the body exactly once and the
    # assignment inside it makes it empty, so the loop stops on the second
    # test. A lowering that tested the address would never stop.
    ("truthy_while_runs_once_then_stops",
     "def main(n):\n"
     "    s = \"ab\"\n"
     "    i = 0\n"
     "    while s:\n"
     "        i = i + 1\n"
     "        s = \"\"\n"
     "    printf(\"i=%d\", i)\n"
     "    return 0\n", 0, "i=1"),
    # A ternary. Two lowerings for it on arm64 — a branch and a branchless
    # CSEL — and the CSEL one is chosen on a purity predicate, so BOTH spellings
    # are needed or a fix in the branch path is invisible.
    ("truthy_ternary_branch_form",
     "def main(n):\n"
     "    printf(\"%d\", 1 if \"\" else 0)\n"
     "    return 0\n", 0, "0"),
    ("truthy_ternary_branchless_form",
     "def main(n):\n"
     "    a = 1\n"
     "    b = 2\n"
     "    printf(\"%d %d\", a if \"\" else b, a if \"x\" else b)\n"
     "    return 0\n", 0, "2 1"),
    # `elif` is a second condition in the same chain and goes down a different
    # arm of the `if` emitter's loop.
    ("truthy_elif_chain",
     "def main(n):\n"
     "    if \"\":\n"
     "        printf(\"A\")\n"
     "    elif 1:\n"
     "        printf(\"B\")\n"
     "    else:\n"
     "        printf(\"C\")\n"
     "    return 0\n", 0, "B"),
    # A comprehension guard.
    ("truthy_comprehension_guard",
     "def main(n):\n"
     "    a = [1, 2, 3]\n"
     "    b = [x for x in a if x]\n"
     "    printf(\"%d\", len(b))\n"
     "    return 0\n", 0, "3"),
    # A short-circuit chain. The one that is NOT just the left operand: `and`/
    # `or` return an OPER operand, and the operand that survives can be the
    # empty string or the empty list, whose zeroness as a returned VALUE is the
    # address and not the answer. `f and e` with `e = []` printed 1 before this.
    ("truthy_and_or_selects_by_truthiness",
     "def main(n):\n"
     "    e = \"\"\n"
     "    s = \"a\"\n"
     "    printf(\"%d %d %d %d\", 1 if (e and s) else 0, 1 if (e or s) else 0,\n"
     "           1 if (s and e) else 0, 1 if (s or e) else 0)\n"
     "    return 0\n", 0, "0 1 0 1"),
    ("truthy_and_or_on_lists",
     "def main(n):\n"
     "    e = []\n"
     "    f = [1]\n"
     "    printf(\"%d %d %d %d\", 1 if (e and f) else 0, 1 if (e or f) else 0,\n"
     "           1 if (f and e) else 0, 1 if (f or e) else 0)\n"
     "    return 0\n", 0, "0 1 0 1"),
    ("truthy_and_or_chain_of_three",
     "def main(n):\n"
     "    a = \"\"\n"
     "    b = []\n"
     "    c = 0\n"
     "    d = \"z\"\n"
     "    printf(\"%d %d %d\", 1 if (a and b and c) else 0,\n"
     "           1 if (a or b or c) else 0, 1 if (a and b and c and d) else 0)\n"
     "    return 0\n", 0, "0 0 0"),
    # `assert` is a truthiness site on both backends, and it is where a
    # cross-architecture disagreement was found: x86-64 emitted `jcc fail`
    # immediately followed by `label fail`, so the branch had nothing to skip
    # and the FALL-THROUGH path went into exit(1). Every `assert` failed on
    # x86-64 and passed on arm64. Both halves are here — the true one (which
    # only x86-64 was getting wrong) and the false one (which must still fail).
    ("truthy_assert_true_survives",
     "def main(n):\n"
     "    k = 5\n"
     "    assert k\n"
     "    printf(\"passed\")\n"
     "    return 0\n", 0, "passed"),
    ("truthy_assert_false_fails",
     "def main(n):\n"
     "    assert 0\n"
     "    printf(\"passed\")\n"
     "    return 0\n", 1, None),
    ("truthy_assert_empty_string_fails",
     "def main(n):\n"
     "    e = \"\"\n"
     "    assert e\n"
     "    printf(\"passed\")\n"
     "    return 0\n", 1, None),

    # A slice of a string is a container operation on a bare `char *`: the
    # count is read from offset 0 of the pointer, which is the first eight
    # CHARACTERS. It SEGFAULTED on both backends (exit 139) rather than
    # answering wrongly, so this asserts a refusal instead of a crash — and the
    # needle is the count, because that is the step that is wrong.
    ("string_slice_refused",
     "def main(n):\n"
     "    s = \"abcde\"\n"
     "    t = s[1:]\n"
     "    printf(\"[%s]\", t)\n"
     "    return 0\n",
     "refuse:a slice of a string is refused", None),

    # GUARDS, not demonstrations: these pass on the pre-change tree too, and
    # they are here because a truthiness helper that "fixed" strings by
    # breaking the shape a string has is the failure mode worth pinning. `len`
    # is the same `strlen` the truthiness conversion makes, so a change to the
    # symbol or the call shape would show up in both.
    ("guard_len_of_a_string_is_still_strlen",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    e = \"\"\n"
     "    printf(\"%d %d\", len(s), len(e))\n"
     "    return 0\n", 0, "3 0"),
    ("guard_and_or_on_ints_still_returns_an_operand",
     "def main(n):\n"
     "    printf(\"%d %d\", 5 and 9, 0 or 9)\n"
     "    return 0\n", 0, "9 9"),
]


def build_formal(src, out, backend=None, tmpdir=None, env=None):
    """`fire.py build --formal --no-prove`, as a (returncode, output) pair.

    `env` is merged over this process's environment rather than replacing it,
    so a case can turn one backend switch off and leave PATH and HOME alone."""
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove", "-o", out]
    if backend:
        cmd.append(f"--backend={backend}")
    cmd.append(src)
    child = os.environ.copy()
    if env:
        child.update(env)
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE, env=child)
    return p.returncode, (p.stderr or p.stdout or "")


# Cases that must be REFUSED with the by-reference receiver switched OFF.
#
# The switch (`formal/model.py`'s `wide_receiver_by_reference`,
# `MOJO_FORMAL_WIDE_RECEIVER`) defaults ON, so the corresponding cases in CASES
# now build and run. These are the same sources with the switch off, and they
# exist because "the switch is off" is a claim about behaviour and a claim with
# no test behind it is a claim nobody has checked: if turning the switch off
# stopped refusing, the switch would not be a switch.
WIDE_OFF_CASES = [
    ("wide_off_pair_two_fields",
     "class Pair:\n"
     "    def __init__(self):\n"
     "        self.a = 1\n"
     "        self.b = 2\n\n"
     "    def total(self):\n"
     "        return self.a + self.b\n\n"
     "def main(n):\n"
     "    p = Pair()\n"
     "    return p.total()\n", "refuse:2 field(s): a, b", None),
    ("wide_off_point_ctor",
     "struct Point:\n"
     "    x: Int\n"
     "    y: Int\n\n"
     "def main(n):\n"
     "    p = Point()\n"
     "    return p.x + p.y\n",
     "refuse:constructing Point needs 2 field(s): x, y", None),
    ("wide_off_two_instance_alias",
     "struct Pair2:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    fn get_a(self):\n"
     "        return self.a\n"
     "    fn set_a(self, v):\n"
     "        self.a = v\n\n"
     "def main(n):\n"
     "    p = Pair2()\n"
     "    q = Pair2()\n"
     "    p.set_a(5)\n"
     "    return q.get_a()\n", "refuse:2 field(s): a, b", None),
]


def run_wide_off_case(name, source, needle, tmpdir, verbose):
    """The same refusal both backends gave before the by-reference receiver."""
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    env = {"MOJO_FORMAL_WIDE_RECEIVER": "0"}
    for backend in ("arm64", "x86_64"):
        rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.{backend}"),
                                backend=backend, env=env)
        if rc == 0:
            return False, (f"--backend={backend} BUILT it with the "
                           f"by-reference receiver switched off; the switch is "
                           f"not a switch")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not with the "
                           f"expected words {needle!r}: "
                           f"{text.strip()[-200:]}")
    if verbose:
        print(f"      refused identically with the switch off: {needle!r}")
    return True, ""


def run_case(name, source, want_exit, want_stdout, tmpdir, verbose):
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)

    # A `refuse:` case is the other half of what this suite is for. Every other
    # case here asks "does the binary compute the right answer"; these ask "does
    # a construct with no representation BUILD AND LIE, or does it say no" — and
    # the answer has to be the same on both backends, or the two architectures
    # are not one language implementation. Checked on both here because the
    # divergences were real in both directions: arm64 refusing what x86-64
    # emitted, and x86-64 emitting a `call _Point` that dyld killed at launch.
    if isinstance(want_exit, str) and want_exit.startswith("refuse:"):
        needle = want_exit[len("refuse:"):]
        for backend in ("arm64", "x86_64"):
            rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.{backend}"),
                                    backend=backend)
            if rc == 0:
                return False, (f"--backend={backend} BUILT a construct that has no "
                               f"representation (expected a refusal naming "
                               f"{needle!r}); the binary is the real answer here")
            if needle not in text:
                return False, (f"--backend={backend} refused, but not with the "
                               f"expected words {needle!r}: "
                               f"{text.strip()[-200:]}")
        if verbose:
            print(f"      refused identically on arm64 and x86-64: {needle!r}")
        return True, ""

    # `refuse_either:` is the same assertion with a weaker equality: each
    # backend must refuse, and each must name ONE OF the given reasons. It
    # exists for a construct where the two architectures refuse at DIFFERENT
    # depths, so the shared-text rule cannot apply and a common substring does
    # not exist — `del a[i, j]`, which arm64 refuses at the subscript and
    # x86-64 refuses at the statement, because it lowers no `del` at all. Both
    # are correct; the point the case is making is that neither BUILDS, and
    # `|` in the expectation separates the alternatives. Prefixed so it cannot
    # be mistaken for a single needle.
    if isinstance(want_exit, str) and want_exit.startswith("refuse_either:"):
        needles = want_exit[len("refuse_either:"):].split("|")
        for backend in ("arm64", "x86_64"):
            rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.{backend}"),
                                    backend=backend)
            if rc == 0:
                return False, (f"--backend={backend} BUILT a construct that has no "
                               f"representation (expected a refusal naming one of "
                               f"{needles!r}); the binary is the real answer here")
            if not any(n in text for n in needles):
                return False, (f"--backend={backend} refused, but not with any of "
                               f"{needles!r}: {text.strip()[-200:]}")
        if verbose:
            print(f"      refused on both, naming one of: {needles!r}")
        return True, ""

    # `refuse_without:` is the anti-rot direction for a REWORDING, and it is the
    # one assertion this suite was missing for the whole class of defect "a
    # refusal that says something false about the file". A `refuse:` case pins
    # that the right words are PRESENT, which a fix satisfies by APPENDING the
    # true sentence and leaving the false one in place — which is how "a formal
    # value is one 64-bit word, and DType is not one thing" survived beside a
    # corrected first clause. So the expectation here is
    # `refuse_without:<needle>[:<forbidden substring>]`: the build must fail,
    # must NOT contain `<forbidden substring>`, and — so the case still means
    # something if the message is replaced wholesale rather than appended to —
    # must still mention `<needle>`.
    #
    # Both halves are required. Without the forbidden-substring half a wholesale
    # rewrite passes; without the needle half, deleting the message altogether
    # passes. `|` separates forbidden substrings, as in `refuse_either:`.
    if isinstance(want_exit, str) and want_exit.startswith("refuse_without:"):
        spec = want_exit[len("refuse_without:"):]
        needle, _, forbidden = spec.partition(":")
        forbiddens = [f for f in forbidden.split("|") if f] or [needle]
        for backend in ("arm64", "x86_64"):
            rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.{backend}"),
                                    backend=backend)
            if rc == 0:
                return False, (f"--backend={backend} BUILT a construct that has no "
                               f"representation (expected a refusal that no longer "
                               f"says {forbiddens!r}); the binary is the real answer "
                               f"here")
            said = [f for f in forbiddens if f in text]
            if said:
                return False, (f"--backend={backend} still says {said!r} — the "
                               f"refusal asserts a fact that is not true of the "
                               f"file it is reported against: "
                               f"{text.strip()[-200:]}")
            if needle and needle not in text:
                return False, (f"--backend={backend} refused without the false "
                               f"wording, but also without naming {needle!r}, so "
                               f"the message may have been dropped rather than "
                               f"corrected: {text.strip()[-200:]}")
        if verbose:
            print(f"      refused on both, no longer saying {forbiddens!r}")
        return True, ""

    out = os.path.join(tmpdir, name)
    rc, text = build_formal(src, out)
    if rc != 0:
        return False, text.strip()[-300:]
    if not os.path.isfile(out):
        return False, "build reported success but wrote no binary"

    # The formal entry function's return value becomes the process exit status.
    run = subprocess.run([out], capture_output=True, text=True, timeout=RUN_TIMEOUT)
    if run.returncode != want_exit:
        return False, (f"exit status {run.returncode}, expected {want_exit}"
                       + (f"; stderr: {run.stderr.strip()[:120]}" if run.stderr.strip() else ""))
    if want_stdout is not None and want_stdout not in run.stdout:
        return False, f"stdout {run.stdout[:120]!r} does not contain {want_stdout!r}"
    if verbose:
        print(f"      stdout={run.stdout[:60]!r} exit={run.returncode}")
    return True, ""


# ── the POINTER VALUE MODEL (wave 6, F2) ────────────────────────────────────
#
# `bugs/FORMAL_pointer_value_model.md` is the long form; the model is
# `formal/model.py`'s `POINTER_TYPE_CTORS` / `POINTEE_WIDTHS` /
# `pointee_of_type_text` / `pointer_pointee` / `dereference_lowering`, and these
# are the cases that hold each decision in place.
#
# The shape every one of the answered cases uses is a PARAMETER annotated with
# its pointee, called with a string — and a string on this path is a `char *`,
# so a `Pointer[UInt8]` argument gets a real, known, NUL-terminated address to
# read.  That is what makes the expected answers checkable against Python
# (`struct.unpack` over `b"ABCDEFGH"`), and the expected values below are those.
POINTER_DEREF_CASES = [
    # A `UInt8` pointee: ONE byte.  This is the case D1 refused over, and the
    # reason the refusal cited it: an 8-byte load of a 1-byte object over-reads
    # by seven bytes, returns a plausible number assembled from the adjacent
    # bytes, and faults at a page edge.  With the pointee declared the load is
    # `LDRB W0, [X0]` / `movzbl (%rax), %eax`, and 'A' is 65 — the FIRST byte
    # and not the eight-byte word.
    ("deref_u8_is_one_byte",
     "def read8(p: Pointer[UInt8]) -> Int:\n"
     "    return Int(p.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    var v = read8(s)\n"
     "    if v == 65:\n"
     "        return 1\n"
     "    return 0\n", 1, None),
    # The width boundary on the other side, and the STRONGEST of these cases
    # because it reads the SAME address four ways in one program and asks the
    # four reads to disagree.  A one-word formal value cannot hold a 4-byte and
    # an 8-byte read of the same address at once unless the width really comes
    # from the pointee's declared type: 1 byte is 65, 2 is 16961, 4 is
    # 1145258561, 8 is 5208208757389214273 (all little-endian over
    # b"ABCDEFGH", i.e. `struct.unpack` of the same eight bytes).
    ("deref_four_widths_at_one_address",
     "def r1(p: Pointer[UInt8]) -> Int:\n"
     "    return Int(p.value())\n"
     "def r2(p: Pointer[UInt16]) -> Int:\n"
     "    return Int(p.value())\n"
     "def r4(p: Pointer[Int32]) -> Int:\n"
     "    return Int(p.unsafe_value())\n"
     "def r8(p: Pointer[Int64]) -> Int:\n"
     "    return Int(p.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    if r1(s) != 65:\n"
     "        return 10\n"
     "    if r2(s) != 16961:\n"
     "        return 11\n"
     "    if r4(s) != 1145258561:\n"
     "        return 12\n"
     "    if r8(s) != 5208208757389214273:\n"
     "        return 13\n"
     "    return 1\n", 1, None),
    # A 4-byte signed pointee.  `LDRSW` sign-extends: the top four bytes of
    # "ABCDEFGH" are 0x47464544, whose top bit is 0, so this cannot tell a
    # sign-extend from a zero-extend.  The GUARD for that is `deref_i8_signed`
    # below, which is the same distinction at one byte where it is visible.
    ("deref_i32_is_four_bytes",
     "def read32(p: Pointer[Int32]) -> Int:\n"
     "    return Int(p.unsafe_value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGHIJKL\"\n"
     "    var v = read32(s)\n"
     "    if v == 1145258561:\n"          # struct.unpack('<i', b'ABCD')
     "        return 1\n"
     "    return 0\n", 1, None),
    # A 2-byte pointee, which is the one width this case list does not get from
    # `deref_four_widths_at_one_address` reading it unsigned.
    ("deref_i16_is_two_bytes",
     "def r(p: Pointer[Int16]) -> Int:\n"
     "    return Int(p.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    if r(s) != 16961:\n"           # struct.unpack('<h', b'AB') == 16961
     "        return 1\n"
     "    return 0\n", 0, None),

    # A POINTER IN A FRAME FIELD.  `Two` has two fields, so its receiver is a
    # frame of slots and `h.p` is slot 1 — the shape every C-library pointer
    # wrapper in the corpus has (`self._data`, `self._ptr`).  This is the case the brief calls the frame-lifetime trap, and the
    # thing worth pinning is that a `Pointer[UInt8]` in a field is SAFE: the
    # word is an address to bytes with static storage duration, not a frame
    # address, so nothing here can outlive anything.  (The unsafe shape — a
    # `Pointer[SomeStruct]` in a field — is `deref_refuse_struct_pointee`.)
    #
    # arm64 only, and the reason is a PRE-EXISTING x86-64 bug recorded in
    # bugs/FORMAL_pointer_value_model.md: `h.p` on a one-field struct reads 0 on
    # x86-64 and the field's value on arm64, on the pre-change tree too.
    # `deref_field_1slot_x86_bug` is the case that pins THAT.
    ("deref_pointer_in_a_frame_field",
     "struct Two:\n"
     "    var tag: Int64\n"
     "    var p: Pointer[UInt8]\n"
     "def read_field(h: Two) -> Int:\n"
     "    return Int(h.p.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    var h = Two()\n"
     "    h.tag = 1\n"
     "    h.p = s\n"
     "    if read_field(h) == 65:\n"
     "        return 1\n"
     "    return 0\n", 1, None),
]

POINTER_DEREF_REFUSALS = [
    # A STRUCT pointee.  The derivation is RIGHT — a struct's value on this path
    # is a frame address, so the receiver already is the pointee, the same
    # identity `Pointer()` gives — and it is refused because nothing recognises
    # a name bound through a pointer as a frame holder, so `q.b` off the result
    # reads a word of nothing.  Measured with the identity emitted: 0 on both
    # architectures where the source says 22.  This is the frame-lifetime trap:
    # a `Pointer[SomeStruct]` IS a frame address, so letting one be dereferenced
    # without the holder analysis is a use-after-free wearing a pointer's
    # clothes.  The refusal says all of that, and the next step is one line in
    # `formal/build.py`'s holder fixpoint rather than a value-model change.
    ("deref_refuse_struct_pointee",
     "struct P3:\n"
     "    var a: Int64\n"
     "    var b: Int64\n"
     "    var c: Int64\n"
     "def read_field(p: Pointer[P3]) -> Int:\n"
     "    return Int(p.value().b)\n"
     "def main(n: Int) -> Int:\n"
     "    var t = P3()\n"
     "    t.b = 22\n"
     "    return read_field(t)\n",
     "refuse:a STRUCT, and a struct's value on this path is a frame ADDRESS", None),
    # A FLOAT pointee.  A formal value has no float kind distinct from an int
    # (the same absence that refuses `__mlir_bool__`), so a 4-byte float load
    # would put IEEE binary32 bits in a register the program then treats as an
    # integer — a wrong answer, not an approximation.
    ("deref_refuse_float_pointee",
     "def read_f(p: Pointer[Float32]) -> Int:\n"
     "    return Int(p.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    return read_f(s)\n",
     "refuse:this path has no float kind distinct from an int", None),
    # A BLOB pointee.  A list is a frame whose FIRST word is its count, so a
    # load at the address would answer with the LENGTH — a plausible number the
    # source never wrote, which is the outcome this table exists to prevent.
    ("deref_refuse_blob_pointee",
     "def read_l(p: Pointer[List[Int]]) -> Int:\n"
     "    return Int(p.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    return read_l(s)\n",
     "refuse:a list is a BLOB on this path", None),
    # A bare type PARAMETER as the pointee: `Pointer[T]`.  `T` is an identifier
    # so it reduces to a base name, and no base name is a WIDTH — which is the
    # unagreed direction, and D2's rule says an absent answer IS the answer.
    ("deref_refuse_type_parameter_pointee",
     "def read_t(p: Pointer[T]) -> Int:\n"
     "    return Int(p.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    return read_t(s)\n",
     "refuse:is not a width this model establishes and not a struct this image declares", None),
    # The corpus's OWN spelling of the same thing, and by a wide margin: of the
    # 60-odd `Pointer[…]` spellings in the stdlib, 149 occurrences are
    # `Pointer[Scalar[dtype]]` and 76 more are `Pointer[mut=True,
    # Scalar[dtype]]`.  `Scalar[dtype]` does not reduce to a single identifier
    # — `dtype` is itself a parameter — so it takes the other untyped branch and
    # gets the other message.  Both messages are the same fact ("the pointee's
    # value is not knowable here") reached two ways, and the pair pins that
    # neither is mistaken for a width.
    ("deref_refuse_scalar_pointee_of_unknown_arity",
     "def read_c(p: Pointer[Scalar[dtype]]) -> Int:\n"
     "    return Int(p.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    return read_c(s)\n",
     "refuse:the element count is not spelled as the literal 1", None),
    # The third untyped spelling, and the one that reaches the remaining
    # untyped branch: a QUALIFIED pointee that is not a `Self.` type-parameter
    # access.  `annotation_base_name` returns None for it on purpose —
    # `ref[self._data]` names the type OF a field and `some.module.Thing` names
    # nothing this unit declares, and returning the last component would look up
    # a struct named after a field.
    ("deref_refuse_qualified_pointee_type",
     "def read_q(p: Pointer[some.module.Thing]) -> Int:\n"
     "    return Int(p.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    return read_q(s)\n",
     "refuse:which is a type PARAMETER or a computed type rather than a type name", None),
    # A 4-byte load at a FRAME SLOT.  `t` is a two-field struct, so its receiver
    # is a frame address, and this path hands that address to a `Pointer[Int32]`
    # parameter as an ordinary word — which is what makes the signedness
    # observable at all, because the interned string bytes are all ASCII and no
    # byte >= 128 is producible on this path yet (see the bug doc).  The value
    # in the slot is -1, so the low four bytes are 0xFFFFFFFF and a signed read
    # must be -1 where a zero-extending one is 4294967295.
    ("deref_i32_at_a_frame_slot_sign_extends",
     "struct Two:\n"
     "    var x: Int64\n"
     "    var y: Int64\n"
     "def r(p: Pointer[Int32]) -> Int:\n"
     "    return Int(p.unsafe_value())\n"
     "def ru(p: Pointer[UInt32]) -> Int:\n"
     "    return Int(p.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var t = Two()\n"
     "    t.x = 0 - 1\n"
     "    if r(t) != 0 - 1:\n"
     "        return 1\n"
     "    if ru(t) != 4294967295:\n"
     "        return 2\n"
     "    return 0\n", 0, None),
    # AN UNDECLARED receiver: a parameter with no annotation.  This is the other
    # untyped direction, and it is the 14-of-47 `unsafe_value` case — a pointer
    # that crossed a call boundary and lost its pointee on the way.
    ("deref_refuse_undeclared_receiver",
     "def read_x(p) -> Int:\n"
     "    return Int(p.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    return read_x(s)\n",
     "refuse:it is a word from the caller and its pointee is not recorded here", None),
    # The OFFSET SCALE.  `p + k` on this path adds the raw integer, which is C
    # for a one-byte pointee and wrong for every other one, so a `Pointer[Int64]`
    # reached through arithmetic is refused rather than loaded at the wrong
    # address.  This is the one refusal whose fix is a lowering rather than a
    # model change, and it is recorded as the next step.
    ("deref_refuse_unscaled_offset",
     "def read_at(p: Pointer[Int64], k: Int) -> Int:\n"
     "    var q = p + k\n"
     "    return Int(q.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    return read_at(s, 1)\n",
     "refuse:WITHOUT scaling it by the pointee's size", None),
    # The SAME arithmetic on a ONE-BYTE pointee is ANSWERED, and this is the
    # guard for the refusal above: refusing the scale must refuse it because
    # the element is 8 bytes, not because the program mentions `+`.  This case
    # is a guard — it passes on the pre-change tree too, because there `value()`
    # on any receiver was refused and this program would not have built.  It is
    # listed here so that a future change which refuses ALL pointer arithmetic
    # fails a case rather than passing quietly.
    ("deref_offset_on_a_one_byte_pointee_is_the_answer",
     "def read_at(p: Pointer[UInt8], k: Int) -> Int:\n"
     "    var q = p + k\n"
     "    return Int(q.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    if read_at(s, 3) == 68:\n"       # 'D'
     "        return 1\n"
     "    return 0\n", 1, None),
    # `value` on a receiver that is NOT a pointer and not established as one.
    # This is the case the table split exists for: pre-change this refused with
    # "it is a load from the address the receiver holds", which is FALSE about
    # 527 of the 528 `value` sites in the stdlib (an enum's, an iterator's and a
    # `SIMD`'s `value()` is an identity, not a load).  The message now names the
    # four questions behind the one spelling.
    ("deref_refuse_value_is_not_always_a_dereference",
     "def main(n: Int) -> Int:\n"
     "    h = n\n"
     "    return h.value()\n",
     "refuse:is spelled the same for four different questions", None),
    # A method this path has no lowering for.  Two things are pinned here and
    # the second is the one that is easy to get wrong.
    #
    # First, the name is refused by the GENERIC value-method refusal, which is
    # where it belongs: `h.unicorn()` has no `how` in either table, so
    # `value_method_refusal` names both tables and says what the receiver
    # holds.  This is a guard — it behaved this way before this wave.
    #
    # Second, and the reason the case is here: `_emit_value_method`'s `else`
    # used to be `_emit_str_count(e)`, so a method that REACHED that arm was
    # answered by calling `str.count` on its receiver.  `count`'s own lowering
    # was that same `else`, so the arm meant two different things.  The visible
    # symptom, measured while landing the pointer value model, was a `value()`
    # newly made answerable reporting `str.count() takes exactly one argument
    # on this path (got 0)` — a reader would have gone looking for a counting
    # bug in a module with no counting in it.  `count` is now an explicit arm
    # and the `else` is a refusal that names the unclaimed `how`.  The evidence
    # that the fall-through is gone is `str_count` above, which passes; and the
    # evidence that it used to mis-report is the git history of this file.
    ("deref_refuse_unknown_method_names_both_tables",
     "def main(n: Int) -> Int:\n"
     "    h = n\n"
     "    return h.unicorn()\n",
     "refuse:is not one of those methods of those receivers", None),
]

# The x86-64 wrong answer this used to pin, and what replaced it.  A
# ONE-FIELD struct's receiver IS its field (`struct_is_framed`: "a one-field
# struct's receiver is its field, so it needs no frame"), and x86-64 did not
# read it that way: `h.v` returned 0 there and 4242 on arm64, on the pre-change
# tree, for the same source.  arm64 was right BY ACCIDENT — `h` is argument 0,
# so it is X19, and `_load_var`'s fall-through read X19; x86-64's fall-through
# read an immediate 0.  Reproduced on `git archive HEAD` with no diff applied.
# It is a member-read site in x86_64_codegen.py and NOT a dereference site, so
# it is out of the pointer value model's lane; it was recorded in
# bugs/FORMAL_pointer_value_model.md with the exact reproducers.
#
# Wave 6 (F1) closed it, and closed it the only way that does not pick a
# winner: a field access through a name bound as a PARAMETER has no layout on
# either architecture, so BOTH now refuse by name, from the same
# `model.field_access_refusal`, and the two architectures can no longer answer
# this program differently.  The case stays — as a refusal — because the
# divergence it recorded was real and its replacement is exactly the assertion
# that says so on both backends.
X86_ONLY_1SLOT_BUG_CASE = (
    "one_field_struct_field_read_is_correct_on_arm64",
    "struct One:\n"
    "    var v: Int64\n"
    "def raw(h: One) -> Int:\n"
    "    return Int(h.v)\n"
    "def main(n: Int) -> Int:\n"
    "    var o = One()\n"
    "    o.v = 4242\n"
    "    if raw(o) == 4242:\n"
    "        return 1\n"
    "    return 0\n",
    "refuse:is a field access through 'h', and this", None)


# ── WHERE A NAME LIVES: module scope, and how a call's arguments bind ──────
#
# `G = 5` at module level, read from a function, returned **20 on arm64 and 0
# on x86-64** where the source says 10 (5 * 2).  The two architectures
# disagreed about ONE PROGRAM, which is the failure this suite exists to
# catch, and the register-level cause is in the diff: `_extract_functions`
# takes only module-level FunctionDefs, so the assignment became NO CODE AT
# ALL, and the read fell through `_load_var` to whatever the allocator had left
# — X19, which is callee-saved and which the caller's own `test_input` (10)
# was sitting in, on arm64; an immediate `movq $0x0, %rax` on x86-64.
# `_store_var` had the same fall-through (`mov x19, src`), so a WRITE to a name
# the analysis did not know was a silent store into the register the next
# function reads as its first parameter.
#
# Every case below FAILED on the pre-change tree, each for the reason its
# comment gives, and each is checked on BOTH backends by `run_case`, so a
# divergence cannot come back.
WAVE6_NAME_CASES = [
    # THE headline.  `G` is written at module level and read from a function
    # that never touched it, which is the ordinary shape for a constant.  Was
    # 20 on arm64 and 0 on x86-64.
    ("modsym_global_read_from_a_function",
     "G = 5\n\n"
     "def read_g() -> Int:\n"
     "    return G\n\n"
     "def main() -> Int:\n"
     "    return read_g() * 2\n", 10, None),
    # A global MUTATED from a function.  In the language a function that
    # assigns the name binds its OWN local of that name, so this is not a
    # mutation of the module's value at all — which is exactly the premise
    # that lets a folded constant be substituted at every read site.  The
    # local is 7 and the constant is 5, so 12 is the only answer, and a
    # substitution blind enough to replace the LOCAL would return 10.
    ("modsym_a_local_shadows_the_module_name",
     "G = 5\n\n"
     "def f() -> Int:\n"
     "    var G = 7\n"
     "    return G\n\n"
     "def main() -> Int:\n"
     "    return f() + G\n", 12, None),
    # A global read BEFORE the function that would have computed it runs, and
    # a module-level binding whose value is literal-only arithmetic.  With a
    # folded value the order cannot matter, which is the point: 3*4 + (-2) is
    # 10 whatever ran first, and `helper()` adds 1.
    ("modsym_read_before_the_defining_function_runs",
     "LIM = 3 * 4\n"
     "NEG = -2\n\n"
     "def helper() -> Int:\n"
     "    return 1\n\n"
     "def read_first() -> Int:\n"
     "    return LIM + NEG\n\n"
     "def main() -> Int:\n"
     "    return read_first() + helper()\n", 11, None),
    # The half that needs STORAGE.  `G = compute()` is a real global: its
    # value is not known before the program runs, so it has to live somewhere
    # that outlives every frame, and every value a formal program can name
    # lives in a function's own stack scratch.  Refused BY NAME, and for THAT
    # reason — on the pre-change tree it read whatever register was left.
    ("modsym_refuse_a_global_the_build_cannot_fold",
     "G = compute()\n\n"
     "def compute() -> Int:\n"
     "    return 5\n\n"
     "def read_g() -> Int:\n"
     "    return G\n\n"
     "def main() -> Int:\n"
     "    return read_g() * 2\n",
     "refuse:is bound at module level, and this path has no module-global storage", None),
    # The other storage shape: an AUGMENTED assignment at module level.  The
    # value is `5 + 2` only after the program has started, so folding it would
    # be a guess about the order of two statements.
    ("modsym_refuse_a_module_level_augmented_assignment",
     "G = 5\n"
     "G += 2\n\n"
     "def main() -> Int:\n"
     "    return G\n",
     "refuse:is bound at module level, and this path has no module-global storage", None),
    # A module-level `comptime` that does not fold.  `comptime` inside a
    # FUNCTION is a compile-time value the backend materializes at its read,
    # and this is a guard for that (`limit_comptime_over_a_runtime_parameter`
    # above is the refusal of the same shape).  At MODULE level the binding is
    # not in scope in any function, so there is nothing for a read to consult
    # and the name must be refused rather than answered from a register.
    ("modsym_refuse_a_module_level_comptime_that_does_not_fold",
     "comptime N = len(3)\n\n"
     "def main() -> Int:\n"
     "    return N\n",
     "refuse:is a `comptime` binding declared at module level", None),
    # A call whose CALLEE this unit does not compile.  A callee is a SYMBOL,
    # not a read of a value, so the new name check must skip it: refusing it
    # would report a link-time fact in the grammar of a codegen gap, and a
    # GUARD in the sense that this program's own `G` is what the case is about.
    ("modsym_an_uncompiled_callee_is_a_symbol_not_a_read",
     "G = 5\n\n"
     "def not_compiled(x) -> Int:\n"
     "    return x\n\n"
     "def main() -> Int:\n"
     "    return G\n", 5, None),
    # ── *args / **kwargs ──
    # THE second headline.  `f(1, 2, r)` against `def f(x, *rest)`: `params`
    # recorded a flat list `['x', '*rest']`, so `rest` was parameter index 1
    # and index 2 had no parameter at all, and nothing looked.  The index
    # shape SEGFAULTED on both architectures before this change (measured on
    # `git archive HEAD`); `len(rest)` was refused by a different rule, which
    # is the accident E3 recorded — "safe today only because a two-element
    # list cannot be indexed at 2".
    ("vararg_refuse_a_read_of_star_args",
     "def f(x, *rest) -> Int:\n"
     "    return rest[2]\n\n"
     "def main() -> Int:\n"
     "    var r = 3\n"
     "    return f(1, 2, r)\n",
     "refuse:its *-parameter, and this path has no variadic ABI", None),
    # `**kwargs` read: the same absence, and the same refusal, for the other
    # star.  `kw["y"]` against `def f(x, **kw)` was a subscript through a name
    # with no home.
    ("vararg_refuse_a_read_of_double_star_kwargs",
     "def f(x, **kw) -> Int:\n"
     "    return kw[\"y\"]\n\n"
     "def main() -> Int:\n"
     "    return f(1, y=2)\n",
     "refuse:its **-parameter, and this path has no variadic ABI", None),
    # A variadic callee that never READS its variadic parameter.  The extra
    # arguments are dropped, which is exactly what the language observes, so
    # this is a GUARD: it behaved this way before this change and must keep
    # behaving this way, because it is what makes the refusal above about the
    # READ rather than about the declaration.
    ("vararg_a_declared_and_unread_star_args_still_runs",
     "def f(*args) -> Int:\n"
     "    return 7\n\n"
     "def main() -> Int:\n"
     "    return f(1, 2)\n", 7, None),
    # `**kwargs` the same way, with a keyword argument that has to be dropped
    # rather than bound.  1 + 40.
    ("vararg_a_declared_and_unread_double_star_kwargs_still_runs",
     "def f(x, **kw) -> Int:\n"
     "    return x + 40\n\n"
     "def main() -> Int:\n"
     "    return f(1, y=2, z=3)\n", 41, None),
    # ── the rest of the binding rule, which the flat list also got wrong ──
    # A DEFAULT argument the caller omits.  The callee's prologue gives `y` a
    # register home, the body only READS it, and so nothing ever wrote it.  The
    # source says 14.  Measured on `git archive HEAD` with no diff, EIGHT
    # CONSECUTIVE BUILDS AND RUNS PER ARCHITECTURE:
    #
    #       arm64   76 76 76 76 76 76 84 84
    #       x86-64  84 76 76 76 76 84 76 76
    #
    # which is the sharpest form of the register-allocation accident this suite
    # has found: the same program, rebuilt, answers DIFFERENTLY, and never 14.
    # After the change, eight builds and runs per architecture: 14 every time.
    # The old comment said "trailing optional parameters the caller omitted are
    # dropped — the callee's prologue only consumes the registers actually
    # passed", and the second half of that was the bug: it consumes ALL of
    # them, it only WRITES the ones it is passed.
    ("binding_a_default_argument_is_passed_not_dropped",
     "def f(x, y=10) -> Int:\n"
     "    return x + y\n\n"
     "def main() -> Int:\n"
     "    return f(1) + f(1, 2)\n", 14, None),
    # Too many positional arguments, no variadic to absorb them.  `f(1, 2, 3)`
    # against `def f(x, y)` bound `y` to 2 and said nothing, where the
    # language says a TypeError.  The arity check only ever ran when the call
    # had a keyword argument, because both copies began with
    # `if not e.kwargs: return list(e.args)`.
    ("binding_refuse_too_many_positional_arguments",
     "def f(x, y) -> Int:\n"
     "    return y\n\n"
     "def main() -> Int:\n"
     "    return f(1, 2, 3)\n",
     "refuse:too many positional arguments", None),
    # A KEYWORD-ONLY parameter reached by position.  `def f(a, *, b)` puts `b`
    # in the flat parameter list at index 1, so `f(1, 2)` bound the 2 to `b`
    # and returned 3; the language says a positional argument cannot fill `b`.
    ("binding_refuse_a_positional_for_a_keyword_only_parameter",
     "def f(a, *, b) -> Int:\n"
     "    return a + b\n\n"
     "def main() -> Int:\n"
     "    return f(1, 2)\n",
     "refuse:too many positional arguments", None),
    # ── the field-access shape the fall-throughs were answering ──
    # `b.z = 1` with `b` a bare parameter.  arm64's `_store_var` had no slot
    # and fell through to `mov x19, src`; x86-64's `AssignStmt` evaluated both
    # sides and RETURNED, discarding the store.  One is a wrong store and one
    # is a dropped store, and neither is a wrong VALUE — which is why no case
    # that only checked a return value ever noticed.  `main` returns 0 either
    # way, so the EXIT STATUS cannot witness this one (0 before, 0 after) and
    # the assertion is the REFUSAL: the store used to be silently absent, and
    # only the refusal distinguishes "discarded" from "never reached".
    ("field_refuse_a_store_through_a_parameter",
     "struct B2:\n"
     "    var z: Int\n\n"
     "def touch(b) -> Int:\n"
     "    b.z = 1\n"
     "    return 0\n\n"
     "def main() -> Int:\n"
     "    return 0\n",
     "refuse:is a field access through 'b'", None),
    # The READ half of the same shape, which is the arm64/x86-64 divergence
    # F2 documented: `h.v` through a parameter returned 4242 on arm64 (X19,
    # because `h` IS argument 0) and 0 on x86-64.  `X86_ONLY_1SLOT_BUG_CASE`
    # above is the same program converted to a refusal; this one is here
    # because the read and the store are two branches and a fix to one is not
    # a fix to the other.
    ("field_refuse_a_read_through_a_parameter",
     "struct One2:\n"
     "    var v: Int64\n\n"
     "def raw(h) -> Int:\n"
     "    return Int(h.v)\n\n"
     "def main() -> Int:\n"
     "    var o = One2()\n"
     "    o.v = 4242\n"
     "    return raw(o)\n",
     "refuse:is a field access through 'h'", None),
    # An MLIR dialect construct the TEMPLATE rules do not cover, so the name
    # check reached it and refused it as "no home" — a symptom of the register
    # fall-through, naming the allocator rather than the construct.  Real
    # stdlib source spells it exactly this way (`std/builtin/value.mojo:203`,
    # `std/sys/debug.mojo:20`).
    ("mlir_dialect_name_is_refused_by_construct",
     "def materialize(value) -> Int:\n"
     "    return __mlir_op.`lit.materialize_into`[value=value](value)\n\n"
     "def main() -> Int:\n"
     "    return materialize(1)\n",
     "refuse:is an MLIR dialect construct", None),
]


# ── WAVE 7 / G2: a builtin that wants a VALUE, handed a frame ──────────────
#
# The audit this block is the evidence for.  Every builtin and value method
# that reads or writes its operand was run against a frame-address receiver on
# both architectures; the table is in the commit message.  Nothing in that audit
# was ACCEPTED wrongly, which is a result and not an accident, and the two
# things this block pins are the two things the audit DID find:
#
#   1. a FRAME SLOT's declared type was not connected to anything.  A field read
#      is not a name the function bound, so `len(self.<field>)` was asked for a
#      kind it had no way to know and refused with "the source does not say what
#      this operand holds … Annotate it (`x: String`)" — FALSE about a declared
#      field, and for a list or string field the refusal was of something this
#      path can answer.  Four of the cases below are that, one per declared type
#      the model has a representation for;
#   2. a kind taken from the declaration ALONE is a wrong answer, not a
#      conservative one.  `S()` does not run `__init__` (premise (B2)), so a
#      fresh instance's slot holds the class-level default and a field with no
#      default is a word of zeros: with the kind claimed, `len(self.xs)` for
#      `var xs: List[Int]` and `len(self.s)` for `var s: String` both BUILT, RAN
#      and died with SIGSEGV (exit 139) on BOTH architectures — `LDR X0, [X0]`
#      with X0 zero, and a `BL _strlen` walking the bytes at address 0.  So the
#      kind is gated on the default being a LITERAL the constructor
#      materializes, and the two refusals below name the premise rather than
#      the annotation.  `len_string_literal_default_field` is the other half: a
#      literal default IS materialized, so that one is ANSWERED, and it did not
#      build before.
#
# Every `refuse:` case is checked on BOTH backends by `run_case` with the SAME
# words, so a divergence between the architectures cannot come back either.
WAVE7_G2_CASES = [
    # ── (1) the four declared types a frame slot can have ──
    # A CONTAINER field.  Refused, and the reason is premise (B2) rather than
    # the annotation: the annotation settles the lowering (a list's length is
    # the count word at offset 0) and what is missing is the VALUE.  Pre-change
    # this said "the source does not say what this operand holds" and told the
    # reader to annotate a field that says `List[Int]` two lines above.
    ("len_frame_slot_declared_container",
     "struct R:\n"
     "    var xs: List[Int]\n"
     "    var n: Int\n"
     "    def __init__(out self):\n"
     "        self.xs = [1, 2, 3]\n"
     "        self.n = 0\n"
     "    def size(self) -> Int:\n"
     "        return len(self.xs)\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    return r.size()\n",
     "refuse:this slot's DECLARED type is 'List[Int]'", None),
    # A STRING field.  The same premise and a DIFFERENT wrong answer, which is
    # why it is a separate case: `strlen` does not read eight bytes and call
    # them a count, it walks the bytes at address 0 looking for a terminator,
    # so the fault is inside libc rather than one instruction after the load.
    ("len_frame_slot_declared_string",
     "struct R:\n"
     "    var s: String\n"
     "    var n: Int\n"
     "    def __init__(out self):\n"
     "        self.s = \"hello\"\n"
     "        self.n = 0\n"
     "    def size(self) -> Int:\n"
     "        return len(self.s)\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    return r.size()\n",
     "refuse:a string's length is a `strlen` over its bytes", None),
    # An INT field.  Here the missing value is NOT what stops the lowering — an
    # integer has no length either way — so this is the integer row plus the
    # one fact it cannot know, that the number in the slot is the default.
    ("len_frame_slot_declared_int",
     "struct R:\n"
     "    var n: Int\n"
     "    var m: Int\n"
     "    def __init__(out self):\n"
     "        self.n = 5\n"
     "        self.m = 0\n"
     "    def size(self) -> Int:\n"
     "        return len(self.n)\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    return r.size()\n",
     "refuse:this slot's DECLARED type is 'Int', and an integer has no length",
     None),
    # A field whose declared type is a struct of this module whose receiver is
    # a frame.  The slot holds the ADDRESS of a frame of 8-byte slots, and
    # `FRAME_KIND` is what says so — which is the case whose refusal reason was
    # most worth its own sentence, because offset 0 of a frame is the struct's
    # FIRST FIELD and `len` over it returns a plausible number meaning nothing.
    # Pre-change this was filed under "the source does not say".
    # `Outer.__init__` stores a WORD and leaves `inner` alone.  It used to store
    # `self.inner = Inner()` — a construction of a FRAMED struct in a
    # constructor's right-hand side — and `Outer()` never ran that body (premise
    # (B2) as it was then worded), so the store was dead code that happened to
    # compile.  `S()` on a struct whose `__init__` takes no required parameter
    # RUNS the body now, and a nested frame construction in it is refused by name
    # — the message here says the same thing, which is why the program is
    # written the recommended way instead: `inner` is a PLACED nested frame, so
    # `Outer()` brings it up without the constructor mentioning it, and `go`
    # reaches exactly the `len()` of a frame address this case is about.
    ("len_frame_slot_is_a_frame_address",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def __init__(out self):\n"
     "        self.a = 1\n"
     "        self.b = 2\n"
     "struct Outer:\n"
     "    var inner: Inner\n"
     "    var n: Int\n"
     "    def __init__(out self):\n"
     "        self.n = 5\n"
     "    def go(self) -> Int:\n"
     "        return len(self.inner)\n"
     "def main(k: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    return o.go()\n",
     "refuse:is len() of a FRAME ADDRESS", None),
    # ── (2) the two shapes a ONE-WORD struct's receiver takes ──
    # `self.<field>` was rewritten to `self` long before the emitter runs,
    # because a single-field struct's receiver IS its field.  So the operand
    # here is a bare `self` and the declared type has to be recovered from the
    # struct's one field.
    #
    # NOT the shape `std/collections/binary_heap.mojo` is in, which is what
    # this comment used to say: `BinaryHeap` has TWO fields here, because its
    # comptime parameter `T` is in `struct_field_names` and `struct_is_framed`
    # counts it, so `BinaryHeap` is a frame and its `len(self)` is the
    # `__len__` call `formal/build.py`'s `_rewrite_len_on_frame_receivers` now
    # makes (see `bugs/FORMAL_frame_receiver_handoff.md` §14).  A one-field
    # struct is not a frame, `b` below is a plain word, and the `__len__` on it
    # is not reached at all — which is why this case still refuses, for the
    # field-value reason and not for a length reason.
    ("len_one_word_struct_receiver_is_a_list_field",
     "struct B:\n"
     "    var _data: List[Int]\n"
     "    def __len__(self) -> Int:\n"
     "        return len(self._data)\n"
     "    def __init__(out self):\n"
     "        self._data = [1, 2, 3]\n"
     "def main(k: Int) -> Int:\n"
     "    var b = B()\n"
     "    return len(b)\n",
     "refuse:this slot's DECLARED type is 'List[Int]'", None),
    # The same one-word struct, read through a LOCAL the constructor was bound
    # to rather than through the receiver.  `b` is a plain word on this path —
    # deliberately not a frame holder, because a one-field struct has no frame —
    # so nothing but the binding says what it holds.
    ("len_local_bound_to_a_one_word_struct_ctor",
     "struct B:\n"
     "    var _data: List[Int]\n"
     "    def __init__(out self):\n"
     "        self._data = [1, 2, 3]\n"
     "def main(k: Int) -> Int:\n"
     "    var b = B()\n"
     "    return len(b)\n",
     "refuse:this slot's DECLARED type is 'List[Int]'", None),
    # ── (3) the case that is ANSWERED, and is the whole point of the gate ──
    # A LITERAL class-level default IS materialized by the constructor at every
    # construction site, so the slot's value is established and `len` is the
    # `strlen` it always was.  This did not build before the change: the field
    # was unclassified, so `len(self.s)` was refused with "the source does not
    # say what this operand holds" about a field that says `String = "hello"`.
    # 5 on both architectures, and the string methods on the same slot come
    # with it (`startswith` is the second half of this case's shape).
    ("len_string_literal_default_field",
     "struct R:\n"
     "    var s: String = \"hello\"\n"
     "    var n: Int = 7\n"
     "    def size(self) -> Int:\n"
     "        return len(self.s)\n"
     "    def pre(self) -> Int:\n"
     "        if self.s.startswith(\"he\"):\n"
     "            return 1\n"
     "        return 0\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    return r.size() + r.pre()\n",
     6, None),
    # GUARD (passes before and after), and it is here because it is the case
    # that would have caught a wrong ACCEPTANCE rather than a wrong refusal:
    # `printf("%d", self.n)` on a field with a literal default prints 7, which
    # is what the source says.  It passes pre-change because `printf` of a
    # MemberExpr does not consult the kind at all, so the field being
    # unclassified cost nothing here — which is exactly why it cannot be
    # presented as a demonstration.  What it pins is the gate: a field with NO
    # default is a different program (the slot holds 0) and is the refusal
    # above, so this pair is what stops "every declared field is answered"
    # from being a way of making that one print 0.
    ("int_literal_default_field_prints_its_value",
     "struct R:\n"
     "    var n: Int = 7\n"
     "    var m: Int\n"
     "    def show(self) -> Int:\n"
     "        printf(\"%d\\n\", self.n)\n"
     "        return 0\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.show()\n"
     "    return 0\n",
     0, "7"),
    # ── (4) the C-library hand-off sets, audited by PROTOTYPE ──
    # `open(const char *, int, ...)` takes a path and a flag word; it does not
    # read the struct's storage, and it never mentions a struct.  This set used
    # to be the "reads the struct's BYTES" one, so the refusal told the reader
    # to go and compare a field list against the C headers' padding for a
    # struct the callee does not have.  `close`, `read`, `write`, `readv`,
    # `writev`, `ioctl`, `fcntl` and `mmap` are the same shape and the same
    # reason; `stat`/`lstat`/`fstat`/`memcpy`/`memcmp`/`qsort` are the ones that
    # genuinely take a pointer to the struct, and the next case is the guard
    # that says so.
    ("c_call_open_takes_a_value_not_the_structs_bytes",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def __init__(out self):\n"
     "        self.a = 3\n"
     "        self.b = 4\n"
     "def f(open) -> Int:\n"
     "    return 0\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    n = open(r, 1)\n"
     "    return 0\n",
     "refuse:takes a VALUE of a type its own prototype names", None),
    # GUARD (passes before and after): the storage half of the same table.  If
    # the set had been emptied rather than corrected, `stat` would get the
    # value sentence and this case would stop failing.
    ("c_call_stat_reads_the_structs_bytes",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def __init__(out self):\n"
     "        self.a = 3\n"
     "        self.b = 4\n"
     "def f(stat) -> Int:\n"
     "    return 0\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    n = stat(r)\n"
     "    return 0\n",
     "refuse:reads the struct's BYTES", None),
    # ── (5) GUARDS: the `len` receiver matrix, one row per operand kind ──
    # A STRING: `strlen`, the row that has always worked.
    ("guard_len_on_a_string",
     "def main(k: Int) -> Int:\n"
     "    var s: String = \"hello\"\n"
     "    return len(s)\n", 5, None),
    # A BLOB: the count field at offset 0.
    ("guard_len_on_a_blob",
     "def main(k: Int) -> Int:\n"
     "    var xs = [1, 2, 3]\n"
     "    return len(xs)\n", 3, None),
    # An INT: refused, with the integer row.
    ("guard_len_on_an_int",
     "def main(k: Int) -> Int:\n"
     "    n = 5\n"
     "    return len(n)\n",
     "refuse:an integer has no length", None),
    # A FRAME ADDRESS as a bare name: refused by the hand-off check, and the
    # reason it gives is the value/bytes one rather than "no definition in
    # hand".  This is the 30-file `binary_heap.mojo` refusal, in miniature.
    #
    # RE-POINTED for the same reason as `byref_refuse_receiver_to_a_builtin`:
    # the same program with a `__len__` on the struct now BUILDS and computes
    # the right answer, so what is left to refuse here is specifically "this
    # struct declares no `__len__`", and the needle says that rather than the
    # category claim it used to.
    ("guard_len_on_a_frame_address",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def __init__(out self):\n"
     "        self.a = 3\n"
     "        self.b = 4\n"
     "def f(len) -> Int:\n"
     "    return 0\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    n = len(r)\n"
     "    return 0\n",
     "refuse:declares no `__len__`", None),
    # ── (6) GUARDS: the value-method receiver matrix ──
    # A string method against each of the four operand kinds.  Two of these are
    # the wrong answer rather than a crash if they were lowered kind-blind: on a
    # BLOB receiver the bytes at the blob's offset 0 are the COUNT and the
    # string method would scan them as text, and on an INT receiver the word is
    # the integer and libc would walk whatever it points at.
    ("guard_string_method_on_a_blob",
     "def main(k: Int) -> Int:\n"
     "    var xs = [1, 2, 3]\n"
     "    if xs.startswith(\"a\"):\n"
     "        return 1\n"
     "    return 0\n",
     "refuse:its receiver is classified as 'list:int' rather than a string",
     None),
    ("guard_string_method_on_an_int",
     "def main(k: Int) -> Int:\n"
     "    n = 5\n"
     "    if n.startswith(\"a\"):\n"
     "        return 1\n"
     "    return 0\n",
     "refuse:its receiver is classified as 'int' rather than a string", None),
    # `write` against a frame address: the `VALUE_METHOD_RECEIVERS` guard, and
    # the case wave 4 found by RUNNING it — `s.write("x")` passed a __TEXT
    # address as fd(2), the syscall returned EBADF, nothing checked it, and the
    # program exited 0 with its output missing.  Same class, frame address.
    ("guard_write_on_a_frame_address",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def __init__(out self):\n"
     "        self.a = 3\n"
     "        self.b = 4\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.write(\"x\")\n"
     "    return 0\n",
     "refuse:its receiver has to be a file descriptor", None),
    # `Pointer(to=stat)` over a frame address is the one hand-off in this family
    # that is simply CORRECT — it is an identity address constructor, so what
    # arrives is the answer rather than the mistake.  D4 found this table
    # already wrong once (`Pointer` sat in the value-only set and its text said
    # the callee "wants the object itself"), so the row that removed it needs
    # a test: this builds and runs 0 on both architectures.
    ("guard_pointer_over_a_frame_address_is_correct",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def __init__(out self):\n"
     "        self.a = 3\n"
     "        self.b = 4\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    var p = Pointer(to=r)\n"
     "    return 0\n", 0, None),
    # `write_string` on a frame address: the WRITER_METHODS row, which exists
    # because `write_string` is the most tempting name in the tree to add next
    # to the `write` that IS lowered, and adding it would pass a frame address
    # as fd(2).
    ("guard_write_string_on_a_frame_address",
     "struct W:\n"
     "    var buf: Int\n"
     "    var n: Int\n"
     "    def __init__(out self):\n"
     "        self.buf = 0\n"
     "        self.n = 0\n"
     "def main(k: Int) -> Int:\n"
     "    var w = W()\n"
     "    w.write_string(\"None\")\n"
     "    return 0\n",
     "refuse:is a method on a Writer", None),
    # ── (7) the CONTAINER family, which is where the audit's one wrong
    # acceptance was ──
    #
    # `len` asks its operand what it is; a SUBSCRIPT, a SLICE, a membership
    # test and a `for` loop do not — they emit the blob walk, which reads eight
    # bytes at offset 0 and calls the result a count.  Handed a bare name the
    # frame-holder analysis holds to be a frame ADDRESS, every one of them
    # computed on a frame.  Measured on BOTH architectures, on a four-field
    # struct whose fields running statements had written 11, 22, 33, 44:
    #
    #     return r[0]                 ->  22   (the SECOND field)
    #     return r[1]                 ->  33   (the THIRD field)
    #     var t = r[0:2]; return 0    ->  arm64 exit 1, x86-64 exit 0
    #     for i in r: s = s + i       ->  arm64 99, x86-64 53
    #
    # Four shapes, three distinct wrong answers, and two of them DISAGREEING
    # between the architectures.  Which field an index reaches is decided by the
    # VALUES in the frame rather than by the index, because the bounds check
    # compared the index against a field's value.  The four cases below are one
    # per shape; each is checked on both backends with the same words, which is
    # the assertion that matters most here, because two of the four wrong
    # answers were the two architectures disagreeing.
    ("frame_address_subscript_read",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "    var d: Int\n"
     "    def __init__(out self):\n"
     "        self.a = 11\n"
     "        self.b = 22\n"
     "        self.c = 33\n"
     "        self.d = 44\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 11\n"
     "    r.b = 22\n"
     "    r.c = 33\n"
     "    r.d = 44\n"
     "    i = 1\n"
     "    return r[i]\n",
     "refuse:is a CONTAINER operation on a R FRAME ADDRESS", None),
    # The STORE, which is the same address computation reached from
    # `_emit_subscript_store_reg` — and `r[0] = 7` returned 11 here, i.e. it
    # wrote through a frame as though the frame were a blob's element area.
    ("frame_address_subscript_store",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "    var d: Int\n"
     "    def __init__(out self):\n"
     "        self.a = 11\n"
     "        self.b = 22\n"
     "        self.c = 33\n"
     "        self.d = 44\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 11\n"
     "    r.b = 22\n"
     "    r.c = 33\n"
     "    r.d = 44\n"
     "    r[0] = 7\n"
     "    return r.a\n",
     "refuse:is a CONTAINER operation on a R FRAME ADDRESS", None),
    ("frame_address_slice",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "    var d: Int\n"
     "    def __init__(out self):\n"
     "        self.a = 11\n"
     "        self.b = 22\n"
     "        self.c = 33\n"
     "        self.d = 44\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 11\n"
     "    r.b = 22\n"
     "    r.c = 33\n"
     "    r.d = 44\n"
     "    var t = r[0:2]\n"
     "    return 0\n",
     "refuse:is a CONTAINER operation on a R FRAME ADDRESS", None),
    ("frame_address_membership_test",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "    var d: Int\n"
     "    def __init__(out self):\n"
     "        self.a = 11\n"
     "        self.b = 22\n"
     "        self.c = 33\n"
     "        self.d = 44\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 11\n"
     "    r.b = 22\n"
     "    r.c = 33\n"
     "    r.d = 44\n"
     "    if 22 in r:\n"
     "        return 1\n"
     "    return 0\n",
     "refuse:is a CONTAINER operation on a R FRAME ADDRESS", None),
    # The `for` loop, which is the one that produced a plain wrong NUMBER on
    # both architectures and a DIFFERENT one on each: 99 and 53 for the same
    # source.  A struct is not iterable, so there is no right answer to
    # compare against, which is exactly what makes this shape the worst of the
    # four — nothing downstream could have detected it.
    ("frame_address_for_in_iteration",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "    var d: Int\n"
     "    def __init__(out self):\n"
     "        self.a = 11\n"
     "        self.b = 22\n"
     "        self.c = 33\n"
     "        self.d = 44\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 11\n"
     "    r.b = 22\n"
     "    r.c = 33\n"
     "    r.d = 44\n"
     "    s = 0\n"
     "    for i in r:\n"
     "        s = s + i\n"
     "    return s\n",
     "refuse:is a CONTAINER operation on a R FRAME ADDRESS", None),
    # GUARD: the same operations on a real blob, so the new refusal cannot be
    # "everything is refused now".  A list of 11, 22, 33: `xs[1]` is 22, the
    # sum of a three-element iteration is 66, and `22 in xs` is TRUE, so the
    # answer is 22 + 66.
    #
    # The SLICE is deliberately NOT in this case, and the reason is a separate
    # pre-existing bug that is not this one and is not fixed here: EVERY arm64
    # slice of a list exits 1, on every bound spelling measured (`xs[0:2]`,
    # `xs[0:3]`, `xs[1:3]`, `xs[0:1]`, `xs[1:2]`, `xs[:]`, `xs[1:]`), while
    # x86-64 returns 0 for all seven.  A two-architecture divergence on a
    # legitimate program, verified identical on a clean `git archive HEAD`
    # tree, in `_emit_slice_parts`'s element-append bounds path.  It is a
    # container lowering bug on a BLOB, not a frame-address one, so folding it
    # in here would make this case fail for a reason that has nothing to do
    # with what it is guarding.
    ("guard_container_ops_on_a_real_blob",
     "def main(k: Int) -> Int:\n"
     "    var xs = [11, 22, 33]\n"
     "    s = 0\n"
     "    for i in xs:\n"
     "        s = s + i\n"
     "    if 22 in xs:\n"
     "        return xs[1] + s\n"
     "    return 0\n", 88, None),
    # GUARD: a container operation on a FRAME SLOT whose declared type is a
    # list.  `h.xs` is a 64-bit FIELD, not an address, so the blob reading of
    # it is the only reading there is — this is the distinction the refusal
    # turns on, and `struct_frame_representable` refuses a container DEFAULT,
    # so the field is given its value by a running statement here.
    ("guard_container_op_on_a_declared_list_field",
     "struct H:\n"
     "    var xs: List[Int]\n"
     "    var n: Int\n"
     "    def __init__(out self):\n"
     "        self.n = 0\n"
     "    def at(self, i: Int) -> Int:\n"
     "        return self.xs[i]\n"
     "    def size(self) -> Int:\n"
     "        s = 0\n"
     "        for i in self.xs:\n"
     "            s = s + i\n"
     "        return s\n"
     "def main(k: Int) -> Int:\n"
     "    var h = H()\n"
     "    h.xs = [11, 22, 33]\n"
     "    return h.at(1) + h.size()\n", 88, None),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is {platform.machine()}")
        return 0

    everything = (CASES + RECVKIND_CASES + FD_CASES + BYREF_CASES
                  + BYREF_REFUSALS + WIDE_OFF_CASES
                  + SUBSCRIPT_CASES + DECLARED_TYPE_CASES
                  + DECLARED_TYPE_REFUSALS
                  + BYREF_HANDOFF_CASES + BYREF_HANDOFF_REFUSALS
                  + CROSS_MODULE_CASES + WAVE5_POSITION_CASES
                  + CONSTRUCTION_CASES + CONSTRUCTION_REFUSALS
                  + POINTER_DEREF_CASES + POINTER_DEREF_REFUSALS
                  + WAVE6_TRUTHY_CASES
                  + WAVE6_NAME_CASES + WAVE7_G2_CASES
                  + [X86_ONLY_1SLOT_BUG_CASE])
    selected = [c for c in everything if not args.cases or c[0] in args.cases]
    known = {c[0] for c in everything}
    if args.cases and len(selected) != len(args.cases):
        missing = set(args.cases) - known
        print(f"ERROR: unknown case(s): {sorted(missing)}", file=sys.stderr)
        return 2
    off_names = {c[0] for c in WIDE_OFF_CASES}
    module_names = {c[0] for c in CROSS_MODULE_CASES}

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, source, want_exit, want_stdout in selected:
            try:
                if name in off_names:
                    ok, detail = run_wide_off_case(
                        name, source, want_exit[len("refuse:"):], tmpdir,
                        args.verbose)
                elif name in module_names:
                    ok, detail = run_module_case(
                        name, source, want_exit, want_stdout, tmpdir,
                        args.verbose)
                else:
                    ok, detail = run_case(name, source, want_exit, want_stdout,
                                          tmpdir, args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:  # unexpected: report, do not mask
                ok, detail = False, f"{type(e).__name__}: {e}"
                if args.verbose:
                    import traceback
                    traceback.print_exc()
            if ok:
                passed += 1
                label = (want_exit
                         if not isinstance(want_exit, str) else
                         want_exit[len("refuse:"):]
                         if want_exit.startswith("refuse:") else
                         want_exit[len("refuse_either:"):])
                print(f"  PASS  {name} ({label})")
            else:
                failed += 1
                print(f"  FAIL  {name}: {detail}")

    print(f"\nformal run: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
