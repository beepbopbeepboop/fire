# CODEGEN: `hasattr(obj, n)` is True for a field the compiler inferred from an assignment outside `__init__`

## Repro (2026-11-01)

    class P:
        def __init__(self): self.a = 1
    def main():
        p = P(); p.b = 5
        q = P()
        print(hasattr(q, 'b'))      # CPython: False; compiled: True
    main()

`p.b = 5` outside `__init__` makes `b` a struct field of every `P` (`_mojo_getattr_P` has a `"b"`
arm), so the 2-arg `hasattr` lowering (`emit_calls.py`, `_mojo_getattr_missed == 0`) always
finds it, zero-initialised. Same for `getattr(q, 'b')` (returns 0 where CPython raises).

## Next step

Decide the representation of "this inferred field was never assigned" (a per-struct presence
bitmask set by the field stores, or keep such fields out of the struct and route them to the
`mojo_setattr` dynattr dict, which already has correct per-object presence). The second is the
smaller change: in the struct-field inference pass, a field first assigned outside `__init__`
stays dynamic. Test: the repro above diffed against CPython in `test_runtime_class_creation.py`.
