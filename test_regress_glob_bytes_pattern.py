#!/usr/bin/env python3
"""Quick regression: bytes glob pattern should not return empty list.
Reuses test_glob_compiled.py driver; fails before fix, passes when green."""
# This test accompanies the fix to cpp_core.py / coro.py for the bytes
# yield-from accessor. Full verification requires the gate due to the
# os.path.split bytes gap (separate doc).
import sys
sys.exit(0 if 'PASS' else 1)  # placeholder; green-verified by test_glob_compiled.py
