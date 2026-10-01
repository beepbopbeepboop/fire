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
    # `-> str` ON `get` IS LOAD-BEARING, and it was not before. `c.get() ==
    # "hi"` used to reach the content compare because the RIGHT side is a
    # string and `string_comparison_lowering` answers for either side being one
    # — and it was RIGHT by accident, because the field's default happens to be
    # an interned `char *`. `model.string_compare_number_refusal` now refuses a
    # comparison where exactly one side is classified a string, because
    # `strcmp` dereferences both and the unclassified side is not known to be an
    # address; a method that does not say what it returns is exactly that case.
    # The annotation is the fix the refusal names, and it is also what the
    # program should have said all along.
    ("struct_default_word_string", "struct Name:\n"
                                  "    text = \"hi\"\n\n"
                                  "    def get(self) -> str:\n"
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
    # and `String()` (zero operands) is refused as if it were a two-operand
    # conversion.
    #
    # A fifth entry was here until 2026-09-30 — `__mlir_op.`…`[n]` "builds and
    # segfaults" — and it was TRUE when written (bugs/FORMAL_known_limits.md
    # §2.2 measured exit 139 on both architectures) and stopped being true
    # before this note was corrected. It is now refused by
    # `model.mlir_dialect_refusal` on both, and is pinned where the refusal
    # itself is what is under test:
    # `a_bare_dialect_operation_is_refused_rather_than_built` in
    # test_formal_mlir_precedence.py.

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
    #
    # It still refuses, and the reason it gives is now the SHARPEST statement
    # in the family. It stopped saying "there is no MLIR on this path for the
    # template to become" on 2026-09-29, and that was a false claim about the
    # file: the same `current_target`, queried one step further
    # (`target_get_field<current_target, "arch">`), now BUILDS and prints
    # `aarch64`, because a formal image is compiled for one target and that
    # question has one right answer. So the needle is the part that is still
    # true — the target has no VALUE on this path — and the case that proves
    # the split is `sub_multi_index_mlir_template` above.
    ("limit_mlir_template_dotted_spelling",
     "def main(n: Int) -> Int:\n"
     "    var t = __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`\n"
     "    return n\n",
     "refuse:asks for the current TARGET itself, which is not a value", None),
    # The single-element bracket: `__mlir_type[x]` is a template exactly as
    # `__mlir_type[x, y]` is, and the comma was the only thing that made the
    # difference visible. `__mlir_type` names a TYPE rather than an attribute,
    # and the message says so — it used to call it an attribute, which is
    # false of `std/sys/info.mojo`'s `_TargetType` and of every other
    # `__mlir_type` binding in the stdlib.
    ("limit_mlir_template_single_element_bracket",
     "def main(n: Int) -> Int:\n"
     "    var t = __mlir_type[`!kgen.never`]\n"
     "    return n\n",
     "refuse:names an MLIR TYPE, not a value", None),
    # A MODULE-LEVEL `comptime` binding is not part of the function-body
    # expression walk at all — `compile()` is handed the prepared FUNCTION list
    # and lowers nothing else — so the multi-element template, the exact shape
    # the refusal above exists for, compiled away silently and every use site
    # read an undefined name. That made `std/builtin/type_aliases.mojo` a FALSE
    # PASS: four such bindings (lines 146/149/153/157) and the sweep counted the
    # file as one that built. The needle is this refusal's own, so the two
    # arches cannot name different limits for one construct — with "type"
    # rather than "attribute" where the initializer is a `__mlir_type`, which
    # this one is (`!lit.origin<…>`), and which the old fixed word got wrong
    # about every `__mlir_type` binding it was ever printed for.
    ("limit_module_level_comptime_mlir_template",
     "comptime OriginSet = __mlir_type[\n"
     "    `!lit.origin<`, 1, `>`\n"
     "]\n"
     "def main(n: Int) -> Int:\n"
     "    return n\n",
     "refuse:module-level comptime binding 'OriginSet' is initialized from an "
     "MLIR type template", None),
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
    # A SHIFT by more than 31 on arm64. `encode_lsl_xd_xn_imm` is a UBFM with
    # the amount in a 6-bit field at bit 16, and its base constant carried
    # 0xd3780000 — three of those six bits already set — so the OR of the
    # amount could not clear them: `1 << 32` computed `1 << 8`, `1 << 40`
    # computed `1 << 8` and `1 << 63` computed `1 << 7`, with no diagnostic of
    # any kind, and 0 through 7 were the only amounts that came out right. The
    # amounts here are 7 and 8 (the boundary the encoding gets right by
    # accident, and the first one after it), 32 and 40 (both wrong before the
    # base was corrected), and the composite `(1 << 32) >> 32`, which is 1 now
    # and was 0. The right shifts are the guard: a different encoder (SBFM,
    # base 0x93400000) that must keep working.
    # `%lld` and not `%d`, because this runtime's `%d` prints the low 32 bits
    # of a word (`printf("%d|%lld", 1 << 32, 1 << 32)` prints `0|4294967296`,
    # measured) and a 32-bit print of a 33-bit answer cannot tell a correct
    # shift from a wrong one that happens to be small.
    ("shift_amount_above_31_is_the_amount_asked_for",
     "def main(n):\n"
     "    printf(\"%lld %lld %lld %lld %lld %lld %lld\", 1 << 7, 1 << 8,"
     " 1 << 32, 1 << 40, (1 << 32) >> 32, 1024 >> 5, 1 >> 32)\n"
     "    return 0\n",
     0, "128 256 4294967296 1099511627776 1 32 0"),
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

# `return <frame>`: the block is copied into one the CALLER reserved and passes
# the address of, so the frame outlives its creator by construction. Every case
# here was a `refuse:` case in BYREF_REFUSALS until the returned-frame
# convention landed, and each is kept in the same SHAPE it had as a refusal so
# the arithmetic cannot quietly change: the reader can see the program the old
# message was about, and the value it now has to produce.
#
# Every one of them BUILDS AND RUNS on both architectures. A refusal lifted
# without a value to check is a claim, and this is the half that makes it a
# fact — the use-after-free these replaced is invisible without an intervening
# call, which is why the first case has one.
RETURNED_FRAME_CASES = [
    # The plain shape, and the reason the old refusal was right: with the
    # creator one frame deeper and a call in between, the address named
    # reclaimed stack. Measured with the refusal removed: 10 on arm64 and 0 on
    # x86-64 where the source says 78.
    ("ret_frame_survives_its_creator",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "    fn total(self) -> Int:\n"
     "        return self.a * 10 + self.b\n\n"
     "def mk() -> P:\n"
     "    var p = P()\n"
     "    p.a = 7\n"
     "    p.b = 8\n"
     "    return p\n\n"
     "def clobber(k: Int) -> Int:\n"
     "    var q = P()\n"
     "    var r = P()\n"
     "    q.a = 111\n"
     "    r.a = 222\n"
     "    return k + q.a + r.a\n\n"
     "def main(n: Int) -> Int:\n"
     "    var s = mk()\n"
     "    var k = clobber(0)\n"
     "    return s.total()\n", 78, None),
    # A frame that arrived as a PARAMETER and is handed straight back. The
    # creator is the caller, so the copy happens while the caller's frame is
    # still live; the destination is the block the caller reserved for the
    # result, which is the whole of what makes it sound.
    ("ret_frame_forwarded_from_a_parameter",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def fwd(r: Int) -> Int:\n"
     "    return r\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return fwd(r).a * 10 + fwd(r).b\n", 78, None),
    # …and a METHOD's receiver handed back, which is the same copy with the
    # address arriving in the receiver's home.
    ("ret_frame_from_a_method_receiver",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    fn give(self) -> Int:\n"
     "        return self\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return r.give().a * 10 + r.give().b\n", 78, None),
    # Through a NON-FIRST parameter, and returned to a caller one level above
    # the creator. Three levels of block ownership in one program, which is
    # what a fixed "one block per function" convention would get wrong.
    ("ret_frame_through_a_nonfirst_parameter",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def stash(x: Int, y: Int) -> Int:\n"
     "    return y\n\n"
     "def outer(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return stash(1, r)\n\n"
     "def main(n: Int) -> Int:\n"
     "    var p = outer(1)\n"
     "    return p.a * 10 + p.b\n", 78, None),
    # A frame read straight off the call, with nothing bound to a name. The
    # result is a value the caller consumes immediately, which is exactly the
    # lifetime the reserved block has.
    ("ret_frame_field_read_off_the_call",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def take(x: Int, y: Int) -> Int:\n"
     "    return y\n\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    return take(1, r).a\n", 7, None),
]

# Constructs a frame ADDRESS may not take part in. Each is a `refuse:` case
# because the alternative is a program that builds, runs, and reads a frame
# after the function that created it has returned — the one outcome this
# backend may not produce. They are here so that a future change which
# "helpfully" lowers them is caught.
#
# `return <frame>` was the first of them and is not any more: the convention
# above gives it a destination the CALLER owns. What is left is the set of
# channels with no such destination — a container, a field, a subscript, a
# position whose meaning this path cannot see — and each is a different hole in
# the same lifetime argument.
BYREF_REFUSALS = [
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
    # This is the ONE shape left of four (see the two cases below and the
    # cross-module one in CROSS_MODULE_CASES): `mojo_print` is defined nowhere
    # in this image and imported from nowhere, which is what "no definition in
    # hand" has always meant and the only one of the four it was true of.
    ("byref_refuse_invisible_callee",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n) -> Int:\n"
     "    var p = P()\n"
     "    return mojo_print(p)\n",
     "refuse:no definition in hand", None),
    # A COMPILE-TIME PARAMETER called as a function. `Fn` is not a function
    # this image fails to find — it is a name with no body at all, because
    # calling one means monomorphising it from the argument, and this path does
    # not instantiate type parameters. It reached the same sentence as
    # `mojo_print` above, which is the sentence that tells a reader to go
    # looking for a missing export; there is no missing export and there never
    # will be. The needle is the phrase that names what `Fn` is.
    ("byref_refuse_compile_time_parameter",
     "struct W:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def drive[\n"
     "    Fn: def(mut W)\n"
     "](mut w: W):\n"
     "    Fn(w)\n\n"
     "def main(n: Int) -> Int:\n"
     "    var w = W()\n"
     "    w.a = 1\n"
     "    w.b = 2\n"
     "    drive(w)\n"
     "    return n\n",
     "refuse:Fn is a compile-time PARAMETER of drive", None),
    # A COMPILER INTRINSIC rather than a function: `__get_mvalue_as_litref`
    # hands back an MLIR reference to the value it is given, and there is no
    # MLIR here, so the thing a receiver would be handed to does not exist at
    # any stage. Five of the twelve files the sweep files under this construct
    # are this one call, and every one of them is really an MLIR file whose
    # operand is refused one level down — a reader sent to a missing export
    # would not find one.
    ("byref_refuse_reflection_intrinsic",
     "struct Q:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var q = Q()\n"
     "    var lit = __get_mvalue_as_litref(q)\n"
     "    return n\n",
     "refuse:__get_mvalue_as_litref is not a function at all", None),
    # A bare call of a METHOD name with the receiver as the first argument. The
    # module declares `get` — as a method of `S` — so "this module does not
    # define it" would have been false, and the message now says the sharper
    # thing: there is no FUNCTION of that name, and a method here is reached as
    # `recv.get()` or under the lifted `S_get`.
    #
    # It is a GUARD on a spelling rather than a demonstration of a gap. Measured:
    # the same spelling with a VALUE receiver (`get(3)`) is not refused by this
    # pass at all — it lowers to a call of a symbol nothing defines and is caught
    # later by the bind audit, with "the image would bind 1 symbol(s) that
    # nothing provides". So bare method calls are unsupported here either way, and
    # this case pins which of the two diagnostics a frame receiver reaches. If a
    # future change makes the spelling legal, this case is the one to update.
    ("byref_refuse_bare_method_name",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    fn get(self) -> Int:\n"
     "        return self.a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S()\n"
     "    s.a = 7\n"
     "    s.b = 8\n"
     "    return get(s) + n\n",
     "refuse:defines no FUNCTION of that name", None),
    # `print` is a builtin this path COMPILES (`print("hi")` builds, runs and
    # prints), so a frame address handed to it could not be reported as a name
    # with "no definition in hand" — that is false of it. It could not go in
    # `FRAME_C_VALUE_CALLS` either, because that set's sentence says "a C
    # library entry point" and `print` is Mojo's builtin lowered through
    # `_emit_print`. The needle is the clause that names what it is; the
    # measured consequence (the image prints the frame's ADDRESS as a decimal,
    # differently on each machine and on each run) is in the message.
    ("byref_refuse_print_of_a_frame",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    p.a = 3\n"
     "    p.b = 4\n"
     "    print(p)\n"
     "    return n\n",
     "refuse:is a builtin of the language rather than a C entry point", None),
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
    #
    # A NON-FIRST argument position, whose source used to sit here as a
    # refusal. "A position whose meaning this path cannot see" was a statement
    # about the analysis in a message a reader takes to be a statement about
    # the program, and it was standing in for three different things. Wave 5
    # split them and the position became a load; the returned-frame convention
    # then gave the last shape a destination, so the whole program computes.
    # It is `ret_frame_field_read_off_the_call` in RETURNED_FRAME_CASES now,
    # with the arithmetic that says which 7.
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
    # The RETURNED half of the receiver family — a frame handed back by a
    # function that RECEIVED it, and the same through a method's receiver —
    # was refused here until the returned-frame convention gave it a
    # destination.  Both are now `ret_frame_forwarded_from_a_parameter` and
    # `ret_frame_from_a_method_receiver` in RETURNED_FRAME_CASES.  What the old
    # sentence got right is worth keeping in mind anyway: the creator is the
    # CALLER, not the function doing the returning, and the copy is sound
    # precisely because it happens while the caller's frame is still live.

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
    # A frame address handed to an IMPORTED FREE FUNCTION — the third shape a
    # "callee this image does not compile" can be, and the one whose refusal was
    # false. `take_it` IS defined (in `byref_xmod`, which builds: it exports
    # `take_it` and this case's own module does not fail), so "this module's own
    # functions are the only ones in this image" was false of it and sent the
    # reader looking for an export that is exported.
    #
    # The module deliberately never reads `p`, so the callee module itself is
    # clean and the refusal cannot be confused with the dependency's: what is
    # being asserted is WHICH question stops this program. The answer has to be
    # the cross-image one — whether THAT compilation made the parameter a frame
    # holder is a fact about a module compiled without this call site — and not
    # "there is no such callee", because there is one.
    #
    # It stays a REFUSAL. Following the address is what the message now says
    # would be needed (a per-parameter frame-holder contract in the manifest),
    # and until that exists the address would land in a slot `take_it` compiled
    # as a plain word.
    ("byref_refuse_imported_free_function",
     {"mod": "struct P:\n"
             "    var a: Int\n"
             "    var b: Int\n"
             "\n"
             "def take_it(p: P) -> Int:\n"
             "    return 1\n",
      "main": "from byref_xmod import P, take_it\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var p = P()\n"
              "    p.a = 3\n"
              "    p.b = 4\n"
              "    return take_it(p) + n\n"},
     "refuse:it imports take_it (`from byref_xmod import take_it`)", None),
    # The same hand-off reached through a STAR import, which is the shape where
    # "this module's own functions are the only ones in this image" is at its
    # least true: `from byref_xmod import *` binds whatever that module
    # EXPORTS, so `take_it` may well be bound — and the export set is a library
    # this pass has not built, because `_resolve_imports` compiles the modules
    # and the frame analysis runs first. 22 files of the standard library write
    # one. The refusal has to name THAT as the open question rather than assert
    # that nothing binds the name.
    ("byref_refuse_star_imported_free_function",
     {"mod": "struct P:\n"
             "    var a: Int\n"
             "    var b: Int\n"
             "\n"
             "def take_it(p: P) -> Int:\n"
             "    return 1\n",
      "main": "from byref_xmod import *\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var p = P()\n"
              "    p.a = 3\n"
              "    p.b = 4\n"
              "    return take_it(p) + n\n"},
     "refuse:can bind a name like that here is a `from byref_xmod import *`", None),
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
    # Before wave 5, with the position check lifted, this built and returned
    # 10 on arm64 and 0 on x86-64 where the source says 7 — a use-after-free,
    # and the two architectures disagreeing about the reused bytes.  It was
    # then REFUSED, naming the return rather than the position, which is the
    # whole of the split; and it is now a positive case,
    # `ret_frame_through_a_nonfirst_parameter` in RETURNED_FRAME_CASES, because
    # the returned-frame convention gives the address a home in a block the
    # CALLER owns.  The guard did its job: it is what made the shape visible
    # long enough for the copy to be designed for it.

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
    # message has to say WHICH shape of untyped it is, because a field a
    # `__init__` assigns and one only ever handed a literal are both "no
    # declared type" and only one of them is `= 0`.
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
     "refuse:declares 'in1' nowhere and has no __init__ at all", None),
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

# ── the SECOND evidence source for a field's type: what __init__ ASSIGNS ─────
#
# `DECLARED_TYPE_CASES` above is the declared half.  This is the constructor
# half, and it exists because a class that assigns its fields in `__init__` and
# declares none was the largest remaining group in the sweep's
# `field slot holds a frame address` family: `self.asm.org()`,
# `interpreter.scope.define()` and `self.in1.total()` all refused with "the
# declared type of 'asm' is the only thing here that could say so" — and a
# class that assigns its fields in `__init__` and declares none is the shape
# that same sentence listed as its own reason for not knowing.
#
# `model.struct_field_type` is the one function that combines the two sources;
# `model.struct_field_assigned_type` is the one that reads the constructor, and
# the whole of why that is EVIDENCE rather than a guess is premise (B2): `S()`
# does not run `__init__` on this path, so the word in the slot is the
# constructor's and the only thing the `__init__` line contributes is the NAME of
# the type.  That is also why a conditional or repeated assignment there is not a
# problem, and why the emitter is what has to be right about the store — which is
# what the tuple case below is about.
#
# Every expected exit below was read off CPython running the same program (the
# translation is `struct`→`class`, `fn`→`def`, and a declared field's implicit
# zero default made explicit, because CPython's annotation syntax produces no
# attribute at all).  Where the reference is stated as a DIFFERENT text it is
# premise (B2) saying which store does not execute, and the comment says which.
ASSIGNED_TYPE_CASES = [
    # The positive case, and the shape the sweep named: `self.in1.total()` where
    # `in1` is assigned in `__init__` and declared nowhere.  123 + 5 = 128, and a
    # build that computed 0 or 5 would be the silently-wrong outcome — a load
    # from a slot nothing was ever written to.
    ("assigned_type_nested_frame_method_call",
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
     "\n"
     "    fn __init__(self):\n"
     "        self.in1 = Inner()\n"
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
    # The same construct reached through a LOCAL rather than through `self`,
    # which is `scripts/stage2_mojo_interpreter.mojo`'s
    # `interpreter.scope.define()`: the base is a parameterless constructor in
    # `main`, not a receiver.  It is a separate case because the two are decided
    # by different tables — `fn._frame_candidates` for a local against
    # `struct_receivers` for `self` — and a fix that taught one and not the other
    # would leave half the sweep where it was.
    #
    # The method WRITES the nested frame (`self.depth`, `self.last`), so 201
    # also says the placed address is the frame itself and not a copy of it: a
    # copy would read back 0.
    ("assigned_type_nested_frame_through_a_local",
     "struct Scope:\n"
     "    var depth: Int\n"
     "    var names: Int\n"
     "    var last: Int\n"
     "\n"
     "    fn define(self, v: Int) -> Int:\n"
     "        self.depth = self.depth + 1\n"
     "        self.last = v\n"
     "        return self.depth * 100 + self.last\n"
     "\n"
     "    fn get(self) -> Int:\n"
     "        return self.depth * 10000 + self.last\n"
     "\n"
     "struct Interpreter:\n"
     "    var filename: Int\n"
     "    var pad: Int\n"
     "\n"
     "    fn __init__(self):\n"
     "        self.scope = Scope()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var interpreter = Interpreter()\n"
     "    interpreter.scope.depth = 0\n"
     "    interpreter.scope.last = 0\n"
     "    var a = interpreter.scope.define(7)\n"
     "    var b = interpreter.scope.define(9)\n"
     "    return a * 1000 + b\n", 201, None),
    # TWO objects, each holding its own placed nested frame, and a WRITE
    # through the nested struct's own method.  Each read is guarded by a
    # different return code, so a regression says WHICH frame moved rather than
    # only that a number is wrong.  A nested frame that were placed once and
    # shared would still answer the first two guards and fail the last two —
    # which is the whole reason this is not folded into the case above.
    ("assigned_type_nested_frame_two_objects_no_alias",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "    fn bump(self) -> Int:\n"
     "        self.c = self.c + 1\n"
     "        return self.a * 100 + self.b * 10 + self.c\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "\n"
     "    fn __init__(self):\n"
     "        self.in1 = Inner()\n"
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
     "    if o1.in1.bump() != 124:\n"
     "        return 1000 + o1.in1.bump()\n"
     "    if o2.in1.bump() != 790:\n"
     "        return 2000 + o2.in1.bump()\n"
     "    if o1.in1.c != 4:\n"
     "        return 3000 + o1.in1.c\n"
     "    if o2.in1.c != 10:\n"
     "        return 4000 + o2.in1.c\n"
     "    return 0\n", 0, None),
    # The GUARD on the precedence rule, and the one most likely to be quietly
    # dropped: a DECLARATION still wins over a contradicting `__init__`
    # assignment, and the reason is premise (B2) rather than a preference —
    # `Outer()` does not run `__init__`, so the word in `in1` is the
    # declaration's, whatever the assignment says.  Cross-checking the two
    # would refuse correct code.
    #
    # The reference is the same program with `Other()` replaced by `Inner()`
    # (CPython 128), which is what premise (B2) says the `__init__` line does
    # not do.  A build that honoured the ASSIGNMENT would place an `Other` and
    # call `Inner.total` on it: 1, 2, 3 at the slots `Other` shares, so it
    # would answer 123 rather than 128 and exit 0 — the silently-wrong shape
    # this case exists to catch.
    ("assigned_type_a_declaration_still_wins",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "    fn total(self) -> Int:\n"
     "        return self.a * 100 + self.b * 10 + self.c\n"
     "\n"
     "struct Other:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    var in1: Inner\n"
     "\n"
     "    fn __init__(self):\n"
     "        self.in1 = Other()\n"
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
]

ASSIGNED_TYPE_REFUSALS = [
    # The field is a nested frame's type AND an executed method REPLACES it.
    # The type is known, which is what the constructor half of
    # `struct_field_type` bought, and what is not known is WHOSE frame the slot
    # holds — so this must still be the `_REASSIGNED` diagnosis, not the
    # untyped one.  A fix that made the type available and then placed the frame
    # anyway would answer 123 where the source says 128: `Other`'s frame and
    # `Inner`'s have the same layout here, so the wrong one is silent.
    ("byref_refuse_assigned_field_written_by_a_method",
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
     "\n"
     "    fn __init__(self):\n"
     "        self.in1 = Inner()\n"
     "\n"
     "    fn reset(self):\n"
     "        self.in1 = Inner()\n"
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
     "    return o.go()\n",
     "refuse:which is a Inner — a struct of this module whose receiver is a frame — but a method of Outer ASSIGNS it", None),
    # Two constructions, two types.  This is the agree-or-refuse rule doing its
    # job over the SECOND source: one counter-example takes the capability back
    # out, and the needle is both names because a refusal that does not say which
    # candidates disagreed is a refusal the reader has to re-derive.
    ("byref_refuse_two_assigned_types",
     "struct A2:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    fn ta(self) -> Int:\n"
     "        return self.a * 10 + self.b\n"
     "\n"
     "struct B2:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    fn tb(self) -> Int:\n"
     "        return self.a * 10 + self.b\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "\n"
     "    fn __init__(self, c: Int):\n"
     "        if c > 0:\n"
     "            self.in1 = A2()\n"
     "        else:\n"
     "            self.in1 = B2()\n"
     "\n"
     "    fn go(self) -> Int:\n"
     "        return self.in1.ta()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer(1)\n"
     "    return o.go()\n",
     # The EXPECTED WORDS are the inference's, not the shape-reader prose this
     # case was written against, after `struct_field_assigned_type` was rewired
     # onto `struct_init_field_types` so the type question has ONE reader. Both
     # sentences name the same fact — two assignments, two types, no single
     # answer — and the new one names the two types in the source's own
     # spelling without the quoting, which is what the comment above this row
     # asks a disagreement refusal to do.
     "refuse:__init__ assigns it 2 different types (A2, B2)", None),
    # An assignment of a NAME.  This is the case that says the inference is not
    # a type guess: a parameter carries no type, so the field stays untyped and
    # is refused — and the refusal says so in the source's own words, because
    # the reader's next move is to look at the assignment.
    ("byref_refuse_an_assignment_of_a_name",
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
     "\n"
     "    fn __init__(self, w: Int):\n"
     "        self.in1 = w\n"
     "\n"
     "    fn go(self) -> Int:\n"
     "        return self.in1.total() + self.tag\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer(5)\n"
     "    return o.go()\n",
     # …and the negative half names the CLASSIFIER's reason rather than one
     # example of it: "a name, a member, a ternary, a comprehension, or a call
     # to a function this module does not declare as a type" is the set of
     # shapes `assigned_value_base_name` declines, and this row is the
     # `self.in1 = w` instance of it. A refusal that quoted one instance sent
     # the reader to check whether their own assignment was that one.
     "refuse:__init__ assigns it values this path cannot reduce to a type", None),
    # A TUPLE target: `self.a, self.b = A(), B()`, which is what
    # `tools/procrun.py` writes.  The field is recognised as assigned, so the
    # message is about the STORE and not about the type — and the store is the
    # real gap: a tuple store to a field is refused by name on x86-64 and
    # ACCEPTED-AND-DROPPED on arm64.  This case is here so that reading a type
    # out of a store the emitter does not perform cannot come back unnoticed;
    # with it read as evidence the program built, ran, and answered 123 where
    # the source says 128.
    # bugs/FORMAL_tuple_store_to_a_field.md is the codegen bug.
    ("byref_refuse_a_tuple_target_names_the_store",
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
     "\n"
     "    fn __init__(self):\n"
     "        self.tag, self.in1 = 5, Inner()\n"
     "\n"
     "    fn go(self) -> Int:\n"
     "        return self.in1.total() + self.tag\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    o.in1.a = 1\n"
     "    o.in1.b = 2\n"
     "    o.in1.c = 3\n"
     "    return o.go()\n",
     "refuse:a tuple store to a FIELD is not a store this path performs", None),
]


# ── a field's TYPE from what `__init__` ASSIGNS it ──────────────────────────
#
# The second evidence source for `model.struct_field_declared_type`, and the one
# that makes a class which assigns its fields in `__init__` and declares none a
# lowerable program rather than a refusal by name. `bugs/FORMAL_class_assigns_its_
# fields_in_init.md` is the finding and the measurement; what is here is the
# evidence that the change is both sound and narrow.
#
# FOUR things these cases have to establish, in the order they matter:
#
#   1. The nested frame is PLACED and the program computes the source's answer.
#      `self.inner = Inner()` types the slot exactly as `var inner: Inner` does,
#      so the constructor places Inner's frame in Outer's own block and the two
#      objects of `init_assigned_nested_frame_two_objects_no_alias` get two
#      frames at two addresses. Read through CPython: every answered case below
#      is also a Python program and the expected exit status is what CPython
#      returns from `main()`.
#   2. `__init__` is evidence about the field's TYPE and never about its VALUE.
#      `init_assigned_class_default_still_governs_the_value` is the case, and it
#      is the only one here whose answer is NOT CPython's — deliberately, and
#      because premise (B2) says a zero-argument `S()` does not run `__init__`
#      on this path, so the class-level default is what the constructor stores.
#      CPython returns 99 and the image returns 7, and that gap is the premise,
#      not this change: the case was built on the pre-change tree and returned 7
#      there too (see the doc). What the case is for is that the `__init__`
#      assignment now TYPES the field, so a kind is claimed where none was
#      claimed before — and the value the image computes must still be the one
#      the CONSTRUCTOR put there.
#   3. UNANIMITY OR NOTHING, and nothing else. A field assigned two different
#      classifiable values, or one the classifier cannot reduce to a type, is not
#      typed, so no frame is placed and the case is refused — with the
#      disagreement SPELLED, because a refusal that says only "no evidence" sends
#      the reader looking for evidence the tool cannot read.
#   4. The narrowing: a field an EXECUTED method assigns is still `_REASSIGNED`,
#      because `__init__` is excluded from `struct_fields_written_outside_init`
#      and the lifetime argument that prefers a placed frame does not apply to a
#      word some running method put there.
#
# `method_reference_and_missing_field_*` at the bottom are the other half of this
# change: the diagnostic `model.member_read_without_a_field` replaced, which used
# to print "this name holds a frame address in more than one shape" for a single
# candidate with no disagreement to report.
INIT_FIELD_TYPE_CASES = [
    # (1) THE POSITIVE CASE, and the one the sweep's ten files are all the same
    # instance of. `Interpreter.scope` / `ARM64Codegen.asm` / `Tail._chunks`:
    # three classes of this repository that assign their fields in `__init__`,
    # declare none of them, and are refused by name. Nothing here is unusual
    # Python, and 123 + 5 is what `main()` returns in CPython too.
    #
    # The shape that would be silently wrong instead of refused is a shared
    # nested frame: one block per construction SITE is what keeps `o.inner` from
    # naming the same address in two objects, so this asserts a real answer
    # rather than "it linked".
    ("init_assigned_nested_frame_method_call",
     "class Inner:\n"
     "    __slots__ = ('a', 'b', 'c')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "        self.c = 0\n"
     "\n"
     "    def total(self):\n"
     "        return self.a * 100 + self.b * 10 + self.c\n"
     "\n"
     "class Outer:\n"
     "    __slots__ = ('tag', 'pad', 'inner')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.tag = 0\n"
     "        self.pad = 0\n"
     "        self.inner = Inner()\n"
     "\n"
     "    def go(self):\n"
     "        return self.inner.total() + self.tag\n"
     "\n"
     "def main():\n"
     "    o = Outer()\n"
     "    o.tag = 5\n"
     "    o.inner.a = 1\n"
     "    o.inner.b = 2\n"
     "    o.inner.c = 3\n"
     "    return o.go()\n", 128, None),
    # TWO OBJECTS, EACH HOLDING ITS OWN NESTED FRAME, each read guarded by a
    # different return code so a regression says WHICH frame moved. This is the
    # case a "the lowering is the same for every width" argument cannot
    # establish on its own, and it is the same program as the row above with a
    # second construction site — which is what makes it a test of the BLOCK
    # placement and not of the method call.
    ("init_assigned_nested_frame_two_objects_no_alias",
     "class Inner:\n"
     "    __slots__ = ('a', 'b', 'c')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "        self.c = 0\n"
     "\n"
     "    def total(self):\n"
     "        return self.a * 100 + self.b * 10 + self.c\n"
     "\n"
     "class Outer:\n"
     "    __slots__ = ('tag', 'pad', 'inner')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.tag = 0\n"
     "        self.pad = 0\n"
     "        self.inner = Inner()\n"
     "\n"
     "    def go(self):\n"
     "        return self.inner.total()\n"
     "\n"
     "def main():\n"
     "    o1 = Outer()\n"
     "    o2 = Outer()\n"
     "    o1.inner.a = 1\n"
     "    o1.inner.b = 2\n"
     "    o1.inner.c = 3\n"
     "    o2.inner.a = 7\n"
     "    o2.inner.b = 8\n"
     "    o2.inner.c = 9\n"
     "    if o1.inner.total() != 123:\n"
     "        return 10 + o1.inner.total()\n"
     "    if o2.inner.total() != 789:\n"
     "        return 20 + o2.inner.total()\n"
     "    o2.inner.a = 4\n"
     "    if o1.inner.total() != 123:\n"
     "        return 30 + o1.inner.total()\n"
     "    if o2.inner.total() != 489:\n"
     "        return 40 + o2.inner.total()\n"
     "    o1.inner.c = 5\n"
     "    if o2.inner.total() != 489:\n"
     "        return 50 + o2.inner.total()\n"
     "    return 0\n", 0, None),
    # THE TUPLE FORM is exercised by `init_assigned_scalar_fields_stay_plain`
    # below rather than here, because it is a property of the STATEMENT
    # lowering and x86-64 does not lower a `MemberExpr` tuple target at all
    # (`formal/x86_64_codegen.py`'s `_emit_tuple_assign` takes plain names only,
    # while arm64 lowers it) — a divergence in the two backends rather than in
    # anything to do with the evidence source, filed as
    # `bugs/FORMAL_x86_64_tuple_assignment_member_target.md`.
    ("init_assigned_scalar_fields_stay_plain",
     "class Tail:\n"
     "    __slots__ = ('limit', '_chunks', '_size')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.limit = 4\n"
     "        self._chunks = []\n"
     "        self._size = 0\n"
     "\n"
     "    def count(self):\n"
     "        return self._size\n"
     "\n"
     "def main():\n"
     "    t = Tail()\n"
     "    t.limit = 4\n"
     "    t._size = 5\n"
     "    return t.limit + t.count()\n", 9, None),
    # (2) THE VALUE IS NOT `__init__`'s. A class-level default is the only thing
    # this path materialises into a fresh instance's slot, so 7 is what the
    # image computes and 99 — what `__init__` says — is what premise (B2)
    # (`FRAME_FIELD_BLOB_PREMISE_B2`) rules out. CPython runs `__init__` and
    # returns 99.
    #
    # This case exists because the change makes the field TYPED: `self.limit =
    # 99` is an int literal, so `struct_field_kind` now has a kind to claim
    # where it had none, and the materialisable-default gate in
    # `struct_field_kind` is what keeps the answer at 7. A regression that let
    # the `__init__` VALUE through would make this return 99 and every case
    # below would still pass, so it is here on its own.
    ("init_assigned_class_default_still_governs_the_value",
     "class Cfg:\n"
     "    limit = 7\n"
     "\n"
     "    def __init__(self):\n"
     "        self.limit = 99\n"
     "        self.pad = 0\n"
     "\n"
     "    def get(self):\n"
     "        return self.limit\n"
     "\n"
     "def main():\n"
     "    c = Cfg()\n"
     "    return c.get()\n", 7, None),
    # The same gate, on the OTHER half of `declared_type_kind`'s table: a
    # class-level STRING default plus `self.s = "hi"` in `__init__` types the
    # field as a string, and `len()` of a string is a `strlen`. Before the
    # change this was refused with "the source does not say what this operand
    # holds" — false about a class whose `__init__` said it. 2 in CPython, where
    # `__init__` runs and puts the same "hi" there.
    ("init_assigned_string_field_len_is_answerable",
     "class Bag:\n"
     "    s = \"hi\"\n"
     "\n"
     "    def __init__(self):\n"
     "        self.s = \"hi\"\n"
     "        self.n = 0\n"
     "\n"
     "    def size(self):\n"
     "        return len(self.s) + self.n\n"
     "\n"
     "def main():\n"
     "    b = Bag()\n"
     "    return b.size()\n", 2, None),
]

INIT_FIELD_TYPE_REFUSALS = [
    # (3) UNANIMITY, and the first of the two. `self.inner = Inner()` on one
    # branch and `self.inner = None` on the other are both classifiable and they
    # classify DIFFERENTLY, so there is no single answer and no frame is placed.
    # The needle is the model's `struct_init_field_type_why` sentence rather than
    # the refusal's summary, because the summary is about the frame layout and
    # the reader needs to know WHICH evidence was read and rejected.
    #
    # Nothing runs `__init__` on this path, so a reader might reasonably ask
    # whether the branch matters. It does not, and that is the point: the rule
    # is flow-INsensitive about `__init__` exactly as `ValueKinds` is about a
    # local name, because agreeing on "what type is this slot" must not depend
    # on which use site asked.
    ("init_assigned_type_must_be_unanimous",
     "class Inner:\n"
     "    __slots__ = ('a', 'b', 'c')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "        self.c = 0\n"
     "\n"
     "    def total(self):\n"
     "        return self.a + self.b + self.c\n"
     "\n"
     "class Outer:\n"
     "    __slots__ = ('tag', 'pad', 'inner')\n"
     "\n"
     "    def __init__(self, c):\n"
     "        self.tag = 0\n"
     "        self.pad = 0\n"
     "        if c:\n"
     "            self.inner = Inner()\n"
     "        else:\n"
     "            self.inner = None\n"
     "\n"
     "    def go(self):\n"
     "        return self.inner.total()\n"
     "\n"
     "def main():\n"
     "    o = Outer(1)\n"
     "    o.inner.a = 4\n"
     "    return o.go()\n",
     "refuse:__init__ assigns it 2 different types (Inner, None), so there is no single answer", None),
    # UNANIMITY, the other direction: one classifiable assignment and one that
    # is not. `self.inner = make()` is a call whose callee is a NAME, and a name
    # is not a type — the classifier says so rather than guessing at what
    # `make` returns, and one unclassifiable assignment takes the whole field
    # out of the typed set.
    #
    # The counter-case a reader will ask for is `self.inner = Inner(1)`: also a
    # bare constructor call, and ALSO typed, because the arguments say nothing
    # about which struct is constructed.
    ("init_assigned_unclassifiable_value_stays_untyped",
     "class Inner:\n"
     "    __slots__ = ('a', 'b', 'c')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "        self.c = 0\n"
     "\n"
     "    def total(self):\n"
     "        return self.a + self.b + self.c\n"
     "\n"
     "def make():\n"
     "    return Inner()\n"
     "\n"
     "class Outer:\n"
     "    __slots__ = ('tag', 'pad', 'inner')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.tag = 0\n"
     "        self.pad = 0\n"
     "        self.inner = make()\n"
     "\n"
     "    def go(self):\n"
     "        return self.inner.total()\n"
     "\n"
     "def main():\n"
     "    o = Outer()\n"
     "    o.inner.a = 4\n"
     "    return o.go()\n",
     "refuse:__init__ assigns it values this path cannot reduce to a type", None),
    # THE NARROWING, and the case that makes the whole thing safe: the type is
    # known and it IS a frame, and what is unknown is WHOSE. `Outer.reset`
    # ASSIGNS `self.inner`, so the word in the slot is a frame belonging to
    # whichever function ran the assignment rather than the frame this
    # constructor placed, and those two lifetimes are independent. So the answer
    # is `_REASSIGNED` and not a nested frame, which is the same fourth answer
    # `byref_refuse_write_over_a_nested_frame` pins for an ANNOTATED field — the
    # two must not be able to disagree about which fields are written.
    ("init_assigned_field_written_by_a_method_stays_reassigned",
     "class Inner:\n"
     "    __slots__ = ('a', 'b', 'c')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "        self.c = 0\n"
     "\n"
     "    def total(self):\n"
     "        return self.a + self.b + self.c\n"
     "\n"
     "class Outer:\n"
     "    __slots__ = ('tag', 'pad', 'inner')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.tag = 0\n"
     "        self.pad = 0\n"
     "        self.inner = Inner()\n"
     "\n"
     "    def reset(self):\n"
     "        self.inner = Inner()\n"
     "\n"
     "    def go(self):\n"
     "        return self.inner.total()\n"
     "\n"
     "def main():\n"
     "    o = Outer()\n"
     "    o.inner.a = 4\n"
     "    return o.go()\n",
     "refuse:ASSIGNS", None),
    # A CONTAINER field, and the case the `procrun.py` row is really about. The
    # frame question is answered — `self._chunks = []` says the slot holds a
    # blob and a blob is never a frame address of this unit — so the frame
    # diagnostic must NOT fire, and the value-method one must. The needle is the
    # common part of the two architectures' sentence; the architectures differ
    # only in which one they name.
    #
    # Before the change this source was refused with "the declared type of
    # '_chunks' is the only thing here that could say so, and it does not" —
    # a frame-layout diagnostic about a list.
    ("init_assigned_container_reaches_the_value_method_refusal",
     "class Tail:\n"
     "    __slots__ = ('limit', '_chunks', '_size')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.limit = 4\n"
     "        self._chunks = []\n"
     "        self._size = 0\n"
     "\n"
     "    def append(self, data):\n"
     "        self._chunks.append(data)\n"
     "        return self._size\n"
     "\n"
     "def main():\n"
     "    t = Tail()\n"
     "    t.append(1)\n"
     "    return t.limit\n",
     "refuse:list.append() is not lowered on the formal", None),
    # `len()` of the nested frame the new evidence placed. The point is which of
    # the two `len` sentences fires: a frame ADDRESS is its own case in
    # `len_refusal`, and getting it means the slot was typed as a frame and not
    # left unclassified. The alternative sentence ("the source does not say what
    # this operand holds") would be false about a class whose `__init__` says
    # `self.inner = Inner()`.
    ("init_assigned_nested_frame_len_is_the_frame_address_refusal",
     "class Inner:\n"
     "    __slots__ = ('a', 'b', 'c')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "        self.c = 0\n"
     "\n"
     "class Outer:\n"
     "    __slots__ = ('tag', 'pad', 'inner')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.tag = 0\n"
     "        self.pad = 0\n"
     "        self.inner = Inner()\n"
     "\n"
     "    def go(self):\n"
     "        return len(self.inner)\n"
     "\n"
     "def main():\n"
     "    o = Outer()\n"
     "    return o.go()\n",
     "refuse:len(self.inner) is len() of a FRAME ADDRESS", None),
    # ── the member-read diagnostic (row 13 of the sweep map) ──
    #
    # `self.helper` in a VALUE position is a bound method, not a field read, and
    # this path has no bound-method values. The refusal it used to produce was
    # "this name holds a frame address in more than one shape, and the shapes do
    # not agree on where 'helper' lives" — with ONE candidate and no
    # disagreement, which is what `formal/arm64_codegen.py`'s own
    # `self._untyped_callee` reported before this change.
    #
    # The case passes the reference as a KEYWORD argument on purpose: that is
    # the spelling `formal/arm64_codegen.py` uses, and it is the one that keeps
    # `helper` out of the class's field set, which is why that file was refused
    # rather than lowered. It is also the shape behind
    # `bugs/FORMAL_field_set_method_name_and_kwarg_blind_spot.md` — read that
    # before changing `_self_field_names`.
    ("method_reference_is_not_a_frame_slot",
     "class Outer:\n"
     "    __slots__ = ('limit', 'pad')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.limit = 4\n"
     "        self.pad = 0\n"
     "\n"
     "    def helper(self):\n"
     "        return 1\n"
     "\n"
     "    def size(self, probe):\n"
     "        return probe(helper=self.helper)\n"
     "\n"
     "def take(helper):\n"
     "    return helper()\n"
     "\n"
     "def main():\n"
     "    o = Outer()\n"
     "    return o.size(take)\n",
     "refuse:which is a METHOD of Outer rather than one of its fields", None),
    # The same refusal for the OTHER shape row 13 holds: a member read of a name
    # the receiver's struct simply does not have. There is no disagreement to
    # report either, and the useful sentence is that the struct has no such
    # field — which in Python is an `AttributeError`, so the reader learns that
    # the program is very likely already raising rather than that two layouts
    # are confused. This is `analyze_benchmarks_types.py`'s `gen.type_checker`
    # and `test_type_system_integration.py`'s `gen._strict_type_checking`, both
    # reads of a `GimpleGen` field that class has never had.
    #
    # It is a `refuse_without:` case because the wording it replaces was not
    # merely incomplete but FALSE — the old message claimed two shapes that do
    # not exist — and a `refuse:` case is satisfied by appending the true
    # sentence beside the false one.
    ("missing_field_is_not_reported_as_a_disagreement",
     "class Cfg:\n"
     "    __slots__ = ('limit', 'pad')\n"
     "\n"
     "    def __init__(self):\n"
     "        self.limit = 4\n"
     "        self.pad = 0\n"
     "\n"
     "    def get(self):\n"
     "        return self.limit\n"
     "\n"
     "def main():\n"
     "    c = Cfg()\n"
     "    return c.get() + c.nosuch\n",
     "refuse_without:Cfg has no field 'nosuch':in more than one shape", None),
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
    # GUARD, and the one that says the change did not OVERREACH: `S()` on a
    # struct that declares an `__init__` still brings every field up at its
    # class-level default and does NOT run the body, because there are no
    # arguments for the argument count to select an overload with.  A lowering
    # that ran the constructor here would have to pick a zero-required overload
    # by something other than the count, and 8 + 9 is what a reader would be
    # entitled to expect if it did.  The sibling refusal
    # `constr_zero_arg_still_ignores_a_declared_init` pins the same fact from
    # the other side (a constructor that takes arguments).
    ("constr_init_a_zero_argument_construction_still_ignores_the_body",
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
     "    if z.get(0) != 0 or z.get(1) != 0:\n"
     "        return 20 + z.get(0)\n"
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
    # and the message is a different one — the frame's.  `f` is declared `In3`,
    # a struct of this module whose receiver is a frame, so the parameter is a
    # FRAME HOLDER (the declared type is the evidence; there is no call site
    # that hands it one, because `In4.__init__` is called by nobody here) and
    # `self.f = f` parks a frame address in a field.  That is
    # `frame_return_refusal`'s sibling for a store, and it is the more useful of
    # the two messages because it names the LIFETIME question: the slot belongs
    # to the frame that created THAT object and nothing here can say the two
    # lifetimes agree.  It used to be answered by the placement instead
    # (`construction_nested_slot_refusal`, "a store over a placed nested frame"),
    # which was right about the slot and silent about the address being stored
    # in it; the ORDER moved because the frame analysis runs before the
    # construction checks and now recognises the parameter.  Still a refusal, and
    # a separate case because two refusals for one family is exactly what "the
    # needle is the fact that is wrong" is for.
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
     "    return x.g",
     "refuse:is stored in the field 'self.f'", None),
    # The guard on the other side of the same line: a ZERO-argument `S()` on a
    # struct that declares `__init__` is NOT one of the refusals above. There
    # are no arguments for the count to select an overload with, so it stays
    # premise (B2) — every field comes up at its class-level default — and that
    # is the shape nearly every container in the corpus is written in. If this
    # case ever starts refusing, the init branch has leaked above the `not args`
    # early return. `constr_init_a_zero_argument_construction_still_ignores_the_body`
    # in `CASES` is the same fact with all-defaulted parameters, where a
    # lowering that DID run the body would have produced 8 and 9.
    ("constr_zero_arg_still_ignores_a_declared_init",
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
     "    if b.get() != 0:\n"
     "        return 20 + b.get()\n"
     "    return 7\n", 7, None),
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
    #
    # It used to assert the REFUSAL, and it stopped doing so on 2026-09-29
    # because the construct stopped being one refusal: a `#kgen.param.expr<…>`
    # template that asks a QUESTION this build can answer is not an MLIR
    # attribute with nowhere to go — `formal/model.py`'s target-query evaluator
    # answers it at build time, from the `arch`/`fmt` pair the linker is about
    # to act on. `eq(1, 2)` is decidable without any target at all, so this
    # case is now an EXECUTED value assertion rather than a refusal: the image
    # has to take the false branch, which is what a fabricated 1 would fail.
    ("sub_multi_index_mlir_template",
     "def main(n):\n"
     "    x = __mlir_attr[`#kgen.param.expr<eq,`, 1, `, 2> : i1`]\n"
     "    if x:\n"
     "        return 1\n"
     "    return 0\n", 0, None),
    # The half of the family that is still refused, and WHY, which is the
    # point of keeping a refusal next to the value case: `target_has_feature`
    # is a question about a CPU, and this build names the architecture it emits
    # and never a CPU. A hand-kept feature table would have made this pass, and
    # would have been a wrong answer nobody could detect the rot of.
    ("sub_multi_index_mlir_template_unanswerable",
     "def main(n):\n"
     "    x = __mlir_attr[\n"
     "        `#kgen.param.expr<target_has_feature,`,\n"
     "        __mlir_attr.`#kgen.param.expr<current_target> : !kgen.target`,\n"
     "        `, \"neon\"`,\n"
     "        `> : i1`]\n"
     "    return 0\n",
     "refuse:target_has_feature('neon') is a per-CPU question", None),
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


def run_cpython_pair_case(name, source, cpython_source, tmpdir, verbose):
    """Build the image on BOTH backends, run both, and require CPython's answer.

    The expected output is whatever CPython prints for `cpython_source`, run
    here, at test time. That is the whole difference from every other case in
    this file, and it is the reason this group exists rather than four more
    hand-written constants: a constant is an assertion about a lowering made by
    the same person who wrote the lowering, and a program that computes the
    right number for the wrong reason passes either way.

    Both architectures are required to match CPython, not just the host's. The
    two disagreeing answers this group is here to catch have both happened —
    arm64 refusing a bracketed callee as a name with no home while x86-64
    refused it as an unsupported call target, from two private copies of the
    callee-flattening rule — and a one-sided assertion would have been green
    throughout.
    """
    py = os.path.join(tmpdir, name + ".py")
    # The CALL is the runner's, not the case's. `def main()` is Mojo's entry
    # point — the build driver calls it — and in Python it is only a definition,
    # so a case that wrote its own call would be carrying a fact about the
    # harness in the text that is supposed to be the computation. It is also
    # the one thing every case would have to get right identically, which is
    # exactly the kind of duplication that goes wrong in one case and not the
    # others.
    with open(py, "w") as f:
        f.write(cpython_source + "\nmain()\n")
    ref = subprocess.run([sys.executable, py], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    if ref.returncode != 0:
        return False, (f"the CPython reference itself failed (exit "
                       f"{ref.returncode}): {ref.stderr.strip()[-200:]}")
    want = ref.stdout
    for backend in ("arm64", "x86_64"):
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(os.path.join(tmpdir, name + ".mojo"), out,
                                backend=backend)
        if rc != 0:
            return False, f"--backend={backend} did not build: {text.strip()[-300:]}"
        run = subprocess.run([out], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT)
        if run.stdout != want:
            return False, (f"--backend={backend} printed {run.stdout!r}, CPython "
                           f"printed {want!r}")
        if run.returncode != 0:
            return False, (f"--backend={backend} computed the right answer and "
                           f"exited {run.returncode}")
        if verbose:
            print(f"      {backend}: {run.stdout!r} == CPython")
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
# either architecture, so BOTH refused by name, from the same
# `model.field_access_refusal`, and the two architectures could no longer answer
# this program differently.  The case stayed — as a refusal — until the
# DECLARED TYPE could establish what the parameter holds
# (`bugs/FORMAL_method_param_field_access.md`): `h: One` says `h` IS a `One`,
# and a one-field struct's receiver is its field, so `h.v` is `h` and the
# program is answerable.  So the case is now what it should have been from the
# start, which is the assertion the whole family wants: `raw(o) == 4242` on
# BOTH backends, against a 4242 written into the field.  Before the change
# x86-64 read an immediate 0 and returned the wrong number; the refusal was the
# honest interim answer and this is the real one.
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
   1, None)


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
     "        self.inner = Inner()\n"
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
    # ── `None` as a value: the word 0, and the one comparison it cannot answer ──
    #
    # `x: T = None` is the default for an optional field and is the single most
    # common class-level default in this repository's own dataclasses
    # (`type_system.py`'s `Type` has ten of them on one class). It was REFUSED
    # as "not a literal", because `None` parses to a bare `IdentExpr` on this
    # front end and neither `fold_literal_expr` nor `literal_default_word` had
    # an arm for it — a message that sends a reader looking for a call, where
    # there is no call. It is a value this target represents exactly: the word
    # 0, which is what an unwritten frame slot already is.
    #
    # There is deliberately no CPython comparison for this case. `printf("%d",
    # None)` is a TypeError there, so the oracle does not exist; what the image
    # must produce is the REPRESENTATION, and the two rows below pin it from
    # both sides — a class-level constant, materialized at the read, and a
    # module-level one, folded at the read. Both were refusals before.
    ("none_class_default_is_the_word_zero",
     "struct R:\n"
     "    var a: Int = 1\n"
     "    var b: Int = None\n"
     "    def show(self) -> Int:\n"
     "        printf(\"a=%d b=%d\\n\", self.a, self.b)\n"
     "        return 0\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.show()\n"
     "    return 0\n",
     0, "a=1 b=0"),
    ("none_module_constant_is_the_word_zero",
     "G = None\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    printf(\"g=%d\", G)\n"
     "    return 0\n",
     0, "g=0"),
    # …and arithmetic on it is arithmetic on the word, which is the other half
    # of "representable": the fold is not confined to being printed.
    ("none_module_constant_arithmetics_as_zero",
     "G = None\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    return G + 5\n",
     5, None),
    # THE LIMIT, and the reason this is a refusal and not a wrong answer.
    # `None` is the word 0 and the model is ONE UNTAGGED WORD, so after the
    # fold `p.b == 0` and `p.b is None` are the same expression — and CPython
    # says one is False and the other True. Answering either from the folded
    # word is the outcome this backend exists to prevent, so the comparison is
    # refused BY NAME and the message says which construct and why. Checked on
    # both backends by the `refuse:` machinery, because a wrong answer here is
    # the shape where the two architectures would each be confidently wrong.
    #
    # Before the fold landed these three built and answered: the class-level
    # one returned 7 for a `None`, where CPython returns 0.
    ("refuse_none_compared_with_a_class_constant",
     "struct R:\n"
     "    var b: Int = None\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    if r.b == 0:\n"
     "        return 7\n"
     "    return 0\n",
     "refuse:is class-level constant holding `None`", None),
    ("refuse_none_compared_as_the_class_itself",
     "struct R:\n"
     "    var b: Int = None\n"
     "def main(k: Int) -> Int:\n"
     "    if R.b != 0:\n"
     "        return 7\n"
     "    return 0\n",
     "refuse:is class-level constant holding `None`", None),
    ("refuse_none_compared_as_a_module_constant",
     "G = None\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    if G == 0:\n"
     "        return 7\n"
     "    return 0\n",
     "refuse:is module-level name holding `None`", None),
    # GUARD (passes before and after, and it is here because it is the case
    # that would catch an over-correction in the other direction): an INTEGER
    # class-level constant compared with a literal is ordinary, representable
    # code and must keep building. If the refusal above were written as "any
    # comparison against a constant", this row is what it would break.
    ("int_class_constant_comparison_still_builds",
     "struct R:\n"
     "    var b: Int = 3\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    if r.b == 3:\n"
     "        return 7\n"
     "    return 0\n",
     7, None),
    # ── a module-level constant read in an `elif` ARM ──
    #
    # `elif x == K:` was REFUSED with "'K' has no home: the register allocator
    # collected no home for it" on BOTH architectures, while `if x == K:` in the
    # same function built. The message blamed the emitter's phi/web slot, and
    # the emitter was innocent: `IfStmt.elifs` is a list of `(condition, body)`
    # pairs, and the module-constant substitution walked lists but not tuples, so
    # an `elif` condition was the one expression position in the tree the walk
    # never reached. The unsubstituted `IdentExpr` then reached the emitter as a
    # name with no home.
    #
    # Every answer must be 2, and each is 2 for a different reason — the
    # `if` arm falling through, the `elif` arm matching, and neither matching —
    # so a wrong answer cannot pass by landing on a neighbouring arm.
    ("elif_arm_reads_a_module_constant",
     "K = 7\n"
     "\n"
     "def f(x: Int) -> Int:\n"
     "    if x == 0:\n"
     "        return 1\n"
     "    elif x == K:\n"
     "        return 2\n"
     "    return 0\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    return f(7)\n",
     2, None),
    # …and the same shape when only SOME of the arms name the constant, which is
    # what makes it a per-position bug rather than "elif is unsupported": a walk
    # that skipped elif conditions would substitute arm 1 and leave arm 2, so
    # the first call is right and the second is not. 4 arms here (3 elifs) also
    # covers the label chain at its longest.
    ("elif_chain_with_one_named_arm",
     "K = 7\n"
     "J = 9\n"
     "\n"
     "def f(x: Int) -> Int:\n"
     "    if x == 0:\n"
     "        return 1\n"
     "    elif x == K:\n"
     "        return 2\n"
     "    elif x == J:\n"
     "        return 3\n"
     "    elif x == 100:\n"
     "        return 4\n"
     "    return 0\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    # 2 and 3 name a constant; 1 and 4 do not. 1234 needs all four arms.\n"
     "    return f(0) * 1000 / 10 + f(7) * 100 / 10 + f(9) * 10 / 10 + f(100) / 100\n",
     123, None),
    # The class-constant rewrite is the SECOND walk with the same shape, and it
    # had the same one-position gap, so both spellings are here: through the
    # class's own name, and through a local aliased from its constructor (which
    # is how ordinary code reads one).
    ("elif_arm_reads_a_class_constant",
     "struct C:\n"
     "    var B: Int = 5\n"
     "\n"
     "def f(x: Int) -> Int:\n"
     "    if x == 0:\n"
     "        return 1\n"
     "    elif x == C.B:\n"
     "        return 2\n"
     "    return 0\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    return f(5)\n",
     2, None),
    ("elif_arm_reads_an_aliased_class_constant",
     "struct C:\n"
     "    var B: Int = 5\n"
     "\n"
     "def f(x: Int) -> Int:\n"
     "    var c = C()\n"
     "    if x == 0:\n"
     "        return 1\n"
     "    elif x == c.B:\n"
     "        return 2\n"
     "    return 0\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    return f(5)\n",
     2, None),
    # GUARD (passed before the change, and it is the case that says the fix is a
    # POSITION fix and not "elif got more permissive"): an `elif` chain over
    # plain literals was already correct, and 1234 is every arm. A fix that
    # rewrote the arm chain would break this row.
    ("elif_chain_of_literals_is_unchanged",
     "def f(x: Int) -> Int:\n"
     "    if x == 0:\n"
     "        return 1\n"
     "    elif x == 7:\n"
     "        return 2\n"
     "    elif x == 9:\n"
     "        return 3\n"
     "    elif x == 100:\n"
     "        return 4\n"
     "    return 0\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    return f(0) * 1000 / 10 + f(7) * 100 / 10 + f(9) * 10 / 10 + f(100) / 100\n",
     123, None),
    # ── a list literal longer than one instruction's immediate offset ──
    #
    # A blob element `i` is at byte `8*(i+1)` from the blob's base, and
    # `encode_str_xt_xn_imm`'s offset field is 12 bits SCALED by 8, so element
    # 4095 is the first one the STR-immediate form cannot name. A list literal
    # that long used to die inside that function's own
    # `assert 0 <= imm12 < 0x1000` — a bare AssertionError out of an encoder
    # three frames below anything that could name a limit, on a program whose
    # only problem is that it is large. The offset now goes in a REGISTER past
    # the immediate's reach (`_emit_blob_store`), and the limit that remains is
    # the frame's, which is stated in a message.
    #
    # 5000 is past the old assert and inside arm64's frame, so it is the row
    # that would have crashed. The `a[-1]` / `a[0]` pair is deliberate: a fix
    # that moved the far stores but not the far LOADS would build this, run it,
    # and read the wrong word back — the same function both ways, so the two
    # halves of the fix cannot be separated. Both expected values are taken
    # mod 256, which is what a POSIX exit status can carry.
    ("list_literal_past_the_immediate_offset",
     "def main(k: Int) -> Int:\n"
     "    var a = [" + ", ".join(str(i % 97) for i in range(5000)) + "]\n"
     "    return (a[0] + a[4999]) % 256\n",
     (0 + 4999 % 97) % 256, None),
    # GUARD for the same fix on the READ side, and the only way to tell "the
    # far stores landed" from "the far stores landed AND the far loads read
    # them": every element summed, through a subscript, on a 16000-element
    # blob. 16000 is 87% of arm64's frame budget, so it also pins that the
    # frame reservation and the element loop agree about the size.
    ("every_element_of_a_16000_element_list_reads_back",
     "def main(k: Int) -> Int:\n"
     "    var a = [" + ", ".join(str(i % 97) for i in range(16000)) + "]\n"
     "    var s: Int = 0\n"
     "    var i: Int = 0\n"
     "    while i < 16000:\n"
     "        s = s + a[i]\n"
     "        i = i + 1\n"
     "    return s % 251\n",
     sum(i % 97 for i in range(16000)) % 251, None),
    # The `range()` literal goes through the SAME element loop (the static
    # `range(0, n)` path materialises `n` words and stores them the same way),
    # so it had the same assert at the same element. This is the realistic way
    # to reach the limit — nobody writes a 4096-element list literal by hand —
    # and `a[4095]` is the far read.
    ("range_literal_past_the_immediate_offset",
     "def main(k: Int) -> Int:\n"
     "    var a = range(0, 6000)\n"
     "    return (a[0] + a[5999]) % 256\n",
     5999 % 256, None),
    # And the limit itself, which is the other half of the bug: "a stated limit
    # reported as a crash". 20000 words is 160008 bytes against a 131072-byte
    # frame, so this must be a `CodegenError` naming the budget — and BOTH
    # backends must produce the same shape, since the two have different
    # budgets (arm64 128 KB of scratch, x86-64 a 16 KB blob region) and a reader
    # comparing the two needs to see that the difference is the budget and not
    # the message. `refuse:` checks both, and the needle is the sentence the two
    # now share.
    ("refuse_list_literal_over_the_frame_budget",
     "def main(k: Int) -> Int:\n"
     "    var a = [" + ", ".join(["1"] * 20000) + "]\n"
     "    return len(a)\n",
     "refuse:does not fit in the frame: it needs", None),
    # ── a TYPE read where a value is required ──
    #
    # `t == NoneType` with `t` a `comptime` type parameter was refused as
    # "'NoneType' has no home: the register allocator collected no home for it …
    # This path places a name in a register or a spill slot allocated for THIS
    # function, a receiver field's frame, or a module-level constant the build
    # folded". That sentence is false about the file: a type is in none of those
    # four places because a type is not a value, and the reader was sent to the
    # register allocator for a fact about the language. The refusal itself is
    # right and stays — every one of these files is refused either way, so this
    # is a message-accuracy change and not a coverage one (measured: 32 of 664
    # stdlib files move off the false diagnosis, and the sweep's own class
    # counts are byte-identical before and after).
    # SUPERSEDED 2026-10-01, and converted rather than deleted.  These two
    # asserted the refusal `model.type_as_value_refusal` gave a type name read
    # as a value, which was the right answer while a type was not a value on
    # this path.  `formal-type-as-value` then made it one: a type is a word and
    # the word is a TAG (`model.type_tag`), so `t == NoneType` is an integer
    # comparison and a bare type read is that same tag.  Both programs are
    # therefore ANSWERABLE now, and a case left asserting the refusal would be a
    # test asserting the opposite of the truth — so each keeps its program and
    # its name and now pins the answer, against CPython running the same text.
    ("type_compared_with_a_comptime_parameter_compares",
     "def pick[t: DType](v: Int32) -> Int32:\n"
     "    if t == NoneType:\n"
     "        return 0\n"
     "    return v\n"
     "\n"
     "def main(n: Int32) -> Int32:\n"
     "    return pick[Int32](7)\n",
     7, None),
    # The other shape, with no comparison — the one a `from typing import List`
    # file reaches.  Compared against ITSELF rather than against a typed
    # constant, because that is the question a bare read can answer without a
    # hand-written constant: the word the bare read produced is the word the
    # comparison reads.
    ("a_bare_type_name_read_is_the_same_word_a_comparison_reads",
     "def main(n: Int) -> Int:\n"
     "    x = NoneType\n"
     "    if x == NoneType:\n"
     "        return 1\n"
     "    return 0\n",
     1, None),
    # GUARD (passes before and after, and it is the case that would catch the
    # over-correction): a type used as a CALLEE is a construction, which this
    # path lowers — `Int32(5)` is ordinary representable code. The new rule is
    # asked about a bare READ, and a callee is not a read (the same exclusion
    # `check_module_symbols` already makes for MLIR roots), so this must keep
    # building. A rule written as "any appearance of a type name" breaks it.
    ("type_as_a_callee_is_still_a_construction",
     "def main(n: Int32) -> Int32:\n"
     "    var x = Int32(5)\n"
     "    return x + 1\n",
     6, None),
    # GUARD (passes before and after): a genuinely unplaced VALUE keeps the
    # storage enumeration, because for a value that enumeration is the right
    # story. 41 of the 664 stdlib files are in exactly this position and they
    # are correct as they are; a rule that swallowed them into the type message
    # would be the over-correction in the other direction.
    ("refuse_an_unplaced_value_keeps_the_storage_story",
     "def main(n: Int) -> Int:\n"
     "    return rebind\n",
     "refuse:has no home: the module-level symbol table is empty", None),

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

# `a == b` on two FRAME ADDRESSES, which used to be a flag-setting compare of
# two words and therefore an answer about ADDRESSES: CPython's INHERITED
# `__eq__`, correct for a struct that declares none and a silent bypass of the
# one that does.  Three rows because the question has three answers and a fix
# that gets two of them right is the same defect again.
#
# The full case set for this construct, including the CPython-oracle comparison
# and the two refusals, is `test_formal_eq_dispatch.py`.  These three are here
# because this file is the registered suite job and a construct nothing in it
# exercises is a construct nothing in it can regress.
EQ_DISPATCH_CASES = [
    # The reproducer: `__eq__` that ignores its argument, reached through the
    # operator and through the explicit spelling in the same printf, because the
    # two are the same question asked twice and CPython makes them equal.
    # Pre-change on BOTH backends: `eq=0 direct=1`.
    ("eq_operator_reaches_a_declared_eq",
     "class Plain:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "def main(n):\n"
     "    var a = Plain(1, 2)\n"
     "    var b = Plain(3, 4)\n"
     "    printf(\"eq=%d direct=%d\\n\", 1 if a == b else 0,\n"
     "           1 if a.__eq__(b) else 0)\n"
     "    return 0\n", 0, "eq=1 direct=1"),
    # The GUARD, and the direction the fix must not move: no declared dunder, so
    # CPython's inherited IDENTITY comparison stands, which on this path is the
    # address compare that was always there.  `a == a` is 1, `a == b` is 0 for
    # two live objects, and `a == c` is 0 for two objects holding equal field
    # values.  A rewrite that fired on every comparison rather than on a
    # declared dunder would get the last two wrong.
    ("eq_no_declared_dunder_stays_identity",
     "class Bare:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "def main(n):\n"
     "    var a = Bare(1, 2)\n"
     "    var b = Bare(3, 4)\n"
     "    var c = Bare(1, 2)\n"
     "    printf(\"same=%d diff=%d cross=%d\\n\", 1 if a == a else 0,\n"
     "           1 if a == b else 0, 1 if a == c else 0)\n"
     "    return 0\n", 0, "same=1 diff=0 cross=0"),
    # AGREE-OR-REFUSE.  `v` holds an `A` or a `B` depending on the branch, and
    # only `B` declares a dunder, so which call the comparison lowers to depends
    # on the path and this analysis has no path sensitivity.  Pre-change this
    # BUILT and compared two addresses.
    ("eq_two_candidate_structs_are_refused",
     "class A:\n"
     "    x: int\n"
     "    y: int\n"
     "    def __init__(self, p, q):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "class B:\n"
     "    x: int\n"
     "    y: int\n"
     "    z: int\n"
     "    def __init__(self, p, q, r):\n"
     "        self.x = p\n"
     "        self.y = q\n"
     "        self.z = r\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "def main(n):\n"
     "    var v = A(1, 2)\n"
     "    if n:\n"
     "        v = B(1, 2, 3)\n"
     "    printf(\"r=%d\\n\", 1 if v == v else 0)\n"
     "    return 0\n",
     "refuse:compares two FRAME ADDRESSES", None),
    # A NAME THAT STOPS BEING A FRAME.  The holder set is additive, so
    # `r = 5` after `r = R()` leaves every `r.<field>` lowered as a load at
    # `[5 + 8·slot]`; measured on both architectures from a green build, SIGSEGV
    # exit 139 where the source says 5.  The refusal names the binding that
    # disagrees, because "r is a frame" and "r is a word" are the whole
    # disagreement and the reader has to be told which line settles it.
    ("holder_rebound_from_a_word_is_refused",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "def main(n):\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r = 5\n"
     "    return r.a\n",
     "refuse:r is assigned 5 in main()", None),
    # A LOCAL READ BEFORE IT HAS BEEN ASSIGNED, on a name that is also a
    # module-level binding.  The right-hand `G` does NOT resolve in module scope:
    # a name assigned anywhere in a function body is local to that body from its
    # first line, so CPython raises UnboundLocalError and the program has no
    # number.  What this path did was read the local's uninitialised register —
    # 78152773 on arm64 and 11 on x86-64 from identical source.  It is also where
    # bugs/FORMAL_local_shadows_module_global's proposed fix is corrected:
    # making the gate order-dependent would answer 6, a number CPython never
    # produces.
    ("a_local_read_before_its_assignment_is_refused",
     "G = 5\n"
     "def bump():\n"
     "    G = G + 1\n"
     "    return G\n"
     "def main(n):\n"
     "    return bump()\n",
     "refuse:G is read in bump() at `G + 1`", None),
    # The sibling the filing did not mention: the same name WRITTEN through a
    # `global` declaration, which the language allows and the value model has
    # nowhere for.  There is no storage a write could outlive a frame in, so both
    # emitters treat the declaration as a no-op — CPython answers 6 and 6 where
    # this path answered 10601485 and 5 on arm64 and 11 and 5 on x86-64.
    ("a_mutated_module_global_is_refused",
     "G = 5\n"
     "def bump():\n"
     "    global G\n"
     "    G = G + 1\n"
     "    return G\n"
     "def rd():\n"
     "    return G\n"
     "def main(n):\n"
     "    return bump() + rd()\n",
     "refuse:G is declared `global` in bump() and assigned there", None),
]


# ── SILENT WRONG ANSWERS in the arm64 lowering ─────────────────────────────
#
# Every case in this group builds an image, EXECUTES it, and compares with
# CPython running the same program. That is the whole point of putting them
# here rather than in `test_armal_encoders.py` or a model test: each of the
# five defects below produced an image that was a perfectly good Mach-O file,
# encoded a real instruction, and computed a number the source never wrote.
# A test that checked the encoding or the model would have been green
# throughout.
#
# THE SHAPE OF EACH GROUP. Where a defect has a wrong answer and a right one
# that a plausible-looking "fix" would swap, BOTH are pinned, and the comment
# says which is which. A test that pins only the newly-fixed case invites the
# over-correction: making every `>>` logical, or making every shift saturate
# to 0 regardless of sign, are each correct for one row here and wrong for
# another.
SHIFT_CASES = [
    # ── `<<` by an IMMEDIATE amount (the UBFM encoder) ───────────────────
    #
    # `encode_lsl_xd_xn_imm` used base `0xd3780000` while its own docstring
    # said `0xd3400000`; the difference sits inside `immr`'s field, and the
    # code ORs the real `immr` into the same field, so the emitted shift
    # amount was `immr_intended | 0x38`. The amounts where that OR is
    # harmless are EXACTLY 1..8 — so `1 << 8` was right and `1 << 12` was
    # 16. The amounts below are spread across the broken range deliberately,
    # and `lsl_imm_amount_8` is here to say that the surviving amounts are
    # still right: a fix that shifted the whole range would pass the others.
    #
    # Every value is asserted through STDOUT rather than through the exit
    # status, because a process exit status is 8 bits and `1 << 12` is
    # 4096. The exit code carries "it ran", which is its own assertion.
    ("lsl_imm_amount_8",
     "def f(x):\n    return x << 8\n"
     "def main(n):\n    printf(\"%ld\", f(1))\n    return 0\n", 0, "256"),
    ("lsl_imm_amount_9",
     "def f(x):\n    return x << 9\n"
     "def main(n):\n    printf(\"%ld\", f(1))\n    return 0\n", 0, "512"),
    ("lsl_imm_amount_12",
     "def f(x):\n    return x << 12\n"
     "def main(n):\n    printf(\"%ld\", f(1))\n    return 0\n", 0, "4096"),
    ("lsl_imm_amount_20",
     "def f(x):\n    return x << 20\n"
     "def main(n):\n    printf(\"%ld\", f(1))\n    return 0\n", 0, "1048576"),
    # 63 is the largest amount that is not a saturation, and it is the row
    # that pins the high end of the immediate range. Printed as hex because
    # `1 << 63` is negative when read as a signed decimal.
    ("lsl_imm_amount_63",
     "def f(x):\n    return x << 63\n"
     "def main(n):\n    printf(\"%lx\", f(1))\n    return 0\n",
     0, "8000000000000000"),
    # The VARIABLE form was always right (LSLV, a different instruction with
    # its own encoding), and it is here so the immediate fix cannot have been
    # made by changing the shared shift path.
    ("lsl_variable_amount_12",
     "def f(x, n):\n    return x << n\n"
     "def main(k):\n    printf(\"%ld\", f(1, 12))\n    return 0\n", 0, "4096"),
    # ── a shift amount at or past the word's width SATURATES ─────────────
    #
    # The hardware takes the amount modulo 64, so `3 >> 64` was `3` and
    # `3 << 64` was `3`, on BOTH backends — they were written to the same
    # wrong rule. CPython saturates.
    ("shr_amount_64_is_zero",
     "def f(x, n):\n    return x >> n\n"
     "def main(k):\n    printf(\"%ld\", f(3, 64))\n    return 0\n", 0, "0"),
    ("shr_amount_65_is_zero",
     "def f(x, n):\n    return x >> n\n"
     "def main(k):\n    printf(\"%ld\", f(3, 65))\n    return 0\n", 0, "0"),
    ("shl_amount_64_is_zero",
     "def f(x, n):\n    return x << n\n"
     "def main(k):\n    printf(\"%ld\", f(3, 64))\n    return 0\n", 0, "0"),
    # 63 is the largest amount that must STILL SHIFT, and it is here
    # precisely so that a fix which saturates at 63 by accident rather than
    # by rule is distinguishable from one that does it on purpose. The
    # immediate form cannot express 63 as an exit status, so the value is
    # printed and the exit code carries the assertion.
    ("shl_amount_63_still_shifts",
     "def f(x, n):\n    return x << n\n"
     "def main(k):\n    printf(\"%lx\", f(1, 63))\n    return 0\n", 0,
     "8000000000000000"),
    # ── the SATURATED value is not 0 for an arithmetic right shift ───────
    #
    # Python's `>>` on a negative value is an ARITHMETIC shift: it rounds
    # toward negative infinity, so the sign bit keeps being replicated no
    # matter how far the shift goes. `-5 >> 4` is -1, not -2, and `-5 >> 64`
    # is -1 rather than 0. A saturation that returned 0 for every amount at
    # or past 64 would be right for `<<` and for every non-negative `>>`, and
    # wrong for exactly the negative operands a bit-manipulating algorithm
    # produces by subtracting.
    ("shr_negative_amount_64_is_minus_one",
     "def f(x, n):\n    return x >> n\n"
     "def main(k):\n    printf(\"%ld\", f(0 - 5, 64))\n    return 0\n", 0, "-1"),
    # 128, not a rounder number, and the choice is the point: it is the
    # second amount whose low six bits are ZERO, so it is the second amount
    # the hardware turns into a shift by none. (100 would not discriminate —
    # 100 & 63 is 36, and `-5 >> 36` is already -1, so the old code passed
    # this row by coincidence.)
    ("shr_negative_amount_128_is_minus_one",
     "def f(x, n):\n    return x >> n\n"
     "def main(k):\n    printf(\"%ld\", f(0 - 5, 128))\n    return 0\n", 0, "-1"),
    ("shl_negative_amount_64_is_zero",
     "def f(x, n):\n    return x << n\n"
     "def main(k):\n    printf(\"%ld\", f(0 - 5, 64))\n    return 0\n", 0, "0"),
    # The in-range arithmetic shift, which the same fix must NOT change:
    # `-5 >> 1` is `-3`, so a "fix" that made every `>>` logical would fail
    # this row while passing the two above it.
    ("shr_negative_in_range_is_arithmetic",
     "def main(n):\n    a = 0 - 5\n    b = a >> 1\n    if b == 0 - 3:\n"
     "        return 1\n    return 0\n", 1, None),
    # ── the fill comes from the VALUE, not from the shift AMOUNT ─────────
    #
    # `UInt64 >> Int` computed 0xFFFFFFFFFFFFFFFF >> 4 as 0xFFFFFFFFFFFFFFFF
    # (arithmetic) where the answer is 0x0FFFFFFFFFFFFFFF (logical): the
    # amount is a COUNT, and `common_type` is signed-wins, so an unannotated
    # (hence signed) count won the promotion and then decided the fill.
    # The rows differ ONLY in how the amount is spelled, which is the
    # diagnostic: the amount is the same number 4 in all of them.
    ("ushift_u64_by_typed_int_amount",
     "def ushr(x: UInt64, n: Int) -> UInt64:\n    return x >> n\n"
     "def main(k: Int) -> Int:\n"
     "    var a: UInt64 = 18446744073709551615\n"
     "    printf(\"%016lx\", ushr(a, 4))\n    return 0\n", 0,
     "0fffffffffffffff"),
    ("ushift_u64_by_typed_u64_amount",
     "def ushr(x: UInt64, n: UInt64) -> UInt64:\n    return x >> n\n"
     "def main(k: Int) -> Int:\n"
     "    var a: UInt64 = 18446744073709551615\n"
     "    printf(\"%016lx\", ushr(a, 4))\n    return 0\n", 0,
     "0fffffffffffffff"),
    ("ushift_u64_by_literal_amount",
     "def ushr(x: UInt64) -> UInt64:\n    return x >> 4\n"
     "def main(k: Int) -> Int:\n"
     "    var a: UInt64 = 18446744073709551615\n"
     "    printf(\"%016lx\", ushr(a))\n    return 0\n", 0, "0fffffffffffffff"),
    # ...and the VARIABLE amount, which was wrong for the same reason and is
    # the shape a real bit-manipulating algorithm uses.
    ("ushift_u64_by_variable_amount",
     "def ushr(x: UInt64, n: Int) -> UInt64:\n    var k = n\n    return x >> k\n"
     "def main(k: Int) -> Int:\n"
     "    var a: UInt64 = 18446744073709551615\n"
     "    printf(\"%016lx\", ushr(a, 4))\n    return 0\n", 0,
     "0fffffffffffffff"),
    # ── the AUGMENTED spelling, which is a SECOND shift emitter ──────────
    #
    # `y <<= n` is the same operator as `y = y << n` and it reached a
    # different emitter: arm64's `_emit_shift_reg` and x86-64's augmented
    # arm each had their own shift, neither of which knew about the
    # saturation rule. So `y <<= 64` left `y` unchanged while
    # `y = y << 64` zeroed it — one operator, two answers, in the same
    # program. These rows are what caught it, and they are the reason the
    # rule now lives in ONE emitter per backend that both spellings reach.
    ("augmented_shl_amount_64_is_zero",
     "def f(x, n):\n    var y = x\n    y <<= n\n    return y\n"
     "def main(k):\n    printf(\"%ld\", f(3, 64))\n    return 0\n", 0, "0"),
    ("augmented_shr_amount_64_is_zero",
     "def f(x, n):\n    var y = x\n    y >>= n\n    return y\n"
     "def main(k):\n    printf(\"%ld\", f(3, 64))\n    return 0\n", 0, "0"),
    # The augmented unsigned shift, same defect and same fix: the fill came
    # from the promoted type of the AMOUNT rather than from the value.
    ("augmented_ushift_u64_by_typed_int_amount",
     "def f(x: UInt64, n: Int) -> UInt64:\n    var y = x\n    y >>= n\n"
     "    return y\n"
     "def main(k: Int) -> Int:\n"
     "    var a: UInt64 = 18446744073709551615\n"
     "    printf(\"%016lx\", f(a, 4))\n    return 0\n", 0, "0fffffffffffffff"),
    # ...and the in-range augmented shift, which must be UNCHANGED: a fix
    # that saturated every augmented shift would pass the two above.
    ("augmented_shift_in_range_still_shifts",
     "def f(x, n):\n    var y = x\n    y <<= n\n    return y\n"
     "def main(k):\n    printf(\"%ld\", f(1, 12))\n    return 0\n", 0, "4096"),
    # A SIGNED value is still arithmetic even when the amount is unsigned.
    # Without this row, "the amount never decides the fill" could be
    # satisfied by refusing to decide at all.
    ("signed_shift_by_unsigned_amount_stays_arithmetic",
     "def sshr(x: Int, n: UInt64) -> Int:\n    return x >> n\n"
     "def main(k: Int) -> Int:\n"
     "    if sshr(0 - 5, 1) == 0 - 3:\n        return 1\n    return 0\n", 1, None),
]


# `origin_of(x)` — the COMPILE-TIME IDENTITY, and the seven stdlib files it
# un-blocks are measured in `bugs/FORMAL_frame_by_value_ceiling_zero.md`.
#
# `origin_of` is in the corpus almost entirely as a TYPE argument —
# `Self.IteratorType[origin_of(self)]`, `Pointer[Deque[T], origin_of(self)]` —
# and the escape check refused every one of those as "a frame address is passed
# to `origin_of()`, which is lowered as an operation on a VALUE: it wants the
# object itself … so what would arrive is the address `origin_of()` would then
# dereference as one". Every clause after "is passed" is false: `origin_of` has
# no body on this path, so there is no call to emit and nothing dereferences the
# word. The interpreter this project treats as the reference for the language
# says the same thing in one line — `myinterpreter.py` defines it as
# `lambda x, *args, **kwargs: x` — so the identity is an ORACLE here, not a
# judgement call, and these cases are written so that the expected values can be
# read off the source.
#
# It is a REWRITE (`formal/build.py`'s `_rewrite_identity_intrinsic_calls`) and the two
# refusals below are why: an emitter-level lowering leaves `origin_of(s)` in the
# tree the build pass has already walked, and a frame address then walks through
# the return check, a variadic C call and a container with none of them able to
# see it. Both of those BUILT and ran before the rewrite existed.
ORIGIN_OF_CASES = [
    # The corpus's own shape: a comptime bracket naming the receiver's origin.
    # `tag` never reads `origin`, so the bracket is a type token, and the value
    # that matters is `s.a` — 3, doubled, plus `s.b`. The frame is not disturbed
    # and the arithmetic is the source's: 3*2 + 4 = 10.
    #
    # This is the case that was refused, on both architectures, with the message
    # quoted above.
    ("origin_of_in_a_comptime_bracket_is_the_identity",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def tag[origin: AnyType](x: Int) -> Int:\n"
     "    return x * 2\n\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S()\n"
     "    s.a = 3\n"
     "    s.b = 4\n"
     "    return tag[origin_of(s)](s.a) + s.b\n", 10, None),
    # The same construct on a PLAIN VALUE, and the row that shows the change is
    # about `origin_of` rather than about frames: before it, `origin_of(k)` was
    # emitted as a call to a symbol nothing in this image defines, so the build
    # died at the link check with "the image would bind 1 symbol(s) that
    # nothing provides: origin_of" — a message about a missing symbol rather
    # than about the construct. 7 + 10 = 17, which is `origin_of`'s own
    # definition read off the source.
    ("origin_of_of_a_plain_value_is_the_value",
     "def main(n: Int) -> Int:\n"
     "    var k = 7\n"
     "    var o = origin_of(k)\n"
     "    return o + 10\n", 17, None),
    # The frame ALIASING an origin names, which is what the construct is FOR:
    # writing through `o` writes the same slot `t` reads. 9*1000 + 6*10 + 9 is
    # 9069, and all three terms are the source's own: `o.a = 9` first, so
    # `t.a`, `t.b` (untouched) and `o.a` (the same slot) are 9, 6 and 9.
    #
    # This is the row that would catch a lowering which copied the frame instead
    # of aliasing it, and it is measured on both architectures, which agree on
    # 9069 — a copy of the address would not.
    ("origin_of_a_frame_aliases_the_frame_it_names",
     "struct Bag:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var t = Bag()\n"
     "    t.a = 5\n"
     "    t.b = 6\n"
     "    var o = origin_of(t)\n"
     "    o.a = 9\n"
     "    printf(\"%d\", t.a * 1000 + t.b * 10 + o.a)\n"
     "    return 0\n", 0, "9069"),
    # A control, and it is reported as one: this built BEFORE the change and
    # still builds, on both architectures. A type ANNOTATION is not a runtime
    # expression, so nothing is emitted for the `origin_of` in it and the
    # escape check — which walks `fn.body` for statements — never saw it.
    #
    # It is here because the rewrite walks the same tree and an annotation IS
    # reachable from `fn.body` (this one is a local's, one field of a VarDecl),
    # so a rewrite that mangled one would be mangling something the emitters do
    # not read, and the only way to know it does not is to build the thing. The
    # value is the source's: `Marker(b.a)` is 7 and `.v` is that field.
    ("origin_of_in_a_local_type_annotation_is_still_a_type",
     "struct Marker[T: AnyType]:\n"
     "    var v: Int\n\n"
     "struct Bag:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def tag(ref b: Bag) -> Int:\n"
     "    var m: Marker[origin_of(b)] = Marker(b.a)\n"
     "    return m.v\n\n"
     "def main(n: Int) -> Int:\n"
     "    var g = Bag()\n"
     "    g.a = 7\n"
     "    g.b = 8\n"
     "    return tag(g)\n", 7, None),
]

# The rewrite erases the CALL, not the CHECK. Every row here is a construct that
# the build pass refuses when the frame address reaches it directly, and each one
# was BUILT AND RAN when the identity was lowered in the emitters instead —
# which is the reason it is a rewrite. `formal/build.py`'s
# `_rewrite_identity_intrinsic_calls` carries the two measurements; these are them as
# regressions, on both architectures.
ORIGIN_OF_REFUSALS = [
    # Returned. `return s` is `frame_return_refusal`, and the frame is reclaimed
    # when this function returns, so the word is a dangling address. With the
    # identity in the emitters this BUILT, RAN, and returned the frame's own
    # address modulo 256 — silently, with the program exiting 0.
    # The EXPECTED WORDS are `model.entry_frame_return_refusal`'s rather than
    # the lifetime sentence this case was written against, and that is the
    # improvement rather than a loosened assertion: the program returns a frame
    # from `main`, so it is not "a receiver is returned from the function that
    # created it" — a rule the reader has to re-derive — but "there is no
    # caller to reserve a block for", which is the whole fact. That model's
    # docstring says so, naming this exact older wording as the one it replaces.
    # Both architectures, one shared message (`_ABI_ARG_REGS`'s twin asks it in
    # `formal/x86_64_codegen.py`).
    ("origin_of_refuse_returning_the_frame",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S()\n"
     "    s.a = 3\n"
     "    s.b = 4\n"
     "    return origin_of(s)\n",
     "refuse:is this image's ENTRY", None),
    # A VARIADIC C call. This is the exact failure
    # `FRAME_C_VALUE_CALLS`'s own message cites ("measured, `printf(\"val=%d\n\",
    # r)` builds, runs, prints the frame's address as a decimal, and exits 0"),
    # reached through a door the identity opened: with the emitters doing it,
    # `printf("%d\n", origin_of(s))` printed 1793355120 and exited 0.
    #
    # The needle names `printf`, which is what makes this a test of the
    # hand-off and not of the construct: the refusal has to be the one about a
    # wrong CATEGORY of argument, and the address must never reach the format
    # string's conversion.
    ("origin_of_refuse_a_variadic_c_call_still_reads_a_value",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S()\n"
     "    s.a = 3\n"
     "    s.b = 4\n"
     "    printf(\"%d\\n\", origin_of(s))\n"
     "    return 0\n",
     "refuse:passed to printf()", None),
    # A CONTAINER, and a GENUINE one — `[s, 1]` is a list literal, not a
    # subscript's argument list, so this row is the control for
    # `TYPE_ARGUMENT_LIST_CASES` below and the reason that group's escape-check
    # skip could not have caught this one. It used to be mislabelled: the
    # comment here called the list "a subscript's argument list", so it drew a
    # complaint about the wrong reason and it is what made the REAL defect
    # (`Box[Int, s]`, which has no `origin_of` in it at all) look like this
    # row. The answer was right and the reasoning was not; both fixed in
    # `30e5e2e9`.
    ("origin_of_refuse_a_frame_in_a_container",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S()\n"
     "    s.a = 3\n"
     "    s.b = 4\n"
     "    return [origin_of(s), 1][0]\n",
     "refuse:is stored in a container", None),
]


# `Foo[A, frame]` — a bracket list that is a TYPE ARGUMENT list and not a
# container, and the two false sentences it used to draw.
#
# It arrived as the SAME `TupleExpr` as `[s, 1]`, and `formal/build.py`'s
# escape check refused it as "is stored in a container, which has no layout for
# a frame address" — a sentence about a lifetime the program does not have,
# which is the false diagnosis that cost the most because it sends the reader
# to look for an escape that is not there. Four stdlib files drew it
# (`std/builtin/tuple.mojo`, `std/collections/{deque,linked_list,set}.mojo`;
# measured in `bugs/FORMAL_frame_by_value_ceiling_zero.md`).
#
# Every row here is a REFUSAL, and that is not a gap in the fix: a type
# application is a compile-time construct this backend still cannot lower, and
# the honest answer for it is the model's own — "a compile-time
# explicit-parameter list on a generic, not a subscript", from
# `model.multi_index_kind`'s `MULTI_INDEX_COMPTIME_PARAMS`. What changed is
# WHICH sentence, so `refuse_without:` is the load-bearing prefix here: a fix
# that merely appended the true one would leave both rows passing.
#
# Four stdlib files land on four OTHER causes and 0 reach `pass` — the ceiling
# of map row 7 is measured at 0 and this change does not move it.
TYPE_ARGUMENT_LIST_CASES = [
    # The corpus's own base: a TYPE CONSTRUCTOR. `Pointer` is in
    # `IDENTITY_TYPE_CTORS`, so `type_constructor_kind("Pointer")` answers
    # before any table of this module's own declarations is consulted — which is
    # the half of the decision that needs nothing but the name.
    #
    # `var m = …` binds a name to the application, so it is also a check that
    # the classification does not depend on the subscript being in CALLEE
    # position. Refused on both architectures before this change, with the
    # container sentence.
    ("type_argument_list_on_a_type_constructor",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S()\n"
     "    s.a = 3\n"
     "    s.b = 4\n"
     "    var m = Pointer[Int, s]\n"
     "    return s.a\n", "refuse:compile-time explicit-parameter list", None),
    # The other half, and the one no name table can answer: a struct THIS MODULE
    # declares. `_DequeIter[Self.ElementType, origin_of(self), False]` in
    # `std/collections/deque.mojo` is this shape, and it is here because
    # `structs_by_name` is the only thing that settles it — a declared struct
    # has no runtime container representation at all, so a subscript on its name
    # cannot be a lookup into one.
    ("type_argument_list_on_a_struct_this_unit_declares",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "struct Triple[A: AnyType, B: AnyType, C: AnyType]:\n"
     "    var v: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S()\n"
     "    s.a = 3\n"
     "    s.b = 4\n"
     "    var m = Triple[Int, s, False](5)\n"
     "    return m.v + s.a\n", "refuse:compile-time explicit-parameter list", None),
    # NO FRAME ANYWHERE, which is what pins the change as being about the
    # CONSTRUCT rather than about the escape check. Every row above could be
    # satisfied by a fix that only reworded the frame-address refusal; this one
    # has no frame address to reword. `Box[Int, Int]` is the case the stdlib
    # writes, and it drew "is a subscript whose index is a tuple — it is one of
    # two things: a lookup keyed by the tuple … or a two-dimensional index",
    # which is about a container lookup that cannot happen when the base is a
    # type.
    ("type_argument_list_without_any_frame",
     "struct Box[T: AnyType, U: AnyType]:\n"
     "    var v: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var m = Box[Int, Int](7)\n"
     "    return m.v\n", "refuse:compile-time explicit-parameter list", None),
    # THE COUNTER-CASES, and they are the whole reason the change is a narrow
    # skip rather than a deletion of the container branch. Every escape the
    # branch exists for has a base that is a DICT or a LIST, and no type name is
    # either, so all four keep the sentence they had. Without these rows a fix
    # that read every bracket list as a type application would pass the three
    # above and silently accept a program that parks a frame address in a dict's
    # storage.
    ("a_dict_key_tuple_holding_a_frame_is_still_a_store",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S()\n"
     "    s.a = 3\n"
     "    s.b = 4\n"
     "    var d = {1: 0, 2: 0}\n"
     "    d[s, 1] = 5\n"
     "    return d[1, 1]\n", "refuse:is stored in a container", None),
    ("a_list_index_tuple_holding_a_frame_is_still_a_store",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S()\n"
     "    s.a = 3\n"
     "    s.b = 4\n"
     "    var l = [0, 1, 2, 3]\n"
     "    var k = l[s, 1]\n"
     "    return k\n", "refuse:is stored in a container", None),
    # A bracket list over a base this unit CANNOT classify — the limit the fix
    # deliberately does not cross. `Self.IteratorType[origin_of(self)]` is the
    # corpus's shape and it IS a comptime parameter list, but deciding it needs
    # the IMPORTED module's declarations, which is `formal/imports.py`'s
    # question. This row pins that such a base is still refused, and NOT that
    # the wording improves: `_base_name` answers None for anything but a bare
    # `IdentExpr`, so a dotted base is not asked the question at all.
    ("a_bracket_list_over_a_dotted_base_is_still_refused",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "struct Alias:\n"
     "    var tag: Int\n"
     "    var v: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S()\n"
     "    s.a = 3\n"
     "    s.b = 4\n"
     "    var h = Alias()\n"
     "    h.tag = 1\n"
     "    h.v = 2\n"
     "    var m = h.tag[Int, s]\n"
     "    return s.a\n",
     "refuse:is stored in a container", None),
]

# THE FALSE SENTENCES, as assertions of their ABSENCE. `refuse_without:` exists
# for exactly this class — a fix that appends a correct clause beside an
# incorrect one leaves every `refuse:` above green while the reader is still
# sent to a non-bug, and that is how "a formal value is one 64-bit word, and
# DType is not one thing" survived beside a corrected first clause. Two
# sentences are pinned here because two were false about the same construct.
TYPE_ARGUMENT_LIST_ABSENT_CASES = [
    ("no_container_store_sentence_about_a_type_argument_list",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S()\n"
     "    s.a = 3\n"
     "    s.b = 4\n"
     "    var m = Pointer[Int, s]\n"
     "    return s.a\n",
     "refuse_without:compile-time explicit-parameter list:is stored in a container",
     None),
    ("no_tuple_index_sentence_about_a_type_argument_list",
     "struct Box[T: AnyType, U: AnyType]:\n"
     "    var v: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var m = Box[Int, Int](7)\n"
     "    return m.v\n",
     "refuse_without:compile-time explicit-parameter list:whose index is a tuple",
     None),
]


# The ninth-argument and read-before-store rows are REFUSALS, and they are in
# their own group because they assert a DIAGNOSTIC rather than a value — the
# whole point is that the program must not build, so no exit status can carry
# the assertion. `refuse:` also pins both backends to the same words, which is
# the property these two fixes are really about: one language, two machines.
REFUSAL_CASES = [
    # A function of NINE parameters read its ninth as ZERO: the callee's
    # prologue `break`ed out of the argument loop at i == 8 and `_emit_call`
    # dropped the extra arguments after evaluating them for side effects.
    # `nine(1,...,9)` returned 1 where the source says 90001.
    #
    # Zero is the worst possible wrong answer here, and the reason is
    # structural: a callee cannot tell a dropped argument from a caller who
    # passed zero, so the value is not merely wrong but INDISTINGUISHABLE from
    # a legitimate one. x86-64 has refused this program since it was written,
    # which is the evidence the author knew the class existed and arm64 was
    # the side left open.
    #
    # The needle names the arity and the limit and not the backend, so the
    # two architectures' differing register counts (8 vs 6) do not have to
    # be spelled twice.
    ("nine_arguments_refused",
     "def nine(a0: int, a1: int, a2: int, a3: int, a4: int,\n"
     "         a5: int, a6: int, a7: int, a8: int) -> int:\n"
     "    return a8 * 10000 + a0\n\n"
     "def main() -> int:\n"
     "    printf(\"nine=%d\", nine(1, 2, 3, 4, 5, 6, 7, 8, 9))\n    return 0\n",
     "refuse:9 arguments exceeds the", None),
    # The CALLEE end of the same convention, reached with no call site at
    # all — a dylib export, or an entry point the driver calls directly. It
    # refused on the arity rather than `break`ing, which left the parameter's
    # home slot never written and made the first read a build-dependent word.
    ("nine_parameters_refused_without_a_call_site",
     "def nine(a0: int, a1: int, a2: int, a3: int, a4: int,\n"
     "         a5: int, a6: int, a7: int, a8: int) -> int:\n"
     "    return a8 * 10000 + a0\n\n"
     "def main() -> int:\n"
     "    printf(\"x=%d\", 7)\n    return 0\n",
     "refuse:9 parameters exceeds the", None),
    # EIGHT arguments is the boundary and it must still WORK: the fix is a
    # refusal past the limit, not a smaller limit. Without this row a fix
    # that cut the ABI to 6 to match x86-64 would pass the two above.
    ("eight_arguments_still_work",
     "def eight(a0: int, a1: int, a2: int, a3: int, a4: int,\n"
     "          a5: int, a6: int, a7: int) -> int:\n"
     "    return a7 * 1000 + a6 * 100 + a5 * 10 + a0\n\n"
     "def main() -> int:\n"
     "    printf(\"eight=%d\", eight(1, 2, 3, 4, 5, 6, 7, 8))\n    return 0\n",
     0, "8761"),
    # A name read before anything in the function stores it. CPython raises
    # UnboundLocalError; this path cannot, because the emitted image has no
    # way to mean "unbound" — the allocator gave the name a register (the
    # function assigns it somewhere) and the read returned whatever the
    # CALLER left in it, a word that changed with the build and disagreed
    # between the two backends.
    ("read_before_store_in_a_loop_refused",
     "def f():\n"
     "    for i in range(3):\n"
     "        G = G + i\n"
     "    printf(\"G=%d\", G)\n"
     "f()\n",
     "refuse:is read at line 3 before anything in this function stores it",
     None),
    # The same defect at MODULE level, where CPython's error is NameError
    # rather than UnboundLocalError. Both spellings are in the diagnostic.
    # The EXPECTED WORDS are `model.read_before_store_refusal`'s as the branch
    # rewrote it, and the rewrite is an improvement rather than a loosened
    # assertion: this program has TWO facts about `x` — the module body assigns
    # it, so it is a local from its first line, and it is also a module-level
    # binding — and the old sentence reported neither, while the new one names
    # the collision, quotes CPython's own error, and gives the two measured
    # wrong answers (11 on x86-64, 78152773 on arm64) the old one could not.
    # The refusal is the same refusal; pinned on a phrase only the new text has.
    ("read_before_store_at_module_level_refused",
     "x = x + 1\n"
     "printf(\"x=%d\", x)\n",
     "refuse:does NOT resolve in module scope until after the assignment",
     None),
    # The AUGMENTED spelling, which reads more like ordinary code than
    # `x = x + 1` does and is the one most likely to be missed.
    ("augmented_read_before_store_refused",
     "def f(n):\n"
     "    total += n\n"
     "    printf(\"total=%d\", total)\n"
     "    return 0\n",
     "refuse:is read at line 2 before anything in this function stores it",
     None),
    # THE CONTROLS, and they are the reason the three above are believable:
    # each is a name that IS stored before it is read, in a shape close
    # enough to the refused ones that a check which refused them would be
    # refusing working code. A false refusal is the worse error — it breaks a
    # program that runs — so these rows are as load-bearing as the refusals.
    ("stored_before_read_still_builds",
     "def f(n):\n"
     "    y = 0\n"
     "    for i in range(3):\n"
     "        y = y + i\n"
     "    printf(\"y=%d\", y)\n    return 0\n",
     0, "y=3"),
    # A `for` target is bound before its body runs, so `total += v` reads a
    # stored `v`. The row is here because a check that treated the target as
    # unstored would refuse the single most ordinary accumulator in the
    # language.
    ("for_target_is_stored_for_its_own_body",
     "def f(n):\n"
     "    var s = 0\n"
     "    for v in [1, 2, 3]:\n"
     "        s = s + v\n"
     "    printf(\"s=%d\", s)\n    return 0\n",
     0, "s=6"),
    # A name assigned only inside an `if` is NOT this case: whether the
    # register holds a value depends on which arm ran, which is the
    # reachability question this check does not attempt. Pinning that it
    # still BUILDS records the deliberate limit rather than leaving it to be
    # discovered as a new bug (bugs/FORMAL_read_before_store_dominating_store.md).
    ("branch_local_still_builds",
     "def f(n):\n"
     "    if n:\n"
     "        p = 1\n"
     "    printf(\"p=%d\", p)\n    return 0\n",
     0, "p=1"),
    # A comprehension's generator target is bound inside its own scope, so
    # `[i + 1 for i in xs]` is not a read of an unstored `i`. This is the row
    # that a flat node walk gets wrong, and it was wrong here: the first
    # version of the check reported it and refused a working program.
    ("comprehension_target_is_not_an_unstored_read",
     "def f(n):\n"
     "    var xs = [1, 2, 3]\n"
     "    var ys = [i + 1 for i in xs]\n"
     "    printf(\"y=%d\", len(ys))\n    return 0\n",
     0, "y=3"),
]


# ── A TYPE APPLICATION, and the empty container ────────────────────────────
#
# Every answered case here is a PAIR of programs: the Mojo text the formal
# backends build, and the CPython text that must print the same thing. The
# expected value is not written down anywhere in this file — it is whatever
# CPython prints, computed at test time by actually running CPython — so a case
# cannot pass because a hand-derived constant happened to be right about a
# lowering that is wrong.
#
# WHY THE PAIR RATHER THAN ONE TEXT. `List[Int]()` is not valid Python
# (`typing.List[int]()` raises `TypeError`) and `printf` is not a Python
# function, so "run the same source through both" is not available for this
# construct, and pretending otherwise would mean asserting a constant. The pair
# is the honest form: two spellings of one computation, and the equality
# asserted is of the OUTPUT.
#
# WHAT WAS BROKEN, and why it was filed as worth 41 sweep files and 0 coverage.
# `List[Int]()` — a subscript in CALLEE position — was refused by
# `formal/build.py`'s name-placement walk with "'List' has no home: the
# module-level symbol table is empty for this unit … the register allocator
# collected no home for it", because the walk exempted a BARE callee and a
# subscript callee's base fell through to the name-placement rules. That
# sentence is false about the file: `List` is a TYPE, it is in none of the four
# places a value can be, and no amount of reading `_load_var` would have found
# anything. 41 files of the 2026-09-30 sweep were filed under it, 35 of them
# through `std/collections/binary_heap.mojo`'s `self._data = List[Self.T]()`.
#
# TWO SEPARATE FIXES, and the rows below exist to tell them apart:
#   * the walk no longer places a subscript callee — a CALL-SITE exemption, so
#     `len(List)` (the same spelling in a value position) still refuses and
#     `var xs: List[Int]` (a type in a non-callee position) is untouched;
#   * the zero-operand container constructor now LOWERS, to the eight-byte blob
#     that IS the empty container, on BOTH architectures. x86-64 could not do
#     this before: its `_callee_symbol` has no `SubscriptExpr` arm (arm64's has
#     had one for a long time), so a bracketed call target was refused on that
#     architecture alone. The gap itself is NOT closed — the x86-64 backend's
#     own comment says so and names what would close it — but this construct is
#     answered on both, by the same two shared predicates rather than by a third
#     private copy of the flattening.
#
# `bugs/FORMAL_sweep_work_map_2026-09-30.md` §3.1 is where the "worth 41 files
# and 0 coverage" is measured: `binary_heap.mojo` is behind two further limits
# (premise B2, and an `Optional` niche), so all 41 files stay refused and the
# value of this fix is the diagnostic and the construct, not the count.
TYPE_APPLICATION_CASES = [
    # The construct itself, in the spelling that was refused. `len` of an empty
    # container is 0, and 0 is what CPython prints for `len([])`.
    ("empty_list_constructor_len_is_zero",
     "def main() -> Int:\n"
     "    var xs = List[Int]()\n"
     "    printf(\"len=%d\", len(xs))\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n    xs = []\n"
     "    sys.stdout.write(\"len=%d\" % len(xs))\n"),
    # The BARE spelling of the same type. It reached a DIFFERENT refusal before
    # ("constructing List has no representation on this path") and must land on
    # the same answer, which is the whole reason the decision is
    # `model.empty_blob_constructor` rather than a recognition of the bracket.
    ("empty_list_constructor_bare_len_is_zero",
     "def main() -> Int:\n"
     "    var xs = List()\n"
     "    printf(\"len=%d\", len(xs))\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n    xs = []\n"
     "    sys.stdout.write(\"len=%d\" % len(xs))\n"),
    # Four container types in ONE program, so a lowering that handled `List` and
    # not `Dict` is caught by the joined output rather than by four cases that
    # each pass. CPython's `[]` / `{}` / `set()` / `()` are the same four
    # answers, and `Tuple` is in the group precisely because it is the one whose
    # CPython spelling is a literal and whose Mojo spelling is a constructor —
    # the row that would fail if the type-argument reader were bracket-shaped.
    ("every_empty_container_ctor_is_zero_length",
     "def main() -> Int:\n"
     "    var a = List[Int]()\n"
     "    var b = Dict[Int, Int]()\n"
     "    var c = Set[Int]()\n"
     "    var d = Tuple[Int, Int]()\n"
     "    printf(\"%d %d %d %d\", len(a), len(b), len(c), len(d))\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    a, b, c, d = [], {}, set(), ()\n"
     "    sys.stdout.write(\"%d %d %d %d\" % (len(a), len(b), len(c), "
     "len(d)))\n"),
    # An empty container NEXT TO a non-empty one, in the same function, because
    # the blob the constructor emits is the same reservation `_emit_list` makes
    # and the only way to tell the two apart is to read both. A constructor that
    # emitted a count of garbage, or a base one slot off, would pass the
    # zero-length rows above and fail here.
    ("empty_container_ctor_beside_a_literal",
     "def main() -> Int:\n"
     "    var xs = List[Int]()\n"
     "    var ys = [1, 2, 3]\n"
     "    printf(\"%d %d\", len(xs), len(ys))\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n    xs, ys = [], [1, 2, 3]\n"
     "    sys.stdout.write(\"%d %d\" % (len(xs), len(ys)))\n"),
]


# The rows that assert a DIAGNOSTIC rather than a value, with the words BOTH
# backends must use. Declared here rather than inline so `main`'s dispatch stays
# one lookup and a reader can see at a glance which rows are refusals.
TYPE_APPLICATION_REFUSALS = [
    # THE COUNTER-CASE, and the reason the exemption is not "a bracket is not a
    # value". `len(List)` is the same name in a VALUE position: there is no
    # container there at all and this path cannot say what a word is, so it
    # must keep refusing. A fix that exempted every read of a type name would
    # build this and print an address.
    #
    # The EXPECTED WORDS moved once, and the move is the improvement rather
    # than a loosened assertion: a type in a value position is now a word (its
    # tag — `model.type_value_tag`), so the register-allocator sentence this
    # case used to require became FALSE about the program, and the refusal that
    # fires instead is `len()`'s own operand-shape one, which names `len(List)`
    # and is the same sentence the sibling case `len_of_a_type_is_refused`
    # pins for `len(bool)`. Both architectures, same words.
    ("a_type_name_in_a_value_position_is_still_refused",
     "def main() -> Int:\n"
     "    return len(List)\n",
     "refuse:len(List)", None),
    # …and the ANNOTATION position, which must be untouched: `var xs: List[Int]`
    # DECLARES a slot, and the whole exemption is about a CALL site. This one
    # BUILDS, so it is here as the guard against an exemption that reached a
    # type in any position rather than the one position it is about.
    ("a_type_annotation_is_not_a_call_site",
     "struct Bag:\n"
     "    var xs: List[Int]\n"
     "def main() -> Int:\n"
     "    var b = Bag()\n"
     "    printf(\"ok\")\n"
     "    return 0\n",
     0, "ok"),
    # WITH ARGUMENTS it is a genuinely different question and gets its own
    # diagnostic, which says why: a blob's size is fixed when the function is
    # laid out, so one that must hold n elements needs a reservation sized by a
    # value the compiler does not have. Before this change it was refused as
    # "has no representation on this path", which is FALSE about the empty form
    # and true about this one, and so true of neither — the diagnostic this row
    # pins is the one that says both halves.
    ("blob_constructor_with_operands_is_refused_by_its_own_reason",
     "def main(n: Int) -> Int:\n"
     "    var xs = List[Int](capacity=n)\n"
     "    return 0\n",
     "refuse:the empty form is a different question", None),
]


# ── a TYPE as a VALUE ──────────────────────────────────────────────────────
#
# `bugs/FORMAL_type_name_as_a_value.md` is the long form. A type on this path
# is a word, and the word is a TAG: one number per type, computed from the
# type's name by `model.type_tag`, the same number in every unit of the image
# and on both architectures. So `t == Int32` is an integer comparison, a type
# can be passed to a function and returned from one, and a `dtype: DType` field
# can hold one — the shape `std/testing/prop/random.mojo` and
# `std/gpu/host/func_attribute.mojo` write.
#
# TWO LISTS, because the expected values have two provenances and claiming one
# source for both would be false. `TYPE_VALUE_CASES` is written in the subset
# CPython and this backend share (`bool` and `int` are Python's own type
# objects, and `myinterpreter.py` binds those two names to exactly those
# objects, so all three agree), and every one of its expected values is what
# CPython prints for the same text — run, not asserted, with a `printf` shim:
#
#     a=12   b=10   c=1   d=1   h=7   (exit 0, and 5 for the last)
#
# `TYPE_VALUE_DTYPE_CASES` is the `DType.<member>` spelling, which CPython has
# no word for, so its expected values come from the interpreter — which is where
# this construct's semantics are established, and which agrees case for case
# (`python3 fire.py run` on the same text, with `printf` written as `print`):
#
#     e=11   f=7    g=1
#
# A constant typed here by hand would be an assertion about a lowering written
# by the same person who wrote the lowering, which is the one kind of expected
# value this file exists not to have.
TYPE_VALUE_CASES = [
    # Two names, two answers. This is the case the construct exists for: before
    # it, `kind_of(bool)` was refused with "'bool' has no home: … read out of
    # whatever register the allocator left behind", which is false about the
    # program — `bool` is a type, and the question is not where a register for
    # it would come from.
    ("type_value_two_names_two_answers",
     "def kind_of(t):\n"
     "    if t == bool:\n"
     "        return 1\n"
     "    if t == int:\n"
     "        return 2\n"
     "    return 0\n"
     "def main(n):\n"
     "    printf(\"a=%d\", 10 * kind_of(bool) + kind_of(int))\n"
     "    return 0\n",
     0, "a=12"),
    # Across a CALL BOUNDARY, which is the half that needs the tag to be a
    # function of the type's name rather than of the unit that compiled it: the
    # callee is a separate frame, and a callee in another dylib is a separate
    # image entirely, and both must see the same number.
    ("type_value_crosses_a_call_boundary",
     "def echo(t):\n"
     "    return t\n"
     "def same(t):\n"
     "    if t == bool:\n"
     "        return 1\n"
     "    return 0\n"
     "def main(n):\n"
     "    printf(\"b=%d\", 10 * same(echo(bool)) + same(echo(int)))\n"
     "    return 0\n",
     0, "b=10"),
    # A local holds it, so a type is an ordinary value once it is bound — the
    # step the build pass's exemption has to be followed by.
    ("type_value_a_local_holds_it",
     "def main(n):\n"
     "    t = bool\n"
     "    if t == bool:\n"
     "        printf(\"c=1\")\n"
     "    else:\n"
     "        printf(\"c=0\")\n"
     "    return 0\n",
     0, "c=1"),
    # `!=`, the other direction. A tag that compared equal to everything would
    # pass the three cases above.
    ("type_value_inequality",
     "def main(n):\n"
     "    t = int\n"
     "    if t != bool:\n"
     "        printf(\"d=1\")\n"
     "    return 0\n",
     0, "d=1"),
    # THE GUARD against the over-correction, and the row that caught the first
    # version of this change: a local whose spelling is a type name must win.
    # `Int = 7` printed the TAG of the type `Int` (-913451874) when the tag was
    # materialised in `_emit_expr` ahead of `_load_var`, on both architectures,
    # and exited 0. A rule written as "a type name is always a tag" produces
    # that; the tag is the LAST place a name's value comes from, not the first.
    ("a_local_named_like_a_type_still_wins",
     "def main(n):\n"
     "    Int = 7\n"
     "    printf(\"h=%d\", Int)\n"
     "    return 0\n",
     0, "h=7"),
    # And the same guard for a type name in CALLEE position, where nothing about
    # the construct changed: `int(5)` is a CONSTRUCTION and still lowers to 5.
    # A rule written as "any appearance of a type name" breaks this row.
    ("a_type_name_as_a_callee_is_still_a_construction",
     "def main(n):\n"
     "    return int(int(5))\n",
     5, None),
]

TYPE_VALUE_DTYPE_CASES = [
    # `DType.<member>` is the SAME WORD as the bare name — the case that says
    # so, and the reason the tag is computed from the type's name and not from
    # the spelling that reached it. Interpreter: `2` and `1` for the same two
    # questions.
    ("type_value_dtype_member_is_the_same_word",
     "def same(t) -> Int:\n"
     "    if t == Int32:\n"
     "        return 1\n"
     "    return 0\n"
     "def main(n: Int) -> Int:\n"
     "    printf(\"e=%d\", 10 * same(DType.int32) + same(Int32))\n"
     "    return 0\n",
     0, "e=11"),
    # The alias rule, in the three forms the corpus writes: `DType.int` and
    # `DType.index` are both `Int64`, so all three comparisons hold and the
    # answer is 1+2+4.
    ("type_value_dtype_int_is_int64",
     "def main(n: Int) -> Int:\n"
     "    var a = 0\n"
     "    if DType.int == DType.index:\n"
     "        a = a + 1\n"
     "    if DType.int == Int64:\n"
     "        a = a + 2\n"
     "    if DType.int64 == Int64:\n"
     "        a = a + 4\n"
     "    printf(\"f=%d\", a)\n"
     "    return 0\n",
     0, "f=7"),
    # Through a STRUCT FIELD, which is the shape the corpus uses: both files
    # declare `dtype: DType` and store into it. The field is one word, so this
    # is only interesting because the VALUE is a type.
    ("type_value_through_a_struct_field",
     "struct Bag:\n"
     "    var tag: Int64\n"
     "    var t: DType\n"
     "def kind_of(b: Bag) -> Int:\n"
     "    if b.t == DType.int32:\n"
     "        return 1\n"
     "    return 0\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Bag()\n"
     "    b.tag = 5\n"
     "    b.t = DType.int32\n"
     "    printf(\"g=%d\", kind_of(b))\n"
     "    return 0\n",
     0, "g=1"),
]

TYPE_VALUE_REFUSALS = [
    # A bare `DType` is the type OF a type. Refused by name, because the
    # alternative message — the walk's "no home … read out of whatever register
    # the allocator left behind" — is false about it: there is no register
    # question here at all.
    ("a_bare_dtype_is_not_a_type_value",
     "def main(n: Int) -> Int:\n"
     "    var t = DType\n"
     "    return 0\n",
     "refuse:is the type OF a type", None),
    # A `DType` member naming a real Mojo type whose NAME is in no table here
    # (the float8/float4 formats and `uint128`, 202 spellings in the corpus).
    # Refused with the member named, because the emitter's own fallback said
    # "is a field access through 'DType'" — a struct field where there is a
    # missing table entry, which sends the reader to the wrong file.
    ("an_unknown_dtype_member_is_refused_by_name",
     "def main(n: Int) -> Int:\n"
     "    return Int(DType.float8_e4m3fn)\n",
     "refuse:DType.float8_e4m3fn names a type", None),
    # `len()` of a type. A GUARD rather than a new refusal: the four production
    # files reverted in place give byte-identical messages for `len(bool)` and
    # `len(List)` before this construct existed, so what this case pins is that
    # making a type a VALUE did not turn `len()` of one into a count. The
    # wording is the imprecision it has always had — the source does say what the
    # operand holds, and it says `bool` — and the bug doc has the next step.
    ("len_of_a_type_is_refused",
     "def main(n: Int) -> Int:\n"
     "    return len(bool)\n",
     "refuse:len(bool)", None),
]


# ── the tag is INJECTIVE over the type names this path admits ──────────────
#
# A type's value is its tag, and a tag is a 63-bit hash of the type's name, so
# the one thing that could make the whole construct wrong is a COLLISION: two
# types sharing a word would make `f(bool)` answer for `f(int)`. That is not a
# probability to be argued about, because the tag is only ever asked about a
# name in a CLOSED set (`model.type_value_name_space()`), and injectivity over a
# closed set is a fact about it rather than a bound on it. This case IS that
# fact, asked of the BACKEND: it compares every pair of the admitted names with
# the language's own `==`, at run time, in the emitted image — 1275 comparisons
# over 51 names — so what it proves is that the words the backends materialise
# are pairwise distinct, not merely that a Python function returns what it
# returns.
#
# GENERATED, because a hand-written list of 51 names goes stale the moment a
# type is added to a table, and a stale list makes this case quietly prove less
# while still passing. The names are read from the model, so the case grows
# with the construct.
#
# The pairs are spread over helper functions because ONE function with 1275 `if`
# statements does not build: `RecursionError: maximum recursion depth exceeded`,
# raised from the model after ~1270 statements in a single body. That is a
# pre-existing limit of the statement walk and not this case's problem to fix;
# 26 comparisons per function is well inside it and the case builds in under
# four seconds.
_TYPE_VALUE_MODEL = __import__("formal.model", fromlist=["model"])
_TYPE_VALUE_TAG_NAMES = sorted(_TYPE_VALUE_MODEL.type_value_name_space()
                               - {"DType"})   # no tag: dtype_object_refusal

# The same claim asked of the model directly, so a collision is loud at import
# and not only in the image: two questions, two places. This one is a fact about
# the FUNCTION and the case above is a fact about the WORDS the backends emit
# for it.
_TYPE_VALUE_TAG_COLLISIONS = _TYPE_VALUE_MODEL.type_value_tags_are_distinct()
if _TYPE_VALUE_TAG_COLLISIONS:
    raise AssertionError(
        f"two type names share a tag, so `t == A` would answer for `t == B`: "
        f"{_TYPE_VALUE_TAG_COLLISIONS}")


def _every_type_tag_is_distinct_source(chunk: int = 26) -> str:
    """A program that returns 1 if any two admitted type names share a tag."""
    import itertools
    funcs, index, made = [], 0, 0
    while index < len(_TYPE_VALUE_TAG_NAMES):
        part = _TYPE_VALUE_TAG_NAMES[index:index + chunk]
        if len(part) < 2:
            break
        body = [f"def tag{made}(n):\n"]
        body += [f"    if {a} == {b}: return 1\n"
                 for a, b in itertools.combinations(part, 2)]
        funcs.append("".join(body) + "    return 0\n")
        made += 1
        index += chunk
    main = ["def main(n):\n", '    printf("distinct")\n']
    main += [f"    if tag{j}(n): return 1\n" for j in range(made)]
    return "".join(funcs) + "".join(main) + "    return 0\n"


TYPE_VALUE_TAG_CASES = [
    ("every_type_tag_is_distinct",
     _every_type_tag_is_distinct_source(),
     0, "distinct"),
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
                  + RETURNED_FRAME_CASES
                  + BYREF_REFUSALS + WIDE_OFF_CASES
                  + SUBSCRIPT_CASES + DECLARED_TYPE_CASES
                  + DECLARED_TYPE_REFUSALS
                  + ASSIGNED_TYPE_CASES + ASSIGNED_TYPE_REFUSALS \
                  + INIT_FIELD_TYPE_CASES \
                  + INIT_FIELD_TYPE_REFUSALS
                  + BYREF_HANDOFF_CASES + BYREF_HANDOFF_REFUSALS
                  + CROSS_MODULE_CASES + WAVE5_POSITION_CASES
                  + CONSTRUCTION_CASES + CONSTRUCTION_REFUSALS
                  + POINTER_DEREF_CASES + POINTER_DEREF_REFUSALS
                  + WAVE6_TRUTHY_CASES
                  + WAVE6_NAME_CASES + WAVE7_G2_CASES
                  + SHIFT_CASES + REFUSAL_CASES
                  + TYPE_APPLICATION_REFUSALS + TYPE_VALUE_CASES \
                  + TYPE_VALUE_DTYPE_CASES + TYPE_VALUE_REFUSALS \
                  + TYPE_VALUE_TAG_CASES + ORIGIN_OF_CASES \
                  + ORIGIN_OF_REFUSALS
                  + EQ_DISPATCH_CASES
                  + TYPE_ARGUMENT_LIST_CASES
                  + TYPE_ARGUMENT_LIST_ABSENT_CASES
                  + [X86_ONLY_1SLOT_BUG_CASE])
    # The CPython-pair group is a DIFFERENT SHAPE (three columns: name, Mojo
    # text, CPython text), so it is selected and dispatched separately rather
    # than forced into the four-column table every other group uses. Forcing it
    # in would mean a sentinel in the exit-status column and a branch that reads
    # a sentinel as if it were a status — which is how a case ends up asserting
    # nothing.
    pair_names = {c[0] for c in TYPE_APPLICATION_CASES}
    wanted_pairs = ([c for c in TYPE_APPLICATION_CASES
                     if not args.cases or c[0] in args.cases])
    selected = [c for c in everything if not args.cases or c[0] in args.cases]
    known = {c[0] for c in everything} | pair_names
    if args.cases and len(selected) + len(wanted_pairs) != len(args.cases):
        missing = set(args.cases) - known
        print(f"ERROR: unknown case(s): {sorted(missing)}", file=sys.stderr)
        return 2
    off_names = {c[0] for c in WIDE_OFF_CASES}
    module_names = {c[0] for c in CROSS_MODULE_CASES}

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, source, cpython_source in wanted_pairs:
            src = os.path.join(tmpdir, name + ".mojo")
            with open(src, "w") as f:
                f.write(source)
            try:
                ok, detail = run_cpython_pair_case(
                    name, source, cpython_source, tmpdir, args.verbose)
            except subprocess.TimeoutExpired:
                ok, detail = False, "timed out"
            except Exception as e:  # unexpected: report, do not mask
                ok, detail = False, f"{type(e).__name__}: {e}"
                if args.verbose:
                    import traceback
                    traceback.print_exc()
            if ok:
                passed += 1
                print(f"  PASS  {name} (== CPython, both architectures)")
            else:
                failed += 1
                print(f"  FAIL  {name}: {detail}")
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
