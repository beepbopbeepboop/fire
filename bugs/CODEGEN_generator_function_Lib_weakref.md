# CODEGEN_generator_function: Lib/weakref.py

## Status (updated 2026-08-23, worktree branch fix/gen-lib-b — the `_cpp_for_stmt` tuple-target gap FIXED; all 8 of weakref.py's own generators now compile; own-code error count 0)

The `for k, wr in self.data.copy().items():` blocker left by the
2026-08-10 entry below is fixed. Three coordinated pieces in the
coroutine-body emitter (commit 53b1aaa):

1. `_cpp_for_stmt`'s tuple-target branch gained a plain-dict case:
   `for k, v in <dict-typed expr>.items():` lowers through the SAME
   runtime protocol the plain-GIMPLE path's tuple branch already uses —
   `mojo_dict_items` builds a MojoList of boxed 2-element sub-lists,
   unpacked per-slot (`mojo_list_get_str` for the key — dict keys are
   always `char *` in this runtime — and `mojo_list_get_int` for the
   value), with the receiver expression evaluated exactly once into a
   cached list local. Previously ANY non-enumerate/non-generator-call
   tuple target fell through to the string-target path and emitted the
   whole comma-joined target as ONE bogus C++ identifier
   (`for (auto k, wr : ...)`, g++ "declaration of 'auto k' has no
   initializer") — exactly this doc's reported failure.
2. `_cpp_for_stmt`'s single-name target path gained `.keys()/
   .values()/.items()` and bare-dict iteration (`for wr in self.data.
   copy():`) via the same helpers, replacing the generic `for (auto x :
   ...)` range-for that cannot compile against opaque pointer types.
3. `_cpp_expr` gained zero-arg `.copy()/.items()/.keys()/.values()` on
   `MojoDict *`-typed receivers (the `.get(...)` case's existing
   siblings), with receiver-type resolution consolidated into a new
   shared `_cpp_receiver_ctype` helper (declared locals, `self.<field>`,
   `cls.<class-attr>`, `<struct-ptr local>.<field>` — the shape that
   makes non-method generators like calendar.py's work too — plus
   zero-arg `.copy()` chains), replacing three previously-inline lookups.

Verified end-to-end, not just eligibility: an isolated
`compile_to_gimple_with_cpp(do_imports=False)` of weakref.py compiles
clean; the emitted C++ shows all five shapes lowering correctly
(`WeakValueDictionary.items/keys/values/itervaluerefs`,
`WeakKeyDictionary.items/keys/values`). A standalone runtime repro
(struct field dict + generator iterating it + consumer loop) compiled
AND ran correctly through both `driver.compile_program` and the inline
builder (`alpha/7/beta/9/got beta/done`).

**weakref.py's own source now contributes ZERO errors** to its whole-
program build; no "not eligible" refusal names any of its own
generators anymore. The build still fails on transitively-imported
files only (traceback.py's `extended_frame_gen` refusal, codecs/
argparse cascade) — out of scope, doc kept open per convention.

Quality gate for the change: `test_gimple.py` 250/250,
`test_module_cache.py` 76/76, `make check-selfhost` clean, stdlib dylib
rebuild 0 skips.

## Status (updated 2026-08-10, later same session — re-verified the "struct _X_toplev" pattern task; a related-but-distinct variant found+fixed)

Investigated this session's cross-cutting task tracing a recurring
`invalid use of undefined type 'struct _<modname>_toplev'` GCC error
across 9 bug docs (this file included, per the 2026-08-06 entry below).
Confirmed via a fresh `python3 mojo.py build` rebuild: this file has
**zero** occurrences of that exact error — already fully fixed by the
mechanism-1/mechanism-2 fixes referenced below (deleted doc, `bugs/
hard/COMPILE_FAIL_module_toplev_struct_never_fully_defined.md`), same
conclusion this doc's own 2026-08-07 status already reached. Not this
file's live blocker.

Fixed one closely related, previously-undocumented residual bug found
while tracing the mechanism: `_gen_struct_method`/`_gen_lifted_closure`
(gimple_codegen.py) never set `self._current_module_ctx`, misrouting a
`global`-statement write inside a class method compiled first in its
module to a DIFFERENT module's globals struct (repro: typing.py's
`_LazyAnnotationLib.__getattr__`). Also fixed a related `_safe_
coerce_emit` gap (`.`-accessed struct-field LHS wasn't recognized,
only `->`-accessed). Full writeup in `bugs/hard/COMPILE_FAIL_module_
toplev_struct_never_fully_defined.md` and this session's commit.

Effect on this file: total build error count dropped 644 -> 642 (this
fix's own signature); the tuple-yield/`_cpp_for_stmt` blocker below is
unaffected and remains this file's real blocker. No reclassification.

## Status (updated 2026-08-10 — tuple-valued yield now FIXED; a separate, pre-existing gap now blocks)

Implemented real tuple-valued-`yield` support this session (see
`gimple_codegen.py`'s `_cpp_yield_tuple`/`_generator_tuple_yield_slot_
ctypes`). Confirmed via an isolated compile: `WeakValueDictionary.
items`/`WeakKeyDictionary.items`'s `yield key, value` sites are no
longer refused, and their own tuple-boxing/`co_yield` text is
syntactically valid C++.

**weakref.py still does not build**, blocked by an INDEPENDENT,
pre-existing gap one statement earlier in the SAME methods:
`for k, wr in self.data.copy().items():` — a plain `for` loop, inside a
coroutine body, over a non-generator call (`dict.items()`), with a
non-`enumerate()` tuple target. `_cpp_for_stmt` only special-cases a
tuple target for `enumerate(...)`; any other tuple-target iterable
(including a plain dict/generator `.items()`-shaped call) falls through
to treating the whole comma-joined target as ONE bogus C++ identifier —
g++: `for (auto k, wr : self->data.copy().items())`, "declaration of
'auto k' has no initializer". Confirmed as the SAME gap independently
found in `calendar.py`'s and `Tools/c-analyzer/c_parser/datafiles.py`'s
own generators (see those docs) — a real, separate, pre-existing
`_cpp_for_stmt` limitation, not the promise/ABI gap this session's fix
targets. Not attempted here. Doc kept open (not deleted).

## Status (re-verified 2026-08-09, unchanged from 2026-08-07)

Fresh from-scratch `python3 mojo.py build /Users/mrs/net/Python-3.14.6/
Lib/weakref.py` on current master reproduces the exact same immediate,
pre-C-emission refusal as 2026-08-07, verbatim:

```
Error building: cannot compile module: function(s) items, items
(generator function(s), contain a `yield`/`yield from`) — this codegen
compiles every function into a single straight-line C function and has
no suspend/resume state-machine transform for generators, ... falling
back to interpreting this module from source instead
```

Root cause confirmed unchanged: `WeakValueDictionary.items`/
`WeakKeyDictionary.items` both `yield key, value` — a 2-tuple.
`gimple_codegen.py`'s `_infer_generator_yield_ctype` (~line 2699-2724)
correctly and deliberately refuses any `TupleExpr`-valued `yield`: the
coroutine-body emitter's C++20 promise type only supports a single
scalar (`int64_t`/`double`/`_Bool`/`char *`) value crossing the
suspend/resume boundary, and there is no tuple/struct-valued promise
codegen at all. This is the SAME "tuple-valued yield" gap that is by
far the single most common finding across this entire
`CODEGEN_generator_function_Lib_*` doc family (dozens of other files
hit the identical `TupleExpr` refusal) — genuinely structural/
feature-sized (would require a real multi-field/boxed promise-type
codegen, not a narrow stub fix), not attempted here per this session's
explicit guidance to leave known structural gaps alone rather than
force a fix. No code change made for this file.

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
