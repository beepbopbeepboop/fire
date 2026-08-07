# CODEGEN_generator_function: Lib/test/test_support.py

## Status (updated 2026-08-07)

Item 1's hard-bug doc (`bugs/hard/CODEGEN_generator_non_plain_
assignment_target_refused.md`, task #150) is now PARTIALLY fixed —
tuple/list-pattern-unpack targets no longer refuse; non-`self`
attribute-assignment targets still do. Re-running `MOJO_DEBUG=1`
against this file's current source no longer shows the "only a plain
identifier assignment target is supported" message at all (nor any
`save_restore_warnings_filters` mention — that name wasn't found in
this checkout's `Lib/test/test_support.py`, possibly moved/renamed
since this doc's original 2026-08-06 pass, or reached via a different
transitively-imported file not independently re-checked here).

Item 3's hard-bug doc (`bugs/hard/CODEGEN_comprehension_return_type_
defaults_int64.md`, task #145) is now ALSO fixed (`_quick_type` gained
a `Comprehension` case) — but this file's own item-3 occurrence was
only ever a SPECULATIVE "same general family" match (a variant
`'component_ref'` GIMPLE-node error, not independently traced to a
confirmed bare-`return`-comprehension shape in this file's own source),
so whether this specific file's item-3 errors are actually gone is not
re-confirmed here.

Item 2 (the `MojoGenerator` incomplete-type error) is unrelated to
either bug and not re-investigated in this pass.

## Status (updated 2026-08-06, superseded above)

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
