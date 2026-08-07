# CODEGEN_generator_function: Lib/ftplib.py

## Status (updated 2026-08-06)

**STILL FAILING**, but re-diagnosed against current master (`2b0c4c5`) —
the 2026-07-30 `.join` .cpp error no longer reproduces. `ftplib.py` has
exactly ONE generator of its own: `FTP.mlsd(self, path="", facts=[])`
(yields `(name, entry)` tuples). It does NOT appear anywhere in the
current error list, and `MOJO_DEBUG=1` shows no "not eligible" refusal
naming it — **`mlsd`'s generator body now appears to compile cleanly
through the coroutine path.**

**Classification: NOT a generator-codegen-cluster failure anymore.**
The one remaining error that's actually inside `ftplib.py` itself:

```
/Users/mrs/net/Python-3.14.6/Lib/ftplib.py:926:7: error: invalid use of void expression
  926 |         print(test.__doc__)
```

This is `test.__doc__` — accessing a plain (non-generator) top-level
function's `__doc__` attribute — a completely unrelated, pre-existing
gap in this codegen's handling of function-object attribute access, not
part of the generator/coroutine codegen path at all. Not investigated
further here (out of scope for this cluster). Once this one unrelated
line is fixed (or the file's `test()` function's use of it is
otherwise worked around), `ftplib.py` looks like it may build cleanly —
worth a quick re-check by whoever picks up the `.__doc__` gap.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/ftplib.py
