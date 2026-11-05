#!/usr/bin/env python3
"""Regress the mojo->fire rename fallout in test_mixed_cpp_link.py (bug:UNTESTED)."""
import sys, importlib.util
spec = importlib.util.spec_from_file_location("t", "test_mixed_cpp_link.py")
mod = importlib.util.module_from_spec(spec)
# Before fix this raised NameError: name 'mojo' is not defined
# inside test_link_executable_default_still_gcc because it referenced mojo._GCC_BIN
try:
    spec.loader.exec_module(mod)
    mod.test_link_executable_default_still_gcc()
    print("PASS regression: fire references resolved, no NameError")
    sys.exit(0)
except Exception as e:
    print("FAIL regression:", e)
    sys.exit(1)
