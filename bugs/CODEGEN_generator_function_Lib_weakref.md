# CODEGEN_generator_function: Lib/weakref.py

## Status (re-verified 2026-08-07, Track B continuation session — supersedes the "2140 -> 700 errors" investigation below)

A fresh, from-scratch `python3 mojo.py build /Users/mrs/net/Python-3.14.6/
Lib/weakref.py` run does NOT reproduce the 2140/700-error-count shape
described below at all: it fails immediately (both via `driver.
compile_program`'s link mode and via `build_executable`'s do_imports
fallback — same `gen_module` code path either way) with a hard, honest
`RuntimeError` refusal BEFORE any C code is emitted:

```
cannot compile module: function(s) items, items (generator function(s),
contain a `yield`/`yield from`) — this codegen compiles every function
into a single straight-line C function and has no suspend/resume
state-machine transform for generators, ...
```

`MOJO_DEBUG=1` shows the cause: `WeakValueDictionary.items`/
`WeakKeyDictionary.items` both `yield key, value` (a 2-tuple) —
`items: every 'yield' must carry a value, and all values must agree on
one scalar type (int64_t/double/_Bool)`. This is the SAME scalar-only
limitation as `bugs/hard/CODEGEN_generator_struct_typed_param_refused.md`
(task #147) and `bugs/COMPILE_FAIL_Lib_contextlib_request_for_member_
module_in_something_not_a_structure_or_union.md`'s 2026-08-07 update
(non-scalar `__aenter__` return) — the C++20 coroutine codegen only
supports scalar (int64_t/double/_Bool) yield/return values, not
tuples/objects. Confirmed via a minimal standalone repro (a struct
method `yield`ing a 2-tuple hits the identical refusal) and via direct
`git log -S` on the refusal message — this scalar-only restriction
predates this session entirely (Milestone B/C, commits `350bf97`/
`292f853`), not something introduced or regressed recently.

**Root-cause note on the discrepancy with the numbers below**: this
raise happens unconditionally whenever ANY top-level generator/async
function in the ROOT module (not a transitively-imported one) has an
unsupported shape, for BOTH `mojo.py build`'s entry points
(`driver.compile_program`'s link mode AND `build_executable`'s
do_imports=True inline mode both call the same `GimpleGen.gen_module`,
which raises before returning any C text either way) — `relaxed_imports`
(the flag that turns this into a per-function stub-and-continue instead
of a hard raise) is never set True for a ROOT module by any code path
`mojo.py`/`driver.py` actually use. Since `weakref.py`'s own `items()`
generators have unconditionally yielded a 2-tuple since long before this
session, it's unclear how the below investigation's `mojo.py build`
invocation produced 2140/700 "error:" lines rather than this immediate
0-error refusal — not re-diagnosed further (out of time budget), but
the CURRENT, freshly-verified ground truth is: `weakref.py` cannot be
compiled at all right now, blocked entirely on this already-flagged-as-
out-of-scope, feature-sized non-scalar-yield/return limitation. Not
attempted here, consistent with this session's explicit instructions to
leave `CODEGEN_generator_struct_typed_param_refused.md` alone.

## Status (updated 2026-08-07, historical — see above for current ground truth)

New, NOT-yet-fixed finding from a `Lib/subprocess.py`-transitive build
(35 errors attributed to this file): a real, confirmed bug, partially
root-caused but not fixed — see `bugs/hard/CODEGEN_function_scoped_
import_rettype_and_literal_cast_mismatches.md`'s "Not fixed" section
for the full writeup. Two distinct findings:
1. `#line` directives mislabel inherited-mixin-method text (confirmed:
   `_collections_abc.py`'s `Mapping.__eq__`/`.items()`, inherited by
   `WeakValueDictionary`) as if it were `weakref.py`'s own source, at
   line numbers (700s-900s) that don't exist in the real 574-line
   `weakref.py` — a diagnostics-only bug (the actual generated C logic
   looked correct), but confusing enough to make this file's error
   output nearly unreadable without cross-referencing line numbers by
   hand against `_collections_abc.py`.
2. `error: expected declaration specifiers or '...' before 'Parameter'/
   'Signature'` (32 of the 35 errors) — `inspect.Parameter`/`Signature`
   (locally-imported classes, not primitives) appearing as literal,
   unmapped C type names in what looks like a declaration/parameter
   list. Not traced to its exact emission site — ruled out `module_
   loader.py`'s `.mojo`-only text-scan path (wrong file type, and its
   own unknown-type fallback is `int64_t`, not the bare name), so the
   real site is presumably in `gimple_codegen.py`'s own annotation-type
   resolution for a scoped-imported class name; not located precisely
   enough to fix in this pass.

## Status (updated 2026-08-06, unaffected by the above — different transitive graph)

**STILL FAILING**, re-diagnosed against current master (`2b0c4c5`) — the
2026-07-30 `'k' was not declared` .cpp error no longer reproduces.
`weakref.py`'s own 8 generator sites (lines 177/182/196/202/370/376/383,
including a `yield from self.data.copy().values()` delegation) do not
appear in the current error list and have no "not eligible" refusal —
they appear to compile cleanly.

**Classification: NOT a generator-codegen-cluster failure anymore.**
Current errors are both already-cross-referenced patterns:
- `bugs/hard/COMPILE_FAIL_module_toplev_struct_never_fully_defined.md`
  (8th confirmed occurrence — `struct _locale_toplev`).
- The recurring `stray '\' in program` / `_classattr_TextWrapper__
  letter` textwrap.py tokenizer bug (6th occurrence).

Not investigated further — out of scope for this generator-codegen
cluster.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/weakref.py
