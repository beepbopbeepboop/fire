# DIAGNOSTICS missing-validation part 2: fold `conforms_to(...)` in comptime conditions

Class: **mid** (this doc lives in `bugs/mid/`). It needs a conformance witness
that walks the declared trait bases, plus one evaluation seam shared by the
gimple comptime wrapper and `elaborate.check_where_clauses`.

Parent: `bugs/hard/DIAGNOSTICS_missing_validation_modular.md`. Plan:
`docs/diagnostics-missing-validation-plan.md` §1/§2 (the
generic/trait-reflection remainder).

## Goal

A `comptime assert`, `constrained`, or `where` clause whose condition is
`conforms_to(T, Trait)` must be decided at compile time when `T` is a concrete
type. A provably-false condition must produce the existing diagnostic
(`comptime assertion failed: <msg>` / `constraint failed: <msg>` /
`requirement '<clause>' is not satisfied`). Today all three forms silently
accept both the false and the true spelling.

## Current state (measured 2026-11-12)

- `def f[T: AnyType](): comptime assert conforms_to(T, Tr), "no"` called as
  `f[No]()` with `trait Tr: pass` / `struct No: pass` compiles with no
  diagnostic; the same with `f[Yes]()` where `struct Yes(Tr): pass` also
  compiles (correct, but by accident — nothing is evaluated).
- `constrained[conforms_to(T, Tr), "no"]()` with a non-conforming `T` also
  compiles.
- `def f[T: AnyType]() where conforms_to(T, Tr)` called with `No` compiles.
- `fire_compiler.py:60` has a runtime shim `def conforms_to(T, Trait): return
  True`; it is a Python-level fallback, not part of the constant folder, so it
  neither proves nor disproves a condition.
- `mojo/middle/comptime.py::eval_const` (`~438`), `_const_foldable` (`~868`),
  `eval_const_bool_state` (`~1001`) and `eval_const_call` (`~1133`) have no
  `conforms_to` case. The existing `call_hook` seam cannot serve it: it folds a
  call by running it with integer arguments, and `conforms_to`'s arguments are
  a type and a trait name, not values.

## Scope

1. **One conformance witness, not two.** Add a small resolver that answers
   `conforms_to(<TypeExpr>, <TraitNameExpr>)` from a `{struct_name: [bases]}`
   map, transitively (a struct conforms to a listed base and to that base's
   ancestors), returning `None` when either name is unresolved. The gimple path
   already has the map as `gen._struct_bases`
   (`mojo/backend_gimple/module_gen.py`, ~7006); `check_where_clauses`
   (`elaborate.py`, ~666) can build the same map from its `module_src`
   (`StructDef.bases`, transitively) and reuse the resolver.
2. **Evaluation seam.** Thread an optional conformance-predicate argument
   through `eval_const` / `eval_const_bool` / `eval_const_bool_state` /
   `_const_foldable` (a new keyword parameter; default `None` means "unknown",
   so every existing caller keeps today's behaviour). A `CallExpr` whose callee
   is `IdentExpr('conforms_to')`, with exactly two positional args and no
   kwargs, folds to the predicate's `True`/`False`; `not conforms_to(...)`
   follows from the existing `UnaryOp('not')` fold. Supply the gimple predicate
   from `_eval_const_bool_state`/`_eval_const_bool`/`_eval_const_int` in
   `mojo/backend_gimple/emit_infra.py` (~7850), and the `elaborate` one from
   `check_where_clauses`.
3. Do not invent a second conformance rule: extend/mirror
   `elaborate.check_conformance` only for the method-requirement half, and use
   the declared-base walk for the declaration half. An unknown trait or type
   stays `None` (accepted conservatively), as elsewhere in the folder.
4. The message is the caller's existing one. No new text.

## Acceptance

- A false `conforms_to` in `comptime assert`, `constrained[...]`, and a
  function `where` clause is rejected with the caller's normal message.
- `conforms_to` on a conforming type (directly listed or inherited) compiles.
- `not conforms_to(...)` on a conforming type is rejected by `comptime assert`
  and accepted on a non-conforming type.
- An unresolved type/trait (e.g. a bare `AnyType` parameter in a
  non-instantiated body) stays undecided and does not produce a diagnostic.
- `comptime assert True/False` and the DType predicates keep their current
  behaviour.

## Done when

Add `test_conforms_to_condition_diagnostic.py` beside the other
`test_*_diagnostic.py` files (do NOT register it in `tools/suite.py`) and run
exactly:

    python3 tools/memslot.py --gb 8 --label conforms-to-condition -- python3 test_conforms_to_condition_diagnostic.py

The test uses locally declared traits/structs (no stdlib import), covers the
three condition forms plus the `not`/positive/undecided controls, and builds
the `where` case through `diagnostic_build.build_refusal` so the instantiated
generic is exercised.

## Not in this part

Conditional conformance declarations and method-requirement evidence are
`bugs/mid/DIAGNOSTICS_trait_conformance-part1.md` and
`-part2.md`; this part only makes the `conforms_to` *condition* fold. No test
registration.

## Status

- **Open.**
