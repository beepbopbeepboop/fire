#!/usr/bin/env python3
"""`_tree`'s `call rel32` arm: a call is a JUMP, and the return is a STACK.

`formal/x86_64_endtoend_test.py`'s path-tree builder had no `call_rel32` arm,
so a call fell through to the linear case and became a `seq` node whose one
successor was `addr + 5` -- the instruction AFTER the call. That is a wrong
model of the instruction rather than a missing one: the model's own successor
says `rip := (Int.ofNat m + 5 + off).toNat`, so the instruction at `m + 5` is
not executed at all after a call, and the step's `rip` side condition (`s.rip =
<m + 5>`) is false. `simp` turned that into `False`, the side-condition guard
admitted it, and eight examples' proofs carried a `sorry` from the instruction
after the call onwards -- with `failing` at 0. The arm is in the driver now
(`build()`'s `if form == "call_rel32"`).

**This is a UNIT test, and that is the point.** The behaviour it pins is a
function over a list of decoded instructions, so it can be asked directly with a
five-instruction body, in milliseconds, with no image and no Lean -- where the
thing it guards (`formal/x86_64_endtoend_test.py`'s own entry point) is 43 Lean
proofs and is one of the eight Lean-checking suites a light worker is not
expected to run. A pin nobody can run is not a pin.

So the rows below build a synthetic function by hand and ask `_tree` two
questions:

  * does the call node's successor name the instruction at `m + 5 + off` (the
    TARGET) rather than `m + 5` (the fall-through)? — the doc's defect;
  * does the tree come back through the RETURN, i.e. does the callee's `ret`
    continue at `m + 5` and run the caller's own instructions to its `ret`? —
    the other half of the same fact, and the one the round trip the library
    already proves (`x86_call_ret_round_trip`) is about.

and one that must NOT build a tree: a BACKWARD call, which is a back edge and
reports `None` rather than recursing in Python until the interpreter's limit.

    python3 test_formal_x86_64_call_tree.py [-v]

The second class is the OTHER thing a `call` can be: one whose target is not in
the image at all. Every program carries one in its prologue — the stack-floor
guard's `exit(2)` — and `_tree` declined the whole body when it reached one, so
every example reported `body loops, or branches out of the function`. It is a
LEAF now, with the call's own address as its halt address, and
`TestACallThatLeavesTheImageIsALeaf` pins that plus the leaf ORDER
(`_leaf_halts`), which is what the emitted theorem's disjuncts are written in.
"""
import os
import struct
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "formal"))

import formal.x86_64_endtoend_test as ET  # noqa: E402

BASE = 0x1000


class _Insn:
    """What `_tree` reads off a decoded instruction: `offset` and `length`.

    `formal/x86_64_decode.py`'s `Insn` is a dataclass with thirteen more fields
    and a decoder in front of it; `_tree` uses these two, so the stub is the
    honest shape for a hand-written body and nothing more."""

    def __init__(self, offset, length):
        self.offset = offset
        self.length = length

    def __repr__(self):
        return f"@{self.offset}+{self.length}"


def _call_rel32(at, target):
    """`E8 disp32` at `at`, branching to `target`."""
    return bytes([0xE8]) + struct.pack("<i", target - (at + 5))


def _cqo():
    """`48 99` -- two bytes, and a form the model steps; only its length is read."""
    return bytes([0x48, 0x99])


def _ret():
    return bytes([0xC3])


def _jne_rel32(at, target):
    """`0F 85 disp32` at `at`, branching to `target` when ZF is clear."""
    return bytes([0x0F, 0x85]) + struct.pack("<i", target - (at + 6))


def _body(pieces):
    """`(shapes, code)` for a body given as `(offset, bytes)`, plus its bytes.

    The offsets are the caller's, so a caller that wants an instruction at 16
    says 16 and the gap in front of it is padding: `_tree` indexes by ADDRESS,
    so a hole in the byte array is a stretch of code no instruction claims, and
    nothing walks into one."""
    shapes, code = [], bytearray()
    at = 0
    for offset, raw in pieces:
        assert offset >= at, (offset, at)
        code += bytes(offset - at)
        shapes.append((_Insn(offset, len(raw)), *_form_of(raw)))
        code += raw
        at = offset + len(raw)
    return shapes, bytes(code)


def _form_of(raw):
    """`(form, raw_bytes)` -- only the forms this test writes."""
    if raw[0] == 0xE8:
        return "call_rel32", raw
    if raw[0] == 0xC3:
        return "ret", raw
    if raw[0] == 0x0F and len(raw) == 6:
        return "jcc_rel32", raw
    if raw == _cqo():
        return "cqo", raw
    raise AssertionError(f"this test does not write {raw.hex()}")


def _tree_of(pieces, entry_offset=0):
    shapes, code = _body(pieces)
    # `func_offset` is an ABSOLUTE address -- `formal/build.py`'s `info` carries
    # `base_addr` and `func_offset` as two absolute values, and `_tree` keys
    # `by_addr` by `base + i.offset` while starting the walk at `func_offset`.
    return ET._tree(code, {"base_addr": BASE, "func_offset": BASE + entry_offset},
                    shapes)


# The body every forward-call row uses, laid out so that the return address is
# an instruction of its own:
#
#   0   call +16        -> the callee at 16
#   5   cqo             <- what the callee's `ret` pops: 0 + 5
#   7   ret             <- the caller's own end of run
#  16   cqo             <- the callee's body
#  18   ret             <- the callee's end, which RETURNS rather than ending
FORWARD = [(0, _call_rel32(0, 16)), (5, _cqo()), (7, _ret()),
           (16, _cqo()), (18, _ret())]


class TestCallIsAJumpNotAFallThrough(unittest.TestCase):
    def test_the_call_nodes_successor_is_the_target_not_the_next_instruction(self):
        t = _tree_of(FORWARD)
        self.assertIsNotNone(t, "no tree at all for a straight-line call")
        self.assertEqual(t.form, "call_rel32")
        self.assertEqual(t.succ, BASE + 16,
                         "the call node's successor is the fall-through "
                         f"{BASE + 5}, which is the instruction after the call: "
                         "a `call` does not execute it, and the model's own "
                         "successor says `rip := m + 5 + off`")

    def test_the_tree_comes_back_through_the_return_address(self):
        """The other half, and the one a `seq` node got wrong as well.

        The callee's `ret` pops `m + 5` and the run CONTINUES there, so the
        path is callee-body, callee-ret, `m + 5`, caller-ret -- four steps after
        the call, not two. A builder that stopped at the callee's `ret` would
        emit a theorem about a run that never returned."""
        t = _tree_of(FORWARD)
        self.assertIsNotNone(t)
        paths = list(ET._paths(t))
        self.assertEqual(len(paths), 1,
                         f"expected one path, got {[[n.addr for n in p] for p in paths]}")
        walked = [n.addr - BASE for n in paths[0]]
        self.assertEqual(walked, [0, 16, 18, 5, 7],
                         f"the run walked {walked}; a call is a jump to 16 and "
                         f"a return to 5, so the path is 0, 16, 18, 5, 7")

    def test_the_callees_ret_is_not_the_end_of_the_run(self):
        """The callee's `ret` must have a kid; the caller's must not.

        `_tree` grew a `rets` LIFO for this, and the failure it replaces is a
        theorem that is FALSE rather than one that could not be proved: with
        every `ret` treated as the end, the closing fact claimed `rip = 0` while
        the model says `rip` is the popped return address."""
        t = _tree_of(FORWARD)
        self.assertIsNotNone(t)
        path = next(ET._paths(t))
        callee_ret = [n for n in path if n.form == "ret"][0]
        self.assertEqual(callee_ret.addr - BASE, 18,
                         "the first `ret` on the path is the CALLEE's")
        self.assertEqual(len(callee_ret.kids), 1,
                         "the callee's `ret` ends the run; it returns into the "
                         "caller, and the run continues at the return address")
        self.assertEqual(callee_ret.kids[0].addr - BASE, 5,
                         "the run continues at the address the CALL pushed, "
                         "`m + 5`")
        self.assertEqual(path[-1].form, "ret")
        self.assertEqual(path[-1].kids, [],
                         "the CALLER's `ret` is the end of the run (nothing is "
                         "left on the return-address stack) and has no kid")

    def test_a_backward_call_is_a_back_edge_and_builds_no_tree(self):
        """`count`/`fact`/`fib` call themselves, and that is a loop.

        Left to a fresh `seen` per callee they would recurse in PYTHON until the
        interpreter's limit reached the same answer by a much worse route.

        The instructions AFTER the call are here so that this row is about the
        call and not about the walk falling off the end of the body: with a
        `ret` reachable from the fall-through, a `call` treated as a fall-through
        would build a tree, and `assertIsNone` would be passing for the wrong
        reason.
        """
        shapes, code = _body([(0, _cqo()), (2, _call_rel32(2, 0)),
                              (7, _cqo()), (9, _ret())])
        t = ET._tree(code, {"base_addr": BASE, "func_offset": BASE}, shapes)
        self.assertIsNone(t,
                          "a call whose target is at or below itself is a back "
                          "edge, and a back edge has no finite unfolding here -- "
                          "but the fall-through path from 7 to the `ret` at 9 "
                          "does, so a tree here means the call was walked as a "
                          "fall-through")


class TestACallThatLeavesTheImageIsALeaf(unittest.TestCase):
    """The stack-floor guard's trap arm, which is a call to the C library.

    `_emit_stack_floor_guard` puts `mov rdi, 2; mov rax, 0; call exit` at the end
    of the guard in EVERY prologue of every program image, so "a `call` whose
    target is not in the image" is not a rarity in this backend — it is the
    first thing every program does. `_tree` used to decline the whole body when it
    reached one (`body loops, or branches out of the function`, which names two
    reasons when the real one is a third), and every example in
    `formal/examples/` reported that.

    The fix is the arm64 generator's own answer to the same question: the halt
    address is the CALL's address, so the claim becomes "the run reaches the
    call". `x86_exec_go_exit` tests `st.rip = exit` before it steps, and the
    model cannot decode an address outside the image (`rc` is 0 there and
    `x86_step_plain` has no arm for 0x00), so stepping the call would leave a
    path that the runner reports as `none` — which is NOT the exit sentinel the
    theorem names.
    """

    #:  0  jne -> 10     a fork, so the leaf ORDER is pinned as well as the leaf
    #:  6  cqo
    #:  8  ret           the fall-through arm's end of run
    #: 10  call -> 0x9000   outside the image: the trap
    OUTSIDE = 0x9000
    TRAP = [(0, _jne_rel32(0, 10)), (6, _cqo()), (8, _ret()),
            (10, _call_rel32(10, OUTSIDE))]

    def _trap_tree(self):
        shapes, code = _body(self.TRAP)
        return code, ET._tree(code, {"base_addr": BASE, "func_offset": BASE},
                              shapes)

    def test_a_call_out_of_the_image_builds_a_tree_rather_than_refusing(self):
        code, t = self._trap_tree()
        self.assertIsNotNone(t,
                             "a call whose target is outside the image must not "
                             "decline the body: every program carries one in its "
                             "prologue (the stack-floor guard's exit(2))")

    def test_the_leaf_is_the_call_and_its_halt_is_the_calls_own_address(self):
        _code, t = self._trap_tree()
        node = t.kids[0]
        self.assertEqual(node.form, "call_rel32",
                         "the fork's taken arm IS the call: `kids[0]` is the "
                         "branch target and the call is the leaf")
        self.assertEqual(node.kind, "leaves",
                         "a leaf that leaves the image is its own kind, not a "
                         "`ret`: the run does not RETURN anywhere, it stops at "
                         "an address the model has no instruction for")
        self.assertEqual(node.succ, BASE + 10,
                         "the halt address is the CALL's own address %d, not "
                         "its target 0x%x: the runner stops at `st.rip = exit` "
                         "BEFORE it steps, so the claim is 'the run reaches the "
                         "call'" % (BASE + 10, self.OUTSIDE))
        self.assertEqual(node.kids, [], "a leaf has nothing after it")

    def test_two_arms_halt_at_different_addresses_in_walk_order(self):
        _code, t = self._trap_tree()
        halts = ET._leaf_halts(t)
        self.assertEqual(halts, [BASE + 10, None],
                         "the trap arm halts at the call and the fall-through "
                         "arm at the exit sentinel (None), TAKEN FIRST because "
                         "it is kids[0] — and `emit_terminates` writes the "
                         "statement's disjuncts in this order and picks between "
                         f"them by index. Got {halts}")
        # The index is on the node, so the statement and the walk cannot read
        # two different leaves as the same one.
        trap = t.kids[0]
        exit_leaf = t.kids[1].kids[0]
        self.assertEqual(trap.halt, 0)
        self.assertEqual(exit_leaf.halt, 1)
        self.assertIsNone(exit_leaf.succ,
                          "the outermost `ret` pops the zero `X86State.init` "
                          "leaves on the stack, so its halt address is the exit "
                          "sentinel and None is how the statement spells it")
        self.assertEqual(trap.form, "call_rel32")

    def test_a_body_that_never_leaves_the_image_still_halts_at_the_sentinel(self):
        """The other direction: the arm above must not have cost the old case."""
        t = _tree_of(FORWARD)
        self.assertEqual(ET._leaf_halts(t), [None],
                         "a body whose every path ends at the outermost `ret` "
                         "has one leaf and it halts at the exit sentinel")

    def test_a_body_whose_paths_all_leave_the_image_has_no_exit_disjunct(self):
        """`subscript_var` is the shape: every path ends at a `call` out.

        The statement then has no disjunct any arm can reach at 0, and that is
        correct rather than a gap — the theorem says the run halts at one of the
        calls, which is all the model supports. Pinned because it is the case a
        later "every image must have an exit arm" tidy-up would break."""
        shapes, code = _body([(0, _call_rel32(0, self.OUTSIDE))])
        t = ET._tree(code, {"base_addr": BASE, "func_offset": BASE}, shapes)
        self.assertIsNotNone(t)
        self.assertEqual(ET._leaf_halts(t), [BASE + 0])
        self.assertEqual(t.halt, 0)


class TestTheReporterNamesTheForm(unittest.TestCase):
    """`no tree: …` truncated to 38 characters is 14 characters of FORM.

    The message for an unmodelled form is `no step lemma wired for: <forms>`,
    so the truncation ate the second and third form names — and the form is the
    only content of the message. (That was the one thing left to add after the
    missing arm, in the bug filed as
    FORMAL_x86_64_endtoend_call_rel32_has_no_tree, now fixed and deleted.)
    """

    def test_every_form_name_survives(self):
        detail = "no step lemma wired for: call_rel32, jmp_rel8, shl_r64_imm"
        line = ET._no_tree_line("form", detail)
        for form in ("call_rel32", "jmp_rel8", "shl_r64_imm"):
            self.assertIn(form, line,
                          f"`{form}` is truncated away from the only message that "
                          f"names it: {line!r}")

    def test_the_three_kinds_still_read_as_three_things(self):
        """The distinction the reporter exists to keep (B21).

        A loop, a path that returns into a caller and an unmodelled form are
        three different outcomes and were once all reported as failures, so the
        lines must not collapse into one another. Only `loops` differs by its
        TEXT — the other two are separated by the counters the reporter keeps
        (`notree` / `nocall` / `noform`) and by the three-way summary line,
        which is the arrangement, not the wording, that carries them apart."""
        self.assertEqual(ET._no_tree_line("loops", ""),
                         "  loops (no finite path tree)")
        for kind in ("form", "call"):
            self.assertNotEqual(ET._no_tree_line(kind, "x"),
                                ET._no_tree_line("loops", ""))
        # …and the bound each one keeps is the other half of it: the `call`
        # branch bounds its PROSE, the `form` branch keeps its LIST whole.
        long_prose = "the callee's ret returns into the caller " * 4
        self.assertLessEqual(len(ET._no_tree_line("call", long_prose)),
                             len("  no tree: ") + 60)
        self.assertIn(long_prose, ET._no_tree_line("form", long_prose))


if __name__ == "__main__":
    unittest.main(verbosity=2)