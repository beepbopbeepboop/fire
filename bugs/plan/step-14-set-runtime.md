# plan/step-14: a set runtime on both backends

**Source:** `bugs/FORMAL_set_value_model.md` (top Status, 2026-10-12).
**Master plan:** `doc/finish-formal.md` §"Step 14".

## Goal

A set lowers as a list, and only the word-canonical half dedups at compile time.
A set whose elements are not word-canonical (a name, a call, a subscript) and a
set comprehension still keep their repeats, so `{x, x, 2}` reports 3 where
CPython reports 2 and a walk sums 10 where CPython sums 6. The doc's durable fix
is a set RUNTIME on both backends — a "run-time-length container" capability.
`add` is refused and `print` is refused for the same missing storage.

## What to add

- A set runtime: a container representation that establishes distinctness at run
  time (hash table or scan), with a documented iteration order. The doc's one
  value-model disagreement is insertion order (this path) vs CPython's hash
  order; whatever is chosen is stated and pinned.
- Extend `set_literal_distinct_elements` from the compile-time word-canonical
  case to the runtime case, and route a set comprehension through it.
- `add`, `print`, and x86-64 set-emitter parity with arm64's existing
  `_emit_set_*` helpers.
- Delete `tools/formal_fuzz.py`'s `KNOWN_DIVERGENCES['set_order']` row **in the
  same commit** the model changes, per the doc, and say what the new order is.
- Differential pins modelled on the doc's three existing cases
  (`s_len_dups`, `s_walk_dups`, `s_len_dups_str`).

## Structure-only rule

The runtime is one capability; scaffold its model arm and any proof obligation
with `sorry` (ledger). Changing iteration order means deleting the neutraliser
row in the same commit.

## Files

`formal/model/values.py`, `formal/arm64_codegen.py`,
`formal/x86_64_codegen.py`, `runtime/`, `test_formal_container_methods.py`,
`tools/formal_fuzz.py`, ledger.

## Verification

`test_formal_container_methods.py` set group (both backends, differential);
`tools/formal_fuzz.py --mix sets`; `test_formal_proof_gaps.py`.

## Done when

- [ ] `{x, x, 2}` is 2 and a walk sums 6, both backends
- [ ] `add` works or refuses with the runtime named
- [ ] `set_order` row deleted and the new order pinned
- [ ] x86-64 has a set emitter or `set_union_refusal` is replaced by a real
      reason

## Dependencies

step-01 (holes only).
