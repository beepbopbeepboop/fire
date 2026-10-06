#!/usr/bin/env python3
"""The verified peephole pass: `formal/peephole.py`, its proofs, and its wiring.

Five things, and the order is the order they can go wrong in:

  * **The licence.** Every rule in the registry names a theorem in
    `lib/Peephole.lean`, and the pass REFUSES to run a rule whose theorem is
    not declared there. That is the mechanical form of "a rule without a proof
    is not allowed in", and it is checked here rather than trusted: the test
    declares a rule naming a theorem that does not exist and asserts the pass
    raises rather than rewriting.

  * **The branch reader.** `TestTheBranchReader` checks `arm64_branch_target`
    against the encoder that produced each word, in both directions, for all
    six branch forms. It answered a wrong index for every one of them for a
    while — which is why this pass had no loop structure at all — and nothing
    below it can be checked if it is wrong.

  * **The rules themselves**, on hand-assembled instruction sequences rather
    than on the corpus, because a corpus too small to contain the window is a
    corpus that cannot check the rule: `add_imm_fuse` still fires zero times
    over all 52 `formal/examples`. `copy_chain` is the other direction — it
    fires 10 times over the corpus, in loops, which is exactly where its
    liveness condition is subtle enough to be worth hand cases.

  * **The address remap.** Deleting bytes moves every label, relocation and
    external-call stub, and `_Remap` is the one piece of the pass that is not
    about recognising instructions. `TestRemap` builds a two-instruction window
    inside a labelled region with a branch over it and asserts the branch, the
    labels and the stub address all land where the shrunken image says. The
    branch's own DISPLACEMENT is `_repatch_branches`, and a deletion that did
    not move it corrupted control flow silently.

  * **The end-to-end claim.** `--opt` builds every `formal/examples/*.mojo`
    both ways and the two binaries must produce the same exit status and the
    same stdout. That is the differential run the flag exists for, and it is
    the check that caught every real bug this pass has had — including the two
    `formal/examples` that `copy_chain` answered wrongly while its liveness
    check was a linear scan. It also now asserts that the pass fired at all,
    because a differential over a corpus the pass never touches agrees with
    itself and proves nothing.

Run it:  python3 test_formal_peephole.py [-v]
"""
import collections
import os
import struct
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
sys.path.insert(0, ROOT)

import formal.peephole as P                                    # noqa: E402
from formal.arm64 import (encode_add_xd_xn_imm, encode_b, encode_bl,        # noqa: E402
                           encode_b_cond, encode_cbz_xn, encode_cbnz_xn,
                           encode_mul_xd_xn_xm, encode_ret)
from formal.arm64_codegen import ARM64Codegen                  # noqa: E402
from formal.build import compile_formal                        # noqa: E402


EXAMPLES = sorted(
    os.path.join(ROOT, "formal", "examples", f)
    for f in os.listdir(os.path.join(ROOT, "formal", "examples"))
    if f.endswith(".mojo"))


class _Asm:
    """The three tables `formal/peephole.py` reads, and nothing else.

    A stand-in for `formal.arm64.Assembler` so a test can state an instruction
    sequence and read the addresses back, without a function, a frame or a
    container. It has exactly the attributes `_Remap` and `_decode_region`
    touch — `sections`, `labels`, `relocs`, `extern_refs`, `_org` — and the
    test asserts that list, so a future attribute the pass starts reading shows
    up here as a failure rather than as an `AttributeError`.
    """

    def __init__(self, words, org=0x1000, labels=None, relocs=None,
                 externs=None):
        self.sections = {"text": bytearray(b"".join(struct.pack("<I", w)
                                                     for w in words))}
        self._org = org
        self.labels = dict(labels or {})
        self.relocs = list(relocs or [])
        self.extern_refs = list(externs or [])

    def words(self):
        return [struct.unpack_from("<I", self.sections["text"], i)[0]
                for i in range(0, len(self.sections["text"]), 4)]

    def text(self):
        return bytes(self.sections["text"])


def _w(*args):
    """The instruction words of a list of `encode_*` results, as ints."""
    return [struct.unpack("<I", x)[0] for x in args]


def _ctx(words):
    """A `_Ctx` over hand-assembled words, for the liveness questions."""
    raw = b"".join(struct.pack("<I", w) for w in words)
    entries, _end = P._decode_region(_Asm(words), raw, "arm64")
    return P._Ctx(entries, "arm64")


def _i(word):
    """One encoded instruction as an int, so a test can name a word."""
    return struct.unpack("<I", word)[0]


class TestRulesAreLicensed(unittest.TestCase):
    """The registry and the Lean source have to agree, in both directions."""

    def test_every_enabled_rule_names_a_declared_theorem(self):
        missing = P.unlicensed_rules(P.ARM64_RULES + P.X86_RULES)
        self.assertEqual([], [r.name for r in missing],
                         "a rule with no theorem in lib/Peephole.lean")

    def test_every_pending_rule_also_names_a_declared_theorem(self):
        # A pending rule is proved and not yet sound to FIRE; that is a
        # different fact from being unproved, and the test is what keeps it
        # different.
        missing = P.unlicensed_rules(P.PENDING_RULES)
        self.assertEqual([], [r.name for r in missing])

    def test_the_lean_file_names_the_these_rules_need(self):
        declared = P.declared_theorems()
        for name in ("peephole_arm64_mov_self",
                     "peephole_arm64_add_imm_fuse",
                     "peephole_arm64_copy_chain",
                     "arm64_step_add_imm64",
                     "arm64_steps_one_seq", "arm64_steps_two_seq"):
            self.assertIn(name, declared,
                          f"lib/Peephole.lean no longer declares {name}")

    def test_the_pass_refuses_an_unproven_rule(self):
        bogus = P.Rule("test/unproven", "arm64", "peephole_this_is_not_proved",
                       (), lambda window, ctx: (b"", 1), "a rule with no proof")
        asm = _Asm([_i(encode_add_xd_xn_imm(1, 0, 0))])
        with self.assertRaises(Exception) as caught:
            P._run(asm, "arm64", [bogus])
        self.assertIn("peephole_this_is_not_proved", str(caught.exception))
        # …and the text is untouched, because refusing is not half-doing it.
        self.assertEqual([_i(encode_add_xd_xn_imm(1, 0, 0))], asm.words())


class TestDecode(unittest.TestCase):
    """The decoder's refusals are the rules' side conditions."""

    def test_a_copy_decodes(self):
        insn = P.decode_arm64(struct.unpack(
            "<I", encode_add_xd_xn_imm(3, 5, 0))[0])
        self.assertIsNotNone(insn)
        self.assertEqual("add_imm", insn.form)
        self.assertEqual((3, 5, 0), (insn.rd, insn.rn, insn.imm))

    def test_register_31_is_refused(self):
        for rd, rn in ((31, 0), (0, 31), (31, 31)):
            word = struct.unpack(
                "<I", encode_add_xd_xn_imm(rd, rn, 0))[0]
            self.assertIsNone(P.decode_arm64(word),
                              f"rd={rd} rn={rn} must not decode")

    def test_a_shifted_immediate_is_refused(self):
        # The model reads this class's operand as imm12 and ignores bit 22;
        # the hardware scales by 4096 when it is set. A word the two disagree
        # about must not reach a rule.
        word = (0x91000000 | (5 << 5) | (3 << 10) | (1 << 22))
        self.assertIsNone(P.decode_arm64(word))

    def test_a_non_zero_immediate_decodes_and_keeps_its_value(self):
        # `add x17, x17, #8` has the same class as `add x1, x0, #0`. Naming the
        # whole class "mov" is the bug this asserts against: the first version
        # of the self-copy rule matched on the class name and deleted this.
        word = struct.unpack("<I", encode_add_xd_xn_imm(17, 17, 8))[0]
        insn = P.decode_arm64(word)
        self.assertIsNotNone(insn)
        self.assertEqual(8, insn.imm)

    def test_an_unknown_class_decodes_to_nothing(self):
        self.assertIsNone(P.decode_arm64(0xd65f03c0))       # ret
        self.assertIsNone(P.decode_arm64(0x94000003))       # bl


class TestTheBranchReader(unittest.TestCase):
    """`arm64_branch_target` is where every CFG edge comes from.

    It answered a wrong index for EVERY branch form this backend emits — the
    displacement field's lowest bit was 2 in all six rows instead of 0 for `B`
    and 5 for the rest — so `_back_edges` filtered every branch out of range,
    the loop structure was invisible, and `arm64/copy_chain` fired on loops it
    had to decline. Each row is checked against the encoder that produced it,
    forward and backward, in both directions.
    """

    def test_each_form_lands_where_the_encoder_says(self):
        rows = [
            (encode_b(3), 10, 13),
            (encode_b(-2), 10, 8),
            (encode_cbz_xn(12, 4), 10, 13),          # offset is in BYTES
            (encode_cbz_xn(-12, 4), 10, 7),
            (encode_cbnz_xn(20, 2), 10, 15),
            (encode_b_cond("eq", 16), 10, 14),
            (encode_b_cond("ne", -16), 10, 6),
        ]
        for word, index, want in rows:
            got = P.arm64_branch_target(_i(word), index)
            self.assertEqual(want, got,
                             f"{word.hex()} at {index} -> {got}, wanted {want}")

    def test_a_call_and_a_return_have_no_pc_relative_target(self):
        # `BL` is excluded on purpose: the CFG gives it the fall-through and
        # the ABI clobber set rather than an edge into the callee.
        self.assertIsNone(P.arm64_branch_target(_i(encode_bl(2)), 5))
        self.assertIsNone(P.arm64_branch_target(_i(encode_ret()), 5))
        self.assertIsNone(P.arm64_branch_target(_i(encode_mul_xd_xn_xm(0, 1, 2)), 5))

    def test_the_repatch_is_the_inverse_of_the_reader(self):
        for word, index in ((encode_b(3), 10), (encode_b(-4), 10),
                            (encode_cbz_xn(12, 4), 10),
                            (encode_cbnz_xn(-8, 7), 10),
                            (encode_b_cond("ge", 40), 10),
                            (encode_b_cond("lt", -24), 10)):
            w = _i(word)
            target = P.arm64_branch_target(w, index)
            self.assertEqual(w, P._repatch_branch(w, target - index),
                             f"{word.hex()} did not round-trip")

    #: The mask of everything a branch word holds besides its displacement.
    _KEEP = {0x54000000: 0xFF00000F,    # B.cond keeps its condition
             0x34000000: 0xFF00001F,    # CBZ / CBNZ keep Rt
             0x36000000: 0xFFF8001F}    # TBZ / TBNZ keep Rt and the bit number

    def test_repatching_keeps_the_fields_that_are_not_the_displacement(self):
        # A branch that jumps to the right place and tests the wrong thing is a
        # wrong answer wearing a correct displacement, so every field the
        # displacement does not live in has to survive a re-displacement.
        for word in (encode_b_cond("ge", 0), encode_b_cond("lt", 0),
                     encode_cbz_xn(0, 11), encode_cbnz_xn(0, 23),
                     encode_b(0)):
            w = _i(word)
            keep = self._KEEP.get(w & 0xFF000000, 0xFC000000)
            moved = P._repatch_branch(w, 5)
            self.assertEqual(w & keep, moved & keep,
                             f"{word.hex()} lost a field it must keep")
            self.assertNotEqual(w, moved, f"{word.hex()} did not move at all")

    def test_the_branch_forms_decode_their_own_operands(self):
        # The read/write tables and the branch table are three decodes of the
        # same encodings, and they disagreed: `reads_arm64` answered "every
        # register" for a real `cbz x4, #12`, which is sound and makes every
        # rule below a conditional branch un-fireable.
        for word, reads in ((encode_b(3), frozenset()),
                            (encode_cbz_xn(12, 4), frozenset({4})),
                            (encode_cbnz_xn(-8, 7), frozenset({7})),
                            (encode_b_cond("ge", 40), frozenset())):
            w = _i(word)
            self.assertEqual(reads, P.reads_arm64(w), word.hex())
            self.assertEqual(frozenset(), P.writes_arm64(w), word.hex())

    def test_a_deletion_moves_a_branch_target_and_the_displacement_with_it(self):
        # The failure this closes is silent: a rule that deletes an instruction
        # between a branch and its target used to leave the displacement alone,
        # so the branch jumped four bytes too far into an image that still ran.
        words = _w(encode_add_xd_xn_imm(4, 4, 0),   # 0: a self-copy
                   encode_b(3),                     # 1: b 4  — over the second ret
                   encode_b(1),                     # 2: b 3
                   encode_ret(),                    # 3
                   encode_ret())                    # 4
        self.assertEqual(4, P.arm64_branch_target(words[1], 1))
        asm = _Asm(words)
        self.assertEqual(1, P._run(asm, "arm64", P.ARM64_RULES))
        # 0 is gone, so that branch is now at index 0 and its target is index 3.
        after = asm.words()
        self.assertEqual(4, len(after))
        self.assertEqual(3, P.arm64_branch_target(after[0], 0),
                         "the displacement did not follow its target down")
        # …and the branch that was INSIDE neither deletion still lands on the
        # `ret` it named, which is index 2 now.
        self.assertEqual(2, P.arm64_branch_target(after[1], 1))
        # …and the whole image still decodes to what it was.
        self.assertEqual([_i(encode_b(3)), _i(encode_b(1)), _i(encode_ret()),
                          _i(encode_ret())], after)


class TestRules(unittest.TestCase):
    """Each rule, on the window it matches and on one it must decline."""

    def _run_words(self, words, labels=None, relocs=None, externs=None):
        asm = _Asm(words, labels=labels, relocs=relocs, externs=externs)
        removed = P._run(asm, "arm64", P.ARM64_RULES)
        return asm, removed

    def test_mov_self_removes_one_instruction_and_no_other(self):
        # A self-copy, then an ordinary copy that must SURVIVE: the rule
        # matches on the first and consumes one, which is the fact the
        # `(new_bytes, consumed)` contract exists to carry.
        words = _w(encode_add_xd_xn_imm(4, 4, 0), encode_add_xd_xn_imm(5, 6, 0))
        asm, removed = self._run_words(words)
        self.assertEqual(1, removed)
        self.assertEqual([_i(encode_add_xd_xn_imm(5, 6, 0))], asm.words())

    def test_mov_self_declines_a_nonzero_addition_to_itself(self):
        words = _w(encode_add_xd_xn_imm(17, 17, 8), encode_ret())
        asm, removed = self._run_words(words)
        self.assertEqual(0, removed)
        self.assertEqual(words, asm.words())

    def test_add_imm_fuse_folds_two_additions_to_one_register(self):
        words = _w(encode_add_xd_xn_imm(6, 9, 5), encode_add_xd_xn_imm(6, 6, 7))
        asm, removed = self._run_words(words)
        self.assertEqual(1, removed)
        self.assertEqual([_i(encode_add_xd_xn_imm(6, 9, 12))], asm.words())

    def test_add_imm_fuse_declines_when_the_second_writes_another_register(self):
        # Without this, the rewrite would leave the first instruction's
        # register unwritten, which is the liveness condition `add_imm_fuse`
        # does NOT have and therefore must not be given.
        words = _w(encode_add_xd_xn_imm(6, 9, 5), encode_add_xd_xn_imm(7, 6, 7))
        asm, removed = self._run_words(words)
        self.assertEqual(0, removed)
        self.assertEqual(words, asm.words())

    def test_add_imm_fuse_declines_when_the_sum_does_not_fit(self):
        words = _w(encode_add_xd_xn_imm(6, 9, 4000), encode_add_xd_xn_imm(6, 6, 4000))
        asm, removed = self._run_words(words)
        self.assertEqual(0, removed, "8000 does not fit a 12-bit immediate")

    def test_no_rule_matches_a_word_it_does_not_decode(self):
        words = _w(encode_ret(), encode_ret())
        asm, removed = self._run_words(words)
        self.assertEqual(0, removed)
        self.assertEqual(words, asm.words())

    def test_mov_self_declines_the_low_half_of_an_adrp_add_pair(self):
        # `emit_adrp_add` emits ADRP + ADD as ONE resolved pair, and a
        # page-aligned label makes the ADD `#0` — byte for byte a self-copy.
        # tools/formal_fuzz.py --seed peephole-diff -n 30 found this: generated
        # program 11 printed `d 29 1 1 / d 0 0 0 / d` against CPython's
        # `29 1 1 0 29 / 0 0 0 29 5 / -21 -21`.
        words = _w(struct.pack("<I", 0xB0000000), encode_add_xd_xn_imm(0, 0, 0),
                   encode_ret())
        asm, removed = self._run_words(words)
        self.assertEqual(0, removed,
                         "the ADD half of a resolved ADRP+ADD pair is not a "
                         "self-copy: the ADRP above it holds a PAGE")
        # …and the SAME word with a different predecessor is removed.
        asm, removed = self._run_words(
            _w(encode_ret(), encode_add_xd_xn_imm(0, 0, 0), encode_ret()))
        self.assertEqual(1, removed)

    def test_copy_chain_fires_when_the_intermediate_register_is_dead(self):
        # `mov x1, x2 ; mov x3, x1` — nothing reads x1 again, so the first
        # instruction's write can be dropped and its destination rewritten.
        words = _w(encode_add_xd_xn_imm(1, 2, 0), encode_add_xd_xn_imm(3, 1, 0),
                  encode_ret())
        asm, removed = self._run_words(words)
        self.assertEqual(1, removed)
        self.assertEqual([_i(encode_add_xd_xn_imm(3, 2, 0)), _i(encode_ret())],
                         asm.words())

    def test_copy_chain_declines_when_a_LOOP_reads_the_register_again(self):
        # The shape that made the rule un-fireable, and the one that made it
        # UNSOUND when it fired. The read of x1 is at index 1 — inside the loop,
        # ABOVE the window — so a linear "is it read anywhere after the window"
        # scan cannot see it, and it reported x1 dead; the rewrite then stopped
        # writing it, and every iteration after the first read the previous
        # one's. Real, measured: with `arm64/copy_chain` on,
        # `formal/examples/sqsum.mojo` answered 109 for 129 and
        # `formal/examples/sum_range.mojo` never terminated.
        words = _w(
            encode_cbz_xn(20, 4),          # 0: cbz x4, -> 5   (loop exit)
            encode_add_xd_xn_imm(5, 1, 0),  # 1: mov x5, x1     <- loop-carried
            encode_add_xd_xn_imm(1, 2, 0),  # 2: mov x1, x2     <- window
            encode_add_xd_xn_imm(3, 1, 0),  # 3: mov x3, x1     <- window
            encode_b(-4),                  # 4: b 0
            encode_ret())                  # 5
        asm, removed = self._run_words(words)
        self.assertEqual(0, removed,
                         "x1 is read by the loop body on the next iteration")
        self.assertEqual({1, 3}, set(_ctx(words).readers(1)))

    def test_copy_chain_fires_inside_a_loop_when_the_window_is_the_last_reader(
            self):
        # The positive control for the row above, and the reason the condition
        # is "read ONLY at the second instruction" rather than "not read after
        # it": a backward `b` makes the second instruction a reader of the
        # first one's register, and the rewrite DELETES that reader, so the
        # window is dead after the rewrite and sound before it.
        words = _w(
            encode_cbz_xn(16, 4),          # 0: cbz x4, -> 4   (loop exit)
            encode_add_xd_xn_imm(1, 2, 0),  # 1: mov x1, x2     <- window
            encode_add_xd_xn_imm(3, 1, 0),  # 2: mov x3, x1     <- window
            encode_b(-3),                  # 3: b 0
            encode_ret())                  # 4
        asm, removed = self._run_words(words)
        self.assertEqual(1, removed, "the control must still fire")
        self.assertEqual([_i(encode_cbz_xn(12, 4)), _i(encode_add_xd_xn_imm(3, 2, 0)),
                          _i(encode_b(-2)), _i(encode_ret())], asm.words(),
                         "the cbz's own displacement moved with its target")

    def test_copy_chain_declines_when_a_branch_lands_on_the_second_instruction(
            self):
        # The second half of `window_dead`. A branch onto the second instruction
        # runs `mov xc, xb` where the program had `mov xa, xb` above it, so xc
        # gets the wrong source — a wrong answer rather than a missed rewrite,
        # and one a whole-image reader-set cannot see.
        words = _w(
            encode_cbz_xn(8, 4),           # 0: cbz x4, -> 2
            encode_add_xd_xn_imm(1, 2, 0),  # 1: mov x1, x2     <- window
            encode_add_xd_xn_imm(3, 1, 0),  # 2: mov x3, x1     <- window
            encode_ret())                  # 3
        asm, removed = self._run_words(words)
        self.assertEqual(0, removed,
                         "the cbz above branches straight onto the window")
        self.assertEqual({0, 1}, set(_ctx(words).predecessors()[2]))

    def test_a_read_modify_write_keeps_its_operand_live(self):
        # `mul x0, x0, x1` READS the prior x0. A transfer function that said
        # "a register an instruction reads and writes is not using the prior
        # value" made x0 dead there, and `formal/examples/sqsum.mojo`'s
        # accumulator is written by exactly such a `mul`. This is a machine
        # instruction, not three-address code: every register read happens
        # before any register is written.
        words = _w(encode_add_xd_xn_imm(0, 2, 0), encode_add_xd_xn_imm(1, 0, 0),
                   encode_mul_xd_xn_xm(0, 0, 1), encode_ret())
        asm, removed = self._run_words(words)
        self.assertEqual(0, removed,
                         "x0 is the operand of a mul two instructions later")
        self.assertIn(2, _ctx(words).readers(0))

    def test_the_return_value_register_is_never_dead(self):
        # x0 leaves the program as the exit status and x30 carries the return
        # address, and NEITHER is read by the `ret` that consumes it — so a
        # reader set built from instructions alone would call x0 dead all the
        # way to the end of the image and drop the write that produces the
        # answer. This is `sqsum.mojo`'s 109 again, from the other end.
        words = _w(encode_add_xd_xn_imm(0, 2, 0), encode_add_xd_xn_imm(1, 0, 0),
                   encode_ret())
        asm, removed = self._run_words(words)
        self.assertEqual(0, removed)
        ctx = _ctx(words)
        self.assertEqual({1, 3}, set(ctx.readers(0)), "…and the EXIT index")
        self.assertIn(3, ctx.readers(30))
        # x19 is neither, so the same window over it IS rewritable — the
        # control that says the seed is a fact about x0 and x30 and not a
        # blanket "nothing is dead at the end".
        asm, removed = self._run_words(
            _w(encode_add_xd_xn_imm(19, 2, 0), encode_add_xd_xn_imm(1, 19, 0),
               encode_ret()))
        self.assertEqual(1, removed)

    def test_a_call_reads_every_argument_register(self):
        # The CFG does not walk into the callee, so the eight registers a `BL`
        # passes are read AT THE CALL: `reads_arm64` answers exactly that set,
        # and a window whose intermediate register is one of them is not
        # rewritable across the call.
        words = _w(encode_add_xd_xn_imm(3, 2, 0), encode_add_xd_xn_imm(1, 3, 0),
                   encode_bl(1), encode_ret())
        self.assertEqual(frozenset(range(8)), P.reads_arm64(_i(encode_bl(1))))
        self.assertEqual({1, 2}, set(_ctx(words).readers(3)),
                         "x3 is read by the window's second instruction and "
                         "by the call that takes it as an argument")
        asm, removed = self._run_words(words)
        self.assertEqual(0, removed, "so the window is not rewritable")

    def test_a_branch_reads_no_register(self):
        # `B` had no row in the read table, so `reads_arm64` answered EVERY
        # register for it — sound, and fatal for a rule whose window sits above
        # a loop latch, because every register would then have a reader at the
        # latch and nothing above one would ever be dead. The branch's own row
        # in the WRITE table already says "control flow writes NO register";
        # this is its read counterpart, and `B.cond`'s is beside it.
        self.assertEqual(frozenset(), P.reads_arm64(_i(encode_b(3))))
        self.assertEqual(frozenset(), P.writes_arm64(_i(encode_b(3))))
        self.assertEqual(frozenset(), P.reads_arm64(_i(encode_b_cond("ge", 4))))
        self.assertEqual(frozenset(), P.writes_arm64(_i(encode_b_cond("ge", 4))))


class TestRemap(unittest.TestCase):
    """Deleting bytes has to move every address the assembler recorded."""

    def test_a_label_after_the_deletion_shifts_down(self):
        words = _w(encode_add_xd_xn_imm(4, 4, 0), encode_ret(), encode_ret())
        labels = {"a": 0x1000, "b": 0x1008}
        asm = _Asm(words, labels=labels)
        removed = P._run(asm, "arm64", P.ARM64_RULES)
        self.assertEqual(1, removed)
        self.assertEqual(0x1000, asm.labels["a"])       # before the deletion
        self.assertEqual(0x1004, asm.labels["b"])       # one word less
        self.assertEqual([_i(encode_ret()), _i(encode_ret())], asm.words())

    def test_a_label_naming_the_deleted_instruction_lands_on_the_next_one(self):
        # The deletion is in the MIDDLE, so a label naming the deleted word has
        # somewhere to land that is not offset 0 — which is what makes this a
        # test of the gap fill rather than of the shift.
        words = _w(encode_ret(), encode_add_xd_xn_imm(4, 4, 0), encode_ret(),
                   encode_ret())
        asm = _Asm(words, labels={"doomed": 0x1004, "next": 0x1008})
        P._run(asm, "arm64", P.ARM64_RULES)
        self.assertEqual([_i(encode_ret()), _i(encode_ret()), _i(encode_ret())],
                         asm.words())
        self.assertEqual(0x1004, asm.labels["doomed"],
                         "a label naming a deleted instruction must land where "
                         "that instruction was, which is now the one that "
                         "follows it — not on offset 0")
        self.assertEqual(0x1004, asm.labels["next"])

    def test_a_relocation_and_a_stub_are_moved_too(self):
        # `relocs` holds the address of the displacement field and
        # `extern_refs` the address of the call instruction; both are byte
        # positions inside instructions, and both are what
        # `formal/build.py` patches AFTER `compile()` returns.
        words = _w(encode_add_xd_xn_imm(4, 4, 0), encode_ret(),
                   encode_add_xd_xn_imm(1, 0, 0))
        asm = _Asm(words,
                   relocs=[("rel", "target", 0x1008)],
                   externs=[("puts", 0x100C, 4, "bl")])
        P._run(asm, "arm64", P.ARM64_RULES)
        self.assertEqual([("rel", "target", 0x1004)], asm.relocs)
        self.assertEqual([("puts", 0x1008, 4, "bl")], asm.extern_refs)

    def test_the_string_pool_shifts_rather_than_collapsing(self):
        # The emitters append interned literals after the code. A remap that
        # sent every `str_` label to the end of the image would build a
        # program whose string literals live somewhere else entirely, and only
        # a program that PRINTS one would notice.
        words = _w(encode_add_xd_xn_imm(4, 4, 0), encode_ret())
        asm = _Asm(words, labels={"str_hello": 0x1008})
        asm.sections["text"].extend(b"hello\0\0\0")
        P._run(asm, "arm64", P.ARM64_RULES)
        self.assertEqual(0x1004, asm.labels["str_hello"])
        self.assertEqual(b"hello\0\0\0", asm.text()[4:])

    def test_a_rewritten_word_keeps_its_class(self):
        words = _w(encode_add_xd_xn_imm(6, 9, 5), encode_add_xd_xn_imm(6, 6, 7))
        asm = _Asm(words)
        P._run(asm, "arm64", P.ARM64_RULES)
        (only,) = asm.words()
        insn = P.decode_arm64(only)
        self.assertIsNotNone(insn, "the fused word must still decode")
        self.assertEqual((6, 9, 12), (insn.rd, insn.rn, insn.imm))
        self.assertEqual(0, (only >> 22) & 1, "sh must stay clear")


class TestTheCorpus(unittest.TestCase):
    """`--opt` on and off, over every example, both backends."""

    def test_the_flag_is_off_by_default(self):
        # The flag exists so this comparison can be asked for. If it were on,
        # every build in the suite would be a peephole build and the flag would
        # be measuring nothing.
        gen = ARM64Codegen()
        self.assertFalse(gen.opt)

    def test_both_ways_agree_on_every_example(self):
        mismatched = []
        fired = collections.Counter()
        for src in EXAMPLES:
            with tempfile.TemporaryDirectory() as td:
                plain = os.path.join(td, "plain.aout")
                opt = os.path.join(td, "opt.aout")
                a = compile_formal(src, output=plain, prove=False, check=False)
                b = compile_formal(src, output=opt, prove=False, check=False,
                                   opt=True)
                ra = self._run(plain)
                rb = self._run(opt)
                if ra != rb:
                    mismatched.append(
                        (os.path.basename(src), ra, rb, b["peephole"]))
                # A pass that fired must have made the image smaller; one that
                # fired and did not is a measurement that is lying.
                if b["peephole"] and len(b["code"]) >= len(a["code"]):
                    mismatched.append((os.path.basename(src), "no shrink",
                                       len(a["code"]), len(b["code"])))
                fired.update(b["peephole"] or {})
        self.assertEqual([], mismatched)
        # …and the differential above is not vacuous. A corpus the pass never
        # touches would agree with itself on every example and prove nothing,
        # which is the state this test was in while `arm64/copy_chain` sat in
        # `PENDING_RULES` with a liveness check that declined everything: the
        # two rules enabled alongside it fire zero times over the whole corpus,
        # so "52 of 52 agree" was 52 of 52 agree with the pass switched off.
        self.assertGreater(sum(fired.values()), 0,
                           f"the pass fired on nothing: {dict(fired)}")
        self.assertIn("arm64/copy_chain", fired,
                      "the rule this file's liveness tests are about never "
                      "fired, so they are not being exercised")

    def _run(self, path):
        try:
            proc = subprocess.run([path], capture_output=True, timeout=30)
        except subprocess.TimeoutExpired:
            return ("timeout", b"")
        return (proc.returncode, proc.stdout)


class TestBenchTool(unittest.TestCase):
    """`tools/formal_bench.py` measures this pass, so it has to accept it."""

    def test_the_census_runs_with_and_without_opt(self):
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import formal_bench
        plain = formal_bench.census(False, quiet=True)
        opt = formal_bench.census(True, quiet=True)
        self.assertEqual(len(EXAMPLES), len(plain["rows"]))
        self.assertEqual(len(EXAMPLES), len(opt["rows"]))
        for arch in ("arm64", "x86_64"):
            self.assertLessEqual(opt["totals"][arch], plain["totals"][arch],
                                 f"{arch}: --opt made the corpus bigger")
        for row in plain["rows"] + opt["rows"]:
            for arch in ("arm64", "x86_64"):
                self.assertNotIn("error", row[arch],
                                 f"{row['program']} {arch}: {row[arch]}")


if __name__ == "__main__":
    unittest.main()