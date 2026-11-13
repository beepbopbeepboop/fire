# DIAGNOSTICS binding deferrals part 2 — part 1: type-argument bound evidence

Part 1 of 2 of `bugs/hard/DIAGNOSTICS_binding_deferrals-part2.md` (itself part 2
of `bugs/hard/DIAGNOSTICS_binding_deferrals.md`). Part 2 is
`DIAGNOSTICS_binding_deferrals-part2-part2.md`: it consumes the decision this
part returns and turns it into a declaration-time diagnostic.

## Class
mid. One conservative semantic decision in `elaborate.py`, with a pure unit
test. No diagnostic plumbing yet.

## Current state (measured 2026-11-13)

Both parts serve this fixture:

```mojo
struct CondCopyable[T: Movable & Deinitable](
    Copyable where conforms_to(T, Copyable), Movable
):
    var value: Self.T


struct NeedsCopyablePos[T: Copyable, n: Int](Movable where False) where n > 0:
    pass
```

- `elaborate.parse_bounds(extract_struct_source(src, 'NeedsCopyablePos'))` is
  `{'T': 'Copyable', 'n': 'Int'}`; for `CondCopyable` it is
  `{'T': 'Movable & Deinitable'}`.
- The parser records the conditional base on the AST as
  `bases=['Copyable', 'Movable']` and
  `base_constraints=[('Copyable', 'conforms_to(T, Copyable)'), ('Movable', '')]`.
  `_where_conformance_bases` therefore drops the `where` text and
  `conforms_to('CondCopyable', 'Copyable', ...)` answers True unconditionally.
- `check_conformance(src, 'CondCopyable[U]', 'Copyable')` returns `(True, [])`,
  but not because the conformance is proven: `Copyable` is not declared as a
  `trait` in the module, so `_extract_trait_def` returns None and the function
  takes its "unknown trait, accept" exit. It cannot decide this case and is not
  the primitive.
- `_constraint_implied_for_evidence('conforms_to(U, Copyable)',
  'conforms_to(U, Movable) and conforms_to(U, Deinitable)', src, {})` returns
  True on this tree (measured 2026-11-13). The atom-level comparison is right
  (`_constraint_implies_text` -> `_conforms_implies` -> False); the value is
  lost in the later undecided fall-through, which ends
  `return False if st2 == CONST_FALSE else True`. This part adds a `strict`
  switch to that one function rather than a second evidence evaluator.

## Goal

Add to `elaborate.py`:

```python
def type_arg_bound_evidence(module_src, template_src, param, arg, fn_bounds):
    """'proven' | 'unproven' | 'unknown' for ARG satisfying PARAM's bound."""
```

`fn_bounds` is the enclosing function's type-parameter facts,
`{param_name: {trait, ...}}` — the shape `_fn_known_bounds` already returns
(`{'U': {'Movable', 'Deinitable'}}` for the signature in part 2). `arg` is one
supplied type argument as source text (`'CondCopyable[U]'`, `'Int'`, `'U'`).

and a `strict=False` keyword on `_constraint_implied_for_evidence`:

- default behaviour unchanged, so `check_conformance`'s existing callers keep
  their accept-on-undecided result;
- `strict=True` runs the atom comparison first and, when BOTH the assumption
  and the clause parse to `_constraint_atoms`, returns that verdict (`True` or
  `False`) instead of falling through to the conservative accept. When either
  side does not parse, it keeps falling through, so unknown stays accepted.

### Decision rules (each one is pinned by the test)

1. No bound for `param`, or a bound that is not a trait-like name (a value
   parameter such as `n: Int`) -> `'unknown'`. The caller accepts it.
2. A bound may be a conjunction (`T: Movable & Deinitable`). Evaluate each
   conjunct: any `'unproven'` -> `'unproven'`; all `'proven'` -> `'proven'`;
   otherwise `'unknown'`.
3. `arg` is exactly a key in `fn_bounds`: the bound is `'proven'` when the
   trait is in `fn_bounds[arg]`, `'unproven'` otherwise.
4. `arg`'s base is a struct declared in `module_src`: inspect its
   `base_constraints` (not only `bases`).
   - A direct base equal to the trait with an empty `where` text -> `'proven'`.
   - A conditional direct base: substitute the struct's bracket parameters from
     `arg`'s arguments, build the assumption text from `fn_bounds`
     (`' and '.join('conforms_to(P, T)' ...)`), and call
     `_constraint_implied_for_evidence(where_text, assumption, module_src,
     bindings, strict=True)`: True -> `'proven'`, False -> `'unproven'`.
   - If the `where` text, after substitution, names a subject that is neither a
     key in `fn_bounds` nor a struct declared in `module_src` (e.g.
     `CondCopyable[Int]` -> `conforms_to(Int, Copyable)`), return `'unknown'`:
     the checker cannot inspect that subject, so it must not report.
   - If the trait is only reachable through an ancestor, resolve it through
     `_where_conformance_bases` + `_ancestors_with_paths` (unconditional in the
     current model); if no path exists, `'unknown'` (Copyable/Movable are
     derived from fields, so absence is not evidence of non-conformance).
5. `arg`'s base is not a struct declared in `module_src` (a builtin, an
   imported/precompiled struct, or a plain identifier): `'unknown'`. This is
   the "do not start rejecting imported or stdlib types on absence of evidence"
   rule.

This part changes no user-visible behaviour. It exists so part 2 has one
decision point to call and one test that pins the conservative boundaries.

## Acceptance

With the fixture above (`src`), `needs_tmpl =
elaborate.extract_struct_source(src, 'NeedsCopyablePos')`:

- `type_arg_bound_evidence(src, needs_tmpl, 'T', 'CondCopyable[U]',
  {'U': {'Movable', 'Deinitable'}}) == 'unproven'`
- the same call with `{'U': {'Movable', 'Deinitable', 'Copyable'}}` ->
  `'proven'`
- `type_arg_bound_evidence(src, needs_tmpl, 'T', 'U', {'U': {'Copyable'}}) ==
  'proven'`
- `type_arg_bound_evidence(src, needs_tmpl, 'T', 'Int', {}) == 'unknown'`
- `type_arg_bound_evidence(src, needs_tmpl, 'T', 'CondCopyable[Int]', {}) ==
  'unknown'`
- `type_arg_bound_evidence(src, needs_tmpl, 'T', 'CondCopyable[U]', {}) ==
  'unproven'` (a generic `U` with no `Copyable` bound)
- `type_arg_bound_evidence(src, needs_tmpl, 'n', '1', {}) == 'unknown'`
- `_constraint_implied_for_evidence('conforms_to(U, Copyable)',
  'conforms_to(U, Movable)', src, {}, strict=True) is False`, and the
  `'conforms_to(U, Copyable)'` assumption is True.

`python3 test_binding_deferral_diagnostic.py` still prints `ok` (its `__main__`
does not yet include the unproven-signature test; that is part 2's work).

## Done when

File: `test_binding_evidence.py` (repo root; created by this part, modelled on
the pure-parser tests in `test_binding_deferral_diagnostic.py`).

Command: `python3 test_binding_evidence.py`

It prints `ok` and exits 0. It parses and decides only — no compilation — so it
needs no memslot wrapper and is cheap enough for the fast tier.

## Status

- Open. Part 2 depends on the `type_arg_bound_evidence` contract above.
