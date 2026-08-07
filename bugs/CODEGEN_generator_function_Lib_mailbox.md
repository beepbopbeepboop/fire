# CODEGEN_generator_function: Lib/mailbox.py

## Status (updated 2026-08-06)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'Mailbox'` .cpp error no longer reproduces. `mailbox.py` has
5 `yield`/`yield from` sites across several generator methods (lines
113, 129, 456, 680, 2035) — none appear in the current error list, and
`MOJO_DEBUG=1` shows no "not eligible" refusal for any of them: all of
mailbox.py's own generator bodies (including the `yield from
self._toc.keys()` delegation at line 680) now appear to compile cleanly
through the coroutine path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
Every current error is the SAME `struct _subprocess_toplev`/`struct
_genericpath_toplev` "undefined module-namespace pseudo-struct" pattern
already seen in `Lib/glob.py`'s and `Lib/modulefinder.py`'s current
re-diagnoses (this is now the 3rd of my 41 files hitting this exact
signature — worth someone folding into its own non-generator hard-bug
doc once a 4th confirms the pattern):

```
/Users/mrs/net/Python-3.14.6/Lib/mailbox.py:78:28: error: invalid use of undefined type 'struct _subprocess_toplev'
/Users/mrs/net/Python-3.14.6/Lib/mailbox.py:282:30: error: invalid use of undefined type 'struct _genericpath_toplev'
```

Not investigated further — out of scope for this generator-codegen
cluster.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/mailbox.py
