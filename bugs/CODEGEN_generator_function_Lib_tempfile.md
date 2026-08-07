# CODEGEN_generator_function: Lib/tempfile.py

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild. Still correctly
classified as **NOT a generator-codegen-cluster failure** —
`_TemporaryFileWrapper.__iter__` still shows zero signal of a problem.
The `struct _threading_toplev`/etc. pattern is GONE (fixed by
`bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_defined.md`'s
"mechanism 2" landing, same fix confirmed across several files this
session) and the `stray '\'` textwrap.py tokenizer issue is also gone
from this file's current error list. Remaining errors (13 total, all
in tempfile.py's own non-generator code): repeated `expected identifier
before numeric constant` (lines 64/200/250/376/423, plus 2 more further
in) and `request for member 'name' in something not a structure or
union` (lines 609/668/703), plus one `stray '\'`/`expected ';' before
'_classattr_TextWrapper__letter'` at line 496 (the textwrap.py issue —
apparently not fully gone, just reduced). Not investigated further here
— out of scope for this generator-codegen cluster; the `expected
identifier before numeric constant` repeating at several near-identical
column offsets (24, 23, 17) looks like a real, possibly-narrow parser/
codegen bug (worth a dedicated look by whoever picks up a non-generator
pass on this file) but wasn't traced to a root cause in this session.

## Status (updated 2026-08-06, superseded above — module_toplev pattern since independently fixed)

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
