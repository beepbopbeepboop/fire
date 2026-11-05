# CODEGEN: a `var` class attribute of a function-scoped class with a non-literal value is dropped

## Status (2026-10-29)

Found while fixing `CODEGEN_nested_class_attr_from_str_param_typed_as_int.md`.
The plain assignment form (`name = s`) reaches the per-execution cell path;
the `var` form never gets there.

Repro (run through `test_gimple_stdout`, as in `test_gimple_runner.py`):

```python
def h(s: str):
    class C():
        var name = s
    return C()

def main():
    print(h("x").name)
    print(h("y").name)
```

Expected (CPython): `x` and `y`. Observed on the tree after the
parameter-annotation fix: `0` and `0`, exit 0.

Cause: `module_gen.py`'s class-attribute registration, in the `VarDecl` branch
(~line 6036), has

```python
if not isinstance(field.value, (StringLiteral, IntLiteral, ...)) \
        and _class_attr_ctype(field.value) is None:
    continue
```

So a `var` attribute whose value is a bare name (or any non-container
expression) is skipped before it is registered: it gets no `_classattr_`
global, no per-execution cell, and no per-instance init. The field-init path
does not pick it up for a function-scoped class either, so the read is the
zero-initialised field.

The `AssignStmt` branch has no such guard, which is why `name = s` works.

Next step: decide the semantics of a `var` class-body field with a
non-constant initializer (it is an instance field with a default in Mojo, so
the default must be evaluated per execution of the class statement and
stored into the instance on construction, not dropped). Then either remove
the guard for function-scoped classes and let the registration treat the
value like the `AssignStmt` branch, or route the value through the field-init
path. The test is the repro above, expected `x\ny\n`, next to
`test_nested_class_attr_from_str_param_regression` in
`test_gimple_runner.py`. Check the module-scope form (`var name = s` in a
module-level class with `s` a module global) at the same time: it must not
regress.
