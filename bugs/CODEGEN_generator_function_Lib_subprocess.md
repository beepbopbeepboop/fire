# CODEGEN_generator_function: Lib/subprocess.py

## Status (updated 2026-08-06)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `cast from 'Popen*' to 'int'` .cpp error no longer reproduces.
`subprocess.py` has one generator, `Popen.__enter__`-adjacent `yield
to_close` (line 1331) — it does NOT appear in the current error list,
and `MOJO_DEBUG=1` shows no "not eligible" refusal naming it:
subprocess.py's own generator body now appears to compile cleanly
through the coroutine path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
Every current error is `bugs/hard/COMPILE_FAIL_module_toplev_struct_
never_fully_defined.md` — an unrelated, non-generator gap where
`genericpath`/`posixpath` module-attribute access
(`genericpath.something`, `os.path.something` resolving through
`posixpath`) hits an incomplete, never-fully-defined opaque struct:

```
/Users/mrs/net/Python-3.14.6/Lib/subprocess.py:615:29: error: invalid use of undefined type 'struct _genericpath_toplev'
/Users/mrs/net/Python-3.14.6/Lib/subprocess.py:1175:28: error: invalid use of undefined type 'struct _posixpath_toplev'
```
Not investigated further here — out of scope for this generator-codegen
cluster; see the hard-bug doc for the shared root-cause writeup (this
file is one of its 4 confirmed occurrences).

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/subprocess.py
