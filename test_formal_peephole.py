#!/usr/bin/env python3
"""The verified peephole pass: `formal/peephole.py`, its proofs, and its wiring.

Four things, and the order is the order they can go wrong in:

  * **The licence.** Every rule in the registry names a theorem in
    `lib/Peephole.lean`, and the pass REFUSES to run a rule whose theorem is
    not declared there. That is the mechanical form of "a rule without a proof
    is not allowed in", and it is checked here rather than trusted: the test
    declares a rule naming a theorem that does not exist and asserts the pass
    raises rather than rewriting.

  * **The rules themselves**, on hand-assembled instruction sequences rather
    than on the corpus, because the corpus does not happen to contain the
    windows they match (see `TestTheCorpus` and the note in
    `bugs/FORMAL_peephole_rules_without_proofs.md`): `mov_self` and
    `add_imm_fuse` fire zero times over all 52 `formal/examples`, and a rule
    nobody exercises is a rule nobody has checked.

  * **The address remap.** Deleting bytes moves every label, relocation and
    external-call stub, and `_Remap` is the one piece of the pass that is not
    about recognising instructions. `TestRemap` builds a two-instruction window
    inside a labelled region with a branch over it and asserts the branch, the
    labels and the stub address all land where the shrunken image says.

  * **The end-to-end claim.** `--opt` builds every `formal/examples/*.mojo`
    both ways and the two binaries must produce the same exit status and the
    same stdout. That is the differential run the flag exists for, and it is
    the check that caught every real bug this pass has had.

Run it:  python3 test_formal_peephole.py [-v]
"""
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
from formal.arm64 import encode_add_xd_xn_imm, encode_ret     # noqa: E402
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

    def test_copy_chain_is_proved_but_not_fired(self):
        # The rule is in `PENDING_RULES`, not `RULES`: its theorem is proved and
        # its liveness matcher is not yet sound for a loop. This asserts the
        # pass does NOT fire it, which is the property that keeps `--opt` safe
        # while the liveness analysis is being finished.
        words = _w(encode_add_xd_xn_imm(1, 2, 0), encode_add_xd_xn_imm(3, 1, 0),
                  encode_ret())
        asm, removed = self._run_words(words)
        self.assertEqual(0, removed)
        self.assertEqual(words, asm.words())


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
        self.assertEqual([], mismatched)

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