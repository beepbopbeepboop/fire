# CODEGEN_generator_function: Lib/test/crashers/gc_inspection.py

## Status (updated 2026-08-07)

**Classification bug PARTIALLY FIXED** (`bugs/hard/CODEGEN_generator_
non_plain_assignment_target_refused.md`, task #150) — `[tup] = [...]`
no longer refuses at the eligibility gate (`AssignStmt`'s target-shape
check now accepts `ListExpr`, not just `TupleExpr`). Confirmed:
`MOJO_DEBUG=1` no longer shows ANY "not eligible" refusal for `g`; it
proceeds to full `.cpp` generation.

**`g` STILL does not compile end-to-end**, for two OTHER, unrelated,
pre-existing reasons in the same function body (confirmed via a direct
g++ compile of the generated `.cpp`):
- `marker = object()` — the builtin `object()` constructor call isn't
  supported by this narrow generator-body model at all — g++: `'object'
  was not declared in this scope`.
- `[tup] = [x for x in gc.get_referrers(marker) if type(x) is tuple]`
  — the RHS is a comprehension, which `_cpp_expr`'s `Comprehension`
  case lowers to an always-EMPTY `mojo_list_new()` stub (a real,
  documented, honest simplification elsewhere in this codegen) — but
  the unpack-target lowering then tries to SUBSCRIPT that `MojoList`
  value directly (`(mojo_list_new())[0]`), which isn't valid (a
  `MojoList` needs the runtime's own accessor, not `operator[]`) — a
  separate, pre-existing gap in how the tuple/list-unpack branch
  handles a non-call RHS, not something this pass's fix introduced
  (confirmed via `git stash`: the identical gap already existed for a
  `TupleExpr` target with a literal/comprehension RHS on unmodified
  code).

Both gaps predate this fix and are unrelated to it; `g`'s overall
compile outcome is unchanged (still fails, same as before) — the
"non-plain assignment target" refusal this doc originally reported is
simply no longer the (first) blocker. See the hard-bug doc's own
"Verification" section for the fuller analysis.

## Status (updated 2026-08-06, superseded above)

**STILL FAILING**, confirmed reproducing against current master
(`2b0c4c5`) with a specific, now fully root-caused reason.

```
$ MOJO_DEBUG=1 python3 mojo.py build /Users/mrs/net/Python-3.14.6/Lib/test/crashers/gc_inspection.py
[gimple_codegen] generator 'g' not eligible for C++ coroutine path, falling back to honest refusal: only a plain identifier assignment target is supported
Error building: cannot compile module: function(s) g (generator function(s), ...) — falling back to interpreting this module from source instead
```

**Classification: `bugs/hard/CODEGEN_generator_non_plain_assignment_
target_refused.md`** (this file is the doc's primary confirmed
occurrence). `g`'s body:
```python
def g():
    marker = object()
    yield marker
    [tup] = [x for x in gc.get_referrers(marker) if type(x) is tuple]
    print(tup)
    print(tup[1])
```
`[tup] = [...]` is a list-pattern destructuring assignment — the
coroutine codegen's generator-body assignment lowering only supports a
bare identifier target, refusing any other shape (tuple/list unpack,
subscript, attribute) wholesale. See the hard-bug doc for full root
cause and fix-scope notes (2 more independent confirmations found
elsewhere in this cluster's pass).

Not fixed here — narrow-looking but inside the coroutine `.cpp`
statement-lowering path, which this task's guidance flags as warranting
its own dedicated verification pass.

## Build error


Source file: /Users/mrs/net/Python-3.14.6/Lib/test/crashers/gc_inspection.py
