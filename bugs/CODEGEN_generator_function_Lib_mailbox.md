# CODEGEN_generator_function: Lib/mailbox.py

## Status (updated 2026-08-09 — RECLASSIFIED: real tuple-valued-yield refusal, now the blocking error)

Re-verified against current master (`5ba7d4b`) via a real
`python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/mailbox.py`.
The build now fails immediately, before reaching any GCC-stage error, on
a hard Python-level `RuntimeError` from `gen_module`
(`gimple_codegen.py:30968`):

```
Error building: cannot compile module: function(s) iteritems
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, ...
```

Root cause, confirmed by reading the source: `Mailbox.iteritems`
(mailbox.py:122) does `yield (key, value)` at line 129 — a real
**tuple-valued yield** (parenthesized 2-tuple). This is the same
well-known, already-tracked structural gap as `ipaddress.py`'s
`_find_address_range` (see that bug doc's 2026-08-09 update for the
mechanism: coroutine promises only support a single scalar, and
`_infer_generator_yield_ctype`'s `TupleExpr` branch at
`gimple_codegen.py:2699-2724` now honestly refuses rather than
mis-emitting a broken `co_yield {a, b, c};`). This supersedes the
2026-08-06/07 statuses below — at that time `iteritems` apparently
compiled through the coroutine path without refusal (or wasn't yet
subject to this tightened check); a later session's work (visible in
current `gimple_codegen.py`) made the tuple-yield eligibility check
stricter, so `iteritems` now correctly aborts the whole-module compile
before any of the previously-reported `mojo_open_file`-arity/pointer-
conversion GCC-stage errors are even reached. mailbox.py's other 4
`yield`/`yield from` sites (lines 113, 456, 680, 2035) are all
single-value/delegating, not tuple-valued.

**Classification: matches the tracked "tuple-valued yield" structural
generator-codegen gap** — out of scope for a narrow fix per this task's
guidance. Not attempted here. The previously-noted `mojo_open_file`
arity mismatch and other non-generator GCC-stage errors are no longer
reachable until tuple-yield support (or a source-level workaround)
unblocks the whole module; left undisturbed below for reference.

## Status (updated 2026-08-07)

Re-verified against current master with a real rebuild. The
`struct _subprocess_toplev`/`struct _genericpath_toplev` "undefined
module-namespace pseudo-struct" errors quoted in the 2026-08-06 note
below are GONE (consistent with `bugs/hard/COMPILE_FAIL_module_toplev_
struct_never_fully_defined.md`'s "mechanism 2" fix having since landed).
Confirmed `MOJO_DEBUG=1` still shows NO "not eligible" refusal for any
of mailbox.py's own generators — all 5 `yield`/`yield from` sites still
compile cleanly through the coroutine path, same as before.

The build still fails, now on a large, entirely different batch of
non-generator `.ci` errors (~1300+ error lines, dominated by repeats
across mailbox.py's several near-identical mailbox-format subclasses):
`mojo_open_file` called with 2 args where 1 is expected (mailbox.py's
own `open(path, mode)`-shaped calls vs. this codegen's built-in
`mojo_open_file`'s fixed 1-arg signature), `assignment to 'char *' from
'int64_t'` at many sites in the 1470-1520 range, and repeated
`non-trivial conversion in 'component_ref'`/`type mismatch in
'pointer_diff_expr'` around lines 1299-1455. None of these are inside a
generator body or involve `yield`/coroutine machinery — **still NOT a
generator-codegen-cluster failure** — but this is a materially
different (and much larger) error set than the 2026-08-06 snapshot, so
not re-classified further here; worth a fresh, dedicated non-generator
investigation (starting with the `mojo_open_file` arity mismatch, which
looks like the most tractable/narrow of the batch) rather than folding
into this doc.

## Status (updated 2026-08-06, superseded above — struct_toplev errors since fixed)

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
