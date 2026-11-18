#!/usr/bin/env python3
"""Regression test: extended-register refusal names the option the word carries.

This pins the part-2 fix for the extended-register refusal naming bug:
`_unmodelled_instruction`'s extended-register arm decodes sf, option and imm3
from the refused word and appends them, by architectural name, to the refusal
reason.
"""

import unittest

from test_formal_call_proof_gen import _assembler_word


class TestExtendRefusalNamesTheOptionPin(unittest.TestCase):
    """The extended-register refusal names the option the word carries."""

    def test_names_the_option_and_imm3(self):
        import formal.arm64_proof_gen as G
        cases = [
            ("add x0, x1, w2, uxtw", "ADD extended",
             "option=010 (UXTW), imm3=0"),
            ("sub x0, x1, x2, sxtx #4", "SUB extended",
             "option=111 (SXTX), imm3=4"),
            ("cmp x1, x2, sxtx", "SUBS/CMP extended",
             "option=111 (SXTX), imm3=0"),
            ("add w0, w1, w2, uxtx", "ADD extended",
             "32-bit, option=011 (UXTX), imm3=0"),
        ]
        for form, want_name, want_decode in cases:
            with self.subTest(form=form):
                word = _assembler_word(form)
                self.assertIsNotNone(word, f"clang refuses `{form}`")
                self.assertIsNone(G._step_branch_index(word),
                                  f"`{form}` should be unmodelled")
                name, why = G._unmodelled_instruction(word)
                self.assertEqual(name, want_name)
                self.assertIn(want_decode, why)

if __name__ == "__main__":
    unittest.main()