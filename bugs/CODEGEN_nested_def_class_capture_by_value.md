# CODEGEN_nested_def_class_capture_by_value

## Summary
A class declared inside a NESTED `def` that reads a local of the OUTER
function still gets the old by-VALUE capture: the `class` statement stores the
name's current value in the per-execution cell, so a rebind after the class
statement is stale. The non-rebind shape compiles and prints the right answer;
the rebind shape is still refused (loudly), so this is a remaining gap, not a
wrong answer:

```
method `get` of class `C` reads `x`, a parameter or local of `outer`, which
declares the class, and reads `x`, which the enclosing function rebinds, so a
snapshot taken at the class statement could differ from Python's late binding;
a class declared inside a function cannot reach its enclosing function's frame
there, so the read would silently answer 0
```

The direct shape (`class C` written straight in the enclosing function) is
late-bound by the by-reference capture fixed in
`bugs/CODEGEN_class_rebind_late_binding` (doc deleted with that fix). This doc
is the one level of nesting that fix deliberately did not take on.

## Reproduce
Both shapes, with `compile_mojo_to_gimple_exe`:

```python
# non-rebind: works, prints 5
def outer():
    x = 5
    def inner():
        class C:
            def get(self):
                return x
        return C().get()
    return inner()

# rebind: refused; Python prints 7
def outer():
    x = 5
    def inner():
        class C:
            def get(self):
                return x
        return C().get()
    x = 7
    return inner()
```

Measured on this branch and on its merge base (`560 passed/19 failed` run
point): non-rebind PASS prints `5`; rebind refuses with the message above.
Pinned in `test_gimple_runner.py` as
`gimple_nested_class_inside_nested_def_capture` (the working half; the
refusal is not pinned because it is the bug).

## Why the by-reference boxing cannot be used as-is
`_gmi_capture_nested_class_enclosing_reads` records a by-reference capture only
when the class is written directly in the enclosing function's body
(`_ec_direct`, i.e. `_gmi_nested_struct_defs`' innermost-enclosing key is
`''`). For a class inside `def inner`, the `class` statement is emitted in the
LIFTED `<outer>_<inner>` C function, while the heap box a direct capture would
install lives in `outer`'s frame. `inner`'s closure env carries `x` BY VALUE
(`outer_inner_env->x`), because `discover_closures` widens an env field to a
pointer (`mut_names`) only when the inner function ASSIGNS the name
(`nonlocal`). Installing `outer`'s box pointer in the lifted function therefore
has no source: an earlier revision of the by-reference change emitted the bare
name there and broke the non-rebind shape with gcc `'x' undeclared` in
`outer_inner`. The fix keeps the by-value cell (and the rebind refusal) for
this shape instead.

## Next step
Make the outer local's box travel through the enclosing closure's env:

1. In `discover_closures` (`mojo/middle/closures.py`), when scanning `inner`'s
   body, detect a hoisted class whose method captures an `outer` local by
   reference (the same `_class_ref_pending`/`_ref_attrs` set the direct path
   uses, keyed by the lifted `<outer>_<inner>` name) and add that name to
   `inner`'s `mut_names`. The env field becomes `T *` and the seeding in
   `_gen_stmt_FunctionDef`/`_gen_lifted_closure` stores the BOX pointer
   instead of the value.
2. Let `_gmi_apply_class_ref_types` accept the lifted outer key so the
   `_classattr_<C>__<cap>` global/`_clscell_` field become `T *`.
3. In `_gen_stmt_StructDef`, the by-reference branch needs the box expression
   for the lifted frame (`_env->x`), not `gen._cname(x)`: lower the capture's
   source `IdentExpr` through the normal expression path when
   `x not in gen._boxed_mut_locals`, and keep the box-pointer install only
   when it IS a local of the emitting function. (The current fall-through is
   the safe by-value cell.)
4. Remove the `not _ec_direct` rebind refusal in
   `_gmi_capture_nested_class_enclosing_reads`, and extend
   `test_gimple_runner.py`'s nested-def test beside
   `gimple_nested_class_inside_nested_def_capture` with the rebind (`7`) and
   instance-built-before-rebind (`7`) shapes.

A cheaper alternative for (1) is to box the local in the LIFTED function
instead of the outer one; rejected unless measured to work, because the
lifted function's env is re-created per call of `inner`, while Python's cell
belongs to `outer`.
