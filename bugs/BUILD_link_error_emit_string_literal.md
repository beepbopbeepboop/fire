# BUILD_link_error_emit_string_literal

## Summary
Self-build of fire fails at link stage with:

```
Undefined symbols for architecture arm64:
  "_GimpleGen__emit_string_literal", referenced from:
      _mojo_backend_gimple_emit_funcs__gen_stmt_ComptimeForStmt_ba2192 in fire.o
ld: symbol(s) not found for architecture arm64
```

## Root cause
`mojo/backend_gimple/emit_funcs.py` calls `gen._emit_string_literal(_v)` in four places inside
`gen_stmt_ComptimeForStmt` (to emit string-valued comptime for-loop targets), but the method
`_emit_string_literal` was never defined on `GimpleGen` (nor in any emit_* module). The method
name is referenced as a mangled C symbol during self-build, producing the link error.

## Fix
Added `_emit_string_literal` to `GimpleGen` (gimple_codegen.py) which escapes the value via
`_c_escape` and interns it through `_intern_string`, mirroring the established string-literal
pattern used elsewhere (e.g. emit_exprs.py lines 335-339).

## Files
- gimple_codegen.py
- mojo/backend_gimple/emit_funcs.py (call sites)

## Status
Fixed.