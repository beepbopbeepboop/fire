# CODEGEN_generator_function: Lib/tarfile.py

## Status (updated 2026-08-06)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'TarFile'` .cpp error no longer reproduces. `tarfile.py` has
3 of its own generator sites (`getmembers`-adjacent `yield from
self.members`/`yield tarinfo` x2, lines 2999/3011/3024) — none appear in
the current error list, and `MOJO_DEBUG=1` shows no "not eligible"
refusal for any of them: tarfile.py's own generator bodies now appear to
compile cleanly through the coroutine path.

**Classification: NOT a generator-codegen-cluster failure anymore** —
this is `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_
defined.md` (5th confirmed occurrence in this cluster):

```
/Users/mrs/net/Python-3.14.6/Lib/tarfile.py:312:29: error: invalid use of undefined type 'struct _genericpath_toplev'
```
Not investigated further here — out of scope for this generator-codegen
cluster; see the hard-bug doc.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/tarfile.py
