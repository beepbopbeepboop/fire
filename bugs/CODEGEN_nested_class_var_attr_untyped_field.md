# CODEGEN_nested_class_var_attr_untyped_field

## Summary
A class-body `var NAME = <value>` (or a typed `NAME: T = <value>`) whose
value is not a literal — a function parameter, an enclosing local, or an
expression over one — reads back `0`/`None` through an INSTANCE, although the
`class` statement stored the right value in its per-execution cell:

```python
def h(s: str):
    class C():
        var name = s
    return C()

def main():
    a = h("x")
    b = h("y")
    print(a.name)      # CPython/expected: x
    print(b.name)      # CPython/expected: y
main()
```

compiled prints `0\n0\n`. The same source with the bare `name = s` spelling
prints `x\ny\n`.

## Measured (2026-11-09, this tree AND `git archive master` — identical)
Compiled with `test_gimple_runner.compile_mojo_to_gimple_exe`:

| class-body spelling | result |
|---|---|
| `var name = "hello"` | `hello` (right — literal types the field) |
| `var name = s` (s: str param) | `0` (WRONG) |
| `var name = s + "!"` | `0` (WRONG) |
| `name = s` (bare, unannotated) | `x` (right) |
| `var name: str = s` | `None` (WRONG) |
| `name: str = s` | `None` (WRONG) |
| module-level `class C: var name = S` (S a global) | `0` (WRONG) |

The existing regression for this shape,
`test_gimple_runner.py::test_nested_class_var_attr_from_str_param_regression`
(`gimple_nested_class_var_attr_from_str_param`), fails with
`expected 'x\ny\n', got '0\n0\n'`. It fails the same way on master: the whole
file is `560 passed, 19 failed` at the branch point and
`563 passed, 19 failed` after the class-rebind work, with an IDENTICAL
19-test failure set — this one is pre-existing, not caused by it.

## Root cause
Two cooperating pieces, both in `module_gen.gen_module_impl`:

1. The field-typing loop (~line 7336) creates a `struct_field_types[Cls][NAME]`
   entry for every class-body `VarDecl` (and, in the typed-AssignStmt loop,
   for `NAME: T`). For an unannotated `var NAME = <non-literal>`,
   `_class_attr_ctype(value)` answers None and the fallback at ~7371 types the
   field `<Cls> *` ("we don't know what this holds"). The cell registration
   later (~7517) classifies the same decl as a function/module-scoped class
   ATTRIBUTE and gives the `_classattr_` global the true type.
2. `_lower_MemberExpr` prefers a real struct FIELD over the class-attribute
   global, so `a.name` lowers to `a->name` (the uninitialized field) instead
   of the per-execution cell. The allocator's per-instance init is gated on
   the field type and the global type AGREEING; `<Cls> *` vs `char *` (or,
   for the annotated case, an ordering/seed mismatch) means it never fires.

Generated C for the first shape confirms it: the struct has
`struct C * name;` and `char * * _clscell_name;`, `h` stores into
`*_classattr_C__name`, and `_alloc_C` copies the cell pointer but never
initializes `_p->name`; `print(a.name)` is `a->name`.

## Next step
Make the field-typing loop resolve the same value type the class-attribute
registration already does, so the field and global agree and the allocator
init fires — mirror the two resolutions at ~7461-7485 there:

* a bare `IdentExpr` that is a parameter of the class's declaring function:
  `self._fn_scoped_param_types[_pair_key(s.name, ident)]`;
* any other non-literal expression over those parameters: run `_quick_type`
  with `var_types` overlaid by `self._fn_scoped_params_by_class[s.name]`.

Alternatively (or additionally) let the ~7567 upgrade accept the
`<Cls> *` fallback as an unknown default, not only `'int'`/`'int64_t'`.
Whichever is chosen, the annotated `NAME: T = value` rows above need their
own measurement: their field type is already right, so the remaining cause is
initialization order, not typing.

Add the regression beside
`test_nested_class_var_attr_from_str_param_regression` in
`test_gimple_runner.py` once the first shape passes; do not delete the
existing test.
