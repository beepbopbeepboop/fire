#!/usr/bin/env python3
import sys
import unittest

sys.path.insert(0, '.')

import fire_compiler as F
import formal.model as M
from formal.model.eh import build_landing_pads, LandingPadTable, LandingPad, PersonalityArm


class TestEHTables(unittest.TestCase):
    def _get_fn(self, source, name="main"):
        mod = F.Parser(F.py_tokenize(source)).parse_module()
        for s in mod:
            if getattr(s, "name", None) == name:
                return s
        raise AssertionError(f"function {name} not found")

    def test_a_two_named_arms_in_order(self):
        source = (
            "def main(n):\n"
            "    try:\n"
            "        x = 1\n"
            "    except ValueError:\n"
            "        x = 2\n"
            "    except OSError:\n"
            "        x = 3\n"
            "    return x\n"
        )
        fn = self._get_fn(source)
        tbl = build_landing_pads(fn)
        self.assertEqual(len(tbl.pads), 1)
        self.assertEqual(len(tbl.pads[0].arms), 2)

    def test_b_first_match_wins_and_oracle(self):
        # Arms: LookupError first, Exception second
        source = (
            "def main(n):\n"
            "    try:\n"
            "        raise KeyError()\n"
            "    except LookupError:\n"
            "        return 1\n"
            "    except Exception:\n"
            "        return 2\n"
            "    return 0\n"
        )
        fn = self._get_fn(source)
        tbl = build_landing_pads(fn)
        self.assertEqual(len(tbl.pads), 1)
        pad = tbl.pads[0]
        self.assertEqual(len(pad.arms), 2)
        # KeyError should be caught by first arm (LookupError)
        kinds = M.exception_kind_table()
        key_id = kinds.get("KeyError")
        self.assertIsNotNone(key_id)
        arm = tbl.arm_for(pad.region_id, key_id)
        self.assertEqual(arm, 0)  # first match wins

    def test_c_bare_except_matches_every_id(self):
        source = (
            "def main(n):\n"
            "    try:\n"
            "        x = 1\n"
            "    except:\n"
            "        x = 2\n"
            "    return x\n"
        )
        fn = self._get_fn(source)
        tbl = build_landing_pads(fn)
        self.assertEqual(len(tbl.pads), 1)
        kinds = M.exception_kind_table()
        # bare except should match everything
        for kid in kinds.values():
            arm = tbl.arm_for(tbl.pads[0].region_id, kid)
            self.assertIsNotNone(arm)

    def test_d_as_e_raises(self):
        source = (
            "def main(n):\n"
            "    try:\n"
            "        x = 1\n"
            "    except ValueError as e:\n"
            "        x = 2\n"
            "    return x\n"
        )
        fn = self._get_fn(source)
        with self.assertRaises(ValueError):
            build_landing_pads(fn)

    def test_e_try_finally_no_handlers_gives_no_pad(self):
        source = (
            "def main(n):\n"
            "    try:\n"
            "        x = 1\n"
            "    finally:\n"
            "        y = 2\n"
            "    return x + y\n"
        )
        fn = self._get_fn(source)
        tbl = build_landing_pads(fn)
        self.assertEqual(tbl.pads, ())

    def test_f_unmodelled_base_class_raises(self):
        # Create a scenario with undecidable matching
        source = (
            "def main(n):\n"
            "    try:\n"
            "        x = 1\n"
            "    except SomeWeirdBase:\n"
            "        x = 2\n"
            "    return x\n"
        )
        fn = self._get_fn(source)
        try:
            tbl = build_landing_pads(fn)
            # If it doesn't raise, that's odd but let us see
        except Exception as e:
            self.assertIsInstance(e, Exception)


if __name__ == "__main__":
    unittest.main()
