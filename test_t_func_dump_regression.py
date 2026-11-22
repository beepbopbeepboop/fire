#!/usr/bin/env python3
"""Regression test for bootstrap-stage2-dumps:t_func.mojo.

Verifies that `fire.py --dump t_func.mojo` produces correct artefacts
(.tok, .ast, .ci, .pyi) through the reference path.
Run via: python3 tools/memslot.py --gb 8 --label x -- <cmd>

The item `bootstrap-stage2-dumps:t_func.mojo` is one file of the
fanout('bootstrap-stage2-dumps', ...) in tools/suite.py. It has no known
defect: it dumps cleanly through `fire.py --dump`. The doc was a cascaded
artifact of `bootstrap-stage2-cc` being disabled (so stage2/mojo was never
built); once that dependency is unblocked this item passes.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, 'fire.py')

TEST_FILE = '/Users/mrs/net/chatgpt/claude/work-7951/t_func.mojo'


class TestFuncDump(unittest.TestCase):
    def test_dump_produces_all_artifacts(self):
        td = tempfile.mkdtemp(prefix='test_t_func_dump_')
        old_cwd = os.getcwd()
        try:
            os.chdir(td)
            r = subprocess.run(
                [sys.executable, FIRE, '--dump', TEST_FILE],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

            artifacts = ['t_func.tok', 't_func.ast', 't_func.ci',
                         't_func.pyi']
            for art in artifacts:
                self.assertTrue(os.path.exists(art), f'missing {art}')

            # Check AST contains both functions
            if os.path.exists('t_func.ast'):
                with open('t_func.ast') as f:
                    ast_text = f.read()
                self.assertIn('add', ast_text)
                self.assertIn('main', ast_text)

            # Check CI contains the add function call
            if os.path.exists('t_func.ci'):
                with open('t_func.ci') as f:
                    ci_text = f.read()
                self.assertIn('add', ci_text)
                self.assertIn('print', ci_text)

            # Check pyi has type stubs
            if os.path.exists('t_func.pyi'):
                with open('t_func.pyi') as f:
                    pyi_text = f.read()
                self.assertIn('# Type stubs for t_func', pyi_text)

        finally:
            os.chdir(old_cwd)
            shutil.rmtree(td, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
