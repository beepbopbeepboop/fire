# CODEGEN_generator_function: Lib/weakref.py

## Status (updated 2026-08-07)

New, NOT-yet-fixed finding from a `Lib/subprocess.py`-transitive build
(35 errors attributed to this file): a real, confirmed bug, partially
root-caused but not fixed — see `bugs/hard/CODEGEN_function_scoped_
import_rettype_and_literal_cast_mismatches.md`'s "Not fixed" section
for the full writeup. Two distinct findings:
1. `#line` directives mislabel inherited-mixin-method text (confirmed:
   `_collections_abc.py`'s `Mapping.__eq__`/`.items()`, inherited by
   `WeakValueDictionary`) as if it were `weakref.py`'s own source, at
   line numbers (700s-900s) that don't exist in the real 574-line
   `weakref.py` — a diagnostics-only bug (the actual generated C logic
   looked correct), but confusing enough to make this file's error
   output nearly unreadable without cross-referencing line numbers by
   hand against `_collections_abc.py`.
2. `error: expected declaration specifiers or '...' before 'Parameter'/
   'Signature'` (32 of the 35 errors) — `inspect.Parameter`/`Signature`
   (locally-imported classes, not primitives) appearing as literal,
   unmapped C type names in what looks like a declaration/parameter
   list. Not traced to its exact emission site — ruled out `module_
   loader.py`'s `.mojo`-only text-scan path (wrong file type, and its
   own unknown-type fallback is `int64_t`, not the bare name), so the
   real site is presumably in `gimple_codegen.py`'s own annotation-type
   resolution for a scoped-imported class name; not located precisely
   enough to fix in this pass.

## Status (updated 2026-08-06, unaffected by the above — different transitive graph)

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
