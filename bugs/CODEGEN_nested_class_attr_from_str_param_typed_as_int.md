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

Next step: when a non-constant value of a function-scoped class is a bare
name that is a PARAMETER of the enclosing function, type the attribute from
that parameter's annotation (`_mojo_type(annotation)`, the same resolver the
field-typing pass uses). The enclosing function is known in
`_gmi_hoist_nested_structs` (`found[i][1]`); record the parameter types there
(e.g. `self._fn_scoped_param_types[(cls, attr)]`) and consult them in the
registration at `module_gen.py` (`ctype = _class_attr_ctype(v)`, ~6080) before
the `int64_t` fallback. Test: the repro above, expected `x\ny\n`, in
`test_gimple_runner.py` beside `test_nested_class_attr_reads_enclosing_local_regression`.
A value that is an expression over parameters (`name = s + "!"`) needs the
same treatment; the repro with the bare name is the minimal case.
