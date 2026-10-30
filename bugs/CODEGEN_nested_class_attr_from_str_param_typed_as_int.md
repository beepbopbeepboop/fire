# CODEGEN: a class attribute of a function-scoped class, taken from a `str` parameter, is typed int64_t

## Status (2026-10-29)

Found while landing the per-execution cells for
`CODEGEN_nested_class_attr_reads_enclosing_local_silently_zero.md`. Not caused
by that change: the unmodified base tree (`git archive` of the branch base)
prints the same garbage.

Repro (`compile_mojo_to_gimple_exe` + run, or `python3 probe_cases.py`-style):

```python
def h(s: str):
    class C():
        name = s
    return C()

def main():
    a = h("x")
    b = h("y")
    print(a.name)
    print(b.name)
```

Expected (CPython): `x` and `y`. Observed on both trees: two pointer-sized
integers (`4339115672` / `4339115672`, values vary by run).

Cause: `module_gen.py`'s class-attribute registration takes the attribute's C
type from its VALUE (`_class_attr_ctype(v)`). For a bare parameter name
(`IdentExpr`) that yields nothing, so the fallback is `int64_t`, and the
attribute is typed `int64_t` while the value stored into it is a `char *`.
The per-execution cell (`_cell_cattr_types`) inherits that type, so the bug
also reaches the new storage. A module-scope class never has this problem:
its values are literals or module names, whose types are known.

## Status (2026-10-29, partial fix landed)

Landed: the BARE-name case. `mojo/middle/exprtypes.py`'s
`_gmi_nested_struct_defs` now returns `[node, enclosing_key, params]`
triples, carrying the nearest enclosing function's (or method's) parameter
list. `mojo/backend_gimple/module_gen.py`'s hoist records each parameter's
annotated C type in `_fn_scoped_param_types` keyed by the class's final name
(`_gmi_record_fn_scoped_param_types`), and the class-attribute registration
types a bare `IdentExpr` value from that table before the `int64_t` fallback.
Regression: `test_nested_class_attr_from_str_param_regression`
(`test_gimple_runner.py`), which failed before the fix with
`4339705632` / `4339705640` and passes after with `x` / `y`.

Still open: a value that is an EXPRESSION over parameters
(`name = s + "!"`) still prints a pointer-sized integer. The registration
has no expression type: `_class_attr_ctype` answers None and
`_quick_type` reads `gen.var_types`, which is empty during the registration
pre-pass. Next step: give the registration a typed view of the enclosing
parameters (the table already holds them) and type the expression from it,
either by seeding a `var_types` overlay for `_quick_type` or by a small
expression typer over `BinaryOp`/`IdentExpr` that defers to `_quick_type`
for the leaves. Test: `name = s + "!"` with `h("x")`/`h("y")`, expected
`x!\ny!\n`.

The `var name = s` form is a different defect (the attribute is dropped
before registration, reads `0`): see
`bugs/CODEGEN_nested_class_var_attr_from_nonliteral_value_is_dropped.md`.
