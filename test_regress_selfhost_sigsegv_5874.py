#!/usr/bin/env python3
"""Regression pin for the selfhost SIGSEGV root cause (bug 5874).

The binary linked cleanly but crashed (exit=-11) on a two-line program
because mojo_read_type_tag_safe allowed a pointer-shaped char* to
produce a tag, which then crashed inside mojo_dict_key_for.
The fix is in runtime/fire_runtime.c; this test verifies the
layer1-shim that links the real runtime passes cleanly.
"""
import subprocess, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_coro_runtime import TESTS, _run, BACKENDS

def test_layer1_shim_no_sigsegv():
    # layer1-shim links the real fire_runtime.c; before the tag-range
    # fix it crashed with EXC_BAD_ACCESS / SIGSEGV on a 5-char string.
    for entry in TESTS:
        if entry[0] == 'layer1-shim':
            for backend in BACKENDS:
                for opt in ('-O0', '-O2'):
                    ok, msg = _run(entry[0], entry[1], entry[2], backend,
                                   opt, '.')
                    assert ok, f"layer1-shim {backend} {opt} failed: {msg}"
    print("PASS regression pin: layer1-shim survives tag-reader fix")

if __name__ == '__main__':
    test_layer1_shim_no_sigsegv()
