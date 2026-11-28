#!/usr/bin/env python3
"""Fetch and build Mathlib for the proof checker: `make mathlib` runs this.

The launch itself lives in `formal/lean.py::fetch_mathlib`, the one module
allowed to start Lean's toolchain, so the Makefile recipe only calls it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from formal import lean as L  # noqa: E402


if __name__ == "__main__":
    try:
        L.fetch_mathlib()
    except RuntimeError as e:
        print(f"mathlib: {e}", file=sys.stderr)
        sys.exit(1)
