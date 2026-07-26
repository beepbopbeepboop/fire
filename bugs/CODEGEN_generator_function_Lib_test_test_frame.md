# CODEGEN_generator_function: Lib/test/test_frame.py

## Status
**TIMEOUT resolved** (2026-07-25) - the hang was caused by the multi-name
import a, b, c binding bug (fixed in commit 52ea4d7). The file no longer
times out, but fails with a codegen limitation.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_frame.py
