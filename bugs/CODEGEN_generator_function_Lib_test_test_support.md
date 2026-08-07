# CODEGEN_generator_function: Lib/test/test_support.py

## Status (updated 2026-08-06)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'LogCaptureHandler' was not declared` .cpp error no longer
reproduces. `test_support.py`'s own generator (`yield handler`, line 49)
does not appear in the current error list.

**Classification: mixed.**
1. `save_restore_warnings_filters`: `bugs/hard/CODEGEN_generator_non_
   plain_assignment_target_refused.md` (5th confirmed occurrence).
2. **New gap, not yet investigated to full root cause:** `error: invalid
   use of incomplete typedef 'MojoGenerator'` at lines 227/300/320,
   paired each time with `error: expected expression before ';' token`
   at the same line — looks like a generator OBJECT (not yet resolved to
   its concrete per-generator type) being used somewhere its type needs
   to be complete (e.g. a variable declared/dereferenced before the
   specific generator's real type is known). Source context at those
   lines didn't show an obvious generator-related expression in a quick
   read — flagged for a closer look rather than fully traced here.
3. The recurring comprehension/`_quick_type`-family "non-trivial
   conversion in 'component_ref'" pattern at lines 112/159/323/337 (a
   variant error message from the same general family documented in
   `bugs/hard/CODEGEN_comprehension_return_type_defaults_int64.md`, here
   `'component_ref'` instead of `'integer_cst'`/`'var_decl'` — same
   underlying decl/body type-mismatch shape, different specific GIMPLE
   node).

Not fixed here.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/test_support.py
