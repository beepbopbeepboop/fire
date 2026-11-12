# CODEGEN_tagged_generator_mixed_type_step1-part2: document the read side of the tagged box

Class: **easy** (this doc lives in `bugs/`, the easy class).

## Parent

`bugs/hard/CODEGEN_tagged_generator_mixed_type_step1.md` (split), which is
step 1 of `docs/tagged_generator_mixed_type-plan.md`. Part 1 documents the
store side and creates `docs/tagged_generator_mixed_type-box.md`; this part
appends the READ side to the same file. The plan's step 1 names this part's
functions explicitly: `tagged_next_bind_name`, `tagged_for_target_name`,
`_local_bindings` in `mojo/backend_gimple/emit_infra.py`.

## Why this part exists

The read half of step 1's acceptance: the rules that decide whether a
name/operand is a tagged box (and must therefore be read by kind), and the
per-kind readers themselves. These rules are exactly what steps 3-5 of the
plan will change (the read sites, the refusal removal, the regression test),
so they must be documented precisely before those parts start; today the rule
and its safety argument live only in the functions' docstrings.

## Scope

Append the READ sections to `docs/tagged_generator_mixed_type-box.md`
(create it with a header if part 1 has not landed):

1. **The binder census.** `_local_bindings` (`mojo/backend_gimple/emit_infra.py`
   ~3614): every binding of `name` in THIS function's body — the `value`
   expression for a plain `name = ...`, `None` for every other binder form
   (an augmented or multi-assign, a for/with target, a comprehension
   generator, a walrus, an except name, a nested def or a declaration). An
   ambiguous form counts as a binder: an over-count only refuses the
   caller's optimisation, which is the safe direction. Computed on demand
   from `gen._cur_func_body`, cached per `(id(body), name)` in
   `gen._local_bindings_cache` (the body id is in the key because a body swap
   can bypass `_reset_func`).
2. **The per-name rules.** All in `emit_infra.py`, all take `(gen, name)`,
   all answer False for a parameter or an unbound name:
   - `tagged_next_bind_name` (~3688): every binding is a tagged word —
     `next(g)` for one generator local `g` bound exactly once (and not a
     parameter), or a copy of another such name (`_seen` breaks a copy
     cycle);
   - `tagged_for_target_name` (~3824): every binding is a `for name in
     <tagged generator>` target — the count of such loops must equal the
     count of binders, and every loop's iterable must satisfy
     `_tagged_generator_iterable`;
   - `tagged_mixed_name` (~3758): the name is bound to a tagged word
     somewhere AND to plain values elsewhere (so `tagged_next_bind_name`
     answers False for it); cheap exit when the module has no `mixed_slots`
     generator (`gen._generator_api`);
   - `tagged_recv_name` (~3857): every binding is `name = yield`
     (`__mojo_coro_yield_i`);
   - `_tagged_generator_iterable` (~3798): the for-iterable is a call of a
     generator whose `gen._generator_api` entry has `mixed_slots` and
     `value_ctype == 'int64_t'`, directly or through a local bound exactly
     once to that call; `_generator_api` is built before any body is emitted,
     so the answer does not depend on the order of the lowering.
   For each: one sentence for the shape that answers True, one for the shapes
   that answer False, and the safety argument (why the rule cannot classify a
   box-holding local as plain).
3. **The operand rule.** `_is_tagged_box_operand`
   (`mojo/backend_gimple/emit_exprs.py` ~1249): an already-lowered operand is
   a tagged box iff its value is in `_boxed_vals` AND (it is in
   `_tagged_word_vals`, or the source node is an `IdentExpr` whose name
   satisfies `tagged_for_target_name`). Record why a for-target word is in
   `_boxed_vals` but not in `_tagged_word_vals` (the loop stores the box; the
   tag comes from the per-name rule at the use site).
4. **The per-kind readers.** The runtime accessors a consumer of a tagged
   word calls, each with its contract: `mojo_box_int` (unwrap; a double box
   is truncated toward zero — a fresh double box must therefore never be
   passed through it), `mojo_box_word` (unwrap; a double box is KEPT),
   `mojo_box_double`, `mojo_word_is_none` (also true for a NULL `'p'`/`'s'`
   box), `mojo_repr_boxed` (the str() spelling by kind; non-box arm: a
   registered string, an re match, or the plain integer),
   `mojo_cstr_or_int_str` / `mojo_word_cstr_value` (the value-side str
   readers), and the arithmetic dispatch in `emit_exprs.py`:
   `_tagged_unary_neg` (~1263), `_tagged_arith_select` (~4122),
   `_tagged_cmp_select` (~4160) compute BOTH answers and let
   `mojo_float_arith_select` / `mojo_float_cmp_select` choose by operand kind
   (a double box in either operand wins; the result is re-registered tagged).
5. **The refusal as read it.** `MIXED_NAME_NON_INT64_REFUSAL`
   (`emit_infra.py` ~3744) and its two trigger halves in the assignment arm
   of `emit_stmts.py` (~1613-1617): a tagged word stored into a name declared
   non-int, or a non-int64 value stored into a mixed name; what each would do
   without the refusal (str: a bare pointer read as a box — segfault; float:
   a double's bits in an int64 box slot — `1.0`/`0.0`); and that the box
   already carries the `'p'` and `'d'` kinds, which is why step 2's split
   parts lift the refusal (float, str) instead of changing the box format.

No code change. No `tools/suite.py` change. No test change.

## Files

- `docs/tagged_generator_mixed_type-box.md` (append; part 1 owns creation).

Reads only: `mojo/backend_gimple/emit_infra.py`,
`mojo/backend_gimple/emit_exprs.py`, `runtime/fire_runtime.c`.

## Test

The same narrow check as part 1 (its Test section owns the baseline):

    python3 tools/memslot.py --gb 8 --label tgbox-doc -- python3 test_gimple_generator_runner.py

No new failure against the 22-case baseline recorded in
`docs/tagged_generator_mixed_type-box.md` ("Test baseline"), and every
`tagged_for_target_*` case passing.

## Acceptance

- The file's read sections (the five items above) exist.
- The three functions the plan named (`_local_bindings`,
  `tagged_next_bind_name`, `tagged_for_target_name`) are all covered, and
  every symbol named in the sections greps in the cited file.
- Every behavioural claim cites the function/line it was read from, and a
  second reader can confirm it against the code at HEAD.
- The test command ends with no new failure against the baseline.

## Status

Not started. Depends on part 1 only for the doc file's existence (create it
with a header if it is missing when this part starts).
