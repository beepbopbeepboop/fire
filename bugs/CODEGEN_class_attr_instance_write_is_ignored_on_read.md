# CODEGEN: assigning an instance attribute that shares a class attribute's name is not seen by a later read

## Status (2026-10-29)

Found while probing the per-execution cells for
`CODEGEN_nested_class_attr_reads_enclosing_local_silently_zero.md`. Pre-existing:
the unmodified base tree gives the same wrong answer, and so does the change.

Repro:

```python
def f(v: int):
    class A():
        x = v
    a = A()
    a.x = 9
    return a.x

def main():
    print(f(4))
    print(f(10))
```

Expected (CPython): `9` and `9` (the instance attribute shadows the class
attribute). Observed on both trees: `4` and `10`. The read goes to the class
attribute and the write is dropped.

Where to look: the write `a.x = 9` lowers through the generic MemberExpr path
in `emit_stmts.py` (`_gen_stmt_AssignStmt`, the `ot` branch), while the read
goes through `_lower_MemberExpr`'s class-attribute branch (`emit_exprs.py`,
the `struct_name in class_attrs` arm), which takes precedence over the
instance field. The fix is to make the read consult the instance first: a
field the instance has written (or one the class does not define as a class
attribute) must win over the class attribute, as in CPython's lookup order.
Module-scope classes show it too, so the cause is not the per-execution
storage. Test: the repro, beside the class-attribute tests in
`test_gimple_runner.py`.
