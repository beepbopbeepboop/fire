"""Quick regression for PERF_struct_self_assign_scan_uncached.
Must FAIL before memo and PASS after. Only covers the new memo paths.
"""
import unittest
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mojo.middle.module_shared import _SELF_ASSIGN_MEMO, _gmi_collect_self_assigns
from fire_compiler import FunctionDef, AssignStmt, IdentExpr, MemberExpr, IntLiteral

def _dummy_body():
    # Simplest body that produces a self-assign: self.x = 1
    return [AssignStmt(
        target=MemberExpr(obj=IdentExpr(name='self'), member='x'),
        value=IntLiteral(value=1)
    )]

class TestSelfAssignMemo(unittest.TestCase):
    def test_memo_replays_self_assign_result(self):
        _SELF_ASSIGN_MEMO.clear()
        class FakeGen:
            struct_bool_fields = {}
            _gmi_bool_params = set()
            struct_field_types = {}
            def _resolve_type(self, s): return s
            def _annotation_dict_val_type(self, a): return None
        gen = FakeGen()
        found = {}
        body = _dummy_body()
        pm = {}
        _gmi_collect_self_assigns(gen, 'S', body, pm, found)
        self.assertIn('x', found)
        found2 = {}
        _gmi_collect_self_assigns(gen, 'S', body, pm, found2)
        self.assertIn('x', found2)
        self.assertEqual(found, found2)

if __name__ == '__main__':
    unittest.main(verbosity=2, exit=False)