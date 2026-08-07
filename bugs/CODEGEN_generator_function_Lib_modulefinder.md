# CODEGEN_generator_function: Lib/modulefinder.py

## Status (updated 2026-08-06)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'dis' was not declared` .cpp error no longer reproduces.
`modulefinder.py` has one generator, `scan_opcodes` (lines 393-403,
`yield "store", (name,)` / `yield "absolute_import", (fromlist, name)` /
`yield "relative_import", (level, fromlist, name)` — a tuple-of-
heterogeneous-arity yields). It does NOT appear anywhere in the current
error list and `MOJO_DEBUG=1` shows no "not eligible" refusal naming it
— `scan_opcodes` now appears to compile cleanly through the coroutine
path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
Every current error is well before the generator (lines 89-343, vs. the
generator at 393+) and is the same recurring pattern seen in
`Lib/glob.py`'s current re-diagnosis:

```
/Users/mrs/net/Python-3.14.6/Lib/modulefinder.py:89:30: error: invalid use of undefined type 'struct _subprocess_toplev'
/Users/mrs/net/Python-3.14.6/Lib/modulefinder.py:282:30: error: invalid use of undefined type 'struct _genericpath_toplev'
/Users/mrs/net/Python-3.14.6/Lib/modulefinder.py:296:1: error: invalid conversion in return statement
```
`struct _subprocess_toplev`/`struct _genericpath_toplev` are opaque
per-module "namespace" pseudo-structs this codegen emits for whole-module
attribute access (e.g. `subprocess.something`) — used here but apparently
never given a matching full definition, a module-attribute-access gap in
the same spirit as (though a different concrete shape from) dyld.py's
already-documented bullet 4 ("module attribute access not threaded into
generator scope"), except this occurs in ORDINARY (non-generator) code,
well outside `scan_opcodes`'s own body. Not investigated further — out
of scope for this generator-codegen cluster; worth a `struct _X_toplev`-
focused non-generator bug report on its own (recurs identically in
`Lib/glob.py`'s current error list too — see that file's bug doc).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/modulefinder.py
