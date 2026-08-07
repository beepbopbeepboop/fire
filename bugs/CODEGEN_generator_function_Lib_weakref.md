# CODEGEN_generator_function: Lib/weakref.py

## Status (updated 2026-08-06)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'k' was not declared` .cpp error no longer reproduces.
`weakref.py`'s own 8 generator sites (lines 177/182/196/202/370/376/383,
including a `yield from self.data.copy().values()` delegation) do not
appear in the current error list and have no "not eligible" refusal —
they appear to compile cleanly.

**Classification: NOT a generator-codegen-cluster failure anymore.**
Current errors are both already-cross-referenced patterns:
- `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_defined.md`
  (8th confirmed occurrence — `struct _locale_toplev`).
- The recurring `stray '\' in program` / `_classattr_TextWrapper__
  letter` textwrap.py tokenizer bug (6th occurrence).

Not investigated further — out of scope for this generator-codegen
cluster.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/weakref.py
