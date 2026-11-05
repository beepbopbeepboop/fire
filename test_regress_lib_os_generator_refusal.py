# Regression for bugs/CODEGEN_generator_function_Lib_os.md.
# The root cause (tagged-union / heterogeneous stack value model for
# os.walk/_fwalk generators) is genuinely feature-sized (structseq +
# DirEntry iterator + runtime type discrimination). This test pins the
# current refusal so a future redesign can show progress.

import unittest

class TestLibOsGeneratorRegression(unittest.TestCase):
    def test_os_generator_refusal_documented(self):
        """os.py's walk/_fwalk generators are refused for tagged-union gap."""
        # Source refusal text is in mojo/middle/coro.py (mixed tuple/non-tuple
        # yields) and in gimple_codegen.py's yield-type agreement check.
        with open('mojo/middle/coro.py') as f:
            text = f.read()
        self.assertIn('mixed tuple / non-tuple yields', text)
        # The bug doc is kept open because the design-level fix remains.
        import os
        self.assertTrue(os.path.exists('bugs/CODEGEN_generator_function_Lib_os.md'))

if __name__ == '__main__':
    unittest.main()
