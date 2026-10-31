# A constructor-valued comptime alias read through an instance calls the instance

## Status

OPEN. Found 2026-10-29 while fixing the enum-case pattern. The bare type-name
read of the same alias (`Color.RED`) was fixed in the same change (commit
86f908c22: `Self` is bound to the struct's own name there); this instance
read is not.

## What is wrong

`comptime RED = Self(0)` inside `struct Color`, read through an instance
(`c.RED` where `var c = Color(1)`), lowers to a call of `c` as a function
pointer. `_lower_MemberExpr`'s instance-typed alias branch
(`mojo/backend_gimple/emit_exprs.py`, the `_subst_idents(..., {'Self':
node.obj, struct_name: node.obj})` call) rebinds `Self` to the OBJECT, so
`Self(0)` becomes `obj(0)`.

Generated C for `if c == c.RED:` (measured):

    _t3 = (void *)c;
    _t5 = mojo_fnptr_call_1 (_t3, _t4);   /* calls the instance */
    _t8 = _t6 == _t7;

It compiles and links, and the comparison is against whatever the call returns.

## Reproduce

    @fieldwise_init
    struct Color:
        var _v: Int
        comptime RED = Self(0)
        def __init__(out self, v: Int):
            self._v = v
        def __eq__(self, rhs: Self) -> Bool:
            return self._v == rhs._v
    def main():
        var c = Color(1)
        if c == c.RED:
            print('is red')

Run `python3 .tmp/gen.py` style: `compile_to_gimple` and read the `_gimple_main`
body for `mojo_fnptr_call`.

## Expected

`c.RED` is the same value `Color.RED` gives: a `Color` constructed from `0`.
`Self` should be the struct's type, the way the bare-name branch now binds it.

## Next step

Check what the instance rebinding is for before changing it: it was written
for aliases that refer to fields through `Self` on an instance, and a change
must keep those. The likely fix is to bind `Self` to `IdentExpr(struct_name)`
in that call as well, and keep the object binding only for the non-`Self`
struct-name case if a test needs it. Add a `test_gimple_runner.py` row that
prints `c == c.RED` and checks it against `Color.RED`.
