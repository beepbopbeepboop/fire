# CODEGEN: a direct read of a compiler-minted field the instance never received returns 0

## Repro (2026-11-01, measured)

    class P:
        def __init__(self):
            self.a = 1

    def main():
        p = P()
        p.b = 5
        q = P()
        print(q.b)
    main()

CPython: `AttributeError: 'P' object has no attribute 'b'` (exit 1).
Compiled (`test_gimple_runner.compile_mojo_to_gimple_exe`, run): prints `0`, exit 0.

## Why it is separate from the hasattr fix

`hasattr` / `getattr(obj, name, default)` / `getattr(obj, name)` are now correct for
these fields: the generated `_mojo_getattr_<S>` arm tests the object's presence bit
(`StructDef.presence_fields`, `mojo/middle/types.py` `presence_bit`) and falls through to
`mojo_obj_getattr` when it is clear. A DIRECT member read (`q.b`) lowers to a plain
`q->b` load, which never consults the presence bit, so it still reads the zero word.

## Status

Not started. The fix that landed for the hasattr bug left this path untouched on purpose:
it is a read-side change in `_lower_MemberExpr` (mojo/backend_gimple/emit_exprs.py), not a
store-side one.

## Next step

In `_lower_MemberExpr`, for a receiver whose struct has `presence_bit(sdef, member)` not None,
emit a presence test before the field load and raise through the same path the nullable
receiver uses (`mojo_raise_attribute_error`, see the `_nullable_ptrs` guard in emit_stmts.py's
AssignStmt MemberExpr branch) when the bit is clear. Limit it to reads that are not the target of a store (the store path sets the bit
first). Test: add the repro to `test_hasattr_minted_fields.py` as an expected-exception case
(or a CPython-diff case that catches the AttributeError), and check the stdout + exit code
match CPython. Watch the self-hosted compiler: its own struct reads go through this same
lowering, so the integrator's `stdlib-dylib` skip count must not rise.
