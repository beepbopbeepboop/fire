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
    ("struct_ctor_args_both_backends",
     "class Resolver:\n"
     "    def resolve(self, name):\n"
     "        return len(name)\n\n"
     "def main(n):\n"
     "    r = Resolver(n, n, n)\n"
     "    return r.resolve(\"a\")\n",
     "refuse:takes no arguments on this path", None),
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
    # spells those entry points in the source. A formal image links libSystem
    # and nothing else, so each of these used to emit a BL against a symbol
    # nothing defines: the build reported success and the program died in the
    # loader. A `refuse:` case, so the assertion is that BOTH architectures
    # say no with the same words.
    ("gimple_runtime_sqlite_refused",
     "def main():\n"
     "    var db = mojo_sqlite3_open(\":memory:\")\n"
     "    mojo_sqlite3_close(db)\n"
     "    return 0\n",
     "refuse:is an entry point of the gimple backend's C runtime", None),
    # `mojo_print` rather than `print`, for the file that spells the runtime's
    # own name. Same namespace, same answer.
    ("gimple_runtime_print_refused",
     "def main():\n"
     "    mojo_print(\"hi\")\n"
     "    return 0\n",
     "refuse:is an entry point of the gimple backend's C runtime", None),
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
    ("str_method_unknown_receiver",
     "def main(n):\n"
     "    h = n\n"
     "    return h.value()\n",
     "refuse:is a method call on a value", None),
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
    ("byref_one_name_two_widths_agree",
     "struct A:\n"
     "    var v: Int\n"
     "    var w: Int\n\n"
     "struct B:\n"
     "    var v: Int\n"
     "    var w: Int\n"
     "    var z: Int\n\n"
     "def touchB(b) -> Int:\n"
     "    b.z = 1\n"
     "    return 0\n\n"
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
     "refuse:this module does not compile", None),
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
    ("byref_refuse_receiver_to_a_builtin",
     "struct P:\n"
     "    var a: Int\n"
     "    var b: Int\n\n"
     "    fn n(self) -> Int:\n"
     "        return len(self)\n\n"
     "def main(n: Int) -> Int:\n"
     "    var p = P()\n"
     "    return p.n()\n",
     "refuse:lowered as an operation on a VALUE", None),
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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="subset of case names")
    args = ap.parse_args()

    if platform.machine() not in ("arm64", "aarch64"):
        print(f"SKIP: formal output is arm64-only, host is {platform.machine()}")
        return 0

    everything = (CASES + BYREF_CASES + BYREF_REFUSALS + WIDE_OFF_CASES
                  + SUBSCRIPT_CASES)
    selected = [c for c in everything if not args.cases or c[0] in args.cases]
    known = {c[0] for c in everything}
    if args.cases and len(selected) != len(args.cases):
        missing = set(args.cases) - known
        print(f"ERROR: unknown case(s): {sorted(missing)}", file=sys.stderr)
        return 2
    off_names = {c[0] for c in WIDE_OFF_CASES}

    passed = failed = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for name, source, want_exit, want_stdout in selected:
            try:
                if name in off_names:
                    ok, detail = run_wide_off_case(
                        name, source, want_exit[len("refuse:"):], tmpdir,
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
