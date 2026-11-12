# DIAGNOSTICS missing-validation part 5: `where` clauses resolve module `alias` constants

Class: **mid** (this doc lives in `bugs/mid/`). The evaluation is already
there — the fix is supplying the alias bindings without letting an ordinary
module-level assignment be treated as a compile-time constant.

Parent: `bugs/hard/DIAGNOSTICS_missing_validation_modular.md` (the "local
`alias` bindings not always visible" remainder). Plan:
`docs/diagnostics-missing-validation-plan.md` §1.

## Goal

A `where` clause over a concrete type argument must be decided even when the
clause names a module `alias`, so a provably-false clause is rejected instead
of silently accepted. Today `alias LIMIT = 2` followed by
`def f[x: Int]() where x < LIMIT` and `f[5]()` compiles with no diagnostic.

## Current state (measured 2026-11-12)

- The program above compiles (no diagnostic) through
  `compile_to_gimple(..., do_imports=True)`; `grep`-measured, the same is true
  for a struct `where x < LIMIT` clause.
- `elaborate.check_where_clauses` (~666) does receive the module source: the
  in-TU pre-pass calls `elaborate.check_bounds(module_src, tmpl, targs)`
  (`mojo/backend_gimple/elab_intu.py`, ~3905) with `module_src` non-empty, and
  the probe printed `module_src_len=81`. A second call from the `.o` route
  passes `''` (`monomorphize.py`, ~994) and must stay conservative.
- The missing piece is `_where_bindings(targs)` (~652): it adds a concrete
  integer or `True`/`False` type argument and nothing else. A clause naming
  `LIMIT` therefore folds to `CONST_UNKNOWN` and is accepted.
- Parser note: this tree's `alias NAME = <literal>` is not a distinct AST
  node — `alias` parses as a no-op `ExprStmt(IdentExpr('alias'))` and the
  binding as an ordinary `AssignStmt`. The AST alone therefore cannot tell a
  module `alias` from a module-level assignment, and a module assignment must
  not be folded as a constant.

## Scope

1. Add `_module_alias_bindings(module_src)` beside `_where_bindings`: scan the
   module text for a top-level `alias NAME = <literal>` line and fold the
   literal with `mojo.middle.comptime.eval_const` (Int/Bool/String and, once
   part 4 lands, Float). Take the last binding for a repeated name, and ignore
   anything that does not fold (an alias to an expression stays unknown).
2. `check_where_clauses` must call `_where_bindings(targs)` and then overlay
   the module alias bindings, with the type-argument bindings winning on a name
   collision (a clause parameter shadows a module alias). Pass `module_src` in;
   an empty `module_src` contributes no aliases, which keeps the
   `monomorphize` call site exactly as conservative as it is now.
3. Do not widen this into folding arbitrary module-level `AssignStmt`s, and do
   not touch the DType/type-equality regex checks in
   `_check_where_text_predicates`: they remain the only check when the folder
   is still undecided.
4. No new message text: a false clause without a message uses the existing
   `requirement '<clause>' is not satisfied`, and `where (cond, "msg")` uses
   the existing message.

## Acceptance

- `alias LIMIT = 2` + `def f[x: Int]() where x < LIMIT` rejects `f[5]()` with
  `requirement 'x < LIMIT' is not satisfied`; `f[1]()` compiles.
- `where (x < LIMIT, "too big")` rejects with `too big`.
- A struct `where x < LIMIT` clause behaves the same at instantiation.
- A clause naming an alias whose value is not a foldable literal stays
  accepted (undecided, not a false positive).
- A module-level mutable assignment with the same name is not used as a
  constant (write a control that would fail if it were).
- Integer/Bool literal `where` clauses and the DType predicates keep their
  current behaviour.

## Done when

Add `test_where_alias_diagnostic.py` beside `test_where_message_diagnostic.py`
(do NOT register it in `tools/suite.py`) and run exactly:

    python3 tools/memslot.py --gb 8 --label where-alias -- python3 test_where_alias_diagnostic.py

The test uses `diagnostic_build.build_refusal` for the call-site cases (the
generic must be instantiated) and keeps every source local — no stdlib import.

## Not in this part

`where` clauses that depend on a generic's own non-concrete parameter, and
alias visibility in the interpreter/formal backends. No test registration.

## Status

- **Open.**
