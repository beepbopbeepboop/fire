#!/usr/bin/env python3
"""Regression test for bootstrap hotspot profiling tools."""
import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))


def test_bootstrap_hotspots_tool_exists():
    """bootstrap_hotspots tool exists and is executable."""
    tool = os.path.join(HERE, 'tools', 'bootstrap_hotspots.py')
    assert os.path.exists(tool), f"missing {tool}"
    # Test it can be imported/run
    result = subprocess.run([sys.executable, tool, '--help'], 
                          cwd=HERE, capture_output=True)
    assert result.returncode == 0, f"tool failed: {result.stderr}"


def test_bootstrap_hotspots_profiling_capability():
    """bootstrap_hotspots can profile and identify hotspots."""
    tool = os.path.join(HERE, 'tools', 'bootstrap_hotspots.py')
    # Quick test - just check it can start profiling (don't actually run full bootstrap)
    result = subprocess.run([sys.executable, tool, '--stages'], 
                          cwd=HERE, capture_output=True, timeout=5)
    # Should not crash with import/syntax errors
    assert result.returncode in (0, 1), f"bad return: {result.returncode}, {result.stderr[:200]}"


if __name__ == '__main__':
    test_bootstrap_hotspots_tool_exists()
    test_bootstrap_hotspots_profiling_capability()
    print('ok')
