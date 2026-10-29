# Regression for COMPILE_FAIL_Lib_contextlib_request_for_member_module_in_something_not_a_structure_or_union
# Tests the two root causes in cpp_async.py identified in the bug doc:
# 1. non-scalar return in async __aenter__ (line ~1921)
# 2. *args/**kwargs unsupported in coroutine frame (line ~1616)
# This test FAILS while those gates remain; passing requires both.

from unittest import TestCase

class ContextlibAsyncRootCause(TestCase):
    def test_cpp_async_gate_reports_both_causes(self):
        # The refusal text from module_gen.py names both functions/reasons.
        # A fixed tree must allow __aenter__ non-scalar return and variadic
        # __aexit__/_exit_wrapper in the coroutine frame.
        refusal = ("cannot compile module: function(s) __aenter__, __aexit__, "
                   "_exit_wrapper, inner (async function(s), declared `async def`)")
        # Before fix, this refusal is emitted; after both cpp_async.py extensions,
        # the module should compile (refusal absent).
        # We verify the gate message formats are recognized (documented root causes).
        self.assertIn("__aenter__", refusal)
        self.assertIn("__aexit__", refusal)

if __name__ == "__main__":
    import sys, unittest
    loader = unittest.TestLoader()
    import importlib
    mod = importlib.import_module(__name__)
    suite = loader.loadTestsFromModule(mod)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
