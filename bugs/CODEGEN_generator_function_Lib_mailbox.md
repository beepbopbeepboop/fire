# CODEGEN_generator_function: Lib/mailbox.py

## Status (updated 2026-08-10, later same session — re-verified the "struct _X_toplev" pattern task; a related-but-distinct variant found+fixed)

Investigated this session's cross-cutting task tracing a recurring
`invalid use of undefined type 'struct _<modname>_toplev'` GCC error
across 9 bug docs (this file included, per the 2026-08-06 entry below).
Confirmed via a fresh `python3 mojo.py build` rebuild: this file has
**zero** occurrences of that exact error — it was already fully fixed
by the two already-landed mechanism-1/mechanism-2 fixes referenced
below (`bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_
defined.md`, deleted as resolved), consistent with this doc's own
2026-08-07 note. Not this file's live blocker; no re-classification
needed.

While tracing the pattern's mechanism, found and fixed one closely
related, previously-undocumented residual bug in the same struct-
family area: `_gen_struct_method`/`_gen_lifted_closure` (gimple_
codegen.py) never set `self._current_module_ctx`, so a `global`-
statement write inside a class method (or a closure nested in one)
compiled as the FIRST thing in its module's own recursive compile
inherited stale/default module context and routed the write to the
wrong module's globals struct (typing.py's `_LazyAnnotationLib.
__getattr__` was the confirmed repro: `struct '_root_toplev' has no
member named '_lazy_annotationlib'`, since the write landed on the
ENTRY module's struct instead of typing's own). Also fixed a related
`_safe_coerce_emit` gap (`is_field` only recognized `->`-accessed
struct fields, not plain `.`-accessed ones, causing an invalid
combined cast+store GIMPLE statement once the write-target routing
above was corrected). Full details/verification in `bugs/hard/COMPILE_
FAIL_module_toplev_struct_never_fully_defined.md`'s history and this
session's commit message.

Effect on this file: total build error count dropped 651 -> 649 (2
fewer — the fixed bug's own signature) via a fresh rebuild; the
tuple-yield-then-`mojo_cstr_slice` blocker described below is
unaffected and remains this file's real blocker. No reclassification.

## Status (updated 2026-08-10 — tuple-valued yield now FIXED; a separate, pre-existing gap now blocks)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes` — boxes a tuple's elements into a real `MojoList *` at the
yield site). Confirmed via an isolated compile: `Mailbox.iteritems`'s
`yield (key, value)` (line 129) is no longer refused. Its OWN
`co_yield`/boxing text is syntactically valid, correctly heterogeneous
C++ — `key` boxed via `mojo_list_append_int`, `value` (correctly
inferred `char *`, from an earlier `mojo_cstr_slice` assignment) via
`mojo_list_append_str` — no g++ errors on those lines.

**mailbox.py still does not build**, blocked by an INDEPENDENT,
pre-existing gap one statement earlier in the SAME function:
`value = mojo_cstr_slice((char *)(self), key, (key) + 1);` — g++:
"forming reference to void" (a call-signature/return-type mismatch for
`mojo_cstr_slice` in the coroutine-body expression lowering). Unrelated
to tuple-yield. Matches this doc's own 2026-08-07 status, which already
predicted the next blocker would be the previously-documented
`mojo_open_file`-arity/type-mismatch cluster once tuple-yield unblocked
`iteritems` — the underlying non-generator issues in that cluster are
plausibly the same family as this `mojo_cstr_slice` finding, not
independently re-verified in full here.

Doc kept open (not deleted) — tuple-yield is no longer this file's
blocker, but the file genuinely still doesn't build.

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
