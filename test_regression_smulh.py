"""Regression for bugs/PROOF_lib_ProofLib_work_step_smulh_cannot_be_proved_against_this_chain.md.

Before the fix the SMULH arm was reverted (or defined with Int.fdiv inside
smulh64, which made bv_decide call the definition noncomputable and hit the
heartbeat ceiling). After: arm64_step ends with the 0xffe07c00/0x9b407c00
branch; work_step_smulh exists at index 68; smulh64 expresses the high half
through umulh64 (no Int division) so bv_decide stays computable.
"""
import re, unittest

HERE = __import__('os').path.dirname(__file__)

class TestSMULHNotReverted(unittest.TestCase):
    def test_smulh_arm_is_last_in_chain(self):
        src = open(HERE + "/lib/ProofLib.lean").read()
        # The SMULH condition must be the LAST else-if before the final else.
        # Find the last "else if" that matches SMULH.
        blocks = re.split(r"else if \(.*?\) = .*? then", src)
        last_cond = re.search(r"else if \(insn &&& 0xffe07c00\) = 0x9b407c00 then",
                              src)
        self.assertIsNotNone(last_cond,
                             "SMULH arm missing from arm64_step")

    def test_smulh_lemma_exists(self):
        src = open(HERE + "/lib/ProofLib.lean").read()
        self.assertIn("theorem work_step_smulh (s : Arm64State)", src)

    def test_smulh_definition_has_no_int_division(self):
        """Root cause of the timeout: Int.fdiv inside smulh64. Fixed by
        expressing the high half through umulh64 (Nat division) instead."""
        src = open(HERE + "/lib/ProofLib.lean").read()
        # The definition must NOT contain Int.fdiv or Int.tdiv.
        def_block = re.search(
            r"def smulh64 \(a b : UInt64\) : UInt64 :=.*?\n[\t ]*\n/--", src, re.DOTALL)
        self.assertIsNotNone(def_block)
        def_text = def_block.group(0)
        self.assertNotIn("Int.fdiv", def_text,
                         "smulh64 still uses Int.fdiv — root cause not fixed")
        self.assertNotIn("Int.tdiv", def_text,
                         "smulh64 still uses Int.tdiv")
        self.assertIn("umulh64", def_text,
                      "smulh64 must delegate to umulh64 (no Int)")

if __name__ == "__main__":
    unittest.main()
