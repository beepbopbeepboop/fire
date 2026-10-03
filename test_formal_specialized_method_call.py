#!/usr/bin/env python3
"""`recv.m[T](args)` — a comptime-specialized METHOD call.

The sweep families "receiver passed at argument position 0" (25 files) and
"value with no representation on this path" (15 files) both name programs this
file is about, and both were refused with a sentence that was **entirely
false**.  Measured, before anything here was written:

    struct Pair:
        var a: Int
        var b: Int
        def combine[T: Int](self, k: Int) -> Int:
            return self.a * 1000 + self.b * 10 + k + T
    def main(n: Int) -> Int:
        var p = Pair(); p.a = 4; p.b = 5
        return p.combine[6](7)

    build: p.combine names 'combine', which is a METHOD of Pair rather than one
           of its fields: a value-position method reference is a bound method,
           and a method is not a word — there is no slot to read it out of and
           nothing to store it in …

Every clause about the CATEGORY is wrong.  `p.combine[6](7)` is a **call**: the
brackets are a generic's comptime parameters, bound at compile time, exactly as
`f[T](x)` is a call and not a subscript.  It arrived at the frame analysis as a
field read because `_rewrite_method_calls` recognised `recv.m(x)` — a callee
that is a `MemberExpr` — and not `recv.m[T](x)`, whose callee is a
`SubscriptExpr` over that same `MemberExpr`.  So the walk descended into the
bracket, found `p.combine` in value position, and asked for a slot.  That is
the defect class `test_refusal_taxonomy.py` holds this path to — "a refusal
whose stated reason is entirely false" — and this is one more example in it.

Six of the eight files the sweep reported this way are this shape, not a
bound-method value.  Measured by reading the refused expression in each:
`val.to_bits[uint_type]()` and `new_data.to_bits[.uint64]()`
(`std/memory/_poison.mojo`, `std/hashlib/_ahash.mojo`),
`resized_from.test_range[False, lo=Self.size]()`
(`std/collections/bitset.mojo`), `handle._get_ctx[_AsyncContext]()`
(`std/runtime/_asyncrt.mojo`), `self.lib.call["Py_Initialize"]()`
(`std/python/_cpython.mojo`), `a.get[i]()` (`std/utils/index.mojo`).  The other
two — `checker.check_temporal_monotonicity` in `run_type_system_tests.py` and
`job.excl` in `tools/suite.py` — ARE value-position method references, and they
are still refused, which is the correct verdict for them.

WHAT LANDED, and why it is a REWRITE rather than a new lowering
----------------------------------------------------------------
`formal/build.py`'s `_rewrite_method_calls` now lifts both spellings through
one recogniser, `_method_call_target`, and keeps the brackets on the callee when
there are any:

    recv.m(a)      ->  Struct_m(recv, a)
    recv.m[T](a)   ->  Struct_m[T](recv, a)

Keeping them is the whole of what a specialization is on this path, and it is
not a new decision: `formal/model.py`'s `incoming_args` puts a generic's
comptime parameters FIRST, and arm64's `_emit_call` passes the bracket
expressions first (`_specialization_args`).  So both spellings deliver the same
words to the same parameters, and the emitter needs no change at all — the same
argument `test_formal_frame_len.py` records for `len(h)`, and the
same reason this is one function rather than two.

Measured on the program above, before the change it refused; after, it builds on
arm64 and returns **223** = 4000 + 50 + 7 + 6, which is CPython's answer for the
same program with the specialization written out.  `specialized_method_call_binds
_comptime_then_runtime_arguments` below is the case that pins the ORDER, because
a specialization lift that transposed the receiver and the comptime arguments
would produce a plausible wrong number rather than a failure.

WHY BOTH ARCHITECTURES ARE RUN, and what the refusal used to be pinning
---------------------------------------------------------------------
`f[T](x)` built on arm64 and was REFUSED on x86-64 with "unsupported call target
on the formal x86-64 path (got SubscriptExpr)", because x86-64's caller did not
pass the comptime arguments while its callee prologue reserved a register for
them (`incoming_args` is shared).  That refusal was LOAD-BEARING, and it was
worth pinning for the reason this file now pins the PARITY instead: a backend
that knows the callee's NAME without the ABI builds an image that links and
computes something else, and only running both machines tells the two apart.
The ABI took THREE halves to port, not one — the call site, `_callee_symbol`,
and the callee prologue's allocation order — and `x86_abi_specialized_method_call_
on_both` is what keeps the three together.  Reverting only the prologue half
makes the case fail on a WRONG NUMBER rather than on a refusal, which is exactly
the failure a refusal-shaped expectation cannot see.

Every differential case is written twice, once as Mojo and once as plain Python,
and the two are made to AGREE rather than the expectation being hand-written —
`test_formal_frame_len.py`'s discipline, for the same reason: a hand-written
expected value is a second implementation of the question.  `printf` carries the
answer because a process exit status is a byte on this host and several of these
answers are larger than 255.

    python3 test_formal_specialized_method_call.py [-v] [case ...]
"""
import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, "fire.py")
BUILD_TIMEOUT = 180
RUN_TIMEOUT = 60
BACKENDS = ("arm64", "x86_64")
# Every case below is BUILT and RUN on BOTH architectures and its stdout must
# equal CPython's.  That was not true while x86-64 refused the comptime
# specialization, and the one-sided assertion is what let that survive:
# nothing here was looking at that machine's answers.

# ── the differential cases ──────────────────────────────────────────────────
#
# (name, mojo_source, python_source)
DIFF_CASES = [
    # THE TERMINAL CONSTRUCT, in miniature: `p.combine[6](7)`.  This is the
    # shape `std/memory/_poison.mojo` and `std/hashlib/_ahash.mojo` are refused
    # on (`val.to_bits[uint_type]()`, `new_data.to_bits[.uint64]()`), and it is
    # the one the false message was about.
    #
    # `Pair` is a TWO-FIELD struct, so its receiver is a FRAME ADDRESS rather
    # than a word (`formal/model.py`'s `struct_is_framed`).  That is deliberate:
    # the receiver hand-off is the reason this construct is in the
    # receiver-position family at all, and a one-field struct would pass this
    # case while proving nothing about the hand-off.
    ("specialized_method_call_on_a_frame_receiver",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def combine[T: Int](self, k: Int) -> Int:\n"
     "        return self.a * 1000 + self.b * 10 + k + T\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = Pair()\n"
     "    p.a = 4\n"
     "    p.b = 5\n"
     '    printf("v=%d", p.combine[6](7))\n'
     "    return 0\n",
     "class Pair:\n"
     "    def __init__(self):\n"
     "        self.a = 4\n"
     "        self.b = 5\n\n"
     "    def combine(self, k):\n"
     "        return self.a * 1000 + self.b * 10 + k + 6\n"
     "\n"
     "def main():\n"
     "    p = Pair()\n"
     '    print("v=%d" % p.combine(7), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # **THE ORDER**, which is the assertion the case above cannot make.  Every
    # parameter of `mark` is read and given a distinct decimal weight, so a
    # lift that put the receiver before the comptime arguments, or bound `T` to
    # the receiver, produces a DIFFERENT NUMBER rather than a crash: 20306
    # against 23406.  A wrong-order lift is the failure mode this backend
    # exists to make impossible, and it is silent.
    #
    # `x` is the first RUNTIME parameter after `self`, so the three weights
    # between them say which of the four bindings is misplaced: T=2, x=3,
    # self.a=4, y=6.
    ("specialized_method_call_binds_comptime_then_runtime_arguments",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def mark[T: Int](self, x: Int, y: Int) -> Int:\n"
     "        return T * 10000 + x * 100 + self.a * 10 + y\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = Pair()\n"
     "    p.a = 4\n"
     "    p.b = 5\n"
     '    printf("v=%d", p.mark[2](3, 6))\n'
     "    return 0\n",
     "class Pair:\n"
     "    def __init__(self):\n"
     "        self.a = 4\n"
     "        self.b = 5\n\n"
     "    def mark(self, x, y):\n"
     "        return 2 * 10000 + x * 100 + self.a * 10 + y\n"
     "\n"
     "def main():\n"
     "    p = Pair()\n"
     '    print("v=%d" % p.mark(3, 6), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # TWO SPECIALIZED CALLS OF THE SAME METHOD, which is the shape
    # `std/collections/bitset.mojo` has (`test_range[False, …]` and
    # `test_range[True, …]`) and the one a fix that cached a lifted callee
    # would get wrong.  Two different comptime bindings, one receiver.
    ("two_specializations_of_one_method",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def scaled[T: Int](self) -> Int:\n"
     "        return T * 100 + self.a * 10 + self.b\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = Pair()\n"
     "    p.a = 4\n"
     "    p.b = 5\n"
     "    var q = Pair()\n"
     "    q.a = 6\n"
     "    q.b = 7\n"
     '    printf("v=%d", p.scaled[1]() * 1000 + q.scaled[2]())\n'
     "    return 0\n",
     "class Pair:\n"
     "    def __init__(self, a, b):\n"
     "        self.a = a\n"
     "        self.b = b\n\n"
     "    def scaled(self, t):\n"
     "        return t * 100 + self.a * 10 + self.b\n"
     "\n"
     "def main():\n"
     "    p = Pair(4, 5)\n"
     "    q = Pair(6, 7)\n"
     '    print("v=%d" % (p.scaled(1) * 1000 + q.scaled(2)), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # A SPECIALIZED METHOD CALLED THROUGH A PLAIN FUNCTION, so the specialized
    # callee is not reached from `main` — the compiler has to compile it and
    # bind it like any other, and this is the shape
    # `std/runtime/_asyncrt.mojo` has (`handle._get_ctx[_AsyncContext]()` called
    # from a helper).
    ("specialized_method_call_from_inside_a_function",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def bump[T: Int](self) -> Int:\n"
     "        return T * 1000 + self.a * 10 + self.b\n"
     "\n"
     "def go(q: Pair) -> Int:\n"
     "    return q.bump[3]()\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var q = Pair()\n"
     "    q.a = 4\n"
     "    q.b = 5\n"
     '    printf("v=%d", go(q))\n'
     "    return 0\n",
     "class Pair:\n"
     "    def __init__(self):\n"
     "        self.a = 4\n"
     "        self.b = 5\n\n"
     "    def bump(self, t):\n"
     "        return t * 1000 + self.a * 10 + self.b\n"
     "\n"
     "def go(q):\n"
     "    return q.bump(3)\n"
     "\n"
     "def main():\n"
     "    q = Pair()\n"
     '    print("v=%d" % go(q), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # THE ADVICE `ambiguous_method_specialization_refusal` gives, built and
    # run.  A diagnostic that sends the reader into a SECOND refusal has moved
    # the cost rather than removed it, and the obvious-looking advice for an
    # ambiguous method name — qualifying the call as `Box.run[...]` — DOES NOT
    # work: a specialization of a DOTTED callee has no receiver to prepend, so
    # `_rewrite_method_calls` cannot lift it and it is refused again by
    # `frame_opaque_position_refusal`'s `callee_shape` arm.  Measured, which is
    # why the message offers the rename and the written-out call instead.
    #
    # So this case is the written-out call, next to the refusal case below that
    # recommends it: a change that reworded the advice into the dotted form
    # would pass every other case here and send a reader into a second refusal.
    # **It passes before this change as well as after** — the written-out
    # spelling was always lifted, which is exactly why it is the advice — so it
    # is a guard on the MESSAGE rather than a demonstration of the lift, and it
    # is not labelled GUARD because what it pins is the advice's text.
    ("the_advice_the_ambiguity_refusal_gives_works",
     "struct Box:\n"
     "    var k: Int\n"
     "    var j: Int\n"
     "    def run[T: Int](self, x: Int) -> Int:\n"
     "        return T * 100 + x + self.k\n"
     "\n"
     "struct Other:\n"
     "    var m: Int\n"
     "    var n: Int\n"
     "    def run[T: Int](self, x: Int) -> Int:\n"
     "        return x + self.m\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Box()\n"
     "    b.k = 1\n"
     "    b.j = 2\n"
     '    printf("v=%d", Box_run[3](b, 4))\n'
     "    return 0\n",
     "class Box:\n"
     "    def __init__(self):\n"
     "        self.k = 1\n"
     "        self.j = 2\n\n"
     "    def run(self, t, x):\n"
     "        return t * 100 + x + self.k\n"
     "\n"
     "class Other:\n"
     "    def __init__(self):\n"
     "        self.m = 0\n"
     "        self.n = 0\n\n"
     "    def run(self, t, x):\n"
     "        return x + self.m\n"
     "\n"
     "def main():\n"
     "    b = Box()\n"
     '    print("v=%d" % b.run(3, 4), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # **GUARD** — the same program with a BARE-NAME callee, `p.combine(7)`,
    # which has always been lifted and must stay lifted.  Labelled a guard
    # because it is correct before this change as well as after, and it is here
    # so that a change which taught the specialization by rewriting `recv.m[T]`
    # into some NEW spelling could not pass every case above while breaking the
    # ordinary one.
    ("GUARD_unspecialized_method_call_is_unchanged",
     "struct Pair:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "    def combine[T: Int](self, k: Int) -> Int:\n"
     "        return self.a * 1000 + self.b * 10 + k + T\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var p = Pair()\n"
     "    p.a = 4\n"
     "    p.b = 5\n"
     '    printf("v=%d", Pair_combine[6](p, 7))\n'
     "    return 0\n",
     "class Pair:\n"
     "    def __init__(self):\n"
     "        self.a = 4\n"
     "        self.b = 5\n\n"
     "    def combine(self, k):\n"
     "        return self.a * 1000 + self.b * 10 + k + 6\n"
     "\n"
     "def main():\n"
     "    p = Pair()\n"
     '    print("v=%d" % p.combine(7), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # **GUARD** — a specialization of a FREE function with no receiver
    # anywhere, which `test_formal_receiver_position.py`'s comptime-ABI group
    # landed.  It
    # is here so that "the comptime ABI is unchanged" is a measurement rather
    # than an assumption: the answer is 307, and a lift that shifted call-time
    # positions by the number of comptime parameters would make it 723.
    ("GUARD_specialized_free_function_is_unchanged",
     "def widen[type: Int](x: Int, y: Int) -> Int:\n"
     "    return x * 100 + y\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     '    printf("v=%d", widen[1](3, 7))\n'
     "    return 0\n",
     "def widen(type, x, y):\n"
     "    return x * 100 + y\n"
     "\n"
     "def main():\n"
     '    print("v=%d" % widen(1, 3, 7), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # **THE KEYWORD HALF OF THE BRACKET**, `c.show[scale=2](3)`.  This was a
    # SILENT WRONG ANSWER, and the two cases below are the fix's whole
    # assertion: the parser keeps a bracket's keyword items in
    # `SubscriptExpr.attrs` and its positional items in `.index`, and
    # `comptime_eval.specialization_args` read only `.index` — so `scale` bound
    # to 0, the same word an unsupplied parameter gets, and the image printed
    # **403** where CPython prints **423**.  It exited 0 and computed a number
    # the source never wrote, which is why it survived as long as it did.
    #
    # `[*, scale: Int]` is the stdlib's own spelling for a defaulted comptime
    # parameter (`std/collections/optional.mojo`'s `_write_to[*, is_repr:
    # Bool]`, `std/collections/list.mojo`'s `_write_self_to[*, is_repr: Bool]`),
    # so this case is the shape two real files are written in.
    #
    # The weights say which binding is wrong: `value` 400, `scale` 20, `n` 3.
    # A binder that ignored `attrs` gives 403; one that bound by the wrong name
    # or the wrong position gives a third number.  It cannot fail loudly.
    ("keyword_comptime_parameter_is_bound_by_name",
     "struct Cell:\n"
     "    var value: Int\n"
     "    var pad: Int\n"
     "    def show[*, scale: Int](self, n: Int) -> Int:\n"
     "        return self.value * 100 + scale * 10 + n\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = Cell()\n"
     "    c.value = 4\n"
     "    c.pad = 1\n"
     '    printf("v=%d", c.show[scale=2](3))\n'
     "    return 0\n",
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self.value = 4\n"
     "        self.pad = 1\n\n"
     "    def show(self, scale, n):\n"
     "        return self.value * 100 + scale * 10 + n\n"
     "\n"
     "def main():\n"
     "    c = Cell()\n"
     '    print("v=%d" % c.show(2, 3), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # **TWO KEYWORD PARAMETERS, SUPPLIED IN THE OPPOSITE ORDER** —
    # `c.mix[by=7, T=3]()`.  This is what makes the first case's fix a NAME
    # binding rather than "the second item of the bracket": a binder that took
    # the keyword items positionally would give `T=7, by=3` and answer **1073**
    # instead of **1037**, and one that ignored `attrs` gives 1000.  Neither is
    # a crash, which is why the split has to be pinned and not assumed.
    #
    # Written keyword-FIRST deliberately.  `c.mix[3, by=7]()` — the more natural
    # reading order — goes through the parser's OTHER bracket arm, which keeps
    # the keyword's VALUE in `.index` and discards its name, so it happens to
    # bind correctly by position and cannot tell the two rules apart.  That
    # parser asymmetry is recorded, not relied on.
    ("keyword_comptime_parameters_bind_by_name_not_by_bracket_order",
     "struct Cell:\n"
     "    var v: Int\n"
     "    var w: Int\n"
     "    def mix[T: Int, *, by: Int](self) -> Int:\n"
     "        return self.v * 1000 + T * 10 + by\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = Cell()\n"
     "    c.v = 1\n"
     "    c.w = 2\n"
     '    printf("v=%d", c.mix[by=7, T=3]())\n'
     "    return 0\n",
     "class Cell:\n"
     "    def __init__(self):\n"
     "        self.v = 1\n"
     "        self.w = 2\n\n"
     "    def mix(self, T, by):\n"
     "        return self.v * 1000 + T * 10 + by\n"
     "\n"
     "def main():\n"
     "    c = Cell()\n"
     '    print("v=%d" % c.mix(3, 7), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # **GUARD** — the same keyword spelling on a FREE function, with no
    # receiver anywhere, so the answer does not depend on the method lift at
    # all.  `mojo/middle/comptime.py` is shared by three compiled paths (the
    # gimple compiled path, arm64, x86-64), which is why the fix lives in the
    # ONE reader rather than in a backend; this is the case that says the
    # reader is the one that changed.  The answer is 110, and a reader that
    # dropped the keyword gives 7 — the `type` weight is there because a body
    # that never READS the parameter cannot tell a dropped binding from any
    # other, which is how the defect stayed invisible for so long.
    ("GUARD_keyword_comptime_parameter_on_a_free_function",
     "def widen[*, type: Int](x: Int, y: Int) -> Int:\n"
     "    return type * 100 + x + y\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     '    printf("v=%d", widen[type=1](3, 7))\n'
     "    return 0\n",
     "def widen(type, x, y):\n"
     "    return type * 100 + x + y\n"
     "\n"
     "def main():\n"
     '    print("v=%d" % widen(1, 3, 7), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),
    # ── a receiver that is a FIELD: `recv.f.m(a)`, dispatched by `f`'s
    #    declared type rather than by the spelling of `m` ──────────────────
    #
    # THE SAME RECOGNITION, one hop further from the name.  `_method_call_target`
    # requires the callee's receiver to be a plain `IdentExpr`, so
    # `self._inner.write_to(writer)` was not recognised as a method call at all;
    # `_rewrite_self_fields` then collapsed `self._inner` to `self` (correctly —
    # `StridedSlice` has ONE field, so its receiver IS that field) and left
    # `self.write_to(writer)`, a name TWO structs of this file declare and
    # therefore a name nothing could lift.  What the refusal then said was false:
    #
    #     StridedSlice_emit_all: self.write_to is not a field of StridedSlice —
    #     write_to is one of its METHODS …
    #
    # The source says neither.  It says `Slice.write_to`, on `self._inner`, which
    # is declared `var _inner: Slice`.  Measured on
    # `std/builtin/builtin_slice.mojo`\'s own `StridedSlice_write_to` — the file the
    # 2026-10-02 x86-64 sweep of `std/builtin` + `std/collections` reported one
    # level down for 7 of the 38 files it reached — with `write_to` spelled the
    # same in both structs, exactly as it is there.
    #
    # `StridedSlice.write_to` returns 99 and is never called, so the only way to
    # print 99 is a mis-dispatch: the case fails on the NUMBER, which a
    # refusal-shaped expectation could not see.
    ("field_receiver_method_call_dispatches_on_the_declared_type",
     "struct Slice:\n"
     "    var start: Int\n"
     "    var end: Int\n"
     "    var step: Int\n"
     "\n"
     "    def write_to(self, mut writer: Int) -> Int:\n"
     '        printf("%d/%d/%d|", self.start, self.end, self.step)\n'
     "        return 0\n"
     "\n"
     "struct StridedSlice:\n"
     "    var _inner: Slice\n"
     "\n"
     "    def write_to(self, mut writer: Int) -> Int:\n"
     "        return 99\n"
     "\n"
     "    def emit_all(self, mut writer: Int) -> Int:\n"
     "        return self._inner.write_to(writer)\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var s = StridedSlice(Slice(1, 2, 3))\n"
     '    printf("rc=%d", s.emit_all(0))\n'
     "    return 0\n",
     "class Slice:\n"
     "    def __init__(self, start, end, step):\n"
     "        self.start = start\n"
     "        self.end = end\n"
     "        self.step = step\n"
     "\n"
     "    def write_to(self, writer):\n"
     '        print("%d/%d/%d|" % (self.start, self.end, self.step), end="")\n'
     "        return 0\n"
     "\n"
     "class StridedSlice:\n"
     "    def __init__(self, inner):\n"
     "        self._inner = inner\n"
     "\n"
     "    def write_to(self, writer):\n"
     "        return 99\n"
     "\n"
     "    def emit_all(self, writer):\n"
     "        return self._inner.write_to(writer)\n"
     "\n"
     "def main():\n"
     "    s = StridedSlice(Slice(1, 2, 3))\n"
     '    print("rc=%d" % s.emit_all(0), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # The SAME shape with the two methods spelled DIFFERENTLY, which is the
    # control for the row above and says the fix is the dispatch rather than the
    # collision: before it, this one got PAST the recogniser\'s reach and died in
    # the emitter instead ("self.emit_slice() is a method call on a value … the
    # receiver is a name on this path"), so both spellings were refused and only
    # the WORDING differed.  It must now compute the same thing, and the one-word
    # struct alias must not have quietly turned `Slice.emit_slice` into
    # `StridedSlice.emit_slice` — whose body would recurse.
    ("field_receiver_method_call_with_distinct_names_agrees",
     "struct Slice:\n"
     "    var start: Int\n"
     "    var end: Int\n"
     "    var step: Int\n"
     "\n"
     "    def emit_slice(self, mut writer: Int) -> Int:\n"
     "        return self.start * 100 + self.end * 10 + self.step\n"
     "\n"
     "struct StridedSlice:\n"
     "    var _inner: Slice\n"
     "\n"
     "    def emit_all(self, mut writer: Int) -> Int:\n"
     "        return self._inner.emit_slice(writer) * 2\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var s = StridedSlice(Slice(1, 2, 3))\n"
     '    printf("v=%d", s.emit_all(0))\n'
     "    return 0\n",
     "class Slice:\n"
     "    def __init__(self, start, end, step):\n"
     "        self.start = start\n"
     "        self.end = end\n"
     "        self.step = step\n"
     "\n"
     "    def emit_slice(self, writer):\n"
     "        return self.start * 100 + self.end * 10 + self.step\n"
     "\n"
     "class StridedSlice:\n"
     "    def __init__(self, inner):\n"
     "        self._inner = inner\n"
     "\n"
     "    def emit_all(self, writer):\n"
     "        return self._inner.emit_slice(writer) * 2\n"
     "\n"
     "def main():\n"
     "    s = StridedSlice(Slice(1, 2, 3))\n"
     '    print("v=%d" % s.emit_all(0), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),

    # ── a FREE FUNCTION whose name is also a METHOD\'s ───────────────────────
    #
    # Method dispatch here is by NAME and nothing more, so `helper` being both a
    # module-level function and a method of `Widget` is perfectly legal source,
    # and `_method_owners` records the collision as data rather than as an error.
    # That is the design.  What is not the design is the SECOND table reading the
    # same collision and concluding that the free function IS a method: the frame
    # pass asked its `{function name: struct}` table by the free function\'s own
    # name, was handed the struct NAME it had just recorded, and passed a string
    # on as if it were a struct.  `_frame_receivers` raised `AttributeError:
    # 'str' object has no attribute 'name'` on any module where a
    # FRAME-HOLDING free function shares its name with any method — this
    # module\'s own or an imported struct\'s.
    #
    # Measured on `std/builtin/reversed.mojo`, which the 2026-10-02 x86-64 sweep
    # classified `backend-crash` (`SIMD.reversed` is real — `std/simd.mojo:3475`
    # — and the module declares a free `reversed`), so the file could not be
    # classified at all rather than being refused for whatever its next problem
    # was.  A crash is also the one class the sweep never replays from cache, so
    # it is the most expensive verdict the tool can print.
    #
    # The case is EXECUTED, because the same substitution that crashed also fed a
    # phantom struct to the `comptime` census: without the fix this function\'s
    # class-level reads were answered as `Widget`\'s.  `Big` is in the image so
    # that `helper` HOLDS A FRAME, which is the condition `_frame_receivers`\'s
    # rewrite loop is gated on — a frame-free free function never reached the
    # crash and would have made this case pass for the wrong reason.
    ("free_function_sharing_a_method_name_is_not_a_method",
     "struct Widget:\n"
     "    var n: Int\n"
     "\n"
     "    def helper(self) -> Int:\n"
     "        return self.n + 1\n"
     "\n"
     "struct Big:\n"
     "    var a: Int\n"
     "    var b: Int\n"
     "\n"
     "    def get(self, k: Int) -> Int:\n"
     "        return self.a * 10 + self.b\n"
     "\n"
     "def helper(x: Int) -> Int:\n"
     "    var b = Big()\n"
     "    b.a = x\n"
     "    b.b = 2\n"
     "    return b.get(0) + 7\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var w = Widget()\n"
     "    w.n = n\n"
     '    printf("v=%d", helper(n) + w.helper())\n'
     "    return 0\n",
     "class Widget:\n"
     "    def __init__(self):\n"
     "        self.n = 0\n"
     "\n"
     "    def helper(self):\n"
     "        return self.n + 1\n"
     "\n"
     "class Big:\n"
     "    def __init__(self):\n"
     "        self.a = 0\n"
     "        self.b = 0\n"
     "\n"
     "    def get(self, k):\n"
     "        return self.a * 10 + self.b\n"
     "\n"
     "def helper(x):\n"
     "    b = Big()\n"
     "    b.a = x\n"
     "    b.b = 2\n"
     "    return b.get(0) + 7\n"
     "\n"
     "def main():\n"
     "    w = Widget()\n"
     "    w.n = 10\n"
     '    print("v=%d" % (helper(10) + w.helper()), end="")\n'
     "    return 0\n"
     "\n"
     "main()\n"),
]

# ── the refusals, which are the point of the two remaining families ─────────
#
# (name, mojo_source, needle)
#
# Every case here refuses for a reason that is TRUE of it, which is the property
# the false message above lost.  All of them fire in the shared build pass or in
# `formal/model.py`, so each is required to refuse identically on BOTH backends.
REFUSALS = [
    # THE GUARD on the field-receiver dispatch, and the only observable thing
    # about it: `FancySlice` DERIVES from `Slice` and declares the same method,
    # so a field declared `Slice` may hold either, and the declared type names
    # only the base.  Lifting to `Slice_emit_slice` would then run the BASE's
    # body against a CHILD's frame — which builds, and computes the base's view
    # of a value the source says is a child.  Measured: with
    # `formal/build.py`'s `_receiver_field_types` guard removed, this program
    # BUILDS on arm64.  With it, it refuses.
    #
    # The refusal is the pre-existing one and that is deliberate: withholding
    # the entry puts the call back on the name-based path, where `emit_slice` is
    # a name two structs declare and so has no owner to lift to.  The needle is
    # therefore the EXISTING diagnosis rather than a new message, which is the
    # honest outcome — this is a limit, and the fix's job was to stop it firing
    # on programs it is not about.
    ("refuse_a_field_receiver_whose_declared_type_has_a_derived_override",
     "struct Slice:\n"
     "    var start: Int\n"
     "\n"
     "    def emit_slice(self, mut writer: Int) -> Int:\n"
     "        return self.start\n"
     "\n"
     "struct FancySlice(Slice):\n"
     "    var tag: Int\n"
     "\n"
     "    def emit_slice(self, mut writer: Int) -> Int:\n"
     "        return 1000\n"
     "\n"
     "struct Box:\n"
     "    var _inner: Slice\n"
     "\n"
     "    def go(self, mut writer: Int) -> Int:\n"
     "        return self._inner.emit_slice(writer)\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    return 0\n",
     "self.emit_slice() is a method call on a value"),

    # A GENUINE VALUE-POSITION METHOD REFERENCE — `checker.check_temporal_...`
    # passed as an ARGUMENT, not called.  This is the two remaining files of the
    # sweep's eight, and it is the case the false message was written for and is
    # right about.  `a bound method is not a word` is the whole truth here: there
    # is no slot to read it out of and nothing to store it in.
    #
    # It is a refusal in this file rather than a demonstration on purpose — a
    # bound-method VALUE is a real gap on this path, and asserting that it
    # refuses for the right reason is what stops a future change from lifting it
    # by accident and producing a word that is not a method.
    ("refuse_a_value_position_method_reference",
     "struct Checker:\n"
     "    var n: Int\n"
     "    var seen: Int\n"
     "    def check(self, k: Int) -> Int:\n"
     "        return self.n + k\n"
     "\n"
     "def take(fn: Int, k: Int) -> Int:\n"
     "    return fn + k\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var c = Checker()\n"
     "    c.n = 3\n"
     "    c.seen = 4\n"
     "    return take(c.check, 7)\n",
     "a value-position method reference is a bound method"),

    # AN AMBIGUOUS METHOD NAME, which is the third of the eight and the reason
    # `std/runtime/_asyncrt.mojo` and `std/utils/index.mojo` are still refused
    # after this change.  Two structs in this image declare `run`, and dispatch
    # on this path is BY NAME because the receiver's type is not inferred — so
    # the lift has no single owner, and the refusal has to say that rather than
    # pick one.
    #
    # The needle is the CALL clause, and it is a distinct assertion from the
    # case above rather than a shorter version of it: before this change this
    # program was refused with the bound-method sentence, which told the reader
    # to add parentheses to a program that already had them.  The needle is
    # also what distinguishes it from a genuine value-position reference, so a
    # change that made the lift refuse for a DIFFERENT but equally untrue reason
    # would still pass.
    ("refuse_an_ambiguous_specialized_method_call_by_name",
     "struct Box:\n"
     "    var k: Int\n"
     "    var j: Int\n"
     "    def run[T: Int](self, x: Int) -> Int:\n"
     "        return x + self.k\n"
     "\n"
     "struct Other:\n"
     "    var m: Int\n"
     "    var n: Int\n"
     "    def run[T: Int](self, x: Int) -> Int:\n"
     "        return x + self.m\n"
     "\n"
     "def main(n: Int) -> Int:\n"
     "    var b = Box()\n"
     "    b.k = 1\n"
     "    b.j = 2\n"
     "    return b.run[3](4)\n",
     "is a method CALL"),
]

# ── the x86-64 half, which was a refusal and is now a lowering ─────────────
#
# This used to be `X86_ABI_REFUSALS`: the same program, required to BUILD on
# arm64 and to be REFUSED on x86-64.  Both backends share the comptime ABI now,
# so it is a differential case instead, and the interesting part is that its
# answer exercises all FOUR argument positions: receiver, comptime parameter,
# then the runtime arguments.  4063 = 4000 + 50 + 7 + 6 is the only number that
# says the receiver came first and `T` second; a lift that passed the receiver
# after the bracket expression would give 463 and a lift that dropped `T`
# entirely would give 4057, and both would exit 0.
DIFF_CASES.append((
    "x86_abi_specialized_method_call_on_both",
    "struct Pair:\n"
    "    var a: Int\n"
    "    var b: Int\n"
    "    def combine[T: Int](self, k: Int) -> Int:\n"
    "        return self.a * 1000 + self.b * 10 + k + T\n"
    "\n"
    "def main(n: Int) -> Int:\n"
    "    var p = Pair()\n"
    "    p.a = 4\n"
    "    p.b = 5\n"
    '    printf("v=%d", p.combine[6](7))\n'
    "    return 0\n",
    "class Pair:\n"
    "    def __init__(self, a, b):\n"
    "        self.a = a\n"
    "        self.b = b\n"
    "    def combine(self, T, k):\n"
    "        return self.a * 1000 + self.b * 10 + k + T\n"
    "\n"
    "def main():\n"
    "    p = Pair(4, 5)\n"
    '    print("v=%d" % p.combine(6, 7), end="")\n'
    "    return 0\n\n"
    "main()\n",
))


def build_formal(src, out, backend):
    cmd = [sys.executable, FIRE, "build", "--formal", "--no-prove",
           f"--backend={backend}", "-o", out, src]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=BUILD_TIMEOUT, cwd=HERE)
    return p.returncode, (p.stderr or p.stdout or "")


def run_cpython(source, tmpdir):
    """The oracle: the same program under CPython, whose stdout the formal
    image has to match.

    Not `mojo run` and not this repository's own interpreter: a differential
    case is worth something because the two answers come from two independent
    implementations of the language, and `myinterpreter.py` shares the AST, so a
    mistake in the AST cannot be caught by comparing against it.
    """
    path = os.path.join(tmpdir, "oracle.py")
    with open(path, "w") as f:
        f.write(source)
    return subprocess.run([sys.executable, path], capture_output=True, text=True,
                          timeout=RUN_TIMEOUT)


def run_diff_case(case, tmpdir, verbose):
    """CPython's answer first, then the image's, and require the two to agree.

    The order is the order of trust: a case whose Python twin does not produce
    the answer the case is about is a bug in the CASE, and running the oracle
    first is what makes that report say so.

    BOTH architectures, since the two now share the comptime ABI (see this
    file's docstring).  It was `COMPTIME_ABI` alone while x86-64 refused the
    construct, and a one-sided assertion is exactly what let the x86-64 caller
    pass only the runtime arguments for as long as it did: the image built, ran,
    and returned a number no source wrote, and no case here was looking at that
    machine.
    """
    name, source, oracle = case
    want = run_cpython(oracle, tmpdir)
    if want.returncode != 0:
        return False, (f"the CPython oracle itself failed (exit "
                       f"{want.returncode}): "
                       f"{(want.stderr or '').strip()[-200:]}")
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in BACKENDS:
        out = os.path.join(tmpdir, f"{name}.{backend}")
        rc, text = build_formal(src, out, backend)
        if rc != 0:
            return False, (f"--backend={backend} did not build: "
                           f"{text.strip()[-300:]}")
        if not os.path.isfile(out):
            return False, f"--backend={backend} built but wrote no binary"
        run = subprocess.run([out], capture_output=True, text=True,
                             timeout=RUN_TIMEOUT)
        if run.returncode != want.returncode:
            return False, (f"--backend={backend} exit status {run.returncode}, "
                           f"CPython {want.returncode}")
        if run.stdout != want.stdout:
            return False, (f"--backend={backend} stdout {run.stdout!r}, CPython "
                           f"{want.stdout!r}")
        if verbose:
            print(f"      --backend={backend} stdout={run.stdout!r}")
    return True, ""


def run_refusal_case(case, tmpdir, verbose):
    """BOTH backends must refuse, and both must refuse with the needle.

    Both architectures, because a refusal raised by the shared build pass has to
    be the same refusal on both: a construct one machine stops and the other
    lowers is the divergence this backend's design exists to make impossible.
    """
    name, source, needle = case
    src = os.path.join(tmpdir, name + ".mojo")
    with open(src, "w") as f:
        f.write(source)
    for backend in BACKENDS:
        rc, text = build_formal(src, os.path.join(tmpdir, f"{name}.{backend}"),
                                backend)
        if rc == 0:
            return False, (f"--backend={backend} BUILT a construct that has no "
                           f"representation (expected a refusal naming "
                           f"{needle!r}); the binary is the real answer here")
        if needle not in text:
            return False, (f"--backend={backend} refused, but not with the "
                           f"expected words {needle!r}: {text.strip()[-300:]}")
        if verbose:
            print(f"      --backend={backend} refused naming {needle!r}")
    return True, ""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cases", nargs="*", help="case name substring filter")
    args = ap.parse_args(argv)

    def wanted(name):
        return not args.cases or any(c in name for c in args.cases)

    runners = (("differential", DIFF_CASES, run_diff_case),
               ("refusal", REFUSALS, run_refusal_case))
    passed = failed = 0
    failures = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for label, cases, runner in runners:
            for case in cases:
                name = case[0]
                if not wanted(name):
                    continue
                try:
                    ok, why = runner(case, tmpdir, args.verbose)
                except subprocess.TimeoutExpired as exc:
                    ok, why = False, f"timed out: {exc}"
                if ok:
                    passed += 1
                    print(f"  PASS  {name}")
                else:
                    failed += 1
                    failures.append(f"  FAIL  {name}: {why}")
                    print(f"  FAIL  {name}: {why}")
    print(f"\nspecialized method call: PASS={passed} FAIL={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
