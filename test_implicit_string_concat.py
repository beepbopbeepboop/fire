#!/usr/bin/env python3
"""Regression test for implicit multi-line string concatenation.

Tests that implicit string concatenation across newlines (without backslash)
is parsed as a single statement rather than emitting "Unexpected INDENT".
"""

import subprocess
import os
import tempfile


def test_implicit_string_concat():
    """Test that implicit string concatenation across newlines works."""
    test_content = 'def f():\n    x = "first"\n        "second"\n    return x\n'

    fd, test_file = tempfile.mkstemp(suffix='.mojo')
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(test_content)

        result = subprocess.run(
            ['python3', 'fire.py', 'build', test_file],
            capture_output=True, text=True,
            cwd='/Users/mrs/net/chatgpt/claude/work-4882',
        )

        assert result.returncode == 0, (
            f"Build failed with returncode {result.returncode}\n"
            f"STDOUT: {result.stdout[-200:]}\nSTDERR: {result.stderr[-200:]}"
        )
        assert 'Unexpected INDENT' not in result.stdout, (
            f"Got 'Unexpected INDENT' in stdout: {result.stdout[-200:]}"
        )
        print("✓ Implicit string concatenation test passed")
    finally:
        os.unlink(test_file)


if __name__ == '__main__':
    test_implicit_string_concat()
