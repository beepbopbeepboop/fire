# CODEGEN_generator_function: Lib/shelve.py

## Status (updated 2026-08-06)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `request for member 'keys'` .cpp error no longer reproduces.
`shelve.py` has one generator, `Shelf.__iter__` (`yield
k.decode(self.keyencoding)`, line 96) — it does NOT appear anywhere in
the current error list (1189 errors total, all in OTHER transitively-
imported files), and `MOJO_DEBUG=1` shows no "not eligible" refusal
naming it: `Shelf.__iter__` now appears to compile cleanly through the
coroutine path.

**Classification: NOT a generator-codegen-cluster failure anymore.**
`shelve.py` transitively pulls in a very large dependency closure (via
`import dbm`, which tries multiple backend modules) and the current
build fails entirely on hundreds of errors in THOSE other files —
dominant patterns: `expected expression before 'int64_t'`/`'char'`/
`'int'` (108/87/66 occurrences), `invalid use of undefined type 'struct
_locale_toplev'`/`'struct _threading_toplev'` (the same recurring
"undefined module-namespace pseudo-struct" pattern seen in this
session's `glob.py`/`modulefinder.py`/`mailbox.py` re-diagnoses, here
for `locale`/`threading` instead of `subprocess`/`genericpath`), and
`expected declaration specifiers or '...' before 'Signature'`/
`'Parameter'`/`'partial'` (looks like the SAME malformed-declaration
pattern seen in `codecs.py`'s current re-diagnosis). None of these
implicate shelve.py's own code or its generator. Not investigated
further — entirely out of scope for this generator-codegen cluster.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/shelve.py
