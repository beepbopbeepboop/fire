# A `Pointer[Float64]` store of an unestablished-kind value is permitted

**Area:** FORMAL (the pointer value model, stores). **Carried over 2026-11-03** from the augmented `Pointer[Float64]` subscript
store (`p[i] op= v`, now answered on both backends). Originally noted 2026-10-07.

## Symptom

`model.pointer_store_kind_disagreement` returns `None` (permissive) when the
stored value's kind is UNESTABLISHED: an unannotated parameter, a name bound from
an unclassified call, or a kind this model has no spelling for. So with an
unannotated `Int` parameter `n`:

    def f(p: Pointer[Float64], n) -> Int:
        p.value() = n      # and equally: p[0] = n
        return 0

the integer's bits are stored into a double slot, which reads back as a denormal
(the same failure the `.value() = 1` refusal exists to stop). Only a literal, or
a name whose kind is established, is refused today.

## Expected

A store into a `Pointer[Float64]` whose value kind is unestablished is refused
by name, or the value's kind is established before the store. The permissive
direction is the wrong one for a double slot.

## Why it is not fixed here

The check is shared: `.value()` stores and subscript stores both route through
`pointer_store_kind_disagreement`, and stdlib code stores through
`Pointer[Float64]`, so tightening it changes both at once. That needs the full
gate (stdlib-dylib skip count and stdlib-syntax `U` count before and after), not
a quick test.

## Status (2026-11-03): fix landed, stdlib gate verification pending

**Decision taken: refuse.** An unestablished value stored into a DOUBLE pointee
is now refused by name, in `pointer_store_kind_disagreement`
(`formal/model/__init__.py`). An INTEGER pointee keeps the permissive `None`
(an integer slot reads any word back as a number, so nothing is corrupted).
Refusal over establishment: establishing every kind would need a kind model
for calls and parameters this build does not have, and the refusal is loud
where the old behaviour was silent.

Landed:

- `formal/model/__init__.py`: the `None` arm for a float pointee now returns a
  refusal naming the value (`whose kind this model cannot establish`) and the
  two ways to state the kind (`n: Float64` annotation, `float(x)`). Both
  `.value() = n` and `p[0] = n` route through it.
- `test_formal_run.py`: `deref_refuse_a_binary64_value_store_of_an_unestablished_value`
  and `deref_refuse_a_binary64_subscript_store_of_an_unestablished_value`
  pin both forms. Both failed before the change (the value built) and pass
  after; the answering cases (`deref_a_binary64_subscript_store_of_a_double_is_exact`,
  the integer refusals) still pass.

Not yet verified: the stdlib gate. No `.mojo` file in the tree names
`Pointer[Float64]` (`git grep`), so the refusal should not reach the stdlib,
but that is a grep, not a gate run. The integrator still owes the comparison.

## The gate comparison still owed

1. Run the full gate once: compare `skip <module>:` count (stdlib-dylib) and the
   `U` count (stdlib-syntax) before and after.
2. If the counts hold, delete this doc in the same commit and run
   `python3 tools/dangling_doc_refs.py --ratchet`.
