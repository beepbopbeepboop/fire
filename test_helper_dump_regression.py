#!/usr/bin/env python3
"""Regression test for bootstrap-stage2-dumps:test_helper.mojo.

Verifies that `fire.py --dump test_helper.mojo` produces correct artefacts
(.tok, .ast, .ci, .pyi) when run through the stage2 compiled binary path.
Run via: python3 tools/memslot.py --gb 8 --label x -- <cmd>

Before fix: the dump failed or produced wrong output; after fix: all four files
are generated and contain expected content.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
FIRE = os.path.join(HERE, 'fire.py')

TEST_FILE = '/Users/mrs/net/chatgpt/claude/work-7921/test_helper.mojo'


class TestHelperDump(unittest.TestCase):
    def test_dump_produces_all_artifacts(self):
        td = tempfile.mkdtemp(prefix='test_helper_dump_')
        old_cwd = os.getcwd()
        try:
            os.chdir(td)
            r = subprocess.run(
                [sys.executable, FIRE, '--dump', TEST_FILE],
                capture_output=True, text=True, timeout=60,
            )
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

            artifacts = ['test_helper.tok', 'test_helper.ast', 'test_helper.ci',
                         'test_helper.pyi']
            for art in artifacts:
                self.assertTrue(os.path.exists(art), f'missing {art}')

            # Check AST contains both functions
            if os.path.exists('test_helper.ast'):
                with open('test_helper.ast') as f:
                    ast_text = f.read()
                self.assertIn('double', ast_text)
                self.assertIn('add', ast_text)

            # Check pyi has type stubs
            if os.path.exists('test_helper.pyi'):
                with open('test_helper.pyi') as f:
                    pyi_text = f.read()
                self.assertIn('# Type stubs for test_helper', pyi_text)

        finally:
            os.chdir(old_cwd)
            shutil.rmtree(td, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
