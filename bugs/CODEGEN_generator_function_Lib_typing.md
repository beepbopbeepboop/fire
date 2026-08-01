# CODEGEN_generator_function: Lib/typing.py

## Status
**STILL FAILING** (2026-07-31) — generator .cpp: `_DeprecatedGenericAlias`/`_CallableType`/`_PlaceholderType` not declared (15 errors total). Previous `Unpack` error fixed by package import scan. Remaining errors are from opaque-class globals struct not emitting forward declarations for typing-related classes.

## Build error

```
error: '_DeprecatedGenericAlias' does not name a type
error: '_CallableType' does not name a type
error: '_PlaceholderType' does not name a type
```

## Fixed errors (this session)
- `Unpack` not declared → fixed (package import scan)

Source file: `/Users/mrs/net/Python-3.14.6/Lib/typing.py`
