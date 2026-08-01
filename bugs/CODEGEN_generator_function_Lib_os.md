# CODEGEN_generator_function: Lib/os.py

## Status
**STILL FAILING** (2026-07-31) — generator .cpp: `_DeprecatedGenericAlias`/`_CallableType`/`_PlaceholderType` not declared (82 errors total). Previous `sys`/`fork`/`execv`/`waitpid` errors fixed by commits da1a05d-6076f23. Remaining errors are from opaque-class globals struct not emitting forward declarations for typing-related classes.

## Build error

```
error: '_DeprecatedGenericAlias' does not name a type
error: '_CallableType' does not name a type
error: '_PlaceholderType' does not name a type
```

## Fixed errors (this session)
- `fork` implicit-decl → fixed (`_NEEDS_SELF_EXTERN` + `_LIBC_SIGS`)
- `execv` incompatible-args → fixed (`_KNOWN_SIGS` arg-padding)
- `waitpid` arg-count → fixed (`_KNOWN_SIGS` arg-padding)
- `execve` conflicting-types → fixed (`_KNOWN_SIGS`)
- `sys` not declared → fixed (package import scan)

Source file: `/Users/mrs/net/Python-3.14.6/Lib/os.py`
