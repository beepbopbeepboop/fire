# COMPILE_FAIL: Lib/importlib/_bootstrap_external.py

Source file: `/Users/mrs/net/Python-3.14.6/Lib/importlib/_bootstrap_external.py`

## Status (updated 2026-08-06)

A real, dangerous bug was found and fixed here: `if _MS_WINDOWS: def
_path_join(...): ...(Windows logic)... else: def _path_join(...):
...(POSIX logic)...` always compiled the WINDOWS branch regardless of
platform (silently wrong runtime behavior, not just a compile failure) —
see commit `7014dde` (gen_module's conditional-toplevel-def promotion now
resolves `sys.platform`-derived conditions and picks the actually-correct
branch).

Still failing, for a DIFFERENT, narrower reason:

```
error: assignment to 'int64_t' from 'char *' makes integer from pointer without a cast
```

on the NOW-correctly-selected POSIX branch's own `return path_sep.join(...)`.
An IDENTICAL function body compiles fine when NOT wrapped in a
conditional-toplevel-def (confirmed via a direct standalone repro), so
this is specifically about return-type inference for a function reached
through the conditional-promotion path — not yet root-caused. Also
still has several separate "invalid conversion in gimple call" errors at
lines 960/1190 unrelated to either issue above.

## What a real fix needs

1. Root-cause why a conditionally-promoted function's return type
   doesn't get the same `str.join(...)`-return-type inference an
   identical top-level (non-conditional) function gets — likely a
   pass-ordering issue where return-type inference runs against a stale
   view of `stmts` (before the promotion's `stmts = _replaced`
   reassignment) for this specific code path.
2. Investigate the separate "invalid conversion in gimple call" errors
   at lines 960/1190 (likely unrelated — not yet looked at).
