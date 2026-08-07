# CODEGEN_generator_function: Lib/tempfile.py

## Status (updated 2026-08-06)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'_TemporaryFileCloser' does not name a type` .cpp error no
longer reproduces. (Note: this build took over an hour wall-clock —
by far the slowest in this cluster — consistent with, though far more
extreme than, the already-documented `bugs/hard/PERF_nested_module_
compile_walk_ast_quadratic_rescan.md` perf issue.) `tempfile.py`'s own
generator (`_TemporaryFileWrapper.__iter__`, `yield line`, line 556)
does not appear in the current error list and has no "not eligible"
refusal — it appears to compile cleanly.

**Classification: NOT a generator-codegen-cluster failure.** Current
errors (100+) are dominated by two already-cross-referenced patterns:
- `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_defined.md`
  (7th confirmed occurrence — `_threading_toplev`, `_pprint_toplev`,
  `_io_toplev`, `__py_warnings_toplev`, by far the largest count of any
  file in this cluster).
- The recurring `stray '\' in program` / `_classattr_TextWrapper__
  letter` textwrap.py tokenizer bug (5th occurrence, seen previously in
  codecs.py/ipaddress.py/enum.py's re-diagnoses).

Also several `expected identifier before numeric constant` and
`'MojoBoundMethod' has no member named '_closer'`/`request for member
'name' in something not a structure or union` errors, not investigated
further. None implicate tempfile.py's own generator.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/tempfile.py
