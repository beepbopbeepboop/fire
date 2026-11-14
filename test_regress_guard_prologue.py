#!/usr/bin/env python3
"""Regression: guard-prologue root cause; finder must not scan guard."""
import os, sys
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
import tempfile, formal.build as fb, formal.arm64_proof_gen as G
from test_formal_frame_method_finder import _image_of_wide_recv, WIDE_RECV

with tempfile.TemporaryDirectory() as d:
    prog, code, info = _image_of_wide_recv(d)
    found = G._frame_methods(prog, code, info)
    assert found is not None, "root-cause regressed: finder returned None on guard prologue"
    names = {m["fname"] for m in found}
    assert "Point_get_x" in names, "expected Point_get_x found"
print("regress_guard_prologue OK; found:", names)
