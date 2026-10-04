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
import re
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
    # A LONG BODY, which is a different axis from spilling: this walk used to
    # recurse once per SIBLING statement, so a function of N statements needed
    # N Python frames and a straight-line body of a little over a thousand
    # statements died with a bare `RecursionError` — no `build:` prefix, no
    # source line, no construct named. Nothing about the SOURCE was wrong
    # (`printf` lowers), and a generated program is exactly this shape, which
    # is why it is a generated case rather than a written one: no hand-written
    # function in this file is 2,001 statements long, so only a generator
    # reaches the limit at all.
    #
    # The last statement prints and the function RETURNS, so the case also
    # pins the walk's answer rather than only its termination: `i >= n` at the
    # end of the list is the branch the old code reached with `rest`, and a
    # dropped implicit `return 0` would still exit 0 while printing the wrong
    # thing.
    ("a_two_thousand_statement_body_builds_and_runs",
     "def main(n):\n"
     + "".join(f'    printf("{i}=%d@@", {i})\n' for i in range(2000))
     + "    return 42\n", 42, "1999=1999@@"),
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
    # A `with … as y:` TARGET is a store, and `y` is bound BEFORE the body
    # runs — so reading it inside the body is not reading an uninitialised
    # name. The read-before-store walk added the alias AFTER walking the body,
    # so it reported exactly that, on BOTH architectures, with a message about
    # `UnboundLocalError` for a program CPython does not run at all (`with 7` is
    # a TypeError: 'int' object does not support the context manager protocol)
    # — a diagnostic naming neither the construct nor an error the reader can
    # reproduce.
    #
    # **This row used to expect the emitters' own lowering** — the alias bound to
    # the context expression's VALUE, which is what `_emit_with` documented on
    # both machines — and it is a `refuse:` case now, because `with` is lowered
    # to the context-manager PROTOCOL (`formal/build.py`'s
    # `_rewrite_with_statements`): `__enter__` produces the name the body sees
    # and `__exit__` runs on the way out. `with 7 as y` has neither, and CPython
    # raises `TypeError: 'int' object does not support the context manager
    # protocol` — so the answer this path owes the reader is that refusal, not a
    # program that binds `y` to 7 and silently skips the exit call. The
    # property the row was written for is now
    # `with_enter_binds_the_alias_before_the_body` below, where the alias is a
    # real `__enter__` result.
    ("with_on_a_word_is_the_context_manager_protocol_or_a_refusal",
     "def main():\n    x = 0\n    with 7 as y:\n        x = y\n"
     "    printf(\"x=%d\", x)\n    return x\n",
     "refuse:is CPython's CONTEXT-MANAGER PROTOCOL", None),
    # …and the property itself, on a value that IS a context manager. The alias
    # is `__enter__`'s return value and not the object, which is the whole
    # difference between the protocol and "bind the expression's own value":
    # this program prints 20, and it would print 11 if the alias were the
    # manager.
    ("with_enter_binds_the_alias_before_the_body",
     "struct Ctx:\n    var tag: Int\n    var name: String\n"
     "    fn __enter__(self) -> Int:\n        printf(\"enter@@\")\n"
     "        return self.tag\n"
     "    fn __exit__(self) -> Int:\n        printf(\"exit@@\")\n"
     "        return 0\n\n"
     "def main():\n    x = 0\n    with Ctx(20, \"c\") as y:\n"
     "        x = y\n        printf(\"x=%d@@\", x)\n"
     "    printf(\"after=%d@@\", x)\n    return x\n",
     20, "enter@@x=20@@exit@@after=20@@"),
    # The exit on the FALL-THROUGH, and — the reason this is a separate row —
    # on a `return` out of the block. A cleanup written "after the body" is
    # right on the first and wrong on the second, and this path lowers the
    # whole `with` to a `try`/`finally` so the second is right too. Before the
    # fix this row also failed for a THIRD reason, in the emitters rather than
    # here: a `finally` was dropped from the fall-through path once an exit edge
    # inside the body had flushed it, which is a `finally` that silently does
    # nothing (measured: a conditional `return` in the body printed nothing from
    # the clause on the path that did not return).
    ("with_exit_runs_on_an_early_return",
     "struct Ctx:\n    var tag: Int\n    var name: String\n"
     "    fn __enter__(self) -> Int:\n        return self.tag\n"
     "    fn __exit__(self) -> Int:\n        printf(\"exit@@\")\n"
     "        return 0\n\n"
     "def f(n):\n    with Ctx(1, \"c\") as y:\n        printf(\"body@@\")\n"
     "        if n > 0:\n            return 9\n    return 0\n\n"
     "def main():\n    printf(\"r=%d@@\", f(1))\n    printf(\"r=%d@@\", f(0))\n"
     "    return 0\n",
     0, "body@@exit@@r=9@@body@@exit@@r=0@@"),
    # Two items: CPython enters left to right and exits RIGHT TO LEFT, and
    # nesting the rewrites inside one another is what produces that order.
    ("with_two_items_exit_in_reverse_order",
     "struct Ctx:\n    var tag: Int\n    var name: String\n"
     "    fn __enter__(self) -> Int:\n        printf(\"enter %s@@\", self.name)\n"
     "        return self.tag\n"
     "    fn __exit__(self) -> Int:\n        printf(\"exit %s@@\", self.name)\n"
     "        return 0\n\n"
     "def main():\n"
     "    with Ctx(1, \"A\") as a, Ctx(2, \"B\") as b:\n"
     "        printf(\"a=%d b=%d@@\", a, b)\n    return 0\n",
     0, "enter A@@enter B@@a=1 b=2@@exit B@@exit A@@"),
    # `with EXPR:` with no `as` — CPython still calls `__enter__` and still runs
    # `__exit__`; the value is simply discarded. A lowering that treated a
    # missing alias as "no context manager" would skip the exit, which is the
    # silent half this whole protocol exists to remove.
    ("with_no_alias_still_enters_and_exits",
     "struct Ctx:\n    var tag: Int\n    var name: String\n"
     "    fn __enter__(self) -> Int:\n        printf(\"enter@@\")\n"
     "        return self.tag\n"
     "    fn __exit__(self) -> Int:\n        printf(\"exit@@\")\n"
     "        return 0\n\n"
     "def main():\n    with Ctx(1, \"c\"):\n        printf(\"body@@\")\n"
     "    return 0\n",
     0, "enter@@body@@exit@@"),
    # A context manager inside a LOOP, with a `continue` — the exit has to run
    # on that edge too, and it is the shape that found the dropped-`finally`
    # defect above (a `continue` inside the block flushed the pending clause at
    # EMIT time, so every LATER iteration's normal path had no cleanup at all).
    ("with_exit_runs_on_a_continue_inside_a_loop",
     "struct Ctx:\n    var tag: Int\n    var name: String\n"
     "    fn __enter__(self) -> Int:\n        return self.tag\n"
     "    fn __exit__(self) -> Int:\n        printf(\"exit %d@@\", self.tag)\n"
     "        return 0\n\n"
     "def f(n):\n    var i = 0\n    var seen = 0\n    while i < n:\n"
     "        with Ctx(i, \"c\") as v:\n"
     "            if v == 0:\n                i = i + 1\n                continue\n"
     "            seen = seen + 1\n        i = i + 1\n    return seen\n\n"
     "def main():\n    printf(\"seen=%d@@\", f(3))\n    return 0\n",
     0, "exit 0@@exit 1@@exit 2@@seen=2@@"),
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
    # A class-level constant whose VALUE is another class's constant — the enum
    # idiom (`origin: TypeOrigin = TypeOrigin.DEFAULT`), and this repository's
    # `type_system.py`. The rewrite already answers a read of `Origin.B` from a
    # function body (the `pyclass_constant_table_only` rows above), so the gap
    # was narrower than it looked: the OUTER site consumes the whole node, so
    # the inner reference was never reached, and the value was reported as "not
    # a literal". Both halves of the resolution are here — the read at the top
    # level and a constant whose own value is a THIRD class's constant, so a
    # recogniser that resolved one hop would fail this row.
    #
    # The recogniser is `S.NAME` and nothing else, and the boundary is the
    # BARE name: `C = B` in a class body is also how a module-level name is
    # read, and this path has no scope at an initializer that could tell the
    # two apart. That spelling is still refused, with the value quoted, which
    # is the refusal a reader can act on.
    ("pyclass_constant_whose_value_is_another_constant",
     "class Inner:\n"
     "    B = 2\n"
     "\n"
     "class Origin:\n"
     "    C = Inner.B\n"
     "\n"
     "struct Holder:\n"
     "    v: Int = Origin.C\n"
     "\n"
     "def get() -> Int:\n"
     "    return Origin.C\n"
     "\n"
     "def main(n):\n"
     "    h = Holder()\n"
     "    printf(\"%d %d\\n\", get(), h.v)\n"
     "    return 0\n", 0, "2 2"),
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
    #
    # The needle is the read (`Table.NAMES`) followed by the VALUE it could not
    # materialize (`["a", "b"]`), because a diagnostic that names the construct
    # without naming the value sends the reader to a literal the file does not
    # contain — which is the whole cost of the message this replaced.
    ("pyclass_nonliteral_constant_refused",
     "class Table:\n"
     "    NAMES = [\"a\", \"b\"]\n"
     "\n"
     "    def first():\n"
     "        return Table.NAMES[0]\n"
     "\n"
     "def main(n):\n"
     "    return Table.first()\n",
     # The needle QUOTES THE VALUE, which is the half that sends a reader to the
     # class body rather than to the read; `class_constant_with_a_container_
     # value_quotes_the_value` below is the same program with the whole sentence
     # pinned, and this one is the plain-constant spelling of it.
     "refuse:Table.NAMES reads a class-level constant of Table, whose value is "
     "`['a', 'b']`", None),
    # ── the `comptime` SPELLING of a class constant ────────────────────────
    #
    # Everything above writes the constant as a class-level assignment
    # (`A = 1`). Mojo has a second spelling for the same thing —
    # `comptime A = 1` in the struct body — and it is not the same thing to a
    # compiler: the parser files it under `StructDef.comptime_aliases` and NOT
    # under `StructDef.fields`, because a `ComptimeVarStmt` is neither a
    # `VarDecl` nor an `AssignStmt`. So it was a class value in no table on this
    # path at all, and a method that read one through its receiver read the slot
    # nothing ever writes. `C` below is one field wide (`n`), the method returns
    # `self.LIMIT + self.n`, and the image printed 0 where the source says 13 —
    # on BOTH architectures, because the zero was the layout's, not a register's
    # leftover. These four cases are the four spellings that now read as the
    # value; the CPython-pair group below runs each against CPython rather than
    # against a number written here.
    ("comptime_alias_through_receiver_is_the_value",
     "struct C:\n"
     "    comptime LIMIT = 10\n"
     "    var n: Int\n"
     "\n"
     "    def scaled(self) -> Int:\n"
     "        return self.LIMIT + self.n\n"
     "\n"
     "def main(n):\n"
     "    c = C(0)\n"
     "    c.n = 3\n"
     "    return c.scaled()\n", 13, None),
    # The same read spelled through the class's OWN name from inside one of its
    # methods. Before, this did not even reach a constant: `C` was read as a
    # value, and a struct name is not a value — the refusal was "'C' is read at
    # line N before anything in this function stores it", which is a statement
    # about a NAME and says nothing about the attribute that was being read.
    ("comptime_alias_through_the_class_name",
     "struct C:\n"
     "    comptime LIMIT = 10\n"
     "    var n: Int\n"
     "\n"
     "    def scaled(self) -> Int:\n"
     "        return C.LIMIT + self.n\n"
     "\n"
     "def main(n):\n"
     "    c = C(0)\n"
     "    c.n = 3\n"
     "    return c.scaled()\n", 13, None),
    # `Self`, which names the method's own type rather than an instance of it,
    # and so is the same read. It was refused as a field access through a base
    # bound as a parameter — a true statement about the BINDING and no answer at
    # all about the name, which is not a field of anything.
    ("comptime_alias_through_Self",
     "struct C:\n"
     "    comptime LIMIT = 10\n"
     "    var n: Int\n"
     "\n"
     "    def scaled(self) -> Int:\n"
     "        return Self.LIMIT + self.n\n"
     "\n"
     "def main(n):\n"
     "    c = C(0)\n"
     "    c.n = 3\n"
     "    return c.scaled()\n", 13, None),
    # Through a base that is NOT a method receiver: `limit_of` takes the frame
    # as an argument, so nothing about the DECLARATION says what it holds. What
    # says it is the holder analysis — every binding of `c` this image can see
    # is a `C` — which is the same "agree or refuse" evidence the slot lookup
    # uses, and a name bound to two structs on two paths is simply not
    # substituted. This is the shape the stdlib's own `shape.is_flat` has.
    ("comptime_alias_through_a_holder_argument",
     "struct C:\n"
     "    comptime LIMIT = 10\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "def limit_of(c) -> Int:\n"
     "    return c.LIMIT\n"
     "\n"
     "def main(n):\n"
     "    c = C(0, 0)\n"
     "    c.a = 1\n"
     "    c.b = 2\n"
     "    return c.a * 100 + c.b * 10 + limit_of(c)\n", 130, None),
    # 130 is 1, 2 and 10: the two fields and the class value, each in its own
    # decimal place, so a read of the constant that came back 0 would give 120
    # and one that picked up a neighbouring slot would give something else
    # again. Written out rather than left to the reader.
    # …and the TIE-BREAK, which is the other direction of the same rule and the
    # one that keeps it from being a wrong answer: a `comptime` name the program
    # WRITES through an object is per-instance state, and the write wins. 7 + 3,
    # not the declared 10. The plain-constant spelling of this rule is
    # `pyclass_name_read_bare_and_written` above; it is repeated for `comptime`
    # because the two spellings reach it through different code — the write
    # census is what vetoes the substitution, and for the plain spelling the
    # same veto is what stops the demotion.
    ("comptime_alias_the_program_overwrites_is_storage",
     "struct C:\n"
     "    comptime LIMIT = 10\n"
     "    var n: Int\n"
     "\n"
     "    def read(self) -> Int:\n"
     "        return self.LIMIT\n"
     "\n"
     "def main(n):\n"
     "    c = C()\n"
     "    c.n = 3\n"
     "    c.LIMIT = 7\n"
     "    return c.read() * 10 + c.n\n", 73, None),
    # A class constant whose VALUE this build cannot materialize has nowhere to
    # live: there is no module-global storage, so the read can only be answered
    # by the value it is written with. This is `Coord.is_flat`
    # (`Self.rank == Self.flat_rank`) and `_ZipIterator._InjectedValues`
    # (`Tuple[*Self.Ts]`) reduced to the smallest program that reaches the same
    # line, and the refusal is the CORRECT verdict for both. Checked on both
    # backends: the pre-change message was a different one that was false about
    # the file ("has no field 'is_flat' … in Python this is an AttributeError at
    # run time", for a name the class declares 20 lines above the read).
    #
    # **THE VALUE IS `N + 4` AND NOT `3 + 4`, AND THAT IS THE WHOLE OF WHAT
    # CHANGED.** `3 + 4` is a literal-only expression of two literals, and
    # `formal/model.py::literal_default_word` — the one classifier behind
    # `class_constant_word`, `struct_default_word` and `struct_field_kind` — used
    # to be a SECOND, smaller copy of `fold_literal_expr` with no unary or binary
    # arm, so `A = -3` was refused as "not a value this build can materialize"
    # and `LIMIT = 3 + 4` with it. It folds with that folder now, so both are
    # materialized: `3 + 4` is 7, exactly, in the same word. What is still
    # refused is a value with a FREE NAME in it, because the class body is not a
    # scope the materializer can resolve — which is the case the real sources
    # are, and is what this row now pins. `N` is a module-level constant of this
    # unit, so it is not a name nobody can find; it is a name the class body
    # cannot read.
    #
    # The NEEDLE is the wording this tree raises, which quotes the VALUE: a
    # "`comptime` class attribute … whose value is `BinaryOp`" rather than the
    # generic "is a class-level constant of C" this case used to expect. The
    # quoted value is the part that sends the reader to the class body instead of
    # to the read.
    ("comptime_alias_nonliteral_value_refused",
     "N = 4\n"
     "\n"
     "struct C:\n"
     "    comptime LIMIT = N + 4\n"
     "    var n: Int\n"
     "\n"
     "def get() -> Int:\n"
     "    return C.LIMIT\n"
     "\n"
     "def main(n):\n"
     "    return get()\n",
     "refuse:C.LIMIT reads a `comptime` class attribute of C", None),
    # The anti-rot direction for the corrected message: the old text claimed a
    # missing attribute is an AttributeError the program is "very likely already
    # raising" on. For a `comptime` member that is false in the strong sense —
    # the attribute exists, so the program does not raise. The needle is the
    # corrected half, the forbidden substring is the false half.
    ("comptime_alias_refusal_does_not_claim_an_attribute_error",
     "N = 4\n"
     "\n"
     "struct C:\n"
     "    comptime LIMIT = N + 4\n"
     "    var n: Int\n"
     "\n"
     "    def read(self) -> Int:\n"
     "        return self.LIMIT\n"
     "\n"
     "def main(n):\n"
     "    c = C(0)\n"
     "    return c.read()\n",
     "refuse_without:self.LIMIT reads a `comptime` class attribute of C:"
     "In Python this is an AttributeError at run time", None),

    # A class-level binding whose value reads a struct PARAMETER is a different
    # refusal from the rows above, and the difference is the sentence's REPAIR.
    # Those say "write the value at the use site (a literal, or an assignment the
    # compiler can see)" — and for a parameter there is no value in the class body
    # to write anywhere: the use site supplies it as an ARGUMENT
    # (`Box[Int, [1,2,3]]`), which is a value and not a literal, and this path does
    # not monomorphize, so at the class body there is no instantiation at all.
    # `std/collections/type_dict.mojo`'s `comptime _index[key: Self.T] =
    # Self.keys.try_index(key)` was refused by the value's own sentence, which
    # describes an edit that cannot be made. Measured on both architectures.
    #
    # `refuse_without:` for the value sentence, and it is the load-bearing half:
    # an arm added here that only appended the parameter fact would pass every
    # other assertion in the tree while still telling the reader to make a
    # literal.
    ("comptime_binding_reading_a_struct_parameter_is_its_own_refusal",
     "struct Box[T: AnyType, keys: List[T]]:\n"
     "    comptime length = len(keys)\n"
     "\n"
     "    def size(self) -> Int:\n"
     "        return Self.length\n"
     "\n"
     "def main(n):\n"
     "    return 0\n",
     "refuse_without:what it reads is 'keys', a PARAMETER of Box:"
     "a formal value is one 64-bit word with nowhere to keep a non-literal one",
     None),
    # A VARIADIC parameter's arity is the same shape with nothing to bind at all,
    # and it is the stdlib's own (`TypeDict`'s `comptime length = len(Self.values)`
    # over `*values: Trait`), so the arm has to reach the `Self.` spelling too and
    # not only a bare read.
    ("comptime_binding_reading_a_variadic_parameter_is_its_own_refusal",
     "struct Pair[T: AnyType, *values: T]:\n"
     "    comptime length = len(Self.values)\n"
     "\n"
     "    def size(self) -> Int:\n"
     "        return Self.length\n"
     "\n"
     "def main(n):\n"
     "    return 0\n",
     "refuse:Self.length reads a `comptime` class attribute of Pair, whose "
     "value is `len(Self.values)` — and what it reads is 'values', a PARAMETER "
     "of Pair", None),
    # …and the CONTROL, which is what keeps the new arm from being a blanket ban
    # on the construct: the same class body with a LITERAL builds, runs, and
    # prints the constant. Measured, both architectures. The read is a free
    # function rather than a method call, so the case is about the CLASS BODY and
    # not about calling a method of a struct whose parameters this path does not
    # bind.
    ("comptime_binding_with_a_literal_value_still_builds",
     "struct Box[T: AnyType, keys: List[T]]:\n"
     "    comptime length = 3\n"
     "\n"
     "    def size(self) -> Int:\n"
     "        return Self.length\n"
     "\n"
     "def show() -> Int:\n"
     "    return Box.length\n"
     "\n"
     "def main(n) -> Int:\n"
     "    printf(\"%d\", show())\n"
     "    return 0\n", 0, "3"),

    # The `refuse:` sibling above with the needle this tree raises: it quotes the
    # VALUE, which is what sends a reader to the class body rather than to the
    # read, where the generic "is a class-level constant of Table" did not.
    # The BOUNDARY of the reference resolution, and it is what keeps the
    # resolution from being "resolve anything": `Missing` is not a class this
    # image declares, so there is no declaration to read the value out of and
    # the read is refused with the value quoted — the same sentence, and the
    # same clause of it, as the container value two rows below.
    ("class_constant_naming_a_class_this_image_does_not_declare_is_refused",
     "struct Holder:\n"
     "    v: Int = Missing.WHAT\n"
     "\n"
     "def main(n):\n"
     "    var h = Holder()\n"
     "    printf(\"%d\\n\", h.v)\n"
     "    return 0\n",
     "refuse:reads a class-level constant of Holder, whose value is "
     "`Missing.WHAT`", None),
    ("class_constant_with_a_container_value_quotes_the_value",
     "struct Table:\n"
     "    NAMES = ['a', 'b']\n\n"
     "def get() -> Int:\n"
     "    return len(Table.NAMES)\n\n"
     "def main(n):\n"
     "    return get()\n",
     "refuse:Table.NAMES reads a class-level constant of Table, whose value is "
     "`['a', 'b']` — and a formal value is one 64-bit word with nowhere to keep "
     "a non-literal one", None),

     # ── a `comptime` class attribute, read through a RECEIVER ────────────
     #
     # `comptime NAME = …` in a struct body is not per-instance state: the parser
     # keeps it in `StructDef.comptime_aliases` and out of `StructDef.fields`, and
     # `myinterpreter` resolves `obj.NAME` out of that dict. Before this group the
     # names were in no table on the formal side at all, so a read of one arrived
     # at the member-access lowering as a name the struct does not have and was
     # refused with a sentence about a run-time `AttributeError` — in a program
     # that does not raise, because the attribute is right there in the class body
     # (`std/iter/__init__.mojo`'s `res._InjectedValues` is the real one).
     #
     # Three spellings in ONE program, because the three have different evidence
     # and a fix that covered two of them would leave the third silently wrong:
     # `self.rank` (the receiver of a method of the struct that declares it),
     # `Self.rank` (the class name, `struct_receivers` has no `self` for a
     # `def first()` that takes no receiver), and `c.rank` through a local the
     # constructor was bound to.
     ("comptime_attribute_read_through_receiver_and_self",
      "struct Coord:\n"
      "    var rows: Int\n"
      "    var cols: Int\n"
      "    comptime rank: Int = 3\n"
      "\n"
      "    def get_rank(self) -> Int:\n"
      "        return self.rank\n"
      "\n"
      "    @staticmethod\n"
      "    def class_rank() -> Int:\n"
      "        return Self.rank\n"
      "\n"
      "def main(n: Int) -> Int:\n"
      "    var c = Coord(2, 3)\n"
      "    printf(\"%d %d %d %d\", c.get_rank(), Coord.class_rank(), c.rank, "
      "c.rows + c.cols)\n"
      "    return 0\n", 0, "3 3 3 5"),
     # The same attribute with a value this path CANNOT materialize, read
     # through a receiver — refused by name, and the diagnostic quotes the VALUE
     # (`Self(0)`), because "not a literal" sends the reader to look for a
     # literal the file does not contain. This is the enum-like shape
     # `logger/logger.mojo:75` writes 10 times over (`comptime NOTSET = Self(0)`).
     ("comptime_attribute_with_a_call_value_is_refused_by_name",
      "struct Level:\n"
      "    var value: Int\n"
      "    comptime NOTSET = Self(0)\n"
      "\n"
      "def main(n: Int) -> Int:\n"
      "    return Level.NOTSET\n",
      "refuse:Level.NOTSET reads a `comptime` class attribute of Level, whose "
      "value is `Self(0)`", None),
     # An MLIR TEMPLATE reached THROUGH the binding is refused as the MLIR
     # construct it is, not as "not a literal". The two questions meet on one
     # node — a `comptime` class attribute whose value is a template — and
     # dropping the MLIR half would replace a refusal that named the construct
     # with one that does not. `_plugin/selector.mojo`, `builtin/variadics.mojo`,
     # `ffi/unsafe_union.mojo` and `memory/pointer.mojo` are the four new-modular
     # stdlib files this moves onto the MLIR verdict, and it is asked through
     # `model.mlir_template_refusal` so a binding that asks the BUILD a target
     # question (`#kgen.param.expr<current_target>`) is still answered rather than
     # refused.
     ("mlir_template_in_a_comptime_attribute_is_refused_as_mlir",
      "struct Tag:\n"
      "    comptime _t = __mlir_type.`!kgen.none`\n"
      "    var v: Int\n"
      "\n"
      "def main(n: Int) -> Int:\n"
      "    var t = Tag()\n"
      "    t.v = n\n"
      "    printf(\"%d\", t.v + Tag._t)\n"
      "    return 0\n",
      "refuse:Tag._t reads a `comptime` class attribute of Tag, whose value is "
      "an MLIR construct: __mlir_type.`!kgen.none` names an MLIR TYPE", None),
     # …and the same template in a TYPE POSITION builds, which is the pair that
     # makes the refusal above a refusal rather than a blanket ban on the
     # construct. `std/builtin/none.mojo` is this file: it declares
     # `comptime _mlir_type = __mlir_type.`!kgen.none`` and BUILDS, because its
     # only reads of the name are a field annotation and a parameter annotation.
     ("mlir_template_in_a_type_annotation_still_builds",
      "struct Tag:\n"
      "    comptime _t = __mlir_type.`!kgen.none`\n"
      "    var v: Self._t\n"
      "\n"
      "def main(n: Int) -> Int:\n"
      "    var t = Tag()\n"
      "    t.v = n\n"
      "    printf(\"%d\", t.v)\n"
      "    return 0\n", 0, "10"),
     # A TYPE POSITION is not a read. `var v: Self.K` is the shape
     # `std/builtin/none.mojo:30` has (`var _value: Self._mlir_type`, a file that
     # BUILDS), and an annotation is not evaluated on this path — the field
     # readers take the SPELLING. Substituting there would put the integer where
     # the source wrote a type, and for a non-literal binding it would REFUSE a
     # file that builds: this case is that file, with 7 * 3 standing in for an MLIR
     # type so the test needs no dialect.
     ("comptime_attribute_in_a_type_annotation_is_inert",
      "struct Scaled:\n"
      "    comptime K = 7 * 3\n"
      "    var v: Self.K\n"
      "\n"
      "def main(n: Int) -> Int:\n"
      "    var s = Scaled()\n"
      "    s.v = 21\n"
      "    printf(\"%d\", s.v)\n"
      "    return 0\n", 0, "21"),
     # A name the unit WRITES is per-instance state whatever the parser says, so
     # it stays a field and the write is what the read sees. This is the one
     # direction `struct_comptime_aliases` resolves the other way, and it is the
     # direction a wrong answer lives in: demoting a name something writes would
     # make two slots share one word.
     ("comptime_attribute_the_unit_writes_is_still_a_field",
      "struct Pair:\n"
      "    var a: Int\n"
      "    comptime b: Int = 3\n"
      "\n"
      "    def get_b(self) -> Int:\n"
      "        return self.b\n"
      "\n"
      "def main(n: Int) -> Int:\n"
      "    var p = Pair()\n"
      "    p.b = 7\n"
      "    printf(\"%d\", p.get_b())\n"
      "    return 0\n", 0, "7"),
     # A base class's `comptime` binding read through a receiver is NOT answered
     # from the base's value when a subclass can override it: the interpreter
     # copies the base's aliases onto the child and lets the child's own win, and
     # it copies the base's METHODS onto the child too, so the method runs with a
     # child receiver and `self.rank` is the child's. Refused by name rather than
     # printed as the parent's value.
     ("comptime_attribute_of_a_derived_struct_is_refused",
      "struct Base:\n"
      "    var a: Int\n"
      "    comptime rank: Int = 3\n"
      "\n"
      "    def get_rank(self) -> Int:\n"
      "        return self.rank\n"
      "\n"
      "struct Child(Base):\n"
      "    var b: Int\n"
      "    comptime rank: Int = 9\n"
      "\n"
      "def main(n: Int) -> Int:\n"
      "    var c = Child(1, 2)\n"
      "    printf(\"%d\", c.get_rank())\n"
      "    return 0\n",
      "refuse:self.rank reads a `comptime` class attribute of Base, whose value "
      "is not necessarily Base's: a struct deriving from Base in this unit "
      "redeclares it", None),
     # The local-alias census has to AGREE before it substitutes. This is the
     # program that made it stricter: `o` is built from `T()` and from `S(1)`, so
     # `o.LIMIT` is a field on one path and the class's own value on the other,
     # and the answer depends on which binding ran. Before the census required
     # agreement the image BUILT, RAN, and printed 3 for both — the wrong answer
     # for `flag == 0`, on both architectures, where this path's own model says
     # the answer is the word 0 of a field nothing wrote.
     ("class_constant_through_a_base_bound_from_two_constructors_is_refused",
      "struct S:\n"
      "    var n: Int\n"
      "    LIMIT = 3\n"
      "\n"
      "struct T:\n"
      "    var LIMIT: Int\n"
      "\n"
      "def pick(flag: Int) -> Int:\n"
      "    var o = T()\n"
      "    if flag:\n"
      "        o = S(1)\n"
      "    return o.LIMIT\n"
      "\n"
      "def main(n: Int) -> Int:\n"
      "    printf(\"%d %d\", pick(0), pick(1))\n"
      "    return 0\n",
      "refuse:o.LIMIT reads a class-level constant of S through 'o', and 'o' is "
      "built from more than one constructor in this function (S(1), T())", None),

    # ── a FUNCTION is not a METHOD just because they share a name ──────────
    #
    # The class-constant census asks two questions and used to be handed the
    # answer to the wrong one. "Which struct is this function a method of?" is
    # keyed by the LIFTED name a rewritten call spells (`Parser_parse_module`)
    # and its value is a StructDef; "who owns this method name?" is keyed by the
    # BARE name a `MemberExpr`'s `.member` is and its value is the struct's
    # NAME. Both are called "owners", they look alike, and
    # `_prepare_functions` passed the second where `_frame_receivers` documents
    # the first — so a module-level `def parse_module` was answered with the
    # string `"Parser"` and the value reached `_overridden_comptime_names`,
    # which asked it for `.name`. A traceback out of the compiler, on a program
    # with nothing exotic in it.
    #
    # The `None` default is LOAD-BEARING and is here for a measured reason, not
    # for coverage: `refuse_none_comparisons` opens with
    # `if not none_names and not none_consts: return`, so without a class-level
    # `None` somewhere in the unit the census never runs and this case would
    # pass with the defect still in it. Two of the struct's fields make it
    # framed, which is the other half — `_frame_receivers` returns before its
    # own census when no struct in the unit holds a frame. Both halves are the
    # reason the shape is `Parser` and not a one-field helper.
    #
    # The corpus case in `test_dataclasses_formal.py` found the same crash on
    # `formal/build.py`, which has a module-level `parse_module` colliding with
    # `fire_compiler.Parser.parse_module` and nothing else unusual about it.
    # That is a `formal/build.py` test wearing a generic name; this is the
    # construct, so a regression here does not need the repository's own source
    # to keep its shape.
    ("class_constant_census_survives_a_function_named_like_a_method",
     "struct Parser:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    var MISSING: Int = None\n"
     "\n"
     "    def parse_module(self) -> Int:\n"
     "        return self.a\n"
     "\n"
     "def parse_module(x: Int) -> Int:\n"
     "    return x + 1\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = Parser()\n"
     "    p.a = 3\n"
     "    p.b = 4\n"
     "    return parse_module(1) + p.parse_module()\n",
     5, None),
    # The `None` read is still a `None` read through this same receiver, so the
    # census that the case above has to survive still REFUSES where the language
    # says it must. Without it, "the crash is gone" and "the check was dropped"
    # would be the same green: this is the row that separates them.
    ("class_constant_none_through_a_receiver_is_still_refused_when_a_function_shares_its_name",
     "struct Parser:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    var MISSING: Int = None\n"
     "\n"
     "    def parse_module(self) -> Int:\n"
     "        return 1\n"
     "\n"
     "def parse_module(x: Int) -> Int:\n"
     "    return x + 1\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = Parser()\n"
     "    if p.MISSING == 0:\n"
     "        return 7\n"
     "    return 0\n",
     "refuse:is class-level constant holding `None`", None),

    # THE SAME REFUSAL, IN A FILE THAT ALSO READS AN ENUM MEMBER — which used to
    # RAISE instead of refuse. `_constant_read_sites` publishes one entry per
    # read of a class-level constant, and the entry is a 3-tuple for an enum
    # member (`struct, kind, accessor`) and a 2-tuple for every other spelling.
    # `_apply_constant_sites` destructured both; `refuse_none_comparisons`
    # destructured one, so this program raised
    # `ValueError: too many values to unpack (expected 2, got 3)` out of the
    # middle of `_prepare_functions` — the backend falling over on a construct it
    # owes a refusal for, and doing it on four of this repository's own files
    # (`type_system.py` and three that import it).
    #
    # It is here, in this table, because the row above it is the one that says
    # "this check still refuses where the language says it must": together they
    # separate "the crash is gone" from "the check was dropped". One shape for
    # every entry (`formal/build.py`'s `_constant_site`) is what fixed it, rather
    # than a patch to the one caller that had destructured the other shape.
    ("refuse_none_in_a_file_that_also_reads_an_enum_member",
     "from enum import Enum\n"
     "\n"
     "class Reg(Enum):\n"
     "    RAX = 0\n"
     "    R15 = 15\n"
     "\n"
     "struct R:\n"
     "    var b: Int = None\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    var r = R()\n"
     "    if r.b == 0:\n"
     "        return 7\n"
     "    if Reg.R15.value == 15:\n"
     "        return 8\n"
     "    return 0\n",
     "refuse:is class-level constant holding `None`", None),
    # And the enum member read ALONE still answers, which is the other direction
    # an over-correction would break: a uniform table shape must not cost the
    # spelling that carries a third element. The two `if`s are in the wrong order
    # on purpose — the answer here is 8, and it is 8 only because the comparison
    # that must be REFUSED comes first.
    ("enum_member_read_answers_without_a_none_constant",
     "from enum import Enum\n"
     "\n"
     "class Reg(Enum):\n"
     "    RAX = 0\n"
     "    R15 = 15\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    if Reg.R15.value != 15:\n"
     "        return 7\n"
     "    return 8\n",
     8, None),
    # ── WHAT AN ENUM MEMBER IS, on this path ────────────────────────────────────
    #
    # The value model answers "is an enum member its `.value`, or is it an
    # object?" ONCE, and both rows below are consequences of the same answer —
    # a member IS its value, and the member's IDENTITY is not in the word.  They
    # cannot be allowed to disagree, so they are written as a pair: the first is
    # the value model making a program answerable, the second is the value model
    # refusing the one construct the word cannot express.  The bug doc is
    # `3b733724` decided it, and it asked for the question to be decided rather
    # than patched.
    #
    # THE REFUSAL, and it is a wrong answer this closes.  A member read
    # materializes to its value (`printf("%d", Reg.A)` prints 7 for `A = 7`), so
    # two members whose values are equal are ONE word, and comparing them answers
    # by value where CPython answers by identity.  Measured on both
    # architectures: with `A = 1` and `B = 1` this printed `same`, and CPython
    # says False.
    ("refuse_two_enum_members_compared_to_each_other",
     "from enum import Enum\n"
     "\n"
     "class Reg(Enum):\n"
     "    A = 1\n"
     "    B = 1\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    if Reg.A == Reg.B:\n"
     "        printf(\"same\")\n"
     "    else:\n"
     "        printf(\"diff\")\n"
     "    return 0\n",
     "refuse:are both reads of MEMBERS of the enum `Reg`", None),
    # THE SAME COMPARISON against itself, which answers True for the wrong
    # reason and is invisible — which is why the rule refuses the shape instead
    # of trying to tell the two apart.  Without this row a narrower rule that
    # compared the two SPELLINGS would pass the row above.
    ("refuse_a_member_compared_with_itself",
     "from enum import Enum\n"
     "\n"
     "class Reg(Enum):\n"
     "    A = 1\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    if Reg.A == Reg.A:\n"
     "        printf(\"same\")\n"
     "    else:\n"
     "        printf(\"diff\")\n"
     "    return 0\n",
     "refuse:are both reads of MEMBERS of the enum `Reg`", None),
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

    # The basic left-strip: a three-character run of spaces, and the two
    # degenerate operands beside it, all observed on stdout through printf.
    #
    # This comment used to describe a leading run of "all three of tab/space"
    # and to explain that a `\t` in it reached the image as a backslash and a
    # `t`, because string literals were not unescaped on this path. Neither is
    # true: the case below holds three SPACES and no tab, and a literal's
    # escapes are decoded (`9023031b`; see the `str_lstrip_all_whitespace`
    # comment below, which is where the tab case lives and which carries the
    # measurement).
    ("str_lstrip_prints",
     "def main(n):\n"
     "    printf(\"[%s][%s][%s]\\n\", \"   hi\".lstrip(), \"hi\".lstrip(),\n"
     "           \"\".lstrip())\n"
     "    return 0\n", 0, "[hi][hi][]"),
    # The all-whitespace and empty cases, which are where a scan that forgets
    # to stop at the terminator walks off the end of the buffer. An all-space
    # string strips to the empty string, and so does the empty one.
    #
    # The second operand is a REAL TAB and it strips to nothing, which it did
    # not used to. It was a BACKSLASH and a `t` — two characters, with the
    # backslash left alone because a backslash is not whitespace — and this
    # case asserted that, in a comment that gave the representation as the
    # reason. Both `fire.py run` and `fire.py build` decode a literal's escapes,
    # so the formal backends were the odd one out;
    # FORMAL_string_literal_escape_is_not_decoded measured it and the
    # decode now happens in `_intern_string`. CPython returns "" here too, so
    # this is the third engine agreeing with the other two rather than a new
    # answer: `lstrip` on a tab is "" on every engine in this repository now.
    ("str_lstrip_all_whitespace",
     "def main(n):\n"
     "    printf(\"[%s][%s]\\n\", \"   \".lstrip(), \"\\t\".lstrip())\n"
     "    return 0\n", 0, "[][]"),
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
    # The ninth FLOATING conversion of a variadic call, which is the boundary
    # of `model.printf_argument_classes`'s placement and the reason the boundary
    # is a refusal rather than an approximation. SysV AMD64 has eight XMM
    # registers, so the ninth `double` is an overflow argument in the caller's
    # frame at a slot nothing on this path assigns; the eight that fit are
    # placed by `encode_movq_xmm_rm64`.
    #
    # `refuse_either:` because the two backends refuse for DIFFERENT and both
    # honest reasons — arm64 has no second register file at all (AAPCS passes
    # everything in x0..x7) and says the variadic stack area is unplaced, while
    # x86-64 says what its own ABI says the ninth one is. Same verdict, and the
    # shared-text rule cannot apply because the two limits are genuinely
    # different facts about two ABIs.
    ("limit_a_ninth_floating_printf_operand",
     "def main(n: Int) -> Int:\n"
     "    var a = 4607182418800017409\n"
     "    printf(\"%f %f %f %f %f %f %f %f %f\",\n"
     "           a, a, a, a, a, a, a, a, a)\n"
     "    return 0\n",
     "refuse_either:floating conversions"
     "|puts 2 of them past the 8 argument registers", None),
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
     # `print("v = %d\n", …)` — the EXPECTED stdout carries a real NEWLINE,
     # because a string literal is decoded before it is interned and
     # `fire.py run` / `fire.py build` both print a real newline there too
     # (FORMAL_string_literal_escape_is_not_decoded). It used to carry
     # a literal backslash-n, which was this suite asserting the bug.
     0, "v = %d\n 7"),
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
     # `print("v = %d\n", …)` — the EXPECTED stdout carries a real NEWLINE,
     # because a string literal is decoded before it is interned and
     # `fire.py run` / `fire.py build` both print a real newline there too
     # (FORMAL_string_literal_escape_is_not_decoded). It used to carry
     # a literal backslash-n, which was this suite asserting the bug.
     0, "v = %d\n 7"),
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
     # The expected stdout carries a real NEWLINE: a string literal is
     # decoded before it is interned, so `print`'s `\n` is the newline printf
     # writes. It used to carry a LITERAL backslash-n, which was this suite
     # asserting the bug (FORMAL_string_literal_escape_is_not_decoded).
     0, "len=%d\n 0"),

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
# The unescaping boundary, and it is the reason this case exists at all.
     # REWRITTEN, because the claim in the comment it replaces was FALSE: it
     # said a string literal is stored UNESCAPED on this path, so `"\t"` is a
     # BACKSLASH and a `t`. That was true until
     # FORMAL_string_literal_escape_is_not_decoded, which measured the
     # opposite — the formal backends intern the RAW source text because they
     # are the one engine here that does not hand a literal to a C compiler to
     # decode it, so `len("\t")` was 4-spelled-2 and a printed line ending came
     # out as a literal `\n`. Both other engines in this repository
     # (`fire.py run`, `fire.py build`) decoded it all along, so the boundary
     # was the parser and BOTH consumers decoded; now all three do.
     #
     # The boundary is still what this case tests, and it is still four
     # different ways to get it wrong, which is why the assertions are kept
     # rather than deleted with the comment:
     #   the letter `t` is NOT in a tab      (1 -> absent)
     #   the letter `x` is NOT in a tab      (2 -> absent)
     #   a tab is not TWO characters         (4 -> absent)
     # and `r` therefore stays 0, which is what CPython prints for the same
     # program. `"\t" in "\t"` (both sides a literal, folded at compile time)
     # is the pair that makes the two lowerings comparable — see
     # `str_membership_literal_fold_agrees_with_the_call`.
     ("str_membership_on_the_decoded_representation",
      "def main(n):\n"
      "    r = 0\n"
      "    if \"t\" in \"\\t\":\n"
      "        r = r + 1\n"
      "    if \"x\" in \"\\t\":\n"
      "        r = r + 2\n"
      "    if len(\"\\t\") == 2:\n"
      "        r = r + 4\n"
      "    printf(\"r=%d\\n\", r)\n"
      "    return 0\n", 0, "r=0"),
     # The same expression with a NAME in it, which is the shape that makes the
     # libc `strstr` rather than the compile-time fold. It exists so the two
     # lowerings are pinned to the SAME answer on the same text: a haystack
     # name's bytes are the interned literal's bytes, so a fold that read raw
     # source text and a call that read interned bytes could disagree, and
     # nothing else in this file compares them.
     ("str_membership_literal_fold_agrees_with_the_call",
      "def main(n):\n"
      "    s = \"\\t\"\n"
      "    r = 0\n"
      "    if \"t\" in s:\n"
      "        r = r + 1\n"
      "    if \"\\t\" in s:\n"
      "        r = r + 2\n"
      "    if \"x\" in s:\n"
      "        r = r + 4\n"
      "    printf(\"r=%d\\n\", r)\n"
      "    return 0\n", 0, "r=2"),
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

    # ── a string literal's ESCAPES are decoded, on this path too ────────────
    #
    # `fire.py run` and `fire.py build` both decoded a literal's escapes and
    # the formal backends did not, because they are the one engine in this
    # repository that does not hand the literal's text to a C compiler to
    # decode for it. So `len("a\nb")` was 4 where every other engine says 3,
    # and `print("a\nb")` wrote a backslash and an `n`. See
    # FORMAL_string_literal_escape_is_not_decoded for the measurement;
    # these are the cases that pin the fix, and each one is a different way to
    # get the decode wrong rather than a restatement of the first.
    #
    # `len` of an escaped literal — the arithmetic form of the defect, so it
    # cannot be explained away as a printing artefact. Three escapes in one
    # program because each decodes to a DIFFERENT byte and a decoder that only
    # knew `\n` would pass two of the three.
    ("str_escape_len_is_decoded",
     "def main(n):\n"
     "    printf(\"%d %d %d %d\\n\", len(\"a\\nb\"), len(\"\\t\"), "
     "len(\"a\\\\b\"), len(\"q\\\"q\"))\n"
     "    return 0\n", 0, "3 1 3 3"),
    # The PRINTED BYTES, which is the symptom a user sees. `od -c` on this
    # program's output on both architectures is
    #   a \n b \n x \t y \n \n
    # and the case's expected stdout is the same three lines, so a decoder that
    # dropped an escape, doubled one, or left the backslash in place all fail
    # here even where `len` happened to agree.
    ("str_escape_printed_bytes_are_decoded",
     "def main(n):\n"
     "    print(\"a\\nb\")\n"
     "    printf(\"c\\nd\\n\")\n"
     "    print(\"\\tx\\ty\\n\")\n"
     "    return 0\n", 0, "a\nb\nc\nd\n\tx\ty\n\n"),
    # A BACKSLASH the source meant, twice over, and this is the case that
    # caught a second bug in the fix rather than in the original defect. The
    # decode happens in `_intern_string`, and `print`'s format string is
    # interned too — so decoding it once in the format builder and again in
    # the intern would turn the second of these two strings into a real
    # newline.
    #
    # Two spellings one level apart, which is the whole point:
    #   `"a\nb"`  the body is a, backslash, n, b — a REAL newline → 3
    #   `"a\\nb"` the body is a, backslash, backslash, n, b → a LITERAL
    #             backslash and an `n` → 4
    # A fix that decoded twice, or not at all, gets the first right and the
    # second wrong (5 and a real newline) or (4 and 4, with the first printing
    # `a\nb`), so the pair distinguishes them. This is the case `print` and
    # `len` are both in because they take different paths — one builds a
    # format string that is interned, the other a length.
    ("str_escape_a_literal_backslash_stays_one_backslash",
     "def main(n):\n"
     "    a = \"a\\nb\"\n"
     "    b = \"a\\\\nb\"\n"
     "    printf(\"%d %d\\n\", len(a), len(b))\n"
     "    print(a)\n"
     "    print(b)\n"
     "    return 0\n", 0, "3 4\na\nb\na\\nb\n"),
    # A `%` that ARRIVES FROM AN ESCAPE, which is the case that found the
    # ordering bug: `print_literal` doubles `%` because a format string is not
    # a string, and it used to do that on the RAW text — where `print("\x25")`
    # is a backslash, an `x`, a `2` and a `5`, with no `%` to double. printf
    # was then handed a bare `%` and read a vararg it was never given, so it
    # printed an EMPTY LINE. `100% done` sits beside it because that spelling
    # has a real `%` in the source and printed correctly all along, which is
    # what makes the pair a diagnosis rather than two coincidences.
    ("str_escape_a_percent_sign_from_an_escape_is_not_a_conversion",
     "def main(n):\n"
     "    print(\"\\x25\")\n"
     "    print(\"100% done\")\n"
     "    printf(\"q=%s\\n\", \"a\\x25b\")\n"
     "    return 0\n", 0, "%\n100% done\nq=a%b\n"),
    # An escape that is NOT one of the simple set is left alone, backslash and
    # all, which is CPython's own behaviour and what `gimple_codegen._c_escape`
    # passes through to C. A decoder that refused an unknown escape, or that
    # dropped the backslash, would change this program's answer; one that
    # guessed a meaning would too. `\d` is a regex fragment and is in the
    # corpus in real literals, so this is not a synthetic spelling.
    ("str_escape_an_unknown_escape_keeps_its_backslash",
     "def main(n):\n"
     "    printf(\"%d\\n\", len(\"\\d\"))\n"
     "    print(\"\\d\")\n"
     "    return 0\n", 0, "2\n\\d\n"),
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

    # ── ITERATING a string is refused, and the refusal is measured ──────────
    #
    # `“FORMAL: iterating a string reads its first eight bytes as an element COUNT”`. The loop family — `for x
    # in s` and `[x for x in s]` — walks its iterable as a BLOB, and a blob's
    # first word is its element COUNT. A `char *` has no header word, so the
    # count is the first eight bytes of TEXT: on the tree this was measured on,
    # `for c in "abc"` returned 97 on x86-64 ('a' read as the count) and died
    # of SIGBUS on arm64, for the SAME source. Refusing is the honest answer
    # because a string has no length in this representation — see the case
    # below for what is still true of it.
    #
    # Both shapes are here because `_emit_compr_gen` is a SEPARATE lowering
    # from the for-in, and each raises from its own place: a fix that added the
    # check to one of them would leave the other building a wrong answer.
    ("string_iteration_for_in_is_refused",
     "def main(n):\n"
     "    var t = 0\n"
     "    for c in \"abc\":\n"
     "        t = t + 1\n"
     "    return t\n",
     "refuse:iterating a string is a CONTAINER operation", None),
    ("string_iteration_comprehension_is_refused",
     "def main(n):\n"
     "    var xs = [c for c in \"abc\"]\n"
     "    return len(xs)\n",
     "refuse:iterating a string is a CONTAINER operation", None),
    # The two surfaces that DO work on a `char *`, in the same program as the
    # refusal above, so a fix that widened the refusal to strings generally
    # would go red here rather than looking like a stricter backend. `len` is
    # a `strlen` to the NUL and `s[i]` is `s + i`; neither reads a count word.
    ("string_len_and_subscript_still_work",
     "def main(n):\n"
     "    printf(\"%d %d\\n\", len(\"abcd\"), \"abcd\"[1])\n"
     "    return 0\n", 0, "4 98"),
    # And a comprehension over a LIST OF STRINGS, which is the spelling the
    # refusal's own message recommends and the one the stdlib reaches for. It
    # is a different lowering from either case above — the elements are
    # `char *` and the walk is over the blob — so it is the case that shows the
    # refusal is about the ITERABLE's representation and not about strings
    # being unable to be elements.
    ("a_comprehension_over_a_list_of_strings_is_not_refused",
     "def main(n):\n"
     "    var xs = [c for c in [\"a\", \"b\", \"c\"]]\n"
     "    printf(\"%d %s\\n\", len(xs), xs[2])\n"
     "    return 0\n", 0, "3 c"),

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
    # ── an f-string is a LITERAL WHOSE TEXT IS NOT ITS VALUE ──
    #
    # Found by `tools/formal_fuzz.py` widening its corpus to string
    # formatting; before this case the same source printed the literal's own
    # SPELLING on both architectures, with exit status 0:
    #
    #     n = 7
    #     printf("[%s]\n", f"n={n}")     ->  [f"n={n}"]   CPython: [n=7]
    #
    # The parser keeps an f-string's whole source token as the literal's value
    # (`fire_compiler.py`'s t/f-string placeholder, which `myinterpreter` and
    # `gimple_codegen` both read) and `decoded_literal` — the reader every
    # engine shares — handed that text to the emitters, so the interpolation was
    # never evaluated. Refused rather than lowered: composition needs a buffer,
    # and a string on this path is a bare `char *` interned into read+execute
    # `__TEXT` (the same missing buffer as `str_concat_refused` above).
    ("fstring_literal_refused",
     "def main(n):\n"
     "    k = 7\n"
     "    printf(\"[%s]\\n\", f\"n={k}\")\n"
     "    return 0\n",
     "refuse:an f-string literal", None),
    # The t-string, which is the OTHER prefix that keeps its token and the same
    # reader: one case each, because the two are different literals with
    # different messages and a rule that caught only `f` would leave `t` printing
    # `t"n={n}"`.
    ("tstring_literal_refused",
     "def main(n):\n"
     "    k = 7\n"
     "    printf(\"[%s]\\n\", t\"n={k}\")\n"
     "    return 0\n",
     "refuse:a t-string literal", None),
    # The GUARD, and it is the half that could have gone the other way: an
    # ordinary string that happens to CONTAIN braces and a quote is still an
    # ordinary string, and a rule that matched on text instead of on the prefix
    # would refuse every program that prints a template. Three spellings — no
    # braces at all, braces with no quotes, and a brace-ful string after a
    # percent — in one program, so the first refusal is the one that fires and
    # the case is one assertion about the family.
    ("braces_in_an_ordinary_string_are_not_a_fstring",
     "def main(n):\n"
     "    a = \"{}\"\n"
     "    b = \"{not a field}\"\n"
     "    c = \"%d%s\"\n"
     "    printf(\"[%s][%s][%s]\\n\", a, b, c)\n"
     "    return 0\n", 0, "[{}][{not a field}][%d%s]"),

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
    # `not s` was a FABRICATED FALSITY rather than a fabricated number, and it
    # was the worst of the set for that reason: a pointer is never zero, so the
    # old lowering (`cmp #0; cset eq` on the operand's own word) said `not s` is
    # False for every string INCLUDING THE EMPTY ONE.  Observed on the pre-change
    # tree, on both backends: `s = "abc"; e = ""; printf("%d %d", 1 if not s else
    # 0, 1 if not e else 0)` printed `0 0`.  Python's answer is `0 1` — a program
    # testing a string for emptiness is told the empty string is non-empty.
    #
    # It is now the SAME conversion `if s:` makes — `truthy_lowering`, i.e. the
    # `strlen` the refusal itself told the reader to write by hand — so the two
    # spellings of one question cannot come to disagree.  The empty string is the
    # case that separates a correct lowering from a null test, which is why it is
    # the first thing to check any change here against.
    ("not_a_string_is_the_truthiness_conversion",
     "def main(n):\n"
     "    s = \"abc\"\n"
     "    e = \"\"\n"
     "    printf(\"%d %d\", 1 if not s else 0, 1 if not e else 0)\n"
     "    return 0\n", 0, "0 1"),
    # The other two rows of the same table, in the same program, because a fix
    # that made `not` a `strlen` for strings only would be "refuse every `not`"
    # with extra steps: an integer is 0 or it is not, and a container's
    # truthiness IS its count, so `not []` is True.  And a SHORT-CIRCUIT chain,
    # which is the operand whose truthiness is not the truthiness of the word it
    # evaluates to — `p and ""` yields the EMPTY STRING, so `not` of it is True
    # even though `p` is not.  All four values are what Python prints.
    ("not_of_an_int_a_container_and_a_short_circuit_chain",
     "def main(n):\n"
     "    a = 0\n"
     "    b = 3\n"
     "    xs = [1]\n"
     "    ys = []\n"
     "    p = \"x\"\n"
     "    printf(\"%d %d %d %d\", 1 if not a else 0, 1 if not b else 0,"
     " 1 if not xs else 0, 1 if not ys else 0)\n"
     "    if not (p and \"\"):\n"
     "        printf(\" chain\")\n"
     "    return 0\n", 0, "1 0 0 1 chain"),
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
    # ── the store a one-field receiver CANNOT deliver ───────────────────────
    #
    # The two ANSWERED rows of this group are `BOTH_ARCH_CASES`
    # (`both_arch_two_field_store_through_a_plain_receiver_still_reaches_it`
    # and the `__init__` guard beside it); these two are here because a
    # `refuse:` expectation is what `run_case` dispatches on both backends.
    #
    # Found by `tools/formal_fuzz.py`, and the shape above is why the two rows
    # before it did not catch it: they are about a REBINDING of the receiver,
    # which CPython also does not deliver, so leaving it alone is right. This is
    # a store to the FIELD, which CPython DOES deliver — into the object the
    # caller holds — and which this path computed and dropped:
    #
    #     class C:
    #         def __init__(self): self.a = 2
    #         def bump(self):     self.a = 7
    #         def get(self):      return self.a
    #     c = C(); c.bump(); print(c.get())      # CPython 7, this path 2
    #
    # Builds, ran, exited 0, and printed the constructor's value on BOTH
    # architectures. `model.one_field_dropped_receiver_stores` is the rule and
    # `receiver_writeback_name` is the mechanism it is about: the write-back
    # needs the receiver declared `out`/`inout`/`mut`, and a plain `self` is
    # never handed back. Refused rather than delivered, because the one return
    # word is the receiver and delivering the store would cost the method's own
    # value — the same ABI reason `mutating_receiver_return_refusal` gives.
    #
    # The needle is the LOAD-BEARING half of the message: it says the receiver
    # is not handed back. A message that only said "one-field receiver" would be
    # indistinguishable from a one-field READER, which builds.
    ("refuse_a_one_field_store_through_a_plain_receiver",
     "class C:\n"
     "    def __init__(self):\n"
     "        self.a = 2\n"
     "\n"
     "    def bump(self):\n"
     "        self.a = 7\n"
     "\n"
     "    def get(self):\n"
     "        return self.a\n"
     "\n"
     "def main(n):\n"
     "    c = C()\n"
     "    c.bump()\n"
     "    printf(\"a=%d\", c.get())\n"
     "    return 0\n",
     "refuse:is not a receiver this path hands back", None),
    # The `+=` spelling is a separate AST node (`AugAssignStmt`), so the rule
    # reads it explicitly and a fix that only walked `AssignStmt` would pass the
    # row above and miss this one — which is the shape every in-place operator
    # in the stdlib is written with.
    ("refuse_a_one_field_augmented_store_through_a_plain_receiver",
     "class C:\n"
     "    def __init__(self):\n"
     "        self.a = 2\n"
     "\n"
     "    def bump(self):\n"
     "        self.a += 5\n"
     "\n"
     "    def get(self):\n"
     "        return self.a\n"
     "\n"
     "def main(n):\n"
     "    c = C()\n"
     "    c.bump()\n"
     "    printf(\"a=%d\", c.get())\n"
     "    return 0\n",
     "refuse:is not a receiver this path hands back", None),
    # ── `var self` is a SPELLING this path does not hand back either ────────
    #
    # The same rule, one corpus site over, and the pair is a DECISION rather
    # than two independent facts: `formal/model.py`'s
    # `MUTATING_RECEIVER_CONVENTIONS` holds `out` and `mut` and NOT `owned`,
    # which is what `var self` and `owned self` both fold to in the parser. The
    # corpus is what settled that, measured over 690 `.py`/`.mojo` files with
    # the rule's own recogniser: 17 methods of a ONE-FIELD struct store that
    # struct's own field, and 13 of them declare `mut`. Exactly ONE declares
    # `var self` — `std/python/python_object.mojo`'s `PythonObject.steal_data`
    # — and its file is a host-import the sweep never answers, so nothing this
    # path can build changes.
    #
    # So the refusal names the convention it read rather than only saying "not
    # handed back", and the needle below is that name: a message which said
    # nothing about `var self` would send the reader to look for a one-field
    # receiver problem, and the fix is one word of source.
    ("refuse_a_one_field_store_through_a_var_self_receiver",
     "class Holder:\n"
     "    def __init__(self):\n"
     "        self._obj_ptr = 7\n"
     "\n"
     "    def steal_data(var self):\n"
     "        var ptr = self._obj_ptr\n"
     "        self._obj_ptr = 0\n"
     "        return ptr\n"
     "\n"
     "    def peek(var self):\n"
     "        return self._obj_ptr\n"
     "\n"
     "def main(n):\n"
     "    h = Holder()\n"
     "    printf(\"p=%d\", h.steal_data())\n"
     "    return 0\n",
     "refuse:`var self` is not a receiver this path hands back", None),
    # The other half of the decision, and the row that says it is not a blanket
    # "a `var self` receiver is refused": 195 of the corpus's 196 methods with a
    # NON-mutating convention are READERS, where `owned`/`var self` is exactly
    # right. Adding `owned` to the list would make every one of them a
    # write-back candidate, and for a one-field struct the write-back IS the
    # receiver — so `mutating_receiver_return_refusal` would start firing on
    # every reader that already returns something, which is what the corpus
    # measurement above is counting against. This row is the readers' side of
    # that trade: `var self` builds, and answers CPython.
    ("both_arch_a_one_field_reader_through_a_var_self_receiver_still_builds",
     "class Holder:\n"
     "    def __init__(self, v):\n"
     "        self._obj_ptr = v\n"
     "\n"
     "    def peek(var self):\n"
     "        return self._obj_ptr\n"
     "\n"
     "def main(n):\n"
     "    h = Holder(41)\n"
     "    printf(\"p=%d\", h.peek())\n"
     "    return 0\n", 0, "p=41"),
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
 # `__mlir_bool__` IS implemented, for every receiver whose DECLARED type says
 # `Bool` — `build._lower_dialect_select` rewrites it to `x != 0` in the shared
 # pipeline, and `test_formal_mlir_precedence.py`'s
 # `a_dialect_select_lowers_when_the_condition_declares_a_bool` builds and RUNS
 # `std/utils/_select.mojo` on both architectures.
 #
 # So this row is the half that is still refused, and the difference is the
 # DECLARATION: `c = n > 3` states nothing about what `c` holds, and an
 # unannotated word is an integer here, so `(c != 0)` would answer 1 for a
 # `char *`. The needle is the guard and the repair, not the impossibility — a
 # reader should come away knowing to annotate the receiver, and that the
 # missing thing is the declared type rather than a new kind.
 #
 # (A local bound to a COMPARISON is provably a Bool too, and this pass
 # deliberately does not claim it: the annotation is what the SOURCE says about
 # the name, while a comparison is a fact about the value's provenance, and the
 # two are different questions. Widening it belongs with the rest of the value
 # model, not here.)
 ("recvkind_mlir_bool_needs_a_declared_bool",
  "def main(n):\n"
  "    c = n > 3\n"
  "    k = c.__mlir_bool__()\n"
  "    return 0\n",
  "refuse:Annotate the receiver `Bool`", None),
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
 #
 # The needle says "classified as 'int'" where it used to say nothing about a
 # kind, and the wording moved because `Box.__init__` literally stores `3`:
 # `model.struct_ctor_field_value` reads the field's value off the construction
 # that filled the slot, so the receiver now HAS a kind and the message can name
 # it.  That is the same refusal on the same program — a word that is not a
 # descriptor — with more said about it, and `3` is a true claim about `b.fd`
 # rather than a convenient one.
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
  "refuse:frame slot classified as 'int'", None),
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
    # A function whose NAME is a Python builtin, defined here. This is a GUARD,
    # and the side it guards is the one `formal/model.py`'s
    # `UNIMPLEMENTED_BUILTINS` table could plausibly take away: that table is
    # consulted by `frame_undefined_callee_refusal`, whose whole subject is a
    # callee this build compiles NOWHERE, so a locally defined `getattr` must
    # keep being an ordinary function that takes a frame receiver by reference
    # and returns 7. If a change made the table name-only, this case would start
    # being refused with "getattr is a Python BUILTIN … no part of this path
    # implements it" — false about this program, which implements it.
    #
    # Labelled a GUARD rather than a demonstration because it was already true
    # before the table existed; it is here because the table is a name test and
    # a name test is exactly the kind of change that can be wrong in this
    # direction silently.
    ("byref_a_local_getattr_is_not_the_builtin",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def getattr(o: P, name: Int) -> Int:\n"
     "    return o.a + o.b\n\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    p.a = 3\n"
     "    p.b = 4\n"
     "    return getattr(p, 0)\n", 7, None),
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
#
# `formal-frame-escape` MOVED `byref_refuse_returned` out of this list rather
# than updating it, and the move is right: the case asserted that `return p`
# from the function that built `p` is refused, which was true and is no longer.
# The object now outlives its creator, so leaving a case here that says
# "refused" about a construct that builds would be a test asserting the
# opposite of the truth. It is a demonstration in
# `test_formal_returned_frame.py` now, beside the rest of the family.
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
    # The NEGATIVE half of `byref_delegating_constructor_stores_a_parameter_frame`
    # in `BYREF_CASES`, and the case that keeps that rule from being written as
    # "a method may store a frame in a field". The one fact that separates them
    # is WHERE the frame was made: `r` arrived as a parameter, so the CALLER
    # reserved it and it cannot outlive the slot; `t` is built here, in this
    # method's own scratch, and the slot may well outlive the call — the object
    # `h` is the caller's and `h.src` is read after `grab` has returned.
    #
    # Nothing reads `h.src` in this program on purpose. The store itself is the
    # defect, so a case that also read the field would be decided by whichever
    # of the two rules came first, and the needle here would be a sentence about
    # a read.
    ("byref_refuse_a_field_store_of_a_frame_built_here",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "struct Holder:\n"
     "    var src: R\n"
     "    var n: Int\n\n"
     "    def grab(out self):\n"
     "        var t = R()\n"
     "        t.a = 5\n"
     "        t.b = 6\n"
     "        self.src = t\n"
     "        self.n = 1\n\n"
     "def main(n: Int) -> Int:\n"
     "    var h = Holder()\n"
     "    h.grab()\n"
     "    return h.n\n",
     "refuse:is stored in the field 'self.src'", None),
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
    # A PYTHON BUILTIN rather than a name somebody forgot to declare. The arm
    # above says "this module defines no FUNCTION of that name … and no
    # `from … import …` in it binds the name either", and for a builtin both of
    # those are impossible — the name comes from the LANGUAGE — so the sentence
    # sent the reader to look for a missing `def` that cannot exist. `type_of`
    # is on the list because `std/memory/unsafe_pointer.mojo` is refused with
    # this very message and the honest reading of that sentence is "`type_of` is
    # a missing builtin, on any receiver"; the two cases below are the two
    # families `model.UNIMPLEMENTED_BUILTINS` carries, and the needle is the
    # clause that names what the callee is rather than what this file lacks.
    #
    # The prefix "which is a name with no definition in hand" is asserted by
    # neither needle and is load-bearing anyway: two taxonomies key on that
    # exact substring (`tools/formal_sweep.py`'s `_FRAME_ESCAPES` and
    # `tools/formal_sweep_causes.py`), so an arm that reworded the opening would
    # silently move files out of the family they are counted in.
    ("byref_refuse_type_of_names_the_builtin",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    p.a = 3\n"
     "    p.b = 4\n"
     "    return type_of(p)\n",
     "refuse:type_of` is a Python BUILTIN", None),
    ("byref_refuse_getattr_names_the_builtin",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "def main(n) -> Int:\n"
     "    var p = P()\n"
     "    p.a = 3\n"
     "    p.b = 4\n"
     "    return getattr(p, \"a\")\n",
     "refuse:getattr` is a Python BUILTIN", None),
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
    # A ONE-FIELD MUTATOR across the boundary, and the third of the three
    # measured shapes that used to drop the receiver write-back: the old
    # statement-shaped rewrite was built from `one_field_mutating_methods`, a
    # PER-MODULE table of the methods this unit compiles, so a call whose callee
    # is a SYMBOL was never rewritten at all. Measured before: built, ran, and
    # printed `c=10` where CPython says 15, on both architectures — the callee
    # computed the new value and the caller kept the old word.
    #
    # The callee's convention now crosses with the symbol:
    # `formal/imports.py`'s `external_declarations` parses the imported module's
    # own source, indexes its METHOD exports under their lifted names and carries
    # the owning struct on each declaration, so `model.declared_receiver_writeback`
    # answers the same question for a callee in another image that it answers for
    # one in this — and a boundary whose contract only held inside a module was
    # not a boundary contract.
    #
    # Both halves in one program, and in that order, because either alone can
    # pass: `c=15` says the write-back crossed (a value-only convention leaves it
    # at 10) and `a=15 c=14` says the DECLARED value came back out of the callee
    # AND the receiver moved again, which is `BinaryHeap.pop`'s shape at a dylib
    # boundary. `both: True` so both architectures are asked, since a disagreement
    # about what an address means is exactly what a single-file case cannot see.
    ("byref_cross_module_one_field_mutator",
     {"mod": "struct Cell:\n"
             "    var _value: Int\n"
             "\n"
             "    def bump(out self, k: Int):\n"
             "        self._value = self._value + k\n"
             "\n"
             "    def pop(out self) -> Int:\n"
             "        var old = self._value\n"
             "        self._value = self._value - 1\n"
             "        return old\n",
      "main": "from byref_xmod import Cell\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var c = Cell()\n"
              "    c._value = 10\n"
              "    c.bump(5)\n"
              "    printf(\"c=%d\", c._value)\n"
              "    var a = c.pop()\n"
              "    printf(\" a=%d c=%d\", a, c._value)\n"
              "    return 0\n", "both": True}, 0, "c=15 a=15 c=14"),
    # A frame address handed to an IMPORTED FREE FUNCTION — the third shape a
    # "callee this image does not compile" can be, and the one whose refusal was
    # false. `take_it` IS defined (in `byref_xmod`, which builds: it exports
    # `take_it` and this case's own module does not fail), so "this module's own
    # functions are the only ones in this image" was false of it and sent the
    # reader looking for an export that is exported.
    #
    # It was a REFUSAL and is now a POSITIVE case, and that is the whole
    # content of the change: the callee module's manifest publishes a
    # per-parameter frame-holder contract (`frame_params`), `take_it`'s
    # parameter 0 is a holder of `P` there, and this image also has a `P` — so
    # `base + 8k` means the same thing on both sides and the address is
    # followed. `take_it` reads `p.a` through the parameter, so the answer is
    # only right if the address really is the caller's `P` frame: 3*10 + 4 = 34,
    # plus `n` = 10, so 44.
    #
    # The module reads BOTH fields and the caller reads both back afterwards,
    # so a wrong address shows up as a wrong number rather than as a
    # coincidence. (`byref_cross_module_wide_receiver_writes` is the same
    # property for the method half; this is the free-function half.)
    ("byref_cross_module_free_function_reads",
     {"mod": "struct P:\n"
             "    var a: Int\n"
             "    var b: Int\n"
             "\n"
             "def take_it(p: P) -> Int:\n"
             "    return p.a * 10 + p.b\n",
      "main": "from byref_xmod import P, take_it\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var p = P()\n"
              "    p.a = 3\n"
              "    p.b = 4\n"
              "    return take_it(p) + n\n"}, 44, None),
    # The WRITE half, and the case that would catch a fix which only got the
    # read right: `bump` writes `p.a` through its parameter and the caller
    # reads `p.a` back on its OWN side afterwards. A hand-off that passed a
    # copy, a re-created block, or any word other than the caller's frame
    # address would leave `p.a` at 3 and return 46; the address is right only if
    # `p.a` reads 8 here, which is what the 96 against 46 says. The contract is
    # per-parameter and says nothing about direction, so a store through the
    # parameter is exactly as load-bearing as a load.
    #
    # The call is its own STATEMENT on purpose. Folding it into the return
    # expression — `return p.a * 10 + p.b + bump(p, 5)` — reads `p.a` BEFORE
    # the call, in CPython and here alike, so it returns 46 and the case would
    # pass with the write going nowhere. An earlier draft of this case did
    # exactly that and "passed" for that reason.
    ("byref_cross_module_free_function_writes",
     {"mod": "struct P:\n"
             "    var a: Int\n"
             "    var b: Int\n"
             "\n"
             "def bump(p: P, by: Int) -> Int:\n"
             "    p.a = p.a + by\n"
             "    return p.a + p.b\n",
      "main": "from byref_xmod import P, bump\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var p = P()\n"
              "    p.a = 3\n"
              "    p.b = 4\n"
              "    var r = bump(p, 5)\n"
              "    return p.a * 10 + p.b + r\n"}, 96, None),
    # ── a FOLDED MODULE CONSTANT as a `memset` byte, INSIDE A MODULE DYLIB ──
    #
    # `folded_module_constant_as_a_memset_byte` above pins the property in a
    # PROGRAM; this is the shape it does not have. `formal/hostmods/argparse.mojo`
    # spells `memset(pat + i, PAT_DASH, 1)` in a file that is compiled as a
    # DYLIB every time a program imports `argparse`, so a substitution that
    # reached only the program path would leave the module refusing with
    # "'PAT_DASH' has no home" — a diagnostic whose subject is a line in
    # somebody else's module, reported against the program that merely imported
    # it. `FORMAL_argparse_memset_constants_comment_is_stale` is the
    # measurement, and its step 3 is this row: the reproducer had to be a module
    # dylib because that is the shape in which it was found.
    #
    # `both`, because a byte folded to the wrong value is a value neither
    # architecture's parser would notice on its own, and the reference buffer is
    # written INLINE on the caller's side — so the folded name is the only thing
    # under test and both machines have to agree it is 45 and then 65. 0 is
    # `memcmp == 0` twice over, and a `memcmp` that compared nothing could not
    # produce it: the buffers differ in every byte the fill wrote.
    ("byref_folded_module_constant_as_a_memset_byte_in_a_dylib",
     {"mod": "PAT_DASH = 45\n"
             "PAT_A = 65\n"
             "\n"
             "def fill(pat, n):\n"
             "    var i: Int = 0\n"
             "    while i < n:\n"
             "        memset(pat + i, PAT_DASH, 1)\n"
             "        i = i + 1\n"
             "    return 0\n"
             "\n"
             "def fill_a(pat, n):\n"
             "    var i: Int = 0\n"
             "    while i < n:\n"
             "        memset(pat + i, PAT_A, 1)\n"
             "        i = i + 1\n"
             "    return 0\n",
      "both": True,
      "main": "from byref_xmod import fill, fill_a\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var got = malloc(64)\n"
              "    var want = malloc(64)\n"
              "    memset(want, 45, 4)\n"
              "    fill(got, 4)\n"
              "    var same = memcmp(got, want, 4)\n"
              "    memset(got, 65, 2)\n"
              "    memset(want, 65, 2)\n"
              "    fill_a(got, 2)\n"
              "    var same2 = memcmp(got, want, 2)\n"
              "    return same * 10 + same2\n"}, 0, None),
    # A DELEGATING CONSTRUCTOR: a method that stores its own PARAMETER into one
    # of its fields, which is 13 of the 14 hand-written `recv.field = <a frame>`
    # sites in this repository and the stdlib (`tools/formal_frame_field_census.py`).
    # It used to be refused as "a S receiver is stored in the field 'self.src',
    # so it outlives the frame it names", and that was false about it: the frame
    # was reserved by the CALLER, in the caller's own scratch, so it cannot
    # outlive the slot it is stored in — both are the caller's. What the refusal
    # was right about is the OTHER lifetime, the one where the frame is built
    # HERE (`byref_refuse_a_field_store_of_a_frame_built_here`), and the one
    # where the slot is not a plain word (the placed nested frame, which
    # `constr_refuse_an_init_store_over_a_placed_nested_frame` pins).
    #
    # It reads through the field by PASSING it, and the callee is in the other
    # module, which is the only way this field can be read at all: a read
    # through a nested frame of this module's own struct is a different
    # construct with its own placement rules (`_nested_frame_levels`'s
    # `_REASSIGNED` arm). So the assertion is the whole point — `peek` computes
    # 7*10 + 8 = 78 from the frame it was handed, so a stored COPY, a
    # re-created block, or any word other than the caller's `S` address leaves
    # `n` alone and answers 1.  The multiplier is 2 rather than 10 so the
    # expected exit status fits in a byte, which every case in this suite
    # requires (see the retraction in BUG.md): CPython's answer is
    # (7*10 + 8) * 2 + 1 = 157.
    ("byref_delegating_constructor_stores_a_parameter_frame",
     {"mod": "struct S:\n"
             "    var a: Int\n"
             "    var b: Int\n"
             "\n"
             "def peek(s: S) -> Int:\n"
             "    return s.a * 10 + s.b\n",
      "main": "from byref_xmod import S, peek\n"
              "\n"
              "struct Holder:\n"
              "    var src: S\n"
              "    var n: Int\n"
              "\n"
              "    def fill(out self, r: S):\n"
              "        self.src = r\n"
              "        self.n = 1\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var r = S()\n"
              "    r.a = 7\n"
              "    r.b = 8\n"
              "    var h = Holder()\n"
              "    h.fill(r)\n"
              "    return peek(h.src) * 2 + h.n\n"}, 157, None),
    # The NEGATIVE half, and the one that makes the positive case above worth
    # anything: the same shape with the two modules declaring the same NUMBER of
    # fields in a different ORDER. `Q.v` is slot 0 and the caller's slot 0 is
    # `P.pad`, so following the address computes on the wrong storage and
    # returns 213 where CPython says 312 — measured on both architectures with
    # the name comparison removed. It is refused, and named as the layout
    # disagreement it is rather than as an unknowable.
    ("byref_refuse_cross_module_layout_disagreement",
     {"mod": "struct Q:\n"
             "    var v: Int\n"
             "    var pad: Int\n"
             "\n"
             "def take_it(q: Q) -> Int:\n"
             "    return q.v * 100 + q.pad\n",
      "main": "struct P:\n"
              "    var pad: Int\n"
              "    var v: Int\n"
              "\n"
              "from byref_xmod import take_it\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var p = P()\n"
              "    p.pad = 2\n"
              "    p.v = 3\n"
              "    return take_it(p) + n\n"},
     "refuse:own manifest says the parameter in that position is a frame "
     "holder of Q", None),
    # And the inverse: the callee was compiled with an ordinary word in that
    # slot, so a frame address arriving there is computed on. Refused, with the
    # same measured consequence the single-file version has — the frame's own
    # address, added to the other operand, different on every run.
    ("byref_refuse_cross_module_plain_parameter",
     {"mod": "def bump(x: Int, by: Int) -> Int:\n"
             "    return x + by\n",
      "main": "struct P:\n"
              "    var a: Int\n"
              "    var b: Int\n"
              "\n"
              "from byref_xmod import bump\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var p = P()\n"
              "    p.a = 7\n"
              "    p.b = 8\n"
              "    return bump(p, n)\n"},
     "refuse:is an ordinary word, NOT a frame holder", None),
    # The same hand-off reached through a STAR import, which is the shape where
    # "this module's own functions are the only ones in this image" is at its
    # least true: `from byref_xmod import *` binds whatever that module
    # EXPORTS. 22 files of the standard library write one. It used to be
    # refused for asking a question the pass could not answer — whether the
    # module exports the name at all, and whether its compilation made the
    # parameter a frame holder — and both are now read off the link line, so
    # this is a POSITIVE case with the same expected answer as the named import
    # above.
    # A `comptime` class attribute declared in an IMPORTED module, read through
    # a receiver here. The in-file half of this is
    # `comptime_attribute_receiver_reads_match_cpython`; the two halves were
    # separate because `formal/imports.py` attached no field census to an
    # imported module's structs, so `_split_declaration` returned None, every
    # class-level name stayed a field, and the read was reported as a field the
    # struct does not have. The census is what decides a struct's WIDTH, which
    # is why attaching it to imported modules was worth measuring rather than
    # assuming: 0 of 316 structs across the 252-file new-modular stdlib change
    # width or receiver classification, because `parse_module` already attached
    # the census for every file it parses and this only extends it to the ones
    # reached through an import.
    #
    # 1 is `IS_FLAT = True`, which CPython also prints.
    ("byref_cross_module_comptime_attribute_through_a_receiver",
     {"mod": "struct C:\n"
             "    comptime IS_FLAT = True\n"
             "    comptime RANK = 3\n"
             "    var storage: Int\n"
             "\n"
             "    fn width(self) -> Int:\n"
             "        return self.RANK\n",
      "main": "from byref_xmod import C\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var c = C()\n"
              "    printf(\"flat=%d rank=%d\\n\", c.IS_FLAT, c.RANK)\n"
              "    return 0\n"}, 0, "flat=1 rank=3"),
    # The RECEIVER spelling of the same read, through a frame holder rather than
    # a local: the read is a field of `c` here too, and this is the shape the
    # original filing named (`shape.is_flat`, `res._InjectedValues`). It is a
    # separate case because a parameter's holder status comes from the holder
    # fixpoint in THIS image while the constant's classification comes from the
    # census of the OTHER one, so the two halves of the answer are established
    # by different passes over different files.
    ("byref_cross_module_comptime_attribute_through_a_parameter",
     {"mod": "struct C:\n"
             "    comptime LIMIT = 10\n"
             "    var storage: Int\n"
             "\n"
             "    fn limit_of(self) -> Int:\n"
             "        return self.LIMIT\n"
             "\n"
             "def limit_of(c: C) -> Int:\n"
             "    return c.LIMIT\n",
      "main": "from byref_xmod import C, limit_of\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var c = C()\n"
              "    printf(\"limit=%d@@\", limit_of(c))\n"
              "    return 0\n"}, 0, "limit=10@"),
    ("byref_cross_module_star_imported_free_function",
     {"mod": "struct P:\n"
             "    var a: Int\n"
             "    var b: Int\n"
             "\n"
             "def take_it(p: P) -> Int:\n"
             "    return p.a * 10 + p.b\n",
      "main": "from byref_xmod import *\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var p = P()\n"
              "    p.a = 3\n"
              "    p.b = 4\n"
              "    return take_it(p) + n\n"}, 44, None),
    # …and the star-import arm's remaining half: a name NO library on the link
    # line publishes. The export table is now consulted, so this is a real
    # "nothing binds it" rather than the old "a library this pass has not
    # built" — which was true of every one of the 22 star-importing stdlib
    # files and of none of the programs.
    ("byref_refuse_star_imported_unpublished_name",
     {"mod": "def helper(x: Int) -> Int:\n"
             "    return x + 1\n",
      "main": "from byref_xmod import *\n"
              "\n"
              "struct P:\n"
              "    var a: Int\n"
              "    var b: Int\n"
              "\n"
              "def main(n: Int) -> Int:\n"
              "    var p = P()\n"
              "    p.a = 3\n"
              "    p.b = 4\n"
              "    return mystery(p) + n\n"},
     "refuse:no manifest on this image's link line mentions it", None),
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
    #
    # **The needle MOVED on 2026-10-03, and the case stayed, because the shape
    # moved rather than the fact.** `mk()` is a CALL RESULT, and a call result
    # as a receiver is now refused at the construct by `_receiver_shape_refusal`
    # — `formal/model.py`'s `subscript_receiver_method_refusal` — which is the
    # same message `bs[0].get()` has had since 2026-10-01 and says the same
    # thing about the same missing fact. The sentence this case used to pin
    # quoted the receiver as `….take`, because `member_chain_text` prints a call
    # result as `…`, and its own tail then said what closes it: "the method's
    # declaration reaching the analysis: a receiver whose type names the struct,
    # so the call can be rewritten and the parameter list read". So the two
    # sentences agree about the fix, and the one that leads with it wins.
    #
    # Measured, because a refusal whose advice does not work is a second defect
    # wearing the first one's clothes: binding the receiver is enough, and the
    # FRAME ARGUMENT that the old sentence was about is then fine —
    # `var b = mk(); return b.take(r)` builds on arm64 (the lift gives the
    # callee a name and its parameter list, so `r` is followed into it).
    #
    # …and the advice stopped being necessary on 2026-10-04, which is why this
    # row is GONE from this table rather than moved: `mk()`'s own `-> Box` is
    # the receiver's type, written down in the source, so
    # `formal/build.py::_call_receiver_target` lifts the call itself
    # (`Box_take(mk(), r)`) and there is nothing left to bind a local for. The
    # row that replaced it is `call_result_receiver_lifted_from_a_return_type`
    # in `CALL_RECEIVER_CASES` below, which runs the program rather than
    # refusing it — a refusal that has become a build is worth a number here,
    # not a deleted test.
    # …and the branch the case above used to cover is still reachable, on the
    # shape where the construct-level refusal CANNOT answer: an AMBIGUOUS method
    # name. `take` is declared by two structs here, so `owners` has no entry for
    # it and `subscript_receiver_method_refusal` — which needs the name to
    # resolve to exactly one struct — declines, exactly as its own docstring says
    # it must. What is left is the analysis's own sentence about an opaque
    # position, and it is the right one here because the missing fact is DEEPER:
    # even with the receiver named, `take` would still be two functions.
    #
    # So the two cases are the two halves of one question — "whose `take`?" — and
    # dropping either would leave the other unmeasured. Both refuse on both
    # architectures, from the shared build pass, before either emitter.
    ("byref_refuse_an_opaque_position_when_the_method_name_is_ambiguous",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "struct A:\n"
     "    var p: Int\n"
     "    var q: Int\n"
     "\n"
     "    fn take(self, o: Int) -> Int:\n"
     "        return self.p + o\n"
     "\n"
     "struct B:\n"
     "    var p: Int\n"
     "    var q: Int\n"
     "\n"
     "    fn take(self, o: Int) -> Int:\n"
     "        return self.q + o\n"
     "\n"
     "def mk() -> A:\n"
     "    var a = A()\n"
     "    a.p = 1\n"
     "    a.q = 2\n"
     "    return a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
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

    # `both` in the file map builds and RUNS this case on BOTH architectures and
    # requires the same answer from each, which the host-only build below cannot
    # see. It is opt-in per case rather than the default because the other
    # cases in this group were written for the host's architecture and doubling
    # their builds would change eleven rows that have nothing to do with the
    # boundary; the rows that are ABOUT the boundary's value handoff already
    # say so in their own comments.
    arches = ("arm64", "x86_64") if files.get("both") else (None,)
    for arch in arches:
        out = os.path.join(tmpdir, name if arch is None else f"{name}.{arch}")
        rc, text = build_formal(src, out, backend=arch)
        if rc != 0:
            who = arch or "the host backend"
            return False, (f"[{who}] build failed: {text.strip()[-300:]}")
        if not os.path.isfile(out):
            return False, (f"[{arch or 'host'}] build reported success and "
                           f"wrote no binary")
        argv = ["arch", "-x86_64", out] if arch == "x86_64" else [out]
        run = subprocess.run(argv, capture_output=True, text=True,
                             timeout=RUN_TIMEOUT)
        who = arch or "the host backend"
        if run.returncode != want_exit:
            return False, (f"[{who}] exit status {run.returncode}, expected "
                           f"{want_exit}"
                           + (f"; stderr: {run.stderr.strip()[:120]}"
                              if run.stderr.strip() else ""))
        if want_stdout is not None and want_stdout not in run.stdout:
            return False, (f"[{who}] stdout {run.stdout[:120]!r} does not "
                           f"contain {want_stdout!r}")
        if verbose:
            print(f"      [{who}] stdout={run.stdout[:60]!r} "
                  f"exit={run.returncode}")
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
    # ── THREE LEVELS: the innermost frame of a chain two frames deep ──
    #
    # Depth 2 is the shape above and it has been there since C5.  Depth 3 is
    # `o.inner.inner2.x`, and it was refused on BOTH architectures with a
    # diagnostic about the WRONG LEVEL: the build pass spelled the outer field as
    # `chain.split(".")[-2]`, which for `o.inner.inner2.x` is `inner2` — a
    # spelling the source does not use and a slot whose layout was never
    # consulted.  It is now a WALK (`formal/build.py`'s `_nested_frame_levels`),
    # so each level asks the placement question in the order the source asks it.
    #
    # Nothing in either emitter changed, and that is the shape of the answer: both
    # resolve a `_frame_nested_slots` key by loading the chain with its last field
    # removed and indexing the frame that leaves, so filling every PREFIX of the
    # chain is the whole of the third level.  Two objects with different values
    # at the innermost level, because "the innermost frame is shared" is the wrong
    # answer a single object cannot see.
    ("byref_three_level_nested_frames_read_and_write",
     "struct Inner2:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "struct Inner:\n"
     "    var inner2: Inner2\n"
     "    var z: Int\n"
     "\n"
     "struct Outer:\n"
     "    var inner: Inner\n"
     "    var w: Int\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    o.inner.inner2.x = 5\n"
     "    o.inner.inner2.y = 6\n"
     "    o.inner.z = 7\n"
     "    o.w = 8\n"
     "    printf(\"x=%d y=%d z=%d w=%d\", o.inner.inner2.x, o.inner.inner2.y,"
     " o.inner.z, o.w)\n"
     "    return 0\n", 0, "x=5 y=6 z=7 w=8"),
    ("byref_three_level_nested_frames_two_objects_no_alias",
     "struct Inner2:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "struct Inner:\n"
     "    var inner2: Inner2\n"
     "    var z: Int\n"
     "\n"
     "struct Outer:\n"
     "    var inner: Inner\n"
     "    var w: Int\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Outer()\n"
     "    var b = Outer()\n"
     "    a.inner.inner2.x = 1\n"
     "    a.inner.inner2.y = 2\n"
     "    a.inner.z = 3\n"
     "    a.w = 4\n"
     "    b.inner.inner2.x = 11\n"
     "    b.inner.inner2.y = 12\n"
     "    b.inner.z = 13\n"
     "    b.w = 14\n"
     "    printf(\"a=%d,%d,%d,%d \", a.inner.inner2.x, a.inner.inner2.y,"
     " a.inner.z, a.w)\n"
     "    printf(\"b=%d,%d,%d,%d\", b.inner.inner2.x, b.inner.inner2.y,"
     " b.inner.z, b.w)\n"
     "    return 0\n", 0, "a=1,2,3,4 b=11,12,13,14"),
    # A ONE-FIELD struct at the third level, which is the one case where the
    # chain is NOT a frame access: a struct of one field has no block, so the
    # word in `o.inner.inner2` IS `Inner2`'s only field and
    # `o.inner.inner2.x` is the same word under a longer spelling.  The
    # REWRITE (`_rewrite_one_word_nested_fields`) collapses it onto
    # `o.inner.inner2`, and every level it walks needs a table entry for the
    # collapsed spelling to have an address — which is why the fill is shared
    # with the frame case rather than duplicated for it.
    ("byref_three_level_chain_through_a_one_field_struct",
     "struct Inner2:\n"
     "    var x: Int\n"
     "\n"
     "struct Inner:\n"
     "    var inner2: Inner2\n"
     "    var z: Int\n"
     "\n"
     "struct Outer:\n"
     "    var inner: Inner\n"
     "    var w: Int\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    o.w = 7\n"
     "    o.inner.inner2.x = 8\n"
     "    printf(\"x=%d z=%d w=%d\", o.inner.inner2.x, o.inner.z, o.w)\n"
     "    return 0\n", 0, "x=8 z=0 w=7"),
    # …and the same with the type coming from the nested struct's `__init__`
    # rather than from the class-body annotation, which is a DIFFERENT evidence
    # source (`struct_field_type`'s "assigned" row rather than its "declared"
    # one) and therefore its own case.  `o.inner = Inner(Inner2(5), 6)` puts a
    # whole `Inner` block in the slot, and the depth-3 chain below has to reach
    # through it.
    ("byref_three_level_chain_with_the_type_assigned_in_init",
     "struct Inner2:\n"
     "    var x: Int\n"
     "\n"
     "struct Inner:\n"
     "    var inner2: Inner2\n"
     "    var z: Int\n"
     "    def __init__(self, i: Inner2, b: Int):\n"
     "        self.inner2 = i\n"
     "        self.z = b\n"
     "\n"
     "struct Outer:\n"
     "    var inner: Inner\n"
     "    var w: Int\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    o.inner = Inner(Inner2(5), 6)\n"
     "    o.w = 7\n"
     "    o.inner.inner2.x = 8\n"
     "    printf(\"x=%d z=%d w=%d\", o.inner.inner2.x, o.inner.z, o.w)\n"
     "    return 0\n", 0, "x=8 z=6 w=7"),
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

    # ── THE ONE CLAUSE OF THE AMBIGUOUS-NAME LIFT THAT IS NOT OPTIONAL ───────
    #
    # `BOTH_ARCH_CASES`'s `both_arch_ambiguous_method_name_settled_by_the_receiver`
    # lifts `o.get()` because `o`'s agreed binding names a struct of this unit
    # that DECLARES `get`. That condition is right, and it has exactly one
    # exception: a struct that DERIVES from the binding's struct and declares
    # the same member too. `b` is bound to `Base`, and `Base_emit` is compiled
    # against `Base`'s two-field layout, so a value of `Derived` read through it
    # is the BASE's view of a child — which builds, runs, and prints digits no
    # source wrote. Python dispatches on the value; this path can only see the
    # DECLARATION, which names the base.
    #
    # So this row is a REFUSAL and not a demonstration, and the reason is worth
    # stating rather than leaving to be found: this path cannot construct the
    # `Derived` value that would make the lift visibly wrong, so there is no
    # program whose ANSWER the lift gets wrong for a case to compare against
    # CPython. What the row pins is the refusal, which is the only end state
    # reachable from here that is not a lie — and `BOTH_ARCH_CASES` is the wrong
    # list for it for the same reason, since that runner requires a build.
    #
    # MEASURED, so this is not a row asserting a guard that is not there: with
    # `formal/build.py`'s `_derived_overrides` clause deleted from the bare-
    # receiver arm of `_lift_one_word_field_method`, this program BUILDS on
    # arm64 and prints 5 — `Base_emit` called on a `Base`, which happens to be
    # right for the only receiver this path can build here and would be wrong
    # for every receiver it cannot. `Base` is TWO fields, so `one_word` does not
    # carry it and the lift this row is about is the one that reads the
    # constructor binding instead.
    #
    # The same guard on the FIELD-receiver arm is pinned by
    # `test_formal_specialized_method_call.py`'s
    # `refuse_a_field_receiver_whose_declared_type_has_a_derived_override`: two
    # arms of one rule, so two rows.
    ("ambiguous_name_a_derived_struct_also_declares_is_still_refused",
     "struct Base:\n"
     "    var start: Int\n"
     "    var pad: Int\n"
     "\n"
     "    def emit(self) -> Int:\n"
     "        return self.start\n"
     "\n"
     "struct Derived(Base):\n"
     "    var extra: Int\n"
     "\n"
     "    def emit(self) -> Int:\n"
     "        return 1000\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Base()\n"
     "    b.start = 5\n"
     "    b.pad = 1\n"
     "    printf(\"%d\\n\", b.emit())\n"
     "    return 0\n",
     "refuse:b.emit() is a method call on a value", None),

    # ── THE TWO ACCESSORS `.value` DOES NOT ANSWER THROUGH A PARAMETER ───────
    #
    # `BOTH_ARCH_CASES`' `both_arch_enum_typed_parameter_value_is_the_word_it_
    # holds` is the half of this that works. These two are the half that does not,
    # and they are two refusals because the two facts are two — a single sentence
    # would have to be false about one of them, and a refusal that is false about
    # the construct is worse than none because it sends a reader to change a
    # correct program.
    #
    # `.name` is a member's SPELLING: the constant's own name in the class body,
    # which the word travelling in the parameter does not carry. The
    # class-constant spelling `Reg.RBP.name` answers, so this is not "the enum
    # machinery is absent" — it is that a parameter has lost which member it is.
    # (CPython's asymmetry is the same one: `Reg.<computed>.value` fails and
    # `Reg.<computed>.name` still answers.)
    ("refuse_an_enum_members_name_through_a_parameter",
     "from enum import Enum\n"
     "\n"
     "class Reg(Enum):\n"
     "    RAX = 0\n"
     "    RBP = 5\n"
     "\n"
     "def name_of(base: Reg) -> String:\n"
     "    return base.name\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    printf(\"%s\\n\", name_of(Reg.RBP))\n"
     "    return 0\n",
     "refuse:base.name` is a member's SPELLING", None),

    # `.value` where the enum has a member this path cannot materialize. The gate
    # is EVERY member and not this read's member, and the reason is that a
    # parameter's value is a word that arrived from a call site: nothing in it
    # says which member it is, so one computed member makes the identity
    # `base.value is base` false for all of them and answering it for the others
    # would be a wrong number rather than a refusal.
    #
    # The call site passes `0` and CPython would raise `TypeError` there — an enum
    # member is not an int. That is deliberate and is what makes this a LIMIT row
    # rather than a differential: the reachable programs on this side of the gate
    # are the ones with no reference answer, so what is pinned is that the build
    # says so INSTEAD of answering. Naming `Reg.NEXT` in the needle is the other
    # half — a message that said only "some member is computed" would send a
    # reader looking through the class body for which one.
    ("refuse_an_enum_value_when_any_member_is_computed",
     "from enum import Enum\n"
     "\n"
     "class Reg(Enum):\n"
     "    RAX = 0\n"
     "    NEXT = RAX + 1\n"
     "\n"
     "def pick(base: Reg) -> Int:\n"
     "    return base.value\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    printf(\"%d\\n\", pick(0))\n"
     "    return 0\n",
     "refuse:`Reg.NEXT` is written as a COMPUTATION", None),

    # THE DIRECTION THAT MATTERS MOST, because it is the one that would refuse
    # real programs: the census is gated on `model.struct_is_enum`, so a
    # parameter whose declared type is an ORDINARY struct still reads `.value`
    # as a field — through the generic `field_access_refusal`, whose wording
    # ("this path has no way to say what 'base' holds") is still TRUE here,
    # because a two-field struct's receiver is a frame address and nothing in
    # `base`'s declaration as used by THIS read settles which. `P` declares a
    # METHOD named `value`, so the program is also one whose answer is a number:
    # a census that stopped at the annotation and dropped the enum gate would
    # rewrite `base.value` to `base` and print a frame address.
    ("refuse_a_non_enum_parameters_value_is_still_a_field_read",
     "struct P:\n"
     "    var v: Int\n"
     "\n"
     "    def value(self) -> Int:\n"
     "        return self.v\n"
     "\n"
     "def pick(base: P) -> Int:\n"
     "    return base.value\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    printf(\"%d\\n\", pick(P()))\n"
     "    return 0\n",
     "refuse:'base.value' is a field access through 'base'", None),
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
    # `in1` is a nested frame of this module and `Outer` declares nothing about
    # it.  123 + 5 = 128, and a build that computed 0 or 5 would be the
    # silently-wrong outcome — a load from a slot nothing was ever written to.
    #
    # `in1` is DECLARED (`var in1: Inner`) and `__init__` stores a word.  It used
    # to be the other way round — `fn __init__(self): self.in1 = Inner()` with no
    # declaration — which made `Outer()` a zero-argument construction of a struct
    # whose `__init__` takes no required parameter, so the body RUNS.  It used
    # to refuse the nested frame construction in it by name
    # (`model.init_body_stores`: the nested block is reserved per construction
    # SITE, and a body inlined into a construction has no such site); the store
    # is now dropped instead, because the field's placement already made it.
    # The guard for the spelling this replaced is
    # `assigned_type_nested_frame_constructed_in_init`, which is now a POSITIVE
    # case rather than a refusal.
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
     "    var in1: Inner\n"
     "\n"
     "    fn __init__(self):\n"
     "        self.tag = 0\n"
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
    # `interpreter.scope.define()`: the base is a parameterless construction in
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
     "    var scope: Scope\n"
     "\n"
     "    fn __init__(self):\n"
     "        self.filename = 0\n"
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
     "    var in1: Inner\n"
     "\n"
     "    fn __init__(self):\n"
     "        self.tag = 0\n"
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
    # THE TUPLE TARGET, and the reason this group has a second list
    # (`BOTH_ARCH_CASES`) at all.  `self.p, self.q, self.r = 3, 4, 7` in an
    # `__init__` is ordinary Python that this repository writes —
    # `tools/procrun.py` opens with `self.limit, self._chunks, self._size =
    # limit, [], 0` — and it used to be refused on x86-64 by name and
    # ACCEPTED-AND-DROPPED on arm64, where it built, ran, and computed 0.
    #
    # 14 is CPython's answer for this text, and every field is READ, so an
    # inline that transposed the pairing (`q` ← 4 and `p` ← 3) or read
    # one slot off by one fails rather than agreeing by luck.
    #
    # MEASURED, and the reason the three `BOTH_ARCH_CASES` rows exist rather
    # than this one being enough: reversing the value pairing in
    # `_init_statement_field_stores` leaves THIS ROW GREEN, because `3 + 4 + 7`
    # is 14 whichever way round it is. It is a positive case built for the host
    # architecture only, and its whole subject — a construct the two backends
    # once disagreed about — is not what it checks. The `BOTH_ARCH_CASES` rows
    # use positional arithmetic and fail on the same sabotage.
    #
    # It is in `BOTH_ARCH_CASES` as well for the other half: a case whose
    # subject is a two-architecture DISAGREEMENT cannot be checked by running
    # one of the two.
    ("tuple_store_to_fields_in_init",
     "class Tail:\n"
     "    def __init__(self):\n"
     "        self.p, self.q, self.r = 3, 4, 7\n"
     "\n"
     "    def total(self):\n"
     "        return self.p + self.q + self.r\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var t = Tail()\n"
     "    return t.total()\n", 14, None),
]

# Positive cases built and RUN on BOTH backends, which is what
# `run_case` above deliberately does not do: it builds the host's architecture
# for an answered case because that is what "does the binary compute the right
# answer" means for the other 400 rows, and a case whose SUBJECT is a
# two-architecture disagreement needs the other half of the assertion.
#
# It exists because that class of defect is invisible to every other shape in
# this file.  A `refuse:` row builds both — and so passes when one architecture
# refuses and the other BUILDS-and-lies is not caught by it either, since the
# refusal half fails; and a positive row runs one, so x86-64 refusing what arm64
# lowers is a green run.  That combination is exactly what
# `“FORMAL_x86_64_tuple_assignment_member_target: arm64 lowers `self.a”` measured: arm64 lowered
# a member tuple target, x86-64 refused it by name, and nothing in the suite
# noticed for the whole life of the divergence.
BOTH_ARCH_CASES = [
    # …and the eq-dispatch case that is in this group for the reason the group's
    # docstring gives, read for this construct: the two backends' HOLDER
    # analysis is one shared table (`formal/build.py`'s `_frame_receivers`), so
    # the dispatch decision is shared, and a construct where they once disagreed
    # is checked on both rather than on the host's.  What is being pinned is
    # that `mk(1) == mk(2)` REACHES the method at all: `__eq__` returns True for
    # everything, so the two answers are 1 (the method ran) and 0 (the operator
    # stayed a compare of two ADDRESSES, which is CPython's INHERITED identity
    # `__eq__` and answers "are these the same object" — and two calls are two
    # objects).  Nothing refused the wrong answer: it was a silent 0 on both
    # machines, which is
    # `bugs/FORMAL_eq_dispatch_two_call_operands_are_not_a_frame_address.md`.
    #
    # The function that dispatches it binds NOTHING, which is the whole shape:
    # the rewrite used to skip any function with no frame-valued name in it, and
    # after the call-operand work a frame operand can be a CALL whose declared
    # return type settles it, with no name involved at all.
    #
    # `__eq__` reads neither operand on purpose.  A field-wise `__eq__` over two
    # call operands is a different case, and it was NOT here because x86-64 used
    # to read both operands' blocks as one (two names bound to returned frames
    # aliased the last block), which would have pinned a known-wrong answer as
    # the expectation.  That defect is FIXED -- the x86-64 call site dropped the
    # returned-frame convention's hidden trailing word -- and the field-wise row
    # is now `a_returned_frame_compared_with_a_returned_frame_call` in
    # `test_formal_returned_frame.py`, on both backends, because it is the shape
    # that fails SILENTLY rather than loudly.
    ("both_arch_eq_dispatch_through_two_call_operands",
     "struct A:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "    def __eq__(self, other: A) -> Bool:\n"
     "        return True\n"
     "\n"
     "def mk(v: Int) -> A:\n"
     "    var a = A()\n"
     "    a.x = v\n"
     "    a.y = v\n"
     "    return a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    printf(\"eq=%d\", 1 if mk(1) == mk(2) else 0)\n"
     "    return 0\n", 0, "eq=1"),
    # …and the case that used to REFUSE a function read as a value, in the
    # group whose docstring says a construct the two backends once disagreed
    # about belongs here.  A function value is its entry ADDRESS
    # (`formal/model.py`'s `function_value_address_note` neighbourhood: each
    # backend's `_load_var`), so storing one in a local and calling it is one
    # `BLR` / `CALL r64` and answers the source's arithmetic.  It was
    # `a_function_name_read_as_a_value_is_named_as_one` in `REFUSAL_CASES`
    # until the lowering landed; the half that is still refused — the same name
    # passed where the callee DECLARES an `Int` — stayed in that table beside
    # it, and the pair is the reason: a word that is an address is not an
    # arithmetic operand, and the build says so where it can see the
    # declaration.
    #
    # `test_formal_specialization.py` carries the same construct WITH the
    # CPython comparison this table cannot make, plus the specialization through
    # a value that `std/algorithm/backend/tile.mojo` is written with.
    ("both_arch_a_function_value_in_a_local_is_called",
     "def dbl(x: Int) -> Int:\n"
     "    return x * 2\n\n"
     "def main(n: Int) -> Int:\n"
     "    var g = dbl\n"
     "    return g(5)\n", 10, ""),
    # A positive case whose expected answer is under 256, because the formal
    # entry point's return value becomes the process exit status and a status is
    # eight bits wide: 347 & 255 == 91, and a constant written as 347 would be a
    # case that can never pass.  3, 4 and 7 rather than 1, 2 and 3 so that a
    # transposed pairing (43) and a slot read one off (74, 370) are all
    # different from the right answer and from each other.
    ("both_arch_tuple_store_to_fields_in_init",
     "class Tail:\n"
     "    def __init__(self):\n"
     "        self.p, self.q, self.r = 3, 4, 7\n"
     "\n"
     "    def total(self):\n"
     "        return self.p * 100 + self.q * 10 + self.r\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var t = Tail()\n"
     "    return t.total()\n", 91, None),
    # A RECEIVER SPELLED `this`, because the receiver set is `struct_receivers`
    # and not the literal `self`: a table that hard-coded the one spelling would
    # make this row pass on the strength of the spelling the other rows use and
    # refuse nothing.  4 * 100 + 9 = 409, and 409 & 255 == 153.
    ("both_arch_tuple_store_through_a_renamed_receiver",
     "class Pair:\n"
     "    def __init__(this):\n"
     "        this.a, this.b = 4, 9\n"
     "\n"
     "    def total(this):\n"
     "        return this.a * 100 + this.b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = Pair()\n"
     "    return p.total()\n", 153, None),
    # The value the tuple form carries that the separate-assignment form cannot:
    # a field assigned a CONSTRUCTOR ARGUMENT.  `__init__(self, n, m)` with
    # `self.p, self.q = n, m` is what `init_body_stores` substitutes the
    # CALLER's own expression for, and it is the half that makes the tuple form
    # a per-field store rather than a store of three constants — a reader
    # checking the row above cannot tell whether the pairing is positional or
    # whether the three slots happen to hold the three constants in order.
    #
    # The values are BARE parameters, not `n * 2`, and that is the shape the
    # inline accepts: `constr_refuse_an_init_body_that_reads_a_parameter_in_an_
    # expression` is the row that says why a name inside an expression is a
    # refusal (the arithmetic names a word the CALLING function does not have),
    # and a tuple element is under exactly the same rule as a plain one.
    # 3 * 100 + 7 = 307, and 307 & 255 == 51.
    ("both_arch_tuple_store_binds_constructor_arguments",
     "class Scale:\n"
     "    def __init__(self, n: Int, m: Int):\n"
     "        self.p, self.q = n, m\n"
     "\n"
     "    def total(self):\n"
     "        return self.p * 100 + self.q\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var s = Scale(3, 7)\n"
     "    return s.total()\n", 51, None),
    # ── THE SCALAR STORE IN A ZERO-ARGUMENT `__init__` OF A ONE-FIELD STRUCT ──
    #
    # The three rows above store through a TUPLE target or with a constructor
    # that HAS a parameter, and all three worked; this row is the shape that did
    # not, and it is here rather than in `CASES` because both backends answered
    # it with the SAME wrong number (0), which is the failure no parity suite,
    # no `refuse:` row and no engine diff can see.
    #
    # WHY 0, and why only for one field: a struct's field is lowered three ways
    # and which applies is decided by the BINDING of the base, not by a type
    # (“FORMAL_method_param_field_access: a method parameter's field”). A ONE-FIELD struct's receiver
    # IS its field — there is no storage of its own to point at — so for
    # `One20()` the one-word path evaluated the construction's value. Both
    # backends asked `model.struct_construction_plan` only when the call carried
    # an ARGUMENT (`if e.args or e.kwargs:`), so a construction with no argument
    # never asked and answered a fresh zero word without asking anyone: the
    # constructor body was DROPPED at the site. Nothing was refused, the exit
    # status was a plausible small integer, and the two machines agreed.
    #
    # The three classes are in ONE program so no single-row special case can
    # pass it, and their answers are deliberately different from each other and
    # from 0:
    #   One20   ONE field, `__init__(self)` with no parameter   -> 20 (was 0)
    #   Two203  TWO fields, the same zero-arg `__init__`         -> 20*10+3 = 203
    #   Arg20   one field, `__init__(self, k: Int)`              -> 20
    # `Two203` is the row that was already right and had to stay right — a fix
    # that de-inlined the constructor to make `One20` work would trade a wrong
    # answer for a wall of refusals — and `Arg20` is the other already-right
    # neighbour. `direct` reads the field from `main` without a method at all,
    # because the SAME construction feeds both halves and the method call is not
    # what loses the store.
    #
    # MEASURED: reverting the fix (both emitters, `model.one_word_construction`)
    # prints `c=0 d=203 e=20 direct=0` on arm64 AND on x86-64; with it,
    # `c=20 d=203 e=20 direct=20` on both. The method names differ per class
    # because dispatch on this path is by BARE method name, and three classes
    # declaring `total` make `d.total()` a call on a value (refused by name).
    ("both_arch_zero_arg_init_stores_a_one_field_scalar",
     "class One20:\n"
     "    def __init__(self):\n"
     "        self.n = 20\n"
     "    def one_total(self):\n"
     "        return self.n\n"
     "\n"
     "class Two203:\n"
     "    def __init__(self):\n"
     "        self.n = 20\n"
     "        self.m = 3\n"
     "    def two_total(self):\n"
     "        return self.n * 10 + self.m\n"
     "\n"
     "class Arg20:\n"
     "    def __init__(self, k: Int):\n"
     "        self.n = k\n"
     "    def arg_total(self):\n"
     "        return self.n\n"
     "\n"
     "def main() -> int:\n"
     "    var c = One20()\n"
     "    var d = Two203()\n"
     "    var e = Arg20(20)\n"
     "    var x = c.one_total()\n"
     "    var y = d.two_total()\n"
     "    var z = e.arg_total()\n"
     "    var w = c.n\n"
     "    printf(\"c=%d d=%d e=%d direct=%d\", x, y, z, w)\n"
     "    return 0\n", 0, "c=20 d=203 e=20 direct=20"),
    # ── A METHOD CALL THROUGH A ONE-WORD STRUCT'S OWN FIELD ───────────────────
    #
    # `o.inner.get()` where `Outer` declares ONE field and `Inner` is a framed
    # two-field struct. The identity this path relies on everywhere is that a
    # one-word struct's field and its receiver are the SAME storage, so
    # `_rewrite_self_fields` turns `o.inner` into `o`. That is right for a READ
    # and it is unbounded recursion for a CALL RECEIVER: the rewrite keeps the
    # method NAME and throws away the struct that name was looked up in, so
    # `Inner.get(o)` became `Outer.get(o)` — a call to a different function that
    # calls itself.
    #
    # Nothing caught it except a check that reads the tree AFTER the rewrite and
    # so reports an expression the source never spells ("`self.write_to` is not
    # a field of StridedSlice … so in Python this expression is the bound
    # method"), and a check that reads it BEFORE. Both had to be right about a
    # shape neither could see, and the one that reads before is what fixes it:
    # `_rewrite_one_word_field_method_calls` lifts `recv.f.m(x)` to `F_m(recv.f,
    # x)` while `f`'s DECLARED type can still be read, and only when the field's
    # struct actually DECLARES `m`. The lift must come BEFORE the collapse, and
    # the argument it passes (`o.inner`) is the collapse's own output (`o`) —
    # which is correct, because at that point `o`'s word IS the `Inner` frame
    # address: `o.inner = Inner()` has itself collapsed to `o = Inner()`.
    #
    # So this row is two rewrites in an order, and each alone is wrong in a
    # different direction: the lift without the collapse is an unresolved
    # symbol, and the collapse without the lift is infinite recursion. 42 is
    # `20 + 22`, so a collapse that recursed would exit on a signal instead of
    # answering, and a lift that named the wrong struct would answer something
    # else. MEASURED: with `_rewrite_one_word_field_method_calls` removed this
    # refuses on BOTH architectures ("o.get() is a method call on a value …").
    #
    # `o.inner = Inner()` before the field writes is not decoration: it is the
    # placement the program needs, and a row that omitted it is refused by
    # `field_access_refusal` for a different reason and would pass for the wrong
    # one.
    ("both_arch_one_word_struct_method_call_through_its_field",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.a + self.b\n"
     "\n"
     "struct Outer:\n"
     "    var inner: Inner\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    o.inner = Inner()\n"
     "    o.inner.a = 20\n"
     "    o.inner.b = 22\n"
     "    return o.inner.get()\n", 42, None),
    # ── AN AMBIGUOUS METHOD NAME, SETTLED BY THE RECEIVER'S OWN BINDING ──────
    #
    # `get` is declared by BOTH structs here, which is the ordinary situation in
    # a module of any size: dispatch on this path is by BARE NAME, and
    # `_method_owners` pops every ambiguous name precisely so
    # `_rewrite_method_calls` cannot pick one. The refusal that follows is
    # "`o.get()` is a method call on a value … 'get' is not one of those methods
    # of those receivers" — a diagnostic about a C library, for a call that is
    # plainly `Outer2.get`.
    #
    # TWO rewrites, and neither alone is enough, which is why this row is here
    # rather than a paragraph in a commit message:
    #
    #   * the receiver is a LOCAL. `var o = Outer2()` is the binding, and
    #     `_constructor_bindings` already computes it — as a LIST, because `x =
    #     A()` on one path and `x = B()` on another is one name with two
    #     layouts. So the lift reads that table and fires only when the
    #     candidates AGREE (`_bound_receiver_structs`).
    #   * the receiver is a FIELD of the holder, inside the holder's own
    #     method: `self.inner.get()` is a depth-2 chain, where the fact that
    #     settles it is the field's DECLARED type rather than the binding
    #     (`_owner_from_receiver_type`). `self`'s own binding settles the first
    #     hop and `self.inner`'s declared `Inner` settles the second.
    #
    # The order matters and it is the order the code is in: a lift that put the
    # name back to the OUTER struct would be unbounded recursion (this program's
    # `Outer2.get` calls `self.inner.get()`), and one that put it back to the
    # INNER struct for `o.get()` would compute on the wrong layout. 42 is
    # `20 + 22`, so neither of those answers 42.
    #
    # MEASURED: without both rewrites this refuses on arm64 and on x86-64
    # ("`o.get()` is a method call on a value …"), and with only the local one
    # it gets one line further and refuses on `self.inner.get()` instead — which
    # is why the row covers both halves rather than one.
    ("both_arch_ambiguous_method_name_settled_by_the_receiver",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.a + self.b\n"
     "\n"
     "struct Outer2:\n"
     "    var pad: Int\n"
     "    var inner: Inner\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.inner.get()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer2()\n"
     "    o.inner.a = 20\n"
     "    o.inner.b = 22\n"
     "    return o.get()\n", 42, None),

    # ── AN ENUM-TYPED PARAMETER, AND `.value` OFF IT ─────────────────────────
    #
    # `Reg.RBP.value` — a CLASS-level member read — lowers, and has since
    # `_enum_member_sites` / `_apply_constant_sites` (that fix is what stopped
    # `Reg.R15.value` answering `0` where CPython answers `15`). The PARAMETER
    # spelling did not, and the difference was one word in the site key: the
    # census was keyed on the literal path `Reg.RBP.value`, and a parameter's path
    # is `base.value`. Measured on both architectures before the rewrite:
    #
    #   build: 'base.value' is a field access through 'base', and this path has
    #   no way to say what 'base' holds …
    #
    # and the refusal was FALSE. Its own rule is that "a field is lowered three
    # ways and which one applies is decided by the BINDING of the base, not by a
    # type" — and `base` is bound by its DECLARATION, which says `Reg`. `base`
    # is not a frame and not a field: it holds an enum member, which on this path
    # is a plain 64-bit word, and **the word an enum member IS, on this path, IS
    # its value** — which is exactly why the class-constant rewrite substitutes
    # the literal for `Reg.RBP.value`. So `base.value` is `base`.
    #
    # In `BOTH_ARCH_CASES` rather than as a `refuse:` row because the rewrite is
    # in the shared build pass and the ANSWER is what has to agree: `formal/
    # x86_64.py` reads these values in its register-number arithmetic, so a
    # backend that got the word wrong would compute wrong machine code, print it,
    # and exit 0.
    #
    # 46 = `scaled(Reg.RSP, 3)`'s 36, `is_bp(Reg.RBP)`'s 10, `is_bp(Reg.RAX)`'s
    # 0 — under 256 because the exit status is a byte, and a weighted sum wide
    # enough to overflow it would compare against `expected & 0xFF` and invent a
    # mismatch (the lesson `bugs/FORMAL_arm64_instruction_coverage.md` §"Every
    # expected value must fit in a byte" records, having been learned there).
    # `is_bp` is a COMPARISON and `scaled` is arithmetic on purpose: the rewrite
    # has to put the bare name where an operand goes, and a row that only
    # returned `base.value` would pass on a substitution that happened to be
    # right for the wrong reason.
    ("both_arch_enum_typed_parameter_value_is_the_word_it_holds",
     "from enum import Enum\n"
     "\n"
     "class Reg(Enum):\n"
     "    RAX = 0\n"
     "    RBP = 5\n"
     "    RSP = 12\n"
     "\n"
     "def is_bp(base: Reg) -> Int:\n"
     "    if base.value == 5:\n"
     "        return 1\n"
     "    return 0\n"
     "\n"
     "def scaled(base: Reg, k: Int) -> Int:\n"
     "    return base.value * k\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return scaled(Reg.RSP, 3) + is_bp(Reg.RBP) * 10 + is_bp(Reg.RAX) * 100\n",
     46, None),
    # ── A ONE-FIELD STRUCT WHOSE SOLE FIELD IS A FRAME ────────────────────────
    #
    # `Box` declares ONE field, `inner`, whose declared type is the framed
    # `Opt`. So `Box`'s receiver IS its field's storage, and that storage is an
    # ADDRESS — `self.inner.v` is one load at `self + 8*slot(v)` for Opt's
    # layout, not two. The frame analysis had no case for a word that is both a
    # receiver and an address: `Box` is not framed, so nothing seeded `self` as
    # a holder, and the read half was refused by
    # `_check_method_receiver_types` with a message about `Box`'s layout that
    # the callee does not use.
    #
    # The seeding and the refusal below it are ONE change, and the row that
    # proves it is the next one: with only the seeding, a method that STORES
    # its sole field (`self.inner = o`, which the identity rewrites to
    # `self = o`) overwrites the frame address the CALLER still holds, so the
    # store never reaches the caller and every later `self.v` in the method
    # reads the caller's object — measured as SIGSEGV on both architectures.
    # `_collect_receiver_rebinds` withdraws its one-field exemption for exactly
    # these owners, and both halves read `model.one_word_sole_field_frame`, so
    # they cannot disagree about which receivers are addresses.
    #
    # 155 is `41 * 10 + 1`, and `two_field_holder_reads_its_nested_frame_through
    # _a_method` — the control, immediately below — computes the SAME number by
    # the other route, so a lowering that read the wrong slot, or read through
    # the holder's own layout instead of `Opt`'s, would have to be wrong in
    # exactly the way both agree on to pass. The two rows differ by one `var pad:
    # Int` and nothing else, which is the whole of the boundary: a two-field
    # struct has storage of its own, so its receiver is an address and the
    # analysis already had a case for it; a one-field struct has none.
    ("one_word_holder_of_a_frame_reads_through_its_method",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var inner: Opt\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.inner.v * 10 + self.inner.has\n"
     "\n"
     "def main() -> int:\n"
     "    var b = Box()\n"
     "    b.inner = Opt()\n"
     "    b.inner.v = 41\n"
     "    b.inner.has = 1\n"
"    return b.get()\n", 155, None),
    # THE CONTROL, and it is what makes the row above an assertion about a
    # boundary rather than about a program: `Box` here declares TWO fields, so
    # `Box`'s receiver is the ADDRESS of a frame of its own and `b.get()` was
    # always answerable. The bodies, the nested writes and the expected 155 are
    # identical, and the only variable is the `var pad: Int`. A change that had
    # answered the one-field case by making the analysis permissive about frame
    # receivers generally would move this row's number too, and a change that had
    # special-cased "one field" would leave it green and prove nothing about the
    # case it was written for.
    ("two_field_holder_reads_its_nested_frame_through_a_method",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var pad: Int\n"
     "    var inner: Opt\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.inner.v * 10 + self.inner.has\n"
     "\n"
     "def main() -> int:\n"
     "    var b = Box()\n"
     "    b.inner = Opt()\n"
     "    b.inner.v = 41\n"
     "    b.inner.has = 1\n"
     "    return b.get()\n", 155, None),
    # ── …AND THE ROW THAT DOES NOT WRITE THE FIELD FIRST ──────────────────────
    #
    # The two rows above are the SAME program with `b.inner = Opt()` in them, and
    # that line is doing more work than it looks: `Box()` builds a one-field
    # struct whose receiver IS its sole field's storage, and that storage is an
    # ADDRESS (`model.one_word_sole_field_frame`). So `Box()` has to bring the
    # `Opt` frame up, and it used not to: `model.struct_default_word` answered
    # `("none", None)` — "no class-level initializer, so a fresh word of zeros is
    # right" — which is true of every other field and false of this one, and the
    # constructor emitted `mov X0, #0` / `mov eax, 0`. Every field read through
    # it was then a load from address 0.
    #
    # **Measured on this tree before the fix, both architectures: SIGSEGV
    # (exit 139) from a green build, with nothing on either stream.** The rows
    # above cannot see it, which is why this is a separate row and not a variant
    # of them: they never read through the null word.
    #
    # 0 is CPython's answer and it is a real assertion, not a weak one: the frame
    # has to EXIST for the method's `self.inner.v` to read as 0, so a lowering
    # that left the word null and a lowering that brought the frame up and
    # initialized it to its defaults both have to agree on the reservation being
    # there, and only one of them survives the fault.
    #
    # **IT WAS A `refuse:` ROW, AND WAS WRONG WHILE IT WAS ONE** (2026-10-03,
    # `261543f8`; reversed the same day by `03e3b7b6`). The refusal's premise was
    # "`Box()` fills the WORD, not the frame that word will hold, so
    # `self.inner.v` is a load at address 0" — which stopped being true at
    # `4af77b16`, which gave that construction the frame it holds:
    # `model.struct_constructor_site_bytes` reserves the nested block alone
    # "because there is no object: the VALUE is the nested frame's address".
    # The refusal kept firing over a program whose word holds exactly that
    # frame's address, and the tree said so from two directions at once — the
    # rows above it (155, through the same frame), and
    # `sole_field_ctor_store_of_a_frame_built_here_is_another_rules` in this file,
    # which reads a FRESH `Opt` as zeros (`v=0 h=0`) and has done since.
    #
    # What answers it now is `model.struct_construction_yields_frame_address`:
    # a local bound from `Box()` IS a frame holder, so `self.inner.v` is one load
    # at `b + 8·0` and the number is 0 — the fresh frame's own default. Renamed
    # with it, because "read before it is written" was the refusal's premise and
    # the constructor writes it. The row above it — the same program WITH
    # `b.inner = Opt()` — still builds and answers 155, which is what keeps this
    # about the reserved-and-defaulted frame rather than about the construct.
    ("one_word_holder_reads_the_frame_its_constructor_brought_up",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var inner: Opt\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.inner.v * 10 + self.inner.has\n"
     "\n"
     "def main() -> int:\n"
     "    var b = Box()\n"
     "    return b.get()\n",
     0, None),
    # **TWO SITES IN ONE FUNCTION**, which is the half of the fix the row above
    # cannot reach: the frame is reserved in the PROLOGUE, one block per call
    # site, laid out in walk order by `model.struct_constructor_sites`, and the
    # second site's block has to start above the first one's. A reservation that
    # handed both sites the same offset would answer 9 twice where CPython says
    # 9 and then 3 — the first object's fields overwritten by the second
    # construction, which is a wrong answer on both machines and not a fault.
    #
    # So the numbers are the assertion: `bx` and `by` are separate
    # constructions, `bx.setboth(4, 5)` writes through the FIRST site's frame and
    # `by.setboth(1, 2)` through the second's, and `54 / 21` is what survives only
    # if the two blocks are disjoint — `get` is `v + has * 10`, so 4 + 50 and
    # 1 + 20. A reservation that handed both sites the same offset would print
    # `1 21`, the first object's fields overwritten by the second construction,
    # which is a wrong answer on both machines and not a fault. CPython prints
    # the same two numbers.
    #
    # …and it was a REFUSAL until `03e3b7b6`, for the reason the row above it
    # gives: `bx.setboth(4, 5)` is a method call, not `bx.inner = Opt()`, and the
    # refusal claimed the frame neither site names was never built. It is built —
    # by `Box()` itself, from `4af77b16` on — and `bx`/`by` are holders of it
    # because `model.struct_construction_yields_frame_address` says a local bound
    # from such a construction is one. So this row is a build again, and it is a
    # BETTER row for it: as a refusal it pinned two words of a message, and as a
    # build it pins the disjointness the row was written for, which nothing else
    # in the file reaches (two call sites of one constructor in one function).
    ("two_one_word_constructions_get_two_different_frames",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var inner: Opt\n"
     "\n"
     "    def setboth(out self, a: Int, b: Int):\n"
     "        self.inner.v = a\n"
     "        self.inner.has = b\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.inner.v + self.inner.has * 10\n"
     "\n"
     "def main() -> int:\n"
     "    var bx = Box()\n"
     "    bx.setboth(4, 5)\n"
     "    var by = Box()\n"
     "    by.setboth(1, 2)\n"
     "    printf(\"%d %d\", bx.get(), by.get())\n"
     "    return 0\n",
     0, "54 21"),
    # THE TRAP, which is the one assertion about augmented division that has no
    # CPython oracle: `DIV`/`IDIV` by zero is a HARDWARE fault (SIGFPE on this
    # target), and CPython raises ZeroDivisionError, so neither answer is a
    # stdout a reference could produce.  x86-64's `_emit_aug_assign` refused
    # `x //= 0` by name for the whole life of the construct — it had no route to
    # the divide at all — and arm64 routed all four of `/=` `//=` `%=` `**=` to
    # the same helper its binary form uses, whose zero arm exits 1.  So the
    # delegation that closed the two-architecture gap had to bring the trap with
    # it, and this row is the only place in the suite that can say whether it
    # did: a lowering that reached the instruction without the check would build,
    # and die on a signal (exit 136), which is a different number from the one
    # below and a worse kind of wrong answer than the refusal it replaced.
    # The four operators' VALUES are `test_formal_x86_64_parity.py`'s
    # `aug_division_and_power_on_a_name`, which has a CPython oracle for them.
    ("both_arch_augmented_division_by_zero_exits_one",
     "def main(n: Int) -> Int:\n"
     "    x = 7\n"
     "    x //= 0\n"
     "    return x\n", 1, None),
    # ── THE ARITY LADDER, which used to be REFUSALS in `REFUSAL_CASES` and is
    # here because it is the one construct the two backends put arguments in
    # DIFFERENT PLACES for ──────────────────────────────────────────────────────
    #
    # AAPCS passes arguments 0..7 in registers and the rest in the caller's
    # frame; SysV AMD64 passes 0..5 and the rest in the caller's frame.  Both
    # conventions are implemented now (`_MAX_INCOMING_ARGS` on both backends),
    # which means a SEVEN-argument call is a program that travels in a register
    # on one architecture and in memory on the other — and a defect in either
    # half of that convention is invisible on the machine that does not use the
    # frame.  A `run_case` row builds the HOST's architecture, so these rows
    # could not live there even once they were answerable.
    #
    # They were refusals until 2026-10-02 (arm64) and were refused on BOTH
    # backends for the nine-argument rows until the x86-64 stack area landed the
    # same day; the history and the measurement are in
    # `FORMAL_x86_64_argument_registers` (deleted — it asked for exactly
    # this) and `“`struct.pack` for a format naming 8 values was refused at the CALL SITE”`.
    #
    # `seven` is the row the whole subject is: `a6` is the FIRST stack argument
    # on x86-64 and the LAST register argument on arm64, and the answer is built
    # from it twice over (`a6 * 1000000 + a0`) so a slot holding the right
    # CONSTANT but the wrong argument still fails.
    ("both_arch_seven_arguments_arrive",
     "def seven(a0: int, a1: int, a2: int, a3: int,\n"
     "          a4: int, a5: int, a6: int) -> int:\n"
     "    return a6 * 1000000 + a0\n\n"
     "def main() -> int:\n"
     "    printf(\"seven=%d\", seven(1, 2, 3, 4, 5, 6, 7))\n"
     "    return 0\n", 0, "seven=7000001"),
    # The ninth argument, which is arm64's first stack slot and x86-64's third.
    # Nine rather than seven so a fix that implemented only the first stack
    # argument of each convention is caught by the count as well as the value.
    ("both_arch_nine_arguments_arrive",
     "def nine(a0: int, a1: int, a2: int, a3: int, a4: int,\n"
     "          a5: int, a6: int, a7: int, a8: int) -> int:\n"
     "    return a8 * 10000 + a0\n\n"
     "def main() -> int:\n"
     "    printf(\"nine=%d\", nine(1, 2, 3, 4, 5, 6, 7, 8, 9))\n"
     "    return 0\n", 0, "nine=90001"),
    # SIXTEEN arguments, which is the SHAPE of the outgoing area rather than the
    # count: SysV spaces arguments 8 bytes and AAPCS 8 bytes, so an ODD number
    # leaves the area short of the 16-byte alignment the `call` requires and the
    # padding has to go at the HIGH end so the first stack argument is still at
    # offset 0.  `a15 + a8 * 10 + a0` reads the last stack slot of each, which is
    # where a padding byte at the wrong end lands.
    ("both_arch_sixteen_arguments_arrive",
     "def wide(a0: int, a1: int, a2: int, a3: int, a4: int,\n"
     "          a5: int, a6: int, a7: int, a8: int, a9: int,\n"
     "          a10: int, a11: int, a12: int, a13: int, a14: int,\n"
     "          a15: int) -> int:\n"
     "    return a15 + a8 * 10 + a0\n\n"
     "def main() -> int:\n"
     "    printf(\"wide=%d\", wide(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16))\n"
     "    return 0\n", 0, "wide=107"),
    # TWENTY-FOUR arguments, which is `_MAX_INCOMING_ARGS` on both backends and
    # the one width where SysV's callee stops being able to read its own stack
    # arguments in ONE byte of displacement.  The prologue's loads are
    # `mov r11, [rbp + 16 + 8k]`, `_rm_disp` picks the narrowest encoding, and
    # 16 + 8k crosses 127 at k = 14: argument index 19 is `4c 8b 5d 78` and
    # argument index 20 is `4c 8b 9d 80 00 00 00` (measured).  So this row is the
    # only one that executes the four-byte form, and `a23` is the parameter whose
    # home is the widest of them.
    #
    # 241 is 24 + 21*10 + 7 — a23, a20 and a6, read from the last stack slot, a
    # middle disp32 slot and arm64's last REGISTER argument respectively, so no
    # single shifted index produces it.  Sixteen, the row above, is the largest
    # count whose stack slots are all disp8; this is the rung that would have
    # caught a call site writing the outgoing area with the disp8 encoder.
    ("both_arch_twenty_four_arguments_arrive",
     "def wide24(a0: int, a1: int, a2: int, a3: int, a4: int, a5: int,\n"
     "              a6: int, a7: int, a8: int, a9: int, a10: int, a11: int,\n"
     "              a12: int, a13: int, a14: int, a15: int, a16: int,\n"
     "              a17: int, a18: int, a19: int, a20: int, a21: int,\n"
     "              a22: int, a23: int) -> int:\n"
     "    return a23 + a20 * 10 + a6\n\n"
     "def main() -> int:\n"
     "    printf(\"w24=%d\", wide24(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12,\n"
     "                          13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24))\n"
     "    return 0\n", 0, "w24=241"),
    # The stack argument arriving from a CALLER'S PARAMETER rather than from a
    # literal, which is the direction a compiler can get wrong by FOLDING, and a
    # NESTED CALL in the ninth position, which is the direction it can get wrong
    # by ORDER: an argument expression that itself calls pushes and pops around
    # RSP, so the outgoing slots must be reserved BEFORE it is evaluated and the
    # store must survive the call.  With the register arguments spilled first,
    # the seventh argument reads as ZERO — indistinguishable from a caller who
    # passed zero, which is the answer the original refusal existed to prevent.
    ("both_arch_a_stack_argument_from_a_parameter_and_a_nested_call",
     "def nine(a0: int, a1: int, a2: int, a3: int, a4: int,\n"
     "          a5: int, a6: int, a7: int, a8: int) -> int:\n"
     "    return a8 * 10000 + a0\n\n"
     "def one() -> int:\n"
     "    return 7\n\n"
     "def call_it(w: int) -> int:\n"
     "    return nine(1, 2, 3, 4, 5, 6, 7, 8, w)\n\n"
     "def main() -> int:\n"
     "    printf(\"param=%d\", call_it(9))\n"
     "    printf(\" nested=%d\", nine(1, 2, 3, 4, 5, 6, 7, 8, one()))\n"
     "    return 0\n", 0, "param=90001 nested=70001"),
    # RECURSION, which is the one caller whose outgoing area is the SAME
    # function's own incoming arguments: `f`'s ninth argument lives in its
    # caller's frame at `[rbp + 16 + 16]`, and the recursive call inside `f`
    # reserves its own outgoing area BELOW `f`'s own RSP \u2014 so the two cannot
    # overlap, which is exactly what a convention that put the outgoing area
    # above RSP would get wrong.  37 is 2 + 5*7: the base case doubles `a0` and
    # every level adds `a6`, so a stack argument read as zero rather than 7
    # answers 2 and one read as a neighbour answers something in between.
    ("both_arch_stack_arguments_survive_recursion",
     "def dbl(v: int) -> int:\n"
     "    return v * 2\n\n"
     "def f(a0: int, a1: int, a2: int, a3: int, a4: int,\n"
     "      a5: int, a6: int, a7: int, n: int) -> int:\n"
     "    if n <= 0:\n"
     "        return dbl(a0)\n"
     "    return f(a0, a1, a2, a3, a4, a5, a6, a7, n - 1) + a6\n\n"
     "def main() -> int:\n"
     "    printf(\"rec=%d\", f(1, 2, 3, 4, 5, 6, 7, 8, 5))\n"
     "    return 0\n", 0, "rec=37"),
    # A DEFAULTED parameter past the sixth, which is the direction the convention
    # is most likely to be got wrong by FOLDING rather than by dropping: the
    # value in the outgoing slot is the DEFAULT the callee's own declaration
    # names, filled in by `bind_call_args` rather than by any call site, and the
    # two printfs differ only in whether the caller supplies those two at all.
    # Both answers are stated: `def=87` is 8*10+7, the defaults, and `870` is the
    # explicit 80 and 70 \u2014 so a convention that made the defaulted call read
    # the caller\u0027s register leftovers fails the first and not the second.
    ("both_arch_a_defaulted_stack_argument",
     "def f(a0: int, a1: int, a2: int, a3: int, a4: int, a5: int,\n"
     "      a6: int = 7, a7: int = 8) -> int:\n"
     "    return a7 * 10 + a6\n\n"
     "def main() -> int:\n"
     "    printf(\"def=%d\", f(1, 2, 3, 4, 5, 6))\n"
     "    printf(\" %d\", f(1, 2, 3, 4, 5, 6, 70, 80))\n"
     "    return 0\n", 0, "def=87 870"),
    # SIX arguments still work, and it is here as the boundary from the other
    # side: the fix is a stack argument PAST the register file, not a smaller
    # register file.  Without this row a change that cut either convention to the
    # other's limit would pass every row above on one architecture.
    ("both_arch_six_arguments_still_work",
     "def six(a0: int, a1: int, a2: int, a3: int, a4: int, a5: int) -> int:\n"
     "    return a5 * 10 + a0\n\n"
     "def main() -> int:\n"
     "    printf(\"six=%d\", six(1, 2, 3, 4, 5, 6))\n"
     "    return 0\n", 0, "six=61"),
    # THE COMPTIME HALF OF THE OPERATOR, and the row above is the reason it is
    # here. `//` is not an exotic operator on this path: `_emit_div_shift_pow`
    # lowers it (arm64 UDIV/SDIV) and `_emit_div_mod` lowers it (x86-64 IDIV),
    # the reference interpreter folds it (`myinterpreter.py`'s binary-op table),
    # and the row above pins what the RUNTIME does when the divisor is zero.
    # What was missing was the compile-time half, and it was missing in the
    # only way a missing operator can be: silently.
    #
    # `mojo/middle/comptime.py:fold_arith` is the ONE folder every compiled
    # path shares for `comptime NAME = ...` — arm64 and x86-64 both call
    # `resolve_var`, and the gimple path's evaluator goes through the same
    # `eval_const`. It had `+ - *` and `/` and no `//`, so
    #
    #     comptime c = 7 // 2
    #
    # printed `3` under `python3 fire.py run`, ran as `3` when the same `//`
    # sat OUTSIDE the `comptime`, and was REFUSED by both compiled backends as
    # "does not fold to a compile-time constant". One source, three answers,
    # and the two compiled ones were the odd ones out.
    #
    # The value is 43 on both architectures and every step is stated so a reader
    # can check it without running anything: `a` binds 100, `b` reads it and
    # folds to `100 // 7 == 14`, `c` reads `b` and folds to `(14 // 2) * 6 + 1
    # == 43`. The chain matters — a folder that resolved the names but not the
    # operator would produce nothing at all (a refusal), and one that folded the
    # operator but not the names likewise, so this row cannot pass with only half
    # the repair. 43 is not 0 and not 1 for a second reason: 1 is what the
    # row below makes the answer to a zero divisor, so a case whose right answer
    # were 1 could not tell "folded correctly" from "divided by zero and
    # trapped".
    ("both_arch_comptime_floor_division_folds",
     "def main(n: Int) -> Int:\n"
     "    comptime a = 100\n"
     "    comptime b = a // 7\n"
     "    comptime c = (b // 2) * 6 + 1\n"
     "    return c\n", 43, None),
    # `self = other` in a method of a MULTI-FIELD struct, and the expected
    # answer is the one that looks wrong until you run CPython.
    #
    # Assigning to `self` inside a method REBINDS THE LOCAL NAME. It does not
    # copy anything into the object the caller is holding: Python has no
    # "assign the receiver" operation at all, so after `self = other` the
    # method's own `self.<field>` reads and writes go to `other` and the
    # caller's object is exactly as it was. CPython 3.14 on this source:
    #
    #     class R:
    #         def __init__(self): self.a = 0; self.b = 0
    #         def copy_from(self, other): self = other
    #     r = R(); q = R(); r.a = 1; q.a = 2; r.copy_from(q)
    #     print(r.a, q.a)        ->  1 2
    #
    # which is what this path answers on both architectures. It was filed as a
    # silent wrong answer against a table saying CPython gives `a=2 b=2`
    # (FORMAL_receiver_copied_to_another_name_does_not_take_effect,
    # deleted): the multi-field receiver IS an address, and rebinding it is
    # precisely what Python does with the local name, so the arithmetic in
    # every later `self.<field>` is right AND the caller's frame is right. The
    # row is here so the next reader of that subject measures CPython before
    # filing it.
    ("both_arch_receiver_copied_from_another_keeps_the_callers_value",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def copy_from(out self, other: Self):\n"
     "        self = other\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    var q = R()\n"
     "    r.a = 1\n"
     "    q.a = 2\n"
     "    r.copy_from(q)\n"
     "    printf(\"a=%d b=%d\", r.a, q.a)\n"
     "    return 0\n", 0, "a=1 b=2"),
    # The same fact from the other direction, and it is the shape with the
    # fields ASSIGNED AFTER the rebinding — so a lowering that copied the
    # fresh object's slots into the caller's would answer 5, 6 here and CPython
    # answers 0, 0. Both numbers are printed, so a wrong one cannot pass for
    # the other: `a=0 b=0` and `a=5 b=6` differ in every position.
    ("both_arch_receiver_assigned_a_construction_keeps_the_callers_value",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def zero(out self):\n"
     "        self = R()\n"
     "        self.a = 5\n"
     "        self.b = 6\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.zero()\n"
     "    printf(\"a=%d b=%d\", r.a, r.b)\n"
     "    return 0\n", 0, "a=0 b=0"),

    # ── a class-level constant and a field default are LITERAL expressions ──
    #
    # `formal/model.py::literal_default_word` is the one classifier behind both
    # of these (`class_constant_word` and `struct_default_word` are the same
    # question of the same node), and it used to have arms for `IntLiteral` /
    # `BoolLiteral` / `StringLiteral` and nothing else. So `-3` — which parses to
    # `UnaryOp('-', IntLiteral(3))`, one token wider than `3` and exactly
    # representable in the word `3` already is — was REFUSED with a message
    # claiming the value "is not a value this build can materialize". That
    # message is false, and it is worse than wrong: it sends a reader looking
    # for something non-literal in their own source, and there is nothing there.
    #
    # The fix is not a new arm but the DELETION of the second classifier:
    # `literal_default_word` now folds with `fold_literal_expr`, the folder the
    # module-level constants already used, so one rule answers "can the build
    # know this value" for every binding a class body or a module body declares.
    # `1 + 2` and `~0` come with it for the same reason, and they are in the
    # same program so a fix that added only the unary-minus arm is visible.
    #
    # Both spellings of a read are here — bare `Regs.A` and `self.A` through a
    # method — because `_rewrite_class_constants` substitutes both from the same
    # census and the receiver spelling has a separate arm (`struct_receivers`).
    ("both_arch_negative_and_folded_class_constant",
     "class Regs:\n"
     "    A = -3\n"
     "    B = 7\n"
     "    C = 1 + 2\n"
     "    D = ~0\n"
     "\n"
     "    def both(self):\n"
     "        printf(\"A=%d B=%d\", self.A, self.B)\n"
     "        return 0\n"
     "\n"
     "def main() -> int:\n"
     "    r = Regs()\n"
     "    r.both()\n"
     "    printf(\" C=%d D=%d\", Regs.C, Regs.D)\n"
     "    return 0\n", 0, "A=-3 B=7 C=3 D=-1"),

    # THE SAME FOLD, on the other side of the same classifier: a FIELD's
    # default, which the constructor materializes rather than the read.
    # `-3` and `100000` are one row each because they failed differently and
    # only one of them was a build crash:
    #
    #   * `100000` does not fit MOVZ's 16-bit unsigned field, and the arm64
    #     emitter reached for `encode_movz_xn_imm` directly instead of this
    #     backend's own `_emit_mov_imm`, so it died on `assert 0 <= imm16 <=
    #     0xffff`. x86-64 was fine — its three twins all call `_emit_mov_imm`.
    #     A wide default has been buildable on one architecture and not the
    #     other, which is why this is a both-arch case and not an arm64 one.
    #   * `-3` is the row above's value in the other position, and it is here
    #     because the two paths are two call sites of one classifier and a fix
    #     that reached only the read would leave the constructor emitting a
    #     truncated word for the very same default.
    #
    # `m` has no default and must read 0 — the boundary between "a default this
    # path materializes" and "no default", which is the refusal/zero distinction
    # `struct_default_word` exists to keep.
    ("both_arch_negative_and_wide_struct_field_default",
     "struct R:\n"
     "    var n: Int = -3\n"
     "    var m: Int\n"
     "    var w: Int = 100000\n"
     "\n"
     "    def show(self) -> Int:\n"
     "        printf(\"n=%d m=%d w=%d\", self.n, self.m, self.w)\n"
     "        return 0\n"
     "\n"
     "def main() -> int:\n"
     "    r = R()\n"
     "    r.show()\n"
     "    return 0\n", 0, "n=-3 m=0 w=100000"),

    # The MODULE-level spelling of the same fold, which is the one that was
    # never broken and is here as the control: `G = -5` was already answered
    # (by `fold_module_value`), so if this row ever fails while the two above
    # pass, the classifier and the module folder have drifted apart again —
    # which is the whole failure mode of having two folders.
    ("both_arch_negative_and_folded_module_constant",
     "G = -5\n"
     "H = ~0\n"
     "I = 6 * 7\n"
     "\n"
     "def main() -> int:\n"
     "    printf(\"G=%d H=%d I=%d\", G, H, I)\n"
     "    return 0\n", 0, "G=-5 H=-1 I=42"),

    # `comptime c = ~3` is the third folder, and it is a row of its own because
    # `mojo/middle/comptime.py:eval_const` is a DIFFERENT function from
    # `fold_literal_expr` that answers the same question about the same operator:
    # both formal backends already LOWERED `~` at run time (one MVN, one NOT) and
    # the reference interpreter evaluates it, while every compile-time folder
    # refused it. So the program printed -4 under `python3 fire.py run`, ran at
    # run time as -4 when the same `~` sat outside the `comptime`, and was
    # REFUSED when it was inside one. `~` is now in all three folders, which is
    # the only way that stays true when a fourth is written.
    ("both_arch_comptime_bitwise_not_folds",
     "def main(n: Int) -> Int:\n"
     "    comptime c = ~3\n"
     "    comptime d = -2\n"
     "    return c + d + 11\n", 5, None),
    # A `while` BODY's store read after the loop, where the condition is
    # decidable on entry because the preheader states it.  This is the shape
    # `“A name stored only in a `while` body is refused, though the loop provably ran”` is about,
    # and the reason the row is here and not only in
    # `test_formal_read_before_store.py` is that the analysis answering `ok` and
    # the EMITTED image printing 1 are two different claims: the analysis runs
    # no code at all, and the register the read comes from is a caller-supplied
    # word, so "the analysis stopped refusing" would be satisfied by a build
    # that answers 8432255232.
    #
    # `t` is stored ONLY in the loop body, which is the whole point: before
    # `model._preheader_literals` this program's build was REFUSED, because the
    # body's first iteration depended on a condition the graph could not decide.
    # The values distinguish the iteration counts — `t` takes `i + 1` on each
    # pass, so it ends at 3 for `i = 2` and `i` at 3 — so a build that ran the
    # body zero times, or once, or twice, prints a different pair, and a build
    # that left the slot at the caller's word does not print this at all.
    ("both_arch_while_body_store_read_after_the_loop",
     "def f(n):\n"
     "    var i = 0\n"
     "    while i < 3:\n"
     "        t = i + 1\n"
     "        i = i + 1\n"
     "    printf(\"t=%d i=%d\", t, i)\n"
     "    return 0\n"
     "def main(n: Int) -> Int:\n"
     "    return f(0)\n", 0, "t=3 i=3"),
    # A BYTE out of a string, and the two rows that say the rule that produces it
    # (`model.subscript_element_kind`) did not take the byte away from the
    # readers that want a NUMBER.  `s[i]` is the byte on this path, so `%d` of it
    # and `s[0] == 97` are true and were true before the rule existed; a change
    # that made the subscript refuse would be a working program traded for a
    # diagnostic, and these are the rows that notice.  Every expected value is
    # the ASCII code of the character: `s[0]` is `'a'` = 97, `s[1]` is `'b'` = 98,
    # `s[2]` is `'c'` = 99, and `97 == 97` is 1.
    ("both_arch_string_byte_renders_as_a_number",
     "def main(n: Int) -> Int:\n"
     "    var s = \"abc\"\n"
     "    printf(\"[%d][%d][%d][%d]\", s[0], s[1], s[2], s[0] == 97)\n"
     "    return 0\n", 0, "[97][98][99][1]"),
    # …and through `print`, which is the half of the rule that is NOT a refusal:
    # `_print_call` asks the KIND, and "the source does not say" was a
    # `print() cannot tell whether SubscriptExpr is a string or a number` about a
    # value the model can now classify.  The row is here for the same reason as
    # the one above it — a NEW emission is worth less than a pinned one.
    ("both_arch_print_of_a_string_byte_renders_the_byte",
     "def main(n: Int) -> Int:\n"
     "    var s = \"abc\"\n"
     "    print(s[0])\n"
     "    return 0\n", 0, "97"),
    # THE GUARDS for the one-field receiver rebinding rule, and they are the
    # reason the rule is scoped to a name of the receiver's OWN TYPE rather than
    # written as "never rebind a one-field receiver". Both of these are the
    # mechanism that rule sits next to, and both are how 28 of the 51
    # hand-written `self = …` sites in this repository and the stdlib are spelled
    # (`self = self & rhs`, `self = False`, `self = _binary_op(self, rhs)`).
    #
    # `self.a = other.a` is the field store the rewrite collapses onto `self`
    # and the write-back exists to deliver: CPython copies 2 into `x` and so
    # does this. `self = self + 4` is the same store spelled as a rebinding of
    # the receiver's own word: CPython's `x` is 5 and so is this. A rule that
    # matched the TARGET rather than the VALUE would refuse both and cost
    # `std/builtin/bool.mojo`, whose `__iand__`/`__ior__`/`__ixor__` are the
    # second row verbatim.
    ("both_arch_one_field_stores_through_the_receiver_still_reach_the_caller",
     "struct T:\n"
     "    var a: Int\n"
     "\n"
     "    def take(out self, other: Self):\n"
     "        self.a = other.a\n"
     "\n"
     "    def bump(out self):\n"
     "        self = self + 4\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = T()\n"
     "    x.a = 1\n"
     "    var y = T()\n"
     "    y.a = 2\n"
     "    x.take(y)\n"
     "    x.bump()\n"
     "    printf(\"a=%d\", x.a)\n"
     "    return 0\n", 0, "a=6"),
    # …and the SCOPE of the rule, which is the receiver WRITE-BACK and not the
    # rebinding: a PLAIN receiver on a one-field struct is never handed back, so
    # nothing this method does to its own word can reach the caller and Python's
    # rebinding semantics are already what happens. `x` keeps 1, which is
    # CPython's answer, and a rule that ignored the receiver's convention would
    # refuse a program that is right.
    ("both_arch_one_field_plain_receiver_rebinding_is_left_alone",
     "struct T:\n"
     "    var a: Int\n"
     "\n"
     "    def peek(self, other: Self) -> Int:\n"
     "        var t = other\n"
     "        self = t\n"
     "        return self\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = T()\n"
     "    x.a = 1\n"
     "    var y = T()\n"
     "    y.a = 2\n"
     "    x.peek(y)\n"
     "    printf(\"a=%d\", x.a)\n"
     "    return 0\n", 0, "a=1"),
    # ── the store a one-field receiver CANNOT deliver ───────────────────────
    #
    # Found by `tools/formal_fuzz.py`, and the shape above is why the two rows
    # before it did not catch it: they are about a REBINDING of the receiver,
    # which CPython also does not deliver, so leaving it alone is right. This is
    # a store to the FIELD, which CPython DOES deliver — into the object the
    # caller holds — and which this path computed and dropped:
    #
    #     class C:
    #         def __init__(self): self.a = 2
    #         def bump(self):     self.a = 7
    #         def get(self):      return self.a
    #     c = C(); c.bump(); print(c.get())      # CPython 7, this path 2
    #
    # Builds, ran, exited 0, and printed the constructor's value on BOTH
    # architectures. `model.one_field_dropped_receiver_stores` is the rule and
    # `receiver_writeback_name` is the mechanism it is about: the write-back
    # needs the receiver declared `out`/`inout`/`mut`, and a plain `self` is
    # never handed back. Refused rather than delivered, because the one return
    # word is the receiver and delivering the store would cost the method's own
    # value — the same ABI reason `mutating_receiver_return_refusal` gives.
    #
    # The needle is the LOAD-BEARING half of the message: it says the receiver
    # is not handed back. A message that only said "one-field receiver" would be
    # indistinguishable from a one-field READER, which builds.
    # …and the WIDTH is the whole rule, so the two-field spelling of the same
    # program is the guard: its receiver is a frame address the caller still
    # owns, so the store lands and CPython's answer is already this path's.
    ("both_arch_two_field_store_through_a_plain_receiver_still_reaches_it",
     "class D:\n"
     "    def __init__(self):\n"
     "        self.a = 2\n"
     "        self.b = 5\n"
     "\n"
     "    def bump(self):\n"
     "        self.a = 7\n"
     "\n"
     "    def get(self):\n"
     "        return self.a + self.b\n"
     "\n"
     "def main(n):\n"
     "    d = D()\n"
     "    d.bump()\n"
     "    printf(\"a=%d\", d.get())\n"
     "    return 0\n", 0, "a=12"),
    # And the CONSTRUCTOR is not refused, because it is not a call: its stores
    # are inlined into the construction site, which is where CPython runs them.
    # `one_field_reader_is_not_a_mutator` and `both_arch_zero_arg_init_stores_a
    # _one_field_scalar` cover the read and the zero-argument spelling; this row
    # is the one where a plain receiver's `__init__` takes a PARAMETER and stores
    # it, so the refusal cannot be "plain receivers are refused" by accident.
    ("both_arch_one_field_init_stores_its_parameter_through_a_plain_receiver",
     "struct T:\n"
     "    var a: Int\n"
     "\n"
     "    def __init__(self, v: Int):\n"
     "        self.a = v\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var t = T(9)\n"
     "    printf(\"a=%d\", t.get())\n"
     "    return 0\n", 0, "a=9"),
    # ── the STACK FLOOR (`formal/model.py`: `stack_floor_guarded_names`,
    # `STACK_FLOOR_BUDGET_BYTES`, `STACK_TRAP_STATUS`) ──
    #
    # A runaway recursion used to be a SIGSEGV on both backends: no output and
    # no status a caller could read, above 61 frames on arm64 and above ~470 on
    # x86-64. These three rows are the whole of the fix's observable behaviour,
    # and each fails if the guard is absent, if it misfires, or if the cycle
    # detection misses a shape:
    #
    #   * `stack_floor_deep_recursion_is_a_status` — the defect. `deep(5000)` is
    #     far past either backend's ceiling and the answer is the exit status
    #     `STACK_TRAP_STATUS`. `want_stdout=None` because `printf` is inside
    #     `main` and the trap fires before it.
    #   * `stack_floor_shallow_recursion_still_answers` — the other direction,
    #     and the one a guard that fired unconditionally would fail: 30 deep is
    #     nowhere near the budget and must still print 30.
    #   * `stack_floor_mutual_recursion_is_a_status` — the cycle detection, not
    #     the guard. `ping`/`pong` are only a cycle TOGETHER, so a rule that
    #     looked for a function calling ITSELF would guard neither and this row
    #     would be a SIGSEGV again.
    ("stack_floor_deep_recursion_is_a_status",
     "def deep(n: Int) -> Int:\n"
     "    if n <= 0:\n"
     "        return 0\n"
     "    return deep(n - 1) + 1\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return deep(5000)\n", 2, None),
    ("stack_floor_shallow_recursion_still_answers",
     "def deep(n: Int) -> Int:\n"
     "    if n <= 0:\n"
     "        return 0\n"
     "    return deep(n - 1) + 1\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    printf(\"%d\\n\", deep(30))\n"
     "    return 0\n", 0, "30"),
    ("stack_floor_mutual_recursion_is_a_status",
     "def pong(n: Int) -> Int:\n"
     "    if n <= 0:\n"
     "        return 0\n"
     "    return ping(n - 1)\n"
     "\n"
     "def ping(n: Int) -> Int:\n"
     "    if n <= 0:\n"
     "        return 0\n"
     "    return pong(n - 1) + 1\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return ping(5000)\n", 2, None),
    # `unsafe_load` is Mojo's OWN name for the read this path already lowers:
    # `UnsafePointer.unsafe_load(i = 0)` is a pointer's `value()` with the index
    # defaulted, and it was in NEITHER the dereference table nor the refusal
    # tables — so `p.unsafe_load()` reached `value_method_refusal`'s generic arm
    # and was reported as a method call on a receiver holding an `int`, on a
    # parameter the source had annotated `Pointer[UInt8]`. Measured before the
    # fix, both architectures, with a declared pointee.
    #
    # The five widths are the whole assertion. What must hold is not "it builds"
    # but "`unsafe_load` answers EXACTLY what `value` answers at the same
    # address", so the row reads one address five ways and each reading has to
    # come back right on its own terms: 65 / 16961 / 1145258561 / 65 / 5208208757
    # 389214273 are the little-endian readings of b"ABCDEFGH" at 1, 2, 4, 8-signed
    # and 8-unsigned bytes — the same constants `deref_four_widths_at_one_address`
    # states for `value`. The signed 1-byte read is 65 and not a sign-extended
    # negative because 'A' has its top bit clear, so it cannot tell a
    # sign-extend from a zero-extend; `deref_i8_signed` is the row that can.
    ("both_arch_deref_unsafe_load_is_the_same_load_as_value",
     "def read8(p: Pointer[UInt8]) -> Int:\n"
     "    return Int(p.unsafe_load())\n"
     "def read2(p: Pointer[UInt16]) -> Int:\n"
     "    return Int(p.unsafe_load())\n"
     "def read4(p: Pointer[Int32]) -> Int:\n"
     "    return Int(p.unsafe_load())\n"
     "def read8s(p: Pointer[Int8]) -> Int:\n"
     "    return Int(p.unsafe_load())\n"
     "def read8u(p: Pointer[UInt64]) -> Int:\n"
     "    return Int(p.unsafe_load())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    if read8(s) != 65:\n"
     "        return 10\n"
     "    if read2(s) != 16961:\n"
     "        return 11\n"
     "    if read4(s) != 1145258561:\n"
     "        return 12\n"
     "    if read8s(s) != 65:\n"
     "        return 13\n"
     "    if read8u(s) != 5208208757389214273:\n"
     "        return 14\n"
     "    return 1\n", 1, None),
    # ── THE ACYCLIC CHAIN, ON BOTH ARCHITECTURES ───────────────────────────
    #
    # A recursion is what the guard was written for and the three rows above are
    # that. This row is the other half: SIX HUNDRED DISTINCT functions, each
    # calling the next, with no call back into anything already on the stack.
    # Unbounded depth needs a cycle, so a chain like this walked straight past
    # the floor — and the corpus is already inside it, which is what
    # `bugs/FORMAL_stack_floor_does_not_guard_an_acyclic_chain.md` spent its life
    # measuring: `tools/formal_call_depth_census.py` puts the deepest single
    # image in this repository at 76 frames against the 60 an arm64 budget
    # affords (`formal/arm64_codegen.py`, and 69 for `x86_64_codegen.py`).
    #
    # 600 rather than 61 because x86-64's frame is 16 KiB to arm64's 128 KiB, so
    # its budget affords 480 frames and a 61-deep chain is correctly INSIDE it.
    # A single depth cannot therefore show the defect on both machines, and a
    # case that only fires on one is a case whose subject is the FRAME SIZE
    # rather than the guard. 600 crosses both: 600 x 128 KiB = 75 MiB against
    # arm64's 7.5 MiB, and 600 x 16 KiB = 9.4 MiB against x86-64's 7.5 MiB.
    #
    # GENERATED, and that is the point rather than a convenience: no hand-written
    # function in this file is 600 calls deep, so only a generator reaches the
    # shape at all — the same reason `spills_2001_statements` exists.
    #
    # `if n > 1000000: return n` in every body is what makes this a case about
    # the SECOND rule rather than the first: a body with no conditional branch
    # is not guarded off the cycle, and 600 of those is the measured residual
    # `stack_floor_guarded_names`'s docstring states (12 frames over the whole
    # corpus, a median of 3).
    #
    # Measured before the widening, on both architectures: exit 139 (SIGSEGV,
    # no output, no status). After: `STACK_TRAP_STATUS`, exit 2.
    ("both_arch_an_acyclic_chain_past_the_floor_is_a_status",
     "".join(
         "def d%d(n: Int) -> Int:\n"
         "    if n > 1000000:\n"
         "        return n\n"
         "    %s\n" % (i, "return n + 1" if i == 599 else "return d%d(n)" % (i + 1))
         for i in range(600))
     + "def main(n: Int) -> Int:\n"
       "    if n > 1000000:\n"
       "        return n\n"
       "    return d0(n)\n", 2, None),
    # ── THE THIRD RULE: EVERY FUNCTION, IN AN IMAGE THAT HAS AN ENTRY ─────
    #
    # The two rules above are a predicate over a body. This one is a fact about
    # the IMAGE, and it is what closes the residual
    # `bugs/FORMAL_stack_floor_does_not_guard_an_acyclic_chain.md` measured: the
    # guard's floor is written by the first guarded function to RUN, so a guard
    # on only some prologues puts the floor wherever the program happens to reach
    # one first, and a chain of unguarded functions below that point is under a
    # floor that was already too deep to catch anything.
    #
    # Measured, both architectures, on the shape below (601 straight-line
    # functions, no cycle and no branch anywhere): before, `exit 139` — a
    # SIGSEGV with no output and no status; after, `STACK_TRAP_STATUS`, exit 2.
    # Guarding `main` ALONE does not do it — the check runs once, at main's
    # prologue, where the stack is one frame deep — which is why the rule is the
    # whole set and not the entry.
    ("both_arch_a_straight_line_chain_past_the_floor_is_a_status",
     "".join(
         "def d%d(n: Int) -> Int:\n"
         "    %s\n" % (i, "return n + 1" if i == 599 else "return d%d(n)" % (i + 1))
         for i in range(600))
     + "def main(n: Int) -> Int:\n"
       "    return d0(n)\n", 2, None),
    # ── A DELEGATING CONSTRUCTOR OVER A STRUCT OF THIS MODULE ──────────────
    #
    # A DELEGATING CONSTRUCTOR storing a frame address into a field of a
    # struct that outlives it — the shape that was refused until
    # `model.init_stores_a_parameter_struct` landed (2026-10-03), and what it
    # took was closing a THREE-step deadlock between two decisions that were
    # each individually right:
    #
    #   1. `model.struct_nested_frame_fields` PLACED a nested frame in every
    #      field whose declared type names a framed struct of this module and
    #      whose only writer is `__init__` — the constructor reserving a block in
    #      the object's own block and storing that block's ADDRESS in the slot.
    #   2. which made `formal/build.py`'s `_frame_field_store_is_sound` refuse
    #      `self.src = r`, correctly: the slot IS placed, so a pointer stored
    #      over it leaves a word where every reader computes a frame base from
    #      it.
    #   3. and `_typed_nested_frame` answered `_REASSIGNED` at the read, because
    #      the placement list — the authority it consults — did not have the
    #      field in it.
    #
    # The store and the read are both right about a field the constructor BUILDS
    # there. This one does not build one: it stores the CALLER's frame. So the
    # slot is a POINTER slot, `struct_nested_frame_fields` now says so
    # (`model.init_stores_a_parameter_struct`, the predicate `one_word_field_struct`
    # was already asking for the same evidence), `_typed_nested_frame` says so
    # too — and it must say it with the STRUCT rather than with `_REASSIGNED`,
    # because `_REASSIGNED`'s own sentence ("a frame belonging to whichever
    # function ran the assignment") is false here: the only assignment is
    # `__init__`'s and the frame in the slot is the caller's.
    #
    # 7 + 1 = 8, and the reader is a METHOD (`h.total()`) as well as a field read
    # (`h.src.a`) because the two go through different arms and a fix that
    # reached only the value-position read would leave the method receiver
    # refusing.
    ("both_arch_a_delegating_constructor_over_a_struct_of_this_module",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct Holder:\n"
     "    var src: R\n"
     "    var n: Int\n"
     "\n"
     "    def __init__(self, r: R):\n"
     "        self.src = r\n"
     "        self.n = 1\n"
     "\n"
     "    def total(self) -> Int:\n"
     "        return self.src.a + self.n\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.b = 8\n"
     "    var h = Holder(r)\n"
     "    printf(\"%d %d\", h.src.a, h.total())\n"
     "    return h.src.a + h.n\n", 8, "7 8"),
    # GUARD for the placement itself, in the direction that keeps it working: a
    # slot whose `__init__` writes only `self.tag` — never `in1` — is still a
    # PLACED nested frame, and two objects still get two frames. Without this row
    # a fix that dropped the placement rather than narrowing it would look green.
    #
    # It is the shape `assigned_type_nested_frame_two_objects_no_alias` uses,
    # deliberately: that case's `Outer` has a two-field frame (`tag`, `pad`) so
    # `in1` lands at slot 2, which is what makes it a depth-2 nested frame rather
    # than the depth-1 one-word case, and it is the only shape on this path that
    # both PLACES a nested frame and writes through one afterwards.
    ("a_constructed_nested_frame_is_still_placed",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    var in1: Inner\n"
     "\n"
     "    fn __init__(self):\n"
     "        self.tag = 0\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o1 = Outer()\n"
     "    var o2 = Outer()\n"
     "    o1.in1.a = 1\n"
     "    o1.in1.b = 2\n"
     "    o2.in1.a = 7\n"
     "    o2.in1.b = 8\n"
     "    printf(\"%d %d\", o1.in1.a * 10 + o1.in1.b, o2.in1.a * 10 + o2.in1.b)\n"
     "    return o1.in1.a + o2.in1.a\n", 8, "12 78"),
    # ── A LOOP VARIABLE'S KIND, ON BOTH ARCHITECTURES ──────────────────────
    #
    # Every other row of this change is in PRINTF_TEXT_CASES and runs on the
    # host only, which is the wrong economy here: the subject is one table in
    # `formal/model.py` that both backends ask (`ValueKinds._iterable_own_shape`
    # for the kind, `truthy_lowering` for the conversion), so what needs proving
    # is that they come out the SAME, and that is what this row is for.
    #
    # The pre-change answers were a WRONG NUMBER on both machines and both were
    # wrong in the same direction, which is the failure mode nothing else here
    # catches: `a` (a `for` over three strings, one of them empty) was 3 and
    # `b` (a comprehension over four of them, one empty) was 4, both where
    # CPython says 2 and 3. `c` and `d` are the two guards — the outer `x` stays
    # an integer beside a comprehension that rebinds `x`, and `len` of a
    # comprehension target is a `strlen` rather than a refusal (which is what
    # made `d` answerable at all).
    #
    # Every number printed is distinct, and the trailing `5` is a constant in the
    # format so a formatter that dropped an argument would still print five of
    # them.
    ("both_arch_loop_and_comprehension_variable_hold_an_element",
     "def main(n: Int) -> Int:\n"
     "    var a = 0\n"
     "    for t in [\"p\", \"\", \"q\"]:\n"
     "        if t:\n"
     "            a = a + 1\n"
     "    var b = len([y for y in [\"p\", \"\", \"q\", \"r\"] if y])\n"
     "    var x = 5\n"
     "    var c = 0\n"
     "    if x:\n"
     "        c = c + 1\n"
     "    var lens = [len(k) for k in [\"a\", \"bb\", \"ccc\", \"dddd\"]]\n"
     "    var d = lens[3]\n"
     "    printf(\"%d %d %d %d %d\", a, b, c, d, 5)\n"
     "    return 0\n", 0, "2 3 1 4 5"),

    # ONE NAME, TWO `__init__`s, only ONE of which has a receiver. Both halves of
    # the defect this pins are about that collision, and each one alone leaves a
    # different program refusing, which is why this is one row and not two.
    #
    # The source is `std/builtin/float_literal.mojo`'s own shape: an `@implicit`
    # CONVERTING constructor is spelled with NO receiver parameter at all
    # (`@implicit def __init__(_value: IntLiteral[_]) -> FloatLiteral[…]`), so
    # its first parameter is an ordinary argument. Two defects followed from
    # reading "first parameter" as "receiver":
    #
    #   * `struct_init_shapes` skipped `_value` as "the receiver" — it asked a
    #     CLASS-WIDE set, and `struct_receivers` takes the first parameter's name
    #     whatever it is called — so this overload counted ZERO required
    #     parameters, `Cell()` was ambiguous against `__init__(out self)`, and
    #     the message read "(0 required; 0 required)" for two constructors whose
    #     arities are 0 and 1;
    #   * `build._return_the_receiver` applied the mutating overload's write-back
    #     entry to THIS one, because the entry is keyed by the lifted name and
    #     `method_function_name` gives one name to every overload of one method.
    #     It refused the file with "both changes its receiver and returns a
    #     value" about a method that changes no receiver — measured on
    #     `float_literal.mojo` before the fix, on both architectures.
    #
    # The answer is `7`, and what it pins is the ARITY READER: the zero-operand
    # `__init__(out self)` is selected, which it could not be while the other
    # overload counted zero required parameters too.
    ("an_implicit_converting_init_next_to_a_mutating_one_is_not_a_mutator",
     "struct Cell:\n"
     "    var _value: Int\n"
     "\n"
     "    def __init__(out self):\n"
     "        self._value = 7\n"
     "\n"
     "    @implicit\n"
     "    def __init__(_value: Int) -> Cell:\n"
     "        return _value\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    printf(\"%d\", c._value)\n"
     "    return 0\n",
     0, "7"),
    # …and the WRITE-BACK half, which the row above does not reach: `Cell()` is
    # a CONSTRUCTION, whose `__init__` body is inlined at the call site, so `7`
    # above is carried by the inline and says nothing about a mutator handing its
    # receiver back. `bump` is a plain method call, which is the shape the
    # write-back exists for, and 9 is `_value = 7` plus the `+ 2` — 7 is what a
    # dropped write-back prints. This row is also the regression guard for the
    # fix itself: the new guard in `build._return_the_receiver` returns early for
    # a function that is not a mutator, and a guard that matched on the LIFTED
    # name instead of on the function would silence this row's write-back along
    # with the false refusal.
    ("a_mutating_init_keeps_its_write_back_beside_a_converting_one",
     "struct Cell:\n"
     "    var _value: Int\n"
     "\n"
     "    def __init__(out self):\n"
     "        self._value = 7\n"
     "\n"
     "    @implicit\n"
     "    def __init__(_value: Int) -> Cell:\n"
     "        return _value\n"
     "\n"
     "    def bump(out self, k: Int):\n"
     "        self._value = self._value + k\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c.bump(2)\n"
     "    printf(\"%d\", c._value)\n"
     "    return 0\n",
     0, "9"),

    # ── a comprehension INSIDE a generator's ITERABLE ──
    #
    # Refused on both architectures before the fix, with a message that names an
    # internal table rather than the construct: "`_cb1` has no home: the
    # register allocator collected no home for it, so the emitter and the
    # allocation walk disagree about this function's locals". The disagreement
    # was exactly one: `_emit_comprehension` raises `_compr_depth` to
    # `d0 + len(gens)` for the WHOLE walk (the iterable included), while
    # `_collect_var_names`' comprehension walk reserved a nested
    # comprehension's `_ci{d}`/`_cb{d}` at the OUTER depth — so the emitter
    # asked for `_ci1` and the collector had reserved `_ci0` only — the depth
    # disagreement between `_emit_comprehension` and `_collect_var_names`, fixed
    # 2026-10-03 in 232011b3: the two now walk a generator's ITERABLE at
    # `depth + len(gens)`, which is the emitter's convention.
    #
    # In this group rather than `CASES` because the two conventions are the two
    # backends' own (`_collect_var_names` is spelled twice, once per backend),
    # and a row checked on the host alone would not have caught the x86-64 half.
    #
    # The four shapes in one program, because each reaches a different part of
    # the walk: the nest in the FIRST generator's iterable (`2 11`), the nest in
    # the SECOND generator's iterable of a two-generator comprehension (`4`),
    # a three-deep nest where the middle generator's ELEMENT holds the inner
    # one, and a DICT comprehension whose values are comprehensions. The `+` in
    # an inner element is the second half of the fix, and without it this row
    # is a fault rather than a wrong number: `_container_ctx` is ambient, so a
    # comprehension reached from a container position lowered its own `+` as a
    # list CONCAT and copied an integer as a blob base (SIGSEGV on x86-64,
    # `movq (%rsi), %r8` with rsi = 10). The row below is that half on its own.
    ("nested_comprehension_in_a_generator_iterable",
     "def main() -> Int:\n"
     "    var a = [y for y in [x + 1 for x in [10, 20]]]\n"
     "    var b = [q for p in [1, 2] for q in [r * 2 for r in [5, 6]]]\n"
     "    var c = [z for z in [y for y in [x for x in [7, 8]]]]\n"
     "    var d = {k: [v for v in [1, 2, 3]] for k in [1, 2]}\n"
     "    printf(\"%d %d %d %d\", len(a), a[0], len(b), b[3])\n"
     "    printf(\" %d %d %d %d\", len(c), len(d), c[0],\n"
     "           len([v for v in [1, 2, 3]]))\n"
     "    return 0\n",
     0, "2 11 4 12 2 2 7 3"),

    # ── a comprehension's BODY is not a container position ──
    #
    # `_container_ctx` is read by `_emit_binop` at whatever depth it finds
    # itself, so a comprehension reached from a for-iterable or a membership
    # RHS inherited that position and concatenated its own arithmetic:
    # `for y in [x + 1 for x in [10, 20]]` copied the integer 10 as a blob base
    # and died with SIGSEGV on BOTH architectures. Inside a comprehension `+` is
    # arithmetic, and the operands decide on their own (`_is_container_expr`).
    #
    # The last two lines are the other side of the same fix and are what keep it
    # from over-correcting: a generator's ITERABLE *is* a container position, so
    # `[x for x in a + b]` concatenates — which it must, and which on both
    # architectures used to loop FOREVER on arm64 (no elevation there at all, so
    # `a + b` took the ALU path and the generated walk never advanced) and on
    # x86-64 only by way of the same ambient flag this row removes.
    ("comprehension_body_is_not_a_container_position",
     "def main() -> Int:\n"
     "    var a = [1, 2]\n"
     "    var b = [3, 4]\n"
     "    var s = 0\n"
     "    for y in [x + 1 for x in [10, 20]]:\n"
     "        s = s + y\n"
     "    if 32 in [x + 1 for x in [10, 20, 21]]:\n"
     "        s = s + 100\n"
     "    var r = [x for x in a + b]\n"
     "    if 1 in [x for x in a + b]:\n"
     "        s = s + 1000\n"
     "    printf(\"%d %d %d %d\", s, len(r), r[3], len([x for x in [1, 2]]))\n"
     "    return 0\n",
     0, "1032 4 4 2"),
    # ── `~` IS BITWISE, and it is in THIS group for a reason ────────────
    #
    # The PROOF layer modelled `~x` as `x = 0` -- Python's `not`, not its `~` --
    # so the source model of every program using `~` was a model of a different
    # program, on both backends at once, and `eval_eq_mojo` did not catch it
    # because `evalExpr` made the same mistake (`bugs/FORMAL_the_semantic_model_
    # renders_a_bitwise_not_as_a_logical_one.md`). The MACHINE half was right all
    # along, which is what makes these rows the ones that had to be written: the
    # fix was a model fix, and a model fix with no executed case beside it is a
    # claim with nothing under it. `test_formal_eval_eq_mojo_bridge.py` carries
    # the model and the run-test assertions; these are the codegen rows, and they
    # are in `BOTH_ARCH_CASES` because `~` is an ARM64 `MVN`/`ORN` and an x86-64
    # `NOT`, two encodings and two step lemmas for one meaning.
    #
    # `~10` is -11, printed as `%lx` because a process exit status is eight bits
    # and 0xfffffffffffffff5 is not. CPython computes the same three answers on
    # the same expressions.
    ("both_arch_bitwise_not_complements_every_bit",
     "def main(n: Int) -> Int:\n"
     "    printf(\"%lx\", ~10)\n"
     "    return 0\n", 0, "fffffffffffffff5"),
    # The row that says BITWISE: a LOGICAL `not 0` is 1 and a bitwise `~0` is all
    # ones, so a model or a lowering that swapped them answers 1 here.
    ("both_arch_bitwise_not_of_zero_is_all_ones",
     "def main(n: Int) -> Int:\n"
     "    printf(\"%lx\", ~0)\n"
     "    return 0\n", 0, "ffffffffffffffff"),
    # The doc's own reproducer: `& ~31` is the ordinary 32-byte-align idiom and
    # this repository writes it in three places. `n` is the entry argument, 10
    # (`formal/build.py`'s `test_input`), so (10 + 48) & ~31 = 58 & 0x…ffe0 =
    # 32 -- a mask of all ones would give 58 and a logical `not` would give a
    # number no align could produce.
    ("both_arch_and_of_a_complemented_align_mask",
     "def main(n: Int) -> Int:\n"
     "    printf(\"%ld\", (n + 48) & ~31)\n"
     "    return 0\n", 0, "32"),
    # ONE POINTER, TWO SPELLINGS, and the callee that reads it the same way
    # from each — the answered half of the pair in `SUBSCRIPT_CASES`. The
    # cheapest regression anybody could have written for this: a helper with an
    # annotated parameter and one without, called on the SAME pointer, both
    # storing, both read back.
    #
    # Both helpers store `43` at index 1 of a `Pointer[Int64]` buffer. The
    # annotated one writes `b + 8`; the unannotated one used to write `b + 16`
    # and bounds-check index 1 against a count word that was never written, so
    # on the old tree this image exited 1 from a raw `exit(1)` syscall — one
    # whole ELEMENT out, and a plausible number rather than a fault on a
    # program that got that far. `7` and `3` as the two failure exits are
    # deliberate: the trap answers 1, which is the value most exit-status
    # assertions use, so an expectation of 1 here would have passed against the
    # very bug this row exists to hold down.
    #
    # Both readings are asserted twice — the exit status AND the printed line —
    # so a lowering that fabricated a plausible pair of numbers would have to
    # fabricate both, and `b[1]` in `main` is a declared-pointer READ, which is
    # the same decision the callee now inherits.
    ("both_arch_an_untyped_parameter_indexes_the_same_pointer_as_an_annotated_one",
     "def fill_ann(p: Pointer[Int64]) -> int:\n"
     "    p[1] = 42\n"
     "    return 0\n"
     "def fill_u(p) -> int:\n"
     "    p[1] = 43\n"
     "    return 0\n"
     "def main(n: Int) -> Int:\n"
     "    var b: Pointer[Int64] = malloc(32)\n"
     "    memset(b, 0, 32)\n"
     "    fill_ann(b)\n"
     "    var first = b[1]\n"
     "    fill_u(b)\n"
     "    var second = b[1]\n"
     "    printf(\"annotated=%d untyped=%d\", first, second)\n"
     "    if first == 42:\n"
     "        if second == 43:\n"
     "            return 7\n"
     "    return 3\n", 7, "annotated=42 untyped=43"),
    # The GUARD for the row above, and the reason it means something: the same
    # program with the SECOND helper's parameter annotated is the behaviour that
    # was always right. If the inherited convention were silently picking a
    # different answer than the declared one, this row would still pass while the
    # row above failed, and vice versa — so the two together are the assertion
    # "the annotation and the call sites agree", which is the whole claim.
    ("both_arch_the_same_two_helpers_with_both_parameters_annotated",
     "def fill_ann(p: Pointer[Int64]) -> int:\n"
     "    p[1] = 42\n"
     "    return 0\n"
     "def fill_u(p: Pointer[Int64]) -> int:\n"
     "    p[1] = 43\n"
     "    return 0\n"
     "def main(n: Int) -> Int:\n"
     "    var b: Pointer[Int64] = malloc(32)\n"
     "    memset(b, 0, 32)\n"
     "    fill_ann(b)\n"
     "    var first = b[1]\n"
     "    fill_u(b)\n"
     "    var second = b[1]\n"
     "    printf(\"annotated=%d untyped=%d\", first, second)\n"
     "    if first == 42:\n"
     "        if second == 43:\n"
     "            return 7\n"
     "    return 3\n", 7, "annotated=42 untyped=43"),
]

# `print`'s KEYWORDS, and the rule that a keyword is dispatched BY NAME before
# its value is looked at.
#
# The refusal this replaces asked "is this value a string literal?" FIRST and
# only then read the keyword, so every keyword whose value is not text was
# refused with a sentence about `sep` and `end` — the two that DO want text:
#
#     print(…, flush=True)
#       ->  print(flush=...) must be a string literal on the formal arm64 path
#           (got Constant): the separator and the line ending are baked into the
#           format string, which is built before the call is emitted
#
# which is false in every clause: `flush` is neither `sep` nor `end`, it is not
# baked into anything, and it is the commonest keyword in THIS repository's own
# source — nine of the sixty items `tools/formal_proof_breadth.py` measures land
# on it (`bugs/FORMAL_proof_coverage_census_2026-10-03.md` §0.2's largest
# `codegen-refused` family), every one of them the same `print(…, flush=True)`
# in a test's `check` helper.
#
# Both architectures, and the answered rows are in `both_arch_names` because the
# fix is an emitted `fflush` in each backend's own `_emit_print`: a case whose
# subject is two emitters writing the same call cannot be checked by running one
# of them. The two `refuse:` rows run on both by construction.
PRINT_KWARG_CASES = [
    # `flush=True` PRINTS, and the `fflush` after it is what makes the answer
    # observable rather than "it built": a formal image whose output is
    # captured through a pipe is FULLY buffered, so the flush is the difference
    # between the line reaching the reader at this statement and at exit.
    # `end=""` beside it is the other half of the same row — the keyword that
    # decides where the NEXT print starts — and it is here because a fix that
    # reordered the loop could easily have broken the one that was already right.
    # Both lines are in ONE program so no single-row special case can pass it.
    ("print_flush_true_emits_a_flush_and_still_prints",
     "def main(n):\n"
     "    print(\"one\", flush=True)\n"
     "    print(\"two\", end=\"|\", flush=True)\n"
     "    print(\"three\")\n"
     "    return 0\n", 0, "one\ntwo|three\n"),
    # `flush=False` is the DEFAULT, so it must cost nothing and change nothing —
    # the control for the row above, and the row that fails if a fix emits the
    # `fflush` on the strength of the keyword being present rather than its
    # value.
    ("print_flush_false_is_the_default_and_still_prints",
     "def main(n):\n"
     "    print(\"one\", flush=False)\n"
     "    print(\"two\", sep=\"-\", end=\"!\")\n"
     "    return 0\n", 0, "one\ntwo!"),
    # `flush` OF A NAME is refused, and the message says what is wanted rather
    # than what the separator is doing: the emitter has to write the `fflush`
    # at build time, so a value it cannot read is a flush this path cannot
    # express. Refusing is the right answer and saying "must be a string
    # literal" was not.
    ("print_flush_of_a_name_is_refused",
     "def main(n):\n"
     "    var flag = 1\n"
     "    print(\"x\", flush=flag)\n"
     "    return 0\n",
     "refuse:print(flush=...) must be True or False", None),
    # THE REGRESSION ROW for the reorder: `sep` is a keyword that really does
    # want a string literal, so it must still refuse one that is a name — with
    # the sentence about the separator, which is what the source has to change.
    # A fix that dispatched on the name and then accepted any value would pass
    # both rows above and silently print a pointer.
    ("print_sep_of_a_name_is_still_refused",
     "def main(n):\n"
     "    var sep = \"-\"\n"
     "    print(\"x\", sep=sep)\n"
     "    return 0\n",
     "refuse:print(sep=...) must be a string literal", None),
    # And the unknown keyword still says WHICH keywords exist, with `flush` in
    # the list now that it is one. A refusal that listed `sep, end, file` while
    # `flush` worked would send the next reader looking for a fourth spelling.
    ("print_unknown_keyword_names_the_four_it_has",
     "def main(n):\n"
     "    print(\"x\", bogus=1)\n"
     "    return 0\n",
     "refuse:no keyword argument 'bogus'", None),
]
ASSIGNED_TYPE_REFUSALS = [
    # THE SHAPE THAT WAS REFUSED AND IS NOW THE POSITIVE CASE, and it is here
    # rather than deleted because it is the one the sweep named.
    # `Outer` DECLARES NOTHING and its `__init__` assigns `self.in1 = Inner()`,
    # which is the only shape that says a field holds a nested frame without
    # declaring it — the assigned-type evidence source
    # (`model.struct_field_assigned_type`) with no other route.
    #
    # `Outer()` on a struct whose `__init__` takes no required parameter RUNS
    # the body, and a body that constructed a FRAMED struct was refused by name:
    # "its block is reserved per call SITE in the prologue of the function whose
    # body names the call, and a body inlined into a construction elsewhere has
    # no such site". Before that refusal, the store never ran and this program
    # built and answered 128 with 1, 2, 3 nowhere in it.
    #
    # The store is now DROPPED rather than refused, which is the same program:
    # `struct_nested_frame_fields` places an `Inner` frame in the object under
    # construction's OWN block (the evidence classifies `in1` as an `Inner`
    # precisely because the constructor assigns one), the `CONSTRUCTION_INIT`
    # lowering brings it up, and `Inner()` is `Inner`'s default value — so the
    # store wrote over a slot that already held that frame's address. What it
    # bought is the assigned-type evidence itself: with this shape refused,
    # `struct_init_field_types` had no end-to-end program left at all. 128 is
    # CPython's answer and is the only one that says the frame
    # the constructor promised is the frame `o.in1` reads.
    ("assigned_type_nested_frame_constructed_in_init",
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
    # The GUARD on the precedence rule, and the one most likely to be quietly
    # dropped: a DECLARATION still wins over a contradicting `__init__`
    # assignment.  `Outer` declares `var in1: Inner` and `__init__` assigns
    # `Other()`, which has the same three fields and therefore the same layout —
    # so honouring the assignment would build, run, and answer 123 where the
    # source says 128, with nothing refused and nothing printed.  It does not
    # build: the assignment is a construction of a framed struct in a
    # constructor's right-hand side, refused by name.  So the rule is now stated
    # as a refusal instead of as a silently-correct answer, which is the stronger
    # of the two claims and the one a reader can act on.
    # The two NEGATIVES of the drop above, and they are what make it a rule
    # rather than an omission. Both are stores into a field the layout PLACED,
    # and both are refused with the nested-slot refusal that has always named
    # them — a word over a frame is a word over a frame whether the store was
    # dropped or not, and the drop is only for the store that IS the placement.
    ("assigned_type_a_word_over_a_placed_nested_frame_is_refused",
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
     "    fn __init__(self):\n"
     "        self.in1 = 5\n"
     "\n"
     "    fn go(self) -> Int:\n"
     "        return self.in1.total() + self.tag\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    return o.go()\n",
     "refuse:whose receiver is a frame", None),
    # …and a construction of the right struct WITH an argument, which is the
    # same struct and a different value: `Inner(7)` fills `a` with 7 where the
    # placement brings the frame up at its defaults. Dropping it would answer
    # with the defaults, so it is refused instead.
    ("assigned_type_an_argument_over_a_placed_nested_frame_is_refused",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    fn __init__(self, x: Int):\n"
     "        self.a = x\n"
     "        self.b = 0\n"
     "\n"
     "    fn total(self) -> Int:\n"
     "        return self.a * 10 + self.b\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    var in1: Inner\n"
     "\n"
     "    fn __init__(self):\n"
     "        self.in1 = Inner(7)\n"
     "\n"
     "    fn go(self) -> Int:\n"
     "        return self.in1.total() + self.tag\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    o.tag = 5\n"
     "    return o.go()\n",
     "refuse:a construction of a struct whose receiver is a frame", None),
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
     "    return o.go()\n",
     "refuse:a construction of a struct whose receiver is a frame", None),
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
    # THE TUPLE TARGET, which used to be pinned HERE as a refusal and is now an
    # ANSWERED row — the second of the two in this group, and the pair is the
    # point: `assigned_type_nested_frame_constructed_in_init` above is the same
    # program with `self.in1 = Inner()`, this one is `self.tag, self.in1 = 5,
    # Inner()`, and the only difference is that the statement is a TUPLE store.
    #
    # Three fixes had to land before it could be answered, and this row is what
    # says all three happened:
    #
    #   * the store is PERFORMED.  A tuple store to a field was refused by name
    #     on x86-64 (until `_tuple_target_key` gave a `MemberExpr` element the
    #     same `_store_var` store a plain `self.x = v` uses) and
    #     ACCEPTED-AND-DROPPED on arm64, which is how the row's own predecessor
    #     built, ran and answered 123 where the source says 128;
    #   * a TYPE is read out of the same shape, so
    #     `struct_init_field_types` can see `self.in1` is an `Inner` from a
    #     TUPLE store and not only from a single one
    #     (`_init_statement_field_stores`, one table for both shapes);
    #   * and the store to the PLACED nested frame is DROPPED rather than
    #     performed, because `struct_nested_frame_fields` already put that
    #     frame in the object's own block and the `CONSTRUCTION_INIT` lowering
    #     brings it up — `Inner()` is `Inner`'s default value.  This is the
    #     reason the row is answered at all: without it the framed construction
    #     in the tuple's second position had no block reserved and refused.
    #
    # So the two answers are now 128 (the store to the struct the placement
    # made, dropped) and 123 is what a reader who LOST the tuple's other
    # element would get — `o.tag` is 5 here and the row is what says it is.
    # `assigned_type_a_declaration_still_wins` below is the guard on the
    # dropping half: the same store to a DIFFERENT struct of the same layout is
    # still refused, which is the narrowness that makes dropping it safe.
    ("tuple_store_of_a_placed_frame_in_a_constructor_body",
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
     # 128 is CPython's answer for this text (`self.tag` is 5 and
     # `o.in1.total()` is 123), so a store that is performed and one that is
     # dropped both have to land on it — which is why this row is the twin of
     # the one above rather than a variant of it.
     128, None),
    # The tuple target's four DECLINED shapes, one row each, because they have
    # four different reasons and "a local assignment" is the one answer none of
    # them can use.  `_init_statement_field_stores` is the one table that both
    # the `__init__` inline and the type evidence read, so these four are the
    # exact complement of what it accepts — a shape it accepts with the wrong
    # pairing would be a wrong ANSWER, and a shape it declines for a reason the
    # message does not name is a diagnostic that sends the reader to look for
    # the wrong thing.
    ("constr_refuse_a_starred_element_of_a_tuple_target",
     "struct S1:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __init__(self):\n"
     "        self.a, *rest = 1, 2, 3\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S1()\n"
     "    return s.a\n",
     "refuse:whose body this path does not inline: a starred target (`*rest`)",
     None),
    ("constr_refuse_a_nested_group_in_a_tuple_target",
     "struct S2:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "    def __init__(self):\n"
     "        (self.a, self.b), self.c = (1, 2), 3\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S2()\n"
     "    return s.a\n",
     "refuse:whose body this path does not inline: a tuple target whose group "
     "`((self.a, self.b), self.c)` holds a nested pair", None),
    ("constr_refuse_a_mixed_target_in_a_tuple_target",
     "struct S3:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __init__(self):\n"
     "        self.a, other.b = 1, 2\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S3()\n"
     "    return s.a\n",
     "refuse:whose body this path does not inline: a tuple target that mixes a "
     "field of the receiver with `other.b`", None),
    ("constr_refuse_a_tuple_target_of_the_wrong_arity",
     "struct S4:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "    def __init__(self):\n"
     "        self.a, self.b, self.c = 1, 2\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S4()\n"
     "    return s.a\n",
     "refuse:whose body this path does not inline: a tuple target of 3 fields "
     "assigned 2 value(s)", None),
    # The BLOB right-hand side: `self.a, self.b = f()` unpacks a runtime
    # container, and the count that says whether the pairing is even possible is
    # a value neither this table nor the store can read at a construction site.
    ("constr_refuse_a_tuple_target_unpacked_from_a_call",
     "struct S5:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __init__(self):\n"
     "        self.a, self.b = pair()\n"
     "\n"
     "def pair():\n"
     "    return [1, 2]\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S5()\n"
     "    return s.a\n",
     "refuse:whose body this path does not inline: a tuple target of 2 fields "
     "assigned from `pair(...)`", None),
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
     "    var inner: Inner\n"
     "\n"
     "    fn __init__(self):\n"
     "        self.tag = 0\n"
     "\n"
     "    fn go(self) -> Int:\n"
     "        return self.inner.total() + self.tag\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
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
     "    var inner: Inner\n"
     "\n"
     "    fn __init__(self):\n"
     "        self.tag = 0\n"
     "\n"
     "    fn go(self) -> Int:\n"
     "        return self.inner.total()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o1 = Outer()\n"
     "    var o2 = Outer()\n"
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
    # THE TUPLE FORM is a PROPERTY OF THE STATEMENT LOWERING rather than of
    # this evidence source, so the target shapes of it are checked against
    # CPython on BOTH backends in `test_formal_value_model.py`'s
    # `TUPLE_STORE_CASES` (which is where the x86-64 half of it was fixed: the
    # `MemberExpr` frame-slot target, and later the `SubscriptExpr` element
    # target).  These cases are written with separate assignments only so that
    # they mean the same thing on both architectures as the model reads them,
    # which is what the comment on
    # `init_assigned_scalar_fields_stay_plain` records.
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
    # (2) THE CONSTRUCTOR'S VALUE, not the class default's.  A zero-argument
    # `S()` on a struct whose `__init__` takes no required parameter RUNS the
    # body (`model.struct_construction_plan` reads `struct_init_shapes` before
    # the zero-argument case), so `limit` is 99 and not the class-level 7 — which
    # is what CPython says too, and this case used to assert the opposite because
    # premise (B2) then read "a zero-argument S() does not run __init__".
    #
    # It is here on its own because `pad` is the other half and the pair is the
    # whole rule: `pad` is assigned NOTHING by the constructor, so it keeps its
    # class-level default.  A lowering that either ran the body where it should
    # not, or failed to bring every other slot up first, changes the answer, and
    # 102 pins both halves: 10 if the class default won for `limit`, 99 if it
    # won for `pad`.
    ("init_assigned_class_default_still_governs_the_value",
     "class Cfg:\n"
     "    limit = 7\n"
     "    pad = 3\n"
     "\n"
     "    def __init__(self):\n"
     "        self.limit = 99\n"
     "\n"
     "    def get(self):\n"
     "        return self.limit + self.pad\n"
     "\n"
     "def main():\n"
     "    c = Cfg()\n"
     "    return c.get()\n", 102, None),
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


# ── an OVERLOADED NAME, and the struct layout each definition is compiled to ──
#
# `formal/build.py`'s `_fn_key` / `_by_name_holder` and the per-definition
# `_check_holder_agreements` loop. Mojo overloads are ordinary — `reversed` is
# declared eight times in `std/builtin/reversed.mojo`, with a different receiver
# type each time — and the frame analysis kept one table per NAME, so the first
# definition's candidate struct answered for all of them.
#
# The measured consequence was a refusal whose every clause is false about the
# program it was reported against: `reversed`'s `_DictEntryIter` overload reads
# `value.src`, `_DictEntryIter` declares `src`, and the message said
# "List has no field 'src'" because the `List` overload was declared first.
#
# The cases are in three groups because the fix has three parts, and only
# together do they hold it:
#
#   * POSITIVE (`OVERLOAD_*_CASES`): each definition's member read resolves
#     against its OWN layout. These build, EXECUTE, and are compared against
#     CPython on both architectures — the layouts differ here, so a case that
#     read the wrong one would print the other struct's field.
#   * `refuse_without:` (`OVERLOAD_*_REFUSALS`): the false-clause refusal is
#     gone. This is the anti-rot direction, and it is the assertion that would
#     have caught the original defect on its own.
#   * `refuse:` (`OVERLOAD_DISPATCH_REFUSALS`): keying the tables per definition
#     LIFTS a refusal, and a lifted refusal has to leave a correct image behind.
#     Both backends register functions in one table keyed by name
#     (`self._functions[f.name] = f`), so an overloaded name is ONE function in
#     the image and a call to it reaches whichever body was registered last.
#     So a call site that hands each definition a different struct is still a
#     refusal — now with the reason that is actually true, and checked against
#     EVERY definition rather than the one that happened to be first.
OVERLOAD_LAYOUT_CASES = [
    # THE CASE, and the one that measures the fix rather than restating it. Two
    # definitions of one name, each building a LOCAL struct under the SAME local
    # name and reading a field of it — and the two structs put that field at
    # DIFFERENT slots (`src` is 1 in `A` and 0 in `B`). Keyed per name, one
    # table held both layouts as candidates for `v.src` and the refusal was
    # "this name holds a frame address in more than one shape … A puts it at
    # slot 1; B puts it at slot 0", which is a true statement about the merged
    # table and a false one about the program: `v` is an `A` in one definition
    # and a `B` in the other, and never both. Keyed per definition each body
    # reads its own struct.
    #
    # Only the SECOND definition survives into the image (both backends key
    # their function table by name), so 33 is the answer — and the CPython
    # reference is written to compute what that body computes, which is what
    # `overload_of_plain_parameters_still_builds` explains at length.
    ("overload_each_definition_reads_its_own_layout",
     "struct A:\n"
     "    var pad: Int\n"
     "    var src: Int\n"
     "\n"
     "struct B:\n"
     "    var src: Int\n"
     "    var pad: Int\n"
     "\n"
     "def f(x: Int) -> Int:\n"
     "    var v = A(7, 42)\n"
     "    var r = v.src\n"
     "    return r\n"
     "\n"
     "def f[K: Copyable](x: Int) -> Int:\n"
     "    var v = B(33, 2)\n"
     "    var r = v.src\n"
     "    return r\n"
     "\n"
     "def main() -> Int:\n"
     "    printf(\"%d\", f(1))\n"
     "    return 0\n",
     "class A:\n"
     "    def __init__(self, pad, src):\n"
     "        self.pad = pad\n        self.src = src\n"
     "\n"
     "class B:\n"
     "    def __init__(self, src, pad):\n"
     "        self.src = src\n        self.pad = pad\n"
     "\n"
     "import sys\n"
     "def main():\n"
     "    # The SECOND definition is the one a name-keyed dispatch reaches, so\n"
     "    # the reference computes what that body computes: B(33, 2).src is 33,\n"
     "    # and reading A's slot instead would give B.pad, which is 2.\n"
     "    sys.stdout.write(\"%d\" % B(33, 2).src)\n"),
    # The same construct with the two definitions SWAPPED, which is what makes
    # the pair a test rather than a demonstration. A first-wins table answers 2
    # here (A's layout, `src` at slot 1, over a B frame holding `pad` there);
    # the reference says 42. One case cannot tell "reads its own layout" from
    # "always reads the first definition's layout", and that is the whole
    # question this fix turns on.
    ("overload_layout_resolves_per_definition_not_by_position",
     "struct A:\n"
     "    var pad: Int\n"
     "    var src: Int\n"
     "\n"
     "struct B:\n"
     "    var src: Int\n"
     "    var pad: Int\n"
     "\n"
     "def f[K: Copyable](x: Int) -> Int:\n"
     "    var v = B(33, 2)\n"
     "    var r = v.src\n"
     "    return r\n"
     "\n"
     "def f(x: Int) -> Int:\n"
     "    var v = A(7, 42)\n"
     "    var r = v.src\n"
     "    return r\n"
     "\n"
     "def main() -> Int:\n"
     "    printf(\"%d\", f(1))\n"
     "    return 0\n",
     "class A:\n"
     "    def __init__(self, pad, src):\n"
     "        self.pad = pad\n        self.src = src\n"
     "\n"
     "class B:\n"
     "    def __init__(self, src, pad):\n"
     "        self.src = src\n        self.pad = pad\n"
     "\n"
     "import sys\n"
     "def main():\n"
     "    # The LAST definition is the one name-keyed dispatch reaches: A(7, 42),\n"
     "    # whose `src` is 42.\n"
     "    sys.stdout.write(\"%d\" % A(7, 42).src)\n"),
    # The direction that is NOT a wrong answer: a name with several definitions
    # whose parameter is an ordinary value. This is the plain-Python shape
    # (`def f(x)` / `def f[K](x)`), it has no frame anywhere, and it must keep
    # building — the fix is about which LAYOUT a read resolves against, not
    # about refusing overloaded names.
    #
    # The CPython reference computes `7 * 3`, i.e. the SECOND body, and that is
    # deliberate rather than a fudge: this image has ONE `f`, so the answer a
    # reader gets is the second definition's. Asserting `7 * 2` would be
    # asserting an overload RESOLUTION this path does not implement — the same
    # limit `formal/build.py`\'s dylib rename comment names when it says a call
    # that wanted the second overload resolves to the first. The case is here to
    # hold the build; the comment is here so the next reader does not read the
    # number as a claim about Mojo.
    ("overload_of_plain_parameters_still_builds",
     "def twice(x: Int) -> Int:\n"
     "    return x * 2\n"
     "\n"
     "def twice[K: Copyable](x: Int) -> Int:\n"
     "    return x * 3\n"
     "\n"
     "def main() -> Int:\n"
     "    printf(\"%d\", twice(7))\n"
     "    return 0\n",
     "import sys\n"
     "def main():\n"
     "    sys.stdout.write(\"%d\" % (7 * 3))\n"),
]

OVERLOAD_REFUSALS = [
    # THE ORIGINAL DEFECT, as a `refuse_without:` case: the member read is
    # legal — `Seven` declares `src` — and the refusal that named a DIFFERENT
    # struct is what is forbidden. Before the fix this said "One has no field
    # 'src'" (or `List`, in `reversed`'s own spelling) and every clause of it
    # was false: `One` was never the receiver, and `Seven` does have `src`.
    ("overload_no_longer_reports_another_structs_layout",
     "struct One:\n"
     "    var n: Int\n"
     "\n"
     "struct Seven:\n"
     "    var pad: Int\n"
     "    var src: Int\n"
     "\n"
     "def go(a: One) -> Int:\n"
     "    return 0\n"
     "\n"
     "def go(a: Seven) -> Int:\n"
     "    var v = a.src\n"
     "    return v\n"
     "\n"
     "def main() -> Int:\n"
     "    var s = Seven(5, 42)\n"
     "    return go(s)\n",
     # `needle` is empty-safe: the assertion is that the forbidden clause is
     # gone, and `has no field 'src'` is what it must no longer say.
     "refuse_without::has no field 'src'", None),
]

OVERLOAD_DISPATCH_REFUSALS = [
    # The half of the fix that keeps a LIFTED refusal honest. Both definitions
    # are compiled, each against its own struct, and each call site hands one of
    # them the OTHER's struct. Both backends register one function per NAME
    # (`self._functions[f.name] = f`), so there is ONE `pick` in the image and
    # the call cannot say which body it reaches — which is a real limit of
    # name-based dispatch here, and the refusal names it.
    #
    # This case is the one that MEASURED the danger: with the tables keyed per
    # definition and the whole-image agreement pass skipping an ambiguous name,
    # this program BUILT, RAN, and printed 7 and 33 where the source says 42 and
    # 33 — a wrong answer on the construct this suite exists to keep honest. It
    # is here so that removing either half of the fix (the per-definition keying
    # OR the per-definition agreement check) is a red test rather than a silent
    # wrong number.
    ("overload_called_with_each_definitions_struct_is_refused",
     "struct A:\n"
     "    var pad: Int\n"
     "    var src: Int\n"
     "\n"
     "struct B:\n"
     "    var src: Int\n"
     "    var pad: Int\n"
     "\n"
     "def pick(ref value: A) -> Int:\n"
     "    var v = value.src\n"
     "    return v\n"
     "\n"
     "def pick[K: Copyable](ref value: B) -> Int:\n"
     "    var w = value.src\n"
     "    return w\n"
     "\n"
     "def main() -> Int:\n"
     "    var a = A(7, 42)\n"
     "    var b = B(33, 2)\n"
     "    printf(\"%d\", pick(a))\n"
     "    printf(\" %d\", pick(b))\n"
     "    return 0\n",
     "refuse:declares 'value' as A", None),
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
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    var inner: Inner\n"
     "\n"
     "    fn __init__(self):\n"
     "        self.tag = 0\n"
     "\n"
     "    fn go(self) -> Int:\n"
     "        return len(self.inner)\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
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
    # `FORMAL_field_set_method_name_and_kwarg_blind_spot` — read that
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
    # THE SAME FALSE CLAIM WITH TWO CANDIDATES, which is the shape the
    # single-candidate fix above could not reach and the one that actually
    # occurs. `model.struct_frame_slot_candidates` reports "these candidates do
    # not agree on a slot" and "no candidate has one" with the SAME
    # `(None, (True, rows))`, so `model.member_read_without_a_field`'s
    # single-candidate branch handled only the second and everything else fell
    # into the disagreement sentence.
    #
    # Measured on `std/io/io.mojo`, where the message printed the rows that
    # contradict it: "…_FlushingWriteBuffer has no such field; _FixedWriteBuffer
    # has no such field" and then "the shapes do not agree on where
    # 'unsafe_mut_cast' lives". They agree perfectly — neither has it, and it is
    # a method of `Pointer` — so the reader was sent to two structs' layouts
    # instead of to the receiver's type.
    #
    # TWO candidates with NO field between them, so the forbidden clause is the
    # one that says they disagree. `A puts it at slot 0; B has no such field` is
    # the REAL disagreement (one has it, one does not) and is the case the
    # surviving branch still has to keep saying — which is what the next case
    # pins, so this one cannot be satisfied by deleting the disagreement
    # sentence altogether.
    #
    # The needle is the corrected sentence, and `refuse_without:` requires both
    # halves: the forbidden wording gone AND the true wording present, so
    # dropping the message passes neither. (`|` separates them, which this
    # runner reads as ALTERNATIVES for the needle and as a LIST for the
    # forbidden substrings — so they are two cases, not one.)
    ("no_candidate_having_a_field_is_not_a_layout_disagreement",
     "struct A:\n"
     "    var pad: Int\n"
     "    var other: Int\n"
     "\n"
     "struct B:\n"
     "    var pad2: Int\n"
     "    var other2: Int\n"
     "\n"
     "def go(n: Int) -> Int:\n"
     "    var w = A(1, 2)\n"
     "    if n > 0:\n"
     "        w = B(3, 4)\n"
     "    var v = w.nosuch\n"
     "    return v\n",
     "refuse_without:NO candidate has field 'nosuch':the shapes do not agree",
     None),
    # …and the real disagreement, in the same program shape, so the case above
    # cannot be satisfied by removing the disagreement sentence altogether. `A`
    # has `src` and `B` does not, which IS a disagreement about where the field
    # lives, and the message must still say so.
    ("a_real_layout_disagreement_still_says_so",
     "struct A:\n"
     "    var src: Int\n"
     "    var pad: Int\n"
     "\n"
     "struct B:\n"
     "    var other: Int\n"
     "    var pad2: Int\n"
     "\n"
     "def go(n: Int) -> Int:\n"
     "    var w = A(1, 2)\n"
     "    if n > 0:\n"
     "        w = B(3, 4)\n"
     "    var v = w.src\n"
     "    return v\n",
     "refuse:the shapes do not agree on where 'src' lives", None),
    # THE SAME CORRECTION ONE LEVEL IN, at the only other site that has to
    # choose between the two shapes. A member read out of a NESTED frame
    # (`self.strong.fetch_add`, `std/memory/arc_pointer.mojo`) had no method
    # check, so a name that is a METHOD of the nested struct was reported as a
    # field it does not have — the same false diagnosis as the case above, one
    # level down, and the reason it is a separate case rather than a note.
    #
    # `helper` is a method of `Inner` and `value` is its field, so the two are
    # distinguishable in the source: `self.strong.helper` is a bound method and
    # `self.strong.value` is a word, and only the second has a slot.
    ("a_nested_frames_method_is_not_reported_as_a_missing_field",
     "struct Inner:\n"
     "    var value: Int\n"
     "    var other: Int\n"
     "\n"
     "    def helper(mut self) -> Int:\n"
     "        return 3\n"
     "\n"
     "struct Outer:\n"
     "    var strong: Inner\n"
     "    var pad: Int\n"
     "\n"
     "    def bump(mut self) -> Int:\n"
     "        var v = self.strong.helper\n"
     "        return v\n"
     "\n"
     "def main() -> Int:\n"
     "    var o = Outer(Inner(7, 8), 0)\n"
     "    printf(\"%d\", o.bump())\n"
     "    return 0\n",
     "refuse:is a METHOD of the nested Inner frame rather than one of its "
     "fields", None),
    # ── a `with` over a RESOURCE (`with open(…) as f:`) ───────────────────
    #
    # The three cases below are the ones `model.resource_context_manager_exit`
    # made buildable, and they are here rather than in the `with_*` group above
    # because that group's subject is the PROTOCOL — `__enter__` binds the alias
    # and `__exit__` runs on the way out, proved with a struct whose two dunders
    # print. A resource has no methods to print from: `__enter__` IS the
    # descriptor and `__exit__` is `close(2)`, so the same three properties have
    # to be observed through the DESCRIPTOR, and that is a different assertion
    # rather than a fourth spelling of the first one.
    #
    # `BOTH_ARCH_CASES` rather than `CASES` because the lowering is shared
    # (`formal/build.py::_one_with_item`) but the two `close(2)` and `write(2)`
    # calls are each emitted by their own backend, and "it worked on the host's
    # architecture" would leave the other one unmeasured.
    #
    # 1. The ALIAS is a live descriptor. `f.write(s)` lowers to
    #    `write(fd, s, strlen(s))` and its VALUE is what the C library returned,
    #    so `5` is the kernel's answer for five bytes and not a constant this
    #    file wrote. A lowering that bound the alias to anything else would
    #    refuse here rather than print a wrong number (`VALUE_METHOD_RECEIVERS`
    #    is a guard on where the word was bound), which is the honest failure:
    #    the case cannot pass by accident.
    ("with_open_alias_is_a_live_descriptor",
     "def main():\n"
     "    with open(\"/tmp/with_open_alias_is_a_live_descriptor.txt\", \"w\") "
     "as f:\n"
     "        k = f.write(\"hello\")\n"
     "        printf(\"wrote=%d@@\", k)\n"
     "    return 0\n",
     0, "wrote=5@@"),
    # 2. `__exit__` RAN, on the fall-through. The observation is the descriptor
    #    NUMBER rather than a flag: `open(2)` returns the lowest free
    #    descriptor, so if the `with` closed it the next `open` gets the same
    #    one and `g - f` is 0. That is number-independent — the case does not
    #    hard-code 3 — and it cannot be satisfied by a lowering that only
    #    dropped the call, because then `g` would be the next number up and the
    #    delta would be 1.
    #
    #    `delta=1` is what a `with` lowered as "evaluate, bind, run the body"
    #    prints, and that is the whole failure this protocol exists to remove:
    #    the program would exit 0 having leaked every descriptor it opened.
    ("with_open_closes_the_descriptor_on_the_fall_through",
     "def main():\n"
     "    with open(\"/tmp/with_open_fall_through_a.txt\", \"w\") as f:\n"
     "        printf(\"in=%d@@\", f)\n"
     "        f.write(\"hello\")\n"
     "    g = open(\"/tmp/with_open_fall_through_b.txt\", \"w\")\n"
     "    printf(\"delta=%d@@\", g - f)\n"
     "    g.close()\n"
     "    return 0\n",
     0, "delta=0@@"),
        # 3. …and on an EARLY `return` out of the body, which is the edge a cleanup
    #    written after the body gets wrong and the reason the whole rewrite is a
    #    `try`/`finally`. Same observation, one edge deeper, and the RETURN
    #    VALUE is the descriptor: `return fd` from inside the block has to both
    #    come back to the caller and leave the descriptor free, so the pending
    #    return cannot be flushed at the cost of the `finally` or the other way
    #    round. `fell=0` is the fall-through arm of the same function, and it is
    #    in the expected output because 0 is not a descriptor number: a `with`
    #    whose exit edge returned early would print it here instead.
    ("with_open_closes_the_descriptor_on_an_early_return",
     "def early_fd(n):\n"
     "    var fd = 0\n"
     "    with open(\"/tmp/with_open_early_return.txt\", \"w\") as f:\n"
     "        fd = f\n"
     "        f.write(\"hello\")\n"
     "        if n > 0:\n"
     "            return fd\n"
     "    return 0\n"
     "\n"
     "def main():\n"
     "    a = early_fd(1)\n"
     "    g = open(\"/tmp/with_open_after_early.txt\", \"w\")\n"
     "    printf(\"delta=%d@@\", g - a)\n"
     "    printf(\"fell=%d@@\", early_fd(0))\n"
     "    g.close()\n"
     "    return 0\n",
     0, "delta=0@@fell=0@@"),
]
# ── a ONE-WORD struct held in a HOLDER'S FIELD ──────────────────────────────
#
# The value `S()` in the construction group below is a WORD. When `S` has more
# than one field the word is the ADDRESS of its frame; when it has exactly one,
# the word IS that field. Both spellings of a struct value have to lower, and the
# second reached a holder's FIELD through a chain the frame analysis had no
# lowering for.
#
# `o.in1.a`, where `Outer.in1` is declared `Inner` and `Inner` has one field:
# the slot for `o.in1` holds `Inner`'s value, and `Inner`'s value is its one
# field, so the chain and `o.in1` are the SAME word and one load answers both.
# That was refused with `model.field_access_refusal`'s `holder=True` sentence —
# "the frame analysis and the emitter disagree about this function's receivers
# — a compiler bug rather than a limit of the path" — and neither half was true:
# the analysis was right that there is no nested frame, and the emitter was
# right that the chain had no slot, because the load had not been placed.
#
# Filed as "the two passes disagree about `struct_is_framed`", with an offer to
# stop the demotion that produced the one-field struct as its semantically honest
# repair; the filing was `FORMAL_class_level_default_flips_a_nested_frames_width`
# and it is deleted, its defect fixed. The trigger is not the demotion: the same
# refusal, byte-identical, comes out of a `struct Inner` that declares exactly ONE
# field and no class-level default at all — which is why the second case below is
# that spelling and not the defaulted one. What was missing was the lowering, for
# every one-field nested field rather than for the defaulted ones.
ONE_WORD_NESTED_CASES = [
    # THE DOC'S REPRODUCER, verbatim, and 8 is CPython's answer: `Inner.add(2)`
    # is 1 + 2 and `self.tag` is 5. It reads through a nested METHOD CALL, so it
    # needs both halves of the lowering — the chain becomes the slot, and the
    # slot becomes the receiver.
    ("one_word_nested_demoted_width_method_call",
     "struct Inner:\n"
     "    var a: Int = 0\n"
     "    var b: Int = 0\n"
     "    var c: Int = 0\n"
     "\n"
     "    fn add(self, v: Int) -> Int:\n"
     "        return self.a + v\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    var in1: Inner\n"
     "\n"
     "    fn go(self, v: Int) -> Int:\n"
     "        return self.in1.add(v) + self.tag\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    o.tag = 5\n"
     "    o.in1.a = 1\n"
     "    return o.go(2)\n", 8, None),
    # The SAME lowering with NO class-level default anywhere — `Inner` declares
    # one field and the others do not exist. This is the case that decides the
    # doc's option (A) against its option (B): if the demotion were what flipped
    # the width, this one would build and the defaulted one would not. Both were
    # refused, identically, so there is no demotion to un-do and no layout the
    # fix could be cementing.
    ("one_word_nested_declared_single_field_read",
     "struct Inner:\n"
     "    var a: Int\n"
     "\n"
     "    fn add(self, v: Int) -> Int:\n"
     "        return self.a + v\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    var in1: Inner\n"
     "\n"
     "    fn go(self, v: Int) -> Int:\n"
     "        return self.in1.a + self.tag\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    o.tag = 5\n"
     "    o.in1.a = 1\n"
     "    return o.go(2)\n", 6, None),
    # …and the WRITE half, read back on the CALLER's own side, because the two
    # reach different code: `o.in1.a = 1` is a store through the chain and
    # `o.in1.a + o.tag` is a load through it. A rewrite that only handled the
    # read would leave the store writing a word nothing reads back, and this
    # program answers 106 rather than 6 only if the store landed.
    ("one_word_nested_write_is_read_back",
     "struct Inner:\n"
     "    var a: Int\n"
     "\n"
     "    fn add(self, v: Int) -> Int:\n"
     "        return self.a + v\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    var in1: Inner\n"
     "\n"
     "    fn go(self, v: Int) -> Int:\n"
     "        return self.in1.a + self.tag\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Outer()\n"
     "    o.tag = 5\n"
     "    o.in1.a = 1\n"
     "    return o.go(2) + o.in1.a * 100\n",
     106, None),
    # TWO objects, which is what makes the placement claim load-bearing. A
    # rewrite that handed one object's slot key for the other's chain would read
    # one object's field out of the other's storage, and the two different `tag`
    # values (5 and 20) and two different `in1.a` values (1 and 4) make it
    # distinguishable: `o1.go(2)` is 8 and `o2.go(3)` is 27, so 107 — under 256,
    # because the exit status is a byte and 278 truncated to 22, which would
    # stop distinguishing anything. Every way of reading one object through the
    # other lands elsewhere: both through `o1` gives 89, both through `o2` 41.
    ("one_word_nested_two_objects_do_not_alias",
     "struct Inner:\n"
     "    var a: Int\n"
     "\n"
     "    fn add(self, v: Int) -> Int:\n"
     "        return self.a + v\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    var in1: Inner\n"
     "\n"
     "    fn go(self, v: Int) -> Int:\n"
     "        return self.in1.add(v) + self.tag\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o1 = Outer()\n"
     "    var o2 = Outer()\n"
     "    o1.tag = 5\n"
     "    o1.in1.a = 1\n"
     "    o2.tag = 20\n"
     "    o2.in1.a = 4\n"
     "    return o1.go(2) * 10 + o2.go(3)\n",
     107, None),
    # The four below are the chain that is the LOCAL'S OWN, where the base is a
    # ONE-FIELD struct rather than a frame — so there is no frame slot and no
    # `field_type_one_word_struct`; the whole chain is `formal/build.py`'s
    # `_one_word_field_map` and `_rewrite_self_fields`, and the base is `var a =
    # Root()` rather than a frame holder. Every one of these was refused before
    # `_one_word_sole_field_chain` existed, with a message naming a name the
    # source never wrote: the rewrite collapsed the FIRST level of `a.x.w.v`
    # and left `a.v` standing, which is in no register home and no frame slot.
    #
    # 195 is 451 & 255 and the truncation is deliberate: `a.get()` is 41 and
    # `a.x.w.v` is 41, and 451 does not fit an exit status, so the case would
    # be 195 on both architectures and under CPython's own byte semantics.
    ("one_word_nested_local_chain_is_one_local",
     "struct Leaf:\n"
     "    var v: Int\n"
     "struct Mid:\n"
     "    var w: Leaf\n"
     "struct Root:\n"
     "    var x: Mid\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.x.w.v\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Root()\n"
     "    a.x.w.v = 41\n"
     "    return a.get() + a.x.w.v * 10\n", 195, None),
    # TWO objects, which is what makes the chain's claim a claim about storage
    # and not about a name. `a.get()` is 4 and `b.get()` is 30, so 304 & 255 is
    # 48; a rewrite that shared one word between them would return 4 + 4*10.
    ("one_word_nested_local_chain_two_objects_do_not_alias",
     "struct Leaf:\n"
     "    var v: Int\n"
     "struct Mid:\n"
     "    var w: Leaf\n"
     "struct Root:\n"
     "    var x: Mid\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.x.w.v\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Root()\n"
     "    var b = Root()\n"
     "    a.x.w.v = 4\n"
     "    b.x.w.v = 30\n"
     "    return a.get() + b.get() * 10\n", 48, None),
    # The WRITE half alone, because a rewrite that only handled the read would
    # build this program and return 0: the chain is a store target here and
    # nothing ever reads the field back, so a dropped store is invisible.
    ("one_word_nested_local_chain_writes_and_reads_back",
     "struct Leaf:\n"
     "    var v: Int\n"
     "struct Mid:\n"
     "    var w: Leaf\n"
     "struct Root:\n"
     "    var x: Mid\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Root()\n"
     "    a.x.w.v = 7\n"
     "    return a.x.w.v\n", 7, None),
    # The same word spelled with the SAME NAME at every level, which is what
    # separates matching a chain from matching a count: `a.q.q.r` has three
    # field reads and the chain is `("q", "q")`, so a rewrite that compared
    # lengths would leave the third one standing. It is legal Mojo and it is
    # the shape a length-based version gets wrong.
    ("one_word_nested_local_chain_repeats_its_field_name",
     "struct Leaf:\n"
     "    var r: Int\n"
     "struct Mid:\n"
     "    var q: Leaf\n"
     "struct Root:\n"
     "    var q: Mid\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Root()\n"
     "    a.q.q.r = 7\n"
     "    return a.q.q.r\n", 7, None),
    # The BOUNDARY, and the case that says the chain is a chain and not a
    # length: `Pair` declares TWO fields, so `x.p` is a FRAME address and
    # `x.p.a` is a load at a frame base. Collapsing it to `x` would read `x`'s
    # own word as an `a`, and 34 is 3*10 + 4 — the answer only if the chain
    # stopped exactly where the identity does.
    ("one_word_nested_chain_stops_at_a_framed_field",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "struct Box:\n"
     "    var p: Pair\n"
     "\n"
     "def mk() -> Pair:\n"
     "    var q = Pair()\n"
     "    q.a = 3\n"
     "    q.b = 4\n"
     "    return q\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = Box()\n"
     "    x.p = mk()\n"
     "    return x.p.a * 10 + x.p.b\n", 34, None),
    # ── the identity READ AS A CALL'S RECEIVER, which is a different program ──
    #
    # Every case above reads a one-word chain, and the rewrite is right for a
    # read: `b.inner` and `b` are one word and reading either gives the field.
    # Reading it as a CALL'S RECEIVER is not the same thing, because the rewrite
    # keeps the METHOD NAME and drops the STRUCT the name belongs to.
    # `std/builtin/builtin_slice.mojo` is the source of the shape and the
    # measurement: `StridedSlice.write_to`'s whole body is
    # `self._inner.write_to(writer)`, where `write_to` is declared by `Slice`,
    # so after the identity the callee reads `self.write_to(writer)` — a call of
    # `StridedSlice.write_to` on `self`, which is that same function, forever.
    # Three refusals come out of it depending on which pass notices, and the one
    # the file itself hit was a FALSE one ("`self.write_to` is not a field of
    # StridedSlice … in Python this expression is the bound method", about an
    # expression that is a CALL and was Slice's).
    #
    # So these assert the LIFT: `self._inner.add(v)` is `Slice.add(self, v)`,
    # because `_inner`'s DECLARED type names the struct and that is the only
    # thing in hand that can. 10 is `3 + 7`, and it is the number a wrong
    # dispatch could not produce — the infinite recursion has no exit status.
    ("one_word_field_method_call_reaches_the_fields_own_method",
     "struct Slice:\n"
     "    var start: Int\n"
     "\n"
     "    def add(self, v: Int) -> Int:\n"
     "        return self.start + v\n"
     "\n"
     "struct StridedSlice:\n"
     "    var _inner: Slice\n"
     "\n"
     "    def emit(self, v: Int) -> Int:\n"
     "        return self._inner.add(v)\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var inner = Slice()\n"
     "    inner.start = 3\n"
     "    var ss = StridedSlice()\n"
     "    ss._inner = inner\n"
     "    return ss.emit(7)\n", 10, None),
    # The chain is a chain, so the receiver can be TWO fields deep: `Root.x` is
    # `Mid`, `Mid.w` is `Leaf`, and `self.x.w.leaf()` is `Leaf.leaf(self)` by the
    # same argument one level up. A lift that matched one level would leave
    # `self.x.leaf()` for the identity to collapse into `self.leaf()`, which is
    # `Root.leaf` — a symbol this image does not define.
    ("one_word_field_method_call_through_a_two_level_chain",
     "struct Leaf:\n"
     "    var v: Int\n"
     "\n"
     "    def scaled(self, k: Int) -> Int:\n"
     "        return self.v * k\n"
     "\n"
     "struct Mid:\n"
     "    var w: Leaf\n"
     "\n"
     "struct Root:\n"
     "    var x: Mid\n"
     "\n"
     "    def get(self, k: Int) -> Int:\n"
     "        return self.x.w.scaled(k)\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Root()\n"
     "    a.x.w.v = 6\n"
     "    return a.get(5)\n", 30, None),
    # The same lift with a LOCAL as the root rather than a method's `self`,
    # because `_one_word_field_map` records both and the lift has to ask the
    # same question of both. `b` is one word from `Box()`, so `b.inner.add(7)`
    # becomes `Slice.add(b, 7)` and `self.start` inside it reads `b`.
    ("one_word_field_method_call_through_a_local_root",
     "struct Slice:\n"
     "    var start: Int\n"
     "\n"
     "    def add(self, v: Int) -> Int:\n"
     "        return self.start + v\n"
     "\n"
     "struct Box:\n"
     "    var inner: Slice\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Box()\n"
     "    b.inner.start = 40\n"
     "    return b.inner.add(2)\n", 42, None),
]

# The BOUNDARY of the lift above: a field whose declared type is NOT a struct of
# this image has no method table, so the call cannot be lifted and must still be
# refused — by the value-receiver sentence, which is true of it. Without this
# case the lift could widen to any `recv.f.m(x)` and every case above would
# still pass.
ONE_WORD_FIELD_METHOD_REFUSALS = [
    ("one_word_field_method_call_on_a_scalar_field_is_still_refused",
     "struct Box:\n"
     "    var n: Int\n"
     "    def go(self) -> Int:\n"
     "        return self.n.add(2)\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Box()\n"
     "    b.n = 3\n"
     "    return b.go()\n",
     "refuse:is a method call on a value", None),
    # The same boundary one step along, and it is the boundary of
    # `model.one_word_field_struct`'s PARAMETER row rather than of the
    # declared-type row above: the field has no class-body declaration at all,
    # only `__init__`'s annotated parameter, and the annotation names a type
    # that is not a struct of this image — so there is no word to continue the
    # chain with and the call stays refused.  A parameter row that ignored
    # whether the annotation names a struct of this module would read `Int` as
    # a chain step and lift `self._inner.total()` onto `self`, which is the
    # wrong receiver for a total.
    ("one_word_field_assigned_from_a_parameter_of_an_unknown_type_is_still_refused",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __init__(out self, a: Int, b: Int):\n"
     "        self.a = a\n"
     "        self.b = b\n"
     "\n"
     "    def total(self) -> Int:\n"
     "        return self.a + self.b\n"
     "\n"
     "struct Box:\n"
     "    def __init__(out self, inner: Int):\n"
     "        self._inner = inner\n"
     "\n"
     "    def go(self) -> Int:\n"
     "        return self._inner.total()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Box(3)\n"
     "    return b.go()\n",
     "refuse:is a method call on a value", None),
]

# ── a CONDITIONAL ARM: `elif` and `comptime if`, and a walk that stops at them ──
#
# Both of these are ONE defect seen twice, and it is a defect in the WALKS rather
# than in either construct. `IfStmt.elifs` is a list of TUPLES — the only
# container in the tree that is not a list — so a walk that recurses on
# `isinstance(node, list)` descends every `if` body and every `else` and stops
# dead at the first `elif`, while `model.iter_nodes` (which every LATE check
# uses) walks all of them. And a `comptime if` is a distinct NODE
# (`fire_compiler.ComptimeIfStmt`), so a walk that knows `IfStmt` does not know
# it at all.
#
# The consequence is the same both times and it is a REFUSAL THAT MISDESCRIBES
# ITS OWN PROGRAM, because the reader is a check and the rewriter is a rewrite:
#
#   * the `elif` case — `formal/build.py`'s `_rewrite_method_calls` misses the
#     arm, so a method call inside it is never lifted, so it reaches
#     `check_value_position_method_reads` as `self._next` and the program is
#     refused with "self._next is not a field of Rng … Call it
#     (`self._next(...)`), which is a receiver and a call and lowers" — about a
#     call that HAS its parentheses. Measured: `std/testing/prop/random.mojo`'s
#     `Rng.rand_scalar`, arm64 and x86-64 identically.
#   * the `comptime if` case — `mojo/middle/boundnames.py`'s `_lbn_walk` misses
#     the node, so a name bound in the branch is not a local, so it gets no
#     register and the program is refused with "'a' has no home: the register
#     allocator collected no home for it, so the emitter and the allocation walk
#     disagree" — which blames a disagreement between two passes instead of
#     naming the one walk both of them should have shared.
#
# Both cases here are the two shapes with and without the offending arm, because
# a case that only has the arm cannot tell a fix from a rewrite that stopped
# emitting the branch: `a` alone and `a` + `b` are different numbers, and the
# `comptime` pair differs by which arm the specialization takes.
#
# The four cases at the end of the group are the four remaining REWRITES that
# stopped at an arm, and they are here for the reason the first two are: each is
# paired with, or distinguished from, the answer the same program gives with the
# arm turned into an `else`.
CONDITIONAL_ARM_CASES = [
    # 9 = the `elif` arm's answer (diff 6 + lo 3). The `if` twin is 0, so a
    # rewrite that dropped the arm entirely would be caught by the exit status
    # rather than passing quietly.
    ("method_call_in_an_elif_arm_is_lifted",
     "struct Rng:\n"
     "    def _next(self, max: Int) -> Int:\n"
     "        return max\n"
     "\n"
     "    def rand_scalar[T: Int](self, lo: Int, hi: Int) -> Int:\n"
     "        if lo > hi:\n"
     "            return 0\n"
     "        elif T == 2:\n"
     "            var diff = hi - lo if hi > lo else lo - hi\n"
     "            var uint64 = self._next(diff)\n"
     "            return uint64 + lo\n"
     "        else:\n"
     "            return hi\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var r = Rng()\n"
     "    return r.rand_scalar[2](3, 9)\n", 9, None),
    ("method_call_in_an_if_body_is_lifted",
     "struct Rng:\n"
     "    def _next(self, max: Int) -> Int:\n"
     "        return max\n"
     "\n"
     "    def rand_scalar[T: Int](self, lo: Int, hi: Int) -> Int:\n"
     "        if T == 2:\n"
     "            var diff = hi - lo if hi > lo else lo - hi\n"
     "            var uint64 = self._next(diff)\n"
     "            return uint64 + lo\n"
     "        return hi\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var r = Rng()\n"
     "    return r.rand_scalar[2](3, 9)\n", 9, None),
    # 5 is the `else` arm (`k + 2` with k = 3), so this case is the one that
    # proves the arm was CHOSEN and not merely compiled: the `then` arm's answer
    # is 4.
    ("a_local_in_a_comptime_if_body_has_a_home",
     "def pick[T: Int](k: Int) -> Int:\n"
     "    comptime if T == 1:\n"
     "        var a = k + 1\n"
     "        return a\n"
     "    else:\n"
     "        var b = k + 2\n"
     "        return b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return pick[2](3)\n", 5, None),
    # The same with an `elif` between the two arms, which is the shape
    # `random.mojo`'s `rand_scalar` actually has (`comptime if … elif
    # dtype.is_integral():`). 45 = the elif arm (15 + 25 + 5); the `then` arm
    # answers 16 and the `else` 15, so all three arms are distinguishable and a
    # rewrite that dropped the elif would not pass as the then arm.
    ("a_local_in_a_comptime_elif_arm_has_a_home",
     "def pick[T: Int](k: Int, lo: Int, hi: Int) -> Int:\n"
     "    comptime if T == 1:\n"
     "        var a = k + 1\n"
     "        return a\n"
     "    elif T == 2:\n"
     "        var diff = hi - lo\n"
     "        var uint64 = k\n"
     "        return uint64 + diff + lo\n"
     "    else:\n"
     "        return k\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return pick[2](15, 5, 30)\n", 45, None),
    # ── the three remaining REWRITES that stopped at an `elif` ──
    #
    # `bugs/FORMAL_elif_arms_and_random_mojo_remainder.md`, Part 1. Four walks
    # recursed on `isinstance(node, list)` and therefore missed every `elif` arm;
    # two of them had been moved onto `model.rewrite_tree` already, and these are
    # the other two. What the arm costs is DIFFERENT for each, which is why they
    # are four cases and not one:
    #
    #   * a one-word struct's own field read (`self.n`) — a REFUSAL, and one this
    #     file has seen before in a different walk: `model.field_access_refusal`
    #     says it "has no way to say what 'self' holds", and in a method of a
    #     one-field struct it is exactly the one thing the walk knows.
    ("one_word_field_read_in_an_elif_arm_is_still_the_receiver",
     "struct Cell:\n"
     "    var n: Int\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        if self.n > 100:\n"
     "            return 1\n"
     "        elif self.n > 0:\n"
     "            return 2\n"
     "        else:\n"
     "            return 3\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = Cell()\n"
     "    c.n = 5\n"
     "    return c.get()\n", 2, None),
    # …and its `if`/`else` twin, which was already right: 2 here and 2 there, so
    # the case above cannot pass by the walk being deleted rather than repaired.
    ("one_word_field_read_in_an_if_arm_is_still_the_receiver",
     "struct Cell:\n"
     "    var n: Int\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        if self.n > 0:\n"
     "            return 2\n"
     "        else:\n"
     "            return 3\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = Cell()\n"
     "    c.n = 5\n"
     "    return c.get()\n", 2, None),
    # The one-field MUTATOR's write-back, which is the one that was a WRONG
    # ANSWER rather than a refusal: `c.bump(5)` in an `elif` arm never became
    # `c = Cell_bump(c, 5)`, so the call was computed and the value the callee
    # handed back was discarded — which is the defect this pass's own docstring
    # records as measured ("the program built, ran, and printed the value the
    # caller had"). 15 is 10 + 5; the unfixed image exits 10, so this is a row
    # that could not pass by accident. All three arms store, so a rewrite that
    # dropped the `elif` outright would answer 1 and fail rather than pass.
    ("one_field_mutator_in_an_elif_arm_stores_back",
     "struct Cell:\n"
     "    var n: Int\n"
     "\n"
     "    def bump(mut self, by: Int):\n"
     "        self.n += by\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.n\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = Cell()\n"
     "    c.n = 10\n"
     "    if n > 100:\n"
     "        c.bump(100)\n"
     "    elif n > 0:\n"
     "        c.bump(5)\n"
     "    else:\n"
     "        c.bump(1)\n"
     "    return c.get()\n", 15, None),
    # The frame-slot half of the same identity (`o.in1.a` → `o.in1`). This one is
    # a CONTROL and it is here because the other three were all live defects: it
    # answers 2 before the change as well as after, because `_frame_receivers`
    # runs after `_fold_target_queries`, which normalizes every `elif` pair into
    # a list as a side effect of its own tuple handling. So the walk reached the
    # arm by an accident of ANOTHER pass's traversal. It is pinned so the
    # conversion of that walk onto `model.rewrite_tree` cannot be the thing that
    # changes it, and so the accident is visible to the next reader rather than
    # being rediscovered as a mystery.
    ("nested_one_word_chain_as_an_elif_condition",
     "struct Inner:\n"
     "    var a: Int\n"
     "\n"
     "struct Outer:\n"
     "    var in1: Inner\n"
     "    var pad: Int\n"
     "\n"
     "def f(o: Outer, x: Int) -> Int:\n"
     "    if x == 100:\n"
     "        return 1\n"
     "    elif o.in1.a:\n"
     "        return 2\n"
     "    else:\n"
     "        return 3\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return f(Outer(Inner(5), 0), 0)\n", 2, None),
]

# ── a DECLARED frame parameter handed a frame-RETURNING call ────────────────
#
# `_frame_valued_calls`'s own docstring says a parameter declared as a framed
# struct is corroborated by "a construction, or a frame-returning call", and
# lists `formal/types.py`'s `mask_of(IntType(w, False))` as the false refusal
# that fixing it was worth. The returned-frame half of that was DEAD: the check
# handed the identity-keyed `returns_frame` to `model.frame_returning_predicate`,
# whose contract is `(callee_name, bound_name)`, so every lookup of a name in a
# dict filed under `id(fn)` missed and the callee read as returning nothing.
#
# The consequence is a refusal that names the callee which WAS handing over the
# frame — the most actionable-looking wrong refusal this family produces, because
# the reader's next move is to go and check an export or a definition that is
# right there.
DECLARED_FRAME_RETURN_CASES = [
    # The minimal shape: `peek` declares `o: Opt` (two fields, so a frame
    # address) and its only call site hands it `mk(4)`, which returns one.
    # 41 is `o.v * 10 + o.has` = 4*10 + 1, and CPython agrees.
    ("declared_frame_parameter_given_a_frame_returning_call",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "def peek(o: Opt) -> Int:\n"
     "    return o.v * 10 + o.has\n"
     "\n"
     "def mk(v: Int) -> Opt:\n"
     "    var o = Opt()\n"
     "    o.v = v\n"
     "    o.has = 1\n"
     "    return o\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return peek(mk(4))\n", 41, None),
    # The value must be the FRAME's, not the callee's scratch. `mk(n)` writes `n`,
    # `n+1`, `n+2` into the block it reserved and returns its address, and
    # `peek` reads all three back as decimal DIGITS, so the answer's digits are
    # `n`, `n+1`, `n+2` in order and every misread word rearranges them.
    #
    # 98 is `n = 10`, which is what the formal startup stub passes as the entry
    # argument when the build was given no `-n` (measured: a program that prints
    # its `n` and is built the way `run_case` builds this one prints 10). The
    # three-digit answer is 1122 and the exit status is a BYTE, so 1122 % 256 =
    # 98 — stated rather than hidden because the arithmetic does not fit a byte,
    # and 98 is the only part of it a reader can check against a run. A `peek`
    # reading the middle slot alone gives 10, the first alone 100, and the two
    # outer slots swapped 210: none of those is 98.
    ("declared_frame_parameter_frame_returned_through_a_call_boundary",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "    var w: Int\n"
     "\n"
     "def peek(o: Opt) -> Int:\n"
     "    return o.v * 100 + o.has * 10 + o.w\n"
     "\n"
     "def mk(n: Int) -> Opt:\n"
     "    var o = Opt()\n"
     "    o.v = n\n"
     "    o.has = n + 1\n"
     "    o.w = n + 2\n"
     "    return o\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return peek(mk(n))\n", 98, None),
    # TWO call sites, both agreeing, one of them a frame-RETURNING call — so this
    # is the case that would still be refused if the fix were "a call to a
    # frame-returning function is always fine" rather than "it is one of the
    # four shapes this analysis places". 81 is `peek(mk(8))` (8*10 + 1) and 30
    # is `peek(o)` where `o` is a local `Opt()` carrying 3 and the zero its
    # construction left; 111 is their sum.
    ("declared_frame_parameter_two_agreeing_sites_one_returned",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "def peek(o: Opt) -> Int:\n"
     "    return o.v * 10 + o.has\n"
     "\n"
     "def mk(v: Int) -> Opt:\n"
     "    var o = Opt()\n"
     "    o.v = v\n"
     "    o.has = 1\n"
     "    return o\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var o = Opt()\n"
     "    o.v = 3\n"
     "    return peek(o) + peek(mk(8))\n", 111, None),
    # …and the SAME program with one site handing a WORD, which is the guard the
    # first two cannot be. It refuses, and the refusal names `peek(7)` — the
    # site that actually disagrees — rather than the frame-returning call beside
    # it. That is the property worth pinning: before the fix both sites were
    # reported, because the returned-frame one was invisible; a fix that lifted
    # the refusal wholesale would satisfy the two positives above and fail here.
    ("declared_frame_parameter_a_word_beside_a_returned_call_is_refused",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "def peek(o: Opt) -> Int:\n"
     "    return o.v * 10 + o.has\n"
     "\n"
     "def mk(v: Int) -> Opt:\n"
     "    var o = Opt()\n"
     "    o.v = v\n"
     "    o.has = 1\n"
     "    return o\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return peek(mk(5)) + peek(7)\n",
     "refuse:passes the literal 7", None),
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
    # (2a-bis) A KEYWORD construction, which used to be refused outright and is
    # now MATCHED against the field list. Every field is named here, so nothing
    # is left to a default and this is the whole of the capability: `x` gets 1
    # and `y` gets 2 whatever order the keywords are written in, which is what
    # makes the matching the answer rather than a reading of a dict.
    #
    # Read back through a METHOD for the same reason the positional case above
    # is: the answer then goes through the slot table rather than through
    # whatever a field read happens to do.
    ("constr_keyword_arguments_name_the_fields",
     "struct Kw:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "    var z: Int\n"
     "\n"
     "    fn get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.x\n"
     "        if i == 1:\n"
     "            return self.y\n"
     "        return self.z\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var t = Kw(z=4, x=1, y=7)\n"
     "    if t.get(0) != 1:\n"
     "        return 10 + t.get(0)\n"
     "    if t.get(1) != 7:\n"
     "        return 20 + t.get(1)\n"
     "    if t.get(2) != 4:\n"
     "        return 30 + t.get(2)\n"
     "    return 37\n", 37, None),
    # (2a-ter) A PARTIAL fill: `Pd(1)` on three fields, the two it leaves out
    # having class-level defaults. This is CPython's generated `__init__` and the
    # language's rule for a `@dataclass` field default, and it is the shape
    # `FORMAL_dataclass_partial_construction` measured.
    #
    # The DEFAULT is what makes it a program, and the case says so by reading
    # the unfilled field back: a `0` there would be a value the source never
    # wrote, which is the outcome the whole construction family refuses to risk
    # and the reason `constr_refuse_too_few_arguments` still refuses when the
    # field has no default.
    ("constr_partial_fill_uses_the_field_defaults",
     "struct Pd:\n"
     "    var a: Int\n"
     "    var b: Int = 40\n"
     "    var c: Int = 5\n"
     "\n"
     "    fn get(self, i: Int) -> Int:\n"
     "        if i == 0:\n"
     "            return self.a\n"
     "        if i == 1:\n"
     "            return self.b\n"
     "        return self.c\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var s = Pd(3)\n"
     "    if s.get(0) != 3:\n"
     "        return 90 + s.get(0)\n"
     "    if s.get(1) != 40:\n"
     "        return 80 + s.get(1)\n"
     "    if s.get(2) != 5:\n"
     "        return 70 + s.get(2)\n"
     "    return 48\n", 48, None),
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
    # This whole block is the construction family's last remaining refusal,
    # closed — the family was `“FORMAL_struct_construction_shapes: `S()`, `S(a, b, …)` and `S(x)`”` and
    # that doc is deleted now that every shape lowers, so the cases here are what
    # stands in its place.  `Slice` — the case that found it — declares
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
    # ── an EXCEPTION constructed with its message ──────────────────────────
    #
    # CPython's `BaseException.__new__` fills `args` from the caller's
    # arguments, so `raise E("boom")` carries the message with nothing declared
    # in `E` — which is why every exception class in CPython can be raised with
    # a message and why this path's field list used to have nowhere to put one:
    # a class whose body is a docstring derives NO fields, so the construction
    # was refused for the arity. `formal/model.py`'s `CPYTHON_EXCEPTION_BASES`
    # is the fix: a base from that table contributes `args`, base first, so the
    # message lands in the slot CPython puts it in.
    #
    # The exit status is 1 and the output empty, and both are what this path
    # documents for a `raise` (`formal`'s has no unwinder: a raise flushes the
    # enclosing `finally` clauses and exits). What this row pins is that the
    # BUILD accepts the construction at all — before the merge this was a
    # refusal on both architectures, byte for byte.
    ("constr_an_exception_carries_its_message",
     "struct Plain5(Exception):\n"
     "    \"\"\"no fields at all\"\"\"\n"
     "\n"
     "def boom5():\n"
     "    raise Plain5(\"the message\")\n"
     "\n"
     "def main(n):\n"
     "    try:\n"
     "        boom5()\n"
     "    except:\n"
     "        pass\n"
     "    return 0\n", 1, None),
    # The same with a field of its own, which is the boundary the doc measured:
    # `args` is inherited FIRST, so the message goes where CPython puts it and
    # the subclass's own field keeps its own default — `Plain6("m").tag` is 0 in
    # CPython, not "m".
    ("constr_an_exception_with_a_field_takes_the_message_in_args",
     "struct Plain6(Exception):\n"
     "    var tag: int = 0\n"
     "\n"
     "def make6() -> Int:\n"
     "    var e = Plain6(\"the message\")\n"
     "    return e.tag\n"
     "\n"
     "def main(n):\n"
     "    printf(\"tag=%d\", make6())\n"
     "    return 0\n", 0, "tag=0"),
]

# ── a one-field HOLDER's CONSTRUCTOR store: which refusal answers it ──
#
# `Box` below has exactly one field and that field is a FRAME, so
# `_rewrite_self_fields` collapses `self.inner` onto `self` before any late pass
# reads the store — which made the receiver-rebind rule answer a CONSTRUCTOR,
# with a message that says the source rebinds `self` (it does not), that CPython
# rejects the shape (it does not: `def __init__(self, o): self.inner = o` is the
# most ordinary constructor in Python), and that names `Box___init__`, a symbol
# `_fieldwise_ctor_synthesized` invented.
#
# The rule now stands down when the method IS the constructor
# (`formal/build.py`'s `_collect_receiver_rebinds`), because this path never
# CALLS one: `model.init_body_stores` inlines a constructor's `self.<field> =
# …` stores into the fresh block at the CONSTRUCTION SITE, so there is no
# callee-local `self` whose rebinding could drop a store.  These three rows are
# the measurement of what answers each spelling instead, and they are the reason
# the exemption is safe to land: every one of them is still refused, and each by
# the rule whose question it actually is.
#
# (a) is formal10-2's original needle and the pair it belongs to is
# `test_formal_method_param_field.py`'s
# `refuse_a_struct_field_initialised_from_a_constructor_argument` plus
# `a_struct_field_assigned_after_construction_is_the_same_program` (the
# workaround, `v=41 h=1` on both architectures).
SOLE_FIELD_CTOR_STORE_CASES = [
    # (a) THE ARGUMENT.  The frame that reaches the object's block is the
    # CALLER's, which is the construction-argument hazard and the sentence the
    # reader can act on.
    ("sole_field_ctor_store_of_an_argument_is_the_construction_argument",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var inner: Opt\n"
     "\n"
     "    def __init__(out self, o: Opt):\n"
     "        self.inner = o\n"
     "\n"
     "def main() -> Int:\n"
     "    var o = Opt()\n"
     "    o.v = 41\n"
     "    o.has = 1\n"
     "    var b = Box(o)\n"
     "    printf(\"v=%d h=%d\", b.inner.v, b.inner.has)\n"
     "    return 0\n",
     "refuse:constructing Box with argument 'o' as field 'inner'", None),
    # (b) A frame built HERE, which the receiver rule already stood down from
    # (`_value_may_be_a_frame` recognises the construction) and which used to be
    # answered by ANOTHER RULE — the field read at the call site, refused as
    # `'b.v' is a field access through 'b'`, because the holder analysis
    # classified a local bound from a ONE-FIELD struct's constructor as a plain
    # word.  It no longer needs an answer from any rule: `b`'s word IS the
    # address of the `Opt` frame (`model.struct_construction_yields_frame_
    # address`), so `b.inner.v` is one load at `b + 8·0` and the two fields read
    # as the zeros a fresh `Opt` holds.  `v=0 h=0` is CPython's answer, so this
    # is a positive row now rather than a `refuse:` one — the numbers are the
    # assertion and they are not weak: they are only reachable if `Box()`
    # reserved and initialised the frame, so a lowering that left the word null
    # and one that read the wrong slot both fail it.  It stayed in this group
    # because the group's question is WHICH RULE ANSWERS each of the three ctor
    # stores, and "none of them" is the answer for this one now.
    # commit 03e3b7b6.
    ("sole_field_ctor_store_of_a_frame_built_here_is_another_rules",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var inner: Opt\n"
     "\n"
     "    def __init__(out self):\n"
     "        self.inner = Opt()\n"
     "\n"
     "def main() -> Int:\n"
     "    var b = Box()\n"
     "    printf(\"v=%d h=%d\", b.inner.v, b.inner.has)\n"
     "    return 0\n",
     0, "v=0 h=0"),
    # (c) A frame the CALLEE made — which the doc predicted would BUILD, and
    # which does NOT: `init_body_stores` only substitutes a BARE PARAMETER for a
    # right-hand side, because only a bare parameter has the caller's own
    # expression standing in for it at the construction site, and a call is not
    # one.  Recorded as measured rather than as hoped: the honest answer is that
    # the constructor is refused with the STATEMENT spelled out, which is the
    # same refusal any other un-inlinable body gets and a different question
    # from the receiver's.
    ("sole_field_ctor_store_of_a_call_is_the_inlining_rule",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "def mk(v: Int) -> Opt:\n"
     "    var o = Opt()\n"
     "    o.v = v\n"
     "    o.has = 1\n"
     "    return o\n"
     "\n"
     "struct Box:\n"
     "    var inner: Opt\n"
     "\n"
     "    def __init__(out self):\n"
     "        self.inner = mk(41)\n"
     "\n"
     "def main() -> Int:\n"
     "    var b = Box()\n"
     "    printf(\"v=%d h=%d\", b.inner.v, b.inner.has)\n"
     "    return 0\n",
     "refuse:whose body this path does not inline", None),
    # THE CONTROL for the exemption: the same store in an ordinary METHOD, which
    # is not a constructor and keeps the receiver refusal — with the measured
    # SIGSEGV behind it (`refuse_a_one_word_holder_of_a_frame_stored_through_its_
    # receiver`, which is this program's `_fieldwise_ctor_synthesized` twin).
    # Without this row an over-broad exemption — "skip one-field owners whose
    # sole field is a frame", ignoring WHICH method it is — would pass every
    # row above.
    ("a_method_not_the_constructor_still_gets_the_receiver_refusal",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "struct Box:\n"
     "    var inner: Opt\n"
     "\n"
     "    def __init__(out self):\n"
     "        self.inner = Opt()\n"
     "\n"
     "    def set(out self, o: Opt):\n"
     "        self.inner = o\n"
     "\n"
     "def main() -> Int:\n"
     "    var o = Opt()\n"
     "    o.v = 41\n"
     "    o.has = 1\n"
     "    var b = Box()\n"
     "    b.set(o)\n"
     "    printf(\"v=%d h=%d\", b.inner.v, b.inner.has)\n"
     "    return 0\n",
     "refuse:self is assigned o in Box_set()", None),
]

# ── a `**` SPREAD ──────────────────────────────────────────────────────
#
# `**mapping` reaches the AST as an entry of `args` wrapped in `UnaryOp('**')`,
# which is right for an interpreter (it splices at call time) and was wrong here:
# the field binding zipped `args` against the FIELD LIST, so a spread was read as
# the next POSITIONAL value.  Measured on both architectures: `S(a=1,
# **{'b': 2})` was refused with ‘gives field a more than one value’ — a duplicate
# the source does not contain — and one keyword fewer would have stored the
# mapping's own word into `a`'s slot.  The rows below are the three answers a
# spread now has, and the middle one is the refusal that must survive them: a
# literal spread's DUPLICATE is CPython's own `TypeError`, and the check that
# catches it is the ordinary keyword check, which is the point of un-spreading
# rather than special-casing.
SPREAD_CONSTRUCTION_CASES = [
    # The capability: both keys and both values are written in the source, and a
    # dict subscript by a literal key already lowers, so this is ordinary
    # Python with a representation. `12` is `a * 10 + b` = 1, 2 in CPython too.
    ("a_dict_literal_spread_fills_the_fields_it_names",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P(a=1, **{'b': 2})\n"
     "    printf(\"%d %d\", p.a, p.b)\n"
     "    return 0\n",
     "import sys\n"
     "class P:\n"
     "    def __init__(self, a, b):\n"
     "        self.a = a\n"
     "        self.b = b\n"
     "def main():\n"
     "    p = P(a=1, **{'b': 2})\n"
     "    sys.stdout.write(\"%d %d\" % (p.a, p.b))\n"),
    # The same on an ordinary CALL, which is the other reader of `args` —
    # `bind_call_arguments`, the one implementation both backends use. It is a
    # separate row because a fix that only taught the construction path would
    # leave this one saying "multiple values for argument 'a'", which is the same
    # fabrication about a different construct.
    ("a_dict_literal_spread_fills_a_calls_keywords",
     "def f(a: Int, b: Int) -> Int:\n"
     "    return a * 10 + b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    printf(\"%d\", f(a=1, **{'b': 2}))\n"
     "    return 0\n",
     "def f(a, b):\n"
     "    return a * 10 + b\n"
     "import sys\n"
     "def main():\n"
     "    sys.stdout.write(\"%d\" % f(a=1, **{'b': 2}))\n"),
]

SPREAD_REFUSALS = [
    # THE DUPLICATE, which is CPython's `TypeError: got multiple values for
    # argument a` and is now reported by the ordinary keyword check — the same
    # sentence, arrived at honestly. Without this row a fix that dropped the
    # duplicate check for spreads would pass the two above.
    ("a_literal_spread_that_duplicates_a_keyword_is_still_a_duplicate",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P(a=1, **{'a': 2})\n"
     "    printf(\"%d\", p.a)\n"
     "    return 0\n",
     "refuse:more than one value", None),
    # A spread whose keys are NOT in the source, at a construction — refused by
    # name, with the reason and the way out.
    ("a_spread_through_a_mapping_name_is_refused_by_name",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var d = {'b': 2}\n"
     "    var p = P(a=1, **d)\n"
     "    printf(\"%d\", p.a)\n"
     "    return 0\n",
     "refuse:constructing P spreads `d` with `**`", None),
    # …and through a `**`-PARAMETER, which is the corpus case
    # (`formal/x86_64_decode.py`'s `insn()` helper forwards `**kw`) and the shape
    # the refusal names as the real blocker: a formal value is one 64-bit word
    # and this target has no variadic ABI, so the callee cannot read its own
    # `**kwargs` at all. The row is here so that, when that capability lands,
    # this is the row that says so.
    ("a_spread_through_a_kwargs_parameter_is_refused_by_name",
     "struct Insn:\n"
     "    var offset: Int\n"
     "    var length: Int\n"
     "\n"
     "def mk(off: Int, ln: Int, **kw) -> Insn:\n"
     "    return Insn(offset=off, length=ln, **kw)\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var i = mk(1, 2)\n"
     "    printf(\"%d\", i.offset)\n"
     "    return 0\n",
     "refuse:constructing Insn spreads `kw` with `**`", None),
    # The same on a call, so the two readers cannot drift: one message, one
    # cause, and the subject spelled by the construct it is about.
    ("a_spread_through_a_mapping_name_is_refused_by_name_at_a_call",
     "def f(a: Int, b: Int) -> Int:\n"
     "    return a * 10 + b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var d = {'b': 2}\n"
     "    printf(\"%d\", f(a=1, **d))\n"
     "    return 0\n",
     "refuse:call f() spreads `d` with `**`", None),
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
     # (5) A READ OF THE RECEIVER.  It used to be one refusal with the needle
     # "a read of 'self' in the right-hand side", because the block's address
     # could not be threaded through as a receiver — and it is now TWO lowerings
     # and a smaller refusal.  A method call is lifted to a real call with the
     # block's address as its receiver and a one-level field read is a load at
     # `block + 8·slot`, both of which the emitters answer from the block
     # `struct_constructor_sites` already reserved for this call
     # (`CTOR_RECEIVER_CASES` builds and runs the two shapes against CPython).
     #
     # What is left is a receiver read with no address to compute from, and the
     # three cases below are the three ways that happens.  This first one is a
     # read THROUGH a field: the slot holds a frame ADDRESS and the offset after
     # it is a different struct's layout, which is the one thing this struct's
     # own field table cannot answer.
     ("constr_refuse_an_init_body_that_reads_through_a_nested_field",
      "struct In5:\n"
      "    var q: Int\n"
      "    var r: Int\n"
      "\n"
      "struct A5:\n"
      "    var a: Int\n"
      "    var inner: In5\n"
      "    var b: Int\n"
      "\n"
      "    def __init__(out self, a: Int):\n"
      "        self.a = a\n"
      "        self.b = self.inner.q\n"
      "\n"
      "def main(n: Int) -> Int:\n"
      "    var x = A5(1)\n"
      "    return x.b\n",
      "refuse:whose body this path does not inline: a read of the receiver this "
      "path cannot resolve against the block being constructed: `self.inner.q`, "
      "a read THROUGH a field of A5",
      None),
     # (5a) The same family from the other side: a field handed to a CALL.
     # A slot holds one word and that word is an ADDRESS when the field holds a
     # nested frame, so whether a callee may be handed one is a question about
     # the CALLEE's parameter convention — and this is the one place in the
     # compiler that cannot ask, because the frame-holder analysis reads
     # function bodies and a call lifted out of an inlined constructor body is in
     # none of them.
     ("constr_refuse_an_init_body_that_hands_a_field_to_a_call",
      "def twice5(v: Int) -> Int:\n"
      "    return v * 2\n"
      "\n"
      "struct A5b:\n"
      "    var a: Int\n"
      "    var b: Int\n"
      "\n"
      "    def __init__(out self, a: Int):\n"
      "        self.a = a\n"
      "        self.b = twice5(self.a)\n"
      "\n"
      "def main(n: Int) -> Int:\n"
      "    var x = A5b(1)\n"
      "    return x.b\n",
      "refuse:whose body this path does not inline: a read of the receiver this "
      "path cannot resolve against the block being constructed: `self.a` handed "
      "to `twice5(…)` as an argument",
      None),
     # (5b) The receiver read with nothing behind it at all: the object itself,
     # rather than one of its fields.  A bare `self` has no word to load and no
     # call to lift, so there is nothing for the block to say.
     ("constr_refuse_an_init_body_that_reads_the_receiver_barely",
      "def sink5(v: Int) -> Int:\n"
      "    return 1\n"
      "\n"
      "struct A5c:\n"
      "    var a: Int\n"
      "    var b: Int\n"
      "\n"
      "    def __init__(out self, a: Int):\n"
      "        self.a = a\n"
      "        self.b = sink5(self)\n"
      "\n"
      "def main(n: Int) -> Int:\n"
      "    var x = A5c(1)\n"
      "    return x.b\n",
      "refuse:whose body this path does not inline: a read of the receiver this "
      "path cannot resolve against the block being constructed: a bare read of "
      "`self`, which is the object under construction and neither one of its "
      "fields nor a method call on it",
      None),
     # (5c) A receiver read on a struct that HAS no block to read.  A struct of
     # one field is a plain word and its receiver IS that word, so the two
     # lowerings above — both of which compute something out of an address —
     # have no address; and the word this construction evaluates to is the LAST
     # store of the body, so an earlier read has no value to read.  The method
     # is a `@staticmethod` because an ordinary method of a one-field struct that
     # returns a value is refused earlier and more specifically, by
     # `receiver_writeback_name` — which is a real answer about a different
     # question and not this one.
     ("constr_refuse_an_init_body_that_reads_a_one_field_receiver",
      "struct One5:\n"
      "    var n: Int\n"
      "\n"
      "    def __init__(out self, v: Int):\n"
      "        self.n = self.plus()\n"
      "\n"
      "    @staticmethod\n"
      "    def plus() -> Int:\n"
      "        return 7\n"
      "\n"
      "def main(n: Int) -> Int:\n"
      "    var x = One5(1)\n"
      "    return x.n\n",
      "refuse:whose body this path does not inline: a read of the receiver this "
      "path cannot resolve against the block being constructed: a read of the "
      "receiver of One5, which is a struct of 1 field(s) and so its receiver IS "
      "its own word",
      None),
     # (5d) The name `self.a + b` used to be refused as a receiver read.  The
     # receiver half of it lowers now and the refusal is about the OTHER name:
     # `b` is a parameter read inside an expression, which this path does not
     # substitute (see `_init_store_value`'s bare-parameter rule, and why the
     # rule is "alone" and not "anywhere").
     ("constr_refuse_an_init_body_that_reads_a_parameter_under_a_field_read",
      "struct A5d:\n"
      "    var a: Int\n"
      "    var b: Int\n"
      "\n"
      "    def __init__(out self, a: Int, b: Int):\n"
      "        self.a = a\n"
      "        self.b = self.a + b\n"
      "\n"
      "def main(n: Int) -> Int:\n"
      "    var x = A5d(1, 2)\n"
      "    return x.b\n",
      "refuse:whose body this path does not inline: a read of 'b' in the "
      "right-hand side",
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
    # (7a) The SAME construction stored DIRECTLY into the one field, on a struct
    # whose ONLY field is a nested frame — the shape a deleted bug doc was filed
    # about, and the PROGRAM half of the pair `test_formal_dylib.py`'s `a
    # receiver write-back is not a returned frame` refuses at a module
    # boundary.  Both halves are here because they are two different questions
    # with two different fixes, and a reader who has only one of them tends to
    # assume the other one is the same refusal:
    #
    #   * in a PROGRAM the obstacle is the INLINE.  `Box1(20, 22)` is a call to a
    #     declared `__init__`, this path inlines that body at the construction
    #     site, and the body builds a frame the inlined copy has no prologue
    #     site to put it in — `init_body_stores`, the same rule as (7).
    #   * at a MODULE BOUNDARY the obstacle is the LIFETIME.  The constructor is
    #     never inlined anywhere, and the frame it hands back is one it built in
    #     its own prologue, so an importer that reserves the block the contract
    #     describes reads a dead one.
    #
    # The needle is (7)'s, on purpose: the two programs differ by one field, one
    # nesting level and where they run, and a reader who lands here should be
    # sent to the same sentence rather than to a fourth one.
    ("constr_refuse_a_one_word_ctor_that_assigns_a_nested_frame",
     "struct In1b:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct Box1b:\n"
     "    var inner: In1b\n"
     "\n"
     "    def __init__(out self, a: Int, b: Int):\n"
     "        self.inner = In1b(a, b)\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var x = Box1b(1, 2)\n"
     "    return x.inner.a\n",
     "refuse:whose body this path does not inline: `In1b(…)`, a construction of "
     "a struct whose receiver is a frame",
     None),
# (8) The SAME construction into a field DECLARED with that struct's type, and
    # **this one used to be a refusal and is now the row that says why it is
    # not** (`model.init_stores_a_parameter_struct`, 2026-10-03).
    #
    # It was refused as "a store over a placed nested frame", and the PLACEMENT
    # is what made the store unsound — `struct_nested_frame_fields` reserves a
    # block in the object's own block and writes that block's address into `f`,
    # so a pointer stored over it leaves a word where every reader computes a
    # frame base from it.  But this constructor does not BUILD a nested frame in
    # `f`: it stores the CALLER's, because `f` arrived as its own annotated
    # parameter.  `f` is therefore a POINTER slot, `g` is the only placed one,
    # and `x.f.a` reads the caller's frame at the slot's own offset.
    #
    # Which is why this case changed from `refuse:` to an ANSWER rather than
    # being deleted: it is the smallest source that reaches the whole deadlock,
    # and a reader who finds the placement predicate and wants to know what it
    # moved should find the answer here.  1 + 2 + 3 = 6.
    ("constr_a_delegating_store_into_a_typed_nested_slot_builds",
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
     "    return x.f.a + x.f.b + x.g\n", 6, None),
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
     # The MESSAGE changed and the VERDICT did not: `P1(1)` used to be an
     # arity refusal because the count did not match the field count, and it is
     # still a refusal because `y` has no class-level default to be filled
     # from — a different reason with a different repair, so it says so.
     # `constr_partial_fill_needs_a_default` is the case that pins the other
     # half: with a default on the field, the same count IS a program.
     "refuse:leaves 'y' unfilled, and 'y' has no default", None),
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
    # ── A KEYWORD construction — the four SPELLINGS and the three
    # `TypeError`s ───────────────────────────────
    #
    # This used to be a REFUSAL, with the case named
    # `constr_refuse_keyword_arguments` and the comment "which the language does
    # not have" — which was never true.  It IS a shape, it is the idiomatic
    # spelling for a struct with many fields, and the stdlib's own
    # `StringSlice(unsafe_from_ptr=p)` is one.  What the old refusal gave as
    # its reason was right about the wrong reading: reading the keywords as
    # POSITIONALS in dict order would make a program's meaning depend on an
    # iteration order nobody wrote.  Matching each keyword against the FIELD
    # LIST by name is the reading that cannot depend on any order, so that is
    # what `model._construction_field_bindings` does.
    #
    # The construct has seven answers and a rule that got six of them right
    # would be the same defect again, so there are seven rows here: every field
    # named (which is `constr_keyword_arguments_name_the_fields` in
    # CONSTRUCTION_CASES, where the keywords are deliberately written OUT of
    # declaration order so a positional reading cannot pass it, and where the
    # answer is read back through a METHOD rather than through a field); a
    # field left at its default; positionals filling the fields a keyword does
    # not name; a keyword on a one-field struct; and the three refusals.
    #
    # A FIELD NO KEYWORD NAMES keeps its class-level default, which is the
    # language's rule (the object is default-initialized before anything is
    # assigned to it).  This is the row that separates the keyword shape from
    # the positional one: `S(a, b)` covers every field, so it has no defaults
    # left to keep, and a rule that read a keyword construction as a permuted
    # positional list would have had to invent a value for `x`.
    ("constr_keyword_leaves_unnamed_fields_at_their_default",
     "struct P3:\n"
     "    var x: Int = 4\n"
     "    var y: Int = 5\n\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P3(y=9)\n"
     "    printf(\"x=%d y=%d\", p.x, p.y)\n"
     "    return p.x + p.y\n", 13, "x=4 y=9"),
    # THE MIXED FORM: the positionals take the fields in declaration order and
    # the keyword names its own.  This row is here because a rule that filled
    # the fields from the keywords alone would answer 0 for `x` and be right
    # about everything else in this comment.
    ("constr_keyword_mixed_with_positional",
     "struct P3:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P3(1, y=2)\n"
     "    printf(\"x=%d y=%d\", p.x, p.y)\n"
     "    return p.x + p.y\n", 3, "x=1 y=2"),
    # A ONE-FIELD struct, where the receiver IS the field: the keyword names
    # it, the value is the result, and there is nothing to store.  This branch
    # used to refuse every keyword before the plan was consulted, which is how
    # the shape stayed a refusal here while the framed case was being fixed.
    ("constr_keyword_on_a_one_field_struct",
     "struct W3:\n"
     "    var v: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var w = W3(v=42)\n"
     "    printf(\"v=%d\", w.v)\n"
     "    return w.v\n", 42, "v=42"),
    # A keyword naming no field.  The FIELD LIST is in the message, because
    # "unknown keyword argument" without the names sends the reader to grep a
    # declaration that is right there.
    ("constr_refuse_keyword_naming_no_field",
     "struct P3:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P3(b=3)\n"
     "    return 0\n",
     "refuse:is not a field of P3 (x, y)", None),
    # A field given twice — `S(1, x=2)`, which is CPython's `got multiple
    # values for argument x`.  The naive reading (append the keywords to the
    # positionals and let the arity rule notice) would have STORED both, and the
    # second store would be the program's answer with nothing to say so.
    ("constr_refuse_a_field_given_twice",
     "struct P3:\n"
     "    var x: Int\n"
     "    var y: Int\n\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P3(1, x=2)\n"
     "    return 0\n",
     "refuse:gives field 'x' more than one value", None),
    # A keyword against a struct that DECLARES an `__init__`, and this is the
    # one the resolution cannot fix rather than a rule it is leaving out:
    # `CONSTRUCTION_INIT` selects the overload by ARGUMENT COUNT, so a keyword
    # call has nothing to select on.  Picking the widest, or the first, would
    # be running a constructor the program did not choose.
    ("constr_refuse_keyword_against_a_declared_init",
     "struct S3:\n"
     "    var start: Int\n"
     "    var end: Int\n"
     "    def __init__(out self, start: Int, end: Int):\n"
     "        self.start = start\n"
     "        self.end = end\n\n"
     "def main(n: Int) -> Int:\n"
     "    var s = S3(end=7)\n"
     "    return 0\n",
     "refuse:is a call to a user-defined `__init__` (S3 declares 1 of them)",
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
    # …and THE SAME CALL SPECIALIZED, which is the row above's twin and the
    # reason it is here. `mklist[1]()` names the same function as `mklist()` —
    # `formal/model.py::call_callee_name` is the tree's one reader of exactly
    # that, and `bugs/FORMAL_a_specialization_defeats_the_frame_escape_refusals.md`
    # is the general statement of it — so the two spellings of one argument must
    # get one answer.
    #
    # They did not, and they got it in the PERMISSIVE direction, which is the
    # expensive one: `model._callee_container_evidence` read the callee with
    # its own `isinstance(arg.func, F.IdentExpr)`, a subscript callee fell out,
    # and `Bag2(mklist[1](), 5)` BUILT on both architectures with a word in the
    # slot that points into reclaimed scratch. That is premise (B1)'s hazard
    # reached by a spelling, and the two neighbouring messages said `?()` where
    # the source says `mklist[1]()`.
    #
    # The needle is the CALLEE'S NAME and not the refusal's presence, so a fix
    # that made the row refuse for some other reason would not pass it.
    ("constr_refuse_a_container_returned_by_a_specialized_callee",
     "struct Bag2:\n"
     "    var items: Int\n"
     "    var n: Int\n"
     "\n"
     "def mklist[a: Int]() -> List[Int]:\n"
     "    var xs = [1, 2, 3]\n"
     "    return xs\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Bag2(mklist[1](), 5)\n"
     "    return b.n\n",
     "refuse:constructing Bag2 with the call to 'mklist' as field 'items' is "
     "refused on this path: mklist() is declared to return a container",
     None),
    # ── the SAME hazard with NO declaration to read ──
    #
    # `def mklist(): return [1, 2, 3]` is an ordinary Mojo spelling and stores
    # exactly the same dead region the case above refuses, so the DECLARATION
    # was never the fact — it was one reader of it.  The needle names the second
    # reader (the callee's return statements) rather than repeating the first,
    # because a message that said "is declared to return a container" about a
    # callee that declares nothing would send the reader looking for a
    # declaration that does not exist.
    ("constr_refuse_container_inferred_from_a_callee",
     "struct Bag4:\n"
     "    var items: Int\n"
     "    var n: Int\n"
     "\n"
     "def mklist():\n"
     "    var xs = [1, 2, 3]\n"
     "    return xs\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Bag4(mklist(), 5)\n"
     "    return b.n\n",
     "refuse:declares no return type and every `return` in it yields a container",
     None),
    # The other direction, and it is a build rather than a refusal because the
    # permissive tie-break has to stay permissive for the cases it is right
    # about: an unannotated callee that returns a STRING (static storage, so no
    # lifetime problem at all), one whose returns DISAGREE with one another (no
    # single question, so no claim), and one declared `-> Int` whose body returns
    # a list (the declaration is the contract). Each field has its own return
    # code, so a regression says which of the three started being refused.
    ("constr_allow_a_callee_that_is_not_a_container",
     "struct Bag5:\n"
     "    var items: Int\n"
     "    var n: Int\n"
     "\n"
     "def mkstr():\n"
     "    return \"abc\"\n"
     "\n"
     "def mixed(c: Int):\n"
     "    if c > 0:\n"
     "        return [1]\n"
     "    return 7\n"
     "\n"
     "def lying() -> Int:\n"
     "    return [9]\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var a = Bag5(mkstr(), 1)\n"
     "    if a.n != 1:\n"
     "        return 10 + a.n\n"
     "    var b = Bag5(mixed(n), 2)\n"
     "    if b.n != 2:\n"
     "        return 20 + b.n\n"
     "    var c = Bag5(lying(), 3)\n"
     "    if c.n != 3:\n"
     "        return 30 + c.n\n"
     "    return 7\n", 7, None),
    # The REACHABLE CONSEQUENCE of the hazard the case above refuses, checked
    # separately and for a different reason. `append` through a frame slot is
    # refused on its own terms — the room an append needs has to be known where
    # the list is built, and a slot is not a list literal — which is what makes
    # the permissive tie-break in `_callee_container_evidence` safe rather
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
    # `bytearray`/`bytes` are the one pair in that list whose refusal is NOT
    # "cannot be conjured out of one word", and the generic sentence is false
    # about them: the blob layout is one this path already lays out (`[]` is it),
    # a bytes LITERAL already builds one, and `len(b"abc")` answers 3. What is
    # undecided is the ELEMENT WIDTH, so the message has to say that — and
    # `bytes(3)` with an argument has to keep saying it too, because an
    # argument does not make the width any more decided.
    #
    # Before this, all four spellings reached the bind audit as a dangling
    # extern named `bytearray`/`bytes` and the build failed with a message about
    # a SYMBOL, which is a fact about the link line and not about the type the
    # reader wrote. `bugs/FORMAL_bytearray_and_bytes_have_no_representation.md`.
    ("constr_refuse_bytearray_by_name",
     "def main(n: Int) -> Int:\n"
     "    var b = bytearray()\n"
     "    return 0\n",
     "refuse:the element width is the undecided part", None),
    ("constr_refuse_bytes_with_an_argument_by_name",
     "def main(n: Int) -> Int:\n"
     "    var b = bytes(3)\n"
     "    return 0\n",
     "refuse:constructing bytes is refused on this path", None),
    # ── INHERITANCE: the fields a class has because a BASE declares them ────
    #
    # `formal/model.py`'s `attach_inherited_fields` merges a declared base's
    # fields into the subclass's layout, base first. These four rows are the
    # three things that merge is FOR, plus the one thing it cannot do.
    #
    # (1) The layout itself. Before, `s.x` through a subclass was refused with
    # a sentence claiming the program raises an AttributeError — false, because
    # the class INHERITS `x`. The program below is the reduction the merge was
    # written for, and it answers CPython on both architectures.
    ("constr_inherit_a_field_through_the_subclass",
     "class Base2:\n"
     "    def __init__(self):\n"
     "        self.x = 7\n"
     "\n"
     "    def get(self):\n"
     "        return self.x\n"
     "\n"
     "class Sub2(Base2):\n"
     "    pass\n"
     "\n"
     "def main(n):\n"
     "    s = Sub2()\n"
     "    s.x = n\n"
     "    printf(\"x=%d\", s.get())\n"
     "    return 0\n", 0, "x=10"),
    # (2) The ORDER, which is what decides which value lands in which slot and
    # is CPython's dataclass order: the base's fields first, the subclass's
    # after. Both classes are two-or-more fields wide on purpose — see the
    # refusal row below for why a one-word base cannot be in this picture.
    ("constr_inherit_the_bases_fields_before_its_own",
     "class Base3:\n"
     "    x: int\n"
     "    z: int\n"
     "\n"
     "class Sub3(Base3):\n"
     "    y: int\n"
     "\n"
     "def main(n):\n"
     "    s = Sub3(1, 2, 3)\n"
     "    printf(\"x=%d z=%d y=%d\", s.x, s.z, s.y)\n"
     "    return 0\n", 0, "x=1 z=2 y=3"),
    # (3) A base this image does not declare. The refusal used to say "no
    # fields at all" and told the reader to declare the fields, which is advice
    # about a class whose missing fields are not the problem: it INHERITS them.
    # The needle is the base's NAME, because that is what the reader has to go
    # and look for.
    ("constr_refuse_an_undeclared_base_by_name",
     "class MyErr(Widget):\n"
     "    \"\"\"no fields at all\"\"\"\n"
     "\n"
     "def boom():\n"
     "    raise MyErr(\"the message\")\n"
     "\n"
     "def main(n):\n"
     "    try:\n"
     "        boom()\n"
     "    except:\n"
     "        pass\n"
     "    return 0\n",
     "refuse:derives from 'Widget', which this image does not declare", None),
    # (4) What the merge CANNOT do, and the reason this is a refusal and not a
    # gap in the merge: a method is compiled against the layout of the class
    # that DECLARES it, and a call site carries no receiver type to check with,
    # so a base whose receiver IS its field cannot receive a subclass whose own
    # fields pushed it over the one-word line. Left alone this reads a frame
    # ADDRESS as the field's value — a wrong answer rather than a missing one.
    ("constr_refuse_a_subclass_whose_base_methods_would_change_layout",
     "class Base4:\n"
     "    def __init__(self):\n"
     "        self.x = 7\n"
     "\n"
     "class Sub4(Base4):\n"
     "    def __init__(self):\n"
     "        self.y = 1\n"
     "\n"
     "def main(n):\n"
     "    s = Sub4()\n"
     "    printf(\"x=%d y=%d\", s.x, s.y)\n"
     "    return 0\n",
     "refuse:do not agree on what a receiver IS", None),
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
    # A bracket list NESTED INSIDE another subscript's index, where the outer
    # one is a runtime index. This is the boundary of `model.type_position_nodes`
    # and it is here because that function exempts a bracket list from the
    # runtime question when it sits in a TYPE position, and "nested in a
    # subscript" is not what makes it one: `a`'s base is a list, so
    # `b[c, d]` is a two-dimensional index of a value and stays refused. The
    # other direction — a type application's own arguments, which ARE compile
    # time by construction — is `external_call["getenv", _CPointer[UInt8,
    # UntrackedOrigin[mut=False]]]`, pinned by execution in
    # `test_formal_external_call.py`'s `env_round_trip`.
    ("sub_multi_index_nested_in_a_runtime_index",
     "def main(n):\n"
     "    a = [[1, 2], [3, 4]]\n"
     "    b = [(0, 1), (0, 2)]\n"
     "    c = 0\n"
     "    d = 1\n"
     "    return a[b[c, d]]\n",
     "refuse:is a subscript whose index is a tuple", None),
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
    # `del a[i, j]`. BOTH backends reach the subscript and refuse with the
    # shared message — x86-64 used to refuse the STATEMENT first ("unsupported
    # statement DelStmt") because it had no `del` at all, and the two spellings
    # of the same refusal are why this reads `refuse_either:`; the second
    # alternative is kept because a `del` reaching a backend that cannot lower
    # it is exactly the divergence the case is here for.
    #
    # This case exists because the shape used to be a silent NO-OP on arm64:
    # the SubscriptExpr branch of `_emit_del` sits after the SliceExpr branch's
    # `continue`, so `del a[i, j]` fell off the end of the loop, built, ran,
    # and left all three elements in place. The three shapes that branch DID
    # reach were wrong in the same unreachable way — three of the four `del`
    # helpers had an inverted branch — and are now `test_formal_x86_64_parity.py`
    # rows measured against CPython, which is where a value assertion belongs.
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
    # ── an ELEMENT of a value that is not a container at all ──
    #
    # The third arm of the family the three refusals above belong to, and the
    # one that had no arm: every one of them is keyed on the base being a FRAME
    # ADDRESS, and `a = 5` is neither a frame address nor a `char *`, so it
    # matched none of them. What was left is the blob walk itself — read the
    # count from offset 0 of the base, read or write at `base + 8 + 8k` — so for
    # an integer the element address is the integer plus 8.
    #
    # Measured on BOTH architectures before the refusal: the build is GREEN and
    # the image dies of SIGSEGV, exit 139. That is the shape this backend's
    # whole refusal discipline exists to convert into a message, and it is a
    # build error now.
    #
    # It is the STORE, and the store only, because the store is the one that
    # computes the address from the base: a read is equally unmapped, and
    # `model.non_container_element_refusal`'s docstring records that. `a[i]` as a
    # value and `a[i] = v` as a store reach the same choke point, so the
    # message is the same one either way — which is why this case asserts the
    # SUBSCRIPT needle rather than the store's.
    ("sub_on_an_integer_is_refused",
     "def main(n):\n"
     "    a = 5\n"
     "    a[0] = 1\n"
     "    printf(\"a=%d\", a)\n"
     "    return 0\n",
     "refuse:asks for a container element", None),
    # THE THREE THAT MUST NOT BE REFUSED, and they are here for the reason they
    # are the interesting half: `INT_KIND` is this model's DEFAULT for a word,
    # so all three carry it while being containers, and a check that read the
    # default as a claim would refuse three correct programs — which is the
    # failure mode a wrong answer causes everywhere else in this backend.
    # Every one of the three BUILT and answered before this refusal existed.
    #
    #   * an unannotated PARAMETER — `at(xs, i)` is what every container-taking
    #     function in the corpus looks like;
    #   * a CALL RESULT whose callee declares `-> List[Int]`, which the kind
    #     table reaches through `func_kind` and cannot tell from a fallback;
    #   * a LOOP VARIABLE over a name — the ordinary way to walk a list of
    #     lists, and the shape a for-in iteration test would refuse.
    #
    # The three answers are 30 (the parameter), 2 (the call) and 13 (the loop),
    # and CPython answers the same three — so this is a value assertion and not
    # a refusal, which is the only thing that can say "still a program". All
    # three are in the exit status AND in the printed line, so a regression that
    # fabricated a plausible number would have to fabricate both.
    ("sub_on_a_parameter_call_result_and_loop_var_still_build",
     "def at(xs, i):\n"
     "    return xs[i]\n"
     "class H:\n"
     "    xs: List[Int]\n"
     "    def get(self) -> List[Int]:\n"
     "        return self.xs\n"
     "def show(rows):\n"
     "    var s = 0\n"
     "    for row in rows:\n"
     "        s = s + row[0]\n"
     "    return s\n"
     "def main(n):\n"
     "    var h = H()\n"
     "    h.xs = [1, 2, 3]\n"
     "    var ys = h.get()\n"
     "    var a = at([10, 20, 30], 2)\n"
     "    var b = ys[1]\n"
     "    var c = show([[1, 2], [3, 4]])\n"
     "    printf(\"%d %d %d\", a, b, c)\n"
     "    return a + b + c\n", 36, "30 2 4"),
    # A base DECLARED to be an integer, which is the row above's question with
    # the answer written down instead of inferred. `a = 5` is refused by the
    # emitter-side rule keyed on `own_shape_kind` — a statement of THIS function
    # bound the name — and `var a: Int = 5` is bound by a statement too, so it
    # is refused there as well. This row is the shape that rule cannot see: a
    # PARAMETER declared `Int` has no binding statement, `own_shape_kind` has
    # nothing to say about it, and before the model-side rule it answered the
    # blob header's neighbour (7 where the caller held 53) on both
    # architectures. CPython raises TypeError, so there is no reading of it that
    # is right.
    #
    # It is a REFUSAL on both backends and the needle is the EVIDENCE clause
    # rather than the word "integer", for two reasons. The clause is what says
    # this is the same construct as the row above rather than a new one — it is
    # the one message both now answer with — and "an integer" appears in the
    # body of the message for reasons that have nothing to do with the base's
    # kind, so a needle on it would pass against a message that had stopped
    # blaming the right thing.
    #
    # The rule asks about `INT_TYPE_CTORS` alone: 198 corpus subscripts have a
    # base some declaration calls a non-pointer and none of them declares an
    # integer — they are `SIMD[…]`, `Span`, `Some`, `Tuple`, `List[Int]`, all
    # real containers whose element walk is right — and this row is what would
    # notice if it grew to ask about "not a pointer" instead.
    ("sub_on_a_parameter_declared_integer_is_refused",
     "def head(e: Int) -> int:\n"
     "    return e[0]\n"
     "def main(n):\n"
     "    var b: Pointer[Int64] = malloc(16)\n"
     "    b[0] = 53\n"
     "    printf(\"a=%d\", head(b))\n"
     "    return 0\n",
     "refuse:is declared 'Int', which is an integer", None),
    # ONE PARAMETER, TWO CONVENTIONS — the disagreement half of
    # `model.parameter_pointee_disagreement_refusal`, which is
    # `frame_holder_disagreement_refusal` one layer down. One call site hands
    # the parameter a declared `Pointer[Int64]` and reads it as MEMORY; the
    # other hands it an unannotated local and reads it as a CONTAINER. The
    # callee gets one convention and both call sites are right about their own,
    # so any single answer is wrong somewhere — and the offset between the two
    # readings is a whole ELEMENT, so the wrong answer is a plausible number
    # rather than a fault.
    #
    # This row cannot exist without the fix above it, which is why it is here
    # and not in a doc: with the annotation choosing the convention, both call
    # sites compiled fine and disagreed at RUN time instead of at build time.
    # The needle is the clause that says a parameter's kind is a property of the
    # whole image, because "two kinds of value" alone would also be produced by
    # a rule that refused every ambiguous parameter.
    ("sub_parameter_reached_two_ways_is_refused",
     "def peek(p) -> int:\n"
     "    return p[0]\n"
     "def main(n):\n"
     "    var b: Pointer[Int64] = malloc(16)\n"
     "    var c = malloc(16)\n"
     "    printf(\"%d\", peek(b) + peek(c))\n"
     "    return 0\n",
     "refuse:One parameter, two kinds of value", None),
]


# ── `%s`, the one printf conversion that DEREFERENCES its argument ───────
#
# Every other conversion reads the word it is handed and renders it; `%s` walks
# bytes at the address until it finds a NUL, so handing it a number is not a
# wrong rendering — it is a walk off the end of whatever the number points into.
#
# `print()` cannot get this wrong: `_print_call` builds the format from each
# operand's kind and refuses the case it cannot tell.  `printf` takes the format
# the SOURCE wrote and hands it to C unchecked, which is what these pin.
PRINTF_TEXT_CASES = [
    # THE reproducer.  Measured on BOTH architectures before the refusal: the
    # build is GREEN, the image runs, prints nothing and dies of SIGSEGV,
    # exit 139, because `%s` walked bytes at address 5 looking for a NUL.  It
    # builds and it runs, which is the shape of failure this backend exists to
    # convert into a message.
    ("printf_s_of_an_integer_is_refused",
     "def main(n):\n"
     "    var a = 5\n"
     "    printf(\"[%s]\", a)\n"
     "    return 0\n",
     "refuse:conversion in printf's format string reads", None),
    # The same thing where the integer is an ARITHMETIC result rather than a
    # literal, because the evidence the refusal rests on is `own_shape_kind`
    # — a statement of this function bound the name to an integer ON THAT
    # STATEMENT'S OWN SHAPE — and `a = 2 + 4` is the shape a corpus program
    # writes.  It faulted identically before.
    ("printf_s_of_an_arithmetic_result_is_refused",
     "def main(n):\n"
     "    var a = 2 + 4\n"
     "    printf(\"[%s]\", a)\n"
     "    return 0\n",
     "refuse:conversion in printf's format string reads", None),
    # THE THREE THAT MUST NOT BE REFUSED, and the second of them is the one
    # that decided the rule.  An UNANNOTATED PARAMETER is a word this build
    # cannot classify, and `show("abc")` through it prints `[abc]` on both
    # architectures — measured.  A rule that read "not known to be text" as
    # "not text" would refuse it, and with it every function in the corpus
    # that takes a string it was never told about, so `None` — the source does
    # not say — is the permissive answer here on purpose.
    ("printf_s_of_a_parameter_a_literal_and_a_bound_string_still_print",
     "def show(s):\n"
     "    printf(\"[%s]\", s)\n"
     "    return 0\n"
     "def main(n):\n"
     "    var s = \"abc\"\n"
     "    show(\"def\")\n"
     "    show(s)\n"
     "    printf(\"[%s]\", \"lit\")\n"
     "    return 0\n", 0, "[def][abc][lit]"),
    # THE VARARG ARITHMETIC, which is the part a scanner gets wrong and which
    # the refusal depends on: the position of a `%s` in the OUTPUT is the
    # position of its argument in the varargs list, and getting that off by one
    # refuses the WRONG argument.  Two things are in this format on purpose and
    # both consume an argument while reading as none:
    #
    #   * `%%` — a literal percent, which `print_literal` doubles so the scanner
    #     can tell it from a conversion.  A scanner that counted it would shift
    #     every later conversion by one;
    #   * `%*d` — a `*` WIDTH, which consumes the `4`.  A scanner that dropped
    #     it would read the SECOND `%s` as the `7`.
    #
    # Both `%s` conversions read a string literal, so a correct scanner finds
    # nothing to refuse and the program prints; a scanner that miscounts lands a
    # `%s` on the integer `7` and the build fails.  The expected bytes are
    # `printf`'s own, checked against the C library on this host.
    ("printf_star_width_and_literal_percent_keep_the_varargs_aligned",
     "def main(n):\n"
     "    printf(\"100%% [%*d] [%s] [%s] %s\", 4, 7, \"a\", \"b\", \"c\")\n"
     "    return 0\n", 0, "100% [   7] [a] [b] c"),
    # A ONE-FIELD STRUCT is the last shape `%s` walked off the end of, and it
    # got past every check because there was nothing to check: a struct of one
    # field has no frame, so `_check_frame_escapes` has no frame ADDRESS to
    # refuse, and the statement that binds the name is a CONSTRUCTION, which
    # `ValueKinds._own_shape_of` counts as no evidence at all. Measured before
    # this case existed, on BOTH architectures from a GREEN build: nothing
    # printed, SIGSEGV, exit 139 — `%s` walking bytes at address 7 looking for
    # a NUL. `model.one_word_value_text_evidence` is what closes it, on the
    # DECLARATION rather than on the integer default.
    ("printf_s_of_a_one_field_struct_is_refused",
     "struct One:\n"
     "    var x: Int\n"
     "\n"
     "def main(n):\n"
     "    var c = One(7)\n"
     "    printf(\"[%s]\", c)\n"
     "    return 0\n",
     "refuse:struct of ONE field has no frame at all", None),
    # The GUARDS, and they are why the fix is not "a name in the one-word table
    # is False for a `%s` conversion".  A one-field struct whose field is a
    # STRING is text, and it worked before this change and works now: `w` IS
    # the `char *`.  And a conversion that does not DEREFERENCE renders the word
    # whatever it is, so `%d` of a one-field Int struct is `7` — which is the
    # same convention `str(c)` and `print(c)` already follow.
    ("printf_s_of_a_one_field_struct_holding_a_string_still_prints",
     "struct W:\n"
     "    var s: String\n"
     "\n"
     "def main(n):\n"
     "    var w = W(\"hi\")\n"
     "    printf(\"[%s]\", w)\n"
     "    return 0\n", 0, "[hi]"),
    ("printf_d_of_a_one_field_struct_renders_the_field",
     "struct One:\n"
     "    var x: Int\n"
     "\n"
     "def main(n):\n"
     "    var c = One(7)\n"
     "    printf(\"[%d]\", c)\n"
     "    return 0\n", 0, "[7]"),
    # The rest of the family, and it is one family: `%s` is the one conversion
    # that DEREFERENCES its argument, so every shape whose word is a number is a
    # walk off the end of it.  Measured on both architectures, from GREEN
    # builds, before this decision existed — SIGSEGV exit 139 in every case:
    #   printf("[%s]", 42)              bytes at address 42
    #   printf("[%s]", 2 + 4)           bytes at address 6
    #   printf("[%s]", str(42))         the word `str()` moved, unchanged
    # `str()` and `String()` are word-for-word IDENTITY conversions here
    # (`printf("[%d]", String(7))` prints 7), so the call's kind table entry —
    # which claims a string — is a claim about the CONVERSION rather than about
    # its operand, and `printf_text_conversion_refusal` asks the operand
    # instead: `model.identity_conversion_operand` + `printf_arg_text_evidence`.
    ("printf_s_of_a_literal_a_binop_and_a_conversion_are_refused",
     "def main(n):\n"
     "    printf(\"[%s]\", 42)\n"
     "    return 0\n",
     "refuse:an EXPRESSION whose own shape holds a number", None),
    ("printf_s_of_an_arithmetic_expression_is_refused",
     "def main(n):\n"
     "    printf(\"[%s]\", 2 + 4)\n"
     "    return 0\n",
     "refuse:an EXPRESSION whose own shape holds a number", None),
    ("printf_s_of_a_conversion_of_a_number_is_refused",
     "def main(n):\n"
     "    printf(\"[%s]\", str(42))\n"
     "    return 0\n",
     "refuse:an EXPRESSION whose own shape holds a number", None),
    # And the GUARD for that unwrapping: a conversion of TEXT is text, and the
    # unwrapping must not cost that.  Without the guard, "a conversion is its
    # operand" would read as "a conversion is never text", and every
    # `String(s)` in the corpus would be refused.
    ("printf_s_of_a_conversion_of_a_string_still_prints",
     "def main(n):\n"
     "    var s = \"abc\"\n"
     "    printf(\"[%s][%s][%s]\", String(s), str(s), String(\"lit\"))\n"
     "    return 0\n", 0, "[abc][abc][lit]"),
    # ── A CONVERSION WITH NO ARGUMENT BEHIND IT ─────────────────────────────
    #
    # The same family, from the other end: not the wrong argument for a
    # conversion but NO argument for one.  `% d` — a space flag and `d` — is a
    # complete conversion specification, which is the shape that occurs in
    # prose ("50% done") and is therefore the one a corpus is most likely to
    # contain.  Measured on BOTH architectures from the same source, with the
    # refusal lifted:
    #
    #     arm64    50 0one
    #     x86-64   50143074168one
    #
    # Both read a vararg nobody passed, and NEITHER is the lenient answer the
    # arm64 output reads as: arm64's unnamed arguments come from the stack area
    # at `[SP]` as it stands at the call, and on this host that word is zero, so
    # `% d` prints its flag and a `0`.  x86-64 passes varargs in the
    # caller-saved argument registers, so it prints what the previous call left
    # there — the two digits are not even the same twice in one run.  A refusal
    # is the honest answer for both, and it has to be the SAME one, because a
    # format string the two machines read differently is the failure this
    # backend exists to prevent.
    ("printf_conversion_with_no_operand_is_refused",
     "def main(n):\n"
     "    printf(\"50% done\\n\")\n"
     "    return 0\n",
     "refuse:read a vararg nobody passed", None),
    # The same construct reached from an ESCAPE, which is the reason to do this
    # now rather than later: a string literal's escapes are decoded before the
    # format is interned, so `\x25` IS a percent sign at the call, and a check
    # that scanned the literal's raw body would find no `%` in `\x25 done` at
    # all.  Both backends hand the refusal the DECODED format for exactly this
    # reason — the same decode-then-transform order `print_literal` gives its
    # own reason for — and this row is what holds that half of it.
    ("printf_conversion_that_arrives_from_an_escape_is_refused",
     "def main(n):\n"
     "    printf(\"\\x25 done\\n\")\n"
     "    return 0\n",
     "refuse:read a vararg nobody passed", None),
    # A callee whose format is NOT the first argument, so the check has to find
    # the format rather than assume `args[0]`: `sprintf`'s buffer is argument 0
    # and its format is argument 1.  Measured with the refusal lifted on both
    # architectures, `sprintf(b, "%d")` printed a number built out of whatever
    # was in the unnamed area.  `model.printf_format_arg_index` DERIVES the
    # index from `VARIADIC_LIBC`'s own count of named arguments rather than
    # carrying a second table, which is what stops `sprintf` and `snprintf`
    # (three named) from being read the same way.
    ("printf_conversion_with_no_operand_is_refused_in_sprintf",
     "def main(n):\n"
     "    var b = String()\n"
     "    sprintf(b, \"%d\")\n"
     "    return 0\n",
     "refuse:read a vararg nobody passed", None),
    # THE CONTROL, and it is what stops the three rows above being satisfied by
    # a refusal of `printf` itself rather than by the arithmetic: the same
    # format with its operand builds and runs on both machines and prints what
    # the source says.  `% d` here really is `%d` with a flag, and the space
    # flag's output is the point — a `0` here is the flag plus the digit, and
    # it is the SOURCE's `0`.
    ("printf_space_flag_with_its_operand_still_prints",
     "def main(n):\n"
     "    printf(\"[% d]\\n\", 0)\n"
     "    return 0\n", 0, "[ 0]"),
    # The off-by-one guard, and it is the row that says the COUNT is arithmetic
    # rather than "there is a `%` in it somewhere".  Two conversions, one
    # operand: the `%d` is satisfied and the `%s` is not, so the string
    # conversion reads a vararg nobody passed and walks bytes at whatever word
    # it finds.  A count that stopped at the first conversion would call this
    # well-formed, and a count that started at the `%s` would be caught by the
    # neighbouring rule instead of this one — which is why this row's needle is
    # the missing-operand sentence and not the `%s` one.
    ("printf_one_short_of_two_conversions_is_refused",
     "def main(n):\n"
     "    printf(\"%d %s\\n\", 7)\n"
     "    return 0\n",
     "refuse:read a vararg nobody passed", None),
    # And `print`, which BUILDS its format rather than being handed one, must
    # keep working: `print_literal` doubles every `%`, so `50% done` reaches
    # `printf` as `50%% done` — zero conversions, zero operands — and the same
    # refusal above sees the generated call and finds nothing wrong.  A fix that
    # swept the two spellings together would break the one that already works,
    # so this row is here to say so.
    ("print_doubles_the_percent_and_is_not_refused",
     "def main(n):\n"
     "    print(\"50% done\")\n"
     "    print(\"100%\")\n"
     "    return 0\n", 0, "50% done\n100%"),
    # A SUBSCRIPT of a string, and the last shape the family had: `s[0]` is a
    # BYTE on this path — a string is a bare `char *` and both emitters load one
    # byte out of it (`_emit_subscript_load`'s `LDRB` at width 1) — so the value
    # kind of `s[i]` is an integer, and the kind table did not say so: `s[0]` is
    # a `SubscriptExpr`, `kind_of` asked `list_elem_kind` of a `char *`, a string
    # is not a blob, and the answer was NOTHING.  Nothing is the permissive
    # direction everywhere it is read, so the row above never fired.  Measured on
    # BOTH architectures before this case existed, from GREEN builds: nothing
    # printed and SIGSEGV, exit 139 — `%s` walking bytes at address 97 looking
    # for a NUL.  `model.subscript_element_kind` is what closes it, by making
    # the model say what the representation already is.
    ("printf_s_of_a_string_byte_is_refused",
     "def main(n):\n"
     "    var s = \"abc\"\n"
     "    printf(\"[%s]\", s[0])\n"
     "    return 0\n",
     "refuse:conversion in printf's format string reads", None),
    # THE GUARD, and the reason the byte is a fact rather than a defect to
    # refuse: a conversion that does not DEREFERENCE renders the word whatever it
    # is, so `%d` of `s[0]` is 97 — `'a'` — and `s[0] == 97` is true.  If the
    # subscript rule ever turned a byte into a refusal by the back door, this is
    # the row that says so.  The two BUILDING rows of this rule are in
    # `BOTH_ARCH_CASES`, because they have to run on both machines to be an
    # assertion about the representation rather than about one emitter.
    # …and `len` of the byte, which is the third reader of the same fact and the
    # one that goes from "the source does not say" to an honest refusal.  Before
    # the rule the answer was the permissive one; the needle is the sentence
    # about an integer, so a reader can tell which of the two messages this is.
    ("len_of_a_string_byte_is_refused",
     "def main(n):\n"
     "    var s = \"abc\"\n"
     "    printf(\"[%d]\", len(s[0]))\n"
     "    return 0\n",
     "refuse:an integer has no length", None),
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
    # The same parameter with NO annotation, which is the ordinary Mojo
    # spelling and used to print `1 1`: `ValueKinds` seeds an unannotated
    # parameter as a WORD (a word is an integer here, which is right for every
    # kind except a string), and the identity test then says the empty string is
    # non-empty. The fix is the call site's argument kind propagated into the
    # callee — `model.string_parameters_by_call_site`, UNANIMOUS over every call
    # site of the name in the image.
    ("truthy_unannotated_parameter_from_a_string_literal",
     "def f(s):\n"
     "    if s:\n"
     "        return 1\n"
     "    return 0\n"
     "def main(n):\n"
     "    printf(\"%d %d\", f(\"\"), f(\"x\"))\n"
     "    return 0\n", 0, "0 1"),
    # The two directions the rule must NOT take, and both are the conservative
    # one. The evidence is UNANIMOUS over every call site of the NAME in the
    # image, so one disagreeing site removes the claim for the whole function —
    # `f` below is called with a string, an integer and a string-returning
    # callee, and all three answers are the identity test's. That is the rule
    # rather than an accident: a parameter that is a `char *` at one call site
    # and a word at another is a word, and answering per site would need a
    # per-site compilation this path does not do.
    ("truthy_unannotated_parameter_needs_every_site_to_agree",
     "def f(s):\n"
     "    if s:\n"
     "        return 1\n"
     "    return 0\n"
     "def g(s):\n"
     "    if s:\n"
     "        return 1\n"
     "    return 0\n"
     "def mk() -> String:\n"
     "    return \"abc\"\n"
     "def main(n):\n"
     "    printf(\"%d %d %d %d\", f(\"\"), f(5), f(mk()), g(mk()))\n"
     "    return 0\n", 0, "1 1 1 1"),
    # The same evidence from a call rather than a literal, in isolation, so the
    # row above's unanimity is the only thing that distinguishes the two: `g` is
    # called with a string-returning callee at both its sites, so its parameter
    # IS a string — and a `def` that DECLARES the return type is the declaration
    # this path reads.
    ("truthy_unannotated_parameter_from_a_string_returning_callee",
     "def g(s):\n"
     "    if s:\n"
     "        return 1\n"
     "    return 0\n"
     "def mk() -> String:\n"
     "    return \"abc\"\n"
     "def main(n):\n"
     "    printf(\"%d %d\", g(mk()), g(mk()))\n"
     "    return 0\n", 0, "1 1"),
    # …and a KEYWORD binds the parameter it names rather than a position, so it
    # is evidence too. The mixed case (positionals AND keywords at one call site)
    # is deliberately not read: the positionals bind parameters this rule does
    # not enumerate, and guessing them would be a claim about a signature.
    ("truthy_unannotated_parameter_bound_by_keyword",
     "def f(s):\n"
     "    if s:\n"
     "        return 1\n"
     "    return 0\n"
     "def main(n):\n"
     "    printf(\"%d %d\", f(s=\"\"), f(s=\"x\"))\n"
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
    # ── THE LOOP VARIABLE'S KIND: an ELEMENT, not the container ────────────
    #
    # The row above is over a NAME, so it says nothing about what a loop
    # variable holds — and that is the gap these two close. `ValueKinds`
    # classified the target of `for x in ["p", "", "q"]` as `list:str`, the
    # LIST's kind, so every reader of a container took it at its word:
    #
    #   * `if x:` → `truthy_lowering`'s TRUTHY_FROM_BLOB_FIELD, which is ONE
    #     LOAD FROM OFFSET 0. For a `char *` that load reads the eight bytes of
    #     `__TEXT,__text` that FOLLOW the terminating NUL — so whether the
    #     empty string came out truthy depended on which other string the
    #     linker happened to intern next to it. Measured on both backends
    #     before the fix, `for x in ["p", "", "q"]: if x: c = c + 1` returned
    #     3 where CPython returns 2.
    #   * `len(x)` → the same load, so it returned a number made of the string's
    #     own bytes: 2013266032 = 0x78000070 for "p", which is `p\0` and the
    #     first three bytes of the next interned string.
    #
    # 3 and 2 are the only two small answers available, and the pre-change
    # number is on the other side of the one-byte boundary from the correct
    # one, so a fixed build cannot reach it by accident.
    ("truthy_for_loop_variable_over_strings",
     "def main(n):\n"
     "    var c = 0\n"
     "    for x in [\"p\", \"\", \"q\"]:\n"
     "        if x:\n"
     "            c = c + 1\n"
     "    printf(\"%d\", c)\n"
     "    return 0\n", 0, "2"),
    # The `else` half, because the two-element list is where the pre-change
    # build was ACCIDENTALLY right: the empty string's interned bytes happened
    # to be adjacent to their own NUL, so offset 0 read zero and the else arm
    # ran. 101 is `then` once and `else` once; 2 or 200 would mean the guard
    # never moved.
    ("truthy_for_loop_variable_else_arm",
     "def main(n):\n"
     "    var c = 0\n"
     "    for x in [\"p\", \"\"]:\n"
     "        if x:\n"
     "            c = c + 1\n"
     "        else:\n"
     "            c = c + 100\n"
     "    printf(\"%d\", c)\n"
     "    return 0\n", 0, "101"),
    # The INTEGER row, and it is the one that CRASHED rather than answered
    # wrongly: with the target classified `list:int`, `if x:` took the count
    # field — `LDR [x, #0]` with X0 holding the integer 1 — so
    # `for x in [1, 0, 2]: if x:` died of SIGSEGV on both backends. An integer
    # is 0 or it is not, so the identity test is the answer and it is what the
    # element kind restores.
    ("truthy_for_loop_variable_over_ints",
     "def main(n):\n"
     "    var c = 0\n"
     "    for x in [1, 0, 2]:\n"
     "        if x:\n"
     "            c = c + 1\n"
     "    printf(\"%d\", c)\n"
     "    return 0\n", 0, "2"),
    # GUARD, and the reason it passes on the pre-change tree too: the target of
    # `for row in [[1, 2], [3, 4]]` IS a blob, and `len(row)` answers from its
    # count field. The nested-container arm of the element kind is what keeps it
    # that way — without it the target kind would fall to the word default and
    # `len` of a program that has always worked would start refusing.
    # 2 + 2 = 4.
    ("truthy_nested_loop_variable_keeps_its_blob",
     "def main(n):\n"
     "    var s = 0\n"
     "    for row in [[1, 2], [3, 4]]:\n"
     "        s = s + len(row)\n"
     "    printf(\"%d\", s)\n"
     "    return 0\n", 0, "4"),
    # ── THE COMPREHENSION'S OWN SCOPE ──────────────────────────────────────
    #
    # A comprehension has its own scope in Python 3, so its loop variable is
    # not a local of the enclosing function and `ValueKinds.locals` must not
    # answer for it. It did not answer at all: `_scan` binds a `for` statement's
    # target and has no `Comprehension` arm, so the target was in no kind map
    # and `if x:` fell to TRUTHY_NONZERO — a null test on the ADDRESS of the
    # empty string. Measured on both backends before the fix, exactly as the
    # `for` row above:
    # `[x for x in ["p", "", "q"] if x]` had THREE elements where CPython
    # builds two.
    #
    # It is an OVERLAY rather than a `_bind` into `locals`, and this row is why
    # that matters: binding `x` into the function's map beside `var x = 5` would
    # file two bindings that do not meet as a conflict, cost the OUTER `x` the
    # integer kind it has here, and leave the comprehension with a word. The
    # outer `x` must stay an integer (c = 1) and the comprehension must still
    # filter (r = 2), and both are asserted here.
    ("comprehension_target_is_its_own_scope",
     "def main(n):\n"
     "    var x = 5\n"
     "    var r = [x for x in [\"p\", \"\", \"q\"] if x]\n"
     "    var c = 0\n"
     "    if x:\n"
     "        c = c + 1\n"
     "    printf(\"%d %d\", len(r), c)\n"
     "    return 0\n", 0, "2 1"),
    # The SAME scope read by the ELEMENT rather than by the guard, and it is a
    # capability as well as a correctness row: `len(k)` over a comprehension
    # target used to be REFUSED for want of a kind ("the source does not say
    # what this operand holds"), and it is a `strlen` now. 2 + 0 + 3 = 5.
    ("comprehension_target_kind_is_visible_to_the_element",
     "def main(n):\n"
     "    var r = [len(k) for k in [\"aa\", \"\", \"bbb\"]]\n"
     "    printf(\"%d %d %d\", len(r), r[0], r[2])\n"
     "    return 0\n", 0, "3 2 3"),
    # A DICT comprehension's KEY is the element and its VALUE is `.key` (the
    # parser's swap), so both sites are inside the scope — and `len(k)` in the
    # value position is the one that would be missed if only the element were
    # routed. 3 pairs, d["aa"] = 2, d["bbb"] = 3.
    ("comprehension_scope_reaches_both_dict_spellings",
     "def main(n):\n"
     "    var d = {k: len(k) for k in [\"aa\", \"\", \"bbb\"]}\n"
     "    printf(\"%d %d %d\", len(d), d[\"aa\"], d[\"bbb\"])\n"
     "    return 0\n", 0, "3 2 3"),
    # GUARD: a comprehension over an iterable this path cannot describe is
    # exactly as unanswerable as it was before the overlay — the overlay claims
    # a kind only from `_iterable_own_shape`, so `for x in a` over a parameter
    # falls through to the function's own map and then to TRUTHY_NONZERO. That
    # is the right answer for integers and the reason the row is 3 and not a
    # refusal.
    ("comprehension_over_a_parameter_is_unchanged",
     "def pick(n, a):\n"
     "    var b = [x for x in a if x]\n"
     "    return len(b)\n"
     "\n"
     "def main(n):\n"
     "    return pick(0, [1, 0, 2])\n", 2, None),
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

    # ── WHAT A `for … in range(…)` LEAVES IN ITS COUNTER ────────────────────
    #
    # Found by `tools/formal_fuzz.py` (its seed 1 reduces to the first row
    # below), and it was a SILENT wrong answer on both architectures: the loop
    # tests the counter before it advances it, so the exit path arrives one past
    # the last value the body saw, and `for i in range(0, 3)` left `i == 3`
    # where CPython leaves 2. Nothing else in this file read a range counter
    # after its loop, which is why ~700 hand-written cases never saw it.
    #
    # Every row's expected value is CPython's, and the arithmetic is in the row
    # rather than taken on trust. The counter after a loop is CPython's LAST
    # BOUND value, which for a step of 2 is not one less than the exit value.
    #
    # The ONE case that was still wrong, and it was a doc rather than a row here
    # because pinning "prints 0" where CPython prints 7 would have made the
    # defect the expectation. CPython's `for` binds the target only when the
    # iteration PRODUCES a value, so a range that yields nothing must leave a
    # name that already held one alone — and `for i in range(0, 0)` stored
    # `start` into the counter before testing it, on both architectures. The
    # emitters' head test now reads `range()`'s own start and the store is
    # emitted after it (`_emit_loop`, per backend), which is the only layout
    # that can produce CPython's answer.
    ("both_arch_empty_for_range_leaves_a_preassigned_counter",
     "def main(n):\n"
     "    i = 7\n"
     "    for i in range(0, 0):\n"
     "        x = 1\n"
     "    printf(\"i=%d\", i)\n"
     "    return 0\n", 0, "i=7"),
    # The same rule where the emptiness is a RUN-TIME fact, which is the shape
    # that matters: `range(0, 0)` could be folded at compile time and `k`
    # cannot, and a fix that only handled the literal would have looked complete.
    ("both_arch_runtime_empty_for_range_leaves_a_preassigned_counter",
     "def main(n):\n"
     "    k = n\n"
     "    if k > 3:\n"
     "        k = 0\n"
     "    i = 7\n"
     "    for i in range(0, k):\n"
     "        x = 1\n"
     "    printf(\"i=%d\", i)\n"
     "    return 0\n", 0, "i=7"),
    # A DESCENDING empty range, which is a second spelling of the same fact and
    # the one the parser makes harder: `-1` is `UnaryOp('-', IntLiteral(1))`,
    # so a reader that only folds `IntLiteral` cannot see that `range(0, 5, -1)`
    # yields nothing. That is `_range_is_nonempty`'s business in `formal/model.py`
    # and this row is what says the two agree about the ANSWER.
    ("both_arch_descending_empty_for_range_leaves_a_preassigned_counter",
     "def main(n):\n"
     "    i = 7\n"
     "    for i in range(0, 5, -1):\n"
     "        x = 1\n"
     "    printf(\"i=%d\", i)\n"
     "    return 0\n", 0, "i=7"),
    # The `else` arm is the other reader of the counter after an empty loop,
    # and it runs on the very path where the loop did not, so it is where a
    # store-then-test head test is visible a second time.
    ("both_arch_empty_for_range_else_sees_the_preassigned_counter",
     "def main(n):\n"
     "    i = 7\n"
     "    for i in range(0, 0):\n"
     "        x = 1\n"
     "    else:\n"
     "        printf(\"else i=%d\", i)\n"
     "    return 0\n", 0, "else i=7"),
    # …and the counter in a FUNCTION, where it is a spill slot rather than a
    # register, so the store that moved cannot pass by working on the register
    # home only.
    ("both_arch_empty_for_range_over_a_spilled_counter",
     "def last():\n"
     "    i = 7\n"
     "    for i in range(0, 0):\n"
     "        x = 1\n"
     "    return i\n"
     "\n"
     "def main(n):\n"
     "    printf(\"i=%d\", last())\n"
     "    return 0\n", 0, "i=7"),
    # THE OTHER HALF, and the reason this is not "store nothing for an empty
    # range": a name NOTHING else binds is UNBOUND after such a loop, CPython
    # raises UnboundLocalError for it, and an emitted image has no way to say
    # so — so the read has to be the refusal the "Read before store" analysis
    # exists to be, by name, on both architectures. Before the head test moved,
    # this program printed 0; with the move and no analysis to match it, it
    # printed the caller's leftover register, which is the failure the refusal
    # exists to prevent (and differed between the two backends).
    ("both_arch_read_of_a_counter_an_empty_range_never_bound_is_refused",
     "def main(n):\n"
     "    for q in range(0, 0):\n"
     "        x = 1\n"
     "    printf(\"q=%d\", q)\n"
     "    return 0\n",
     "refuse:'q' is read at line", None),
    ("both_arch_for_range_leaves_the_counter_at_the_last_value_it_bound",
     "def main(n):\n"
     "    for i in range(0, 3):\n"
     "        x = 1\n"
     "    printf(\"i=%d\", i)\n"
     "    return 0\n", 0, "i=2"),
    ("both_arch_for_range_step_leaves_the_counter_one_step_back",
     "def main(n):\n"
     "    for i in range(0, 5, 2):\n"
     "        x = 1\n"
     "    printf(\"i=%d\", i)\n"
     "    return 0\n", 0, "i=4"),
    ("both_arch_for_range_descending_leaves_the_counter_at_the_last_value",
     "def main(n):\n"
     "    for i in range(3, 0, -1):\n"
     "        x = 1\n"
     "    printf(\"i=%d\", i)\n"
     "    return 0\n", 0, "i=1"),
    # `break` leaves the counter where the body last had it, which is the last
    # value CPython bound — so the restore on the exit path must NOT run for a
    # break, or this row would print 1.
    ("both_arch_for_range_break_leaves_the_counter_where_break_ran",
     "def main(n):\n"
     "    for i in range(0, 9):\n"
     "        if i == 2:\n"
     "            break\n"
     "    printf(\"i=%d\", i)\n"
     "    return 0\n", 0, "i=2"),
    # `continue` re-enters through the counter advance, so the value after the
    # loop is the last one the TEST rejected — here 4, since `range(0, 5)` last
    # yielded 3 and the skipped `continue` on 4 still advanced and tested.
    ("both_arch_for_range_continue_advances_before_it_tests_again",
     "def main(n):\n"
     "    for i in range(0, 5):\n"
     "        if i == 4:\n"
     "            continue\n"
     "        x = 1\n"
     "    printf(\"i=%d\", i)\n"
     "    return 0\n", 0, "i=4"),
    # …and the `else` arm runs on exhaustion, with the counter already restored,
    # so the two are asserted together rather than one at a time.
    ("both_arch_for_range_else_runs_with_the_counter_already_restored",
     "def main(n):\n"
     "    for i in range(0, 3):\n"
     "        x = 1\n"
     "    else:\n"
     "        printf(\"else i=%d\", i)\n"
     "    return 0\n", 0, "else i=2"),
    # The loop in a FUNCTION, which is where the counter is a spill slot rather
    # than a register: the restore has to go through the same load/operate/store
    # path the advance does, and a fix that only handled the register home would
    # pass every row above and fail this one.
    ("both_arch_for_range_restores_a_spilled_counter_too",
     "def last(k):\n"
     "    s = 0\n"
     "    for i in range(0, k):\n"
     "        s = s + i\n"
     "    return i\n"
     "\n"
     "def main(n):\n"
     "    printf(\"i=%d\", last(4))\n"
     "    return 0\n", 0, "i=3"),
    # NESTED: the inner loop's restore must not disturb the outer counter, which
    # is the value the outer loop keeps testing. Both were one past before.
    ("both_arch_nested_for_range_restores_only_its_own_counter",
     "def main(n):\n"
     "    for i in range(0, 2):\n"
     "        for j in range(0, 3):\n"
     "            x = j\n"
     "    printf(\"i=%d j=%d\", i, j)\n"
     "    return 0\n", 0, "i=1 j=2"),
    # A `while` is untouched by the fix and says so: its counter is the user's
    # own increment, so there is nothing to restore and this row must not move.
    ("both_arch_while_counter_is_unchanged_by_the_for_range_fix",
     "def main(n):\n"
     "    i = 0\n"
     "    while i < 3:\n"
     "        i = i + 1\n"
     "    printf(\"i=%d\", i)\n"
     "    return 0\n", 0, "i=3"),

    # ── a FLEXIBLE type is not an UNSIGNED one ─────────────────────────────
    #
    # Found by `tools/formal_fuzz.py` (its seed 206 reduces to the last row
    # below), and it was silent on both architectures. `infer_expr` returns
    # `None` for an expression with no declared type — a bare literal, or an
    # operator whose operands are both typeless — and `None` means "this value
    # takes the type of its context", not "this value is unsigned". Reading it
    # as unsigned made `print` choose `%llu`, so `print(0 - 3)` printed
    # 18446744073709551613. The confusing part, and the reason a hand-written
    # case did not catch it: `v = 0 - 3; print(v)` printed `-3` all along,
    # because an ASSIGNMENT resolves the flexible type to the default. The
    # difference had no name in the source — only whether the expression was
    # printed directly or bound first.
    #
    # `types.cmp_signed` is the one decision both backends and both proof
    # generators read, so this is a single change with a single blast radius;
    # these rows are the four places it reached.
    ("both_arch_print_of_a_flexible_negation_is_signed",
     "def main(n):\n"
     "    print(0 - 3)\n"
     "    return 0\n", 0, "-3"),
    ("both_arch_print_of_a_flexible_folded_negation_is_signed",
     "def main(n):\n"
     "    print(-(1 + 2))\n"
     "    return 0\n", 0, "-3"),
    # The comparison half, and the row that matters most: a constant expression
    # with no declared type was compared with UNSIGNED condition codes, so
    # `(0 - 5) < 3` was FALSE — `-5` was 0xFFFF…FB. Both directions are here
    # because a fix that made every constant comparison signed would pass the
    # first and fail nothing here.
    ("both_arch_a_constant_comparison_is_signed_in_both_directions",
     "def main(n):\n"
     "    printf(\"%d %d\", 1 if (0 - 5) < 3 else 0,"
     " 1 if (0 - 5) > 3 else 0)\n"
     "    return 0\n", 0, "1 0"),
    # The row the fuzzer reduced to: a negation of a REMAINDER. `%` returns a
    # typeless value (both operands typeless), so `-(…)` was flexible and
    # printed unsigned: 18446744073709551614 where CPython prints -2.
    ("both_arch_print_of_a_negated_flexible_remainder_is_signed",
     "def main(n):\n"
     "    print(-(2 % 5))\n"
     "    return 0\n", 0, "-2"),
    # THE GUARD, and it is the row that decides whether the fix is safe rather
    # than a blanket "everything is signed": a DECLARED unsigned type still
    # reads as unsigned, because `common_type` treats a flexible operand as
    # neutral and the declared `UInt32` is what decides. Without this row a
    # change that resolved every `None` to signed without asking `common_type`
    # first would pass all four above.
    ("both_arch_a_declared_unsigned_operand_is_still_unsigned",
     "def main(n):\n"
     "    x: UInt32 = 7\n"
     "    y: UInt32 = 2\n"
     "    x = x - 4\n"
     "    printf(\"%d %d\", 1 if x > y else 0, x)\n"
     "    return 0\n", 0, "1 3"),
    # …and the assignment half, which was never wrong and must stay right: it
    # is what made the defect look like a `print` bug.
    ("both_arch_a_bound_flexible_negation_was_always_signed",
     "def main(n):\n"
     "    v = 0 - 3\n"
     "    printf(\"%d\", v)\n"
     "    return 0\n", 0, "-3"),
    # ── a NEGATIVE CONSTANT beside a DECLARED UNSIGNED operand ────────────
    #
    # The four rows above are about a flexible value whose context says
    # NOTHING about its sign: `cmp_signed` resolves `None` to the signed
    # default, which is what makes them answer. This pair is the case that
    # resolution cannot reach, because here the context DOES say — `x: UInt32`
    # is a declared unsigned type, `common_type` treats the flexible operand as
    # neutral, and the declared type is what decides. So `(0 - 3) < x` compares
    # 0xFFFF...FD against 7 with unsigned condition codes and answers FALSE
    # where CPython answers TRUE.
    #
    # `formal/types.py`'s `_negative_constant_type` is the fix and the ONE
    # reader of the question: a value the build can FOLD and knows to be
    # negative cannot be unsigned, whichever of the two spellings wrote it.
    # Both rows below are that one rule on the two shapes it applies to, and
    # the `x < …` half of each is the direction a "fix" that only ever
    # special-cased the left operand would get backwards.
    ("both_arch_a_negated_folded_constant_beside_a_declared_unsigned_operand_is_signed",
     "def main(n):\n"
     "    x: UInt32 = 7\n"
     "    printf(\"%d %d %d\", 1 if -(1 + 2) < x else 0, 1 if x < -(1 + 2) else 0,"
     " 1 if -(1 + 2) == x else 0)\n"
     "    return 0\n", 0, "1 0 0"),
    # The BINARY spelling of the same value, which is the row the reduction of
    # this family stopped at: `(0 - 3)` folds negative through `fold_literal_expr`
    # rather than through the unary rule, and both spellings must land in the same
    # place. It is here as the regression guard for the second reader of the one
    # folder, not as a row that was ever wrong.
    ("both_arch_a_folded_negative_beside_a_declared_unsigned_operand_is_signed",
     "def main(n):\n"
     "    x: UInt32 = 7\n"
     "    printf(\"%d %d %d\", 1 if (0 - 3) < x else 0, 1 if x < (0 - 3) else 0,"
     " 1 if (0 - 3) == x else 0)\n"
     "    return 0\n", 0, "1 0 0"),
    # `~` is the OTHER unary spelling and the folder folds it, so the rule
    # reaches it without a second test: `~3` is -4. Before, only `-` with a
    # bare `IntLiteral` operand was answered, which is why `-3` was right and
    # `-(1 + 2)` was not — the same value, two answers.
    ("both_arch_a_bit_not_of_a_constant_beside_a_declared_unsigned_operand_is_signed",
     "def main(n):\n"
     "    x: UInt32 = 7\n"
     "    printf(\"%d %d %d\", 1 if ~3 < x else 0, 1 if x < ~3 else 0,"
     " 1 if ~3 == x else 0)\n"
     "    return 0\n", 0, "1 0 0"),
    # …and the guard, which is the row that decides the fix is a SIGN and not a
    # blanket "constants are signed": a POSITIVE constant beside a declared
    # unsigned operand takes that operand's type, and `x: UInt8 = 200` read as
    # a SIGNED byte would be -56 — so this row answers 1 unsigned and 0 signed,
    # and it is the row a fix that made every foldable operand signed 64-bit
    # would move. (CPython cannot express the case — it has no `UInt8` — so the
    # row asserts what the language says rather than what CPython prints, which
    # is what makes it a guard on the promotion and not an oracle.)
    ("both_arch_a_positive_constant_beside_a_declared_unsigned_operand_is_unsigned",
     "def main(n):\n"
     "    x: UInt8 = 200\n"
     "    printf(\"%d\", 1 if (0 + 100) < x else 0)\n"
     "    return 0\n", 0, "1"),
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


# Cases whose program must STOP AT RUN TIME, saying WHY on stderr.
#
# The other 600-odd cases in this file assert an exit status and a stdout, which
# is the right assertion for a program that computes an answer. It cannot
# express "the program refused to compute, and here is the limit it hit", and a
# run-time stop used to have exactly no way to say so: the bound was checked at
# run time and enforced with a bare `exit(1)`, so the whole observable was a
# nonzero status and an empty stderr. A reader who hit that had nothing to go on
# but the source, and every other bounded-container stop on this path names its
# bound.
#
# So this group exists to pin the MESSAGE, on both architectures and byte for
# byte against each other — two machines naming one limit differently is the
# failure this file's CPython-pair group was created for, and a diagnostic
# diverging by architecture is the same defect with a different subject.
#
# (name, mojo_source, want_exit, stderr_needles)
STDERR_CASES = [
    # `xs.append` in a loop, past the capacity the append-site scan reserved.
    # One site, three executions, and the capacity is ONE — which is the whole
    # bargain `formal/model.py`'s `BUILTIN_VALUE_METHODS` entry for `append`
    # states, so the case is not a pathological program but the shape every
    # loop that accumulates a list has.
    #
    # The three needles are chosen to be load-bearing rather than decorative:
    # the name says which list, the capacity says which number was exceeded, and
    # "append SITES" says the rule behind it — a message that said only "list
    # overflow" would leave a reader unable to tell this from a frame-budget
    # refusal (`frame_blob_refusal`), which has a different and differently
    # fixable remedy.
    ("list_append_overflow_is_loud",
     "def main(n):\n"
     "    xs = []\n"
     "    var i = 0\n"
     "    while i < 3:\n"
     "        xs.append(7)\n"
     "        i = i + 1\n"
     "    printf(\"n=%d\", len(xs))\n"
     "    return 0\n",
     1, ["list.append overflowed 'xs'", "its capacity is 1", "append SITES"]),
    # `d[k] = v` for a key the blob does NOT hold, which is CPython's INSERT and
    # used to be a key scan that missed and stopped the program having printed
    # nothing. The reservation is `formal/model.py`'s `dict_store_capacity` —
    # the pairs the literal wrote plus one per `d[k] = v` SITE in the function
    # that built it — so the three needles are the same three the append case
    # asks for and for the same reason: a message that said only "dict overflow"
    # would leave a reader unable to tell this from a frame-budget refusal, which
    # has a different remedy.
    #
    # `i` is the INDEX, so every execution is a DIFFERENT key and the reservation
    # of one pair is genuinely exceeded — the shape `xs.append` in a loop has,
    # and the reason the guard is a run-time check rather than a refusal.
    ("dict_store_past_its_reservation_is_loud",
     "def main(n):\n"
     "    d = {\"a\": 1}\n"
     "    var i = 0\n"
     "    while i < 3:\n"
     "        d[i] = i\n"
     "        i = i + 1\n"
     "    printf(\"n=%d\", len(d))\n"
     "    return 0\n",
     1, ["dict store into 'd' overflowed", "its capacity is 2 pairs",
         "SITE"]),
    # The OTHER half of the two sentences, and it is a different problem with a
    # different repair: this blob's pairs were written by ANOTHER function, so
    # this build never saw them and has no reservation to add to. The needle set
    # says which of the two it is, because a reader who is told "cannot reserve"
    # and not which of the two reasons would go and look at the wrong thing.
    ("dict_store_into_a_blob_this_build_cannot_size_is_loud",
     "def fill(d: Dict[String, Int], k: String, v: Int):\n"
     "    d[k] = v\n\n"
     "def main(n):\n"
     "    var t = {\"a\": 1}\n"
     "    fill(t, \"b\", 2)\n"
     "    printf(\"b=%d\", t[\"b\"])\n"
     "    return 0\n",
     1, ["dict store of 'k' into 'd'", "cannot reserve",
         "not built by a dict LITERAL"]),
]

# `d[k] = v` INSERTS, and these are the answers CPython gives. They are in
# `CASES` rather than in a dict-shaped suite because the construct is a STORE
# and every store on this path goes through `_emit_subscript_store_reg`, which
# is where the shape that is not this one — "compute an address and store
# through it" — lives: on a miss there is no address to return, because the
# store IS the insert.
#
# `dict_store_of_a_present_key_is_the_control` is what keeps a "fix" that
# refuses every dict store from passing: that program computed correctly before
# this change and still does.
DICT_STORE_CASES = [
    ("dict_store_of_a_new_key_inserts",
     "def main(n):\n"
     "    d = {}\n"
     "    d[\"x\"] = 3\n"
     "    printf(\"v=%d n=%d\", d[\"x\"], len(d))\n"
     "    return 0\n", 0, "v=3 n=1"),
    ("dict_store_of_an_absent_key_after_a_literal_inserts",
     "def main(n):\n"
     "    d = {\"a\": 1}\n"
     "    d[\"b\"] = 2\n"
     "    d[\"a\"] = 7\n"
     "    printf(\"a=%d b=%d n=%d\", d[\"a\"], d[\"b\"], len(d))\n"
     "    return 0\n", 0, "a=7 b=2 n=2"),
    ("dict_store_of_a_present_key_is_the_control",
     "def main(n):\n"
     "    d = {\"a\": 1, \"b\": 2}\n"
     "    d[\"a\"] = 7\n"
     "    printf(\"a=%d n=%d\", d[\"a\"], len(d))\n"
     "    return 0\n", 0, "a=7 n=2"),
    # Through a `Dict[…]` PARAMETER, to a key the table HOLDS: the blob was
    # built elsewhere, so there is no reservation here — and the store is still
    # correct, because a key that is present takes the scan's hit arm on both
    # backends and never reaches the capacity check. This is the case that says
    # the reservation is an INSERT's requirement and not a STORE's.
    ("dict_store_through_a_dict_parameter_of_a_present_key",
     "def fill(d: Dict[String, Int], k: String, v: Int):\n"
     "    d[k] = v\n\n"
     "def main(n):\n"
     "    var t = {\"a\": 1}\n"
     "    fill(t, \"a\", 9)\n"
     "    printf(\"a=%d n=%d\", t[\"a\"], len(t))\n"
     "    return 0\n", 0, "a=9 n=1"),
    # THE SAME KEY in a loop: every execution hits the key the first one put
    # there, so the count does not grow and the reservation is never exceeded.
    # It is here because it is the arrangement that looks like the overflow case
    # and is not: one site, three executions, one pair.
    ("dict_store_of_the_same_key_in_a_loop_is_the_last_write",
     "def main(n):\n"
     "    d = {\"a\": 1}\n"
     "    var i = 0\n"
     "    while i < 3:\n"
     "        d[\"k\"] = i\n"
     "        i = i + 1\n"
     "    printf(\"k=%d n=%d\", d[\"k\"], len(d))\n"
     "    return 0\n", 0, "k=2 n=2"),
    # An INTEGER key, which is the other half of what this path's dict surface
    # is (the rest is interned string literals) and takes the raw 64-bit compare
    # rather than the element-wise one. `d = {}` reserves nothing of its own, so
    # the whole of the blob is the reservation.
    ("dict_store_of_an_integer_key_into_an_empty_table",
     "def main(n):\n"
     "    d = {}\n"
     "    d[10] = 1\n"
     "    printf(\"v=%d n=%d\", d[10], len(d))\n"
     "    return 0\n", 0, "v=1 n=1"),
]
CASES.extend(DICT_STORE_CASES)


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


def run_stderr_case(name, source, want_exit, needles, tmpdir, verbose):
    """The program must stop at run time, exit `want_exit`, and SAY WHY.

    Three assertions, in the order of how badly each has been missed before:
    the exit status (the only thing the old behaviour asserted), the needles on
    stderr (the thing it did not have at all), and the two architectures
    producing the SAME stderr byte for byte.

    That last one is not tidiness. `model.list_append_overflow_message` exists
    so the two backends cannot name one limit differently, and the only way to
    know they are calling it is to compare what came out — two emitters with two
    copies of a sentence pass every needle and diverge on the fourth word.
    """
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    seen = {}
    for backend in ("arm64", "x86_64"):
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, out, backend=backend)
        if rc != 0:
            return False, (f"--backend={backend} did not build, so this case "
                           f"cannot see the run-time stop: {text.strip()[-300:]}")
        if not os.path.isfile(out):
            return False, f"--backend={backend} built but wrote no binary"
        run = subprocess.run([out], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT)
        if run.returncode != want_exit:
            return False, (f"--backend={backend} exited {run.returncode}, "
                           f"expected {want_exit}; stderr: "
                           f"{run.stderr.strip()[-200:]}")
        missing = [n for n in needles if n not in run.stderr]
        if missing:
            return False, (f"--backend={backend} stopped without saying "
                           f"{missing!r}; stderr: {run.stderr.strip()[-300:]!r}. "
                           f"A bare exit with nothing on either stream is the "
                           f"defect this case exists for")
        seen[backend] = run.stderr
        if verbose:
            print(f"      --backend={backend} exit={run.returncode} "
                  f"stderr={run.stderr.strip()[:80]!r}")
    if seen["arm64"] != seen["x86_64"]:
        return False, (f"the two architectures named the limit differently:\n"
                       f"      arm64:  {seen['arm64'].strip()[-300:]!r}\n"
                       f"      x86_64: {seen['x86_64'].strip()[-300:]!r}")
    return True, ""


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
    # not exist. `del a[i, j]` is the case it was written for: arm64 refused it
    # at the subscript and x86-64 at the statement, because it lowered no `del`
    # at all. Both now refuse at the SUBSCRIPT with the same shared text (both
    # lower `del` — see `test_formal_x86_64_parity.py`'s `del_*` rows), and the
    # statement-depth alternative is kept in that case's needle list so a
    # backend that loses its `del` lowering again fails the case instead of
    # passing it on the other alternative. Prefixed so it cannot be mistaken
    # for a single needle.
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


def run_both_arch_case(name, source, want_exit, want_stdout, tmpdir, verbose):
    """Build and RUN on BOTH backends, and require the same answer from each.

    `run_case` builds the host's architecture for an answered case, which is
    the right economy for the other four hundred rows and the wrong one here:
    a case whose subject is a construct the two backends once DISAGREED about
    cannot be checked by running one of them.  Both halves of the assertion are
    needed and neither subsumes the other — `want_exit` alone would accept two
    different wrong answers, and "it built" alone would accept a program that
    computes the wrong number on both, which is the worse of the two failures
    and the one this suite exists to catch.

    The expected answer is a constant rather than a CPython run because the
    form is the four-column one every other group uses and CPython cannot run
    these sources verbatim (`class` fields with `var`-less annotations and a
    `main(n: Int)` signature).  Each constant is stated in the case's comment
    with its arithmetic, which is the property a constant has to have for this
    to be an assertion rather than a transcript of the lowering.

    A `refuse:` row is not that: there is no image to run, so this defers to
    `run_case`, which already asserts exactly what a refusal row has to assert
    (both backends, and the same words from each). Delegating rather than
    growing a second refusal path here is the point — two copies of "did it
    refuse, with these words" would be two answers to one question, and the
    group a construct sits in is a reading convenience rather than a claim
    about what the case checks. The delegation stays although no row of
    `BOTH_ARCH_CASES` uses it: the two that did — the one-word HOLDER's method
    reading a nested frame, and two constructions of it in one function — are
    answered by the holder analysis rather than refused since `03e3b7b6` (see
    `one_word_holder_reads_the_frame_its_constructor_brought_up` and
    `two_one_word_constructions_get_two_different_frames`), and a future refusal
    row here has to be checked on BOTH backends by the same code that checks the
    builds, which is `run_case` and not this.
    """
    if isinstance(want_exit, str) and want_exit.startswith(
            ("refuse:", "refuse_either:")):
        return run_case(name, source, want_exit, want_stdout, tmpdir, verbose)
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in ("arm64", "x86_64"):
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, out, backend=backend)
        if rc != 0:
            return False, f"--backend={backend} did not build: {text.strip()[-300:]}"
        if not os.path.isfile(out):
            return False, (f"--backend={backend} reported success but wrote no "
                           f"binary")
        run = subprocess.run([out], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT)
        if run.returncode != want_exit:
            return False, (f"--backend={backend} exited {run.returncode}, "
                           f"expected {want_exit}"
                           + (f"; stderr: {run.stderr.strip()[:120]}"
                              if run.stderr.strip() else ""))
        if want_stdout is not None and want_stdout not in run.stdout:
            return False, (f"--backend={backend} stdout {run.stdout[:120]!r} "
                           f"does not contain {want_stdout!r}")
        if verbose:
            print(f"      {backend}: exit={run.returncode}")
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
    # `p + k` is ELEMENT arithmetic and the ALU now scales it, which is what
    # these three cases exist for.  Before the scale, `p + 1` on a `Pointer[Int64]`
    # was REFUSED rather than answered at the wrong address (`_offset_scale`'s
    # own list), and the answer it now gives is the one `struct.unpack` gives
    # over the same bytes: `q = p + 1` reads `b"IJKLMNOP"[0:8]` and NOT the eight
    # bytes at `p+1`, which is what an unscaled add would have loaded (the first
    # of which is 'B' — a plausible number that is the wrong element).
    #
    # Three offsets on one address, both widths, because the failure mode this
    # replaces was silent in the direction that matters: a scale of 1 on an
    # 8-byte element reads the SECOND element and reports it as the first, which
    # no exit code distinguishes from a right answer.
    ("deref_offset_scales_by_the_pointee_width",
     "def read_at(p: Pointer[Int64], k: Int) -> Int:\n"
     "    var q = p + k\n"
     "    return Int(q.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGHIJKLMNOPQRSTUVWX\"\n"
     "    if read_at(s, 0) != 5208208757389214273:      # struct.unpack('<q', b'ABCDEFGH')\n"
     "        return 1\n"
     "    if read_at(s, 1) != 5786930140093827657:      # …b'IJKLMNOP'\n"
     "        return 2\n"
     "    if read_at(s, 2) != 6365651522798441041:      # …b'QRSTUVWX'\n"
     "        return 3\n"
     "    return 0\n", 0, None),
    ("deref_offset_scales_by_four_for_a_32_bit_pointee",
     "def read_at(p: Pointer[Int32], k: Int) -> Int:\n"
     "    var q = p + k\n"
     "    return Int(q.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGHIJKLMNOPQRSTUVWX\"\n"
     "    if read_at(s, 0) != 1145258561:              # struct.unpack('<i', b'ABCD')\n"
     "        return 1\n"
     "    if read_at(s, 1) != 1212630597:              # …b'EFGH'\n"
     "        return 2\n"
     "    return 0\n", 0, None),
    # `p - k` is the same arithmetic backwards, and it is here because the scale
    # is emitted at ONE place in `_emit_binop` for both operators and a
    # one-sided fix is the shape that reads as finished.  The base pointer comes
    # from a function that returns `Pointer[Int64]`, so this also pins that the
    # scale composes across a call boundary: `mid` is `s + 8`, established by
    # `at`'s own `p + k`, and reading one element back has to land on `s`.
    ("deref_offset_backwards_scales_too",
     "def at(p: Pointer[Int64], k: Int) -> Pointer[Int64]:\n"
     "    var q = p + k\n"
     "    return q\n"
     "def read_back(p: Pointer[Int64], k: Int) -> Int:\n"
     "    var q = p - k\n"
     "    return Int(q.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGHIJKLMNOPQRSTUVWX\"\n"
     "    var mid = at(s, 1)\n"
     "    if read_back(mid, 0) != 5786930140093827657:      # …b'IJKLMNOP'\n"
     "        return 1\n"
     "    if read_back(mid, 1) != 5208208757389214273:      # …b'ABCDEFGH'\n"
     "        return 2\n"
     "    return 0\n", 0, None),

    # ── a STRUCT pointee, which is the IDENTITY rather than a load ─────────
    #
    # Six cases for one decision, and the reason there are six is that a frame
    # has FIVE ways of being touched and this is the first path on which all of
    # them work.  `p.value()` on a `Pointer[SomeStruct]` used to be REFUSED with
    # a message that named its own reason exactly: nothing recognised a name
    # bound through a pointer as a frame holder, so `q.b` off the result read a
    # word of nothing — measured, 0 on both architectures where the source says
    # 22.  `model.pointer_frame_pointee` is the recognition, and it has three
    # consumers which between them cover the five touches: `_frame_receivers`
    # seeds the name (`pointer_frame_bindings`), `_frame_return_status` counts a
    # `return` of one as returning a FRAME, and both backends emit the receiver
    # and nothing else.
    #
    # The direct spelling `p.value().b` comes first because it is the shape the
    # refusal's own reproducer used, and it is the one that needs no name: the
    # field read is one `LDR`/`mov` at `[address, 8*slot]` straight after the
    # receiver is evaluated.  22, not 0 and not `a` — a load at the frame's
    # FIRST slot would answer `a`, which is 0 here, so this case cannot tell a
    # right answer from a right-looking one and the next one is what does.
    ("deref_struct_pointee_is_the_receiver",
     "struct P3:\n"
     "    var a: Int64\n"
     "    var b: Int64\n"
     "    var c: Int64\n"
     "def read_field(p: Pointer[P3]) -> Int:\n"
     "    return Int(p.value().b)\n"
     "def main(n: Int) -> Int:\n"
     "    var t = P3()\n"
     "    t.b = 22\n"
     "    return read_field(t)\n", 22, None),
    # The NAMED spelling, which is the recognition the refusal asked for and the
    # one every later case is built on: `q` is a frame holder, so `q.b` is a
    # frame slot and the whole existing machinery — layouts, escapes, nested
    # frames — applies to it unchanged.  The two are separate cases because they
    # are two lowerings (an emitter arm and a holder-table entry), and a
    # one-sided fix here is the shape that reads as finished.
    ("deref_struct_pointee_through_a_name_is_a_holder",
     "struct P3:\n"
     "    var a: Int64\n"
     "    var b: Int64\n"
     "    var c: Int64\n"
     "def read_field(p: Pointer[P3]) -> Int:\n"
     "    var q = p.value()\n"
     "    return Int(q.b)\n"
     "def main(n: Int) -> Int:\n"
     "    var t = P3()\n"
     "    t.b = 22\n"
     "    return read_field(t)\n", 22, None),
    # A STORE through the named holder, and the part of it worth pinning is the
    # SECOND assertion inside the program: `bump` writes `t.b` in the CALLER's
    # frame, so the value has to be visible there.  A store through a pointer
    # that landed in the callee's own scratch would answer 41 and leave `t.b`
    # at 0, which is a wrong answer with no diagnostic — so the program returns
    # 90+41 in that case and 41 when it is right.
    ("deref_struct_pointee_store_through_a_name_reaches_the_caller",
     "struct P3:\n"
     "    var a: Int64\n"
     "    var b: Int64\n"
     "    var c: Int64\n"
     "def bump(p: Pointer[P3]) -> Int:\n"
     "    var q = p.value()\n"
     "    q.b = 41\n"
     "    return Int(q.b)\n"
     "def main(n: Int) -> Int:\n"
     "    var t = P3()\n"
     "    var got = bump(t)\n"
     "    if t.b != 41:\n"
     "        return 90 + got\n"
     "    return got\n", 41, None),
    # The same store spelled directly, `p.value().b = 41`.  It exists because
    # the READ being answerable makes the store's old refusal FALSE: that
    # sentence said "this path has no way to say what 'p.value(...)' holds", and
    # after the read arm it plainly can.  A diagnostic that is false about the
    # program is worse than a missing one, so the store arm is not optional
    # tidiness — it is what keeps the message true.
    ("deref_struct_pointee_store_directly_is_one_slot_store",
     "struct P3:\n"
     "    var a: Int64\n"
     "    var b: Int64\n"
     "    var c: Int64\n"
     "def bump(p: Pointer[P3]) -> Int:\n"
     "    p.value().b = 41\n"
     "    return Int(p.value().b)\n"
     "def main(n: Int) -> Int:\n"
     "    var t = P3()\n"
     "    var got = bump(t)\n"
     "    if t.b != 41:\n"
     "        return 90 + got\n"
     "    return got\n", 41, None),
    # `+=` through the named holder, which goes through no new code at all: the
    # name is in `_frame_slots`, so `_load_var`/`_store_var` resolve
    # `q.b += 5` as the load/op/store they always were.  It is here because it
    # is the cheapest possible evidence that the recognition went into the
    # EXISTING tables rather than beside them — a name special-cased in the
    # emitter would answer this and nothing else.
    ("deref_struct_pointee_augmented_through_a_name",
     "struct P3:\n"
     "    var a: Int64\n"
     "    var b: Int64\n"
     "    var c: Int64\n"
     "def bump(p: Pointer[P3]) -> Int:\n"
     "    var q = p.value()\n"
     "    q.b += 5\n"
     "    return Int(q.b)\n"
     "def main(n: Int) -> Int:\n"
     "    var t = P3()\n"
     "    var got = bump(t)\n"
     "    if t.b != 5:\n"
     "        return 90 + got\n"
     "    return got\n", 5, None),
    # `return p.value()` — the frame-LIFETIME half, and the case that says why
    # the answer above is safe rather than merely reachable.  Without
    # `_frame_return_status` recognising it, `give` was classified
    # `_RETURN_WORD`: no caller reserved a block, the callee copied into a
    # register it was handed by accident, and the address of the CALLER's frame
    # came back as a plain word.  With it, the block is in the caller's scratch
    # and the frame is COPIED into it — which is why `u.b` is 7 here and would
    # be reclaimed stack if the convention did not apply.
    ("deref_struct_pointee_returned_is_copied_into_the_callers_block",
     "struct P3:\n"
     "    var a: Int64\n"
     "    var b: Int64\n"
     "    var c: Int64\n"
     "def give(p: Pointer[P3]) -> P3:\n"
     "    return p.value()\n"
     "def main(n: Int) -> Int:\n"
     "    var t = P3()\n"
     "    t.b = 7\n"
     "    var u = give(t)\n"
     "    return Int(u.b)\n", 7, None),
]

POINTER_DEREF_REFUSALS = [
    # A ONE-FIELD STRUCT pointee, which is the half of the struct-pointee
    # question that stays refused, and it is a DIFFERENT fact rather than a
    # half-answer: a struct of one field has no frame — its value IS its own
    # field — so there is nothing at the address, and the identity would be
    # wrong rather than right.  `struct_is_framed` is the one test for the two,
    # as everywhere else on this path.  It is pinned here because the
    # multi-field case is now ANSWERED (`deref_struct_pointee_is_the_receiver`
    # and its five siblings), so without this row nothing would say where the
    # answer stops.
    ("deref_refuse_one_field_struct_pointee",
     "struct One:\n"
     "    var v: Int64\n"
     "def read_one(p: Pointer[One]) -> Int:\n"
     "    return Int(p.value().v)\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    return read_one(s)\n",
     "refuse:a one-field struct whose value on this path is the word itself",
     None),
    # The frame-LIFETIME half of the same question, and the one that says the
    # answered case above is safe rather than merely reachable: a name bound
    # from `p.value()` is a frame HOLDER, and every channel that would carry a
    # frame address past its creator is already refused for a holder.  This is
    # that channel — a store into another object's field, where the slot outlives
    # the frame by however long the object lives.  Without the recognition this
    # program built and `o.held` held the address of `main`'s own frame.
    ("deref_refuse_a_pointer_frame_stored_in_a_field",
     "struct P3:\n"
     "    var a: Int64\n"
     "    var b: Int64\n"
     "    var c: Int64\n"
     "struct Box:\n"
     "    var inner: Int64\n"
     "    var held: Pointer[P3]\n"
     "def park(p: Pointer[P3], o: Box) -> Int:\n"
     "    var q = p.value()\n"
     "    o.held = q\n"
     "    return Int(q.b)\n"
     "def main(n: Int) -> Int:\n"
     "    var t = P3()\n"
     "    var o = Box()\n"
     "    return park(t, o)\n",
     "refuse:is stored in the field 'o.held'", None),
    # A field the pointee's struct does NOT declare, in both the read and the
    # store spelling.  They are here for the SENTENCE rather than the refusal:
    # both backends raise these from `model.pointer_frame_member_refusal` /
    # `…_store_refusal`, one function each for the same reason
    # `model.member_access_refusal` is one function — a construct the two
    # machines newly answer has to refuse with the same WORDS, and a message
    # written out at four sites (two machines × read and store) is four texts
    # that agree until one of them is edited.
    ("deref_refuse_a_field_the_struct_pointee_does_not_declare",
     "struct P3:\n"
     "    var a: Int64\n"
     "    var b: Int64\n"
     "    var c: Int64\n"
     "def read_bad(p: Pointer[P3]) -> Int:\n"
     "    return Int(p.value().zz)\n"
     "def main(n: Int) -> Int:\n"
     "    var t = P3()\n"
     "    return read_bad(t)\n",
     "refuse:reads 'zz' out of a P3 this pointer points at, and that struct's",
     None),
    ("deref_refuse_a_store_into_a_field_the_struct_pointee_does_not_declare",
     "struct P3:\n"
     "    var a: Int64\n"
     "    var b: Int64\n"
     "    var c: Int64\n"
     "def store_bad(p: Pointer[P3]) -> Int:\n"
     "    p.value().zz = 5\n"
     "    return 0\n"
     "def main(n: Int) -> Int:\n"
     "    var t = P3()\n"
     "    return store_bad(t)\n",
     "refuse:stores into 'zz' of a P3 this pointer points at, and that struct's",
     None),
    # `p.value().b += 5` — the ONE shape of this family that is still refused,
    # and it is pinned so it is a recorded limit rather than a surprise.  The
    # augmented-assignment arm works from a NAME (`_load_var`/`_store_var` on a
    # `_frame_slots` key), and a base that is an EXPRESSION has no name to key
    # on, so the two backends refuse it from their own augmented arms.  Their
    # WORDS differ, which is a pre-existing divergence in that diagnostic and not
    # one of the pointer model's — hence `refuse_either:` with both needles
    # rather than one, which is the honest encoding of "refused on both, and the
    # two disagree about how they say so".  The named spelling is answered:
    # `deref_struct_pointee_augmented_through_a_name`.
    ("deref_refuse_augmented_through_a_pointer_frame",
     "struct P3:\n"
     "    var a: Int64\n"
     "    var b: Int64\n"
     "    var c: Int64\n"
     "def bump(p: Pointer[P3]) -> Int:\n"
     "    p.value().b += 5\n"
     "    return Int(p.value().b)\n"
     "def main(n: Int) -> Int:\n"
     "    var t = P3()\n"
     "    return bump(t)\n",
     "refuse_either:unsupported augmented assignment target on the formal arm64"
     " path|augmented assignment target must be a plain name on the formal"
     " x86-64 path", None),
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
    # untyped direction, and it was the 14-of-47 `unsafe_value` case — a pointer
    # that crossed a call boundary and lost its pointee on the way.  It is now
    # the case the image has NOTHING to say about: `read_x` has no call site in
    # this unit at all, which is what an exported function looks like from inside
    # the library that defines it and is the one shape no amount of walking this
    # image can answer.  The two cases below are the other two shapes, and they
    # are separate cases because a reader who hits one of them has a different
    # fix from a reader who hits this one.
    ("deref_refuse_undeclared_receiver",
     "def read_x(p) -> Int:\n"
     "    return Int(p.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    return 0\n",
     "refuse:it is a word from the caller and its pointee is not recorded here", None),
    # …and the ANSWERED half: the same unannotated parameter, reached only with
    # arguments this image establishes, is now loaded at the pointee's width.  The
    # value is the same word `deref_four_widths_at_one_address` reads with an
    # ANNOTATION, so this case is the measure of the fix: 5208208757389214273 is
    # `struct.unpack('<q', b'ABCDEFGH')` and 65 is what a one-byte read of the
    # same address would say, so a callee that loaded the wrong width would be
    # caught rather than agreeing with itself.
    #
    # `through` is the second hop on purpose: the pointee travels `main`'s
    # declared `Pointer[Int64]` into `read_x` through a parameter of its own that
    # nothing declares either, so the chain is walked rather than one level, and
    # a reader who takes `seen` for a loop guard can see it terminate here.
    ("deref_call_site_pointee_of_an_unannotated_parameter",
     "def read_x(p) -> Int:\n"
     "    return Int(p.value())\n"
     "def through(x) -> Int:\n"
     "    return read_x(x)\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    var q: Pointer[Int64] = s\n"
     "    if through(q) != 5208208757389214273:  # struct.unpack('<q', b'ABCDEFGH')\n"
     "        return 1\n"
     "    return 0\n", 0, None),
    # …and the first wrong answer this could have had: the same parameter reached
    # with a `Pointer[UInt8]`.  One parameter has one pointee, the load's width is
    # chosen per parameter, and one answer cannot serve both — so it is refused
    # with both call sites named rather than compiled at whichever width was seen
    # first.
    ("deref_refuse_two_call_site_pointees",
     "def read_x(p) -> Int:\n"
     "    return Int(p.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    var q8: Pointer[Int64] = s\n"
     "    var q1: Pointer[UInt8] = s\n"
     "    return read_x(q8) + read_x(q1)\n",
     "refuse:this image reaches it with two different pointees", None),
    # …and the third shape, which is the one a reader is most likely to hit: the
    # image reads one call site and cannot place another's argument.  A string
    # literal is a bare `char *` here, and `POINTEES_REFUSED` says in as many
    # words that a list is a BLOB — a frame whose FIRST word is its count — so a
    # width taken from the sites that DO answer would be a guess about the one
    # that does not, and a blob would answer with a length the source never
    # wrote.  The refusal names the site it cannot read, because the reader
    # standing at that call is the one who can fix it.
    ("deref_refuse_a_call_site_the_image_cannot_place",
     "def read_x(p) -> Int:\n"
     "    return Int(p.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    var q: Pointer[Int64] = s\n"
     "    return read_x(q) + read_x(s)\n",
     "refuse:this image cannot say what one of its call sites passes", None),
    # The OFFSET, and the one that is still refused: the ALU scales an integer
    # offset it can read a POINTER and an ELEMENT WIDTH off a declaration for,
    # and this program's `k` has no annotation, so there is nothing to say
    # whether it is an `Int` at all.  That is the refusing direction and it is
    # the whole of what `pointer_offset_scale`'s `_is_integer_expression` buys:
    # a scaled offset the model cannot account for is a load at an address
    # nothing in the image vouches for, which is the defect the refusal exists
    # to stop.  The message names the MISSING declaration — the offset's — and
    # the needle pins that, because the sentence used to name the address's
    # BASE instead and so claimed that a `p` declared `Pointer[Int64]` "is not
    # a pointer to a 8-byte element", which is false and tells the reader to
    # declare the one thing that is already declared.  (`bugs/FORMAL_pointer_
    # value_model.md` §9's first item, fixed; its "remaining half".)
    ("deref_refuse_offset_with_an_undeclared_offset",
     "def read_at(p: Pointer[Int64], k) -> Int:\n"
     "    var q = p + k\n"
     "    return Int(q.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    return read_at(s, 1)\n",
     "refuse:scales only an offset it can establish as an INTEGER by "
     "declaration", None),
    # …and the OTHER half of the same message, which is a different program and
    # a different missing fact: here the offset IS a declared `Int` and the scale
    # is established, but the base's element is four bytes and the load wants
    # eight, so the scale that IS emitted is the wrong one.  It is its own case
    # because the advice inverts here — hand-scaling the offset would be scaled a
    # second time on top of the first — and a needle that only pinned "the
    # offset is not established" would pass on this sentence too.
    ("deref_refuse_a_scale_of_the_wrong_element_width",
     "def read_at(p: Pointer[Int32], k: Int) -> Int:\n"
     "    var q: Pointer[Int64] = p + k\n"
     "    return Int(q.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    return read_at(s, 1)\n",
     "refuse:do NOT scale the offset by hand here, because this path already "
     "scales it by 4", None),
    # …and the same arithmetic on a ONE-BYTE pointee is ANSWERED, and this is the
    # guard for the case above: the scale must not fire where it is the identity,
    # because every `char *` in the corpus — `env.mojo`'s `getenv` result, every
    # `String(unsafe_from_utf8_ptr=…)` — adds a raw byte offset and must keep
    # doing so.  It is also the guard that a future change which scales EVERY
    # pointer offset fails a case rather than passing quietly.
    ("deref_offset_on_a_one_byte_pointee_is_the_answer",
     "def read_at(p: Pointer[UInt8], k: Int) -> Int:\n"
     "    var q = p + k\n"
     "    return Int(q.value())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    if read_at(s, 3) == 68:       # 'D'\n"
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
    # `unsafe_load(i)` is a different CONSTRUCT from `unsafe_load()`: it reads at
    # an OFFSET, and the address and the load are one decision in
    # `dereference_lowering` of which only the load half is answered. `p[i]` is
    # the same program and IS lowered today. What this pins is that the refusal
    # says that, rather than reporting an argument count — `i = 0` is
    # `unsafe_load`'s declared DEFAULT, so "takes no arguments" would be a true
    # sentence sent to a reader who wrote the ordinary spelling and nothing
    # wrong. Both architectures, identical words.
    ("deref_refuse_unsafe_load_with_an_offset",
     "def read_at(p: Pointer[UInt8], i: Int) -> Int:\n"
     "    return Int(p.unsafe_load(i))\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    return read_at(s, 1)\n",
     "refuse:reads at an OFFSET from the receiver", None),
    # …and the bracket, which is refused by a DIFFERENT and pre-existing rule —
    # the callee is a `SubscriptExpr` rather than a `MemberExpr`, so it never
    # reaches the dereference arm at all and is named as a specialization this
    # path cannot name a callee for. Pinned here because the two rules sit next
    # to each other and a reader who has just seen `unsafe_load` answered will
    # reasonably expect `unsafe_load[width=4]` to be answered too; what it must
    # NOT do is reach a load, which is the outcome the bracketed-callee refusal
    # exists to prevent.
    ("deref_refuse_unsafe_load_bracketed_width",
     "def read_at(p: Pointer[UInt8]) -> Int:\n"
     "    return Int(p.unsafe_load[width=4]())\n"
     "def main(n: Int) -> Int:\n"
     "    var s = \"ABCDEFGH\"\n"
     "    return read_at(s)\n",
     "refuse:Refused rather than emitted with the brackets dropped", None),
    # A receiver that is NOT a pointer gets the four-questions message and NOT
    # "is a load from the address the receiver holds" — which is what putting
    # `unsafe_load` in `DEREFERENCE_METHODS` would have produced, and is false
    # of a `def read_it(n: Int)`. This row is the reason the entry is in
    # `IDENTITY_VALUE_METHODS` instead: the receiver is asked FIRST, and the
    # specific missing fact named is that it is not established to be a pointer.
    ("deref_refuse_unsafe_load_on_a_non_pointer_receiver",
     "def read_it(n: Int) -> Int:\n"
     "    return Int(n.unsafe_load())\n"
     "def main(n: Int) -> Int:\n"
     "    return read_it(7)\n",
     "refuse:The receiver is not established to be a pointer here", None),
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
# (`formal/build.py`'s `_frame_receivers`, seeding a method's parameters from
# `frame_field_type_candidates`): `h: One` says `h` IS a `One`,
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


# ── SLICES, CONCATENATION and the length of a slice ─────────────────────────
#
# Four defects, four architectures' worth of wrong answers, and every one of
# them was a number rather than a crash — which is why they are here as
# CPython PAIRS and not as expected constants: a hand-written constant is an
# assertion about the lowering made by the person who wrote the lowering, and
# `sum(xs[1:3]) == 5` written by the person who just made it answer 5 is worth
# nothing. CPython answers each one at test time.
#
# ONE slice (or one `+`) per program, and that is not tidiness: x86-64's slice
# emitter cannot lower a SECOND slice in the same function — it reads a
# pointer that is not one — so a table with two per program would be a table of
# failures about that instead of about these. The reproducer and what is known
# about the cause are the three bound-clamp labels of `_emit_slice_parts`, fixed
# 2026-10-03 in 68671a62.
#
# What each case pins, and what it was before:
#
#   * `_emit_slice_parts` armed the loop's exit test the wrong way round. The
#     clamp step then RAISED every in-range bound to the element count
#     (`cmp x9, x4; cset hi` asks "count > bound?" and stored the count), so
#     `xs[1:3]` became `xs[6:6]`: every forward slice was an empty list that
#     `len` and every consumer agreed was empty, and the descending cases were
#     right by coincidence. arm64 exited 1 with nothing printed; see the two
#     rows below for the two halves.
#   * The descending direction walked from `stop - 1` and stopped at `i >= 0`,
#     consulting no bound the source wrote: `xs[5:0:-1]` copied nothing.
#   * `xs[::-1]` and `xs[:2:-1]` need the DESCENDING defaults (`count - 1` and
#     `-1`), which are different words from the ascending ones (0 and `count`).
#     Reading them as the ascending pair is what made `xs[:2:-1]` answer
#     `[2]` instead of `[6, 5, 4]`.
#   * `list + list` wrote the right COUNT and copied no elements: both copy
#     loops left on their first iteration, and the right one addressed
#     `nL` BYTES further on rather than `nL` ELEMENTS. So `len` was right and
#     `sum` was 0, which is the shape of a bug that looks like a typing one.
#   * `a + b` on two NAMES was not recognised as a concatenation at all on
#     arm64 and lowered to pointer arithmetic — the sum of two addresses.
#   * `len` of a slice was refused on BOTH backends, because nothing classified
#     a slice as a blob.

# (name, mojo expression, CPython expression) — the same slice spelled twice.
_SLICE_TABLE = [
    ("slice_forward_bounds", "xs[1:3]"),
    ("slice_forward_tail", "xs[2:6]"),
    ("slice_step_two", "xs[0:6:2]"),
    ("slice_step_three", "xs[0:6:3]"),
    ("slice_step_beyond_end", "xs[0:5:3]"),
    ("slice_open_start", "xs[1:]"),
    ("slice_open_stop", "xs[:3]"),
    ("slice_both_open", "xs[:]"),
    ("slice_negative_start", "xs[-2:]"),
    ("slice_negative_stop", "xs[:-2]"),
    ("slice_empty_range", "xs[3:3]"),
    ("slice_inverted_range", "xs[5:2]"),
    ("slice_one_element", "xs[0:1]"),
    ("slice_start_past_end", "xs[100:200]"),
    ("slice_far_negative_start", "xs[-99:]"),
    ("slice_both_negative", "xs[-99:-97]"),
    ("slice_stop_past_end", "xs[1:99]"),
    ("slice_reversed_empty", "xs[0:6:-1]"),
    ("slice_reversed_bounds", "xs[5:0:-1]"),
    ("slice_reversed_all", "xs[::-1]"),
    ("slice_reversed_open_stop", "xs[:2:-1]"),
    ("slice_reversed_open_start", "xs[5::-1]"),
    ("slice_reversed_step_two", "xs[5:0:-2]"),
    ("slice_last_element", "xs[-1:]"),
    ("slice_reversed_inner", "xs[4:1:-1]"),
]


def _sum_slice_pair(name, expr):
    """One slice, summed, with CPython as the oracle for the same text.

    The two sides differ in their WRAPPER and nowhere else: Mojo's entry point
    is `def main() -> Int:` and the runner appends the call, while CPython's is a
    `def main():` the same runner calls. Keeping the bodies textually identical
    is the point — a case whose expected value is a number written by the same
    hand as the lowering is worth nothing, and the whole reason this group is
    pairs rather than constants.
    """
    body = ("    xs = [1, 2, 3, 4, 5, 6]\n"
            "    s = 0\n"
            f"    for v in {expr}:\n"
            "        s += v\n"
            "    print(\"sum=%d\" % s)\n")
    return (
        name,
        "def main() -> Int:\n"
        "    var xs = [1, 2, 3, 4, 5, 6]\n"
        "    var s = 0\n"
        f"    for v in {expr}:\n"
        "        s += v\n"
        "    printf(\"sum=%d\\n\", s)\n"
        "    return 0\n",
        "def main():\n" + body)


SLICE_CASES = [_sum_slice_pair(n, e) for n, e in _SLICE_TABLE]


# The BOUND half of the same construct: the result assigned to a name, then
# read three ways. `len` of it is the case that was refused on both backends,
# and a `for` over it is the case that read as empty, so one program covers
# both and neither can pass alone.
SLICE_BOUND_CASES = [
    # The BOUND half of the same construct: the result assigned to a name, then
    # read three ways. `len` of it is the case that was REFUSED on both
    # backends, and the `for` is the case that read as empty, so one program
    # covers both and neither can pass alone.
    ("slice_bound_sum_and_len",
     "def main() -> Int:\n"
     "    var xs = [1, 2, 3, 4, 5, 6]\n"
     "    var ys = xs[1:3]\n"
     "    var s = 0\n"
     "    for v in ys:\n"
     "        s += v\n"
     "    printf(\"sum=%d len=%d e0=%d\\n\", s, len(ys), ys[0])\n"
     "    return 0\n",
     "def main():\n"
     "    xs = [1, 2, 3, 4, 5, 6]\n"
     "    ys = xs[1:3]\n"
     "    s = 0\n"
     "    for v in ys:\n"
     "        s += v\n"
     "    print(\"sum=%d len=%d e0=%d\" % (s, len(ys), ys[0]))\n"),
    # `len` of the slice EXPRESSION, which has no name to classify: the answer
    # is the count word of a blob the expression materialises, and nothing in
    # the model said a slice was a blob. THREE cases rather than one program
    # with three `len`s in it, because each is a different SHAPE of the same
    # question — a bounded slice, the whole list, an EMPTY one — and the empty
    # one is the one a "non-zero means present" shortcut gets wrong. They cannot
    # share a program for the reason the head of this group gives.
    ("slice_len_of_a_bounded_expression",
     "def main() -> Int:\n"
     "    var xs = [1, 2, 3, 4, 5, 6]\n"
     "    printf(\"len=%d\\n\", len(xs[1:3]))\n"
     "    return 0\n",
     "def main():\n"
     "    xs = [1, 2, 3, 4, 5, 6]\n"
     "    print(\"len=%d\" % len(xs[1:3]))\n"),
    ("slice_len_of_the_whole_list",
     "def main() -> Int:\n"
     "    var xs = [1, 2, 3, 4, 5, 6]\n"
     "    printf(\"len=%d\\n\", len(xs[:]))\n"
     "    return 0\n",
     "def main():\n"
     "    xs = [1, 2, 3, 4, 5, 6]\n"
     "    print(\"len=%d\" % len(xs[:]))\n"),
    ("slice_len_of_an_empty_slice",
     "def main() -> Int:\n"
     "    var xs = [1, 2, 3, 4, 5, 6]\n"
     "    printf(\"len=%d\\n\", len(xs[3:3]))\n"
     "    return 0\n",
     "def main():\n"
     "    xs = [1, 2, 3, 4, 5, 6]\n"
     "    print(\"len=%d\" % len(xs[3:3]))\n"),
    # A bound slice read back through a SUBSCRIPT, which is the read that
    # exited 1 at the bounds check before: the blob was full and its count word
    # read 0, so every element was out of range.
    ("slice_bound_subscript_read",
     "def main() -> Int:\n"
     "    var xs = [1, 2, 3, 4, 5, 6]\n"
     "    var ys = xs[2:5]\n"
     "    printf(\"%d %d %d\\n\", ys[0], ys[1], ys[2])\n"
     "    return 0\n",
     "def main():\n"
     "    xs = [1, 2, 3, 4, 5, 6]\n"
     "    ys = xs[2:5]\n"
     "    print(\"%d %d %d\" % (ys[0], ys[1], ys[2]))\n"),
]


# Concatenation. Five shapes, one `+` each: a literal and a name, a result read
# by subscript, two NAMES, a name and a slice, and an alias — the last three all
# need a NAME classified as a blob, which is the evidence arm64 did not have.
CONCAT_CASES = [
    # `xs = xs + [3]`: one side is a literal, so the operator WAS recognised —
    # and the count was written while both copy loops left on their first
    # iteration, so `len` was 3 and every element read 0.
    ("concat_rebinds_a_local",
     "def main() -> Int:\n"
     "    var xs = [1, 2]\n"
     "    xs = xs + [3]\n"
     "    var s = 0\n"
     "    for v in xs:\n"
     "        s += v\n"
     "    printf(\"sum=%d len=%d\\n\", s, len(xs))\n"
     "    return 0\n",
     "def main():\n"
     "    xs = [1, 2]\n"
     "    xs = xs + [3]\n"
     "    s = 0\n"
     "    for v in xs:\n"
     "        s += v\n"
     "    print(\"sum=%d len=%d\" % (s, len(xs)))\n"),
    # The result read by SUBSCRIPT rather than by iteration, which is what
    # caught the second half of the copy: the right operand's first element was
    # addressed `nL` BYTES further on rather than `nL` ELEMENTS, six bytes into
    # the left's last element.
    ("concat_read_by_subscript",
     "def main() -> Int:\n"
     "    var xs = [1, 2, 3]\n"
     "    var zs = xs + [4, 5]\n"
     "    printf(\"%d %d %d %d\\n\", zs[0], zs[2], zs[3], zs[4])\n"
     "    return 0\n",
     "def main():\n"
     "    xs = [1, 2, 3]\n"
     "    zs = xs + [4, 5]\n"
     "    print(\"%d %d %d %d\" % (zs[0], zs[2], zs[3], zs[4]))\n"),
    # TWO NAMES, and nothing else: no literal anywhere, so the operator had no
    # evidence it was a concatenation and lowered to `add` on the two blob
    # addresses. The program built, ran, exited 0 and printed a word of whatever
    # was mapped at the sum of two addresses.
    ("concat_of_two_names",
     "def main() -> Int:\n"
     "    var xs = [1, 2, 3]\n"
     "    var ys = [4, 5]\n"
     "    var zs = xs + ys\n"
     "    var s = 0\n"
     "    for v in zs:\n"
     "        s += v\n"
     "    printf(\"sum=%d\\n\", s)\n"
     "    return 0\n",
     "def main():\n"
     "    xs = [1, 2, 3]\n"
     "    ys = [4, 5]\n"
     "    zs = xs + ys\n"
     "    s = 0\n"
     "    for v in zs:\n"
     "        s += v\n"
     "    print(\"sum=%d\" % s)\n"),
    # A NAME and a SLICE: both halves have to be classified as blobs, and the
    # slice half is the one nothing classified before this change.
    ("concat_of_a_name_and_a_slice",
     "def main() -> Int:\n"
     "    var xs = [1, 2, 3, 4, 5, 6]\n"
     "    var ys = xs[1:3]\n"
     "    var zs = ys + [9]\n"
     "    var s = 0\n"
     "    for v in zs:\n"
     "        s += v\n"
     "    printf(\"sum=%d\\n\", s)\n"
     "    return 0\n",
     "def main():\n"
     "    xs = [1, 2, 3, 4, 5, 6]\n"
     "    ys = xs[1:3]\n"
     "    zs = ys + [9]\n"
     "    s = 0\n"
     "    for v in zs:\n"
     "        s += v\n"
     "    print(\"sum=%d\" % s)\n"),
    # An ALIAS: `ys = xs` keeps the mark. That is the flow half of the same
    # table, and the case that catches a table built from DECLARATIONS instead
    # of from bindings — which would have the alias by accident and this one
    # only by construction.
    ("concat_through_an_alias",
     "def main() -> Int:\n"
     "    var xs = [1, 2]\n"
     "    var ys = xs\n"
     "    ys = ys + [3]\n"
     "    var s = 0\n"
     "    for v in ys:\n"
     "        s += v\n"
     "    printf(\"sum=%d\\n\", s)\n"
     "    return 0\n",
     "def main():\n"
     "    xs = [1, 2]\n"
     "    ys = xs\n"
     "    ys = ys + [3]\n"
     "    s = 0\n"
     "    for v in ys:\n"
     "        s += v\n"
     "    print(\"sum=%d\" % s)\n"),
]


# ── an inlined `__init__`'s OWN RECEIVER ─────────────────────────────────────
#
# `model.init_receiver_rewrite` resolves a read of the object under construction
# against the block `struct_constructor_sites` reserved for that construction,
# in two ways: a METHOD CALL is lifted to the call it is with the block's address
# as its receiver, and a one-LEVEL FIELD READ is a load at `block + 8·slot`.  It
# used to be one refusal ("whose body this path does not inline: a read of 'self'
# in the right-hand side"), and the two files it blocked were this repository's
# own — `module_spec_gen.py`'s `self.spec_content = self._read_spec()`.  The
# refusals that remain are in `CONSTRUCTION_REFUSALS` (5), (5a), (5b), (5c).
#
# A CPython-pair group rather than four-column constants, because the whole
# content of the change is an ORDER: the stores run in the body's own order, each
# receiver read sees what the stores BEFORE it wrote, and the block belongs to the
# construction SITE.  A hand-written constant would not notice a receiver reading
# a slot before the store that fills it, and CPython does.
CTOR_RECEIVER_CASES = [
    # (1) A METHOD CALL with no arguments, and a field read of what it returned.
    # The last store is the whole value of the answer, so a receiver that read
    # the wrong block would return the caller's block's garbage rather than 15.
    ("ctor_recv_a_method_call_and_a_field_read",
     "struct S:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    var c: Int\n"
     "\n"
     "    def __init__(out self, n: Int):\n"
     "        self.a = n\n"
     "        self.b = self.ten()\n"
     "        self.c = self.a + self.b\n"
     "\n"
     "    def ten(out self) -> Int:\n"
     "        return 10\n"
     "\n"
     "def main() -> Int:\n"
     "    var s = S(5)\n"
     "    printf(\"%d\\n\", s.c)\n"
     "    return 0\n",
     "class S:\n"
     "    def __init__(self, n):\n"
     "        self.a = n\n"
     "        self.b = self.ten()\n"
     "        self.c = self.a + self.b\n"
     "\n"
     "    def ten(self):\n"
     "        return 10\n"
     "\n"
     "def main():\n"
     "    s = S(5)\n"
     "    print(s.c)\n"),
    # (2) A method that reads TWO fields, one of them at its CLASS-LEVEL default
    # and one the body has already stored — so the receiver the method reads
    # through is the block under construction and the store order is load-bearing.
    ("ctor_recv_a_method_reads_a_class_default",
     "struct Box:\n"
     "    var w: Int = 40\n"
     "    var h: Int\n"
     "    var area: Int\n"
     "    var tag: Int\n"
     "\n"
     "    def __init__(out self, h: Int):\n"
     "        self.h = h\n"
     "        self.area = self.scaled()\n"
     "        self.tag = self.pick(3)\n"
     "\n"
     "    def scaled(out self) -> Int:\n"
     "        return self.w * self.h\n"
     "\n"
     "    def pick(out self, k: Int) -> Int:\n"
     "        if k == 3:\n"
     "            return 7\n"
     "        return 0\n"
     "\n"
     "def main() -> Int:\n"
     "    var b = Box(2)\n"
     "    printf(\"%d\\n\", b.area + b.tag)\n"
     "    return 0\n",
     "class Box:\n"
     "    def __init__(self, h):\n"
     "        self.w = 40\n"
     "        self.h = h\n"
     "        self.area = self.scaled()\n"
     "        self.tag = self.pick(3)\n"
     "\n"
     "    def scaled(self):\n"
     "        return self.w * self.h\n"
     "\n"
     "    def pick(self, k):\n"
     "        if k == 3:\n"
     "            return 7\n"
     "        return 0\n"
     "\n"
     "def main():\n"
     "    b = Box(2)\n"
     "    print(b.area + b.tag)\n"),
    # (3) TWO constructions of one struct in one function, which is the case the
    # receiver has to name its own SITE for: the block is per call site, so a
     # receiver that resolved to the first construction would read 5 where the
     # source says 7.
    ("ctor_recv_two_sites_get_two_blocks",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def __init__(out self, n: Int):\n"
     "        self.a = n\n"
     "        self.b = self.ten()\n"
     "\n"
     "    def ten(out self) -> Int:\n"
     "        return 10\n"
     "\n"
     "def main() -> Int:\n"
     "    var p = P(5)\n"
     "    var q = P(7)\n"
     "    printf(\"%d\\n\", p.b * 100 + q.b + p.a)\n"
     "    return 0\n",
     "class P:\n"
     "    def __init__(self, n):\n"
     "        self.a = n\n"
     "        self.b = self.ten()\n"
     "\n"
     "    def ten(self):\n"
     "        return 10\n"
     "\n"
     "def main():\n"
     "    p = P(5)\n"
     "    q = P(7)\n"
     "    print(p.b * 100 + q.b + p.a)\n"),
    # (4) The shape `module_spec_gen.py` is written in: a constructor whose stores
    # are the constructor's own ARGUMENT and two calls on the object being built,
    # with the methods reading fields the earlier stores wrote.  Written out here
    # with a file-shaped body instead of `open()`/`f.read()` so the case measures
    # the receiver and nothing else.
    ("ctor_recv_module_spec_generator_shape",
     "struct ModuleSpecGenerator:\n"
     "    var spec_file: String = \"\"\n"
     "    var spec_len: Int\n"
     "    var type_count: Int\n"
     "\n"
     "    def __init__(out self, spec_file: String):\n"
     "        self.spec_file = spec_file\n"
     "        self.spec_len = self.measure()\n"
     "        self.type_count = self.count_types()\n"
     "\n"
     "    def measure(out self) -> Int:\n"
     "        return len(self.spec_file)\n"
     "\n"
     "    def count_types(out self) -> Int:\n"
     "        return self.spec_len + 2\n"
     "\n"
     "def main() -> Int:\n"
     "    var g = ModuleSpecGenerator(\"abcd\")\n"
     "    printf(\"%d\\n\", g.spec_len * 100 + g.type_count)\n"
     "    return 0\n",
     "class ModuleSpecGenerator:\n"
     "    spec_file = \"\"\n"
     "    def __init__(self, spec_file):\n"
     "        self.spec_file = spec_file\n"
     "        self.spec_len = self.measure()\n"
     "        self.type_count = self.count_types()\n"
     "\n"
     "    def measure(self):\n"
     "        return len(self.spec_file)\n"
     "\n"
     "    def count_types(self):\n"
     "        return self.spec_len + 2\n"
     "\n"
     "def main():\n"
     "    g = ModuleSpecGenerator(\"abcd\")\n"
     "    print(g.spec_len * 100 + g.type_count)\n"),
]


# ── a CALL RESULT as a method receiver: the type is in a return annotation ──
#
# The third shape `_rewrite_method_calls` lifts, after a bare name
# (`_method_call_target`) and a subscript whose element type the source states
# (`_subscript_receiver_target`).  `formal/build.py::_call_receiver_target` asks
# `model.receiver_struct` about the receiver, and the CALL row of that predicate
# reads the callee's own `-> T` — so `mk().take(r)` dispatches on a type the
# source STATES rather than on one a binding had to be found for.
#
# These are CPython-pair rows (Mojo text, CPython text, one stdout) because the
# failure this shape can have is a wrong number rather than a refusal: the
# receiver is passed as the call itself, `Box_take(mk(), r)`, so an emitter that
# evaluated the receiver expression twice, or read the wrong word for the
# receiver, produces a plausible answer with nothing reporting a failure.
#
# What is NOT here is the shape the lift must refuse, and that is the point of
# the guards in `test_formal_receiver_position.py`: a CONSTRUCTION (`Box()`)
# names its struct too, and lifting that one reads at address 0.  The row this
# table replaces is the same table's old
# `byref_refuse_an_opaque_position_as_opaque`, whose refusal is gone because
# the advice it gave — bind the receiver to a local — is no longer needed when
# the return annotation already says what the local would have said.
CALL_RECEIVER_CASES = [
    # (1) `mk()` is a free function whose declared return type names a one-field
    # struct of this unit.  The answer reads BOTH the receiver the call produced
    # and a FRAME argument, so a receiver that arrived as the wrong word would
    # change the sum rather than crash.
    ("call_result_receiver_lifted_from_a_return_type",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "struct Box:\n"
     "    var v: Int\n"
     "\n"
     "    def take(self, o: R) -> Int:\n"
     "        return self.v + o.a\n"
     "\n"
     "def mk() -> Box:\n"
     "    var bx = Box()\n"
     "    bx.v = 40\n"
     "    return bx\n"
     "\n"
     "def main() -> Int:\n"
     "    var r = R()\n"
     "    r.a = 2\n"
     "    printf(\"%d\\n\", mk().take(r))\n"
     "    return 0\n",
     "class R:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "\n"
     "class Box:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "\n"
     "    def take(self, o):\n"
     "        return self.v + o.a\n"
     "\n"
     "def mk():\n"
     "    bx = Box()\n"
     "    bx.v = 40\n"
     "    return bx\n"
     "\n"
     "def main():\n"
     "    r = R()\n"
     "    r.a = 2\n"
     "    print(mk().take(r))\n"),
    # (2) The receiver is a METHOD call, which is the shape
    # `std/builtin/float_literal.mojo` is refused on:
    # `self.__int_literal__().__int__()`.  Two things are new here and both are
    # needed for that file — the receiver's type comes from the METHOD's `-> T`
    # rather than a function's, and the inner call has to be lifted too, which
    # is why `formal/build.py`'s `visit` recurses into the receiver before the
    # call that takes it (`model.rewrite_tree` does not descend into a
    # construct it has consumed).
    #
    # `IntLike` and `Whole` are BOTH one field, and `whole()`'s body STORES
    # through the receiver it is given, so a receiver word that was a frame
    # address instead of the field would store somewhere else and read back a
    # zero — which is the failure the value is chosen to make visible.
    ("call_result_receiver_of_a_method_call",
     "struct IntLike:\n"
     "    var n: Int\n"
     "\n"
     "    def twice(self) -> Int:\n"
     "        return self.n * 2\n"
     "\n"
     "struct Whole:\n"
     "    var n: Int\n"
     "\n"
     "    def whole(self) -> IntLike:\n"
     "        var q = IntLike()\n"
     "        q.n = self.n\n"
     "        return q\n"
     "\n"
     "    def report(self, k: Int) -> Int:\n"
     "        return self.whole().twice() + k\n"
     "\n"
     "def main() -> Int:\n"
     "    var w = Whole()\n"
     "    w.n = 21\n"
     "    printf(\"%d\\n\", w.report(1))\n"
     "    return 0\n",
     "class IntLike:\n"
     "    def __init__(self):\n"
     "        self.n = 0\n"
     "\n"
     "    def twice(self):\n"
     "        return self.n * 2\n"
     "\n"
     "class Whole:\n"
     "    def __init__(self):\n"
     "        self.n = 0\n"
     "\n"
     "    def whole(self):\n"
     "        q = IntLike()\n"
     "        q.n = self.n\n"
     "        return q\n"
     "\n"
     "    def report(self, k):\n"
     "        return self.whole().twice() + k\n"
     "\n"
     "def main():\n"
     "    w = Whole()\n"
     "    w.n = 21\n"
     "    print(w.report(1))\n"),
    # (3) A CHAIN of two, so the recursion is pinned at depth 2 rather than at
    # the one call `std/builtin/float_literal.mojo` happens to have.  Each hop
    # reads a DIFFERENT struct's `-> T` (`to_a` says `A`, `to_c` says `C`), so a
    # lift that stopped after one hop — or that carried the first hop's struct
    # into the second — would call the wrong method rather than fail to call
    # one.  The arithmetic is chosen so both hops and the final read are visible
    # in one number: 5 * 3 = 15, + 4 = 19.
    ("call_result_receiver_chain_of_two_calls",
     "struct A:\n"
     "    var v: Int\n"
     "\n"
     "    def to_c(self, k: Int) -> C:\n"
     "        var c = C()\n"
     "        c.v = self.v + k\n"
     "        return c\n"
     "\n"
     "struct B:\n"
     "    var v: Int\n"
     "\n"
     "    def to_a(self, k: Int) -> A:\n"
     "        var a = A()\n"
     "        a.v = self.v * k\n"
     "        return a\n"
     "\n"
     "struct C:\n"
     "    var v: Int\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.v\n"
     "\n"
     "def main() -> Int:\n"
     "    var b = B()\n"
     "    b.v = 5\n"
     "    printf(\"%d\\n\", b.to_a(3).to_c(4).get())\n"
     "    return 0\n",
     "class A:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "\n"
     "    def to_c(self, k):\n"
     "        c = C()\n"
     "        c.v = self.v + k\n"
     "        return c\n"
     "\n"
     "class B:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "\n"
     "    def to_a(self, k):\n"
     "        a = A()\n"
     "        a.v = self.v * k\n"
     "        return a\n"
     "\n"
     "class C:\n"
     "    def __init__(self):\n"
     "        self.v = 0\n"
     "\n"
     "    def get(self):\n"
     "        return self.v\n"
     "\n"
     "def main():\n"
     "    b = B()\n"
     "    b.v = 5\n"
     "    print(b.to_a(3).to_c(4).get())\n"),
]



# ── REPETITION: `xs * n`, which was not a construct on this path at all ─────
#
# It reached the integer ALU with both operands still holding blob ADDRESSES,
# so `[7] * 4` was `7 * 4 * 8` — the address of nothing — and every read
# through it walked a count at that address. Measured on both architectures
# before the change, on this one program per architecture:
#
#     def main():
#         C = [7] * 4
#         n = 0
#         for x in C:
#             n = n + 1
#         printf("n=%d", n)
#
# built, ran, and died with SIGSEGV (exit 139) on arm64 and on x86-64 alike,
# where CPython counts 4. A build that succeeds and then crashes is the worst of
# the three answers this backend can give, and the kind half made it worse: a
# list of ints has kind `list:int`, and `_unify` compared that against the bare
# `LIST_PREFIX` only, so `[1, 2] * 3` did not unify with the `int` on its other
# side and the name was bound to the "a word is an integer" default — which is
# also why `len()` of one was refused as "len() of a value classified as
# 'int'" and why `print` of one said it could not tell a SubscriptExpr from a
# string or a number.
#
# So these are CPython PAIRS for the reason the slice group above gives: a
# constant written by the same hand as the lowering is worth nothing.
# The two shapes a repetition CANNOT have, and both of them used to build.
# A dynamic count and a container-times-container both reached the integer ALU
# as address arithmetic, so the cases below are the direction the fix has to
# keep: a named refusal on BOTH architectures, never a build.
REPEAT_REFUSALS = [
    # A COUNT THIS PATH CANNOT READ. The reservation is made before anything
    # runs and there is no heap to grow into, so a repetition of unknown length
    # has nowhere to put its elements — and the alternative (reserve a guess,
    # check at run time) turns `[0.0] * (m * k)` into a program that builds and
    # then dies, which is the outcome this backend exists to prevent. The needle
    # is the CONSTRUCT, so a refusal about anything else fails the case.
    ("repeat_refuses_a_count_it_cannot_read",
     "def main(n: Int) -> Int:\n"
     "    var xs = [1, 2]\n"
     "    var ys = xs * n\n"
     "    return len(ys)\n",
     "refuse:is a REPETITION, and this path can only lower one whose count it "
     "can read while emitting", None),
    # TWO CONTAINERS. Python raises a TypeError for every such pair, so there is
    # no program here to answer — and the multiply of two blob addresses is a
    # number nowhere near either blob.
    ("repeat_refuses_two_containers",
     "def main() -> Int:\n"
     "    var a = [1] * [2]\n"
     "    return a[0]\n",
     "refuse:multiplies two containers", None),
]


REPEAT_CASES = [
    # The reproducer, verbatim. Counting is the one read that cannot be a
    # wrong number: it walks the count word the emitter wrote.
    ("repeat_counts_the_elements",
     "def main() -> Int:\n"
     "    var C = [7] * 4\n"
     "    var n = 0\n"
     "    for x in C:\n"
     "        n = n + 1\n"
     "    printf(\"n=%d\\n\", n)\n"
     "    return 0\n",
     "def main():\n"
     "    C = [7] * 4\n"
     "    n = 0\n"
     "    for x in C:\n"
     "        n = n + 1\n"
     "    print(\"n=%d\" % n)\n"),
    # The ELEMENTS, which the count cannot vouch for: the count word is
    # computed from nL*count, so it is right even when the copy wrote nothing —
    # the shape both concat copy loops had, where `len` was right and `sum` was
    # 0. A multi-element source is what makes the repetition's own copy loop
    # observable at all.
    ("repeat_copies_the_elements",
     "def main() -> Int:\n"
     "    var xs = [1, 2] * 3\n"
     "    var s = 0\n"
     "    for v in xs:\n"
     "        s += v\n"
     "    printf(\"sum=%d len=%d e0=%d e5=%d\\n\", s, len(xs), xs[0], xs[5])\n"
     "    return 0\n",
     "def main():\n"
     "    xs = [1, 2] * 3\n"
     "    s = 0\n"
     "    for v in xs:\n"
     "        s += v\n"
     "    print(\"sum=%d len=%d e0=%d e5=%d\" % (s, len(xs), xs[0], xs[5]))\n"),
    # `len()` OF THE REPETITION, and a SUBSCRIPT of it: the kind half of the
    # change is what makes these answerable at all — `list:int` against `int`
    # did not unify, so the name was an integer and `len` refused with "an
    # integer has no length".
    ("repeat_len_and_subscript",
     "def main() -> Int:\n"
     "    var xs = [3, 4] * 2\n"
     "    printf(\"len=%d e0=%d e1=%d e3=%d\\n\",\n"
     "           len(xs), xs[0], xs[1], xs[3])\n"
     "    return 0\n",
     "def main():\n"
     "    xs = [3, 4] * 2\n"
     "    print(\"len=%d e0=%d e1=%d e3=%d\" %\n"
     "          (len(xs), xs[0], xs[1], xs[3]))\n"),
    # THE COUNT ON THE LEFT, which is the same repetition spelled the other way
    # round and a separate branch in the emitter (which operand is the blob).
    ("count_on_the_left_repeats_too",
     "def main() -> Int:\n"
     "    var xs = 2 * [5]\n"
     "    var s = 0\n"
     "    for v in xs:\n"
     "        s += v\n"
     "    printf(\"sum=%d len=%d\\n\", s, len(xs))\n"
     "    return 0\n",
     "def main():\n"
     "    xs = 2 * [5]\n"
     "    s = 0\n"
     "    for v in xs:\n"
     "        s += v\n"
     "    print(\"sum=%d len=%d\" % (s, len(xs)))\n"),
    # A NAME on the left, where the source length is a fact about the BLOB
    # rather than about the syntax: `xs * 3` has to copy what `xs` holds at run
    # time, which a static element count cannot answer.
    ("repeat_of_a_name",
     "def main() -> Int:\n"
     "    var xs = [1, 2]\n"
     "    var ys = xs * 3\n"
     "    var s = 0\n"
     "    for v in ys:\n"
     "        s += v\n"
     "    printf(\"sum=%d len=%d\\n\", s, len(ys))\n"
     "    return 0\n",
     "def main():\n"
     "    xs = [1, 2]\n"
     "    ys = xs * 3\n"
     "    s = 0\n"
     "    for v in ys:\n"
     "        s += v\n"
     "    print(\"sum=%d len=%d\" % (s, len(ys)))\n"),
    # A COUNT OF ZERO, and a NEGATIVE one: CPython's answer is the empty list
    # for both (`[7] * 0` and `[7] * -1` are `[]`), so the loop bound must be
    # clamped rather than left to run with a negative trip count — which is a
    # walk off the front of the blob area, and silent.
    ("repeat_of_zero_and_of_a_negative_count",
     "def main() -> Int:\n"
     "    var a = [9] * 0\n"
     "    var b = [9] * -1\n"
     "    var n = 0\n"
     "    for v in a:\n"
     "        n = n + 1\n"
     "    for v in b:\n"
     "        n = n + 1\n"
     "    printf(\"n=%d len_a=%d len_b=%d\\n\", n, len(a), len(b))\n"
     "    return 0\n",
     "def main():\n"
     "    a = [9] * 0\n"
     "    b = [9] * -1\n"
     "    n = 0\n"
     "    for v in a:\n"
     "        n = n + 1\n"
     "    for v in b:\n"
     "        n = n + 1\n"
     "    print(\"n=%d len_a=%d len_b=%d\" % (n, len(a), len(b)))\n"),
    # A STORE INTO THE RESULT, and a CONCATENATION with it: the result is an
    # ordinary frame blob, so both neighbouring operations have to work on it
    # — and `[1, 2] * 2 + [7]` puts the new emitter
    # and the old one next to each other.
    ("repeat_then_store_and_concat",
     "def main() -> Int:\n"
     "    var a = [1, 2] * 2\n"
     "    a[0] = 9\n"
     "    var b = a + [7]\n"
     "    var s = 0\n"
     "    for v in b:\n"
     "        s += v\n"
     "    printf(\"sum=%d len=%d e0=%d\\n\", s, len(b), a[0])\n"
     "    return 0\n",
     "def main():\n"
     "    a = [1, 2] * 2\n"
     "    a[0] = 9\n"
     "    b = a + [7]\n"
     "    s = 0\n"
     "    for v in b:\n"
     "        s += v\n"
     "    print(\"sum=%d len=%d e0=%d\" % (s, len(b), a[0]))\n"),
    # A NESTED REPETITION, `([5] * 2) * 3`: the source of the outer copy is the
    # inner RESULT, so the count the emitter reserves for the outer one is a
    # product of two of them, and the copy reads a blob whose count word was
    # itself just written.
    ("repeat_of_a_repeat",
     "def main() -> Int:\n"
     "    var xs = ([5] * 2) * 3\n"
     "    var s = 0\n"
     "    for v in xs:\n"
     "        s += v\n"
     "    printf(\"sum=%d len=%d\\n\", s, len(xs))\n"
     "    return 0\n",
     "def main():\n"
     "    xs = ([5] * 2) * 3\n"
     "    s = 0\n"
     "    for v in xs:\n"
     "        s += v\n"
     "    print(\"sum=%d len=%d\" % (s, len(xs)))\n"),
    # A COMPREHENSION on the left, and a FOR over the result with no name in
    # between: the repetition as an EXPRESSION rather than as a bound temporary,
    # which is the shape the reproducer's `for x in C` has and the one a
    # reservation made only for a bound name would miss.
    ("repeat_of_a_comprehension_iterated_directly",
     "def main() -> Int:\n"
     "    var s = 0\n"
     "    for v in [i * 2 for i in range(3)] * 2:\n"
     "        s += v\n"
     "    printf(\"sum=%d\\n\", s)\n"
     "    return 0\n",
     "def main():\n"
     "    s = 0\n"
     "    for v in [i * 2 for i in range(3)] * 2:\n"
     "        s += v\n"
     "    print(\"sum=%d\" % s)\n"),
    # A STRING element, where the copied word is a `char *` rather than a
    # number: the copy is a word copy either way, and a program that only ever
    # summed its repetitions would not notice a receiver kind that made `*` a
    # string operation.
    ("repeat_of_a_list_of_strings",
     "def main() -> Int:\n"
     "    var xs = [\"ab\"] * 2\n"
     "    printf(\"n=%d first=%s second=%s\\n\", len(xs), xs[0], xs[1])\n"
     "    return 0\n",
     "def main():\n"
     "    xs = [\"ab\"] * 2\n"
     "    print(\"n=%d first=%s second=%s\" % (len(xs), xs[0], xs[1]))\n"),
]


# `|` on two containers is a SET UNION (`{1,2} | {2,3}` in CPython — a LIST
# pair is a TypeError there, so the operands below are set literals), and the
# two backends now DISAGREE
# HONESTLY about it: arm64 lowers it (`_emit_set_union`, whose left-copy loop was
# leaving on its first iteration for the same reason concat's did, so
# `[1,2] | [2,3]` summed to 5), and x86-64 has no union emitter and used to
# lower it as a plain concatenation — which builds, runs, exits 0 and answers
# `[1, 2, 2, 3]` for a set, 8 where CPython says 6. That is a wrong answer, so
# x86-64 now refuses and names the reason.
#
# It cannot be one of the four-column cases: those require BOTH backends to
# refuse (`refuse_either:`) or both to answer, and this construct is the one
# place where "one answers and one says it cannot" is the correct end state.
# Hence its own runner, which asserts exactly that — and which fails if either
# side changes, because the failure it is watching for is the silent one.
SET_UNION_CASES = [
    ("set_union_is_a_set_on_arm64_and_refused_on_x86_64",
     "def main() -> Int:\n"
     "    var a = {1, 2}\n"
     "    var b = {2, 3}\n"
     "    var s = 0\n"
     "    for v in a | b:\n"
     "        s += v\n"
     "    printf(\"%d\\n\", s)\n"
     "    return 0\n",
     "def main():\n"
     "    a = {1, 2}\n"
     "    b = {2, 3}\n"
     "    s = 0\n"
     "    for v in a | b:\n"
     "        s += v\n"
     "    print(\"%d\" % s)\n"),

    # ── THE SAME UNION, READ AS A VALUE — the row above structurally cannot
    # fail on this, and that is why it is a separate row rather than a comment.
    #
    # The row above walks the result.  A walk reads elements until it hits
    # something else, so it gets the right three even when the count word is
    # wrong — the failure `_emit_set_union` had was a count of `nL + nR`
    # written over a result holding `nL` elements, which made the dedup loop
    # append `3` at index 4 and settle on 5 over the words [1, 2, 3] and two
    # unwritten ones.  Iterating that reads five slots, sums 6, and agrees with
    # CPython on the sum while disagreeing on everything else.
    #
    # `len` reads the count word itself, and so does a walk's own trip count, so
    # both are asked here and CPython is asked both.  Measured on arm64 before
    # the fix: `3 5 6` where CPython says `3 3 6`; and the subscript spelling
    # `c[0], c[1], c[2]` answered `1, 2, 0` where CPython has no subscript for
    # a set at all, which is why this row asks `len` and the trip count rather
    # than reproducing that.  (It is not lost: `c[3]` on a three-element union
    # now exits 1 through the blob bounds check, which is the other half of the
    # same answer.)
    ("set_union_count_read_as_a_value_through_locals",
     "def main() -> Int:\n"
     "    var a = {1, 2}\n"
     "    var b = {2, 3}\n"
     "    var c = a | b\n"
     "    var s = 0\n"
     "    var k = 0\n"
     "    for v in c:\n"
     "        s += v\n"
     "        k += 1\n"
     "    printf(\"%d %d %d\\n\", len(c), k, s)\n"
     "    return 0\n",
     "def main():\n"
     "    a = {1, 2}\n"
     "    b = {2, 3}\n"
     "    c = a | b\n"
     "    s = 0\n"
     "    k = 0\n"
     "    for v in c:\n"
     "        s += v\n"
     "        k += 1\n"
     "    print(\"%d %d %d\" % (len(c), k, s))\n"),

    # THE SAME THROUGH LITERALS, which is a different path and not a
    # variation on the row above: `_blob_est` answers a set literal with its
    # element count and an `IdentExpr` with 64, so the two spellings reserve a
    # different number of words for the result.  A fix that only got the
    # reservation right would pass one of these two rows and fail the other.
    ("set_union_count_read_as_a_value_through_literals",
     "def main() -> Int:\n"
     "    var c = {1, 2} | {2, 3}\n"
     "    var s = 0\n"
     "    var k = 0\n"
     "    for v in c:\n"
     "        s += v\n"
     "        k += 1\n"
     "    printf(\"%d %d %d\\n\", len(c), k, s)\n"
     "    return 0\n",
     "def main():\n"
     "    c = {1, 2} | {2, 3}\n"
     "    s = 0\n"
     "    k = 0\n"
     "    for v in c:\n"
     "        s += v\n"
     "        k += 1\n"
     "    print(\"%d %d %d\" % (len(c), k, s))\n"),
]


def run_set_union_case(name, source, cpython_source, tmpdir, verbose):
    """arm64 must ANSWER CPython; x86-64 must REFUSE, naming the union.

    Both halves are load-bearing and they fail differently. If x86-64 builds
    this again, it is answering with a concatenation and the case says so
    instead of a reader discovering `[1, 2, 2, 3]` where a set belongs. If
    arm64 refuses, the construct has been lost on the backend that can lower it
    — which is the over-refusal this project treats as a regression just as
    much as a wrong answer.
    """
    py = os.path.join(tmpdir, name + ".py")
    with open(py, "w") as f:
        f.write(cpython_source + "\nmain()\n")
    ref = subprocess.run([sys.executable, py], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    if ref.returncode != 0:
        return False, (f"the CPython reference itself failed (exit "
                       f"{ref.returncode}): {ref.stderr.strip()[-200:]}")
    want = ref.stdout
    with open(os.path.join(tmpdir, name + ".mojo"), "w") as f:
        f.write(source)
    out = os.path.join(tmpdir, f"{name}.arm64")
    rc, text = build_formal(os.path.join(tmpdir, name + ".mojo"), out,
                            backend="arm64")
    if rc != 0:
        return False, (f"arm64 REFUSED a set union it lowers: "
                       f"{text.strip()[-300:]}")
    run = subprocess.run([out], capture_output=True, text=True,
                         timeout=RUN_TIMEOUT)
    if run.stdout != want:
        return False, (f"arm64 answered {run.stdout.strip()!r}, CPython "
                       f"{want.strip()!r}")
    out = os.path.join(tmpdir, f"{name}.x86_64")
    rc, text = build_formal(os.path.join(tmpdir, name + ".mojo"), out,
                            backend="x86_64")
    if rc == 0:
        return False, ("x86_64 BUILT `a | b`, which it lowers as a "
                       "concatenation — that is the wrong answer this case "
                       "exists for, and it is silent")
    if "SET UNION" not in text:
        return False, (f"x86-64 refused, but not by naming the union: "
                       f"{text.strip()[-200:]}")
    if verbose:
        print(f"      arm64 answered {want.strip()!r}; x86-64 refused by name")
    return True, ""



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
    # that outlives every frame.  Refused BY NAME until the module BODY's store
    # was recognised as the module's own write — on the tree before this it read
    # whatever register was left.  The trailing `main()` is what makes the
    # answer 10 rather than 0: a module body IS the entry (`entry_function`
    # rule 1) and it calls `main` only if the source says so, which is
    # CPython's own rule for a module-level call.
    ("modsym_a_global_the_module_body_computes",
     "def compute() -> Int:\n"
     "    return 5\n"
     "\n"
     "G = compute()\n"
     "\n"
     "def read_g() -> Int:\n"
     "    return G\n"
     "\n"
     "def main() -> Int:\n"
     "    printf(\"%d\", read_g() * 2)\n"
     "    return 0\n"
     "\n"
     "main()\n", 0, "10"),
    # The other storage shape: an AUGMENTED assignment at module level.  The
    # value is `5 + 2` only after the program has started, so folding it would
    # be a guess about the order of two statements.  7 and not 2 is the whole
    # point: `G = 5` is a FOLDED constant the body would normally drop, and it
    # is kept only because the body rebinds the name (`module_body`'s `rebound`
    # rule).  A slot that starts at the zero an unwritten slot gives would
    # answer 2 — a plausible number, and the wrong one.
    ("modsym_a_module_level_augmented_assignment",
     "G = 5\n"
     "G += 2\n\n"
     "def main() -> Int:\n"
     "    printf(\"%d\", G)\n"
     "    return 0\n"
     "\n"
     "main()\n", 0, "7"),
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
    # ── the same fall-through through a base that is not a NAME ──
    # (`FORMAL_an_attribute_read_through_an_unclassified_base_reads_zero`)
    #
    # A name is only half of what can be a base, and the other half used to
    # answer 0 on arm64 while x86-64 refused: `(7).foo` and `C.A.value` both
    # printed `0`, `g().x` printed `0` where the source says the field's value,
    # and CPython raises `AttributeError` for the first two.  A plausible-looking
    # number and not the program's — the one direction a read must never take.
    #
    # The needle is the LITERAL half of the wording rather than the generic
    # "is a field access through", because that is what distinguishes the fix
    # from the generic refusal every other member case in this file pins: a
    # literal has NO binding at all, so there is nothing to classify and nothing
    # to guess, and the refusal says so.  Both architectures, because the
    # refusal is raised in the SHARED build pass — one architecture refusing
    # what the other answers is the defect, not a difference of opinion.
    ("field_refuse_a_read_through_an_integer_literal",
     "def main() -> Int:\n"
     "    printf(\"%d\\n\", (7).foo)\n"
     "    return 0\n",
     "refuse:which is a LITERAL", None),
    # A CLASS CONSTANT is the same read by another route, and it is here
    # because the refusal for it is raised at a different depth than the case
    # above: `C.A` is a MemberExpr over the class name when the pass runs, and
    # only `_rewrite_class_constants` materializing it is what makes the base a
    # literal.  A refusal asked before that rewrite classified the base as
    # "unclassified" and printed the generic message about a shape the build
    # knows exactly — so this case is also the anti-rot for the ORDERING.
    ("field_refuse_a_read_through_a_class_constant",
     "class C2:\n"
     "    A = 7\n\n"
     "def main() -> Int:\n"
     "    printf(\"%d\\n\", C2.A.value)\n"
     "    return 0\n",
     "refuse:which is a LITERAL", None),
    # The arm a literal needs that the number arm's sentence cannot cover: on a
    # STRING the read is not an AttributeError, it is a BOUND METHOD, which is a
    # real Python value this path has no representation for — there is no slot
    # to read it out of and nothing to store it in.  It used to build and print
    # `(null)`, which is a pointer-shaped answer to a question about a method.
    ("field_refuse_a_bound_method_through_a_string_literal",
     "def main() -> Int:\n"
     "    f = \"ab\".upper\n"
     "    return 0\n",
     "refuse:is a METHOD REFERENCE on", None),
    # The STORE half of the shape, on a base no analysis can classify: `a[0].x`
    # used to evaluate both sides and RETURN, which is a silently discarded
    # store — the program built, ran, and the write was simply not there.
    # `main` returns 0 either way, so again the exit status cannot witness it
    # and the assertion is the refusal.  The needle also pins that the message
    # SPELLS THE BASE: it used to print `….x` through `…`, which names neither
    # the expression the reader wrote nor the one the message is about.
    ("field_refuse_a_store_through_a_subscript_base",
     "def main() -> Int:\n"
     "    var a = [1, 2, 3]\n"
     "    a[0].x = 1\n"
     "    return 0\n",
     "refuse:is a field access through 'a[0]'", None),
    # …and the same store through a call result, which is the shape the doc
    # measured as the silently-dropped one (`g().x = 1`).  Its base is spelled
    # `g(...)` in both halves of the sentence, so the needle checks the
    # agreement between them.
    ("field_refuse_a_store_through_a_call_result",
     "struct P2:\n"
     "    var x: Int\n\n"
     "def g() -> P2:\n"
     "    return P2()\n\n"
     "def main() -> Int:\n"
     "    g().x = 1\n"
     "    return 0\n",
     "refuse:is a field access through 'g(...)'", None),
    # …and the same store inside a TUPLE target, which is a third arm rather
    # than a variant of the second: `a, b = rhs` computes one slot per element
    # and arm64's slot resolver had a line reading "Non-named base: evaluate for
    # effects, store nowhere" — a silently discarded store, in a program that
    # then runs. x86-64's `_tuple_target_key` has refused this shape since, so
    # the same source built on one architecture and was refused on the other,
    # and the case that could see it had to be written per architecture to do
    # so. `b` is a real store on both sides of the test: what is refused is the
    # element before it, not the tuple assignment.
    ("field_refuse_a_tuple_target_through_a_subscript_base",
     "def main() -> Int:\n"
     "    var a = [1, 2, 3]\n"
     "    a[0].x, b = 1, 2\n"
     "    return 0\n",
     "refuse:is a field access through 'a[0]'", None),
    # An MLIR dialect construct the TEMPLATE rules do not cover, so the name
    # check reached it and refused it as "no home" — a symptom of the register
    # fall-through, naming the allocator rather than the construct.  Real
    # stdlib source spells it exactly this way (`std/builtin/value.mojo:203`,
    # `std/sys/debug.mojo:20`).
    #
    # The needle is the classified operation wording rather than the old fixed
    # sentence, because `mlir_dialect_op_refusal` now says what the OPERATION
    # denotes — this one is `lit.materialize_into`, which is in no table, so it
    # takes the honest fallback branch and names itself. What the row is about
    # is unchanged: the construct is refused BY NAME, and both architectures say
    # the same thing, which is the property `test_formal_mlir_precedence.py`
    # pins at the level of a whole construct.
    ("mlir_dialect_name_is_refused_by_construct",
     "def materialize(value) -> Int:\n"
     "    return __mlir_op.`lit.materialize_into`[value=value](value)\n\n"
     "def main() -> Int:\n"
     "    return materialize(1)\n",
     "refuse:is a dialect OPERATION", None),
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
    # BOTH of these used to be REFUSALS naming "this slot's DECLARED type is
    # 'List[Int]'", and they are the two halves of the change
    # `model.ctor_establishes_slot` made: a container cannot come into a slot
    # through a class-level default on this path (a container default is refused
    # by name, `struct_frame_representable`: "the default is not a literal"), so
    # the CONSTRUCTOR was the only remaining door and it was shut.  `S()` DOES
    # run `__init__` — the body is inlined at the construction site — so a value
    # the constructor assigns is a value the object has at every site, and 3 is
    # what `len(b)` returns on both architectures.
    #
    # This IS the shape `std/collections/binary_heap.mojo` is in, which is what
    # this comment used to say and then denied.  It denied it because
    # `BinaryHeap` measured TWO fields: its comptime parameter `T` was in
    # `struct_field_names`, `struct_is_framed` counted it, so `BinaryHeap` was a
    # frame and its `len(self)` became the `__len__` call
    # `formal/build.py`'s `_rewrite_len_on_frame_receivers` makes (see
    # `test_formal_frame_len.py`) — a different construct, which
    # is why the file was refused for a field-VALUE reason on a frame-slot read.
    # `BinaryHeap[T: Copyable & Comparable & Deinitable]` spells its bound as a
    # CONJUNCTION, which the parser did not recognise as a bound and filed as a
    # `VarDecl` field; `fire_compiler._struct_param_is_bound` closes that, and
    # `BinaryHeap` is one field again.  The first of these two cases is its
    # `__len__` in miniature and the second is its `__len__` removed.
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
     3, None),
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
     3, None),
    # ── and the shapes that must STILL be refused, which are the whole of
    # the gate's safety ──
    #
    # Each of these is a case where claiming the kind from the DECLARATION
    # alone would be a wrong answer, and for the first one the wrong answer was
    # MEASURED rather than argued: with the kind taken from `var _data:
    # List[Int]` and nothing else, this built on BOTH architectures, ran, and
    # died with SIGSEGV (exit 139) — `LDR X0, [X0]` with X0 zero, because the
    # slot held 0 and `len` read eight bytes from address 0.  A build that stays
    # green and faults is the failure this suite exists to catch, so the case is
    # here rather than left to the refusal it is.
    ("len_one_word_struct_with_no_constructor_is_refused",
     "struct B:\n"
     "    var _data: List[Int]\n"
     "def main(k: Int) -> Int:\n"
     "    var b = B()\n"
     "    return len(b)\n",
     "refuse:this slot's DECLARED type is 'List[Int]'", None),
    # The constructor's store is not a blob.  `self._data = k` is a WORD, and a
    # word is not `[count][elements…]`, so `len` still has no count to read —
    # the constructor door is not "the struct declares a constructor", it is
    # "every constructor puts a materialized blob in THIS field".
    ("len_one_word_struct_whose_constructor_stores_a_word_is_refused",
     "struct B:\n"
     "    var _data: List[Int]\n"
     "    def __init__(out self, k: Int):\n"
     "        self._data = k\n"
     "def main(k: Int) -> Int:\n"
     "    var b = B(k)\n"
     "    return len(b)\n",
     "refuse:this slot's DECLARED type is 'List[Int]'", None),
    # A container constructor with a `capacity=` RESERVATION, which is a
    # DIFFERENT question from one that has to hold n elements and so is
    # answered: a capacity says how much room to set aside, not what is in the
    # container, and the container is empty either way.  0, not 3 — the count
    # word of the blob is zero and the reservation is not modelled, which
    # `model.blob_constructor_lowering` states as its limits.  This store is the
    # one that kept `ctor_establishes_slot` shut for
    # `std/collections/binary_heap.mojo`, whose second `__init__` is
    # `self._data = List[Self.T](capacity=capacity)`.
    ("len_one_word_struct_constructed_with_a_capacity",
     "struct B:\n"
     "    var _data: List[Int]\n"
     "    def __init__(out self):\n"
     "        self._data = List[Int](capacity=3)\n"
     "def main(k: Int) -> Int:\n"
     "    var b = B()\n"
     "    return len(b)\n",
     0, None),
    # …and the two operand shapes that are STILL a sized blob and so are still
    # refused.  A positional argument says how many elements the container has,
    # which is content rather than reservation, and `model` recognises exactly
    # one reservation keyword because that is the one this stdlib spells.
    ("len_one_word_struct_constructed_with_a_positional_size_is_refused",
     "struct B:\n"
     "    var _data: List[Int]\n"
     "    def __init__(out self):\n"
     "        self._data = List[Int](3)\n"
     "def main(k: Int) -> Int:\n"
     "    var b = B()\n"
     "    return len(b)\n",
     "refuse:has no representation on this path", None),
    ("len_one_word_struct_constructed_with_an_unknown_keyword_is_refused",
     "struct B:\n"
     "    var _data: List[Int]\n"
     "    def __init__(out self):\n"
     "        self._data = List[Int](reserve=3)\n"
     "def main(k: Int) -> Int:\n"
     "    var b = B()\n"
     "    return len(b)\n",
     "refuse:has no representation on this path", None),
    # A TWO-field struct, where the container door is SHUT.  Premise (B1) —
    # `FRAME_FIELD_BLOB_PREMISE_B1`, "no executed method writes a container into
    # a field" — is about the two lifetimes coming apart: the blob would live in
    # the ASSIGNING function's frame while the slot's lifetime is the object's,
    # and the object's frame can outlive the assignment.  A one-field struct has
    # no frame, so its blob is governed by the ordinary value path and the door
    # is open; a multi-field struct has one, so it stays shut.  Same program as
    # the first answered case with one `Int` field added, and that one field is
    # the whole difference.
    ("len_container_field_of_a_two_field_struct_is_refused",
     "struct P:\n"
     "    var _data: List[Int]\n"
     "    var n: Int\n"
     "    def __init__(out self):\n"
     "        self._data = [1, 2, 3]\n"
     "        self.n = 1\n"
     "    def size(self) -> Int:\n"
     "        return len(self._data)\n"
     "def main(k: Int) -> Int:\n"
     "    var p = P()\n"
     "    return p.size()\n",
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
    # ── a module-level literal as `memset`'s BYTE argument ──
    #
    # `FORMAL_folded_module_constant_as_memset_argument`. A module-level
    # name whose value the build FOLDS is substituted at every read BEFORE any
    # emitter runs (`build._substitute_module_constants`), so it never needs a
    # register, a spill slot or a `__DATA` slot of its own. That is what makes
    # this row build, and it is worth stating because the failure it replaced
    # was not a narrow one: `memset(pat + i, PAT_DASH, 1)` was REFUSED with
    # "'PAT_DASH' has no home: the register allocator collected no home for
    # it", and the refusal named whichever constant the allocator ran out of
    # room for, so it tracked the NUMBER of folded constants in a module and
    # read as a property of whichever one lost the race. `argparse.mojo` worked
    # around it by spelling every such byte inline.
    #
    # The answer is checked through `memcmp` rather than through a subscript: a
    # `malloc`'d buffer has no count field, so `buf[i]` is a different question
    # and this case is not about it. Both must be 0 (equal), and the control
    # below is a differing byte, so a `memcmp` that compares nothing cannot pass
    # this row.
    ("folded_module_constant_as_a_memset_byte",
     "PAT_DASH = 45\n"
     "PAT_A = 65\n"
     "\n"
     "def fill(pat, n):\n"
     "    var i: Int = 0\n"
     "    while i < n:\n"
     "        memset(pat + i, PAT_DASH, 1)\n"
     "        i = i + 1\n"
     "    return 0\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    var got = malloc(64)\n"
     "    var want = malloc(64)\n"
     "    memset(want, PAT_DASH, 4)\n"
     "    fill(got, 4)\n"
     "    var same = memcmp(got, want, 4)\n"
     "    memset(got, PAT_A, 2)\n"
     "    memset(want, PAT_A, 2)\n"
     "    var same2 = memcmp(got, want, 2)\n"
     "    return same * 10 + same2\n",
     0, None),
    # GUARD for the row above, and it is what makes that row mean something: the
    # SAME two programs with the constant spelled inline is the behaviour that
    # was always correct, so if the folded spelling were silently substituting
    # the wrong value this would still pass while the row above failed. `1` is a
    # DIFFERENCE, so it can only be produced by a comparison that really looked.
    ("memset_byte_spelled_inline_is_unchanged",
     "def fill(pat, n):\n"
     "    var i: Int = 0\n"
     "    while i < n:\n"
     "        memset(pat + i, 45, 1)\n"
     "        i = i + 1\n"
     "    return 0\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    var got = malloc(64)\n"
     "    var want = malloc(64)\n"
     "    memset(want, 45, 4)\n"
     "    fill(got, 4)\n"
     "    var same = memcmp(got, want, 4)\n"
     "    memset(got, 65, 2)\n"
     "    memset(want, 65, 2)\n"
     "    var same2 = memcmp(got, want, 2)\n"
     "    return same * 10 + (1 - same2)\n",
     1, None),
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


# ── ORDERING a frame address: `<`, `>`, `<=`, `>=` ──────────────────────
#
# The sibling of the four refusals above and the same mistake one operator
# further along: a multi-field struct's receiver is the ADDRESS of a frame of
# 8-byte slots, and every operator that reaches the flag-setting compare is
# therefore operating on an address.  For `+`, `&`, `%` and the shifts that is a
# wrong NUMBER; for `<`, `>` and their non-strict forms it is a wrong BRANCH,
# which is the worse shape because a correct program takes the wrong path and
# nothing downstream can tell.
#
# Measured on BOTH architectures before the refusal, on two objects of a
# two-field struct holding EQUAL field values with a field-wise `__eq__`
# declared: `lt=1 gt=0 le=1 ge=0`.  Four relations decided by nothing in the
# program — by where the allocator put the two frames — and reordering two
# independent statements reverses every one of them.  CPython answers the same
# program with `TypeError: '<' not supported between instances`.
FRAME_ORDER_CASES = [
    ("frame_address_ordering_is_refused",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def __eq__(self, other: Pair) -> Bool:\n"
     "        return self.a == other.a and self.b == other.b\n"
     "def main(n: Int) -> Int:\n"
     "    var x = Pair()\n"
     "    var y = Pair()\n"
     "    x.a = 1\n"
     "    x.b = 2\n"
     "    y.a = 1\n"
     "    y.b = 2\n"
     "    printf(\"lt=%d gt=%d le=%d ge=%d\",\n"
     "           1 if x < y else 0, 1 if x > y else 0,\n"
     "           1 if x <= y else 0, 1 if x >= y else 0)\n"
     "    return 0\n",
     "refuse:orders the ADDRESS of a Pair FRAME", None),
    # The CONDITION form, and it is a separate case because arm64 has a flags
    # fast path for a comparison in a condition that never reaches
    # `_emit_binop` — which is exactly how `if s < t:` came to branch on the
    # interning order of two string literals while `r = s < t` was a build
    # error.  Two spellings of one question disagreeing is how a wrong BRANCH
    # gets in, so the choke point has to be asked at both.
    ("frame_address_ordering_in_a_condition_is_refused",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "def main(n: Int) -> Int:\n"
     "    var x = Pair()\n"
     "    var y = Pair()\n"
     "    x.a = 1\n"
     "    x.b = 2\n"
     "    y.a = 5\n"
     "    y.b = 6\n"
     "    if x < y:\n"
     "        return 1\n"
     "    return 0\n",
     "refuse:orders the ADDRESS of a Pair FRAME", None),
    # The CHAIN, a THIRD emitter that never went through `_emit_binop` — the
    # `s += t` lesson one loop over.
    ("frame_address_ordering_chain_is_refused",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "def main(n: Int) -> Int:\n"
     "    var x = Pair()\n"
     "    var y = Pair()\n"
     "    var z = Pair()\n"
     "    x.a = 1\n"
     "    y.a = 2\n"
     "    z.a = 3\n"
     "    printf(\"chain=%d\", 1 if x < y < z else 0)\n"
     "    return 0\n",
     "refuse:orders the ADDRESS of a Pair FRAME", None),
    # THE GUARD, and it is two guards in one case because the two things a
    # too-eager version of this rule would break are both here.
    #
    #   * `==`, `!=` and `is` on frames are NOT this refusal, and `eq=1` is the
    #     dispatch working: a declared `__eq__` reached through the operator,
    #     which the filing for the operator recorded as open and which
    #     `EQ_DISPATCH_CASES` above owns.  An address compare IS CPython's
    #     inherited `object.__eq__`, so for a struct declaring no dunder it is
    #     the right answer — see `eq_no_declared_dunder_stays_identity`.
    #   * a FIELD comparison is not a frame comparison: `x.a < x.b` reads two
    #     64-bit words, and it is what the refusal tells the reader to write.
    ("guard_field_ordering_and_frame_equality_still_work",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def __eq__(self, other: Pair) -> Bool:\n"
     "        return self.a == other.a and self.b == other.b\n"
     "def main(n: Int) -> Int:\n"
     "    var x = Pair()\n"
     "    var y = Pair()\n"
     "    x.a = 1\n"
     "    x.b = 2\n"
     "    y.a = 1\n"
     "    y.b = 2\n"
     "    var f = 1 if x.a < x.b else 0\n"
     "    var eq = 1 if x == y else 0\n"
     "    var ne = 1 if x != y else 0\n"
     "    printf(\"f=%d eq=%d ne=%d\", f, eq, ne)\n"
     "    return 0\n", 0, "f=1 eq=1 ne=0"),
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
    # A ONE-FIELD struct, whose value is a plain word rather than a frame
    # address — so no holder table has anything to say about the name and
    # `a == b` compared two FIELD VALUES while the method sat there reachable by
    # name.  Measured before: `eq=0 direct=1` on both architectures, where
    # CPython prints `eq=1 direct=1`.
    #
    # The pair is the same question twice, and both halves are needed: the
    # local spelling is the doc's own reproducer and the parameter spelling is
    # what a reader writes when the comparison is in a helper.  The ANNOTATION
    # on `eq`'s parameters is load-bearing and not tidiness — an untyped
    # parameter carries no type on this path, which is the pre-existing limit
    # `declared_param` covers, and this case would then be asserting a rule the
    # backend does not have.
    ("eq_operator_reaches_a_one_field_eq",
     "class One:\n"
     "    x: int\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "def eq(a: One, b: One):\n"
     "    if a == b:\n"
     "        return 1\n"
     "    return 0\n"
     "def main(n):\n"
     "    var a = One(1)\n"
     "    var b = One(3)\n"
     "    printf(\"eq=%d direct=%d\\n\", eq(a, b),\n"
     "           1 if a.__eq__(b) else 0)\n"
     "    return 0\n", 0, "eq=1 direct=1"),
    # The same one-field struct, compared in the scope that BOUND it, so no
    # annotation is involved at all — the case a helper-function spelling cannot
    # reach.  `same` is 1 where the pre-change image printed `diff` and exited
    # 0: the operator had become a compare of 1 against 3.
    ("eq_operator_reaches_a_one_field_eq_in_the_binding_scope",
     "class One:\n"
     "    x: int\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "def main(n):\n"
     "    var a = One(1)\n"
     "    var b = One(3)\n"
     "    printf(\"%d\\n\", 1 if a == b else 0)\n"
     "    return 0\n", 0, "1"),
    # The same one-field struct compared through a CALL BOUNDARY, with the
    # helper's parameters UNTYPED — which is the shape the two cases above cannot
    # reach, and the one a reader writes when the comparison lives in a helper.
    # Before the call-site edge the one-word table was seeded from constructions
    # in the function's OWN body, so a parameter was in it only if some call site
    # in the image handed it a one-word construction, and nothing did that
    # seeding: `eq(a, b)` answered 0 where CPython answers 1, on both machines.
    #
    # The `id` column is why that is a bug and not a coincidence. It compares
    # `a` with ITSELF and answers 1 — by the ADDRESS compare, which is CPython's
    # INHERITED `__eq__` — so the pre-change image printed `eq=0 id=1` for a class
    # whose own method returns True, which reads as "it worked".
    ("eq_operator_reaches_a_one_field_eq_across_a_call",
     "class Tag:\n"
     "    v: int\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "def eq(a, b):\n"
     "    if a == b:\n"
     "        return 1\n"
     "    return 0\n"
     "def main(n):\n"
     "    var a = Tag(5)\n"
     "    var b = Tag(6)\n"
     "    printf(\"eq=%d id=%d\\n\", eq(a, b), eq(a, a))\n"
     "    return 0\n", 0, "eq=1 id=1"),
    # …and TWO boundaries, plus the parameter handed to a SECOND function — the
    # three things a one-shot "read the call sites" fix gets wrong, so they are
    # pinned here rather than discovered one at a time. `eq3` passes `a` twice,
    # which is the same name in two positions, and the edge has to place a
    # candidate at BOTH.
    #
    # The edge is a FIXPOINT (`_seed_one_word_call_edges` is asked again while it
    # moves anything), which is what makes the two-hop column work: `eq2`'s
    # parameters are plain words until `eq2`'s own call sites are read, and `eq`'s
    # parameters are plain words until `eq2`'s are.
    ("eq_operator_reaches_a_one_field_eq_two_hops_and_a_repeated_argument",
     "class Tag:\n"
     "    v: int\n"
     "    def __eq__(self, other):\n"
     "        return True\n"
     "def eq(a, b):\n"
     "    if a == b:\n"
     "        return 1\n"
     "    return 0\n"
     "def eq2(a, b):\n"
     "    return eq(a, b)\n"
     "def eq3(a):\n"
     "    return eq(a, a)\n"
     "def main(n):\n"
     "    var a = Tag(5)\n"
     "    var b = Tag(6)\n"
     "    printf(\"eq=%d %d eq2=%d eq3=%d\\n\", eq(a, b), eq(a, a),\n"
     "           eq2(a, b), eq3(b))\n"
     "    return 0\n", 0, "eq=1 1 eq2=1 eq3=1"),
    # ── a CALL as one of the two operands ──────────────────────────────────
    #
    # The frame case's safety argument is about two words that are both frame
    # ADDRESSES of one struct, and it was settled by asking the HOLDER TABLE,
    # which is keyed by name — so an operand that is a call was never asked
    # about, and the operator stayed a flag-setting compare of two addresses. For
    # two names that is CPython's inherited `object.__eq__`; for a struct that
    # DECLARES one it is a bypass, and a bypass of a field-wise `__eq__` on two
    # DISTINCT objects with equal fields answers False where CPython answers
    # True. Measured, both architectures, `eq=0` where CPython prints `eq=1` —
    # and nothing refused it.
    #
    # The fix reads the CALL's struct off the callee's own DECLARED RETURN TYPE
    # (`model.call_result_frame_struct`), which is an interprocedural fact
    # rather than an inference, and leaves every operand it cannot resolve
    # alone. `mk` is annotated, which is the point: an unannotated callee
    # answers None and the address compare stands.
    ("eq_operator_reaches_a_declared_eq_through_a_call_operand",
     "struct A:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "    def __eq__(self, other: A) -> Bool:\n"
     "        if other.y != self.y:\n"
     "            return False\n"
     "        return self.x == other.x\n"
     "\n"
     "def mk(v: Int) -> A:\n"
     "    var a = A()\n"
     "    a.x = v\n"
     "    a.y = v\n"
     "    return a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var t = mk(1)\n"
     "    printf(\"eq=%d ne=%d diff=%d\", 1 if t == mk(1) else 0,\n"
     "           1 if t != mk(1) else 0, 1 if t == mk(2) else 0)\n"
     "    return 0\n", 0, "eq=1 ne=0 diff=0"),
    # …and the CHAIN, whose ends may each be a call: `mk(1) == t == mk(1)` is
    # two links and each `mk(1)` appears in ONE of them, so the call is evaluated
    # where the source put it. This row exists because the first attempt at it
    # produced a REFUSAL whose message was false about the file — the
    # holder-agreement check counted a frame-returning call as "something that
    # is not a frame address" — which is why that check now asks
    # `_argument_is_frame_address` and reuses `_frame_valued_calls`, the table
    # the emitters build their blocks from.
    ("eq_chain_with_a_call_at_each_end",
     "struct A:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "    def __eq__(self, other: A) -> Bool:\n"
     "        if other.y != self.y:\n"
     "            return False\n"
     "        return self.x == other.x\n"
     "\n"
     "def mk(v: Int) -> A:\n"
     "    var a = A()\n"
     "    a.x = v\n"
     "    a.y = v\n"
     "    return a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var t = mk(1)\n"
     "    printf(\"chain=%d\", 1 if mk(1) == t == mk(1) else 0)\n"
     "    return 0\n", 0, "chain=1"),
    # …and the call in a chain's MIDDLE, which stays an address compare, and is
    # pinned as the ONE remaining shape rather than left to be discovered: the
    # lowering reads each operand twice, so `t == mk(1) == u` would call `mk`
    # three times where the source calls it twice. The remedy is a
    # STATEMENT-level rewrite — bind the operand to a temporary in the enclosing
    # statement, which needs its own round in the holder fixpoint — and it is
    # written down in `bugs/FORMAL_eq_dispatch_on_a_frame_receiver.md` rather
    # than done here.
    ("eq_chain_with_a_call_in_the_middle_stays_an_address_compare",
     "struct A:\n"
     "    var x: Int\n"
     "    var y: Int\n"
     "\n"
     "    def __eq__(self, other: A) -> Bool:\n"
     "        if other.y != self.y:\n"
     "            return False\n"
     "        return self.x == other.x\n"
     "\n"
     "def mk(v: Int) -> A:\n"
     "    var a = A()\n"
     "    a.x = v\n"
     "    a.y = v\n"
     "    return a\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var t = mk(1)\n"
     "    printf(\"chain=%d\", 1 if t == mk(1) == mk(1) else 0)\n"
     "    return 0\n", 0, "chain=0"),
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
    # THE RECEIVER HALF OF THE WIDE OWNER, and it is the one shape in this group
    # whose defect is a WRONG ANSWER rather than a refusal, because a struct of
    # ONE field has no address-shaped cause: its receiver IS its single word.
    #
    #     struct T:
    #         var a: Int
    #         def take(out self, other: Self):
    #             self = other
    #
    # CPython runs that and leaves the caller's object alone — Python has no
    # "assign the receiver" operation, so after `self = other` the method's own
    # `self.a` goes to `other` and `x` is untouched (`a=1`). This path builds,
    # runs, prints the OTHER object's value and exits 0, because a one-field
    # mutator's word is HANDED BACK and stored over the caller's object
    # (`formal/model.py`'s `receiver_writeback_name`) — the same mechanism that
    # makes `self.a = self.a + 4` reach the caller at all.
    #
    # The rule cannot be asked after `_rewrite_self_fields`, which collapses
    # `recv.<field>` onto `recv` and makes this text identical to a field store
    # that must keep working, so `formal/build.py`'s
    # `_collect_one_field_receiver_rebinds` runs before it and
    # `model.receiver_own_type_names` recognises the two spellings of "a
    # reference to an object of the receiver's own type" from declarations.
    # Measured exposure: 0 sites in 1002 files (`tools/
    # formal_receiver_rebind_census.py` counts 51 hand-written `self = …` in
    # one-field methods, 23 constructions and 28 values the method computed, and
    # not one name of the receiver's own type).
    ("one_field_receiver_rebound_to_a_parameter_is_refused",
     "struct T:\n"
     "    var a: Int\n"
     "    def take(out self, other: Self):\n"
     "        self = other\n"
     "def main(n):\n"
     "    var x = T()\n"
     "    x.a = 1\n"
     "    var y = T()\n"
     "    y.a = 2\n"
     "    x.take(y)\n"
     "    return x.a\n",
     "refuse:`other` is a parameter of this method and holds a `T`", None),
    # …and the LOCAL spelling, which is a different object with the same answer:
    # `t` belongs to this method, so Python's later stores through the rebound
    # receiver mutate something nobody outside can name, and this path has no
    # way to deliver that either. A rule that recognised only the parameter
    # spelling would let this one through.
    ("one_field_receiver_rebound_to_a_local_of_its_own_type_is_refused",
     "struct T:\n"
     "    var a: Int\n"
     "    def grab(out self):\n"
     "        var t = T()\n"
     "        t.a = 9\n"
     "        self = t\n"
     "def main(n):\n"
     "    var x = T()\n"
     "    x.a = 1\n"
     "    x.grab()\n"
     "    return x.a\n",
     "refuse:`t` is a local of this method and holds a `T`", None),
    # THE RECEIVER HALF of the row above, and it is a separate rule because the
    # rule above's two REPAIRS do not exist for a receiver: a receiver is not
    # a name the caller can re-declare, and "copy the value out of it first" is
    # not a thing. So the local check skips receiver names by NAME — which is
    # what kept 9 stdlib files building, the ones that write `self = Self(...)`
    # — and this is the question that skipping leaves open.
    #
    # The defect is a DROPPED STORE with an address-shaped cause: a method's
    # write reaches its caller because the caller holds the same address the
    # method dereferences, so rebinding the receiver points the method at a
    # different word and the write never gets back. CPython rejects the shape
    # outright, which is why the message says the source does not mean what it
    # looks like rather than that it computes a different answer.
    ("receiver_rebound_to_a_word_is_refused",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def rebind(self):\n"
     "        self = 5\n"
     "    def read(self):\n"
     "        return self.a\n"
     "def main(n):\n"
     "    var r = R()\n"
     "    r.a = 7\n"
     "    r.rebind()\n"
     "    return r.read()\n",
     "refuse:self is assigned 5 in R_rebind()", None),
    # The receiver spelled something other than `self`, which is why the rule
    # reads the receiver SET rather than the literal name. Without this row a
    # fix that hard-coded `self` would pass the one above.
    ("receiver_rebound_under_another_spelling_is_refused",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def rebind(this):\n"
     "        this = 5\n"
     "def main(n):\n"
     "    var r = R()\n"
     "    r.rebind()\n"
     "    return r.a\n",
     "refuse:this is assigned 5 in R_rebind()", None),
    # A CALL is a refusal too, and it is the shape a real rotation helper uses
    # (`self = self.unsafe_offset(offset)` in stdlib `memory/pointer.mojo`), so
    # this is the row that says the rule is not merely "not a literal".
    ("receiver_rebound_to_a_call_is_refused",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def rebind(self):\n"
     "        self = f()\n"
     "def main(n):\n"
     "    var r = R()\n"
     "    r.rebind()\n"
     "    return r.a\n",
     "refuse:self is assigned f() in R_rebind()", None),
    # THE GUARDS, and they are what make the three above mean something: a rule
    # written as "never rebind a receiver" would refuse all of these, and nine
    # real stdlib files with it.
    #
    # 1. `self = self` — an address moved onto itself. No store, no dropped
    #    write, nothing for a rule to report, and the one spelling of this
    #    statement that is a genuine no-op. A rule of the form "never assign a
    #    receiver" breaks it for no reason.
    #
    #    This row was `receiver_rebound_to_a_same_type_parameter_still_builds`
    #    until 2026-10-02, guarding the OTHER spelling (`self = other` with
    #    `other: Self`) for the reason the bug doc gave. That doc is deleted: its
    #    central claim was false, CPython does not copy on `self = other`
    #    either, and the shape is now pinned with its VALUE by
    #    `both_arch_receiver_copied_from_another_keeps_the_callers_value` in
    #    `BOTH_ARCH_CASES`, which is a stronger row than a bare "it builds" and
    #    would have made this one a second copy of the same program.
    ("receiver_assigned_itself_still_builds",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def noop(out self):\n"
     "        self = self\n"
     "def main(n):\n"
     "    var r = R()\n"
     "    r.a = 3\n"
     "    r.noop()\n"
     "    printf(\"a=%d\", r.a)\n"
     "    return 0\n",
     0, "a=3"),
    # 2. a LOCAL is not a receiver, which is the other half of "the rule reads
    #    the receiver SET": a fix that matched by position rather than by name
    #    would refuse this.
    ("a_local_rebound_inside_a_method_still_builds",
     "struct R:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def set(self):\n"
     "        var q = 5\n"
     "        self.a = q\n"
     "def main(n):\n"
     "    var r = R()\n"
     "    r.set()\n"
     "    printf(\"a=%d\", r.a)\n"
     "    return 0\n",
     0, "a=5"),
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
    # `global` declaration, which the language allows.  It USED to be refused,
    # because a formal value lives in a function's own stack scratch and there
    # was nowhere for a write to a module-level name to outlive a frame in — so
    # both emitters treated the declaration as a no-op and CPython's 6 and 6
    # came out as 10601485 and 5 on arm64 and 11 and 5 on x86-64, with the two
    # architectures unable to agree on the first number because it was never
    # computed.
    #
    # `formal-module-globals` landed the `__DATA` slot that write can be
    # redirected into, and `formal/build.py`'s `_collect_shadowed_global_reads`
    # gates the finding on `declared_globals & assigned - module_slots()`, so a
    # name that HAS a slot is no longer a finding.  The gate's own comment
    # carries the measurement (6 of `test_formal_globals.py`'s 17 cases before,
    # 0 after, and the image answers CPython), and `test_formal_globals.py` was
    # updated with it — this row was left behind asserting a refusal the module
    # no longer owes, and it was red for that reason alone
    # (bugs/TEST_a_mutated_module_global_is_refused_is_stale_after_the_slot_
    # landed.md).
    #
    # So the row asserts the BUILT program's own answer, which is CPython's:
    # `bump()` makes `G` 6 and returns 6, `rd()` reads back 6, and `main`
    # returns 12 — so the exit status is 12.  Renamed from
    # `a_mutated_module_global_is_refused`, because a row whose name says
    # `_is_refused` and whose expectation says otherwise is a lie in the
    # registry; three older bug docs quote the old name in transcripts of runs
    # that happened when it was accurate.
    #
    # The shape `test_formal_globals.py` does not cover is the `return` of the
    # global from inside the writing function, which is why this row is worth
    # keeping rather than folding into that file.
    ("a_mutated_module_global_is_computed",
     "G = 5\n"
     "def bump():\n"
     "    global G\n"
     "    G = G + 1\n"
     "    return G\n"
     "def rd():\n"
     "    return G\n"
     "def main(n):\n"
     "    return bump() + rd()\n",
     12, None),
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
     "def main(k: Int) -> Int:\n    if sshr(0 - 5, 1) == 0 - 3:\n        return 1\n    return 0\n", 1, None),
    # ── a NEGATIVE shift AMOUNT is a trap, not a masked shift ─────────────
    #
    # The third of the three answers a shift amount can have, and the only one
    # that is not a value. `LSL`/`ASR`/`LSR` use the low six bits of the shift
    # register, so `-1 & 63` is 63: `1 << -1` was `-9223372036854775808`
    # (`1 << 63`) and `8 >> -1` was `0`, on BOTH backends, identically, while
    # CPython raises `ValueError: negative shift count` for both. The wrong
    # answer here is a plausible word rather than a failure — a deliberate
    # high-bit set — which is what makes it worth a row of its own.
    #
    # Two halves, because the amount is usually a VARIABLE and a build-time
    # diagnostic cannot see a variable's value:
    #
    #   * a static negative amount is REFUSED at build time, by name, from
    #     `model.negative_shift_refusal` — one wording read by both backends,
    #     because a diagnostic that differs between the two architectures is
    #     not a diagnostic. `0 - 1` rather than `-1` on purpose: it is the
    #     spelling the bug doc's reproducer used, and it is the one a
    #     literal-only `_static_int` does NOT see, so a fix that read the
    #     amount with this backend's private helper would pass the `-1` row
    #     and fail this one.
    #   * a run-time negative amount TRAPS with `model.SHIFT_TRAP_STATUS`, the
    #     same status the divide-by-zero arm leaves behind, so "this program
    #     has no answer" is one answer on this path.
    #
    # The trap rows are exit-status assertions and not `refuse:` cases, which
    # is the point: a run-time trap is not a build refusal, and the two
    # backends have to agree on the STATUS, not merely both fail to build.
    ("refuse_negative_literal_shift_amount_shl",
     "def main(k):\n    printf(\"%ld\", 1 << 0 - 1)\n    return 0\n",
     "refuse:a shift by a negative amount", None),
    ("refuse_negative_literal_shift_amount_shr",
     "def main(k):\n    printf(\"%ld\", 8 >> 0 - 1)\n    return 0\n",
     "refuse:a shift by a negative amount", None),
    # `-1` spelled as a unary minus, which the immediate form's `0 <= v` range
    # check also rejects — so this row is here to say the two spellings of one
    # literal reach the same refusal rather than one of them being emitted.
    ("refuse_negative_unary_shift_amount",
     "def f(x):\n    return x << -1\n"
     "def main(k):\n    printf(\"%ld\", f(1))\n    return 0\n",
     "refuse:a shift by a negative amount", None),
    # The run-time halves. `n` is negative only because main says so, which is
    # what makes them run-time facts rather than build-time ones: the build
    # cannot refuse a program whose amount is a variable, so the answer has to
    # be a status the two backends agree on.
    #
    # 1 and 8 are the two values the bug doc measured, so the rows are the
    # reproducer itself rather than a shape near it.
    ("negative_shift_amount_traps_shl",
     "def shl(x, n):\n    return x << n\n"
     "def main(k):\n    var neg = 0 - 1\n"
     "    printf(\"l=%ld\", shl(1, neg))\n    return 0\n", 1, ""),
    ("negative_shift_amount_traps_shr",
     "def shr(x, n):\n    return x >> n\n"
     "def main(k):\n    var neg = 0 - 1\n"
     "    printf(\"r=%ld\", shr(8, neg))\n    return 0\n", 1, ""),
    # The AUGMENTED spelling, which reaches `_emit_shift_reg` without passing
    # through the binary form at all — so a trap installed only in
    # `_emit_div_shift_pow`/`_emit_shift` would leave `y <<= neg` masking
    # exactly as it did before. This is the same second-emitter hole the
    # saturation rows above are about, in the other direction.
    ("negative_augmented_shift_amount_traps",
     "def main(k):\n    var neg = 0 - 1\n    var y = 3\n"
     "    y <<= neg\n    printf(\"%ld\", y)\n    return 0\n", 1, ""),
    # …and the SUBSCRIPT target, which is the third caller of
    # `_emit_shift_reg` on x86-64 (`p[0] <<= n`). A trap that only the name
    # and binary spellings reach is a trap two of three callers do not have.
    ("negative_subscript_augmented_shift_amount_traps",
     "def main(k):\n    var neg = 0 - 1\n"
     "    var p = [3, 4]\n    p[0] <<= neg\n"
     "    printf(\"%ld\", p[0])\n    return 0\n", 1, ""),
    # THE GUARD, and it is the row that makes the five above mean something: a
    # trap installed by comparing the amount UNSIGNED would take the
    # saturating branch instead and answer 0 for every one of them — a THIRD
    # wrong answer, and one that still "passes" a test that only asserted a
    # non-zero exit on a program that traps anyway. So the amount 63 and the
    # amount 0 — the two nearest non-negative values to the boundary the trap
    # sits on, one on each side of 64's predecessor — must still SHIFT.
    #
    # 63 rather than 12 because 12 is the row `lsl_variable_amount_12` already
    # covers: this one is about the boundary, and 63 is the largest amount the
    # hardware and this path agree to shift by.
    ("negative_shift_trap_leaves_amount_63_shifting",
     "def f(x, n):\n    return x << n\n"
     "def main(k):\n    printf(\"%lx\", f(1, 63))\n    return 0\n", 0,
     "8000000000000000"),
    # …and amount 0, the other side. A trap written as `CMP amount, #0; B.GE`
    # instead of `B.LT` would take it for every shift and this row is what
    # catches that.
    ("negative_shift_trap_leaves_amount_0_shifting",
     "def f(x, n):\n    return x << n\n"
     "def main(k):\n    printf(\"%ld\", f(7, 0))\n    return 0\n", 0, "7"),
]


# `origin_of(x)` — the COMPILE-TIME IDENTITY. It was one of three false
# diagnoses counted in map rows 7 and 8 of the sweep work map, all three now
# fixed (`origin_of` here, a subscript's argument list in
# `model.subscript_index_is_a_comptime_parameter_list`, and `type_of` in
# `model.UNIMPLEMENTED_BUILTINS`).
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
# (`std/builtin/tuple.mojo`, `std/collections/{deque,linked_list,set}.mojo`).
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


# The read-before-store rows are REFUSALS, and they are in their own group
# because they assert a DIAGNOSTIC rather than a value — the whole point is
# that the program must not build, so no exit status can carry the assertion.
# `refuse:` also pins both backends to the same words, which is the property
# these two fixes are really about: one language, two machines.
#
# The ARITY LADDER rows below used to be refusals in this group and are now
# ANSWERED ones (`run_case` dispatches on the expectation, not the group), so
# they no longer say what this paragraph says about them; they are here
# because the diagnosis they record is a diagnosis about a refusal.
# `int(s)` and `int(s, base)` — a PARSE, not a conversion. See
# “FORMAL: `int(s, base)` is refused as a conversion with two operands” (deleted by the commit that landed
# this) for the two-operand refusal that used to fire; what is here is the
# one-operand half, which was WORSE and silent: the arity test did not fire, so
# a string was read as the NUMBER its bit pattern is and `int("41")` answered the
# ADDRESS of the literal — 48694217 on arm64 and 4449243 on x86-64, two
# architectures disagreeing about one program.
#
# Every expected value is CPython's, and each is chosen so a lowering wrong in an
# interesting way prints something else: `0x29` is 41 only if the `0x` PREFIX is
# read, `-7` is negative only if the sign survives, `  41  ` is 41 only if BOTH
# ends' whitespace is, and `ff` is 255 only if the base is the STATED one rather
# than base 10. 0 is in there because `int("0")` is 0: a parse that could not
# tell "parsed zero" from "parsed nothing" would have no way to refuse anything.
INT_PARSE_CASES = [
    ("int_of_a_decimal_string",
     'def main():\n'
     '    printf("%d %d %d %d", int("41"), int("0"), int("-7"),'
     ' int("  41  "))\n'
     '    return 0\n', 0, "41 0 -7 41"),
    ("int_with_a_stated_base",
     'def main():\n'
     '    printf("%d %d %d %d %d", int("41", 10), int("ff", 16),'
     ' int("101010", 2), int("777", 8), int("+7", 10))\n'
     '    return 0\n', 0, "41 255 42 511 7"),
    # A base's own PREFIX, which is the case a reader is most likely to think is
    # about the base rather than about the digits: C's `strtoll` takes `0x` with
    # an explicit 16 and `strtoll`'s auto-detection takes it with 0, and both are
    # this path. It also pins that the base is not double-applied — `0x29` in
    # base 16 is 41, and a lowering that passed 16 twice would not be.
    ("int_in_base_sixteen_reads_the_0x_prefix",
     'def main():\n'
     '    printf("%d %d %d", int("0x29", 16), int("FF", 16), int("0xff", 16))\n'
     '    return 0\n', 0, "41 255 255"),
    # The one-operand form through a PARAMETER, which is the shape a real caller
    # has and the one the emitter's evidence test turns on: an annotated
    # `String` parameter is positively text, and an undecided operand keeps the
    # number conversion.
    ("int_of_a_string_parameter",
     'def parse(s: String) -> Int:\n'
     '    return int(s)\n'
     'def main():\n'
     '    printf("%d %d", parse("41"), parse("-123"))\n'
     '    return 0\n', 0, "41 -123"),
    # …and the CONTROL: `int(n)` for a NUMBER is unchanged, which is what the
    # permissive `None` in `model.int_parse_lowering` exists for. A parse applied
    # to a number would make every numeric `int(x)` in the corpus a parse of
    # digits, and the operand is an unannotated word there.
    ("int_of_a_number_is_still_a_conversion",
     'def widen(n: Int) -> Int:\n'
     '    var v = int(n)\n'
     '    var w = Int32(n)\n'
     '    printf("%d %d", v, w)\n'
     '    return 0\n'
     'def main():\n'
     '    widen(300)\n'
     '    return 0\n', 0, "300 300"),
]

# The four ways the parse is REFUSED, and each is a different fact:
#
#   * a base that is not a constant the build knows — the base is an immediate in
#     both lowerings, so a run-time base would need a slot to survive the call;
#   * base 0, which is CPython's "detect from the prefix" and NOT something
#     `strtoll` does the same way (`model.int_parse_base_is_valid` has the
#     measured table);
#   * a first operand that is not text, which is a CATEGORY error rather than an
#     arity one and so must not borrow the arity sentence;
#   * a base outside 2..36, which is `int(s, 1)` and is refused because neither
#     C nor CPython has a base 1 — a `0 <= base <= 36` test would let it through.
INT_PARSE_REFUSALS = [
    ("int_parse_base_zero_refused",
     "def f(s: String) -> Int:\n    return int(s, 0)\n",
     "refuse:0 is CPython's", None),
    ("int_parse_non_constant_base_refused",
     "def f(s: String, n: Int) -> Int:\n    return int(s, n)\n",
     "refuse:it is not a constant the build knows", None),
    ("int_parse_non_text_first_operand_refused",
     "def f(n: Int) -> Int:\n    return int(n, 16)\n",
     "refuse:the second operand of this call is a BASE", None),
    ("int_parse_base_one_refused",
     "def f(s: String) -> Int:\n    return int(s, 1)\n",
     "refuse:1 is not a base", None),
    ("int_parse_three_operands_refused",
     "def f(s: String) -> Int:\n    return int(s, 16, 3)\n",
     "refuse:takes exactly one value to convert on this path (got 3", None),
]

REFUSAL_CASES = [
    # A FUNCTION NAME in a value position, which is the first thing any
    # first-class-function work hits and the reason `functools` is not a host
    # module (`bugs/FORMAL_functools_is_unbuildable_as_a_host_module.md`).
    # The refusal used to be the unresolved-NAME one, whose reason clause is
    # "the register allocator collected no home for it, so the emitter and the
    # allocation walk disagree about this function's locals" — false in every
    # clause: both know `dbl` is not a local, which is why neither gave it one,
    # and what is actually true is that a function is a code address and a value
    # here is one 64-bit word. The needle is the clause that names the
    # CONSTRUCT, so a change that went back to blaming the allocator fails.
    #
    # Two spellings, because they now reach two DIFFERENT answers and the
    # difference is the point of the pair.
    #
    # The first STORES the name in a local and calls it, and it is a working
    # program: a function value is its entry ADDRESS (each backend's
    # `_load_var`), so `g` holds one word and `g(5)` is one `BLR` / `CALL r64`.
    # It moved from this table to `BOTH_ARCH_CASES` when the lowering landed
    # (`bugs/FORMAL_stdlib_tile_row_is_a_specialization_through_a_function_
    # value.md` §"What landed"); `test_formal_specialization.py` carries the
    # same construct with the CPython comparison this table's `refuse:` rows
    # could not make.
    ("a_function_name_passed_as_an_argument_is_named_as_one",
     "def dbl(x: Int) -> Int:\n"
     "    return x * 2\n\n"
     "def call2(f: Int, a: Int) -> Int:\n"
     "    return f + a\n\n"
     "def main(n: Int) -> Int:\n"
     "    return call2(dbl, 5)\n",
     "refuse:read as a value, and it is passed to `call2()`", None),

    # The ARITY LADDER rows below were REFUSALS here and are ANSWERED ones in
    # `BOTH_ARCH_CASES` now, so they no longer say what the paragraph this group
    # used to open with says about them.  What is left of that history is worth
    # one paragraph, because it is the reason the answered rows are where they
    # are: a function of NINE parameters read its ninth as ZERO — the callee's
    # prologue stopped moving arguments at the register count and `_emit_call`
    # dropped the rest after evaluating them for side effects, so
    # `nine(1,...,9)` returned 1 where the source says 90001.  Zero is the worst
    # possible wrong answer here and the reason is structural: a callee cannot
    # tell a dropped argument from a caller who passed zero, so the value was
    # not merely wrong but INDISTINGUISHABLE from a legitimate one.
    #
    # The refusal that replaced it was RIGHT about the register count and wrong
    # about the consequence: both ABIs put arguments past the register file in
    # the CALLER's frame, and neither convention was implemented, so argument 8
    # (arm64) and argument 6 (x86-64) were refused instead of loaded from it.
    # `formal/hostmods/struct.mojo`'s own "a format I cannot serve returns an
    # empty list" contract was unreachable because of it — `pack(fmt, v0..v7)` is
    # nine arguments — and so was `formal/hostmods/fnmatch.mojo`'s
    # `match_core(7)`, which took `pathlib` and four files in `tools/` with it.
    # ── THE IMPORT DIAGNOSIS OUTRANKS A FRAME REFUSAL ──────────────────────────
    #
    # `_prepare_functions` runs BEFORE `_resolve_imports`, and every frame
    # refusal is raised from inside it. So a file that both trips a frame clause
    # AND imports something used to be reported with the frame sentence — a
    # `codegen` class, a gap in this backend in this file — when the import
    # says the file is out of reach entirely. The reader is sent after a
    # construct they could reach.
    #
    # The codebase has fixed this twice by hand (`check_frame_field_blob_premises`
    # for 67 files of this repository, `check_construction_shapes` for 14 more)
    # and the frame refusals were left inside. What is different now is that
    # `_resolve_imports` needs nothing `_prepare_functions` produces, so the
    # refusal is HELD rather than moved: same words, raised at the first point
    # after the imports have had their say.
    #
    # `p.zz` is the frame clause: a member read through a frame receiver naming
    # a field the struct does not declare, refused by `_frame_receivers` from
    # inside the pipeline. The needle is the import sentence, so this case is
    # asserting the ORDER and nothing else — the frame refusal is still there,
    # it is just asked second.
    ("an_import_outranks_a_frame_refusal",
     "from copy import copy\n"
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    p.a = 3\n"
     "    p.b = 4\n"
     "    return p.zz + n\n",
     "refuse:is a host module (CPython standard library)", None),
    # THE WRITE HALF of the one-word-holder-of-a-frame pair. The read half is
    # `BOTH_ARCH_CASES`'s `one_word_holder_of_a_frame_reads_through_its_method`
    # and it builds and answers 155, because a method handed `b`'s frame
    # address may READ `self.inner.v` as one load at `self + 8*slot(v)`. What it
    # may not do is STORE it: `self.inner = o` is `self = o` after the identity
    # a one-word struct's field and receiver share, so the method overwrites the
    # address the CALLER still holds — the caller's `b` keeps pointing at the
    # original frame, every later `self.v` in the method reads the caller's
    # object, and the program answers a number no source wrote. Measured as
    # exit 139 on BOTH architectures in the window between the two halves.
    #
    # So it is here and not in the answered group: the assertion is that it does
    # not build, and a positive row cannot say that. `_collect_receiver_rebinds`
    # is where the refusal comes from, and it is the same check whose one-field
    # EXEMPTION has to be withdrawn for these owners —
    # `refuse_a_one_field_mutator_that_also_returns_a_value` in
    # `test_formal_bracketed_method_field_set.py` is the exemption still being
    # right for a one-word struct whose field is a plain value, so the two rows
    # together are the whole rule rather than one half of it.
    ("refuse_a_one_word_holder_of_a_frame_stored_through_its_receiver",
     "struct Opt:\n"
     "    var v: Int\n"
     "    var has: Int\n"
     "\n"
     "def mk(k: Int) -> Opt:\n"
     "    var o = Opt()\n"
     "    o.v = k\n"
     "    o.has = 1\n"
     "    return o\n"
     "\n"
     "struct Box:\n"
     "    var inner: Opt\n"
     "\n"
     "    def set(self, o: Opt) -> Int:\n"
     "        self.inner = o\n"
     "        return self.inner.v\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Box()\n"
     "    b.inner = Opt()\n"
     "    b.set(mk(41))\n"
     "    return b.inner.v\n",
     "refuse:self is assigned o in Box_set()", None),
    # The CONTROL, and it is the half that makes the case above mean something:
    # the SAME program without the import is refused by the frame clause, on
    # both architectures. Without this row a change that deleted the frame
    # refusal altogether would leave the row above green.
    ("the_same_frame_refusal_still_fires_without_an_import",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    p.a = 3\n"
     "    p.b = 4\n"
     "    return p.zz + n\n",
     "refuse:P has no field 'zz'", None),
    # EIGHT arguments used to be this row's subject — the boundary arm64
    # answered and x86-64 refused, so it ran on one architecture and could not
    # see the divergence.  Both conventions have a stack area now, and the whole
    # ladder (7, 9, 16 arguments, a stack argument from a caller's parameter, a
    # nested call in argument position, and 6 as the boundary from the other
    # side) is in `BOTH_ARCH_CASES`, where every row builds and runs on both.
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
    # A `while` BODY's store read after the loop, with the counter coming from a
    # PARAMETER. This is the limit `model._preheader_literals` leaves in place
    # and it is pinned here rather than only in
    # `test_formal_read_before_store.py`, because a refusal that holds on one
    # machine and not the other is the divergence this pair of backends is not
    # allowed to have, and `run_case` checks the needle on BOTH for a
    # `refuse:` row without needing the `BOTH_ARCH_CASES` group. CPython raises
    # `UnboundLocalError` for `n == 0`, where the body never runs.
    ("while_body_store_from_a_parameter_refused",
     "def f(n):\n"
     "    var i = n\n"
     "    while i < 3:\n"
     "        t = 1\n"
     "        i = i + 1\n"
     "    printf(\"t=%d\", t)\n"
     "    return 0\n"
     "def main(n: Int) -> Int:\n"
     "    return f(0)\n",
     "refuse:is read at line 6 before anything in this function stores it",
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
    # A name stored in only SOME arm of a branch. This row used to assert the
    # OPPOSITE — that this program still BUILDS — because the check was an
    # ordered walk and could not see it; the pin recorded a deliberate limit
    # rather than leaving it to be rediscovered as a new bug. The limit is gone:
    # the check is a "definitely stored" FIXPOINT over the function's CFG, so a
    # store dominates the read only when every path to the read passes one.
    # CPython raises UnboundLocalError whenever `n` is falsey, and the emitted
    # image has no way to say that: the read returns whatever the CALLER left
    # in the register, which is why this used to print `p=1` by luck.
    ("branch_local_refused",
     "def f(n):\n"
     "    if n:\n"
     "        p = 1\n"
     "    printf(\"p=%d\", p)\n    return 0\n",
     "refuse:is read at line 4 before anything in this function stores it",
     None),
    # The doc's own reproducer, which is the shape the walk could NOT see at
    # all: the store is inside a LOOP, so it is not merely on one arm of an
    # `if` — the loop may run zero times, and `printf` sits after it. Before
    # the fix this built on both backends and printed `t=1`, which is the right
    # answer only by luck.
    ("loop_local_refused",
     "def f(n):\n"
     "    for i in range(3):\n"
     "        if i:\n"
     "            t = 1\n"
     "    printf(\"t=%d\", t)\n    return 0\n",
     "refuse:is read at line 5 before anything in this function stores it",
     None),
    # ── AND THE CONTROLS THAT KEEP THE FIXPOINT FROM OVER-REFUSING ──
    #
    # A refusal that fires on a program CPython accepts breaks working code,
    # so the rows below are as load-bearing as the two above. Each is a name
    # stored on EVERY path to the read, in the shape where a "count the arms"
    # heuristic would also get it right — and each is here because the fixpoint
    # gets it for a different reason than the old walk did.
    #
    # Stored in every arm of an `if`/`else`: the join INTERSECTS the arms'
    # OUT sets, so both storing `p` puts it in the join. The entry function is
    # called with the startup stub's `10` (formal's `-n`), so `n > 100` takes
    # the `else` arm — the row is here to show the FALSE edge stores too, and
    # a case that only ever took the `then` arm would not.
    ("if_else_chain_store_is_dominating",
     "def f(n):\n"
     "    if n > 100:\n"
     "        p = 1\n"
     "    else:\n"
     "        p = 2\n"
     "    printf(\"p=%d\", p)\n    return 0\n",
     0, "p=2"),
    # The same through an `elif` chain, where the missing `else` is the thing
    # that would make it a defect: the false edge falls through from the LAST
    # arm, which is the arm that stores it.
    ("elif_chain_store_is_dominating",
     "def f(n):\n"
     "    if n > 3:\n"
     "        p = 1\n"
     "    elif n > 1:\n"
     "        p = 5\n"
     "    else:\n"
     "        p = 9\n"
     "    printf(\"p=%d\", p)\n    return 0\n",
     0, "p=1"),
    # A `try`'s BODY store dominates after the statement. It used to be
    # `every_handler_stores_is_dominating` — `except Exception: p = 2` — and the
    # handler is gone from the program because a handler arm with a body is now
    # REFUSED: neither emitter emits the arms (`_emit_try` skips them, `RaiseStmt`
    # flushes the pending `finally` clauses and `exit(1)`s), so an arm's store is
    # not in the image and the graph that walked it described a program nobody
    # runs. The refusal is the next case down; this one keeps the RUNNING
    # coverage of the dominance itself, which the `pass` arm does not weaken: the
    # join is reached from the body's exits alone and `p` is in its IN set.
    ("try_body_store_is_dominating_after_the_statement",
     "def f(n):\n"
     "    try:\n"
     "        p = 1\n"
     "    except Exception:\n"
     "        pass\n"
     "    printf(\"p=%d\", p)\n    return 0\n",
     0, "p=1"),
    # …and the refusal itself, on the shape this file already had: a handler
    # that PRINTS. Built and run before the change, it printed nothing and
    # exited 0 — the program silently is not the program that was written, with
    # no refusal, no warning and nothing on stderr. 921 arms in this
    # repository's own 400 files have a body.
    ("refuse_handler_arm_with_a_body",
     "def f(n):\n"
     "    try:\n"
     "        sink(n)\n"
     "    except ValueError:\n"
     "        printf(\"HANDLER RAN\")\n"
     "    return 0\n"
     "\n"
     "def sink(v):\n"
     "    printf(\"s=%d\", v)\n",
     "refuse:is a handler arm with a body this path cannot put in the image",
     None),
    # …and the store in an arm, which is the shape `read_before_store` was
    # answering wrongly: it reported `p` as read before any store, on the
    # strength of a path the image does not have.
    ("refuse_handler_arm_that_stores",
     "def f(n):\n"
     "    try:\n"
     "        sink(n)\n"
     "    except ValueError:\n"
     "        p = 1\n"
     "    printf(\"p=%d\", p)\n    return 0\n"
     "\n"
     "def sink(v):\n"
     "    printf(\"s=%d\", v)\n",
     "refuse:is a handler arm with a body this path cannot put in the image",
     None),
    # A `try`'s `else` clause, which is the shape the whole clause exists for:
    # do the work where it can fail, and use the result only on the path where
    # it did not. It was REFUSED on both architectures — "'p' is read at line 7
    # before anything in this function stores it, and CPython raises
    # UnboundLocalError for that program", which is false about both halves: the
    # clause runs only when the body completed, so `p` is always stored there,
    # and CPython runs the program. The graph reached the clause from the try's
    # header, i.e. from the one path the language skips it on. Same program
    # shape as `test_struct_formal.py:603`, which is where it was measured.
    #
    # The handler arm was `except Exception: return 1`, and a `return` is an
    # effect like any other — an arm whose body says what the program should
    # answer on failure is a program whose answer DEPENDS on which arm ran, and
    # this path cannot compute that. `pass` says the same thing about the
    # clause's reach, which is what this row is for, and keeps running.
    ("try_else_clause_runs_only_when_the_body_completed",
     "def f(n):\n"
     "    try:\n"
     "        p = n + 1\n"
     "    except Exception:\n"
     "        pass\n"
     "    else:\n"
     "        printf(\"p=%d\", p)\n"
     "    return 0\n",
     0, "p=11"),
    # ── a `finally` is emitted at every point the body LEAVES EARLY ──────────
    #
    # `_flush_pending_finally` walks the pending frames and emits a clause's
    # statements AT the `return`/`raise`/`break`/`continue` site, so the clause
    # reads the frame as it stood THERE. `formal/model.py`'s CFG gives the clause
    # that set of predecessors; it used to be "the arms' fall-through, or the
    # body's FIRST block", on the reasoning that "the body may have raised" —
    # and these backends have no unwinder to raise into it (`_emit_try` skips
    # the handler arms outright and `RaiseStmt` flushes and then `exit(1)`s).
    #
    # The program below is one CPython REJECTS — `UnboundLocalError` for
    # `n > 0`, which is the value the startup stub passes — and BOTH backends
    # used to build it and RUN it:
    #
    #     $ ./finally.arm64
    #     8432255232          # sink's argument: a word nobody wrote
    #     exit 100            # CPython: UnboundLocalError, exit 1
    #
    # which is the failure mode no exit code reports: right-looking, status 0,
    # and a number that changes with the build. It is a `refuse:` case rather
    # than an expected answer because there is no answer to expect.
    ("finally_runs_where_the_body_leaves_early_not_at_its_end",
     "def sink(v):\n"
     "    printf(\"v=%d\", v)\n"
     "    return 0\n\n"
     "def f(n):\n"
     "    try:\n"
     "        if n > 0:\n"
     "            return 100\n"
     "        v = 7\n"
     "    finally:\n"
     "        sink(v)\n"
     "    return 0\n\n"
     "def main(n):\n"
     "    return f(n)\n",
     "refuse:'v' is read at line 11 before anything in this function stores it",
     None),
    # …and the CONTROL, which is the direction a fix like that gets wrong: the
    # same clause, with the store before every early exit. `n` is 10, so the
    # `return 100` is the path taken, the clause is emitted there, and `v` is 7.
    # Without this row the `refuse:` above is satisfied by a rule that refuses
    # every `finally` that reads anything.
    ("finally_after_every_early_exit_reads_the_stored_value",
     "def sink(v):\n"
     "    printf(\"v=%d\", v)\n"
     "    return 0\n\n"
     "def f(n):\n"
     "    try:\n"
     "        v = 7\n"
     "        if n > 0:\n"
     "            return 100\n"
     "    finally:\n"
     "        sink(v)\n"
     "    return 0\n\n"
     "def main(n):\n"
     "    return f(n)\n",
     100, "v=7"),
    # …and the dead code after an always-terminating body: `_emit_try`
    # suppresses the clause's own fall-through once an early exit has flushed
    # the frame (`need_fallthrough = False`), so nothing follows the statement.
    # The old rule judged the unreachable `printf` on the state at the body's
    # FIRST block, which refused `try: … total = … / finally: cleanup` then
    # `print(total)` — the single most common reason to write a `finally` at
    # all — on seven files of this repository.
    ("dead_code_after_a_finally_is_not_judged_on_the_bodys_state",
     "def f(n):\n"
     "    try:\n"
     "        total = 1\n"
     "        if n > 0:\n"
     "            total = 2\n"
     "        return 0\n"
     "    finally:\n"
     "        printf(\"done=%d\", total)\n"
     "    printf(\"total=%d\", total)\n"
     "    return 0\n\n"
     "def main(n):\n"
     "    return f(n)\n",
     0, "done=2"),
    # A `for` target STAYS bound after its loop, because the target is a
    # definition in the loop's HEADER and the join is reached from the header's
    # exit edge — so `range(0, 100)` with an immediate break is legal and
    # returns 4. `for_range_break` in the corpus above is the same program; it
    # is named here too because a fixpoint that treated the target as stored by
    # the BODY would refuse the single most ordinary loop in the language.
    ("for_target_survives_its_loop",
     "def f(n):\n"
     "    for i in range(0, 100):\n"
     "        if i > 3:\n"
     "            break\n"
     "    printf(\"i=%d\", i)\n    return 0\n",
     0, "i=4"),
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
    # THE OTHER HALF OF `//`, and a CRASH rather than a wrong answer, which is
    # the shape that makes it worth a row. `fold_arith` reaches Python's
    # operators directly, so a literal-zero divisor raised out of it, out of
    # `eval_const`, out of `resolve_var` and out of the backend — a
    # `ZeroDivisionError` traceback where the reader gets no message at all and
    # no indication of which statement in their file caused it:
    #
    #     $ python3 fire.py build --formal --no-prove -o t t.mojo
    #     build: division by zero
    #     ZeroDivisionError: division by zero
    #
    # Both spellings are here because the guard has to cover the one that was
    # already broken as well as the one the new `//` arm would otherwise have
    # added: `/` was in that table from the start and had the same exposure, so
    # a fix that closed only `//` would have left the identical crash reachable.
    #
    # REFUSING is the right answer and not a trap. At compile time there is
    # nothing running to trap: the value is wanted as a constant and the build
    # does not have one, which is exactly what `comptime_fold_refusal` is for.
    # The runtime's answer to the same question is pinned separately by
    # `both_arch_augmented_division_by_zero_exits_one`, and it is a different
    # question — `x //= 0` has an `x`, this has no program to run.
    ("comptime_division_by_zero_is_refused_not_a_crash",
     "def f(n):\n"
     "    comptime c = 1 / 0\n"
     "    return c\n\n"
     "def main(n: Int) -> Int:\n"
     "    return f(n)\n",
     "refuse:does not fold to a compile-time constant", None),
    ("comptime_floor_division_by_zero_is_refused_not_a_crash",
     "def f(n):\n"
     "    comptime c = 1 // 0\n"
     "    return c\n\n"
     "def main(n: Int) -> Int:\n"
     "    return f(n)\n",
     "refuse:does not fold to a compile-time constant", None),
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


# ── a `comptime` class attribute read through a receiver, against CPython ──
#
# A `comptime NAME = …` in a class body is a compile-time value the class
# PUBLISHES: the parser keeps it in `StructDef.comptime_aliases` and out of
# `StructDef.fields`, and `myinterpreter` resolves `obj.NAME` out of that dict.
# The formal backend had no table for those names at all, so a read of one
# reached the member-access lowering as a name the struct does not have and was
# refused with a sentence about a run-time `AttributeError` — in a program that
# does not raise.
#
# These are CPython PAIRS and not four-column cases because the property under
# test is a VALUE: the substitution has to put the class's own number where the
# read is, and a hand-written expectation in this file is an assertion about the
# lowering made by whoever wrote the lowering. CPython's class attribute is the
# same object by a different route (a dict on the class rather than a `comptime`
# binding), which is the closest available oracle and the one the interpreter
# agrees with.
COMPTIME_ATTRIBUTE_CASES = [
    ("comptime_attribute_receiver_reads_match_cpython",
     "struct Coord:\n"
     "    var rows: Int\n"
     "    var cols: Int\n"
     "    comptime rank: Int = 3\n"
     "    comptime label: String = \"xy\"\n"
     "\n"
     "    def get_rank(self) -> Int:\n"
     "        return self.rank\n"
     "\n"
     "    @staticmethod\n"
     "    def class_rank() -> Int:\n"
     "        return Self.rank\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = Coord(2, 3)\n"
     "    printf(\"%d %d %d %s\", c.get_rank(), Coord.class_rank(), c.rank, "
     "c.label)\n"
     "    return 0\n",
     "import sys\n"
     "class Coord:\n"
     "    rank = 3\n"
     "    label = \"xy\"\n"
     "    def __init__(self, rows, cols):\n"
     "        self.rows = rows\n"
     "        self.cols = cols\n"
     "    def get_rank(self):\n"
     "        return self.rank\n"
     "    @staticmethod\n"
     "    def class_rank():\n"
     "        return Coord.rank\n"
     "def main():\n"
     "    c = Coord(2, 3)\n"
     "    sys.stdout.write(\"%d %d %d %s\" % (c.get_rank(), "
     "Coord.class_rank(), c.rank, c.label))"),
    # The name a subclass REDECLARES, through the class's own spelling, which is
    # unambiguous and therefore answerable: `Base.rank` names Base's value even
    # where `self.rank` inside a method Base declares does not. The pair is here
    # so the refusal and the answer are the two halves of one rule rather than
    # two independent facts.
    ("comptime_attribute_through_the_class_name_is_the_base_value",
     "struct Base:\n"
     "    var a: Int\n"
     "    comptime rank: Int = 3\n"
     "\n"
     "struct Child(Base):\n"
     "    var b: Int\n"
     "    comptime rank: Int = 9\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    printf(\"%d %d\", Base.rank, Child.rank)\n"
     "    return 0\n",
     "import sys\n"
     "class Base:\n"
     "    rank = 3\n"
     "class Child(Base):\n"
     "    rank = 9\n"
     "def main():\n"
     "    sys.stdout.write(\"%d %d\" % (Base.rank, Child.rank))"),

    # ── the two halves of ‘what an enum member is’ that must KEEP working ──────────
    #
    # The refusal rows above are half of one decision; these are the other half,
    # and they are the reason the rule is as narrow as it is.  A field of an enum
    # type is a WORD on this path, so the ordinary enum idiom — a slot compared
    # with a member — is a comparison of two values and answers itself, and a
    # comparison of two `.value` reads is two values too.  Refusing either would
    # cost every reader who writes `self.kind == Kind.A`, which is the shape an
    # enum exists for.
    ("a_slot_compared_with_a_member_is_a_comparison_of_two_values",
     "from enum import Enum\n"
     "\n"
     "class Kind(Enum):\n"
     "    A = 1\n"
     "    B = 2\n"
     "\n"
     "struct Holder:\n"
     "    var kind: Int\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    var h = Holder()\n"
     "    h.kind = Kind.A\n"
     "    if h.kind == Kind.A:\n"
     "        printf(\"A\")\n"
     "    else:\n"
     "        printf(\"B\")\n"
     "    return 0\n",
     "import sys\n"
     "class Kind:\n"
     "    A = 1\n"
     "    B = 2\n"
     "class Holder:\n"
     "    def __init__(self):\n"
     "        self.kind = 0\n"
     "def main():\n"
     "    h = Holder()\n"
     "    h.kind = Kind.A\n"
     "    sys.stdout.write(\"A\" if h.kind == Kind.A else \"B\")\n"),
    # …and the two `.value` reads, where equal values really are equal in
    # CPython too — the row that says the refusal is about IDENTITY and not
    # about the values behind the members.
    ("two_member_values_compare_by_value",
     "from enum import Enum\n"
     "\n"
     "class Reg(Enum):\n"
     "    A = 1\n"
     "    B = 1\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    if Reg.A.value == Reg.B.value:\n"
     "        printf(\"same\")\n"
     "    else:\n"
     "        printf(\"diff\")\n"
     "    return 0\n",
     "import sys\n"
     "class Reg:\n"
     "    A = 1\n"
     "    B = 1\n"
     "def main():\n"
     "    sys.stdout.write(\"same\" if Reg.A == Reg.B else \"diff\")\n"),
    # A MEMBER as a field default, which is the position the value model was
    # refused at: `origin: TypeOrigin = TypeOrigin.DEFAULT` was refused with
    # ‘not a value this build can materialize’ because a member read is not a
    # literal.  It is one word now — the member IS its value — so the field
    # constructs and reads `default`.  A `@dataclass` because that is the corpus
    # case (three files blocked on it) and because the dataclass path raises the
    # refusal itself, so this row is the one that says the fix reached it.
    #
    # Read through `t.origin` and NOT `t.origin.value`: the member is gone from
    # the word, so `.value` on it is a method reference on a string and is
    # refused.  That is the trade this value model makes and the reason the
    # message of the next line is a different question — see
    # `3b733724`.
    ("a_member_as_a_field_default_materializes_to_its_value",
     "from dataclasses import dataclass\n"
     "from enum import Enum\n"
     "\n"
     "class TypeOrigin(Enum):\n"
     "    DEFAULT = \"default\"\n"
     "\n"
     "@dataclass\n"
     "class Type:\n"
     "    origin: TypeOrigin = TypeOrigin.DEFAULT\n"
     "\n"
     "def main(k: Int) -> Int:\n"
     "    var t = Type()\n"
     "    printf(\"%s\", t.origin)\n"
     "    return 0\n",
     "import sys\n"
     "class TypeOrigin:\n"
     "    DEFAULT = \"default\"\n"
     "class Type:\n"
     "    def __init__(self):\n"
     "        self.origin = TypeOrigin.DEFAULT\n"
     "def main():\n"
     "    t = Type()\n"
     "    sys.stdout.write(\"%s\" % t.origin)\n"),
]


# ── a ONE-FIELD struct's MUTATING method (the receiver hand-off) ──────────────
#
# A multi-field struct's receiver is the ADDRESS of a frame of 8-byte slots, so
# `self.f = x` in the callee writes into storage the caller still owns. A
# ONE-field struct's receiver IS its field: `formal/build.py`'s
# `_rewrite_self_fields` turns `self._value` into `self` and `c._value` into `c`,
# so the caller's local and the callee's parameter are the same word in two
# registers and a store to the callee's copy is a store the caller never reads
# back. Measured before the first fix, on BOTH architectures and on the PLAIN
# spelling (`c.bump()`, no brackets anywhere): the program built, ran, and
# printed the value the caller had — the new one was computed and dropped.
#
# **HOW the receiver comes back is the decision this group now pins, and it is
# the second one, not the first.** It used to be the RETURN REGISTER: the callee
# appended `return self` on every path and the caller stored that over the
# expression the receiver was read from (`formal/model.py`'s
# `receiver_writeback_name`). Three shapes dropped that write-back, each measured
# on both architectures, and all three are in this file — one as an answered row
# and two as refusals:
#
#   * a method that ALSO returns a value. The return register was the receiver,
#     so there was nowhere to put one. This is `BinaryHeap.pop() -> Self.T`, the
#     shape that refused the whole 165-file `binary_heap.mojo` sweep row;
#   * a mutator call in a VALUE position — `x = c.bump(4)` — which is the only
#     position the statement-shaped rewrite could express, so nothing was
#     rewritten and the receiver kept the old word. It is now a refusal for a
#     method that declares no return type and an ANSWER for one that does;
#   * a mutator call whose CALLEE IS IN ANOTHER MODULE, which is not in the
#     per-module table the rewrite was built from at all. `byref_cross_module_
#     one_field_mutator` in `CROSS_MODULE_CASES` is that program.
#
# The receiver is now handed over BY REFERENCE: the caller passes the ADDRESS of
# the receiver's own storage (a one-word cell in its frame, which is why
# `_allocation_split` keeps such a local out of every register) and the callee
# writes the new value back through it on every exit. The return register then
# carries only the declared return value, which is what makes "mutate AND return"
# one lowering rather than two — and a store through the caller's own storage
# does not care what position the call is in or which image compiled the callee.
#
# These are the CPython-pair group because that is the only group here that
# builds and runs BOTH architectures and compares the OUTPUT with CPython's —
# which is the assertion this needs, since every defect it had was two machines
# agreeing on the wrong number. The refusals are in the `refuse:` form so BOTH
# backends are asked and the words are required to be IDENTICAL — the same
# property the answered rows need for their output, asserted the other way round.
# They are the boundary of the mechanism rather than a defect in it.
MUTATING_RECEIVER_REFUSALS = [
    # A mutator whose result is USED and which has no result to give. Since the
    # receiver stopped travelling in the return register, the call's value IS the
    # declared return type and nothing else — so a method with no declaration has
    # nothing to put in the expression position, and what the callee happens to
    # leave behind is the fall-through zero. Named rather than emitted, because a
    # number the source never wrote is worse than a refusal.
    ("one_field_mutator_without_a_return_value_used_as_one_is_refused",
     "struct Cell:\n"
     "    var _value: Int\n"
     "\n"
     "    def bump(out self, k: Int):\n"
     "        self._value = self._value + k\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c._value = 5\n"
     "    var x = c.bump(4)\n"
     "    printf(\"%d\", x)\n"
     "    return 0\n",
     "refuse:declares no return type, so the call has no value", None),
    # The evaluation-order shape: one argument list with a hand-off in it AND a
    # read of the same receiver. Left to right the read is evaluated before the
    # call is made, so it sees the old word; the source means the new one.
    # `one_field_mutator_result_nested_in_a_call` is the same program with the
    # read REMOVED, and it builds — which is what makes this a boundary rather
    # than "value positions do not work".
    ("one_field_mutator_read_in_its_own_argument_list_is_refused",
     "struct Cell:\n"
     "    var _value: Int\n"
     "\n"
     "    def pop(out self) -> Int:\n"
     "        var old = self._value\n"
     "        self._value = self._value - 1\n"
     "        return old\n"
     "\n"
     "def sink(a: Int, b: Int):\n"
     "    printf(\"sink %d %d\", a, b)\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c._value = 5\n"
     "    sink(c.pop(), c._value)\n"
     "    return 0\n",
     "refuse:is called in the same argument list that reads", None),
    # A receiver with no ADDRESS. The write-back is a store through the receiver's
    # own storage, so the caller must produce that storage's address, and a
    # SUBSCRIPT is not a place: a formal value is one word and nothing here
    # computed a location for it. `items[0]` rather than a bare `xs` on purpose —
    # `formal/build.py`'s `_rewrite_method_calls` LIFTS this call by name
    # (`Cell_bump(xs[0], 4)`) because `receiver_struct` can answer the element
    # type from the parameter's `List[Cell]` annotation, so the receiver reaching
    # this refusal at all means the lift succeeded and the ADDRESS is the only
    # thing missing. With the element type unstated it never gets here; it is
    # refused earlier, by name, for not knowing what the subscript holds.
    ("one_field_mutator_over_a_subscript_receiver_is_refused",
     "struct Cell:\n"
     "    var _value: Int\n"
     "\n"
     "    def bump(out self, k: Int):\n"
     "        self._value = self._value + k\n"
     "\n"
     "def use(xs: List[Cell]):\n"
     "    xs[0].bump(4)\n"
     "\n"
     "def main() -> Int:\n"
     "    var one = Cell()\n"
     "    one._value = 1\n"
     "    var xs = List[Cell](2)\n"
     "    xs[0] = one\n"
     "    use(xs)\n"
     '    printf("v=%d", one._value)\n'
     "    return 0\n",
     "refuse:is not a place this path can take the address of", None),
    # The one shape the by-reference receiver does not cover: a method that also
    # RETURNS A FRAME. Both conventions want a hidden word — the frame's
    # caller-reserved block and the receiver's one-word cell — and nothing states
    # an order between them, so it is refused rather than guessed. It is the
    # remaining half of what used to be `mutating_receiver_return_refusal`, which
    # is why that diagnostic kept its name while its subject narrowed from
    # "returns a value" to this.
    ("one_field_mutator_that_also_returns_a_frame_is_refused",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct Cell:\n"
     "    var _p: Pair\n"
     "\n"
     "    def swap(out self) -> Pair:\n"
     "        var old = self._p\n"
     "        self._p = Pair()\n"
     "        return old\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c._p.a = 1\n"
     "    var q = c.swap()\n"
     "    printf(\"%d %d\", q.a, c._p.a)\n"
     "    return 0\n",
     "refuse:two hidden-word conventions", None),
]


# ── a call THROUGH a one-field struct's own field ──────────────────────────
#
# `formal/build.py`'s `_rewrite_self_fields` is the identity that keeps
# `self.f` and `self` one storage: a one-field struct's receiver IS its field.
# It cannot tell a field READ from a CALL of that field, because both arrive as
# the same node — and in callee position the rewrite used to collapse the
# callee as well, so `c.f(5)` became `c(5)`, a call of the RECEIVER.  Both
# backends refused that one stage later with the only name they had left:
#
#     `c` is a call through a VALUE rather than through a function of this unit
#
# which is true of the node they held and useless to the reader, who wrote
# `c.f`.  The refusal happens at the rewrite, by name, on both architectures and
# in the same words (`formal/model.py`'s `sole_field_call_refusal`); the
# measurement it answers is in `82c22a48`.
#
# The pair is the assertion: a field READ and a METHOD CALL on the same struct
# must both still build and compute, so a fix that refused every member access on
# a one-field struct — the over-correction this shape invites — fails here.
# Each refusal names the FIELD (`c.f`, `self.f`, `b._leaf.x`), because the
# spelling is the whole point: a message naming `c` sends the reader to the
# wrong line, and costs a second build to discover that `f` is the field.
SOLE_FIELD_CALLEE_REFUSALS = [
    # The reported shape: a field read in callee position on a LOCAL.
    ("call_through_a_one_word_structs_own_field_is_refused_by_its_name",
     "struct Cb:\n"
     "    var f: Int\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = Cb()\n"
     "    var v = c.f(5)\n"
     "    printf(\"%d\", v)\n"
     "    return 0\n",
     "refuse:`c.f` is a call of a VALUE rather than of a function of this "
     "unit", None),
    # THE SAME THING inside the struct's own method, where the receiver is
    # spelled `self` — a different name in the message and therefore a
    # different row.  Before the fix this one said `self`, which reads as "the
    # method's own receiver is the problem".
    ("call_through_a_one_word_receivers_own_field_is_refused_by_its_name",
     "struct Cb:\n"
     "    var f: Int\n"
     "\n"
     "    def go(self) -> Int:\n"
     "        var v = self.f(5)\n"
     "        return v\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = Cb()\n"
     "    printf(\"%d\", c.go())\n"
     "    return 0\n",
     "refuse:`self.f` is a call of a VALUE rather than of a function of this "
     "unit", None),
    # The TRANSITIVE chain, which is the same rule reached through
    # `_one_word_sole_field_chain` walking two structs: `Box`'s sole field is
    # `Leaf`, `Leaf`'s is `x`, so `b._leaf.x` and `b` are one word.  This is the
    # row that says the refusal covers the chain and not just the one-hop
    # spelling, and the row a fix that compared the chain's LENGTH against the
    # map's would fail.
    ("call_through_a_transitive_sole_field_chain_is_refused_by_its_name",
     "struct Leaf:\n"
     "    var x: Int\n"
     "\n"
     "struct Box:\n"
     "    var _leaf: Leaf\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Box(Leaf(5))\n"
     "    printf(\"%d\", b._leaf.x(1))\n"
     "    return 0\n",
     "refuse:`b._leaf.x` is a call of a VALUE rather than of a function of "
     "this unit", None),
    # A local whose name is ALSO a module-level function — and this is the
    # case where the old collapse was not even a refusal.  `c.f(5)` became
    # `c(5)`, which is a call of the function `c` this unit compiles, so it
    # BUILT, ran, and printed 10 where CPython raises `TypeError: 'int' object
    # is not callable`.  The row asserts the refusal, because "it computes
    # something" is the worse outcome here and the only way to say so is to
    # refuse.
    ("a_call_through_a_field_is_not_the_function_the_receiver_is_named_after",
     "struct Cb:\n"
     "    var f: Int\n"
     "\n"
     "def c(n: Int) -> Int:\n"
     "    return n * 2\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = Cb()\n"
     "    printf(\"%d\", c.f(5))\n"
     "    return 0\n",
     "refuse:`c.f` is a call of a VALUE rather than of a function of this "
     "unit", None),
    # A METHOD CALLEE whose name the receiver's own struct declares as a method.
    # `check_value_position_method_reads` walks the body's member expressions and
    # cannot tell a callee from a value read, so `self.clear` in
    # `self._data.clear()` -- `_data` collapsed into the receiver by
    # `_rewrite_self_fields`, because a one-field struct's receiver IS its field
    # -- was reported as a field READ of a method, with the message "Call it
    # (`self.clear(...)`), which is a receiver and a call and lowers" about an
    # expression that IS already a call.  This is the construct
    # `bugs/FORMAL_binary_heap_mojo_after_the_len_value.md` §3 row 0a names, and
    # it is the file's reported verdict.
    #
    # The expectation WAS the METHOD-TABLE refusal and is now a BUILD, because
    # `List.clear` landed (row 1 of `bugs/FORMAL_binary_heap_mojo_after_the_len_
    # value.md`'s table).  Two things in the note above were corrected by that
    # landing, and both are worth the row staying here as a build rather than
    # moving out of the group: the collapsed receiver is NOT one "the emitter
    # cannot type" — `_method_recv_kind(self)` answers `list`, from the field's
    # declared type through `one_word_receiver_kind`, which is what made the
    # one-store lowering possible at all; and `clear` is not "not in its table"
    # any more.
    #
    # `size=%d`/`after=%d` are here so the row is not a bare exit status: they
    # are only reachable if BOTH `len(self._data)` and `self.clear()` lower,
    # and the numbers are 0 and 0 for the reason the constructor is
    # `List[Int]()` — an EMPTY list.  The row that shows the store landing is
    # `test_formal_x86_64_parity.py`'s
    # `list_clear_through_a_one_word_structs_sole_field`, whose constructor puts
    # three elements in and prints the length before and after; this one keeps
    # the zero-operand construction, which is the OTHER of
    # `ctor_establishes_slot`'s two doors.
    ("a_method_callee_through_a_collapsed_field_is_not_a_field_read",
     "struct Wrap:\n"
     "    var _data: List[Int]\n"
     "\n"
     "    def __init__(out self):\n"
     "        self._data = List[Int]()\n"
     "\n"
     "    def clear(mut self):\n"
     "        self._data.clear()\n"
     "\n"
     "    def size(self) -> Int:\n"
     "        return len(self._data)\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var w = Wrap()\n"
     '    printf("size=%d", w.size())\n'
     "    w.clear()\n"
     '    printf(" after=%d", w.size())\n'
     "    return 0\n",
     0, "size=0 after=0"),
]

# The two spellings that must keep BUILDING, as the CPython-pair shape, because
# the assertion is about an answer rather than about a message: a field READ and
# a METHOD CALL on a one-word struct, and a method call THROUGH such a field.
# They are here rather than in the refusal group because "must not be refused"
# is not a refusal expectation — `refuse_either:` asserts that the build FAILS.
# `5` is the field's value, `5 5` is the read and the method on one struct.
SOLE_FIELD_CALLEE_CASES = [
    ("a_one_word_fields_read_and_method_both_answer",
     "struct Cell:\n"
     "    var _v: Int\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self._v\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = Cell()\n"
     "    c._v = 5\n"
     "    printf(\"%d %d\", c._v, c.get())\n"
     "    return 0\n",
     "import sys\n"
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self._v = 0\n"
     "    def get(self):\n"
     "        return self._v\n"
     "def main():\n"
     "    c = Cell()\n"
     "    c._v = 5\n"
     "    sys.stdout.write(\"%d %d\" % (c._v, c.get()))\n"),
    # A method call THROUGH the field, which is the shape a fix that refused
    # every chain through a sole field would take with it.
    # `_rewrite_one_word_field_method_calls` lifts it to `Leaf_get(b)` before
    # `_rewrite_self_fields` runs, so the chain in the callee is `b._leaf.get`
    # and it is not a prefix of the map's `_leaf.x`.  The declared-type twin of
    # this row is `test_formal_receiver_spelling.py`'s
    # `one_word_field_through_one_field_receiver`; this one has no declaration to
    # read, so the lift is off the binding `b = Box(...)` alone.
    ("a_method_through_a_transitive_sole_field_is_still_answered",
     "struct Leaf:\n"
     "    var x: Int\n"
     "\n"
     "    def get(self) -> Int:\n"
     "        return self.x\n"
     "\n"
     "struct Box:\n"
     "    var _leaf: Leaf\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Box(Leaf(5))\n"
     "    printf(\"%d\", b._leaf.get())\n"
     "    return 0\n",
     "import sys\n"
     "class Leaf:\n"
     "    def __init__(self, x):\n"
     "        self.x = x\n"
     "    def get(self):\n"
     "        return self.x\n"
     "class Box:\n"
     "    def __init__(self, leaf):\n"
     "        self._leaf = leaf\n"
     "def main():\n"
     "    b = Box(Leaf(5))\n"
     "    sys.stdout.write(\"%d\" % b._leaf.get())\n"),
]

ONE_FIELD_MUTATOR_CASES = [
    ("one_field_mutator_no_args",
     "struct Cell:\n"
     "    var _value: Int\n"
     "\n"
     "    def bump(out self):\n"
     "        self._value = self._value + 4\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c._value = 5\n"
     "    c.bump()\n"
     "    printf(\"%d\", c._value)\n"
     "    return 0\n",
     "import sys\n"
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self._value = 0\n"
     "    def bump(self):\n"
     "        self._value = self._value + 4\n"
     "def main():\n"
     "    c = Cell()\n"
     "    c._value = 5\n"
     "    c.bump()\n"
     "    sys.stdout.write(\"%d\" % c._value)"),
    # WITH a runtime argument, so the answer cannot be confused with a stale
    # register that happens to hold the right number — the second of the two
    # cases the bug doc asks for, and the one that catches a write-back which
    # recomputes rather than propagates.
    # The `k` is what makes this row different from the one above: the callee
    # ADDS something the caller chose at run time, so a write-back that dropped
    # the callee's word and re-emitted the old one, or that propagated the
    # argument instead of the receiver, gives a different number. 5 + 4 is 9,
    # which is neither the value before (5) nor the argument (4).
    ("one_field_mutator_with_an_argument",
     "struct Cell:\n"
     "    var _value: Int\n"
     "\n"
     "    def bump(out self, k: Int):\n"
     "        self._value = self._value + k\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c._value = 5\n"
     "    c.bump(4)\n"
     "    printf(\"%d\", c._value)\n"
     "    return 0\n",
     "import sys\n"
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self._value = 0\n"
     "    def bump(self, k):\n"
     "        self._value = self._value + k\n"
     "def main():\n"
     "    c = Cell()\n"
     "    c._value = 5\n"
     "    c.bump(4)\n"
     "    sys.stdout.write(\"%d\" % c._value)"),
    # An EARLY RETURN is the case that separates \"every path hands the receiver
    # back\" from \"the last statement returns it\": a method that returns
    # nothing on one path would hand the caller whatever the return register
    # held, and the caller would store that over the object\'s value.
    ("one_field_mutator_early_return_still_hands_the_receiver_back",
     "struct Cell:\n"
     "    var _value: Int\n"
     "\n"
     "    def bump(out self, k: Int):\n"
     "        if k > 100:\n"
     "            return\n"
     "        self._value = self._value + k\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = Cell()\n"
     "    c._value = 5\n"
     "    c.bump(4)\n"
     "    printf(\"%d\", c._value)\n"
     "    return 0\n",
     "import sys\n"
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self._value = 0\n"
     "    def bump(self, k):\n"
     "        if k > 100:\n"
     "            return\n"
     "        self._value = self._value + k\n"
     "def main():\n"
     "    c = Cell()\n"
     "    c._value = 5\n"
     "    c.bump(4)\n"
     "    sys.stdout.write(\"%d\" % c._value)"),
    # THE GUARD, and it is the row that makes the three above mean something: a
    # one-field struct\'s method that only READS its receiver is not a mutator
    # and must not acquire a write-back. If the rule were \"every method of a
    # one-field struct returns its receiver\", this would store the receiver
    # over the caller\'s local on a call that changed nothing — still right by
    # accident here, and wrong the moment the caller\'s local had been rebound
    # in between.
    # A reader in a VALUE position, which is the shape that makes the guard
    # discriminating rather than decorative: the write-back refuses a mutator
    # call used as a value (see `one_field_mutator_in_a_value_position_is_refused`),
    # so a rule written as "every method of a one-field struct hands its
    # receiver back" would REFUSE this program. It has to build, and the `* 10`
    # means a write-back that fired anyway would also store the wrong number.
    ("one_field_reader_is_not_a_mutator",
     "struct Cell:\n"
     "    var _value: Int\n"
     "\n"
     "    def scaled(self) -> Int:\n"
     "        return self._value * 10\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c._value = 5\n"
     "    printf(\"%d %d\", c.scaled(), c._value)\n"
     "    return 0\n",
     "import sys\n"
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self._value = 0\n"
     "    def scaled(self):\n"
     "        return self._value * 10\n"
     "def main():\n"
     "    c = Cell()\n"
     "    c._value = 5\n"
     "    sys.stdout.write(\"%d %d\" % (c.scaled(), c._value))"),
    # …and the OTHER representation, unchanged: a two-field struct\'s receiver is
    # a frame address, so its mutating method already reached the caller and must
    # keep doing so through the ordinary store. If the write-back were applied by
    # \"a method that assigns to self\" rather than by \"a one-field receiver\",
    # this row would double-store and the value would be the same — so it is here
    # to say the framed path was not touched, and its value is checked against
    # CPython like every other pair row.
    # ── a mutator that ALSO RETURNS A VALUE ──────────────────────────────────
    #
    # The shape `std/collections/binary_heap.mojo`'s `pop(mut self) -> Self.T`
    # is, and the one that used to be refused outright: the return register was
    # the receiver, so a method that both changed the receiver and produced a
    # value had nowhere to put the value. It is `mutating_receiver_return_refusal`
    # at its worst, and it is what held 165 sweep files.
    #
    # TWO pops rather than one, because a single pop's answer and the receiver's
    # new value could be confused for each other in a way two cannot: `5 4 3` says
    # the first call returned the value from BEFORE it, the second returned the
    # value from between the two, and the object ended at 3. A write-back that
    # stored the wrong register gives `5 5 5`; one that dropped the second pop's
    # effect gives `5 4 4`.
    ("one_field_mutator_that_also_returns_a_value",
     "struct Cell:\n"
     "    var _value: Int\n"
     "\n"
     "    def pop(out self) -> Int:\n"
     "        var old = self._value\n"
     "        self._value = self._value - 1\n"
     "        return old\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c._value = 5\n"
     "    var a = c.pop()\n"
     "    var b = c.pop()\n"
     "    printf(\"%d %d %d\", a, b, c._value)\n"
     "    return 0\n",
     "import sys\n"
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self._value = 0\n"
     "    def pop(self):\n"
     "        old = self._value\n"
     "        self._value = self._value - 1\n"
     "        return old\n"
     "def main():\n"
     "    c = Cell()\n"
     "    c._value = 5\n"
     "    a = c.pop()\n"
     "    b = c.pop()\n"
     "    sys.stdout.write(\"%d %d %d\" % (a, b, c._value))"),
    # …with an ARGUMENT, so the receiver write-back and the declared value are
    # both live at a call whose receiver the caller chose at run time. `a=-1 c=0`
    # then `b=7 c=10` says both branches: the early return writes AND returns,
    # and the ordinary path adds the argument and returns the value from before
    # it. The object is re-seeded between the two calls so the second number is
    # not a continuation of the first.
    ("one_field_mutator_returning_a_value_from_two_paths",
     "struct Cell:\n"
     "    var _value: Int\n"
     "\n"
     "    def take(out self, k: Int) -> Int:\n"
     "        if k > 100:\n"
     "            self._value = 0\n"
     "            return -1\n"
     "        var old = self._value\n"
     "        self._value = self._value + k\n"
     "        return old\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c._value = 7\n"
     "    var a = c.take(200)\n"
     "    printf(\"a=%d c=%d\", a, c._value)\n"
     "    c._value = 7\n"
     "    var b = c.take(3)\n"
     "    printf(\" b=%d c=%d\", b, c._value)\n"
     "    return 0\n",
     "import sys\n"
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self._value = 0\n"
     "    def take(self, k):\n"
     "        if k > 100:\n"
     "            self._value = 0\n"
     "            return -1\n"
     "        old = self._value\n"
     "        self._value = self._value + k\n"
     "        return old\n"
     "def main():\n"
     "    c = Cell()\n"
     "    c._value = 7\n"
     "    a = c.take(200)\n"
     "    sys.stdout.write(\"a=%d c=%d\" % (a, c._value))\n"
     "    c._value = 7\n"
     "    b = c.take(3)\n"
     "    sys.stdout.write(\" b=%d c=%d\" % (b, c._value))"),
    # A mutator whose result is NESTED in another call, which is the second of the
    # three shapes that used to drop the write-back: `sink(c.bump(5))` has no
    # statement for the old rewrite to put a store in, so the callee computed 15,
    # `twice` printed 10 and the object kept 10. `10 4` says the value came out
    # of the nested call (5 doubled) AND the object moved (5 -> 4), which is the
    # whole of the by-reference convention.
    ("one_field_mutator_result_nested_in_a_call",
     "struct Cell:\n"
     "    var _value: Int\n"
     "\n"
     "    def pop(out self) -> Int:\n"
     "        var old = self._value\n"
     "        self._value = self._value - 1\n"
     "        return old\n"
     "\n"
     "def twice(v: Int) -> Int:\n"
     "    return v * 2\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c._value = 5\n"
     "    printf(\"%d %d\", twice(c.pop()), c._value)\n"
     "    return 0\n",
     "import sys\n"
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self._value = 0\n"
     "    def pop(self):\n"
     "        old = self._value\n"
     "        self._value = self._value - 1\n"
     "        return old\n"
     "def twice(v):\n"
     "    return v * 2\n"
     "def main():\n"
     "    c = Cell()\n"
     "    c._value = 5\n"
     "    sys.stdout.write(\"%d %d\" % (twice(c.pop()), c._value))"),
    # A mutator with an UNDECLARED return type and an early `return <literal>`:
    # the spelling a hand-written method has, and the other half of what
    # `mutating_receiver_return_refusal` used to refuse. It is an ANSWER now and
    # deliberately so: the call is a statement, so there is no value position to
    # fill, and the early `return 1` leaves a word in the return register that
    # nobody reads. CPython returns 1 there too, and the object is 9 either way,
    # which is the row that says the early exit did not skip the write-back.
    ("one_field_mutator_returning_a_literal_has_no_return_type",
     "struct Cell:\n"
     "    var _value: Int\n"
     "\n"
     "    def bump(out self, k: Int):\n"
     "        if k > 100:\n"
     "            return 1\n"
     "        self._value = self._value + k\n"
     "\n"
     "def main() -> Int:\n"
     "    var c = Cell()\n"
     "    c._value = 5\n"
     "    c.bump(4)\n"
     "    printf(\"%d\", c._value)\n"
     "    return 0\n",
     "import sys\n"
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self._value = 0\n"
     "    def bump(self, k):\n"
     "        if k > 100:\n"
     "            return 1\n"
     "        self._value = self._value + k\n"
     "def main():\n"
     "    c = Cell()\n"
     "    c._value = 5\n"
     "    c.bump(4)\n"
     "    sys.stdout.write(\"%d\" % c._value)"),
    ("two_field_mutator_is_unchanged",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def bump(out self, k: Int):\n"
     "        self.a = self.a + k\n"
     "\n"
     "def main() -> Int:\n"
     "    var p = Pair()\n"
     "    p.a = 5\n"
     "    p.b = 1\n"
     "    p.bump(4)\n"
     "    printf(\"%d\", p.a)\n"
     "    return 0\n",
     "import sys\n"
     "class Pair:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "    def bump(self, k):\n"
     "        self.a = self.a + k\n"
     "def main():\n"
     "    p = Pair()\n"
     "    p.a = 5\n"
     "    p.b = 1\n"
     "    p.bump(4)\n"
     "    sys.stdout.write(\"%d\" % p.a)"),
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
    # WITH ARGUMENTS that are CONTENT it is a genuinely different question and
    # gets its own diagnostic, which says why: a blob's size is fixed when the
    # function is laid out, so one that must hold n elements needs a reservation
    # sized by a value the compiler does not have. Before the diagnostic existed
    # this was refused as "has no representation on this path", which is FALSE
    # about the empty form and true about this one, and so true of neither — the
    # diagnostic this row pins is the one that says both halves.
    #
    # It was `capacity=n`, and `capacity=n` no longer belongs here: a capacity is
    # a RESERVATION rather than content, so
    # `model.blob_constructor_lowering` answers it with the empty container and
    # `len_container_field_constructed_with_a_positional_size_is_refused` is the
    # row that keeps the class. The needle still says "the empty form is a
    # different question" because that clause is what makes the refusal a
    # statement about CONTENT.
    ("blob_constructor_with_operands_is_refused_by_its_own_reason",
     "def main(n: Int) -> Int:\n"
     "    var xs = List[Int](n)\n"
     "    return 0\n",
     "refuse:the empty form is a different question", None),
    # …and the reservation form, which is the case this file's row above used to
    # pin as a refusal and which now has to be pinned as an ANSWER instead, or
    # nothing would notice it changing back. `len(xs)` is 0 because the
    # container a capacity builds is empty; the room is not modelled and
    # `blob_constructor_lowering`'s docstring is where that is written down.
    ("blob_constructor_with_a_capacity_operand_is_the_empty_container",
     "def main(n: Int) -> Int:\n"
     "    var xs = List[Int](capacity=n)\n"
     "    printf(\"n=%d\", len(xs))\n"
     "    return 0\n",
     0, "n=0"),
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

# The model itself, imported rather than a table of its answers: a tag is a hash
# of a canonical name, and a literal written here would be a second
# implementation of that hash in a test.
_TYPE_VALUE_MODEL = __import__("formal.model", fromlist=["model"])


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
    # The NARROW float formats and `UInt128`, which were 202 corpus spellings
    # refused as "a name no table in formal/model.py lists". The expected values
    # are `model.type_tag` read from the model rather than written down here,
    # and that is the right oracle for THIS row specifically: a tag IS a hash of
    # the canonical name, so a constant typed by hand would be a second
    # implementation of the same hash in a test. What the row asserts is the
    # thing the list exists for — every one of the ten corpus spellings is a
    # word, the member and the bare type name are the SAME word, and two
    # different formats are DIFFERENT words (which is the injectivity property
    # the closed set buys, checked here where a reader can see it).
    ("type_value_narrow_float_formats_and_uint128_are_tags",
     "def main(n: Int) -> Int:\n"
     "    var a = 0\n"
     "    if DType.float8_e4m3fn == Float8_e4m3fn:\n        a = a + 1\n"
     "    if DType.float8_e5m2 == Float8_e5m2:\n        a = a + 2\n"
     "    if DType.uint128 == UInt128:\n        a = a + 4\n"
     "    if DType.float4_e2m1fn != Float4_e2m1fn:\n        a = a + 8\n"
     "    printf(\"h=%d@@\", a)\n"
     "    printf(\"i=%d@@\", DType.float6_e3m2fn != DType.float8_e3m4)\n"
     "    printf(\"j=%d@@\", DType.float8_e4m3fnuz != DType.float8_e5m2fnuz)\n"
     "    printf(\"k=%d@@\", DType.float8_e8m0fnu != UInt128)\n"
     "    return 0\n",
     0, "h=7@@i=1@@j=1@@k=1@@"),
    # …and the WORDS themselves, because "it built" is not "it is the right
    # word": a member that resolved to some OTHER type's tag would satisfy
    # every comparison above and answer a program wrongly. `print()` and not
    # `printf("%d")`, which is the reason the expected values are the full
    # 64-bit tags: `%d` is a 32-bit conversion in C and every one of the 67
    # admitted tags is above 2**31 — `bool`'s included, which is why
    # `TYPE_VALUE_NUMBER_CASES` below uses `print` for the same reason.
    ("type_value_dtype_narrow_format_tags_are_the_model_words",
     "def main(n: Int) -> Int:\n"
     "    a = DType.float8_e4m3fn\n    print(a)\n"
     "    b = DType.uint128\n    print(b)\n"
     "    c = DType.float8_e3m4\n    print(c)\n"
     "    return 0\n",
     0, "\n".join(str(_TYPE_VALUE_MODEL.type_tag(n)) for n in
                   ("Float8_e4m3fn", "UInt128", "Float8_e3m4"))),
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
    # A `DType` member naming a real Mojo type whose NAME is in no table here.
    # **This used to be the corpus's own spellings** — the float8/float6/float4
    # formats and `uint128`, 202 of them — and it is now a member outside the
    # closed list in `TYPE_VALUE_NAMES`, which is the boundary that keeps
    # `type_value_tags_are_distinct` a proof over a finite set rather than a
    # hope over a shape rule. A format Mojo has and this list does not is
    # refused, and still with the member named, because the emitter's own
    # fallback says "is a field access through 'DType'" — a struct field where
    # there is a missing table entry, which sends the reader to the wrong file.
    ("an_unknown_dtype_member_is_refused_by_name",
     "def main(n: Int) -> Int:\n"
     "    return Int(DType.float8_e7m0fnu)\n",
     "refuse:DType.float8_e7m0fnu names a type", None),
    # `len()` of a type.  This was a GUARD against making a type a VALUE turning
    # `len()` of one into a count, and the guard held; what it also pinned was the
    # imprecision: "the source does not say what this operand holds … Annotate it
    # (`x: String`)" is FALSE about `len(bool)`, because the source says `bool` at
    # the use site and the advice is to annotate a name that already has a type.
    # So the row is now `refuse_without:` — the same program, asserting the false
    # sentence is gone AND that a type-specific one replaced it, which a wholesale
    # deletion of the message would not satisfy.  The old needle is the FORBIDDEN
    # half, which is why the two clauses are one case rather than two.
    ("len_of_a_type_is_refused",
     "def main(n: Int) -> Int:\n"
     "    return len(bool)\n",
     "refuse_without:len(bool) is len() of a TYPE:"
     "the source does not say what this operand holds", None),
    # The same message for a LOCAL BOUND TO A TYPE, which is the half that needed
    # a kind of its own: `t = bool` bound `t` as an `int` by `_value_kind`'s word
    # default, so `len(t)` said "an integer has no length" — a sentence about a
    # value that is a TYPE TAG.  Without this row the kind could go back to
    # INT_KIND for a local and only the bare-name spelling would notice.
    ("len_of_a_bound_type_is_refused",
     "def main(n: Int) -> Int:\n"
     "    t = bool\n"
     "    return len(t)\n",
     "refuse_without:len(t) is len() of a TYPE:"
     "an integer has no length", None),
    # A type as a SUBSCRIPT INDEX.  Before the kind existed this BUILT on both
    # architectures, ran, and exited 1 with nothing printed — the tag bounds-checked
    # against a three-element blob and took the out-of-range exit, which is the
    # bounds check doing its job on a number the source never wrote.  A build-time
    # refusal is the only answer here: a tag is not an element position.
    ("refuse_a_type_as_a_subscript_index",
     "def main(n: Int) -> Int:\n"
     "    var xs = [10, 20, 30]\n"
     "    printf(\"%d\", xs[bool])\n"
     "    return 0\n",
     "refuse:is a TYPE used as a subscript index", None),
    # …and through a LOCAL, because that is what makes it a kind rather than a
    # check of the operand's node: `t = bool; xs[t]` is the same program with one
    # more line in it, and a node-only recogniser would answer the first and refuse
    # the second.
    ("refuse_a_bound_type_as_a_subscript_index",
     "def main(n: Int) -> Int:\n"
     "    var xs = [10, 20, 30]\n"
     "    t = bool\n"
     "    printf(\"%d\", xs[t])\n"
     "    return 0\n",
     "refuse:is a TYPE used as a subscript index", None),
    # On a STRING, where the index is not bounds-checked at all — it is `s + i` on a
    # bare `char *`.  `s[bool]` SEGFAULTED on both architectures before the kind
    # existed (measured), so this is the case where the refusal is worth having at
    # all rather than a nicer message, and it is asked at the same choke point as
    # the blob case precisely so both are covered by one check.
    ("refuse_a_type_as_a_string_index",
     "def main(n: Int) -> Int:\n"
     "    var s = \"abc\"\n"
     "    printf(\"%d\", s[bool])\n"
     "    return 0\n",
     "refuse:is a TYPE used as a subscript index", None),
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


# The other direction, and it is here because a kind nothing reads as a NUMBER
# would be a refusal rather than an improvement: `print()` picks its conversion
# from the kind, and a tag is a word, so `print(t)` for `t = bool` must still
# print the tag.  That is what `model.is_number_kind` is for, and without it
# these two rows are refusals ("print() cannot tell whether IdentExpr is a
# string or a number") — a change that made the construct's own value
# unprintable.
#
# The expected answer is `type_tag("bool")`, read from the model rather than
# written down, so a change to the TAG FUNCTION cannot leave a literal behind
# that the image no longer produces: the rows would fail with a number mismatch
# instead of passing on "it built".
#
# The local spelling and the BARE spelling are separate rows because they take
# different paths — the local is bound by `_value_kind` from the same
# classification, and the bare one arrives at `print` with nothing bound at all,
# which is the row that was refused outright before `TYPE_KIND` existed.
TYPE_VALUE_NUMBER_CASES = [
    ("type_value_a_local_prints_as_a_number",
     "def main(n):\n"
     "    t = bool\n"
     "    print(t)\n"
     "    return 0\n",
     0, str(_TYPE_VALUE_MODEL.type_tag("bool"))),
    ("type_value_a_bare_type_prints_as_a_number",
     "def main(n):\n"
     "    print(bool)\n"
     "    return 0\n",
     0, str(_TYPE_VALUE_MODEL.type_tag("bool"))),
]


# ── the field census, asked of the model directly ────────────────────────────
#
# Everything above this point is a build and a run, which is the only kind of
# evidence that settles whether a program computes the right number — and the
# slowest kind. The census underneath it is a pure function of a parsed class
# body, so its four answers are asserted here, once, against the model, with no
# compiler in the loop: a `comptime` member is a class CONSTANT and not a field,
# it is not counted again when a method reaches it through the receiver, a name
# the unit WRITES through an object is a field again (so the write has a slot),
# and a struct with no evidence attached is left entirely alone.
#
# The last of those is the one that decides how far the fix reaches, so it is
# here rather than in a comment: a `comptime` member declared in an IMPORTED
# module needs the census that `formal/imports.py`'s `_attach_declared_census`
# attaches, and the two cross-module cases that exercise that are
# `byref_cross_module_comptime_attribute_through_a_receiver` and
# `…_through_a_parameter`.
_CENSUS_PROBES = [
    # (name, source, expected field names, expected constant names)
    ("a comptime member with no receiver read is a constant",
     "struct C:\n"
     "    comptime LIMIT = 10\n"
     "    var n: Int\n"
     "\n"
     "def get() -> Int:\n"
     "    return C.LIMIT\n",
     ["n"], ["LIMIT"]),
    ("a receiver read does not make it a field again",
     "struct C:\n"
     "    comptime LIMIT = 10\n"
     "    var n: Int\n"
     "\n"
     "    def scaled(self) -> Int:\n"
     "        return self.LIMIT + self.n\n",
     ["n"], ["LIMIT"]),
    ("a name the unit writes through an object is storage again",
     "struct C:\n"
     "    comptime LIMIT = 10\n"
     "    var n: Int\n"
     "\n"
     "def main():\n"
     "    c = C(0)\n"
     "    c.LIMIT = 7\n"
     "    return c.n\n",
     ["n", "LIMIT"], []),
    ("a unit with a write nobody can name demotes nothing",
     "struct C:\n"
     "    comptime LIMIT = 10\n"
     "    var n: Int\n"
     "\n"
     "def main(k):\n"
     "    c = C(0)\n"
     "    setattr(c, k, 1)\n"
     "    return c.n\n",
     ["n", "LIMIT"], []),
    ("without evidence every declared name stays a field",
     "struct C:\n"
     "    comptime LIMIT = 10\n"
     "    var n: Int\n",
     ["n"], []),
]


def check_comptime_alias_census(verbose=False):
    """The four census answers above, against `formal.model` and nothing else.

    Returns `(passed, failures)`. The evidence is attached for the first four
    rows and deliberately NOT for the last, which is the whole content of that
    row: `attach_field_evidence` is the pipeline's job and a caller that has not
    done it gets the pre-rule answer, counting every class-level name as a
    field. That is the conservative direction and it is the reason the same
    class can measure differently in the module that declares it and in one that
    imports it."""
    build = __import__("formal.build", fromlist=["build"])
    passed, failures = 0, []
    for name, source, want_fields, want_consts in _CENSUS_PROBES:
        attach = name != "without evidence every declared name stays a field"
        stmts = build.parse_module(source, "<census>")
        if not attach:
            # Undo the attachment `parse_module` just made, which is the state
            # an imported module's parse is in (`formal/imports.py` parses
            # imported sources directly rather than through `parse_module`).
            for st in _TYPE_VALUE_MODEL.iter_struct_defs(stmts):
                if hasattr(st, "_field_evidence"):
                    delattr(st, "_field_evidence")
        structs = list(_TYPE_VALUE_MODEL.iter_struct_defs(stmts))
        if len(structs) != 1:
            failures.append(f"{name}: parsed {len(structs)} structs, expected 1")
            continue
        st = structs[0]
        got_fields = _TYPE_VALUE_MODEL.struct_field_names(st)
        got_consts = [c for c, _v in _TYPE_VALUE_MODEL.struct_class_constants(st)]
        if got_fields != want_fields or got_consts != want_consts:
            failures.append(
                f"{name}: fields {got_fields} (want {want_fields}), "
                f"constants {got_consts} (want {want_consts})")
            continue
        passed += 1
        if verbose:
            print(f"  PASS  census: {name}")
    for detail in check_emitter_builtin_agreement():
        failures.append(detail)
    return passed - len([f for f in failures if f.startswith("emitter-builtins")]), \
        [f for f in failures if not f.startswith("emitter-builtins")]


# The names a backend compiles ITSELF, asked of `formal.model` and of nothing
# else — and asked because three places used to have to agree about them and
# did not have to.
#
# `bugs/FORMAL_callee_no_def_ceiling_zero.md` §5 measured the consequence: with
# the model's set and an emitter's own `if name == …` chain disagreeing, a name
# the emitter lowers is one the model does not know is a callee, so
# `print(p)` builds, runs, exits 0 and prints the frame's own ADDRESS as a
# decimal — 6102330608 on arm64, 13027830976 on x86-64, a different number on
# every run. `byref_refuse_print_of_a_frame` is the end-to-end half; this is the
# half that says the table and the dispatch cannot drift, because there is only
# one table.
#
# The emitter sources are READ rather than imported-and-called, because the fact
# under test is what each dispatch chain spells. A source that names a builtin
# the table does not have is a name the backend compiles and the model will not
# recognise; a table entry no emitter dispatches is the reverse, and is a dead
# entry that would make `emitter_lowers` answer yes for a name that reaches a
# symbol nothing defines.
def check_emitter_builtin_agreement():
    """Failures for `model.EMITTER_BUILTINS` disagreeing with the two emitters."""
    m = _TYPE_VALUE_MODEL
    import os
    failures = []
    here = os.path.dirname(os.path.abspath(__file__))
    for backend in ("arm64_codegen.py", "x86_64_codegen.py"):
        path = os.path.join(here, "formal", backend)
        with open(path) as f:
            src = f.read()
        # Each `if not is_extern_call and name == "<x>":` is a name the dispatch
        # spells itself; each is required to be in the table. `range` is in the
        # table and spelled, so the two checks below are the same direction and
        # the second is what says no table entry is dead.
        for spelled in re.findall(
                r'if not is_extern_call and name == "(\w+)":', src):
            if spelled not in m.EMITTER_BUILTINS:
                failures.append(
                    f"emitter-builtins: {backend} dispatches {spelled!r} and "
                    f"model.EMITTER_BUILTINS does not have it, so a frame "
                    f"address handed to it would be answered by the "
                    f"FRAME_VARIADIC path as an unbound name")
        dispatched = set(re.findall(
            r'if not is_extern_call and (?:name == "(\w+)"|'
            r'm\.emitter_lowers\(name\)):', src))
        if not dispatched:
            failures.append(
                f"emitter-builtins: {backend} has no builtin dispatch at all — "
                f"the chain this reads was renamed or removed")
        # `M.emitter_lowers(name)` gates the two `_emit_*` calls the table names,
        # and each named method must be one the file defines, or the table would
        # be routing a name to a method that is not there.
        for suffix in set(m.EMITTER_BUILTINS.values()):
            if suffix == "range_list":
                continue        # `range` is spelled, not dispatched
            if f"def _emit_{suffix}(" not in src:
                failures.append(
                    f"emitter-builtins: {backend} does not define "
                    f"_emit_{suffix}, which EMITTER_BUILTINS names")
    variadic = set(m.FRAME_VARIADIC_BUILTIN_CALLS)
    if not variadic <= set(m.EMITTER_BUILTINS):
        failures.append(
            f"emitter-builtins: FRAME_VARIADIC_BUILTIN_CALLS has "
            f"{sorted(variadic - set(m.EMITTER_BUILTINS))}, which no emitter "
            f"lowers, so a frame address handed to one is answered as an "
            f"unbound name instead of a wrong category")
    if "print" not in variadic:
        failures.append(
            "emitter-builtins: `print` left FRAME_VARIADIC_BUILTIN_CALLS, which "
            "is the refusal `byref_refuse_print_of_a_frame` measures")
    return failures


# WHICH PROLOGUES CARRY THE STACK-FLOOR GUARD, asked of
# `model.stack_floor_guarded_names` and nothing else — the decision the three
# `stack_floor_*` rows above can only observe indirectly, and the half of it they
# cannot see at all.
#
# They can see that a cycle is guarded (the trap fires) and that a shallow
# recursion is not disturbed. They CANNOT see that a straight-line function is
# left alone, because leaving it alone and guarding it differ only in bytes, and
# guarding a straight-line body would cost the per-export contract proof — see
# `stack_floor_guarded_names`'s docstring for why that is a cost and not a
# detail, and why adding the guard to a body that ALREADY has a branch is not.
# So the "not guarded" rows are asked directly, here, which is the level at which
# the answer is the honest one.
_STACK_FLOOR_PROBES = [
    # (name, source, want — the set of guarded function names)
    ("self_recursion", "def deep(n):\n    return deep(n - 1)\n"
     "def main(n):\n    return deep(n)\n", {"deep"}),
    # The shape a "does it call itself" rule gets wrong: neither function is
    # recursive alone.
    ("mutual_recursion", "def a(n):\n    return b(n - 1)\n"
     "def b(n):\n    return a(n - 1)\n"
     "def main(n):\n    return a(n)\n", {"a", "b"}),
    # A three-function cycle, and the two functions that merely CALL it: they
    # are on no cycle, so they are not guarded. The frames that accumulate
    # while `b` runs are `b`'s to notice.
    ("three_cycle_and_its_callers",
     "def c(n):\n    return a(n - 1)\n"
     "def b(n):\n    return c(n - 1)\n"
     "def a(n):\n    return b(n - 1)\n"
     "def caller(n):\n    return a(n)\n"
     "def main(n):\n    return caller(n)\n", {"a", "b", "c"}),
    # The shape that must NOT be guarded, twice: no self-call, and a call that
    # goes out of the image (an unknown name) cannot close a cycle here.
    ("acyclic_chain", "def leaf(n):\n    return n * 2\n"
     "def mid(n):\n    return leaf(n)\n"
     "def main(n):\n    return mid(n)\n", set()),
    ("out_of_image_call", "def f(n):\n    return g(n - 1)\n"
     "def main(n):\n    return f(n)\n", set()),
    # A call inside a comprehension and inside an `elif`: the walk has to reach
    # both, and `iter_nodes` is what reaches them — `iter_nodes`'s own docstring
    # records a walker that descended every `if` body and stopped at the first
    # `elif`, losing a third of the conditionals in a module.
    ("cycle_through_a_comprehension",
     "def f(n):\n    return [y for y in range(n)] and f(n - 1)\n"
     "def main(n):\n    return f(n)\n", {"f"}),
    ("cycle_through_an_elif",
     "def f(n):\n"
     "    if n > 0:\n        return 1\n"
     "    elif n < 0:\n        return f(n + 1)\n"
     "    return 0\n"
     "def main(n):\n    return f(n)\n", {"f"}),
    # A METHOD call is the symbol `Struct_method`, not `method`, so a rule that
    # read the member name would find no edge here and guard neither — and a
    # struct that ping-pongs through two of its own methods is an ordinary
    # recursive descent, not a shape invented for this test.
    ("cycle_through_two_methods",
     "struct R:\n"
     "    def ping(self) -> Int:\n        return self.pong()\n"
     "    def pong(self) -> Int:\n        return self.ping()\n"
     "def main(n):\n    var r = R()\n    return r.ping()\n",
     {"R_ping", "R_pong"}),
    # ── THE SECOND RULE: a body that ALREADY branches, with no cycle ──────
    #
    # The cycle rule alone left a DAG of distinct functions free to walk past
    # the floor, and the measured cost of that is in
    # `bugs/FORMAL_stack_floor_does_not_guard_an_acyclic_chain.md`: the deepest
    # single image in this corpus is 76 frames against the 60 an arm64 budget
    # affords. So a body that already contains a conditional branch is guarded
    # whether or not anything calls back into it.
    ("a_branching_body_is_guarded_off_the_cycle",
     "def leaf(n):\n    return n * 2\n"
     "def mid(n):\n"
     "    if n > 0:\n"
     "        return leaf(n)\n"
     "    return 0\n"
     "def main(n):\n    return mid(n)\n", {"mid"}),
    # A LOOP is a branch — `_emit_loop` always emits a compare and a branch, on
    # both backends — and a loop is the shape that actually recurses through a
    # call chain in this corpus's own lowering code.
    ("a_looping_body_is_guarded_off_the_cycle",
     "def total(n):\n"
     "    var c = 0\n"
     "    for i in range(n):\n"
     "        c = c + i\n"
     "    return c\n"
     "def main(n):\n    return total(n)\n", {"total"}),
    # A COMPREHENSION GUARD is a branch too, and it is the third site the truthy
    # conversion routes through, so it is the one a reader of `if s:` would
    # forget.
    ("a_comprehension_guard_is_a_branch",
     "def keep(n):\n    return [y for y in [1, 2, 3] if y]\n"
     "def main(n):\n    return len(keep(n))\n", {"keep"}),
    ("an_assert_is_a_branch",
     "def need(n):\n    assert n > 0\n    return n\n"
     "def main(n):\n    return need(n)\n", {"need"}),
    # ── THE THREE ROWS THAT PIN THE PREDICATE'S DIRECTION ────────────────
    #
    # The argument that widening costs nothing is that a body that already has
    # a branch had no per-export contract to lose. That argument inverts into a
    # requirement: the predicate must answer True ONLY for a body the emitter
    # lays out with a branch in it, or a straight-line export loses the contract
    # it has. These three are the shapes where a careless predicate over-counts,
    # and each is a REFUSAL of the widening rather than of the guard.
    #
    # A TERNARY: both backends have a branchless CSEL form behind a purity
    # predicate, so `1 if n else 2` can be straight-line in the image.
    ("a_ternary_is_not_a_branch",
     "def pick(n):\n    return 1 if n else 2\n"
     "def main(n):\n    return pick(n)\n", set()),
    # A SHORT-CIRCUIT chain, for the same reason and the same measurement: the
    # branchless form is gated on the left operand needing no conversion.
    ("a_short_circuit_is_not_a_branch",
     "def pick(n):\n    return n and 1\n"
     "def main(n):\n    return pick(n)\n", set()),
    # A NESTED `def`'s branch is in the NESTED function's prologue, so a
    # predicate that walked the whole tree — `iter_nodes` does, a nested def
    # being just another dataclass node — would guard the enclosing function and
    # cost it a contract it still has.
    #
    # Asked on `main` itself, and that is not a contrivance: `formal/build.py`'s
    # `_flatten_closures` LIFTS every nested def to top level (renamed
    # `ci.<name>`) before the function table exists, so the lifted child's
    # branch is a separate function's and `main`'s body is left with a call.
    # The pruning is what keeps that true when the table is built from an
    # unlifted tree, and `iter_nodes` would not keep it.
    ("a_nested_defs_branch_is_not_the_enclosing_functions",
     "def main(n):\n"
     "    def inner(m):\n"
     "        if m > 0:\n"
     "            return 1\n"
     "        return 0\n"
     "    return inner(n)\n", set()),
]

# THE THIRD RULE, asked directly: `every_function` is the image's shape, not a
# predicate over a body, so it cannot be answered by the probe table above — and
# the thing that has to hold is BOTH halves. True covers the image whose floor is
# otherwise set too deep; False is the module-dylib rule, unchanged, because
# there every function may be an export with a proved per-export contract.
_STACK_FLOOR_IMAGE_PROBES = [
    # The acyclic straight-line chain: the two-rule predicate guards NOTHING in
    # it, which is the residual, and `every_function` is what closes it.
    ("an_image_with_an_entry_guards_every_function",
     "def leaf(n):\n    return n * 2\n"
     "def mid(n):\n    return leaf(n)\n"
     "def main(n):\n    return mid(n)\n",
     True, {"leaf", "mid", "main"}),
    # The same source as a module dylib, where the answer must not move: the
    # per-export contract is what the two rules protect, and a straight-line
    # export still has one.
    ("a_module_dylib_keeps_the_two_rules",
     "def leaf(n):\n    return n * 2\n"
     "def mid(n):\n    return leaf(n)\n"
     "def main(n):\n    return mid(n)\n",
     False, set()),
    # …and a branching body in one is still guarded, because the cycle-or-branch
    # half is not conditional on the image's shape.
    ("a_module_dylib_still_guards_a_cycle",
     "def deep(n):\n    return deep(n - 1)\n"
     "def main(n):\n    return deep(n)\n",
     False, {"deep"}),
]


def check_stack_floor_decision(verbose=False):
    """`model.stack_floor_guarded_names` on the parsed probes, and
    `model.call_graph_depth` on the graphs that decide the widening's cost.

    Returns `(passed, failures)`; a probe's last element is the guarded set it
    must answer, read off the source rather than off an image."""
    build = __import__("formal.build", fromlist=["build"])
    from formal import model as M
    passed, failures = 0, []
    for probe in _STACK_FLOOR_PROBES:
        name, source, want = probe
        stmts = build.parse_module(source, "<stack-floor>")
        # The function list the EMITTER sees: `formal/build.py` lifts every
        # struct method into the function table as `Struct_method` before
        # codegen runs, and the guard reads that table — so a probe that passed
        # only the module's top-level `def`s would ask about a graph the emitter
        # never builds.
        structs = {st.name: st for st in stmts
                   if type(st).__name__ == "StructDef"}
        # `_struct_methods` (formal/build.py) lifts each method into a COPY
        # named by `model.method_function_name`, and it is that name a lifted
        # `self.ping()` call carries — so the probe applies the same rename
        # through the same function, rather than inventing the spelling. Without
        # it the graph has `ping` calling `ping` on one side and `R_ping` on the
        # other and finds no edge.
        import copy as _copy
        fns = [st for st in stmts if type(st).__name__ == "FunctionDef"]
        for st in structs.values():
            for mth in M.struct_methods(st):
                lifted = _copy.deepcopy(mth)
                lifted.name = M.method_function_name(st.name, mth.name)
                fns.append(lifted)
        got = M.stack_floor_guarded_names(fns, structs)
        if got != want:
            failures.append(f"{name}: {sorted(got)} (want {sorted(want)})")
            continue
        passed += 1
        if verbose:
            print(f"  PASS  stack-floor-decision: {name}")
    for name, source, every, want in _STACK_FLOOR_IMAGE_PROBES:
        stmts = build.parse_module(source, "<stack-floor-image>")
        structs = {st.name: st for st in stmts
                   if type(st).__name__ == "StructDef"}
        fns = [st for st in stmts if type(st).__name__ == "FunctionDef"]
        for st in structs.values():
            for mth in M.struct_methods(st):
                lifted = _copy.deepcopy(mth)
                lifted.name = M.method_function_name(st.name, mth.name)
                fns.append(lifted)
        got = M.stack_floor_guarded_names(fns, structs,
                                          every_function=every)
        if got != want:
            failures.append(f"image/{name}: {sorted(got)} (want {sorted(want)})")
            continue
        passed += 1
        if verbose:
            print(f"  PASS  stack-floor-decision: image/{name}")
    passed, failures = passed, list(failures)
    for name, edges, want in _STACK_FLOOR_DEPTH_PROBES:
        got = M.call_graph_depth(edges)
        if got != want:
            failures.append(f"depth/{name}: {got} (want {want})")
            continue
        passed += 1
        if verbose:
            print(f"  PASS  stack-floor-decision: depth/{name}")
    return passed, failures


# HOW DEEP A CHAIN GETS, asked of `model.call_graph_depth` — the half of the
# residual the guard cannot reach, and the number that decided
# `bugs/FORMAL_stack_floor_does_not_guard_an_acyclic_chain.md`'s widening.
#
# These are GRAPHS, not modules, because the question is about the function and
# not about the parse: a module the corpus already holds would make a test that
# goes red the moment an unrelated function is added, which is a test of the
# corpus rather than of the rule. The corpus figure is
# `tools/formal_call_depth_census.py`'s (deepest image 76 frames against the 60
# an arm64 budget affords; deepest branch-free chain 12), and it is a
# MEASUREMENT rather than an assertion — pinning it here would pin today's
# corpus.
_STACK_FLOOR_DEPTH_PROBES = [
    # A straight chain of n: the answer is n, and the point of the row is that
    # 76 of them is a real number the cycle rule cannot see.
    ("chain_of_one", {"f0": set()}, 1),
    ("chain_of_two", {"f0": {"f1"}, "f1": set()}, 2),
    ("chain_of_twenty", {f"f{i}": {f"f{i + 1}"} for i in range(19)}
     | {"f19": set()}, 20),
    # A chain LONGER than the budget, which is the whole reason the rule was
    # widened: 60 frames is what `STACK_FLOOR_BUDGET_BYTES` affords on arm64 and
    # this is three times it, with no cycle anywhere.
    ("chain_past_the_arm64_budget",
     {f"f{i}": {f"f{i + 1}"} for i in range(179)} | {"f179": set()}, 180),
    # A cycle and the tail behind it: the cycle's two members count ONCE each
    # (a simple path cannot visit one twice) and the two after it once each, so
    # the bound is 4 and not unbounded. This is the "the guard already covers
    # that half" row.
    ("cycle_then_a_tail", {"a": {"b"}, "b": {"a", "c"}, "c": {"d"},
                           "d": set()}, 4),
    # A diamond: two routes to one function, one frame live at a time. 3, and
    # not 4 — a walk that counted EDGES rather than the stack would.
    ("diamond", {"a": {"b", "c"}, "b": {"d"}, "c": {"d"}, "d": set()}, 3),
    # No edges at all: two exports side by side is a depth of 1, and the empty
    # graph is 0. Both are rows because a function that reports 1 for an empty
    # module has an off-by-one that reads as correct on everything else.
    ("two_functions_no_edge", {"a": set(), "b": set()}, 1),
    ("empty_graph", {}, 0),
]


# The four rules `model.struct_init_field_types` is, asked of `formal.model` and
# nothing else, and they are here as well as end to end: the evidence shape,
# `self.<f> = T()` for a `T` of this unit whose receiver is a frame, is now
# reachable (`assigned_type_nested_frame_constructed_in_init`), so this is no
# longer the ONLY level at which the rule is asked. It stays asked directly
# because directly is the honest level for it: the value of the inference is
# what it infers from a parsed class, not what an image does with the answer,
# and the direct probes cover the disagreeing and no-decls rows that a built
# program cannot express.
_ASSIGNED_TYPE_PROBES = [
    # The positive row: a nested frame the class body never declares.
    ("a nested frame is read off __init__'s construction of it",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    fn __init__(self):\n"
     "        self.in1 = Inner()\n",
     {"in1": ("Inner", "Inner")}),
    # UNANIMITY OR NOTHING, and the two ways it says no: one assignment that
    # classifies to nothing at all, and two that classify differently. Both leave
    # the field OUT of the map rather than answering with the one that worked,
    # because a type of a slot whose other store says otherwise is a wrong answer
    # that nothing downstream can see.
    ("one assignment that classifies to nothing leaves the field out",
     "struct Inner:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    fn __init__(self):\n"
     "        self.in1 = Inner()\n"
     "        self.n = make()\n",
     {"in1": ("Inner", "Inner")}),
    ("two assignments of different types leave the field out",
     "struct A2:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct B2:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    fn __init__(self, c: Int):\n"
     "        if c > 0:\n"
     "            self.in1 = A2()\n"
     "        else:\n"
     "            self.in1 = B2()\n",
     {}),
    # `decls` is the GATE and its absence is the safe direction: without it
    # `make()` cannot become "a type that is not a struct of this unit", which
    # would answer the frame question "provably not a frame" about a slot that
    # may well hold one.
    ("without decls a construction of an unknown name classifies to nothing",
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    fn __init__(self):\n"
     "        self.in1 = Inner()\n",
     {}, False),
    # A LITERAL row, and the narrowness the last probe names: `self.tag = 0`
    # classifies (as the language's own `int`), while `pad` — a field the
    # constructor never mentions at all — is ABSENT rather than defaulted to
    # something. The map is what `__init__` says, and the annotation and the
    # class-level default are two other functions' questions.
    ("a literal classifies and a field __init__ never mentions is absent",
     "struct Outer:\n"
     "    var tag: Int\n"
     "    var pad: Int\n"
     "    fn __init__(self):\n"
     "        self.tag = 0\n",
     {"tag": ("int", "int")}),
]


def check_assigned_type_evidence(verbose=False):
    """`model.struct_init_field_types` on five parsed classes.

    Returns `(passed, failures)`; a probe's last element is the `decls` to
    build it with, and only the fourth says no."""
    build = __import__("formal.build", fromlist=["build"])
    passed, failures = 0, []
    for probe in _ASSIGNED_TYPE_PROBES:
        name, source, want = probe[0], probe[1], probe[2]
        with_decls = probe[3] if len(probe) > 3 else True
        stmts = build.parse_module(source, "<assigned-type>")
        structs = {st.name: st
                   for st in _TYPE_VALUE_MODEL.iter_struct_defs(stmts)}
        target = structs.get("Outer")
        if target is None:
            failures.append(f"{name}: parsed no Outer")
            continue
        decls = structs if with_decls else None
        got = _TYPE_VALUE_MODEL.struct_init_field_types(target, decls)
        if got != want:
            failures.append(f"{name}: {got!r} (want {want!r})")
            continue
        passed += 1
        if verbose:
            print(f"  PASS  assigned-type: {name}")
    return passed, failures


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


# ── a `comptime` class member, diffed against CPython rather than pinned ─────
#
# The four `comptime_alias_*` cases in `CASES` above pin this construct to
# numbers. A number is an assertion about a lowering made by the same person who
# wrote the lowering, so these four re-ask the same questions with CPython as the
# oracle: each program is written twice, once as Mojo and once as the Python it
# is a superset of, and the two must print the same bytes on BOTH architectures.
# That is the only form in which "the value is the constant" is evidence rather
# than a restatement — the defect being pinned is a program that builds, runs,
# and returns a number nobody wrote, and a hand-written expectation of `13`
# would have been written by the same reasoning that produced the 0.
#
# The Python text cannot be derived from the Mojo text the way
# `test_formal_value_model.py` derives it, because `comptime LIMIT = 10` has no
# Python spelling: it is the class attribute `LIMIT = 10`. The two texts are
# therefore written out, and the case is the assertion that they mean the same
# thing.
COMPTIME_ALIAS_PAIR_CASES = [
    # Through the receiver, with real instance state beside it — the shape the
    # stdlib's own `std/python/numpy.mojo` has (`comptime assert shape.is_flat`)
    # and the one that read 0 before.
    ("comptime_alias_receiver_matches_cpython",
     "struct Coord:\n"
     "    comptime IS_FLAT = True\n"
     "    var rank: Int\n"
     "    var product: Int\n"
     "\n"
     "    def scaled(self) -> Int:\n"
     "        return self.product * 100 + self.rank * 10\n"
     "\n"
     "def is_flat(s) -> Int:\n"
     "    if s.IS_FLAT:\n"
     "        return 1\n"
     "    return 0\n"
     "\n"
     "def main():\n"
     "    var s = Coord(0, 0)\n"
     "    s.rank = 2\n"
     "    s.product = 7\n"
     "    printf(\"is_flat=%d scaled=%d\", is_flat(s), s.scaled())\n"
     "    return 0\n",
     "import sys\n"
     "class Coord:\n"
     "    IS_FLAT = True\n"
     "    def __init__(self, rank, product):\n"
     "        self.rank = rank\n"
     "        self.product = product\n"
     "    def scaled(self):\n"
     "        return self.product * 100 + self.rank * 10\n"
     "def is_flat(s):\n"
     "    if s.IS_FLAT:\n"
     "        return 1\n"
     "    return 0\n"
     "def main():\n"
     "    s = Coord(0, 0)\n"
     "    s.rank = 2\n"
     "    s.product = 7\n"
     "    sys.stdout.write(\"is_flat=%d scaled=%d\" % (is_flat(s), s.scaled()))\n"),
    # The same value read four ways in ONE program, so the four spellings cannot
    # be right by accident in a way the single-case rows would not catch: the
    # class name from inside a method, `Self` from inside a method, the receiver
    # from inside a method, and a base that is a frame argument. 40 + 20 + 13 +
    # 5 = 78, and 78 is not reachable from any subset of {0, 10} plus the field
    # reads, so a spelling that quietly read a neighbouring slot or an unwritten
    # one would not land on it.
    ("comptime_alias_every_spelling_agrees",
     "struct C:\n"
     "    comptime LIMIT = 5\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def by_receiver(self) -> Int:\n"
     "        return self.LIMIT\n"
     "\n"
     "    def by_class_name(self) -> Int:\n"
     "        return C.LIMIT\n"
     "\n"
     "    def by_Self(self) -> Int:\n"
     "        return Self.LIMIT\n"
     "\n"
     "    def state(self) -> Int:\n"
     "        return self.a * 10 + self.b\n"
     "\n"
     "def by_argument(c) -> Int:\n"
     "    return c.LIMIT\n"
     "\n"
     "def main():\n"
     "    var c = C(0, 0)\n"
     "    c.a = 4\n"
     "    c.b = 2\n"
     "    printf(\"%d %d %d %d %d\", c.by_receiver(), c.by_class_name(),\n"
     "           c.by_Self(), by_argument(c), c.state())\n"
     "    return 0\n",
     "import sys\n"
     "class C:\n"
     "    LIMIT = 5\n"
     "    def __init__(self, a, b):\n"
     "        self.a = a\n"
     "        self.b = b\n"
     "    def by_receiver(self):\n"
     "        return self.LIMIT\n"
     "    def by_class_name(self):\n"
     "        return C.LIMIT\n"
     "    def by_Self(self):\n"
     "        return C.LIMIT\n"
     "    def state(self):\n"
     "        return self.a * 10 + self.b\n"
     "def by_argument(c):\n"
     "    return c.LIMIT\n"
     "def main():\n"
     "    c = C(0, 0)\n"
     "    c.a = 4\n"
     "    c.b = 2\n"
     "    sys.stdout.write(\"%d %d %d %d %d\" % (c.by_receiver(),\n"
     "           c.by_class_name(), c.by_Self(), by_argument(c), c.state()))\n"),
    # A `comptime` member the program OVERWRITES. The oracle is CPython's own
    # rule — an instance attribute shadows the class one — and it is the case
    # that keeps the rewrite from being a wrong answer: substituting the
    # declared 5 here would be a number nobody wrote, and the substitution is
    # vetoed by the same write census that stops a plain class constant being
    # demoted.
    ("comptime_alias_overwritten_matches_cpython",
     "struct C:\n"
     "    comptime LIMIT = 5\n"
     "    var n: Int\n"
     "\n"
     "    def read(self) -> Int:\n"
     "        return self.LIMIT\n"
     "\n"
     "def main():\n"
     "    var c = C()\n"
     "    c.n = 3\n"
     "    c.LIMIT = 7\n"
     "    printf(\"%d %d\", c.read(), c.n)\n"
     "    return 0\n",
     "import sys\n"
     "class C:\n"
     "    LIMIT = 5\n"
     "    def __init__(self):\n"
     "        self.n = 0\n"
     "    def read(self):\n"
     "        return self.LIMIT\n"
     "def main():\n"
     "    c = C()\n"
     "    c.n = 3\n"
     "    c.LIMIT = 7\n"
     "    sys.stdout.write(\"%d %d\" % (c.read(), c.n))\n"),
    # A class of nothing but `comptime` members, read through the receiver, and
    # the class read through the CLASS name. This is the zero-instance-state
    # shape: the receiver has no slots of its own, so before the census learned
    # the alias the struct measured one field wide and the read returned the
    # receiver word. It is the case where the width itself is the bug, and where
    # `_one_word_field_map`'s "a method's `self` IS the field" rewrite would
    # otherwise have turned the read of a class value into a read of that word.
    ("comptime_alias_only_class_reads_through_both",
     "struct Regs:\n"
     "    comptime A = 3\n"
     "    comptime B = 4\n"
     "\n"
     "    def span(self) -> Int:\n"
     "        return self.B - self.A\n"
     "\n"
     "    def first(self) -> Int:\n"
     "        return Regs.A + 1\n"
     "\n"
     "def main():\n"
     "    var r = Regs()\n"
     "    printf(\"%d %d\", r.span(), r.first())\n"
     "    return 0\n",
     "import sys\n"
     "class Regs:\n"
     "    A = 3\n"
     "    B = 4\n"
     "    def span(self):\n"
     "        return self.B - self.A\n"
     "    def first(self):\n"
     "        return Regs.A + 1\n"
     "def main():\n"
     "    r = Regs()\n"
     "    sys.stdout.write(\"%d %d\" % (r.span(), r.first()))\n"),
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
                  + SUBSCRIPT_CASES + PRINTF_TEXT_CASES
                  + DECLARED_TYPE_CASES
                  + DECLARED_TYPE_REFUSALS
                  + ASSIGNED_TYPE_CASES + ASSIGNED_TYPE_REFUSALS \
                  + BOTH_ARCH_CASES \
                  + PRINT_KWARG_CASES \
                  + INIT_FIELD_TYPE_CASES \
                  + INIT_FIELD_TYPE_REFUSALS \
                  + ONE_WORD_NESTED_CASES \
                  + ONE_WORD_FIELD_METHOD_REFUSALS \
                  + CONDITIONAL_ARM_CASES \
                  + DECLARED_FRAME_RETURN_CASES
                  + OVERLOAD_LAYOUT_CASES + OVERLOAD_REFUSALS
                  + OVERLOAD_DISPATCH_REFUSALS
                  + BYREF_HANDOFF_CASES + BYREF_HANDOFF_REFUSALS
                  + CROSS_MODULE_CASES + WAVE5_POSITION_CASES
                  + CONSTRUCTION_CASES + CONSTRUCTION_REFUSALS
                  + REPEAT_REFUSALS
                  + SOLE_FIELD_CTOR_STORE_CASES
                  + SPREAD_CONSTRUCTION_CASES + SPREAD_REFUSALS
                  + POINTER_DEREF_CASES + POINTER_DEREF_REFUSALS
                  + WAVE6_TRUTHY_CASES
                  + WAVE6_NAME_CASES + WAVE7_G2_CASES
                  + SHIFT_CASES + REFUSAL_CASES + INT_PARSE_CASES
                  + INT_PARSE_REFUSALS
                  + TYPE_APPLICATION_REFUSALS + TYPE_VALUE_CASES \
                  + TYPE_VALUE_DTYPE_CASES + TYPE_VALUE_REFUSALS \
                  + TYPE_VALUE_TAG_CASES + ORIGIN_OF_CASES \
                  + TYPE_VALUE_NUMBER_CASES \
                  + ORIGIN_OF_REFUSALS
                  + EQ_DISPATCH_CASES + FRAME_ORDER_CASES
                  + TYPE_ARGUMENT_LIST_CASES
                  + TYPE_ARGUMENT_LIST_ABSENT_CASES
                  + MUTATING_RECEIVER_REFUSALS + SOLE_FIELD_CALLEE_REFUSALS
                  # STDERR_CASES is also a different shape (name, source, exit,
                  # needles) and is selected here so the `--cases` filter knows
                  # the name, then dispatched by `stderr_names` below. It is
                  # listed in `everything` rather than beside `pair_names`
                  # because it is still selected from `everything` and only its
                  # RUNNER differs.
                  + STDERR_CASES
                  + [X86_ONLY_1SLOT_BUG_CASE])
    # The CPython-pair group is a DIFFERENT SHAPE (three columns: name, Mojo
    # text, CPython text), so it is selected and dispatched separately rather
    # than forced into the four-column table every other group uses. Forcing it
    # in would mean a sentinel in the exit-status column and a branch that reads
    # a sentinel as if it were a status — which is how a case ends up asserting
    # nothing.
    set_union_names = {c[0] for c in SET_UNION_CASES}
    pair_names = ({c[0] for c in TYPE_APPLICATION_CASES}
                  | {c[0] for c in COMPTIME_ALIAS_PAIR_CASES}
                  | {c[0] for c in COMPTIME_ATTRIBUTE_CASES}
                  | {c[0] for c in SPREAD_CONSTRUCTION_CASES}
                  | {c[0] for c in OVERLOAD_LAYOUT_CASES}
                  | {c[0] for c in ONE_FIELD_MUTATOR_CASES}
                  | {c[0] for c in SOLE_FIELD_CALLEE_CASES}
                  | {c[0] for c in SLICE_CASES}
                  | {c[0] for c in SLICE_BOUND_CASES}
                  | {c[0] for c in CONCAT_CASES}
                  | {c[0] for c in REPEAT_CASES}
                  | {c[0] for c in SET_UNION_CASES}
                  | {c[0] for c in CTOR_RECEIVER_CASES}
                  | {c[0] for c in CALL_RECEIVER_CASES})
    wanted_pairs = ([c for c in TYPE_APPLICATION_CASES
                     + COMPTIME_ALIAS_PAIR_CASES
                     + SPREAD_CONSTRUCTION_CASES
                     + OVERLOAD_LAYOUT_CASES
                     + COMPTIME_ATTRIBUTE_CASES
                     + ONE_FIELD_MUTATOR_CASES
                     + SOLE_FIELD_CALLEE_CASES
                     + SLICE_CASES + SLICE_BOUND_CASES + CONCAT_CASES
                     + REPEAT_CASES + SET_UNION_CASES
                     + CTOR_RECEIVER_CASES + CALL_RECEIVER_CASES
                     if not args.cases or c[0] in args.cases])
    # `BOTH_ARCH_CASES` is the four-column shape, so it rides `selected` and the
    # ordinary `run_case` dispatch; what makes it different is the RUNNER, and
    # that is a set of names rather than a table of its own.
    # A `refuse:` row is EXCLUDED from the both-architecture runner even
    # when it lives in a group that is otherwise run on both: `run_case`
    # already builds both backends for that shape and requires them to
    # refuse with the same words, and `run_both_arch_case` requires the
    # build to SUCCEED — so routing a refusal row through it would assert
    # the opposite of what the row says. `PRINT_KWARG_CASES` is the group
    # that made that worth stating: three of its five rows are refusals and
    # two are answered.
    both_arch_names = ({c[0] for c in BOTH_ARCH_CASES}
                      | {c[0] for c in PRINT_KWARG_CASES}
                      | {c[0] for c in POINTER_DEREF_CASES
                         if c[0].startswith("deref_struct_pointee")}) - {
        c[0] for c in PRINT_KWARG_CASES
        if isinstance(c[2], str) and c[2].startswith('refuse:')}
    selected = [c for c in everything
                if c[0] not in pair_names
                and (not args.cases or c[0] in args.cases)]
    known = {c[0] for c in everything} | pair_names
    if args.cases and len(selected) + len(wanted_pairs) != len(args.cases):
        missing = set(args.cases) - known
        print(f"ERROR: unknown case(s): {sorted(missing)}", file=sys.stderr)
        return 2
    off_names = {c[0] for c in WIDE_OFF_CASES}
    module_names = {c[0] for c in CROSS_MODULE_CASES}
    stderr_names = {c[0] for c in STDERR_CASES}

    passed = failed = 0
    # Before the builds, because it is the only group here that needs no
    # compiler: a census regression should say so in a second rather than after
    # a minute of images.
    census_passed, census_failures = check_comptime_alias_census(args.verbose)
    for detail in census_failures:
        print(f"  FAIL  census: {detail}")
    print(f"formal run: census PASS={census_passed} "
          f"FAIL={len(census_failures)}")
    passed += census_passed
    failed += len(census_failures)
    at_passed, at_failures = check_assigned_type_evidence(args.verbose)
    for detail in at_failures:
        print(f"  FAIL  assigned-type: {detail}")
    print(f"formal run: assigned-type PASS={at_passed} "
          f"FAIL={len(at_failures)}")
    passed += at_passed
    failed += len(at_failures)
    sf_passed, sf_failures = check_stack_floor_decision(args.verbose)
    for detail in sf_failures:
        print(f"  FAIL  stack-floor-decision: {detail}")
    print(f"formal run: stack-floor-decision PASS={sf_passed} "
          f"FAIL={len(sf_failures)}")
    passed += sf_passed
    failed += len(sf_failures)
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, source, cpython_source in wanted_pairs:
            src = os.path.join(tmpdir, name + ".mojo")
            with open(src, "w") as f:
                f.write(source)
            try:
                if name in set_union_names:
                    ok, detail = run_set_union_case(
                        name, source, cpython_source, tmpdir, args.verbose)
                else:
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
                print(f"  PASS  {name} ("
                      + ("arm64 == CPython, x86-64 refused by name"
                         if name in set_union_names
                         else "== CPython, both architectures") + ")")
            else:
                failed += 1
                print(f"  FAIL  {name}: {detail}")
        for name, source, want_exit, want_stdout in selected:
            try:
                if name in off_names:
                    ok, detail = run_wide_off_case(
                        name, source, want_exit[len("refuse:"):], tmpdir,
                        args.verbose)
                elif name in stderr_names:
                    ok, detail = run_stderr_case(
                        name, source, want_exit, want_stdout, tmpdir,
                        args.verbose)
                elif name in module_names:
                    ok, detail = run_module_case(
                        name, source, want_exit, want_stdout, tmpdir,
                        args.verbose)
                elif name in both_arch_names:
                    ok, detail = run_both_arch_case(
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
