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

## The exact next step

1. Decide: refuse unestablished kinds outright, or establish them (annotation at
   the call site). Read the stdlib `Pointer[Float64]` store sites first
   (`git grep -n "Pointer\[Float64\]" -- std`) to see which would newly refuse.
2. Flip `pointer_store_kind_disagreement`'s `None` for the unestablished case, in
   `formal/model/__init__.py` (the package is the one Python imports).
3. Pin both forms (`.value() = n` and `p[0] = n`) as refusals on both backends
   in `test_formal_run.py`, next to `deref_refuse_a_binary64_subscript_store_of_an_integer`.
4. Run the full gate once: compare `skip <module>:` count (stdlib-dylib) and the
   `U` count (stdlib-syntax) before and after.
